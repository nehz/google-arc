#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import unittest

from util.test import suite_runner_config
from util.test.suite_runner import SuiteRunnerBase
from util.test.suite_runner_config_flags import _ExclusiveFlag
from util.test.suite_runner_config_flags import ExclusiveFlagSet
from util.test.suite_runner_config_flags import FAIL
from util.test.suite_runner_config_flags import FLAKY
from util.test.suite_runner_config_flags import LARGE
from util.test.suite_runner_config_flags import NOT_SUPPORTED
from util.test.suite_runner_config_flags import PASS
from util.test.suite_runner_config_flags import TIMEOUT


def ones_count(x):
  """Returns the count of 1 bits in the input."""
  return bin(x).count("1")  # More efficient than a python loop.


class SuiteFlagMergeTest(unittest.TestCase):
  def test_pass_exclusive_with_fail(self):
    # These all should have the same mask to be properly exclusive.
    self.assertEquals(PASS._mask, FAIL._mask)
    self.assertEquals(PASS._mask, NOT_SUPPORTED._mask)
    self.assertEquals(PASS._mask, TIMEOUT._mask)

    # Verify that merging FAIL clears PASS, and visa-versa.
    flags = PASS
    self.assertIn(PASS, flags)
    self.assertNotIn(FAIL, flags)
    flags |= FAIL
    self.assertIn(FAIL, flags)
    self.assertNotIn(PASS, flags)
    flags |= PASS
    self.assertIn(PASS, flags)
    self.assertNotIn(FAIL, flags)

  def test_complex_merge(self):
    flags = PASS
    self.assertIsInstance(flags, _ExclusiveFlag)
    self.assertIn(PASS, flags)
    self.assertNotIn(FLAKY, flags)
    self.assertNotIn(LARGE, flags)
    self.assertEquals(1, ones_count(flags._value))
    self.assertEquals(PASS._mask, flags._mask)

    flags |= FLAKY
    self.assertIsInstance(flags, ExclusiveFlagSet)
    self.assertIn(PASS, flags)
    self.assertIn(FLAKY, flags)
    self.assertNotIn(LARGE, flags)
    self.assertEquals(2, ones_count(flags._value))
    self.assertEquals(PASS._mask, flags._mask)

    temp = LARGE
    self.assertIsInstance(temp, ExclusiveFlagSet)
    self.assertNotIn(PASS, temp)
    self.assertNotIn(FLAKY, temp)
    self.assertIn(LARGE, temp)
    self.assertEquals(1, ones_count(temp._value))
    self.assertEquals(0, temp._mask)

    flags |= temp
    self.assertIsInstance(flags, ExclusiveFlagSet)
    self.assertIn(PASS, flags)
    self.assertIn(FLAKY, flags)
    self.assertIn(LARGE, flags)
    self.assertEquals(3, ones_count(flags._value))
    self.assertEquals(PASS._mask, flags._mask)


def _evaluate(raw_config, defaults=None):
  return suite_runner_config._evaluate(raw_config, defaults=defaults)


def _evaluate_test_expectations(suite_test_expectations):
  return _evaluate(dict(suite_test_expectations=suite_test_expectations))[
      'suite_test_expectations']


