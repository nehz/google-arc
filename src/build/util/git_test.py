# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests covering git interaction code."""

import unittest

from util import git


# Without creating a fake git tree only used for testing, it is difficult
# to test git integration.  We test here only things that should never fail.
class TestUtilGit(unittest.TestCase):
  def setUp(self):
    self._ignore_checker = git.GitIgnoreChecker()

  def test_repository_gitignore_matching(self):
    self.assertTrue(self._ignore_checker.matches('foo.pyc'))
    self.assertFalse(self._ignore_checker.matches('foo.py'))

  def test_exclusion_gitignore_matching(self):
    self.assertTrue(self._ignore_checker.matches('out/foo.cc'))
    self.assertFalse(self._ignore_checker.matches(
                     'foo/bar/out/file/foo.cc'))
    self.assertFalse(self._ignore_checker.matches(
                     'mods/android/dalvik/vm/mterp/out/foo.cc'))

  def test_get_submodules_succeeds(self):
    submodules = git.get_submodules('.', True)
    self.assertTrue(any(['third_party/android' in s.path
                         for s in submodules]))
    # The following test essentially tests if you have stale entries
    # in .git/config. Removing entries from .gitmodules and running
    # "git submodule sync" does not remove entries from .git/config.
    submodules = git.get_submodules('.', False)
    self.assertTrue(any(['third_party/android' in s.path
                         for s in submodules]))

  def test_is_not_initial_commit(self):
    self.assertTrue(git.has_initial_commit())

  def test_get_head_revision(self):
    self.assertIsNotNone(git.get_head_revision())

  def test_get_origin_url(self):
    self.assertIsNotNone(git.get_origin_url())


if __name__ == '__main__':
  unittest.main()
