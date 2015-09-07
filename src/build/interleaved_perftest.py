#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import Queue
import argparse
import ast
import collections
import contextlib
import logging
import os
import random
import re
import subprocess
import sys
import threading

from src.build import build_common
from src.build.build_options import OPTIONS
from src.build.util import concurrent_subprocess
from src.build.util import logging_util
from src.build.util import statistics

# Prefixes for stash directories.
_STASH_DIR_PREFIX = '.stash'

# Location of the test SSH key.
_TEST_SSH_KEY = (
    'third_party/tools/crosutils/mod_for_test_scripts/ssh_keys/testing_rsa')

# File name pattern used for ssh connection sharing (%r: remote login name,
# %h: host name, and %p: port). See man ssh_config for the detail.
_SSH_CONTROL_PATH = '/tmp/perftest-ssh-%r@%h:%p'


def get_abs_arc_root():
  return os.path.abspath(build_common.get_arc_root())


def get_abs_stash_root():
  return get_abs_arc_root() + _STASH_DIR_PREFIX


def _parse_args(args):
  """Parses the command line arguments.

  Args:
    args: Command line arguments.

  Returns:
    An argparse.Namespace object.
  """
  description = """
Interleaved perftest runner.

This scripts runs "launch_chrome perftest" in interleaved manner against
two ARC binaries to obtain stable PERF comparison.
"""

  epilog = """
Typical usage:

  1) Save a copy of the control build (usually "master" branch).

     $ %(prog)s stash

  2) Make changes to the code or switch to another branch.

  3) Run perftest comparison.

     $ %(prog)s compare
"""

  base_parser = argparse.ArgumentParser(add_help=False)
  base_parser.add_argument(
      '--noninja', dest='run_ninja', action='store_false',
      help='Do not attempt build before running the above command.')
  base_parser.add_argument(
      '--allow-debug-builds', action='store_true',
      help='Allow comparing debug builds.')
  base_parser.add_argument(
      '--verbose', '-v', action='store_true',
      help='Show verbose logging.')

  root_parser = argparse.ArgumentParser(
      description=description,
      epilog=epilog,
      formatter_class=argparse.RawTextHelpFormatter,
      parents=[base_parser])

  subparsers = root_parser.add_subparsers(title='commands')

  stash_parser = subparsers.add_parser(
      'stash',
      help='Stash current ARC working directory for comparison.',
      parents=[base_parser])
  stash_parser.set_defaults(entrypoint=handle_stash)

  compare_parser = subparsers.add_parser(
      'compare',
      help='Run perftest comparison with the stashed binaries.',
      parents=[base_parser])
  compare_parser.add_argument(
      '--iterations', type=int, metavar='<N>', default=60,
      help='Number of perftest iterations.')
  compare_parser.add_argument(
      '--confidence-level', type=int, metavar='<%>', default=90,
      help='Confidence level of confidence intervals.')
  compare_parser.add_argument(
      '--launch-chrome-opt', action='append',
      default=['--enable-nacl-list-mappings'], metavar='OPTIONS',
      help=('An Option to pass on to launch_chrome. Repeat as needed for any '
            'options to pass on.'))
  compare_parser.add_argument(
      '--remote', metavar='<HOST>',
      help=('The host name of the Chrome OS remote host to run perftest on. '
            'Other OSs are not currently supported.'))
  compare_parser.set_defaults(entrypoint=handle_compare)

  clean_parser = subparsers.add_parser(
      'clean',
      help='Clean up the stashed ARC tree copy.',
      parents=[base_parser])
  clean_parser.set_defaults(entrypoint=handle_clean)

  parsed_args = root_parser.parse_args(args)
  return parsed_args


def check_current_configure_options(parsed_args):
  """Checks if the current configure options are good for comparison.

  Args:
    parsed_args: An argparse.Namespace object.
  """
  # Require --opt build.
  if not OPTIONS.is_optimized_build() and not parsed_args.allow_debug_builds:
    sys.exit(
        'configure option bad: either --opt or --official-build '
        'must be specified. If you want to compare debug builds, '
        'please use --allow-debug-builds.')


