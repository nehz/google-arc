#!/usr/bin/python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess
import sys

import build_common
from build_options import OPTIONS
from util import platform_util

# Paths for various tools, libs, and sdks.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PEPPER_VERSION = 'pepper_canary'
_CANNED_QEMU_ARM = 'canned/host/bin/linux-x86_64/qemu-arm'
_DEXMAKER_PATH = os.path.join('third_party', 'android', 'external', 'dexmaker')
_NACL_DEPS_PATH = os.path.join(_SCRIPT_DIR, 'DEPS.naclsdk')
_NACL_SDK_PATH = os.path.join('third_party', 'nacl_sdk', _PEPPER_VERSION)
_NACL_TOOLS_PATH = os.path.join(_NACL_SDK_PATH, 'tools')
# TODO(crbug.com/247242): support --naclsdktype={debug,release}
_NACL_SDK_RELEASE = 'Release'  # alternative: Debug
_QEMU_ARM_LD_PATH = '/usr/arm-linux-gnueabihf'
_CHROMEOS_USR_LOCAL_DIR = '/usr/local'
_CLANG_BIN_DIR = 'third_party/ndk/toolchains/llvm-3.4/prebuilt/linux-x86/bin'

# Used in get_gcc_raw_version().
_GCC_RAW_VERSION_CACHE = {}

# The pinned version of the Android SDK's build tools is used for ARC build.
_ANDROID_SDK_BUILD_TOOLS_PINNED_VERSION = '19.1.0'


def _get_android_build_tools_dir():
  return os.path.join('third_party', 'android', 'build', 'tools')


def get_android_sdk_build_tools_pinned_version():
  """Returns the pinned version of the Android SDK's build tools."""
  return _ANDROID_SDK_BUILD_TOOLS_PINNED_VERSION


def get_android_sdk_build_tools_dir():
  return os.path.join('third_party', 'android-sdk', 'build-tools',
                      get_android_sdk_build_tools_pinned_version())


def get_chromeos_dir_without_noexec():
  """Returns a directory whose filesystem is mounted without noexec.

  Chrome OS mounts most filesystems with noexec mount option, which prevents
  executable files from being executed directly. In order to run executable
  files for testing, we need to copy the files to a directory whose filesystem
  is mounted without noexec. This function returns /usr/local as one of such
  directories.
  """
  return _CHROMEOS_USR_LOCAL_DIR


def get_adb_path_for_chromeos():
  """Returns the directory that contains the adb executable for Chrome OS."""

  if platform_util.is_running_on_chromeos():
    # The adb binary is copied to a directory whose filesystem is mounted
    # without noexec mount options on Chrome OS.
    root = get_chromeos_dir_without_noexec()
  else:
    root = build_common.get_arc_root()

  # Chrome OS based on linux-i686 is not supported.
  target = 'linux-arm' if OPTIONS.is_arm() else 'linux-x86_64'
  return os.path.join(root, 'out/adb', target, 'adb')


def _get_adb_path_for_localhost():
  root = os.path.join(build_common.get_arc_root(), 'out/adb')
  if platform_util.is_running_on_mac():
    return os.path.join(root, 'mac-x86_64/adb')
  elif platform_util.is_running_on_cygwin():
    return os.path.join(root, 'win-x86_64/adb.exe')
  elif platform_util.is_running_on_chromeos():
    return get_adb_path_for_chromeos()
  else:
    # For Linux desktop.
    return 'third_party/android-sdk/platform-tools/adb'


def get_nacl_sdk_path():
  return _NACL_SDK_PATH


def get_nacl_toolchain_root():
  linux_libc = 'linux_arm_newlib' if OPTIONS.is_arm() else 'linux_x86_glibc'
  return os.path.join(_NACL_SDK_PATH, 'toolchain', linux_libc)


def get_nacl_toolchain_libs_path():
  if OPTIONS.is_arm():
    nacl = 'arm-nacl'
    libdir = 'lib'
  else:
    nacl = 'x86_64-nacl'
    libdir = 'lib%d' % OPTIONS.get_target_bitsize()
  return os.path.join(get_nacl_toolchain_root(), nacl, libdir)


def get_nacl_toolchain_path():
  return os.path.join(get_nacl_toolchain_root(), 'bin')


