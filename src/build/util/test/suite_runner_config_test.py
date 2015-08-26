# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import unittest

from build_options import OPTIONS
from util.test import flags
from util.test import suite_runner
from util.test import suite_runner_config


def _evaluate(raw_config, defaults=None):
  return suite_runner_config._evaluate(raw_config, defaults=defaults)


def _evaluate_test_expectations(suite_test_expectations):
  return _evaluate(dict(suite_test_expectations=suite_test_expectations))[
      'suite_test_expectations']


class SuiteRunConfigInputTests(unittest.TestCase):
  """Tests the evaluation of the input configuration."""

  def test_defaults_applied(self):
    result = _evaluate({'flags': flags.FlagSet(flags.PASS)},
                       defaults={'bug': 'crbug.com/1234',
                                 'flags': flags.FlagSet(flags.FAIL)})
    self.assertEquals('crbug.com/1234', result['bug'])
    self.assertEquals(suite_runner_config._DEFAULT_OUTPUT_TIMEOUT,
                      result['deadline'])
    self.assertEquals(flags.PASS, result['flags'].status)

  def test_simple_passing_test(self):
    self.assertEquals(flags.PASS, _evaluate(None)['flags'].status)
    self.assertEquals(flags.PASS, _evaluate({})['flags'].status)
    self.assertEquals(
        flags.PASS,
        _evaluate({'flags': flags.FlagSet(flags.PASS)})['flags'].status)

  def test_simple_failing_test(self):
    result = _evaluate({'flags': flags.FlagSet(flags.FAIL)})
    self.assertEquals(flags.FAIL, result['flags'].status)

  def test_configured_to_fail_for_target(self):
    result = _evaluate(
        {'configurations': [{'flags': flags.FlagSet(flags.FLAKY)}]})
    self.assertEquals(flags.FLAKY, result['flags'].status)

    result = _evaluate({'configurations': [{
        'enable_if': False,
        'flags': flags.FlagSet(flags.FLAKY)
    }]})
    self.assertEquals(flags.PASS, result['flags'].status)

  def test_flat_suite_test_expectations(self):
    result = _evaluate_test_expectations({'x': flags.FlagSet(flags.FLAKY)})
    self.assertEqual(flags.FlagSet(flags.FLAKY), result['x'])

    result = _evaluate_test_expectations({'*': flags.FlagSet(flags.FLAKY)})
    self.assertEqual(flags.FlagSet(flags.FLAKY), result['*'])

    # Only a simple '*' pattern is allowed.
    # (Though this pattern still allows us to do a prefix match later, we
    # disallow it.)
    with self.assertRaisesRegexp(AssertionError, r'"x\*" is not allowed'):
      _evaluate_test_expectations({'x*': flags.FlagSet(flags.PASS)})

    # Only a simple '*' pattern is allowed.
    # (This allows us to to a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"\*x" is not allowed'):
      _evaluate_test_expectations({'*x': flags.FlagSet(flags.PASS)})

    # A "class#method" style name is allowed.
    result = _evaluate_test_expectations({'x#y': flags.FlagSet(flags.FLAKY)})
    self.assertEqual(flags.FlagSet(flags.FLAKY), result['x#y'])

    # Only one '#' is allowed.
    with self.assertRaisesRegexp(AssertionError, r'"x#y#z" is not allowed'):
      _evaluate_test_expectations({'x#y#z': flags.FlagSet(flags.PASS)})

  def test_hierarchical_suite_test_expectations(self):
    result = _evaluate_test_expectations(
        {'x': {'y': flags.FlagSet(flags.FLAKY)}})
    self.assertEqual(flags.FlagSet(flags.FLAKY), result['x#y'])

    result = _evaluate_test_expectations(
        {'x': {'*': flags.FlagSet(flags.FLAKY)}})
    self.assertEqual(flags.FlagSet(flags.FLAKY), result['x#*'])

    # Only a simple '*' pattern is allowed.
    # (Though this pattern still allows us to do a prefix match later, we
    # disallow it.)
    with self.assertRaisesRegexp(AssertionError, r'"x#y\*" is not allowed'):
      _evaluate_test_expectations({'x': {'y*': flags.FlagSet(flags.FLAKY)}})

    # Only a simple '*' pattern is allowed.
    # (This allows us to use a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"x#\*y" is not allowed'):
      _evaluate_test_expectations({'x': {'*y': flags.FlagSet(flags.FLAKY)}})

    # If there is an asterisk wildcard, it must be in the leaf.
    # (This allows us to to a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"\*" is not a valid name'):
      _evaluate_test_expectations({'*': {'x': flags.FlagSet(flags.FLAKY)}})

    # If there is an asterisk wildcard, it must be in the leaf.
    # (This allows us to to a simple prefix match later)
    with self.assertRaisesRegexp(AssertionError, r'"\*" is not a valid name'):
      _evaluate_test_expectations({'*': {'*': flags.FlagSet(flags.FLAKY)}})

    # Only one '#' is allowed.
    with self.assertRaisesRegexp(AssertionError, r'"x#y#z" is not allowed'):
      _evaluate_test_expectations({'x': {'y#z': flags.FlagSet(flags.FLAKY)}})

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
          'flags': flags.FlagSet(flags.PASS),
          'deadline': 60,
      },
      'dummy_suite_1': None,
      'dummy_suite_2': {},
      'dummy_suite_3': {
          'flags': flags.FlagSet(flags.FAIL),
          'bug': 'crbug.com/123123',
      },
      'dummy_suite_4': {
          'flags': flags.FlagSet(flags.LARGE),
          'configurations': [{
              'test_order': collections.OrderedDict([
                  ('priMethod', -1)]),
              'suite_test_expectations': {
                  'Class1': {
                      'method1': flags.FlagSet(flags.FAIL),
                      'method2': flags.FlagSet(flags.FLAKY),
                  },
                  'Class2#method1': flags.FlagSet(flags.TIMEOUT),
              },
          }],
      },
  }))

  def setUp(self):
    OPTIONS.parse([])

  def _make_suite_runner(self, name):
    return suite_runner.SuiteRunnerBase(
        name,
        {
            'Class1#method1': flags.FlagSet(flags.PASS),
            'Class1#method2': flags.FlagSet(flags.PASS),
            'Class2#method1': flags.FlagSet(flags.PASS),
            'Class2#method2': flags.FlagSet(flags.PASS),
        },
        config=SuiteRunConfigIntegrationTests.my_config()[name])

  def test_works_as_intended(self):
    runner = self._make_suite_runner('dummy_suite_1')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': flags.FlagSet(flags.PASS),
            'Class1#method2': flags.FlagSet(flags.PASS),
            'Class2#method1': flags.FlagSet(flags.PASS),
            'Class2#method2': flags.FlagSet(flags.PASS),
        },
        runner.expectation_map)
    self.assertEquals(None, runner.bug)

    runner = self._make_suite_runner('dummy_suite_2')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': flags.FlagSet(flags.PASS),
            'Class1#method2': flags.FlagSet(flags.PASS),
            'Class2#method1': flags.FlagSet(flags.PASS),
            'Class2#method2': flags.FlagSet(flags.PASS),
        },
        runner.expectation_map)
    self.assertEquals(None, runner.bug)

    runner = self._make_suite_runner('dummy_suite_3')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': flags.FlagSet(flags.FAIL),
            'Class1#method2': flags.FlagSet(flags.FAIL),
            'Class2#method1': flags.FlagSet(flags.FAIL),
            'Class2#method2': flags.FlagSet(flags.FAIL),
        },
        runner.expectation_map)
    self.assertEquals('crbug.com/123123', runner.bug)

    runner = self._make_suite_runner('dummy_suite_4')
    self.assertEquals(60, runner.deadline)
    self.assertEquals(
        {
            'Class1#method1': flags.FlagSet(flags.LARGE | flags.FAIL),
            'Class1#method2': flags.FlagSet(flags.LARGE | flags.FLAKY),
            'Class2#method1': flags.FlagSet(flags.LARGE | flags.TIMEOUT),
            'Class2#method2': flags.FlagSet(flags.LARGE | flags.PASS),
        },
        runner.expectation_map)
    self.assertEquals(None, runner.bug)
    self.assertEquals(
        ['priMethod', 'abcMethod', 'xyzMethod'],
        runner.apply_test_ordering(['xyzMethod', 'abcMethod', 'priMethod']))


if __name__ == '__main__':
  unittest.main()
