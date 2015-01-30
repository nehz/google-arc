#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Runs unittests for NaCl or Bare Metal under GDB.
#
# TODO(crbug.com/439369): Move run_unittest.py to this directory,
# update the document, and deprecate this script.

import signal
import sys

import toolchain
from build_options import OPTIONS
from util.test import unittest_util


def main():
  OPTIONS.parse_configure_file()
  test_args = sys.argv[1:]
  if not test_args:
    print 'Usage: %s test_binary [test_args...]' % sys.argv[0]
    sys.exit(1)

  # This script must not die by Ctrl-C while GDB is running. We simply
  # ignore SIGINT. Note that GDB will still handle Ctrl-C properly
  # because GDB sets its signal handler by itself.
  signal.signal(signal.SIGINT, signal.SIG_IGN)

  runner_args = toolchain.get_tool(OPTIONS.target(), 'runner').split()
  unittest_util.run_gdb(runner_args + test_args)


if __name__ == '__main__':
  sys.exit(main())
