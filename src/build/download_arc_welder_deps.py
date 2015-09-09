# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build.util import download_package_util
from src.build.util import npm_package_sync


def check_and_perform_updates(cache_base_path, cache_history_size):
  download_package_util.BasicCachedPackage(
      'src/build/DEPS.naclports-python',
      'out/naclports-python',
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  ).check_and_perform_update()

  download_package_util.BasicCachedPackage(
      'src/build/DEPS.polymer-elements',
      'out/polymer-elements',
      cache_base_path=cache_base_path,
      cache_history_size=cache_history_size
  ).check_and_perform_update()

  npm_package_sync.NpmPackageSync(
      'src/build/DEPS.arc-welder-npm-packages',
      'out/arc-welder-npm-packages'
  ).check_and_perform_update()
