# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import cPickle
import collections
import errno
import logging
import marshal
import os
import re

from src.build import build_common
from src.build import config_loader
from src.build import dependency_inspection
from src.build import file_list_cache
from src.build import make_to_ninja
from src.build import ninja_generator
from src.build import ninja_generator_runner
from src.build import open_source
from src.build.build_options import OPTIONS
from src.build.util import file_util


_CONFIG_CACHE_VERSION = 1

_config_loader = config_loader.ConfigLoader()


def _get_build_system_dependencies():
  options_file = build_common.get_target_configure_options_file()
  return [options_file] + ninja_generator.get_configuration_dependencies()


class ConfigResult(object):
  """Represents a result of a task that ran in ninja_generator_runner.

  The instance holds the output and dependencies of the task.
  """

  def __init__(self, config_name, entry_point, files, listing_queries,
               ninja_list):
    self.config_name = config_name
    self.entry_point = entry_point
    self.files = files
    self.listing_queries = listing_queries
    self.generated_ninjas = ninja_list

  def merge(self, other):
    assert self.config_name == other.config_name
    assert self.entry_point == other.entry_point
    self.files.update(other.files)
    self.listing_queries.update(other.listing_queries)
    self.generated_ninjas.extend(other.generated_ninjas)

  def get_file_dependency(self):
    return self.files


class FileEntry(object):
  def __init__(self, mtime):
    self.mtime = mtime


class CacheDependency(object):
  """Represents the dependency part of Config Cache. The instance holds
  informations to decide a cache is fresh.
  """

  def __init__(self, files=None, listings=None):
    self.files = {} if files is None else files
    self.listings = set() if listings is None else listings

  def refresh(self, file_paths, queries):
    files = {}
    for path in file_paths:
      try:
        files[path] = FileEntry(os.stat(path).st_mtime)
      except OSError as e:
        if e.errno != errno.ENOENT:
          raise
    self.files = files

    listings = set()
    new_queries = queries.difference({
        listing.query for listing in self.listings})
    reused_queries = queries.difference(new_queries)
    for query in new_queries:
      listings.add(file_list_cache.FileListCache(query))
    for listing in self.listings:
      if listing.query in reused_queries:
        listings.add(listing)

    for listing in listings:
      listing.refresh_cache()
    self.listings = listings

  def check_freshness(self):
    for path in self.files:
      try:
        if os.stat(path).st_mtime != self.files[path].mtime:
          return False
      except OSError as e:
        if e.errno == errno.ENOENT:
          return False
        raise
    for listing in self.listings:
      if not listing.refresh_cache():
        return False
    return True

  def to_dict(self):
    return {
        'version': _CONFIG_CACHE_VERSION,
        'files': [(path, entry.mtime)
                  for path, entry in self.files.iteritems()],
        'listings': [listing.to_dict() for listing in self.listings]}

  def save_to_file(self, cache_path):
    _save_dict_to_file(self.to_dict(), cache_path)


class ConfigCache(object):
  """Represents an on-disk cache entry to persist the cache."""

  def __init__(self, config_name, entry_point,
               files, listings, serialized_generated_ninjas):
    self.config_name = config_name
    self.entry_point = entry_point
    self.deps = CacheDependency(files, listings)
    self.serialized_generated_ninjas = serialized_generated_ninjas

  def refresh_with_config_result(self, config_result):
    assert self.config_name == config_result.config_name
    assert self.entry_point == config_result.entry_point
    self.deps.refresh(config_result.get_file_dependency(),
                      config_result.listing_queries)
    self.serialized_generated_ninjas = cPickle.dumps(
        config_result.generated_ninjas)

  def check_cache_freshness(self):
    """Returns True if the cache is fresh."""

    return self.deps.check_freshness()

  def to_config_result(self):
    try:
      generated_ninjas = cPickle.loads(self.serialized_generated_ninjas)
    except Exception:
      logging.warning('Failed to load NinjaGenerator from cache: %s',
                      self.config_name, exc_info=True)
      return None
    return ConfigResult(self.config_name, self.entry_point,
                        set(self.deps.files.keys()),
                        {listing.query for listing in self.deps.listings},
                        generated_ninjas)

  def to_dict(self):
    return {
        'version': _CONFIG_CACHE_VERSION,
        'config_name': self.config_name,
        'entry_point': self.entry_point,
        'files': [(path, entry.mtime)
                  for path, entry in self.deps.files.iteritems()],
        'listings': [listing.to_dict() for listing in self.deps.listings],
        'generated_ninjas': self.serialized_generated_ninjas,
    }

  def save_to_file(self, path):
    _save_dict_to_file(self.to_dict(), path)


