# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import re
import subprocess

from src.build import build_common
from src.build import build_options
from src.build import toolchain
from src.build.util import file_util
from src.build.util import gdb_util


def get_nacl_tools():
  """Returns a list of the NaCl tools that are needed to run unit tests."""
  if build_options.OPTIONS.is_bare_metal_build():
    return [toolchain.get_nonsfi_loader()]

  bitsize = build_options.OPTIONS.get_target_bitsize()
  arch = 'x86_%d' % bitsize
  nacl_tools = [toolchain.get_nacl_tool('sel_ldr_%s' % arch),
                toolchain.get_nacl_tool('irt_core_%s.nexe' % arch),
                os.path.join(toolchain.get_nacl_toolchain_libs_path(bitsize),
                             'runnable-ld.so')]
  return [os.path.relpath(nacl_tool, build_common.get_arc_root())
          for nacl_tool in nacl_tools]


def _get_test_executable(test):
  # Although <test>.2.json, <test>.3.json, .. may also exist, they use the same
  # binary, so read <test>.1.json as a representative.
  unittest_info_path = build_common.get_unittest_info_path('%s.1.json' % test)
  with open(unittest_info_path) as f:
    return json.load(f)['variables']['in']


def get_test_executables(tests):
  """Returns a list of the unit test executables."""
  # Remove duplicates because separate tests may use the same executable.
  return list(set(_get_test_executable(test) for test in tests))


def is_bionic_fundamental_test(test_name):
  return test_name.startswith('bionic_fundamental.')


def get_all_tests():
  """Returns the list of all unittest names."""
  test_info_files = file_util.read_metadata_file(
      build_common.get_all_unittest_info_path())
  tests = set()
  for test_info_file in test_info_files:
    # The basename of |test_info_file| is something like bionic_test.1.json.
    m = re.match(r'(.+)\.[0-9]+\.json', os.path.basename(test_info_file))
    if not m:
      continue
    tests.add(m.group(1))
  return sorted(tests)


def build_gtest_options(enabled_tests, disabled_tests):
  """Returns gtest options based on |enabled_tests| and |disabled_tests|."""
  gtest_options = ['--gtest_color=yes']
  if enabled_tests or disabled_tests:
    enabled_tests = build_common.as_list(enabled_tests)
    disabled_tests = build_common.as_list(disabled_tests)
    minus = '-' if disabled_tests else ''
    gtest_filter = ' --gtest_filter=%s%s%s' % (
        ':'.join(enabled_tests), minus, ':'.join(disabled_tests))
    gtest_options.append(gtest_filter)
  return ' '.join(gtest_options)


def _run_gdb_for_nacl(args, test_args):
  runnable_ld = args[-1]
  assert 'runnable-ld.so' in runnable_ld
  # Insert -g flag before -a to let sel_ldr wait for GDB.
  a_index = args.index('-a')
  assert 'sel_ldr' in args[a_index - 1]
  args.insert(a_index, '-g')
  args.extend(test_args)
  # The child process call setsid(2) to create a new session so that
  # sel_ldr will not die by Ctrl-C either. Note that ignoring SIGINT
  # does not work for sel_ldr, because sel_ldr will override the
  # setting.
  sel_ldr_proc = subprocess.Popen(args, stderr=subprocess.STDOUT,
                                  preexec_fn=os.setsid)

  gdb = toolchain.get_tool(build_options.OPTIONS.target(), 'gdb')
  irt = toolchain.get_nacl_irt_core(build_options.OPTIONS.get_target_bitsize())

  # The Bionic loader only provides the base name of each loaded binary in L
  # for 32-bit platforms due to a compatibility issue.
  # ARC keeps the behavior and provides full path information for debugging
  # explicitly. See SEARCH_NAME() in mods/android/bionic/linker/linker.cpp.
  # DSOs are covered by build_common.get_load_library_path(), but full path
  # information for test main binary should be specified separately.
  #
  # Note GDB uses NaCl manifest for arc.nexe so we do not need the library
  # search paths for launch_chrome.
  solib_paths = [build_common.get_load_library_path_for_test(),
                 build_common.get_load_library_path(),
                 os.path.dirname(test_args[0])]

  args = [
      gdb,
      '-ex', 'target remote :4014',
      '-ex', 'nacl-irt %s' % irt,
      # The Bionic does not pass a fullpath of a shared object to the
      # debugger. Fixing this issue by modifying the Bionic loader
      # will need a bunch of ARC MOD. We work-around the issue by
      # passing the path of shared objects here.
      '-ex', 'set solib-search-path %s' % ':'.join(solib_paths),
      '-ex',
      'echo \n*** Type \'continue\' or \'c\' to start debugging ***\n\n',
      runnable_ld]
  subprocess.call(args)
  sel_ldr_proc.kill()


