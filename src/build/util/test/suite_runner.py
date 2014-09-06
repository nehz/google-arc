# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Defines the integration test interface to running a suite of tests."""

import filtered_subprocess
import fnmatch
import json
import os
import subprocess
import threading

import build_common
from util.test.scoreboard import Scoreboard
from util.test.suite_runner_config import default_run_configuration
from util.test.suite_runner_config_flags import FAIL
from util.test.suite_runner_config_flags import TIMEOUT
from util.test.test_method_result import TestMethodResult


# Number of times to retry because of Chrome startup flake.
LAUNCH_CHROME_FLAKE_RETRY_COUNT = 3
# This is the minimum line count that is required to consider Chrome to have
# launched correctly.
_LAUNCH_CHROME_MINIMUM_LINES = 16


class TimeoutError(Exception):
  """Timeout class raised in this module."""


class SuiteRunnerOutputHandler(object):
  """Class to handle output generated by test runners.

  When a test suite runner is run, it will use a filtered_subprocess
  to execute the tests, using this class as an output handler.  This
  class will write all output from the test run to disk and then allow
  the runner to perform further processing.
  """
  def __init__(self, verbose, output_file, runner):
    self._output_file = output_file
    self._verbose = verbose
    self._runner = runner
    self._output = []

  def is_done(self):
    return False

  def handle_stdout(self, txt):
    self._handle_output(txt)

  def handle_stderr(self, txt):
    self._handle_output(txt)

  def get_output(self):
    return ''.join(self._output)

  def _handle_output(self, txt):
    if txt:
      if self._verbose:
        print '%s %s' % (self._runner.name, txt.strip())
      self._output_file.write(txt)
      self._output.append(txt)
      self._runner.handle_output(txt)


