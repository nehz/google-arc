#!/usr/bin/python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import atexit
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urlparse

import build_common
import launch_chrome_options
import prep_launch_chrome
import toolchain
from build_options import OPTIONS
from util import chrome_process
from util import concurrent_subprocess
from util import file_util
from util import gdb_util
from util import jdb_util
from util import logging_util
from util import minidump_filter
from util import output_handler
from util import platform_util
from util import remote_executor
from util import signal_util
from util import startup_stats


_ROOT_DIR = build_common.get_arc_root()

_CHROME_KILL_DELAY = 0.1

_CHROME_KILL_TIMEOUT = 10

_CHROME_PID_PATH = None

_PERF_TOOL = 'perf'

_USER_DATA_DIR = None  # Will be set after we parse the commandline flags.

# List of lines for stdout/stderr Chrome output to suppress.
_SUPPRESS_LIST = [
    # When debugging with gdb, NaCl is emitting many of these messages.
    'NaClAppThreadSetSuspendedRegisters: Registers not modified',
]


# Caution: The feature to kill the running chrome has race condition, that this
# may kill unrelated process. The file can be rewritten at anytime, so there
# is no simpler way to guarantee that the pid read from the file is reliable.
# Note that technically we should be able to lock the file, but python does
# not provide portable implementation.
def _read_chrome_pid_file():
  if not os.path.exists(_CHROME_PID_PATH):
    return None

  with open(_CHROME_PID_PATH) as pid_file:
    lines = pid_file.readlines()
  if not lines:
    logging.error('chrome.pid is empty.')
    return None
  try:
    return int(lines[0])
  except ValueError:
    logging.error('Invalid content of chrome.pid: ' + lines[0])
    return None


def _kill_running_chrome():
  pid = _read_chrome_pid_file()
  if pid is None:
    return

  try:
    # Use SIGKILL instead of more graceful signals, as Chrome's
    # behavior for other signals are not well defined nor
    # tested. Actually, we cannot kill Chrome with NaCl's debug stub
    # enabled by SIGTERM. Also, there was a similar issue in Bare
    # Metal mode with M39 Chrome. See crbug.com/433967.
    os.kill(pid, signal.SIGKILL)

    # Unfortunately, there is no convenient API to wait subprocess's
    # termination with timeout. So, here we just poll it.
    wait_time_limit = time.time() + _CHROME_KILL_TIMEOUT
    while True:
      retpid, status = os.waitpid(pid, os.WNOHANG)
      if retpid:
        break
      now = time.time()
      if now > wait_time_limit:
        logging.error('Terminating Chrome is timed out: %d', pid)
        break
      time.sleep(min(_CHROME_KILL_DELAY, wait_time_limit - now))
  except OSError:
    # Here we ignore the OS error. The process may have been terminated somehow
    # by external reason, while the file still exists on the file system.
    pass

  _remove_chrome_pid_file(pid)


def _remove_chrome_pid_file(pid):
  read_pid = _read_chrome_pid_file()
  if read_pid == pid:
    try:
      os.remove(_CHROME_PID_PATH)
    except OSError:
      # The file may already be removed due to timing issue. Ignore the error.
      pass


def _prepare_chrome_user_data_dir(parsed_args):
  global _USER_DATA_DIR
  if parsed_args.use_temporary_data_dirs:
    _USER_DATA_DIR = tempfile.mkdtemp(
        prefix=build_common.CHROME_USER_DATA_DIR_PREFIX + '-')
    atexit.register(lambda: file_util.rmtree_with_retries(_USER_DATA_DIR))
  elif parsed_args.user_data_dir:
    _USER_DATA_DIR = parsed_args.user_data_dir
  else:
    _USER_DATA_DIR = build_common.get_chrome_default_user_data_dir()


