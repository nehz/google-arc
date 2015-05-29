# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

import build_options
import make_to_ninja
import ninja_generator
import staging


def generate_ninjas():
  # libcompiler_rt is used internally inside libc and libc++.
  def _filter(vars):
    if vars.is_shared():
      return False
    module_name = vars.get_module_name()
    if module_name != 'libcompiler_rt':
      return False

    # compilerrt_abort_impl has unused parameters.
    vars.get_cflags().extend(['-Wno-unused-parameter', '-Werror'])

    # Android.mk assumes that .S files are built via clang as a front end,
    # but we just use gcc. Remove a clang specific flag here.
    # TODO(crbug.com/416353): We may be able to support this conversion inside
    # MakefileNinjaTranslator.
    vars.get_asmflags().remove('-integrated-as')

    if vars.is_target() and build_options.OPTIONS.is_nacl_i686():
      # Replace original assembly source files with NaClized source files.
      sources = vars.get_sources()
      asm_sources = [source for source in sources
                     if os.path.splitext(source)[1] == '.S']
      for source in asm_sources:
        sources.remove(source)

      # Use C implementation instead of some assembly source files that
      # can not be converted easily.
      asm_sources = [source for source in asm_sources
                     if os.path.basename(source) not in [
                         'floatdidf.S', 'floatdisf.S', 'floatdixf.S',
                         'floatundidf.S', 'floatundisf.S', 'floatundixf.S']]
      sources.extend([
          'android/external/compiler-rt/lib/builtins/floatdidf.c',
          'android/external/compiler-rt/lib/builtins/floatdisf.c',
          'android/external/compiler-rt/lib/builtins/floatdixf.c',
          'android/external/compiler-rt/lib/builtins/floatundidf.c',
          'android/external/compiler-rt/lib/builtins/floatundisf.c',
          'android/external/compiler-rt/lib/builtins/floatundixf.c'])

      # Assembly files need to include ../assembly.h that is relative path
      # from the original directory. Add the directory as an include path.
      asm_path = os.path.dirname(asm_sources[0])
      vars.get_asmflags().append('-I' + staging.as_staging(asm_path))

      n = ninja_generator.NaClizeNinjaGenerator('compier-rt')
      generated_file_list = n.generate(asm_sources)

      # Add generated files to the source file list.
      sources.extend(generated_file_list)

    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/external/compiler-rt').generate(_filter)
