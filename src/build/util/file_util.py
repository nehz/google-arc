# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import atexit
import cStringIO
import errno
import glob as _glob  # To avoid conflict with glob() defined in this module.
import itertools
import logging
import os
import shutil
import tempfile
import time
import zipfile


# Create a symlink from link_target to link_source, creating any necessary
# directories along the way and overwriting any existing links.
def create_link(link_target, link_source, overwrite=False):
  dirname = os.path.dirname(link_target)
  makedirs_safely(dirname)
  source_rel_path = os.path.relpath(link_source, dirname)
  if os.path.lexists(link_target):
    if overwrite:
      os.unlink(link_target)
      os.symlink(source_rel_path, link_target)
  else:
    os.symlink(source_rel_path, link_target)


def create_tempfile_deleted_at_exit(*args, **kwargs):
  """Creates a named temporary file, which will be deleted at exit.

  The arguments of this function is as same as tempfile.NamedTemporaryFile,
  except that 'delete' param cannot be accepted.

  The result is a file-like object with 'name' attribute (as same as
  tempfile.NamedTemporaryFile).
  """
  result = tempfile.NamedTemporaryFile(delete=False, *args, **kwargs)
  atexit.register(lambda: result.unlink(result.name))
  return result


def makedirs_safely(path):
  """Ensures the specified directory exists (i.e., mkdir -p)."""
  # We should not use if os.path.isdir to avoid EEXIST because another
  # process may create the directory after we check its existence.
  try:
    os.makedirs(path)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise
  assert os.path.isdir(path)


def rmtree(path, ignore_errors=False):
  """Removes a directory tree or unlinks a symbolic link."""
  if os.path.islink(path):
    os.unlink(path)
  else:
    shutil.rmtree(path, ignore_errors=ignore_errors)


def rmtree_with_retries(d):
  for retry_count in xrange(10):
    try:
      rmtree(d)
      break
    except:
      time.sleep(1)
      continue
  else:
    raise Exception('Failed to remove ' + d)


def remove_file_force(filename):
  """Removes the file by ignoring the nonexistent file error (i.e., rm -f)."""
  try:
    os.remove(filename)
  except OSError as e:
    if e.errno != os.errno.ENOENT:
      raise


def read_metadata_file(path):
  """Read given metadata file into a list.

  Gets rid of leading/trailing whitespace and comments which are indicated
  with the pound/hash sign."""
  reduced_lines = []
  with open(path, 'r') as f:
    lines = f.readlines()
    for l in lines:
      l = l.strip()  # Remove trailing \n
      l = l.split('#')[0].strip()  # Remove comments
      if l:
        reduced_lines.append(l)
  return reduced_lines


def write_atomically(filepath, content):
  """Writes content to a file atomically.

  This function writes the content to a temporary file first, then moves the
  temporary file to the desired file path. In this way, an incomplete file is
  not created even if the thread is interrupted in the middle of the function.
  """
  generate_file_atomically(filepath, lambda f: f.write(content))


def generate_file_atomically(filepath, generator):
  """Generate a file atomically.

  This function is similar to write_atomically but takes a function to generate
  file content instead of the content itself.
  """
  with tempfile.NamedTemporaryFile(
      delete=False, dir=os.path.dirname(filepath)) as f:
    atexit.register(lambda: remove_file_force(f.name))
    generator(f.file)
  os.rename(f.name, filepath)


def inflate_zip(content, dest_dir):
  """Inflates the zip content into the dest_dir."""
  makedirs_safely(dest_dir)
  with zipfile.ZipFile(cStringIO.StringIO(content)) as archive:
    logging.info('Extracting...')
    for info in archive.infolist():
      logging.info('  inflating: %s', info.filename)
      archive.extract(info, path=dest_dir)
    logging.info('Done.')


def walk_ancestor(path):
  """Yields the |path|'s ancestor paths.

  For example, if |path| is "a/b/c/d/e", this function will yield;
  - a/b/c/d/e
  - a/b/c/d
  - a/b/c
  - a/b
  - a

  Args:
      path: a path to be traversed. Absolute path is not supported.
          Normalized path must not start with '../'.

  Yields: |path|'s ancestor paths.
  """
  assert not path.startswith('/'), 'Absolute path is not supported: ' + path
  normpath = os.path.normpath(path)
  assert normpath != '..' and not normpath.startswith('../'), (
      'Normalized path must not start with ../: ' + path)
  while normpath:
    yield normpath
    normpath = os.path.dirname(normpath)


def glob(*patterns):
  """Expands the glob pattern.

  Unlike glob.glob(), this takes an abitrary number of arguments.

  Args:
     patterns: glob pattern.

  Return:
     A List of glob'ed paths. All glob'ed paths are merged, uniqued and then
     sorted.
  """
  return sorted(set(itertools.chain.from_iterable(
      _glob.iglob(pattern) for pattern in patterns)))
