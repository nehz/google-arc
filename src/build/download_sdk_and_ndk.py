#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import logging
import os
import select
import subprocess
import sys

from src.build import toolchain
from src.build.util import download_package_util
from src.build.util import download_package_util_flags
from src.build.util import nonblocking_io


# TODO(lpique): This code really needs to use or otherwise be unified with
# filtered_subprocess.py
def _process_sdk_update_output_fragment(process, fragment):
  # Look for the last newline, and split there
  if '\n' in fragment:
    completed, remaining = fragment.rsplit('\n', 1)
    if completed:
      sys.stdout.write(completed + '\n')
  else:
    remaining = fragment
  if remaining.startswith('Do you accept the license '):
    sys.stdout.write(remaining)
    process.stdin.write('y\n')
    remaining = ''
  return remaining


# TODO(lpique): This code really needs to use or otherwise be unified with
# filtered_subprocess.py
def accept_android_license_subprocess(args):
  logging.info('accept_android_license_subprocess: %s', args)
  p = subprocess.Popen(
      args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
      stderr=subprocess.PIPE)
  stdout = nonblocking_io.LineReader(p.stdout)
  stderr = nonblocking_io.LineReader(p.stderr)
  current_line = ''
  while True:
    select_streams = []
    if not stdout.closed:
      select_streams.append(stdout)
    if not stderr.closed:
      select_streams.append(stderr)
    rset = []
    if select_streams:
      rset, _, _ = select.select(select_streams, [], [])

    for stream in rset:
      new_fragment = os.read(stream.fileno(), 4096)
      if not new_fragment:
        stream.close()
        continue
      current_line = _process_sdk_update_output_fragment(
          p, current_line + new_fragment)
    if p.poll() is not None:
      while not stdout.closed:
        stdout.read_full_line()
      while not stderr.closed:
        stderr.read_full_line()
      break
  if p.wait() != 0:
    raise subprocess.CalledProcessError(p.returncode, args)


class AndroidSDKFiles(download_package_util.BasicCachedPackage):
  """The Android SDK."""

  _SDK_TOOLS_ID = 'tools'
  _SDK_PLATFORM_TOOLS_ID = 'platform-tools'

  def __init__(self, *args, **kwargs):
    super(AndroidSDKFiles, self).__init__(*args, **kwargs)
    self.android_tool = os.path.join(
        self.unpacked_linked_cache_path, 'tools', 'android')

  def _update_component_by_id(self, update_component_ids):
    if not update_component_ids:
      return

    logging.info('Updating Android SDK components: %s',
                 ','.join(update_component_ids))
    accept_android_license_subprocess([
        self.android_tool, 'update', 'sdk', '--all', '--no-ui', '--filter',
        ','.join(update_component_ids)])

    # Ensure the final directory properly links to the cache.
    self.populate_final_directory()

  def post_update_work(self):
    """Perform some one time work after the SDK is first downloaded."""
    # Perform a self-update on the SDK tools, to ensure we have the latest
    # version. We do this update before downloading any other components so that
    # the tools are up to date for even doing that fetch.
    self._update_component_by_id([AndroidSDKFiles._SDK_TOOLS_ID])

  def _check_platform_tools_update(self, update_component_ids):
    """Checks and performs update for the platform-tools."""
    platform_tools_dir = os.path.join(
        self.unpacked_linked_cache_path, 'build-tools')
    if not os.path.exists(platform_tools_dir):
      update_component_ids.append(AndroidSDKFiles._SDK_PLATFORM_TOOLS_ID)

  def _check_sdk_platform_update(self, update_component_ids):
    """Checks and performs update for the sdk platform."""
    pinned_id = 'android-%d' % toolchain.get_android_api_level()
    pinned_dir = os.path.join(
        self.unpacked_linked_cache_path, 'platforms', pinned_id)
    if not os.path.exists(pinned_dir):
      update_component_ids.append(pinned_id)

  def _check_pinned_build_tools_update(self, update_component_ids):
    """Checks and performs update for the pinned build-tools."""
    pinned_version = toolchain.get_android_sdk_build_tools_pinned_version()
    pinned_id = 'build-tools-' + pinned_version
    pinned_dir = os.path.join(
        self.unpacked_linked_cache_path, 'build-tools', pinned_version)
    if not os.path.exists(pinned_dir):
      update_component_ids.append(pinned_id)

  def check_and_perform_component_updates(self):
    update_component_ids = []
    self._check_platform_tools_update(update_component_ids)
    self._check_sdk_platform_update(update_component_ids)
    self._check_pinned_build_tools_update(update_component_ids)
    self._update_component_by_id(update_component_ids)


def check_and_perform_updates(cache_base_path, cache_history_size):
  download_package_util.BasicCachedPackage(
      'src/build/DEPS.ndk',
      'third_party/ndk',
      unpack_method=download_package_util.unpack_self_extracting_archive(),
      link_subdir='android-ndk-r10d',
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  ).check_and_perform_update()

  sdk = AndroidSDKFiles(
      'src/build/DEPS.android-sdk',
      'third_party/android-sdk',
      unpack_method=download_package_util.unpack_tar_archive('pigz'),
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  )
  sdk.check_and_perform_update()
  sdk.check_and_perform_component_updates()


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--verbose', '-v', action='store_true')
  download_package_util_flags.add_extra_flags(parser)
  args = parser.parse_args(sys.argv[1:])
  if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
  check_and_perform_updates(args.download_cache_path, args.download_cache_size)


if __name__ == '__main__':
  sys.exit(main())
