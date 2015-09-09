# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import shutil
import subprocess

from src.build import build_common
from src.build.util import file_util


class NpmPackageSync(object):
  """Install and sync npm packages based on a DEPS file.

  The DEPS file contains the contents of an npm package.json file.

  Note that the packages are installed according to semantic versioning which
  means it is possible for API compatable different versions of dependencies to
  be installed.
  """

  def __init__(self, deps_file_path, unpacked_final_path):
    self._name = os.path.basename(unpacked_final_path)
    self._deps_file_path = deps_file_path
    self._unpacked_final_path = unpacked_final_path

  def check_and_perform_update(self):
    with open(self._deps_file_path) as f:
      deps_file_contents = f.read()

    stamp_file_path = os.path.join(self._unpacked_final_path,
                                   'STAMP')
    stamp_file = build_common.StampFile(deps_file_contents,
                                        stamp_file_path)
    if stamp_file.is_up_to_date():
      # Nothing has changed.
      return

    logging.info('%s: Updating npm package.', self._name)

    file_util.makedirs_safely(self._unpacked_final_path)
    package_json_file_path = os.path.join(self._unpacked_final_path,
                                          'package.json')
    shutil.copy(self._deps_file_path, package_json_file_path)

    # The Ubuntu npm package uses ~/tmp as its temporary directory
    # (https://github.com/npm/npm/issues/2936). On the buildbots we do not
    # have write access to this dir.  Set a different dir to use here.
    npm_env = os.environ.copy()
    npm_env['TMP'] = '/tmp'
    # npm installs packages listed in the package.json file of the CWD to a
    # directory named 'node_modules' in the CWD.
    npm_command = [
        'npm',
        'install',
    ]
    try:
      subprocess.check_output(npm_command,
                              stderr=subprocess.STDOUT,
                              cwd=self._unpacked_final_path,
                              env=npm_env)
    except subprocess.CalledProcessError as e:
      print 'Output of failed npm install:'
      print e.output
      raise e
    stamp_file.update()
