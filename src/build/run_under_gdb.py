#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Runs unittests for NaCl or Bare Metal under GDB.
#
# TODO(crbug.com/439369): Remove this script.

import sys


def main():
  print ('This script is deprecated. '
         'Use src/build/run_unittest.py --gdb instead.')


if __name__ == '__main__':
  sys.exit(main())
