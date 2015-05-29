# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import shutil
import stat
import subprocess
import time

import build_common
from build_options import OPTIONS
import prep_launch_chrome
import staging
import toolchain
from util.test import scoreboard
from util.test import suite_runner
from util.test import system_mode
from util.test.test_method_result import TestMethodResult
from util import file_util


_NACL_FILTER_PATTERN = re.compile('|'.join(
    [r'^WARNING: SIGPIPE not blocked$',
     r'^linker:']))


_BARE_METAL_FILTER_PATTERN = re.compile('|'.join(
    [r'^WARNING: SIGPIPE not blocked$',
     r'^WARNING: linker: libdvm.so has text relocations.',
     r'^bm_loader:',
     r'^linker:']))


# The remote directory where test files are written.
_DEX_LOCATION = '/data/run-test'


def _cleanup_output(raw):
  if OPTIONS.is_nacl_build():
    filter_pattern = _NACL_FILTER_PATTERN
  elif OPTIONS.is_bare_metal_build():
    filter_pattern = _BARE_METAL_FILTER_PATTERN
  else:
    assert False, 'Must not reach here'
  lines = [line for line in raw.split('\n') if not filter_pattern.match(line)]
  return '\n'.join(lines)


class ArtTestRunner(suite_runner.SuiteRunnerBase):
  """A test runner for ART integration tests."""

  _SUITE_NAME_RE = re.compile(r'[0-9]+-\w+')

  def __init__(self, suite_name, config, **kwargs):
    """Constructs a ART test suite.

    Args:
      suite_name: ART test suite name (e.g. "008-exception").
      config: Suite config dictionary.
      **kwargs: Other constructor parameters passed through to SuiteRunnerBase.
    """
    self._suite_name = suite_name
    self._source_dir = os.path.join(self.get_source_root(), self._suite_name)
    self._work_dir = os.path.join(self.get_work_root(), self._suite_name)
    self._is_benchmark = os.path.exists(
        os.path.join(self._source_dir, 'README.benchmark'))

    self._case_args_map = {}  # Test case name -> [VM options]
    testcase_file = os.path.join(self._source_dir, 'test_cases')
    if not os.path.exists(testcase_file):
      self._case_args_map['Main'] = []
    else:
      # tests_cases contains VM arguments and VM options, separated by colon.
      with open(testcase_file) as stream:
        for line in stream:
          vm_args, vm_options = [s.strip() for s in line.split(':', 1)]
          self._case_args_map[vm_args] = vm_options.split()

    base_expectation_map = dict.fromkeys(self._case_args_map, config['flags'])
    super(ArtTestRunner, self).__init__(
        'art.' + suite_name, base_expectation_map, config=config, **kwargs)

  @staticmethod
  def list_suites():
    """Returns the list of available ART test suite names."""
    suite_names = []
    for suite_name in os.listdir(ArtTestRunner.get_source_root()):
      if ArtTestRunner._SUITE_NAME_RE.match(suite_name):
        suite_names.append(suite_name)
    return suite_names

  @staticmethod
  def get_source_root():
    """Returns the root directory of ART test source files."""
    return staging.as_staging('android/art/test')

  @staticmethod
  def get_work_root():
    """Returns the root directory of working files."""
    return os.path.join(build_common.get_target_common_dir(), 'art_tests')

  @staticmethod
  def setup_work_root():
    file_util.makedirs_safely(ArtTestRunner.get_work_root())

  def prepare(self, unused_test_methods_to_run):
    """Builds test jar files for a test."""
    shutil.rmtree(self._work_dir, ignore_errors=True)

    # Copy the source directory to the working directory.
    # Note that we must not copy the files by python's internal utilities
    # here, such as shutil.copy, or loops written manually, etc., because it
    # would cause ETXTBSY in run_subprocess called below if we run this
    # on multi-threading. Here is the senario:
    # Let there are two cases A, and B, and, to simplify, let what we do here
    # are 1) copying the "{A_src,B_src}/build" files to "{A,B}/build", and then
    # 2) fork() and execute() "{A,B}/build". Each will run on a different
    # threads, named thread-A and thread-B.
    # 1) on thread-A, "A_src/build" is copied to "A/build".
    # 2) on thread-B, "B_src/build" starts to be copied to "B/build". For that
    #    purpose, "B/build" is opened with "write" flag.
    # 3) on thread-A, the process is fork()'ed, *before the copy of "B/build"
    #    is completed. So, subprocess-A keeps the FD of "B/build" with "write".
    # 4) on thread-B, "B/build" is copied, and close()'ed, then fork()'ed.
    # 5) on subprocess-B, it tries to exec "B/build". However, the file is
    #    still kept opened by subprocess-A. As a result, ETXTBSY is reported.
    # Probably, the ideal solution would be that such an issue should be
    # handled by the framework (crbug.com/345667), but it seems to need some
    # more investigation. So, instead, we copy the files in another process.
    subprocess.check_call(['cp', '-Lr', self._source_dir, self._work_dir])

    build_script = os.path.abspath(os.path.join(self._work_dir, 'build'))
    if not os.path.isfile(build_script):
      # If not found, use the default-build script.
      # Note: do not use a python function here, such as shutil.copy directly.
      # See above comment for details.
      subprocess.check_call(
          ['cp', os.path.join(self.get_source_root(), 'etc', 'default-build'),
           build_script])
    # Ensure that the executable bit is set.
    os.chmod(build_script, stat.S_IRWXU)

    env = {
        'DX': 'dx',
        'NEED_DEX': 'true',
        'TEST_NAME': self._suite_name,
        'JAVAC': toolchain.get_tool('java', 'javac'),
        'PATH': ':'.join([
            os.path.join(build_common.get_arc_root(),
                         toolchain.get_android_sdk_build_tools_dir()),
            # Put PATH in the end to prevent shadowing previous path.
            os.environ['PATH']
        ])
    }
    subprocess.check_call([build_script], env=env, cwd=self._work_dir)

    args = self.get_system_mode_launch_chrome_command(self._name)
    prep_launch_chrome.prepare_crx_with_raw_args(args)

  def run(self, test_methods_to_run):
    # When this test runs through run_integraion_tests.py, ALL_TESTS_DUMMY_NAME
    # is passed as test_methods_to_run. Otherwise, e.g., perf_test.py,
    # specify a proper test name list.
    if test_methods_to_run == [scoreboard.Scoreboard.ALL_TESTS_DUMMY_NAME]:
      test_methods_to_run = sorted(self._case_args_map)

    for case_name in test_methods_to_run:
      output = None
      with system_mode.SystemMode(self) as arc:
        self._push_test_files(arc)
        begin_time = time.time()
        output = self._run_test(arc, case_name)
        elapsed_time = time.time() - begin_time

      # At this point, output can be None because evil SystemMode.__exit__()
      # quietly suppress an exception raised from SystemMode.run_adb()!
      if output is None:
        # In this case, arc.run_adb() should have recorded some logs
        # which will be retrieved by arc.get_log() later.
        result = TestMethodResult(case_name, TestMethodResult.FAIL)

      elif self._is_benchmark:
        self._logger.write(
            'Benchmark %s: %d ms\n' % (case_name, elapsed_time * 1000))
        result = TestMethodResult(case_name, TestMethodResult.PASS)

      else:
        result = self._check_output(case_name, output)

      self.get_scoreboard().update([result])

  def _push_test_files(self, arc):
    """Pushes test files via ADB.

    This function mimics the test preparation task performed in
    android/art/test/etc/push-and-run-test-jar.

    Args:
      arc: SystemMode object.
    """
    test_file = os.path.join(self._work_dir, '%s.jar' % self._suite_name)
    assert os.access(test_file, os.R_OK), (
        'can not read a test file %s' % test_file)
    arc.run_adb(['shell', 'mkdir', _DEX_LOCATION])
    arc.run_adb(['push', test_file, _DEX_LOCATION])
    test_ex_file = os.path.join(self._work_dir, '%s-ex.jar' % self._suite_name)
    if os.access(test_ex_file, os.R_OK):
      arc.run_adb(['push', test_ex_file, _DEX_LOCATION])

  def _run_test(self, arc, case_name):
    """Runs the test case.

    This function mimics the test execution task performed in
    android/art/test/etc/push-and-run-test-jar.

    Args:
      arc: SystemMode object.
      case_name: Test case name.
    """
    jars = [
        '/system/framework/%s' % jar
        for jar in ('core.jar', 'ext.jar', 'framework.jar')]
    vm_args = [
        '-Xbootclasspath:%s' % ':'.join(jars),
        '-ea',
        # TODO(crbug.com/473456): Remove when patchoat is fixed.
        '-Xnorelocate',
        '-cp', '/data/run-test/%s.jar' % self._suite_name]
    if not OPTIONS.enable_art_aot:
      vm_args.extend(['-Xint', '-Xnoimage-dex2oat'])
    vm_args.extend(self._case_args_map[case_name])
    # The case name is actually extra arguments passed to VM.
    vm_args.extend(case_name.split())

    commands = [
        ['cd', _DEX_LOCATION],
        ['export', 'DEX_LOCATION=%s' % _DEX_LOCATION],
        ['dalvikvm'] + vm_args,
    ]

    adb_args = ['shell']
    for command in commands:
      adb_args += command + [';']

    # Many ART tests assume stdout and stderr are written to the same output
    # in order.
    return arc.run_adb(adb_args, stderr=subprocess.STDOUT)

  def _check_output(self, case_name, output):
    """Inspects the output of the test run and determines if a test passed.

    Args:
      case_name: The test case name.
      output: The raw output string of the test case.

    Returns:
        A TestMethodResult object.
    """
    output_file_path = os.path.join(self._work_dir, 'output.txt')
    with open(output_file_path, 'w') as output_file:
      output_file.write(_cleanup_output(output))
    expected_file_path = os.path.join(self._source_dir, 'expected.txt')

    # We diff the output against expected, ignoring whitespace,
    # as the output file comes from running adb in ARC and so
    # has \r\n instead of just \n.
    try:
      self.run_subprocess(
          ['diff', '-b', output_file_path, expected_file_path],
          omit_xvfb=True)
    except subprocess.CalledProcessError:
      result = TestMethodResult(case_name, TestMethodResult.FAIL)
    else:
      result = TestMethodResult(case_name, TestMethodResult.PASS)

    return result
