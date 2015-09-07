#!src/build/run_python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This script exists to filter out known dex2oat logs and warnings."""

import sys

from src.build.util import concurrent_subprocess


def main():
  handler = concurrent_subprocess.RedirectOutputHandler(
      # dex2oat prints a lot of Info-level messages normally.
      r'dex2oatd? I.*',
      # Some binder stubs don't start with 'I'.
      r'dex2oatd? W.*Found a stub class that does not start with \'I\':',
      # IapService$Stub is not abstract.
      (r'dex2oatd? W.* Binder stub is not abstract: ' +
       r'org.chromium.arc.iap.IapService\$Stub'),
      # Slow to compile/verify methods generate info messages.
      r'dex2oatd? W.*(Compilation|Verification) of.* took .*',
      r'org.ccil.cowan.tagsoup.HTMLSchema.<init>()')

  p = concurrent_subprocess.Popen(sys.argv[1:])
  return p.handle_output(handler)


if __name__ == '__main__':
  sys.exit(main())
