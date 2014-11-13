# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides a class to determine if the given test should run or not."""

import fnmatch

from util.test import suite_runner_config_flags as flags


def _match_pattern_list(name, pattern_list):
  """Returns True if |name| matches to any of patterns in the list."""
  return any(fnmatch.fnmatch(name, pattern) for pattern in pattern_list)


class TestFilter(object):
  def __init__(self,
               include_pattern_list=None, exclude_pattern_list=None,
               include_fail=False, include_large=False,
               include_timeout=False, include_requires_opengl=False):
    self._include_pattern_list = include_pattern_list or []
    self._exclude_pattern_list = exclude_pattern_list or []

    # PASS or FLAKY tests are included into the list of tests to run by
    # default, and then run.
    # FAIL or LARGE tests are included upon request (practically controlled by
    # --include-failing and --include-large options in run_integration_tests).
    # When included, they run.
    # TIMEOUT tests are also included upon request (practically controlled by
    # --include-timeouts option). When included, they run also upon request.
    # Note that the behavior is slightly different from FAIL or LARGE ones.
    # All these tests are included if the name matches with patterns (if
    # specified) regardless of the flags. In such a case, FAIL or LARGE
    # tests will run, but TIMEOUT tests will not (unless requested).
    # REQUIRES_OPENGL tests are similar to TIMEOUT. Note that practically
    # they are not controlled by runtime flags, but its condition is calculated
    # implicitly from other conditions about OpenGL.
    # NOT_SUPPORTED tests are not included by default. Even if it matches the
    # patterns, it will never run.

    # Map from a primitive flag to bool representing whether the test case
    # should be included in the list.
    self._include_expectation_map = {
        flags.PASS: True,
        flags.FAIL: include_fail,
        flags.TIMEOUT: include_timeout,
        flags.NOT_SUPPORTED: False,
        flags.LARGE: include_large,
        flags.FLAKY: True,
        flags.REQUIRES_OPENGL: include_requires_opengl,
    }

    # Map from a primitive flag to bool representing whether the test case
    # should actually run.
    self._run_expectation_map = {
        flags.PASS: True,
        flags.FAIL: True,
        flags.TIMEOUT: include_timeout,
        flags.NOT_SUPPORTED: False,
        flags.LARGE: True,
        flags.FLAKY: True,
        flags.REQUIRES_OPENGL: include_requires_opengl,
    }

  def should_include(self, name, expectation):
    if not self._include_pattern_list:
      # If include pattern is not set, infer from the expectation.
      # We include it only when all flags say the test should include.
      result = all(self._include_expectation_map[flag] for flag in expectation)
    else:
      result = _match_pattern_list(name, self._include_pattern_list)

    return result and not _match_pattern_list(name, self._exclude_pattern_list)

  def should_run(self, expectation):
    # The test should run only when all flags say the test can run.
    return all(self._run_expectation_map[flag] for flag in expectation)
