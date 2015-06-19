# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Provides basic utilities to implement remote-host-execution of
# launch_chrome, run_integration_tests, and run_unittests.py on Chrome OS,
# Windows (Cygwin), and Mac.

import atexit
import glob
import logging
import os
import pipes
import shutil
import subprocess
import tempfile

import build_common
import toolchain
from build_options import OPTIONS
from util import concurrent_subprocess
from util import file_util
from util import gdb_util
from util import jdb_util
from util import logging_util
from util.minidump_filter import MinidumpFilter
from util.test import unittest_util

RUN_UNIT_TEST = 'src/build/run_unittest.py'
SYNC_ADB = 'src/build/sync_adb.py'
SYNC_CHROME = 'src/build/sync_chrome.py'
SYNC_ANDROID_SDK_BUILD_TOOLS = 'src/build/sync_android_sdk_build_tools.py'

_TEST_SSH_KEY = ('third_party/tools/crosutils/mod_for_test_scripts/ssh_keys/'
                 'testing_rsa')

# Following lists contain files or directories to be copied to the remote host.
_COMMON_FILE_PATTERNS = ['out/configure.options',
                         'src/build',
                         'third_party/tools/ninja/misc',
                         _TEST_SSH_KEY]
_LAUNCH_CHROME_FILE_PATTERNS = ['launch_chrome',
                                'out/target/%(target)s/runtime',
                                build_common.get_arc_welder_unpacked_dir(),
                                'src/packaging']
_INTEGRATION_TEST_FILE_PATTERNS = [
    'mods/android/dalvik/tests',
    'out/data_roots/art.*',
    'out/data_roots/arc.*',
    'out/data_roots/cts.*',
    'out/data_roots/graphics.*',
    'out/data_roots/jstests.*',
    'out/data_roots/ndk.*',
    'out/data_roots/system_mode.*',
    'out/staging/android/art/test/*/expected.txt',
    # The following two files are needed only for 901-perf test.
    'out/staging/android/art/test/901-perf/README.benchmark',
    'out/staging/android/art/test/901-perf/test_cases',
    'out/target/%(target)s/integration_tests',
    'out/target/%(target)s/root/system/usr/icu/icudt48l.dat',
    'out/target/common/art_tests/*/expected.txt',
    'out/target/common/art_tests/*/*.jar',
    'out/target/common/integration_test/*',
    # TODO(crbug.com/340594): Avoid checking for APK files when CRX is
    # already generated so that we don't need to send APK to remote,
    # for package.apk, HelloAndroid.apk, glowhockey.apk, and
    # perf_tests_codec.apk
    'out/target/common/obj/APPS/HelloAndroid_intermediates/HelloAndroid.apk',
    'out/target/common/obj/APPS/ndk_translation_tests_intermediates/work/libs/*',  # NOQA
    'out/target/common/obj/APPS/perf_tests_codec_intermediates/perf_tests_codec.apk',  # NOQA
    'out/target/common/obj/JAVA_LIBRARIES/uiautomator.*/javalib.jar',
    'out/target/common/vmHostTests',
    'out/third_party_apks/*',
    'out/tools/apk_to_crx.py',
    'run_integration_tests',
    'src/integration_tests',
    'third_party/android-cts/android-cts/repository/plans/CTS.xml',
    'third_party/android-cts/android-cts/repository/testcases/bionic-unit-tests-cts32',  # NOQA
    'third_party/android-cts/android-cts/repository/testcases/*.xml',
    'third_party/android-cts/android-cts/repository/testcases/CtsUiAutomator*',
    # Java files are needed by VMHostTestRunner, which parses java files to
    # obtain the information of the test methods at testing time.
    'third_party/android/cts/tools/vm-tests-tf/src/dot/junit/format/*/*.java',
    'third_party/android/cts/tools/vm-tests-tf/src/dot/junit/opcodes/*/*.java',
    'third_party/android/cts/tools/vm-tests-tf/src/dot/junit/verify/*/*.java',
    'third_party/examples/apk/*/*.apk',
    'third_party/ndk/sources/cxx-stl/stlport/libs/armeabi-v7a/libstlport_shared.so']  # NOQA
