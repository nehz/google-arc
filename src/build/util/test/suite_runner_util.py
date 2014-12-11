# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utilities to for suite runner implementation."""

from util.test import suite_runner_config_flags as flags


def merge_test_expectations(
    base_test_expectations, override_test_expectations):
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
