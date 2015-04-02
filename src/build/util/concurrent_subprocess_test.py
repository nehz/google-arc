# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


""" Unit test for concurrent_subprocess."""

import os
import signal
import threading
import unittest


from util import concurrent_subprocess


class SimpleOutputHandler(concurrent_subprocess.OutputHandler):
  """Simple output handler to store stdout, stderr and timeout."""

  def __init__(self):
    super(SimpleOutputHandler, self).__init__()
    self.done = False
    self.stdout = ''
    self.stderr = ''
    self.timeout = False
    self.returncode = None

  def is_done(self):
    return self.done

  def handle_stdout(self, line):
    self.stdout += line

  def handle_stderr(self, line):
    self.stderr += line

  def handle_timeout(self):
    self.timeout = True

  def handle_terminate(self, returncode):
    if self.returncode is not None:
      return self.returncode
    return returncode


class FakeTimer(object):
  def __init__(self, interval, callback):
    self.interval = interval
    self.callback = callback
    self.ran = False
    self.cancelled = False

  def cancel(self):
    if not self.ran:
      self.cancelled = True

  def __eq__(self, other):
    return ((self.interval == other.interval) and
            (self.callback == other.callback) and
            (self.ran == other.ran) and
            (self.cancelled == other.cancelled))

  def __repr__(self):
    return ('FakeTimer(interval=%r, callback=%r, ran=%r, cancelled=%r)' %
            (self.interval, self.callback, self.ran, self.cancelled))

  def run(self):
    assert not self.cancelled
    self.ran = True
    self.callback()


def _make_pipe():
  """Returns a pair of file objects."""
  read, write = os.pipe()
  return os.fdopen(read, 'r'), os.fdopen(write, 'w', 0)


def _maybe_close(stream):
  try:
    if stream and not stream.closed:
      stream.close()
  except IOError:
    # Ignore IO errors.
    pass


class FakePopen(object):
  def __init__(self):
    self.stdout, self._child_stdout = _make_pipe()
    self.stderr, self._child_stderr = _make_pipe()
    self.pid = None
    self.returncode = None

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    _maybe_close(self.stdout)
    _maybe_close(self.stderr)
    _maybe_close(self._child_stdout)
    _maybe_close(self._child_stderr)

  def write_stdout(self, text):
    self._child_stdout.write(text)

  def write_stderr(self, text):
    self._child_stderr.write(text)

  def close_child_stdout(self):
    _maybe_close(self._child_stdout)

  def close_child_stderr(self):
    _maybe_close(self._child_stderr)

  def poll(self):
    return self.returncode

  def terminate(self):
    assert self.returncode is None
    _maybe_close(self._child_stdout)
    _maybe_close(self._child_stderr)
    self.returncode = -signal.SIGTERM

  def kill(self):
    assert self.returncode is None
    _maybe_close(self._child_stdout)
    _maybe_close(self._child_stderr)
    self.returncode = -signal.SIGKILL


class TestPopen(concurrent_subprocess.Popen):
  def __init__(self, process_fake, *args, **kwargs):
    # _start_timer_locked may be called insider __init__, so set up
    # created_timer_list in advance.
    self.created_timer_list = []
    super(TestPopen, self).__init__(
        subprocess_factory=(lambda *args, **kwargs: process_fake),
        *args, **kwargs)

  def _start_timer_locked(self, interval, callback):
    # Inject a fake instance.
    timer = FakeTimer(interval, callback)
    self.created_timer_list.append(timer)
    # Emulate the _start_timer_locked.
    self._timers.append(timer)


