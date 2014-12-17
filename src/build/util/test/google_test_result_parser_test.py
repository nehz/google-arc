# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util.test import google_test_result_parser as result_parser


class MockCallback(object):
  def __init__(self):
    self.result = []

  def start_test(self, test_name):
    self.result.append(('start_test', test_name))

  def update(self, result_list):
    self.result.append(('update', result_list))


class GoogleTestResultParser(unittest.TestCase):
  def test_start(self):
    callback = MockCallback()
    parser = result_parser.GoogleTestResultParser(
        callback, fixture_prefix='android.bionic.')
    parser.process_line('[ RUN      ] strings.ffs')
    self.assertEqual(
        [('start_test', 'android.bionic.strings#ffs')],
        callback.result)
    self.assertFalse(parser.test_result)

  def test_success(self):
    callback = MockCallback()
    parser = result_parser.GoogleTestResultParser(
        callback, fixture_prefix='android.bionic.')
    parser.process_line('[       OK ] strings.ffs (65 ms)')
    self.assertEqual(1, len(callback.result))
    self.assertEqual('update', callback.result[0][0])

    update_result = callback.result[0][1]
    self.assertEqual(1, len(update_result))
    self.assertEqual('android.bionic.strings#ffs', update_result[0].name)
    self.assertTrue(update_result[0].passed)
    self.assertAlmostEqual(0.065, update_result[0].duration)

    test_result = parser.test_result
    self.assertEqual(1, len(test_result))
    self.assertIn('android.bionic.strings#ffs', test_result)
    test_case_result = test_result['android.bionic.strings#ffs']
    self.assertEqual('android.bionic.strings#ffs', test_case_result.name)
    self.assertTrue(test_case_result.passed)
    self.assertAlmostEqual(0.065, test_case_result.duration)

  def test_fail(self):
    callback = MockCallback()
    parser = result_parser.GoogleTestResultParser(
        callback, fixture_prefix='android.bionic.')
    parser.process_line('[  FAILED  ] signal.raise_invalid (155 ms)')
    self.assertEqual(1, len(callback.result))
    self.assertEqual('update', callback.result[0][0])

    update_result = callback.result[0][1]
    self.assertEquals(1, len(update_result))
    self.assertEqual('android.bionic.signal#raise_invalid',
                     update_result[0].name)
    self.assertTrue(update_result[0].failed)
    self.assertAlmostEqual(0.155, update_result[0].duration)

    test_result = parser.test_result
    self.assertEqual(1, len(test_result))
    self.assertIn('android.bionic.signal#raise_invalid', test_result)
    test_case_result = test_result['android.bionic.signal#raise_invalid']
    self.assertEqual(
        'android.bionic.signal#raise_invalid', test_case_result.name)
    self.assertTrue(test_case_result.failed)
    self.assertAlmostEqual(0.155, test_case_result.duration)


class JavaScriptTestResultParser(unittest.TestCase):
  def test_start(self):
    callback = MockCallback()
    parser = result_parser.JavaScriptTestResultParser(callback)
    parser.process_line(
        '[13748:13748:1202/184723:INFO:CONSOLE(136)] '
        '"INFO: [ RUN      ] BackgroundPageTest.SendCrashReportsFromRelease", '
        'source: chrome-extension://dummy_hash_code/chrome_test.js (136)')
    self.assertEqual(
        [('start_test', 'BackgroundPageTest#SendCrashReportsFromRelease')],
        callback.result)
    self.assertFalse(parser.test_result)

  def test_success(self):
    callback = MockCallback()
    parser = result_parser.JavaScriptTestResultParser(callback)
    parser.process_line(
        '[13748:13748:1202/184723:INFO:CONSOLE(136)] '
        '"INFO: [       OK ] BackgroundPageTest.SendCrashReportsFromRelease '
        '(215ms)", source: chrome-extension://dummy_hash_code/chrome_test.js '
        '(136)')
    self.assertEqual(1, len(callback.result))
    self.assertEqual('update', callback.result[0][0])

    update_result = callback.result[0][1]
    self.assertEqual(1, len(update_result))
    self.assertEqual('BackgroundPageTest#SendCrashReportsFromRelease',
                     update_result[0].name)
    self.assertTrue(update_result[0].passed)
    self.assertAlmostEqual(0.215, update_result[0].duration)

  def test_fail(self):
    callback = MockCallback()
    parser = result_parser.JavaScriptTestResultParser(callback)
    parser.process_line(
        '[13748:13748:1202/184723:INFO:CONSOLE(136)] '
        '"INFO: [  FAILED  ] BackgroundPageTest.SendCrashReportsFromRelease '
        '(1.5s)", source: chrome-extension://dummy_hash_code/chrome_test.js '
        '(136)')
    self.assertEqual(1, len(callback.result))
    self.assertEqual('update', callback.result[0][0])

    update_result = callback.result[0][1]
    self.assertEquals(1, len(update_result))
    self.assertEqual('BackgroundPageTest#SendCrashReportsFromRelease',
                     update_result[0].name)
    self.assertTrue(update_result[0].failed)
    self.assertAlmostEqual(1.5, update_result[0].duration)
