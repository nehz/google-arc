# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implements a simple ARC ATF Suite test runner."""

import os
import subprocess

import launch_chrome_options
import prep_launch_chrome
from util import platform_util
from util.test import atf_instrumentation_result_parser as result_parser
from util.test import atf_instrumentation_scoreboard_updater as scoreboard_updater  # NOQA
from util.test import scoreboard
from util.test import suite_runner
from util.test import suite_runner_util


def _build_atf_launch_chrome_args(test_apk, target_apk, app_namespace, runner,
                                  test_methods_to_run, extra_args):
  """Returns flags and arguments to run ATF based test suites.

  test_apk: path to .apk file containing test code.
  target_apk: path to .apk file for the test target. Optional.
  app_namespace: the name space of the test application.
  runner: the instrumentation runner.
    Both app_namespace and runner must be set at once, or not set.
  test_methods_to_run: a list of tests which need to be run. Optional.
  extra_args: If necessary, more flags can be set via this param.

  Returned arguments may contain following flags:
    --start-test-component <name>
        Identifies the entry point of start for the tests.
    --run-test-classes <class>#<method>[,<class>#<method>...]
        Identifies the classes/methods to specifically run.
  """
  assert (app_namespace is None) == (runner is None)

  args = ['atftest', test_apk]
  if target_apk:
    args.append(target_apk)
  if app_namespace:
    args.extend(['--start-test-component', '%s/%s' % (app_namespace, runner)])
  if test_methods_to_run:
    args.extend(['--run-test-classes', ','.join(test_methods_to_run)])
  if extra_args:
    args.extend(extra_args)
  return args


class AtfSuiteRunnerBase(suite_runner.SuiteRunnerBase):
  """Base class of the suite runners for ATF based test suites.

  This is the base class to implement ATF based test suites.
  If you want to run ATF based test suite, this is probably not the one you
  need. Please see also AtfSuiteRunner and CtsSuiteRunner.
  """
  def __init__(self, test_name, test_apk, base_expectation_map,
               target_apk=None, app_namespace=None, runner=None,
               extra_args=None, extra_env=None, config=None):
    super(AtfSuiteRunnerBase, self).__init__(
        test_name, base_expectation_map, config=config)

    self._test_apk = test_apk
    self._target_apk = target_apk
    self._app_namespace = app_namespace
    self._runner = runner
    self._extra_args = extra_args
    self._extra_env = extra_env

    self._result_parser = None
    self._scoreboard_updater = None
    self._first_run = False
    self._name_override = None

  def handle_output(self, line):
    self._result_parser.process_line(line)
    self._scoreboard_updater.update(self._result_parser)

  def _build_launch_chrome_command(self, test_methods_to_run):
    # Handle a special case where there is no explicit listing of tests in this
    # CTS suite, and so the framework automatically adds a dummy 'test' to run
    # to represent the entire suite.
    if test_methods_to_run == [scoreboard.Scoreboard.ALL_TESTS_DUMMY_NAME]:
      test_methods_to_run = None

    return self.get_launch_chrome_command(
        _build_atf_launch_chrome_args(
            self._test_apk, self._target_apk, self._app_namespace, self._runner,
            test_methods_to_run, self._extra_args),
        name_override=self._name_override)

  def prepare(self, test_methods_to_run):
    args = self._build_launch_chrome_command(test_methods_to_run)
    prep_launch_chrome.prepare_crx_with_raw_args(args)

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
    self._result_parser = result_parser.AtfInstrumentationResultParser()
    self._scoreboard_updater = (
        scoreboard_updater.AtfInstrumentationScoreboardUpdater(
            self.get_scoreboard()))
    self._first_run = False

  def run(self, test_methods_to_run):
    try:
      args = self._build_launch_chrome_command(test_methods_to_run)
      # The CRX is built in prepare, so it is unnecessary build here.
      args.append('--nocrxbuild')
      env = None
      if self._extra_env:
        env = os.environ.copy()
        env.update(self._extra_env)
      raw_output = self.run_subprocess(args, env=env)
    except subprocess.CalledProcessError as e:
      raw_output = e.output or ''
    return raw_output

  def finalize(self, test_methods_to_run):
    # Use the args as those of prepare to run remove_crx_at_exit_if_needed in
    # the same condition.
    args = self._build_launch_chrome_command(test_methods_to_run)
    parsed_args = launch_chrome_options.parse_args(args)
    # Removing the CRX is deferred in case this is running for the remote
    # execution, which needs to copy all the CRXs after all the suite runners
    # in the local host have finished.
    prep_launch_chrome.remove_crx_at_exit_if_needed(parsed_args)


class AtfSuiteRunner(AtfSuiteRunnerBase):
  """Suite runner to run ATF based test suites.

  The biggest diff from AtfSuiteRunnerBase is;
  The constructor takes the path to the file containing the list of
  <class>#<method>s for the suite, although AtfSuiteRunnerBase takes
  a dict from '<class>#<method>' to expectation.
  """
  def __init__(self, test_name, test_apk, test_list_path, **kwargs):
    super(AtfSuiteRunner, self).__init__(
        test_name, test_apk,
        suite_runner_util.read_test_list(test_list_path), **kwargs)
