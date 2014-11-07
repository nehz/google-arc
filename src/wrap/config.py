#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import ninja_generator
from build_options import OPTIONS


def _generate_libwrap_ninja():
  ninja = ninja_generator.ArchiveNinjaGenerator('libwrap',
                                                base_path='src/wrap',
                                                enable_clang=True)
  ninja.add_compiler_flags('-Werror')
  ninja.add_libchromium_base_compile_flags()
  if OPTIONS.use_verbose_memory_viewer():
    ninja.add_defines('USE_VERBOSE_MEMORY_VIEWER')
  return ninja.build_default_all_sources().archive()


def generate_ninjas():
  _generate_libwrap_ninja()