class SuiteRunnerBase(object):
  """Base class for a test suite runner.

  A suite runner can be constructed with several keyword options:

    flags

      A combination of util.test.suite_runner_config_flags flag values that
      indicate the expected result of running the suite.

    suite_test_expectations

      A dictionary mapping fully qualified test names to an expectation flag
      value indicating if that test will pass or not.

      Example:

        suite_test_expectations = {
            'Class1': {
                'method1': PASS, # passes
                'method2': FLAKY,  # passes, but flaky
                'method3': FAIL,  # fails
                'method4': NOT_SUPPORTED  # blacklist from running
            }
        }

    deadline

        The deadline in seconds in which the test suite should run to
        completion.
    """
  DEFAULT_DEADLINE = 300

  WRITE_ARGS_MIN_LENGTH = 10000

  # Output from tests will be written in this directory.
  _output_directory = 'out/integration_tests'

  @classmethod
  def set_output_directory(cls, output_directory):
    cls._output_directory = output_directory

  @classmethod
  def get_output_directory(cls):
    return cls._output_directory

  @staticmethod
  def get_xvfb_args(output_filename):
    assert output_filename, 'output_filename is not specified.'
    return ['xvfb-run', '--auto-servernum',
            # Use 24-bit color depth, as Chrome does not work with 8-bit color
            # depth, which is used in xvfb-run by default.
            '--server-args', '-screen 0 640x480x24',
            '--error-file', output_filename]

  def __init__(self, name, **config):
    self._lock = threading.Lock()
    self._name = name
    self._terminated = False

    merged_config = default_run_configuration()
    merged_config.update(config)
    self._flags = merged_config.pop('flags')
    self._set_suite_test_expectations(
        merged_config.pop('suite_test_expectations'))
    self._deadline = merged_config.pop('deadline')
    self._bug = merged_config.pop('bug')
    self._metadata = merged_config.pop('metadata')
    self._test_order = merged_config.pop('test_order')
    assert not merged_config, ('Unexpected keyword arguments %s' %
                               merged_config.keys())

    # For scoreboard, we pass a slightly modified expectations. If the
    # expectation for '*' is not filled, we propagate the top level
    # expectation.
    scoreboard_expectations = self._suite_test_expectations.copy()
    scoreboard_expectations.update(
        {Scoreboard.ALL_TESTS_DUMMY_NAME: self._flags})
    self._scoreboard = Scoreboard(name, scoreboard_expectations)

    # These will be set up later, in prepare_to_run(), and run_subprocess().
    self._args = None
    self._output_filename = None
    self._xvfb_output_filename = None
    self._subprocess = None

  def _ensure_test_method_details(self):
    if not self._suite_test_expectations:
      self._suite_test_expectations = {
          Scoreboard.ALL_TESTS_DUMMY_NAME: self._flags}

  @property
  def name(self):
    """Returns the name of this test runner."""
    return self._name

  @property
  def deadline(self):
    """Returns the deadline the test should run in."""
    return self._deadline

  @property
  def should_include_by_default(self):
    """Returns whether the suite should run by default."""
    return self._flags.should_include_by_default

  @property
  def suite_expectation(self):
    """Returns the expected result of the whole suite."""
    return self._flags

  @property
  def suite_test_expectations(self):
    """Returns the expected result of individual tests."""
    self._ensure_test_method_details()
    return self._suite_test_expectations.copy()

  @property
  def terminated(self):
    return self._terminated

  def _set_suite_test_expectations(self, suite_test_expectations):
    # Propagate flags set at the suite level to all the tests contained within
    # (FLAKY, LARGE, etc). Note that the suite expectation must be first to
    # allow the test expectation to properly override it.
    suite_expectation = self._flags
    self._suite_test_expectations = dict(
        (name, suite_expectation | expectation)
        for name, expectation in suite_test_expectations.iteritems())

  def set_suite_test_expectations(self, suite_test_expectations):
    self._set_suite_test_expectations(suite_test_expectations)
    self._scoreboard.set_expectations(self._suite_test_expectations)
    if (len(self._suite_test_expectations) > 1 and
        Scoreboard.ALL_TESTS_DUMMY_NAME in self._suite_test_expectations):
      del self._suite_test_expectations[Scoreboard.ALL_TESTS_DUMMY_NAME]

  def get_scoreboard(self):
    return self._scoreboard

  @property
  def expect_failure(self):
    """Returns the expected result of the whole suite."""
    return FAIL in self._flags or TIMEOUT in self._flags

  @property
  def bug(self):
    """Returns the bug url(s) associated with this suite."""
    return self._bug

  def has_test_method_details(self):
    """Returns true if this suite runner knows what test methods will be run.

    This is overridden by the actual implementations which have these
    details."""
    return True

  def get_test_method_expectation_counts(self):
    """Returns a dictionary mapping expectations to method counts.

    The keys of the dictionary are the lowercase letters p (for passing tests),
    f (for failing tests), and s (for skipped tests).

    It is the responsibility of any override to count all test methods as
    skipped if the suite itself will be skipped.
    """
    self._ensure_test_method_details()
    # We return a simple dictionary of pass/fail/skipped test method counts.
    details = dict(p=0, f=0, s=0)
    # Determine if the suite as a whole is skipped, as that affects how we
    # should count each test.
    is_suite_skipped = self.suite_expectation.should_not_run
    does_suite_fail = self.expect_failure
    for name, expectation in self._suite_test_expectations.iteritems():
      # Depending on what we expect to happen, adjust the count for the
      # appropriate bucket.
      if not expectation.should_include_by_default or is_suite_skipped:
        details['s'] += 1
      elif FAIL in expectation or does_suite_fail:
        details['f'] += 1
      else:
        details['p'] += 1
    return details

  def check_test_runnable(self):
    if self._flags.should_not_run:
      return False
    return True

  def prepare(self, test_methods_to_run):
    """Overridden in actual implementations to do preparations on the host.

    This is invoked on the host but not invoked on a remote host (Windows, Mac,
    and Chrome OS) when --remote option is specified for run_integration_tests.
    This is a good place to prepare the files that are copied to the remote host
    for running tests on it.
    This function is invoked only once even if flaky tests are retried.
    """
    pass

  def setUp(self, test_methods_to_run):
    """Overridden in actual implementations to do pre-test setup."""
    pass

  def tearDown(self, test_methods_to_run):
    """Overridden in actual implementations to do post-test cleanup."""
    pass

  def run(self, test_methods_to_run):
    """Invoked by the framework to run one or more test methods.

    The names in test_methods_to_run will be some subset of the names returned
    by the suite_test_expectations property.

    This function should return a pair:

      (raw_test_output, test_method_results)

    raw_test_output should be a string containing the full output of running the
    suite, or something equivalent.

    test_method_results should be a dictionary mapping test method names to
    instances of test_method_results.TestMethodResult, which describes whether
    each test passed or failed, and any test specific output or error messages.

    Note that a special test method name of ALL_TESTS_DUMMY_NAME is used if the
    test runner implementation does not seem to provide any
    suite_test_expectations, and this may need to be ignored.

    This should be overridden in actual implementations as necessary to run the
    tests.
    This is invoked on Chrome OS when --remote option specified for
    run_integration_tests, so the tools that are not available on Chrome OS
    should not be used in this function (e.g. ninja, javac, dx etc.).
    """
    return "", {}

  def finalize(self, test_methods_to_run):
    """Overridden in actual implementations to do final cleanup.

    This function differs from tearDown in that tearDown can be invoked several
    times if flaky tests are retried but finalize is invoked only once at the
    end of the test.
    """
    pass

  def handle_output(self, line):
    pass

  def prepare_to_run(self, test_methods_to_run, args):
    self._args = args
    self.prepare(test_methods_to_run)

  def run_with_setup(self, test_methods_to_run, args):
    self._args = args
    try:
      self._scoreboard.start(test_methods_to_run)
      self.setUp(test_methods_to_run)
      return self.run(test_methods_to_run)
    finally:
      self.tearDown(test_methods_to_run)

  def restart(self, test_methods_to_run, args):
    self._scoreboard.restart()

  def abort(self, test_methods_to_run, args):
    self._scoreboard.abort()

  def finalize_after_run(self, test_methods_to_run, args):
    self._args = args
    self.finalize(test_methods_to_run)
    self._scoreboard.finalize()

  def apply_test_ordering(self, test_methods_to_run):
    def key_fn(name):
      for pattern, order in self._test_order.iteritems():
        if fnmatch.fnmatch(name, pattern):
          return (order, name)
      return (0, name)
    return sorted(test_methods_to_run, key=key_fn)

  def get_launch_chrome_command(self, additional_args, mode=None,
                                name_override=None):
    """Returns the commandline for running suite runner with launch_chrome."""
    args = build_common.get_launch_chrome_command()
    if mode:
      args.append(mode)
    name = name_override if name_override else self._name
    args.extend(['--crx-name-override=' + name,
                 '--noninja',
                 '--use-temporary-data-dirs',
                 '--disable-sleep-on-blur'])

    # Force software GPU emulation mode when running tests under Xvfb.
    if self._args.enable_osmesa or self._args.use_xvfb:
      args.append('--enable-osmesa')

    if self._metadata:
      args.append('--additional-metadata=' + json.dumps(self._metadata))

    args.extend(self._args.launch_chrome_opts)

    deadline = self.deadline
    if self._args.min_deadline:
      deadline = max(deadline, self._args.min_deadline)
    if self._args.max_deadline:
      deadline = min(deadline, self._args.max_deadline)
    args.append('--timeout=' + str(deadline))

    return args + additional_args

  def get_system_mode_launch_chrome_command(self, name, additional_args=[]):
    return self.get_launch_chrome_command(['--stderr-log=I'] + additional_args,
                                          mode='system',
                                          name_override='system_mode.' + name)

  def _get_subprocess_output(self):
    output = ''
    if self._output_filename:
      with open(self._output_filename, 'r') as output_file:
        output = output_file.read()
      self._output_filename = None
    return output

  def _get_xvfb_output(self):
    output = ''
    if self._xvfb_output_filename:
      with open(self._xvfb_output_filename, 'r') as output_file:
        output = output_file.read()
      self._xvfb_output_filename = None
    return output

  def get_use_xvfb(self):
    return self._args.use_xvfb

  def terminate(self):
    with self._lock:
      self._terminated = True
      if self._subprocess and self._subprocess.returncode is None:
        self._subprocess.terminate()

  def kill(self):
    with self._lock:
      if self._subprocess and self._subprocess.returncode is None:
        self._subprocess.kill()

  def write_args_if_needed(self, args):
    """Writes args to a file if it is too long and returns a new args."""
    # Do not rewrite args of the commands other than launch_chrome because
    # the commands do not necessarily support the syntax of reading arguments
    # from a file.
    if not build_common.is_launch_chrome_command(args):
      return args
    remaining_args = build_common.remove_leading_launch_chrome_args(args)
    args_string = '\n'.join(remaining_args)
    # Do not rewrite args to file if the argument list is short enough.
    if len(args_string) < SuiteRunnerBase.WRITE_ARGS_MIN_LENGTH:
      return args

    args_dir = os.path.join(build_common.get_build_dir(), 'integration_tests')
    build_common.makedirs_safely(args_dir)

    args_file = os.path.join(args_dir, self._name + '_args')
    with open(args_file, 'w') as f:
      f.write(args_string)
    return args[:-len(remaining_args)] + ['@' + args_file]

  # Using run-xvfb increases launching time, and is useless for command line
  # tools, e.g., javac and adb. Even though --use-xvfb is specified, do not
  # use run-xvfb for them if omit_xvfb=True.
  def run_subprocess(self, args, omit_xvfb=False, *vargs, **kwargs):
    """Runs a subprocess handling verbosity flags."""
    output_directory = SuiteRunnerBase._output_directory
    if self._args.use_xvfb and not omit_xvfb:
      self._xvfb_output_filename = os.path.abspath(
          os.path.join(output_directory, self._name + '-xvfb.log'))
      args = SuiteRunnerBase.get_xvfb_args(self._xvfb_output_filename) + args
    self._output_filename = os.path.join(output_directory, self._name)
    with open(self._output_filename, 'w') as output_file:
      with self._lock:
        if self._terminated:
          raise subprocess.CalledProcessError(1, args)
        args = self.write_args_if_needed(args)
        build_common.log_subprocess_popen(args, *vargs, **kwargs)
        self._subprocess = filtered_subprocess.Popen(args, *vargs, **kwargs)
      verbose = self._args.output == 'verbose'
      handler = SuiteRunnerOutputHandler(verbose, output_file, self)
      self._subprocess.run_process_filtering_output(handler)
      returncode = self._subprocess.wait()
      # We emulate subprocess.check_call() here, as the callers expect to catch
      # a CalledProcessError when there is a problem.
      if returncode:
        raise subprocess.CalledProcessError(returncode, args)
    output = handler.get_output()
    xvfb_output = self._get_xvfb_output()
    if xvfb_output and self._args.output == 'verbose':
      print '-' * 10 + ' XVFB output starts ' + '-' * 10
      print xvfb_output
    return output

  def run_subprocess_test(self, args, env=None, cwd=None):
    """Runs a test which runs subprocess and sets status appropriately."""
    result = None
    # We cannot use the normal retry methods used in test_driver to
    # determine whether to run the test suites that are failing because of
    # Chrome launch failures.  This is because most of the suite runners have
    # default expectations, and the set of tests that is run is
    # ALL_TESTS_DUMMY_NAME, both of which do not track 'incompletes' properly in
    # the scoreboard.  Keep our own count here.
    chrome_flake_retry = LAUNCH_CHROME_FLAKE_RETRY_COUNT
    while True:
      try:
        raw_output = self.run_subprocess(args, env=env, cwd=cwd)
        result = TestMethodResult(Scoreboard.ALL_TESTS_DUMMY_NAME,
                                  TestMethodResult.PASS)
        break
      except subprocess.CalledProcessError:
        raw_output = self._get_subprocess_output()
        is_timeout = raw_output.endswith("[  TIMEOUT  ]\n")
        # TODO(crbug.com/359859): Remove this hack when it is no longer
        # necessary.  Workaround for what we suspect is a problem with Chrome
        # failing on launch a few times a day on the waterfall.  The symptom is
        # that we get 3-5 lines of raw output followed by a TIMEOUT message.
        if (is_timeout and
            len(raw_output.split('\n')) < _LAUNCH_CHROME_MINIMUM_LINES and
            chrome_flake_retry > 0 and
            build_common.is_launch_chrome_command(args)):
          print '@@@STEP_WARNINGS@@@'
          print '@@@STEP_TEXT@Retrying ' + self.name + ' (Chrome flake)@@@'
          chrome_flake_retry -= 1
          continue

        if self._xvfb_output_filename is not None:
          raw_output += '-' * 10 + ' XVFB output starts ' + '-' * 10
          raw_output += self._get_xvfb_output()
        if is_timeout:
          result = TestMethodResult(Scoreboard.ALL_TESTS_DUMMY_NAME,
                                    TestMethodResult.INCOMPLETE)
        else:
          result = TestMethodResult(Scoreboard.ALL_TESTS_DUMMY_NAME,
                                    TestMethodResult.FAIL)
        break

    self._scoreboard.update([result])
    return raw_output, {result.name: result}