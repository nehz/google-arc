#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for download_package_util."""

import logging
import os
import shutil
import tempfile
import unittest

from util import download_package_util


class NoVersionFileError(Exception):
  pass


class TestPackageStub(download_package_util.BasicCachedPackage):
  """Records information about what functions were called."""
  def __init__(self, mock, deps_path, final_path, cache_base_path,
               url=None, link_subdir=None):
    super(TestPackageStub, self).__init__(
        deps_path, final_path, url=url, link_subdir=link_subdir,
        unpack_method=self.unpack_update, cache_base_path=cache_base_path,
        cache_history_size=3)
    self.mock = mock

  def _download_package_with_retries(self, url, download_package_path):
    return self.mock.retrieve(url, download_package_path)

  def unpack_update(self, download_file, unpack_path):
    return self.mock.unpack_update(download_file, unpack_path)

  def post_update_work(self):
    return self.mock.post_update_work(self.unpacked_cache_path)


class NoUpdateMock(object):
  def __init__(self, test):
    self._test = test

  def retrieve(self, url, download_file):
    self._test.fail('Unexpected call to retrieve()')

  def unpack_update(self, download_file, unpack_path):
    self._test.fail('Unexpected call to unpack_update()')

  def post_update_work(self, cache_path):
    self._test.fail('Unexpected call to post_update_work()')


class DownloadFailedMock(object):
  def __init__(self, test):
    self._test = test

  def retrieve(self, url, download_file):
    assert False

  def unpack_update(self, download_file, unpack_path):
    self._test.fail('Unexpected call to unpack_update()')

  def post_update_work(self, cache_path):
    self._test.fail('Unexpected call to post_update_work()')


class UpdateMock(object):
  def __init__(self, test, version, url, link_subdir=None):
    self._test = test
    self.retrieved = False
    self.unpacked = False
    self.post_update = False
    self.version = version or 'unknown'
    self.link_subdir = link_subdir
    self.url = url

  def retrieve(self, url, download_file):
    self._test.assertFalse(self.retrieved)
    self._test.assertEqual(url, self.url)
    self.retrieved = True

  def unpack_update(self, download_file, unpack_path):
    self._test.assertFalse(self.unpacked)
    self.unpacked = True
    os.makedirs(os.path.join(unpack_path, self.link_subdir))

  def post_update_work(self, cache_path):
    self._test.assertFalse(self.post_update)
    self.post_update = True


