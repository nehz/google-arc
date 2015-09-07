# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build libcpufeatures library."""

from src.build import make_to_ninja
from src.build.build_options import OPTIONS


def _generate_libcpufeatures_ninja():
  def _filter(vars):
    # -fstack-protector emits undefined symbols.
    if not OPTIONS.is_bare_metal_build():
      vars.get_cflags().append('-fno-stack-protector')
    return True
  path = 'android/ndk/sources/android/cpufeatures'
  make_to_ninja.MakefileNinjaTranslator(path).generate(_filter)


def generate_ninjas():
  _generate_libcpufeatures_ninja()
