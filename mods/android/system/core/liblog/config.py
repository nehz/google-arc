# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import make_to_ninja


def generate_ninjas():
  def _filter(vars):
    if vars.get_module_name() != 'liblog':
      # Only build liblog
      return False

    # We cannot build both static and shared versions of a library with the
    # same name, so add the '_static' suffix to the static library.
    if vars.is_static():
      vars.set_module_name('liblog_static')
    else:
      vars.get_whole_archive_deps().remove('liblog')
      vars.get_whole_archive_deps().append('liblog_static')

    return True
  make_to_ninja.MakefileNinjaTranslator('android/system/core/liblog').generate(
      _filter)
