# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import cStringIO
import re
import unittest

from util import debug


# Functions for testing stack frame output.
def foo(arg0, out):
  debug.write_frames(out)
  return arg0


def bar(arg0, arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, out):
  return foo(arg0, out) + (arg1 if arg8 or arg7 else len(arg6))


def baz(arg0, arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, out, *args,
        **kwargs):
  return bar(arg0, arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, out)


class DebugTest(unittest.TestCase):
  _ARG_INFO_RE = re.compile('ArgInfo: .+')

  def test_write_frames(self):
    out = cStringIO.StringIO()
    baz(1, 2.3, 'abc', True, False, None, [], (), {}, set(), out, 4, 5,
        kwarg0=6, kwarg1=7)

    # Extract ArgInfo lines.
    arg_info_list = [line for line in out.getvalue().splitlines()
                     if DebugTest._ARG_INFO_RE.search(line)]

    # ArgInfo lines should appear in this order.
    expected_list = [
        (r'ArgInfo: arg0=1, arg1=2.3, arg2=\'abc\', arg3=True, arg4=False, '
         'arg5=None, arg6=\[\], arg7=\(\), arg8={}, arg9=set\(\[\]\), '
         'out=\|out\|, kwargs={\'kwarg0\': 6, \'kwarg1\': 7}, args=\(4, 5\)'),
        (r'ArgInfo: arg0=1, out=\|out\|, arg1=2.3, arg8={}, arg7=\(\), '
         'arg6=\[\], arg2=\'abc\', arg3=True, arg4=False, arg5=None, '
         'arg9=set\(\[\]\)'),
        r'ArgInfo: out=\|out\|, arg0=1',
    ]
    try:
      it = iter(arg_info_list)
      for expected in expected_list:
        while not re.search(expected, it.next()):
          pass
    except StopIteration:
      self.fail('%s\n\ndoes not appear in the following output:\n\n%s' %
                ('\n'.join(expected_list), out.getvalue()))

  def test_write_frames_with_no_code_context_func(self):
    # This test is just for checking debug.write_frames works without raising
    # an exception when a function which does not have code context is in the
    # stack.
    out = cStringIO.StringIO()
    eval('debug.write_frames(out)')
    self.assertTrue(out.getvalue())


if __name__ == '__main__':
  unittest.main()