class FakePopenTest(unittest.TestCase):
  def test_trivial_successful_run(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])
      p.write_stdout('xyz\n123')
      p.write_stderr('abc\n456')
      p.close_child_stdout()
      p.close_child_stderr()
      p.returncode = 0

      output_handler = SimpleOutputHandler()
      returncode = popen.handle_output(output_handler)
    self.assertEquals('xyz\n123', output_handler.stdout)
    self.assertEquals('abc\n456', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    self.assertEquals(0, returncode)

  def test_large_output(self):
    large_string = 1024 * (50 * 'x' + '\n')
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])
      p.write_stdout(large_string)
      p.close_child_stdout()
      p.close_child_stderr()
      p.returncode = 0

      output_handler = SimpleOutputHandler()
      returncode = popen.handle_output(output_handler)
    self.assertEquals(large_string, output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    self.assertEquals(0, returncode)

  def test_is_done(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])
      p.write_stdout('xyz\n123')
      output_handler = SimpleOutputHandler()
      output_handler.done = True
      returncode = popen.handle_output(output_handler)
    self.assertEquals('xyz\n123', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    self.assertEquals(-signal.SIGTERM, returncode)

    # Make sure that kill tried to be invoked, but cancelled.
    kill_timer = FakeTimer(
        concurrent_subprocess.Popen._SHUTDOWN_WAIT_SECONDS, popen.kill)
    kill_timer.cancelled = True
    self.assertEquals([kill_timer], popen.created_timer_list)

  def test_timeout(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'], timeout=10)  # Timeout immediately.
      # The timer should start.
      self.assertEquals([FakeTimer(10, popen._timeout)],
                        popen.created_timer_list)
      # Here, fire the timeout, manually.
      popen.created_timer_list[0].run()

      output_handler = SimpleOutputHandler()
      returncode = popen.handle_output(output_handler)
    self.assertEquals('', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertTrue(output_handler.timeout)
    self.assertEquals(-signal.SIGTERM, returncode)

    # Make sure that kill tried to be invoked, but cancelled.
    timeout_timer = FakeTimer(10, popen._timeout)
    timeout_timer.ran = True
    kill_timer = FakeTimer(
        concurrent_subprocess.Popen._SHUTDOWN_WAIT_SECONDS, popen.kill)
    kill_timer.cancelled = True
    self.assertEquals([timeout_timer, kill_timer], popen.created_timer_list)

  def test_terminate(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])

      p.close_child_stdout()
      p.close_child_stderr()
      p.returncode = 0

      output_handler = SimpleOutputHandler()
      output_handler.returncode = 100
      returncode = popen.handle_output(output_handler)
    self.assertEquals('', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    # |returncode| should be overriden.
    self.assertEquals(100, returncode)

  def test_async_terminate(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])

      output_handler = SimpleOutputHandler()
      # Here, what case we want to test is that terminate() while
      # handle_output() is waiting at select(). However, theoretically,
      # there is no way to ensure it. So, we *try* to do it by waiting
      # 0.3 secs (heuristically). Note that, even if the terminate() is
      # invoked before the select(), the test must pass stably.
      timer = threading.Timer(0.3, popen.terminate)
      timer.start()
      returncode = popen.handle_output(output_handler)
      timer.join()
    self.assertEquals('', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    self.assertEquals(-signal.SIGTERM, returncode)

  def test_async_kill(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])

      output_handler = SimpleOutputHandler()
      # Similar to test_async_terminate(), we wait 0.3 secs to send kill().
      timer = threading.Timer(0.3, popen.kill)
      timer.start()
      returncode = popen.handle_output(output_handler)
      timer.join()
    self.assertEquals('', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    self.assertEquals(-signal.SIGKILL, returncode)

  def test_terminate_later(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])
      popen.terminate_later(5)
    self.assertEquals([FakeTimer(5, popen.terminate)],
                      popen.created_timer_list)

  def test_signal_after_process_termination(self):
    with FakePopen() as p:
      popen = TestPopen(p, ['cmd'])
      # Emulate subprocess termination.
      p.close_child_stdout()
      p.close_child_stderr()
      p.returncode = 0

    # These should be no effect.
    popen.terminate()
    popen.terminate_later(5)
    popen.kill()

    # Even timer should not be created.
    self.assertEquals([], popen.created_timer_list)


class PopenTest(unittest.TestCase):
  # For sanity check, we run real Popen.
  def test_simple_run(self):
    p = concurrent_subprocess.Popen(['python', '-c', 'print "abc"'])
    output_handler = SimpleOutputHandler()
    returncode = p.handle_output(output_handler)
    self.assertEquals('abc\n', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertFalse(output_handler.timeout)
    self.assertEquals(0, returncode)

  def test_timeout(self):
    p = concurrent_subprocess.Popen(
        ['python', '-c', 'while True: pass'], timeout=0.3)
    output_handler = SimpleOutputHandler()
    returncode = p.handle_output(output_handler)
    self.assertEquals('', output_handler.stdout)
    self.assertEquals('', output_handler.stderr)
    self.assertTrue(output_handler.timeout)
    self.assertEquals(-signal.SIGTERM, returncode)
