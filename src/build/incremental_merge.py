#!src/build/run_python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A helper script to do incremental git merge.

See docs/working-on-lol5.md for usage.
"""

import argparse
import pipes
import re
import subprocess
import sys


# How incremental merge works
# ===========================
#
# Assume that HEAD is origin/lol5 and the branch to be merged is origin/master,
# which is the usual case for periodic merge during Android rebase work.
#
# On "start" subcommand, an empty commit (P) is created on HEAD. P is used to
# mark the commit where the incremental merge process started and to keep some
# metadata as its commit message.
#
#   ---A---B---C---D <origin/master
#       \
#   -----E---F---G---H---P <HEAD
#                    ^
#                    origin/lol5
#
# As the script continues, commits in origin/master is merged to HEAD commit by
# commit. Even if the user choose to drop a commit, a merge commit is created,
# but it is a no-op merge (git-merge --strategy=ours).
#
#   ---A-------------------B---C---D <origin/master
#       \                   \   \   \
#   -----E---F---G---H---P---Q---R---S <HEAD
#                    ^
#                    origin/lol5
#
# Once all commits are merged to HEAD, "squash" subcommand is used to squash all
# merge commits (P, Q, R, S) into a single commit (M).
#
#   ---A---B---C-------D <origin/master
#       \               \
#   -----E---F---G---H---M <HEAD
#                    ^
#                    origin/lol5


# git-log pretty format used internally to parse git commits.
_LOG_FORMAT = '%H%n%P%n%ae%n%B'

_CHERRY_PICK_COMMENT_RE = re.compile(r'cherry picked from commit ([0-9a-f]+)')


def clear_screen():
  """Clears the screen and move the cursor top-left."""
  sys.stdout.write('\x1b[2J\x1b[1;1H')


def prepend_indent(text, width):
  """Prepends indentation to multi-line text.

  Args:
    text: A multi-line text.
    width: Number of whitespaces prepended to each line.

  Returns:
    An indented multi-line text.
  """
  return '\n'.join((' ' * width + line) for line in text.splitlines())


def run_git_merge(commit, use_strategy_ours=False):
  """Run git-merge command to merge the given commit.

  Args:
    commit: The commit dictionary of a commit to be merged to HEAD.
    use_strategy_ours: If True, no-op merge is performed (--strategy=ours).

  Returns:
    The return code of git-merge command.
  """
  args = ['git', 'merge']
  if use_strategy_ours:
    args.append('--strategy=ours')
  commit_message = (
      '%(action)-6s %(short_hash)s %(subject)s\n\nINCREMENTAL_MERGE=COMMIT' %
      {
          'action': 'drop:' if use_strategy_ours else 'merge:',
          'short_hash': commit['hash'][:8],
          'subject': commit['subject'],
      })
  args.extend(['-m', commit_message, commit['hash']])
  print '+ %s' % ' '.join(pipes.quote(s) for s in args)
  return subprocess.call(args)


def ensure_clean_tree_or_die():
  """Ensures the git checkout is clean, otherwise abort."""
  if subprocess.call(['git', 'diff', '--quiet', '--ignore-submodules']):
    sys.exit('ERROR: The working tree is not clean.')


def parse_log_chunk(chunk):
  """Parses git log chunk to build a commit dictionary.

  Args:
    chunk: A string containing git log message formatted as _LOG_FORMAT.

  Returns:
    A commit dictionary.
  """
  hash, parents, author, body = chunk.split('\n', 3)
  parents = parents.split()
  subject = body.splitlines()[0]
  # Since the whole commit body is redundant to show in console, here we
  # build "short" body excluding metadata lines from the full body.
  # We assume the first line starting with r"[A-Z]+=" (e.g. "TEST=") is
  # the beginning of metadata lines and drop them, except for the last
  # "Reviewed-on:" line which is actually useful.
  main_match = re.search(r'(.*?)^[A-Z]+=', body, re.DOTALL | re.MULTILINE)
  if main_match:
    short_body = main_match.group(1).strip()
    review_lines = re.findall(r'^(Reviewed-on: .*)$', body, re.MULTILINE)
    if review_lines:
      short_body += '\n\n%s\n' % review_lines[-1]
  else:
    short_body = body
  commit = {
      'hash': hash,
      'parents': parents,
      'author': author,
      'subject': subject,
      'body': body,
      'short_body': short_body,
  }
  return commit


def get_commit(revision):
  """Parses git log of the specified commit.

  Args:
    revision: The revision to be parsed.

  Returns:
    A commit dictionary.
  """
  output = subprocess.check_output(
      ['git', 'log', '--pretty=format:%s' % _LOG_FORMAT, '-1', revision])
  return parse_log_chunk(output)


def get_commits_with_args(extra_args):
  """Runs `git log $args` and parses the output.

  Args:
    extra_args: A list of strings given to `git log` as extra arguments.

  Returns:
    A list of commit dictionaries.
  """
  args = ['git', 'log', '--pretty=format:%s%%x00' % _LOG_FORMAT,
          '--topo-order', '--reverse'] + extra_args
  output = subprocess.check_output(args)
  commits = [
      parse_log_chunk(chunk.strip())
      for chunk in output.split('\0')
      if chunk.strip()]
  return commits


def get_commit_range(include_revision, exclude_revision):
  """Parses git log of the specified commit range.

  This function parses git log for exclude_revision..include_revision, that is,
  any commit reachable from include_revision but not from exclude_revision.
  See gitrevisions(7) manpage for details.

  Args:
    include_revision: The revision to be included.
    exclude_revision: The revision to be excluded.

  Returns:
    A list of commit dictionaries.
  """
  return get_commits_with_args(
      ['%s..%s' % (exclude_revision, include_revision)])


def grep_commits(pattern):
  """Parses git log of commits matching to the given pattern.

  Args:
    pattern: A string given as --grep= parameter of git log.

  Returns:
    A list of commit dictionaries.
  """
  return get_commits_with_args(['--grep=%s' % pattern])


def get_merge_status():
  """Returns the incremental merge process status.

  Returns:
    A dictionary containing two entries:
    - 'start_hash': The hash of the commit created by initial "start" command.
    - 'merge_head': The revision (not necessarily the commit hash) of the branch
          to be merged as specified in initial "start" command.
    If an incremental merge process has not started yet, None is returned.
  """
  output = subprocess.check_output(
      ['git', 'log', '-1', '--pretty=format:%H%n%B',
       '--grep=INCREMENTAL_MERGE=START'])
  if not output:
    return None
  start_hash, start_body = output.split('\n', 1)
  m = re.search(r'MERGE_HEAD=(.+)', start_body)
  merge_head = m.group(1)
  return {'start_hash': start_hash, 'merge_head': merge_head}


def is_cherry_pick(their_commit, our_commit):
  """Determines if the two commits are equivalent.

  Args:
    their_commit: A commit dictionary.
    our_commit: A commit dictionary.

  Returns:
    True if a commit is a cherry-pick of the other commit. Otherwise False.
  """
  # First, scan for Gerrit automated cherry-pick message.
  their_cherry_picks = _CHERRY_PICK_COMMENT_RE.findall(their_commit['body'])
  our_cherry_picks = _CHERRY_PICK_COMMENT_RE.findall(our_commit['body'])
  if (their_commit['hash'] in our_cherry_picks or
      our_commit['hash'] in their_cherry_picks):
    return True

  # Secondly, match changes with the subject lines.
  # We are conservative here with whitelisted prefixes so as not to match
  # "Fix foobar" with "Reland: Fix foobar" etc.
  def simplify_subject(s):
    s = s.strip()
    for prefix in ('lol5:', 'l-rebase:'):
      if s.lower().startswith(prefix):
        s = s[len(prefix):].strip()
    return s

  if (simplify_subject(their_commit['subject']) ==
      simplify_subject(our_commit['subject'])):
    return True

  return False


def mark_cherry_picks(their_commits, our_commits):
  """Marks cherry-pick commits.

  If a commit in their_commits has a corresponding cherry-pick commit in
  our_commits, its commit['cherry_pick_hash'] is set to the hash of the
  other commit.

  Args:
    their_commits: A list of commit dictionaries reachable only from the
        branch to be merged. These dictionaries will be mutated.
    our_commits: A list of commit dictionaries reachable only from HEAD.
        These dictionaries will be untouched.
  """
  # This is O(N^2) computation, but it is okay for now since N is small.
  for their_commit in their_commits:
    for our_commit in our_commits:
      if is_cherry_pick(their_commit, our_commit):
        their_commit['cherry_pick_hash'] = our_commit['hash']
        break
    else:
      their_commit['cherry_pick_hash'] = None


def check_target_branch_linearity_or_die(commits):
  """Ensures the given commits do not include merge commits.

  If any merge commit is found, the script aborts with an error message.

  Args:
    commits: A list of commit dictionaries to be inspected.
  """
  for c in commits:
    if len(c['parents']) != 1:
      sys.exit(
          'ERROR: A commit to be merged has more than one parent: %s'
          % c['subject'])


def handle_start(parsed_args):
  """The entry point for "start" subcommand."""
  ensure_clean_tree_or_die()

  if get_merge_status():
    sys.exit(
        'ERROR: The incremental merge process has already started.\n'
        'ERROR: Try continuing the process instead:\n'
        'ERROR: $ %s continue' % sys.argv[0])

  # Create an initial empty commit. This commit is used to record the
  # state of incremental merge process and also mark the beginning of
  # merge commits.
  commit_message = """WIP: Start incremental merge of %(branch)s.

