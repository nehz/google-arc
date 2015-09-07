# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import make_to_ninja
from src.build import ninja_generator
from src.build import open_source
from src.build import staging
from src.build.build_options import OPTIONS


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
      vars.get_shared_deps().append('libcompiler_rt')
    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/external/skia').generate(_filter)
