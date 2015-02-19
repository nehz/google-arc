# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import errno
import marshal
import os
import pickle

import build_common
import dependency_inspection
import file_list_cache
import make_to_ninja
import ninja_generator
import ninja_generator_runner
import open_source
from build_options import OPTIONS
from config_loader import ConfigLoader
from util import file_util


_CONFIG_CACHE_VERSION = 0

_config_loader = ConfigLoader()


def _get_build_system_dependencies():
  options_file = OPTIONS.get_configure_options_file()
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
    return self.files.union(_get_build_system_dependencies())


class FileEntry(object):
  def __init__(self, mtime):
    self.mtime = mtime


class ConfigCache(object):
  """Represents an on-disk cache entry to persist the cache."""

  def __init__(self, config_name, entry_point,
               files, listings, generated_ninjas):
    self.config_name = config_name
    self.entry_point = entry_point
    self.files = files
    self.listings = listings
    self.generated_ninjas = generated_ninjas

  def refresh_with_config_result(self, config_result):
    assert self.config_name == config_result.config_name
    assert self.entry_point == config_result.entry_point
    files = {}
    for path in config_result.get_file_dependency():
      try:
        files[path] = FileEntry(os.stat(path).st_mtime)
      except OSError as e:
        if e.errno != errno.ENOENT:
          raise
    self.files = files

    new_listings = set()
    queries = config_result.listing_queries.copy()
    for listing in self.listings:
      if listing.query in queries:
        new_listings.add(listing)
        queries.remove(listing.query)
    for query in queries:
      new_listings.add(file_list_cache.FileListCache(query))
    for listing in new_listings:
      listing.refresh_cache()
    self.listings = new_listings

    self.generated_ninjas = config_result.generated_ninjas

  def check_cache_freshness(self):
    """Returns True if the cache is fresh."""

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

  def to_config_result(self):
    return ConfigResult(self.config_name, self.entry_point,
                        set(self.files.keys()),
                        {listing.query for listing in self.listings},
                        self.generated_ninjas)

  def to_dict(self):
    return {
        'version': _CONFIG_CACHE_VERSION,
        'config_name': self.config_name,
        'entry_point': self.entry_point,
        'files': [(path, entry.mtime)
                  for path, entry in self.files.iteritems()],
        'listings': [listing.to_dict() for listing in self.listings],
        'generated_ninjas': pickle.dumps(self.generated_ninjas),
    }

  def save_to_file(self, path):
    file_util.makedirs_safely(os.path.dirname(path))
    with open(path, 'w') as file:
      marshal.dump(self.to_dict(), file)


def _load_config_cache_from_file(path):
  try:
    with open(path, 'r') as file:
      data = marshal.load(file)
  except EOFError:
    return None
  except IOError as e:
    if e.errno == errno.ENOENT:
      return None
    raise

  if data['version'] != _CONFIG_CACHE_VERSION:
    return None

  config_name = data['config_name']
  entry_point = data['entry_point']
  files = {path: FileEntry(mtime) for path, mtime in data['files']}
  listings = {file_list_cache.file_list_cache_from_dict(listing)
              for listing in data['listings']}
  generated_ninjas = pickle.loads(data['generated_ninjas'])

  return ConfigCache(config_name, entry_point, files, listings,
                     generated_ninjas)


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
      config_result.generated_ninjas)


class ConfigContext:
  """A class that a task on ninja_generator_runner runs with.

  The instance is created for each config.py, hooks each task invocation and
  handles the results.
  """

  def __init__(self, config_name, entry_point):
    self.config_name = config_name
    self.entry_point = entry_point
    self.files = set()
    self.listing_queries = set()

  def set_up(self):
    dependency_inspection.reset()

  def tear_down(self):
    self.files.update(dependency_inspection.get_files())
    self.listing_queries.update(dependency_inspection.get_listings())

    dependency_inspection.stop()

  def make_result(self, ninja_list):
    return ConfigResult(self.config_name, self.entry_point,
                        self.files, self.listing_queries, ninja_list)


