# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import make_to_ninja


def generate_ninjas():
  def _filter(vars):
    # -fexceptions and -frtti are defined in Android.mk, but automatically
    # removed by MakefileNinjaGenerator. Redefine them here.
    vars.get_cxxflags().extend(['-fexceptions', '-frtti'])
    # libc++ and libpdfium depend on libc++abi.
    vars.set_instances_count(2)
    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/external/libcxxabi').generate(_filter)
