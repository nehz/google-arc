# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import ninja_generator
from build_options import OPTIONS
from make_to_ninja import MakefileNinjaTranslator


def _filter_libunwind(vars):
  # TODO(crbug.com/414569): L-rebase: Figure out why this is not here.
  # if OPTIONS.is_arm():
    # The same is implemented by unw_tdep_getcontext() in libunwind-arm.h.
    # vars.get_sources().remove(
    #     'android/external/libunwind/src/arm/getcontext.S')
  if OPTIONS.is_x86_64() and vars.is_target():
    # setcontext is used by unw_resume(), which we do not support.
    vars.get_sources().remove(
        'android/external/libunwind/src/x86_64/setcontext.S')
    # Gtrace.c caches requests to libunwind and is only implemented for x64,
    # most likely because only 64-bit compilation was removing frame pointers.
    # It cannot compile here because it uses __thread.
    vars.get_sources().remove(
        'android/external/libunwind/src/x86_64/Gtrace.c')
    vars.get_sources().remove(
        'android/external/libunwind/src/x86_64/Ltrace.c')
  return True


def _filter_libunwind_ptrace(vars):
  return True


def generate_ninjas():
  def _filter(vars):
    if vars.is_static():
      if vars.is_host():
        return False
      vars.set_module_name(vars.get_module_name() + '_static')
      # The static version of libunwind is only used in tests.
      vars.set_instances_count(0)

    return {
        'libunwind': _filter_libunwind,
        'libunwind_static': _filter_libunwind,
        'libunwind-ptrace': _filter_libunwind_ptrace,
    }.get(vars.get_module_name(), lambda vars: False)(vars)

  MakefileNinjaTranslator('android/external/libunwind').generate(_filter)


def generate_test_ninjas():
  if not OPTIONS.is_nacl_x86_64():
    return

  n = ninja_generator.TestNinjaGenerator('libunwind_test',
                                         base_path='android/external/libunwind',
                                         enable_cxx11=True)
  sources = []
  if OPTIONS.is_x86_64():
    sources.append('src/x86_64/ucontext_i_test.cc')
  n.build_default(sources)
  n.run(n.link())
