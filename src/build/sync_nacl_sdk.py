#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Syncs the nacl sdk at a pinned version given in NACLSDK.json."""

import argparse
import logging
import os
import sys
import urllib

import build_common
from util import logging_util
from util import download_package_util
from util import download_package_util_flags


_DEPS_FILE_PATH = 'src/build/DEPS.naclsdk'
_NACL_MIRROR = 'https://commondatastorage.googleapis.com/nativeclient-mirror'
_LATEST_MANIFEST_URL = _NACL_MIRROR + '/nacl/nacl_sdk/naclsdk_manifest2.json'
_NACL_SDK_ZIP_URL = _NACL_MIRROR + '/nacl/nacl_sdk/nacl_sdk.zip'


@build_common.with_retry_on_exception
def roll_pinned_manifest_forward():
  """Roll forward the pinned manifest to the latest version."""
  logging.info('Rolling forward the pinned NaCl manifest.')
  urllib.urlretrieve(_LATEST_MANIFEST_URL, _DEPS_FILE_PATH)
  logging.info('Done.')


class NaClSDKFiles(download_package_util.BasicCachedPackage):
  """Handles syncing the NaCl SDK."""
  @build_common.with_retry_on_exception
  def post_update_work(self):
    # Update based on pinned manifest. This part can be as slow as 1-2 minutes
    # regardless of whether it is a fresh install or an update.
    logging.info('%s: Updating naclsdk using manifest.', self.name)
    download_package_util.execute_subprocess([
        './naclsdk', 'update', '-U',
        'file://' + os.path.join(build_common.get_arc_root(),
                                 _DEPS_FILE_PATH),
        '--force', 'pepper_canary'], cwd=self.unpacked_linked_cache_path)


def check_and_perform_updates(cache_base_path, cache_history_size):
  NaClSDKFiles(
      _DEPS_FILE_PATH,
      'third_party/nacl_sdk',
      url=_NACL_SDK_ZIP_URL,
      link_subdir='nacl_sdk',
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  ).check_and_perform_update()


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-v', '--verbose', action='store_true', help='Emit '
                      'verbose output.')
  parser.add_argument('-r', '--roll-forward', dest='roll', action='store_true',
                      help='Update pinned NaCl SDK manifest version to the '
                      'latest..')
  download_package_util_flags.add_extra_flags(parser)
  args = parser.parse_args(args)
  logging_util.setup(level=logging.DEBUG if args.verbose else logging.WARNING)
  if args.roll:
    roll_pinned_manifest_forward()

  check_and_perform_updates(args.download_cache_path, args.download_cache_size)


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