def _get_cache_file_path(config_name, entry_point):
  return os.path.join(build_common.get_config_cache_dir(),
                      config_name, entry_point)


def _filter_excluded_libs(vars):
  excluded_libs = [
      'libandroid',          # Added as an archive to plugin
      'libandroid_runtime',  # Added as an archive to plugin
      'libaudioutils',       # Converted to an archive
      'libbinder',           # Added as an archive to plugin
      'libcamera_client',    # Added as an archive to plugin
      'libcamera_metadata',  # Added as an archive to plugin
      'libcutils',           # Added as an archive to plugin
      'libcorkscrew',        # Added as an archive to plugin
      'libcrypto',           # Added as an archive to plugin
      'libcrypto_static',    # Added as an archive to plugin
      'libdl',               # Provided in Bionic replacement
      'libdvm',              # Added as an archive to plugin
      'libEGL',              # Added as an archive to plugin
      'libeffects',          # Added as an archive to plugin
      'libemoji',            # Added as an archive to plugin
      'libETC1',             # Added as an archive to plugin
      'libexpat',            # Added as an archive to plugin
      'libexpat_static',     # Added as an archive to plugin
      'libGLESv1_CM',        # Added as an archive to plugin
      'libGLESv2',           # Not built
      'libgui',              # Converted to an archive
      'libhardware',         # Added as an archive to plugin
      'libharfbuzz_ng',      # Added as an archive to plugin
      'libhwui',             # Added as an archive to plugin (when enabled)
      'libicui18n',          # Added as an archive to plugin
      'libicuuc',            # Added as an archive to plugin
      'libinput',            # Added as an archive to plugin
      'libjpeg',             # Added as an archive to plugin (as libjpeg_static)
      'liblog',              # Part of libcommon
      'libmedia',            # Converted to an archive
      'libskia',             # Added as an archive to plugin
      'libsonivox',          # Added as an archive to plugin
      'libsqlite',           # Added as an archive to plugin
      'libssl',              # Added as an archive to plugin
      'libssl_static',       # Added as an archive to plugin
      'libstlport',          # Trying to avoid in favor of GLIBC
      'libsync',             # FD sync is not supported
      'libui',               # Added as an archive to plugin
      'libz']                # Added as an archive to plugin

  deps = vars.get_shared_deps()
  deps[:] = [x for x in deps if x not in excluded_libs]
  deps = vars.get_static_deps()
  deps[:] = [x for x in deps if x not in excluded_libs]
  deps = vars.get_whole_archive_deps()
  deps[:] = [x for x in deps if x not in excluded_libs]


def _filter_for_nacl_x86_64(vars):
  # This supresses the -m32 load flag for 64-bit NaCl builds.
  if '-m32' in vars.get_ldflags():
    vars.get_ldflags().remove('-m32')


def _filter_for_arm(vars):
  # third_party/android/build/core/combo/TARGET_linux-arm.mk adds
  # this gold-only option for ARM. TODO(http://crbug.com/239870)
  # This flag may appear multiple times.
  while '-Wl,--icf=safe' in vars.get_ldflags():
    vars.get_ldflags().remove('-Wl,--icf=safe')


def _filter_libchromium_net(vars):
  # Handle libchromium_net. We have to convert libchromium_net to .a and
  # link it into shared libraries. Note that we cannot link it into the
  # plugin because of symbol conflicts with libchromium_base.a.
  assert 'libchromium_net' not in vars.get_static_deps()
  assert 'libchromium_net' not in vars.get_whole_archive_deps()
  deps = vars.get_shared_deps()
  if 'libchromium_net' in deps:
    deps.remove('libchromium_net')
    for lib in ['dmg_fp', 'libchromium_net', 'libevent', 'modp_b64']:
      vars.get_static_deps().append(lib)


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
    _filter_libchromium_net(vars)

    if OPTIONS.is_nacl_x86_64():
      _filter_for_nacl_x86_64(vars)

    if OPTIONS.is_arm():
      _filter_for_arm(vars)
    else:
      _filter_for_when_not_arm(vars)

  return True


