# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build libjnigraphics.so."""

from make_to_ninja import Filters, MakefileNinjaTranslator


def generate_libjnigraphics_ninja(force_static):
  def _filter(vars):
    if force_static:
      Filters.convert_to_static_lib(vars)
      vars.set_module_name(vars.get_module_name() + '_static')
    return True
  MakefileNinjaTranslator(
      'android/frameworks/base/native/graphics/jni').generate(_filter)


def generate_ninjas():
  generate_libjnigraphics_ninja(force_static=False)
  # libwebviewchromium requires a static version of this library since it has an
  # alternative, _slightly_ different implementation of skia.
  generate_libjnigraphics_ninja(force_static=True)
