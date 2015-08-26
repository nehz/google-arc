#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Provides functions for running Chrome and dalvik tests on a remote host.

import argparse
import os.path
import sys

import build_common
from util import platform_util
from util import remote_chromeos_executor
from util import remote_executor_util
from util import remote_mac_executor
from util import remote_windows_executor


def _get_win_chrome_exe_path():
  return os.path.join(build_common.get_arc_root(),
                      build_common.get_chrome_prebuilt_path(),
                      'chrome.exe')


def _get_mac_chrome_exe_path():
  return os.path.join(build_common.get_arc_root(),
                      build_common.get_chrome_prebuilt_path(),
                      'Chromium.app/Contents/MacOS/Chromium')


def _get_chrome_exe_path_on_remote_host():
  """If this script is running on remote host, returns the path to Chrome."""
  if platform_util.is_running_on_chromeos():
    return remote_chromeos_executor.get_chrome_exe_path()
  if platform_util.is_running_on_cygwin():
    return _get_win_chrome_exe_path()
  if platform_util.is_running_on_mac():
    return _get_mac_chrome_exe_path()
  raise NotImplementedError(
      'get_chrome_exe_path_on_remote_host is supported only for Chrome OS, '
      'Cygwin, and Mac.')


def get_chrome_exe_path():
  """Returns the chrome path based on the platform the script is running on."""
  if platform_util.is_running_on_remote_host():
    return _get_chrome_exe_path_on_remote_host()
  return build_common.get_chrome_exe_path_on_local_host()


def resolve_path(path):
  if platform_util.is_running_on_cygwin():
    # As relative path on cygwin, which is passed to Chrome via an environment
    # variable or a flag, is not resolved by Chrome on Windows,
    # it is necessary to resolve beforehand.
    return remote_windows_executor.resolve_cygpath(path)
  return path


def maybe_extend_remote_host_chrome_params(parsed_args, params):
  """Adds chrome flags for Chrome on remote host, if necessary."""
  if platform_util.is_running_on_chromeos():
    remote_chromeos_executor.extend_chrome_params(parsed_args, params)
  if platform_util.is_running_on_cygwin():
    remote_windows_executor.extend_chrome_params(parsed_args, params)


def add_remote_arguments(parser):
  parser.add_argument('--remote',
                      help='The IP address of the remote host, which is '
                      'either a Chrome OS device running a test image, MacOS, '
                      'or cygwin\'s sshd on Windows.')
  parser.add_argument('--ssh-key',
                      help='The ssh-key file to login to remote host. Used '
                      'only when --remote option is specified.')
  parser.add_argument('--remote-host-type',
                      choices=('chromeos', 'cygwin', 'mac'), default=None,
                      help='The OS type of the remote host. Used only when '
                      '--remote option is specified. If --remote option is '
                      'specified but --remote-host-type is not, it will be '
                      'automatically detected by communicating with the '
                      'remote machine.')
  parser.add_argument('--no-remote-machine-setup',
                      dest='remote_machine_setup', action='store_false',
                      help='Do not perform remote machine setup. Used to run '
                      'multiple launch_chrome instances concurrently.')
  parser.add_argument('--remote-arc-dir-name', metavar='<name>',
                      help='The directory name of a remote ARC checkout '
                      'directory. Used to run multiple launch_chrome '
                      'instances concurrently.')
  parser.add_argument('--login-user', help='The user name(typically email '
                      'address) to be used for signing-in in remote host. This '
                      'value is only available for Chrome OS devices')


