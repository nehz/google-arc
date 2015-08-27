# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import signal
import subprocess
import time
import unittest

from util import file_util
from util import chrome_process


# Note that flush()es are needed, because these may point to the same fd.
# In such a case, buffering confuses the order of output, so to ensure the
# output order, flush()es are needed.
_SIMPLE_TEST_PROGRAM = """
import sys

print >>sys.stdout, 'PROGRAM STDOUT DATA'
sys.stdout.flush()
print >>sys.stderr, 'PROGRAM STDERR DATA'
sys.stderr.flush()
"""

_SIMPLE_SLEEP = """
import time

while True:
  time.sleep(1000000)  # Use huge value.
"""


def _wait_by_busy_loop(process):
  while process.poll() is None:
    time.sleep(0.1)


class TailProxyChromePopenTest(unittest.TestCase):
  def test_simple_no_pipe(self):
    p = chrome_process._TailProxyChromePopen(
        ['python', '-c', _SIMPLE_TEST_PROGRAM], stdout=None, stderr=None)
    _wait_by_busy_loop(p)
    self.assertEqual(0, p.returncode)
    self.assertIsNone(p.stdout)
    self.assertIsNone(p.stderr)

  def test_proxy(self):
    p = chrome_process._TailProxyChromePopen(
        ['python', '-c', _SIMPLE_TEST_PROGRAM],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={})
    _wait_by_busy_loop(p)
    self.assertEqual(0, p.returncode)
    with contextlib.closing(p.stdout), contextlib.closing(p.stderr):
      self.assertEquals('PROGRAM STDOUT DATA\n', p.stdout.read())
      self.assertEquals('PROGRAM STDERR DATA\n', p.stderr.read())

  def test_proxy_stdout(self):
    p = chrome_process._TailProxyChromePopen(
        ['python', '-c', _SIMPLE_TEST_PROGRAM],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={})
    _wait_by_busy_loop(p)
    self.assertEqual(0, p.returncode)
    with contextlib.closing(p.stdout):
      self.assertEquals('PROGRAM STDOUT DATA\nPROGRAM STDERR DATA\n',
                        p.stdout.read())
    self.assertIsNone(p.stderr)

  def test_nacl_exe(self):
    nacl_stdout = file_util.create_tempfile_deleted_at_exit(
        prefix='NACL_STDOUT').name
    nacl_stderr = file_util.create_tempfile_deleted_at_exit(
        prefix='NACL_STDERR').name
    with open(nacl_stdout, 'w') as f:
      f.write('NACL STDOUT DATA\n')
    with open(nacl_stderr, 'w') as f:
      f.write('NACL STDERR DATA\n')
    p = chrome_process._TailProxyChromePopen(
        ['python', '-c', _SIMPLE_TEST_PROGRAM],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={'NACL_EXE_STDOUT': nacl_stdout, 'NACL_EXE_STDERR': nacl_stderr})
    _wait_by_busy_loop(p)
    self.assertEqual(0, p.returncode)

    with contextlib.closing(p.stdout), contextlib.closing(p.stderr):
      stdout = p.stdout.read()
      stderr = p.stderr.read()
    self.assertIn('PROGRAM STDOUT DATA\n', stdout)
    self.assertIn('NACL STDOUT DATA\n', stdout)
    self.assertIn('PROGRAM STDERR DATA\n', stderr)
    self.assertIn('NACL STDERR DATA\n', stderr)

  def test_terminate(self):
    p = chrome_process._TailProxyChromePopen(
        ['python', '-c', _SIMPLE_SLEEP],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={})
    p.terminate()
    # Make sure tail processes are terminated, even if we have not poll()ed the
    # main proess yet.
    with contextlib.closing(p.stdout), contextlib.closing(p.stderr):
      self.assertEqual('', p.stdout.read())
      self.assertEqual('', p.stderr.read())
    _wait_by_busy_loop(p)
    self.assertEqual(-signal.SIGTERM, p.returncode)


  def test_kill(self):
    p = chrome_process._TailProxyChromePopen(
        ['python', '-c', _SIMPLE_SLEEP],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={})
    p.kill()
    # Make sure tail processes are terminated, even if we have not poll()ed the
    # main proess yet.
    with contextlib.closing(p.stdout), contextlib.closing(p.stderr):
      self.assertEqual('', p.stdout.read())
      self.assertEqual('', p.stderr.read())
    _wait_by_busy_loop(p)
    self.assertEqual(-signal.SIGKILL, p.returncode)
