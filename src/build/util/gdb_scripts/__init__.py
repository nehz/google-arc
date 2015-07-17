# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

raise Exception(
    'It is completely wrong to import modules under src/build/util/gdb_scripts '
    'from build scripts. They are expected to be loaded by GDB.')
