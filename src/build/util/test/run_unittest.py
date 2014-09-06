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
# $ src/build/util/test/run_unittest.py test0 test1 ...
#
# Run unit tests remotely on a Chrome OS device.
# $ src/build/util/test/run_unittest.py test0 test1 ... --remote=<REMOTE>
#
# When --remote is specified, the test binaries and other necessary files are
# copied to the remote Chrome OS device. The the unit tests need to be built
# before running this script.

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, 'src/build')
import build_common
import build_options
import toolchain
from util import platform_util
from util import remote_executor


# A placeholder to represent runner.
_RUNNER_PLACEHOLDER = '$runner'


def _get_test_path(test):
  return '%s/intermediates/%s/%s' % (build_common.get_build_dir(), test, test)


def _get_test_info_file():
  return '%s/test_info' % build_common.get_build_dir()


def _read_test_info():
  with open(_get_test_info_file(), 'r') as f:
    return json.load(f)


def _write_test_info(test_info):
  with open(_get_test_info_file(), 'w') as f:
    json.dump(test_info, f)


def _get_results_files(test):
  """Returns a list of the results file names corresponding to the test."""
  # Find the name of results files corresponding to test.
  ninja_file = 'out/generated_ninja/%s.ninja' % test
  if not os.path.exists(ninja_file):
    return []
  test_regex = re.compile(r'%s.results.[1-9]+' % _get_test_path(test))
  results_files = []
  with open(ninja_file) as f:
    for line in f:
      m = test_regex.search(line)
      if m:
        results_files.append(m.group(0))
  return results_files


def _get_test_info_from_file(tests):
  """Gets a test info by reading the stored file."""
  test_info = {}
  invalid_tests = []
  all_test_info = _read_test_info()
  for test in tests:
    if test in all_test_info:
      test_info[test] = all_test_info[test]
    else:
      invalid_tests.append(test)
  if invalid_tests:
    raise Exception(
        'Incorrect test names specified: ' + ' '.join(invalid_tests))
  return test_info


def _get_test_info_from_ninja(tests):
  """Gets a test info by reading the output from ninja."""
  test_info = {}
  invalid_tests = []
  for test in tests:
    results_files = _get_results_files(test)
    if not results_files or not os.path.exists(_get_test_path(test)):
      invalid_tests.append(test)
      continue
    # Examine the output by "ninja -t commands", which prints the list of
    # the commands needed to generate the results file. The command to run
    # unit tests is listed at the end of the list
    for results_file in results_files:
      cmd = ['ninja', '-t', 'commands', results_file]
      output_lines = subprocess.check_output(cmd).split('\n')
      # Use the second last line because the last line is an empty line.
      assert not output_lines[-1]
      test_command = output_lines[-2]
      test_commands = test_info.get(test, [])
      test_commands.append(test_command)
      test_info[test] = test_commands
  if invalid_tests:
    hint = ''
    if filter(lambda t: t.find('/') != -1, invalid_tests):
      hint = ('. Hint: a path name to the test should NOT be passed. For '
              'example, use \'bionic_test\' instead of \''
              'out/target/nacl_i686/intermediates/bionic_test/bionic_test\'.')
    raise Exception(
        'Incorrect test names specified or the specified tests are not ' +
        'built yet: ' + ' '.join(invalid_tests) + hint)
  return test_info


def _get_test_info(tests):
  "Creates a test info, which is the dictionary of (test_name, test_commands)."
  if platform_util.is_running_on_remote_host():
    return _get_test_info_from_file(tests)
  else:
    return _get_test_info_from_ninja(tests)


def _replace_test_info_for_remote(test_info):
  """Replaces commands in test_info for executing in the remote device."""
  remote_test_info = {}
  for test, test_commands in test_info.iteritems():
    for test_command in test_commands:
      # Replace the runner command with a placeholder.
      remote_test_command = test_command.replace(
          ' '.join(toolchain.get_nacl_runner()), _RUNNER_PLACEHOLDER)
      # Convert absolute paths into the relative paths
      remote_test_command = remote_test_command.replace(
          build_common.get_arc_root(), './')
      remote_test_commands = remote_test_info.get(test, [])
      remote_test_commands.append(remote_test_command)
      remote_test_info[test] = remote_test_commands
  return remote_test_info


def _get_copied_files_for_remote(test_info):
  """Gets a list of the files that need to be copied to the remote device."""
  copied_files = [_get_test_info_file()]
  for test in test_info:
    test_path = _get_test_path(test)
    if test_path not in copied_files:
      copied_files.append(test_path)
  return copied_files


def _run_unittest(parsed_args, test_info):
  """Runs the unit tests specified in test_info.

  This can run unit tests without depending on ninja and is mainly used on the
  remote device where ninja is not installed.
  """
  failed_tests = []
  for test, test_commands in test_info.iteritems():
    for test_command in test_commands:
      if platform_util.is_running_on_remote_host():
        # Replace the placeholder of the runner with the real runner command.
        test_command = test_command.replace(
            _RUNNER_PLACEHOLDER, ' '.join(toolchain.get_nacl_runner()))
      if parsed_args.verbose:
        print 'Running: ', test_command
      cmd = shlex.split(test_command)
      # Remove trailing redirection for outputting to console.
      # The command to be performed on remote is obtained by "ninja -t command"
      # which does not output to stdout. However this script is intended for
      # interactive debugging, so that we have to remove trailing output handler
      # defined in build_common.py. Unfortunately we can't remove output handler
      # easily from raw command string because output handler can not be
      # obtained at this moment directly.
      # Following is workaround for removing output handler by dropping tokens
      # after shell redirection operator. This approaches assumes output handler
      # starts with a shell redirection operator defined as _TEST_OUTPUT_HANDLER
      # in build_common.py
      assert '>' in cmd, 'Need to update this script to reflect the change of '\
          'test_command.'
      cmd = cmd[0:cmd.index('>')]
      returncode = subprocess.call(cmd)
      if returncode != 0:
        print 'FAILED: ' + test
        failed_tests.append(test)
    if failed_tests:
      print 'Failed tests: ' + ' '.join(failed_tests)
      return -1
  return 0


def main():
  build_options.OPTIONS.parse_configure_file()

  description = 'Runs unit tests, verifying they pass.'
  parser = argparse.ArgumentParser(description=description)
  parser.add_argument('tests', metavar='test', nargs='+',
                      help='The name of a unit test, such as libcommon_test')
  parser.add_argument('-v', '--verbose', action='store_true',
                      default=False, dest='verbose',
                      help=('Show verbose output, including commands run'))
  remote_executor.add_remote_arguments(parser)
  parsed_args = parser.parse_args()

  test_info = _get_test_info(parsed_args.tests)
  if parsed_args.remote:
    _write_test_info(_replace_test_info_for_remote(test_info))
    return remote_executor.run_remote_unittest(
        parsed_args, _get_copied_files_for_remote(test_info))
  else:
    return _run_unittest(parsed_args, test_info)


if __name__ == '__main__':
  sys.exit(main())
