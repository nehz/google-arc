# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util.test import extract_js_test_list


class TestExtractJsTestList(unittest.TestCase):
  def test_parse_test_list(self):
    # Simple cases.
    self.assertEquals(
        ['Fixture1#test_method1',
         'Fixture1#test_method2',
         'Fixture2#test_method1',
         'Fixture2#test_method2'],
        extract_js_test_list._parse_test_list('\n'.join([
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
        extract_js_test_list._parse_test_list('\n'.join([
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
        extract_js_test_list._parse_test_list('\n'.join([
            'function TEST_F(fixtureClass, testName, testFunc, opt_caseName) {',
            '  // The definition code line 1.',
            '  // The definition code line 2.',
            '  // The definition code line 3.',
            '}'])))
