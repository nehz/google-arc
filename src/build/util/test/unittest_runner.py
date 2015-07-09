# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implements a suite runner that runs unittests."""

from util.test import suite_runner
from util.test import suite_runner_config_flags as flags


class UnittestRunner(suite_runner.SuiteRunnerBase):
  # Currently UnittestRunner contains only one test case, "unittest#main".
  # Each suite may contain multiple test cases. However, in this runner,
  # the set of all test cases are handled as one test case for now.
  # Note: in order to split all test cases, we need to support test filters
  # and log parsers (to update its scoreboard). However, it introduces bigger
  # complexity. Specifically:
  # 1) This is only for ChromeOS. On other platforms, it should run on
  # ninja-time. Unfortunately, some tests are disabled by #ifdef guards,
  # so we need to have some blacklist and to keep consistent with the #ifdefs.
  # It would increase the maintenance cost, unfortunately.
  # 2) Most tests use googletest library, but some are not. Specifically,
  # stlport_unittest uses CPPUNIT. Supporting its test filter and log parser
  # is possible, but it introduces another complexity to run_unittest.py.
  #
  # Considering all the costs and complexities, a singlet test name is used
  # just to represent all the tests.
  _TEST_NAME = 'unittest#main'

  def __init__(self, test_name, **kwargs):
    super(UnittestRunner, self).__init__(
        test_name, {UnittestRunner._TEST_NAME: flags.PASS}, **kwargs)

  def run(self, test_methods_to_run):
    assert test_methods_to_run == [UnittestRunner._TEST_NAME]
    unittest_name = self._name.replace('unittests.', '', 1)

    self.run_subprocess_test(
        UnittestRunner._TEST_NAME,
        ['python', 'src/build/run_unittest.py', unittest_name])
