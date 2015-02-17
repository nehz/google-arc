#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util.test import suite_runner_config_flags as flags
from util.test import test_filter


class TestFilterTest(unittest.TestCase):
  def _test_should_include_internal(
      self, name, expectation, expected_without_pattern, **kwargs):
    # Check the default behavior of should_include.
    instance = test_filter.TestFilter(**kwargs)
    self.assertEquals(
        expected_without_pattern, instance.should_include(name, expectation))

    # If the name matches to include_pattern, it should be included.
    instance = test_filter.TestFilter(include_pattern_list=['*'], **kwargs)
    self.assertTrue(instance.should_include(name, expectation))

    # If the name matches to exclude_pattern, it should not be included.
    instance = test_filter.TestFilter(exclude_pattern_list=['*'], **kwargs)
    self.assertFalse(instance.should_include(name, expectation))

    # If the name matches to both patterns, it should not be included.
    instance = test_filter.TestFilter(
        include_pattern_list=['*'], exclude_pattern_list=['*'], **kwargs)
    self.assertFalse(instance.should_include(name, expectation))

  def test_should_include(self):
    # PASS or FLAKY tests should be included by default.
    # NOT_SUPPORTED tests should not be included by default.
    # The default behavior for FAIL, TIMEOUT, LARGE and REQUIRES_OPENGL tests
    # is controlled by include_fail, include_timeout, include_large and
    # include_requires_opengl respectively.
    self._test_should_include_internal(
        'test_name', flags.PASS, expected_without_pattern=True)

    self._test_should_include_internal(
        'test_name', flags.FAIL, expected_without_pattern=False,
        include_fail=False)
    self._test_should_include_internal(
        'test_name', flags.FAIL, expected_without_pattern=True,
        include_fail=True)

    self._test_should_include_internal(
        'test_name', flags.TIMEOUT, expected_without_pattern=False,
        include_timeout=False)
    self._test_should_include_internal(
        'test_name', flags.TIMEOUT, expected_without_pattern=True,
        include_timeout=True)

    self._test_should_include_internal(
        'test_name', flags.NOT_SUPPORTED, expected_without_pattern=False)

    self._test_should_include_internal(
        'test_name', flags.LARGE, expected_without_pattern=False,
        include_large=False)
    self._test_should_include_internal(
        'test_name', flags.LARGE, expected_without_pattern=True,
        include_large=True)

    self._test_should_include_internal(
        'test_name', flags.FLAKY, expected_without_pattern=True)

    self._test_should_include_internal(
        'test_name', flags.REQUIRES_OPENGL, expected_without_pattern=False,
        include_requires_opengl=False)
    self._test_should_include_internal(
        'test_name', flags.REQUIRES_OPENGL, expected_without_pattern=True,
        include_requires_opengl=True)

  def test_should_include_pattern(self):
    # Tests for pattern matching. include_pattern_list and exclude_pattern_list
    # takes a list of patterns. Each is effective, if one of the pattern
    # matches the name.
    instance = test_filter.TestFilter(
        include_pattern_list=['test_name_include', 'test_name_both'],
        exclude_pattern_list=['test_name_exclude', 'test_name_both'])

    self.assertTrue(instance.should_include('test_name_include', flags.FAIL))
    self.assertFalse(instance.should_include('test_name_exclude', flags.PASS))
    self.assertFalse(instance.should_include('test_name_both', flags.FAIL))
    self.assertFalse(instance.should_include('test_name_both', flags.PASS))

  def test_should_include_expectation_combination(self):
    # If two or more flags are set, the default behavior is 'logical-and' of
    # each primitive flag's default behavior.

    instance = test_filter.TestFilter()
    self.assertTrue(instance.should_include(
        'test_name', flags.PASS | flags.FLAKY))  # Both are True by default.
    self.assertFalse(instance.should_include(
        'test_name', flags.PASS | flags.LARGE))  # LARGE is False by default.

    # Set include_large True.
    instance = test_filter.TestFilter(include_large=True)
    self.assertTrue(instance.should_include(
        'test_name', flags.PASS | flags.LARGE))

  def _test_should_run_internal(self, expectation, expected, **kwargs):
    # Note that the name is slightly confusing here.
    # |expectation| is the input for the should_run. It is the expectation
    # of each case of CTS, such as PASS, FAIL, FLAKY, LARGE, etc.
    # |expected| is the expected return value of should_run() for this
    # unittest.
    instance = test_filter.TestFilter(**kwargs)
    self.assertEquals(expected, instance.should_run(expectation))

    # Patterns should not affect to should_run()
    instance = test_filter.TestFilter(include_pattern_list=['*'], **kwargs)
    self.assertEquals(expected, instance.should_run(expectation))
    instance = test_filter.TestFilter(exclude_pattern_list=['*'], **kwargs)
    self.assertEquals(expected, instance.should_run(expectation))
    instance = test_filter.TestFilter(
        include_pattern_list=['*'], exclude_pattern_list=['*'], **kwargs)
    self.assertEquals(expected, instance.should_run(expectation))

  def test_should_run(self):
    # PASS, FAIL, LARGE and FLAKY tests run always if they are in the list,
    # regardless of include_fail and include_large flags.
    # TIMEOUT and REQUIRES_OPENGL tests run if include_timeout or
    # include_requires_opengl flag is set respectively.
    # NOT_SUPPORTED tests should never run.
    # File patterns do not affect to should_run().
    self._test_should_run_internal(flags.PASS, expected=True)

    self._test_should_run_internal(flags.FAIL, expected=True)
    self._test_should_run_internal(flags.FAIL, expected=True,
                                   include_fail=True)

    self._test_should_run_internal(flags.LARGE, expected=True)
    self._test_should_run_internal(flags.LARGE, expected=True,
                                   include_large=True)

    self._test_should_run_internal(flags.FLAKY, expected=True)

    self._test_should_run_internal(flags.TIMEOUT, expected=False)
    self._test_should_run_internal(flags.TIMEOUT, expected=True,
                                   include_timeout=True)

    self._test_should_run_internal(flags.REQUIRES_OPENGL, expected=False)
    self._test_should_run_internal(flags.REQUIRES_OPENGL, expected=True,
                                   include_requires_opengl=True)

    self._test_should_run_internal(flags.NOT_SUPPORTED, expected=False)


if __name__ == '__main__':
  unittest.main()
