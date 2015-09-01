# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for parsing, validating, and requesting build options."""

import argparse
import atexit
import os
import subprocess
import sys
import time

from util import download_package_util_flags

# --target=
_TARGET_NACL_I686 = 'nacl_i686'
_TARGET_NACL_X86_64 = 'nacl_x86_64'
_TARGET_BARE_METAL_I686 = 'bare_metal_i686'
_TARGET_BARE_METAL_ARM = 'bare_metal_arm'
ALLOWED_TARGETS = [_TARGET_NACL_I686,
                   _TARGET_NACL_X86_64,
                   _TARGET_BARE_METAL_I686,
                   _TARGET_BARE_METAL_ARM]
_CONSUMER_SUPPORTED_TARGETS = [_TARGET_NACL_X86_64,
                               _TARGET_BARE_METAL_I686,
                               _TARGET_BARE_METAL_ARM]
_TARGET_MAPPING = {'ni': _TARGET_NACL_I686,
                   'n32': _TARGET_NACL_I686,
                   'nx': _TARGET_NACL_X86_64,
                   'n64': _TARGET_NACL_X86_64,
                   'bi': _TARGET_BARE_METAL_I686,
                   'ba': _TARGET_BARE_METAL_ARM}
_DEFAULT_TARGET = _TARGET_BARE_METAL_I686

# --chrometype=
_ALLOWED_CHROMETYPES = ['beta',
                        'dev',
                        'lkgr',
                        'prebuilt',
                        'stable']
_CHROMETYPE_MAPPING = {'b': 'beta',
                       'v': 'dev',
                       'l': 'lkgr',
                       'p': 'prebuilt',
                       's': 'stable'}
_DEFAULT_CHROMETYPE = 'prebuilt'

# --internal-apks-source=
# prebuilt: use the artifacts previously built by corp builder
# internal: build apk from local checkout.  Used by corp builder.
# internal-dev: a self-pilot mode comparing to internal.  It cuts a
#   almost-always-actually-satisfied dependency from internal apks to framework
#   jar to speed up development iteration.  In addition, it does not sync git
#   repo to DEPS automatically.
_ALLOWED_INTERNAL_APKS_SOURCES = ['internal',  # for the corp builder
                                  'internal-dev',  # for local development
                                  'prebuilt']  # for everyone else
_DEFAULT_INTERNAL_APKS_SOURCES = 'prebuilt'

# --logging=
_ANSI_FB_LOGGING = 'ansi-fb'
_ANSI_SF_LAYER_LOGGING = 'ansi-sf-layer'
_BIONIC_LOADER_LOGGING = 'bionic-loader'
_EGL_API = 'egl-api'
_EGL_API_TRACING = 'egl-api-tracing'
_GLES_API_LOGGING = 'gles-api'
_GLES_API_TRACING = 'gles-api-tracing'
_GLES_PASSTHROUGH_LOGGING = 'gles-passthrough'
_GLES_PASSTHROUGH_TRACING = 'gles-passthrough-tracing'
_JAVA_METHODS_LOGGING = 'java-methods'
_LIBDVM_DEBUG = 'libdvm-debug'
_LOG_THREAD_IDS = 'thread-ids'
_LOG_TIMESTAMPS = 'timestamps'
_MAKE_TO_NINJA_LOGGING = 'make-to-ninja'
_MEMORY_USAGE = 'memory-usage'
_NINJA_GENERATOR_LOGGING = 'ninja-generator'
_NOTICES_LOGGING = 'notices'
_POSIX_TRANSLATION_DEBUG = 'posix-translation-debug'
_VERBOSE_MEMORY_VIEWER = 'verbose-memory-viewer'
_ALLOWED_LOGGING = [_ANSI_FB_LOGGING,
                    _ANSI_SF_LAYER_LOGGING,
                    _BIONIC_LOADER_LOGGING,
                    _EGL_API,
                    _EGL_API_TRACING,
                    _GLES_API_LOGGING,
                    _GLES_API_TRACING,
                    _GLES_PASSTHROUGH_LOGGING,
                    _GLES_PASSTHROUGH_TRACING,
                    _JAVA_METHODS_LOGGING,
                    _LIBDVM_DEBUG,
                    _LOG_THREAD_IDS,
                    _LOG_TIMESTAMPS,
                    _MAKE_TO_NINJA_LOGGING,
                    _MEMORY_USAGE,
                    _NINJA_GENERATOR_LOGGING,
                    _NOTICES_LOGGING,
                    _POSIX_TRANSLATION_DEBUG,
                    _VERBOSE_MEMORY_VIEWER]