def set_environment_for_chrome():
  # Prevent GTK from attempting to move the menu bar, which prints many warnings
  # about undefined symbol "menu_proxy_module_load"
  if 'UBUNTU_MENUPROXY' in os.environ:
    del os.environ['UBUNTU_MENUPROXY']


def _maybe_wait_iteration_lock(parsed_args):
  if not parsed_args.iteration_lock_file:
    return
  with open(parsed_args.iteration_lock_file, 'w'):
    pass
  # This message is hard-coded in interleaved_perftest.py. Don't change it.
  sys.stderr.write('waiting for next iteration\n')
  while os.path.exists(parsed_args.iteration_lock_file):
    time.sleep(0.1)


def _run_chrome_iterations(parsed_args):
  if not parsed_args.no_cache_warming:
    _maybe_wait_iteration_lock(parsed_args)
    stats = _run_chrome(parsed_args, cache_warming=True)
    if parsed_args.mode == 'perftest':
      total = (stats.pre_embed_time_ms + stats.plugin_load_time_ms +
               stats.on_resume_time_ms)
      print 'WARM-UP %d %d %d %d' % (total,
                                     stats.pre_embed_time_ms,
                                     stats.plugin_load_time_ms,
                                     stats.on_resume_time_ms)
      startup_stats.print_raw_stats(stats)
      sys.stdout.flush()

  if parsed_args.iterations > 0:
    stat_list = []
    for i in xrange(parsed_args.iterations):
      _maybe_wait_iteration_lock(parsed_args)

      sys.stderr.write('\nStarting Chrome, test run #%s\n' % (i + 1))
      stats = _run_chrome(parsed_args)
      startup_stats.print_raw_stats(stats)
      sys.stdout.flush()
      stat_list.append(stats)

    startup_stats.print_aggregated_stats(stat_list)
    sys.stdout.flush()


def _check_apk_existence(parsed_args):
  for apk_path in parsed_args.apk_path_list:
    is_file = (parsed_args.mode != 'driveby' or
               urlparse.urlparse(apk_path).scheme == '')
    if is_file and not os.path.exists(apk_path):
      raise Exception('APK does not exist:' + apk_path)


def _check_crx_existence(parsed_args):
  if (not parsed_args.build_crx and
      parsed_args.mode != 'driveby' and
      not os.path.exists(parsed_args.arc_data_dir)):
    raise Exception('--nocrxbuild is used but CRX does not exist in %s.\n'
                    'Try launching chrome without --nocrxbuild in order to '
                    'rebuild the CRX.' % parsed_args.arc_data_dir)


def _get_chrome_path(parsed_args):
  if parsed_args.chrome_binary:
    return parsed_args.chrome_binary
  else:
    return remote_executor.get_chrome_exe_path()


def _get_nacl_helper_path(parsed_args):
  if parsed_args.nacl_helper_binary:
    return parsed_args.nacl_helper_binary
  chrome_path = _get_chrome_path(parsed_args)
  return os.path.join(os.path.dirname(chrome_path), 'nacl_helper')


def _get_nacl_irt_path(parsed_args):
  if not OPTIONS.is_nacl_build():
    return None
  chrome_path = _get_chrome_path(parsed_args)
  irt = toolchain.get_tool(OPTIONS.target(), 'irt')
  nacl_irt_path = os.path.join(os.path.dirname(chrome_path), irt)
  nacl_irt_debug_path = nacl_irt_path + '.debug'
  # Use debug version nacl_irt if it exists.
  if os.path.exists(nacl_irt_debug_path):
    return nacl_irt_debug_path
  else:
    return nacl_irt_path