def load_configure_options(arc_root):
  """Returns configure options for the specific ARC tree.

  Args:
    arc_root: A path to ARC root directory.

  Returns:
    Configure options as a string.
  """
  with open(os.path.join(
      arc_root, build_common.OUT_DIR, 'configure.options')) as f:
    return f.read().strip()


class _InteractivePerfTestOutputHandler(concurrent_subprocess.OutputHandler):
  """Output handler for InteractivePerfTestRunner."""

  def __init__(self, iteration_ready_event, vrawperf_queue):
    super(_InteractivePerfTestOutputHandler, self).__init__()
    self._iteration_ready_event = iteration_ready_event
    self._vrawperf_queue = vrawperf_queue

  def handle_stdout(self, line):
    sys.stdout.write(line)
    sys.stdout.flush()
    return self._handle_common(line)

  def handle_stderr(self, line):
    sys.stderr.write(line)
    sys.stderr.flush()
    return self._handle_common(line)

  def _handle_common(self, line):
    m = re.search(r'^VRAWPERF=(.*)', line)
    if m:
      # block=False triggers the Queue.Full if the queue is not empty.
      # See also the comment in
      # _InteractivePerfTestLaunchChromeThread.__init__().
      self._vrawperf_queue.put(ast.literal_eval(m.group(1)), block=False)
    m = re.search(r'waiting for next iteration', line)
    if m:
      self._iteration_ready_event.set()


class _InteractivePerfTestLaunchChromeThread(threading.Thread):
  """Dedicated thread to communicate with ./launch_chrome"""

  def __init__(self, name, args, cwd):
    """Initializes the thread.

    Args:
      name: thread name.
      arcs: ./launch_chrome's argument, including ./launch_chrome command.
      cwd: working directory for ./launch_chrome.
    """
    super(_InteractivePerfTestLaunchChromeThread, self).__init__(name=name)
    self._args = args
    self._cwd = cwd
    self._iteration_ready_event = threading.Event()
    # We set |maxsize| to 1, expecting that the VRAMPERF is read by the
    # main thread, before we run the next iteration.
    self._vrawperf_queue = Queue.Queue(maxsize=1)

    # It is necessary to guard |self._terminated| and |self._process| to be
    # thread safe, which is touched by both run() invoked on the dedicated
    # thread, and terminate() invoked on the main thread.
    self._lock = threading.Lock()
    self._terminated = False
    self._process = None

  def run(self):
    # Overrides threading.Thread.run()
    output_handler = _InteractivePerfTestOutputHandler(
        self._iteration_ready_event, self._vrawperf_queue)
    with self._lock:
      if self._terminated:
        return
      self._process = concurrent_subprocess.Popen(self._args, cwd=self._cwd)
    self._process.handle_output(output_handler)

  def wait_iteration_ready(self):
    """Waits until "waiting for next iteration" is read."""
    self._iteration_ready_event.wait()
    self._iteration_ready_event.clear()

  def read_vrawperf(self):
    """Reads VRAMPERF line from ./launch_chrome output.

    This blocks until VRAMPERF line is output by ./launch_chrome.
    """
    # Queue.get() does not abort on Ctrl-C unless some timeout is set (see:
    # http://bugs.python.org/issue1360.) We put long (1h) timeout to workaround.
    result = self._vrawperf_queue.get(True, 60 * 60)
    self._vrawperf_queue.task_done()
    return result

  def terminate(self):
    """Tries to terminate the ./launch_chrome process.

    Returns immediately (i.e. does *not* block the calling thread).
    The process termination eventually triggers the thread termination,
    so the caller thread can wait for it by join().
    """
    with self._lock:
      self._terminated = True
      if self._process:
        self._process.terminate()


