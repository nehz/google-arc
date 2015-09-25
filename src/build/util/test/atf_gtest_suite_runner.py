# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implements a suite runner for gtest based on ATF."""

from src.build import prep_launch_chrome
from src.build.util import platform_util
from src.build.util.test import atf_suite_runner
from src.build.util.test import google_test_result_parser as result_parser
from src.build.util.test import suite_runner_util


def _build_atf_launch_chrome_args(test_apk, test_list, test_methods_to_run,
                                  extra_args):
  """Returns flags and arguments to run gtest based on ATF."""
  args = ['atftest', test_apk]
  if test_methods_to_run:
    # If test_methods_to_run is set, test_list must be set at the same time.
    assert test_list
    args.extend([
        '--atf-gtest-list',
        ':'.join(test.replace('#', '.') for test in test_list),
        '--atf-gtest-filter',
        ':'.join(test.replace('#', '.') for test in test_methods_to_run)])
  if extra_args:
    args.extend(extra_args)
  return args


class AtfGTestSuiteRunner(atf_suite_runner.AtfSuiteRunnerBase):
  def __init__(self, test_name, test_apk, test_list_path, **kwargs):
    super(AtfGTestSuiteRunner, self).__init__(
        test_name, test_apk,
        suite_runner_util.read_test_list(test_list_path), **kwargs)

  def handle_output(self, line):
    if self._result_parser:
      self._result_parser.process_line(line)

  def _build_launch_chrome_command(self, test_methods_to_run):
    return self.get_launch_chrome_command(
        _build_atf_launch_chrome_args(
            self._test_apk,
            sorted(self.expectation_map.keys()),
            test_methods_to_run, self._extra_args))

  def setUp(self, test_methods_to_run):
    if not self._first_run or platform_util.is_running_on_remote_host():
      # When |self._first_run| is False, the test suite is being retried.
      # In this case we need to update the shell command written in the CRX
      # manifest, which specifies the tests to run, so that only failed tests
      # are retried.
      # When running on a remote host, the shell command needs to be
      # rewritten even at the first run so that platform dependent
      # test configurations are reflected.
      prep_launch_chrome.update_shell_command(
          self._build_launch_chrome_command(test_methods_to_run))

    # Use GoogleTestResultParser instead of AtfInstrumentationTestParser.
    self._first_run = False

  def run(self, test_methods_to_run, scoreboard):
    self._result_parser = (
        result_parser.GoogleTestResultParser(scoreboard))

    super(AtfGTestSuiteRunner, self).run(test_methods_to_run, scoreboard)

  def tearDown(self, test_methods_to_run):
    self._result_parser = None
