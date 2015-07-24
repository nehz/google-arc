# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
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
_PNACL_BIN_PATH = os.path.join(_NACL_SDK_PATH, 'toolchain/linux_pnacl/bin')
_PNACL_CLANG_VERSIONS_PATH = \
    os.path.join(_NACL_SDK_PATH, 'toolchain/linux_pnacl/lib/clang')
# Don't calculate _PNACL_INCLUDE_DIR here (since it needs filesystem access),
# do that in get_pnacl_include_dir() instead.
_PNACL_INCLUDE_DIR = None
# TODO(crbug.com/247242): support --naclsdktype={debug,release}
_NACL_SDK_RELEASE = 'Release'  # alternative: Debug
_QEMU_ARM_LD_PATH = '/usr/arm-linux-gnueabihf'
_CLANG_DIR = 'third_party/android/prebuilts/clang/linux-x86/host/3.6'
_CLANG_BIN_DIR = os.path.join(_CLANG_DIR, 'bin')
_CLANG_INCLUDE_DIR = os.path.join(_CLANG_DIR, 'lib', 'clang', '3.6', 'include')

# Used in get_gcc_raw_version().
_GCC_RAW_VERSION_CACHE = {}
_CLANG_RAW_VERSION_CACHE = {}

# The pinned version of the Android SDK's build tools is used for ARC build.
_ANDROID_SDK_BUILD_TOOLS_PINNED_VERSION = '21.1.2'


def _get_android_build_tools_dir():
  return os.path.join('third_party', 'android', 'build', 'tools')


def get_android_api_level():
  """Returns the pinned version of the Android API."""
  return int(_ANDROID_SDK_BUILD_TOOLS_PINNED_VERSION.split('.')[0])


def get_framework_aidl():
  """Finds framework.aidl."""
  api_level = get_android_api_level()
  out = os.path.join(build_common.get_android_sdk_path(), 'platforms',
                     'android-%d' % api_level, 'framework.aidl')
  assert os.path.isfile(out), 'framework.aidl not found at: ' + out
  return out


def get_android_sdk_build_tools_pinned_version():
  """Returns the pinned version of the Android SDK's build tools."""
  return _ANDROID_SDK_BUILD_TOOLS_PINNED_VERSION


def get_android_sdk_build_tools_dir():
  return os.path.join('third_party', 'android-sdk', 'build-tools',
                      get_android_sdk_build_tools_pinned_version())


def get_clang_include_dir():
  return _CLANG_INCLUDE_DIR


def get_adb_path_for_chromeos(relative=True):
  """Returns the directory that contains the adb executable for Chrome OS."""

  if platform_util.is_running_on_chromeos():
    # The adb binary is copied to a directory whose filesystem is mounted
    # without noexec mount options on Chrome OS.
    root = build_common.get_chromeos_arc_root_without_noexec()
  else:
    root = build_common.get_arc_root()

  # Chrome OS based on linux-i686 is not supported.
  target = 'linux-arm' if OPTIONS.is_arm() else 'linux-x86_64'
  path = os.path.join('out/adb', target, 'adb')
  if relative:
    return path
  return os.path.join(root, path)


def _get_adb_path_for_localhost():
  root = os.path.join(build_common.get_arc_root(), 'out/adb')
  if platform_util.is_running_on_mac():
    return os.path.join(root, 'mac-x86_64/adb')
  elif platform_util.is_running_on_cygwin():
    return os.path.join(root, 'win-x86_64/adb.exe')
  elif platform_util.is_running_on_chromeos():
    return get_adb_path_for_chromeos(relative=False)
  else:
    # For Linux desktop.
    return 'third_party/android-sdk/platform-tools/adb'


def get_nacl_sdk_path():
  return _NACL_SDK_PATH


def get_nacl_toolchain_root():
  return os.path.join(_NACL_SDK_PATH, 'toolchain/linux_x86_glibc')


def get_nacl_toolchain_libs_path(bitsize):
  return os.path.join(get_nacl_toolchain_root(), 'x86_64-nacl/lib%d' % bitsize)


def get_nacl_toolchain_path():
  return os.path.join(get_nacl_toolchain_root(), 'bin')


