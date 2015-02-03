# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

import build_common
from ninja_generator import ApkFromSdkNinjaGenerator
import prep_launch_chrome
import subprocess
from util.test import google_test_result_parser as result_parser
from util.test import scoreboard
from util.test import suite_runner
from util.test import suite_runner_util


class JavaScriptTestRunner(suite_runner.SuiteRunnerBase):
  """A test runner for running JavaScript tests."""

  def __init__(self, name, apks=None, additional_launch_chrome_args=None,
               **kwargs):
    if apks is None:
      apks = [
          ApkFromSdkNinjaGenerator.get_install_path_for_module('HelloAndroid')]

    super(JavaScriptTestRunner, self).__init__(
        name,
        suite_runner_util.read_test_list(
            build_common.get_integration_test_list_path(
                'test_template_' + name)),
        **kwargs)
    self._apks = apks
    self._additional_launch_chrome_args = additional_launch_chrome_args

  def handle_output(self, line):
    self._result_parser.process_line(line)

  def _get_js_test_options(self, test_methods_to_run):
    if test_methods_to_run == [scoreboard.Scoreboard.ALL_TESTS_DUMMY_NAME]:
      test_methods_to_run = None
    args = ['atftest']
    args.extend(self._apks)
    args.extend(['--app-template',
                 build_common.get_build_path_for_gen_test_template(self._name),
                '--run-test-as-app'])
    if self._additional_launch_chrome_args:
      args.extend(self._additional_launch_chrome_args)
    if test_methods_to_run:
      js_full_test_list = sorted(
          test_name.replace('#', '.') for test_name in self.expectation_map)
      js_test_filter_list = sorted(
          test_name.replace('#', '.') for test_name in test_methods_to_run)
      args.extend(['--additional-metadata',
                   json.dumps({
                       'jsFullTestList': js_full_test_list,
                       'jsTestFilter': ':'.join(js_test_filter_list)})])
    return args

  def prepare(self, test_methods_to_run):
    args = self.get_launch_chrome_command(
        self._get_js_test_options(test_methods_to_run))
    prep_launch_chrome.prepare_crx_with_raw_args(args)

  def setUp(self, test_methods_to_run):
    super(JavaScriptTestRunner, self).setUp(test_methods_to_run)
    self._result_parser = result_parser.JavaScriptTestResultParser(
        self.get_scoreboard())

  def run(self, test_methods_to_run):
    args = self.get_launch_chrome_command(
        self._get_js_test_options(test_methods_to_run))
    try:
      raw_output = self.run_subprocess(args)
    except subprocess.CalledProcessError:
      raw_output = self._get_subprocess_output()
    return raw_output, self._result_parser.test_method_results
