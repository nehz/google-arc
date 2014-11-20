#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

import build_common
import ninja_generator
import open_source
from build_options import OPTIONS


def _add_compile_flags(ninja):
  if OPTIONS.is_memory_usage_logging():
    ninja.add_defines('MEMORY_USAGE_LOGGING')
  ninja.add_ppapi_compile_flags()  # for mprotect_rwx.cc
  ninja.add_libchromium_base_compile_flags()


def _get_generated_file(ninja, out_name, script_name, implicit_add):
  script_path = os.path.join('src/common', script_name)
  rule_name = os.path.splitext(os.path.basename(script_path))[0]
  ninja.rule(rule_name,
             command='%s > $out.tmp && mv $out.tmp $out' % script_path,
             description=rule_name + ' $in')

  out_path = os.path.join(build_common.get_build_dir(), 'common_gen_sources',
                          out_name)
  implicit = [script_path, 'src/build/build_options.py'] + implicit_add
  ninja.build(out_path, rule_name, implicit=implicit)
  return out_path


def _get_wrapped_functions_cc(ninja):
  return _get_generated_file(
      ninja,
      out_name='wrapped_functions.cc',
      script_name='gen_wrapped_functions_cc.py',
      implicit_add=['src/build/wrapped_functions.py'])


def _get_android_static_libraries_cc(ninja):
  return _get_generated_file(
      ninja,
      out_name='android_static_libraries.cc',
      script_name='gen_android_static_libraries_cc.py',
      implicit_add=['src/build/android_static_libraries.py'])


def _get_fake_posix_translation_cc(ninja):
  return _get_generated_file(
      ninja,
      out_name='fake_posix_translation.cc',
      script_name='gen_fake_posix_translation_cc.py',
      implicit_add=['src/build/wrapped_functions.py'])


def _get_real_syscall_aliases_s(ninja):
  return _get_generated_file(
      ninja,
      out_name='real_syscall_aliases.S',
      script_name='gen_real_syscall_aliases_s.py',
      implicit_add=['src/build/wrapped_functions.py'])


def _generate_libpluginhandle_ninja():
  n = ninja_generator.ArchiveNinjaGenerator('libpluginhandle')
  return n.build_default(['src/common/plugin_handle.cc']).archive()


# Generate libcommon.a, the library that should be linked into everything.
def generate_ninjas():
  if open_source.is_open_source_repo():
    # The open source version of ARC does not provide libposix_translation.so
    # but most of the open-sourced DSOs depend on it. Build a fake POSIX
    # translation library which exports the same set of __wrap_* symbols as
    # the real one.
    n = ninja_generator.SharedObjectNinjaGenerator('libposix_translation',
                                                   is_system_library=True,
                                                   enable_clang=True)
    n.add_notice_sources(['src/NOTICE'])
    n.build_default([_get_fake_posix_translation_cc(n)]).link()

  n = ninja_generator.ArchiveNinjaGenerator(
      'libcommon_test_main',
      base_path='src/common/tests',
      instances=0)  # Should not be used by production binary.
  sources = n.find_all_sources(include_tests=True)
  n.build_default(sources, base_path=None).archive()

  n = ninja_generator.ArchiveNinjaGenerator(
      'libcommon_real_syscall_aliases',
      instances=0)  # Should not be used by production binary.
  sources = [_get_real_syscall_aliases_s(n)]
  n.build_default(sources, base_path=None).archive()

  _generate_libpluginhandle_ninja()

  n = ninja_generator.ArchiveNinjaGenerator('libcommon',
                                            enable_clang=True,
                                            base_path='src/common')
  n.add_compiler_flags('-Werror')
  if build_common.use_ndk_direct_execution():
    n.add_compiler_flags('-DUSE_NDK_DIRECT_EXECUTION')
  # Specify the few include directories needed for building code in
  # common directories.  Common code really should not reach out into
  # external.
  n.add_include_paths('android/system/core/include', 'android_libcommon')
  _add_compile_flags(n)
  sources = n.find_all_sources()
  sources.remove('src/common/plugin_handle.cc')
  sources.append(_get_wrapped_functions_cc(n))
  sources.append(_get_android_static_libraries_cc(n))
  return n.build_default(sources, base_path=None).archive()


def generate_test_ninjas():
  n = ninja_generator.TestNinjaGenerator('libcommon_test',
                                         enable_clang=True,
                                         base_path='src/common')
  n.build_default_all_test_sources()
  n.add_compiler_flags('-Werror')
  n.add_library_deps('libgccdemangle.a')
  _add_compile_flags(n)
  n.run(n.link())