def get_nacl_tool(tool):
  return os.path.join(_NACL_TOOLS_PATH, tool)


def get_nacl_irt_core(bitsize):
  return get_nacl_tool('irt_core_x86_%d.nexe' % bitsize)


def _find_pnacl_include_dir():
  versions = os.listdir(_PNACL_CLANG_VERSIONS_PATH)
  assert versions, 'No clang versions found under %s' % \
      _PNACL_CLANG_VERSIONS_PATH
  # Get the largest version, taking care to order '10' above '2'
  # by converting the string into an array of integers.
  version = max(versions, key=lambda v: [int(x) for x in v.split('.')])
  return os.path.join(_PNACL_CLANG_VERSIONS_PATH, version, 'include')


def get_pnacl_include_dir():
  global _PNACL_INCLUDE_DIR
  # Recalculate _PNACL_INCLUDE_DIR if needed
  if _PNACL_INCLUDE_DIR is None:
    _PNACL_INCLUDE_DIR = _find_pnacl_include_dir()
  return _PNACL_INCLUDE_DIR


def _get_runner_env_vars(use_test_library=True,
                         extra_library_paths=None, extra_envs=None):
  extra_library_paths = extra_library_paths or []
  extra_envs = extra_envs or {}
  load_library_paths = []
  if use_test_library:
    load_library_paths.append(build_common.get_load_library_path_for_test())
  load_library_paths.append(build_common.get_load_library_path())
  envs = {
      'LD_LIBRARY_PATH': ':'.join(load_library_paths + extra_library_paths)
  }
  if extra_envs:
    conflict_keys = envs.viewkeys() & extra_envs.viewkeys()
    assert not conflict_keys, ('The following keys are duplicated: %s' %
                               sorted(conflict_keys))
    envs.update(extra_envs)
  return envs


def get_nacl_runner(bitsize, bin_dir=None, use_test_library=True,
                    extra_library_paths=None, extra_envs=None):
  extra_library_paths = extra_library_paths or []
  extra_envs = extra_envs or {}
  # We use the NACL_IRT_DEV_FILENAME interface for unit tests.
  args = ['env', 'NACL_DANGEROUS_ENABLE_FILE_ACCESS=1']

  arch = 'x86_%d' % bitsize
  sel_ldr = get_nacl_tool('sel_ldr_%s' % arch)
  irt_core = get_nacl_irt_core(bitsize)
  if bin_dir:
    sel_ldr = os.path.join(bin_dir, sel_ldr)
    irt_core = os.path.join(bin_dir, irt_core)
  args.extend([sel_ldr, '-a', '-B', irt_core])
  library_path = build_common.get_load_library_path()
  library_path_for_test = build_common.get_load_library_path_for_test()
  runnable_ld = os.path.join(library_path, 'runnable-ld.so')
  if use_test_library:
    library_path = ':'.join([library_path_for_test, library_path])
  args.extend(['-E', 'LD_LIBRARY_PATH=' +
               ':'.join([library_path] + extra_library_paths)])
  for key, value in extra_envs.iteritems():
    args.extend(['-E', '%s=%s' % (key, value)])
  args.append(runnable_ld)
  return args


def get_nonsfi_loader(nacl_arch=None):
  if nacl_arch is None:
    nacl_arch = 'arm' if OPTIONS.is_arm() else 'x86_32'
  return os.path.join(_NACL_TOOLS_PATH, 'nonsfi_loader_' + nacl_arch)


def get_bare_metal_runner(nacl_arch=None, use_qemu_arm=False, bin_dir=None,
                          use_test_library=True,
                          extra_library_paths=None, extra_envs=None,
                          with_env_cmd=True):
  args = []
  if with_env_cmd:
    args.append('env')
    envs = _get_runner_env_vars(use_test_library,
                                extra_library_paths, extra_envs)
    args.extend('%s=%s' % item for item in envs.iteritems())
  if use_qemu_arm:
    args.extend(get_qemu_arm_args())
  loader = get_nonsfi_loader(nacl_arch)
  if bin_dir:
    loader = os.path.join(bin_dir, loader)
  args.append(loader)
  args.append(os.path.join(build_common.get_load_library_path(),
                           'runnable-ld.so'))
  return args


