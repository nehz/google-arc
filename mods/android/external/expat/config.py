# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import make_to_ninja


def generate_ninjas():
  def _filter(vars):
    if vars.is_host():
      return False
    return True
  make_to_ninja.MakefileNinjaTranslator(
      'android/external/expat').generate(_filter)
