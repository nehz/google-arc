# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This file is a part of the Dalvik test infrastructure for ARC.
# It contains helper routines for running dalvikvm in system mode.
#

import re
import threading
import traceback

import toolchain
from util import concurrent_subprocess
from util import output_handler
from util.test import suite_runner

_ADB_SERVICE_PATTERN = re.compile(
    'I/AdbService:\s+(?:(emulator\-\d+)|Failed to start)')


class SystemModeError(Exception):
  """SystemMode class raised in this module."""


def _is_crash_line(line):
  return (output_handler.is_crash_line(line) or
          output_handler.is_abnormal_exit_line(line))


class _SystemModeThread(threading.Thread, concurrent_subprocess.OutputHandler):
  def __init__(self, suite_runner, additional_launch_chrome_opts):
    super(_SystemModeThread, self).__init__()
    self._suite_runner = suite_runner
    self._name = suite_runner.name
    self._additional_launch_chrome_opts = additional_launch_chrome_opts

    self._android_serial = None
    self._adb_wait_event = threading.Event()

    self._chrome_lock = threading.Lock()
    self._terminated = False
    self._chrome = None
    self._xvfb_output_filepath = None
    self._chrome_output_filepath = None
    self._chrome_output_file = None

    self._has_error = False

  def run(self):
    try:
      args = self._suite_runner.get_system_mode_launch_chrome_command(
          self._name, additional_args=self._additional_launch_chrome_opts)
      logfile_path = self._suite_runner.logger.path
      if self._suite_runner.use_xvfb:
        # This may override older log. However, it should be ok, because
        # older log should be already copied into logger.
        self._xvfb_output_filepath = logfile_path + '-system-mode-xvfb.log'
        args = suite_runner.SuiteRunnerBase.get_xvfb_args(
            self._xvfb_output_filename) + args

      with self._chrome_lock:
        if not self._terminated:
          self._chrome = concurrent_subprocess.Popen(args)
      if self._chrome:
        # This may override older log. However, it should be ok, because
        # older log should be already copied into logger.
        self._chrome_output_filepath = logfile_path + '-system-mode-chrome.log'
        with open(self._chrome_output_filepath, 'w') as chrome_output_file:
          try:
            self._chrome_output_file = chrome_output_file
            self._chrome.handle_output(self)
          finally:
            self._chrome_output_file = None
    finally:
      self._adb_wait_event.set()

  # Output handler implementation.
  def handle_stdout(self, line):
    # Although we expect serial is output from stderr, we look at stdout, too
    # because all stderr outputs are rerouted to stdout on running over
    # xvfb-run.
    self._handle_line(line)

  def handle_stderr(self, line):
    self._handle_line(line)

  def _handle_line(self, line):
    self._chrome_output_file.write(line)

    if _is_crash_line(line):
      # An error is found.
      self._suite_runner.logger.write(
          'chrome unexpectedly exited with line: %s\n' % line)
      self._has_error = True
      self._adb_wait_event.set()
      return

    if self._adb_wait_event.is_set():
      return

    # Look for a device serial name (such as "emulator-5554").
    match = _ADB_SERVICE_PATTERN.match(line)
    if not match:
      return

    self._android_serial = match.group(1)  # Note: None on failure.
    if self._android_serial:
      self._suite_runner.logger.write(
          'ARC adb service serial number is %s\n' % self._android_serial)
    else:
      self._suite_runner.logger.write('ARC adb service failed to start.\n')
      self._has_error = True

    self._adb_wait_event.set()

  def handle_timeout(self):
    self._has_error = True

  def is_done(self):
    # Terminate if an error is found.
    return self._has_error

  # Following methods are called from SystemMode, running on other thread.
  def wait_for_adb(self):
    self._adb_wait_event.wait(90)

  @property
  def is_ready(self):
    return self._android_serial is not None

  @property
  def android_serial(self):
    return self._android_serial

  @property
  def has_error(self):
    return self._has_error

  def shutdown(self):
    # First, terminate the chrome process.
    with self._chrome_lock:
      self._terminated = True
      if self._chrome:
        self._chrome.terminate()

    # Then, the thread will be terminated. Join it.
    self.join()

    # Finally, copy the log if necessary.
    if self._chrome_output_filepath:
      args = self._suite_runner.get_system_mode_launch_chrome_command(
          self._name, additional_args=self._additional_launch_chrome_opts)

      self._suite_runner.logger.writelines([
          '--------------------\n',
          ' '.join(args),
          '\n--------------------\n'])
      with open(self._chrome_output_filepath) as f:
        self._suite_runner.logger.writelines(f.read())
      self._suite_runner.logger.write('--------------------\n')

      # Output XVFB's log, if necessary.
      if self._xvfb_output_filepath:
        self._suite_runner.logger.write('---------- XVFB output ----------\n')
        with open(self._xvfb_output_filepath) as f:
          self._suite_runner.logger.write(f.read())
        self._suite_runner.logger.write('---------------------------------\n')
      self._suite_runner.logger.flush()


class SystemMode(object):
  """A class to manage ARC system mode for integration tests.

  Example:

    from util.test.suite_runner import SuiteRunnerBase
    from util.test.system_mode import SystemMode

    class MyTestRunner(SuiteRunnerBase):
      ...

      def run(self, unused_test_methods_to_run):
        with SystemMode(self) as arc:
          print arc.run_adb(['shell', 'echo', 'hello'])
        if arc.has_error():
          raise TimeoutError(arc.get_log())
        ...
  """

  def __init__(self, suite_runner, additional_launch_chrome_opts=None,
               rebuild_crx=False):
    if additional_launch_chrome_opts is None:
      additional_launch_chrome_opts = []
    self._suite_runner = suite_runner
    self._name = suite_runner.name
    self._additional_launch_chrome_opts = additional_launch_chrome_opts[:]
    if not rebuild_crx:
      self._additional_launch_chrome_opts.append('--nocrxbuild')

    self._adb = toolchain.get_tool('host', 'adb')
    self._has_error = False
    self._thread = None

  def __enter__(self):
    assert self._thread is None

    # Start the Chrome, and wait its serial to connect via adb command.
    self._thread = _SystemModeThread(
        self._suite_runner, self._additional_launch_chrome_opts)
    self._thread.start()
    self._thread.wait_for_adb()
    if not self._thread.is_ready:
      self._suite_runner.logger.write(
          'Timeout waiting to get adb serial number.\n')
      self._thread.shutdown()
      raise suite_runner.TimeoutError()

    try:
      self._suite_runner.run_subprocess(
          [self._adb, 'devices'], omit_xvfb=True)
      self.run_adb(['wait-for-device'])
    except Exception as e:
      # On failure, we need to terminate the Chrome.
      try:
        self._thread.shutdown()
      except Exception:
        # Ignore any exception here, because we re-raise the original
        # exception.
        self._suite_runner.logger.write(
            'Failed to terminate the Chrome: ' + traceback.format_exc())
      raise e

    # All set up is successfully passed.
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    # Terminate the Chrome.
    self._thread.shutdown()

  def run_adb(self, commands, **kwargs):
    """Runs an adb command and returns output.

    Returns single adb command's output. The output is also appended to
    the internal log container so that all logs can be obtained through
    get_log().
    """
    if self._thread is None or not self._thread.is_ready:
      raise SystemModeError('adb is not currently serving.')

    args = [self._adb, '-s', self._thread.android_serial] + commands
    kwargs.setdefault('omit_xvfb', True)
    return self._suite_runner.run_subprocess(args, **kwargs)

  def has_error(self):
    return self._has_error or self._thread.has_error