def get_target_runner(bin_dir=None, extra_library_paths=None, extra_envs=None):
  if OPTIONS.is_bare_metal_build():
    return get_bare_metal_runner(bin_dir=bin_dir,
                                 extra_library_paths=extra_library_paths,
                                 extra_envs=extra_envs)
  else:
    return get_nacl_runner(OPTIONS.get_target_bitsize(), bin_dir=bin_dir,
                           extra_library_paths=extra_library_paths,
                           extra_envs=extra_envs)


def get_qemu_arm_args():
  return [_CANNED_QEMU_ARM, '-L', _QEMU_ARM_LD_PATH]


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


def _get_valgrind_runner(target, nacl_arch=None, use_test_library=True):
  valgrind_lib_path = 'third_party/valgrind/linux_x64/lib/valgrind'
  env_vars = _get_runner_env_vars(extra_envs={
      'VALGRIND_LIB': valgrind_lib_path,
      'VALGRIND_LIB_INNER': valgrind_lib_path,
  })
  valgrind_env = 'env ' + ' '.join(
      '%s=%s' % item for item in env_vars.iteritems())
  valgrind_path = 'third_party/valgrind/linux_x64/bin/valgrind'
  valgrind_options = [
      '--error-exitcode=1', '--num-callers=50', '--gen-suppressions=all',
      '--trace-children=yes', '--trace-children-skip=env', '--leak-check=full',
      '--suppressions=src/build/valgrind/memcheck/suppressions.txt']
  if target.startswith('bare_metal_'):
    runner = ' '.join(get_bare_metal_runner(nacl_arch, with_env_cmd=False,
                                            use_test_library=use_test_library))
  else:
    runner = _get_native_runner(target)
  return '%s %s %s %s' % (
      valgrind_env, valgrind_path, ' '.join(valgrind_options), runner)


def _get_java_command(command):
  # First, look at environment variable. E.g. JAR for jar, JAVAC for javac.
  env_var = os.getenv(command.upper())
  if env_var:
    return env_var

  # Then, if java_dir is set, look at its bin/ directory.
  java_dir = OPTIONS.java_dir()
  if java_dir:
    bin_path = os.path.join(java_dir, 'bin', command)
    if os.path.exists(bin_path):
      return bin_path
  return command