INCREMENTAL_MERGE=START
MERGE_HEAD=%(branch)s
""" % {'branch': parsed_args.branch}
  subprocess.check_call(
      ['git', 'commit', '--allow-empty', '-m', commit_message])

  return handle_continue(parsed_args)


def handle_continue(parsed_args):
  """The entry point for "continue" subcommand."""
  ensure_clean_tree_or_die()

  status = get_merge_status()
  if not status:
    sys.exit(
        'ERROR: The incremental merge process has not started yet.\n'
        'ERROR: Try starting the process by:\n'
        'ERROR: $ %s start BRANCH-NAME' % sys.argv[0])

  our_commits = get_commit_range(
      include_revision='HEAD',
      exclude_revision=status['merge_head'])
  their_commits = get_commit_range(
      include_revision=status['merge_head'],
      exclude_revision='HEAD')

  check_target_branch_linearity_or_die(their_commits)

  mark_cherry_picks(their_commits, our_commits)

  while their_commits:
    num_remaining_commits = len(their_commits)
    commit = their_commits.pop(0)
    clear_screen()
    print '%d commit(s) to go. Next:' % num_remaining_commits
    print
    print '    === %s' % commit['hash']
    print prepend_indent(commit['short_body'].strip(), 4)
    print

    if commit['cherry_pick_hash']:
      twin = get_commit(commit['cherry_pick_hash'])
      print 'This commit has an apparent cherry-pick commit:'
      print
      print '    === %s' % commit['cherry_pick_hash']
      print prepend_indent(twin['short_body'].strip(), 4)
      print
      print 'It is recommended to drop this commit.'
      print
      recommend = 'D'
    else:
      print 'This commit has no known cherry-pick commit.'
      print 'It is recommended to merge this commit.'
      print
      recommend = 'M'

    while True:
      cmd = raw_input(
          'Action ([M]erge/[D]rop/[Q]uit; default=%s)? ' % recommend)
      cmd = cmd.strip().upper() or recommend
      if cmd == 'M':
        if run_git_merge(commit) != 0:
          print
          print 'If this conflict looks legitimate, please resolve it and'
          print 'commit by git-commit.'
          print
          print 'Otherwise, you can revert the merge by:'
          print '$ git reset --hard'
          print
          print 'After you resolved the state, continue the process by:'
          print '$ %s continue' % sys.argv[0]
          return 1
        break
      elif cmd == 'D':
        run_git_merge(commit, use_strategy_ours=True)
        break
      elif cmd == 'Q':
        print 'You can continue the merge process by:'
        print '$ %s continue' % sys.argv[0]
        print 'Or if you want to abort the process:'
        print '$ %s abort' % sys.argv[0]
        return 0

  print 'All commits merged!'
  print
  print 'Please run the following command to squash the merge commits:'
  print '$ %s squash' % sys.argv[0]


def handle_squash(parsed_args):
  """The entry point for "squash" subcommand."""
  ensure_clean_tree_or_die()

  status = get_merge_status()
  if not status:
    sys.exit(
        'ERROR: The incremental merge process has not started yet.\n'
        'ERROR: Try starting the process by:\n'
        'ERROR: $ %s start BRANCH-NAME' % sys.argv[0])

  remaining_commits = get_commit_range(
      include_revision=status['merge_head'],
      exclude_revision='HEAD')
  if remaining_commits:
    sys.exit(
        'ERROR: There are still pending commits to merge.\n'
        'ERROR: Try continuing the merge process by:\n'
        'ERROR: $ %s continue' % sys.argv[0])

  merge_commits = grep_commits('INCREMENTAL_MERGE=COMMIT')
  merge_log = 'Merge %s.\n\n%s' % (
      status['merge_head'],
      '\n'.join(c['subject'] for c in merge_commits))

  subprocess.check_call(
      ['git', 'reset', '--soft', '%s~' % status['start_hash']])
  with open('.git/MERGE_HEAD', 'w') as f:
    f.write(status['merge_head'])
  subprocess.check_call(['git', 'commit', '-m', merge_log])

  print
  print 'Squashed the merge commits to a single merge commit.'
  print
  print 'Please complete the commit message by:'
  print '$ git commit --amend'
  print
  print 'Afterwards, please test the commit and send it for review.'
  print 'Have a good day!'


def handle_abort(parsed_args):
  """The entry point for "abort" subcommand."""
  ensure_clean_tree_or_die()

  status = get_merge_status()
  if not status:
    sys.exit('The incremental merge process inactive.')

  subprocess.check_call(
      ['git', 'reset', '--hard', '%s~' % status['start_hash']])

  print
  print 'Aborted the incremental merge process.'


def create_parser():
  """Contructs the argument parser.

  Returns:
    An argparse.ArgumentParser object.
  """
  root_parser = argparse.ArgumentParser(
      description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
  subparsers = root_parser.add_subparsers()

  start_parser = subparsers.add_parser(
      'start',
      help='Start an incremental merge process.')
  start_parser.add_argument(
      'branch',
      help='The name of branch to merge. (e.g. origin/master)')
  start_parser.set_defaults(entrypoint=handle_start)

  continue_parser = subparsers.add_parser(
      'continue',
      help=('Continue an incremental merge process interrupted by events like '
            'merge conflicts.'))
  continue_parser.set_defaults(entrypoint=handle_continue)

  squash_parser = subparsers.add_parser(
      'squash',
      help=('Squash multiple merge commits into a single merge commit after '
            'all commits have been merged.'))
  squash_parser.set_defaults(entrypoint=handle_squash)

  abort_parser = subparsers.add_parser(
      'abort',
      help='Abort an incremental merge process.')
  abort_parser.set_defaults(entrypoint=handle_abort)

  return root_parser


def main(argv):
  parser = create_parser()
  parsed_args = parser.parse_args(argv[1:])
  return parsed_args.entrypoint(parsed_args)


if __name__ == '__main__':
  sys.exit(main(sys.argv))
