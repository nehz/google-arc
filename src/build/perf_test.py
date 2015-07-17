#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Runs performance tests, storing the result for submitting.  This script is
actually a driver class to:

  1. performs different types of performance test,
  2. captures the output of launch_chrome.py,
  3. post the measurement to a file based queue.

Example to run supported tests:

  # Standard perftest:
  $ perf_test.py standard
"""

import argparse
import contextlib
import os
import logging
import re
import subprocess
import sys

import dashboard_submit
import run_integration_tests
from build_options import OPTIONS
from ninja_generator import ApkFromSdkNinjaGenerator
from util import concurrent_subprocess
from util import launch_chrome_util
from util import logging_util
from util import remote_executor
from util.test import art_test_runner
from util.test import suite_runner
from util.test import suite_runner_config_flags as flags

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ARC_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))

_OUTPUT_LOG_FILE = os.path.join('out', 'perf.log')

_PACKAGE_NAME_RE = re.compile(r"package: name='([^']+)'")
_PERF_LINE_RE = re.compile(
    r'PERF=boot:(?P<total>\d+)ms \(preEmbed:(?P<pre_embed_time>\d+)ms \+ '
    r'pluginLoad:(?P<plugin_load_time>\d+)ms \+ '
    r'onResume:(?P<on_resume_time>\d+)ms\),\n'
    r'     virt:(?P<virt_mem>[\d.]+)MB, res:(?P<res_mem>[\d.]+)MB, '
    r'pdirt:(?P<pdirt_mem>[\d.]+)MB, runs:\d+',
    re.MULTILINE)
_WARM_UP_RE = re.compile(
    r'WARM-UP (?P<first_boot_total>\d+) '
    r'(?P<first_boot_pre_embed_time>\d+) '
    r'(?P<first_boot_plugin_load_time>\d+) '
    r'(?P<first_boot_on_resume_time>\d+)')
_BENCHMARK_RESULT_RE = re.compile(
    r'Benchmark (?P<name>[^:]+):(?P<time_ms>.+) ms')

_OUTPUT_DUMP_FORMAT = """
*** STDOUT and STDERR ***
%s