_UNIT_TEST_FILE_PATTERNS = [
    # These two files are used by stlport_unittest
    'out/target/%(target)s/intermediates/stlport_unittest/test_file.txt',  # NOQA
    'out/target/%(target)s/intermediates/stlport_unittest/win32_file_format.tmp',  # NOQA
    'out/target/%(target)s/lib',
    'out/target/%(target)s/posix_translation_fs_images/test_readonly_fs_image.img',  # NOQA
    'out/target/%(target)s/root/system/framework/art-gtest-*.jar',
    'out/target/%(target)s/root/system/framework/core-libart.jar',
    # Used by posix_translation_test
    'out/target/%(target)s/runtime/_platform_specific/*/readonly_fs_image.img',  # NOQA
    'out/target/%(target)s/test',
    'out/target/%(target)s/unittest_info']

# Flags to remove when launching Chrome on remote host.
_REMOTE_FLAGS = ['--nacl-helper-binary', '--remote', '--ssh-key']


_TEMP_DIR = None
_TEMP_KEY = 'temp_arc_key'
_TEMP_KNOWN_HOSTS = 'temp_arc_known_hosts'
# File name pattern used for ssh connection sharing (%r: remote login name,
# %h: host name, and %p: port). See man ssh_config for the detail.
_TEMP_SSH_CONTROL_PATH = 'ssh-%r@%h:%p'
_TEMP_REMOTE_BINARIES_DIR = 'remote_bin'


def _get_temp_dir():
  global _TEMP_DIR
  if not _TEMP_DIR:
    _TEMP_DIR = tempfile.mkdtemp(prefix='arc_')
    atexit.register(lambda: file_util.rmtree_with_retries(_TEMP_DIR))
  return _TEMP_DIR


def _get_ssh_key():
  return os.path.join(_get_temp_dir(), _TEMP_KEY)


def _get_original_ssh_key():
  return os.path.join(build_common.get_arc_root(), _TEST_SSH_KEY)


def _get_known_hosts():
  return os.path.join(_get_temp_dir(), _TEMP_KNOWN_HOSTS)


def _get_ssh_control_path():
  return os.path.join(_get_temp_dir(), _TEMP_SSH_CONTROL_PATH)


def get_remote_binaries_dir():
  """Gets a directory for storing remote binaries like nacl_helper."""
  path = os.path.join(_get_temp_dir(), _TEMP_REMOTE_BINARIES_DIR)
  file_util.makedirs_safely(path)
  return path


