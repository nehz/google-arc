#!/usr/bin/python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
import staging
import subprocess
import sys
import time

import eclipse_connector


def maybe_launch_jdb(jdb_port, jdb_type):
  # If jdb option is specified and jdb_port exists. Now it is time to
  # check which Java debugger to start.
  if jdb_port and jdb_type == 'eclipse':
      if not eclipse_connector.connect_eclipse_debugger(jdb_port):
        # We already should have error message now. Just exit.
        sys.exit(1)


class JdbHandlerAdapter(object):
  _WAITING_JDB_CONNECTION_PATTERN = re.compile(
      r'Waiting for JDWP connection on port (\d+)')

  def __init__(self, base_handler, jdb_port, jdb_type):
    self._base_handler = base_handler
    self._jdb_port = jdb_port
    self._jdb_type = jdb_type

  def handle_timeout(self):
    self._base_handler.handle_timeout()

  def handle_stdout(self, line):
    self._base_handler.handle_stdout(line)

  def _start_emacsclient_jdb(self):
    source_path = ':'.join([
        staging.as_staging('android/frameworks/base/core/java/'),
        # Add the real paths too to let emacs know these paths too are
        # candidates for setting breakpoints etc.
        './mods/android/frameworks/base/core/java/',
        './third_party/android/frameworks/base/core/java/'])
    command = ['emacsclient', '-e',
               ('(jdb "jdb -attach localhost:%i '
                '-sourcepath%s ")') % (self._jdb_port, source_path)]
    # TODO(crbug.com/469037): Try to wait until JDWP port is
    # really available. There should be a better way?
    time.sleep(0.6)
    subprocess.Popen(command)

  def handle_stderr(self, line):
    self._base_handler.handle_stderr(line)

    match = JdbHandlerAdapter._WAITING_JDB_CONNECTION_PATTERN.search(line)
    if not match:
      return

    if self._jdb_type == 'emacsclient':
      self._start_emacsclient_jdb()

  def get_error_level(self, child_level):
    return self._base_handler.get_error_level(child_level)

  def is_done(self):
    return self._base_handler.is_done()