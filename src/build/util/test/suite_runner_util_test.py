# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util.test import suite_runner_util
from util.test import suite_runner_config_flags as flags


class SuiteRunnerUtilTest(unittest.TestCase):
  def test_merge_expectation_map(self):
    base_map = {
        'test1': flags.PASS,
        'test2': flags.FAIL,
    }

    # Not overriden.
    self.assertEquals(
        {
            'test1': flags.PASS,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_expectation_map(base_map, {}, None))

    # "'*': PASS" does not override anything.
    self.assertEquals(
        {
            'test1': flags.PASS,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_expectation_map(
            base_map, {}, flags.PASS))

    # Both should be overriden.
    self.assertEquals(
        {
            'test1': flags.NOT_SUPPORTED,
            'test2': flags.NOT_SUPPORTED,
        },
        suite_runner_util.merge_expectation_map(
            base_map, {}, flags.NOT_SUPPORTED))

    # Only "test1" should be overriden.
    self.assertEquals(
        {
            'test1': flags.FAIL,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_expectation_map(
            base_map, {'test1': flags.FAIL}, None))

    # Only "test1" should be overriden.
    self.assertEquals(
        {
            'test1': flags.FAIL,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_expectation_map(
            base_map, {'test1': flags.FAIL}, flags.PASS))

    # Only "test1" should be overriden to FAIL, and "test2" to
    # NOT_SUPPORTED (default value).
    self.assertEquals(
        {
            'test1': flags.FAIL,
            'test2': flags.NOT_SUPPORTED,
        },
        suite_runner_util.merge_expectation_map(
            base_map, {'test1': flags.FAIL}, flags.NOT_SUPPORTED))

    self.assertEquals(
        # Each should be overriden.
        {
            'test1': flags.FAIL,
            'test2': flags.PASS,
        },
        suite_runner_util.merge_expectation_map(
            base_map,
            {'test1': flags.FAIL, 'test2': flags.PASS}, None))

    with self.assertRaises(AssertionError):
      # Raise an exception if suite_expectations contains an unknown test name.
      suite_runner_util.merge_expectation_map(
          base_map, {'test3': flags.PASS}, None)

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
