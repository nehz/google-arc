#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import hashlib
import logging
import multiprocessing
import os
import subprocess
import sys

import build_common
import re
import toolchain
from build_options import OPTIONS
from util import concurrent
from util import concurrent_subprocess
from util import file_util
from util import logging_util


_MINIDUMP_DUMP_TOOL = toolchain.get_nacl_tool('minidump_dump')
_MINIDUMP_STACKWALK_TOOL = toolchain.get_nacl_tool('minidump_stackwalk')
_SYMBOL_OUT_DIR = 'out/symbols'


def _get_symbol_marker(path):
  sha1 = hashlib.sha1()
  with open(path) as f:
    sha1.update(f.read())
  return os.path.join(_SYMBOL_OUT_DIR, 'hash', sha1.hexdigest())


class _DumpSymsFilter(concurrent_subprocess.OutputHandler):
  _WARNING_RE = re.compile('|'.join([
      # TODO(crbug.com/468597): Figure out if these are benign.
      # From src/common/dwarf_cu_to_module.cc
      r".*: in compilation unit '.*' \(offset 0x.*\):",
      r".*: warning: function at offset .* has no name",
      (r".*: the DIE at offset 0x.* has a DW_AT_abstract_origin"
       r" attribute referring to the die at offset 0x.*, which either"
       r" was not marked as an inline, or comes later in the file"),
      (r".*: the DIE at offset 0x.* has a DW_AT_specification"
       r" attribute referring to the die at offset 0x.*, which either"
       r" was not marked as a declaration, or comes later in the file"),
      # From src/common/dwarf_cfi_to_module.cc
      (r".*, section '.*': "
       r"the call frame entry at offset .* refers to register .*,"
       r" whose name we don't know"),
      (r".*, section '.*': "
       r"the call frame entry at offset 0x%zx sets the rule for "
       r"register '.*' to 'undefined', but the Breakpad symbol file format"
       r" cannot express this\n"),
      # TODO(crbug.com/393140): It might be that this needs to be implemented
      # for stack trace to work.
      (r".*, section '.*': "
       r"the call frame entry at offset .* uses a DWARF expression to "
       r"describe how to recover register '.*',  but this translator cannot "
       r"yet translate DWARF expressions to Breakpad postfix expressions"),
      # TODO(http://crbug.com/468587): Host cxa_demangle doesn't like some
      # C++ names.
      r".*: warning: failed to demangle .* with error -2"]))

  def __init__(self):
    """Generate a filter that will filter warnings and also allow stdout
    result to be obtained as |stdout_result|.
    """
    super(_DumpSymsFilter, self).__init__()
    self.stdout_result = []

  def _has_warning(self, line):
    return self._WARNING_RE.match(line) is not None

  def handle_stdout(self, line):
    self.stdout_result.append(line)

  def handle_stderr(self, line):
    if not self._has_warning(line):
      sys.stderr.write(line)


def _extract_symbols_from_one_binary(binary):
  # If the marker is already written, we should already have the
  # extracted symbols.
  marker_path = _get_symbol_marker(binary)
  if os.path.exists(marker_path):
    logging.info('Skip extracting symbols from: %s' % binary)
    return

  logging.info('Extracting symbols from: %s' % binary)
  dump_syms_tool = build_common.get_build_path_for_executable(
      'dump_syms', is_host=True)
  p = concurrent_subprocess.Popen([dump_syms_tool, binary])
  my_filter = _DumpSymsFilter()
  p.handle_output(my_filter)
  syms = ''.join(my_filter.stdout_result)
  # The first line should look like:
  # MODULE Linux arm 0222CE01F27D6870B1FA991F84B9E0460 libc.so
  symhash = syms.splitlines()[0].split()[3]
  base = os.path.basename(binary)
  sympath = os.path.join(_SYMBOL_OUT_DIR, base, symhash, base + '.sym')
  file_util.makedirs_safely(os.path.dirname(sympath))

  with open(sympath, 'w') as f:
    f.write(syms)

  # Create the marker directory so we will not need to extract symbols
  # in the next time.
  file_util.makedirs_safely(marker_path)


def _extract_symbols():
  # Extract symbols in parallel.
  with concurrent.CheckedExecutor(concurrent.ThreadPoolExecutor(
      max_workers=multiprocessing.cpu_count(), daemon=True)) as executor:
    for root, _, filenames in os.walk(build_common.get_load_library_path()):
      for filename in filenames:
        if os.path.splitext(filename)[1] in ['.so', '.nexe']:
          executor.submit(_extract_symbols_from_one_binary,
                          os.path.join(root, filename))


def _stackwalk(minidump):
  _extract_symbols()
  subprocess.check_call([_MINIDUMP_STACKWALK_TOOL, minidump, _SYMBOL_OUT_DIR])


def _dump(minidump):
  subprocess.check_call([_MINIDUMP_DUMP_TOOL, minidump])


def _parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument('mode', choices=('stackwalk', 'dump'))
  parser.add_argument('minidump', type=str, metavar='<file>',
                      help='The minidump file to be analyzed.')
  parser.add_argument('--verbose', '-v', action='store_true')
  return parser.parse_args()


def main():
  args = _parse_args()
  logging_util.setup()
  OPTIONS.parse_configure_file()
  if args.mode == 'stackwalk':
    _stackwalk(args.minidump)
  elif args.mode == 'dump':
    _dump(args.minidump)


if __name__ == '__main__':
  sys.exit(main())
