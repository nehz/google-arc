#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A utility for working with the third_party/android directories."""

import argparse
import os
import subprocess
import sys
import logging
import xml.etree.cElementTree

from util import git
from util.rebase import state

_EPILOG = """
    To view help information specific to each command, use:

        %(prog)s <command> --help

sub-project mapping:
  ARC generally maps all paths under third_party/android otherwise using the
  same path as the Android sub-project. The exception is any sub-projects
  beginning with "platform" -- for these the "platform" component is removed, so
  for example "platform/frameworks/base" is mapped to
  "third_party/android/frameworks/base".

deps files:
  The deps file specifies how to synchronize with the Android code. If it is a
  single-line file, it is taken to be the name of an Android branch or tag, such
  as "android-4.4_r1".

  Otherwise it is assumed to be an Android XML manifest file identifying
  specific versions for all sub-projects.

  Manifest files are available from http://android-builds. Make sure you are
  on the right branch (see the drop-down at the top), and find a recent green
  build on the dashboard.

  If you have a specific manifest number to use, you can find its build with:

      android-build/builds.html?lower_limit=<number>&upper_limit=<number>

  For example, if you wanted manifest_12345.xml, you would use:

      android-build/builds.html?lower_limit=12345&upper_limit=12345

  You can download the manifest file by clicking the manifest_<number>.xml link
  listed in the build artifacts from any of the builders.

  Note that manifest files may contain private/internal information, and should
  not be submitted outside of arc/next-pastry.
"""[1:]

_EPILOG_ADD = """
For example:

    # Adds third_party/android/frameworks/base
    %(prog)s platform/frameworks/based

    # Adds third_party/android/device/generic/goldfish
    %(prog)s device/generic/goldfish
"""[1:]

_EPILOG_VERIFY = """
For example:

    # Verifies third_party/android/frameworks/base
    %(prog)s platform/frameworks/based

    # Verifies third_party/android/device/generic/goldfish
    %(prog)s device/generic/goldfish
"""[1:]

_EPILOG_UPDATE = """
For example:

    # Updates third_party/android/frameworks/base
    %(prog)s platform/frameworks/based

    # Updates third_party/android/device/generic/goldfish
    %(prog)s device/generic/goldfish

Iterative Updates

    This tool runs through a verification pass first, before trying to make any
    changes to the source code tree.  If there is a verification failure, or a
    subsequent update failure, you will need to manually fix up whatever was
    reported as a failure.

    You should be then able to run the same update command again, which will
    again do a verification pass, and otherwise continue the update process as
    needed.

    If all requested subprojects have been updated to the version specified in
    DEPS.android, the update process is a no-op.
"""[1:]

_EPILOG_REMOVE = """
For example:

    # Removes third_party/android/frameworks/base
    %(prog)s platform/frameworks/based

    # Removes third_party/android/device/generic/goldfish
    %(prog)s device/generic/goldfish
"""[1:]

_DEFAULT_DEPS_FILE = 'src/build/DEPS.android'
_DEFAULT_BRANCH_NAME = 'android-4.4_r1'
_ANDROID_BASE_URL = 'https://android.googlesource.com/'


class _AndroidManifestFile(object):
  """Allows an Android build manifest to be used to specify revisions."""
  def __init__(self, contents):
    self._document = xml.etree.cElementTree.fromstring(contents)
    default = self._document.find('default')
    self._default = default.get('revision') if default is not None else None

  def get_revision_for(self, name):
    """Gets the git revision hash for a particular project from the manifest."""
    project = self._document.find("project[@name='%s']" % name)
    return project.get('revision') if project is not None else self._default


class _SimpleBranchName(object):
  """Allows for a single branch name to be used to specify revisions."""
  def __init__(self, branch):
    self._branch = branch

  def get_revision_for(self, name):
    """Gets the common branch name to be used for every project."""
    return self._branch


def _get_remote_url_for_project(name):
  return os.path.join(_ANDROID_BASE_URL, name)


def _get_third_party_directory(subproject):
  if subproject.startswith('platform/'):
    subproject = subproject.split('/', 1)[1]
  return os.path.join('third_party', 'android', subproject)


def _do_add(args):
  """Adds a git submodule for an Android sub-project."""
  remote_path = _get_remote_url_for_project(args.subproject)
  third_party_dir = _get_third_party_directory(args.subproject)
  logging.info('Adding %s as %s', remote_path, third_party_dir)
  git.add_submodule(remote_path, third_party_dir)
  _do_update(args)


def _update_subproject(deps, state, subproject, module_path, verify_only=False):
  desired_revision = deps.get_revision_for(subproject)
  if desired_revision is None:
    logging.warning('Skipping unknown subproject %s', subproject)
    return

  logging.info('%s Fetching information about %s', subproject, desired_revision)

  # Convert the desired revision into a hash (if not already one).
  desired_revision = git.get_ref_hash(desired_revision, cwd=module_path)

  # Get the current version of the repo. We will need this to rebase the mods
  # after we roll forward.
  current_revision = git.get_head_revision(cwd=module_path)

  if desired_revision == current_revision:
    logging.info('%s is already at %s', subproject, desired_revision)

    # If we are doing an update, we can stop now, and assume that no work needs
    # to be done to the mods for that submodule.
    if not verify_only:
      return

  if not state.verify_submodule_path(current_revision, module_path):
    return

  # If we are only verifying, stop here before making any actual changes.
  if verify_only:
    return

  logging.info('%s checking out %s', subproject, desired_revision)
  git.force_checkout_revision(desired_revision, cwd=module_path)
  git.add_to_staging(module_path)

  logging.info('%s rebasing mods', subproject)
  state.rebase_submodule_path(current_revision, module_path)


