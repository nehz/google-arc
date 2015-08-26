# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from util import python_deps


class TestPythonDeps(unittest.TestCase):
  def test_normal_success(self):
    # Get the dependencies of this test module.
    deps = python_deps.find_deps('src/build/util/python_deps_test.py')

    # build_common is imported by python_deps, which we import.
    self.assertIn('src/build/build_common.py', deps)

    # python_deps is something we import directly.
    self.assertIn('src/build/util/python_deps.py', deps)

    # The dependencies should include the file at the root of the search.
    self.assertIn('src/build/util/python_deps_test.py', deps)

    # We should not see any standard library modules such as 'unittest' which
    # this test imports.
    for path in deps:
      self.assertNotRegexpMatches(path, r'\Wunittest\W')


if __name__ == '__main__':
  unittest.main()