class SuiteRunConfigInputTests(unittest.TestCase):
  """Tests the evaluation of the input configuration."""

  def test_defaults_applied(self):
    result = _evaluate({'flags': PASS},
                       defaults={'bug': 'crbug.com/1234', 'flags': FAIL})
    self.assertEquals('crbug.com/1234', result['bug'])
    self.assertEquals(suite_runner_config._DEFAULT_OUTPUT_TIMEOUT,
                      result['deadline'])
    self.assertIn(PASS, result['flags'])
    self.assertNotIn(FAIL, result['flags'])

  def test_simple_passing_test(self):
    self.assertIn(PASS, _evaluate(None)['flags'])
    self.assertIn(PASS, _evaluate({})['flags'])
    self.assertIn(PASS, _evaluate({'flags': PASS})['flags'])

  def test_simple_failing_test(self):
    result = _evaluate({'flags': FAIL})
    self.assertNotIn(PASS, result['flags'])
    self.assertIn(FAIL, result['flags'])

  def test_configured_to_fail_for_target(self):
    result = _evaluate({'configurations': [{'flags': FAIL | FLAKY}]})
    self.assertNotIn(PASS, result['flags'])
    self.assertIn(FAIL, result['flags'])
    self.assertIn(FLAKY, result['flags'])

    result = _evaluate({'configurations': [{
        'enable_if': False,
        'flags': FAIL | FLAKY
    }]})
    self.assertIn(PASS, result['flags'])
    self.assertNotIn(FAIL, result['flags'])
    self.assertNotIn(FLAKY, result['flags'])

  def test_flat_suite_test_expectations(self):
    result = _evaluate_test_expectations({'x': FLAKY})
    self.assertEqual(PASS | FLAKY, result['x'])

    result = _evaluate_test_expectations({'*': FLAKY})
    self.assertEqual(PASS | FLAKY, result['*'])

    # Only a simple '*' pattern is allowed.
    # (Though this pattern still allows us to do a prefix match later, we
    # disallow it.)
    with self.assertRaisesRegexp(AssertionError, r'"x\*" is not allowed'):
      _evaluate_test_expectations({'x*': PASS})

    # Only a simple '*' pattern is allowed.
    # (This allows us to to a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"\*x" is not allowed'):
      _evaluate_test_expectations({'*x': PASS})

    # A "class#method" style name is allowed.
    result = _evaluate_test_expectations({'x#y': FLAKY})
    self.assertEqual(PASS | FLAKY, result['x#y'])

    # Only one '#' is allowed.
    with self.assertRaisesRegexp(AssertionError, r'"x#y#z" is not allowed'):
      _evaluate_test_expectations({'x#y#z': PASS})

  def test_hierarchical_suite_test_expectations(self):
    result = _evaluate_test_expectations({'x': {'y': FLAKY}})
    self.assertEqual(PASS | FLAKY, result['x#y'])

    result = _evaluate_test_expectations({'x': {'*': FLAKY}})
    self.assertEqual(PASS | FLAKY, result['x#*'])

    # Only a simple '*' pattern is allowed.
    # (Though this pattern still allows us to do a prefix match later, we
    # disallow it.)
    with self.assertRaisesRegexp(AssertionError, r'"x#y\*" is not allowed'):
      _evaluate_test_expectations({'x': {'y*': FLAKY}})

    # Only a simple '*' pattern is allowed.
    # (This allows us to use a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"x#\*y" is not allowed'):
      _evaluate_test_expectations({'x': {'*y': FLAKY}})

    # If there is an asterisk wildcard, it must be in the leaf.
    # (This allows us to to a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"\*" is not a valid name'):
      _evaluate_test_expectations({'*': {'x': FLAKY}})

    # If there is an asterisk wildcard, it must be in the leaf.
    # (This allows us to to a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"\*" is not a valid name'):
      _evaluate_test_expectations({'*': {'*': FLAKY}})

    # Only one '#' is allowed.
    with self.assertRaisesRegexp(AssertionError, r'"x#y#z" is not allowed'):
      _evaluate_test_expectations({'x': {'y#z': FLAKY}})

  def test_suite_test_order(self):
    result = _evaluate({
        'configurations': [{
            'test_order': {'x': 1}
        }]
    })
    test_order = result['test_order']
    self.assertIn('x', test_order)
    self.assertEquals(test_order['x'], 1)


class SuiteRunConfigIntegrationTests(unittest.TestCase):
  """Uses the module interface as intended."""

  # This is the configuration the tests will use:
  my_config = staticmethod(suite_runner_config.make_suite_run_configs(lambda: {
      suite_runner_config.SUITE_DEFAULTS: {
          'flags': PASS,
          'deadline': 60,
      },
      'dummy_suite_1': None,
      'dummy_suite_2': {},
      'dummy_suite_3': {
          'flags': FAIL,
          'bug': 'crbug.com/123123',
      },
      'dummy_suite_4': {
          'flags': LARGE,
          'configurations': [{
              'test_order': collections.OrderedDict([
                  ('priMethod', -1)]),
              'suite_test_expectations': {
                  'Class1': {
                      'method1': FAIL,
                      'method2': FLAKY,
                  },
                  'Class2#method1': TIMEOUT,
              },
          }],
      },
  }))

  def _make_suite_runner(self, name):
    return SuiteRunnerBase(
        name,
        {
            'Class1#method1': PASS,
            'Class1#method2': PASS,
            'Class2#method1': PASS,
            'Class2#method2': PASS,
        },
        config=SuiteRunConfigIntegrationTests.my_config()[name])

  def test_works_as_intended(self):
    runner = self._make_suite_runner('dummy_suite_1')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': PASS,
            'Class1#method2': PASS,
            'Class2#method1': PASS,
            'Class2#method2': PASS,
        },
        runner.expectation_map)
    self.assertEquals(None, runner.bug)

    runner = self._make_suite_runner('dummy_suite_2')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': PASS,
            'Class1#method2': PASS,
            'Class2#method1': PASS,
            'Class2#method2': PASS,
        },
        runner.expectation_map)
    self.assertEquals(None, runner.bug)

    runner = self._make_suite_runner('dummy_suite_3')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': FAIL,
            'Class1#method2': FAIL,
            'Class2#method1': FAIL,
            'Class2#method2': FAIL,
        },
        runner.expectation_map)
    self.assertEquals('crbug.com/123123', runner.bug)

    runner = self._make_suite_runner('dummy_suite_4')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': LARGE | FAIL,
            'Class1#method2': LARGE | FLAKY | PASS,
            'Class2#method1': LARGE | TIMEOUT,
            'Class2#method2': LARGE | PASS,
        },
        runner.expectation_map)
    self.assertEquals(None, runner.bug)
    self.assertEquals(
        ['priMethod', 'abcMethod', 'xyzMethod'],
        runner.apply_test_ordering(['xyzMethod', 'abcMethod', 'priMethod']))


if __name__ == '__main__':
  unittest.main()
