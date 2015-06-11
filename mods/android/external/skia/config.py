# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from build_options import OPTIONS
from make_to_ninja import MakefileNinjaTranslator
import ninja_generator
import open_source
import staging


def generate_ninjas():
  if open_source.is_open_source_repo():
    # Provide a stub.
    n = ninja_generator.SharedObjectNinjaGenerator('libskia')
    n.add_notice_sources([staging.as_staging('src/NOTICE')])
    n.link()
    return

  def _filter(vars):
    if vars.is_executable():
      return False
    if vars.get_module_name() == 'libskia':
      if not OPTIONS.is_optimized_build():
        # Enable basic optimizations for SKIA as it otherwise fails as it
        # refers to unimplemented FT_Get_FSType_Flags. For some reason using
        # -ffunction-sections with --gc-sections did not solve the problem
        # here.
        vars.get_cflags().append('-O1')
      # GNU assembler outputs some warnings for memset.arm.S because
      # we specify -Wa,-mimplicit-it=thumb in ninja_generator.py.
      # It seems skia expects the default choice (arm) so we specify
      # this. Note that this seems not to change the assembler output
      # for memset.arm.S. See this document for detail of this option:
      # https://sourceware.org/binutils/docs/as/ARM-Options.html
      if OPTIONS.is_arm():
        vars.get_cflags().append('-Wa,-mimplicit-it=arm')
    return True

  MakefileNinjaTranslator('android/external/skia').generate(_filter)
