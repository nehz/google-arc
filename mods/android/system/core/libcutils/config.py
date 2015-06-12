# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import make_to_ninja
from build_options import OPTIONS


def generate_ninjas():
  def _filter(vars):
    if vars.is_executable():
      return False
    if vars.get_module_name() == 'lib64cutils':
      assert vars.is_host()
      return False
    if vars.is_shared():
      # Makefile system builds this both ways. Build .a only.
      return False
    # TODO(crbug.com/163446): Get the assembly working with nacl.
    src = vars.get_sources()
    # Not usable/compilable in ARC.
    if not vars.is_host():
      src.remove('android/system/core/libcutils/android_reboot.c')
    src.remove('android/system/core/libcutils/iosched_policy.c')

    # TODO(crbug.com/462555): L-rebase: enable assembly implementation.
    # Use C implementation in memory.c for NaCl.
    if OPTIONS.is_nacl_build():
      vars.remove_c_or_cxxflag('-DHAVE_MEMSET16')
      vars.remove_c_or_cxxflag('-DHAVE_MEMSET32')
      src[:] = [x for x in src if not x.endswith('.S')]
    return True
  make_to_ninja.MakefileNinjaTranslator(
      'android/system/core/libcutils').generate(_filter)
