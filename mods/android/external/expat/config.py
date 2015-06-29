# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from make_to_ninja import MakefileNinjaTranslator


def generate_ninjas():
  def _filter(vars):
    if vars.is_host():
      return False
    return True
  MakefileNinjaTranslator('android/external/expat').generate(_filter)
