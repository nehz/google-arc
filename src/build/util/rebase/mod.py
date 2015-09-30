# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tracks the rebase state of an individual ARC mod."""

import logging
import os

from src.build import staging
from src.build.util import git
from src.build.util.rebase import constants
from src.build.util.rebase import internal


class _ModState(object):
  def __init__(self, mod_path, android_path, android_module_path,
               uses_mod_track):
    self._mod_path = mod_path
    self._android_path = android_path
    self._android_module_path = android_module_path
    self._uses_mod_track = uses_mod_track
    self._verified = False
    self._status = None
    self._new_mod_path = mod_path
    self._new_android_path = android_path

  @property
  def android_path(self):
    return self._android_path

  @property
  def new_mod_path(self):
    return self._new_mod_path

  @property
  def status(self):
    return self._status

  def validate(self):
    if not internal.validate_android_mod(self._mod_path, self._android_path):
      self._status = constants.RESULT_MOD_INCORRECT_FOR_OLD_VERSION
      return False
    return True

  def _find_new_mod_path(self, force_new_mod_path, android_sources):
    if force_new_mod_path:
      self._new_mod_path = force_new_mod_path
      self._new_android_path = staging.get_default_tracking_path(
          force_new_mod_path)
    if os.path.exists(self._android_path):
      self._new_mod_path = self._mod_path
      self._new_android_path = self._android_path
    elif android_sources:
      if self._uses_mod_track:
        self._status = constants.RESULT_NO_UPSTREAM
        return

      # TODO(crbug.com/464948): While this basic search might work most of the
      # time, it needs to be improved further to handle finding renamed files,
      # and files moved to other subprojects (possibly renamed in the process).
      new_android_path = internal.find_new_android_path(
          android_sources, self._android_path)
      if not new_android_path:
        self._status = constants.RESULT_NO_UPSTREAM
        return

      self._new_mod_path = internal.get_mod_path_for_android_path(
          new_android_path)
      self._new_android_path = new_android_path
    else:
      self._status = constants.RESULT_NO_UPSTREAM

  def verify(self, old_revision, force_new_mod_path=None,
             android_source_list=None):
    if self._status is not None:
      return

    if not self._android_module_path:
      self._status = constants.RESULT_MOD_ANDROID_SUBMODULE_NOT_IDENTIFIED
      return

    # Verify the mod on disk validates against the copy of the old source file.
    with internal.old_file_content(
        old_revision, self._android_path,
        self._android_module_path) as tmp_android_path:
      if not internal.validate_android_mod(self._mod_path, tmp_android_path):
        logging.info('Detected error comparing %s to %s (%s at %s)',
                     self._mod_path, tmp_android_path, self._android_path,
                     old_revision)
        self._status = constants.RESULT_MOD_INCORRECT_FOR_OLD_VERSION
        return

    if self._status is not None:
      return

    self._find_new_mod_path(force_new_mod_path, android_source_list)

    # If the mod is moving, make sure there is not already a file in the new
    # location.
    if (self._new_mod_path != self._mod_path and
        os.path.exists(self._new_mod_path)):
      self._status = constants.RESULT_MOD_EXISTS_AT_NEW_LOCATION
      return

    self._verified = True

  def rebase(self, old_revision, force_new_mod_path=None):
    if not self._verified:
      self.verify(old_revision, force_new_mod_path)

    if self._status is not None:
      return

    # Move the mod to the new location if different from the old location
    internal.move_mod_file(self._mod_path, self._new_mod_path)

    with internal.old_file_content(
        old_revision, self._android_path,
        self._android_module_path) as tmp_android_path:
      # Attempt an automatic three-way merge using the mod, the old source code
      # and the new source code.
      if not internal.merge3(
          self._new_mod_path, tmp_android_path, self._new_android_path):
        self._status = constants.RESULT_NO_CLEAN_MERGE
        return

    if not internal.validate_android_mod(
        self._new_mod_path, self._new_android_path):
      self._status = constants.RESULT_NO_CLEAN_MERGE
      return

    git.add_to_staging(self._new_mod_path)
    self._status = constants.RESULT_OK


def get_arc_android_mod(mod_path, submodules=None):
  submodules = internal.ensure_android_submodule_paths(submodules)

  mod_path = internal.relpath(mod_path, constants.ARC_ROOT)
  android_path = internal.get_android_path_for_mod(mod_path)
  if not android_path:
    return None

  android_module_path = internal.identify_containing_submodule(
      android_path, submodules=submodules)

  uses_mod_track = android_path != staging.get_default_tracking_path(mod_path)

  return _ModState(mod_path, android_path, android_module_path, uses_mod_track)


def get_all_arc_android_mods(submodules=None):
  logging.info('Gathering a list of mods...')
  submodules = internal.ensure_android_submodule_paths(submodules)
  mod_count = 0
  for mod_path in internal.find_all_files_under(
      os.path.join(constants.ARC_ROOT, constants.ANDROID_MODS_PATH)):
    logging.debug('Considering %s', mod_path)
    mod = get_arc_android_mod(mod_path, submodules=submodules)
    if mod is None:
      continue
    yield mod
    mod_count += 1

  logging.info('%d mods found.', mod_count)