def _load_dict_from_file(path):
  try:
    with open(path) as file:
      data = marshal.load(file)
  except EOFError:
    return None
  except IOError as e:
    if e.errno == errno.ENOENT:
      return None
    raise
  return data


def _save_dict_to_file(dict, path):
  file_util.makedirs_safely(os.path.dirname(path))
  file_util.generate_file_atomically(path, lambda f: marshal.dump(dict, f))


def _load_global_deps_from_file(cache_path):
  """Load a set of dependency that is depended by all config.py."""
  data = _load_dict_from_file(cache_path)
  if data is None or data['version'] != _CONFIG_CACHE_VERSION:
    return None

  files = {path: FileEntry(mtime) for path, mtime in data['files']}
  listings = set()
  for dict in data['listings']:
    listing = file_list_cache.file_list_cache_from_dict(dict)
    if listing is None:
      return None
    listings.add(listing)
  return CacheDependency(files, listings)


def _load_config_cache_from_file(path):
  data = _load_dict_from_file(path)
  if data is None or data['version'] != _CONFIG_CACHE_VERSION:
    return None

  config_name = data['config_name']
  entry_point = data['entry_point']
  files = {path: FileEntry(mtime) for path, mtime in data['files']}
  listings = set()
  for dict in data['listings']:
    listing = file_list_cache.file_list_cache_from_dict(dict)
    if listing is None:
      return None
    listings.add(listing)

  serialized_generated_ninjas = data['generated_ninjas']
  return ConfigCache(config_name, entry_point, files, listings,
                     serialized_generated_ninjas)


def _config_cache_from_config_result(config_result):
  files = {}
  for path in config_result.get_file_dependency():
    try:
      files[path] = FileEntry(os.stat(path).st_mtime)
    except OSError as e:
      if e.errno != errno.ENOENT:
        raise

  listings = set()
  for query in config_result.listing_queries:
    listing = file_list_cache.FileListCache(query)
    listing.refresh_cache()
    listings.add(listing)

  return ConfigCache(
      config_result.config_name,
      config_result.entry_point,
      files, listings,
      cPickle.dumps(config_result.generated_ninjas))


class ConfigContext:
  """A class that a task on ninja_generator_runner runs with.

  The instance is created for each config.py, hooks each task invocation and
  handles the results.
  """

  def __init__(self, config_file, config_name, entry_point):
    self.config_name = config_name
    self.entry_point = entry_point
    self.files = {config_file}
    self.listing_queries = set()

  def set_up(self):
    dependency_inspection.start_inspection()

  def tear_down(self):
    self.files.update(dependency_inspection.get_files())
    self.listing_queries.update(dependency_inspection.get_listings())

    dependency_inspection.stop_inspection()

  def make_result(self, ninja_list):
    return ConfigResult(self.config_name, self.entry_point,
                        self.files, self.listing_queries, ninja_list)


def _get_global_deps_file_path():
  return os.path.join(build_common.get_config_cache_dir(), 'global_deps')


def _get_cache_file_path(config_name, entry_point):
  return os.path.join(build_common.get_config_cache_dir(),
                      config_name, entry_point)


