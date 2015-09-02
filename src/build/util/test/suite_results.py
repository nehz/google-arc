# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import json
import os
import sys
import threading
import time

from util import color
from util import synchronized_interface
from util.test import scoreboard_constants

# The different types of message outputs.
_EXPECT_FAIL = 0
_FAIL = 1
_IMPORTANT = 2
_INFO = 3
_NORMAL = 4
_PASS = 5
_SKIPPED = 6
_WARNING = 7

# The size of the name/label column.
_LABEL_COLUMN_SIZE = 50

_ACCEPTABLE_STATUS = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.UNEXPECT_PASS,
    scoreboard_constants.SKIPPED,
)

_EXPECTATION_BY_PRIORITY = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.FLAKE,
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.SKIPPED,
)

_EXPECTED_STATUS_STRING = {
    scoreboard_constants.EXPECT_PASS: "are expected to pass",
    scoreboard_constants.EXPECT_FAIL: "are expected to fail",
    scoreboard_constants.SKIPPED: "will be skipped",
}

_PASS_STATUS = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.UNEXPECT_PASS
)

_STATUS_MODE = {
    scoreboard_constants.INCOMPLETE: _SKIPPED,
    scoreboard_constants.EXPECT_PASS: _PASS,
    scoreboard_constants.EXPECT_FAIL: _WARNING,
    scoreboard_constants.UNEXPECT_PASS: _WARNING,
    scoreboard_constants.UNEXPECT_FAIL: _FAIL,
    scoreboard_constants.SKIPPED: _SKIPPED,
    scoreboard_constants.FLAKE: _WARNING,
}

_STATUS_STRING = {
    scoreboard_constants.INCOMPLETE: 'Incomplete',
    scoreboard_constants.EXPECT_PASS: 'Passed',
    scoreboard_constants.EXPECT_FAIL: 'Expected Failures',
    scoreboard_constants.UNEXPECT_PASS: 'Unexpectedly Passed',
    scoreboard_constants.UNEXPECT_FAIL: 'Failed',
    scoreboard_constants.SKIPPED: 'Skipped',
    scoreboard_constants.FLAKE: 'Flaky',
}

_SUMMARY_STATUS_ORDER = (
    scoreboard_constants.EXPECT_PASS,
    scoreboard_constants.UNEXPECT_PASS,
    scoreboard_constants.EXPECT_FAIL,
    scoreboard_constants.UNEXPECT_FAIL,
    scoreboard_constants.INCOMPLETE,
    scoreboard_constants.SKIPPED,
)

_TERSE_STATUS = {
    scoreboard_constants.INCOMPLETE: 'I',
    scoreboard_constants.EXPECT_PASS: 'P',
    scoreboard_constants.EXPECT_FAIL: 'XF',
    scoreboard_constants.UNEXPECT_PASS: 'UP',
    scoreboard_constants.UNEXPECT_FAIL: 'F',
    scoreboard_constants.SKIPPED: 'S',
    scoreboard_constants.FLAKE: 'FK',
}


# Helper class to write formatted (i.e. colored) output.
class FormattedWriter:
  def __init__(self, format_map=None):
    self._format_map = format_map or {}

  def write(self, mode, message):
    color.write_ansi_escape(sys.stdout, self._format_map.get(mode), message)
    return len(message)

  def header(self, mode, label):
    self.write(mode, '\n######## %s ########\n' % (label))


_PLAIN_WRITER = FormattedWriter()

_ANSI_WRITER = FormattedWriter({
    _FAIL: color.RED,
    _INFO: color.CYAN,
    _NORMAL: None,
    _PASS: color.GREEN,
    _SKIPPED: color.MAGENTA,
    _WARNING: color.YELLOW,
    _IMPORTANT: color.YELLOW,
    _EXPECT_FAIL: color.YELLOW
})

_REVERSE_ANSI_WRITER = FormattedWriter({
    _FAIL: color.WHITE_ON_RED,
    _INFO: color.WHITE_ON_CYAN,
    _NORMAL: None,
    _PASS: color.WHITE_ON_GREEN,
    _SKIPPED: color.WHITE_ON_MAGENTA,
    _WARNING: color.WHITE_ON_YELLOW,
    _IMPORTANT: color.WHITE_ON_YELLOW,
    _EXPECT_FAIL: color.WHITE_ON_YELLOW
})

# The single instance of the SuiteResultsBase used for displaying results.
SuiteResults = None


