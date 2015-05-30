# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import logging
import re
import select
import signal
import subprocess
import sys
import threading
import time

from util import logging_util
from util import nonblocking_io
from util import signal_util

try:
  import psutil
except ImportError:
  # On platforms other than Linux, psutil may not exist. As such environment
  # does not have xvfb-run, we can ignore the error.
  pass


def _signal_xvfb_children(pid, signum):
  """Sends |signum| signal to the children of the process with |pid|."""
  try:
    for child in psutil.Process(pid).get_children():
      if child.name != 'Xvfb':
        child.send_signal(signum)
  except psutil.NoSuchProcess:
    # We should also ignore NoSuchProcess. This means the program has
    # terminated after creating psutil.Process object.
    pass


class _XvfbPopen(subprocess.Popen):
  """Popen for "xvfb-run" program.

  On terminate() and kill(), this class sends SIGTERM or SIGKILL to the
  child processes of the xvfb-run program, instead of to the xvfb-run
  process.
  """
  def terminate(self):
    _signal_xvfb_children(self.pid, signal.SIGTERM)

  def kill(self):
    _signal_xvfb_children(self.pid, signal.SIGKILL)


def _maybe_create_line_reader(reader):
  if reader is None:
    return None
  return nonblocking_io.LineReader(reader)


def _handle_output(reader, handler):
  """Reads lines from |reader| and invoke handler for each line.

  At EOF, this closes the |reader|, and returns True.
  Otherwise, returns False.
  """
  if reader is None:
    return False

  try:
    for line in reader:
      handler(line)
  except io.BlockingIOError:
    # All available lines are read. No more line is available for now.
    return False
  else:
    reader.close()  # EOF is found.
    return True