def _get_gdb_command_to_inject_bare_metal_gdb_py(main_binary):
  return (
      gdb_util.get_gdb_python_init_args() +
      gdb_util.get_gdb_python_script_init_args(
          'bare_metal_support_for_unittest',
          nonsfi_loader=toolchain.get_nonsfi_loader(),
          test_binary=main_binary,
          library_path=build_common.get_load_library_path(),
          runnable_ld_path=build_common.get_bionic_runnable_ld_so()))


def _run_gdb_for_bare_metal_arm(runner_args, test_args):
  gdb = toolchain.get_tool(build_options.OPTIONS.target(), 'gdb')
  bare_metal_loader_index = runner_args.index(
      toolchain.get_nonsfi_loader())

  # For Bare Metal ARM, we use qemu's remote debugging interface.
  args = (runner_args[:bare_metal_loader_index] +
          ['-g', '4014'] +
          runner_args[bare_metal_loader_index:] + test_args)
  # Create a new session using setsid. See the comment in
  # _run_gdb_for_nacl for detail.
  qemu_arm_proc = subprocess.Popen(args, stderr=subprocess.STDOUT,
                                   preexec_fn=os.setsid)

  gdb_command = _get_gdb_command_to_inject_bare_metal_gdb_py(test_args[0])

  args = ([gdb, '-ex', 'target remote :4014'] +
          gdb_command +
          gdb_util.get_args_for_stlport_pretty_printers() +
          ['-ex',
           'echo \n*** Type \'continue\' or \'c\' to start debugging ***\n\n',
           toolchain.get_nonsfi_loader()])
  subprocess.call(args)

  qemu_arm_proc.kill()


def _run_gdb_for_bare_metal(runner_args, test_args):
  gdb = toolchain.get_tool(build_options.OPTIONS.target(), 'gdb')
  bare_metal_loader_index = runner_args.index(
      toolchain.get_nonsfi_loader())

  gdb_command = _get_gdb_command_to_inject_bare_metal_gdb_py(test_args[0])

  args = (runner_args[:bare_metal_loader_index] +
          [gdb] +
          gdb_command +
          gdb_util.get_args_for_stlport_pretty_printers() +
          ['-ex',
           'echo \n*** Type \'run\' or \'r\' to start debugging ***\n\n',
           '--args'] +
          runner_args[bare_metal_loader_index:] +
          test_args)
  subprocess.call(args)


def run_gdb(args):
  # Find the index of runnable-ld.so to split the command line to two
  # parts. The first part consists of the supervisor binary, its
  # arguments, and the Binoic loader. The second part consists of the
  # test binary and its arguments (e.g., --gtest_filter).
  runnable_ld_index = 0
  while 'runnable-ld.so' not in args[runnable_ld_index]:
    runnable_ld_index += 1
  runner_args = args[:runnable_ld_index + 1]
  test_args = args[runnable_ld_index + 1:]

  if build_options.OPTIONS.is_nacl_build():
    _run_gdb_for_nacl(runner_args, test_args)
  elif build_options.OPTIONS.is_bare_metal_build():
    if build_options.OPTIONS.is_arm():
      _run_gdb_for_bare_metal_arm(runner_args, test_args)
    else:
      _run_gdb_for_bare_metal(runner_args, test_args)