class InteractivePerfTestRunner(object):
  """Provides a programmatic interface of launch_chrome interactive perftest.

  launch_chrome script supports command line options to allow running perftest
  interactively. Here, "interactive" means that it pauses before each perftest
  iteration and waits to be instructed to start an iteration.

  Usage of this class is simple:

  >>> runner = InteractivePerfTestRunner('/path/to/arc')
  >>> runner.start()
  >>> runner.run()
  {'app_res_mem': [49.08984375], 'on_resume_time_ms': [1545], ...}
  >>> runner.run()
  {'app_res_mem': [49.07812525], 'on_resume_time_ms': [3110], ...}
  >>> runner.close()

  Also it is worth noting that you can run multiple instances in parallel by
  passing different instance_id to the constructor, provided that the "master"
  runner with instance_id=0 must be start()ed first.
  """

  def __init__(
      self, arc_root, remote=None, launch_chrome_opts=(), instance_id=0):
    """Initializes a runner.

    Args:
      arc_root: A path to ARC root directory.
      remote: The host name of the Chrome OS remote host to run perftest on.
          If not specified, perftest is run on local workstation.
      launch_chrome_opts: Optional arguments to launch_chrome.
      instance_id: An integer ID of this instance. You can create multiple
          instances in parallel by passing different instance_id, provided that
          the "master" runner with instance_id=0 must be start()ed first.
    """
    self._arc_root = arc_root
    self._remote = remote
    self._launch_chrome_opts = launch_chrome_opts
    self._instance_id = instance_id
    user = os.getenv('USER', 'default')
    self._iteration_lock_file = '/var/tmp/arc-iteration-lock-%s-%d' % (
        user, instance_id)
    self._thread = None

  def start(self):
    """Starts launch_chrome script and performs warmup.

    If instance_id is 0, launch_chrome script will also do extra setup if
    it's running on remote machine.
    """
    assert not self._thread, (
        'InteractivePerfTestRunner cannot be started while it is running.')
    args = [
        './launch_chrome',
        'perftest',
        # We set the number of iterations to arbitrary large number and
        # terminate the instance by signals.
        '--iterations=99999999',
        '--noninja',
        '--use-temporary-data-dirs',
        # Note: the number of retries is as same as run_integration_tests'.
        # cf) suite_runner.py.
        '--chrome-flakiness-retry=2',
        '--iteration-lock-file=%s' % self._iteration_lock_file]
    if self._remote:
      args.extend([
          '--remote=%s' % self._remote,
          '--remote-arc-dir-name=arc%d' % self._instance_id])
      if self._instance_id > 0:
        args.append('--no-remote-machine-setup')
    args.extend(self._launch_chrome_opts)

    # Remove the lock file in case it's left.
    self._remove_iteration_lock_file()

    # Run ./launch_chrome from a dedicated thread.
    self._thread = _InteractivePerfTestLaunchChromeThread(
        'InteractivePerfTestLaunchChromeThread-%d' % self._instance_id,
        args, cwd=self._arc_root)
    self._thread.start()

    # Process a warmup run.
    self.run()

  def run(self):
    """Runs a perftest iteration.

    Returns:
      VRAWPERF dictionary scraped from launch_chrome output.
    """
    assert self._thread, 'InteractivePerfTestRunner has not been started.'
    # Wait until launch_chrome gets ready for an iteration.
    self._thread.wait_iteration_ready()

    # Remove the lock file so launch_chrome starts an iteration.
    self._remove_iteration_lock_file()

    # Watch the output to scrape VRAWPERF.
    return self._thread.read_vrawperf()

  def close(self):
    """Terminates launch_chrome."""
    if not self._thread:
      return

    # Terminates ./launch_chrome process, which eventually terminates
    # the dedicated thread.
    self._thread.terminate()
    self._thread.join()
    self._thread = None

  def _remove_iteration_lock_file(self):
    """Removes the iteration lock file, possibly on remote machine."""
    if self._remote:
      args = [
          'ssh',
          '-o', 'StrictHostKeyChecking=no',
          '-o', 'UserKnownHostsFile=/dev/null',
          '-o', 'PasswordAuthentication=no',
          '-o', 'ControlMaster=auto',
          '-o', 'ControlPersist=60s',
          '-o', 'ControlPath=%s' % _SSH_CONTROL_PATH,
          '-i', _TEST_SSH_KEY,
          'root@%s' % self._remote]
      os.chmod(os.path.join(self._arc_root, _TEST_SSH_KEY), 0600)
    else:
      args = ['bash', '-c']
    args.append('rm -f "%s"' % self._iteration_lock_file)
    logging.info('$ %s',
                 logging_util.format_commandline(args, cwd=self._arc_root))
    subprocess.check_call(args, cwd=self._arc_root)


def merge_perfs(a, b):
  """Merges two VRAWPERF dictionaries."""
  for key, values in b.iteritems():
    a[key].extend(values)