class DownloadPackageUtilTest(unittest.TestCase):
  def setUp(self):
    logging.basicConfig(level=logging.DEBUG)
    self._deps_file = os.path.join(tempfile.mkdtemp(), 'DEPS.testing')
    self._final_dir = tempfile.mkdtemp()
    self._cache_base_path = tempfile.mkdtemp()

  def tearDown(self):
    # clean up temporary files
    shutil.rmtree(os.path.dirname(self._deps_file), ignore_errors=True)
    shutil.rmtree(self._final_dir, ignore_errors=True)
    shutil.rmtree(self._cache_base_path, ignore_errors=True)

  def _setup_deps(self, version):
    with open(self._deps_file, 'w') as f:
      f.write(version or 'unknown')

  def _create_stub(self, mock, url=None, link_subdir=None):
    self._stub = TestPackageStub(
        mock, self._deps_file, self._final_dir, self._cache_base_path, url=url,
        link_subdir=link_subdir)
    return self._stub

  def _setup_cache(self, version):
    version = version or 'unknown'
    cache_path = self._stub._get_cache_entry_path([version])
    os.makedirs(os.path.join(cache_path, self._stub._link_subdir))
    with open(os.path.join(cache_path, self._stub._link_subdir, 'URL'),
              'w') as f:
      f.write(version)

  def _setup_final(self, version):
    version = version or 'unknown'
    with open(os.path.join(self._stub.unpacked_final_path, 'URL'), 'w') as f:
      f.write(version)

  def _check_cache(self, version):
    version = version or 'unknown'
    cache_path = self._stub._get_cache_entry_path([version])
    url_path = os.path.join(cache_path, self._stub._link_subdir, 'URL')
    if not os.path.isfile(url_path):
      raise NoVersionFileError(url_path)
    with open(url_path) as f:
      return version == f.read().strip()

  def _check_final(self, version):
    version = version or 'unknown'
    url_path = os.path.join(self._stub.unpacked_final_path, 'URL')
    if not os.path.isfile(url_path):
      raise NoVersionFileError(url_path)
    with open(url_path) as f:
      return version == f.read().strip()

  def test_no_update_needed(self):
    self._setup_deps('v1')
    stub = self._create_stub(NoUpdateMock(self), link_subdir='sub')
    self._setup_cache('v1')

    stub.check_and_perform_update()

  def test_cache_populated_from_final(self):
    self._setup_deps('v1')
    stub = self._create_stub(NoUpdateMock(self), link_subdir='sub')
    self._setup_final('v1')

    stub.check_and_perform_update()
    self.assertTrue(self._check_cache('v1'))

  def test_final_populated_from_cache(self):
    self._setup_deps('v2')
    stub = self._create_stub(NoUpdateMock(self), link_subdir='sub')
    self._setup_final('v1')
    self._setup_cache('v2')

    stub.check_and_perform_update()
    self.assertTrue(self._check_final('v2'))

  def test_cache_and_final_not_populated_from_failed_download(self):
    mock = DownloadFailedMock(self)
    self._setup_deps('v2')
    stub = self._create_stub(mock, link_subdir='sub')
    self._setup_final('v1')

    self.assertRaises(AssertionError, stub.check_and_perform_update)
    self.assertRaises(NoVersionFileError, self._check_cache, 'v2')
    self.assertRaises(NoVersionFileError, self._check_final, 'v2')
    self.assertRaises(NoVersionFileError, self._check_final, 'v1')

  def test_cache_and_final_populated_from_download(self):
    url = 'http://example.com/test_download.zip'
    mock = UpdateMock(self, 'v1', url, link_subdir='sub')
    self._setup_deps('v1')
    stub = self._create_stub(mock, url=url, link_subdir='sub')

    stub.check_and_perform_update()

    self.assertTrue(mock.retrieved)
    self.assertTrue(mock.unpacked)
    self.assertTrue(mock.post_update)
    self.assertTrue(self._check_cache('v1'))
    self.assertTrue(self._check_final('v1'))

  def test_cache_files_limited_correctly(self):
    def _rollTo(version):
      mock = UpdateMock(self, version, version, link_subdir='sub')
      self._setup_deps(version)
      stub = self._create_stub(mock, link_subdir='sub')
      stub.check_and_perform_update()

    def _rollToCached(version):
      mock = NoUpdateMock(self)
      self._setup_deps(version)
      stub = self._create_stub(mock, link_subdir='sub')
      stub.check_and_perform_update()

    _rollTo('v1')
    self.assertTrue(self._check_cache('v1'))
    self.assertTrue(self._check_final('v1'))

    _rollTo('v2')
    self.assertTrue(self._check_cache('v1'))
    self.assertTrue(self._check_cache('v2'))
    self.assertTrue(self._check_final('v2'))

    _rollTo('v3')
    self.assertTrue(self._check_cache('v1'))
    self.assertTrue(self._check_cache('v2'))
    self.assertTrue(self._check_cache('v3'))
    self.assertTrue(self._check_final('v3'))

    _rollTo('v4')
    self.assertRaises(NoVersionFileError, self._check_cache, 'v1')
    self.assertTrue(self._check_cache('v2'))
    self.assertTrue(self._check_cache('v3'))
    self.assertTrue(self._check_cache('v4'))
    self.assertTrue(self._check_final('v4'))

    _rollToCached('v2')
    self.assertRaises(NoVersionFileError, self._check_cache, 'v1')
    self.assertTrue(self._check_cache('v2'))
    self.assertTrue(self._check_cache('v3'))
    self.assertTrue(self._check_cache('v4'))
    self.assertTrue(self._check_final('v2'))

    _rollTo('v5')
    self.assertRaises(NoVersionFileError, self._check_cache, 'v1')
    self.assertTrue(self._check_cache('v2'))
    self.assertRaises(NoVersionFileError, self._check_cache, 'v3')
    self.assertTrue(self._check_cache('v4'))
    self.assertTrue(self._check_cache('v5'))
    self.assertTrue(self._check_final('v5'))

if __name__ == '__main__':
  unittest.main()
