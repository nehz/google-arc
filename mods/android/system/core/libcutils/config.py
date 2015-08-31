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
    assert vars.get_module_name() == 'libcutils'

    if vars.is_host():
      # On host, we build libcutils.a only.
      assert vars.is_static()
    else:
      # On target, we build both libutils_static.a and libutils.so.
      # libutils_static.a is linked to unit tests.
      if vars.is_static():
        vars.set_module_name(vars.get_module_name() + '_static')

    if vars.is_target() and vars.is_shared():
      # libcutils.so links liblog.a because some legacy Android prebuilt
      # binaries expect liblog symbols in libcutils.so. It is not the case
      # with ARC, so do not static link liblog.a. See Android.mk for details.
      vars.get_whole_archive_deps().remove('liblog')

    # TODO(crbug.com/163446): Get the assembly working with nacl.
    src = vars.get_sources()
    # Not usable/compilable in ARC.
    if vars.is_shared():
      deps = vars.get_whole_archive_deps()
      deps.remove('libcutils')
      deps.append('libcutils_static')
    else:
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