def _get_tool_map():
  android_build_tools_dir = _get_android_build_tools_dir()
  android_sdk_build_tools_dir = get_android_sdk_build_tools_dir()

  return {
      'host': {
          'cxx': os.getenv('HOSTCXX', 'g++'),
          'cc': os.getenv('HOSTCC', 'gcc'),
          'asm': os.getenv('HOSTCC', 'gcc'),
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
          'clangxx': os.path.join(_CLANG_BIN_DIR, 'clang++'),
          'clang': os.path.join(_CLANG_BIN_DIR, 'clang'),
      },
      'nacl_i686': {
          'cxx': (os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-g++') +
                  ' -m32'),
          'cc': (os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-gcc') +
                 ' -m32'),
          'asm': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-clang'),
          'ld': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-g++'),
          'ar': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-ar'),
          'nm': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-nm'),
          'objcopy': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-objcopy'),
          'objdump': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-objdump'),
          'addr2line': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-addr2line'),
          'strip': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-strip'),
          'runner': ' '.join(get_nacl_runner(32)),
          'runner_without_test_library': ' '.join(
              get_nacl_runner(32, use_test_library=False)),
          # The target does not support Valgrind. Use nacl_runner.
          'valgrind_runner': ' '.join(get_nacl_runner(32)),
          'valgrind_runner_without_test_library': ' '.join(
              get_nacl_runner(32, use_test_library=False)),
          'ncval': os.path.join(_NACL_TOOLS_PATH, 'ncval'),
          'gdb': os.path.join(get_nacl_toolchain_path(), 'i686-nacl-gdb'),
          'irt': 'nacl_irt_x86_32.nexe',
          'deps': [_NACL_DEPS_PATH],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'llvm-tblgen', is_host=True),
          'clangxx': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-clang++'),
          'clang': os.path.join(_PNACL_BIN_PATH, 'i686-nacl-clang'),
      },
      'nacl_x86_64': {
          'cxx': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-g++'),
          'cc': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-gcc'),
          'ld': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-g++'),
          'asm': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-clang'),
          'ar': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-ar'),
          'nm': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-nm'),
          'objcopy': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-objcopy'),
          'objdump': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-objdump'),
          'addr2line': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-addr2line'),
          'strip': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-strip'),
          'runner': ' '.join(get_nacl_runner(64)),
          'runner_without_test_library': ' '.join(
              get_nacl_runner(64, use_test_library=False)),
          # The target does not support Valgrind. Use nacl_runner.
          'valgrind_runner': ' '.join(get_nacl_runner(64)),
          'valgrind_runner_without_test_library': ' '.join(
              get_nacl_runner(64, use_test_library=False)),
          'ncval': os.path.join(_NACL_TOOLS_PATH, 'ncval'),
          'gdb': os.path.join(get_nacl_toolchain_path(), 'x86_64-nacl-gdb'),
          'irt': 'nacl_irt_x86_64.nexe',
          'deps': [_NACL_DEPS_PATH],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'llvm-tblgen', is_host=True),
          'clangxx': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-clang++'),
          'clang': os.path.join(_PNACL_BIN_PATH, 'x86_64-nacl-clang'),
      },
      'bare_metal_i686': {
          'cxx': os.getenv('TARGETCXX', 'g++-4.8'),
          'cc': os.getenv('TARGETCC', 'gcc-4.8'),
          'asm': os.getenv('TARGETCC', 'gcc-4.8'),
          'clangxx': os.path.join(_CLANG_BIN_DIR, 'clang++'),
          'clang': os.path.join(_CLANG_BIN_DIR, 'clang'),
          'ld': os.getenv('TARGETLD', 'g++-4.8'),
          'ar': os.getenv('TARGETAR', 'ar'),
          'nm': os.getenv('TARGETNM', 'nm'),
          'objcopy': os.getenv('TARGETOBJCOPY', 'objcopy'),
          'objdump': os.getenv('TARGETOBJDUMP', 'objdump'),
          'addr2line': os.getenv('TARGETADDR2LINE', 'addr2line'),
          'strip': os.getenv('TARGETSTRIP', 'strip'),
          'runner': ' '.join(get_bare_metal_runner('x86_32')),
          'runner_without_test_library': ' '.join(
              get_bare_metal_runner('x86_32', use_test_library=False)),
          'valgrind_runner': _get_valgrind_runner('bare_metal_i686',
                                                  nacl_arch='x86_32'),
          'valgrind_runner_without_test_library': _get_valgrind_runner(
              'bare_metal_i686', use_test_library=False, nacl_arch='x86_32'),
          'gdb': 'gdb',
          'deps': [],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'llvm-tblgen', is_host=True),
      },
      'bare_metal_arm': {
          'cxx': os.getenv('TARGETCXX', ' arm-linux-gnueabihf-g++'),
          'cc': os.getenv('TARGETCC', ' arm-linux-gnueabihf-gcc'),
          'asm': os.getenv('TARGETCC', ' arm-linux-gnueabihf-gcc'),
          'clangxx': os.path.join(_CLANG_BIN_DIR, 'clang++'),
          'clang': os.path.join(_CLANG_BIN_DIR, 'clang'),
          'clang.ld': os.path.join(_CLANG_BIN_DIR, 'clang'),
          'ld': os.getenv('TARGETLD', 'arm-linux-gnueabihf-g++'),
          'ar': os.getenv('TARGETAR', 'arm-linux-gnueabihf-ar'),
          'nm': os.getenv('TARGETNM', 'arm-linux-gnueabihf-nm'),
          'objcopy': os.getenv('TARGETOBJCOPY', 'arm-linux-gnueabihf-objcopy'),
          'objdump': os.getenv('TARGETOBJDUMP', 'arm-linux-gnueabihf-objdump'),
          'addr2line': os.getenv('TARGETADDR2LINE',
                                 'arm-linux-gnueabihf-addr2line'),
          'strip': os.getenv('TARGETSTRIP', 'arm-linux-gnueabihf-strip'),
          'runner': ' '.join(get_bare_metal_runner('arm', use_qemu_arm=True)),
          'runner_without_test_library': ' '.join(
              get_bare_metal_runner('arm', use_qemu_arm=True,
                                    use_test_library=False)),
          # We do not support valgrind on Bare Metal ARM.
          'valgrind_runner': ' '.join(get_bare_metal_runner(
              'arm', use_qemu_arm=True)),
          'valgrind_runner_without_test_library': ' '.join(
              get_bare_metal_runner(use_qemu_arm=True, use_test_library=False)),
          'gdb': build_common.get_gdb_multiarch_path(),
          'deps': [],
          'llvm_tblgen': build_common.get_build_path_for_executable(
              'llvm-tblgen', is_host=True),
      },
      'java': {
          'aapt': os.getenv(
              'AAPT', os.path.join(android_sdk_build_tools_dir, 'aapt')),
          'aidl': os.path.join(android_sdk_build_tools_dir, 'aidl'),
          'dx': os.getenv(
              'DX', os.path.join(android_sdk_build_tools_dir, 'dx')),
          'deps': [],
          'dex2oat': build_common.get_build_path_for_executable(
              'dex2oatd' if OPTIONS.is_debug_code_enabled() else 'dex2oat',
              is_host=True),
          'dexdump': os.path.join(android_sdk_build_tools_dir, 'dexdump'),
          'java-event-log-tags': os.path.join(android_build_tools_dir,
                                              'java-event-log-tags.py'),
          'jar': _get_java_command('jar'),
          'jarjar': os.getenv('JARJAR', os.path.join(
              _DEXMAKER_PATH, 'lib', 'jarjar.jar')),
          'java': _get_java_command('java'),
          'javac': _get_java_command('javac'),
          'runner': _get_native_runner('java'),
          'zipalign': os.path.join(android_sdk_build_tools_dir, 'zipalign'),
      },
  }


