# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# A helper script for programs loaded by the Bare Metal loader.
#

# GDB may use Python3 to run this script, so we should not use print
# statements. Enforce this rule by this magical module.
from __future__ import print_function

# See this document for detail of the gdb module.
# https://sourceware.org/gdb/onlinedocs/gdb/Python.html
import gdb
import os
import re
import subprocess
import traceback
import time


# The text section in the objdump result looks for something like:
#
# Idx Name         Size      VMA       LMA       File off  Algn
#  8 .text         0006319b  0000bc20  0000bc20  0000bc20  2**4
#                  CONTENTS, ALLOC, LOAD, READONLY, CODE
_TEXT_SECTION_PATTERN = re.compile(r'\.text\s+(?:\w+\s+){3}(\w+)')


_ARCH_ARM = 'arm'
_ARCH_I686 = 'i686'


# We set a breakpoint to this symbol.
_BARE_METAL_NOTIFY_GDB_OF_LOAD_FUNC = '__bare_metal_notify_gdb_of_load'


def _get_text_section_file_offset(path):
  """Returns the offset of the text section in the file."""
  objdump_result = subprocess.check_output(['objdump', '-h', path])
  match = _TEXT_SECTION_PATTERN.search(objdump_result.decode())
  if not match:
    print('Unexpected objdump output for %s' % path)
    return None
  return int(match.group(1), 16)


def _strip_gdb_result(result):
  # Strip the leading string like "$5 = " and uninterested lines.
  # TODO(hamaji): Once I get a sample which has uninterested lines,
  # write a unittest. See
  # https://chrome-internal-review.googlesource.com/#/c/185719/
  matched = re.search(r'^\$\d+ = (.*)', result, re.M)
  if not matched:
    print('GDB returned an unexpected expression: ' + result)
    return None
  return matched.group(1)


def _get_arg_expr(arch, argno):
  """Returns a GDB expression which specifies an argument.

  This function works even when we have no debug information.

  All the target function's arguments before the target argument,
  specified by |argno|, must be 32bit types. Other types, such as
  floating point, 64bit integer, and structs are not supported.
  """
  assert argno < 4
  if arch == _ARCH_ARM:
    # With ARM ABI, we use R0, R1, R2, and R3 to pass the first,
    # second, third, and forth arguments, respectively.
    return '((void*)$r%d)' % argno
  elif arch == _ARCH_I686:
    # With x86 ABI, we use the stack to pass arguments:
    # $esp+0: return address
    # $esp+4: first argument
    # $esp+8: second argument
    # ... and so on.
    return '(*(void**)($esp+%d))' % (argno * 4 + 4)
  else:
    raise ValueError('Unsupported architecture: ' + arch)


def _get_arg(arch, c_type, argno):
  result = gdb.execute('p (%s)%s' % (c_type, _get_arg_expr(arch, argno)),
                       to_string=True)
  return _strip_gdb_result(result)


class _LoadHandlerBreakpoint(gdb.Breakpoint):
  def __init__(self, arch, main_binary, library_path):
    super(_LoadHandlerBreakpoint, self).__init__(
        _BARE_METAL_NOTIFY_GDB_OF_LOAD_FUNC)
    self._arch = arch
    self._main_binary = main_binary
    self._library_path = library_path

  def _get_binary_path_from_link_map(self):
    name = _get_arg(self._arch, 'char*', 0)
    if not name:
      return None
    # This will be like: 0x357bc "libc.so"
    matched = re.match(r'.*"(.*)"', name)
    if not matched:
      print('Failed to retrieve the name of the shared object: "%s"' % name)
      return None

    path = matched.group(1)
    # Check if this is the main binary before the check for
    # "lib" to handle tests which start from lib such as libndk_test
    # properly.
    if path == os.path.basename(self._main_binary) or path == 'main.nexe':
      path = self._main_binary
    else:
      # Some files are in a subdirectory. So search files in the _library_path.
      for dirpath, _, filenames in os.walk(self._library_path):
        if path in filenames:
          path = os.path.join(dirpath, path)
          break

    if not os.path.exists(path):
      # TODO(crbug.com/354290): In theory, we should be able to
      # extract the APK and tell GDB the path to the NDK shared
      # object.
      print('%s does not exist! Maybe NDK in APK?' % path)
      return None

    return path

  def _get_text_section_address_from_link_map(self, path):
    base_addr_str = _get_arg(self._arch, 'unsigned int', 1)
    if not base_addr_str:
      return None
    try:
      base_addr = int(base_addr_str)
    except ValueError:
      print('Failed to retrieve the address of the shared object: ' +
            base_addr_str)
      return None
    file_off = _get_text_section_file_offset(path)
    if file_off is None:
      return None
    return file_off + base_addr

  def stop(self):
    """Called when _NOTIFY_GDB_OF_LOAD_FUNC_NAME function is executed."""
    try:
      path = self._get_binary_path_from_link_map()
      if not path:
        return False

      text_addr = self._get_text_section_address_from_link_map(path)
      if text_addr is None:
        print('Type \'c\' or \'continue\' to keep debugging')
        # Return True to stop the execution.
        return True

      gdb.execute('add-symbol-file %s 0x%x' % (path, text_addr))
      return False
    except:
      print(traceback.format_exc())
      return True


