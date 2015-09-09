# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import json
import os
import sys
import threading
import time

from src.build.util import synchronized_interface
from src.build.util.test import scoreboard_constants

# Note: The order of this list is the order displayed in the output.
STATUS_ORDER = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.UNEXPECT_PASS,
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.UNEXPECT_FAIL,
    scoreboard_constants.INCOMPLETE,
    scoreboard_constants.SKIPPED,
)

# The text displayed for each status
TERSE_STATUS_TEXT = {
    scoreboard_constants.EXPECT_FAIL: 'XF',
    scoreboard_constants.EXPECT_PASS: 'P',
    scoreboard_constants.FLAKE: 'FK',
    scoreboard_constants.INCOMPLETE: 'I',
    scoreboard_constants.SKIPPED: 'S',
    scoreboard_constants.UNEXPECT_FAIL: 'F',
    scoreboard_constants.UNEXPECT_PASS: 'UP',
}

VERBOSE_STATUS_TEXT = {
    scoreboard_constants.EXPECT_FAIL: 'Expected Failures',
    scoreboard_constants.EXPECT_PASS: 'Passed',
    scoreboard_constants.FLAKE: 'Flaky',
    scoreboard_constants.INCOMPLETE: 'Incomplete',
    scoreboard_constants.SKIPPED: 'Skipped',
    scoreboard_constants.UNEXPECT_FAIL: 'Failed',
    scoreboard_constants.UNEXPECT_PASS: 'Unexpectedly Passed',
}

# This indicates that the overall result of the test run is good.
# (e.g. all tests passed that should have)
_RUN_RESULT_GOOD = 0

# This indicates that the overall result of the test run is ok, but there were
# some warnings. (e.g. some tests were flaky)
_RUN_RESULT_WARNING = 1

# This indicates that the overall result of the test run is bad.
# (e.g. tests failed that were not expected to)
_RUN_RESULT_BAD = 2

# The width to use for the suite state column in the output.
_SUITE_STATE_COLUMN_WIDTH = 51

_ATTEMPTED_STATUS = (
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.FLAKE,
    scoreboard_constants.INCOMPLETE,
    scoreboard_constants.SKIPPED,
    scoreboard_constants.UNEXPECT_FAIL,
    scoreboard_constants.UNEXPECT_PASS,
)

_BAD_STATUS = (
    scoreboard_constants.INCOMPLETE,
    scoreboard_constants.UNEXPECT_FAIL,
)

# Note: The order of the values in this list needs to be from best result to
# worst result.
_EXPECTATION_BY_PRIORITY = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.FLAKE,
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.SKIPPED,
)

_EXPECTED_STATUS_STRING = {
    scoreboard_constants.EXPECT_FAIL: 'are expected to fail',
    scoreboard_constants.EXPECT_PASS: 'are expected to pass',
    scoreboard_constants.SKIPPED: 'will be skipped',
}

_GOOD_STATUS = (
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.SKIPPED,
    scoreboard_constants.UNEXPECT_PASS,
)

_PASS_STATUS = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.UNEXPECT_PASS,
)

# Note: The order of this list is the order displayed in the output.
_TO_LIST_STATUS = (
    scoreboard_constants.FLAKE,
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.UNEXPECT_PASS,
    scoreboard_constants.UNEXPECT_FAIL,
    scoreboard_constants.INCOMPLETE,
)

# If a suite contains any tests with this status, its output is included in the
# test log.
_TO_LOG_OUTPUT_STATUS = (
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.INCOMPLETE,
    scoreboard_constants.UNEXPECT_FAIL,
)

# If a suite contains any tests with this status, a warning annotation is
# emitted for the build step.
_TO_WARN_STATUS = (
    scoreboard_constants.UNEXPECT_PASS,
)

# The single instance of the SuiteResultsBase used for displaying results.
SuiteResults = None


def _compute_count_by_expectation(scoreboard):
  # Get the expected result of each test
  expectations = scoreboard.get_expectations()
  # Convert these results into a count by each result
  counts = collections.Counter(expectations.itervalues())
  # Count flaky tests as passing tests.
  counts[scoreboard_constants.EXPECT_PASS] += counts[scoreboard_constants.FLAKE]
  return counts


