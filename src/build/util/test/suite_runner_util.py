# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utilities to for suite runner implementation."""

from src.build.util.test import flags


class _GlobalExpectationMatcher(object):
  """Handles the special case of a single {"*": <expectation>} entry."""
  def __init__(self, expectations):
    self._expectation = expectations['*']
    assert len(expectations) == 1, (
        'Using the test expectation pattern "*" with anything else is '
        'ambiguous. Use either "*" alone, or specify just the patterns:\n'
        '    "%s"' % '"\n    "'.join(
            name for name in expectations if name != '*'))

  def __getitem__(self, name):
    return self._expectation

  def check_unused(self):
    # "*" is allowed to match nothing.
    pass


class _ExpectationMatcher(object):
  """Handles the general case of a list of exact or class names."""
  def __init__(self, expectations):
    for name in expectations:
      assert name.count('#') == 1, (
          'The test expectation pattern "%s" does not match the expected form. '
          'A name like "class_name#test_name" is expected' % name)
      if not name.endswith('#*'):
        class_name = name.split('#', 1)[0]
        assert (class_name + '#*') not in expectations, (
            'The test expectation patterns "%s" and "%s#*" are ambiguous. '
            'Mixing an exact match with a class name match is not allowed.' % (
                name, class_name))

    self._expectations = expectations
    self._unused = set(expectations)

  def __getitem__(self, name):
    # If this triggers, we would need to handle it in a special way, and we
    # might not be able to set an override expectation without additional work.
    assert not name.endswith('#*'), (
        'Test name "%s" ends with a reserved sequence "#*".' % name)

    match_name = name
    expectation = self._expectations.get(match_name)
    if expectation is None:
      # If the exact match failed to find an expectation, see if there is an
      # expectation for the class name.
      match_name = name.split('#', 1)[0] + '#*'
      expectation = self._expectations.get(match_name)

    # Mark the match as used.
    if expectation is not None and match_name in self._unused:
      self._unused.remove(match_name)

    return expectation

  def check_unused(self):
    # Every name should have been used. If not, display a message so the
    # configuration can be cleaned up.
    assert not self._unused, (
        'The expectations configuration includes patterns with no match:\n'
        '    %s\n'
        'Please remove the ones that that are no longer used.' % (
            '\n    '.join(sorted(self._unused))))


def _merge(base_expectation, override_expectation, default_expectation):
  if override_expectation:
    return default_expectation.override_with(override_expectation)

  # We choose 'worse' status here. Considering;
  # |base_expectation| should be either |PASS| or |FAIL|, because it is based
  # on the original Android's test config. On the other hand,
  # default_expectation is what we defined for each test suite. Specifically,
  # it's |PASS| by default.
  # It should make sense that a test case, which is marked |FAIL| by base
  # but |PASS| by default, fails.
  # On the other hand, if we annotate NOT_SUPPORTED or TIMEOUT for a test
  # case, we do not want to run (by default) regardless of whether it is
  # marked as PASS or FAIL by base expectation.
  status = max(base_expectation.status, default_expectation.status)
  return flags.FlagSet(status | default_expectation.attribute)


def merge_expectation_map(
    base_expectation_map, override_expectation_map, default_expectation):
  if '*' in override_expectation_map:
    overrides = _GlobalExpectationMatcher(override_expectation_map)
  else:
    overrides = _ExpectationMatcher(override_expectation_map)

  result = dict((name, _merge(expectation, overrides[name],
                              default_expectation))
                for name, expectation in base_expectation_map.iteritems())
  overrides.check_unused()
  return result


def read_test_list(path):
  """Reads a list of test methods from file, and returns an expectation map."""
  with open(path) as stream:
    data = stream.read()
  return dict.fromkeys(data.splitlines(), flags.FlagSet(flags.PASS))


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