def bootstrap_sample(sample):
  """Performs Bootstrap sampling.

  Args:
    sample: A sample as a list of numbers.

  Returns:
    A Bootstrap sample as a list of numbers. The size of the returned Bootstrap
    sample is equal to that of the original sample.
  """
  return [random.choice(sample) for _ in sample]


def bootstrap_estimation(
    ctrl_sample, expt_sample, statistic, confidence_level):
  """Estimates confidence interval of difference of a statistic by Bootstrap.

  Args:
    ctrl_sample: A control sample as a list of numbers.
    expt_sample: An experiment sample as a list of numbers.
    statistic: A function that computes a statistic from a sample.
    confidence_level: An integer that specifies requested confidence level
        in percentage, e.g. 90, 95, 99.

  Returns:
    Estimated range as a number tuple.
  """
  bootstrap_distribution = []
  for _ in xrange(1000):
    bootstrap_distribution.append(
        statistic(bootstrap_sample(expt_sample)) -
        statistic(bootstrap_sample(ctrl_sample)))
  return statistics.compute_percentiles(
      bootstrap_distribution, (100 - confidence_level, confidence_level))


def handle_stash(parsed_args):
  """The entry point for stash command.

  Args:
    parsed_args: An argparse.Namespace object.
  """
  arc_root = get_abs_arc_root()
  stash_root = get_abs_stash_root()

  check_current_configure_options(parsed_args)

  options = load_configure_options(arc_root)
  logging.info('options: %s', options)
  if parsed_args.run_ninja:
    build_common.run_ninja()

  # See FILTER RULES section in rsync manpages for syntax.
  rules_text = """
  # No git repo.
  - .git/
  # Artifacts for the target arch and common.
  + /{out}/target/{target}/runtime/
  + /{out}/target/{target}/unittest_info/
  - /{out}/target/{target}/*
  + /{out}/target/{target}/
  + /{out}/target/common/
  - /{out}/target/*
  - /{out}/staging/
  # No internal-apks build artifacts.
  - /{out}/gms-core-build/
  - /{out}/google-contacts-sync-adapter-build/
  + /{out}/
  + /src/
  # aapt etc.
  + /third_party/android-sdk/
  # ninja etc.
  + /third_party/tools/ninja/
  + /third_party/tools/crosutils/mod_for_test_scripts/ssh_keys/
  - /third_party/tools/crosutils/mod_for_test_scripts/*
  + /third_party/tools/crosutils/mod_for_test_scripts/
  - /third_party/tools/crosutils/*
  + /third_party/tools/crosutils/
  - /third_party/tools/*
  + /third_party/tools/
  - /third_party/*
  + /third_party/
  + /launch_chrome
  - /*
  """.format(
      out=build_common.OUT_DIR,
      target=build_common.get_target_dir_name())

  rules = []
  for line in rules_text.strip().splitlines():
    line = line.strip()
    if line and not line.startswith('#'):
      rules.append(line)

  args = ['rsync', '-a', '--delete', '--delete-excluded', '--copy-links']
  if parsed_args.verbose:
    args.append('-v')
  args.extend(['--filter=%s' % rule for rule in rules])
  # A trailing dot is required to make rsync work as we expect.
  args.extend([os.path.join(arc_root, '.'), stash_root])

  logging.info(
      'running rsync to copy the arc tree to %s. please be patient...',
      stash_root)
  subprocess.check_call(args)

  logging.info('stashed the arc tree at %s.', stash_root)


def handle_clean(parsed_args):
  """The entry point for clean command.

  Args:
    parsed_args: An argparse.Namespace object.
  """
  args = ['rm', '-rf', get_abs_stash_root()]
  logging.info('running: %s', ' '.join(args))
  subprocess.check_call(args)


