# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Defines an object which describes the current testing environment."""


class _TestOptions(object):
  def __init__(self):
    self.reset()

  def reset(self):
    self._is_buildbot = False

  def set_is_running_on_buildbot(self, value):
    self._is_buildbot = bool(value)

  @property
  def is_buildbot(self):
    return self._is_buildbot

TEST_OPTIONS = _TestOptions()
