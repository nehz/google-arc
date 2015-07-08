#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import ast
import distutils.spawn
import errno
import os
import pipes
import shutil
import subprocess
import sys

import build_common
import config_runner
import download_arc_welder_deps
import download_cts_files
import download_sdk_and_ndk
import open_source
import staging
import sync_adb
import sync_gdb_multiarch
import sync_nacl_sdk
import toolchain
from build_options import OPTIONS
from util import file_util


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
      'commit-msg': 'third_party/gerrit/commit-msg',
  }
  obsolete_hooks = ['pre-commit']  # Replaced by pre-push hook.

  git_hooks_dir = os.path.join(build_common.get_arc_root(), '.git', 'hooks')
  for git_hook, source_path in hooks.iteritems():
    symlink_path = os.path.join(git_hooks_dir, git_hook)
    file_util.create_link(symlink_path, source_path, overwrite=True)

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

  want_version = '1.7.'
  javac_version = subprocess.check_output(
      [javac_path, '-version'], stderr=subprocess.STDOUT)
  if want_version not in javac_version:
    print '\nWARNING: You are not using Java 7.',
    print 'Installed version:', javac_version.strip()
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


def _cleanup_stripped_dir():
  # Remove binaries in the stripped directory when they are unnecessary to
  # prevent stale binaries from being used for remote execution.
  if not OPTIONS.is_debug_info_enabled():
    file_util.rmtree(build_common.get_stripped_dir(), ignore_errors=True)
  elif OPTIONS.strip_runtime_binaries:
    file_util.rmtree(
        build_common.get_runtime_platform_specific_path(
            build_common.get_runtime_out_dir(), OPTIONS.target()),
        ignore_errors=True)


def _cleanup_unittest_info():
  if os.path.exists(build_common.get_unittest_info_path()):
    file_util.rmtree(build_common.get_unittest_info_path())


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
  cache_path = OPTIONS.download_cache_path()
  cache_size = OPTIONS.download_cache_size()

  sync_nacl_sdk.check_and_perform_updates(cache_path, cache_size)
  download_sdk_and_ndk.check_and_perform_updates(cache_path, cache_size)
  download_cts_files.check_and_perform_updates(cache_path, cache_size)
  download_arc_welder_deps.check_and_perform_updates(cache_path, cache_size)

  if sync_gdb_multiarch.main():
    sys.exit(1)

  # The open source repository does not have download_internal_apks.py.
  if (not open_source.is_open_source_repo() and
      OPTIONS.internal_apks_source() == 'prebuilt'):
    import download_internal_apks
    download_internal_apks.check_and_perform_updates(cache_path, cache_size)

  if not open_source.is_open_source_repo():
    import download_third_party_apks
    download_third_party_apks.check_and_perform_updates(cache_path, cache_size)


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
        file_util.rmtree(old_path)
      else:
        shutil.move(old_path, new_path)
    else:
      os.remove(old_path)

  # Create an empty directory as a placeholder if necessary.
  file_util.makedirs_safely(new_path)

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
      'third_party/angle',
      'third_party/brotli/src',
      ('third_party/eyesfree/src/android/java/'
       'src/com/googlecode/eyesfree/braille'),
      'third_party/freetype',
      'third_party/icu',
      'third_party/leveldatabase/src',
      'third_party/libjingle/source/talk',
      'third_party/libphonenumber/src/phonenumbers',
      'third_party/libphonenumber/src/resources',
      'third_party/libsrtp',
      'third_party/libvpx',
      'third_party/libyuv',
      'third_party/mesa/src',
      'third_party/openmax_dl',
      'third_party/openssl',
      'third_party/opus/src',
      'third_party/ots',
      'third_party/sfntly/cpp/src',
      'third_party/skia',
      'third_party/smhasher/src',
      'third_party/usrsctp/usrsctplib',
      'third_party/webrtc',
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
    target = os.path.join(CHROMIUM_ORG_ROOT, s)
    # As an example, this maps 'sdch/open-vcdiff' to
    # 'android/external/chromium_org__sdch_open-vcdiff', which is the true
    # location of the submodule checkout.
    source = 'third_party/android/external/chromium_org__' + s.replace('/', '_')
    if not os.path.exists(source):
      print 'ERROR: path "%s" does not exist.' % source
      print 'ERROR: Did you forget to run git submodules update --init?'
      sys.exit(1)

    # Remove existing symlink for transition from previous version.
    # The previous configuration script creates symlinks to the top of
    # chromium.org submodules, and now it tries to symlink them one-level
    # deeper.
    #
    # TODO(tzik): Remove this clean up code after the transition is no longer
    # needed.
    if os.path.islink(target):
      os.remove(target)

    target_contents = set()
    try:
      target_contents = set(os.listdir(target))
    except OSError as e:
      if e.errno != errno.ENOENT:
        raise

    source_contents = set(os.listdir(source))
    for content in source_contents:
      link_source = os.path.join(source, content)
      link_target = os.path.join(target, content)
      # If a real directory exists, remove it explicitly. |overwrite|
      # flag does not care for real directories and files, but old symlinks.
      if os.path.exists(link_target) and not os.path.islink(link_target):
        file_util.rmtree(link_target)

      file_util.create_link(link_target, link_source, overwrite=True)

    for removed_item in target_contents.difference(source_contents):
      os.unlink(os.path.join(target, removed_item))


def _update_arc_version_file():
  stamp = build_common.StampFile(build_common.get_build_version(),
                                 build_common.get_build_version_path())
  if not stamp.is_up_to_date():
    stamp.update()


def _set_up_internal_repo():
  if OPTIONS.internal_apks_source() == 'internal':
    # Sync internal/third_party/* to internal/build/DEPS.*.  The files needs to
    # be re-staged and is done in staging.create_staging.
    subprocess.check_call('src/build/sync_arc_int.py')

  # Create a symlink to the integration_test definition directory, either in the
  # internal repository checkout or in the downloaded archive.
  # It is used to determe the definitions loaded in run_integration_tests.py
  # without relying on OPTIONS. Otherwise, run_integration_tests_test may fail
  # due to the mismatch between the expectations and the actual test apk since
  # it always runs under the default OPTIONS.
  if OPTIONS.internal_apks_source_is_internal():
    test_dir = 'internal/integration_tests'
  else:
    test_dir = 'out/internal-apks/integration_tests'
  file_util.create_link('out/internal-apks-integration-tests', test_dir, True)


def main():
  # Disable line buffering
  sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

  if not _configure_build_options():
    return -1

  _update_arc_version_file()

  _ensure_downloads_up_to_date()

  if not open_source.is_open_source_repo():
    import sync_chrome
    sync_chrome.run()

  adb_target = 'linux-arm' if OPTIONS.is_arm() else 'linux-x86_64'
  sync_adb.run(adb_target)

  _set_up_internal_repo()

  _gclient_sync_third_party()
  _check_javac_version()
  _cleanup_orphaned_pyc_files()
  _cleanup_stripped_dir()
  _cleanup_unittest_info()

  _set_up_git_hooks()

  _set_up_chromium_org_submodules()

  # Make sure the staging directory is up to date whenever configure
  # runs to make it easy to generate rules by scanning directories.
  staging.create_staging()

  config_runner.generate_ninjas()

  return 0


if __name__ == '__main__':
  sys.exit(main())
