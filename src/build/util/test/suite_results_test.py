# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import unittest

from util.test import scoreboard_constants
from util.test import suite_results


class FormatElipsizedTextTests(unittest.TestCase):
  """Tests for _format_elipsized_text"""

  def _format(self, text, target_len):
    return suite_results._format_elipsized_text(text, target_len)

  def test_ellipsize_lengthen(self):
    self.assertEqual('       ', self._format('', 7))
    self.assertEqual('123    ', self._format('123', 7))
    self.assertEqual('1234   ', self._format('1234', 7))
    self.assertEqual('123456 ', self._format('123456', 7))

  def test_ellipsize_identity(self):
    self.assertEqual('1234567', self._format('1234567', 7))

  def test_ellipsize_shorten(self):
    self.assertEqual('12...78', self._format('12345678', 7))
    self.assertEqual('12...89', self._format('123456789', 7))

    self.assertEqual('12...789', self._format('123456789', 8))

  def test_ellipsize_shorten_extreme(self):
    self.assertEqual('1...8', self._format('12345678', 5))
    self.assertEqual('...8', self._format('12345678', 4))
    self.assertEqual('...', self._format('12345678', 3))
    self.assertEqual('..', self._format('12345678', 2))
    self.assertEqual('.', self._format('12345678', 1))
    self.assertEqual('', self._format('12345678', 0))


class FormatDurationTests(unittest.TestCase):
  """Tests for _format_duration"""

  def _format(self, duration, fractions=False):
    return suite_results._format_duration(duration, fractions=fractions)

  def test_various(self):
    self.assertEqual('0s', self._format(0))

    self.assertEqual('0s', self._format(0.1))
    self.assertEqual('0.100s', self._format(0.1, fractions=True))

    self.assertEqual('1s', self._format(1.1))
    self.assertEqual('1.234s', self._format(1.2345, fractions=True))

    self.assertEqual('59s', self._format(59))
    self.assertEqual('1m', self._format(60))
    self.assertEqual('1m 1s', self._format(61))

    self.assertEqual('59m 59s', self._format(3599))
    self.assertEqual('1h', self._format(3600))
    self.assertEqual('1h 1s', self._format(3601))

    self.assertEqual('100h 1s', self._format(360001))

  def test_unexpected(self):
    self.assertEqual('-61s', self._format(-61))


class FormatDurationOldTests(unittest.TestCase):
  """Tests for _format_duration_old"""

  def _format(self, duration):
    return suite_results._format_duration_old(duration)

  def test_various(self):
    self.assertEqual('00:00', self._format(0))
    self.assertEqual('00:00', self._format(0.9))
    self.assertEqual('00:01', self._format(1.2345))

    self.assertEqual('00:59', self._format(59))
    self.assertEqual('01:00', self._format(60))
    self.assertEqual('01:01', self._format(61))

    self.assertEqual('59:59', self._format(3599))
    self.assertEqual('60:00', self._format(3600))
    self.assertEqual('60:01', self._format(3601))

    self.assertEqual('6000:01', self._format(360001))

  def test_unexpected(self):
    self.assertEqual('00:-61', self._format(-61))


class FormatProgressTests(unittest.TestCase):
  """Tests for _format_progress"""

  def _format(self, index, total):
    return suite_results._format_progress(index, total)

  def test_various(self):
    self.assertEqual('0/9', self._format(0, 9))
    self.assertEqual('1/9', self._format(1, 9))
    self.assertEqual('9/9', self._format(9, 9))
    self.assertEqual('10/10', self._format(10, 9))

    self.assertEqual('01/10', self._format(1, 10))
    self.assertEqual('001/100', self._format(1, 100))

  def test_unexpected(self):
    self.assertEqual('0/0', self._format(0, 0))
    self.assertEqual('1/1', self._format(1, 0))
    self.assertEqual('-1/1', self._format(-1, 1))
    self.assertEqual('1/1', self._format(1, -1))
    self.assertEqual('-1/-1', self._format(-1, -1))


class FormatStatusCountsTests(unittest.TestCase):
  """Tests for the wrappers around _format_status_counts"""

  def test_verbose(self):
    _format = suite_results._format_verbose_status_counts
    counts = collections.Counter({
        scoreboard_constants.UNEXPECT_FAIL: 1,
        scoreboard_constants.EXPECT_PASS: 99})
    self.assertEqual('99 Passed  1 Failed',
                     _format(counts))

  def test_terse(self):
    _format = suite_results._format_terse_status_counts
    counts = collections.Counter({
        scoreboard_constants.UNEXPECT_FAIL: 1,
        scoreboard_constants.EXPECT_PASS: 99})
    self.assertEqual('   99P      0UP      0XF      1F      0I      0S',
                     _format(counts))

  def test_expected(self):
    _format = suite_results._format_expected_status_counts
    counts = collections.Counter({
        scoreboard_constants.UNEXPECT_FAIL: 1,
        scoreboard_constants.EXPECT_PASS: 99})
    self.assertEqual('    0S     99P      0XF',
                     _format(counts))

if __name__ == '__main__':
  unittest.main()