class Popen(object):
  """Thread-safe wrapper around subprocess.Popen.

  Operations such as kill() and poll() on a normal subprocess.Popen instance
  can have races.
  This wrapper additionally supports defining a timeout after which the
  process should automatically be terminated, and supports monitoring
  the subprocess output in a non-blocking way.
  """

  # If the subprocess is not terminated even 5 secs after sending terminate(),
  # this class tries to kill().
  _SHUTDOWN_WAIT_SECONDS = 5

  def __init__(self, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               cwd=None, env=None, timeout=None, subprocess_factory=None):
    """Constructs the Popen instance.

    Unlike subprocess.Popen, this class supports only the following arguments.
    - |args|: Command line arguments. Must be a list of str. Note that
      subprocess.Popen supports str args, but it is not supported here.
    - |stdout|, |stderr|: Must be None or subprocess.PIPE.
    - |cwd|, |env|: passed through to the subprocess.Popen.
    - |timeout|: Process timeout duration in seconds. |timeout| secs after
      the process is created, terminate() is invoked. Also, handle_timeout()
      will be invoked, via handle_output(). |timeout| can be None to not
      apply a timeout.
    - subprocess_factory: factory to launch a real subprocess. It should take
      |args|, |stdout|, |stderr|, |cwd| and |env| as its arguments.
      By default (= None), the default subprocess factory is used.
    """
    assert isinstance(args, list), '|args| must be a list, %r' % (args,)
    assert stdout in (None, subprocess.PIPE), (
        'stdout for concurrent_subprocess.Popen must be None or PIPE.')
    assert stderr in (None, subprocess.PIPE, subprocess.STDOUT), (
        'stderr for concurrent_subprocess.Popen must be None, PIPE or STDOUT.')

    self._lock = threading.Lock()

    # Set True when timed out.
    self._timedout = False
    self._handle_output_invoked = False
    # Set when kill() is called.
    self._kill_event = threading.Event()

    # threading.Timer instances for timeout or terminate_later.
    # When the subprocess is poll()ed, all timers will be cancelled and
    # _timers will be set to None. See _poll_locked() for more details.
    self._timers = []

    if subprocess_factory is None:
      subprocess_factory = (
          _XvfbPopen if args[0] == 'xvfb-run' else subprocess.Popen)

    formatted_commandline = (
        logging_util.format_commandline(args, cwd=cwd, env=env))
    logging.info('Popen: %s', formatted_commandline)
    try:
      self._process = subprocess_factory(
          args, stdout=stdout, stderr=stderr, cwd=cwd, env=env)
    except Exception:
      logging.exception('Popen failed: %s', formatted_commandline)
      raise
    logging.info('Created pid %d', self._process.pid)

    # Set timeout timer, when specified.
    if timeout:
      with self._lock:
        self._start_timer_locked(timeout, self._timeout)

  def _start_timer_locked(self, interval, callback):
    """Starts the timer.

    threading.Timer is based on threading.Thread. Each Timer invocation creates
    a thread. We set it as daemon, so that even if there is pending timeout
    we can terminate the main scripts.
    For thread safety, any method that is called by a callback should acquire
    |self._lock|, and call |self._poll_locked()| to ensure the process still
    exists. If it does, it should continue performing its functionality while
    still holding the same lock.
    """
    assert self._timers is not None, (
        '_start_timer_locked() must be called while the subprocess is alive.')
    timer = threading.Timer(interval, callback)
    timer.daemon = True
    timer.start()
    self._timers.append(timer)

  @property
  def pid(self):
    return self._process.pid

  def _timeout(self):
    with self._lock:
      self._terminate_locked(is_timedout=True)

  def terminate(self):
    with self._lock:
      self._terminate_locked(is_timedout=False)

  def _terminate_locked(self, is_timedout):
    # Check if the subprocess is already terminated, just before sending
    # terminate message.
    if self._process.returncode is not None:
      return

    logging.info('Terminating process: %d', self._process.pid)
    self._process.terminate()
    # Just in case that the subprocess handles SIGTERM but it takes too
    # long (or hangs up), we send kill after a certain period.
    # This will be cancelled if the SIGTERM is handled soon.
    self._start_timer_locked(Popen._SHUTDOWN_WAIT_SECONDS, self.kill)
    if is_timedout:
      self._timedout = True

  def terminate_later(self, timeout):
    with self._lock:
      if self._process.returncode is None:
        self._start_timer_locked(timeout, self.terminate)

  def kill(self):
    with self._lock:
      if self._process.returncode is None:
        logging.info('Killing process: %d', self._process.pid)
        self._process.kill()
        signal_util.kill_recursively(self._process.pid)
        self._kill_event.set()

  def poll(self):
    with self._lock:
      return self._poll_locked()

  def _poll_locked(self):
    # This method must be called with self._lock acquired.
    result = self._process.poll()

    # If poll is successfully returned, cancel all |self._timers|.
    # Note that all |self._timers|' events should be sending a signal to the
    # subprocess.
    # Also, note that there is a case that, the timer is already fired after
    # the lock is acquired. As long as all timers invoke methods which check
    # if the subprocess is already dead before delivering the signal (both
    # under the same lock), then there is no potential race.
    if result is not None and self._timers is not None:
      for timer in self._timers:
        timer.cancel()
      self._timers = None
    return result

  def wait(self, timeout=None):
    """Wait until the subprocess is terminated with timeout.

    Returns status code, or None if timed out.
    """
    deadline = None if timeout is None else time.time() + timeout
    while True:
      # Because poll is guarded by the lock, we can just use busy-loop with
      # 0.1 secs interval (chosen heuristically).
      result = self.poll()
      if (result is not None or
          (deadline is not None and time.time() >= deadline)):
        # If subprocess is terminated or timed out, return the result.
        return result
      time.sleep(0.1)

  def handle_output(self, output_handler):
    """Reads output from the subprocess, wait()s until the termination.

    This function reads stdout and stderr (if available), and invokes
    the corresponding callback of |output_handler|.
    For each iteration, |output_handler.is_done()| is invoked. If it returns
    True, this tries to terminate the subprocess. Later, is_done() will no
    longer be called, but handle_output and handle_error will be as long as
    there is still output to be processed.
    If it is timed out, handle_timeout() is invoked, after the subprocess
    termination.
    Returns the status code.
    This method must be called at most once per instance.
    """
    with self._lock:
      assert not self._handle_output_invoked, (
          'handle_output() must be called at most once.')
      self._handle_output_invoked = True

    stdout = _maybe_create_line_reader(self._process.stdout)
    stderr = _maybe_create_line_reader(self._process.stderr)

    # Note: Exit from the loop, whenever kill() is invoked.
    # In most cases, when kill() is called, all the descendant processes should
    # be terminated immediately, and then the write-end of stdout and stderr
    # are closed, which triggers graceful shutdown of this method.
    # However, there seems some process which keeps the write-end opened,
    # so that it causes TIMEOUT flakiness in some cases.
    # To avoid such a situation, even if either stdout or stderr is still
    # available, exit from the loop. It should be ok to ignore the
    # remaining stdout and stderr, because nothing valuable should be output
    # in such cases.
    # Note that it is *not* necessary to exit from select() immediately,
    # because it is timed out on every 5 seconds, and it is ok to rely on
    # that fact, as this is last-resort.
    # Note that it does not exit from the loop on terminate(), because
    # graceful shutdown is expected for the terminate().
    done = False
    while (stdout or stderr) and not self._kill_event.is_set():
      # We do not take care about subprocess termination here, because
      # on the subprocess termination, write-side of stdout and stderr are
      # closed, so that select() should return at the time. Then,
      # stdout and stderr will reach to EOF and those are closed, so that
      # we exit from the loop.
      # Also note that, on Windows, select for non-socket FDs are not supported.
      # For such a case, we time out the loop by 5 seconds at most.
      select.select(filter(None, [stdout, stderr]), [], [], 5)
      if _handle_output(stdout, output_handler.handle_stdout):
        stdout = None
      if _handle_output(stderr, output_handler.handle_stderr):
        stderr = None
      if not done and output_handler.is_done():
        done = True
        self.terminate()

    # In case of kill() termination, stdout and stderr may be kept opened.
    # Here, close() them if necessary.
    if stdout:
      stdout.close()
    if stderr:
      stderr.close()

    # Wait for the subprocess terminate.
    returncode = self.wait()

    # Invoke handle_timeout() the process is terminated due to timeout.
    if self._timedout:
      logging.info('Process %d was timed out', self._process.pid)
      output_handler.handle_timeout()

    return output_handler.handle_terminate(returncode)


