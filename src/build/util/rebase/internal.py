# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Internal helper/utility code."""

import contextlib
import logging
import os
import subprocess
import sys
import tempfile

from src.build import analyze_diffs
from src.build.util import git
from src.build.util.rebase import constants


def relpath(path, base_path):
  """Given a path |path|, returns a version of it relative to |base_path|."""
  return os.path.relpath(os.path.abspath(path), base_path)


def ensure_directory_exists(path):
  """Ensure the directory |path| exists, creating it if necessary."""
  if not os.path.isdir(path):
    os.makedirs(path)


def find_all_files_under(base_path):
  """Enumerates every file contained under |base_path|."""
  for root, dirs, files in os.walk(base_path):
    for path in files:
      yield os.path.join(root, path)


def lazy_find_all_files_under(base_path):
  """Lazily gets the list of files contained under |base_path|.

  This allows the list to be retrieved only when it actually needs to be
  enumerated.
  """
  class _LazyContainer(object):
    def __init__(self, base_path):
      self._files = None
      self._base_path = base_path

    def __iter__(self):
      if self._files is None:
        self._files = list(find_all_files_under(self._base_path))
      return iter(self._files)
  return _LazyContainer(base_path)


def get_android_path_for_mod(mod_path):
  """Returns the path to the upstream Android file being modified by a mod."""
  tracking_path = analyze_diffs.get_tracking_path(
      mod_path, check_exist=False, check_uses_tags=True)

  if tracking_path is None:
    logging.debug('No tracking path for %s', mod_path)
    return None

  # Some paths under third_party/android/chromium_org/third_party actually link
  # to third_party/android/chromium_org__third_party_*.
  tracking_path = os.path.realpath(tracking_path)

  tracking_path = relpath(tracking_path, constants.ARC_ROOT)

  if not tracking_path.startswith(constants.ANDROID_SUBMODULE_PATH):
    logging.debug('Not under ANDROID_SUBMODULE_PATH for %s (%s)', mod_path,
                  tracking_path)
    return None

  logging.debug('Found a tracking path of %s for %s', tracking_path, mod_path)
  return tracking_path


def validate_android_mod(mod_path, android_base_path):
  """Checks that |mod_path| is a valid mod of |android_base_path|"""
  stats = analyze_diffs.construct_stats(
      mod_path, android_base_path, display_errors=False)
  analyze_diffs.analyze_diff(stats, mod_path, android_base_path)
  return not stats['errors']


def get_mod_path_for_android_path(android_path):
  """Returns the default mod path corresponding to the given Android path."""
  if android_path.startswith(constants.ANDROID_SUBMODULE_PATH):
    return os.path.join('mods', os.path.relpath(android_path, 'third_party'))
  return None


def find_new_android_path(sources, old_android_path):
  """Tries to find an Android source code file that has been moved.

  After a version upgrade, mods may be present for files that have been moved
  around in the Android tree. This function helps locate the Android code, so
  the mod can be properly updated.

  |sources| is a list of Android sources to try and find a match in.
  |old_android_path| is the path a source file used to have.

  Returns the path to the moved file, or None if no file could be located.
  """
  for path in sources:
    if os.path.basename(path) == os.path.basename(old_android_path):
      return path
  return None


def get_android_submodule_paths():
  """Get all the Android submodule paths currently used by ARC."""

  # Note we sort by longest path to smallest path
  # for identify_containing_submodule().
  return sorted(
      (submodule.path for submodule in git.get_submodules(constants.ARC_ROOT,
                                                          use_gitmodules=True)
       if submodule.path.startswith(constants.ANDROID_SUBMODULE_PATH)),
      key=lambda path: len(path), reverse=True)


def ensure_android_submodule_paths(paths):
  """Ensures that we have a valid list of Android submodules."""
  if paths is None:
    paths = get_android_submodule_paths()
  return paths


def identify_containing_submodule(path, submodules=None):
  """Determine the path to the submodule containing the given |path|.

  The path is found by looking through all the submodules for the one with the
  longest common prefix."""

  # Make sure we have the submodule information.
  submodules = ensure_android_submodule_paths(submodules)

  # Create a dummy default match.
  containing_module = ''

  # Check all the submodules for a better path match.
  for module_path in submodules:
    if (path.startswith(module_path + '/') and
        len(module_path) > len(containing_module)):
      containing_module = module_path

  logging.debug('identify_containing_submodule(%s) -> %s', path,
                containing_module or None)

  # Return the path to the submodule, or None if not found.
  return containing_module or None


def write_old_file_content(revision, path, module_path, write_path):
  """Write out a specific revision of a file |path| to |tmp_path|.

  The file is assumed to exist in git at the given |revision|. """

  logging.debug('write_old_file_content(%s, %s, %s, %s)', revision, path,
                module_path, write_path)
  ensure_directory_exists(os.path.dirname(write_path))
  with open(write_path, 'w') as f:
    f.write(git.get_file_at_revision(
        revision, os.path.relpath(path, module_path), cwd=module_path))


@contextlib.contextmanager
def old_file_content(revision, path, module_path):
  os_handle, tmp_path = tempfile.mkstemp()
  write_old_file_content(revision, path, module_path, tmp_path)

  yield tmp_path

  os.close(os_handle)
  os.remove(tmp_path)


# TODO(lpique) This and util.git._subprocess_check_output are the same thing.
# Move them to a common utility module.
def quiet_subprocess_call(cmd, cwd=None):
  try:
    subprocess.check_output(cmd, cwd=cwd)
  except subprocess.CalledProcessError as e:
    logging.error('While running %s%s', cmd, (' in ' + cwd) if cwd else '')
    if e.output:
      logging.error(e.output)
    raise


def add_to_staging(path):
  """Issue a "git add" command to add |path| to staging."""
  quiet_subprocess_call(['git', 'add', path])


def move_mod_file(old_path, new_path):
  """Issue a "git mv" command if necessary to move |old_path| to |new_path|."""

  # Do nothing if the path does not actually need to change.
  if new_path == old_path:
    return

  if os.path.exists(new_path):
    sys.exit('Unable to move "%s" to "%s" -- the destination file already '
             'exists.' % (old_path, new_path))
  ensure_directory_exists(os.path.dirname(new_path))
  quiet_subprocess_call(['git', 'mv', old_path, new_path])


def merge3(mod_path, old_base_path, new_base_path):
  """Perform a three way merge.

  The modification in |mod_path| is updated in-place based on the base file
  |old_base_path| being changed to |new_base_path|.

  Returns True if the merge succeeded cleanly or False if the file did not merge
  cleanly."""

  try:
    subprocess.check_output(['merge', mod_path, old_base_path, new_base_path],
                            stderr=subprocess.STDOUT)
    return True
  except subprocess.CalledProcessError as e:
    # Merge exits with a code of 1 if the merge failed.
    if e.returncode != 1:
      raise
    return False
