#!/usr/bin/env python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# The generated source code allows open source DSO files to have the
# 'DT_NEEDED libposix_translation.so' entry even though we have not
# open sourced the library yet.

import string
import sys

sys.path.insert(0, 'src/build')

import wrapped_functions
from build_options import OPTIONS


_CC_TEMPLATE = string.Template("""// Auto-generated file - DO NOT EDIT!
// DO NOT USE THIS FOR PRODUCTION EITHER.

#include "common/alog.h"

${FAKE_WRAP_FUNCTIONS}
""")


def main():
  OPTIONS.parse_configure_file()

  weak_symbols = []
  for function in wrapped_functions.get_wrapped_functions():
    weak_symbols.append(
        ('extern "C" void __wrap_%s() {'
         ' ALOG_ASSERT(false, "%s is called"); '
         '}') % (function, function))
  sys.stdout.write(_CC_TEMPLATE.substitute({
      'FAKE_WRAP_FUNCTIONS': '\n'.join(weak_symbols)
  }))


if __name__ == '__main__':
  sys.exit(main())
