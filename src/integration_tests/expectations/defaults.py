# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from build_options import OPTIONS
from util.test.suite_runner_config_flags import FLAKY
from util.test.suite_runner_config_flags import PASS


def get_expectations():
  return {
      'flags': PASS,
      'suite_test_expectations': {},
      'deadline': 300,  # Seconds
      'configurations': [{
          'enable_if': OPTIONS.weird(),
          'flags': FLAKY,
      }],
      'metadata': {}
  }
