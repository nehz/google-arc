#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import ast
import distutils.spawn
import os
import pipes
import shutil
import subprocess
import sys

import build_common
import config_runner
import download_cts_files
import download_naclports_files
import download_sdk_and_ndk
import open_source
import staging
import sync_adb
import sync_gdb_multiarch
import sync_nacl_sdk
import toolchain
from build_options import OPTIONS


def _set_up_git_hooks():
  # These git hooks do not make sense for the open source repo because they:
  # 1) lint the source, but that was already done when committed internally,
  #    and we will run 'ninja all' as a test step before committing to open
  #    source.
  # 2) add fields to the commit message for the internal dev workflow.
  if open_source.is_open_source_repo():
    return
  script_dir = os.path.dirname(__file__)
  hooks = {
      'pre-push': os.path.join(script_dir, 'git_pre_push.py'),
      'prepare-commit-msg': os.path.join(script_dir, 'git_prepare_commit.py'),
      'commit-msg': staging.as_staging('gerrit/commit-msg')}
  obsolete_hooks = ['pre-commit']  # Replaced by pre-push hook.

  git_hooks_dir = os.path.join(build_common.get_arc_root(), '.git', 'hooks')
  for git_hook, source_path in hooks.iteritems():
    symlink_path = os.path.join(git_hooks_dir, git_hook)
    build_common.create_link(symlink_path, source_path, overwrite=True)

  for git_hook in obsolete_hooks:
    symlink_path = os.path.join(git_hooks_dir, git_hook)
    if os.path.lexists(symlink_path):
      os.unlink(symlink_path)


def _check_javac_version():
  # Stamp file should keep the last modified time of the java binary.
  javac_path = distutils.spawn.find_executable(
      toolchain.get_tool('java', 'javac'))
  stamp_file = build_common.StampFile(
      '%s %f' % (javac_path, os.path.getmtime(javac_path)),
      build_common.get_javac_revision_file())
  if stamp_file.is_up_to_date():
    return

  want_version = '1.6.'
  javac_version = subprocess.check_output(
      [javac_path, '-version'], stderr=subprocess.STDOUT)
  if want_version not in javac_version:
    print('\nWARNING: You are not using the supported Java SE 1.6.: ' +
          javac_version.strip())
    print 'See docs/getting-java.md.\n'
  else:
    stamp_file.update()


def _cleanup_orphaned_pyc_files():
  # Watch out for .pyc files without a corresponding .py file
  for base_path in ('src/', 'mods/'):
    for root, dirs, files in os.walk(base_path):
      for name in files:
        fullpath = os.path.join(root, name)
        base, ext = os.path.splitext(fullpath)
        if ext == '.pyc' and not os.path.exists(base + '.py'):
          print ('\nWARNING: %s appears to be a compiled python file without '
                 'any associated python code. It has been removed.') % fullpath
          os.unlink(fullpath)


def _gclient_sync_third_party():
  gclient_filename = 'third_party/.gclient'

  # For whatever reason gclient wants to take revisions from the command line
  # and does not read them from the .gclient file -- they used to be part of the
  # url. To work around this, we look for a new revision key for each dictionary
  # in the .gclient solution array, and use that to pass the revision
  # information on the command line.
  # TODO(lpique): Modify gclient to have it look for 'revision' in the .gclient
  # file itself, which will make this block of code unnecessary.
  with open(gclient_filename) as f:
    # Read the gclient file ourselves to extract some extra information from it
    gclient_content = f.read()
    # Make sure it appears to have an expected beginning, so we can quickly
    # parse it.
    assert gclient_content.startswith('solutions = [')
    # Use ast.literal_eval on the array, which works to evaluate simple python
    # constants. Using the built-in eval is potentially unsafe as it can execute
    # arbitrary code.
    # We start with the first array bracket, ignoring anything before it.
    gclient_contents = ast.literal_eval(
        gclient_content[gclient_content.find('['):])

  with open(gclient_filename, 'r') as f:
    stamp_file = build_common.StampFile(
        gclient_content, build_common.get_thirdparty_gclient_revision_file())
  if stamp_file.is_up_to_date():
    return

  cmd = ['gclient', 'sync', '--gclientfile', os.path.basename(gclient_filename)]

  # TODO(lpique): Modify gclient to have it look for 'revision' in the .gclient
  # file itself, which will make this block of code unnecessary.
  for entry in gclient_contents:
    if 'name' in entry and 'revision' in entry:
      cmd.extend(['--revision', pipes.quote('%(name)s@%(revision)s' % entry)])

  try:
    subprocess.check_output(cmd, cwd=os.path.dirname(gclient_filename))
    stamp_file.update()
  except subprocess.CalledProcessError as e:
    sys.stderr.write(e.output)
    sys.exit('Error running "%s"' % ' '.join(cmd))


