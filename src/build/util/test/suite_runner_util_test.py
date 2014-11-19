# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util.test import suite_runner_util
from util.test import suite_runner_config_flags as flags


class SuiteRunnerUtilTest(unittest.TestCase):
  def test_merge_test_expectations(self):
    base_expectations = {
        'test1': flags.PASS,
        'test2': flags.FAIL,
    }

    # Not overriden.
    self.assertEquals(
        {
            'test1': flags.PASS,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_test_expectations(base_expectations, {}))

    # "'*': PASS" does not override anything.
    self.assertEquals(
        {
            'test1': flags.PASS,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_test_expectations(
            base_expectations, {'*': flags.PASS}))

    # Both should be overriden.
    self.assertEquals(
        {
            'test1': flags.NOT_SUPPORTED,
            'test2': flags.NOT_SUPPORTED,
        },
        suite_runner_util.merge_test_expectations(
            base_expectations, {'*': flags.NOT_SUPPORTED}))

    # Only "test1" should be overriden.
    self.assertEquals(
        {
            'test1': flags.FAIL,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_test_expectations(
            base_expectations, {'test1': flags.FAIL}))

    # Only "test1" should be overriden.
    self.assertEquals(
        {
            'test1': flags.FAIL,
            'test2': flags.FAIL,
        },
        suite_runner_util.merge_test_expectations(
            base_expectations, {'test1': flags.FAIL, '*': flags.PASS}))

    # Only "test1" should be overriden to FAIL, and "test2" to
    # NOT_SUPPORTED (default value).
    self.assertEquals(
        {
            'test1': flags.FAIL,
            'test2': flags.NOT_SUPPORTED,
        },
        suite_runner_util.merge_test_expectations(
            base_expectations,
            {'test1': flags.FAIL, '*': flags.NOT_SUPPORTED}))

    self.assertEquals(
        # Each should be overriden.
        {
            'test1': flags.FAIL,
            'test2': flags.PASS,
        },
        suite_runner_util.merge_test_expectations(
            base_expectations, {'test1': flags.FAIL, 'test2': flags.PASS}))

    with self.assertRaises(AssertionError):
      # Raise an exception if suite_expectations contains an unknown test name.
      suite_runner_util.merge_test_expectations(
          base_expectations, {'test3': flags.PASS})
