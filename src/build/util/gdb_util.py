# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import logging
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

import build_common
import toolchain
from build_options import OPTIONS
from util import concurrent_subprocess
from util import file_util
from util import platform_util


# Note: DISPLAY may be overwritten in the main() of launch_chrome.py.
__DISPLAY = os.getenv('DISPLAY')

# Bare metal GDB will wait at port (_BARE_METAL_GDB_PORT_BASE + pid).
# This value must be small enough to allow all possible PIDs to map to a
# valid TCP port. Linux's PID_MAX_DEFAULT is 32768.
_BARE_METAL_GDB_PORT_BASE = 10000

# The Bionic loader has a MOD for Bare Metal mode so that it waits GDB
# to attach the process if this directory exists. See maybe_wait_gdb_attach
# in bionic/linker/linker.cpp.
_BARE_METAL_GDB_LOCK_DIR = '/tmp/bare_metal_gdb'

_LOCAL_HOST = '127.0.0.1'

# The default password of Chrome OS test images.
_CROS_TEST_PASSWORD = 'test0000'

# Pretty printers for STLport.
_STLPORT_PRINTERS_PATH = ('third_party/android/ndk/sources/host-tools/'
                          'gdb-pretty-printers/stlport/gppfs-0.2')


def _wait_by_busy_loop(func, interval=0.1):
  """Repeatedly calls func() until func returns value evaluated to true."""
  while True:
    result = func()
    if result:
      return result
    time.sleep(interval)


def _create_command_file(command):
  # After gdb is finished, we expect SIGINT is sent to this process.
  command = command + [';', 'kill', '-INT', str(os.getpid())]

  with file_util.create_tempfile_deleted_at_exit(
      prefix='arc-gdb-', suffix='.sh') as command_file:
    # Escape by wrapping double-quotes if an argument contains a white space.
    command_file.write(' '.join(
        '"%s"' % arg if ' ' in arg else arg for arg in command))
  os.chmod(command_file.name, stat.S_IRWXU)
  return command_file


def _get_bare_metal_gdb_port(plugin_pid):
  return _BARE_METAL_GDB_PORT_BASE + plugin_pid


def maybe_launch_gdb(gdb_target_list, gdb_type, chrome_pid):
  """Launches the gdb command if necessary.

  It is expected for this method to be called right after chrome is launched.
  """
  if 'browser' in gdb_target_list:
    _launch_gdb('browser', str(chrome_pid), gdb_type)


def _get_xterm_gdb(title, gdb, extra_argv):
  return ['xterm',
          '-display', __DISPLAY,
          '-title', title, '-e',
          gdb, '--tui',  # Run gdb with text UI mode.
          '--tty', os.ttyname(sys.stdin.fileno()),
          '-ex', 'set use-deprecated-index-sections on'] + extra_argv


def _get_screen_gdb(title, gdb, extra_argv):
  return ['screen',
          '-t', title,
          gdb,
          '--tty', os.ttyname(sys.stdin.fileno()),
          '-ex', 'set use-deprecated-index-sections on'] + extra_argv


def _get_emacsclient_gdb(title, gdb, extra_argv):
  command = [gdb,
             # First parameter gets used as the buffer name and current
             # directory. Make it somewhat unique non-directory name.
             '-ex', 'echo %s' % title,
             '-ex', 'set use-deprecated-index-sections on'] + extra_argv
  # Emacs lisp instruction sent through emacsclient, needs to have " escaped.
  elisp = '(gud-gdb "%s")' % (
      subprocess.list2cmdline(command).replace('"', '\\"'))
  return ['emacsclient',
          '-e', elisp]


def _run_gdb_watch_thread(gdb_process):
  def _thread_callback():
    gdb_process.wait()
    # When the gdb is terminated, kill myself.
    os.kill(os.getpid(), signal.SIGINT)
  thread = threading.Thread(target=_thread_callback)
  thread.daemon = True
  thread.start()


