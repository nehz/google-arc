#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Download gdb-multiarch binary which is useful to debug ARM target.

import contextlib
import hashlib
import os
import posixpath
import subprocess
import sys
import urllib2

import build_common
from util import file_util


_UBUNTU_BASE_URL = 'http://us.archive.ubuntu.com/ubuntu/pool'
# List of pairs of package URL and its SHA256 checksum.
_GDB_PACKAGES = [
    (posixpath.join(_UBUNTU_BASE_URL, 'main/g/gdb/gdb_7.7-0ubuntu3_amd64.deb'),
     '9be5f35a8c2f8368594204896e2c238db4b22439c110c97e84f7d6004f323c2b'),
    (posixpath.join(_UBUNTU_BASE_URL,
                    'universe/g/gdb/gdb-multiarch_7.7-0ubuntu3_amd64.deb'),
     '0632211d40848196b5c41d85b8ea9a72677a877df1c8f0ef4c8bb54b34e73c1d'),
]


class Error(Exception):
  """An exception class raised in this module."""


@contextlib.contextmanager
def _change_directory(dirname):
  orig_dirname = os.getcwd()
  os.chdir(dirname)
  try:
    yield
  finally:
    os.chdir(orig_dirname)


def _download_and_verify_package(url, checksum, output_filename):
  print 'Downloading %s...' % url
  with contextlib.closing(urllib2.urlopen(url)) as response:
    content = response.read()

  sha256 = hashlib.sha256()
  sha256.update(content)
  actual_checksum = sha256.hexdigest()
  if checksum != actual_checksum:
    raise Error('Checksum mismatched for %s: expected=%s actual=%s' %
                (url, checksum, actual_checksum))

  with open(output_filename, 'w') as f:
    f.write(content)


def _extract_package(deb_filename):
  # Extract the deb file in the current directory.
  subprocess.check_call(['dpkg', '-x', deb_filename, '.'])


def main():
  stamp_content = ('\n'.join(
      '%s %s' % (checksum, url) for url, checksum in _GDB_PACKAGES) + '\n')
  stamp = build_common.StampFile(
      stamp_content,
      posixpath.join(build_common.get_gdb_multiarch_dir(), 'STAMP'))
  if stamp.is_up_to_date():
    return 0

  print 'Need to download gdb-multiarch'
  file_util.makedirs_safely(build_common.get_gdb_multiarch_dir())
  with _change_directory(build_common.get_gdb_multiarch_dir()):
    for url, checksum in _GDB_PACKAGES:
      deb_filename = posixpath.basename(url)
      _download_and_verify_package(url, checksum, deb_filename)
      _extract_package(deb_filename)

  stamp.update()
  return 0


if __name__ == "__main__":
  sys.exit(main())