def _pretty_time(time):
  return '%0.3fs' % time


def _pretty_progress(index, total):
  max_total = max(index, total)
  return '%s/%s' % (str(index).rjust(len(str(max_total)), '0'), str(max_total))


def _pretty_label(name):
  if len(name) > _LABEL_COLUMN_SIZE:
    halflen = (_LABEL_COLUMN_SIZE - 3) / 2  # Subtract 3 for the '...'
    name = name[:halflen] + '...' + name[-halflen:]
  return '%s' % name.ljust(_LABEL_COLUMN_SIZE, ' ')


def _simple_name(name):
  # The simple name of a suite is the last element of the full name which
  # is split with '.'
  return name.rsplit('.')[-1]


def _compute_percentage(count, total):
  """Handles the case of the denominator being zero."""
  return (100 * count // total) if total else 0


def _compute_counts_by_expectation(scoreboard):
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


class SuiteResultsBase(object):
  """Suite results accumulation.

  Records basically how many suites of various kinds occurred, with plain output
  presented.  Messages are formatted using the writer given during construction.
  """
  def __init__(self, test_driver_list, options, writer=_PLAIN_WRITER,
               reverse_writer=_PLAIN_WRITER):
    self._writer = writer
    self._reverse_writer = reverse_writer
    self._options = options
    self._start_time = time.time()
    self._important_warnings = []

    self._test_driver_list = test_driver_list
    self._remaining_suites = test_driver_list[:]
    self._running_suites = set()

    self._run_count = 0
    self._pass_count = 0
    self._expected_test_count = 0
    self._counters = collections.Counter()

    for test_driver in test_driver_list:
      self._expected_test_count += test_driver.scoreboard.total

  @property
  def pass_count(self):
    return self._pass_count

  @property
  def run_count(self):
    return self._run_count

  @property
  def total_count(self):
    # Some tests might end up with more tests being run than we initially know
    # about. Cleanly compensate for a larger total in the end.
    self._expected_test_count = max(self.run_count,
                                    self._expected_test_count)
    return self._expected_test_count

  @property
  def run_percent(self):
    return _compute_percentage(self.run_count, self.total_count)

  @property
  def overall_failure(self):
    if self._counters[scoreboard_constants.UNEXPECT_FAIL]:
      return True
    elif self._counters[scoreboard_constants.INCOMPLETE]:
      return True
    elif self.run_count == 0:
      return True
    else:
      return False

  def should_write(self, msgtype):
    return True

  def write(self, msgtype, message):
    if self.should_write(msgtype):
      self._writer.write(msgtype, message)

  def _get_test_driver(self, score_board):
    return next((test_driver for test_driver in self._test_driver_list
                 if test_driver.scoreboard == score_board), None)

  def start(self, score_board):
    test_driver = self._get_test_driver(score_board)
    self._running_suites.add(test_driver)
    self.report_start(test_driver)

  def restart(self, score_board):
    test_driver = self._get_test_driver(score_board)
    incomplete = score_board.get_incomplete_tests()
    if len(incomplete):
      self.warn(
          'Retrying %d tests in %s that did not complete.\n' %
          (len(incomplete), test_driver.name),
          'Retry: %s' % test_driver.name)
    blacklist = score_board.get_incomplete_blacklist()
    if len(blacklist):
      self.warn(
          'Blacklisting %d tests in %s that did not complete\n' %
          (len(blacklist), test_driver.name),
          'Blacklist: %s' % test_driver.name)
    self.warn_logonly('Retrying %d tests in %s.\n' %
                      (len(test_driver.tests_to_run), test_driver.name))
    self.report_restart(test_driver)

  def abort(self, score_board):
    self.warn('Aborting running %s -- the number of tests remaining to run is'
              ' not decreasing.' % score_board.name,
              'Abort: %s' % score_board.name)

  def start_test(self, score_board, test):
    test_driver = self._get_test_driver(score_board)
    self.report_start_test(test_driver, test)

  def update_test(self, score_board, name, status, duration):
    test_driver = self._get_test_driver(score_board)
    self._run_count += 1
    if status in _PASS_STATUS:
      self._pass_count += 1
    self._counters.update([status])
    self.report_update_test(test_driver, name, status, duration)

  def end(self, score_board):
    test_driver = self._get_test_driver(score_board)
    if test_driver in self._remaining_suites:
      self._remaining_suites.remove(test_driver)
    if test_driver in self._running_suites:
      self._running_suites.remove(test_driver)
    self.report_end(test_driver, score_board)

  def warn_logonly(self, log_message):
    """Just shows an warning on the log, not changing the buildbot result."""
    self.write(_WARNING, log_message)

  def warn(self, log_message, bot_message):
    """Records an important warning reported as the buildbot warning.

    The |bot_message| is emit as annotations after deduplication, when the
    test running step ended up in the warning state. The warning messages
    are suppressed if any failure occurred elsewhere.
    """
    self.write(_IMPORTANT, log_message)
    if bot_message not in self._important_warnings:
      self._important_warnings.append(bot_message)

  def summarize(self, output_dir):
    for suite in self._remaining_suites:
      self.end(suite.scoreboard)
    self._remaining_suites = []
    self.report_summary(output_dir)
    return [self.overall_failure, self.pass_count, self.total_count]

  def report_start(self, suite):
    pass

  def report_restart(self, suite):
    pass

  def report_start_test(self, test_driver, test):
    pass

  def report_update_test(self, test_driver, name, status, duration):
    pass

  def report_end(self, test_driver, scoreboard):
    pass

  def report_summary(self, output_dir):
    pass

  def report_expected_results(self, scoreboards):
    accum_suite_counts = collections.Counter()
    accum_test_counts = collections.Counter()

    for scoreboard in scoreboards:
      counts = _compute_counts_by_expectation(scoreboard)
      status = _determine_overall_status_from_counts(counts)

      # Print out a summary message for this suite.
      self._write_expected_summary_for_suite(status, counts, scoreboard.name)

      # Accumulate the status counts
      accum_test_counts += counts
      accum_suite_counts[status] += 1

    # Print out the status totals for all suites and all tests.
    self._write_expected_totals('suites', accum_suite_counts)
    self._write_expected_totals('tests', accum_test_counts)

  def _write_list(self, writer, mode, label, tests):
    if len(tests):
      writer.header(mode, '%s (%d)' % (label, len(tests)))
      writer.write(mode, '%s\n' % ('\n'.join(sorted(tests))))

  def _write_single_stat(self, writer, mode, value, label):
    mode = mode if value else _NORMAL
    writer.write(mode, ' % 5d%s' % (value, label))

  def _write_scoreboard_stats(self, writer, sb):
    self._write_single_stat(writer, _PASS, sb.expected_passed, 'P')
    self._write_single_stat(writer, _WARNING, sb.unexpected_passed, 'UP')
    self._write_single_stat(writer, _EXPECT_FAIL, sb.expected_failed, 'XF')
    self._write_single_stat(writer, _FAIL, sb.unexpected_failed, 'F')
    self._write_single_stat(writer, _SKIPPED, sb.incompleted, 'I')
    self._write_single_stat(writer, _SKIPPED, sb.skipped, 'S')

  def _write_status(self, writer, status, duration, terse=False):
    mode = _STATUS_MODE[status]
    status_map = _TERSE_STATUS if terse else _STATUS_STRING
    elapsed_time = _pretty_time(duration)
    writer.write(mode, '[%s:%s]' % (status_map[status], elapsed_time))

  def _write_count(self, writer, terse, status):
    if status not in self._counters:
      return 0
    status_map = _TERSE_STATUS if terse else _STATUS_STRING
    text = ' %d %s ' % (self._counters[status], status_map[status])
    return writer.write(_STATUS_MODE[status], text)

  # Returns the current position (column) of the cursor in the terminal window.
  def _write_summary(self, writer=None, terse=False, header=True):
    writer = writer if writer else self._writer
    if header:
      self._writer.header(_INFO, 'Summary')
    elapsed = time.time() - self._start_time
    w = 0
    w += writer.write(_INFO, '%02d:%02d ' % (elapsed / 60, elapsed % 60))
    w += writer.write(_INFO, '%d/%d ' % (self.run_count, self.total_count))
    w += writer.write(_INFO, '% 3s%% ' % (self.run_percent))
    if not self.total_count:
      w += writer.write(_FAIL, ' No Tests were selected to run. ')
    for status in _SUMMARY_STATUS_ORDER:
      w += self._write_count(writer, terse, status)
    if header:
      self._writer.write(_INFO, '\n')
      w = 0
    return w

  def _write_results(self):
    if self._test_driver_list:
      self._writer.header(_INFO, 'Results')
      for test_driver in sorted(self._test_driver_list,
                                key=lambda driver: driver.name):
        sb = test_driver.scoreboard
        label = _pretty_label(test_driver.name)
        self._writer.write(_NORMAL, label)
        self._write_scoreboard_stats(self._writer, sb)
        self._writer.write(_NORMAL, '  ')
        self._write_status(self._writer, sb.overall_status, sb.duration)
        self._writer.write(_NORMAL, '\n')

  def _write_raw_output(self, output_dir):
    for suite in self._test_driver_list:
      if (suite.scoreboard.unexpected_failed or
          suite.scoreboard.expected_failed or
          suite.scoreboard.incompleted):
        self._writer.header(_NORMAL, 'Raw Output: %s' % (suite.name))
        try:
          with open(os.path.join(output_dir, suite.name)) as f:
            raw_output = f.read()
        except IOError:
          raw_output = '(No log file. The suite has not started.)'
        self._writer.write(_NORMAL, raw_output)
        self._writer.write(_NORMAL, '\n')

  def _write_errors(self):
    incomplete = []
    expected_failures = []
    unexpected_passes = []
    unexpected_failures = []
    for test_driver in self._test_driver_list:
      sb = test_driver.scoreboard

      def prepend_suite_name(test):
        return '%s:%s' % (sb.name, test)

      incomplete.extend(
          map(prepend_suite_name, sb.get_incomplete_tests()))
      unexpected_passes.extend(
          map(prepend_suite_name, sb.get_unexpected_passing_tests()))
      expected_failures.extend(
          map(prepend_suite_name, sb.get_expected_failing_tests()))
      unexpected_failures.extend(
          map(prepend_suite_name, sb.get_unexpected_failing_tests()))
    self._write_list(self._writer, _WARNING, 'Unexpected Passes',
                     unexpected_passes)
    self._write_list(self._writer, _EXPECT_FAIL, 'Expected Failures',
                     expected_failures)
    self._write_list(self._writer, _FAIL, 'Unexpected Failures',
                     unexpected_failures)
    self._write_list(self._writer, _SKIPPED, 'Incomplete', incomplete)

  def _write_expected_summary_for_suite(self, status, counts, name):
    for key in _EXPECTED_STATUS_STRING:
      self._reverse_writer.write(
          _STATUS_MODE[key] if counts[key] else _NORMAL,
          " % 5d %s " % (counts[key], _TERSE_STATUS[key]))
    self._writer.write(_STATUS_MODE[status],
                       "[%- 20s]" % _STATUS_STRING[status])
    self._writer.write(_NORMAL, " %s\n" % name)

  def _write_expected_totals(self, name, accum):
    total = sum(accum[key] for key in _EXPECTED_STATUS_STRING)
    self._writer.write(_INFO, '-' * 70 + '\n')
    self._writer.write(_INFO, '%d total %s\n' % (total, name))
    for key in _EXPECTED_STATUS_STRING:
      self._writer.write(
          _INFO, "%d (%d%%) %s\n" % (
              accum[key],
              _compute_percentage(accum[key], total),
              _EXPECTED_STATUS_STRING[key]))


class SuiteResultsBuildBot(SuiteResultsBase):
  """Handles the results for each test suite in buildbot output mode.

  Accumulates the results, dumps them as the suites are run, and
  finally shows a summary of the results.  Handles verbose mode as well.
  Specifically outputs tags to indicate ultimate success/failure of
  the integration test run phase of the buildbot.
  """

  def __init__(self, test_driver_list, options):
    # TODO(elijahtaylor): Investigate HTML formatting on the bots. These HTML
    # bits are being escaped in the bot logs. For now do no formatting.
    super(SuiteResultsBuildBot, self).__init__(test_driver_list, options)
    self._warn_on_failure = options.warn_on_failure

  def _emit_step_text_annotation(self, message):
    self.write(_INFO, '\n@@@STEP_TEXT@%s<br/>@@@\n' % message)

  def _emit_step_message(self, message):
    self.write(_INFO, '\n@@@STEP_%s@@@\n' % message)

  def _report_step_result(self):
    # Emit a single buildbot annotation for the highest level of failure we
    # observed.
    if self.overall_failure:
      if self._warn_on_failure:
        # Reporting a failure on the CTS bots stops the build, but we want it to
        # continue. Report a warning instead.
        self._emit_step_message('WARNINGS')
      else:
        self._emit_step_message('FAILURE')
    elif (self._important_warnings or
          self._counters[scoreboard_constants.UNEXPECT_PASS]):
      self._emit_step_message('WARNINGS')
      for message in self._important_warnings:
        self._emit_step_text_annotation(message)
      if self._counters[scoreboard_constants.UNEXPECT_PASS]:
        self._emit_step_text_annotation(
            '%d Unexpected Passes' %
            self._counters[scoreboard_constants.UNEXPECT_PASS])

  def report_start_test(self, test_driver, test):
    if self._options.output == 'verbose':
      self.write(_NORMAL, '- ')
    sb = test_driver.scoreboard
    # Add 1 since this test is not included in the 'completed' count yet.
    progress = _pretty_progress(sb.completed + 1, sb.total)
    label = _pretty_label(sb.name + ' ' + progress)
    self.write(_NORMAL, '%s - ' % (label))
    self.write(_NORMAL, '(Running) %s\n' % (test))

  def report_update_test(self, test_driver, name, status, duration):
    if self._options.output == 'verbose':
      self.write(_NORMAL, '- ')
    sb = test_driver.scoreboard
    progress = _pretty_progress(sb.completed, sb.total)
    label = _pretty_label(sb.name + ' ' + progress)
    self.write(_NORMAL, '%s - ' % (label))
    self._write_status(self._writer, status, duration, True)
    self.write(_NORMAL, ' %s\n' % (name))

  def report_end(self, test_driver, sb):
    if self._options.output == 'verbose':
      self.write(_NORMAL, '- ')
    label = _pretty_label(test_driver.name)
    self.write(_NORMAL, '%s # ' % (label))
    self._write_status(self._writer, sb.overall_status, sb.duration, True)
    self._write_scoreboard_stats(self._writer, sb)
    self.write(_NORMAL, '\n')
    if sb.overall_status not in _ACCEPTABLE_STATUS:
      self._emit_step_text_annotation('Failure: %s' % sb.name)

  def report_summary(self, output_dir):
    self.write(_NORMAL, '\n')
    self._write_raw_output(output_dir)
    self._write_results()
    self._write_errors()
    self._write_summary()
    self._report_step_result()


class SuiteResultsAnsi(SuiteResultsBase):
  """Handles the results for each test suite for non-buildbot output modes.

  Accumulates the results, dumps them as the suites are run, and
  finally shows a summary of the results.  Handles verbose mode as well.
  """

  def __init__(self, test_driver_list, options):
    super(SuiteResultsAnsi, self).__init__(
        test_driver_list, options, writer=_ANSI_WRITER,
        reverse_writer=_REVERSE_ANSI_WRITER)

  def should_write(self, message_type):
    if message_type != _FAIL:  # TODO(lpique) check verbose!
      return False
    return True

  def _write_running_tests(self, writer, remaining):
    txt = ' ' + ' '.join(_simple_name(ss.name) for ss in self._running_suites)
    if len(txt) > remaining:
      txt = txt[:remaining - 2] + ' +'
    writer.write(_NORMAL, txt)

  def _write_progress(self):
    writer = self._reverse_writer

    remaining = color.get_terminal_width()
    remaining -= self._write_summary(writer, terse=True, header=False)
    remaining -= writer.write(_INFO, ' %d jobs ' % len(self._running_suites))
    self._write_running_tests(writer, remaining)

  def _update_progress(self):
    if sys.stdout.isatty():
      color.write_ansi_escape(sys.stdout, color.CLEAR_TO_LINE_END, '')
      self._write_progress()
      color.write_ansi_escape(sys.stdout, color.CURSOR_TO_LINE_BEGIN, '')

  def report_start(self, suite):
    self._update_progress()

  def report_update_test(self, test_driver, name, status, duration):
    self._update_progress()

  def report_results(self, suite_name, is_completed=True):
    self._update_progress()

  def report_summary(self, output_dir):
    self.write(_NORMAL, '\n')
    self._write_raw_output(output_dir)
    self._write_results()
    self._write_errors()
    self._write_summary(terse=True)


class SuiteResultsTracing(object):
  """Handles the results for each test suite in Chrome tracing mode.

  This prints events in JSON notation compatible with chrome://tracing that
  help to visualize the timeline in which tests are executed. This wraps around
  another SuiteResultsBase object, so any method invoked on this class will also
  call the wrapped object.
  """

  def __init__(self, wrapped_suite_results, test_driver_list, options):
    self._wrapped = wrapped_suite_results
    self._started_tests = set()
    self._tracing_log = open(options.tracing, 'w')
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

  def start_test(self, score_board, test):
    test_driver = self._wrapped._get_test_driver(score_board)
    if test_driver.name not in self._started_tests:
      event = self._event(test_driver.name, 'B')
      self._tracing_log.write(json.dumps(event) + ',\n')
      self._tracing_log.flush()
      self._started_tests.add(test_driver.name)

    self._wrapped.start_test(score_board, test)

  def restart(self, score_board):
    test_driver = self._wrapped._get_test_driver(score_board)
    event = self._event(test_driver.name, 'E')
    event['args'] = {
        'status': 'Restarted',
    }
    self._tracing_log.write(json.dumps(event) + ',\n')
    self._tracing_log.flush()
    self._started_tests.remove(test_driver.name)

    self._wrapped.restart(score_board)

  def update_test(self, score_board, name, status, duration):
    test_driver = self._wrapped._get_test_driver(score_board)
    begin = (time.time() - duration) * 1e6
    if test_driver.name not in self._started_tests:
      event = self._event(test_driver.name, 'B')
      event['ts'] = begin
      self._tracing_log.write(json.dumps(event) + ',\n')
      self._tracing_log.flush()
      self._started_tests.add(test_driver.name)
    event = self._event(name, 'X')
    event['ts'] = begin
    event['dur'] = duration * 1e6
    event['args'] = {
        'status': _STATUS_STRING[status],
    }
    self._tracing_log.write(json.dumps(event) + ',\n')
    self._tracing_log.flush()

    self._wrapped.update_test(score_board, name, status, duration)

  def end(self, score_board):
    test_driver = self._wrapped._get_test_driver(score_board)
    event = self._event(test_driver.name, 'E')
    event['args'] = {
        'status': _STATUS_STRING[score_board.overall_status],
    }
    if test_driver.name not in self._started_tests:
      event['ph'] = 'X'
      event['dur'] = 1000
    self._tracing_log.write(json.dumps(event) + ',\n')
    self._tracing_log.flush()

    self._wrapped.end(score_board)

  def __getattr__(self, name):
    return getattr(self._wrapped, name)


class SuiteResultsPrepare(SuiteResultsBase):
  """Outputs the progress of preparing files for remote executions."""

  def __init__(self, test_driver_list, options):
    super(SuiteResultsPrepare, self).__init__(test_driver_list, options)
    self._suites = set()

  def report_update_test(self, test_driver, name, status, duration):
    # Print messages in report_update_test because only report_update_test and
    # report_end are called in the case of prepare_only path.
    # As report_update_test is called per test method, limit the output per
    # suite so that the output does not get too verbose.
    if test_driver.name not in self._suites:
      self._writer.write(_INFO, 'Preparing: %s\n' % test_driver.name)
      self._suites.add(test_driver.name)


def initialize(test_driver_list, args, prepare_only):
  global SuiteResults
  if prepare_only:
    results = SuiteResultsPrepare(test_driver_list, args)
  elif args.ansi:
    results = SuiteResultsAnsi(test_driver_list, args)
  else:
    results = SuiteResultsBuildBot(test_driver_list, args)
  if args.tracing:
    # The SuiteResultsTracing acts as a wrapper around whatever SuiteResults
    # object was originally chosen. This allows to non-intrusively collect
    # tracing information.
    results = SuiteResultsTracing(results, test_driver_list, args)
  SuiteResults = synchronized_interface.Synchronized(results)


def summarize(output_dir):
  if SuiteResults:
    return SuiteResults.summarize(output_dir)
  else:
    pass_count = 0
    total_count = 0
    overall_failure = False
    return (overall_failure, pass_count, total_count)


def report_start(score_board):
  if SuiteResults:
    SuiteResults.start(score_board)


def report_restart(score_board):
  if SuiteResults:
    SuiteResults.restart(score_board)


def report_abort(score_board):
  if SuiteResults:
    SuiteResults.abort(score_board)


def report_start_test(score_board, test):
  if SuiteResults:
    SuiteResults.start_test(score_board, test)


def report_update_test(score_board, name, status, duration=0):
  if SuiteResults:
    SuiteResults.update_test(score_board, name, status, duration)


def report_results(score_board):
  if SuiteResults:
    SuiteResults.end(score_board)


def report_expected_results(score_boards):
  if SuiteResults:
    SuiteResults.report_expected_results(score_boards)
