# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Finds and loads config.py files scattered through the source code tree."""

import imp
import os
import os.path
import sys

import build_options
from build_common import get_arc_root


def _all_config_files(base_paths):
  for base_path in base_paths:
    for root, dirs, files in os.walk(base_path, followlinks=False):
      for name in files:
        if name == 'config.py':
          yield os.path.join(root, name), base_path


def _register_module(module_path, module):
  sys.modules[module_path] = module
  if '.' in module_path:
    parent_name, child_name = module_path.rsplit('.', 1)
    setattr(sys.modules[parent_name], child_name, module)


def _walk_module_path(module_path):
  path = module_path.split('.')
  for index in xrange(len(path) - 1):
    yield '.'.join(path[:index + 1])


def _ensure_parents_exist(module_path):
  for parent in _walk_module_path(module_path):
    if parent not in sys.modules:
      _register_module(parent, imp.new_module(parent))


class ConfigLoader:
  def __init__(self):
    self._config_modules = []

  def find_name(self, attribute_name):
    """Iterates over all loaded config modules and does a name lookup on """
    """them."""
    for module in self._config_modules:
      if hasattr(module, attribute_name):
        yield getattr(module, attribute_name)

  def find_config_modules(self, attribute_name):
    """Finds the loaded config modules that have the specified attribute """
    """name."""
    for module in self._config_modules:
      if hasattr(module, attribute_name):
        yield module

  def load_from_subdirectories(self, base_paths):
    """Loads all the config.py files found under the base_path."""

    # Get the list and sort it to avoid nondeterministic import issues caused
    # by some modules being set up before others.
    return self.load_config_files(_all_config_files(base_paths))

  def load_config_files(self, config_files):
    """Loads all the config.py files found under the base_path.

    The files are loaded as an appropriately named submodule.
    If this function finds base_path/foo/bar/config.py, a module named
    foo.bar is created with its contents, and can be subsequently
    referenced with an 'import foo.bar' (foo.bar.config seemed redundant).
    No __init__.py files are needed.

    Returns a list of all the modules loaded so that later code can optional
    do some introspection to decide what to do with them.
    """

    # For safety, acquire the import lock.
    imp.acquire_lock()
    try:
      for path_name, base_path in config_files:
        # Convert the filename into a dotted python module name.
        # base_path/foo/bar/config.py -> foo.bar
        top_level_dir = os.path.basename(base_path)
        dirs = [top_level_dir]
        relative_path_to_config = os.path.dirname(
            os.path.relpath(path_name, base_path))
        if relative_path_to_config:
          dirs.extend(relative_path_to_config.split(os.sep))
        module_name = '.'.join(dirs)

        # Ensure parent modules exist, creating them if needed.
        _ensure_parents_exist(module_name)

        # Compile and load the source file as a module
        with open(path_name, 'r') as config_file:
          config_module = imp.load_source(module_name, path_name, config_file)

        # Register the module so we can just a later normal looking import to
        # reference it.
        _register_module(module_name, config_module)

        self._config_modules.append(config_module)
    finally:
      imp.release_lock()

    return self._config_modules

  def load_from_default_path(self):
    # On the first import, automatically discover all config modules in the
    # project for later use, including allowing them to be imported by their
    # containing directory name.
    paths = [
        os.path.join(get_arc_root(), 'mods', 'android'),
        os.path.join(get_arc_root(), 'mods', 'chromium-ppapi'),
        os.path.join(get_arc_root(), 'mods', 'examples'),
        os.path.join(get_arc_root(), 'mods', 'graphics_translation'),
        os.path.join(get_arc_root(), 'src'),
    ]

    if build_options.OPTIONS.internal_apks_source_is_internal():
      paths.append(os.path.join(get_arc_root(), 'internal', 'mods'))

    return self.load_from_subdirectories(paths)
