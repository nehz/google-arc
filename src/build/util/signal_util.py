# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import atexit
import logging
import os
import signal
import subprocess
import sys

from util import debug
from util import platform_util


def _list_child_process(*target_pid):
  """Returns a list of PIDs whose parent PID is |target_pid|."""
  if platform_util.is_running_on_linux():
    # On Linux Workstation or Chrome OS.
    try:
      output = subprocess.check_output(
          ['ps', '-o', 'pid=', '--ppid', ','.join(str(p) for p in target_pid)])
    except subprocess.CalledProcessError:
      # If not found, ps returns status code 1.
      return []
    return [int(child.strip()) for child in output.splitlines()]

  if platform_util.is_running_on_mac():
    # On Mac.
    try:
      output = subprocess.check_output(['ps', 'x', '-o', 'pid=,ppid='])
    except subprocess.CalledProcessError:
      return []
    result = []
    for line in output.splitlines():
      pid, ppid = line.split()
      if int(ppid) in target_pid:
        result.append(int(pid))
    return result

  if platform_util.is_running_on_cygwin():
    # On Cygwin.
    try:
      output = subprocess.check_output(['ps', 'aux'])
    except subprocess.CalledProcessError:
      return []
    result = []
    for line in output.splitlines()[1:]:
      pid, ppid = line.split(None, 2)[:2]
      if int(ppid) in target_pid:
        result.append(int(pid))
    return result
  raise NotImplementedError('Unknown platform: ' + sys.platform)


def _terminate_subprocess():
  """Terminates all the direct subprocesses by sending SIGTERM."""
  for pid in _list_child_process(os.getpid()):
    try:
      os.kill(pid, signal.SIGTERM)
    except Exception:
      # Ignore any exception here.
      pass


def _sigterm_handler(signum, frame):
  """Signal handler for the SIGTERM."""
  # First of all, on TERMINATE, print the stacktrace.
  assert signum == signal.SIGTERM
  logging.error('SIGTERM is recieved.')
  debug.write_frames(sys.stderr)

  # If we can send SIGTERM to child processes, we do not exit here,
  # with expecting the graceful shutdown.
  # Note that, although we do this in atexit handler, too, it is too late
  # (runs after all threads are terminated). So we need it here.
  # Note that, to avoid race conditions, the program must not poll or wait
  # on a non-main thread. Practically, it is almost safe, but there is
  # a small chance for un-related processes to be killed by SIGTERM
  # accidentally.
  _terminate_subprocess()

  # Then, terminate the script. Note that at the end of the interpreter,
  # functions registered by atexit.register() will run.
  sys.exit(1)


def setup():
  """Sets up SIGTERM's handler and registers a atexit handler.

  This function should be called very early stage of the script.
  On SIGTERM, the installed handler does following three things:
  - Prints the stack trace.
  - Sends SIGTERM to direct child processes (if exist).
  - Raises SystemExit(1) exception to terminate the script with running
    atexit registered functions.

  At exit, the installed callback sends SIGTERM to direct child
  processes (if exist).
  """
  signal.signal(signal.SIGTERM, _sigterm_handler)

  # At the end of the program, we terminates known subprocesses.
  # Note that, when this is fired, we assume there is no thread other than
  # main, and also main thread is being terminated. So, no one wait()'s the
  # subprocesses.
  atexit.register(_terminate_subprocess)


def kill_recursively(root_pid):
  """Sends SIGKILL to the |root_pid| process and its descendants.

  While this function is running, killed processes must not be wait()ed,
  specifically root. Otherwise, it may kill un-related processes.
  Here is an example scenario;
  1) Let be a process tree as follows:
    this process - process A[root_pid] - process B[pid1].
  2) Send SIGKILL to process A, and it terminates immediately.
  3) Here, root process is wait()ed, wrongly, so that |root_pid| can be
    reused by any new process.
  4) Before A's children is listed (in more precise, children of a process
    with |root_pid| are listed), a new process is created and |root_pid| is
    reassigned. (Note: this should be practically very rare, because in common
    system, PID is assigned in round-robin way. Thus, so many processes need
    to be created in this very short period.)
  5) The new process creates its child, named process C[pid2].
  6) List the children of |root_pid|, which is process C[pid2], not
    process B[pid1].
  7) Then, send SIGKILL to process C[pid2], wrongly.
  Note that this PID-reused problem can happen any level of the process tree.

  Args:
    root_pid: PID of the root process of the target process tree.
  """
  pid_list = [root_pid]
  while pid_list:
    for pid in pid_list:
      os.kill(pid, signal.SIGKILL)
    pid_list = _list_child_process(*pid_list)