def main():
  signal_util.setup()

  OPTIONS.parse_configure_file()

  parsed_args = launch_chrome_options.parse_args(sys.argv)
  logging_util.setup(verbose=parsed_args.verbose)

  _prepare_chrome_user_data_dir(parsed_args)
  global _CHROME_PID_PATH
  _CHROME_PID_PATH = os.path.join(_USER_DATA_DIR, 'chrome.pid')

  # If there is an X server at :0.0 and GPU is enabled, set it as the
  # current display.
  if parsed_args.display:
    os.environ['DISPLAY'] = parsed_args.display

  os.chdir(_ROOT_DIR)

  if not parsed_args.remote:
    _kill_running_chrome()

  if parsed_args.run_ninja:
    build_common.run_ninja()

  ld_library_path = os.environ.get('LD_LIBRARY_PATH')
  lib_paths = ld_library_path.split(':') if ld_library_path else []
  lib_paths.append(build_common.get_load_library_path())
  # Add the directory of the chrome binary so that .so files in the directory
  # can be loaded. This is needed for loading libudev.so.0.
  # TODO(crbug.com/375609): Remove the hack once it becomes no longer needed.
  lib_paths.append(os.path.dirname(_get_chrome_path(parsed_args)))
  os.environ['LD_LIBRARY_PATH'] = ':'.join(lib_paths)
  set_environment_for_chrome()

  if not platform_util.is_running_on_remote_host():
    _check_apk_existence(parsed_args)

  # Do not build crx for drive by mode.
  # TODO(crbug.com/326724): Transfer args to metadata in driveby mode.
  if parsed_args.mode != 'driveby':
    if not platform_util.is_running_on_remote_host():
      prep_launch_chrome.prepare_crx(parsed_args)
    prep_launch_chrome.remove_crx_at_exit_if_needed(parsed_args)

  if parsed_args.remote:
    remote_executor.launch_remote_chrome(parsed_args, sys.argv[1:])
  else:
    platform_util.assert_machine(OPTIONS.target())
    _check_crx_existence(parsed_args)
    _run_chrome_iterations(parsed_args)

  return 0


def _compute_chrome_plugin_params(parsed_args):
  params = []
  extensions = [
      remote_executor.resolve_path(build_common.get_runtime_out_dir()),
      remote_executor.resolve_path(build_common.get_handler_dir())]
  params.append('--load-extension=' + ','.join(extensions))

  # Do not use user defined data directory if user name for remote host is
  # provided. The mounted cryptohome directory is used instead.
  if not parsed_args.login_user:
    params.append(
        '--user-data-dir=' + remote_executor.resolve_path(_USER_DATA_DIR))

  # Not all targets can use nonsfi mode.
  if OPTIONS.is_bare_metal_build():
    params.append('--enable-nacl-nonsfi-mode')

  return params


def _is_no_sandbox_needed(parsed_args):
  if parsed_args.disable_nacl_sandbox:
    return True

  # Official Chrome needs setuid + root ownership to run.  --no-sandbox
  # bypasses that.
  if OPTIONS.is_official_chrome():
    return True

  # In some cases, --no-sandbox is needed to work gdb properly.
  if gdb_util.is_no_sandbox_needed(parsed_args.gdb):
    return True

  # Set --no-sandbox on Mac for now because ARC apps crash on Mac Chromium
  # without the flag.
  # TODO(crbug.com/332785): Investigate the cause of crash and remove the flag
  # if possible.
  if platform_util.is_running_on_mac():
    return True

  return False


def _compute_chrome_sandbox_params(parsed_args):
  params = []
  if _is_no_sandbox_needed(parsed_args):
    params.append('--no-sandbox')
    if OPTIONS.is_bare_metal_build():
      # Non-SFI NaCl helper, which heavily depends on seccomp-bpf,
      # does not start without seccomp sandbox initialized unless we
      # specify this flag explicitly.
      params.append('--nacl-dangerous-no-sandbox-nonsfi')

  # Environment variables to pass through to nacl_helper.
  passthrough_env_vars = []

  if OPTIONS.is_nacl_build() and parsed_args.disable_nacl_sandbox:
    os.environ['NACL_DANGEROUS_ENABLE_FILE_ACCESS'] = '1'
    passthrough_env_vars.append('NACL_DANGEROUS_ENABLE_FILE_ACCESS')
  if OPTIONS.is_nacl_build() and parsed_args.enable_nacl_list_mappings:
    os.environ['NACL_DANGEROUS_ENABLE_LIST_MAPPINGS'] = '1'
    passthrough_env_vars.append('NACL_DANGEROUS_ENABLE_LIST_MAPPINGS')
  if passthrough_env_vars:
    os.environ['NACL_ENV_PASSTHROUGH'] = ','.join(passthrough_env_vars)
  return params