class RemoteExecutor(object):
  def __init__(self, user, remote, remote_env=None, ssh_key=None,
               enable_pseudo_tty=False, attach_nacl_gdb_type=None,
               nacl_helper_binary=None, arc_dir_name=None,
               jdb_port=None, jdb_type=None):
    self._user = user
    self._remote_env = remote_env or {}
    if not ssh_key:
      # Copy the default ssh key and change the permissions. Otherwise ssh
      # refuses the key by saying permissions are too open.
      ssh_key = _get_ssh_key()
      if not os.path.exists(ssh_key):
        shutil.copyfile(_get_original_ssh_key(), ssh_key)
        os.chmod(ssh_key, 0400)
    self._ssh_key = ssh_key
    # Use a temporary known_hosts file
    self._known_hosts = _get_known_hosts()
    self._enable_pseudo_tty = enable_pseudo_tty
    self._attach_nacl_gdb_type = attach_nacl_gdb_type
    self._nacl_helper_binary = nacl_helper_binary
    self._arc_dir_name = arc_dir_name or 'arc'
    self._jdb_port = jdb_port
    self._jdb_type = jdb_type
    if ':' in remote:
      self._remote, self._port = remote.split(':')
    else:
      self._remote = remote
      self._port = None
    # Terminates the Control process at exit, explicitly. Otherwise,
    # in some cases, the process keeps the stdout/stderr open so that
    # wrapper scripts (especially interleaved_perftest.py) are confused and
    # think that this process is still alive.
    # Suppress the warning with -q as the control path does not exist when the
    # script exits normally.
    atexit_command = ['ssh', '%s@%s' % (self._user, self._remote),
                      '-o', 'ControlPath=%s' % _get_ssh_control_path(),
                      '-O', 'exit', '-q']
    if self._port:
      atexit_command.extend(['-p', self._port])
    atexit.register(subprocess.call, atexit_command)

  def copy_remote_files(self, remote_files, local_dir):
    """Copies files from the remote host."""
    scp = ['scp'] + self._build_shared_command_options(port_option='-P')
    assert remote_files
    remote_file_pattern = ','.join(remote_files)
    # scp does not accept {single_file}, so we should add the brackets
    # only when multiple remote files are specified.
    if len(remote_files) > 1:
      remote_file_pattern = '{%s}' % remote_file_pattern
    scp.append('%s@%s:%s' % (self._user, self._remote, remote_file_pattern))
    scp.append(local_dir)
    _run_command(subprocess.check_call, scp)

  def set_enable_pseudo_tty(self, enabled):
    original_value = self._enable_pseudo_tty
    self._enable_pseudo_tty = enabled
    return original_value

  def get_remote_tmpdir(self):
    """Returns the path used as a temporary directory on the remote host."""
    return self._remote_env.get('TMPDIR', '/tmp')

  def get_remote_arc_root(self):
    """Returns the arc root path on the remote host."""
    return os.path.join(self.get_remote_tmpdir(), self._arc_dir_name)

  def get_remote_env(self):
    """Returns the environmental variables for the remote host."""
    return ' '.join(
        '%s=%s' % (k, v) for (k, v) in self._remote_env.iteritems())

  def get_ssh_options(self):
    """Returns the list of options used for ssh in the runner."""
    return self._build_shared_ssh_command_options()

  def rsync(self, local_src, remote_dst):
    """Runs rsync command to copy files to remote host."""
    # For rsync, the order of pattern is important.
    # First, add exclude patterns to ignore common editor temporary files, and
    # .pyc files.
    # Second, add all paths to be copied.
    # Finally, add exclude '*', in order not to copy any other files.
    pattern_list = []
    for pattern in build_common.COMMON_EDITOR_TMP_FILE_PATTERNS:
      pattern_list.extend(['--exclude', pattern])
    pattern_list.extend(['--exclude', '*.pyc'])
    for path in self._build_rsync_include_pattern_list(local_src):
      pattern_list.extend(['--include', path])
    pattern_list.extend(['--exclude', '*'])

    rsync_options = [
        # The remote files need to be writable and executable by chronos. This
        # option sets read, write, and execute permissions to all users.
        '--chmod=a=rwx',
        '--compress',
        '--copy-links',
        '--delete',
        '--inplace',
        '--perms',
        '--progress',
        '--recursive',
        '--rsh=' + ' '.join(['ssh'] + self._build_shared_ssh_command_options()),
        '--times',
    ]
    dest = '%s@%s:%s' % (self._user, self._remote, remote_dst)
    # Checks both whether to enable debug info and the existence of the stripped
    # directory because build bots using test bundle may use the configure
    # option with debug info enabled but binaries are not available in the
    # stripped directory.
    if (not OPTIONS.is_debug_info_enabled() or
        not os.path.exists(build_common.get_stripped_dir())):
      _run_command(subprocess.check_call,
                   ['rsync'] + pattern_list + ['.', dest] + rsync_options)
      return

    # When debug info is enabled, copy the corresponding stripped binaries if
    # available to save the disk space on ChromeOS.
    list_output = _run_command(
        subprocess.check_output,
        ['rsync'] + pattern_list + ['.', dest] + rsync_options +
        ['--list-only'])
    paths = [line.rsplit(' ', 1)[-1] for line in list_output.splitlines()[1:]]

    stripped_binaries, others = self._split_stripped_binaries(paths)

    # Send the file list via stdin.
    logging.debug('rsync others: %s', ', '.join(others))
    _run_command(_check_call_with_input,
                 ['rsync', '--files-from=-', '.', dest] + rsync_options,
                 input='\n'.join(others))

    logging.debug('rsync stripped binaries: %s', ', '.join(stripped_binaries))
    dest_build = os.path.join(dest, build_common.get_build_dir())
    # rsync results in error if the parent directory of the destination
    # directory does not exist, so ensure it exists.
    self.run('mkdir -p ' + dest_build.rsplit(':', 1)[-1])
    _run_command(_check_call_with_input,
                 ['rsync', '--files-from=-', build_common.get_stripped_dir(),
                  dest_build] + rsync_options,
                 input='\n'.join(stripped_binaries))

  def port_forward(self, port):
    """Uses ssh to forward a remote port to local port so that remote service
    listening to localhost only can be reached."""
    return _run_command(
        subprocess.call,
        self._build_ssh_command(
            # Something that waits until connection is established and
            # terminates.
            "sleep 3",
            extra_options=['-L', '{port}:localhost:{port}'.format(port=port)]))

  def run(self, cmd, ignore_failure=False, cwd=None):
    """Runs the command on remote host via ssh command."""
    if cwd is None:
      cwd = self.get_remote_arc_root()
    cmd = 'cd %s && %s' % (cwd, cmd)
    return _run_command(
        subprocess.call if ignore_failure else subprocess.check_call,
        self._build_ssh_command(cmd))

  def run_commands(self, commands, cwd=None):
    return self.run(' && '.join(commands), cwd)

  def run_with_filter(self, cmd, cwd=None):
    if cwd is None:
      cwd = self.get_remote_arc_root()
    cmd = 'cd %s && %s' % (cwd, cmd)

    handler = MinidumpFilter(concurrent_subprocess.RedirectOutputHandler())
    if self._attach_nacl_gdb_type:
      if OPTIONS.is_nacl_build():
        handler = gdb_util.NaClGdbHandlerAdapter(
            handler, None, self._attach_nacl_gdb_type, host=self._remote)
      elif OPTIONS.is_bare_metal_build():
        handler = gdb_util.BareMetalGdbHandlerAdapter(
            handler, self._nacl_helper_binary,
            self._attach_nacl_gdb_type, host=self._remote,
            ssh_options=self.get_ssh_options())
    if self._jdb_type and self._jdb_port:
      handler = jdb_util.JdbHandlerAdapter(
          handler, self._jdb_port, self._jdb_type, self)
    return run_command_with_filter(self._build_ssh_command(cmd),
                                   output_handler=handler)

  def run_command_for_output(self, cmd):
    """Runs the command on remote host and returns stdout as a string."""
    return _run_command(subprocess.check_output,
                        self._build_ssh_command(cmd))

  def _build_shared_command_options(self, port_option='-p'):
    """Returns command options shared among ssh and scp."""
    # By the use of Control* options, the ssh connection lives 3 seconds longer
    # so that the next ssh command can reuse it.
    result = ['-o', 'StrictHostKeyChecking=no',
              '-o', 'PasswordAuthentication=no',
              '-o', 'ControlMaster=auto', '-o', 'ControlPersist=3s',
              '-o', 'ControlPath=%s' % _get_ssh_control_path()]
    if self._port:
      result.extend([port_option, str(self._port)])
    if self._ssh_key:
      result.extend(['-i', self._ssh_key])
    if self._known_hosts:
      result.extend(['-o', 'UserKnownHostsFile=' + self._known_hosts])
    return result

  def _build_shared_ssh_command_options(self):
    """Returns command options for ssh, to be shared among run and rsync."""
    result = self._build_shared_command_options()
    # For program which requires special terminal control (e.g.,
    # run_integration_tests), we need to specify -t. Otherwise,
    # it is better to specify -T to avoid extra \r, which messes
    # up the output from locally running program.
    result.append('-t' if self._enable_pseudo_tty else '-T')
    return result

  def _build_ssh_command(self, cmd, extra_options=[]):
    ssh_cmd = (['ssh', '%s@%s' % (self._user, self._remote)] +
               self._build_shared_ssh_command_options() +
               extra_options + ['--', cmd])
    return ssh_cmd

  def _build_rsync_include_pattern_list(self, path_list):
    pattern_set = set()
    for path in path_list:
      if os.path.isdir(path):
        # For directory, adds all files under the directory.
        pattern_set.add(os.path.join(path, '**'))

      # It is necessary to add all parent directories, otherwise some parent
      # directory won't be created and the files wouldn't be copied.
      while path:
        pattern_set.add(path)
        path = os.path.dirname(path)

    return sorted(pattern_set)

  def _split_stripped_binaries(self, paths):
    """Separates the paths for which stripped binaries are available.

    Returns a tuple (stripped, others).
    |stripped| includes the paths for which stripped binaries exist in the
    stripped directory. The path is converted to the relative path from the
    build directory for later use.
    |others| includes the remaining paths and paths are not converted.
    """
    all_stripped_binaries = set(build_common.find_all_files(
        build_common.get_stripped_dir(), relative=True, use_staging=False))
    stripped_binaries = []
    others = []
    for path in paths:
      if os.path.isdir(path):
        continue
      relpath = os.path.relpath(path, build_common.get_build_dir())
      if relpath in all_stripped_binaries:
        stripped_binaries.append(relpath)
      else:
        others.append(path)
    return stripped_binaries, others