def get_tool(target, tool, with_cc_wrapper=True):
  tool = {
      'asm_with_preprocessing': 'asm',
      'clang.ld': 'clang',
      'clang.ld_system_library': 'clang',
      'ld_system_library': 'ld',
  }.get(tool, tool)
  command = _get_tool_map()[target][tool]
  if (tool in ['cc', 'cxx', 'clang', 'clangxx'] and
      OPTIONS.cc_wrapper() and with_cc_wrapper):
    command = OPTIONS.cc_wrapper() + ' ' + command
  return command


def get_gcc_raw_version(target):
  """Returns the gcc version of as a string like "4.8.2"."""

  raw_version = _GCC_RAW_VERSION_CACHE.get(target, 0)
  if raw_version:
    return raw_version
  cc = get_tool(target, 'cc', with_cc_wrapper=False)
  # Should call split() as cc might be prefixed with a wrapper like goma.
  raw_version = subprocess.check_output(cc.split() + ['-dumpversion']).strip()

  _GCC_RAW_VERSION_CACHE[target] = raw_version
  return raw_version


def get_gcc_version(target):
  """Returns the gcc version as an array of three integers.

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


def _get_clang_raw_version(target):
  raw_version = _CLANG_RAW_VERSION_CACHE.get(target)
  if raw_version:
    return raw_version
  clang = get_tool(target, 'clang', with_cc_wrapper=False)
  # Should call split() as cc might be prefixed with a wrapper like goma.
  raw_version = subprocess.check_output(clang.split() + ['--version'])

  _CLANG_RAW_VERSION_CACHE[target] = raw_version
  return raw_version


def get_clang_version(target):
  """Returns the clang version as an array of three integers.

  See also get_gcc_version.
  """

  raw_version = _get_clang_raw_version(target)
  match = re.search('clang version ([0-9.]+)', raw_version)
  assert match is not None
  version = [int(x) for x in match.group(1).split('.')]
  while len(version) < 3:
    version.append(0)
  return version
