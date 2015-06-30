# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Code shared between configure.py and generate_chrome_launch_script.py

import contextlib
import fnmatch
import functools
import json
import logging
import modulefinder
import os
import platform
import random
import re
import subprocess
import sys
import time
import urllib2

import dependency_inspection
from build_options import OPTIONS
from util import platform_util

# Following paths are relative to ARC root directory.
OUT_DIR = 'out'
TARGET_COMMON_DIR = os.path.join(OUT_DIR, 'target', 'common')
ARC_WELDER_OUTPUT_DIR = os.path.join(TARGET_COMMON_DIR, 'arc_welder')
ARC_WELDER_UNPACKED_DIR = os.path.join(
    ARC_WELDER_OUTPUT_DIR, 'arc_welder_unpacked')


# When running Python unittest set up by PythonTestNinjaGenerator, this file
# is loaded as out/staging/src/build/build_common.py. Use os.path.realpath
# so that get_arc_root() always returns the real ARC root directory.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
_ARC_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))

# Libraries that are used for checking static initializers.
CHECKED_LIBRARIES = ['arc_nacl_x86_64.nexe', 'libposix_translation.so']

COMMON_EDITOR_TMP_FILE_PATTERNS = ['.*.swp', '*~', '.#*', '#*#']
COMMON_EDITOR_TMP_FILE_REG = re.compile(
    '|'.join('(?:' + fnmatch.translate(pattern) + ')'
             for pattern in COMMON_EDITOR_TMP_FILE_PATTERNS))
CHROME_USER_DATA_DIR_PREFIX = 'arc-test-profile'

# If test succeeds, $out will be written and there will be no terminal
# output. If the test fails, this shows the test output in the
# terminal and does exit 1. $out will not be written and $out.tmp will
# have the output when the test failed.
_TEST_OUTPUT_HANDLER = (' > $out.tmp 2>&1 && mv $out.tmp $out ' +
                        '|| (cat $out.tmp;%s exit 1)')

_CHROMEOS_USR_LOCAL_DIR = '/usr/local'


class SimpleTimer:
  def __init__(self):
    self._start_time = 0
    self._running = False
    self._show = False

  def start(self, msg, show=False):
    assert(not self._running)
    self._start_time = time.time()
    self._running = True
    self._show = show
    if self._show:
      sys.stdout.write(msg + '...')

  def done(self):
    assert(self._running)
    if self._show:
      total_time = time.time() - self._start_time
      sys.stdout.write('.. done! [%0.3fs]\n' % (total_time))
    self._running = False


class StampFile(object):
  def __init__(self, revision, stamp_file, force=False):
    self._revision = str(revision).strip()
    self._stamp_file = stamp_file
    self._force = force

  def is_up_to_date(self):
    """Returns True if stamp file says it is up to date."""
    logging.info('Considering stamp file: %s', self._stamp_file)

    # For force updating, the stamp should be always out of date.
    if self._force:
      logging.info('Always treating as out of date')
      return False

    if os.path.exists(self._stamp_file):
      with open(self._stamp_file, 'r') as f:
        # Ignore leading and trailing white spaces.
        stamp = f.read().strip()
    else:
      stamp = ''

    logging.info('Comparing current stamp \'%s\' to expected \'%s\'',
                 stamp, self._revision)
    return stamp == self._revision

  def update(self):
    """Updates the stamp file to the current revision."""
    with open(self._stamp_file, 'w') as f:
      f.write(self._revision + '\n')


def as_list(input):
  if input is None:
    return []
  if isinstance(input, list):
    return input
  return [input]


def as_dict(input):
  if input is None:
    return dict()
  if isinstance(input, dict):
    return input
  raise TypeError('Cannot convert to dictionary')


def get_arc_root():
  return os.path.abspath(os.path.join(_SCRIPT_DIR, '..', '..'))


def get_android_sdk_path():
  return os.path.join(get_arc_root(), 'third_party', 'android-sdk')


def get_staging_root():
  return os.path.join(OUT_DIR, 'staging')


def get_stripped_dir():
  return os.path.join(get_build_dir(), 'stripped')


def get_stripped_path(path):
  """Returns the path in stripped dir corresponding to |path|."""
  if not path.startswith(get_build_dir() + '/'):
    return None
  return os.path.join(get_stripped_dir(),
                      os.path.relpath(path, get_build_dir()))


