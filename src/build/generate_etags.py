#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

import build_common

os.chdir(build_common.get_arc_root())
if not os.path.exists(build_common.OUT_DIR):
    os.mkdir(build_common.OUT_DIR)
tag_file = os.path.join(build_common.OUT_DIR, 'TAGS')
if os.path.exists(tag_file):
    os.unlink(tag_file)
os.system('find . \\( '
          '-name \\*.cc -or '
          '-name \\*.cpp -or '
          '-name \\*.c -or '
          '-name \\*.java -or '
          '-name \\*.h \\) '
          '-and \\! -wholename ./out/staging/\\* '  # ignore out/staging
          '-and \\! -xtype l '  # ignore broken symlinks
          '-print0 '  # support filenames with spaces, with xargs -0
          '| xargs -0 etags --append --output=' + tag_file)
