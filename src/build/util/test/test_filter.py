# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides a class to determine if the given test should run or not."""

import fnmatch
import re

from util.test import suite_runner_config_flags as flags


def _build_re(pattern_list):
  """Builds a regular expression string from |pattern_list|.

  The regular expression will match if any of the glob patterns listed match. It
  can be used to replace:

    any(fnmatch.fnmatch(name, pattern) for pattern in pattern_list)

  with:

    bool(re.match(_build_any_pattern_match_re(pattern_list), name))
  """
  # An empty list would match any string, which is not what is intended. Handle
  # it by using a regular expression which is guaranteed to match nothing.
  if not pattern_list:
    return re.compile('(?!)')
  return re.compile(
      '|'.join(r'(?:%s)' % fnmatch.translate(pattern)
               for pattern in pattern_list))


class TestListFilter(object):
  def __init__(self, include_pattern_list=None, exclude_pattern_list=None):
    # By default we include all test names and exclude none of them.
    self._include_re = _build_re(include_pattern_list or ['*'])
    self._exclude_re = _build_re(exclude_pattern_list or [])

  def should_include(self, test_name):
    return (bool(self._include_re.match(test_name) and
                 not self._exclude_re.match(test_name)))


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
