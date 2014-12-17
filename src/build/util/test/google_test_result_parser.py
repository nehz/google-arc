# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from util.test import test_method_result


def _parse_duration(duration):
  """Parses duration and returns it in second."""
  if duration.endswith('ms'):
    return float(duration[:-2].strip()) / 1000.
  if duration.endswith('s'):
    return float(duration[:-1].strip())
  raise ValueError('Unknown duration format: %s' % duration)


def _build_test_name(fixture_name, test_method_name):
  return '%s#%s' % (fixture_name, test_method_name)


class GoogleTestResultParser(object):
  """Parser for the output of GoogleTest style test cases."""

  _COLOR_PATTERN = '(?:\x1b\[[^m]*m)?'
  _TEST_BEGIN_MARK = '[ RUN      ]'
  _TEST_PASS_MARK = '[       OK ]'
  _TEST_FAILED_MARK = '[  FAILED  ]'
  _TEST_NAME_PATTERN = r'(?P<fixture>\w+)\.(?P<method>\w+)'
  _TEST_DURATION_PATTERN = r'\((?P<duration>.+?)\)'

  _STATUS_CODE_MAP = {
      _TEST_PASS_MARK: test_method_result.TestMethodResult.PASS,
      _TEST_FAILED_MARK: test_method_result.TestMethodResult.FAIL,
  }

  def __init__(self, callback, prefix_pattern='', suffix_pattern='',
               fixture_prefix=''):
    self._begin_pattern = re.compile(
        '%(prefix)s%(color)s%(mark)s %(color)s%(name)s%(suffix)s' % {
            'prefix': prefix_pattern,
            'suffix': suffix_pattern,
            'color': GoogleTestResultParser._COLOR_PATTERN,
            'mark': re.escape(GoogleTestResultParser._TEST_BEGIN_MARK),
            'name': GoogleTestResultParser._TEST_NAME_PATTERN,
        })
    self._end_pattern = re.compile(
        ('%(prefix)s%(color)s(?P<status>%(pass)s|%(failed)s) %(color)s'
         '%(name)s %(duration)s%(suffix)s') % {
             'prefix': prefix_pattern,
             'suffix': suffix_pattern,
             'color': GoogleTestResultParser._COLOR_PATTERN,
             'pass': re.escape(GoogleTestResultParser._TEST_PASS_MARK),
             'failed': re.escape(GoogleTestResultParser._TEST_FAILED_MARK),
             'name': GoogleTestResultParser._TEST_NAME_PATTERN,
             'duration': GoogleTestResultParser._TEST_DURATION_PATTERN,
         })
    self._callback = callback
    self._fixture_prefix = fixture_prefix
    self._result_map = {}

  @property
  def test_result(self):
    return self._result_map.copy()

  def process_line(self, line):
    match = self._begin_pattern.match(line)
    if match:
      self._process_test_begin(match)
      return
    match = self._end_pattern.match(line)
    if match:
      self._process_test_end(match)
      return

  def _process_test_begin(self, match):
    self._callback.start_test(_build_test_name(
        self._fixture_prefix + match.group('fixture'), match.group('method')))

  def _process_test_end(self, match):
    name = _build_test_name(
        self._fixture_prefix + match.group('fixture'), match.group('method'))
    result = test_method_result.TestMethodResult(
        name,
        GoogleTestResultParser._STATUS_CODE_MAP[match.group('status')],
        duration=_parse_duration(match.group('duration')))
    self._result_map[name] = result
    self._callback.update([result])


class JavaScriptTestResultParser(GoogleTestResultParser):
  """Parser for the output of JavaScript test cases."""

  def __init__(self, callback):
    super(JavaScriptTestResultParser, self).__init__(
        callback,
        prefix_pattern=r'\[\d+:\d+:\d+/\d+:INFO:CONSOLE\(\d+\)\] \"INFO: ',
        suffix_pattern=r'"')
