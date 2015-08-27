# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tracks the state of ARC mods for rebasing purposes."""

import collections
import logging
import sys

from util.rebase import constants
from util.rebase import internal
from util.rebase import mod as rebase_mod


class State(object):
  def __init__(self):
    self._mods = collections.defaultdict(list)
    android_submodule_paths = internal.get_android_submodule_paths()
    for mod in rebase_mod.get_all_arc_android_mods():
      android_submodule_path = internal.identify_containing_submodule(
          mod.android_path, submodules=android_submodule_paths)
      # logging.debug('%s %s', android_submodule_path, mod.new_mod_path)
      self._mods[android_submodule_path].append(mod)

    self._verified_mods = []
    self._rebased_mods = []
    self._rebased_submodules = 0

  def verify_submodule_path(self, old_revision, module_path):
    logging.info('Verifying %d mods for %s at %s', len(self._mods[module_path]),
                 module_path, old_revision)
    android_sources = internal.lazy_find_all_files_under(module_path)
    for mod in self._mods[module_path]:
      logging.info('Verifying %s', mod.new_mod_path)
      mod.verify(old_revision, android_source_list=android_sources)
      self._verified_mods.append(mod)
    return all(not mod.status for mod in self._mods[module_path])

  def rebase_submodule_path(self, old_revision, module_path):
    self._rebased_submodules += 1
    for mod in self._mods[module_path]:
      self._rebased_mods.append(mod)
      mod.rebase(old_revision)

  def _report_status(self, message, mods):
    if not mods:
      return
    mods = sorted(mods, key=lambda mod: mod.new_mod_path)
    sys.stdout.write(message)
    for mod in mods:
        sys.stdout.write('\n    ')
        sys.stdout.write(mod.new_mod_path)
    sys.stdout.write('\n')

  def _print_report(self, mod_list):
    mod_by_status = collections.defaultdict(list)
    for mod in mod_list:
      mod_by_status[mod.status].append(mod)

    self._report_status(
        'These mods do not appear to be correct for the OLD source code:',
        mod_by_status[constants.RESULT_MOD_INCORRECT_FOR_OLD_VERSION])
    self._report_status(
        'The Android submodule path could not be indentified for the following '
        'mods:',
        mod_by_status[constants.RESULT_MOD_ANDROID_SUBMODULE_NOT_IDENTIFIED])
    self._report_status(
        'The following mods would have to be moved, but a file exists at the '
        'new location:',
        mod_by_status[constants.RESULT_MOD_EXISTS_AT_NEW_LOCATION])
    self._report_status(
        'The upstream source code could not be located for the following mods:',
        mod_by_status[constants.RESULT_REBASE_RESULT_NO_UPSTREAM])
    self._report_status(
        ('The following mods did not merge cleanly, and will need to be '
         'resolved manually:'),
        mod_by_status[constants.RESULT_NO_CLEAN_MERGE])
    self._report_status(
        ('The following mods still had unexpected differences after an '
         'otherwise clean merge. Use analyze_diffs to analyze what is wrong:'),
        mod_by_status[constants.RESULT_DIFFS_AFTER_MERGE])

  def print_report(self):
    self._print_report(set(self._verified_mods) | set(self._rebased_mods))

  def rebase_succeeded(self):
    return all(mod.status == constants.RESULT_OK
               for mod in self._rebased_mods)

  @property
  def rebased_mod_count(self):
    return len(self._rebased_mods)

  @property
  def rebased_submodule_count(self):
    return self._rebased_submodules
