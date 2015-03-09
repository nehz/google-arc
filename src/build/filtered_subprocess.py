# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility class, extending subprocess.Popen"""

import errno
import io
import logging
import select
import signal
import subprocess
import sys
import threading
import time

import build_common
from util import nonblocking_io


def _handle_stream_output(reader, handler):
  if reader is None or reader.closed:
    return False

  read = False
  try:
    for line in reader:
      handler(line)
      read = True
    reader.close()  # EOF is found.
  except io.BlockingIOError:
    # All available lines are read. No more line is available for now.
    pass
  return read


try:
  # On platforms other than Linux, psutil may not exist. As such
  # environment does not have xvfb-run, we can ignore the error.
  # We should also ignore NoSuchProcess. This means the program has
  # finished after creating psutil.Process object.
  import psutil

  def _signal_children_of_xvfb(pid, signum):
    try:
      for child in psutil.Process(pid).get_children():
        if child.name != 'Xvfb':
          child.send_signal(signum)
    except psutil.NoSuchProcess:
      # Ignore the case that no process is found. This could happen
      # when the subprocess is already terminated.
      pass

except ImportError:
  def _signal_children_of_xvfb(pid, signum):
    raise AssertionError('xvfb is not supported on this platform')


# TODO(2015-03-16): Get rid of subprocess.Popen inheritance.
# Now this class gets more different from subprocess.Popen, especially
# about multi-thread supporting. For example, we would not like to expose
# poll(), wait() or returncode, etc. terminate() and kill() semantics
# have been changed. Also, the arguments of __init__() have more restrictions.
# To simplify them, it's time to get rid of inheritance.
class Popen(subprocess.Popen):
  """Extends subprocess.Popen to run a process and filter its output. """

  _SHUTDOWN_WAIT_SECONDS = 5
  _NO_DEADLINE = float('inf')

  def __init__(self, args, stdin=None, stdout=subprocess.PIPE,
               stderr=subprocess.PIPE, **kwargs):
    assert not kwargs.get('shell', False), (
        'We do not expect to run process with shell.')
    assert kwargs.get('bufsize', 0) == 0, (
        'buffering should be disabled.')
    assert isinstance(args, list), (
        'non list args is not supported: %r' % (args,))
    assert 'executable' not in kwargs, 'executable is not supported.'
    self._launch_process(
        args, stdout=stdout, stderr=stderr, stdin=stdin, **kwargs)

    # Remember the executable name. This will be used to check if the process
    # is running with xvfb-run.
    self._is_xvfb = args[0] == 'xvfb-run'

    logging.info('Created pid %d; the command follows:', self.pid)
    build_common.log_subprocess_popen(args, **kwargs)

    # Wrap the stdout and stderr with setting them non-blocking.
    if self.stdout:
      self.stdout = nonblocking_io.LineReader(self.stdout)
    if self.stderr:
      self.stderr = nonblocking_io.LineReader(self.stderr)

    # Because terminate() or kill() can be called from various threads,
    # we need to guard them and their _deadline variables declared below.
    # In addition, poll(), wait() and returncode must be guarded with this
    # lock, in order to avoid sending signals to a subprocess, which is already
    # wait()ed in multi-threading manner.
    self._timeout_lock = threading.Lock()

    # This is the wall clock time of the timeout after terminate() is
    # invoked. This is set at the first invocation of terminate().
    self._terminate_deadline = None

    # Similar to _terminate_deadline, this is the wall clock time of the
    # timeout after kill() is invoked. This is set at the first invocation
    # of kill().
    self._kill_deadline = None

  def _launch_process(self, args, **kwargs):
    # This is just invoking super's constructor. This is injecting point
    # for testing.
    try:
      super(Popen, self).__init__(args, **kwargs)
    except Exception:
      logging.exception('Popen for args failed: %s', args)
      raise

  def _handle_output(self, output_handler):
    """Consumes output and invokes the corresponding handlers with them.

    Returns True if any output is observed.
    """
    stderr_read = _handle_stream_output(
        self.stderr, output_handler.handle_stderr)
    stdout_read = _handle_stream_output(
        self.stdout, output_handler.handle_stdout)
    return stderr_read or stdout_read

  def _has_open_pipe(self):
    """Returns True if either stdout or stderr is still opened."""
    return ((self.stdout and not self.stdout.closed) or
            (self.stderr and not self.stderr.closed))

  def _wait_for_child_output(self, timeout):
    """Waits for the child process to generate output."""
    # |timeout| must be set.
    assert timeout >= 0, 'Timeout must be non-negative value.'

    # Generate a list of handles to wait on for being able to read them.
    # Filter out any that have been closed.
    streams_to_block_reading_on = []
    if self.stdout and not self.stdout.closed:
      streams_to_block_reading_on.append(self.stdout)
    if self.stderr and not self.stderr.closed:
      streams_to_block_reading_on.append(self.stderr)

    if not streams_to_block_reading_on:
      # Here, we do not have any channel to the subprocess.
      # So, we wait for its termination until timeout.
      # We must check poll() inside the lock to be thread safe.
      # So, we use busy-loop, instead of wait() with timeout.
      # Note that Python 2.7 does not support wait() with timeout.
      # It is supported since 3.3, anyway.
      deadline = time.time() + timeout
      while time.time() < deadline:
        with self._timeout_lock:
          if self.poll() is not None:
            break
          # Poll every 0.1 secs, heuristically.
          time.sleep(0.1)
      return

    try:
      select.select(streams_to_block_reading_on, [], [], timeout)
    except select.error as e:
      if e[0] == errno.EINTR:
        logging.info("select has been interrupted, exit normally.")
        sys.exit(0)
      logging.error("select error: " + e[1])
      sys.exit(-1)

  def terminate(self):
    # To be thread safe, terminate() needs to be processed with lock.
    # When terminate() is invoked on a thread, the target subprocess may
    # be already wait()ed on another thread. In such a case, we should
    # not send the terminate signal to the subprocess.
    # So, unlike subprocess.Popen.terminate(), this ignores such a case.
    # Note that subprocess.Popen.terminate() will raise OSError with ENOENT
    # when terminate() is called for an already wait()ed subprocess.
    # It is a sign of programming error that should never be happened, rather
    # than handling a runtime error.
    with self._timeout_lock:
      self._terminate_locked()

  def _terminate_locked(self):
    # Must be invoked with holding |_timeout_lock|.
    self._terminate_locked_internal()
    # Record the timeout for terminate() at first time.
    if self._terminate_deadline is None:
      self._terminate_deadline = time.time() + Popen._SHUTDOWN_WAIT_SECONDS

  def _terminate_locked_internal(self):
    # This is the injecting point for testing.
    if self._is_xvfb:
      _signal_children_of_xvfb(self.pid, signal.SIGTERM)
    elif self.returncode is None:
      super(Popen, self).terminate()

  def kill(self):
    # To be thread safe, kill() needs to be processed with lock.
    # Similar to terminate(), this does not send kill() to an already wait()ed
    # subprocess. Please see terminate()'s comment, for more details.
    with self._timeout_lock:
      self._kill_locked()

  def _kill_locked(self):
    # Must be invoked with holding |_timeout_lock|.
    self._kill_locked_internal()
    # Record the timeout for kill() at first time.
    if self._kill_deadline is None:
      self._kill_deadline = time.time() + Popen._SHUTDOWN_WAIT_SECONDS

  def _kill_locked_internal(self):
    # This is the injecting point for testing.
    if self._is_xvfb:
      _signal_children_of_xvfb(self.pid, signal.SIGKILL)
    elif self.returncode is None:
      super(Popen, self).kill()

  def run_process_filtering_output(self, output_handler, timeout=None,
                                   output_timeout=None, stop_on_done=False):
    """Runs the process, invoking methods on output_handler as appropriate.

    output_handler is expected to have the following interface:

        output_handler.is_done()
            Should return true if process should be terminated. Note however
            it is called only immediately after output is processed, so if
            the process is not generating any output when this call would
            return True, then it will not be terminated.
        output_handler.handle_stdout(line)
            Called whenever the process writes a line of text to stdout.
        output_handler.handle_stderr(line)
            Called whenever the process writes a line of text to stderr.
        output_handler.handle_timeout()
            Called whenever the process timeout is over.

    If timeout is not None, it is a count in seconds to wait for process
    termination.

    if output_timeout is not None, it is the maximum count in seconds to wait
    for any output activity from the child process.

    If stop_on_done is True, the run loop stops trying to filter output as soon
    as the output_handler signals it is done, and just waits for process
    termination.
    """
    for _ in self.run_process_filtering_output_generator(
        output_handler, timeout=timeout, output_timeout=output_timeout,
        stop_on_done=stop_on_done):
      pass

  def run_process_filtering_output_generator(
      self, output_handler, timeout=None, output_timeout=None,
      stop_on_done=False):
    """Generator version of run_process_filtering_output().

    This generator yields after processing process output chunk.
    """

    # Calculate the deadline.
    now = time.time()
    total_deadline = Popen._NO_DEADLINE if timeout is None else timeout + now
    output_deadline = (
        Popen._NO_DEADLINE if output_timeout is None else output_timeout + now)

    # Yield before processing any output.
    yield

    while True:
      # The condition to terminate.
      if not self._has_open_pipe():
        with self._timeout_lock:
          if self.poll() is not None:
            # Here, both stdout and stderr are closed (i.e. reached to EOF),
            # and the subprocess is terminated. Exit the loop.
            break

      # First of all, calculate the timeout duration.
      with self._timeout_lock:
        # If either kill() or terminate() is invoked, we do not need to take
        # care of timeout due to |total_deadline| or |output_deadline|.
        # Here, we give priority to kill()'s deadline. Because what we'll do
        # after |terminate_deadline| timeout is invoking kill(), if it is not
        # yet invoked, so if kill() is already invoked, we'll do nothing.
        if self._kill_deadline is not None:
          deadline = self._kill_deadline
        elif self._terminate_deadline is not None:
          deadline = self._terminate_deadline
        else:
          # Here, neither kill() nor terminate() has been invoked. Take the
          # minimum of |total_deadline| and |output_deadline|.
          deadline = min(total_deadline, output_deadline)

      # Here, there is a small race. After timeout calculation is done,
      # another thread may invoke terminate() or kill().
      # 1) In regular cases, the subprocess is expected to be terminated.
      #    So, _wait_for_child_output() is expected to be returned quickly
      #    as stdout/stderr are closed and/or self.poll() is succeeded.
      # 2) In irregular cases, the subprocess is not terminated. In such a
      #    case, _wait_for_child_output is not returned quickly. However,
      #    what we want to do after the terminate() is just sending kill()
      #    to the subprocess, or exit from the loop after kill()'s timeout.
      #    To ensure it happens, we set timeout at most _SHUTDOWN_WAIT_SECONDS.
      now = time.time()
      timeout = max(0, min(deadline - now, Popen._SHUTDOWN_WAIT_SECONDS))
      self._wait_for_child_output(timeout)

      now = time.time()
      # Process the stdout and stderr. If there is some output for either,
      # update |output_deadline|.
      # Note that |output_deadline| will never be updated, after closing of
      # the streams. I.e., we expect that the subprocess is terminated
      # within the |timeout| after closing the stream.
      if self._handle_output(output_handler) and output_timeout is not None:
        output_deadline = output_timeout + now

      # Yield after processing the output.
      yield

      # Process timeout.
      with self._timeout_lock:
        if self._kill_deadline is not None:
          # Here, kill() is already invoked, at least once.
          if self._kill_deadline < now:
            # The process looks not terminated yet even after certain time.
            # Timeout it, and exit the loop.
            break

        elif self._terminate_deadline is not None:
          # Here, terminate() is already invoked, at least once.
          if self._terminate_deadline < now:
            # The process looks not terminated yet even after certain time.
            # Timeout it, and send kill().
            self._kill_locked()

        elif output_handler.is_done():
          # The handler tells that what it needs is completed in subprocess.
          # Try to terminate.
          self._terminate_locked()

        elif output_deadline < now or total_deadline < now:
          # Here, no output is observed from the subprocess for certain time
          # or, the subprocess is alive too long. Timeout and try to
          # terminate it.
          # Note that this should be called at most once. It is ensured by the
          # fact that _terminate_locked() will set |_terminate_deadline|
          # internally, so that the condition above will hit.
          self._terminate_locked()

          # Notify output_handler via handle_timeout() invocation.
          # To avoid recursive lock, we call it with unlocking the
          # _timeout_lock.
          self._timeout_lock.release()
          try:
            output_handler.handle_timeout()
          finally:
            self._timeout_lock.acquire()
