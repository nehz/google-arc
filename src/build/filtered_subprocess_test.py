# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests of filtered_subprocess."""

import os
import signal
import subprocess
import unittest

import filtered_subprocess


class SimpleOutputHandler(object):
  """Simple ouput handler type with functionality useful for tests.

  Buffers all output (stdout and stderr) sent to it by
  filtered_subprocess.Popen, and can terminate the process early.
  """

  def __init__(self):
    self.stdout = ''
    self.stderr = ''
    self.timeout = False
    self.done = False

  def is_done(self):
    """Invoked to check if the process is done and should be terminated."""
    return self.done

  def handle_stdout(self, text):
    """Invoked to handle output written to stdout."""
    self.stdout += text

  def handle_stderr(self, text):
    """Invoked to handle output written to stderr."""
    self.stderr += text

  def handle_timeout(self):
    """Invoked to notify the handler that the child has timed-out."""
    self.timeout = True


def _make_pipe():
  """Returns a pair of file objects."""
  read, write = os.pipe()
  return os.fdopen(read, 'r'), os.fdopen(write, 'w', 0)


def _maybe_close(stream):
  try:
    if stream and not stream.closed:
      stream.close()
  except IOError:
    # Ignore errors.
    pass


class FakePopen(filtered_subprocess.Popen):
  """Fake implementation of Popen by stubbing some methods.

  Because Popen communicates with other processes, it is difficult to be
  tested. This fake does not create an actual child process, but pipes for
  stdout and stderr are available.
  """
  def __init__(self, args, ignore_terminate=False, ignore_kill=False):
    """Initializes the FakePopen.

    - ignore_terminate: if set to True, this ignores the terminate().
    - ignore_kill: if set to True, this ignores the kill().
    These are useful to emulate the situation that the signals are already sent
    but the subprocess is not yet terminated.
    """
    super(FakePopen, self).__init__(args)
    self.returncode = None
    self._ignore_terminate = ignore_terminate
    self._ignore_kill = ignore_kill
    self._process_collected = False

  def _launch_process(self, args, **kwargs):
    # Set up dummy stdout/stderr, if necessary.
    if kwargs.get('stdout') == subprocess.PIPE:
      self.stdout, self._stdout_write = _make_pipe()
    else:
      self.stdout = None
      self._stdout_write = None

    if kwargs.get('stderr') == subprocess.PIPE:
      self.stderr, self._stderr_write = _make_pipe()
    else:
      self.stderr = None
      self._stderr_write = None

    # Set dummy pid.
    self.pid = -1

  # To ensure file streams are closed on test completion, we support
  # with statement.
  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    _maybe_close(self.stdout)
    _maybe_close(self._stdout_write)
    _maybe_close(self.stderr)
    _maybe_close(self._stderr_write)

  def write_stdout(self, text):
    self._stdout_write.write(text)

  def write_stderr(self, text):
    self._stderr_write.write(text)

  def close_child_stdout(self):
    self._stdout_write.close()

  def close_child_stderr(self):
    self._stderr_write.close()

  def _terminate_locked_internal(self):
    assert not self._process_collected
    # Stubbed out.
    if not self._ignore_terminate and self.returncode is None:
      self.returncode = -signal.SIGTERM
      _maybe_close(self._stdout_write)
      _maybe_close(self._stderr_write)

  def _kill_locked_internal(self):
    assert not self._process_collected
    # Stubbed out.
    if not self._ignore_kill and self.returncode is None:
      self.returncode = -signal.SIGKILL
      _maybe_close(self._stdout_write)
      _maybe_close(self._stderr_write)

  def poll(self):
    if self.returncode is not None:
      self._process_collected = True
    return self.returncode

  def wait(self):
    raise AssertionError('We do not expect wait() is invoked.')


class FakePopenTest(unittest.TestCase):
  def setUp(self):
    # Set shutdown wait to 0, to make test stable.
    self._shutdown_wait_seconds_backup = (
        filtered_subprocess.Popen._SHUTDOWN_WAIT_SECONDS)
    filtered_subprocess.Popen._SHUTDOWN_WAIT_SECONDS = 0

  def tearDown(self):
    filtered_subprocess.Popen._SHUTDOWN_WAIT_SECONDS = (
        self._shutdown_wait_seconds_backup)

  def test_trivial_successful_run(self):
    with FakePopen(['cmd']) as p:
      p.write_stdout('xyz\n123')
      p.write_stderr('abc\n456')
      p.close_child_stdout()
      p.close_child_stderr()
      p.returncode = 0  # Fake termination of the subprocess.

      output_handler = SimpleOutputHandler()
      p.run_process_filtering_output(output_handler)

    self.assertEquals('xyz\n123', output_handler.stdout)
    self.assertEquals('abc\n456', output_handler.stderr)
    self.assertFalse(output_handler.timeout)

  def test_large_output(self):
    large_string = 1024 * (50 * 'x' + '\n')

    with FakePopen(['cmd']) as p:
      p.write_stdout(large_string)
      p.close_child_stdout()
      p.close_child_stderr()
      p.returncode = 0  # Fake termination of the subprocess.

      output_handler = SimpleOutputHandler()
      p.run_process_filtering_output(output_handler)

    self.assertEquals(large_string, output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)

  def test_output_handler_can_terminate_subprocess(self):
    with FakePopen(['cmd']) as p:
      p.write_stdout('xyz\n123')

      output_handler = SimpleOutputHandler()
      output_handler.done = True
      p.run_process_filtering_output(output_handler)

    self.assertEquals(-signal.SIGTERM, p.returncode)
    self.assertEquals('xyz\n123', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)

  def test_global_timeout(self):
    with FakePopen(['cmd']) as p:
      output_handler = SimpleOutputHandler()
      # Timeout immediately.
      p.run_process_filtering_output(output_handler, timeout=0)

    self.assertEquals(-signal.SIGTERM, p.returncode)
    self.assertTrue(output_handler.timeout)

  def test_output_timeout(self):
    with FakePopen(['cmd']) as p:
      output_handler = SimpleOutputHandler()
      # Timeout immediately.
      p.run_process_filtering_output(output_handler, output_timeout=0)

    self.assertEquals(-signal.SIGTERM, p.returncode)
    self.assertTrue(output_handler.timeout)

  def test_terminate_timeout(self):
    with FakePopen(['cmd'], ignore_terminate=True) as p:
      p.terminate()
      output_handler = SimpleOutputHandler()
      p.run_process_filtering_output(output_handler)
    self.assertEquals(-signal.SIGKILL, p.returncode)
    self.assertFalse(output_handler.timeout)

  def test_kill_timeout(self):
    with FakePopen(['cmd'], ignore_terminate=True, ignore_kill=True) as p:
      p.terminate()
      output_handler = SimpleOutputHandler()
      p.run_process_filtering_output(output_handler)
    self.assertIsNone(p.returncode)
    self.assertFalse(output_handler.timeout)


class PopenTest(unittest.TestCase):
  # For sanity check, we run real Popen.
  def test_simple_run(self):
    output_handler = SimpleOutputHandler()
    p = filtered_subprocess.Popen(['python', '-c', 'print "abc"'])
    p.run_process_filtering_output(output_handler)
    self.assertEquals(0, p.returncode)
    self.assertEquals('', output_handler.stderr)
    self.assertEquals('abc\n', output_handler.stdout)
    self.assertFalse(output_handler.timeout)
