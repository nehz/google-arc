#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import sys

from util import download_package_util


def check_and_perform_updates(include_media=False):
  # Downloads the pre-built CTS packages and .xml files.
  download_package_util.BasicCachedPackage(
      'src/build/DEPS.android-cts',
      'third_party/android-cts'
  ).check_and_perform_update()

  if include_media:
    # Approx 1Gb of data specific to the media tests.
    download_package_util.BasicCachedPackage(
        'src/build/DEPS.android-cts-media',
        'third_party/android-cts-media'
    ).check_and_perform_update()


def main():
  description = 'Downloads Android CTS related files.'
  parser = argparse.ArgumentParser(description=description)
  parser.add_argument('--include-media', action='store_true',
                      default=False, dest='include_media',
                      help='Include the CTS Media files (1Gb)')

  args = parser.parse_args()

  check_and_perform_updates(include_media=args.include_media)


if __name__ == '__main__':
  sys.exit(main())