def get_android_config_header(is_host):
  if is_host:
    arch_subdir = 'linux-x86'
  elif OPTIONS.is_arm():
    arch_subdir = 'linux-arm'
  else:
    arch_subdir = 'target_linux-x86'
  return os.path.join(get_staging_root(),
                      'android/build/core/combo/include/arch',
                      arch_subdir,
                      'AndroidConfig.h')


def get_android_deps_file():
  return 'src/build/DEPS.android'


def get_android_fs_path(filename):
  return os.path.join(get_android_fs_root(), filename.lstrip(os.sep))


def get_android_fs_root():
  return os.path.join(get_build_dir(), 'root')


def get_android_root():
  return get_android_fs_path('system')


def get_android_sdk_ndk_dependencies():
  return [os.path.join('third_party', 'android-sdk', 'URL'),
          os.path.join('third_party', 'ndk', 'URL')]


def get_build_type():
  # Android has three build types, 'user', 'userdebug', and 'eng'.
  # 'user' is a build with limited access permissions for production.
  # 'eng' is a development configuration with debugging code. See,
  # https://source.android.com/source/building-running.html#choose-a-target.
  # ARC uses 'user' only when debug code is disabled.
  if OPTIONS.is_debug_code_enabled():
    return 'eng'
  return 'user'


def get_bionic_crtbegin_o():
  return os.path.join(get_load_library_path(), 'crtbegin.o')


def get_bionic_crtbegin_so_o():
  return os.path.join(get_load_library_path(), 'crtbeginS.o')


def get_bionic_crtend_o():
  return os.path.join(get_load_library_path(), 'crtend.o')


def get_bionic_crtend_so_o():
  return os.path.join(get_load_library_path(), 'crtendS.o')


def get_bionic_libc_so():
  return os.path.join(get_load_library_path(), 'libc.so')


def get_bionic_libcxx_so():
  return os.path.join(get_load_library_path(), 'libc++.so')


def get_bionic_libdl_so():
  return os.path.join(get_load_library_path(), 'libdl.so')


def get_bionic_libm_so():
  return os.path.join(get_load_library_path(), 'libm.so')


def get_bionic_libstlport_so():
  return os.path.join(get_load_library_path(), 'libstlport.so')


def get_bionic_libc_malloc_debug_leak_so():
  return os.path.join(get_load_library_path(), 'libc_malloc_debug_leak.so')


def get_bionic_objects():
  return ([get_bionic_crtbegin_o(),
           get_bionic_crtbegin_so_o(),
           get_bionic_crtend_o(),
           get_bionic_crtend_so_o(),
           get_bionic_runnable_ld_so()] +
          get_bionic_shared_objects(use_stlport=False, use_libcxx=False))


def get_bionic_runnable_ld_so():
  return os.path.join(get_load_library_path(), 'runnable-ld.so')


def get_bionic_shared_objects(use_stlport, use_libcxx):
  assert not (use_stlport and use_libcxx), (
      'STLport and libc++ cannot be used together in one library.')
  objects = [get_bionic_libc_so(),
             get_bionic_libdl_so(),
             get_bionic_libm_so()]
  if use_stlport:
    objects.append(get_bionic_libstlport_so())
  if use_libcxx:
    objects.append(get_bionic_libcxx_so())
  return objects


def get_bionic_arch_name():
  """Returns Bionic's architecture name as used in sub directories.

  The architecture name is used in sub directories like
  android/bionic/libc/kernel/uapi/asm-arm.
  android/bionic/libc/arch-arm.
  """
  if OPTIONS.is_arm():
    return 'arm'
  else:
    return 'x86'


def filter_params_for_harfbuzz(vars):
  if OPTIONS.is_nacl_x86_64() and not OPTIONS.is_optimized_build():
    # To work around nativeclient:3844, use -O1 even when --opt is not
    # specified.
    # TODO(nativeclient:3844): Remove this.
    vars.get_cflags().append('-O1')


def _get_opt_suffix():
  return '_opt' if OPTIONS.is_optimized_build() else '_dbg'


def get_target_dir_name(target_override=None):
  target = target_override or OPTIONS.target()
  return target + _get_opt_suffix()