def _compute_chrome_graphics_params(parsed_args):
  params = []
  params.append('--disable-gl-error-limit')

  # Always use the compositor thread. All desktop Chrome except Linux already
  # use it.
  params.append('--enable-threaded-compositing')

  if parsed_args.enable_osmesa:
    params.append('--use-gl=osmesa')

  # The NVidia GPU on buildbot is blacklisted due to unstableness of graphic
  # driver even there is secondary Matrox GPU(http://crbug.com/145600). It
  # happens with low memory but seems safe for buildbot. So passing
  # ignore-gpu-blacklist to be able to use hardware acceleration.
  params.append('--ignore-gpu-blacklist')

  return params


def _compute_chrome_debugging_params(parsed_args):
  params = []

  # This reduce one step necessary to enable filesystem inspector.
  params.append('--enable-devtools-experiments')

  if OPTIONS.is_nacl_build() and 'plugin' in parsed_args.gdb:
    params.append('--enable-nacl-debug')

  if len(parsed_args.gdb):
    params.append('--disable-hang-monitor')

  if 'gpu' in parsed_args.gdb:
    params.append('--gpu-startup-dialog')
    params.append('--disable-gpu-watchdog')

  if 'renderer' in parsed_args.gdb:
    params.append('--renderer-startup-dialog')

  if parsed_args.enable_fake_video_source:
    params.append('--use-fake-device-for-media-stream')

  return params


def _compute_chrome_diagnostic_params(parsed_args):
  if OPTIONS.is_nacl_build():
    opt = '--nacl-loader-cmd-prefix'
  else:
    opt = '--ppapi-plugin-launcher'

  params = []
  # Loading NaCl module gets stuck if --enable-logging=stderr is specified
  # together with --perfstartup.
  # TODO(crbug.com/276891): Investigate the root cause of the issue and fix it.
  if OPTIONS.is_nacl_build() and parsed_args.perfstartup:
    params.append('--enable-logging')
  else:
    params.append('--enable-logging=stderr')
  params.append('--log-level=0')

  if parsed_args.tracestartup > 0:
    params.append('--trace-startup')
    params.append('--trace-startup-duration=%d' % parsed_args.tracestartup)

  if parsed_args.perfstartup:
    params.append('%s=timeout -s INT %s %s record -gf -o out/perf.data' %
                  (opt, parsed_args.perfstartup, _PERF_TOOL))

  return params


def _compute_chrome_performance_test_params(unused_parsed_args):
  """Add params that are necessary for stable perftest result."""
  params = []

  # Skip First Run tasks, whether or not it's actually the First Run.
  params.append('--no-first-run')

  # Disable default component extensions with background pages - useful for
  # performance tests where these pages may interfere with perf results.
  params.append('--disable-component-extensions-with-background-pages')

  # Enable the recording of metrics reports but disable reporting. In contrast
  # to kDisableMetrics, this executes all the code that a normal client would
  # use for reporting, except the report is dropped rather than sent to the
  # server. This is useful for finding issues in the metrics code during UI and
  # performance tests.
  params.append('--metrics-recording-only')

  # Disable several subsystems which run network requests in the background.
  # This is for use when doing network performance testing to avoid noise in the
  # measurements.
  params.append('--disable-background-networking')

  # They are copied from
  #  ppapi/native_client/tools/browser_tester/browsertester/browserlauncher.py
  # These features could be a source of non-determinism too.
  params.append('--disable-default-apps')
  params.append('--disable-preconnect')
  params.append('--disable-sync')
  params.append('--disable-web-resources')
  params.append('--dns-prefetch-disable')
  params.append('--no-default-browser-check')
  params.append('--safebrowsing-disable-auto-update')

  return params


