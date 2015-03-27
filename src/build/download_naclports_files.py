#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys

from util import download_package_util


def check_and_perform_updates():
  download_package_util.BasicCachedPackage(
      'src/build/DEPS.naclports-python',
      'out/naclports-python'
  ).check_and_perform_update()


def main():
  check_and_perform_updates()


if __name__ == '__main__':
  sys.exit(main())
