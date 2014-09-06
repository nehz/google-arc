#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests covering filtered_subprocess"""

import subprocess
import time
import unittest

from filtered_subprocess import Popen


class SimpleOutputHandler(object):
  def __init__(self, done_on_timeout=False):
    self.stdout = ''
    self.stderr = ''
    self.timeout = False
    self.done = False
    self.done_on_timeout = done_on_timeout

  def is_done(self):
    return self.done or (self.done_on_timeout and self.timeout)

  def handle_stdout(self, text):
    self.stdout += text

  def handle_stderr(self, text):
    self.stderr += text

  def handle_timeout(self):
    self.timeout = True


class TestFilteredSubprocess(unittest.TestCase):
  # This is the extra time allowed for the child python process to start up and
  # compile the code before actually executing anything.
  _ALLOWED_STARTUP_TIME = 3

  # If we kill the child almost immediately, this is the maximum amount of time
  # that should be needed to shut it down.
  _WORST_CASE_WAIT_TIME = (Popen._SHUTDOWN_WAIT_SECONDS * 2 +
                           Popen._MIN_TIMEOUT_SECONDS * 2 +
                           _ALLOWED_STARTUP_TIME)

  def __init__(self, *args, **kwargs):
    super(TestFilteredSubprocess, self).__init__(*args, **kwargs)
    self.longMessage = True

  def _run_python_script(self, code, handler, **kwargs):
    p = Popen(['python', '-'], stdin=subprocess.PIPE)
    p.stdin.write(code)
    p.stdin.close()
    start_time = time.time()
    p.run_process_filtering_output(handler, **kwargs)
    elapsed_time = time.time() - start_time
    return p, elapsed_time

  def test_simple_run(self):
    output = SimpleOutputHandler()
    self.assertFalse(output.timeout)
    p, elapsed_time = self._run_python_script(r"""
import sys
sys.stdout.write('xyz\n')
sys.stderr.write('abc\n')
sys.stdout.flush()
sys.stderr.flush()""", output)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('abc\n', output.stderr)
    self.assertEquals('xyz\n', output.stdout)
    self.assertFalse(output.timeout)
    self.assertGreater(self._ALLOWED_STARTUP_TIME, elapsed_time,
                       '_ALLOWED_STARTUP_TIME seems to be too small?')

  def test_finishes_quickly_when_done_indicated(self):
    output = SimpleOutputHandler()
    output.done = True
    p, elapsed_time = self._run_python_script(r"""
import sys
import time
sys.stdout.write('xyz\n123')
sys.stdout.flush()
time.sleep(10)""", output, timeout=10, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals('xyz\n', output.stdout)
    self.assertFalse(output.timeout)
    self.assertGreater(
        self._ALLOWED_STARTUP_TIME, elapsed_time, 'Did not timeout')

  def test_timeout_with_partial_output(self):
    output = SimpleOutputHandler(done_on_timeout=True)
    p, elapsed_time = self._run_python_script(r"""
import sys
import time
sys.stdout.write('xyz\n123')
sys.stdout.flush()
time.sleep(10)""", output, timeout=1, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals('xyz\n', output.stdout)
    self.assertTrue(output.timeout)
    self.assertGreater(
        self._ALLOWED_STARTUP_TIME, elapsed_time, 'Did not timeout')

  def test_ends_before_output_fully_read(self):
    output = SimpleOutputHandler()
    p, _ = self._run_python_script(r"""
import sys
sys.stdout.write(1024 * (50 * 'x' + '\n'))""", output)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals(1024 * (50 * 'x' + '\n'), output.stdout)
    self.assertFalse(output.timeout)

  def test_subprocess_closes_handles_before_output_fully_read(self):
    output = SimpleOutputHandler()
    p, _ = self._run_python_script(r"""
import sys
import time
sys.stdout.write(1024 * (50 * 'x' + '\n'))
sys.stdout.close()
time.sleep(1)""", output)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals(1024 * (50 * 'x' + '\n'), output.stdout)
    self.assertFalse(output.timeout)

  def test_subprocess_times_out_but_ignores_sigterm(self):
    output = SimpleOutputHandler(done_on_timeout=True)
    p, elapsed_time = self._run_python_script(r"""
import signal
import sys
import time
def nack(signum, frame):
  sys.stdout.write('whoa ')
  sys.stdout.flush()
sys.stdout.write('hi ')
sys.stdout.flush()
signal.signal(signal.SIGTERM, nack)
# Extra sleeps used as a signal terminates a sleep
time.sleep(10)
time.sleep(10)
time.sleep(10)
sys.stdout.write('bye ')
sys.stdout.flush()""", output, timeout=1, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals('', output.stdout)
    self.assertTrue(output.timeout)
    self.assertGreater(
        self._WORST_CASE_WAIT_TIME, elapsed_time, 'Did not get killed')

  def test_subprocess_dumps_small_text_blob_on_sigterm(self):
    output = SimpleOutputHandler(done_on_timeout=True)
    p, elapsed_time = self._run_python_script(r"""
import signal
import sys
import time
def noise(signum, frame):
  sys.stdout.write('xyz\n123')
  sys.stdout.flush()
  assert False
signal.signal(signal.SIGTERM, noise)
time.sleep(10)
# A second sleep is needed since a signal terminates the first.
time.sleep(10)""", output, timeout=1, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertIn('', output.stderr)
    self.assertEquals('', output.stdout)
    self.assertTrue(output.timeout)
    self.assertGreater(
        self._WORST_CASE_WAIT_TIME, elapsed_time, 'Did not get killed')

  def test_subprocess_dumps_large_text_blob_on_sigterm(self):
    output = SimpleOutputHandler(done_on_timeout=True)
    p, elapsed_time = self._run_python_script(r"""
import signal
import sys
import time
def noise(signum, frame):
  sys.stdout.write(10 * 1024 * (50 * 'x' + '\n'))
  sys.stdout.flush()
  assert False
signal.signal(signal.SIGTERM, noise)
time.sleep(10)
# A second sleep is needed since a signal terminates the first.
time.sleep(10)""", output, timeout=1, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals('', output.stdout)
    self.assertTrue(output.timeout)
    self.assertGreater(
        self._WORST_CASE_WAIT_TIME, elapsed_time, 'Did not get killed')

  def test_output_timeout_triggered(self):
    output = SimpleOutputHandler(done_on_timeout=True)
    script = r"""
import sys
import time
sys.stdout.write('1\n')
sys.stdout.flush()
time.sleep(10)"""
    p, elapsed_time = self._run_python_script(
        script, output, output_timeout=self._ALLOWED_STARTUP_TIME + 1,
        timeout=self._ALLOWED_STARTUP_TIME * 10, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals('1\n', output.stdout)
    self.assertTrue(output.timeout)
    self.assertGreater(
        self._ALLOWED_STARTUP_TIME * 10, elapsed_time, 'Did not timeout')

  def test_output_timeout_not_triggered(self):
    output = SimpleOutputHandler(done_on_timeout=True)
    script = r"""
import sys
import time
for i in xrange(1, 10):
  sys.stdout.write('%d\n' % i)
  sys.stdout.flush()
  time.sleep(1)"""
    p, elapsed_time = self._run_python_script(
        script, output, output_timeout=self._ALLOWED_STARTUP_TIME + 1,
        timeout=self._ALLOWED_STARTUP_TIME * 10, stop_on_done=True)
    self.assertEquals(p._STATE_FINISHED, p._state)
    self.assertEquals('', output.stderr)
    self.assertEquals('123456789', output.stdout.replace('\n', ''))
    self.assertFalse(output.timeout)

if __name__ == '__main__':
  unittest.main()
