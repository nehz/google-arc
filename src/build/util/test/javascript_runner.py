# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess

import build_common
import ninja_generator
import prep_launch_chrome
from util.test import google_test_result_parser as result_parser
from util.test import scoreboard
from util.test import source_annotator
from util.test import suite_runner
from util.test import suite_runner_util


class _JavaScriptLoggerWrapper(object):
  """Wraps the SuiteRunnerLogger to annotate original JavaScript location."""

  def __init__(self, base_logger, annotator):
    self.base_logger = base_logger
    self._annotator = annotator

  @property
  def path(self):
    return self.base_logger.path

  def close(self):
    return self.base_logger.close()

  def flush(self):
    return self.base_logger.flush()

  def write(self, text):
    text = ''.join(
        self._annotator.annotate(line) for line in text.splitlines(True))
    return self.base_logger.write(text)

  def writelines(self, text_list):
    return self.write(''.join(text_list))


class JavaScriptTestRunner(suite_runner.SuiteRunnerBase):
  """A test runner for running JavaScript tests."""

  def __init__(self, name, apks=None, additional_launch_chrome_args=None,
               **kwargs):
    if apks is None:
      apks = [
          ninja_generator.ApkFromSdkNinjaGenerator.get_install_path_for_module(
              'HelloAndroid')]

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

  def _get_js_test_options(self):
    args = ['atftest']
    args.extend(self._apks)
    args.extend(['--app-template',
                 build_common.get_build_path_for_gen_test_template(self._name),
                '--run-test-as-app'])
    if self._additional_launch_chrome_args:
      args.extend(self._additional_launch_chrome_args)

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
    args = self.get_launch_chrome_command(
        self._get_js_test_options(),
        additional_metadata=self._get_additional_metadata(test_methods_to_run))
    prep_launch_chrome.prepare_crx_with_raw_args(args)

  def setUp(self, test_methods_to_run):
    super(JavaScriptTestRunner, self).setUp(test_methods_to_run)
    self._result_parser = result_parser.JavaScriptTestResultParser(
        self.get_scoreboard())
    additional_metadata = self._get_additional_metadata(test_methods_to_run)
    args = self.get_launch_chrome_command(
        self._get_js_test_options(),
        additional_metadata=additional_metadata)
    prep_launch_chrome.update_arc_metadata(additional_metadata, args)

    # List of sourcemap files. This needs to be sync with the build-time
    # configuration. cf) src/packaging/config.py.
    runtime_dir = build_common.get_runtime_out_dir()
    test_template_dir = build_common.get_build_path_for_gen_test_template(
        self.name)
    annotator = source_annotator.SourceAnnotator([
        ('gen_main.min.js',
         os.path.join(runtime_dir, 'gen_main.min.js'),
         os.path.join(runtime_dir, 'gen_main.min.js.map')),
        ('gen_index.min.js',
         os.path.join(runtime_dir, 'gen_index.min.js'),
         os.path.join(runtime_dir, 'gen_index.min.js.map')),
        ('gen_test.min.js',
         os.path.join(test_template_dir, 'gen_test.min.js'),
         os.path.join(test_template_dir, 'gen_test.min.js.map'))
    ])
    self._logger = _JavaScriptLoggerWrapper(self._logger, annotator)

  def tearDown(self, test_methods_to_run):
    # Note: this is called even when setUp() is failed, currently.
    if isinstance(self._logger, _JavaScriptLoggerWrapper):
      self._logger = self._logger.base_logger
    super(JavaScriptTestRunner, self).tearDown(test_methods_to_run)

  def run(self, test_methods_to_run):
    args = self.get_launch_chrome_command(
        self._get_js_test_options(),
        additional_metadata=self._get_additional_metadata(test_methods_to_run))
    args.append('--nocrxbuild')
    try:
      self.run_subprocess(args)
    except subprocess.CalledProcessError:
      pass
