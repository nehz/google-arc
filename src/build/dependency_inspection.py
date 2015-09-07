# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Inspects dependencies from a config.py to the source tree.

This is for the config cache.

Intended usage in configuration scripts in src/build:
 1) Call start_inspection() before config.py invocation to start recording
    dependencies.
 2) Record dependencies of the config.py by hooking functions called from
    config.py.
 3) After config.py completes, collect the recorded dependencies from
    get_files() and get_listing().
 4) Call stop_inspection() at the end of config.py invocation for clean-up.
"""

from src.build import file_list_cache


# These are not None between start_inspection() and stop_inspection().
# Holds dependencies from the current config.py.
_files = None
_listings = None


def add_files(*files):
  """Declare that the current config.py depends on |files|.

  This implies the config cache for the current config.py needs invalidated when
  any of |files| is updated.
  """
  if _files is None:
    return

  for file in files:
    _files.add(file)


def add_file_listing(base_paths, matcher, root, include_subdirectories):
  """Declare that the current config.py depends on a generated file list.

  This implies the config cache for the current config.py needs invalidated when
  the result of the listing is changed.
  |base_paths| is the list of directories that the listing is performed.
  |matcher| is None or a picklable object with match() method, that filters the
  listed file. The file path passed to the matcher is relative to |root|.
  """
  if _listings is None:
    return

  _listings.add(file_list_cache.Query(
      base_paths, matcher, root, include_subdirectories))


def get_files():
  return _files


def get_listings():
  return _listings


def start_inspection():
  """Start recording dependency."""
  global _files
  global _listings
  _files = set()
  _listings = set()


def stop_inspection():
  """Stop recording dependency."""
  global _files
  global _listings
  _files = None
  _listings = None
