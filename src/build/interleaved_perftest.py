#!/usr/bin/python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import ast
import collections
import logging
import os
import random
import re
import subprocess
import sys

import build_common
from build_options import OPTIONS
import filtered_subprocess
from util import statistics

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
      '--launch-chrome-opt', action='append', default=[], metavar='OPTIONS',
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

  logging.basicConfig(
      level=logging.DEBUG if parsed_args.verbose else logging.INFO)

  return parsed_args


def load_and_check_configure_options(arc_root, parsed_args):
  """Checks if configure options is good for comparison.

  Args:
    arc_root: A path to ARC root directory.
    parsed_args: An argparse.Namespace object.

  Returns:
    Configure options as a string.
  """
  with open(os.path.join(
      arc_root, build_common.OUT_DIR, 'configure.options')) as f:
    options = f.read().strip()

  # Require --opt build.
  if (not parsed_args.allow_debug_builds and
      not ('--official-build' in options or '--opt' in options)):
    sys.exit(
        'configure option bad: either --opt or --official-build '
        'must be specified. If you want to compare debug builds, '
        'please use --allow-debug-builds.')

  return options


class InteractivePerfTestOutputHandler(object):
  """Output handler for InteractivePerfTestRunner."""

  def __init__(self, runner):
    self._runner = runner

  def handle_stdout(self, text):
    sys.stdout.write(text)
    sys.stdout.flush()
    return self._handle_common(text)

  def handle_stderr(self, text):
    sys.stderr.write(text)
    sys.stderr.flush()
    return self._handle_common(text)

  def _handle_common(self, text):
    m = re.search(r'VRAWPERF=(.*)', text)
    if m:
      self._runner._on_perf(ast.literal_eval(m.group(1)))
    m = re.search(r'waiting for next iteration', text)
    if m:
      self._runner._on_ready()

  def handle_timeout(self):
    pass

  def is_done(self):
    return False


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
    self._iteration_lock_file = '/var/tmp/iteration-lock-arc%d' % instance_id
    self._process = None
    self._process_generator = None

  def start(self):
    """Starts launch_chrome script and performs warmup.

    If instance_id is 0, launch_chrome script will also do extra setup if
    it's running on remote machine.
    """
    assert not self._process
    args = [
        './launch_chrome',
        'perftest',
        # We set the number of iterations to arbitrary large number and
        # terminate the instance by signals.
        '--iterations=99999999',
        '--noninja',
        '--use-temporary-data-dirs',
        '--iteration-lock-file=%s' % self._iteration_lock_file]
    if self._remote:
      args.extend([
          '--remote=%s' % self._remote,
          '--remote-arc-dir-name=arc%d' % self._instance_id])
      if self._instance_id > 0:
        args.append('--no-remote-machine-setup')
    args.extend(self._launch_chrome_opts)

    self._process = filtered_subprocess.Popen(args, cwd=self._arc_root)
    self._process_generator = (
        self._process.run_process_filtering_output_generator(
            InteractivePerfTestOutputHandler(self)))

    # Remove the lock file in case it's left.
    self._remove_iteration_lock_file()
    self._iteration_ready = False

    # Process a warmup run.
    self.run()

  def run(self):
    """Runs a perftest iteration.

    Returns:
      VRAWPERF dictionary scraped from launch_chrome output.
    """
    # Wait until launch_chrome gets ready for an iteration.
    while not self._iteration_ready:
      self._process_generator.next()
    self._iteration_ready = False

    # Remove the lock file so launch_chrome starts an iteration.
    self._remove_iteration_lock_file()

    # Watch the output to scrape VRAWPERF.
    self._last_perf = None
    while not self._last_perf:
      self._process_generator.next()
    return self._last_perf

  def close(self):
    """Terminates launch_chrome."""
    self._process.terminate()
    while True:
      try:
        self._process_generator.next()
      except StopIteration:
        break
    self._process = None
    self._process_generator = None

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
    build_common.log_subprocess_popen(args, cwd=self._arc_root)
    subprocess.check_call(args, cwd=self._arc_root)

  def _on_perf(self, perf):
    """Called back from output handler to notify VRAWPERF is scraped."""
    self._last_perf = perf

  def _on_ready(self):
    """Called back from output handler to notify launch_chrome is ready."""
    self._iteration_ready = True


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

  options = load_and_check_configure_options(arc_root, parsed_args)
  logging.info('options: %s', options)
  if parsed_args.run_ninja:
    build_common.run_ninja()

  # See FILTER RULES section in rsync manpages for syntax.
  rules_text = """
  # No git repo.
  - .git/
  # Artifacts for the target arch and common.
  + /{out}/target/{target}/runtime/
  - /{out}/target/{target}/*
  + /{out}/target/{target}/
  + /{out}/target/common/
  - /{out}/target/*
  - /{out}/staging/
  + /{out}/
  + /src/
  # aapt etc.
  + /third_party/android-sdk/
  # ninja etc.
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

  args = ['rsync', '-av', '--delete', '--delete-excluded']
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

  ctrl_options = load_and_check_configure_options(ctrl_root, parsed_args)
  expt_options = load_and_check_configure_options(expt_root, parsed_args)

  logging.info('iterations: %d', parsed_args.iterations)
  logging.info('ctrl_options: %s', ctrl_options)
  logging.info('expt_options: %s', expt_options)

  if parsed_args.run_ninja:
    build_common.run_ninja()

  ctrl_runner = InteractivePerfTestRunner(
      arc_root=ctrl_root,
      remote=parsed_args.remote,
      launch_chrome_opts=parsed_args.launch_chrome_opt,
      instance_id=0)
  expt_runner = InteractivePerfTestRunner(
      arc_root=expt_root,
      remote=parsed_args.remote,
      launch_chrome_opts=parsed_args.launch_chrome_opt,
      instance_id=1)

  ctrl_runner.start()
  expt_runner.start()

  ctrl_perfs = collections.defaultdict(list)
  expt_perfs = collections.defaultdict(list)

  for iteration in xrange(parsed_args.iterations):
    print '*** iteration %d/%d ***' % (iteration + 1, parsed_args.iterations)
    merge_perfs(ctrl_perfs, ctrl_runner.run())
    merge_perfs(expt_perfs, expt_runner.run())

  ctrl_runner.close()
  expt_runner.close()

  print
  print 'VRAWPERF_CTRL=%r' % dict(ctrl_perfs)  # Convert from defaultdict.
  print 'VRAWPERF_EXPT=%r' % dict(expt_perfs)  # Convert from defaultdict.
  print
  print 'PERF=runs:%d CI:%d%%' % (
      parsed_args.iterations, parsed_args.confidence_level)
  if expt_options == ctrl_options:
    print '     configure_opts:%s' % expt_options
  else:
    print '     configure_opts:%s (vs. %s)' % (expt_options, ctrl_options)
  print '     launch_chrome_opts:%s' % ' '.join(parsed_args.launch_chrome_opt)

  def _print_metric(prefix, key, unit):
    ctrl_sample = ctrl_perfs[key]
    expt_sample = expt_perfs[key]
    expt_estimate = statistics.compute_median(expt_sample)
    diff_estimate_lower, diff_estimate_upper = (
        bootstrap_estimation(
            ctrl_sample, expt_sample,
            statistics.compute_median,
            parsed_args.confidence_level))
    sign = ''
    if diff_estimate_upper < -0.5:
      sign = '[-]'
    if diff_estimate_lower > +0.5:
      sign = '[+]'
    print '     %s:%.0f%s (%+.0f%s, %+.0f%s) %s' % (
        prefix,
        expt_estimate, unit,
        diff_estimate_lower, unit,
        diff_estimate_upper, unit,
        sign)

  _print_metric('boot', 'boot_time_ms', 'ms')
  _print_metric('  preEmbed', 'pre_embed_time_ms', 'ms')
  _print_metric('  pluginLoad', 'plugin_load_time_ms', 'ms')
  _print_metric('  onResume', 'on_resume_time_ms', 'ms')
  _print_metric('virt', 'app_virt_mem', 'MB')
  _print_metric('res', 'app_res_mem', 'MB')


def main():
  OPTIONS.parse_configure_file()
  parsed_args = _parse_args(sys.argv[1:])
  return parsed_args.entrypoint(parsed_args)


if __name__ == '__main__':
  sys.exit(main())