# libppapi_*, libnacl_io, etc.
def _get_nacl_libs_path():
  if OPTIONS.is_arm():
    libc = 'newlib_arm'
  else:
    libc = str('glibc_x86_%d' % OPTIONS.get_target_bitsize())
  return os.path.join(get_nacl_sdk_path(), 'lib', libc, _NACL_SDK_RELEASE)


def get_nacl_tool(tool):
  return os.path.join(build_common.get_arc_root(), _NACL_TOOLS_PATH, tool)


def get_nacl_runner(env=None):
  # We use the NACL_IRT_DEV_FILENAME interface for unit tests.
  args = ['env', 'NACL_DANGEROUS_ENABLE_FILE_ACCESS=1']

  arch = 'arm' if OPTIONS.is_arm() else 'x86_%d' % OPTIONS.get_target_bitsize()
  if OPTIONS.is_arm():
    if not platform_util.is_running_on_remote_host():
      args.extend(get_qemu_arm_args())
    # nacl_helper_bootstrap is required on ARM.
    args.append(get_nacl_tool('nacl_helper_bootstrap_%s' % arch))
  args.append(get_nacl_tool('sel_ldr_%s' % arch))
  if OPTIONS.is_arm():
    # The first two flags are required for sel_ldr to load NaCl modules on ARM.
    args.extend(['--r_debug=0xXXXXXXXXXXXXXXXX',
                 '--reserved_at_zero=0xXXXXXXXXXXXXXXXX'])
    if not platform_util.is_running_on_remote_host():
      # Disable platform qualification of sel_ldr because sel_ldr requires DEP
      # (data execution prevention), but it is not supported on qemu-arm.
      args.append('-Q')
  args.extend(['-a', '-B', get_nacl_tool('irt_core_%s.nexe' % arch)])
  # To run dalvik tests, we need lots of additional environment variables.
  if env:
    args.extend(env)
  # TODO(victorhsieh): remove unnecessary library path below once sel_ldr has
  # them by default.
  library_path = os.path.join(build_common.get_arc_root(),
                              build_common.get_load_library_path())
  args.extend(['-E', 'LD_LIBRARY_PATH=' + library_path,
               '%s/runnable-ld.so' % library_path])
  return args


def get_bare_metal_runner(env=None, use_realpath=False):
  realpath = os.path.realpath if use_realpath else (lambda x: x)
  load_library_path = realpath(build_common.get_load_library_path())
  args = []
  if OPTIONS.is_arm():
    args.extend(get_qemu_arm_args())
  args.extend([realpath(build_common.get_bare_metal_loader()),
               '-E', 'LD_LIBRARY_PATH=' + load_library_path])
  if env:
    args.extend(env)
  args.append(os.path.join(load_library_path, 'runnable-ld.so'))
  return args


def get_qemu_arm_args():
  return [os.path.join(build_common.get_arc_root(), _CANNED_QEMU_ARM),
          '-L', _QEMU_ARM_LD_PATH]


def _get_create_nmf_script():
  return 'src/packaging/create_nmf.py'


def _get_create_nmf():
  return ' '.join([
      # These environ variables are needed for our fork of create_nmf.py.
      'PYTHONPATH=third_party/chromium-ppapi/native_client_sdk/src/tools',
      'NACL_SDK_ROOT=third_party/nacl_sdk/pepper_canary',
      sys.executable,
      _get_create_nmf_script()])


def get_create_nmf_dependencies():
  deps = [_get_create_nmf_script(), 'src/packaging/lib/quote.py']
  objdump = get_tool(OPTIONS.target(), 'objdump')
  if objdump.startswith(get_nacl_toolchain_path()):
    deps.append(objdump)
  return deps


def _get_native_runner(target):
  if target == 'host' or target == 'java':
    return ''
  return 'env LD_LIBRARY_PATH=' + build_common.get_load_library_path(target)


def _get_qemu_runner(target, qemu):
  runner = _get_native_runner(target)
  return runner + ' ' + qemu


def _get_valgrind_runner(target):
  valgrind_lib_path = 'third_party/valgrind/linux_x64/lib/valgrind'
  valgrind_env = ('env VALGRIND_LIB=%s VALGRIND_LIB_INNER=%s' %
                  (valgrind_lib_path, valgrind_lib_path))
  valgrind_path = 'third_party/valgrind/linux_x64/bin/valgrind'
  valgrind_options = [
      '--error-exitcode=1',
      '--trace-children=yes', '--trace-children-skip=env', '--leak-check=full',
      '--suppressions=src/build/valgrind/memcheck/suppressions.txt']
  if target.startswith('bare_metal_'):
    runner = ' '.join(get_bare_metal_runner())
  else:
    runner = _get_native_runner(target)
  return '%s %s %s %s' % (
      valgrind_env, valgrind_path, ' '.join(valgrind_options), runner)