def _filter_excluded_libs(vars):
  excluded_libs = [
      'libhardware_legacy',  # Not built
      # TODO(crbug.com/336316): Build graphics translation as DSO. Currently
      # it is linked statically to arc.nexe, so such dependencies are removed.
      'libEGL',              # Provided by libegl.a from graphics translation
      'libGLESv1_CM',        # Provided by libgles.a from graphics translation
      'libGLESv2',           # Not built
      'libstlport',          # Trying to avoid in favor of GLIBC
      'libsync']             # FD sync is not supported

  deps = vars.get_shared_deps()
  deps[:] = [x for x in deps if x not in excluded_libs]
  deps = vars.get_static_deps()
  deps[:] = [x for x in deps if x not in excluded_libs]
  deps = vars.get_whole_archive_deps()
  deps[:] = [x for x in deps if x not in excluded_libs]


def _filter_for_when_not_arm(vars):
  # Sources sometimes are explicitly listed with a .arm variant.  Use the
  # non-arm version instead.
  for source in vars.get_sources():
    base, ext = os.path.splitext(source)
    if ext == '.arm':
      vars.get_sources().remove(source)
      vars.get_sources().append(base)


def _filter_all_make_to_ninja(vars):
  # All the following filters are only for the target.
  if vars.is_host():
    return True
  if vars.is_java_library() and open_source.is_open_source_repo():
    # We do not yet build all of the Java prerequisites in the open source
    # repository.
    return False
  if vars.is_c_library() or vars.is_executable():
    _filter_excluded_libs(vars)

    if not OPTIONS.is_arm():
      _filter_for_when_not_arm(vars)

  return True


def _list_ninja_generators(config_loader, name):
  for module in config_loader.find_config_modules(name):
    config_path = re.sub('\\.pyc$', '.py', module.__file__)
    yield (ConfigContext(config_path, module.__name__, name),
           getattr(module, name))


def _set_up_generate_ninja():
  # Create generated_ninja directory if necessary.
  ninja_dir = build_common.get_generated_ninja_dir()
  if not os.path.exists(ninja_dir):
    os.makedirs(ninja_dir)

  # Set up default resource path.
  framework_resources_base_path = (
      build_common.get_build_path_for_apk('framework-res', subpath='R'))
  ninja_generator.JavaNinjaGenerator.add_default_resource_include(
      os.path.join(framework_resources_base_path, 'framework-res.apk'))

  # Set up global filter for makefile to ninja translator.
  make_to_ninja.MakefileNinjaTranslator.add_global_filter(
      _filter_all_make_to_ninja)

  dependency_inspection.start_inspection()
  dependency_inspection.add_files(*_get_build_system_dependencies())
  make_to_ninja.prepare_make_to_ninja()
  depended_files = dependency_inspection.get_files()
  depended_listings = dependency_inspection.get_listings()
  dependency_inspection.stop_inspection()

  cache_to_save = []
  needs_clobbering = True
  if OPTIONS.enable_config_cache():
    needs_clobbering = False
    cache_path = _get_global_deps_file_path()
    global_deps = _load_global_deps_from_file(cache_path)
    if global_deps is None:
      needs_clobbering = True
      global_deps = CacheDependency()
    else:
      if not global_deps.check_freshness():
        needs_clobbering = True
    global_deps.refresh(depended_files, depended_listings)

    cache_to_save.append((global_deps, cache_path))

  _config_loader.load()

  return needs_clobbering, cache_to_save