def _launch_gdb(title, pid_string, gdb_type):
  """Launches GDB for a non-plugin process."""
  host_gdb = toolchain.get_tool('host', 'gdb')
  command = ['-p', pid_string]
  if title in ('gpu', 'renderer'):
    command.extend(['-ex', r'echo To start: signal SIGUSR1\n'])
  if gdb_type == 'xterm':
    command = _get_xterm_gdb(title, host_gdb, command)
  elif gdb_type == 'screen':
    command = _get_screen_gdb(title, host_gdb, command)
  elif gdb_type == 'emacsclient':
    command = _get_emacsclient_gdb(title, host_gdb, command)
  gdb_process = subprocess.Popen(command)

  if gdb_type == 'xterm':
    _run_gdb_watch_thread(gdb_process)


def _launch_plugin_gdb(gdb_args, gdb_type):
  """Launches GDB for a plugin process."""
  gdb = toolchain.get_tool(OPTIONS.target(), 'gdb')
  if gdb_type == 'xterm':
    # For "xterm" mode, just run the gdb process.
    command = _get_xterm_gdb('plugin', gdb, gdb_args)
    subprocess.Popen(command)
  elif gdb_type == 'screen':
    command = _get_screen_gdb('plugin', gdb, gdb_args)
    subprocess.Popen(command)
    print '''

=====================================================================

Now gdb should be running in another screen. Set breakpoints as you
like and start debugging by

(gdb) continue

=====================================================================
'''
  elif gdb_type == 'emacsclient':
    command = _get_emacsclient_gdb('plugin', gdb, gdb_args)
    subprocess.Popen(command)
    print '''

=====================================================================

Now gdb should be running in your emacs session. Set breakpoints as you
like and start debugging by

(gdb) continue

=====================================================================
'''
  else:
    # For "wait" mode, we create a shell script and let the user know.
    command_file = _create_command_file([gdb] + gdb_args)
    print '''

=====================================================================

Now you can attach GDB. Run the following command in another shell.

$ cd /path/to/arc
$ sh %s

Then, set breakpoints as you like and start debugging by

(gdb) continue

=====================================================================

''' % command_file.name


def get_gdb_python_init_args():
  """Builds gdb arguments to initialize Python interpreter.

  These arguments must be inserted before any argument built by
  get_gdb_python_script_init_args().

  Returns:
    A list of gdb argument strings.
  """
  return [
      '-ex',
      'python sys.path.insert(0, %r)' %
      os.path.abspath('src/build/util/gdb_scripts'),
  ]


def get_gdb_python_script_init_args(script_name, **kwargs):
  """Builds gdb arguments to load and init a given gdb script.

  gdb scripts are all located under src/build/util/gdb_scripts.

  Args:
    script_name: Basename of the gdb script to be loaded.
    **kwargs: Arguments passed to init() in the gdb script.

  Returns:
    A list of gdb argument strings.
  """
  return [
      '-ex', 'python import %s' % script_name,
      '-ex',
      'python %s.init(%s)' % (
          script_name,
          ', '.join('%s=%r' % item for item in kwargs.iteritems())),
  ]


def _launch_nacl_gdb(gdb_type, nacl_irt_path, port):
  nmf = os.path.join(build_common.get_runtime_out_dir(),
                     'arc_' + OPTIONS.target() + '.nmf')
  assert os.path.exists(nmf), (
      nmf + ' not found, you will have a bad time debugging')

  # TODO(nativeclient:3739): We explicitly specify the path of
  # runnable-ld.so to work-around the issue in nacl-gdb, but we should
  # let nacl-gdb find the path from NMF.
  gdb_args = ['-ex', 'nacl-manifest %s' % nmf]
  if nacl_irt_path:
    gdb_args.extend(['-ex', 'nacl-irt %s' % nacl_irt_path])
  gdb_args.extend(['-ex', 'target remote %s:%s' % (_LOCAL_HOST, port),
                   build_common.get_bionic_runnable_ld_so()])
  _launch_plugin_gdb(gdb_args, gdb_type)


