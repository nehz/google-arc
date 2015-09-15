#!src/build/run_python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parses downloaded buildbot logs to find failing tests.

To download buildbot logs, run:

   $ src/build/util/download_bot_logs.py

For more options, consult that script.  Once downloaded, run `./configure
[flags] && ninja` for the platform you want to analyze to build the necessary
files needed to calculate test expectations.  The choice of flags will affect
which tests are run, so you will most likely want to use the same flags the
buildbots use.  Once the build is finished, run this script and it will print a
report with the top failing tests that have not been marked as SKIP.
"""

import collections
import os
import re
import subprocess
import sys

from src.build.build_options import OPTIONS
from src.build.util.test import scoreboard_constants
from src.build.util.test import suite_results


_BOTLOGS_DIR = 'botlogs'
_SECTION_PATTERN = r'######## %s \(\d+\) ########'
_UNEXPECTED_FAILURES_RE = re.compile(
    _SECTION_PATTERN % (
        suite_results.VERBOSE_STATUS_TEXT[
            scoreboard_constants.UNEXPECTED_FAIL]))
_INCOMPLETE_RE = re.compile(
    _SECTION_PATTERN % (
        suite_results.VERBOSE_STATUS_TEXT[
            scoreboard_constants.INCOMPLETE]))
_EXPECTATIONS_RE = re.compile(r'\[(RUN|SKIP)\s+([A-Z_,]+)\s*\] (.*)')


def _get_expectations(extra_flags=None):
  params = ['./run_integration_tests', '--list', '--buildbot',
            '--noninja']
  if extra_flags:
    params.extend(extra_flags)
  expectations = {}
  for line in subprocess.check_output(params).split('\n'):
    match = _EXPECTATIONS_RE.match(line)
    if match:
      # Test name -> (PASS/SKIP, flag list)
      expectations[match.group(3)] = [match.group(1),
                                      match.group(2).split(',')]
  return expectations


def _parsefile(filename, header_re, collection):
  with open(filename, 'r') as log:
    for line in log:
      if header_re.match(line):
        break
    # We found the header. All following lines until the next blank line are
    # reported errors.
    for line in log:
      line = line.strip()
      if not line:
        break
      collection[line] += 1


def _parse(logfiles):
  failures = collections.defaultdict(int)
  incompletes = collections.defaultdict(int)
  for logfile in logfiles:
    _parsefile(logfile, _UNEXPECTED_FAILURES_RE, failures)
    _parsefile(logfile, _INCOMPLETE_RE, incompletes)
  return failures, incompletes


def main():
  OPTIONS.parse_configure_file()
  target = OPTIONS.target()
  regular_expectations = _get_expectations()
  large_expectations = _get_expectations(['--include-large'])
  for botname in os.listdir(_BOTLOGS_DIR):
    if not botname.replace('-', '_').startswith(target):
      continue
    botdir = os.path.join(_BOTLOGS_DIR, botname)
    lognames = [os.path.join(botdir, filename) for filename in
                os.listdir(botdir)]
    failures, incompletes = _parse(lognames)
    top_flake = sorted([(freq, name) for name, freq in failures.iteritems()],
                       reverse=True)
    print '%s:' % botname
    if 'large_tests' in botname:
      expectations = large_expectations
    else:
      expectations = regular_expectations
    for freq, name in top_flake:
      assert name in expectations, '%s is not in expectations list' % name
      run, flags = expectations[name]
      if run == 'SKIP':
        continue
      failrate = 100.0 * freq / float(len(lognames))
      print '%5.2f%% fail rate [%-4s %-19s] %s' % (failrate, run,
                                                   ','.join(flags), name)
    print
  return 0


if __name__ == '__main__':
  sys.exit(main())
