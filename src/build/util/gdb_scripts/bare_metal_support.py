# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# A GDB script that inserts memory map on module load.

# GDB may use Python3 to run this script, so we should not use print
# statements. Enforce this rule by this magical module.
from __future__ import print_function

import os
import re
import subprocess
import traceback
import time

# See this document for detail of the gdb module.
# https://sourceware.org/gdb/onlinedocs/gdb/Python.html
import gdb

import gdb_script_util


# We set a breakpoint to this symbol.
_BARE_METAL_NOTIFY_GDB_OF_LOAD_FUNC = '__bare_metal_notify_gdb_of_load'


class LoadHandlerBreakpoint(gdb.Breakpoint):
  def __init__(self, main_binary, library_path):
    super(LoadHandlerBreakpoint, self).__init__(
        _BARE_METAL_NOTIFY_GDB_OF_LOAD_FUNC)
    self._main_binary = main_binary
    self._library_path = library_path

  def _get_binary_path_from_link_map(self):
    name = gdb_script_util.get_arg('char*', 0)
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
    base_addr_str = gdb_script_util.get_arg('unsigned int', 1)
    if not base_addr_str:
      return None
    try:
      base_addr = int(base_addr_str)
    except ValueError:
      print('Failed to retrieve the address of the shared object: ' +
            base_addr_str)
      return None
    file_off = gdb_script_util.get_text_section_file_offset(path)
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
  program_address = (
      _get_program_loaded_address(runnable_ld_path) +
      gdb_script_util.get_text_section_file_offset(runnable_ld_path))
  gdb.execute('add-symbol-file %s 0x%x' % (runnable_ld_path, program_address))
  LoadHandlerBreakpoint(arc_nexe, library_path)

  # Everything gets ready, so unlock the program.
  if remote_address:
    command = ['ssh', 'root@%s' % remote_address]
    if ssh_options:
      command.extend(ssh_options)
    command.extend(['rm', lock_file])
    subprocess.check_call(command)
  else:
    os.unlink(lock_file)


# TODO(crbug.com/310118): It seems only very recent GDB has
# remove-symbol-file. Create a hook for unload events once we switch
# to recent GDB.
