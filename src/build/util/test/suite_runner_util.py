# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utilities to for suite runner implementation."""

from util.test import suite_runner_config_flags as flags


def merge_test_expectations(
    base_test_expectations, override_test_expectations):
  # In test cases, base_test_expectations is stubbed out as {'*': flags.PASS}.
  # cf) src/build/run_integration_tests_test.py.
  # We cannot easily avoid this situation, because the real files are
  # generated at build time, so the unittests do not know about them.
  # To avoid test failure, we temporarily handle it here, too.
  # TODO(crbug.com/432507): Once the '*' expansion work is done, we can
  # get rid of '*'. We should revisit here then.
  if base_test_expectations == {'*': flags.PASS}:
    return base_test_expectations

  # First, check the integrity of our CTS configuration. Note that this check
  # may raise a false alarm for upstream CTS configuration which does not
  # specify individual test methods. The only known instance of this is
  # CtsDpiTestCases2, and we have no test expectations for the test.
  # cf) android-cts/android-cts/repository/testcases/CtsDpiTestCases2.xml
  unknown_test_list = []
  for test_name in override_test_expectations:
    if test_name != '*' and test_name not in base_test_expectations:
      unknown_test_list.append(test_name)
  assert not unknown_test_list, (
      'Unknown tests found:\n%s' % '\n'.join(unknown_test_list))

  # Then merge the expectation dicts as follows:
  # 1) If the test's expectation is in |override_test_expectations|, choose it.
  # 2) If there is default expectation (its key is '*') and it is not PASS,
  #    choose it.
  # 3) Otherwise (i.e. there is no default expectation or the default
  #    expectation is PASS), then choose the original expectation.
  default_expectation = override_test_expectations.get('*')
  if default_expectation and default_expectation == flags.PASS:
    default_expectation = None
  result = {}
  for test_name, original_expectation in base_test_expectations.iteritems():
    expectation = override_test_expectations.get(
        test_name, default_expectation or original_expectation)
    result[test_name] = expectation
  return result


def read_test_list(path):
  """Reads a list of test methods from file, and returns an expectation map."""
  with open(path) as stream:
    data = stream.read()
  return dict.fromkeys(data.splitlines(), flags.PASS)


def create_gtest_filter_list(test_list, max_length):
  # We use 'adb shell' command to run an executable gtest binary on ARC.
  # However, adb_client.c defines a maximum command line length of 1024
  # characters. We have many test methods, so that just concatenating
  # them can easily exceed the limit. To avoid such an error, we split
  # the test_list into some groups which fit, and return them.
  # If one test name length exceeds |max_length|, raises ValueError.
  # Note: |test_list| is a list of 'TestCase#TestMethod' formatted test names.
  result = []

  current_list = []
  current_length = 0
  for test_name in test_list:
    # Convert to gtest_filter test name format.
    test_name = test_name.replace('#', '.')
    test_name_len = len(test_name)

    if test_name_len > max_length:
      raise ValueError(
          'TestName \'%s\' (len: %d) exceeds the max_length (%d)' % (
              test_name, test_name_len, max_length))

    # |current_list| can be empty at the first iteration. We should not
    # create an empty group. Otherwise, |current_list| should not be empty,
    # it means, we need a separator. +1 below means a separator length.
    if current_list and (current_length + test_name_len + 1 > max_length):
      result.append(current_list)
      current_list = []
      current_length = 0
    current_length += test_name_len + (1 if current_list else 0)
    current_list.append(test_name)
  if current_list:
    result.append(current_list)
  return [':'.join(group) for group in result]