def _get_tool_map():
  android_build_tools_dir = _get_android_build_tools_dir()
  android_sdk_build_tools_dir = get_android_sdk_build_tools_dir()

  return {
      'host': {
          'cxx': os.getenv('HOSTCXX', 'g++'),
          'cc': os.getenv('HOSTCC', 'gcc'),
          'ld': os.getenv('HOSTLD', 'g++'),
          'ar': os.getenv('HOSTAR', 'ar'),
          'nm': os.getenv('HOSTNM', 'nm'),
          'objcopy': os.getenv('HOSTOBJCOPY', 'objcopy'),
          'objdump': os.getenv('HOSTOBJDUMP', 'objdump'),
          'addr2line': os.getenv('HOSTADDR2LINE', 'addr2line'),
          'strip': os.getenv('HOSTSTRIP', 'strip'),
          'runner': _get_native_runner('host'),
          'valgrind_runner': _get_valgrind_runner('host'),
          'gdb': 'gdb',
          'create_nmf': _get_create_nmf(),
          'deps': [],
          'adb': _get_adb_path_for_localhost(),
      },
      'nacl_i686': {
          'cxx': (os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-g++') +
                  ' -m32'),
          'cc': (os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-gcc') +
                 ' -m32'),
          'ld': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-g++'),
          'ar': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-ar'),
          'nm': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-nm'),
          'objcopy': os.path.join(get_nacl_toolchain_path(),
                                  'i686-nacl-objcopy'),
          'objdump': os.path.join(get_nacl_toolchain_path(),
                                  'i686-nacl-objdump'),
          'addr2line': os.path.join(get_nacl_toolchain_path(),
                                    'i686-nacl-addr2line'),
          'strip': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-strip'),
          'runner': ' '.join(get_nacl_runner()),
          # The target does not support Valgrind. Use nacl_runner.
          'valgrind_runner': ' '.join(get_nacl_runner()),
          'ncval': os.path.join(_NACL_TOOLS_PATH, 'ncval'),
          'gdb': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-gdb'),
          'irt': 'nacl_irt_x86_32.nexe',
          'deps': [_NACL_DEPS_PATH],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'tblgen', is_host=True),
      },
      'nacl_x86_64': {
          'cxx': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-g++'),
          'cc': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-gcc'),
          'ld': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-g++'),
          'ar': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-ar'),
          'nm': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-nm'),
          'objcopy': os.path.join(get_nacl_toolchain_path(),
                                  'x86_64-nacl-objcopy'),
          'objdump': os.path.join(get_nacl_toolchain_path(),
                                  'x86_64-nacl-objdump'),
          'addr2line': os.path.join(get_nacl_toolchain_path(),
                                    'x86_64-nacl-addr2line'),
          'strip': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-strip'),
          'runner': ' '.join(get_nacl_runner()),
          # The target does not support Valgrind. Use nacl_runner.
          'valgrind_runner': ' '.join(get_nacl_runner()),
          'ncval': os.path.join(_NACL_TOOLS_PATH, 'ncval'),
          'gdb': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-gdb'),
          'irt': 'nacl_irt_x86_64.nexe',
          'deps': [_NACL_DEPS_PATH],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'tblgen', is_host=True),
      },
      'bare_metal_i686': {
          'cxx': os.getenv('TARGETCXX', 'g++'),
          'cc': os.getenv('TARGETCC', 'gcc'),
          'clangxx': os.path.join(_CLANG_BIN_DIR, 'clang++'),
          'clang': os.path.join(_CLANG_BIN_DIR, 'clang'),
          'ld': os.getenv('TARGETLD', 'g++'),
          'ar': os.getenv('TARGETAR', 'ar'),
          'nm': os.getenv('TARGETNM', 'nm'),
          'objcopy': os.getenv('TARGETOBJCOPY', 'objcopy'),
          'objdump': os.getenv('TARGETOBJDUMP', 'objdump'),
          'addr2line': os.getenv('TARGETADDR2LINE', 'addr2line'),
          'strip': os.getenv('TARGETSTRIP', 'strip'),
          'runner': ' '.join(get_bare_metal_runner()),
          'valgrind_runner': _get_valgrind_runner('bare_metal_i686'),
          'gdb': 'gdb',
          'deps': [],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'tblgen', is_host=True),
      },
      'bare_metal_arm': {
          'cxx': os.getenv('TARGETCXX', ' arm-linux-gnueabihf-g++'),
          'cc': os.getenv('TARGETCC', ' arm-linux-gnueabihf-gcc'),
          'ld': os.getenv('TARGETLD', 'arm-linux-gnueabihf-g++'),
          'ar': os.getenv('TARGETAR', 'arm-linux-gnueabihf-ar'),
          'nm': os.getenv('TARGETNM', 'arm-linux-gnueabihf-nm'),
          'objcopy': os.getenv('TARGETOBJCOPY', 'arm-linux-gnueabihf-objcopy'),
          'objdump': os.getenv('TARGETOBJDUMP', 'arm-linux-gnueabihf-objdump'),
          'addr2line': os.getenv('TARGETADDR2LINE',
                                 'arm-linux-gnueabihf-addr2line'),
          'strip': os.getenv('TARGETSTRIP', 'arm-linux-gnueabihf-strip'),
          'runner': ' '.join(get_bare_metal_runner()),
          # We do not support valgrind on Bare Metal ARM.
          'valgrind_runner': ' '.join(get_bare_metal_runner()),
          'gdb': 'gdb-multiarch',
          'deps': [],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'tblgen', is_host=True),
      },
      'java': {
          'aapt': os.getenv(
              'AAPT', os.path.join(android_sdk_build_tools_dir, 'aapt')),
          'aidl': os.path.join(android_sdk_build_tools_dir, 'aidl'),
          'dx': os.getenv(
              'DX', os.path.join(android_sdk_build_tools_dir, 'dx')),
          'deps': [],
          'dexopt': build_common.get_build_path_for_executable('dexopt',
                                                               is_host=True),
          'java-event-log-tags': os.path.join(android_build_tools_dir,
                                              'java-event-log-tags.py'),
          'jar': os.getenv('JAR', 'jar'),
          'jarjar': os.getenv('JARJAR', os.path.join(
              _DEXMAKER_PATH, 'lib', 'jarjar.jar')),
          'java': os.getenv('JAVA', 'java'),
          'javac': os.getenv('JAVAC', 'javac'),
          'runner': _get_native_runner('java'),
          'zipalign': 'third_party/android-sdk/tools/zipalign',
      },
  }


