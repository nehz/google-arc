# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for downloading and unpacking archives, with caching."""

import contextlib
import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import time
import urllib

from src.build import build_common
from src.build.util import file_util


_DEFAULT_CACHE_BASE_PATH = os.path.join(build_common.get_arc_root(), 'cache')
_DEFAULT_CACHE_HISTORY_SIZE = 3


class CacheHistory(object):
  """Interface for the working with the history of a particular package."""

  def __init__(self, name, base_path, history_size, contents):
    self._name = name
    self._base_path = base_path
    self._history_size = history_size
    self._contents = contents

  def clean_old(self):
    """Cleans out the least-recently used entries, deleting cache paths."""
    while len(self._contents) > self._history_size:
      path = self._contents.pop(0)
      assert path.startswith(self._base_path)
      logging.info('%s: Cleaning old cache entry %s', self._name,
                   os.path.basename(path))
      shutil.rmtree(path, ignore_errors=True)

  def ensure_recent(self, path):
    """Ensures the path is moved to a recently-used position in the history."""
    if path in self._contents:
      self._contents.remove(path)
    self._contents.append(path)


@contextlib.contextmanager
def _persisted_cache_history(name, base_path, history_size):
  """Persists the cache history using a context."""

  # Ensure we have a cache directory
  file_util.makedirs_safely(base_path)
  cache_contents_path = os.path.join(base_path, 'contents.json')

  # Load in the existing cache content history.
  cache_contents = {}
  if os.path.exists(cache_contents_path):
    with open(cache_contents_path) as cache_contents_file:
      try:
        cache_contents = json.load(cache_contents_file)
      except ValueError:
        pass

  # Get the history for this particular download, and yield it for use by the
  # caller.
  history = CacheHistory(
      name, base_path, history_size,
      cache_contents.setdefault('cache', {}).setdefault(name, []))

  # If the user of this contextmanager generates an exception, this yield
  # will effectively reraise the exception, and the rest of this function will
  # not be executed since we do not have anything like a  try...finally block
  # here.
  yield history

  history.clean_old()

  # Save out the modified cache content history.
  with open(cache_contents_path, 'w') as cache_contents_file:
    json.dump(cache_contents, cache_contents_file, indent=2, sort_keys=True)


def execute_subprocess(cmd, cwd=None):
  """Executes a subprocess, logging its output.

  Since logging.info() is used if the process runs normally, the subprocess is
  run quietly. However should the process exit with a non-zero error code, its
  output will be logged at a higher error level, allowing problems to be
  diagnosed.
  """
  try:
    output = subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
    for line in output.splitlines():
      logging.info(line)
  except subprocess.CalledProcessError as e:
    logging.error('While running %s%s', cmd, (' in ' + cwd) if cwd else '')
    if e.output:
      logging.error(e.output)
    raise


def default_download_url():
  """Creates a closure for downloading a file given a standard URL for it."""
  def _download(url, destination_path):
    urllib.urlretrieve(url, destination_path)
  return _download


def gsutil_download_url():
  """Creates a closure for downloading a Google Cloud Storage file."""
  def _download(url, destination_path):
    try:
      execute_subprocess([
          build_common.get_gsutil_executable(), 'cp', url, destination_path])
    except subprocess.CalledProcessError:
      logging.error('Try prodaccess, and if it does not solve the problem try '
                    'rm ~/.devstore_token')
      raise
  return _download


def unpack_zip_archive(extra_args=None):
  """Creates a closure which performs a simple unzip of an archive file."""
  def _unpack(archive_path, destination_path):
    args = ['unzip']
    if extra_args:
      args.extend(extra_args)
    args.extend(['-d', destination_path, archive_path])
    execute_subprocess(args)
  return _unpack


def unpack_tar_archive(compression_program=None):
  """Creates a closure which performs a simple untar of an archive file."""
  def _unpack(archive_path, destination_path):
    cmd = ['tar', '--extract']
    if compression_program:
      cmd.append('--use-compress-program=' + compression_program)
    cmd.extend(['--directory=' + destination_path, '--strip-components=1',
                '--file=' + archive_path])
    execute_subprocess(cmd)
  return _unpack


def unpack_self_extracting_archive():
  """Creates a closure which unpacks a self-extracting archive."""
  def _unpack(archive_path, destination_path):
    os.chmod(archive_path, stat.S_IRWXU)
    execute_subprocess([archive_path], cwd=destination_path)
  return _unpack