# -W options
_ALLOWED_WARNING_LEVEL = ['all',
                          'yes',  # all except -Wunused-*.
                          'no']


class _Options(object):

  def __init__(self):
    self._loggers = {}
    self._goma_ctl_process = None
    self._goma_dir = None
    self._system_packages = []
    self._values = {}
    self.parsed = False

  def __getattr__(self, name):
    """Provides getters for values originated from the command line options.

    For example, OPTIONS.weird() returns True if --weird is passed from the
    command line.
    """

    if name in self._values:
      return lambda: self._values[name]
    raise AttributeError("'_Options' object has no attribute '" + name + "'")

  def get_target_bitsize(self):
    return 64 if self.target().endswith('_x86_64') else 32

  def is_arm(self):
    return self.target().endswith('_arm')

  def is_x86(self):
    return self.is_i686() or self.is_x86_64()

  def is_i686(self):
    return self.target().endswith('_i686')

  def is_x86_64(self):
    return self.target().endswith('_x86_64')

  def is_bare_metal_arm(self):
    return self.target() == _TARGET_BARE_METAL_ARM

  def is_bare_metal_i686(self):
    return self.target() == _TARGET_BARE_METAL_I686

  def is_bare_metal_build(self):
    return self.target().startswith('bare_metal_')

  def is_nacl_build(self):
    return _Options._is_nacl_target(self.target())

  def is_nacl_i686(self):
    return self.target() == _TARGET_NACL_I686

  def is_nacl_x86_64(self):
    return self.target() == _TARGET_NACL_X86_64

  def is_consumer_supported_target(self):
    return self.target() in _CONSUMER_SUPPORTED_TARGETS

  def is_debug_info_enabled(self):
    return not self.disable_debug_info()

  def is_debug_code_enabled(self):
    return not self.disable_debug_code()

  def is_optimized_build(self):
    return self.opt()

  def is_lkgr_chrome(self):
    return self.chrometype() == 'lkgr'

  def is_official_chrome(self):
    return self.chrometype() in ['dev', 'beta', 'stable']

  def is_ansi_fb_logging(self):
    return _ANSI_FB_LOGGING in self._loggers

  def is_ansi_sf_layer_logging(self):
    return _ANSI_SF_LAYER_LOGGING in self._loggers

  def is_bionic_loader_logging(self):
    return _BIONIC_LOADER_LOGGING in self._loggers

  def is_egl_api_logging(self):
    return _EGL_API in self._loggers

  def is_egl_api_tracing(self):
    return _EGL_API_TRACING in self._loggers

  def is_gles_api_logging(self):
    return _GLES_API_LOGGING in self._loggers

  def is_gles_api_tracing(self):
    return _GLES_API_TRACING in self._loggers

  def is_gles_passthrough_logging(self):
    return _GLES_PASSTHROUGH_LOGGING in self._loggers

  def is_gles_passthrough_tracing(self):
    return _GLES_PASSTHROUGH_TRACING in self._loggers

  def is_java_methods_logging(self):
    return _JAVA_METHODS_LOGGING in self._loggers

  def is_libdvm_debug(self):
    return _LIBDVM_DEBUG in self._loggers

  def is_make_to_ninja_logging(self):
    return _MAKE_TO_NINJA_LOGGING in self._loggers

  def is_memory_usage_logging(self):
    return _MEMORY_USAGE in self._loggers

  def is_ninja_generator_logging(self):
    return _NINJA_GENERATOR_LOGGING in self._loggers

  def is_notices_logging(self):
    return _NOTICES_LOGGING in self._loggers

  def is_posix_translation_debug(self):
    return _POSIX_TRANSLATION_DEBUG in self._loggers

  def log_thread_ids(self):
    return _LOG_THREAD_IDS in self._loggers

  def log_timestamps(self):
    return _LOG_TIMESTAMPS in self._loggers

  def internal_apks_source_is_internal(self):
    return self.internal_apks_source().startswith('internal')

  def use_verbose_memory_viewer(self):
    return _VERBOSE_MEMORY_VIEWER in self._loggers

  def get_warning_suppression_cflags(self):
    if self._show_warnings == 'all':
      return []  # no suppression
    elif self._show_warnings == 'yes':
      return ['-Wno-unused-but-set-variable',
              '-Wno-unused-function',
              '-Wno-unused-variable']
    return ['-w']

  def get_system_packages(self):
    return self._system_packages

  @staticmethod
  def _is_nacl_target(target):
    return target.startswith('nacl_')

  @staticmethod
  def _parse_target(value):
    if value in ALLOWED_TARGETS:
      return value
    elif value in _TARGET_MAPPING.keys():
      return _TARGET_MAPPING[value]
    raise argparse.ArgumentTypeError('Invalid target')

  @staticmethod
  def _parse_chrometype(value):
    if value in _ALLOWED_CHROMETYPES:
      return value
    elif value in _CHROMETYPE_MAPPING.keys():
      return _CHROMETYPE_MAPPING[value]
    raise argparse.ArgumentTypeError('Invalid chrometype')

  @staticmethod
  def _print_mapping(label, mapping):
    lines = ('  % 3s: %s' % (k, v) for k, v in mapping.iteritems())
    return '%s:\n%s\n' % (label, '\n'.join(lines))

  @staticmethod
  def _help_epilog():
    str = _Options._print_mapping('Target type shortcuts', _TARGET_MAPPING)
    str += _Options._print_mapping('Chrometype shortcuts', _CHROMETYPE_MAPPING)
    return str

  def _apply_args(self, args):
    args.logging = args.logging.split(',') if args.logging else []
    if args.weird:
      if _Options._is_nacl_target(args.target):
        args.enable_touch_overlay = True
        args.logging.extend([
            # TODO(crbug.com/342652): Re-enable _LIBDVM_DEBUG.
            # _LIBDVM_DEBUG,
            _LOG_THREAD_IDS,
            _LOG_TIMESTAMPS,
            _MEMORY_USAGE,
            _POSIX_TRANSLATION_DEBUG,
            _VERBOSE_MEMORY_VIEWER
        ])
      else:
        # TODO(yusukes|hamaji): Configure Bare Metal i686 weird builder.
        pass
    if args.official_build:
      args.opt = True
      args.disable_debug_code = True
      args.regen_build_prop = True
    return args

  def parse(self, args):
    parser = argparse.ArgumentParser(
        usage=os.path.basename(sys.argv[0]) + ' <options>',
        epilog=_Options._help_epilog(),
        formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--cc-wrapper', metavar='[cc-wrapper]',
                        help='Compiler wrapper used by goma')

    parser.add_argument('--chrometype', '-c', choices=_ALLOWED_CHROMETYPES,
                        default=_DEFAULT_CHROMETYPE,
                        type=_Options._parse_chrometype,
                        help='Indicates Chrome type.')

    parser.add_argument('--configure-jobs', '-j', default=None, type=int,
                        metavar='jobs',
                        help='Max number of parellel jobs run during '
                        'configure.  Defaults to number of CPUs. Set to 0 to '
                        'force configure to run in a single process which can '
                        'aid in diagnosing failures.')

    parser.add_argument('--disable-art-aot', action='store_false',
                        dest='enable_art_aot', help='Disable ART boot image '
                        'and AOT compilation.')

    parser.add_argument('--disable-config-cache', action='store_false',
                        dest='enable_config_cache',
                        help='Disable configuration cache.')

    parser.add_argument('--disable-debug-info', action='store_true',
                        help='Do not generate debug information. ')

    parser.add_argument('--disable-debug-code', action='store_true',
                        help='Skip debug logging / assertions.')

    parser.add_argument('--disable-goma', action='store_true',
                        help='Do not use goma to build.')

    parser.add_argument('--disable-hwui', action='store_true',
                        help='Disable the use of hardware accelerated '
                        'rendering in the Android UI code.')

    parser.add_argument('--disable-method-whitelist', action='store_false',
                        dest='enable_method_whitelist',
                        help='Disable method whitelist for boot.oat. '
                        'This also changes the compiler filter to '
                        '"everything", which will require adjustments to the '
                        'executable section address to be able to run.')

    parser.add_argument('--enable-aacenc', action='store_true',
                        help='Build libraries to support AAC encoding.')

    parser.add_argument('--enable-atrace', action='store_true',
                        help='Enable Android trace events through Chromium')

    parser.add_argument('--enable-binder', action='store_true',
                        help='Enable Binder calls for all services.')

    parser.add_argument('--enable-jemalloc-debug', action='store_true',
                        help='Enable jemalloc debug mode.  This fills all '
                        'memory returned from malloc() and all memory passed '
                        'to free() with garbage.')

    parser.add_argument('--enable-touch-overlay', action='store_true',
                        help='[EXPERIMENTAL]  Overlay touch spots on the '
                        'screen in the plugin after the app renders.')

    parser.add_argument('--enable-valgrind', action='store_true',
                        help='Run unit tests under Valgrind.')

    parser.add_argument('--goma-dir', help='The directory for goma.')

    parser.add_argument('--java-dir',
                        default='/usr/lib/jvm/java-7-openjdk-amd64',
                        help='The directory for Java. The path '
                        'points to a directory, which usually JAVA_HOME env '
                        'variable points to. E.g. '
                        '/usr/lib/jvm/java-7-openjdk-amd64 for Ubuntu.')

    parser.add_argument('--logging', metavar=str(_ALLOWED_LOGGING),
                        help='A comma-separated list of logging to enable on '
                        'build.')

    parser.add_argument('--notest', action='store_false', dest='run_tests',
                        help='Disable automatic running of unit tests during '
                        'build.')

    parser.add_argument('--official-build', action='store_true',
                        help='Set configure options for an official Runtime '
                        'build.')

    parser.add_argument('--opt', '-O', action='store_true',
                        help='Enable optimizations.')

    parser.add_argument('--internal-apks-source',
                        choices=_ALLOWED_INTERNAL_APKS_SOURCES,
                        default=_DEFAULT_INTERNAL_APKS_SOURCES,
                        help='Source of play-services and '
                        'GoogleContactsSyncAdapter APKs. \'prebuilt\' is the '
                        'default and it requires production server access.')

    parser.add_argument('--regen-build-prop', action='store_true',
                        help='Forces regeneration of the build.prop file '
                        'which contains git HEAD information for release '
                        'purposes.  Pass this option to make sure the file is '
                        'up to date.  Note: requires rebuilding the rootfs.')

    parser.add_argument('--restart-goma', action='store_true',
                        help='Restart goma. This is mainly for buildbots.')

    parser.add_argument('--show-warnings', metavar=str(_ALLOWED_WARNING_LEVEL),
                        default='no',
                        help='By default, most of third_party code is '
                        'compiled with -w (ignore all wanings). This option '
                        'removes the compiler flag.')

    parser.add_argument('--strip-runtime-binaries', action='store_true',
                        help='Strip binaries in ARC. Files in '
                        'out/target/<target>/lib will not be stripped. '
                        'This is useful for remote debugging.')

    parser.add_argument('--system-packages',
                        help='A comma-separated list of APK files that should '
                        'be added as system apps.')

    parser.add_argument('--target', '-t', choices=ALLOWED_TARGETS,
                        default=_DEFAULT_TARGET, type=_Options._parse_target,
                        help='Target type to build')

    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show verbose messages while configure runs.')

    parser.add_argument('--weird', action='store_true',
                        help='Automatically sets configuration values used by '
                        'the weird builder.')

    download_package_util_flags.add_extra_flags(parser)

    parsed_args = None
    # Note we override any options in the .configure file with options passed on
    # the command line.
    parsed_args = parser.parse_args(args, parsed_args)
    parsed_args = self._apply_args(parsed_args)
    self._values = vars(parsed_args)

    for name in parsed_args.logging:
      if name in _ALLOWED_LOGGING:
        self._loggers[name] = True
      else:
        print 'Unknown logging:', name
        parser.print_help()
        return -1

    if parsed_args.show_warnings:
      if parsed_args.show_warnings in _ALLOWED_WARNING_LEVEL:
        self._show_warnings = parsed_args.show_warnings
      else:
        print 'Unknown warning level:', parsed_args.show_warnings
        parser.print_help()
        return -1

    if parsed_args.system_packages:
      self._system_packages = parsed_args.system_packages.split(',')

    # ARM Chrome OS does not have a lot of storage and it takes a lot
    # of time to transfer binaries. Note that you still have debug
    # symbols in out/target/<target>/lib.
    if self.is_arm():
      self._values['strip_runtime_binaries'] = True

    # NaCl i686 does not support ART AOT and support is not planned in the
    # future.
    if self.is_nacl_i686():
      self._values['enable_art_aot'] = False

    error = self._check_args(parsed_args)
    if error:
      parser.print_help()
      print '\n', error
      return -1

    self.parsed = True
    return 0

  def _check_args(self, args):
    if args.enable_valgrind and not self.is_bare_metal_i686():
      return '--enable-valgrind works only on Bare Metal i686 target.'
    if args.enable_valgrind and args.opt:
      return ('--enable-valgrind memcheck suppression patterns do not work ' +
              'with optimized code.')

    # Java method logging does not work properly with ART AOT enabled.
    if 'java-methods' in args.logging and args.enable_art_aot:
      return ('java-methods logging cannot be used with ART AOT enabled. '
              'Use --disable-art-aot')

    return None

  @staticmethod
  def _is_goma_path(dirname):
    for goma_file in ['goma_ctl.py', 'gomacc', 'compiler_proxy',
                      'gcc', 'g++', 'clang', 'clang++']:
      if not os.path.exists(os.path.join(dirname, goma_file)):
        return False
    return True

  def _find_goma_path(self):
    if self.goma_dir():
      if not self._is_goma_path(self.goma_dir()):
        print 'goma is not in ' + self.goma_dir()
        sys.exit(1)
      return self.goma_dir()
    goma_home = os.path.join(os.getenv('HOME'), 'goma')
    paths = os.getenv('PATH').split(':') + [goma_home]
    for path in paths:
      if _Options._is_goma_path(path):
        self._goma_dir = path
        return path
    return None

  def _get_goma_ensure_start_command(self):
    return 'restart' if self.restart_goma() else 'ensure_start'

  def wait_for_goma_ctl(self):
    """Waits for goma_ctl process to be finished."""
    if self._goma_ctl_process is None:
      return
    sleep_count = 0
    while self._goma_ctl_process.poll() is None:
      time.sleep(0.1)
      sleep_count += 1
      if sleep_count > 50:
        print 'killing goma_ctl because it took too long at shutdown'
        self._goma_ctl_process.kill()
        return

    # Note that it is safe to wait a subprocess multiple times.
    if self._goma_ctl_process.wait():
      print self._goma_ctl_process.stdout.read()
      print 'goma_ctl %s failed!' % self._get_goma_ensure_start_command()
      sys.exit(1)

  def set_up_goma(self):
    """Checks the path of goma.

    If it's found, this function runs compiler_proxy and returns True.
    """
    if self.disable_goma():
      return False

    goma_path = self._find_goma_path()
    # We honor --cc-wrapper if it is set explicitly.
    if self.cc_wrapper():
      self._values['goma'] = False
      print '%s is used instead of Goma.' % self.cc_wrapper()
      return False

    if not goma_path:
      # Do not use Goma as it is not installed.
      self._values['goma'] = False
      return False

    self._values['goma'] = True
    self._values['cc_wrapper'] = os.path.join(goma_path, 'gomacc')

    if not self._goma_ctl_process:
      goma_ctl_command = [os.path.join(goma_path, 'goma_ctl.py'),
                          self._get_goma_ensure_start_command()]
      # It takes about 2 seconds to run goma_ctl.py ensure_start. To
      # reduce the total time for ./configure, we run this in background
      # and check the exit status of it in the atexit handler.
      self._goma_ctl_process = subprocess.Popen(goma_ctl_command,
                                                stdout=subprocess.PIPE)
      atexit.register(self.wait_for_goma_ctl)
    return True

  def write_configure_file(self, output_file=None):
    options_file = output_file or self.get_configure_options_file()
    output_dir = os.path.dirname(options_file)
    if not os.path.exists(output_dir):
      os.makedirs(output_dir)

    new_configuration_options = ' '.join(sys.argv[1:]) + '\n'
    try:
      with open(options_file, 'r') as f:
        old_configuration_options = f.read()
    except IOError:
      old_configuration_options = ''

    if new_configuration_options != old_configuration_options:
      with open(options_file, 'w') as f:
        f.write(new_configuration_options)

  # Parse the configure.options file.  This is useful for standalone tools that
  # are not run at configure time but rely on configured details (e.g.,
  # launch_chrome.py needs the path to Chrome which changes based on
  # chrometype).
  def parse_configure_file(self, input_file=None):
    options_file = input_file or self.get_configure_options_file()
    if os.path.exists(options_file):
      with open(options_file) as f:
        self.parse(f.read().split())
    else:
      raise IOError('File ' + options_file + ' does not exist.')

  def get_configure_options_file(self):
    return os.path.join('out', 'configure.options')

  def check_access(self, name):
    """Called by AccessControlProxy to check attribute access."""
    if (not self.parsed and
        name not in ('parse', 'parsed', 'parse_configure_file')):
      raise AttributeError(
          'Attempted to access uninitialized OPTIONS values. Please consider '
          'calling OPTIONS.parse_configure_file() in the very beginning of '
          'your script.')


class _AccessControlProxy(object):
  """Wraps an arbitrary object to add attribute access check."""

  __slots__ = ['__target', '__check_access']

  def __init__(self, target, check_access):
    self.__target = target
    self.__check_access = check_access

  def __getattr__(self, name):
    self.__check_access(name)
    return getattr(self.__target, name)


_real_options = _Options()
OPTIONS = _AccessControlProxy(_real_options, _real_options.check_access)
