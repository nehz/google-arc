#!src/build/run_python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Check if important symbols for NDKs are available."""

import logging
import subprocess
import sys

from src.build import toolchain
from src.build.build_options import OPTIONS


def get_defined_symbols(filename):
  output = subprocess.check_output([toolchain.get_tool(OPTIONS.target(), 'nm'),
                                    '--defined-only', '-D', filename])
  syms = set()
  for line in output.splitlines():
    toks = line.split()
    # Empty lines or a filename line.
    if len(toks) <= 1:
      continue
    addr, sym_type, name = line.split()
    syms.add(name)
  return syms


def main():
  OPTIONS.parse_configure_file()
  logging.getLogger().setLevel(logging.INFO)

  if len(sys.argv) != 3:
    logging.fatal('Usage: %s android-lib.so arc-lib.so' % sys.argv[0])
    return 1

  android_lib = sys.argv[1]
  arc_lib = sys.argv[2]

  android_syms = get_defined_symbols(android_lib)
  arc_syms = get_defined_symbols(arc_lib)

  missing_syms = set(android_syms - arc_syms)

  # Ignore symbols starting with two underscores since they are internal ones.
  # However, we do not ignore symbols starting with one underscore so that the
  # script can check symbols such as _Zxxx (mangled C++ symbols), _setjmp, and
  # _longjmp.
  important_missing_syms = [
      sym for sym in missing_syms if not sym.startswith('__')]

  if important_missing_syms:
    for sym in sorted(important_missing_syms):
      logging.error('Missing symbol: %s' % sym)
    return 1
  return 0


if __name__ == '__main__':
  sys.exit(main())
