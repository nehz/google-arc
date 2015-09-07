#!src/build/run_python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

from src.build import build_common
from src.build import toolchain
from src.build.build_options import OPTIONS
from src.build.util import file_util

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ARC_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))

_SUBAPK_PATH = 'assets/chimera-modules'
_SUBAPK_PATTERN = os.path.join(_SUBAPK_PATH, '*.apk')
_INSTALL_LOCATION_PATTERN = os.path.join('/data/data/com.google.android.gms',
                                         'files/chimera-modules/module-%s/%s')


def _calc_sha1(path):
  """Calculates the SHA1 checksum of the file.

  The SHA1 digest is used to derive the path where the inner apk (and the odex)
  is expanded during runtime.
  """
  calc = hashlib.sha1()
  with open(path, 'r') as f:
    calc.update(f.read())
  return calc.hexdigest()


def _preoptimize_subapk(src_apk, dest_apk, work_dir):
  # Extract inner apks from |src_apk|.
  # Note that we cannot use Python zipfile module for handling apk.
  # See: https://bugs.python.org/issue14315.
  subprocess.call(['unzip', '-q', src_apk, _SUBAPK_PATTERN, '-d', work_dir])
  inner_apk_list = file_util.glob(os.path.join(work_dir, _SUBAPK_PATTERN))

  # Optimize each apk and place the output odex next to the apk.
  odex_files = []
  for apk_path in inner_apk_list:
    apk_name = os.path.basename(apk_path)
    odex_name = re.sub(r'\.apk$', '.odex', apk_name)
    odex_path_in_apk = os.path.join(_SUBAPK_PATH, odex_name)
    odex_path = os.path.join(work_dir, odex_path_in_apk)
    odex_files.append(odex_path_in_apk)
    install_path = _INSTALL_LOCATION_PATTERN % (_calc_sha1(apk_path), apk_name)

    dex2oat_cmd = [
        'src/build/filter_dex2oat_warnings.py',
        toolchain.get_tool('java', 'dex2oat')
    ] + build_common.get_dex2oat_for_apk_flags(
        apk_path=apk_path,
        apk_install_path=install_path,
        output_odex_path=odex_path)
    if subprocess.call(dex2oat_cmd, cwd=_ARC_ROOT) != 0:
      print 'ERROR: preoptimize failed for %s.' % apk_path
      return False

  # Prepare |dest_apk|.
  shutil.copyfile(src_apk, dest_apk)

  # Add odex files to |dest_apk| by using aapt.
  if odex_files:
    aapt_add_cmd = [os.path.join(_ARC_ROOT, toolchain.get_tool('java', 'aapt')),
                    'add', os.path.join(_ARC_ROOT, dest_apk)] + odex_files
    with open(os.devnull, 'w') as devnull:
      if subprocess.call(aapt_add_cmd, cwd=work_dir, stdout=devnull) != 0:
        print 'ERROR: adding odex files to %s failed.' % dest_apk
        file_util.remove_file_force(dest_apk)
        return False
  return True


def main():
  OPTIONS.parse_configure_file()

  parser = argparse.ArgumentParser(
      description='Apply dex2oat to sub apks contained as assets in GmsCore.')
  parser.add_argument('--input', required=True, help='input apk')
  parser.add_argument('--output', required=True, help='output apk')
  args = parser.parse_args()

  work_dir = tempfile.mkdtemp()
  try:
    return 0 if _preoptimize_subapk(args.input, args.output, work_dir) else 1
  finally:
    file_util.rmtree(work_dir)


if __name__ == '__main__':
  sys.exit(main())