def _generate_independent_ninjas(needs_clobbering):
  timer = build_common.SimpleTimer()

  # Invoke an unordered set of ninja-generators distributed across config
  # modules by name, and if that generator is marked for it.
  timer.start('Generating independent generate_ninjas', True)

  generator_list = list(_list_ninja_generators(
      _config_loader, 'generate_ninjas'))
  if OPTIONS.run_tests():
    generator_list.extend(_list_ninja_generators(
        _config_loader, 'generate_test_ninjas'))

  task_list = []
  cached_result_list = []
  cache_miss = {}

  for config_context, generator in generator_list:
    cache_path = _get_cache_file_path(config_context.config_name,
                                      config_context.entry_point)
    config_cache = None
    if OPTIONS.enable_config_cache() and not needs_clobbering:
      config_cache = _load_config_cache_from_file(cache_path)

    if config_cache is not None and config_cache.check_cache_freshness():
      cached_result = config_cache.to_config_result()
      if cached_result is not None:
        cached_result_list.append(cached_result)
        continue

    task_list.append(ninja_generator_runner.GeneratorTask(
        config_context, generator))
    cache_miss[cache_path] = config_cache

  result_list = ninja_generator_runner.run_in_parallel(
      task_list, OPTIONS.configure_jobs())

  aggregated_result = {}
  ninja_list = []
  for config_result in result_list:
    cache_path = _get_cache_file_path(config_result.config_name,
                                      config_result.entry_point)
    ninja_list.extend(config_result.generated_ninjas)
    if cache_path in aggregated_result:
      aggregated_result[cache_path].merge(config_result)
    else:
      aggregated_result[cache_path] = config_result

  for cached_result in cached_result_list:
    ninja_list.extend(cached_result.generated_ninjas)

  cache_to_save = []
  if OPTIONS.enable_config_cache():
    for cache_path, config_result in aggregated_result.iteritems():
      config_cache = cache_miss[cache_path]
      if config_cache is None:
        config_cache = _config_cache_from_config_result(config_result)
      else:
        config_cache.refresh_with_config_result(config_result)

      cache_to_save.append((config_cache, cache_path))

  ninja_list.sort(key=lambda ninja: ninja.get_module_name())
  timer.done()
  return ninja_list, cache_to_save


def _generate_shared_lib_depending_ninjas(ninja_list):
  timer = build_common.SimpleTimer()

  timer.start('Generating plugin and packaging ninjas', OPTIONS.verbose())
  # We must generate plugin/nexe ninjas after make->ninja lazy generation
  # so that we have the full list of production shared libraries to
  # pass to the load test.
  # These modules depend on shared libraries generated in the previous phase.
  production_shared_libs = (
      ninja_generator.NinjaGenerator.get_production_shared_libs(ninja_list[:]))
  generator_list = list(_list_ninja_generators(
      _config_loader, 'generate_shared_lib_depending_ninjas'))

  if OPTIONS.run_tests():
    generator_list.extend(_list_ninja_generators(
        _config_loader, 'generate_shared_lib_depending_test_ninjas'))

  result_list = ninja_generator_runner.run_in_parallel(
      [ninja_generator_runner.GeneratorTask(
          config_context,
          (generator, production_shared_libs))
       for config_context, generator in generator_list],
      OPTIONS.configure_jobs())
  ninja_list = []
  for config_result in result_list:
    ninja_list.extend(config_result.generated_ninjas)
  ninja_list.sort(key=lambda ninja: ninja.get_module_name())

  timer.done()
  return ninja_list


def _generate_dependent_ninjas(ninja_list):
  """Generate the stage of ninjas coming after all executables."""
  timer = build_common.SimpleTimer()

  timer.start('Generating dependent ninjas', OPTIONS.verbose())

  root_dir_install_all_targets = []
  for n in ninja_list:
    root_dir_install_all_targets.extend(build_common.get_android_fs_path(p) for
                                        p in n._root_dir_install_targets)

  generator_list = _list_ninja_generators(_config_loader,
                                          'generate_binaries_depending_ninjas')
  result_list = ninja_generator_runner.run_in_parallel(
      [ninja_generator_runner.GeneratorTask(
          config_context,
          (generator, root_dir_install_all_targets))
          for config_context, generator in generator_list],
      OPTIONS.configure_jobs())
  dependent_ninjas = []
  for config_result in result_list:
    dependent_ninjas.extend(config_result.generated_ninjas)

  notice_ninja = ninja_generator.NoticeNinjaGenerator('notices')
  notice_ninja.build_notices(ninja_list + dependent_ninjas)
  dependent_ninjas.append(notice_ninja)

  all_test_lists_ninja = ninja_generator.NinjaGenerator('all_test_lists')
  all_test_lists_ninja.build_all_test_lists(ninja_list)
  dependent_ninjas.append(all_test_lists_ninja)

  all_unittest_info_ninja = ninja_generator.NinjaGenerator('all_unittest_info')
  all_unittest_info_ninja.build_all_unittest_info(ninja_list)
  dependent_ninjas.append(all_unittest_info_ninja)

  timer.done()
  return dependent_ninjas


