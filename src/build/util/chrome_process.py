# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time
import os
import subprocess

from util import concurrent_subprocess
from util import file_util
from util import platform_util


class ChromeProcess(concurrent_subprocess.Popen):
  def __init__(self, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               cwd=None, env=None, timeout=None):
    # To stabilize the Chrome flakiness problem handling, we use customized
    # Popen for Chrome. Note that we do not need to worry about the xvfb-run
    # as we do in concurrent_subprocess._XvfbPopen, because we are launching
    # Chrome process, here.
    if platform_util.is_running_on_cygwin():
      # To launch on Cygwin, stdout and stderr for NaCl are not yet supported.
      # We instead use a customized Popen class. See its doc for the details.
      # TODO(crbug.com/171836): Remove this when stdout and stderr are
      # supported.
      subprocess_factory = _TailProxyChromePopen
    else:
      subprocess_factory = None
    super(ChromeProcess, self).__init__(
        args=args, stdout=stdout, stderr=stderr, cwd=cwd, env=env,
        timeout=timeout, subprocess_factory=subprocess_factory)


def _maybe_create_output_file(output, prefix):
  """Creates a temporary file if |output| is PIPE."""
  if output != subprocess.PIPE:
    return None
  return file_util.create_tempfile_deleted_at_exit(prefix=prefix)


def _maybe_wait_for_file_created(path):
  """Waits until a file is created at |path|."""
  if not path:
    # Do nothing.
    return
  while not os.path.exists(path):
    time.sleep(0.1)


def _maybe_popen_tail(path_list, pid):
  """Launches a 'tail' observing files at |path_list|.

  |path_list| can contain None. None will be just ignored.
  If no path is specified (except None), 'tail' will not be launched and
  returns None.
  The created process will die when the process with |pid| dies.
  """
  path_list = filter(None, path_list)
  if not path_list:
    return None
  # Note, for our use case, --pid may not enough. E.g., if the main program
  # (here, Chrome) terminates unexpectedly, like SIGSEGV, but not yet poll()ed,
  # then, tail will *not* be terminated at the moment, so that stdout and stderr
  # will not be closed.
  # Assuming that the usage is limited (only in ./launch_chrome on Cygwin), we
  # ignore it for now. Note that terminate() or kill() to the main program via
  # _TailProxyChromePopen should properly work.
  return subprocess.Popen(
      ['tail', '-n', '+1', '--pid', str(pid), '-f'] + path_list,
      stdout=subprocess.PIPE)


def _maybe_terminate(process):
  """Sends terminate() if the |process| is alive."""
  if process and process.poll() is None:
    process.terminate()


def _maybe_kill(process):
  """Sends kill() if the |process| is alive."""
  if process and process.poll() is None:
    process.kill()


def _maybe_poll(process):
  """Runs poll() if available."""
  if process:
    process.poll()


class _TailProxyChromePopen(subprocess.Popen):
  """Customized Popen to read NaCl's stdout and stderr via "tail -f".

  Currently, on Windows, stdout and stderr are not inherited to the
  subprocesses, so we cannot use subprocess.PIPE to read the logs from
  NaCl processes.
  Instead, here we redirect them to each file, and use "tail -f".
  To merge the log from NaCl and Chrome into one stream, we also redirect
  stdout and stderr of Chrome to temporary files and pass them to tail, too.
  So that the outputs from both Chrome and NaCl are filtered by the
  output handler.
  """

  def __init__(self, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               cwd=None, env=None):
    assert stdout in (None, subprocess.PIPE), (
        'stdout for _TailProxyChromePopen must be None or PIPE.')
    assert stderr in (None, subprocess.PIPE, subprocess.STDOUT), (
        'stderr for _TailProxyChromePopen must be None, PIPE or STDOUT.')

    chrome_stdout = _maybe_create_output_file(stdout, 'Chrome-stdout')
    chrome_stderr = _maybe_create_output_file(stderr, 'Chrome-stderr')
    if env is None:
      env = os.environ.copy()
    super(_TailProxyChromePopen, self).__init__(
        args, stdout=chrome_stdout,
        # If |chrome_stderr| is None, stderr is either None or STDOUT.
        stderr=chrome_stderr or stderr,
        cwd=cwd, env=env)

    nacl_stdout_path = stdout and env.get('NACL_EXE_STDOUT')
    nacl_stderr_path = stderr and env.get('NACL_EXE_STDERR')
    _maybe_wait_for_file_created(nacl_stdout_path)
    _maybe_wait_for_file_created(nacl_stderr_path)

    # Launch tail subprocesses.
    stdout_path_list = [getattr(chrome_stdout, 'name', None), nacl_stdout_path]
    stderr_path_list = [getattr(chrome_stderr, 'name', None), nacl_stderr_path]
    if stderr == subprocess.STDOUT:
      # Even if stderr == subprocess.STDOUT but stdout is None, the output
      # from stderr will be just ignored.
      if stdout:
        stdout_path_list += stderr_path_list
      stderr_path_list = []
    self._tail_stdout_process = _maybe_popen_tail(stdout_path_list, self.pid)
    self._tail_stderr_process = _maybe_popen_tail(stderr_path_list, self.pid)

    # Set stdout and stderr streams.
    self.stdout = getattr(self._tail_stdout_process, 'stdout', None)
    self.stderr = getattr(self._tail_stderr_process, 'stdout', None)

  def terminate(self):
    _maybe_terminate(self._tail_stdout_process)
    _maybe_terminate(self._tail_stderr_process)
    super(_TailProxyChromePopen, self).terminate()

  def kill(self):
    _maybe_kill(self._tail_stdout_process)
    _maybe_kill(self._tail_stderr_process)
    super(_TailProxyChromePopen, self).kill()

  def poll(self):
    _maybe_poll(self._tail_stdout_process)
    _maybe_poll(self._tail_stderr_process)
    return super(_TailProxyChromePopen, self).poll()

  def wait(self):
    # From concurrent_subprocess.Popen, wait() should not be called.
    raise NotImplementedError('_TailProxyChromePopen does not support wait().')
