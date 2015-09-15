# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time

from src.build.util.test import flags
from src.build.util.test import suite_results
from src.build.util.test import scoreboard_constants


class Scoreboard:
  """A class used to track test results and overall status of a SuiteRunner."""

  # This special name is used to denote all tests that are a part of a suite.
  # This allows exceptions to be placed on all tests, rather than having
  # to specify them individually.
  # TODO(haroonq): All sorts of weird problems occur if we have a test named
  # '*'.  Unfortunately, for several tests (like the dalvik tests), we do not
  # actually have test names, so ALL_TESTS_DUMMY_NAME is being used instead.
  # Ideally, this class should not really have any 'special' test name and
  # treat all test names the same.  Instead, the expectations should be
  # expanded out by the owning class before it reaches here.
  ALL_TESTS_DUMMY_NAME = '*'

  # The (internal) expectations for individual tests.
  _SHOULD_PASS = 0
  _SHOULD_FAIL = 1
  _SHOULD_SKIP = 2
  _MAYBE_FLAKY = 3

  _MAP_EXPECTATIONS_TO_RESULT = {
      _SHOULD_FAIL: scoreboard_constants.EXPECTED_FAIL,
      _MAYBE_FLAKY: scoreboard_constants.EXPECTED_FLAKE,
      _SHOULD_SKIP: scoreboard_constants.SKIPPED,
      _SHOULD_PASS: scoreboard_constants.EXPECTED_PASS,
  }

  def __init__(self, name, expectations):
    self._name = name
    self._complete_count = 0
    self._restart_count = 0
    self._start_time = None
    self._end_time = None
    self._expectations = {}
    self._results = {}

    # Once a test has not been completed twice, it will be 'blacklisted' so
    # that the SuiteRunner can skip it going forward.
    self._did_not_complete_once = set()
    self._did_not_complete_blacklist = []

    # Update the internal expectations for the tests.
    self._default_expectation = self._SHOULD_PASS
    self.set_expectations(expectations)

  def reset_results(self, tests):
    for test in tests:
      if test != self.ALL_TESTS_DUMMY_NAME:
        self._results[test] = scoreboard_constants.INCOMPLETE

  @staticmethod
  def map_expectation_flag_to_result(ex):
    return Scoreboard._MAP_EXPECTATIONS_TO_RESULT[
        Scoreboard.map_expectation_flag_to_scoreboard_expectation(ex)]

  @staticmethod
  def map_expectation_flag_to_scoreboard_expectation(ex):
    status = ex.status
    if status == flags.NOT_SUPPORTED:
      return Scoreboard._SHOULD_SKIP
    # Tests marked as TIMEOUT will be skipped, unless --include-timeouts is
    # specified.  Unfortunately, we have no way of knowing, so we just assume
    # they will be skipped.  If it turns out that this test is actually run,
    # then it will get treated as though it was expected to PASS.  We assume
    # the TIMEOUT is not specified with FAIL or FLAKY as well.
    if status == flags.TIMEOUT:
      return Scoreboard._SHOULD_SKIP
    if status == flags.FAIL:
      return Scoreboard._SHOULD_FAIL
    if status == flags.FLAKY:
      return Scoreboard._MAYBE_FLAKY
    return Scoreboard._SHOULD_PASS

  def set_expectations(self, expectations):
    """
    Specify test suite expectations.

    In addition to settings expectations at creation time, additional
    expectations can be defined later once more information is known about
    the tests.
    """
    if not expectations:
      return
    for name, ex in expectations.iteritems():
      expectation = self.map_expectation_flag_to_scoreboard_expectation(ex)
      if name == self.ALL_TESTS_DUMMY_NAME:
        self._default_expectation = expectation
      else:
        self._expectations[name] = expectation

  def register_tests(self, tests_to_run):
    """
    Call only once when the suite is being started to run with the list of
    tests that are expected to run.
    """
    self._start_time = time.time()
    suite_results.report_start(self)
    for name in tests_to_run:
      if self.ALL_TESTS_DUMMY_NAME in name:
        continue
      self._register_test(name)

  def start(self, tests_to_run):
    """
    Sets the results for the specified tests to INCOMPLETE.

    This is done even if the test has been run before since it is needed when
    rerunning flaky tests.
    """
    for name in tests_to_run:
      if self.ALL_TESTS_DUMMY_NAME in name:
        continue
      assert name in self._expectations
      self._results[name] = scoreboard_constants.INCOMPLETE

  def restart(self, num_retried_tests):
    """
    Notifies the scoreboard that the tests are going to be restarted.

    This is most likely to rerun any incomplete or flaky tests.
    """
    for name, result in self._results.iteritems():
      # All remaining tests were not completed (most likely due to other
      # failures or timeouts).
      if result == scoreboard_constants.INCOMPLETE:
        if name in self._did_not_complete_once:
          self._did_not_complete_blacklist.append(name)
        else:
          self._did_not_complete_once.add(name)
    self._restart_count += 1
    suite_results.report_restart(self, num_retried_tests)

  def abort(self):
    """Notifies the scoreboard that test runs are being ended prematurely."""
    suite_results.report_abort(self)

  def start_test(self, test):
    """Notifies the scoreboard that a single test is about to be run."""
    suite_results.report_start_test(self, test)

  def update(self, tests):
    """Updates the scoreboard with a list of TestMethodResults."""
    for test in tests:
      expect = self._default_expectation
      if self.ALL_TESTS_DUMMY_NAME in test.name:
        if len(self._expectations) != 0:
          continue
      else:
        self._register_test(test.name)
        expect = self._expectations[test.name]
      if test and test.passed:
        result = scoreboard_constants.EXPECTED_PASS
      else:
        result = scoreboard_constants.EXPECTED_FAIL
      actual = self._determine_actual_status(result, expect)
      self._set_result(test.name, actual)
      self._complete_count += 1
      suite_results.report_update_test(self, test.name, actual, test.duration)

  def finalize(self):
    """
    Notifies the scoreboard that the test suite is finished.

    It is expected that the suite will not be run again.  Any tests that did
    not run will be marked as SKIPPED and any flaky tests will be marked as
    UNEXPECTED_FAIL.
    """
    if not self._expectations and not self._results:
      # Expectations were likely not set because the test does not specify
      # expectations so ALL_TESTS_DUMMY_NAME was used. Results should not be
      # empty. Any valid test should report at least one test result so we will
      # mark the entire suite as INCOMPLETE.
      self._set_result(
          self.ALL_TESTS_DUMMY_NAME, scoreboard_constants.INCOMPLETE)
      suite_results.report_update_test(self,
                                       self.ALL_TESTS_DUMMY_NAME,
                                       scoreboard_constants.INCOMPLETE)
    else:
      for name, ex in self._expectations.iteritems():
        self._finalize_test(name, ex)
    self._end_time = time.time()
    suite_results.report_results(self)

  @property
  def name(self):
    return self._name

  @property
  def duration(self):
    start_time = self._start_time or time.time()
    end_time = self._end_time or time.time()
    return end_time - start_time

  # This is the expected total number of tests in a suite.  This value can
  # change over time (eg. as flaky tests are rerun or new tests are
  # discovered).  As such, there is no correlation between the total and the
  # completed/incompleted properties.
  @property
  def total(self):
    # If a test suite has a scoreboard, we have to assume that at least one
    # test will be run.  len(self._expectations) can be zero if only a '*'
    # expectation was specified.
    return max(self._complete_count, len(self._expectations), 1)

  @property
  def completed(self):
    return self._complete_count

  @property
  def incompleted(self):
    return len(self.get_incomplete_tests())

  @property
  def passed(self):
    return self.expected_passed + self.unexpected_passed

  @property
  def failed(self):
    return self.expected_failed + self.unexpected_failed

  @property
  def expected_passed(self):
    return self._get_count(scoreboard_constants.EXPECTED_PASS)

  @property
  def unexpected_passed(self):
    return self._get_count(scoreboard_constants.UNEXPECTED_PASS)

  @property
  def expected_failed(self):
    return self._get_count(scoreboard_constants.EXPECTED_FAIL)

  @property
  def unexpected_failed(self):
    return self._get_count(scoreboard_constants.UNEXPECTED_FAIL)

  @property
  def skipped(self):
    return self._get_count(scoreboard_constants.SKIPPED)

  @property
  def restarts(self):
    return self._restart_count

  def get_flaky_tests(self):
    return self._get_list(scoreboard_constants.EXPECTED_FLAKE)

  def get_skipped_tests(self):
    return self._get_list(scoreboard_constants.SKIPPED)

  def get_incomplete_tests(self):
    return self._get_list(scoreboard_constants.INCOMPLETE)

  def get_expected_passing_tests(self):
    return self._get_list(scoreboard_constants.EXPECTED_PASS)

  def get_unexpected_passing_tests(self):
    return self._get_list(scoreboard_constants.UNEXPECTED_PASS)

  def get_expected_failing_tests(self):
    return self._get_list(scoreboard_constants.EXPECTED_FAIL)

  def get_unexpected_failing_tests(self):
    return self._get_list(scoreboard_constants.UNEXPECTED_FAIL)

  def _get_list(self, result):
    return [key for key, value in self._results.iteritems() if value == result]

  def _get_count(self, result):
    return self._results.values().count(result)

  def get_incomplete_blacklist(self):
    return self._did_not_complete_blacklist

  @property
  def overall_status(self):
    if self.incompleted:
      return scoreboard_constants.INCOMPLETE
    elif self.unexpected_failed:
      return scoreboard_constants.UNEXPECTED_FAIL
    elif self.unexpected_passed:
      return scoreboard_constants.UNEXPECTED_PASS
    elif self.expected_failed:
      return scoreboard_constants.EXPECTED_FAIL
    elif self.skipped and not self.passed:
      return scoreboard_constants.SKIPPED
    else:
      return scoreboard_constants.EXPECTED_PASS

  def _register_test(self, name):
    if name not in self._expectations:
      self._expectations[name] = self._SHOULD_PASS
      self._set_result(name, scoreboard_constants.INCOMPLETE)

  def _set_result(self, name, result):
    if (name in self._did_not_complete_blacklist and
        result != scoreboard_constants.INCOMPLETE):
      self._did_not_complete_blacklist.remove(name)
    self._results[name] = result

  def _finalize_test(self, name, expect):
    assert self._is_valid_expectation(expect)

    if expect in [self._SHOULD_PASS, self._SHOULD_FAIL]:
      # This test was never started, so record and report it as being skipped.
      if name not in self._results:
        self._set_result(name, scoreboard_constants.SKIPPED)
        # We are officially marking the test completed so that the total
        # tests adds up correctly.
        self._complete_count += 1
        suite_results.report_update_test(
            self, name, scoreboard_constants.SKIPPED)
      # This test had no chance to start, or was started but never completed.
      # Report it as incomplete.
      elif self._results[name] == scoreboard_constants.INCOMPLETE:
        suite_results.report_update_test(
            self, name, scoreboard_constants.INCOMPLETE)
    # This test was expected to be skipped and we have no results (ie. it
    # really was skipped) so record and report it as such.  Note: It is
    # possible for tests that were expected to be skipped to be run.  See
    # comment about TIMEOUT above.
    elif expect == self._SHOULD_SKIP and name not in self._results:
      self._set_result(name, scoreboard_constants.SKIPPED)
      suite_results.report_update_test(self, name, scoreboard_constants.SKIPPED)
    # This flaky test never successfully passed, so record and report it as
    # a failure.
    elif (expect == self._MAYBE_FLAKY and
          self._results.get(name) == scoreboard_constants.EXPECTED_FLAKE):
      self._set_result(name, scoreboard_constants.UNEXPECTED_FAIL)
      suite_results.report_update_test(
          self, name, scoreboard_constants.UNEXPECTED_FAIL)
    elif (expect == self._MAYBE_FLAKY and
          self._results.get(name) == scoreboard_constants.INCOMPLETE):
      self._set_result(name, scoreboard_constants.INCOMPLETE)
      suite_results.report_update_test(
          self, name, scoreboard_constants.INCOMPLETE)

  @classmethod
  def _determine_actual_status(cls, status, expect):
    assert status in [scoreboard_constants.EXPECTED_PASS,
                      scoreboard_constants.EXPECTED_FAIL]
    assert cls._is_valid_expectation(expect)

    if status == scoreboard_constants.EXPECTED_PASS:
      if expect in [cls._SHOULD_PASS, cls._MAYBE_FLAKY]:
        return scoreboard_constants.EXPECTED_PASS
      elif expect in [cls._SHOULD_FAIL, cls._SHOULD_SKIP]:
        return scoreboard_constants.UNEXPECTED_PASS
    elif status == scoreboard_constants.EXPECTED_FAIL:
      if expect in [cls._SHOULD_PASS, cls._SHOULD_SKIP]:
        return scoreboard_constants.UNEXPECTED_FAIL
      elif expect in [cls._SHOULD_FAIL]:
        return scoreboard_constants.EXPECTED_FAIL
      elif expect in [cls._MAYBE_FLAKY]:
        return scoreboard_constants.EXPECTED_FLAKE
    return status

  @classmethod
  def _is_valid_expectation(cls, exp):
    return exp in [cls._SHOULD_PASS, cls._SHOULD_FAIL, cls._SHOULD_SKIP,
                   cls._MAYBE_FLAKY]

  def get_expectations(self):
    expectations = {}
    for name, test_expectation in self._expectations.iteritems():
      expectations[name] = self._MAP_EXPECTATIONS_TO_RESULT[test_expectation]
    if len(self._expectations) == 0:
      expectations[self.ALL_TESTS_DUMMY_NAME] = (
          self._MAP_EXPECTATIONS_TO_RESULT[self._default_expectation])
    return expectations
