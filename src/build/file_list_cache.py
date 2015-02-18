# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import errno
import hashlib
import logging
import marshal
import os
import pickle
import stat


_CACHE_FILE_VERSION = 0


# Splits given |cache_entries| into |cache_hit|, |cache_miss| and removed
# entries, and returns |cache_hit| and |cache_miss|.
# |cache_entries|, |cache_hit| and |cache_miss| are dictionaries from a file
# path to a CacheEntry.
def _check_cache_freshness(cache_entries):
  cache_hit = {}
  cache_miss = {}

  for path, cached in cache_entries.iteritems():
    try:
      st = os.stat(path)
      if not stat.S_ISDIR(st.st_mode):
        # |path| is a removed entry.
        continue
      elif st.st_mtime > cached.mtime:
        cache_miss[path] = cached
        cached.mtime = st.st_mtime
        continue
      cache_hit[path] = cached
    except OSError as e:
      if e.errno == errno.ENOENT:
        # |path| is a removed entry.
        continue
      raise

  return cache_hit, cache_miss


def _calculate_dir_contents_hash(dirs, files):
  return hashlib.sha1('\0'.join(dirs + [''] + files)).hexdigest()


class Query:
  def __init__(self, base_paths, matcher, root, include_subdirectories):
    self.base_paths = sorted(base_paths)
    self.matcher = matcher
    self.root = root
    self.include_subdirectories = include_subdirectories

  def __eq__(self, other):
    return pickle.dumps(self) == pickle.dumps(other)

  def __hash__(self):
    return pickle.dumps(self).__hash__()


# Represents a result of a file listing in a specific directory.
class CacheEntry:
  def __init__(self, mtime, content_hash, contents):
    self.mtime = mtime
    self.content_hash = content_hash
    self.contents = contents


class FileListCache:
  def __init__(self, query, entries=None):
    self.query = query
    self.cache_entries = {} if entries is None else entries

  # Searches cached entries and refreshes them if needed.
  def refresh_cache(self):
    cache_hit, cache_miss = _check_cache_freshness(self.cache_entries)

    for base_path in self.query.base_paths:
      if base_path not in cache_hit and base_path not in cache_miss:
        cache_miss[base_path] = None

    new_cache_entries = cache_hit
    cache_is_fresh = True

    for path in cache_miss:
      for root, dirs, files in os.walk(path, followlinks=True):
        matched_files = []
        for file in files:
          file_path = os.path.join(root, file)
          if not self.query.matcher:
            matched_files.append(file_path)
            continue

          if self.query.root is None:
            match_path = file_path
          else:
            match_path = os.path.relpath(file_path, self.query.root)
          if self.query.matcher.match(match_path):
            matched_files.append(file_path)
        matched_files = sorted(matched_files)

        if not self.query.include_subdirectories:
          dirs[:] = []

        content_hash = _calculate_dir_contents_hash(sorted(dirs), matched_files)
        recurse = []
        # Recurse into new directories only.
        for subdir_name in dirs:
          subdir = os.path.join(root, subdir_name)
          if subdir not in cache_hit and subdir not in cache_miss:
            recurse.append(subdir_name)
        dirs[:] = recurse

        # Populate cache for |root|.
        cache = cache_miss.get(root)
        if cache:
          if cache.content_hash != content_hash:
            cache_is_fresh = False
          cache.content_hash = content_hash
          cache.contents = matched_files
          new_cache_entries[root] = cache
        else:
          cache = CacheEntry(os.stat(root).st_mtime,
                             content_hash, matched_files)
          cache_is_fresh = False
          new_cache_entries[root] = cache

      self.cache_entries = new_cache_entries

    return cache_is_fresh

  def enumerate_files(self):
    for cached_dir_path in self.cache_entries:
      for path in self.cache_entries[cached_dir_path].contents:
        yield path

  def _enumerate_entries(self):
    for path, cache in self.cache_entries.iteritems():
      yield (path, cache.mtime, cache.content_hash, cache.contents)

  def to_dict(self):
    return {
        'version': _CACHE_FILE_VERSION,
        'query': pickle.dumps(self.query),
        'cache_entries': list(self._enumerate_entries()),
    }

  def save_to_file(self, file_path):
    with open(file_path, 'w') as f:
      marshal.dump(self.to_dict(), f)


def _entries_from_list(list):
  for (path, mtime, content_hash, contents) in list:
    yield [path, CacheEntry(mtime, content_hash, contents)]


def file_list_cache_from_dict(data):
  if data['version'] != _CACHE_FILE_VERSION:
    logging.warn('Version mismatch: %d', data['version'])
    return None

  query = pickle.loads(data['query'])
  entries = dict(_entries_from_list(data['cache_entries']))
  return FileListCache(query, entries)


def load_from_file(file_path):
  try:
    with open(file_path) as f:
      return file_list_cache_from_dict(marshal.load(f))
  except IOError as e:
    if e.errno == errno.ENOENT:
      logging.warn('Cache file is not found: %s', file_path)
      return None
    raise