*** END ***
"""


class InvalidResultError(Exception):
  """Exception class raised in this module on unexpected results."""


def _queue_data(args, label, unit, data):
  dashboard_submit.queue_data(label, unit, data)
  print label
  for key, value in data.iteritems():
    print '  %s : %s %s' % (key, value, unit)


def _prepare_integration_tests_args(min_deadline):
  args = run_integration_tests.parse_args([])
  args.min_deadline = min_deadline
  return args


class BaseDriver(object):
  def __init__(self, args):
    self._args = args

  def _run(self, args, **kargs):
    logging.debug('>>> %s' % (' '.join(args)))
    with open(_OUTPUT_LOG_FILE, 'w') as f:
      subprocess.call(args,
                      stdout=f,
                      stderr=subprocess.STDOUT,
                      **kargs)

  def _perftest(self, args=None):
    if args is None:
      args = []
    if self._args.verbose:
      args.append('-v')
    remote_executor.copy_remote_arguments(self._args, args)
    self._run(launch_chrome_util.get_launch_chrome_command([
        'perftest',
        '--noninja',
        '--iterations=' + str(self._args.iterations)
    ] + args))

  def _atftest(self, args=None):
    if not args:
      raise Exception("At least one parameter needed for atftest")
    if self._args.verbose:
      args.append('-v')
    remote_executor.copy_remote_arguments(self._args, args)
    self._run(launch_chrome_util.get_launch_chrome_command([
        'atftest',
        '--noninja',
    ] + args))

  def _load_output(self):
    with open(_OUTPUT_LOG_FILE, 'r') as f:
      return f.read()

  def _parse_output(self, output):
    data = {}

    match = _WARM_UP_RE.search(output)
    if match is None:
      logging.error('WARM-UP is missing')
      return None
    data.update(match.groupdict())

    match = _PERF_LINE_RE.search(output)
    if match is None:
      logging.error('PERF= is missing')
      return None
    data.update(match.groupdict())

    # Convert from string to int/float
    for k, v in data.items():
      if k.endswith('_mem'):
        data[k] = float(v)
      else:
        data[k] = int(v)

    return data


class PerfDriver(BaseDriver):
  def __init__(self, args, enable_play_services=False):
    super(PerfDriver, self).__init__(args)
    self._enable_play_services = enable_play_services

  def main(self):
    args = []

    if self._enable_play_services:
      variant = '+play_services'
      # Enable minimum service as baseline
      args += ['--additional-metadata', '{"usePlayServices": ["gcm"]}']
    else:
      variant = ''

    if self._args.test_mode:
      output = self._load_output()
    else:
      if OPTIONS.is_nacl_build():
        # Enable to allow collecting memory usage on NaCl
        args += ['--enable-nacl-list-mappings']
      self._perftest(args)
      output = self._load_output()
      logging.debug(_OUTPUT_DUMP_FORMAT % output)

    data = self._parse_output(output)
    if data:
      self._post(data, variant)
    else:
      logging.error(_OUTPUT_DUMP_FORMAT % output)
      sys.exit(-1)

  def _post(self, data, suffix):
    _queue_data(self._args, 'first_boot_time', 'ms', {
        'pre_embed_time' + suffix: data['first_boot_pre_embed_time'],
        'plugin_load_time' + suffix: data['first_boot_plugin_load_time'],
        'on_resume_time' + suffix: data['first_boot_on_resume_time'],
        'total' + suffix: data['first_boot_total']
    })
    _queue_data(self._args, 'boot_time', 'ms', {
        'pre_embed_time' + suffix: data['pre_embed_time'],
        'plugin_load_time' + suffix: data['plugin_load_time'],
        'on_resume_time' + suffix: data['on_resume_time'],
        'total' + suffix: data['total']
    })
    _queue_data(self._args, 'mem_usage', 'MB', {
        'virt_mem' + suffix: data['virt_mem'],
        'res_mem' + suffix: data['res_mem'],
        'pdirt_mem' + suffix: data['pdirt_mem']
    })


class PerfDriverWithPlayServices(PerfDriver):
  def __init__(self, args):
    super(PerfDriverWithPlayServices, self).__init__(args, True)


class _AccumulateOutputHandler(concurrent_subprocess.OutputHandler):
  """Output handler to accumulate the outputs from the subprocess.

  This accumulates all output from both subprocess's stdout and stderr into
  |self.accumulated_output|.
  """
  def __init__(self, end_pattern):
    """Initializes the handler.

    Args:
      end_pattern: termination message from the subprocess. Once this message is
          observed, is_done() starts to return True.
    """
    self.accumulated_output = []
    self._end_pattern = end_pattern
    self._done = False

  def _handle_output(self, line):
    if self._end_pattern in line:
      self._done = True
    self.accumulated_output.append(line)

  def handle_stdout(self, line):
    self._handle_output(line)

  def handle_stderr(self, line):
    self._handle_output(line)

  def handle_timeout(self):
    logging.error('Unexpected timeout')

  def is_done(self):
    return self._done


class GLPerfDriver(BaseDriver):
  _PEPPER_BENCH_DIR = 'mods/examples/PepperPerf'
  _BENCH_TIME_RE = re.compile(
      r"^(?:E/GLPerf:\s+)?(.*?)\s+((?:\d+,)*(?:\d+)) \(us\)$")
  _BENCH_TARGET_MAP = {
      'AndroidGL: TextureLoadTest128::TexImage2D': 'an-tex-128',
      'AndroidGL: TextureLoadTest512::TexImage2D': 'an-tex-512',
      'AndroidGL: TextureLoadTest2048::TexImage2D': 'an-tex-2048',
      'AndroidGL: BufferLoadTest10000::BufferDataLoad': 'an-vbo',
      'AndroidGL: BufferLoadTest10000::BufferDataLoad2': 'an-vbo-elem',

      'PepperGL: TextureLoadTest128::TexImage2D': 'pp-tex-128',
      'PepperGL: TextureLoadTest512::TexImage2D': 'pp-tex-512',
      'PepperGL: TextureLoadTest2048::TexImage2D': 'pp-tex-2048',
      'PepperGL: BufferLoadTest10000::BufferDataLoad': 'pp-vbo',
      'PepperGL: BufferLoadTest10000::BufferDataLoad2': 'pp-vbo-elem',
      # TODO(victorhsieh): is it possible to benchmark page flip on Android?
      # 'PepperGL: PageflipBenchmarkTest::RenderAsOnlyApp': 'pp-flip',
      # 'PepperGL: PageflipBenchmarkTest::RenderAsAppWithFrameworkCompositing':
      #    'pp-flip-comp',
  }
  _TIMEOUT = 30

  def __init__(self, args):
    super(GLPerfDriver, self).__init__(args)

  # TODO(crbug.com/315873): currently the new chrome processes (which are
  # spawned by launch_chrome, spawned here) don't get killed.  We need to get
  # this fixed before we start running this test on buildbot.
  def main(self):
    output = self._run_pepper_perf()
    results = self._parse(output)
    self._post(results)

    self._build_gl_perf_apk()
    output = self._run_arc_perf()
    results = self._parse(output)
    self._post(results)

  def _run_pepper_perf(self):
    return self._accumulate_subprocess_output(
        ['make', 'runbench'],
        '-------- FINISHED --------',
        cwd=GLPerfDriver._PEPPER_BENCH_DIR)

  def _run_arc_perf(self):
    return self._accumulate_subprocess_output(
        launch_chrome_util.get_launch_chrome_command(
            ['run', 'mods/examples/PepperPerf/android/bin/GLPerf-debug.apk']),
        '--------------- END ---------------')

  def _accumulate_subprocess_output(self, command, end_pattern, **kwargs):
    output_handler = _AccumulateOutputHandler(end_pattern)
    p = concurrent_subprocess.Popen(
        command, timeout=GLPerfDriver._TIMEOUT, **kwargs)
    p.handle_output(output_handler)
    return output_handler.accumulated_output

  def _build_gl_perf_apk(self):
    return self._run(
        ['ant',
         '-Dsdk.dir=' + os.path.join(_ARC_ROOT, 'third_party/android-sdk'),
         '-Dndk.dir=' + os.path.join(_ARC_ROOT, 'third_party/ndk'),
         'debug'],
        cwd=os.path.join(GLPerfDriver._PEPPER_BENCH_DIR, 'android'))

  def _parse(self, lines):
    data = {}
    for line in lines:
      match = GLPerfDriver._BENCH_TIME_RE.search(line)
      if not match:
        continue

      shortname = GLPerfDriver._BENCH_TARGET_MAP.get(match.group(1))
      if shortname:
        data[shortname] = int(match.group(2).replace(',', ''))
    return data

  def _post(self, data):
    _queue_data(self._args, 'gl_perf', 'us', data)


class VMPerfDriver(BaseDriver):
  def __init__(self, args):
    super(VMPerfDriver, self).__init__(args)

  def _run(self, benchmark):
    runner = art_test_runner.ArtTestRunner('901-perf',
                                           config={'flags': flags.PASS})
    args = _prepare_integration_tests_args(100)

    # We reuse scripts for integration tests in vm tests, and they expect
    # that out/integration_tests exists. It is true if integration tests ran
    # before calling perf_test.py, but not true for perf builders.
    # Let's create it if it does not exist.
    run_integration_tests.setup_output_directory(args.output_dir)

    # Call setup_work_root() and prepare_to_run() iff source files
    # to build tests exist. Perf builders do not have them, and can skip it.
    # The builders have downloaded pre-built files.
    if os.path.exists(os.path.join(runner.get_source_root(), 'etc')):
      runner.setup_work_root()
      runner.prepare_to_run([], args)

    with contextlib.closing(suite_runner.SuiteRunnerLogger(
        runner.name,
        os.path.join(args.output_dir, runner.name),
        False)) as logger:
      runner.run_with_setup([benchmark], args, logger)
    with open(logger.path) as f:
      for line in f:
        # Result line format is 'Benchmark <name>: <result> ms'.
        match = _BENCHMARK_RESULT_RE.match(line)
        if not match or match.group(1) != benchmark:
          continue
        return match.group(2)
    raise InvalidResultError(benchmark)

  def main(self):
    results = {}
    for benchmark in ['GCBench', 'ackermann 9', 'fibo 36', 'heapsort 70000',
                      'matrix 10000', 'nestedloop 15', 'random 300000',
                      'sieve 10000']:
      result = self._run(benchmark)
      results[benchmark] = int(result)
    _queue_data(self._args, 'vm_benchmarks', 'ms', results)


class ApkBenchDriver(BaseDriver):
  """Run APK via ATF for performance benchmarks.

  They should output test results in standard output in the following form
  Benchmark [name]: [time_ms] ms
  """
  # TODO(crbug.com/374687): Add other APKs we want to measure
  # performance continuously.

  def __init__(self, args):
    super(ApkBenchDriver, self).__init__(args)

  def _parse_output(self, output):
    data = {}
    for line in output.splitlines():
      match = _BENCHMARK_RESULT_RE.search(line)
      if match:
        matches = match.groupdict()
        data[matches['name']] = int(float(matches['time_ms']))
    return data

  def _post(self, data):
    _queue_data(self._args, 'apk_bench', 'ms', data)

  def main(self):
    self._atftest([
        ApkFromSdkNinjaGenerator.get_install_path_for_module(
            'perf_tests_codec'),
        # On bare_metal_arm target, this test takes about 200 seconds
        # to complete.
        '--timeout=400'])
    output = self._load_output()
    logging.debug(output)
    data = self._parse_output(output)
    if data:
      self._post(data)
    else:
      raise InvalidResultError(output)


_TEST_CLASS_MAP = {
    'standard': PerfDriver,
    'standard+play': PerfDriverWithPlayServices,
    'gl': GLPerfDriver,
    'vm': VMPerfDriver,
    'apkbench': ApkBenchDriver,
}


def create_test_class(name):
  if name not in _TEST_CLASS_MAP:
    raise Exception('Unknown type of perf test: ' + name)
  return _TEST_CLASS_MAP[name]


def main():
  OPTIONS.parse_configure_file()
  parser = argparse.ArgumentParser(
      description=__doc__,
      formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('mode', choices=_TEST_CLASS_MAP.keys())
  parser.add_argument('--iterations', default=20, type=int,
                      help=('Number of iterations to run after warmup phase. '
                            'The default is 20.'))
  parser.add_argument('--test-mode', action='store_true',
                      help='Test mode. Parse %s and exit.' % _OUTPUT_LOG_FILE)
  parser.add_argument('--verbose', '-v', action='store_true',
                      help='Verbose mode')

  remote_executor.add_remote_arguments(parser)

  args = parser.parse_args()
  remote_executor.maybe_detect_remote_host_type(args)
  logging_util.setup(level=logging.DEBUG if args.verbose else logging.WARNING)

  clazz = create_test_class(args.mode)
  clazz(args).main()


if __name__ == '__main__':
  sys.exit(main())
