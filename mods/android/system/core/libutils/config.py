# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build libutils.so."""

import build_options
import make_to_ninja
import ninja_generator


def _generate_libutils_arc_tests_ninja():
  base_path = 'android/system/core/libutils/arc_tests'
  n = ninja_generator.TestNinjaGenerator(
      'libutils_arc_tests', base_path=base_path)
  n.build_default_all_test_sources()
  n.emit_framework_common_flags()
  n.add_compiler_flags('-Werror')
  library_deps = ['libchromium_base.a',  # for libcommon.a etc.
                  'libcommon.a',
                  'libcutils_static.a',
                  'libgccdemangle_static.a',
                  'libpluginhandle.a',
                  'libunwind_static.a',
                  'libutils_static.a']
  n.add_library_deps(*library_deps)
  n.run(n.link())


def _generate_libutils_ninja():
  # We generate both static library and shared library because arc_tests needs
  # to compile without --wrap flags. See crbug.com/423063.
  def _filter(vars):
    if vars.get_module_name() != 'libutils':
      return False
    if vars.is_shared():
      vars.get_whole_archive_deps().remove('libutils')
      vars.get_whole_archive_deps().append('libutils_static')
      # TODO(crbug.com/364344): Once Renderscript is built from source, this
      # canned install can be removed.
      # TODO(crbug.com/484862): Or, once we set up NDK trampolines for
      # libutils.so, this canned install can be removed.
      if not build_options.OPTIONS.is_arm():
        vars.set_canned_arm(True)
    else:
      vars.set_module_name('libutils_static')
    return True
  make_to_ninja.MakefileNinjaTranslator(
      'android/system/core/libutils').generate(_filter)


def generate_ninjas():
  _generate_libutils_ninja()


def generate_test_ninjas():
  _generate_libutils_arc_tests_ninja()