def _get_command(*args, **kwargs):
  """Returns command line from Popen's arguments."""
  command = kwargs.get('args')
  if command is not None:
    return command
  return args[0]


def _check_call_with_input(*args, **kwargs):
  """Works as subprocess.check_call(), but can send to it |input| via stdin."""
  if 'input' not in kwargs:
    return subprocess.check_call(*args, **kwargs)

  if 'stdin' in kwargs:
    raise ValueError('stdin and input are not allowed at once.')
  inputdata = kwargs.pop('input')
  process = subprocess.Popen(stdin=subprocess.PIPE, *args, **kwargs)
  process.communicate(inputdata)
  retcode = process.poll()
  if retcode:
    raise subprocess.CalledProcessError(retcode, _get_command(*args, **kwargs))
  return 0


def _run_command(func, *args, **kwargs):
  logging.info(
      '%s', logging_util.format_commandline(_get_command(*args, **kwargs)))
  return func(*args, **kwargs)


def run_command_with_filter(cmd, output_handler):
  """Run the command with some output filters. """
  p = concurrent_subprocess.Popen(cmd)
  returncode = p.handle_output(output_handler)
  if returncode:
    raise subprocess.CalledProcessError(cmd, returncode)


def create_launch_remote_chrome_param(argv):
  """Creates flags to run ./launch_chrome on remote_host.

  To run ./launch_chrome, it is necessary to tweak the given flags.
  - Removes --nacl-helper-binary, --remote, and --ssh-key flags.
  - Adds --noninja flag.
  """
  result_argv = []
  skip_next = False
  for arg in argv:
    if skip_next:
      skip_next = False
      continue
    if arg in _REMOTE_FLAGS:
      skip_next = True
      continue
    if any(arg.startswith(flag + '=') for flag in _REMOTE_FLAGS):
      continue
    # pipes.quote should be replaced with shlex.quote on Python v3.3.
    result_argv.append(pipes.quote(arg))
  return result_argv + ['--noninja']


