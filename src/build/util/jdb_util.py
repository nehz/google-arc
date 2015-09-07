#!src/build/run_python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import subprocess
import sys

from src.build import eclipse_connector
from src.build import staging
from src.build.util import concurrent_subprocess

# The list of Java source file root paths.
# TODO(crbug.com/470798): Find proper paths.
_JAVA_SOURCE_PATHS = (
    'android/libcore/luni/src/main/java',
    'android/frameworks/base/core/java',
)


def maybe_launch_jdb(jdb_port, jdb_type):
  # If jdb option is specified and jdb_port exists. Now it is time to
  # check which Java debugger to start.
  if jdb_port and jdb_type == 'eclipse':
      if not eclipse_connector.connect_eclipse_debugger(jdb_port):
        # We already should have error message now. Just exit.
        sys.exit(1)


class JdbHandlerAdapter(concurrent_subprocess.DelegateOutputHandlerBase):
  _WAITING_JDB_CONNECTION_PATTERN = re.compile(
      r'Hello ARC, start jdb please at port (\d+)')

  def __init__(self, base_handler, jdb_port, jdb_type, remote_executor=None):
    super(JdbHandlerAdapter, self).__init__(base_handler)
    self._jdb_port = jdb_port
    self._jdb_type = jdb_type
    self._remote_executor = remote_executor

  def handle_stderr(self, line):
    super(JdbHandlerAdapter, self).handle_stderr(line)

    if not JdbHandlerAdapter._WAITING_JDB_CONNECTION_PATTERN.search(line):
      return

    if self._remote_executor:
      self._remote_executor.port_forward(self._jdb_port)

    if self._jdb_type == 'emacsclient':
      self._start_emacsclient_jdb()

  def _start_emacsclient_jdb(self):
    source_paths = []
    for path in _JAVA_SOURCE_PATHS:
      source_paths.extend([
          staging.as_staging(path),
          # Add the real paths too to let emacs know these paths too are
          # candidates for setting breakpoints etc.
          os.path.join('./mods', path),
          os.path.join('./third_party', path),
      ])
    command = [
        'emacsclient', '-e',
        '(jdb "jdb -attach localhost:{port} -sourcepath{path}")'.format(
            port=self._jdb_port,
            path=':'.join(source_paths))]
    subprocess.Popen(command)