class BasicCachedPackage(object):
  """Handles downloading and extracting a package from a URL."""

  def __init__(self, deps_file_path, unpacked_final_path, url=None,
               link_subdir=None, download_method=None, unpack_method=None,
               cache_base_path=None, cache_history_size=None):
    """Sets up the basic configuration for this package.

    |deps_file_path| is the relative path to the DEPS.XXXX file to use for this
    package.
    |unpacked_final_path| is the path the unpacked package should appear at.
    |url| is the URL to use to retrieve the download. If not specified (the
    typical case), the URL is taken from the first line of the DEPS file.
    |link_subdir| is the subdirectory of the unpacked package from the cache
    that should appear at the final location. This is useful if the archive
    unpacks to a subdirectory.
    |download_method| is a function to call taking a pair of arguments, (URL,
    archive_path), which should retrieve the package given its URL, and write
    the contents as a file to archive_path.
    |unpack_method| is a function to call taking a pair of arguments,
    (archive_path, destination_path), to extract the archive file to the
    indicated destination.
    |cache_base_path| allows a derived class to choose the cache path
    explicitly, but is really only meant for the unittest.
    |cache_history_size| allows a derived class to choose the cache history
    size, but it is really only meant for the unittest.
    """
    if cache_base_path:
      cache_base_path = os.path.abspath(cache_base_path)

    self._name = os.path.basename(unpacked_final_path)
    self._cache_base_path = cache_base_path or _DEFAULT_CACHE_BASE_PATH
    self._cache_history_size = cache_history_size or _DEFAULT_CACHE_HISTORY_SIZE
    self._deps_file_path = os.path.join(
        build_common.get_arc_root(), deps_file_path)
    self._unpacked_final_path = os.path.join(
        build_common.get_arc_root(), unpacked_final_path)
    self._link_subdir = link_subdir or '.'
    self._download_method = download_method or default_download_url()
    self._unpack_method = unpack_method or unpack_zip_archive()
    self._deps_file_lines = file_util.read_metadata_file(deps_file_path)
    self._url = url or self._deps_file_lines[0]
    self._unpacked_cache_path = (
        self._get_cache_entry_path(self._deps_file_lines))

  @property
  def name(self):
    """The name to use to identify the package."""
    return self._name

  @property
  def cache_base_path(self):
    """The base path to use for the cache."""
    return self._cache_base_path

  @property
  def unpacked_final_path(self):
    """The path to the final location for the package."""
    return self._unpacked_final_path

  @property
  def unpacked_cache_path(self):
    """The path to the location in the cache to unpack the package to."""
    return self._unpacked_cache_path

  @property
  def unpacked_linked_cache_path(self):
    return os.path.abspath(os.path.join(
        self._unpacked_cache_path, self._link_subdir))

  def _get_stampfile_content(self):
    return ','.join(self._deps_file_lines)

  def post_update_work(self):
    """Override in derived classes to perform additional work after downloading
    and unpacking the download."""
    pass

  def _get_cache_entry_path(self, deps_file_lines):
    return os.path.join(self.cache_base_path, '%s.%s' % (
        self.name,
        hashlib.sha1(','.join(deps_file_lines)).hexdigest()[:7]))

  @build_common.with_retry_on_exception
  def _download_package_with_retries(self, url, download_package_path):
    self._download_method(url, download_package_path)

  def _fetch_and_cache_package(self):
    """Downloads an update file to a temp directory, and manages replacing the
    final directory with the stage directory contents."""
    try:
      # Clean out the cache unpack location.
      logging.info('%s: Cleaning %s', self._name, self._unpacked_cache_path)
      file_util.rmtree(self._unpacked_cache_path, ignore_errors=True)
      file_util.makedirs_safely(self._unpacked_cache_path)

      # Setup the temporary location for the download.
      tmp_dir = tempfile.mkdtemp()
      try:
        downloaded_package_path = os.path.join(tmp_dir, self._name)

        # Download the package.
        logging.info('%s: Downloading %s', self._name,
                     downloaded_package_path)
        self._download_package_with_retries(self._url, downloaded_package_path)

        # Unpack it.
        logging.info('%s: Unpacking %s to %s', self._name,
                     downloaded_package_path, self._unpacked_cache_path)
        self._unpack_method(downloaded_package_path,
                            self._unpacked_cache_path)
      finally:
        file_util.rmtree(tmp_dir, ignore_errors=True)
    except:
      file_util.rmtree(self._unpacked_cache_path, ignore_errors=True)
      raise

  def touch_all_files_in_cache(self):
    logging.info('%s: Touching all files in cache %s', self._name,
                 self.unpacked_linked_cache_path)
    cache_path = self.unpacked_linked_cache_path
    for dirpath, dirnames, filenames in os.walk(cache_path):
      for filename in filenames:
        file_util.touch(os.path.join(cache_path, dirpath, filename))

  def populate_final_directory(self):
    """Sets up the final location for the download from the cache."""
    logging.info('%s: Setting up %s from cache %s', self._name,
                 self._unpacked_final_path, self.unpacked_linked_cache_path)

    file_util.makedirs_safely(self._unpacked_final_path)

    # We create a directory, and make symbolic links for the first level
    # of contents for backwards compatibility with an older version of
    # this code, which could only handle FINAL_DIR being a directory.
    for child in os.listdir(self.unpacked_linked_cache_path):
      file_util.create_link(
          os.path.join(self._unpacked_final_path, child),
          os.path.join(self.unpacked_linked_cache_path, child),
          overwrite=True)

  # TODO(2015-04-20): This is here for backwards compatibility with previous
  # code which unpacked directly to the FINAL_DIR (no cache), and should be
  # able to be removed after this timestamp.  Worst case the download has to
  # be re-downloaded into the cache directory when it is removed.
  def _populate_cache_from_non_symlinked_files(self, history):
    final_url_path = os.path.join(self._unpacked_final_path, 'URL')
    # See if there is an existing URL file
    if not os.path.isfile(final_url_path):
      return

    # Read the content of the URL file in the subdirectory to figure out
    # how to move it into the cache (the DEPS hash may not match!)
    url_file_content = file_util.read_metadata_file(final_url_path)
    cache_path = self._get_cache_entry_path(url_file_content)
    cache_link = os.path.abspath(os.path.join(cache_path, self._link_subdir))

    # Ensure that this cache path is in our history as the most recent entry.
    history.ensure_recent(cache_path)

    # If there appears to be something already cached, then we do not need to do
    # anything.
    if os.path.isdir(cache_path):
      return

    # Move the existing unpacked download into the cache directory
    file_util.makedirs_safely(os.path.dirname(cache_link))
    os.rename(self._unpacked_final_path, cache_link)

  def check_and_perform_update(self):
    """Checks the current and dependency stamps, and performs the update if
    they are different."""
    start = time.time()

    with _persisted_cache_history(self._name, self._cache_base_path,
                                  self._cache_history_size) as history:
      # Maintain a recent used history of entries for this path.
      history.ensure_recent(self._unpacked_cache_path)

      # Temporarily populate the cache path from the final path, if we do not
      # already have the contents cached.
      self._populate_cache_from_non_symlinked_files(history)

      logging.info('%s: Checking %s', self._name, self._unpacked_final_path)
      stamp_file = build_common.StampFile(
          self._get_stampfile_content(),
          os.path.join(self._unpacked_final_path, 'URL'))
      if stamp_file.is_up_to_date():
        logging.info('%s: %s is up to date', self._name,
                     self._unpacked_final_path)
        return

      logging.info('%s: %s is out of date', self._name,
                   self._unpacked_final_path)
      file_util.rmtree(self._unpacked_final_path, ignore_errors=True)

      cached_stamp_file = build_common.StampFile(
          self._get_stampfile_content(),
          os.path.join(self.unpacked_linked_cache_path, 'URL'))
      if not cached_stamp_file.is_up_to_date():
        self._fetch_and_cache_package()

        # We do this now so that the post_update_work step can run out of
        # FINAL_DIR if it wants to.
        self.populate_final_directory()

        # Do any extra work needed after unpacking the package.
        self.post_update_work()

        # Write out the updated stamp file
        cached_stamp_file.update()

      # Reset the mtime on all the entries in the cache.
      self.touch_all_files_in_cache()

      # Ensure the final directory properly links to the cache.
      self.populate_final_directory()

    total_time = time.time() - start
    if total_time > 1:
      print '%s update took %0.3fs' % (
          self._name[:-5] if self._name.endswith('Files') else self._name,
          total_time)
    logging.info('%s: Done. [%0.3fs]', self._name, total_time)
