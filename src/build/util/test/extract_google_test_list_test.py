# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import StringIO
import unittest

from src.build.util.test import extract_google_test_list


class TestExtractGoogleTestList(unittest.TestCase):

  def _parse_cpp_test_list(self, content):
    """Simple wrapper of _parse_test_list for C++ testing."""
    return extract_google_test_list._parse_test_list(
        StringIO.StringIO(content),
        extract_google_test_list._CPP_TEST_METHOD_PATTERN)

  def test_parser_cpp_test_list(self):
    # Simple cases for TEST_F.
    self.assertEquals(
        ['Fixture1#test_method1',
         'Fixture1#test_method2',
         'Fixture2#test_method1',
         'Fixture2#test_method2'],
        self._parse_cpp_test_list('\n'.join([
            'TEST_F(Fixture1, test_method1) {',
            '  // test body',
            '}',
            '',
            'TEST_F(Fixture1, test_method2) {',
            '  // test body',
            '}',
            '',
            'TEST_F(Fixture2, test_method1) {',
            '  // test body',
            '}',
            '',
            'TEST_F(Fixture2, test_method2) {',
            '  // test body',
            '}'])))

    # Simple cases for TEST.
    self.assertEquals(
        ['Fixture1#test_method1',
         'Fixture1#test_method2',
         'Fixture2#test_method1',
         'Fixture2#test_method2'],
        self._parse_cpp_test_list('\n'.join([
            'TEST(Fixture1, test_method1) {',
            '  // test body',
            '}',
            '',
            'TEST(Fixture1, test_method2) {',
            '  // test body',
            '}',
            '',
            'TEST(Fixture2, test_method1) {',
            '  // test body',
            '}',
            '',
            'TEST(Fixture2, test_method2) {',
            '  // test body',
            '}'])))

    # Line breaks around fixture and test name.
    self.assertEquals(
        ['Fixture1#test_method1',
         'Fixture1#test_method2',
         'Fixture1#test_method3'],
        self._parse_cpp_test_list('\n'.join([
            'TEST_F(Fixture1,'
            '       test_method1) {',
            '  // test body',
            '}',
            '',
            'TEST_F('
            '    Fixture1, test_method2) {',
            '  // test body',
            '}',
            '',
            'TEST_F('
            '    Fixture1,'
            '    test_method3) {',
            '  // test body',
            '}'])))

  def _parse_javascript_test_list(self, content):
    """Simple wrapper of _parse_test_list for JavaScript testing."""
    return extract_google_test_list._parse_test_list(
        StringIO.StringIO(content),
        extract_google_test_list._JAVASCRIPT_TEST_METHOD_PATTERN)

  def test_parse_javascript_test_list(self):
    # Simple cases.
    self.assertEquals(
        ['Fixture1#test_method1',
         'Fixture1#test_method2',
         'Fixture2#test_method1',
         'Fixture2#test_method2'],
        self._parse_javascript_test_list('\n'.join([
            'TEST_F(Fixture1, "test_method1", function() {',
            '  // Some test body code;',
            '});',
            '',
            'TEST_F(Fixture1, "test_method2", function() {',
            '  // Some test body code;',
            '});',
            '',
            'TEST_F(Fixture2, "test_method1", function() {',
            '  // Some test body code;',
            '});',
            '',
            'TEST_F(Fixture2, "test_method2", function() {',
            '  // Some test body code;',
            '});',
            ''])))

    # Some line breaks around the parameters.
    self.assertEquals(
        ['Fixture1#test_method1',
         'Fixture1#test_method2',
         'Fixture1#test_method3',
         'Fixture1#test_method4'],
        self._parse_javascript_test_list('\n'.join([
            'TEST_F(Fixture1, "test_method1",',
            '       function() {',
            '  // Some test body code;',
            '});',
            '',
            'TEST_F(Fixture1,',
            '       "test_method2", function() {',
            '  // Some test body code;',
            '});',
            '',
            'TEST_F(',
            '    Fixture1, "test_method3", function() {',
            '  // Some test body code;',
            '});',
            '',
            'TEST_F(',
            '    Fixture1,',
            '    "test_method4",',
            '    function() {',
            '  // Some test body code;',
            '});',
            ''])))

    # The definition of TEST_F should not be included.
    self.assertEquals(
        [],
        self._parse_javascript_test_list('\n'.join([
            'function TEST_F(fixtureClass, testName, '
            'testFunc, opt_caseName) {',
            '  // The definition code line 1.',
            '  // The definition code line 2.',
            '  // The definition code line 3.',
            '}'])))

if __name__ == '__main__':
  unittest.main()