def get_tool(target, tool, with_cc_wrapper=True):
  if tool == 'asm' or tool == 'asm_with_preprocessing':
    tool = 'cc'
  if tool == 'ld_system_library':
    tool = 'ld'
  command = _get_tool_map()[target][tool]
  if (tool in ['cc', 'cxx', 'clang', 'clangxx'] and
      OPTIONS.cc_wrapper() and with_cc_wrapper):
    command = OPTIONS.cc_wrapper() + ' ' + command
  elif tool == 'irt':
    command = os.path.join(build_common.get_chrome_prebuilt_path(), command)
  return command


def get_gcc_raw_version(target):
  """Returns the gcc version of as a string like "4.8.2"."""

  raw_version = _GCC_RAW_VERSION_CACHE.get(target, 0)
  if raw_version:
    return raw_version
  cc = get_tool(target, 'cc')
  # Should call split() as cc might be prefixed with a wrapper like goma.
  raw_version = subprocess.check_output(cc.split() + ['-dumpversion']).strip()

  _GCC_RAW_VERSION_CACHE[target] = raw_version
  return raw_version


def get_gcc_version(target):
  """Returns the gcc version of as an array of three integers.

  Array of intgers is used so that two versions can be compared easily.
  Example: [4, 8, 0] < [4, 10, 0]. The result is cached so gcc is not run
  multiple times for the same target.
  """

  raw_version = get_gcc_raw_version(target)
  version = [int(x) for x in raw_version.split('.')]
  while len(version) < 3:
    version.append(0)
  assert len(version) == 3

  return version


def has_clang(target, is_host=False):
  if is_host:
    target = 'host'
  tools = _get_tool_map()[target]
  result = 'clang' in tools
  assert result == ('clangxx' in tools)
  return result
