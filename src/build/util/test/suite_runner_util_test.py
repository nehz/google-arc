#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util.test import flags
from util.test import suite_runner_util


class SuiteRunnerUtilTest(unittest.TestCase):
  def test_merge_expectation_map(self):
    base_map = {
        'c#test1': flags.FlagSet(flags.PASS),
        'c#test2': flags.FlagSet(flags.FAIL),
    }

    # With no override expectations, the base expectations should be used.
    self.assertEquals(
        {
            'c#test1': flags.FlagSet(flags.PASS),
            'c#test2': flags.FlagSet(flags.FAIL),
        },
        suite_runner_util.merge_expectation_map(
            base_map, {}, flags.FlagSet(flags.PASS)))

    # test1 should be overridden to FAIL, test2 should keep the base FAIL.
    self.assertEquals(
        {
            'c#test1': flags.FlagSet(flags.FAIL),
            'c#test2': flags.FlagSet(flags.FAIL),
        },
        suite_runner_util.merge_expectation_map(
            base_map,
            {'c#test1': flags.FlagSet(flags.FAIL)},
            flags.FlagSet(flags.PASS)))

    # The pure expectation from the default expectation should end up in the
    # output expectation map.
    self.assertEquals(
        {
            'c#test1': flags.FlagSet(flags.FLAKY),
            'c#test2': flags.FlagSet(flags.FAIL),
        },
        suite_runner_util.merge_expectation_map(
            base_map, {}, flags.FlagSet(flags.FLAKY)))

    # If the default expectation is TIMEOUT, all the tests inside should be too
    # if no other test-level overrides are given
    self.assertEquals(
        {
            'c#test1': flags.FlagSet(flags.FLAKY),
            'c#test2': flags.FlagSet(flags.TIMEOUT),
        },
        suite_runner_util.merge_expectation_map(
            base_map,
            {'c#test1': flags.FlagSet(flags.FLAKY)},
            flags.FlagSet(flags.TIMEOUT)))

    # A suite level FLAKY flag should cause all tests to be marked FLAKY,
    # regardless of whether the base or override expectation is used.
    self.assertEquals(
        {
            'c#test1': flags.FlagSet(flags.FAIL | flags.LARGE),
            'c#test2': flags.FlagSet(flags.FAIL),
        },
        suite_runner_util.merge_expectation_map(
            base_map,
            {'c#test1': flags.FlagSet(flags.FAIL | flags.LARGE)},
            flags.FlagSet(flags.FLAKY)))

    # A suite level LARGE flag should cause all tests to be marked LARGE,
    # regardless of whether the base or override expectation is used.
    self.assertEquals(
        {
            'c#test1': flags.FlagSet(flags.PASS | flags.LARGE),
            'c#test2': flags.FlagSet(flags.PASS | flags.LARGE),
        },
        suite_runner_util.merge_expectation_map(
            base_map,
            {'c#test2': flags.FlagSet(flags.PASS)},
            flags.FlagSet(flags.PASS | flags.LARGE)))

    with self.assertRaises(AssertionError):
      # Raise an exception if suite_expectations contains an unknown test name.
      suite_runner_util.merge_expectation_map(
          base_map,
          {'c#test3': flags.FlagSet(flags.PASS)},
          flags.FlagSet(flags.PASS))

  def _check_simple(self, expected, patterns):
    self.assertEquals(
        dict((key, flags.FlagSet(value))
             for key, value in expected.iteritems()),
        suite_runner_util.merge_expectation_map(
            dict.fromkeys(expected, flags.FlagSet(flags.PASS)),
            dict((key, flags.FlagSet(value))
                 for key, value in patterns.iteritems()),
            flags.FlagSet(flags.PASS)))

  def test_merge_star_matches_all(self):
    # An entry of '*' should match all tests."""
    self._check_simple({
        'x#m1': flags.TIMEOUT,
        'y#m2': flags.TIMEOUT,
        'z#m1': flags.TIMEOUT,
    }, {
        '*': flags.TIMEOUT,
    })

  def test_merge_class_name_matching(self):
    # An entry like 'classname#*' should match "classname#any_method_name".
    self._check_simple({
        'x#m1': flags.FAIL,
        'x#m2': flags.FAIL,
        'x#m3': flags.FAIL,
        'y#m1': flags.TIMEOUT,
        'y#m2': flags.TIMEOUT,
        'z#m1': flags.PASS,
    }, {
        'x#*': flags.FAIL,
        'y#*': flags.TIMEOUT,
    })

  def test_merge_all_patterns_used(self):
    # The logic should verify that all patterns were matched.
    with self.assertRaisesRegexp(
        AssertionError, r'.*patterns with no match:\s+y#*\*'):
      self._check_simple({
          'x#m1': flags.PASS,
      }, {
          'y#*': flags.FAIL,
      })

  def test_merge_star_can_match_no_tests(self):
    # '*' as a special case is allowed to match no tests.
    self._check_simple({}, {'*': flags.FAIL})

  def test_merge_patterns_cannot_overlap(self):
    # No two patterns can match the same test name.
    with self.assertRaisesRegexp(
        AssertionError,
        r'The test expectation patterns "x#m1" and "x#\*" are ambiguous'):
      self._check_simple({
          'x#m1': flags.PASS,
      }, {
          'x#*': flags.FAIL,
          'x#m1': flags.FAIL,
      })

  def test_merge_star_is_exclusive(self):
    # A global '*' cannot be used with any other patterns.
    with self.assertRaisesRegexp(
        AssertionError,
        (r'Using the test expectation pattern "\*" with anything else is '
         r'ambiguous')):
      self._check_simple({
          'x#m1': flags.PASS,
      }, {
          '*': flags.TIMEOUT,
          'x#*': flags.FAIL,
          'x#m1': flags.FAIL,
      })

  def test_create_gtest_filter_list(self):
    # Result should be empty for an empty list.
    self.assertEquals(
        [],
        suite_runner_util.create_gtest_filter_list([], 10))

    # Normal case.
    self.assertEquals(
        ['aaa:bbb', 'ccc:ddd'],
        suite_runner_util.create_gtest_filter_list(
            ['aaa', 'bbb', 'ccc', 'ddd'], 10))

    # "aaa:bbb:cc" is just fit to the max_length (=10).
    self.assertEquals(
        ['aaa:bbb:cc', 'ddd:eee'],
        suite_runner_util.create_gtest_filter_list(
            ['aaa', 'bbb', 'cc', 'ddd', 'eee'], 10))

    # Boundary test for an element.
    self.assertEquals(
        ['aaa', 'b' * 10, 'ccc'],
        suite_runner_util.create_gtest_filter_list(
            ['aaa', 'b' * 10, 'ccc'], 10))

    # The second element exceeds the limit.
    with self.assertRaises(ValueError):
      suite_runner_util.create_gtest_filter_list(
          ['aaa', 'b' * 11, 'ccc'], 10)


if __name__ == '__main__':
  unittest.main()
