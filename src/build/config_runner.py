#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import os

import build_common
import config_loader
import make_to_ninja
import ninja_generator
import ninja_generator_runner
import open_source
from build_options import OPTIONS


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


def _generate_independent_ninjas():
  timer = build_common.SimpleTimer()

  # Invoke an unordered set of ninja-generators distributed across config
  # modules by name, and if that generator is marked for it.
  timer.start('Generating independent generate_ninjas', True)
  task_list = list(config_loader.find_name('generate_ninjas'))
  if OPTIONS.run_tests():
    task_list.extend(config_loader.find_name('generate_test_ninjas'))
  ninja_list = ninja_generator_runner.run_in_parallel(task_list,
                                                      OPTIONS.configure_jobs())
  timer.done()

  return ninja_list


def _generate_shared_lib_depending_ninjas(ninja_list):
  timer = build_common.SimpleTimer()

  timer.start('Generating plugin and packaging ninjas', OPTIONS.verbose())
  # We must generate plugin/nexe ninjas after make->ninja lazy generation
  # so that we have the full list of shared libraries to pass to
  # the load test.
  # These modules depend on shared libraries generated in the previous phase.
  installed_shared_libs = (
      ninja_generator.NinjaGenerator.get_installed_shared_libs(ninja_list[:]))
  ninja_generators = list(
      config_loader.find_name('generate_shared_lib_depending_ninjas'))
  task_list = [(f, installed_shared_libs) for f in ninja_generators]

  if OPTIONS.run_tests():
    test_ninja_generators = list(
        config_loader.find_name('generate_shared_lib_depending_test_ninjas'))
    task_list.extend([(f, installed_shared_libs)
                     for f in test_ninja_generators])

  result = ninja_generator_runner.run_in_parallel(task_list,
                                                  OPTIONS.configure_jobs())
  timer.done()
  return result


def _generate_dependent_ninjas(ninja_list):
  """Generate the stage of ninjas coming after all executables."""
  timer = build_common.SimpleTimer()

  timer.start('Generating dependent ninjas', OPTIONS.verbose())

  root_dir_install_all_targets = []
  for n in ninja_list:
    root_dir_install_all_targets.extend(build_common.get_android_fs_path(p) for
                                        p in n._root_dir_install_targets)
  dependent_ninjas = ninja_generator_runner.run_in_parallel(
      [(job, root_dir_install_all_targets) for job in
       config_loader.find_name('generate_binaries_depending_ninjas')],
      OPTIONS.configure_jobs())

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
