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


def _git_has_local_modification():
  if util.git.get_current_branch_name(cwd=_ARC_INTERNAL_DIR) != 'master':
    return True  # not on master
  if util.git.get_uncommitted_files(cwd=_ARC_INTERNAL_DIR):
    return True  # found modified or staged file(s)
  return False


def sync_repo(target_revision):
  logging.info('Resetting %s to %s' % (_ARC_INTERNAL_DIR, target_revision))
  util.git.reset_to_revision(target_revision, cwd=_ARC_INTERNAL_DIR)


def run():
  # Check if internal/ exists. Run git-clone if not.
  if not os.path.isdir(_ARC_INTERNAL_DIR):
    # TODO(tandrii): Move this nacl-x86_64-bionic-internal recipe's botupdate
    # step.
    url = 'https://chrome-internal.googlesource.com/arc/internal-packages.git'
    logging.info('Cloning %s' % url)
    subprocess.check_call('git clone %s internal' % url,
                          cwd=_ARC_ROOT, shell=True)

  # Check if internal/ is clean and on master.
  if _git_has_local_modification():
    logging.error('%s has local modification' % _ARC_INTERNAL_DIR)
    sys.exit(-1)

  # Check if internal/ is up to date. Run git-reset if not.
  with open(_DEPS_FILE) as f:
    target_revision = f.read().rstrip()
  logging.info('%s has %s' % (_DEPS_FILE, target_revision))
  if target_revision != _get_current_arc_int_revision():
    sync_repo(target_revision)

  # Check if the Android internal code is up to date.
  xml = tempfile.NamedTemporaryFile(prefix='repo_manifest_output_')
  # 'repo manifest' does not access the internal Android code repository.
  subprocess.check_call(
      'repo manifest -o %s -r --suppress-upstream-revision' % xml.name,
      cwd=_GMS_CORE_DIR, shell=True)

  result = subprocess.call(['diff', xml.name, _GMS_CORE_DEPS])
  if result != 0:
    logging.error('Android internal source code is not up to date.  Please run '
                  'internal/build/configure.py to update the code.  If you are '
                  'trying to sync on buildbot, please refer to '
                  'internal/docs/rebasing.md')
  return result


if __name__ == '__main__':
  sys.exit(run())