class OutputHandler(object):
  """Default (stub) definition for the handler Popen.handle_output() requires.

  This handler does almost nothing.
  """

  def handle_stdout(self, line):
    """Called when a line is output via subprocess's stdout.

    Args:
      line: A line. Note that the line has trailing LF.
    """
    pass

  def handle_stderr(self, line):
    """Called when a line is output via subprocess's stderr.

    Args:
      line: A line. Note that the line has trailing LF.
    """
    pass

  def is_done(self):
    """Returns whether we should terminate the subprocess.

    This method is called after handle_stdout() and handle_stderr().
    If returns True, the subprocess will be terminated soon, and
    this method will never be called.
    Note that, even if no line is output from subprocess, this method is
    periodically called.
    """
    # Do not terminate the subprocess, by default.
    return False

  def handle_timeout(self):
    """Called when the subprocess is timed out, after process termination.

    If |timeout| parameter is passed to Popen, the subprocess will be
    terminated at the time. In such a case, after the process is
    terminated, this method is called.
    """
    pass

  def handle_terminate(self, returncode):
    """Called at the very end of Popen.handle_output().

    This method is called at the very end of the Popen.handle_output(),
    so that it can override returncode based on the observed stdout and stderr.

    This must return the status code, which will be returned from the
    Popen.handle_output().
    """
    # Do not override the returncode, by default.
    return returncode


# Common OutputHandler implementations.
class DelegateOutputHandlerBase(OutputHandler):
  """Delegate every handler invocation to the given output handler.

  One of the common patterns of OutputHandler is doing something for
  interesting events (like stdout line, stderr line etc.), and delegating
  anything else to other OutputHandler.
  This is the base class for such purposes.
  """
  def __init__(self, base_handler):
    super(DelegateOutputHandlerBase, self).__init__()
    assert base_handler is not None
    self._base_handler = base_handler

  def handle_stdout(self, line):
    self._base_handler.handle_stdout(line)

  def handle_stderr(self, line):
    self._base_handler.handle_stderr(line)

  def is_done(self):
    return self._base_handler.is_done()

  def handle_timeout(self):
    self._base_handler.handle_timeout()

  def handle_terminate(self, returncode):
    return self._base_handler.handle_terminate(returncode)


class RedirectOutputHandler(OutputHandler):
  """Output handler to redirect stdout and stderr to sys.stdout and stderr."""

  _NUM_WRITE_RETRIES = 30

  def __init__(self, *suppress_patterns):
    """Initializes the redirect output handler.

    Args:
      *suppress_patterns: string regex of suppressing lines. If an output line
        (regardless stdout or stderr) matches one of them, the line will not
        be redirected to the stdout or stderr (respectively).
    """
    super(RedirectOutputHandler, self).__init__()
    self._suppress_pattern = (
        re.compile('|'.join(suppress_patterns)) if suppress_patterns else None)

  def handle_stdout(self, line):
    if not self._is_suppress_target(line):
      for attempt in range(RedirectOutputHandler._NUM_WRITE_RETRIES):
        try:
          sys.stdout.write(line)
          return
        except IOError as e:
          if e.errno == 11:
            # Retry on resource temporarily unavailable.
            time.sleep(0.1)
          else:
            raise
      raise Exception('Could not write to sys.stdout')

  def handle_stderr(self, line):
    if not self._is_suppress_target(line):
      for attempt in range(RedirectOutputHandler._NUM_WRITE_RETRIES):
        try:
          sys.stderr.write(line)
          return
        except IOError as e:
          if e.errno == 11:
            # Retry on resource temporarily unavailable.
            time.sleep(0.1)
          else:
            raise
      raise Exception('Could not write to sys.stderr')

  def _is_suppress_target(self, line):
    return self._suppress_pattern and self._suppress_pattern.match(line)
