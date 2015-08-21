# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Finds and loads config.py files scattered through the source code tree."""

import imp
import os
import sys

import build_common
import build_options


def _find_config_py(base_path):
  """Finds config.py files under |base_path| and its descendants.

  Args:
    base_path: The root path for the searching, relative to ARC_ROOT.

  Yields:
    Paths to the found config.py files, relative to ARC_ROOT.
  """
  arc_root = build_common.get_arc_root()
  base_abs_path = os.path.join(arc_root, base_path)
  for dirpath, dirnames, filenames in os.walk(base_abs_path):
    for name in filenames:
      if name == 'config.py':
        # Returns the path relative to ARC_ROOT.
        # Note that, as |base_abs_path| is an absolute path, dirpath is
        # also an absolute path.
        yield os.path.relpath(os.path.join(dirpath, name), arc_root)

    # "third_party" directories are out of our focus.
    if 'third_party' in dirnames:
      dirnames.remove('third_party')


def _import_package(package_path, filepath):
  """Import the package at given |package_path|.

  This is almost same to __import__. The only difference is; when it is not
  found, creates an empty package, and registers it. Practically, this happens
  when __init__.py is not found.

  Args:
    package_path: The path of the package being imported.
    filepath: The path on the file system corresponding to the package.

  Returns:
    Module instance.
  """
  try:
    return __import__(package_path)
  except ImportError:
    # Here, we assume __init__.py is missing. Create a new empty module
    # instance.
    package = imp.new_module(package_path)
    package.__path__ = [filepath]
    sys.modules[package_path] = package
    if '.' in package_path:
      parent, name = package_path.rsplit('.', 1)
      parent_package = _import_package(parent, os.path.dirname(filepath))
      setattr(parent_package, name, package)
    return package


def _load_internal(path_list):
  """Loads all files in |path_list|.

  The files are loaded as an appropriately named submodule.
  Note that the modules will be loaded even if parent modules are not found,
  like because of missing __init__.py. In such a case, empty modules will be
  created.

  Args:
    path_list: a list of files to be loaded, relative to ARC_ROOT.

  Returns:
    A list of loaded modules.
  """

  # For safety, acquire the import lock.
  imp.acquire_lock()
  try:
    result = []
    for path in path_list:
      path = os.path.normpath(path)
      abs_path = os.path.join(build_common.get_arc_root(), path)
      module_name = os.path.splitext(path)[0].replace(os.sep, '.')

      # Ensure ancestor packages.
      if '.' in module_name:
        _import_package(module_name.rsplit('.', 1)[0],
                        os.path.dirname(abs_path))

      with open(abs_path, 'rb') as config_file:
        result.append(imp.load_source(module_name, abs_path, config_file))

    return result
  finally:
    imp.release_lock()


class ConfigLoader(object):
  def __init__(self):
    self._config_modules = []

  def find_config_modules(self, attribute_name):
    """Finds the loaded config modules that have the specified attribute name.

    Args:
      attribute_name: the name of a field or method to be found.

    Yields:
      Modules that have the given |attribute_name|.
    """
    for module in self._config_modules:
      if hasattr(module, attribute_name):
        yield module

  def load(self):
    """Loads all config.py files in the project."""
    search_root_list = [
        os.path.join('mods', 'android'),
        os.path.join('mods', 'chromium-ppapi'),
        os.path.join('mods', 'examples'),
        os.path.join('mods', 'graphics_translation'),
        'src',
    ]
    if build_options.OPTIONS.internal_apks_source_is_internal():
      search_root_list.append('internal')

    config_file_list = []
    for search_root in search_root_list:
      config_file_list.extend(_find_config_py(search_root))

    self._config_modules = _load_internal(config_file_list)
