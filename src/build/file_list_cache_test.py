#!/usr/bin/env python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittest for file_list_cache.py."""

import os
import re
import tempfile
import unittest

import file_list_cache


def _touch(path):
  open(path, 'w').close()


def _reset_timestamp():
  for root, dirs, files in os.walk('.'):
    for path in dirs + files:
      os.utime(os.path.join(root, path), (0, 0))


def _list_files(*args):
  cache = file_list_cache.FileListCache(file_list_cache.Query(*args))
  cache.refresh_cache()
  return list(cache.enumerate_files())


class FileListCacheUnittest(unittest.TestCase):
  def setUp(self):
    os.chdir(tempfile.mkdtemp())

    os.makedirs('foo/bar/baz')
    _touch('foo/bar/baz/hoge.cc')
    _touch('foo/bar/baz/fuga.py')

    _reset_timestamp()

  def testCacheFreshness(self):
    os.makedirs('foo/o/o')
    _touch('foo/o/o/o.cc')
    _touch('foo/o/o/o.h')
    _reset_timestamp()

    query = file_list_cache.Query(
        ['foo'], re.compile('.*\.cc'), True)
    cache = file_list_cache.FileListCache(query)

    # Cache should not be fresh here.
    self.assertFalse(cache.refresh_cache())

    # Cache should be fresh now.
    self.assertTrue(cache.refresh_cache())

    # New matched files should make the cache dirty.
    _touch('foo/bar/baz/piyo.cc')
    self.assertFalse(cache.refresh_cache())

    # Unmatched file should not affect the freshness.
    _touch('foo/bar/piyo.h')
    self.assertTrue(cache.refresh_cache())

    # Removing matched file should make the cache dirty.
    os.remove('foo/o/o/o.cc')
    self.assertFalse(cache.refresh_cache())

    os.remove('foo/o/o/o.h')
    self.assertTrue(cache.refresh_cache())

    os.rmdir('foo/o/o')
    self.assertFalse(cache.refresh_cache())

  def testListingFiles(self):
    self.assertEquals(_list_files(['foo'], re.compile('.*\.cc'), True),
                      ['foo/bar/baz/hoge.cc'])

    # include_subdirectory == False case.
    _touch('foo/oo.cc')
    self.assertEquals(_list_files(['foo'], re.compile('.*\.cc'), False),
                      ['foo/oo.cc'])

    # Multiple base_paths case.
    os.makedirs('oof/rab/zab')
    _touch('oof/rab/zab/aguf.py')
    self.assertEquals(_list_files(['foo', 'oof'], re.compile('.*\.py'), True),
                      ['oof/rab/zab/aguf.py', 'foo/bar/baz/fuga.py'])

  def testQueryEquality(self):
    query = file_list_cache.Query(['foo'], re.compile('.*\.cc'), True)
    query2 = file_list_cache.Query(['foo'], re.compile('.*\.h'), True)
    self.assertNotEquals(query, query2)

    query2.matcher = re.compile('.*\.cc')
    self.assertEquals(query, query2)

if __name__ == '__main__':
  unittest.main()
