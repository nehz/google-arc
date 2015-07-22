# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Provides basic utilities to implement remote-host-execution of
# launch_chrome, run_integration_tests, and run_unittests.py on Chrome OS,
# Windows (Cygwin), and Mac.

import atexit
import itertools
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

RUN_UNITTEST = 'src/build/run_unittest.py'
SYNC_ADB = 'src/build/sync_adb.py'
SYNC_CHROME = 'src/build/sync_chrome.py'
SYNC_ANDROID_SDK_BUILD_TOOLS = 'src/build/sync_android_sdk_build_tools.py'

_TEST_SSH_KEY = (
    'third_party/tools/crosutils/mod_for_test_scripts/ssh_keys/testing_rsa')

# Following lists contain glob patterns with place holders (see also
# build_common.expand_path_placeholder()) of files or directories to be copied
# to the remote host.
_COMMON_GLOB_TEMPLATE_LIST = [
    '{out}/configure.options',
    'src/build',
    'third_party/tools/ninja/misc',
    _TEST_SSH_KEY,
]
_LAUNCH_CHROME_GLOB_TEMPLATE_LIST = [
    'launch_chrome',
    '{out}/target/{target}/runtime',
    build_common.ARC_WELDER_UNPACKED_DIR,
    'src/packaging',
]
_INTEGRATION_TEST_GLOB_TEMPLATE_LIST = [
    'mods/android/dalvik/tests',
    '{out}/data_roots/art.*',
    '{out}/data_roots/arc.*',
    '{out}/data_roots/cts.*',
    '{out}/data_roots/graphics.*',
    '{out}/data_roots/jstests.*',
    '{out}/data_roots/ndk.*',
    '{out}/data_roots/system_mode.*',
    '{out}/staging/android/art/test/*/expected.txt',
    # The following two files are needed only for 901-perf test.
    '{out}/staging/android/art/test/901-perf/README.benchmark',
    '{out}/staging/android/art/test/901-perf/test_cases',
    '{out}/target/{target}/integration_tests',
    '{out}/target/{target}/root/system/usr/icu/icudt48l.dat',
    '{out}/target/common/art_tests/*/expected.txt',
    '{out}/target/common/art_tests/*/*.jar',
    '{out}/target/common/integration_test/*',
    # TODO(crbug.com/340594): Avoid checking for APK files when CRX is
    # already generated so that we don't need to send APK to remote,
    # for package.apk, HelloAndroid.apk, glowhockey.apk, and
    # perf_tests_codec.apk
    '{out}/target/common/obj/APPS/HelloAndroid_intermediates/HelloAndroid.apk',
    '{out}/target/common/obj/APPS/ndk_translation_tests_intermediates/work/libs/*',  # NOQA
    '{out}/target/common/obj/APPS/perf_tests_codec_intermediates/perf_tests_codec.apk',  # NOQA
    '{out}/target/common/obj/JAVA_LIBRARIES/uiautomator.*/javalib.jar',
    '{out}/target/common/vmHostTests',
    '{out}/third_party_apks/*',
    '{out}/tools/apk_to_crx.py',
    'run_integration_tests',
    'src/integration_tests',
    'third_party/android-cts/android-cts/repository/plans/CTS.xml',
    'third_party/android-cts/android-cts/repository/testcases/bionic-unit-tests-cts32',  # NOQA
    'third_party/android-cts/android-cts/repository/testcases/*.xml',
    'third_party/android-cts/android-cts/repository/testcases/CtsUiAutomator*',
    'third_party/android-cts-x86/android-cts/repository/testcases/*.xml',
    'third_party/android-cts-x86/android-cts/repository/testcases/bionic-unit-tests-cts32',  # NOQA
    # Java files are needed by VMHostTestRunner, which parses java files to
    # obtain the information of the test methods at testing time.
    'third_party/android/cts/tools/vm-tests-tf/src/dot/junit/format/*/*.java',
    'third_party/android/cts/tools/vm-tests-tf/src/dot/junit/opcodes/*/*.java',
    'third_party/android/cts/tools/vm-tests-tf/src/dot/junit/verify/*/*.java',
    'third_party/examples/apk/*/*.apk',
    'third_party/ndk/sources/cxx-stl/stlport/libs/armeabi-v7a/libstlport_shared.so',  # NOQA
]
_UNITTEST_GLOB_TEMPLATE_LIST = [
    # These two files are used by stlport_unittest
    '{out}/target/{target}/intermediates/stlport_unittest/test_file.txt',
    '{out}/target/{target}/intermediates/stlport_unittest/win32_file_format.tmp',  # NOQA
    '{out}/target/{target}/lib',
    '{out}/target/{target}/posix_translation_fs_images/test_readonly_fs_image.img',  # NOQA
    '{out}/target/{target}/root/system/framework/art-gtest-*.jar',
    '{out}/target/{target}/root/system/framework/core-libart.jar',
    # Used by posix_translation_test
    '{out}/target/{target}/runtime/_platform_specific/*/readonly_fs_image.img',  # NOQA
    '{out}/target/{target}/test',
    '{out}/target/{target}/unittest_info'
]
_PROTECT_GLOB_TEMPLATE_LIST = [
    # Downloaded in remote Win/Mac machine.
    '{out}/chrome32',
    '{out}/chrome64',
    '{out}/adb',
]

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

  def rsync(self, source_paths, remote_dest_root, exclude_paths=None):
    """Runs rsync command to copy files to remote host.

    Sends |source_paths| to |remote_dest_root| directory in the remote machine.
    |exclude_paths| can be used to exclude files or directories from the
    sending list.
    The files which are under |remote_dest_root| but not in the sending list
    will be deleted.

    Note:
    - Known editor temporary files would never be sent.
    - .pyc files in remote machine will *not* be deleted.
    - If debug info is enabled and therer is a corresponding stripped binary,
      the stripped binary will be sent, instead of original (unstripped)
      binary.
    - Files newly created in the remote machine will be deleted. Specifically,
      if a file in the host machine is deleted, the corresponding file in the
      remote machine is also deleted after the rsync.

    Args:
        source_paths: a list of paths to be sent. Each path can be a file or
            a directory. If the path is directory, all files under the
            directory will be sent.
        remote_dest_root: the path to the destination directory in the
            remote machine.
        exclude_paths: an optional list of paths to be excluded from the
            sending path list. Similar to |source_paths|, if a path is
            directory, all paths under the directory will be excluded.
    """
    filter_list = (
        self._build_rsync_filter_list(source_paths, exclude_paths or []))
    rsync_options = [
        # The remote files need to be writable and executable by chronos. This
        # option sets read, write, and execute permissions to all users.
        '--chmod=a=rwx',
        '--compress',
        '--copy-links',
        '--delete',
        '--delete-excluded',
        '--inplace',
        '--perms',
        '--progress',
        '--recursive',
        '--rsh=' + ' '.join(['ssh'] + self._build_shared_ssh_command_options()),
        '--times',
    ]
    dest = '%s@%s:%s' % (self._user, self._remote, remote_dest_root)
    # Checks both whether to enable debug info and the existence of the stripped
    # directory because build bots using test bundle may use the configure
    # option with debug info enabled but binaries are not available in the
    # stripped directory.
    unstripped_paths = None
    if (OPTIONS.is_debug_info_enabled() and
        os.path.exists(build_common.get_stripped_dir())):
      # When debug info is enabled, copy the corresponding stripped binaries if
      # available to save the disk space on ChromeOS.
      list_output = _run_command(
          subprocess.check_output,
          ['rsync'] + filter_list + ['.', dest] + rsync_options +
          ['--list-only'])
      paths = [
          line.rsplit(' ', 1)[-1] for line in list_output.splitlines()[1:]]
      unstripped_paths = [
          path for path in paths if self._has_stripped_binary(path)]

      # here, prepend filter rules to "protect" and "exclude" the files which
      # have the corresponding stripped binary.
      # Note: the stripped binraies will be sync'ed by the second rsync
      # command, so it is necessary to "protect" here, too. Otherwise, the
      # files will be deleted at the first rsync.
      filter_list = list(itertools.chain.from_iterable(
          (('--filter', 'P /' + path, '--exclude', '/' + path)
           for path in unstripped_paths))) + filter_list

    # Copy files to remote machine.
    _run_command(subprocess.check_call,
                 ['rsync'] + filter_list + ['.', dest] + rsync_options)

    if unstripped_paths:
      # Copy strippted binaries to the build/ directory in the remote machine
      # directly.
      stripped_binary_relative_paths = [
          os.path.relpath(path, build_common.get_build_dir())
          for path in unstripped_paths]

      logging.debug('rsync stripped_binaries: %s', ', '.join(unstripped_paths))
      dest_build = os.path.join(dest, build_common.get_build_dir())
      # rsync results in error if the parent directory of the destination
      # directory does not exist, so ensure it exists.
      self.run('mkdir -p ' + dest_build.rsplit(':', 1)[-1])
      _run_command(_check_call_with_input,
                   ['rsync', '--files-from=-', build_common.get_stripped_dir(),
                    dest_build] + rsync_options,
                   input='\n'.join(stripped_binary_relative_paths))

  def _build_rsync_filter_list(self, source_paths, exclude_paths):
    """Builds rsync's filter options to send |source_paths|.

    Builds a list of command line arguments for rsync's filter option
    to send |source_paths| excluding |exclude_paths|.
    The rsync's filter is a bit complicated.

    Note:
    - The order of the rule is important. Earlier rule is stronger than
      rest.
    - In the rule, paths beginning with '/' matches with the paths relative
      to the copy source directory, otherwise it matches any component.
      For example, assuming the copy source directory is "source",
      "*.pyc" matches any files (or directories) whose name ends with .pyc,
      such as "source/test.pyc", "source/dir1/test.pyc", "source/dir2/main.pyc"
      and so on.
    - rsync traverses the paths recursively from top to bottom, and checks
      filters for each path. So, if a file needs to be sent, all its ancestors
      must be included.
      E.g., if a/b/c/d needs to be sent;
      --inlucde /a --include /a/b --include /a/b/c --include /a/b/c/d
      must be set.
    - If a directory path matches with the include pattern, all its descendants
      will be sent. So, in above case, /a/*, /a/b/*, /a/b/c* and all their
      descendants will be also sent. To avoid such a situation, this function
      also adds;
      --exclude /a/* --exclude /a/b/* --exclude /a/b/c/* --exclude /*
      after include rules (as weaker rules).

    Args:
        source_paths: a list of paths for files and directories to be sent.
            Please see rsync()'s docstring for more details.
        exclude_paths: a list of paths for files and directories to be
            excluded from the list of sending paths.

    Returns: a list of filter command line arguments for rsync.
    """
    result = []

    # 1) exclude all known editor temporary files and .pyc files.
    # Note that, to keep .pyc files generated in the remote machine, protect
    # then at first, otherwise these are removed every rsync execution.
    # If we update a '.py' file, the corresponding '.pyc' file should be
    # re-generated on execution automatically in remote host side.
    result.extend(['--filter', 'P *.pyc'])
    result.extend(itertools.chain.from_iterable(
        ('--exclude', pattern) for pattern in (
            build_common.COMMON_EDITOR_TMP_FILE_PATTERNS + ['*.pyc'])))

    # 2) protect files downloaded and cached in remote machine.
    result.extend(itertools.chain.from_iterable(
        ('--filter', 'P %s' % build_common.expand_path_placeholder(pattern))
        for pattern in _PROTECT_GLOB_TEMPLATE_LIST))

    # 3) append all exclude paths.
    result.extend(itertools.chain.from_iterable(
        ('--exclude', '/' + path) for path in sorted(set(exclude_paths))))

    # 4) append source paths as follows;
    # 4-1) Remove "redundant" paths. Here "redundant" means paths whose
    #    anscestor is contained in the include paths.
    # 4-2) Then, append remaining paths and their anscestors. See docstring
    #    for more details why anscestors are needed.
    # 4-3) Finally, exclude unnecessary files and directories.
    #    Note: the "redundant" paths are removed at 1), so we can assume that
    #    all paths here are leaves.
    source_paths = set(source_paths)

    # 4-1) Remove redundant paths.
    redundant_paths = []
    for path in source_paths:
      for dirpath in itertools.islice(file_util.walk_ancestor(path), 1, None):
        if dirpath in source_paths:
          redundant_paths.append(path)
          break
    for path in redundant_paths:
      source_paths.discard(path)

    # 4-2) Build --include arguments.
    include_paths = set(itertools.chain.from_iterable(
        file_util.walk_ancestor(path) for path in source_paths))
    result.extend(itertools.chain.from_iterable(
        ('--include', '/' + path) for path in sorted(include_paths)))

    # 4-3) Exclude unnecessary files.
    result.extend(itertools.chain.from_iterable(
        ('--exclude', '/%s/*' % path)
        for path in sorted(include_paths - source_paths)))
    result.extend(('--exclude', '/*'))

    return result

  def _has_stripped_binary(self, path):
    """Returns True if a stripped binary corresponding to |path| is found."""
    relpath = os.path.relpath(path, build_common.get_build_dir())
    if relpath.startswith('../'):
      # The given file is not under build directory.
      return False

    # Returns True if there is a stripped file corresponding to the |path|.
    return os.path.isfile(
        os.path.join(build_common.get_stripped_dir(), relpath))

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
            handler, None, self._attach_nacl_gdb_type,
            remote_executor=self)
      elif OPTIONS.is_bare_metal_build():
        handler = gdb_util.BareMetalGdbHandlerAdapter(
            handler, self._nacl_helper_binary,
            self._attach_nacl_gdb_type, host=self._remote,
            ssh_options=self.get_ssh_options(),
            remote_executor=self)
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


