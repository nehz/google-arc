#!/usr/bin/python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for make_to_ninja.py."""

import make_to_ninja
import unittest


class MakeToNinjaUnittest(unittest.TestCase):
  def testFlagsRemove(self):
    cflags = ['cflags']
    conlyflags = ['conlyflags']
    cxxflags = ['cxxflags']
    ldflags = ['ldflags']

    flags = make_to_ninja.Flags(cflags, conlyflags, cxxflags, ldflags)

    # Ensure that the instance holds flags in the right member.
    self.assertEquals(cflags, flags.cflags)
    self.assertEquals(conlyflags, flags.conlyflags)
    self.assertEquals(cxxflags, flags.cxxflags)
    self.assertEquals(ldflags, flags.ldflags)

    # Ensure remove() removes specific flag, and that doesn't have a side effect
    # to the original flag list.
    flags.remove('cflags')
    self.assertEquals([], flags.cflags)
    self.assertEquals(['cflags'], cflags)


if __name__ == '__main__':
  unittest.main()