def get_build_dir(target_override=None, is_host=False):
  if is_host:
    return os.path.join(OUT_DIR, 'target', 'host' + _get_opt_suffix())
  else:
    target = target_override or OPTIONS.target()
    assert target != 'host' and target != 'java'
    return os.path.join(OUT_DIR, 'target', get_target_dir_name(target))


def get_intermediates_dir_for_library(library, is_host=False):
  """Returns intermediate output directory for the given library.

  host:  out/target/host_(dbg|opt)/intermediates/libmylib_a
  target:  out/target/<target>/intermediates/libmylib_a
  """
  basename, extension = os.path.splitext(library)
  extension = extension[1:]
  return os.path.join(get_build_dir(is_host=is_host),
                      'intermediates', basename + '_' + extension)


def get_build_path_for_library(library, is_host=False):
  """Returns intermediate build path to the given library.

  host: out/target/host_(dbg|opt)/intermediates/libmylib_a/libmylib.a
  target: out/target/<target>/intermediates/libmylib_a/libmylib.a
  """
  return os.path.join(get_intermediates_dir_for_library(
      library, is_host=is_host), library)


def get_build_path_for_executable(executable, is_host=False):
  """Returns intermediate build path to the given host executable.

  host: out/target/host_(dbg|opt)/intermediates/executable/executable
  target: out/target/<target>/intermediates/executable/executable
  """
  return os.path.join(get_build_dir(is_host=is_host),
                      'intermediates', executable, executable)


def get_build_path_for_jar(jar_name, subpath=None, is_target=False):
  root = get_target_common_dir()
  if is_target:
    root = get_build_dir()
  path = os.path.join(root, 'obj', 'JAVA_LIBRARIES',
                      jar_name + '_intermediates')
  if subpath:
    path = os.path.join(path, subpath)
  return path


def get_build_path_for_apk(apk_name, subpath=None, is_target=False):
  root = get_target_common_dir()
  if is_target:
    root = get_build_dir()
  path = os.path.join(root, 'obj', 'APPS', apk_name + '_intermediates')
  if subpath:
    path = os.path.join(path, subpath)
  return path


def get_build_path_for_gen_test_template(test_name):
  return os.path.join(get_target_common_dir(),
                      'test_template_' + test_name)


def get_arc_welder_output_dir():
  return ARC_WELDER_OUTPUT_DIR


def get_arc_welder_unpacked_dir():
  return ARC_WELDER_UNPACKED_DIR


def get_build_tag(commit='HEAD'):
  if not os.path.exists(os.path.join(get_arc_root(), '.git')):
    # This ARC tree should be a stashed copy. Return a fake version.
    return '0'
  return subprocess.check_output(
      ['git', 'describe', '--first-parent',
       '--match', 'arc-runtime-*', commit]).strip()


def get_build_version_path():
  return os.path.join(OUT_DIR, 'ARC_VERSION')


def get_build_version(commit='HEAD'):
  if commit == 'HEAD':
    dependency_inspection.add_files(get_build_version_path())
  return get_build_tag(commit).replace('arc-runtime-', '')


def get_chrome_default_user_data_dir():
  return os.path.join(os.getenv('TMPDIR', '/tmp'),
                      os.getenv('USER'),
                      CHROME_USER_DATA_DIR_PREFIX,
                      get_target_dir_name())


def get_chrome_deps_file():
  return 'src/build/DEPS.chrome'


def get_chrome_revision_by_hash(hash):
  url = ('https://chromium.googlesource.com/chromium/src'
         '/+/%s?format=JSON') % hash
  try:
    raw_data = urllib2.urlopen(url).read()
  except urllib2.URLError:
    print 'Failed to get data from: ' + url
    return None
  if raw_data.startswith(')]}\'\n'):
    raw_data = raw_data[5:]
  data = json.loads(raw_data)
  message = data['message'].replace('\n', ' ')
  m = re.match(r'.*Cr-Commit-Position: refs/heads/master@{#([0-9]+).*}',
               message)
  if m:
    return m.group(1)
  print 'Chrome revision not found for', hash
  return None


def get_prebuilt_chrome_libosmesa_path():
  return os.path.join(get_chrome_prebuilt_path(), 'libosmesa.so')


