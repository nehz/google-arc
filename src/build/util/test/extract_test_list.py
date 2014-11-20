# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Extracts a list of test methods from .apk file.

This script dumps the method signatures in the .apk file by dexdump,
and finds the test methods from them.
"""

import argparse
import subprocess
from xml.etree import ElementTree

import toolchain


def _parse_apk(apk_path):
  """Parses the XML meta data of classes.dex in the given .apk file."""
  parsed_data = subprocess.check_output([
      toolchain.get_tool('java', 'dexdump'), apk_path, '-lxml'])
  return ElementTree.fromstring(parsed_data)


def _extract_test(dex_xml):
  """Extracts a list of test cases from the parsed XML metadata of classes.dex.

  This function takes a parsed XML element tree, which is the output of
  "dexdump -lxml", and extracts a list of the test cases in the following form.

  package.name.TestClass1#testMethod1
  package.name.TestClass1#testMethod2
  package.name.TestClass2#testMethod1
      :
  """
  # Please see android.test.suitebuilder.TestGrouping in
  # android/frameworks/base/test-runner/src/android/test/suitebuilder/ for
  # the default condition for the tests to be included.

  test_name_list = []
  for package_node in dex_xml:
    assert package_node.tag == 'package'
    package_name = package_node.get('name')

    for class_node in package_node:
      assert class_node.tag == 'class'
      class_name = class_node.get('name')

      # See android.test.suitebuilder.TestGrouping$TestCasePredicate#apply().
      if (class_node.get('visibility') != 'public' or
          class_node.get('abstract') == 'true'):
        # To keep the condition simpler, we ignore following condition checks:
        # - Check if the class has a valid constructor. (see the referred
        #   method for the definition of "valid").
        # - Check if it inherits TestCase or not.
        continue

      for member_node in class_node:
        # Ignore non-method members.
        if member_node.tag != 'method':
          continue

        # We expect all methods in concrete class (non-abstract class) are
        # non-abstract.
        assert member_node.get('abstract') == 'false'

        # Accept only "public void testMethodName()" style functions.
        # Please see also
        # android.test.suitebuilder.TestGroup$TestMethodPredicate$apply()
        # for more details.
        if (member_node.get('visibility') != 'public' or
            member_node.get('return') != 'void' or
            not member_node.get('name').startswith('test') or
            len(member_node)):  # This means it has some arguments.
          continue

        # The output format is "package.name.ClassName#testMethodName"
        test_name_list.append(
            '%s.%s#%s' % (package_name, class_name, member_node.get('name')))
  return test_name_list


def _parse_args():
  parser = argparse.ArgumentParser(
      description='Create a list of test methods in .apk file')
  parser.add_argument('--apk', dest='apk', help='path to input apk file')
  parser.add_argument('--output', dest='output', help='path to output file')
  return parser.parse_args()


def main():
  args = _parse_args()

  dex_xml = _parse_apk(args.apk)
  test_list = _extract_test(dex_xml)
  if args.output:
    with open(args.output, mode='w') as stream:
      stream.write('\n'.join(test_list))
      stream.write('\n')
  else:
    print '\n'.join(test_list)


if __name__ == '__main__':
  main()
