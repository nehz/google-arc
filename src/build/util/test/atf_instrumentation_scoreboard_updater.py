# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


class ATFInstrumentationScoreboardUpdater(object):
  def __init__(self, scoreboard):
    self._scoreboard = scoreboard

    self._current_result = None
    self._current_test = None

  def update(self, result_parser):
    current_test = result_parser.get_current_test_name()
    if current_test and current_test != self._current_test:
      self._scoreboard.start_test(current_test)
      self._current_test = current_test

    result = result_parser.get_latest_result()
    if result and not result.incomplete and result != self._current_result:
      self._current_result = result
      self._scoreboard.update([result])
