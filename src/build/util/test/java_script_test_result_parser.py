# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from util.test import test_method_result


def _parse_duration(duration):
  """Parses duration and returns it in second."""
  if duration.endswith('ms'):
    return float(duration[:-2]) / 1000.
  if duration.endswith('s'):
    return float(duration[:-1])
  raise ValueError('Unknown duration format: %s' % duration)


class JavaScriptTestResultParser(object):
  """Parser for the output of JavaScript test cases."""

  _TEST_BEGIN_PATTERN = re.compile(
      r'\[\d+:\d+:\d+/\d+:INFO:CONSOLE\(\d+\)\] '
      '\"INFO: \[ RUN      \] (\w+)\.(\w+)\"')
  _TEST_END_PATTERN = re.compile(
      r'\[\d+:\d+:\d+/\d+:INFO:CONSOLE\(\d+\)\] '
      '\"INFO: \[(       OK |  FAILED  )\] (\w+)\.(\w+) \((\S+)\)\"')
  _TEST_CODE_MAP = {
      '       OK ': test_method_result.TestMethodResult.PASS,
      '  FAILED  ': test_method_result.TestMethodResult.FAIL,
  }

  def __init__(self, suite_name, callback):
    self._suite_name = suite_name
    self._result_map = {}
    self._callback = callback

  @property
  def test_result(self):
    return self._result_map.copy()

  def process_line(self, line):
    match = JavaScriptTestResultParser._TEST_BEGIN_PATTERN.match(line)
    if match:
      self._process_test_begin(match)
      return
    match = JavaScriptTestResultParser._TEST_END_PATTERN.match(line)
    if match:
      self._process_test_end(match)
      return

  def _process_test_begin(self, match):
    self._callback.start_test(
        self._build_fully_qualified_name(match.group(1), match.group(2)))

  def _process_test_end(self, match):
    name = self._build_fully_qualified_name(match.group(2), match.group(3))
    result = test_method_result.TestMethodResult(
        name,
        JavaScriptTestResultParser._TEST_CODE_MAP[match.group(1)],
        duration=_parse_duration(match.group(4)))
    self._result_map[name] = result
    self._callback.update([result])

  def _build_fully_qualified_name(self, fixture_name, test_case_name):
    return '%s:%s#%s' % (self._suite_name, fixture_name, test_case_name)