def _attach_bare_metal_gdb(
    remote_address, plugin_pid, ssh_options, nacl_helper_binary, gdb_type):
  """Attaches to the gdbserver, running locally or port-forwarded.

  If |remote_address| is set, it is used for ssh.
  """
  gdb_port = _get_bare_metal_gdb_port(plugin_pid)

  # Before launching 'gdb', we wait for that the target port is opened.
  _wait_by_busy_loop(
      lambda: _is_remote_port_open(_LOCAL_HOST, gdb_port))

  gdb_args = []
  if nacl_helper_binary:
    gdb_args.append(nacl_helper_binary)
    # TODO(crbug.com/376666): Remove this once newlib-switch is done. The
    # new loader is always statically linked and does not need this trick.
    gdb_args.extend(['-ex', 'set solib-search-path %s' % os.path.dirname(
        nacl_helper_binary)])
  gdb_args.extend([
      '-ex', 'target remote %s:%d' % (_LOCAL_HOST, gdb_port)])

  gdb_args.extend(get_gdb_python_init_args())

  library_path = os.path.abspath(build_common.get_load_library_path())
  gdb_args.extend(get_gdb_python_script_init_args(
      'bare_metal_support',
      arc_nexe=os.path.join(
          library_path,
          os.path.basename(build_common.get_runtime_main_nexe())),
      library_path=library_path,
      runnable_ld_path=os.path.join(library_path, 'runnable-ld.so'),
      lock_file=os.path.join(_BARE_METAL_GDB_LOCK_DIR, str(plugin_pid)),
      remote_address=remote_address,
      ssh_options=ssh_options))

  gdb_args.extend(['-ex', r'echo To start: c or cont\n'])

  _launch_plugin_gdb(gdb_args, gdb_type)


def _is_remote_port_open(remote_address, port):
  with contextlib.closing(socket.socket()) as sock:
    sock.settimeout(2)
    return sock.connect_ex((remote_address, port)) == 0


def _launch_bare_metal_gdbserver(plugin_pid, is_child_plugin):
  gdb_port = _get_bare_metal_gdb_port(plugin_pid)
  command = ['gdbserver', '--attach', ':%d' % gdb_port, str(plugin_pid)]

  if platform_util.is_running_on_chromeos():
    gdb_process = _popen_with_sudo_on_chromeos(command)
  else:
    gdb_process = subprocess.Popen(command)

  if not is_child_plugin:
    _run_gdb_watch_thread(gdb_process)


def _popen_with_sudo_on_chromeos(command):
  p = subprocess.Popen(['sudo', '-S'] + command, stdin=subprocess.PIPE)
  p.stdin.write(_CROS_TEST_PASSWORD + '\n')
  return p


def _check_call_with_sudo_on_chromeos(command):
  p = _popen_with_sudo_on_chromeos(command)
  retcode = p.wait()
  if retcode:
    raise subprocess.CalledProcessError(retcode, ' '.join(command))


def create_or_remove_bare_metal_gdb_lock_dir(gdb_target_list):
  file_util.rmtree(_BARE_METAL_GDB_LOCK_DIR, ignore_errors=True)
  if 'plugin' in gdb_target_list and OPTIONS.is_bare_metal_build():
    file_util.makedirs_safely(_BARE_METAL_GDB_LOCK_DIR)


def is_no_sandbox_needed(gdb_target_list):
  """Returns whether --no-sandbox is needed to run Chrome with GDB properly.
  """
  # Chrome uses getpid() to print the PID of the renderer/gpu process to be
  # debugged, which is parsed by launch_chrome.  If the sandbox is enabled,
  # fake PIDs are returned from getpid().
  if 'renderer' in gdb_target_list or 'gpu' in gdb_target_list:
    return True

  # To suspend at the very beginning of the loader, we use a lock file.
  # no-sandox option is necessary to access the file.
  # TODO(crbug.com/354290): Remove this when GDB is properly supported.
  if OPTIONS.is_bare_metal_build() and 'plugin' in gdb_target_list:
    return True

  return False


def get_args_for_stlport_pretty_printers():
  # Disable the system wide gdbinit which may contain pretty printers for
  # other STL libraries such as libstdc++.
  gdb_args = ['-nx']

  # However, -nx also disables ~/.gdbinit. Adds it back if the file exists.
  if os.getenv('HOME'):
    user_gdb_init = os.path.join(os.getenv('HOME'), '.gdbinit')
    if os.path.exists(user_gdb_init):
      gdb_args.extend(['-x', user_gdb_init])

  # Load pretty printers for STLport.
  gdb_args.extend([
      '-ex', 'python sys.path.insert(0, "%s")' % _STLPORT_PRINTERS_PATH,
      '-ex', 'python import stlport.printers',
      '-ex', 'python stlport.printers.register_stlport_printers(None)'])

  return gdb_args


