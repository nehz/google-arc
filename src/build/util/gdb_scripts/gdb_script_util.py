# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Utility functions used by GDB scripts.

# GDB may use Python3 to run this script, so we should not use print
# statements. Enforce this rule by this magical module.
from __future__ import print_function

import re
import subprocess

# See this document for detail of the gdb module.
# https://sourceware.org/gdb/onlinedocs/gdb/Python.html
import gdb


_TEXT_SECTION_PATTERN = re.compile(r'\.text\s+(?:\w+\s+){3}(\w+)')


# Set in init().
_target = None


def get_target():
  """Returns the target name, e.g. 'bare_metal_i686'."""
  return _target


def is_arm():
  return _target == 'bare_metal_arm'


def is_i686():
  return _target in ('bare_metal_i686', 'nacl_i686')


def is_x86_64():
  return _target == 'nacl_x86_64'


def _strip_gdb_result(result):
  # Strip the leading string like "$5 = ".
  matched = re.match(r'\$\d+ = (.*)', result)
  if not matched:
    print('GDB returned an unexpected expression: ' + result)
    return None
  return matched.group(1)


def _get_arg_expr(argno):
  """Returns a GDB expression which specifies an argument.

  This function works even when we have no debug information.

  All the target function's arguments before the target argument,
  specified by |argno|, must be 32bit types. Other types, such as
  floating point, 64bit integer, and structs are not supported.
  """
  assert argno < 4
  if is_arm():
    # With ARM ABI, we use R0, R1, R2, and R3 to pass the first,
    # second, third, and forth arguments, respectively.
    return '((void*)$r%d)' % argno
  elif is_i686():
    # With x86 ABI, we use the stack to pass arguments:
    # $esp+0: return address
    # $esp+4: first argument
    # $esp+8: second argument
    # ... and so on.
    return '(*(void**)($esp+%d))' % (argno * 4 + 4)
  else:
    raise ValueError('Unsupported target: %s' % get_target())


def get_var(c_type, name):
  """Extracts a variable value.

  Args:
    c_type: C type name to interpret the argument as (e.g. 'long').
    name: The name of the variable.

  Returns:
    The variable value as a GDB-formatted string.
  """
  result = gdb.execute('p (%s)%s' % (c_type, name), to_string=True)
  return _strip_gdb_result(result)


def get_arg(c_type, argno):
  """Extracts an argument value of the function triggering a breakpoint.

  This function works even when we have no debug information.

  Args:
    c_type: C type name to interpret the argument as (e.g. 'long').
    argno: 0-origin index of the argument.

  Returns:
    The argument value as a GDB-formatted string.
  """
  return get_var(c_type, _get_arg_expr(argno))


def get_text_section_file_offset(path):
  """Returns the offset of the text section in the file."""
  objdump_result = subprocess.check_output(['objdump', '-h', path])
  match = _TEXT_SECTION_PATTERN.search(objdump_result.decode())
  if not match:
    print('Unexpected objdump output for %s' % path)
    return None
  return int(match.group(1), 16)


def init(target):
  global _target
  _target = target
