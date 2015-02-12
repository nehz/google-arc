# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import shutil

import build_common
import ninja_generator
import open_source
import staging
from util import platform_util
if not open_source.is_open_source_repo():
  from util.test import atf_gtest_suite_runner
from util.test import suite_runner_config_flags as flags
from util.test.test_options import TEST_OPTIONS

_TEST_TIMEOUT = 120


def _get_integration_test_name():
  return 'graphics.translation.test'


def _get_generator_name():
  return 'graphics_translation_image_generator'


def _get_apk_path():
  return build_common.get_build_path_for_apk(_get_integration_test_name())


def _get_crx_path():
  return os.path.join(build_common.get_arc_root(), 'out', 'data_roots',
                      _get_integration_test_name())


def _get_gen_path():
  return os.path.join(build_common.get_build_dir(is_host=True),
                      'intermediates', _get_generator_name())


def _get_data_path():
  return os.path.join('mods', 'graphics_translation', 'tests', 'data')


def _get_apk_to_crx_script():
  return os.path.join(build_common.get_arc_root(), 'src', 'packaging',
                      'apk_to_crx.py')


def _clean_dir(dst):
  if (os.path.exists(dst)):
    shutil.rmtree(dst)
  os.makedirs(dst)


def _copy_tree(src, dst):
  if os.path.exists(dst):
    shutil.rmtree(dst)
  if os.path.exists(src):
    shutil.copytree(src, dst)


def _add_compile_flags(n):
  n.add_compiler_flags('-Werror')
  n.emit_gl_common_flags()
  n.add_include_paths('mods',
                      'mods/graphics_translation',
                      'android/system/core/include',
                      'android/hardware/libhardware/include',
                      'android/frameworks/native/include',
                      'android/frameworks/native/opengl/include')


def _generate_unit_test_ninja():
  n = ninja_generator.TestNinjaGenerator('graphics_translation_unit_test',
                                         enable_clang=True,
                                         base_path='graphics_translation')
  _add_compile_flags(n)
  n.add_ppapi_link_flags()
  n.add_library_deps('libcutils.a', 'libetc1.a', 'libgccdemangle.a',
                     'libutils_static.a', 'libppapi_mocks.a', 'libegl.a',
                     'libgles.a')
  sources = n.find_all_files('graphics_translation/gles', ['_test.cpp'],
                             include_tests=True)
  n.build_default(sources, base_path='mods')
  n.run(n.link())


def _generate_image_generator_ninja():
  n = ninja_generator.ExecNinjaGenerator(
      _get_generator_name(), host=True,
      base_path='mods/graphics_translation/tests')
  _add_compile_flags(n)
  n.add_defines('HAVE_PTHREADS')
  n.add_include_paths('third_party/googletest/include',
                      'third_party/googletest')
  sources = build_common.find_all_files(
      ['mods/graphics_translation/tests'],
      suffixes='.cpp',
      include_tests=True,
      use_staging=False)
  sources.extend(['mods/graphics_translation/gles/debug.cpp',
                  'mods/graphics_translation/gles/texture_codecs.cpp',
                  'src/common/vector.cc',
                  'src/common/matrix.cc',
                  'third_party/googletest/src/gtest-all.cc'])
  sources = [x for x in sources if x.find('apk') < 0]
  n.build_default(sources, base_path=None)
  variables = {'my_static_libs': '-lX11 -lGL'}
  n.link(variables=variables)


def _generate_integration_test_ninja():
  n = ninja_generator.ApkFromSdkNinjaGenerator(
      _get_integration_test_name(),
      base_path='graphics_translation/tests/apk',
      use_ndk=True, use_gtest=True)
  sources = build_common.find_all_files(
      base_paths=['graphics_translation/tests',
                  'graphics_translation/tests/util'],
      suffixes=['.cpp', '.h'],
      include_tests=True,
      include_subdirectories=False)

  # Additional source code dependencies to outside of
  # graphics_translation/tests.
  implicit = [
      'android_libcommon/common/alog.h',
      'graphics_translation/gles/debug.cpp',
      'graphics_translation/gles/debug.h',
      'graphics_translation/gles/texture_codecs.cpp',
      'graphics_translation/gles/texture_codecs.h',
      'src/common/math_test_helpers.h',
      'src/common/matrix.cc',
      'src/common/matrix.h',
      'src/common/vector.cc',
      'src/common/vector.h',
  ]

  n.build_default_all_sources(
      implicit=[staging.as_staging(path) for path in (sources + implicit)])
  n.build_google_test_list(sources)


if not open_source.is_open_source_repo():
  class GraphicsTranslationIntegrationTest(
      atf_gtest_suite_runner.AtfGTestSuiteRunner):
    def __init__(self):
      super(GraphicsTranslationIntegrationTest, self).__init__(
          _get_integration_test_name(),
          os.path.join(_get_apk_path(), _get_integration_test_name() + '.apk'),
          build_common.get_integration_test_list_path(
              _get_integration_test_name()),
          config={
              # TODO(crbug.com/430311): Figure out why this test is flaky.
              'flags': flags.FLAKY,
              'deadline': _TEST_TIMEOUT,
              'suite_test_expectations': {
                  'GraphicsTextureTest#TestCopyTextures': flags.NOT_SUPPORTED,
              },
          })

    def _write_metafile(self, filename):
      metadata = {
          'disableHeartbeat': False,
          'enableAdb': True,
          'stderrLog': 'E',
          'allowEmptyActivityStack': True,
      }
      with open(filename, 'w') as f:
        f.write(json.dumps(metadata))

    def _build_apk_to_crx_command(self):
      apkfile = os.path.join(_get_apk_path(), self.name + '.apk')
      metafile = os.path.join(_get_apk_path(), self.name + '.json')
      self._write_metafile(metafile)
      return [
          'python', _get_apk_to_crx_script(),
          apkfile,
          '--badging-check', 'warning',
          '--destructive',
          '--metadata', metafile,
          '-o', _get_crx_path()]

    def _generate_golden_images(self):
      # Clean the output folders.
      _clean_dir(os.path.join(_get_gen_path(), 'out', 'glx'))

      # Copy test data (eg. textures) to the generator's data folder.
      _copy_tree(_get_data_path(), os.path.join(_get_gen_path(), 'data'))

      # Run the generator.
      cmd = ['./' + _get_generator_name()]
      return self.run_subprocess(cmd, cwd=_get_gen_path())

    def _copy_data_to_crx(self):
      datadir = _get_data_path()
      imagedir = os.path.join(_get_gen_path(), 'out', 'glx')
      outdir = os.path.join(_get_crx_path(), 'vendor', 'chromium', 'crx')

      _copy_tree(datadir, os.path.join(outdir, 'data'))
      _copy_tree(imagedir, os.path.join(outdir, 'gold'))

    def _build_crx(self):
      command = self._build_apk_to_crx_command()
      return self.run_subprocess(command)

    def prepare(self, unused):
      return self._build_crx()

    def setUp(self, test_methods_to_run):
      if (not TEST_OPTIONS.is_buildbot and
          not platform_util.is_running_on_remote_host()):
        self._generate_golden_images()
        self._copy_data_to_crx()
      super(GraphicsTranslationIntegrationTest, self).setUp(test_methods_to_run)


def generate_test_ninjas():
  if open_source.is_open_source_repo():
    return
  _generate_unit_test_ninja()
  _generate_image_generator_ninja()
  _generate_integration_test_ninja()


def get_integration_test_runners():
  if open_source.is_open_source_repo():
    return []
  return [GraphicsTranslationIntegrationTest()]
