# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import stat
import subprocess
import time
import traceback

import build_common
import prep_launch_chrome
import staging
import toolchain
from build_options import OPTIONS
from util import file_util
from util import platform_util
from util.test import suite_runner
from util.test import suite_runner_config_flags as flags
from util.test import system_mode
from util.test import test_method_result


_NACL_FILTER_PATTERN = re.compile('|'.join([
    r'^WARNING: SIGPIPE not blocked$',
    r'^linker:']))


_BARE_METAL_FILTER_PATTERN = re.compile('|'.join([
    r'^WARNING: SIGPIPE not blocked$',
    r'^WARNING: linker: libdvm.so has text relocations.',
    r'^bm_loader:',
    # TODO(crbug.com/406226): r'^libcxx: DANGER' should be removed once
    # ARC is rebased to L.
    r'^libcxx: DANGER',
    r'^linker:',
    # TODO(crbug.com/266627): This filter is
    # for temporary messages. Remove this.
    r'^nacl_irt_']))


def _cleanup_output(raw):
  if platform_util.is_running_on_cygwin():
    # TODO(crbug.com/355468): Normalize the newline characters.
    # If the root cause is inside ARC, text mode handling should be killed
    # in posix translation or dalvik runtime to be compatible with Linux.
    raw = raw.replace('\r\n', '\n')

  filter_pattern = None
  if OPTIONS.is_nacl_build():
    filter_pattern = _NACL_FILTER_PATTERN
  elif OPTIONS.is_bare_metal_build():
    filter_pattern = _BARE_METAL_FILTER_PATTERN
  if not filter_pattern:
    return raw
  lines = [line for line in raw.split('\n') if not filter_pattern.match(line)]
  return '\n'.join(lines)