def _compute_chrome_params(parsed_args):
  chrome_path = _get_chrome_path(parsed_args)
  params = [chrome_path]

  if parsed_args.mode in ('perftest', 'atftest'):
    # Do not show the New Tab Page because showing NTP during perftest makes the
    # benchmark score look unnecessarily bad.
    # TODO(crbug.com/315356): Remove the IF once 315356 is fixed.
    params.append('about:blank')
    # Append flags for performance measurement in test modes to stabilize
    # integration tests and perf score. Do not append these flags in run mode
    # because apps that depend on component extensions (e.g. Files.app) will not
    # work with these flags.
    params.extend(_compute_chrome_performance_test_params(parsed_args))
    # Make the window size small on Goobuntu so that it does not cover the whole
    # desktop during perftest/integration_test.
    params.append('--window-size=500,500')

  if parsed_args.lang:
    params.append('--lang=' + parsed_args.lang)
    # LANGUAGE takes priority over --lang option in Linux.
    os.environ['LANGUAGE'] = parsed_args.lang
    # In Mac, there is no handy way to change the locale.
    if platform_util.is_running_on_mac():
      print '\nWARNING: --lang is not supported in Mac.'

  if (parsed_args.mode == 'atftest' and
      not platform_util.is_running_on_chromeos() and
      not platform_util.is_running_on_mac()):
    # This launches ARC without creating a browser window.  We only do it for
    # automated tests, in case the user wants to do something like examine the
    # Chromium settings ("about:flags" for example), which requires using the
    # browser window. Note that this does not work on Mac, and should be
    # unnecessary on a remote Chromebook target.
    params.append('--silent-launch')

  params.extend(_compute_chrome_plugin_params(parsed_args))
  params.extend(_compute_chrome_sandbox_params(parsed_args))
  params.extend(_compute_chrome_graphics_params(parsed_args))
  params.extend(_compute_chrome_debugging_params(parsed_args))
  params.extend(_compute_chrome_diagnostic_params(parsed_args))
  remote_executor.maybe_extend_remote_host_chrome_params(parsed_args, params)

  if parsed_args.mode == 'driveby':
    params.append(remote_executor.resolve_path(parsed_args.apk_path_list[0]))
  else:
    params.append(
        '--load-and-launch-app=' +
        remote_executor.resolve_path(parsed_args.arc_data_dir))

  # This prevents Chrome to add icon to Gnome panel, which current leaks memory.
  # See http://crbug.com/341724 for details.
  params.append('--disable-background-mode')

  if parsed_args.chrome_args:
    params.extend(parsed_args.chrome_args)

  return params


def _should_timeouts_be_used(parsed_args):
  if parsed_args.jdb_port or parsed_args.gdb:
    # Do not apply a timeout if debugging
    return False

  if parsed_args.mode not in ('atftest', 'perftest'):
    return False

  return True


def _select_chrome_timeout(parsed_args):
  if not _should_timeouts_be_used(parsed_args):
    return None
  return parsed_args.timeout


