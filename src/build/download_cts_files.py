# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from util import download_package_util


def check_and_perform_updates(cache_base_path, cache_history_size,
                              include_media=False):
  # Downloads the pre-built CTS packages and .xml files.
  download_package_util.BasicCachedPackage(
      'src/build/DEPS.android-cts',
      'third_party/android-cts',
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  ).check_and_perform_update()

  # Downloads the x86 CTS suite.
  download_package_util.BasicCachedPackage(
      'src/build/DEPS.android-cts-x86',
      'third_party/android-cts-x86',
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  ).check_and_perform_update()

  if include_media:
    # Approx 1Gb of data specific to the media tests.
    download_package_util.BasicCachedPackage(
        'src/build/DEPS.android-cts-media',
        'third_party/android-cts-media',
        cache_base_path=cache_base_path,
        cache_history_size=cache_history_size
    ).check_and_perform_update()
