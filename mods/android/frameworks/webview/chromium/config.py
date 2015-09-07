# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from src.build import build_common
from src.build import make_to_ninja
from src.build import ninja_generator
from src.build import ninja_generator_runner
from src.build import open_source
from src.build import staging

# A map which provides a relative path for a directory that contains template
# file to generate Java source files for each chromium component.
_GYP_TEMPLATE_PATH_MAP = {
    'base': 'base/android/java/src/org/chromium/base',
    'content': 'content/public/android/java/src/org/chromium/content',
    'media': 'media/base/android/java/src/org/chromium/media',
    'net': 'net/android/java',
    'ui': 'ui/android/java'}


def _get_path_components_following_mark(path, mark):
  """Splits |path| and return a path components list that follow |mark|.

  For instance, when |path| is '/foo/mark/bar/baz' and |mark| is 'mark', it
  returns ['bar', 'baz'].
  """
  paths = path.split('/')
  return paths[paths.index(mark) + 1:]


def _fix_gen_source_path(path):
  """Fixes a generated source path that make_to_ninja can not expand correctly.

  |path| is something like '/<somewhere>/arc/out/target/common/make_to_ninja/
  out/target/product/generic_x86/obj/GYP/shared_intermediates/templates/org/
  chromium/base/ActivityState.java'. This strips a long full path prefix before
  'GYP/...', and make it replaced under the build dir as e.g., 'out/target/
  common/obj/GYP/shared_intermediates/templates/org/chromium/base/
  ActivityState.java'.
  """
  return os.path.join(build_common.get_target_common_dir(), 'obj/GYP',
                      *_get_path_components_following_mark(path, 'GYP'))


def _get_template_path(base_path, path):
  """Provides a template file path for a Java source file.

  Some Java source files are generated from template files, and the place for
  template files are different and depend on chromium components. This function
  converts |path| for a generated Java source file to a template file path.
  For instance, when |path| is ['net', 'foo', 'bar.baz'], it returns
  'ui/android/java/net/bar.template' by using _GYP_TEMPLATE_PATH_MAP for the
  'net' components.
  For real Android build, Android.mk includes a bunch of .mk files to provide
  them. But make_to_ninja does not support 'LOCAL_MODULE_CLASS := GYP' used in
  .mk files.

  """
  chromium_path = _get_path_components_following_mark(path, 'chromium')
  template_path = _GYP_TEMPLATE_PATH_MAP[chromium_path[0]]
  if chromium_path[0] == 'ui':
    # ui does not follow the convention, it only uses the basename.
    name = os.path.splitext(chromium_path[-1])[0] + '.template'
  else:
    name = os.path.splitext(os.path.join(*chromium_path[1:]))[0] + '.template'
  return os.path.join(base_path, '..', template_path, name)


def _generate_webview_package():
  # We modified package.mk to generate the intermediate .jar since it does not
  # use any of the normal mechanisms to produce the final package. We perform
  # those steps manually:
  resource_subdirectories = ['res']
  gen_resource_dirs = [
      ('android_gen_sources/GYP/shared_intermediates/'
       'android_webview_jarjar_content_resources/jarjar_res'),
      ('android_gen_sources/GYP/shared_intermediates/'
       'android_webview_jarjar_ui_resources/jarjar_res'),
      ('android_gen_sources/GYP/ui_strings_grd_intermediates/'
       'ui_strings_grd/res_grit'),
      ('android_gen_sources/GYP/content_strings_grd_intermediates/'
       'content_strings_grd/res_grit')
  ]
  for gen_resource_dir in gen_resource_dirs:
    resource_subdirectories.append(
        os.path.relpath(
            os.path.join(build_common.get_target_common_dir(),
                         gen_resource_dir),
            staging.as_staging('android/frameworks/webview/chromium')))
  n = ninja_generator.ApkNinjaGenerator(
      'webview',
      base_path='android/frameworks/webview/chromium',
      install_path='/system/framework',
      aapt_flags=[
          '--shared-lib',
          '--auto-add-overlay',
          '--extra-packages',
          'com.android.webview.chromium:org.chromium.content:org.chromium.ui'],
      resource_subdirectories=resource_subdirectories)
  # This package is about adding Android resources to the webview_library.
  # Since the resources are built from pre-generated soruce files, we need to
  # explicitly include the right NOTICE file.
  n.add_notice_sources([
      staging.as_staging('android/frameworks/webview/chromium/NOTICE')])

  n.add_extracted_jar_contents('webview_library')

  n.package()
  n.install()


