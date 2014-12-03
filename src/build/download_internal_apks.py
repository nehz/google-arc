#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import os.path
import subprocess
import sys

import build_common
import download_common


_ROOT_DIR = build_common.get_arc_root()


class InternalApksDownload(download_common.BaseGetAndUnpackArchiveFromURL):
  """Handles syncing a pre-built internal APK archive."""
  NAME = 'internal apks'
  DEPS_FILE = os.path.join(_ROOT_DIR, 'src', 'build', 'DEPS.internal-apks')
  FINAL_DIR = os.path.join(_ROOT_DIR, 'out', 'internal-apks')
  STAGE_DIR = os.path.join(_ROOT_DIR, 'out', 'internal-apks.bak')
  DOWNLOAD_NAME = 'internal-apks.zip'

  @classmethod
  def _unpack_update(cls, download_file):
    subprocess.check_call(['unzip', '-d', cls.STAGE_DIR, download_file])


def check_and_perform_updates():
  return not InternalApksDownload.check_and_perform_update()


def main():
  return check_and_perform_updates()


if __name__ == '__main__':
  sys.exit(main())