def _select_output_handler(parsed_args, stats, chrome_process, **kwargs):
  if parsed_args.mode == 'atftest':
    handler = output_handler.AtfTestHandler()
  elif parsed_args.mode == 'perftest':
    handler = output_handler.PerfTestHandler(
        parsed_args, stats, chrome_process, **kwargs)
  else:
    handler = concurrent_subprocess.RedirectOutputHandler(
        *['.*' + re.escape(suppress) for suppress in _SUPPRESS_LIST])

  if 'gpu' in parsed_args.gdb or 'renderer' in parsed_args.gdb:
    handler = gdb_util.GdbHandlerAdapter(
        handler, parsed_args.gdb, parsed_args.gdb_type)

  if 'plugin' in parsed_args.gdb:
    if OPTIONS.is_nacl_build():
      handler = gdb_util.NaClGdbHandlerAdapter(
          handler, _get_nacl_irt_path(parsed_args), parsed_args.gdb_type)
    elif OPTIONS.is_bare_metal_build():
      handler = gdb_util.BareMetalGdbHandlerAdapter(
          handler, _get_nacl_helper_path(parsed_args), parsed_args.gdb_type)

  if (parsed_args.enable_arc_strace and
      parsed_args.arc_strace_output != 'stderr'):
    handler = output_handler.ArcStraceFilter(
        handler, parsed_args.arc_strace_output)

  handler = output_handler.CrashAddressFilter(handler)

  if parsed_args.jdb_port:
    handler = jdb_util.JdbHandlerAdapter(
        handler, parsed_args.jdb_port, parsed_args.jdb_type)

  if not platform_util.is_running_on_remote_host():
    handler = minidump_filter.MinidumpFilter(handler)

  if parsed_args.chrome_flakiness_retry:
    handler = output_handler.ChromeFlakinessHandler(handler, chrome_process)

  return output_handler.ChromeStatusCodeHandler(handler)


def _terminate_chrome(chrome):
  _remove_chrome_pid_file(chrome.pid)

  if OPTIONS.is_nacl_build():
    # For now use sigkill, as NaCl's debug stub seems to cause sigterm to
    # be ignored.
    chrome.kill()
  else:
    chrome.terminate()

  chrome.wait(_CHROME_KILL_TIMEOUT)


def _run_chrome(parsed_args, **kwargs):
  if parsed_args.logcat is not None:
    # adb process will be terminated in the atexit handler, registered
    # in the signal_util.setup().
    subprocess.Popen(
        [toolchain.get_tool('host', 'adb'), 'logcat'] + parsed_args.logcat)

  params = _compute_chrome_params(parsed_args)
  gdb_util.create_or_remove_bare_metal_gdb_lock_dir(parsed_args.gdb)

  # Similar to adb subprocess, using atexit has timing issue. See above comment
  # for the details.
  chrome_timeout = _select_chrome_timeout(parsed_args)
  for i in xrange(parsed_args.chrome_flakiness_retry + 1):
    if i:
      logging.error('Chrome is flaky. Retrying...: %d', i)

    p = chrome_process.ChromeProcess(params, timeout=chrome_timeout)
    atexit.register(_terminate_chrome, p)

    gdb_util.maybe_launch_gdb(parsed_args.gdb, parsed_args.gdb_type, p.pid)
    jdb_util.maybe_launch_jdb(parsed_args.jdb_port, parsed_args.jdb_type)

    # Write the PID to a file, so that other launch_chrome process sharing the
    # same user data can find the process. In common case, the file will be
    # removed by _terminate_chrome() defined above.
    file_util.makedirs_safely(_USER_DATA_DIR)
    with open(_CHROME_PID_PATH, 'w') as pid_file:
      pid_file.write('%d\n' % p.pid)

    stats = startup_stats.StartupStats()
    handler = _select_output_handler(parsed_args, stats, p, **kwargs)

    # Wait for the process to finish or us to be interrupted.
    try:
      returncode = p.handle_output(handler)
    except output_handler.ChromeFlakinessError:
      # Chrome is terminated due to its flakiness. Retry.
      continue

    if returncode:
      sys.exit(returncode)
    return stats

  # Here, the Chrome flakiness failure has continued too many times.
  # Terminate the script.
  logging.error('Chrome is too flaky so that it hits retry limit.')
  sys.exit(1)


if __name__ == '__main__':
  sys.exit(main())
