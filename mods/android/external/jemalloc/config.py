# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

import build_common
import make_to_ninja
import ninja_generator
import ninja_generator_runner

from build_options import OPTIONS


def generate_ninjas():
  def _filter(vars):
    if vars.is_host() or vars.is_shared():
      return False
    if vars.get_module_name() not in ('libjemalloc',
                                      'libjemalloc_jet',
                                      'libjemalloc_unittest',
                                      'libjemalloc_integrationtest'):
      return False

    if vars.get_module_name() != 'libjemalloc':
      # All the other modules are only used in tests.
      vars.set_instances_count(0)
    # x86_64-nacl-gcc miscompiles malloc_conf_next in --opt mode.
    # 'malloc_conf_next' that parses configuration value trying to
    # parse key-value pair of "abort:true,..."
    # expected result: key=abort, value=true
    # parsed as: key=abort, value=  and the rest gets misparsed.
    # https://code.google.com/p/nativeclient/issues/detail?id=4036
    if OPTIONS.is_nacl_x86_64():
      vars.enable_clang()
      vars.enable_cxx11()
    if OPTIONS.enable_jemalloc_debug():
      vars.get_cflags().append('-DJEMALLOC_DEBUG')
    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/external/jemalloc').generate(_filter)


def _generate_jemalloc_unit_tests():
  paths = build_common.find_all_files(
      'android/external/jemalloc/test/unit', ['.c'], include_tests=True)

  # These tests need -DJEMALLOC_PROF which we do not enable.
  paths.remove('android/external/jemalloc/test/unit/prof_accum.c')
  paths.remove('android/external/jemalloc/test/unit/prof_accum_a.c')
  paths.remove('android/external/jemalloc/test/unit/prof_accum_b.c')
  paths.remove('android/external/jemalloc/test/unit/prof_gdump.c')
  paths.remove('android/external/jemalloc/test/unit/prof_idump.c')

  # Disable some multi-threaded tests flaky under ARM qemu.
  if OPTIONS.is_arm():
    paths.remove('android/external/jemalloc/test/unit/mq.c')
    paths.remove('android/external/jemalloc/test/unit/mtx.c')

  for path in paths:
    name = os.path.splitext(os.path.basename(path))[0]
    n = ninja_generator.TestNinjaGenerator('jemalloc_unit_test_' + name)
    n.add_include_paths(
        'android/external/jemalloc/include',
        'android/external/jemalloc/test/include')
    n.add_c_flags('-Werror')
    n.add_c_flags('-DJEMALLOC_UNIT_TEST')
    if OPTIONS.enable_jemalloc_debug():
      n.add_c_flags('-DJEMALLOC_DEBUG')
    # Needs C99 for "restrict" keyword.
    n.add_c_flags('-std=gnu99')
    n.add_library_deps('libjemalloc_jet.a')
    n.add_library_deps('libjemalloc_unittest.a')
    n.build_default([path])
    n.run(n.link(), enable_valgrind=OPTIONS.enable_valgrind(), rule='run_test')


def _generate_jemalloc_integration_tests():
  paths = build_common.find_all_files(
      'android/external/jemalloc/test/integration', ['.c'], include_tests=True)

  # Disable some multi-threaded tests flaky under ARM qemu.
  if OPTIONS.is_arm():
    paths.remove('android/external/jemalloc/test/integration/MALLOCX_ARENA.c')
    paths.remove('android/external/jemalloc/test/integration/thread_arena.c')

  for path in paths:
    name = os.path.splitext(os.path.basename(path))[0]
    n = ninja_generator.TestNinjaGenerator('jemalloc_integartion_test_' + name)
    n.add_include_paths(
        'android/external/jemalloc/include',
        'android/external/jemalloc/test/include')
    n.add_c_flags('-Werror')
    n.add_c_flags('-DJEMALLOC_INTEGRATION_TEST')
    if OPTIONS.enable_jemalloc_debug():
      n.add_c_flags('-DJEMALLOC_DEBUG')
    # Needs C99 for "restrict" keyword.
    n.add_c_flags('-std=gnu99')
    n.add_library_deps('libjemalloc.a')
    n.add_library_deps('libjemalloc_integrationtest.a')
    n.build_default([path])
    n.run(n.link(), enable_valgrind=OPTIONS.enable_valgrind(), rule='run_test')


def generate_test_ninjas():
  ninja_generator_runner.request_run_in_parallel(
      _generate_jemalloc_unit_tests,
      _generate_jemalloc_integration_tests)