def get_chrome_exe_path_on_local_host():
  if OPTIONS.is_official_chrome():
    assert platform.system() == 'Linux', 'Only Linux is supported this time'

    if OPTIONS.chrometype() == 'dev':
      chrome_dir = 'chrome-unstable'
    elif OPTIONS.chrometype() == 'beta':
      chrome_dir = 'chrome-beta'
    else:
      chrome_dir = 'chrome'

    return os.path.join(get_chrome_prebuilt_path(),
                        'opt', 'google', chrome_dir, 'chrome')
  else:
    return os.path.join(get_chrome_prebuilt_path(), 'chrome')


def get_chrome_prebuilt_path():
  # Use 32-bit version of Chrome on Windows regardless of the target bit size.
  if platform_util.is_running_on_cygwin():
    return os.path.join('out', 'chrome32')
  if OPTIONS.is_x86_64():
    return os.path.join('out', 'chrome64')
  else:
    return os.path.join('out', 'chrome32')


def get_chrome_prebuilt_stamp_file():
  return os.path.join(get_chrome_prebuilt_path(), 'STAMP')


def get_chrome_ppapi_root_path():
  return os.path.join('third_party', 'chromium-ppapi')


def get_chromeos_arc_root_without_noexec(*subdirs):
  """Returns a directory whose filesystem is mounted without noexec.

  Chrome OS mounts most filesystems with noexec mount option, which prevents
  executable files from being executed directly. In order to run executable
  files for testing, we need to copy the files to a directory whose filesystem
  is mounted without noexec. This function returns /usr/local/arc as one of
  such directories. |subdirs| is joined to this path.
  """
  return os.path.join(_CHROMEOS_USR_LOCAL_DIR, 'arc', *subdirs)


def get_extract_google_test_list_path():
  return os.path.join(
      'src', 'build', 'util', 'test', 'extract_google_test_list.py')


def get_gdb_multiarch_dir():
  return 'third_party/gdb-multiarch'


def get_gdb_multiarch_path():
  return os.path.join(get_gdb_multiarch_dir(), 'usr/bin/gdb-multiarch')


def get_load_library_path(target_override=None):
  return os.path.join(get_build_dir(target_override), 'lib')


def get_load_library_path_for_test(target_override=None):
  return os.path.join(get_build_dir(target_override), 'test/lib')


def get_posix_translation_readonly_fs_image_file_path():
  return os.path.join(get_build_dir(), 'posix_translation_fs_images',
                      'readonly_fs_image.img')


def get_ppapi_fpabi_shim_dir():
  assert use_ppapi_fpabi_shim()
  return os.path.join(get_build_dir(), 'ppapi_fpabi_shim')


def get_runtime_combined_out_dir():
  return os.path.join(OUT_DIR, 'target', 'common', 'runtime_combined')


def get_runtime_main_nexe():
  return os.path.join(get_build_dir(),
                      'lib/arc_%s.nexe' % OPTIONS.target())


def get_runtime_file_list():
  return os.path.join(get_build_dir(), 'runtime_file_list.txt')


def get_runtime_file_list_cc():
  return os.path.join(get_build_dir(), 'runtime_file_list.cc')


def get_runtime_platform_specific_path(runtime_out_dir, target):
  return os.path.join(runtime_out_dir, '_platform_specific', target)


def get_runtime_out_dir():
  return os.path.join(get_build_dir(), 'runtime')


def get_runtime_build_stamp():
  return os.path.join(get_runtime_out_dir(), 'BUILD_STAMP')


def get_runtime_version():
  runtime_tag = subprocess.check_output(
      ['git', 'describe', '--first-parent', '--abbrev=0',
       '--match', 'arc-runtime-*']).strip()
  version_string = runtime_tag.replace('arc-runtime-', '')
  for part in version_string.split('.'):
    num = int(part)
    assert 0 <= num < 65535, 'runtime version out of range: ' + runtime_tag
  assert len(version_string.split('.')) <= 4
  return version_string


def get_host_common_dir():
  return os.path.join(OUT_DIR, 'host', 'common')


def get_target_common_dir():
  return TARGET_COMMON_DIR


def get_notice_files_dir():
  return os.path.join(get_target_common_dir(), 'NOTICE_FILES')