class DalvikVMTestRunner(suite_runner.SuiteRunnerBase):
  """A test runner for running Dalvik VM tests."""

  DALVIK_TESTS_DIR = staging.as_staging('android/dalvik/tests')

  def __init__(self, test_name, **kwargs):
    test_source_dir = os.path.join(
        DalvikVMTestRunner.DALVIK_TESTS_DIR, test_name)

    # TODO(crbug.com/354354): Currently we cannot write an expectation
    # for a test which does not have a third level name, and need to
    # store the expectation manually.
    test_cases_file = os.path.join(test_source_dir, 'test_cases')
    if os.path.exists(test_cases_file):
      # If we have testcase file, it contains, "Java arguments" and "dalvik
      # VM options". We use "Java arguments" part as its name as is, although
      # it sometimes contains white spaces.
      with open(test_cases_file) as stream:
        test_arg_map = dict(line.split(':', 1) for line in stream)
    else:
      # There is no individual test case. So we name whole the test case as
      # "Main" here.
      test_arg_map = {'Main': ''}

    super(DalvikVMTestRunner, self).__init__(
        'dalvik.' + test_name,
        dict.fromkeys(test_arg_map.iterkeys(), flags.PASS),
        **kwargs)
    self._dalvik_test_name = test_name
    self._test_source_dir = test_source_dir
    self._test_dir = os.path.join(
        build_common.get_target_common_dir(), 'dalvik_tests', test_name)
    self._is_benchmark = os.path.exists(
        os.path.join(test_source_dir, 'README.benchmark'))
    self._test_arg_map = test_arg_map

  @staticmethod
  def setup_work_root():
    test_root = os.path.join(
        build_common.get_target_common_dir(), 'dalvik_tests')
    file_util.makedirs_safely(test_root)

  def _shell_args(self, class_extra_args, dalvik_extra_args):
    jars = ['/system/framework/' + jar for jar in ['core.jar',
                                                   'ext.jar',
                                                   'framework.jar']]
    execution_mode = 'jit' if OPTIONS.enable_dalvik_jit() else 'fast'
    classpath = ':'.join(jars)
    class_args = ['-cp', 'test.jar'] + class_extra_args.split()
    dalvik_args = ['-Xbootclasspath:' + classpath,
                   '-Xgc:precise',
                   '-Xgenregmap',
                   '-Xint:' + execution_mode,
                   '-ea'] + dalvik_extra_args.split() + class_args

    return ['shell', 'cd', '/data', ';', 'dalvikvm'] + dalvik_args

  def prepare(self, unused_test_methods_to_run):
    """Builds test jar files for a test."""
    test_dir = self._test_dir
    if os.path.exists(test_dir):
      file_util.rmtree(test_dir)

    # Copy the source directory to the working directory.
    # Note that we must not copy the files by python's internal utilities
    # here, such as shutil.copy, or loops written manually, etc., because it
    # would cause ETXTBSY in run_subprocess called below if we run this
    # on multi-threading. Here is the scenario:
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
    subprocess.check_call(['cp', '-Lr', self._test_source_dir, test_dir])

    build_script = os.path.abspath(os.path.join(test_dir, 'build'))
    if not os.path.isfile(build_script):
      # If not found, use the default-build script.
      # Note: do not use a python function here, such as shutil.copy directly.
      # See above comment for details.
      subprocess.check_call(
          ['cp',
           os.path.join(DalvikVMTestRunner.DALVIK_TESTS_DIR,
                        'etc', 'default-build'),
           build_script])
    # Ensure that the executable bit is set.
    os.chmod(build_script, stat.S_IRWXU)

    env = {
        'JAVAC': toolchain.get_tool('java', 'javac'),
        'PATH': ':'.join([
            os.environ['PATH'],
            # TODO(crbug.com/378196): We should remove canned/host/android/bin
            # from PATH when we remove the canned directory.
            os.path.join(build_common.get_arc_root(),
                         'canned', 'host', 'android', 'bin', 'linux-i686'),
            os.path.join(build_common.get_arc_root(),
                         toolchain.get_android_sdk_build_tools_dir())
        ])
    }

    self.run_subprocess([build_script], env=env, cwd=test_dir)

    args = self.get_system_mode_launch_chrome_command(self._name)
    prep_launch_chrome.prepare_crx_with_raw_args(args)

  def run(self, test_methods_to_run):
    results = {}
    raw_output = []
    for test_name in test_methods_to_run:
      dalvik_args = self._test_arg_map[test_name]
      with system_mode.SystemMode(self) as arc:
        try:
          # Mark incomplete at beginning. Will be overwrite on completion.
          test_status = test_method_result.TestMethodResult.INCOMPLETE
          test_file = os.path.join(self._test_dir, 'test.jar')
          assert os.access(test_file, os.R_OK), ('can not read a test file ' +
                                                 test_file)
          arc.run_adb(['push', test_file, '/data'])
          test_ex_file = os.path.join(self._test_dir, 'test-ex.jar')
          if os.access(test_ex_file, os.R_OK):
            arc.run_adb(['push', test_ex_file, '/data'])

          begin_time = time.time()
          output = arc.run_adb(self._shell_args(test_name, dalvik_args))
          elapsed_time = time.time() - begin_time

          if self._is_benchmark:
            output = 'Benchmark %s: %d ms' % (test_name, elapsed_time * 1000)
            if self._args.output == 'verbose':
              print output
            raw_output.append(output)
          else:
            output_file_path = os.path.join(self._test_dir, 'output.txt')
            with open(output_file_path, 'w') as output_file:
              output_file.write(_cleanup_output(output))
            expected_file_path = os.path.join(
                self._test_source_dir, 'expected.txt')
            # We diff the output against expected, ignoring whitespace,
            # as the output file comes from running adb in ARC and so
            # has \r\n instead of just \n.
            output = self.run_subprocess(
                ['diff', '-b', output_file_path, expected_file_path],
                omit_xvfb=True)
            raw_output.append(output)
          test_status = test_method_result.TestMethodResult.PASS
        except subprocess.CalledProcessError as e:
          if hasattr(e, 'output') and e.output:
            raw_output.append(e.output)
          result = test_method_result.TestMethodResult.FAIL
        except system_mode.SystemModeError:
          raw_output.append(arc.get_log())
          result = test_method_result.TestMethodResult.FAIL
        except Exception:
          raw_output.append(traceback.format_exc())
          raw_output.append(self._get_subprocess_output())
          result = test_method_result.TestMethodResult.FAIL
        result = test_method_result.TestMethodResult(test_name, test_status)
        self.get_scoreboard().update([result])
        results[test_name] = result
      raw_output.append(arc.get_log())
    return '\n'.join(raw_output), results
