#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re
import subprocess
import sys
import traceback


_BUG_PREFIX = 'BUG='
_PERF_PREFIX = 'PERF='
_TEST_PREFIX = 'TEST='
_PREFIXES = [_TEST_PREFIX, _PERF_PREFIX, _BUG_PREFIX]

_CHANGED_FILE_RE = re.compile(r'.*?:\s+(.*)')
_CRBUG_URL_RE = re.compile(r'crbug.com/(\d{6,})')


def _append_prefixes(existing_prefixes, output_lines):
  """Appends missing prefix lines."""
  if len(existing_prefixes) != 3:
    # Remove trailing line breaks.
    while output_lines and output_lines[-1] == '\n':
      output_lines.pop()

    if not existing_prefixes:
      # Add a blank line before TEST/PERF/BUG lines if none present.
      output_lines.append('\n')
    for prefix in _PREFIXES:
      if prefix not in existing_prefixes:
        output_lines.append(prefix + '\n')
    # Add a space after what we added.
    output_lines.append('\n')


def add_mandatory_lines(lines):
  """Adds mandatory lines such as TEST= to the commit message."""
  output_lines = []
  existing_prefixes = set()
  while lines:
    line = lines.pop(0)
    for prefix in _PREFIXES:
      if line.startswith(prefix):
        existing_prefixes.add(prefix)
    if line.startswith('#') or line.startswith('Change-Id:'):
      lines = [line] + lines
      break
    output_lines.append(line)

  _append_prefixes(existing_prefixes, output_lines)
  return output_lines + lines


def get_bug_ids_from_diffs(diffs):
  """Gets removed bug IDs from diffs.

  When a bug is removed but also added into another line, this
  function does not return it.
  """
  added_bug_ids = set()
  removed_bug_ids = set()
  for diff in diffs:
    for diff_line in diff.splitlines():
      bug_ids = set(_CRBUG_URL_RE.findall(diff_line))
      if diff_line.startswith('+'):
        added_bug_ids.update(bug_ids)
      elif diff_line.startswith('-'):
        removed_bug_ids.update(bug_ids)
  return removed_bug_ids - added_bug_ids


def update_bug_line(lines, bug_ids):
  """Updates BUG= line.

  When no bug_ids is specified, this function does nothing. When
  bug_ids will be specified, add them into the existing BUG= line. In
  this case, this function removes existing bug description which
  claims there is no existing bug (e.g., N/A or None).
  """
  if not bug_ids:
    return lines

  def _reject_empty_bug(bug_id):
    return not re.match(r'(n/a|none)', bug_id, flags=re.IGNORECASE)

  for index, line in enumerate(lines):
    if line.startswith(_BUG_PREFIX):
      orig_bug_ids = re.split(r',\s*', line[len(_BUG_PREFIX):].strip())
      orig_bug_ids = [bug_id for bug_id in orig_bug_ids if bug_id]
      bug_ids.update(set(filter(_reject_empty_bug, orig_bug_ids)))
      orig_bug_ids_str = ', '.join(sorted(orig_bug_ids))
      bug_ids_str = ', '.join(sorted(bug_ids))
      if orig_bug_ids_str != bug_ids_str:
        if orig_bug_ids_str == '':
          lines[index] = _BUG_PREFIX + '%s\n' % bug_ids_str
        else:
          lines[index] = _BUG_PREFIX + '%s\n' % orig_bug_ids_str
          lines.insert(index + 1, '# Suggestion: %s%s\n' % (
              _BUG_PREFIX, bug_ids_str))
      return lines
  logging.error('No BUG= line')
  return lines


def _get_changed_files(base_git_commit):
  git_diff_output = subprocess.check_output([
      'git', 'diff', '--staged',
      '--diff-filter=ADM',  # List only {Add,Delete,Modify} changes.
      '--name-status', base_git_commit])
  # The output format of 'git diff --name-status' is something like:
  #
  # A       path/to/added_file
  # D       path/to/deleted_file
  # M       path/to/modified_file
  # ...
  return [line.split('\t')[1] for line in git_diff_output.splitlines()]


def _detect_and_update_bug_id(lines):
  """Updates BUG= line based on the change."""
  optional_args = sys.argv[2:]
  # Decide the base git commit from the type of this commit.
  if not optional_args:
    # A normal commit without --amend.
    base_git_commit = 'HEAD'
  elif optional_args == ['commit', 'HEAD']:
    # An --amend commit.
    base_git_commit = 'HEAD~'
  else:
    # It seems there are some other cases such as merge commit
    # but we do not support them as we do not use them often.
    return

  changed_files = _get_changed_files(base_git_commit)

  diffs = []
  for changed_file in changed_files:
    # MOD for Chromium code may contain non-ARC bugs.
    if changed_file.startswith('mods/') and 'chromium' in changed_file:
      continue
    # Whether or not the commit was -a, hooks run under the index staging all
    # changes to be committed. Thus, the desired diff is printed by --staged.
    diffs.append(subprocess.check_output(['git', 'diff', '--staged',
                                          base_git_commit, '--', changed_file]))

  bug_ids = get_bug_ids_from_diffs(diffs)
  lines = update_bug_line(lines, bug_ids)


if __name__ == '__main__':
  commit_file = sys.argv[1]
  with open(commit_file) as f:
    lines = f.readlines()

  lines = add_mandatory_lines(lines)
  # This function is not trivial and may raise an exception. As bug ID
  # detection is an optional feature, the failure in this step must
  # not prevent us from creating a commit.
  try:
    _detect_and_update_bug_id(lines)
  except Exception, e:
    sys.stderr.write('*** An exception is raised, bug IDs will not be '
                     'filled automatically ***\n')
    traceback.print_exc()

  with open(commit_file, 'w') as f:
    f.write(''.join(lines))
