# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import make_to_ninja
from src.build.build_options import OPTIONS


def generate_ninjas():
  def _filter(vars):
    if vars.get_module_name() not in ('libjpeg', 'libjpeg_static'):
      return False
    if OPTIONS.is_x86():
      # Adding this flag should be safe for all x86 Chromebooks.
      vars.get_cflags().append('-msse2')
    return True
  make_to_ninja.MakefileNinjaTranslator(
      'android/external/jpeg').generate(_filter)