def do_post_update_messages(rebase_state, verify_only=False):
  rebase_state.print_report()

  if verify_only:
    assert rebase_state.rebased_submodule_count == 0
    return

  if rebase_state.rebased_submodule_count == 0:
    sys.stdout.write('No changes made.\n')
  elif not rebase_state.rebase_succeeded():
    sys.exit('The update succeeded, but some manual work needs to be done to '
             'fix-up the mods.')
  else:
    sys.stdout.write(
        'The update completed successfully. %d mods rebased cleanly.\n' % (
            rebase_state.rebased_mod_count))


def _do_update(args, verify_only=False):
  """Updates the version used for a single Android subproject."""
  third_party_dir = _get_third_party_directory(args.subproject)
  rebase_state = state.State()
  _update_subproject(args.deps, rebase_state, args.subproject, third_party_dir,
                     verify_only=verify_only)
  do_post_update_messages(rebase_state, verify_only=verify_only)


def _do_update_all(args, verify_only=False):
  """Updates the version used for all Android sub-projects."""
  submodules = git.get_submodules('.', False)
  logging.info('Examining %d submodules....', len(submodules))
  rebase_state = state.State()
  for submodule in submodules:
    if submodule.url.startswith(_ANDROID_BASE_URL):
      third_party_dir = submodule.path
      subproject = submodule.url[len(_ANDROID_BASE_URL):].rstrip('/')
      if not os.path.exists(third_party_dir):
        # Some subprojects might be listed from older versions that are not used
        # anymore.
        logging.info('Ignoring %s as there is no local directory for it.',
                     submodule)
        continue
      _update_subproject(args.deps, rebase_state, subproject, third_party_dir,
                         verify_only=verify_only)
  do_post_update_messages(rebase_state, verify_only=verify_only)


def _do_verify(args):
  """Verifies the version used for a single Android subproject."""
  _do_update(args, verify_only=True)


def _do_verify_all(args):
  """Verifies the version used for all Android sub-projects."""
  _do_update_all(args, verify_only=True)


def _do_remove(args):
  """Removes a git submodule for an Android sub-project."""
  third_party_dir = _get_third_party_directory(args.subproject)
  logging.info('removing %s', third_party_dir)
  git.remove_submodule(third_party_dir)


def deps_contents_to_lookup_helper(contents):
  if '\n' in contents:
    return _AndroidManifestFile(contents)
  return _SimpleBranchName(contents)


def _read_deps(depsfile):
  with open(depsfile) as f:
    return deps_contents_to_lookup_helper(f.read().rstrip())


class _SetDepsAction(argparse.Action):
  def __call__(self, parser, namespace, value, option_string=None):
    setattr(namespace, self.dest, _read_deps(value))


def _android_subproject_name(name):
  try:
    remote_path = _get_remote_url_for_project(name)
    subprocess.check_output(['git', 'ls-remote', remote_path, 'HEAD'])
  except subprocess.CalledProcessError:
    raise argparse.ArgumentTypeError(
        '"%s" is not a valid Android subproject name.' % name)
  return name


def main():
  parser = argparse.ArgumentParser(
      description=__doc__, epilog=_EPILOG,
      formatter_class=argparse.RawTextHelpFormatter)

  parser.add_argument(
      '-v', '--verbose', action='count', default=0, help='Shows more messages.')
  parser.add_argument(
      '--deps', metavar='<DEPS>', dest='deps',
      default=_read_deps(_DEFAULT_DEPS_FILE), action=_SetDepsAction,
      help=('Specifies the version to use for each sub-project. The default '
            'is ' + _DEFAULT_DEPS_FILE))

  subparsers = parser.add_subparsers(title='commands')

  verify_command = subparsers.add_parser(
      'verify', help=_do_verify.__doc__, epilog=_EPILOG_VERIFY,
      formatter_class=argparse.RawTextHelpFormatter)
  verify_command.add_argument(
      'subproject', metavar='<subproject>', type=_android_subproject_name,
      help='The Android subproject to verify')
  verify_command.set_defaults(func=_do_verify)

  verify_all_command = subparsers.add_parser(
      'verify-all', help=_do_verify_all.__doc__,
      formatter_class=argparse.RawTextHelpFormatter)
  verify_all_command.set_defaults(func=_do_verify_all)

  add_command = subparsers.add_parser(
      'add', help=_do_add.__doc__, epilog=_EPILOG_ADD,
      formatter_class=argparse.RawTextHelpFormatter)
  add_command.add_argument(
      'subproject', metavar='<subproject>', type=_android_subproject_name,
      help='The Android subproject to add')
  add_command.set_defaults(func=_do_add)

  update_command = subparsers.add_parser(
      'update', help=_do_update.__doc__, epilog=_EPILOG_UPDATE,
      formatter_class=argparse.RawTextHelpFormatter)
  update_command.add_argument(
      'subproject', metavar='<subproject>', type=_android_subproject_name,
      help='The Android subproject to update.')
  update_command.set_defaults(func=_do_update)

  update_all_command = subparsers.add_parser(
      'update-all', help=_do_update_all.__doc__)
  update_all_command.set_defaults(func=_do_update_all)

  remove_command = subparsers.add_parser(
      'remove', help=_do_remove.__doc__, epilog=_EPILOG_REMOVE,
      formatter_class=argparse.RawTextHelpFormatter)
  remove_command.add_argument(
      'subproject', metavar='<subproject>', type=_android_subproject_name,
      help='The Android subproject to remove.')
  remove_command.set_defaults(func=_do_remove)

  args = parser.parse_args()
  logging.basicConfig(
      format='%(levelname)s: %(message)s',
      level=(logging.WARNING, logging.INFO, logging.DEBUG)[args.verbose])
  args.func(args)
  return 0

if __name__ == '__main__':
  sys.exit(main())