def _ensure_downloads_up_to_date():
  # Always sync NaCl SDK.
  verbosity_option = ['-v'] if OPTIONS.verbose() else []
  if sync_nacl_sdk.main(verbosity_option):
    sys.exit(1)

  if download_sdk_and_ndk.check_and_perform_updates():
    sys.exit(1)

  if download_cts_files.check_and_perform_updates():
    sys.exit(1)

  if download_naclports_files.check_and_perform_updates():
    sys.exit(1)

  if sync_gdb_multiarch.main():
    sys.exit(1)

  # The open source repository does not have download_internal_apks.py.
  if (not open_source.is_open_source_repo() and
      OPTIONS.internal_apks_source() == 'prebuilt'):
    import download_internal_apks
    if download_internal_apks.check_and_perform_updates():
      sys.exit(1)


def _configure_build_options():
  if OPTIONS.parse(sys.argv[1:]):
    print 'Args error'
    return False

  # Write out the configure file early so all other scripts can use
  # the options passed into configure. (e.g., sync_chrome).
  OPTIONS.write_configure_file()

  # Target directory is replaced. If an old directory, out/target/<target>,
  # exists, move it to the new place, out/target/<target>_<opt>.
  old_path = os.path.join('out/target', OPTIONS.target())
  new_path = build_common.get_build_dir()
  if os.path.lexists(old_path):
    if os.path.isdir(old_path) and not os.path.islink(old_path):
      if os.path.exists(new_path):
        shutil.rmtree(old_path)
      else:
        shutil.move(old_path, new_path)
    else:
      os.remove(old_path)

  # Create an empty directory as a placeholder if necessary.
  build_common.makedirs_safely(new_path)

  # Create a symlink from new place to old place to keep as compatible as
  # possible.
  os.symlink(os.path.basename(new_path), old_path)

  # Write out the configure file to a target specific location, which can be
  # queried later to find out what the config for a target was.
  OPTIONS.write_configure_file(build_common.get_target_configure_options_file())

  OPTIONS.set_up_goma()
  return True


def _set_up_chromium_org_submodules():
  CHROMIUM_ORG_ROOT = 'third_party/android/external/chromium_org'
  # android/external/chromium_org contains these required submodules.  It is not
  # posible to have submodules within a submodule path (i.e., chromium_org)
  # using git submodules.  This is the list of subdirectories relative to
  # chromium_org that we need to symlink to the appropriate submodules.
  submodules = [
      'sdch/open-vcdiff',
      'testing/gtest',
      'third_party/WebKit',
      'third_party/angle_dx11',
      ('third_party/eyesfree/src/android/java/'
       'src/com/googlecode/eyesfree/braille'),
      'third_party/freetype',
      'third_party/icu',
      'third_party/leveldatabase/src',
      'third_party/libjingle/source/talk',
      'third_party/libphonenumber/src/phonenumbers',
      'third_party/libphonenumber/src/resources',
      'third_party/mesa/src',
      'third_party/openssl',
      'third_party/opus/src',
      'third_party/ots',
      'third_party/skia/gyp',
      'third_party/skia/include',
      'third_party/skia/src',
      'third_party/smhasher/src',
      'third_party/yasm/source/patched-yasm',
      'v8']

  # First remove all existing symlinks to make sure no stale links exist.
  for dirpath, dirs, fnames in os.walk(CHROMIUM_ORG_ROOT):
    # We only create symlinks for directories.
    for name in dirs:
      directory = os.path.join(dirpath, name)
      if os.path.islink(directory):
        os.unlink(directory)
  for s in submodules:
    symlink = os.path.join(CHROMIUM_ORG_ROOT, s)
    # As an example, this maps 'sdch/open-vcdiff' to
    # 'android/external/chromium_org__sdch_open-vcdiff', which is the true
    # location of the submodule checkout.
    source = 'third_party/android/external/chromium_org__' + s.replace('/', '_')
    if not os.path.exists(source):
      print 'ERROR: path "%s" does not exist.' % source
      print 'ERROR: Did you forget to run git submodules update --init?'
      sys.exit(1)
    # If a real directory exists, remove it explicitly. |overwrite| flag does
    # not care for real directories and files, but old symlinks.
    if not os.path.islink(symlink) and os.path.isdir(symlink):
      shutil.rmtree(symlink)
    build_common.create_link(symlink, source, overwrite=True)


def main():
  # Disable line buffering
  sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

  if not _configure_build_options():
    return -1

  _ensure_downloads_up_to_date()

  if not open_source.is_open_source_repo():
    import sync_chrome
    sync_chrome.run()

  adb_target = 'linux-arm' if OPTIONS.is_arm() else 'linux-x86_64'
  sync_adb.run(adb_target)

  if OPTIONS.internal_apks_source() == 'internal':
    # Check if internal/third_party/{gms-core, google-contacts-sync-adapter}/
    # checkout, which requires manual sync for now, is consistent with
    # internal/build/DEPS.*.xml.
    subprocess.check_call('src/build/check_arc_int.py')

  _gclient_sync_third_party()
  _check_javac_version()
  _cleanup_orphaned_pyc_files()

  _set_up_git_hooks()

  _set_up_chromium_org_submodules()

  # Make sure the staging directory is up to date whenever configure
  # runs to make it easy to generate rules by scanning directories.
  staging.create_staging()

  config_runner.generate_ninjas()

  return 0


if __name__ == '__main__':
  sys.exit(main())
