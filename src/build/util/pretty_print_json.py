#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Parse the JSON string given as the first argument and print its formatted
# version.

import json
import sys


def main():
  data = json.loads(sys.argv[1])
  json.dump(data, sys.stdout, sort_keys=True, indent=2)
  return 0

if __name__ == '__main__':
  sys.exit(main())
