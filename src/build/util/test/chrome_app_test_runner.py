# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess
import shutil

import build_common
import prep_launch_chrome
from util.test import google_test_result_parser as result_parser
from util.test import scoreboard
from util.test import suite_runner
from util.test import suite_runner_util


class ChromeAppTestRunner(suite_runner.SuiteRunnerBase):
  """A test runner for running Chrome App tests (e.g. jstests.arc_welder).

  This test runner manually copies Chrome apps to the data_roots directory and
  executes launch_chrome with arguments such that apk_to_crx is bypassed and
  the Chrome App is launched directly.
  """

  def __init__(self, name, unpacked_dir, **kwargs):
    super(ChromeAppTestRunner, self).__init__(
        name,
        suite_runner_util.read_test_list(
            build_common.get_integration_test_list_path(
                'chrome_app_test_' + name)),
        **kwargs)
    self._unpacked_dir = unpacked_dir

  def handle_output(self, line):
    self._result_parser.process_line(line)

  def _get_launch_chrome_options(self):
    args = [
        'atftest',
        '--nocrxbuild',
        '--crx-name-override',
        self.name
    ]
    return args

  def _get_additional_metadata(self, test_methods_to_run):
    if test_methods_to_run == [scoreboard.Scoreboard.ALL_TESTS_DUMMY_NAME]:
      test_methods_to_run = None
    if not test_methods_to_run:
      return None

    js_full_test_list = sorted(
        test_name.replace('#', '.') for test_name in self.expectation_map)
    js_test_filter_list = sorted(
        test_name.replace('#', '.') for test_name in test_methods_to_run)

    return {
        'jsFullTestList': js_full_test_list,
        'jsTestFilter': ':'.join(js_test_filter_list)
    }

  def prepare(self, test_methods_to_run):
    data_roots_dir = os.path.join(build_common.get_data_root_dir(), self.name)
    input_dir = self._unpacked_dir
    shutil.rmtree(data_roots_dir, ignore_errors=True)
    shutil.copytree(input_dir, data_roots_dir)

  def setUp(self, test_methods_to_run):
    super(ChromeAppTestRunner, self).setUp(test_methods_to_run)
    self._result_parser = result_parser.JavaScriptTestResultParser(
        self.get_scoreboard())
    additional_metadata = self._get_additional_metadata(test_methods_to_run)
    args = self.get_launch_chrome_command(
        self._get_launch_chrome_options(),
        additional_metadata=additional_metadata)
    prep_launch_chrome.update_arc_metadata(additional_metadata, args)

  def run(self, test_methods_to_run):
    args = self.get_launch_chrome_command(
        self._get_launch_chrome_options(),
        additional_metadata=self._get_additional_metadata(test_methods_to_run))
    try:
      self.run_subprocess(args)
    except subprocess.CalledProcessError:
      pass