def _determine_overall_status_from_counts(counts):
  status = scoreboard_constants.EXPECT_PASS
  for expectation in _EXPECTATION_BY_PRIORITY:
    if counts[expectation]:
      status = expectation
  return status


# TODO(lpique): Move the _format_xxx functions and FormattedLogger class to a
# new module.
def _format_elipsized_text(text, target_len):
  """Shrinks or grows a string so that it occupies target_len characters.

  If the string is shorter than target_len, it is padded on the right with
  spaces. If the string is longer than target_len, a middle section of the
  string is replaced with '...' to get it to meet the target length. If
  necessary, the elipsis itself is shortened to fit the target length.

  Args:
    text: The string to adjust
    target_len: The length to target.

  Returns:
    The adjusted string.

  Examples:
    _format_elipsized_text('123456', 7) -> '123456 '
    _format_elipsized_text('1234567', 7) -> '1234567'
    _format_elipsized_text('12345678', 7) -> '12...78'
    _format_elipsized_text('123456789', 7) -> '12...89'
    _format_elipsized_text('1234567890', 8) -> '12...890'
    _format_elipsized_text('1234567890', 7) -> '12...90'
    _format_elipsized_text('1234567890', 6) -> '1...90'
    _format_elipsized_text('1234567890', 5) -> '1...0'
    _format_elipsized_text('1234567890', 4) -> '...0'
    _format_elipsized_text('1234567890', 3) -> '...'
    _format_elipsized_text('1234567890', 2) -> '..'
    _format_elipsized_text('1234567890', 1) -> '.'
    _format_elipsized_text('1234567890', 0) -> ''
  """
  assert target_len >= 0
  if len(text) <= target_len:
    return text.ljust(target_len)
  # Adjust for the length of the elipsis
  elipsis = '...'
  target_len -= len(elipsis)
  if target_len <= 0:
    return elipsis[:len(elipsis) + target_len]
  first_half = target_len // 2
  second_half = target_len - first_half
  return '%s%s%s' % (text[:first_half], elipsis, text[-second_half:])


def _format_duration(duration, fractions=False):
  """Converts a duration in seconds to a human readable 'Xh Ym Zs' string.

  Args:
    duration: The duration in seconds.
    fractions: If True, the seconds will be displayed to three decimal places.
        Otherwise only the whole seconds will be displayed.

  Returns:
    The more human readable string representing the duration. Note that
    negative durations will just be output as a negative count of seconds.

  Examples:
    _format_duration(10) -> '10s'
    _format_duration(75) -> '1m 15s'
    _format_duration(3608.12, fractions=True) -> '1h 8.120s'
    _format_duration(-100) -> '-100s'
  """

  seconds = duration
  if seconds >= 0:
    minutes = seconds // 60
    seconds -= minutes * 60
    hours = minutes // 60
    minutes -= hours * 60
  else:
    minutes = 0
    hours = 0

  components = []
  if hours:
    components.append('%dh' % hours)
  if minutes:
    components.append('%dm' % minutes)
  if seconds or duration == 0:
    components.append(('%0.3fs' if fractions else '%ds') % seconds)
  return ' '.join(components)


# TODO(lpique): Eliminate this MM:SS format. Requires changes to other tests.
def _format_duration_old(duration):
  """Converts the duration in seconds to a human readable 'MM:SS' string.

  Args:
    duration: The duration in seconds. Only the whole number of seconds is used.

  Returns:
    The more human readable string representing the duration.  Note that
    negative durations will lead to unexpected output.

  Examples:
    _format_duration(10) -> '00:10'
    _format_duration(75) -> '01:15'
    _format_duration(3608.12, fractions=True) -> '60:08'
  """
  seconds = duration
  if seconds > 0:
    minutes = seconds // 60
    seconds = seconds - minutes * 60
  else:
    minutes = 0
  return '%02d:%02d' % (minutes, seconds)


def _format_progress(index, total):
  """Format a reasonably consistent-width progress indicator.

  The indicator is just the index and total

  Args:
    index: The index for the progress.
    total: The expected total count for the progress. Note that if index exceeds
        this value, then the index is used as the total instead.

  Returns:
    The string representing the progress.

  Examples:
    _format_progress(0, 99) -> '00/99'
    _format_progress(0, 100) -> '000/100'
    _format_progress(100, 99) -> '100/100'
  """
  max_total = str(max(index, total))
  progress = str(index).rjust(len(max_total), '0')
  return '%s/%s' % (progress, max_total)


