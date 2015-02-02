#!/usr/bin/env python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import build_common
import build_options
import subprocess
import toolchain
from util import gdb_util


def get_nacl_tools():
  """Returns a list of the NaCl tools that are needed to run unit tests."""
  if build_options.OPTIONS.is_bare_metal_build():
    return [build_common.get_bare_metal_loader()]

  bitsize = build_options.OPTIONS.get_target_bitsize()
  arch = 'x86_%d' % bitsize
  nacl_tools = [toolchain.get_nacl_tool('sel_ldr_%s' % arch),
                toolchain.get_nacl_tool('irt_core_%s.nexe' % arch),
                os.path.join(toolchain.get_nacl_toolchain_libs_path(bitsize),
                             'runnable-ld.so')]
  return [os.path.relpath(nacl_tool, build_common.get_arc_root())
          for nacl_tool in nacl_tools]


def get_test_executables(tests):
  """Returns a list of the unit test executables."""
  return [build_common.get_build_path_for_executable(test) for test in tests]


def is_bionic_fundamental_test(test_name):
  return test_name.startswith('bionic_fundamental_')


def get_all_tests():
  """Returns the list of all unittest names."""
  test_info_dir = build_common.get_remote_unittest_info_path('')
  test_info_files = os.listdir(test_info_dir)
  tests = set()
  for test_info_file in test_info_files:
    # test info file name is something like bionic_test.1.json.
    m = re.match(r'(.+)\.[0-9]+\.json', test_info_file)
    if not m:
      continue
    tests.add(m.group(1))
  return sorted(tests)


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
  subprocess.call([
      gdb,
      '-ex', 'target remote :4014',
      '-ex', 'nacl-irt %s' % irt,
      # The Bionic does not pass a fullpath of a shared object to the
      # debugger. Fixing this issue by modifying the Bionic loader
      # will need a bunch of ARC MOD. We work-around the issue by
      # passing the path of shared objects here.
      #
      # GDB uses NaCl Manifest file for arc.nexe so we do not need
      # this for launch_chrome.
      '-ex', 'set solib-search-path %s' %
      build_common.get_load_library_path(),
      '-ex',
      'echo \n*** Type \'continue\' or \'c\' to start debugging ***\n\n',
      runnable_ld])
  sel_ldr_proc.kill()


def _get_gdb_command_to_inject_bare_metal_gdb_py(main_binary):
  bare_metal_gdb_init_args = map(gdb_util.to_python_string_literal, [
      build_common.get_bare_metal_loader(),
      main_binary,
      build_common.get_load_library_path(),
  ])

  # This GDB command sequence initializes the Python script for GDB to
  # load shared objects in Bare Metal mode properly.
  return ['-ex', 'python sys.path.insert(0, "src/build")',
          '-ex', 'python from util import bare_metal_gdb',
          '-ex', 'python bare_metal_gdb.init_for_unittest(%s)' % (
              ', '.join(bare_metal_gdb_init_args))]


def _run_gdb_for_bare_metal_arm(runner_args, test_args):
  gdb = toolchain.get_tool(build_options.OPTIONS.target(), 'gdb')
  bare_metal_loader_index = runner_args.index(
      build_common.get_bare_metal_loader())

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
           build_common.get_bare_metal_loader()])
  subprocess.call(args)

  qemu_arm_proc.kill()


def _run_gdb_for_bare_metal(runner_args, test_args):
  gdb = toolchain.get_tool(build_options.OPTIONS.target(), 'gdb')
  bare_metal_loader_index = runner_args.index(
      build_common.get_bare_metal_loader())

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
