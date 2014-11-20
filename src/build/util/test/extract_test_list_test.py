# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from xml.etree import ElementTree

from util.test import extract_test_list


class ExtractTestListTest(unittest.TestCase):
  def test_extract_test(self):
    self.assertEquals(
        ['test.package.TestClass1#testMethod1',
         'test.package.TestClass1#testMethod2',
         'test.package.TestClass2#testMethod1'],
        extract_test_list._extract_test(ElementTree.fromstring('\n'.join([
            '<api>',
            '<package name="test.package">',

            '<class name="TestClass1"',
            ' extends="junit.framework.TestCase"',
            ' abstract="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',

            # Constructor should be ignored.
            '<constructor name="TestClass1"',
            ' type="test.package.TestClass1"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</constructor>',

            # Simplest test method.
            '<method name="testMethod1"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</method>',

            # Methods with non-public visibility should be ignored.
            '<method name="testProtected"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="protected"',
            '>',
            '</method>',

            # Methods whose name does not have 'test' prefix should be ignored.
            '<method name="nonTestMethod"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</method>',

            # Methods whose return value is not void should be ignored.
            '<method name="testNonVoid"',
            ' return="int"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</method>',

            # Methods with parameters should be ignored.
            '<method name="testWithParams"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '<parameter name="arg0" type="int">',
            '</parameter>',
            '</method>',

            # Fields should be ignored.
            '<field name="testField"',
            ' type="int"',
            ' transient="false"',
            ' volatile="false"',
            ' static="false"',
            ' final="true"',
            ' visibility="public"',
            '>',
            '</field>',

            # One more simplest test method.
            '<method name="testMethod2"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</method>',

            '</class>',

            # Test for another class.
            '<class name="TestClass2"',
            ' extends="junit.framework.TestCase"',
            ' abstract="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '<method name="testMethod1"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</method>',
            '</class>',

            # Abstract class should be ignored, even if it contains a valid
            # test method.
            '<class name="TestAbstractClass"',
            ' extends="junit.framework.TestCase"',
            ' abstract="true"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '<method name="testMethod1"',
            ' return="void"',
            ' abstract="false"',
            ' native="false"',
            ' synchronized="false"',
            ' static="false"',
            ' final="false"',
            ' visibility="public"',
            '>',
            '</method>',
            '</class>',

            '</package>',
            '</api>']))))
