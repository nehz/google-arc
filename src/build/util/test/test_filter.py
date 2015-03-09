# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides a class to determine if the given test should run or not."""

import fnmatch

from util.test import suite_runner_config_flags as flags


def _match_pattern_list(name, pattern_list):
  """Returns True if |name| matches to any of patterns in the list."""
  return any(fnmatch.fnmatch(name, pattern) for pattern in pattern_list)


class TestListFilter(object):
  def __init__(self, include_pattern_list=None, exclude_pattern_list=None):
    # Use '*' for include pattern by default, which means, include all
    # tests by default.
    self._include_pattern_list = include_pattern_list or ['*']
    self._exclude_pattern_list = exclude_pattern_list or []

  def should_include(self, test_name):
    return (_match_pattern_list(test_name, self._include_pattern_list) and
            not _match_pattern_list(test_name, self._exclude_pattern_list))


class TestRunFilter(object):
  def __init__(self,
               include_fail=False, include_large=False, include_timeout=False):
    # Map from a primitive flag to bool representing whether the test case
    # should actually run.
    # PASS, FLAKY tests will run always.
    # FAIL, LARGE, TIMEOUT tests will run iff their corresponding flag is set.
    # NOT_SUPPORTED tests will never run.
    self._run_expectation_map = {
        flags.PASS: True,
        flags.FAIL: include_fail,
        flags.TIMEOUT: include_timeout,
        flags.NOT_SUPPORTED: False,
        flags.LARGE: include_large,
        flags.FLAKY: True,
    }

  def should_run(self, expectation):
    # The test should run only when all flags say the test can run.
    return all(self._run_expectation_map[flag] for flag in expectation)
