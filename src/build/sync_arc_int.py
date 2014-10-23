#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This script is responsible for syncing arc-int checkout inside of an ARC
# checkout.  It is not capable to detect changes inside arc-int repo, so it
# really just syncs arc-int to DEPS.arc-int, then syncs gms-core.

import logging
import os
import subprocess
import sys
import util.git

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ARC_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
_ARC_INTERNAL_DIR = os.path.join(_ARC_ROOT, 'internal')
_DEPS_FILE = os.path.join(_ARC_ROOT, 'src', 'build', 'DEPS.arc-int')


def _get_current_arc_int_revision():
  return util.git.get_last_landed_commit(cwd=_ARC_INTERNAL_DIR)


def _git_has_local_modification():
  if util.git.get_current_branch_name(cwd=_ARC_INTERNAL_DIR) != 'master':
    return True  # not on master
  if util.git.get_uncommitted_files(cwd=_ARC_INTERNAL_DIR):
    return True  # found modified or staged file(s)
  return False


def sync_repo(target_revision):
  util.git.reset_to_revision(target_revision, cwd=_ARC_INTERNAL_DIR)
  logging.info('Reset to arc-int to ' + target_revision)


def run():
  if not os.path.isdir(_ARC_INTERNAL_DIR):
    logging.error('This script only works when internal checkout exists.')
    sys.exit(-1)

  if _git_has_local_modification():
    logging.warning('Skip syncing internal/. Stash or revert your local '
                    'change(s) in internal/ and/or checkout master if you '
                    'need to sync the internal directory.')
  else:
    with file(_DEPS_FILE) as f:
      target_revision = f.read().rstrip()
    if target_revision != _get_current_arc_int_revision():
      sync_repo(target_revision)

  subprocess.check_call('build/configure.py', cwd=_ARC_INTERNAL_DIR)
  return 0


if __name__ == '__main__':
  sys.exit(run())
