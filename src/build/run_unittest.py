#!/usr/bin/env python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This is a script for running a unit tests locally or remotely on a Chrome OS
# device.
#
# Usage:
# Run unit tests locally:
# $ src/build/run_unittest.py test0 test1 ...
#
# Run unit tests remotely on a Chrome OS device.
# $ src/build/run_unittest.py test0 test1 ... --remote=<REMOTE>
#
# When --remote is specified, the test binaries and other necessary files are
# copied to the remote Chrome OS device. The the unit tests need to be built
# before running this script.
#
# Some examples:
#
# To see the list of unittest binaries:
#
# $ src/build/run_unittest.py --list
#
# To debug a unittest with GDB:
#
# $ src/build/run_unittest.py bionic_test --gdb
#
# To run a unittest on a Chromebook:
#
# $ src/build/run_unittest.py posix_translation_test --remote=yoshi
#
# To see the list of test cases in a unittest binary:
#
# $ src/build/run_unittest.py libndk_test --gtest-list-tests
#
# To run the unittest with a GTEST_FILTER:
#
# $ src/build/run_unittest.py libndk_test --gtest-filter 'NdkTest.Opt*'
#

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import string

sys.path.insert(0, 'src/build')
import build_common
import build_options
import toolchain
from util import platform_util
from util import remote_executor
from util.test import unittest_util


def _read_test_info(filename):
  test_info_path = build_common.get_unittest_info_path(filename)
  if not os.path.exists(test_info_path):
    return None
  with open(test_info_path, 'r') as f:
    return json.load(f)


def _construct_command(test_info, gtest_filter, gtest_list_tests):
  variables = test_info['variables'].copy()
  variables.setdefault('argv', '')
  variables.setdefault('qemu_arm', '')

  if platform_util.is_running_on_chromeos():
    # On ChromeOS, binaries in directories mounted with noexec options are
    # copied to the corresponding directories mounted with exec option.
    # Change runner to use the binaries under the directory mounted with exec
    # option.
    # Also do not use qemu_arm when running on ARM Chromebook.
    arc_root_without_noexec = \
        build_common.get_chromeos_arc_root_without_noexec()
    if build_options.OPTIONS.is_bare_metal_build():
      variables['runner'] = ' '.join(
          toolchain.get_bare_metal_runner(bin_dir=arc_root_without_noexec))
      variables['runner_without_test_library'] = ' '.join(
          toolchain.get_bare_metal_runner(bin_dir=arc_root_without_noexec,
                                          use_test_library=False))
      if build_options.OPTIONS.is_arm():
        variables['qemu_arm'] = ''
        # Update --gtest_filter to re-enable the tests disabled only on qemu.
        if variables.get('qemu_disabled_tests'):
          variables['gtest_options'] = unittest_util.build_gtest_options(
              variables.get('enabled_tests'), variables.get('disabled_tests'))
    else:
      variables['runner'] = ' '.join(
          toolchain.get_nacl_runner(
              build_options.OPTIONS.get_target_bitsize(),
              bin_dir=arc_root_without_noexec))
      variables['runner_without_test_library'] = ' '.join(
          toolchain.get_nacl_runner(
              build_options.OPTIONS.get_target_bitsize(),
              bin_dir=arc_root_without_noexec,
              use_test_library=False))
    build_dir = build_common.get_build_dir()
    # Use test binary in the directory mounted without noexec.
    variables['in'] = variables['in'].replace(
        build_dir, os.path.join(arc_root_without_noexec, build_dir))
  else:
    if build_options.OPTIONS.is_arm():
      # Pass environment variables by -E flag for qemu-arm instead of
      # "env" command.
      # TODO(hamaji): This and the is_running_on_chromeos() case above
      # are both hacky. We probably want to construct the command to
      # run a unittest here based on the info in variables, and remove
      # test_info['command'].
      qemu_arm = variables['qemu_arm'].split(' ')
      if '$qemu_arm' in test_info['command']:
        runner = variables['runner'].split(' ')
        assert runner[0] == 'env'
        runner.pop(0)
        qemu_arm.append('-E')
        while '=' in runner[0]:
          qemu_arm.append(runner[0])
          runner.pop(0)
        variables['qemu_arm'] = ' '.join(qemu_arm)
        variables['runner'] = ' '.join(runner)

  if gtest_filter:
    variables['gtest_options'] = '--gtest_filter=' + gtest_filter
  if gtest_list_tests:
    variables['gtest_options'] = '--gtest_list_tests'
  # Test is run as a command to build a test results file.
  command_template = string.Template(test_info['command'])
  return command_template.substitute(variables)