def _generate_top_level_ninja(ninja_list):
  """Generate build.ninja.  This must be the last generated ninja."""
  top_ninja = ninja_generator.TopLevelNinjaGenerator('build.ninja')
  top_ninja.emit_subninja_rules(ninja_list)
  top_ninja.emit_target_groups_rules(ninja_list + [top_ninja])
  return top_ninja


def _verify_ninja_generator_list(ninja_list):
  module_name_count_dict = collections.defaultdict(int)
  output_path_name_count_dict = collections.defaultdict(int)
  archive_ninja_list = []
  shared_ninja_list = []
  exec_ninja_list = []
  test_ninja_list = []
  for ninja in ninja_list:
    # Use is_host() in the key as the accounting should be done separately
    # for the target and the host.
    key = (ninja.get_module_name(), ninja.is_host())
    module_name_count_dict[key] += 1
    output_path_name_count_dict[ninja.get_ninja_path()] += 1
    if isinstance(ninja, ninja_generator.ArchiveNinjaGenerator):
      archive_ninja_list.append(ninja)
    if isinstance(ninja, ninja_generator.SharedObjectNinjaGenerator):
      shared_ninja_list.append(ninja)
    if isinstance(ninja, ninja_generator.ExecNinjaGenerator):
      if isinstance(ninja, ninja_generator.TestNinjaGenerator):
        test_ninja_list.append(ninja)
      else:
        exec_ninja_list.append(ninja)

  # Make sure there are no duplicated ninja modules.
  duplicated_module_list = [
      item for item in module_name_count_dict.iteritems() if item[1] > 1]
  if duplicated_module_list:
    errors = []
    for (module_name, is_host), count in duplicated_module_list:
      host_or_target = ('host' if is_host else 'target')
      error = '%s for %s: %d' % (module_name, host_or_target, count)
      errors.append(error)
    raise Exception(
        'Ninja generated multiple times: ' + ', '.join(errors))

  # Make sure there are no duplicated ninja files.
  duplicated_ninja_paths = [
      (path, count) for path, count in output_path_name_count_dict.iteritems()
      if count > 1]
  if duplicated_ninja_paths:
    errors = ['%s: %d' % (path, count)
              for path, count in duplicated_ninja_paths]
    raise Exception(
        'Ninja files generated multiple times: ' + ', '.join(errors))

  # Make sure for each modules, the expected usage count and actual reference
  # count is same.  The open source repository builds a subset of binaries so
  # we do not check its numbers.
  if not open_source.is_open_source_repo():
    ninja_generator.ArchiveNinjaGenerator.verify_usage(
        archive_ninja_list, shared_ninja_list, exec_ninja_list, test_ninja_list)


def generate_ninjas():
  needs_clobbering, cache_to_save = _set_up_generate_ninja()
  ninja_list, independent_ninja_cache = _generate_independent_ninjas(
      needs_clobbering)
  cache_to_save.extend(independent_ninja_cache)
  ninja_list.extend(
      _generate_shared_lib_depending_ninjas(ninja_list))
  ninja_list.extend(_generate_dependent_ninjas(ninja_list))

  top_level_ninja = _generate_top_level_ninja(ninja_list)
  ninja_list.append(top_level_ninja)

  # Run verification before emitting to files.
  _verify_ninja_generator_list(ninja_list)

  # Emit each ninja script to a file.
  timer = build_common.SimpleTimer()
  timer.start('Emitting ninja scripts', OPTIONS.verbose())
  for ninja in ninja_list:
    ninja.emit()
  top_level_ninja.emit_depfile()
  top_level_ninja.cleanup_out_directories(ninja_list)
  timer.done()

  if OPTIONS.enable_config_cache():
    for cache_object, cache_path in cache_to_save:
      cache_object.save_to_file(cache_path)
