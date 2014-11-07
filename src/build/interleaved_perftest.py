#!/usr/bin/python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import ast
import atexit
import collections
import logging
import os
import random
import re
import subprocess
import sys
import tempfile

import build_common
from build_options import OPTIONS
from util import statistics

# Prefixes for stash directories.
_STASH_DIR_PREFIX = '.stash'


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


def load_and_check_configure_options(arc_root):
  """Checks if configure options is good for comparison.

  Args:
    arc_root: A path to ARC root directory.

  Returns:
    Configure options as a string.
  """
  with open(os.path.join(
      arc_root, build_common.OUT_DIR, 'configure.options')) as f:
    options = f.read().strip()

  # Require --opt build.
  if not ('--official-build' in options or '--opt' in options):
    sys.exit('configure option bad: either --opt or --official-build '
             'must be specified')

  return options


def run_perftest(arc_root, user_data_dir, parsed_args, cache_warming=False):
  """Runs launch_chrome perftest and scrapes the PERF result.

  Args:
    arc_root: A path to ARC root directory.
    user_data_dir: A path to the user data directory.
    parsed_args: An argparse.Namespace object.
    cache_warming: Whether this is a cache-warming run.

  Returns:
    A VRAWPERF dictionary.
  """
  args = [
      './launch_chrome',
      'perftest',
      '--iterations=1',
      '--noninja',
      '--user-data-dir=%s' % user_data_dir,
  ]
  # Let launch_chrome perftest do cache-warming run that saves NaCl
  # validation cache.
  if not cache_warming:
    args.append('--no-cache-warming')
  args.extend(parsed_args.launch_chrome_opt)

  for _ in xrange(3):  # Retry up to 3 times for transient failures.
    logging.debug('cd %s; %s', arc_root, ' '.join(args))
    try:
      output = subprocess.check_output(args, cwd=arc_root)
      break
    except subprocess.CalledProcessError as e:
      logging.error(
          'launch_chrome perftest failed with returncode=%d. retrying.',
          e.returncode)
  else:
    sys.exit('all attempts failed.')

  # Scrape VRAWPERF from launch_chrome output.
  m = re.search(r'VRAWPERF=(.*)', output)
  if not m:
    sys.exit('launch_chrome did not output VRAWPERF.\n' + output)
  perf = ast.literal_eval(m.group(1))
  logging.debug('VRAWPERF=%r', perf)
  return perf


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

  options = load_and_check_configure_options(arc_root)
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

  ctrl_options = load_and_check_configure_options(ctrl_root)
  expt_options = load_and_check_configure_options(expt_root)

  logging.info('iterations: %d', parsed_args.iterations)
  logging.info('ctrl_options: %s', ctrl_options)
  logging.info('expt_options: %s', expt_options)

  if parsed_args.run_ninja:
    build_common.run_ninja()

  ctrl_user_data_dir = tempfile.mkdtemp(
      prefix=build_common.CHROME_USER_DATA_DIR_PREFIX + '-')
  expt_user_data_dir = tempfile.mkdtemp(
      prefix=build_common.CHROME_USER_DATA_DIR_PREFIX + '-')
  atexit.register(lambda: build_common.rmtree_with_retries(ctrl_user_data_dir))
  atexit.register(lambda: build_common.rmtree_with_retries(expt_user_data_dir))

  print '*** warming up ***'

  run_perftest(
      ctrl_root, ctrl_user_data_dir, parsed_args, cache_warming=True)
  run_perftest(
      expt_root, expt_user_data_dir, parsed_args, cache_warming=True)

  ctrl_perfs = collections.defaultdict(list)
  expt_perfs = collections.defaultdict(list)

  for iteration in xrange(parsed_args.iterations):
    print '*** iteration %d/%d ***' % (iteration + 1, parsed_args.iterations)
    merge_perfs(
        ctrl_perfs,
        run_perftest(ctrl_root, ctrl_user_data_dir, parsed_args))
    merge_perfs(
        expt_perfs,
        run_perftest(expt_root, expt_user_data_dir, parsed_args))

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
