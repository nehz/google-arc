# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Extracts a list of Googletest style test methods from source codes."""

import argparse
import re
import sys


# In this script, we match the test method pattern with regular expression
# heuristically. There could be alternative approaches. For example,
# for C++, we may be able to extract the list by some tools such as nm/strings.
# Though, unfortunately, the text fixture name and test method name is
# concatenated by '_', so we cannot easily do it because we don't know where
# we should split the name.
# In order to avoid mis-extraction, we have verify it on run-time.
_CPP_TEST_METHOD_PATTERN = re.compile(
    r'^(?:TEST|TEST_F)\(\s*(\w+)\s*,\s*(\w+)\s*\)\s*{',
    re.MULTILINE)
_JAVASCRIPT_TEST_METHOD_PATTERN = re.compile(
    r'^TEST_F\(\s*(\w+)\s*,\s*(?:\'|")(\w+)(?:\'|")\s*,\s*function\(\)',
    re.MULTILINE)
_TEST_METHOD_PATTERN_MAP = {
    'c++': _CPP_TEST_METHOD_PATTERN,
    'javascript': _JAVASCRIPT_TEST_METHOD_PATTERN,
}


def _parse_test_list(stream, pattern):
  return ['%s#%s' % (m.group(1), m.group(2))
          for m in pattern.finditer(stream.read())]


def _parse_args():
  parser = argparse.ArgumentParser(
      description='Parse source code and extract a list of test methods.')
  parser.add_argument('--language', choices=['javascript', 'c++'],
                      help='Programming language written in the source code.')
  parser.add_argument('paths', metavar='PATH', nargs='+',
                      help='Paths to the input source code files.')
  return parser.parse_args()


def main():
  args = _parse_args()

  pattern = _TEST_METHOD_PATTERN_MAP[args.language]
  test_list = []
  for path in args.paths:
    with open(path) as stream:
      test_list.extend(_parse_test_list(stream, pattern))
  test_list.sort()

  for test_method in test_list:
    print test_method


if __name__ == '__main__':
  sys.exit(main())
