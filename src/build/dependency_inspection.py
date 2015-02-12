# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# A module to holds sets of files and of directories to global variables.
# Intended usage is to inspect dependency from a config.py to files and
# directories by hooking file accessors.

import file_list_cache


_files = None
_listings = None


def add_files(*files):
  if _files is None:
    return

  for file in files:
    _files.add(file)


def add_file_listing(base_paths, matcher, root, include_subdirectories):
  if _listings is None:
    return

  _listings.add(file_list_cache.Query(
      base_paths, matcher, root, include_subdirectories))


def get_files():
  return _files


def get_listings():
  return _listings


def stop():
  global _files
  global _listings
  _files = None
  _listings = None


def reset():
  global _files
  global _listings
  _files = set()
  _listings = set()