class GdbHandlerAdapter(concurrent_subprocess.DelegateOutputHandlerBase):
  _START_DIALOG_PATTERN = re.compile(r'(Gpu|Renderer) \((\d+)\) paused')

  def __init__(self, base_handler, target_list, gdb_type):
    super(GdbHandlerAdapter, self).__init__(base_handler)
    assert target_list, 'No GDB target is specified.'
    self._target_list = target_list
    self._gdb_type = gdb_type

  def handle_stderr(self, line):
    super(GdbHandlerAdapter, self).handle_stderr(line)

    match = GdbHandlerAdapter._START_DIALOG_PATTERN.search(line)
    if not match:
      return

    process_type = match.group(1).lower()
    if process_type not in self._target_list:
      logging.error('%s process startup dialog found, but not a gdb target' %
                    process_type)
      return
    pid = match.group(2)
    logging.info('Found %s process (%s)' % (process_type, pid))
    _launch_gdb(process_type, pid, self._gdb_type)


class NaClGdbHandlerAdapter(concurrent_subprocess.DelegateOutputHandlerBase):
  _START_DEBUG_STUB_PATTERN = re.compile(r'debug stub on port (\d+)')

  def __init__(
      self, base_handler, nacl_irt_path, gdb_type, remote_executor=None):
    super(NaClGdbHandlerAdapter, self).__init__(base_handler)
    self._nacl_irt_path = nacl_irt_path
    self._gdb_type = gdb_type
    self._remote_executor = remote_executor

  def handle_stderr(self, line):
    super(NaClGdbHandlerAdapter, self).handle_stderr(line)

    match = NaClGdbHandlerAdapter._START_DEBUG_STUB_PATTERN.search(line)
    if not match:
      return

    port = int(match.group(1))
    # Note that, for remote debugging, NaClGdbHandlerAdapter will run in
    # both local and remote machine.
    if not platform_util.is_running_on_chromeos():
      logging.info('Found debug stub on port (%d)' % port)
      if self._remote_executor:
        self._remote_executor.port_forward(port)
      _launch_nacl_gdb(self._gdb_type, self._nacl_irt_path, port)


class BareMetalGdbHandlerAdapter(
    concurrent_subprocess.DelegateOutputHandlerBase):
  # This pattern must be in sync with the message in
  # mods/android/bionic/linker/linker.cpp.
  _WAITING_GDB_PATTERN = re.compile(r'linker: waiting for gdb \((\d+)\)')

  def __init__(self, base_handler, nacl_helper_path, gdb_type, host=None,
               ssh_options=None, remote_executor=None):
    super(BareMetalGdbHandlerAdapter, self).__init__(base_handler)
    self._nacl_helper_path = nacl_helper_path
    self._gdb_type = gdb_type
    self._host = host
    self._ssh_options = ssh_options
    self._next_is_child_plugin = False
    self._remote_executor = remote_executor

  def handle_stderr(self, line):
    super(BareMetalGdbHandlerAdapter, self).handle_stderr(line)

    match = BareMetalGdbHandlerAdapter._WAITING_GDB_PATTERN.search(line)
    if not match:
      return

    plugin_pid = int(match.group(1))

    # Note that, for remote debugging, BareMetalGdbHandlerAdapter will run in
    # both local and remote machine.
    if platform_util.is_running_on_chromeos():
      _launch_bare_metal_gdbserver(plugin_pid, self._next_is_child_plugin)
    else:
      logging.info('Found new %s plugin process %d',
                   'child' if self._next_is_child_plugin else 'main',
                   plugin_pid)
      if self._remote_executor:
        self._remote_executor.port_forward(_get_bare_metal_gdb_port(plugin_pid))
      else:
        _launch_bare_metal_gdbserver(plugin_pid, self._next_is_child_plugin)
      _attach_bare_metal_gdb(
          self._host, plugin_pid, self._ssh_options, self._nacl_helper_path,
          self._gdb_type)

    self._next_is_child_plugin = True