def create_remote_executor(parsed_args, remote_env=None,
                           enable_pseudo_tty=False):
  return RemoteExecutor(os.environ['USER'], remote=parsed_args.remote,
                        remote_env=remote_env, ssh_key=parsed_args.ssh_key,
                        enable_pseudo_tty=enable_pseudo_tty)


def get_launch_chrome_files_and_directories(parsed_args):
  patterns = (_COMMON_FILE_PATTERNS +
              _LAUNCH_CHROME_FILE_PATTERNS +
              [parsed_args.arc_data_dir])
  return expand_target_and_glob(patterns)


def get_integration_test_files_and_directories():
  all_unittest_executables = unittest_util.get_test_executables(
      unittest_util.get_all_tests())
  patterns = (_COMMON_FILE_PATTERNS +
              _LAUNCH_CHROME_FILE_PATTERNS +
              _INTEGRATION_TEST_FILE_PATTERNS +
              _UNIT_TEST_FILE_PATTERNS +
              unittest_util.get_nacl_tools() +
              all_unittest_executables +
              [toolchain.get_adb_path_for_chromeos()])
  return expand_target_and_glob(patterns)


def get_unit_test_files_and_directories(parsed_args):
  patterns = (_COMMON_FILE_PATTERNS +
              _UNIT_TEST_FILE_PATTERNS +
              unittest_util.get_nacl_tools() +
              unittest_util.get_test_executables(parsed_args.tests))
  return expand_target_and_glob(patterns)


def expand_target_and_glob(file_patterns):
  """Expands %(target)s and glob pattern in |file_patterns|.

  NOTE: This function just expands %(target)s and glob pattern and does NOT
  convert a directory path into a list of files under the directory.
  """
  format_args = {
      'target': build_common.get_target_dir_name()
  }
  file_patterns = [pattern % format_args for pattern in file_patterns]
  paths = []
  for pattern in file_patterns:
    paths += glob.glob(pattern)
  return paths


def _detect_remote_host_type_from_uname_output(str):
  """Categorizes the output from uname -s to one of cygwin|mac|chromeos."""
  if 'CYGWIN' in str:
    return 'cygwin'
  if 'Darwin' in str:
    return 'mac'
  if 'Linux' in str:
    # We don't support non-chromeos Linux as a remote target.
    return 'chromeos'
  raise NotImplementedError('Unsupported remote host OS: %s.' % str)


def detect_remote_host_type(remote, ssh_key):
  """Tries logging in and runs 'uname -s' to detect the host type."""
  # The 'root' users needs to be used for Chrome OS and $USER for other targets.
  # Here we try 'root' first, to give priority to Chrome OS.
  users = ['root', os.environ['USER']]
  for user in users:
    executor = RemoteExecutor(user, remote=remote, ssh_key=ssh_key)
    try:
      return _detect_remote_host_type_from_uname_output(
          executor.run_command_for_output('uname -s'))
    except subprocess.CalledProcessError:
      pass
  raise Exception(
      'Cannot remote log in by: %s\n'
      'Please check the remote address is correct: %s\n'
      'If you are trying to connect to a Chrome OS device, also check that '
      'test image (not dev image) is installed in the device.' % (
          ','.join(users), remote))