def _run_unittest(tests, verbose, use_gdb, gtest_filter, gtest_list_tests):
  """Runs the unit tests specified in test_info.

  This can run unit tests without depending on ninja and is mainly used on the
  remote device where ninja is not installed.
  """
  failed_tests = []
  unfound_tests = []
  for test in tests:
    index = 1
    while True:
      test_info = _read_test_info('%s.%d.json' % (test, index))
      if not test_info:
        # The format of test info file is [test name].[index].json, where index
        # is one of consecutive numbers from 1. If the test info file for index
        # 1 is not found, that means the corresponding test does not exist.
        if index == 1:
          unfound_tests.append(test)
        break
      command = _construct_command(test_info, gtest_filter, gtest_list_tests)
      if verbose:
        print 'Running:', command
      args = shlex.split(command)
      if use_gdb:
        print args
        unittest_util.run_gdb(args)
      else:
        returncode = subprocess.call(args)
        if returncode != 0:
          print 'FAILED: ' + test
          failed_tests.append('%s.%d' % (test, index))
      index += 1
  if unfound_tests:
    print 'The following tests were not found: \n' + '\n'.join(unfound_tests)
  if failed_tests:
    print 'The following tests failed: \n' + '\n'.join(failed_tests)
  if unfound_tests or failed_tests:
    return -1
  return 0


def _check_args(parsed_args):
  if parsed_args.gdb:
    if len(parsed_args.tests) != 1:
      raise Exception('You should specify only one test with --gdb.')
    # TODO(crbug.com/439369): Support --gdb with --remote.
    if parsed_args.remote:
      raise Exception('Setting both --gdb and --remote is not supported yet.')
  if (parsed_args.remote and
      filter(unittest_util.is_bionic_fundamental_test, parsed_args.tests)):
    raise Exception('You cannot use --remote for bionic_fundamental_*_test')


def main():
  build_options.OPTIONS.parse_configure_file()

  description = 'Runs unit tests, verifying they pass.'
  parser = argparse.ArgumentParser(description=description)
  parser.add_argument('tests', metavar='test', nargs='*',
                      help=('The name of a unit test, such as libcommon_test.'
                            'If tests argument is not given, all unit tests '
                            'are run.'))
  parser.add_argument('--gdb', action='store_true', default=False,
                      help='Run the test under GDB.')
  parser.add_argument('-f', '--gtest-filter',
                      help='A \':\' separated list of googletest test filters')
  parser.add_argument('--gtest-list-tests', action='store_true', default=False,
                      help='Lists the test names to run')
  parser.add_argument('--list', action='store_true',
                      help='List the names of tests.')
  parser.add_argument('-v', '--verbose', action='store_true',
                      default=False, dest='verbose',
                      help=('Show verbose output, including commands run'))
  remote_executor.add_remote_arguments(parser)
  parsed_args = parser.parse_args()
  remote_executor.maybe_detect_remote_host_type(parsed_args)

  if parsed_args.list:
    for test_name in unittest_util.get_all_tests():
      print test_name
    return 0

  _check_args(parsed_args)

  if not parsed_args.tests:
    parsed_args.tests = unittest_util.get_all_tests()
    # Bionic fundamental tests are not supported on remote host.
    if parsed_args.remote:
      parsed_args.tests = [
          t for t in parsed_args.tests
          if not unittest_util.is_bionic_fundamental_test(t)]

  if parsed_args.gdb:
    # This script must not die by Ctrl-C while GDB is running. We simply
    # ignore SIGINT. Note that GDB will still handle Ctrl-C properly
    # because GDB sets its signal handler by itself.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

  if parsed_args.remote:
    return remote_executor.run_remote_unittest(parsed_args)
  else:
    return _run_unittest(parsed_args.tests, parsed_args.verbose,
                         parsed_args.gdb, parsed_args.gtest_filter,
                         parsed_args.gtest_list_tests)


if __name__ == '__main__':
  sys.exit(main())