def get_target_configure_options_file(target=None):
  return os.path.join(get_build_dir(target), 'configure.options')


def get_generated_metadata_js_file():
  return os.path.join(get_target_common_dir(),
                      'packaging_gen_sources/metadata.js')


def get_temp_dir():
  return os.path.join(OUT_DIR, 'tmp')


def get_test_bundle_name(commit='HEAD'):
  return 'test-bundle-%s.zip' % get_build_version(commit)


def get_thirdparty_gclient_revision_file():
  return os.path.join('third_party', '.gclient_last_sync')


def get_javac_revision_file():
  return os.path.join(OUT_DIR, 'STAMP.jdk')


def get_generated_ninja_dir():
  return os.path.join(OUT_DIR, 'generated_ninja')


def get_config_cache_dir():
  return os.path.join(get_build_dir(), 'config_cache')


def get_integration_test_list_dir():
  return os.path.join(get_target_common_dir(), 'integration_test')


def get_integration_test_list_path(module_name):
  return os.path.join(
      get_integration_test_list_dir(), module_name + '.txt')


def get_all_integration_test_lists_path():
  return os.path.join(
      get_integration_test_list_dir(), 'ALL_TEST_LISTS.txt')


def expand_path_placeholder(path):
  """Returns the path whose replacement fields are filled properly.

  Following replacement fields are supported.
  - '{out}': filled with OUT_DIR.
  - '{target}': filled with get_target_dir_name().
  """
  return path.format(out=OUT_DIR, target=get_target_dir_name())


def get_test_output_handler(use_crash_analyzer=False):
  analyzer = ''
  # Only Bionic build can be handled by crash_analyzer.
  if use_crash_analyzer:
    # Note that crash_analyzer outputs nothing if it cannot find a
    # crash message.
    analyzer = ' python src/build/crash_analyzer.py $out.tmp;'
  return _TEST_OUTPUT_HANDLER % analyzer


def get_tools_dir():
  return os.path.join(OUT_DIR, 'tools')


def get_unittest_info_path(*subpath):
  return os.path.join(get_build_dir(), 'unittest_info', *subpath)


def get_all_unittest_info_path():
  return get_unittest_info_path('ALL_UNITTEST_INFO.txt')


def get_graphics_translation_test_name():
  return 'graphics.translation.test'


def get_graphics_translation_image_generator_name():
  return 'graphics_translation_image_generator'


def is_common_editor_tmp_file(filename):
  return bool(COMMON_EDITOR_TMP_FILE_REG.match(filename))


def get_dex2oat_target_dependent_flags_map():
  # New flags added here might need to be accounted for in
  # src/build/generate_build_prop.py for runtime dex2oat to work properly.
  flags = {}
  if not OPTIONS.is_debug_info_enabled():
    flags['no-include-debug-symbols'] = ''

  if OPTIONS.is_i686():
    flags['instruction-set-features'] = 'default'
    flags['instruction-set'] = 'x86'
    flags['compiler-filter'] = 'speed'
  elif OPTIONS.is_x86_64():
    flags['instruction-set-features'] = 'default'
    flags['instruction-set'] = 'x86_64'
    flags['compiler-filter'] = 'space'
    flags['small-method-max'] = '30'
    flags['tiny-method-max'] = '10'
  elif OPTIONS.is_arm():
    flags['instruction-set-features'] = 'div'
    flags['instruction-set'] = 'arm'
    flags['compiler-filter'] = 'everything'
  return flags


def get_dex2oat_target_dependent_flags():
  flags_map = get_dex2oat_target_dependent_flags_map()
  flags = []
  for flag, value in flags_map.iteritems():
    if value == '':
      flags.append('--' + flag)
    else:
      flags.append('--' + flag + '=' + value)
  return flags


def get_art_isa():
  if OPTIONS.is_i686():
    return 'x86'
  elif OPTIONS.is_x86_64():
    return 'x86_64'
  elif OPTIONS.is_arm():
    return 'arm'
  raise Exception('Unable to map target into an ART ISA: %s' % OPTIONS.target())


def use_ppapi_fpabi_shim():
  return OPTIONS.is_arm()


def use_ndk_direct_execution():
  # On -t=ba, we always use NDK direct execution. On -t=bi, it is dynamically
  # enabled/disabled at runtime. When --ndk-abi=x86 is passed, it is enabled.
  # Otherwise it is not.
  return OPTIONS.is_bare_metal_build()