def _list_ninja_generators(config_loader, name):
  for module in config_loader.find_config_modules(name):
    yield (ConfigContext(module.__name__, name), getattr(module, name))


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
  make_to_ninja.prepare_make_to_ninja()

  _config_loader.load_from_default_path()


def _generate_independent_ninjas():
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
    config_cache = _load_config_cache_from_file(cache_path)

    if config_cache is not None and config_cache.check_cache_freshness():
      cached_result_list.append(config_cache.to_config_result())
    else:
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

  for cache_path, config_result in aggregated_result.iteritems():
    config_cache = cache_miss[cache_path]
    if config_cache is None:
      config_cache = _config_cache_from_config_result(config_result)
    else:
      config_cache.refresh_with_config_result(config_result)

    config_cache.save_to_file(cache_path)

  ninja_list.sort(key=lambda ninja: ninja.get_module_name())
  timer.done()
  return ninja_list


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
  for config_cache in result_list:
    dependent_ninjas.extend(config_cache.generated_ninjas)

  notice_ninja = ninja_generator.NoticeNinjaGenerator('notices')
  notice_ninja.build_notices(ninja_list + dependent_ninjas)
  dependent_ninjas.append(notice_ninja)
  return dependent_ninjas


def _generate_top_level_ninja(ninja_list):
  """Generate build.ninja.  This must be the last generated ninja."""
  top_ninja = ninja_generator.TopLevelNinjaGenerator('build.ninja')
  top_ninja.emit_subninja_rules(ninja_list)
  top_ninja.emit_target_groups_rules(ninja_list + [top_ninja])
  return top_ninja


def _verify_ninja_generator_list(ninja_list):
  module_name_count_dict = collections.defaultdict(int)
  archive_ninja_list = []
  shared_ninja_list = []
  exec_ninja_list = []
  for ninja in ninja_list:
    # Use is_host() in the key as the accounting should be done separately
    # for the target and the host.
    key = (ninja.get_module_name(), ninja.is_host())
    module_name_count_dict[key] += 1
    if isinstance(ninja, ninja_generator.ArchiveNinjaGenerator):
      archive_ninja_list.append(ninja)
    if isinstance(ninja, ninja_generator.SharedObjectNinjaGenerator):
      shared_ninja_list.append(ninja)
    if (isinstance(ninja, ninja_generator.ExecNinjaGenerator) and
        # Do not check the used count of tests.
        not isinstance(ninja, ninja_generator.TestNinjaGenerator)):
      exec_ninja_list.append(ninja)

  # Make sure there is no duplicated ninja modules.
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

  # Make sure for each modules, the expected usage count and actual reference
  # count is same.  The open source repository builds a subset of binaries so
  # we do not check its numbers.
  if not open_source.is_open_source_repo():
    ninja_generator.ArchiveNinjaGenerator.verify_usage_counts(
        archive_ninja_list, shared_ninja_list, exec_ninja_list)


def generate_ninjas():
  _set_up_generate_ninja()
  ninja_list = []
  ninja_list.extend(_generate_independent_ninjas())
  ninja_list.extend(
      _generate_shared_lib_depending_ninjas(ninja_list))
  ninja_list.extend(_generate_dependent_ninjas(ninja_list))
  ninja_list.append(_generate_top_level_ninja(ninja_list))

  # Run verification before emitting to files.
  _verify_ninja_generator_list(ninja_list)

  # Emit each ninja script to a file.
  timer = build_common.SimpleTimer()
  timer.start('Emitting ninja scripts', OPTIONS.verbose())
  for ninja in ninja_list:
    ninja.emit()
  timer.done()