def get_launch_chrome_deps(parsed_args):
  """Returns a list of paths needed to run ./launch_chrome.

  The returned path may be a directory. In that case, all its descendents are
  needed.
  """
  glob_template_list = (
      _COMMON_GLOB_TEMPLATE_LIST + _LAUNCH_CHROME_GLOB_TEMPLATE_LIST)
  patterns = (
      map(build_common.expand_path_placeholder, glob_template_list) +
      [parsed_args.arc_data_dir])
  return file_util.glob(*patterns)


def get_integration_test_deps():
  """Returns a list of paths needed to run ./run_integration_tests.

  The returned path may be a directory. In that case, all its descendants are
  needed.
  """
  # Note: integration test depends on ./launch_chrome. Also, we run unittests
  # as a part of integration test on ChromeOS.
  glob_template_list = (
      _COMMON_GLOB_TEMPLATE_LIST + _LAUNCH_CHROME_GLOB_TEMPLATE_LIST +
      _INTEGRATION_TEST_GLOB_TEMPLATE_LIST + _UNITTEST_GLOB_TEMPLATE_LIST)
  patterns = (
      map(build_common.expand_path_placeholder, glob_template_list) +
      [toolchain.get_adb_path_for_chromeos()] +
      unittest_util.get_nacl_tools() +
      unittest_util.get_test_executables(unittest_util.get_all_tests()))
  return file_util.glob(*patterns)


def get_unittest_deps(parsed_args):
  """Returns a list of paths needed to run unittests.

  The returned path may be a directory. In that case, all its descendants are
  needed.
  """
  glob_template_list = (
      _COMMON_GLOB_TEMPLATE_LIST + _UNITTEST_GLOB_TEMPLATE_LIST)
  patterns = (
      map(build_common.expand_path_placeholder, glob_template_list) +
      unittest_util.get_nacl_tools() +
      unittest_util.get_test_executables(parsed_args.tests))
  return file_util.glob(*patterns)


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
