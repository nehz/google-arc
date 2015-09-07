# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Identify Python code dependencies."""

import modulefinder
import os
import sys

from src.build import build_common
from src.build import dependency_inspection


def find_deps(source_path, python_path=None):
  """Returns the list of dependencies for a python script.

  Args:
      source_path: The path to the Python module/script to examine.
      python_path: A list of paths to use as the Python search path to find
          imported modules.

  Returns:
    The list of returned dependencies, filtered to the files located under the
    project source code tree.

    Note that the input source_path is returned as one of the output
    dependencies.

  If this function is called while a config.py is running, it records the output
  dependencies as dependencies of the config.py.
  """
  python_path = build_common.as_list(python_path) + sys.path
  finder = modulefinder.ModuleFinder(python_path)
  finder.run_script(source_path)

  # Examine the paths of all the modules that were loaded. Some of the paths we
  # get back are relative. Some absolute. Convert everything to absolute.
  dependencies = [os.path.abspath(module.__file__)
                  for module in finder.modules.itervalues()
                  if module.__file__]

  # Filter down the dependencies to those that are contained under the project,
  # and convert paths into project relative paths.
  # We assume that changes to the Python standard library for example are
  # irrelevant.
  result = [build_common.get_project_relpath(path)
            for path in dependencies
            if build_common.is_abs_path_in_project(path)]

  dependency_inspection.add_files(source_path, *result)

  return sorted(result)