def handle_compare(parsed_args):
  """The entry point for compare command.

  Args:
    parsed_args: An argparse.Namespace object.
  """
  expt_root = get_abs_arc_root()
  ctrl_root = get_abs_stash_root()

  if not os.path.exists(ctrl_root):
    sys.exit('%s not found; run "interleaved_perftest.py stash" first to save '
             'control binaries' % ctrl_root)

  check_current_configure_options(parsed_args)

  ctrl_options = load_configure_options(ctrl_root)
  expt_options = load_configure_options(expt_root)

  logging.info('iterations: %d', parsed_args.iterations)
  logging.info('ctrl_options: %s', ctrl_options)
  logging.info('expt_options: %s', expt_options)

  if parsed_args.run_ninja:
    build_common.run_ninja()

  launch_chrome_opts = []
  if parsed_args.verbose:
    launch_chrome_opts.append('--verbose')
  launch_chrome_opts.extend(parsed_args.launch_chrome_opt)

  ctrl_runner = InteractivePerfTestRunner(
      arc_root=ctrl_root,
      remote=parsed_args.remote,
      launch_chrome_opts=launch_chrome_opts,
      instance_id=0)
  expt_runner = InteractivePerfTestRunner(
      arc_root=expt_root,
      remote=parsed_args.remote,
      launch_chrome_opts=launch_chrome_opts,
      instance_id=1)

  with contextlib.closing(ctrl_runner), contextlib.closing(expt_runner):
    ctrl_runner.start()
    expt_runner.start()

    ctrl_perfs = collections.defaultdict(list)
    expt_perfs = collections.defaultdict(list)

    def do_ctrl():
      merge_perfs(ctrl_perfs, ctrl_runner.run())

    def do_expt():
      merge_perfs(expt_perfs, expt_runner.run())

    for iteration in xrange(parsed_args.iterations):
      print
      print '=================================== iteration %d/%d' % (
          iteration + 1, parsed_args.iterations)
      for do in random.sample((do_ctrl, do_expt), 2):
        do()

  print
  print 'VRAWPERF_CTRL=%r' % dict(ctrl_perfs)  # Convert from defaultdict.
  print 'VRAWPERF_EXPT=%r' % dict(expt_perfs)  # Convert from defaultdict.
  print
  print 'PERF=runs=%d CI=%d%%' % (
      parsed_args.iterations, parsed_args.confidence_level)
  if expt_options == ctrl_options:
    print '     configure_opts=%s' % expt_options
  else:
    print '     configure_opts=%s (vs. %s)' % (expt_options, ctrl_options)
  print '     launch_chrome_opts=%s' % ' '.join(parsed_args.launch_chrome_opt)

  def _print_metric(prefix, key, unit, frac_digits=0):
    def format_frac(k, sign=False):
      format_string = '%'
      if sign:
        format_string += '+'
      format_string += '.%d' % frac_digits
      format_string += 'f'
      return (format_string % k) + unit
    ctrl_sample = ctrl_perfs[key]
    expt_sample = expt_perfs[key]
    ctrl_median = statistics.compute_median(ctrl_sample)
    expt_median = statistics.compute_median(expt_sample)
    diff_estimate_lower, diff_estimate_upper = (
        bootstrap_estimation(
            ctrl_sample, expt_sample,
            statistics.compute_median,
            parsed_args.confidence_level))
    if diff_estimate_upper < 0:
      significance = '[--]'
    elif diff_estimate_lower > 0:
      significance = '[++]'
    else:
      significance = '[not sgfnt.]'
    print '     %s: ctrl=%s, expt=%s, diffCI=(%s,%s) %s' % (
        prefix,
        format_frac(ctrl_median),
        format_frac(expt_median),
        format_frac(diff_estimate_lower, sign=True),
        format_frac(diff_estimate_upper, sign=True),
        significance)

  _print_metric('boot', 'boot_time_ms', 'ms')
  _print_metric('  preEmbed', 'pre_embed_time_ms', 'ms')
  _print_metric('  pluginLoad', 'plugin_load_time_ms', 'ms')
  _print_metric('  onResume', 'on_resume_time_ms', 'ms')
  _print_metric('virt', 'app_virt_mem', 'MB', frac_digits=1)
  _print_metric('res', 'app_res_mem', 'MB', frac_digits=1)
  _print_metric('pdirt', 'app_pdirt_mem', 'MB', frac_digits=1)

  print '     (see go/arcipt for how to interpret these numbers)'


def main():
  OPTIONS.parse_configure_file()
  parsed_args = _parse_args(sys.argv[1:])
  logging_util.setup(
      level=logging.DEBUG if parsed_args.verbose else logging.INFO)
  return parsed_args.entrypoint(parsed_args)


if __name__ == '__main__':
  sys.exit(main())
