#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import fnmatch
import md5
import os.path
import subprocess
import sys

import build_common
import check_chrome_lkgr
import convert_docs
import lint_source
import util.git
import staging
import suggest_reviewers

"""A git pre-push hook script."""


def _is_patch_to_next_pastry():
  """Determines if the current patch is to arc/next-pastry or not."""
  return util.git.get_branch_tracked_remote_url().endswith('arc/next-pastry')


def _check_uncommitted_change():
  uncommitted_files = util.git.get_uncommitted_files()
  if uncommitted_files:
    print ''
    print 'Please commit or stash the following uncommitted files.'
    print '\n'.join(uncommitted_files)
    print ''
    return -1
  return 0


def _check_lint(push_files):
  ignore_file = os.path.join('src', 'build', 'lint_ignore.txt')
  # If push_files contains any directories (representing submodules), filter
  # them out. Passing a directory to the lint_source.process will cause all
  # the files in that directory to be checked for lint errors, when those files
  # may not even conform to the standards of the current project.
  push_files = filter(os.path.isfile, push_files)
  result = lint_source.process(push_files, ignore_file)
  if result != 0:
    print ''
    print 'lint_source.py reports there are issues with the code you are trying'
    print 'to submit.  Buildbot will run the same checks and fail if you do not'
    print 'fix or suppress them. See docs/source-code-style-tools.md for how'
    print 'to suppress the errors if they are false alarms.'
    print ''
  return result


def _check_build_steps():
  build_steps = os.path.join('src', 'buildbot', 'build_steps.py')
  result = subprocess.call([build_steps, '--test', '--silent'])
  if result != 0:
    print ''
    print 'build_steps.py reports there are issues with the recipes you are'
    print 'trying to submit.  Buildbot will run the same checks and fail.'
    print 'Run "./src/buildbot/build_steps.py --train" to update the recipes.'
    print ''
  return result


def _check_prebuilt_chrome_deps(push_files):
  chrome_deps_file = build_common.get_chrome_deps_file()
  if chrome_deps_file not in push_files:
    return 0
  with open(chrome_deps_file) as f:
    revision = f.read().strip()
  if not check_chrome_lkgr.check_all_prebuilt_chrome(revision, True):
    print ''
    print 'check_chrome_lkgr.py reports there is no prebuilt chrome binary '
    print 'corresponding to the chrome revision you are trying to submit. '
    print 'Run "./src/build/check_chrome_lkgr.py" to pick an LKGR.'
    print ''
    return -1
  return 0


def _check_android_deps(push_files):
  android_deps_file = build_common.get_android_deps_file()
  if android_deps_file not in push_files:
    return 0
  with open(android_deps_file) as f:
    linecount = len(f.readlines())
  # For normal purposes, we expect that the DEPS.android file will contain just
  # a single line naming an Android release branch tag, or a very small file
  # mapping a few subprojects to specific release tags, with a default mapping
  # of the official Android branch tag used for everything else.
  # For arc/next-pastry we allow it to be an Android manifest file, which
  # identifies git hash tags for each Android sub-project. However these
  # sub-project names may be confidential, and should not be published, so we
  # have this check to help ensure that does not happen accidentally.
  if linecount > 10:
    if not _is_patch_to_next_pastry():
      print ''
      print 'DEPS.android appears to be something other than a simple file'
      print 'naming a publicly visible branch tag.  Any other content should'
      print 'be restricted to arc/next-pastry.'
      print ''
      return -1


def _check_ninja_lint_clean_after_deps_change(push_files):
  # Watch out for any deps changes that could impact mods
  prefix_pattern = os.path.join('src', 'build', 'DEPS.')
  if not any(name.startswith(prefix_pattern) for name in push_files):
    return 0
  return subprocess.call(['ninja', 'lint'])


def _check_commit_messages():
  MAX_COLS = 100
  error = False
  changes = util.git.get_in_flight_commits()
  for change in changes:
    msg = util.git.get_commit_message(change)
    seen_change_id = False
    trailing_lines = False
    for line_num, line in enumerate(msg):
      if len(line) > MAX_COLS:
        print 'Commit %s line %d is too long:' % (change, line_num + 1)
        print line
        print (' ' * MAX_COLS) + ('^' * (len(line) - MAX_COLS))
        error = True
      if seen_change_id:
        trailing_lines = True
      if line.startswith('Change-Id:'):
        seen_change_id = True
    if not seen_change_id:
      print 'Commit %s does not have a Change-Id label' % change
      error = True
    elif trailing_lines:
      print 'Commit %s has trailing lines after Change-Id label' % change
      error = True
  if error:
    return -1
  return 0


def _check_docs(push_files):
  """Check if files in 'docs' directory are valid.

  Ensure that files in 'docs' are named and formatted correctly.
  """

  doc_files = fnmatch.filter(push_files, 'docs/*.*')
  if not convert_docs.validate_docs(doc_files):
    print ''
    print 'convert_docs.py reports there are issues with the docs you are '
    print 'trying to submit.  Run '
    print '"./src/build/convert_docs --validate docs/*.md" to validate.'
    print ''
    return -1
  return 0


def _get_file_list_digest(files):
  digest = md5.new()
  for f in sorted(files):
    digest.update(f)
    # Add a file path separator.  chr(1) is unlikely to be part of a
    # file path.
    digest.update(chr(1))
  return digest.hexdigest()


def _has_file_list_changed_since_last_push(files):
  file_list_digest = _get_file_list_digest(files)
  old_file_list_digest = util.git.get_branch_specific_config('filelist')
  if not old_file_list_digest:
    return True
  return old_file_list_digest != file_list_digest


def _save_file_list(files):
  util.git.set_branch_specific_config('filelist', _get_file_list_digest(files))


# Export for other repo to reuse.
def get_push_files():
  last_landed_commit = util.git.get_last_landed_commit()
  # Find out what files have changed since last landed commit
  #   * That are staged (--cached) -- this speeds up the check
  #   * Returning their names as a simple list (--name-only)
  #   * That are not deleted (--diff-filter=ACM)
  cmd = ('git diff %s --cached --name-only --diff-filter=ACM' %
         last_landed_commit)
  push_files = subprocess.check_output(cmd, shell=True).splitlines()

  # Remove files that will confuse analyze_diffs
  return filter(
      lambda f: not f.startswith(staging.TESTS_BASE_PATH),
      push_files)


def main():
  push_files = get_push_files()
  if not push_files:
    return 0

  non_push_file_checks = [
      _check_uncommitted_change,
      _check_commit_messages,
      _check_build_steps,
  ]

  push_file_checks = [
      _check_lint,
      _check_prebuilt_chrome_deps,
      _check_android_deps,
      _check_ninja_lint_clean_after_deps_change,
      _check_docs,
  ]

  for check in non_push_file_checks:
    result = check()
    if result != 0:
      return result

  for check in push_file_checks:
    result = check(push_files)
    if result != 0:
      return result

  if _has_file_list_changed_since_last_push(push_files):
    suggest_reviewers.suggest_reviewer_set_for_in_flight_commits(False)
    # Add some space to make sure this is visible to the user as
    # lots of extra push noise will be shown immediately after.
    print ''
  _save_file_list(push_files)
  return 0


if __name__ == '__main__':
  sys.exit(main())