def _format_status_counts(count_by_status, format_string, status_map,
                          status_order, show_zero_counts=False):
  """Displays a list of counts and their associated status results.

  This is an implementation function meant to be called by utility wrappers
  which provide the arguments beyond count_by_status.

  Args:
    count_by_status: A mapping of status codes to their counts.
    format_string: The format string to use.
    status_map: The mapping of status codes to text strings to use.
    status_order: A list of status codes, used to set the output order.
    show_zero_counts: If False, any status with a count of zero is omitted
        from the output.

  Returns:
    A string containing the formatted result.
  """
  return '  '.join(
      format_string % (count_by_status[status], status_map[status])
      for status in status_order
      if count_by_status[status] or show_zero_counts)


def _format_verbose_status_counts(count_by_status):
  """Displays a verbose list of counts and their associated status results.

  Args:
    count_by_status: A mapping of status codes to their counts.

  Returns:
    A string containing the formatted result.
  """
  return _format_status_counts(
      count_by_status,
      '%d %s',
      VERBOSE_STATUS_TEXT,
      STATUS_ORDER)


def _format_terse_status_counts(count_by_status):
  """Displays a terse list of counts and their associated status results.

  Args:
    count_by_status: A mapping of status codes to their counts.

  Returns:
    A string containing the formatted result.
  """
  return _format_status_counts(
      count_by_status,
      '% 5d%s',
      TERSE_STATUS_TEXT,
      STATUS_ORDER,
      show_zero_counts=True)


def _format_expected_status_counts(count_by_status):
  """Displays a list of expected counts and their status results.

  Args:
    count_by_status: A mapping of status codes to their counts.

  Returns:
    A string containing the formatted result.
  """
  return _format_status_counts(
      count_by_status,
      '% 5d%s',
      TERSE_STATUS_TEXT,
      _EXPECTED_STATUS_STRING,
      show_zero_counts=True)