def maybe_detect_remote_host_type(parsed_args):
  """Sets remote_host_type if necessary.

  This function ensures that parsed_args has |remote_host_type| value,
  if it has |remote|.
  On remote execution, this function checks if remote_host_type is already
  set or not. If not, detects the remote host type by communicating with the
  remote machine by using |remote| and |ssh_key| values.

  Unfortunately, currently ArgumentParser does not support default values
  evaluated lazily (after actual parsing) with already parsed arguments.
  So, all parsers using add_remote_arguments() defined above need to call
  this function just after its parse_known_args() family.
  """
  if platform_util.is_running_on_remote_host():
    # On remote machine, we expect --remote flag is removed.
    assert parsed_args.remote is None, (
        'Found --remote flag, but the script runs on the remote machine.')

    # Detect the remote_host_type of the machine, and fix up or verify
    # the parsed flag.
    if platform_util.is_running_on_cygwin():
      remote_host_type = 'cygwin'
    elif platform_util.is_running_on_mac():
      remote_host_type = 'mac'
    elif platform_util.is_running_on_chromeos():
      remote_host_type = 'chromeos'
    else:
      raise Exception('Unknown platform')

    if parsed_args.remote_host_type is None:
      parsed_args.remote_host_type = remote_host_type
    assert parsed_args.remote_host_type == remote_host_type, (
        '--remote_host_type is mismatching: "%s" vs "%s"' % (
            parsed_args.remote_host_type, remote_host_type))
    return

  # Hereafter, this runs on the host machine.
  if parsed_args.remote_host_type or not parsed_args.remote:
    # If --remote-host-type is already set, or it is not --remote execution,
    # we do nothing.
    return
  parsed_args.remote_host_type = remote_executor_util.detect_remote_host_type(
      parsed_args.remote, parsed_args.ssh_key)


def copy_remote_arguments(parsed_args, args):
  if parsed_args.remote:
    args.append('--remote=' + parsed_args.remote)
  if parsed_args.ssh_key:
    args.append('--ssh-key=' + parsed_args.ssh_key)
  if parsed_args.remote_host_type:
    args.append('--remote-host-type=' + parsed_args.remote_host_type)


def launch_remote_chrome(parsed_args, argv):
  remote_host_type = parsed_args.remote_host_type
  if remote_host_type == 'chromeos':
    return remote_chromeos_executor.launch_remote_chrome(parsed_args, argv)
  if remote_host_type == 'cygwin':
    return remote_windows_executor.launch_remote_chrome(parsed_args, argv)
  if remote_host_type == 'mac':
    return remote_mac_executor.launch_remote_chrome(parsed_args, argv)
  raise NotImplementedError(
      'launch_remote_chrome is supported only for Chrome OS, Cygwin, and Mac.')


def run_remote_unittest(parsed_args):
  if parsed_args.remote_host_type == 'chromeos':
    return remote_chromeos_executor.run_remote_unittest(parsed_args)
  raise NotImplementedError(
      'run_remote_unittest is only supported for Chrome OS.')


def run_remote_integration_tests(parsed_args, argv,
                                 configs_for_integration_tests):
  remote_host_type = parsed_args.remote_host_type
  if remote_host_type == 'chromeos':
    return remote_chromeos_executor.run_remote_integration_tests(
        parsed_args, argv, configs_for_integration_tests)
  if remote_host_type == 'cygwin':
    return remote_windows_executor.run_remote_integration_tests(
        parsed_args, argv, configs_for_integration_tests)
  if remote_host_type == 'mac':
    return remote_mac_executor.run_remote_integration_tests(
        parsed_args, argv, configs_for_integration_tests)
  raise NotImplementedError(
      'run_remote_integration_tests is only supported for Chrome OS, Cygwin, '
      'and Mac.')


def cleanup_remote_files(parsed_args):
  if parsed_args.remote_host_type == 'chromeos':
    return remote_chromeos_executor.cleanup_remote_files(parsed_args)
  raise NotImplementedError(
      'cleanup_remote_files is only supported for Chrome OS.')


def main():
  parser = argparse.ArgumentParser(description='remote executor')
  parser.add_argument('command', choices=('cleanup_remote_files',),
                      help='Specify the command to run in remote host.')
  parser.add_argument('--verbose', '-v', action='store_true',
                      help='Show verbose logging.')
  add_remote_arguments(parser)
  parsed_args = parser.parse_args()
  maybe_detect_remote_host_type(parsed_args)
  if parsed_args.command == 'cleanup_remote_files':
    return cleanup_remote_files(parsed_args)
  else:
    sys.exit('Unknown command: ' + parsed_args.command)


if __name__ == '__main__':
  sys.exit(main())
