#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This script checks if both our code in internal/ and the Android internal
# checkout in the directory are up to date.

import logging
import os
import subprocess
import sys
import tempfile
import util.git

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ARC_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
_ARC_INTERNAL_DIR = os.path.join(_ARC_ROOT, 'internal')
_DEPS_FILE = os.path.join(_ARC_ROOT, 'src/build/DEPS.arc-int')
_GMS_CORE_DIR = os.path.join(_ARC_INTERNAL_DIR, 'third_party/gms-core')
_GMS_CORE_DEPS = os.path.join(_ARC_INTERNAL_DIR, 'build/DEPS.gms.xml')


def _get_current_arc_int_revision():
  return util.git.get_last_landed_commit(cwd=_ARC_INTERNAL_DIR)


def run():
  if not os.path.isdir(_ARC_INTERNAL_DIR):
    logging.error('This script only works when internal checkout exists.')
    sys.exit(-1)

  # Check if internal/ is up to date.
  with open(_DEPS_FILE) as f:
    target_revision = f.read().rstrip()
  if target_revision != _get_current_arc_int_revision():
    logging.error('The revision of internal/ (%s) does not match %s (%s). '
                  'Run src/build/sync_arc_int.py.' % (
                  _get_current_arc_int_revision(), _DEPS_FILE, target_revision))
    sys.exit(-1)

  # Check if the Android internal code is up to date.
  xml = tempfile.NamedTemporaryFile(prefix='repo_manifest_output_')
  # 'repo manifest' does not access the internal Android code repository.
  subprocess.check_call('repo manifest -o %s -r' % xml.name,
                        cwd=_GMS_CORE_DIR, shell=True)

  result = subprocess.call(['diff', xml.name, _GMS_CORE_DEPS])
  if result != 0:
    logging.error('Android internal source code is not up to date. '
                  'Run src/build/sync_arc_int.py.')
  return result


if __name__ == '__main__':
  sys.exit(run())