def has_internal_checkout():
  return os.path.exists(os.path.join(_ARC_ROOT, 'internal'))


class _Matcher(object):
  def __init__(self, include_re, exclude_re):
    self._include_re = include_re
    self._exclude_re = exclude_re

  def match(self, x):
    if self._exclude_re and self._exclude_re.search(x):
      return False
    if not self._include_re:
      return True
    return self._include_re.search(x)


class _MatcherFactory(object):
  def __init__(self):
    self._include_pattern_list = []
    self._exclude_pattern_list = []

  def add_inclusion(self, pattern):
    self._include_pattern_list.append(pattern)

  def add_exclusion(self, pattern):
    self._exclude_pattern_list.append(pattern)

  @staticmethod
  def _compile(pattern_list):
    if not pattern_list:
      return None
    return re.compile('|'.join(pattern_list))

  def build_matcher(self):
    return _Matcher(_MatcherFactory._compile(self._include_pattern_list),
                    _MatcherFactory._compile(self._exclude_pattern_list))


def _build_matcher(exclude_filenames, include_tests, include_suffixes,
                   include_filenames):
  factory = _MatcherFactory()

  factory.add_exclusion(COMMON_EDITOR_TMP_FILE_REG.pattern)

  for value in as_list(exclude_filenames):
    factory.add_exclusion(
        re.escape(value if '/' not in value else ('/' + value)) + '$')

  if not include_tests:
    factory.add_exclusion(re.escape('_test.'))
    factory.add_exclusion(re.escape('/tests/'))
    factory.add_exclusion(re.escape('/test_util/'))

  for value in as_list(include_suffixes):
    factory.add_inclusion(re.escape(value) + '$')

  for value in as_list(include_filenames):
    factory.add_inclusion(re.escape('/' + value) + '$')

  return factory.build_matcher()


def _enumerate_files(base_path, recursive):
  for root, dirs, files in os.walk(base_path, followlinks=True):
    if not recursive:
      dirs[:] = []
    for one_file in files:
      yield os.path.join(root, one_file)


def _maybe_relpath(path, root):
  return path if root is None else os.path.relpath(path, root)


def _maybe_join(root, path):
  return path if root is None else os.path.join(root, path)


def find_all_files(base_paths, suffixes=None, include_tests=False,
                   use_staging=True, exclude=None, filenames=None,
                   recursive=True):
  """Find all files under given set of base_paths matching criteria.

  Args:
      base_paths: A list of paths to search. For example ['src/'] to include
          files under the 'src' directory.
      suffixes: (Optional) A list of suffixes to match. For example ['.cpp'] to
          only match C++ files with that extension. The default is to match any
          suffix.
      include_tests: (Optional) Set this to true to include them, for example
          when building a unit test module. The default is to exclude tests.
      use_staging: (Optional) The most common use case of this function is to
          find files under the staging directory. Set this to False to instead
          look for files outside it.
      exclude: (Optional) A list of suffixes or paths to exclude. For example
          ['/test/', '_test.c'] excludes any files inside a directory named
          test, or any file that ends with the suffix '_test.c'. The default is
          to not exclude any match this way.
      filenames: (Optional) A list of filenames to restrict the match to,
         regardless of path. For example ['foo.c'] will match files foo/foo.c
         and foo/bar/foo.c if those are encountered by the search. The default
         is to not restrict the matching this way.
      recursive: (Optional) The default is to search and try to match files in
          all subdirectories found from each base_path. Set this to false to
          restrict the search to just the named directories.

  Returns:
      A list of files, matching the criteria specified by the arguments.

      Matching is done by applying any exclusion rules first, and then applying
      any inclusion rules to select what files to return.

      Each file will be prefixed by the base path under which it was found. For
      example, with the call find_all_files(['foo/'], 'suffixes=['.c']), the
      output might be foo/bar.c when bar.c is found under foo/.

  Notes:
      For the most common use case where the default of use_staging=True, the
      base_paths are expected to be valid relative paths in the staging
      directory, and the output list of files will also be relative paths to
      files there.

      If this code is being used to more generally find files, then the caller
      is responsible for passing use_staging=False.

      Also, if this function is called while a config.py is running, it records
      the base_paths as dependencies of the config.py so they build files are
      properly regenerated on change.
  """
  matcher = _build_matcher(exclude, include_tests, suffixes, filenames)
  root = None
  if use_staging:
    root = os.path.join(get_arc_root(), get_staging_root())
  listing_roots = [_maybe_join(root, base_path)
                   for base_path in as_list(base_paths)]
  if listing_roots:
    dependency_inspection.add_file_listing(
        listing_roots, matcher, root, recursive)

  result = []
  for listing_root in listing_roots:
    for file_path in _enumerate_files(listing_root, recursive):
      result_path = _maybe_relpath(file_path, root)
      if matcher.match(result_path):
        result.append(result_path)
  # For debugging/diffing purposes, sort the file list.
  return sorted(result)


