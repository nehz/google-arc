# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# A GDB script that inserts memory map on module load.

# GDB may use Python3 to run this script, so we should not use print
# statements. Enforce this rule by this magical module.
from __future__ import print_function

import re
import subprocess

# See this document for detail of the gdb module.
# https://sourceware.org/gdb/onlinedocs/gdb/Python.html
import gdb

import bare_metal_support
import gdb_script_util


_ARCH_ARM = 'arm'
_ARCH_I686 = 'i686'


class MmapFinishBreakpoint(gdb.FinishBreakpoint):
  def __init__(self, arch, main_binary, library_path,
               runnable_ld_path, mmap_addr):
    super(MmapFinishBreakpoint, self).__init__()
    self._arch = arch
    self._main_binary = main_binary
    self._library_path = library_path
    self._runnable_ld_path = runnable_ld_path
    self._mmap_addr = mmap_addr

  def stop(self):
    # Note as this class is inherited from FinishBreakpoint, this
    # breakpoint will be removed this function returns once.
    file_off = gdb_script_util.get_text_section_file_offset(
        self._runnable_ld_path)
    if file_off is None:
      return None
    gdb.execute('add-symbol-file %s 0x%x' % (self._runnable_ld_path,
                                             file_off + self._mmap_addr))
    bare_metal_support.LoadHandlerBreakpoint(
        self._arch, self._main_binary, self._library_path)


class MmapBreakpoint(gdb.Breakpoint):
  def __init__(self, arch, nonsfi_loader,
               main_binary, library_path, runnable_ld_path):
    if arch == _ARCH_ARM:
      # Unfortunately, GDB does not handle remotely running PIE. We
      # need to adjust the loaded address by ourselves.
      #
      # The execution is suspended at the entry point. We can
      # calculate the load bias for nonsfi_loader by subtracting the
      # statically decided entry point from the programming counter.
      readelf_result = subprocess.check_output(['readelf', '-h', nonsfi_loader])
      # Need str() as readelf_result is bytes on Python 3.
      matched = re.search(
          r'Entry point address:\s+0x([0-9a-f]+)', str(readelf_result))
      assert matched, ('"readelf -h %s" did not return entry point' %
                       nonsfi_loader)
      entry_addr = int(matched.group(1), 16)
      pc = int(gdb_script_util.strip_gdb_result(
          gdb.execute('p (unsigned int)$pc', to_string=True)))
      load_bias = pc - entry_addr
      mmap = '*(void*)(0x%x+(int)mmap)' % load_bias
    elif arch == _ARCH_I686:
      mmap = '*(void*)mmap'
    else:
      raise Exception('Unsupported architecture')

    super(MmapBreakpoint, self).__init__(mmap)
    self._arch = arch
    self._main_binary = main_binary
    self._library_path = library_path
    self._runnable_ld_path = runnable_ld_path

  def stop(self):
    prot = int(gdb_script_util.get_arg(self._arch, 'int', 2))
    # Wait until the first PROT_READ|PROT_EXEC mmap.
    if prot != 5:
      return False

    # We do not use return_value of FinishBreakpoint because it
    # requires debug information. As of March 2015, nonsfi_loader has
    # debug information, but NaCl team may strip it in future.
    addr = int(gdb_script_util.get_arg(self._arch, 'unsigned int', 0))
    assert addr
    # self.delete() should work according to the document, but it
    # finishes the debugger for some reason. Instead, just disable
    # this breakpoint.
    self.enabled = False
    MmapFinishBreakpoint(
        self._arch, self._main_binary, self._library_path,
        self._runnable_ld_path, addr)


def init(nonsfi_loader, test_binary, library_path, runnable_ld_path):
  """Initializes GDB plugin for unittests in Bare Metal mode.

  To set an appropriate breakpoint in runnable-ld.so, we should know
  the address runnable-ld.so is placed. To find it, we wait until mmap
  is called with PROT_EXEC then execute add-symbol-file for
  runnable-ld.so with the address for mmap.
  """
  if nonsfi_loader.endswith('_arm'):
    arch = _ARCH_ARM
  elif nonsfi_loader.endswith('_x86_32'):
    arch = _ARCH_I686
  else:
    raise ValueError('Unsupported architecture: ' + nonsfi_loader)

  MmapBreakpoint(
      arch, nonsfi_loader, test_binary, library_path, runnable_ld_path)
