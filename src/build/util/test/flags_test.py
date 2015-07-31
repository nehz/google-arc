# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import unittest

from util.test import flags


class FlagSetTest(unittest.TestCase):
  def test_property(self):
    flagset = flags.FlagSet(flags.PASS)
    self.assertEquals(flags.PASS, flagset.status)
    self.assertEquals(0, flagset.attribute)

    flagset = flags.FlagSet(flags.PASS | flags.LARGE)
    self.assertEquals(flags.PASS, flagset.status)
    self.assertEquals(flags.LARGE, flagset.attribute)

    # Also, attribute only FlagSet is allowed.
    flagset = flags.FlagSet(flags.LARGE)
    self.assertEquals(0, flagset.status)
    self.assertEquals(flags.LARGE, flagset.attribute)

  def test_or(self):
    merged = flags.FlagSet(flags.PASS) | flags.FlagSet(flags.LARGE)
    self.assertEquals(flags.PASS, merged.status)
    self.assertEquals(flags.LARGE, merged.attribute)

    # If both operands has status, raise an AssertionError.
    with self.assertRaises(AssertionError):
      flags.FlagSet(flags.PASS) | flags.FlagSet(flags.NOT_SUPPORTED)

  def test_eq_ne(self):
    self.assertEquals(flags.FlagSet(flags.PASS), flags.FlagSet(flags.PASS))
    self.assertNotEquals(flags.FlagSet(flags.PASS), flags.FlagSet(flags.FAIL))
    self.assertEquals(flags.FlagSet(flags.PASS | flags.LARGE),
                      flags.FlagSet(flags.PASS | flags.LARGE))
    self.assertNotEquals(flags.FlagSet(flags.PASS | flags.LARGE),
                         flags.FlagSet(flags.PASS))

    # Can be compared to None.
    self.assertNotEquals(flags.FlagSet(flags.PASS), None)
    self.assertNotEquals(None, flags.FlagSet(flags.PASS))

  def test_override_with(self):
    self.assertEquals(
        flags.FlagSet(flags.FAIL),
        flags.FlagSet(flags.PASS).override_with(flags.FlagSet(flags.FAIL)))

    self.assertEquals(
        flags.FlagSet(flags.FAIL | flags.LARGE),
        flags.FlagSet(flags.PASS).override_with(
            flags.FlagSet(flags.FAIL | flags.LARGE)))

    self.assertEquals(
        flags.FlagSet(flags.FAIL | flags.LARGE),
        flags.FlagSet(flags.PASS | flags.LARGE).override_with(
            flags.FlagSet(flags.FAIL)))

    self.assertEquals(
        flags.FlagSet(flags.PASS | flags.LARGE),
        flags.FlagSet(flags.PASS).override_with(flags.FlagSet(flags.LARGE)))

    self.assertEquals(
        flags.FlagSet(flags.PASS | flags.LARGE),
        flags.FlagSet(flags.LARGE).override_with(flags.FlagSet(flags.PASS)))
