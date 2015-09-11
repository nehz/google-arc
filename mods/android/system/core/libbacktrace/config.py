# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import open_source
from make_to_ninja import MakefileNinjaTranslator


def generate_ninjas():
  def _filter(vars):
    if open_source.is_open_source_repo() and vars.is_host():
      return False
    if vars.get_module_name() == 'libbacktrace_test':
      # libbacktrace_test is for building 'backtrace_test' target defined in
      # the same Android.mk, but we do not have an easy way to build the test
      # binary.
      return False
    vars.enable_clang()
    vars.enable_cxx11()
    vars.get_shared_deps().append('liblog')
    return True
  MakefileNinjaTranslator('android/system/core/libbacktrace').generate(_filter)