def _get_ninja_jobs_argument():
  # -j200 might be good because having more tasks doesn't help a
  # lot and Z620 doesn't die even if everything runs locally for
  # some reason.
  if OPTIONS.set_up_goma():
    OPTIONS.wait_for_goma_ctl()
    return ['-j200', '-l40']
  return []


class RunNinjaException(Exception):
  def __init__(self, msg, cmd):
    super(RunNinjaException, self).__init__(msg)
    self.cmd = cmd


def run_ninja(args=None, cwd=None):
  cmd = ['ninja'] + _get_ninja_jobs_argument()
  if args:
    cmd = cmd + args

  res = subprocess.call(cmd, cwd=cwd)
  if res != 0:
    raise RunNinjaException('Ninja error %d' % res, ' '.join(cmd))


def find_python_dependencies(package_root_path, module_path):
  """Returns a filtered list of dependencies of a python script.

  'module_path' is the path to the python module/script to examine.

  'package_root_path' serves to identify the root of the package the module
  belongs to, and additionally is used to filter the returned dependency list to
  the list of imported files contained under it.

  Also, if this function is called while a config.py is running, records the
  resulting python scripts as the dependencies of the config.py.
  """
  pythonpath = sys.path[:]
  if package_root_path not in pythonpath:
    pythonpath[0:0] = [package_root_path]

  module_dir = os.path.dirname(module_path)
  if module_dir not in pythonpath:
    pythonpath[0:0] = [module_dir]

  finder = modulefinder.ModuleFinder(pythonpath)
  finder.run_script(module_path)
  dependencies = [module.__file__ for module in finder.modules.itervalues()
                  if module.__file__]

  result = [path for path in dependencies
            if (path.startswith(package_root_path) and path != module_path)]

  dependency_inspection.add_files(module_path, *result)
  return result


def get_gsutil_executable():
  gsutil = 'third_party/tools/depot_tools/third_party/gsutil/gsutil'
  if not os.access(gsutil, os.X_OK):
    raise Exception('%s is not available' % gsutil)
  return gsutil


def with_retry_on_exception(func):
  """Decorator to run a function with retry on exception.

  On failure (when an exception is raised), recalls the function with the
  same arguments after certain sleep. If retry does not work for several
  times (currently it attempts 5 retries, i.e. 6 trials in total), re-raises
  the last exception.
  """
  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    # On first failure, we retry with 5 secs sleep. If it still fails,
    # we wait 30 secs, 1 min, 2 mins and then 4 mins, before retry.
    # The sleeping duration is chosen just heuristically.
    # cf) Exponential backoff.
    backoff_list = [5, 30, 60, 120, 240]
    while True:
      try:
        return func(*args, **kwargs)
      except Exception:
        # Let bot mark warning.
        print '@@@STEP_WARNINGS@@@'
        if not backoff_list:
          raise
        # Add small randomness to avoid continuous conflicting.
        sleep_duration = backoff_list.pop(0) + random.randint(0, 15)
        logging.exception('Retrying after %d s sleeping', sleep_duration)
        time.sleep(sleep_duration)
  return wrapper


def download_content(url):
  """Downloads the content at the URL.

  Considering server/network flakiness and error, this tries downloading on
  failure several times.
  """
  logging.info('Downloading... %s', url)

  @with_retry_on_exception
  def internal():
    with contextlib.closing(urllib2.urlopen(url)) as stream:
      return stream.read()
  return internal()
