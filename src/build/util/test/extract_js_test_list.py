# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Extracts a list of test methods from .js files."""

import re
import sys


def _parse_test_list(content):
  test_list = []
  for m in re.finditer(
      r'^TEST_F\(\s*(\w+)\s*,\s*(?:\'|")(\w+)(?:\'|")\s*,\s*function\(\)',
      content, re.MULTILINE):
    test_list.append('%s#%s' % (m.group(1), m.group(2)))
  return test_list


def _extract_test_list(path):
  with open(path) as stream:
    content = stream.read()
  return _parse_test_list(content)


def main():
  test_list = []
  for path in sys.argv[1:]:
    test_list.extend(_extract_test_list(path))

  test_list.sort()
  for test_method in test_list:
    print test_method


if __name__ == '__main__':
  sys.exit(main())
