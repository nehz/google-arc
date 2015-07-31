# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Defines expectation types and its combination for integration tests."""

# The flags is consistent as follows:
# Lower 4 bits are for expected test run status.
# Remaining bits are for attributes for a test.

# Defines expected test run status. Bigger values are worse.
# Note that '0' is preserved to indicate 'unspecified'. Please see also
# FlagSet defined below.

# The test should pass successfully.
PASS = 0x1

# In most cases, the test should pass successfully, but occasionally fail
# due to some reason.
FLAKY = 0x2

# The test should fail.
FAIL = 0x3

# The test does not complete in a specific period.
TIMEOUT = 0x4

# The test does not work at all. This looks similar to TIMEOUT, but this
# flag means, for example, the test does not finish due to crash.
NOT_SUPPORTED = 0x5

# The bit mask for test run status.
_STATUS_BITMASK = 0xF


# This is the marker to indicate that the test is LARGE (= takes longer time
# to complete).
LARGE = 0x10

# The bit mask for the attribute. Currently only LARGE is available.
_ATTRIBUTE_BITMASK = 0x10


# A map from bit to its name.
_FLAG_NAME_MAP = {
    PASS: 'PASS',
    FLAKY: 'FLAKY',
    FAIL: 'FAIL',
    TIMEOUT: 'TIMEOUT',
    NOT_SUPPORTED: 'NOT_SUPPORTED',
    LARGE: 'LARGE'
}


class FlagSet(object):
  """A set of flags defined above.

  Each test flag set should have one expected test run status and a set of
  attributes.
  However, for convenience, this class allows to have status unspecified.
  Such an instance represents attributes only.
  """

  def __init__(self, value):
    """Initialize a set with given bits.

    Args:
      value: a bits represents of a status and attributes.
    """
    assert (value & ~(_STATUS_BITMASK | _ATTRIBUTE_BITMASK)) == 0, (
        'Unknown bit is set: %x' % value)
    assert ((PASS <= (value & _STATUS_BITMASK) <= NOT_SUPPORTED) or
            (value & _STATUS_BITMASK) == 0 and (value & _ATTRIBUTE_BITMASK)), (
        'Invalid bit pattern: %x' % value)
    self._value = value

  @property
  def status(self):
    return self._value & _STATUS_BITMASK

  @property
  def attribute(self):
    return self._value & _ATTRIBUTE_BITMASK

  def __or__(self, other):
    """Returns the union of bits.

    |self| or |other| must be 'attribute only' FlagSet. Otherwise status
    would conflict.

    Args:
      other: Another FlagSet.

    Return:
      A new FlagSet which contain both flags.
    """
    assert ((self._value & _STATUS_BITMASK) == 0 or
            (other._value & _STATUS_BITMASK) == 0), (
        'The value of "%s" cannot be combined with the value of "%s" '
        'as both contain status flags.' % (self, other))
    return FlagSet(self._value | other._value)

  def __eq__(self, other):
    """Returns True if both have same bits. Otherwise False."""
    return other is not None and self._value == other._value

  def __ne__(self, other):
    """Returns False if both have same bits. Otherwise True."""
    return not (self == other)

  def __str__(self):
    """Returns string representation."""
    name_list = []
    status_name = _FLAG_NAME_MAP.get(self.status)
    if status_name:
      name_list.append(status_name)
    attribute = self.attribute
    if attribute & LARGE:
      name_list.append(_FLAG_NAME_MAP[LARGE])
    return ','.join(name_list)

  def override_with(self, overriding):
    """Returns a new overriden FlagSet.

    Return:
      A new FlagSet instance, whose;
      - status: if overriding has status, it is used. Otherwise self.status is
          used.
      - attributes: both attributes are simply merged.
    """
    status = overriding.status or self.status
    attribute = overriding.attribute | self.attribute
    return FlagSet(status | attribute)
