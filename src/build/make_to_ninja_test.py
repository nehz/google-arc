# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for make_to_ninja.py."""

import unittest

import make_to_ninja


class MakeToNinjaUnittest(unittest.TestCase):
  def testFlagsRemove(self):
    asmflags = ['asmflags']
    cflags = ['cflags']
    conlyflags = ['conlyflags']
    cxxflags = ['cxxflags']
    ldflags = ['ldflags']

    flags = make_to_ninja.Flags(asmflags, cflags, conlyflags, cxxflags, ldflags)

    # Ensure that the instance holds flags in the right member.
    self.assertEquals(asmflags, flags.asmflags)
    self.assertEquals(cflags, flags.cflags)
    self.assertEquals(conlyflags, flags.conlyflags)
    self.assertEquals(cxxflags, flags.cxxflags)
    self.assertEquals(ldflags, flags.ldflags)

    # Ensure remove() removes specific flag, and that doesn't have a side effect
    # to the original flag list.
    flags.remove('cflags')
    self.assertEquals([], flags.cflags)
    self.assertEquals(['cflags'], cflags)

  def testFlagsHasFlag(self):
    flags = make_to_ninja.Flags([], ['abc'], [], [], [])
    self.assertTrue(flags.has_flag('abc'))
    self.assertFalse(flags.has_flag('cba'))


if __name__ == '__main__':
  unittest.main()