def _generate_android_webview():
  def _filter(vars):
    if not (vars.is_java_library() or vars.is_package()):
      return False
    module_name = vars.get_module_name()
    if module_name not in ['android_webview_java_with_new_resources',
                           'android_webview_java']:
      return False
    # Building parts of chromium is special and make_to_ninja can not handle
    # path expansion on LOCAL_GENERATED_SOURCES correctly. |sources| contains
    # files that are listed in LOCAL_GENERATED_SOURCES, and following code
    # replaces them with right places.
    sources = vars.get_generated_sources()
    sources[:] = [_fix_gen_source_path(x) for x in sources]

    if module_name == 'android_webview_java':
      # Generate a custom NinjaGenerator to generate Java source files from
      # template files.  This rule is based on target .mk files in
      # android/external/chromium_org/base/.
      # TODO(crbug.com/394654): Remove a manually converted NinjaGenerator once
      # make_to_ninja supports 'LOCAL_MODULE_CLASS := GYP' modules.
      n = ninja_generator.NinjaGenerator(module_name + '_gyp')
      n.rule('gyp_gcc_preprocess',
             'mkdir -p $out_dir && '
             'cd $work_dir && '
             'python ../build/android/gyp/gcc_preprocess.py '
             '--include-path=.. --output=$real_out --template=$in',
             description='gyp/gcc_preprocess.py --include-path=.. '
                         '--output=$out --template=$in')
      base_path = vars.get_path()
      for source in sources:
        template = _get_template_path(base_path, source)
        out_dir = os.path.dirname(source)
        work_dir = os.path.join(
            base_path, '..',
            _get_path_components_following_mark(source, 'chromium')[0])
        variables = {
            'out_dir': out_dir,
            'work_dir': work_dir,
            'real_out': os.path.realpath(source)}
        n.build(source, 'gyp_gcc_preprocess',
                inputs=os.path.realpath(template), variables=variables)
    return True
  make_to_ninja.MakefileNinjaTranslator(
      'android/external/chromium_org/android_webview').generate(_filter)


def _generate_webview_library():
  def _filter(vars):
    module_name = vars.get_module_name()
    if module_name != 'webview_library':
      return False

    # LOCAL_JARJAR_RULES should be defined as $(LOCAL_PATH)/jarjar-rules.txt.
    # But, webviewchromium defines it as $(CHROMIUM_PATH) relative, and
    # $(CHROMIUM_PATH) is 'external/chromium_org'. As a result, ARC cannot
    # handle the file path for LOCAL_JARJAR_RULES correctly.
    # ARC manually fixes the path with 'android' prefix, and converts it to
    # a staging path.
    vars._jarjar_rules = staging.as_staging(
        os.path.join('android', vars._jarjar_rules))
    return True

  env = {
      'res_overrides': '',
      'version_build_number': '',
      'R_file_stamp': ''}
  make_to_ninja.MakefileNinjaTranslator(
      'android/frameworks/webview/chromium',
      extra_env_vars=env).generate(_filter)


def generate_ninjas():
  # Only Java code is built here, so nothing to do in open source.
  if open_source.is_open_source_repo():
    return

  ninja_generator_runner.request_run_in_parallel(
      _generate_android_webview,
      _generate_webview_library,
      _generate_webview_package)