class FormattedLogger(object):
  """Handles formatting and outputting the results of the test run."""

  def __init__(self, logfile, verbose):
    self._logfile = logfile
    self._verbose = verbose
    self._update_prefix = '- ' if verbose else ''

  def _log_build_step_annotation(self, content):
    """Writes a buildbot annotation.

    Args:
      content: String to use for the content
    """
    self._logfile.write('\n@@@%s@@@\n' % content)

  def log_build_step_failure(self):
    """Writes a buildbot step failure annotation."""
    self._log_build_step_annotation('STEP_FAILURE')

  def log_build_step_warnings(self):
    """Writes a buildbot step warnings annotation."""
    self._log_build_step_annotation('STEP_WARNINGS')

  def log_build_step_text(self, text):
    """Writes a buildbot step text annotation.

    The text is visible on the waterfall page.

    Args:
      text: The text to display.
    """
    self._log_build_step_annotation('STEP_TEXT@%s<br>' % text)

  def log_section(self, label):
    """Writes a section indicator to call out different parts of the log.

    Args:
      label: The text to display as the section label.
    """
    self._logfile.write('\n######## %s ########\n' % label)

  def log_newline(self):
    """Writes a newline."""
    self._logfile.write('\n')

  def log_message(self, text):
    """Writes an arbitrary string."""
    self._logfile.write(text)

  def log_test_raw_output(self, test_name, test_output_path):
    """Writes the raw output from a suite run.

    Args:
      test_name: The name of the test. Used to output a section to label the
          source of the raw output.
      test_output_path: The path to the file containing the raw output.
    """
    try:
      with open(test_output_path) as f:
        raw_output = f.read()
    except IOError:
      raw_output = '(No log file. The suite has not started.)'

    self.log_section('Raw Output: %s' % test_name)
    self._logfile.write(raw_output)
    self._logfile.write('\n')

  def _log_test_status(self, suite_state, test_state):
    """Writes a one-line status update for an test in a suite.

    The status update consists of a bit of text describing the suite state, and
    a bit of text describing the test state. This function ensures the output is
    consistent for various status messages.

    Args:
      suite_state: The text to display as the suite state. This is ellipsized or
          otherwise adjusted to fit a fixed column width.
      test_state: The text to display as the test state.
    """
    self._logfile.write('%s%s - %s\n' % (
        self._update_prefix,
        _format_elipsized_text(suite_state, _SUITE_STATE_COLUMN_WIDTH),
        test_state))

  def log_test_status_start(self, suite_name, index, total, test_name):
    """Writes a one-line status update for an test which started.

    Args:
      suite_name: The name of the suite.
      index: The index of the test in the suite.
      total: The total number of tests in the suite.
      test_name: The name of the test.
    """
    suite_state = '%s %s' % (suite_name, _format_progress(index, total))
    test_state = '(Running) %s' % test_name
    self._log_test_status(suite_state, test_state)

  def log_test_status_update(self, suite_name, index, total, test_name, status,
                             duration):
    """Writes a one-line status update for an test which completed.

    Args:
      suite_name: The name of the suite.
      index: The index of the test in the suite.
      total: The total number of tests in the suite.
      test_name: The name of the test.
      status: The scoreboard_constant result code for the rest.
      duration: The time taken to run the test in seconds.
    """
    if status == scoreboard_constants.SKIPPED and not self._verbose:
      return

    suite_state = '%s %s' % (suite_name, _format_progress(index, total))
    test_state = '[%s:%s] %s' % (
        TERSE_STATUS_TEXT[status],
        _format_duration(duration, fractions=True),
        test_name)
    self._log_test_status(suite_state, test_state)

  def log_scoreboard_finish_status(self, scoreboard):
    """Writes a one-line status update for an suite which completed.

    Args:
      scoreboard: The status of the suite that has finished.
    """
    # TODO(lpique): Make _get_count public.
    count_by_status = dict((status, scoreboard._get_count(status))
                           for status in STATUS_ORDER)
    suite_state = scoreboard.name
    test_state = '[%s:%s] %s' % (
        TERSE_STATUS_TEXT[scoreboard.overall_status],
        _format_duration(scoreboard.duration, fractions=True),
        _format_terse_status_counts(count_by_status))
    self._log_test_status(suite_state, test_state)

  def _log_scoreboard_stats(self, scoreboard):
    """Writes a one-line summary for the final status of a suite.

    Args:
      scoreboard: The status of the suite.
    """
    # TODO(lpique): Make _get_count public.
    count_by_status = dict((status, scoreboard._get_count(status))
                           for status in STATUS_ORDER)
    self._logfile.write('%s %s [%s:%s]\n' % (
        _format_elipsized_text(scoreboard.name, _SUITE_STATE_COLUMN_WIDTH),
        _format_terse_status_counts(count_by_status),
        VERBOSE_STATUS_TEXT[scoreboard.overall_status],
        _format_duration(scoreboard.duration, fractions=True)))

  def log_scoreboards_stats(self, scoreboard_list):
    """Writes a summary section for the final status of list of suites.

    Args:
      scoreboard_list: The list of scoreboards to log the status of.
    """
    if not scoreboard_list:
      return
    self.log_section('Results')
    for scoreboard in sorted(
        scoreboard_list, key=lambda scoreboard: scoreboard.name):
      self._log_scoreboard_stats(scoreboard)

  def log_test_name_section_for_status(self, test_names, status):
    """Writes a single summary section listing tests with a common status.

    Sections are omitted if they would be empty.

    Args:
      test_names: The names of all the tests.
      status: The common status of each of the named tests.
    """
    if test_names:
      self.log_section('%s (%d)' % (
          VERBOSE_STATUS_TEXT[status], len(test_names)))
      self._logfile.write('%s\n' % ('\n'.join(sorted(test_names))))

  def log_summary_stats(self, elapsed, count_tests_attempted, count_tests_known,
                        count_by_status):
    """Writes an summary of stats for the entire test run (all suites).

    Args:
      elapsed: The total time for the run in seconds.
      count_tests_attempted: The count of tests attempted.
      count_tests_known: The count of tests known.
      count_by_status: A mapping of result status codes to the count of tests
          with that status for all tests.
    """
    self.log_section('Summary')
    self._logfile.write('%s %d/%d  100%%  %s%s\n' % (
        _format_duration_old(elapsed),
        count_tests_attempted,
        count_tests_known,
        ' No Tests were selected to run. ' if not count_tests_known else '',
        _format_verbose_status_counts(count_by_status)))

  def log_expected_summary_stats(self, count_by_status, overall_status,
                                 suite_name):
    """Writes an one-line summary of expected status for a single suite.

    Args:
      count_by_status: A mapping of result status codes to the count of tests
          with that status.
      overall_status: The status of the suite.
    """
    self._logfile.write('%s [%- 20s] %s\n' % (
        _format_expected_status_counts(count_by_status),
        VERBOSE_STATUS_TEXT[overall_status],
        suite_name))

  def log_expected_totals(self, name, count_by_status):
    """Writes an summary of expected stats for the entire test run.

    Args:
      name: The name to use to identify the totals.
      count_by_status: A mapping of result status codes to the count of tests
          with that status.
    """
    total = sum(count_by_status.values())
    self.log_section('%d total %s' % (total, name))
    self._logfile.write('\n'.join(
        '% 8d (% 3d%%) %s' % (
            count_by_status[status],
            (100 * count_by_status[status] // total) if total else 0,
            _EXPECTED_STATUS_STRING[status])
        for status in _EXPECTED_STATUS_STRING))
    self.log_newline()


class SuiteResultsBase(object):
  """The base interface used to report test results for the test run."""

  def start_suite(self, scoreboard):
    """Called to indicate that a suite has started."""
    pass

  def restart_suite(self, scoreboard, num_retried_tests):
    """Called to indicate that a suite is restarting (retrying)."""
    pass

  def abort_suite(self, scoreboard):
    """Called to indicate that a suite is aborting."""
    pass

  def finish_suite(self, scoreboard):
    """Called to indicate that a suite has finished."""
    pass

  def start_test(self, scoreboard, test):
    """Called to indicate that a test is starting in a suite.

    Note that tests can be retried, so they may be started more than once.
    """
    pass

  def finish_test(self, scoreboard, test_name, test_status, test_duration=0):
    """Called to indicate that a test has finished in a suite."""
    pass

  def finalize_run(self, output_dir):
    """Called to finalize the run, and generate a report for it.

    Args:
      output_dir: The directory containing the raw output for each suite. Used
          to copy the raw output to the log for suites that failed.

    Returns:
      A tuple (failed, pass_count, total_count):
        failed: True if the run failed.
        pass_count: The count of tests that passed.
        total_count: The total count of tests.
    """
    return False, 0, 0

  def report_expected_results(self, scoreboards):
    """Called to generate a expected result report for the indicated suites."""
    pass


class CallNotExpectedError(Exception):
  """Used to indicate that the call was not expected."""


# TODO(lpique): Rename as follows:
# suite_results -> run_observer (observes and logs results for the entire run)
# scoreboard -> suite_result (result for a single suite)
class SuiteResultsPrepare(SuiteResultsBase):
  """Outputs the progress of preparing files for remote executions."""

  def __init__(self, logfile):
    self._already_listed = set()
    self._logfile = logfile

  def start_suite(self, *args, **kwargs):
    raise CallNotExpectedError()

  def restart_suite(self, *args, **kwargs):
    raise CallNotExpectedError()

  def abort_suite(self, *args, **kwargs):
    raise CallNotExpectedError()

  def finish_suite(self, *args, **kwargs):
    # Note: This is called. We intentionally do nothing in response.
    pass

  def start_test(self, *args, **kwargs):
    raise CallNotExpectedError()

  def finish_test(self, scoreboard, test_name, test_status, test_duration):
    # TODO(lpique): Add a "prepare_suite" call used by the prepare code path.
    # Print messages in finish_test because only finish_test and finish_suite
    # are called in the case of prepare_only path.
    # As finish_test is called per test method, limit the output per suite so
    # that the output does not get too verbose.
    if scoreboard.name not in self._already_listed:
      self._logfile.write('Preparing: %s\n' % scoreboard.name)
      self._already_listed.add(scoreboard.name)

  def finalize_run(self, *args, **kwargs):
    raise CallNotExpectedError()

  def report_expected_results(self, *args, **kwargs):
    raise CallNotExpectedError()


class SuiteResultsBuildBot(SuiteResultsBase):
  """Generates a log of test results for use on a build bot.

  Accumulates the results of running each test, and logs a summary of the final
  status at the end.
  """
  def __init__(self, scoreboard_list, warn_on_failure, logger):
    self._all_suites = scoreboard_list
    self._any_tests_finished = False
    self._important_warnings = set()
    self._logger = logger
    self._run_end_time = None
    # TODO(lpique): add a more explicit start_run callback and set the start
    # time there.
    self._run_start_time = time.time()
    self._warn_on_failure = warn_on_failure

  def _get_run_result(self):
    if not self._any_tests_finished:
      return _RUN_RESULT_BAD

    count_tests_bad = self._count_tests_bad()

    # TODO(lpique) _warn_on_failure will become _warn_if_failures_reasonable,
    # and reasonable will mean half the known tests do not fail.
    if count_tests_bad > 0 and not self._warn_on_failure:
      return _RUN_RESULT_BAD

    if (count_tests_bad or self._count_tests_to_warn() or
        self._important_warnings):
      return _RUN_RESULT_WARNING

    return _RUN_RESULT_GOOD

  def _count_tests_for_status_list(self, status_list):
    # TODO(lpique): Make _get_count public.
    return sum(scoreboard._get_count(status)
               for status in status_list
               for scoreboard in self._all_suites)

  def _count_tests_bad(self):
    """The count of tests that resolve to an bad status."""
    return self._count_tests_for_status_list(_BAD_STATUS)

  def _count_tests_bad_limit(self):
    """The maximum count of bad tests that might not mean failure."""
    if self._warn_on_failure:
      return self._count_tests_known()
    else:
      return 0

  def _count_tests_known(self):
    """The total count of tests known."""
    return sum(scoreboard.total for scoreboard in self._all_suites)

  def _count_tests_attempted(self):
    """The total count of tests that passed."""
    return self._count_tests_for_status_list(_ATTEMPTED_STATUS)

  def _count_tests_passed(self):
    """The total count of tests that passed."""
    return self._count_tests_for_status_list(_PASS_STATUS)

  def _count_tests_to_warn(self):
    """The count of tests that resolved to a warnable status."""
    return self._count_tests_for_status_list(_TO_WARN_STATUS)

  def _get_tests_for_status(self, status):
    result = []
    for scoreboard in self._all_suites:
      # TODO(lpique): Make _get_list public.
      result.extend('%s:%s' % (scoreboard.name, test_name)
                    for test_name in scoreboard._get_list(status))
    return result

  def start_suite(self, scoreboard):
    pass

  def restart_suite(self, scoreboard, num_retried_tests):
    # TODO(lpique): Move logic out.  Caller should instead be calling warn()
    # directly.
    incomplete = scoreboard.get_incomplete_tests()
    if incomplete:
      self.warn(
          'Retrying %d tests in %s that did not complete.\n' %
          (len(incomplete), scoreboard.name),
          'Retry: %s' % scoreboard.name)
    blacklist = scoreboard.get_incomplete_blacklist()
    if blacklist:
      self.warn(
          'Blacklisting %d tests in %s that did not complete\n' %
          (len(blacklist), scoreboard.name),
          'Blacklist: %s' % scoreboard.name)
    self.warn_logonly('Retrying %d tests in %s.\n' %
                      (num_retried_tests, scoreboard.name))

  def abort_suite(self, scoreboard):
    self.warn('Aborting running %s -- the number of tests remaining to run is'
              ' not decreasing.' % scoreboard.name,
              'Abort: %s' % scoreboard.name)

  def start_test(self, scoreboard, test_name):
    self._logger.log_test_status_start(
        scoreboard.name, scoreboard.completed + 1, scoreboard.total, test_name)

  def finish_test(self, scoreboard, test_name, test_status, test_duration):
    self._any_tests_finished = True

    self._logger.log_test_status_update(
        scoreboard.name, scoreboard.completed, scoreboard.total, test_name,
        test_status, test_duration)

  def finish_suite(self, scoreboard):
    self._logger.log_scoreboard_finish_status(scoreboard)
    if scoreboard.overall_status not in _GOOD_STATUS:
      self._logger.log_build_step_text('Failure: %s' % scoreboard.name)

  def warn_logonly(self, log_message):
    """Just shows a warning in the log, not changing the buildbot result."""
    self._logger.log_message(log_message)

  def warn(self, log_message, bot_message):
    """Records an important warning reported as the buildbot warning.

    Args:
      log_message: The message to log for the warning.
      bot_message: The message emitted as annotations after deduplication when
          the run end result is _RUN_RESULT_WARNING. The warning messages are
          suppressed if any failure occurred elsewhere.
    """
    self._logger.log_message(log_message)
    self._important_warnings.add(bot_message)

  # TODO(lpique): Split into finalizing the run, and getting the final stats.
  def finalize_run(self, output_dir):
    self._run_end_time = time.time()

    self._logger.log_newline()

    # Log the output from any test where that status indicates we should log it.
    for scoreboard in self._all_suites:
      # TODO(lpique): Make _get_count public.
      if any(scoreboard._get_count(status)
             for status in _TO_LOG_OUTPUT_STATUS):
        self._logger.log_test_raw_output(
            scoreboard.name, os.path.join(output_dir, scoreboard.name))

    # Log the stats for each scoreboard.
    self._logger.log_scoreboards_stats(
        scoreboard for scoreboard in self._all_suites)

    # Log a list of any tests with a status that we should generate a list for
    # (generally test that failed on some way).
    for status in _TO_LIST_STATUS:
      self._logger.log_test_name_section_for_status(
          self._get_tests_for_status(status), status)

    # Write a summary section, giving the overall stats for the run.
    self._logger.log_summary_stats(
        self._run_end_time - self._run_start_time,
        self._count_tests_attempted(),
        self._count_tests_known(),
        dict((status, self._count_tests_for_status_list([status]))
             for status in STATUS_ORDER))

    # Emit a single buildbot annotation for the highest level of failure we
    # observed.
    run_result = self._get_run_result()
    if run_result == _RUN_RESULT_BAD:
      self._logger.log_build_step_failure()
    elif run_result == _RUN_RESULT_WARNING:
      self._logger.log_build_step_warnings()
      for message in sorted(self._important_warnings):
        self._logger.log_build_step_text(message)
      for status in _TO_WARN_STATUS:
        count = self._count_tests_for_status_list([status])
        if count:
          self._logger.log_build_step_text(
              '%d %s' % (count, VERBOSE_STATUS_TEXT[status]))

    return [
        run_result == _RUN_RESULT_BAD,
        self._count_tests_passed(),
        self._count_tests_known()
    ]

  def report_expected_results(self, scoreboards):
    accum_suite_counts = collections.Counter()
    accum_test_counts = collections.Counter()

    for scoreboard in scoreboards:
      counts = _compute_count_by_expectation(scoreboard)
      status = _determine_overall_status_from_counts(counts)

      # Print out a summary message for this suite.
      self._logger.log_expected_summary_stats(counts, status, scoreboard.name)

      # Accumulate the status counts
      accum_test_counts += counts
      accum_suite_counts[status] += 1

    # Print out the status totals for all suites and all tests.
    self._logger.log_expected_totals('suites', accum_suite_counts)
    self._logger.log_expected_totals('tests', accum_test_counts)


class SuiteResultsTracing(object):
  """Handles the results for each test suite in Chrome tracing mode.

  This prints events in JSON notation compatible with chrome://tracing that
  help to visualize the timeline in which tests are executed. This wraps around
  another SuiteResultsBase object, so any method invoked on this class will also
  call the wrapped object.
  """

  def __init__(self, wrapped_suite_results, tracing_file):
    self._wrapped = wrapped_suite_results
    self._started_suites = set()
    self._tracing_log = open(tracing_file, 'w')
    self._tracing_log.write('[')
    self._tracing_log.flush()

  def _event(self, name, event_type):
    return {
        'name': name,
        'ph': event_type,
        'pid': 1,
        'tid': threading.current_thread().ident,
        'ts': time.time() * 1e6,
    }

  def _write_start_suite_event(self, suite_name):
    if suite_name not in self._started_suites:
      event = self._event(suite_name, 'B')
      self._tracing_log.write(json.dumps(event) + ',\n')
      self._tracing_log.flush()
      self._started_suites.add(suite_name)

  def _write_restart_suite_event(self, suite_name):
    event = self._event(suite_name, 'E')
    event['args'] = {
        'status': 'Restarted',
    }
    self._tracing_log.write(json.dumps(event) + ',\n')
    self._tracing_log.flush()
    self._started_suites.discard(suite_name)

  def _write_finish_test_event(self, suite_name, test_name, test_status,
                               test_duration):
    begin = (time.time() - test_duration) * 1e6
    if suite_name not in self._started_suites:
      event = self._event(suite_name, 'B')
      event['ts'] = begin
      self._tracing_log.write(json.dumps(event) + ',\n')
      self._tracing_log.flush()
      self._started_suites.add(suite_name)
    event = self._event(test_name, 'X')
    event['ts'] = begin
    event['dur'] = test_duration * 1e6
    event['args'] = {
        'status': VERBOSE_STATUS_TEXT[test_status],
    }
    self._tracing_log.write(json.dumps(event) + ',\n')
    self._tracing_log.flush()

  def _write_finish_suite_event(self, suite_name, suite_status):
    event = self._event(suite_name, 'E')
    event['args'] = {
        'status': VERBOSE_STATUS_TEXT[suite_status],
    }
    if suite_name not in self._started_suites:
      event['ph'] = 'X'
      event['dur'] = 1000
    self._tracing_log.write(json.dumps(event) + ',\n')
    self._tracing_log.flush()

  def start_suite(self, *args, **kwargs):
    return self._wrapped.start_suite(*args, **kwargs)

  def start_test(self, scoreboard, test):
    # TODO(lpique): Investigate moving this to start_suite
    self._write_start_suite_event(scoreboard.name)
    self._wrapped.start_test(scoreboard, test)

  def abort_suite(self, *args, **kwargs):
    self._wrapped.abort_suite(*args, **kwargs)

  def restart_suite(self, scoreboard, num_retried_tests):
    self._write_restart_suite_event(scoreboard.name)
    self._wrapped.restart_suite(scoreboard, num_retried_tests)

  def finish_test(self, scoreboard, test_name, test_status, test_duration):
    self._write_finish_test_event(scoreboard.name, test_name, test_status,
                                  test_duration)
    self._wrapped.finish_test(scoreboard, test_name, test_status, test_duration)

  def finish_suite(self, scoreboard):
    self._write_finish_suite_event(scoreboard.name, scoreboard.overall_status)
    self._wrapped.finish_suite(scoreboard)

  def finalize_run(self, *args, **kwargs):
    return self._wrapped.finalize_run(*args, **kwargs)

  def report_expected_results(self, *args, **kwargs):
    return self._wrapped.report_expected_results(*args, **kwargs)


def initialize(test_driver_list, args, prepare_only=False):
  # TODO(lpique): Eliminate global singleton.
  global SuiteResults

  # TODO(lpique): Push conversion to caller.
  scoreboard_list = [test_driver.scoreboard
                     for test_driver in test_driver_list]

  if prepare_only:
    results = SuiteResultsPrepare(sys.stdout)
  else:
    results = SuiteResultsBuildBot(
        scoreboard_list, args.warn_on_failure,
        FormattedLogger(sys.stdout, args.output == 'verbose'))

  if args.tracing:
    # The SuiteResultsTracing acts as a wrapper around whatever SuiteResults
    # object was originally chosen. This allows to non-intrusively collect
    # tracing information.
    results = SuiteResultsTracing(results, args.tracing)

  SuiteResults = synchronized_interface.Synchronized(results)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def summarize(output_dir):
  if SuiteResults:
    return SuiteResults.finalize_run(output_dir)

  pass_count = 0
  total_count = 0
  overall_failure = False
  return (overall_failure, pass_count, total_count)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_start(scoreboard):
  if SuiteResults:
    SuiteResults.start_suite(scoreboard)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_restart(scoreboard, num_retried_tests):
  if SuiteResults:
    SuiteResults.restart_suite(scoreboard, num_retried_tests)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_abort(scoreboard):
  if SuiteResults:
    SuiteResults.abort_suite(scoreboard)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_start_test(scoreboard, test):
  if SuiteResults:
    SuiteResults.start_test(scoreboard, test)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_update_test(scoreboard, name, status, duration=0):
  if SuiteResults:
    SuiteResults.finish_test(scoreboard, name, status, duration)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_results(scoreboard):
  if SuiteResults:
    SuiteResults.finish_suite(scoreboard)


# TODO(lpique) Eliminate this public interface and instead directly invoke the
# method on an instance known to the caller.
def report_expected_results(score_boards):
  if SuiteResults:
    SuiteResults.report_expected_results(score_boards)
