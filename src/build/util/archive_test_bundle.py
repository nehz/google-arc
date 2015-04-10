#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Archives files needed to run integration tests such as arc runtime,
# CRX files, config files, and test jar files.

import argparse
import logging
import os
import re
import sys
import zipfile

sys.path.insert(0, 'src/build')

import build_common
import run_integration_tests
import toolchain
from build_options import OPTIONS
from util import remote_executor_util


def _collect_descendants(paths):
   """Returns the set of descendant files of the directories in |paths|.

   If |paths| includes files in |paths|, the files are included in the returned
   set. Unnecessary files for running integration tests such as temporary files
   created by editor, .pyc, and .ncval files are excluded from the returned set.
   """
   files = [path for path in paths if os.path.isfile(path)]
   dirs = [path for path in paths if os.path.isdir(path)]
   files += build_common.find_all_files(dirs, include_tests=True,
                                        use_staging=False)
   files = [f for f in files if not re.match(r'.*\.(pyc|ncval)', f)]
   return set(files)


def _get_archived_file_paths():
  """Returns the file paths to be archived."""
  paths = _collect_descendants(
      remote_executor_util.get_integration_test_files_and_directories())
  paths |= set(run_integration_tests.get_dependencies_for_integration_tests())
  paths.add(os.path.relpath(toolchain.get_adb_path_for_chromeos(),
                            build_common.get_arc_root()))
  return paths


def _zip_files(filename, paths):
  """Creates a zip file that contains the specified files."""
  # Set allowZip64=True so that large zip files can be handled.
  with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED,
                       allowZip64=True) as f:
    for path in set(paths):
      if path.startswith(build_common.get_stripped_dir()):
        # When archiving a stripped file, use the path of the corresponding
        # unstripped file as archive name
        arcname = os.path.join(
            build_common.get_build_dir(),
            os.path.relpath(path, build_common.get_stripped_dir()))
        f.write(path, arcname=arcname)
      else:
        f.write(path)


def _get_integration_tests_args(jobs):
  """Gets args of run_integration_tests.py adjusted for archiving files."""
  args = run_integration_tests.parse_args(['--jobs=%d' % jobs])
  # Create an archive to be used on buildbots.
  args.buildbot = True
  # Assume buildbots support GPU.
  args.gpu = 'on'
  # Archive failing tests as well.
  args.include_failing = True
  return args


def _convert_to_stripped_paths(paths):
  """Converts |paths| to a list that includes corresponding stripped paths."""
  new_paths = []
  for path in paths:
    stripped_path = build_common.get_stripped_path(path)
    if stripped_path and os.path.exists(stripped_path):
      new_paths.append(stripped_path)
    else:
      new_paths.append(path)
  return new_paths


def _parse_args():
  description = 'Archive files needed to run integration tests.'
  parser = argparse.ArgumentParser(description=description)
  parser.add_argument('-j', '--jobs', metavar='N', default=1, type=int,
                      help='Prepare N tests at once.')
  parser.add_argument('--noninja', action='store_false',
                      default=True, dest='run_ninja',
                      help='Do not run ninja before archiving test bundle.')
  parser.add_argument('-o', '--output',
                      default=build_common.get_test_bundle_name(),
                      help=('The name of the test bundle to be created.'))
  return parser.parse_args()


if __name__ == '__main__':
  OPTIONS.parse_configure_file()

  # Prepare all the files needed to run integration tests.
  parsed_args = _parse_args()
  # Build arc runtime.
  if parsed_args.run_ninja:
    build_common.run_ninja()

  logging.basicConfig(level=logging.WARNING)
  integration_tests_args = _get_integration_tests_args(parsed_args.jobs)
  assert run_integration_tests.prepare_suites(integration_tests_args)

  # Prepare dalvik.401-perf for perf vm tests.
  integration_tests_args.include_patterns = ['dalvik.401-perf:*']
  assert run_integration_tests.prepare_suites(integration_tests_args)

  # Archive all the files needed to run integration tests into a zip file.
  paths = _get_archived_file_paths()
  if OPTIONS.is_debug_info_enabled():
    paths = _convert_to_stripped_paths(paths)
  print 'Creating %s' % parsed_args.output
  _zip_files(parsed_args.output, paths)
  print 'Done'