class _MmapFinishBreakpoint(gdb.FinishBreakpoint):
  def __init__(self, arch, main_binary, library_path,
               runnable_ld_path, mmap_addr):
    super(_MmapFinishBreakpoint, self).__init__()
    self._arch = arch
    self._main_binary = main_binary
    self._library_path = library_path
    self._runnable_ld_path = runnable_ld_path
    self._mmap_addr = mmap_addr

  def stop(self):
    # Note as this class is inherited from FinishBreakpoint, this
    # breakpoint will be removed this function returns once.
    file_off = _get_text_section_file_offset(self._runnable_ld_path)
    if file_off is None:
      return None
    gdb.execute('add-symbol-file %s 0x%x' % (self._runnable_ld_path,
                                             file_off + self._mmap_addr))
    _LoadHandlerBreakpoint(self._arch, self._main_binary, self._library_path)


class _MmapBreakpoint(gdb.Breakpoint):
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
      pc = int(_strip_gdb_result(
          gdb.execute('p (unsigned int)$pc', to_string=True)))
      load_bias = pc - entry_addr
      mmap = '*(void*)(0x%x+(int)mmap)' % load_bias
    elif arch == _ARCH_I686:
      mmap = '*(void*)mmap'
    else:
      raise Exception('Unsupported architecture')

    super(_MmapBreakpoint, self).__init__(mmap)
    self._arch = arch
    self._main_binary = main_binary
    self._library_path = library_path
    self._runnable_ld_path = runnable_ld_path

  def stop(self):
    prot = int(_get_arg(self._arch, 'int', 2))
    # Wait until the first PROT_READ|PROT_EXEC mmap.
    if prot != 5:
      return False

    # We do not use return_value of FinishBreakpoint because it
    # requires debug information. As of March 2015, nonsfi_loader has
    # debug information, but NaCl team may strip it in future.
    addr = int(_get_arg(self._arch, 'unsigned int', 0))
    assert addr
    # self.delete() should work according to the document, but it
    # finishes the debugger for some reason. Instead, just disable
    # this breakpoint.
    self.enabled = False
    _MmapFinishBreakpoint(self._arch, self._main_binary, self._library_path,
                          self._runnable_ld_path, addr)


def _get_program_loaded_address(path):
  path_suffix = '/' + os.path.basename(path)
  while True:
    mapping = gdb.execute('info proc mapping', to_string=True)
    for line in mapping.splitlines():
      # Here is the list of columns:
      # 1) Start address.
      # 2) End address.
      # 3) Size.
      # 4) Offset.
      # 5) Pathname.
      # For example:
      # 0xf5627000 0xf5650000 0x29000 0x0 /ssd/arc/out/.../runnable-ld.so
      column_list = line.split()
      if len(column_list) == 5 and column_list[4].endswith(path_suffix):
        return int(column_list[0], 16)
    print('Failed to find the loaded address of ' + path +
          ', retrying...')
    time.sleep(0.1)


def init(arc_nexe, library_path, runnable_ld_path, lock_file,
         remote_address=None, ssh_options=None):
  """Initializes GDB plugin for nacl_helper in Bare Metal mode.

  If remote_address is specified, we control the _LOCK_FILE using this
  address. This should be specified only for Chrome OS.
  """
  if arc_nexe.endswith('_arm.nexe'):
    arch = _ARCH_ARM
  elif arc_nexe.endswith('_i686.nexe'):
    arch = _ARCH_I686
  else:
    raise ValueError('Unsupported architecture: ' + arc_nexe)

  program_address = (_get_program_loaded_address(runnable_ld_path) +
                     _get_text_section_file_offset(runnable_ld_path))
  gdb.execute('add-symbol-file %s 0x%x' % (runnable_ld_path, program_address))
  _LoadHandlerBreakpoint(arch, arc_nexe, library_path)
  # Everything gets ready, so unlock the program.
  if remote_address:
    command = ['ssh', 'root@%s' % remote_address]
    if ssh_options:
      command.extend(ssh_options)
    command.extend(['rm', lock_file])
    subprocess.check_call(command)
  else:
    os.unlink(lock_file)


def init_for_unittest(nonsfi_loader, test_binary, library_path,
                      runnable_ld_path):
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

  _MmapBreakpoint(arch, nonsfi_loader, test_binary,
                  library_path, runnable_ld_path)

# TODO(crbug.com/310118): It seems only very recent GDB has
# remove-symbol-file. Create a hook for unload events once we switch
# to recent GDB.
