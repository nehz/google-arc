# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# TODO(crbug.com/312571): The class name suffix XxxNinjaGenerator looks
# redundant. Rename NinjaGenerator family into simpler one.

import collections
import copy
import fnmatch
import hashlib
import json
import logging
import multiprocessing
import os
import pipes
import re
import StringIO
import traceback

import ninja_syntax

from src.build import analyze_diffs
from src.build import build_common
from src.build import ninja_generator_runner
from src.build import notices
from src.build import open_source
from src.build import staging
from src.build import toolchain
from src.build import wrapped_functions
from src.build.build_options import OPTIONS
from src.build.util import file_util
from src.build.util import python_deps
from src.build.util.test import unittest_util

# Extensions of primary source files.
_PRIMARY_EXTENSIONS = ['.c', '.cpp', '.cc', '.java', '.S', '.s']


def get_libgcc_for_bare_metal():
  return os.path.join(build_common.get_build_dir(),
                      'intermediates/libgcc/libgcc.a')


def get_libgcc_eh_for_nacl():
  return os.path.join(build_common.get_build_dir(),
                      'intermediates/libgcc/libgcc_eh.a')


def get_libgcc_installed_dir_for_bare_metal():
  assert OPTIONS.is_bare_metal_build()
  return ('third_party/ndk/toolchains/arm-linux-androideabi-4.6/prebuilt/'
          'linux-x86/lib/gcc/arm-linux-androideabi/4.6/armv7-a')


def _get_libgcc_for_bionic_realpath():
  # Compilers uses libgcc.a as the runtime library, and emit code to call
  # functions in libgcc.a.
  # https://gcc.gnu.org/onlinedocs/gccint/Libgcc.html
  #
  # TODO(crbug.com/283798): We might need to build libgcc by ourselves.
  if OPTIONS.is_nacl_build():
    # libgcc_eh.a contains exception handling code that we use it to get
    # backtrace.
    return [os.path.join(toolchain.get_nacl_libgcc_dir(), 'libgcc.a'),
            get_libgcc_eh_for_nacl()]
  elif OPTIONS.is_bare_metal_build():
    return [get_libgcc_for_bare_metal()]
  raise Exception('Bionic is not supported yet for ' + OPTIONS.target())


def get_libgcc_for_bionic():
  """Returns libgcc path for the current target.

  When libgcc for the current target exists under third party directory, this
  function returns the corresponding staging path, which starts with
  out/staging.
  """
  return map(staging.third_party_to_staging, _get_libgcc_for_bionic_realpath())


def get_configuration_dependencies():
  deps = [
      'src/build/DEPS.android-sdk',
      'src/build/DEPS.chrome',
      'src/build/DEPS.naclsdk',
      'src/build/DEPS.ndk',
      'src/build/build_common.py',
      'src/build/build_options.py',
      'src/build/sync_arc_int.py',
      'src/build/config.py',
      'src/build/config_loader.py',
      'src/build/config_runner.py',
      'src/build/download_sdk_and_ndk.py',
      'src/build/gms_core_ninja_generator.py',
      'src/build/make_to_ninja.py',
      'src/build/ninja_generator.py',
      'src/build/sync_adb.py',
      'src/build/sync_chrome_deps.py',
      'src/build/sync_gdb_multiarch.py',
      'src/build/sync_nacl_sdk.py',
      'src/build/toolchain.py',
      'src/build/wrapped_functions.py',
      'third_party/android/build/target/product/core_minimal.mk']

  if not open_source.is_open_source_repo():
    deps += [
        'src/build/sync_chrome.py',
        'src/packaging/runtime/active_window_back.png',
        'src/packaging/runtime/active_window_close.png',
        'src/packaging/runtime/active_window_extdir.png',
        'src/packaging/runtime/active_window_maximize.png',
        'src/packaging/runtime/active_window_minimize.png',
        'src/packaging/runtime/style.css']
  return deps


class _TargetGroupInfo(object):
  def __init__(self):
    self.outputs = set()
    self.inputs = set()
    self.required_target_groups = set()

  def get_root_set(self):
    return self.outputs - self.inputs


class _TargetGroups(object):
  # We are trying to keep the number of target groups to a small,
  # managable level, so we whitelist the ones that are allowed.
  ALL = 'all'
  DEFAULT = 'default'

  def __init__(self):
    self._map = collections.defaultdict(_TargetGroupInfo)
    self._started_emitting = False
    self._allowed = set()
    self.define_target_group(self.DEFAULT)
    self.define_target_group(self.ALL, self.DEFAULT)

  def define_target_group(self, target_group, required=None):
    assert set(build_common.as_list(required)) <= self._allowed
    self._allowed.add(target_group)
    self._map[target_group].required_target_groups = (
        build_common.as_list(required))

  def record_build_rule(self, target_groups, outputs, inputs):
    """Remembers the build rule for later writing target group rule."""
    if self._started_emitting:
      return
    if not target_groups <= self._allowed:
      raise Exception('Unexpected target groups: %s' %
                      (target_groups - self._allowed))
    for target_group in target_groups:
      my_info = self._map[target_group]
      my_info.outputs |= outputs
      my_info.inputs |= inputs

  def emit_rules(self, n):
    self._started_emitting = True
    for tg, tgi in self._map.iteritems():
      implicit = (sorted(list(tgi.required_target_groups)) +
                  sorted(list(tgi.get_root_set())))
      n.build(tg, 'phony', implicit=implicit)
    n.default(self.DEFAULT)


class _VariableValueBuilder(object):
  """Utility class for extending an existing Ninja variable (defined in an
  different scope) with additional flags"""

  def __init__(self, base_flag):
    super(_VariableValueBuilder, self).__init__()
    self._base_flag = base_flag
    self._extra = []

  def append_flag(self, flag):
    """Adds the indicated flag"""
    self._extra.append(flag)

  def append_flag_pattern(self, flag_pattern, values):
    """Formats the given flag pattern using each entry in values."""
    for value in build_common.as_list(values):
      self._extra.append(flag_pattern % value)

  def append_optional_path_list(self, flag, paths):
    """If paths is not empty, adds a flag for the paths."""
    if paths:
      self.append_flag(flag + ' ' + ':'.join(paths))

  def __str__(self):
    extra = ' '.join(self._extra)
    if self._base_flag:
      return '$%s %s' % (self._base_flag, extra)
    else:
      return extra


class _BootclasspathComputer(object):

  _string = None
  _classes = []
  _installed_jars = []

  @staticmethod
  def _compute_jar_list_from_core_minimal_definition(definition_name):
    name_list = _extract_pattern_from_file(
        'third_party/android/build/target/product/core_minimal.mk',
        definition_name + r' := ((.*\\\n)*.*\n)')
    return ['/system/framework/%s.jar' % name.strip()
            for name in name_list.split('\\\n') if name.strip()]

  @staticmethod
  def _compute():
    """Compute the system's bootclasspath.

    The odex format and dependency analysis requires the bootclasspath
    contents and order to be the same during build time and run time.
    This function determines that bootclasspath.
    """
    if _BootclasspathComputer._string is None:
      upstream_installed = (
          _BootclasspathComputer._compute_jar_list_from_core_minimal_definition(
              'PRODUCT_BOOT_JARS'))

      # We do not have mms-common.jar yet.
      try:
        upstream_installed.remove('/system/framework/mms-common.jar')
      except:
        logging.error('Could not remove from: %s' % upstream_installed)
        raise

      # TODO(crbug.com/414569): The Android build code now seems to have this
      # next list of .jars as a classpath and not a bootclasspath. We should
      # probably be consistent with it, but to get things to work without a lot
      # of ARC code fixups, we add them to the bootclasspath
      upstream_installed.extend(
          _BootclasspathComputer._compute_jar_list_from_core_minimal_definition(
              'PRODUCT_SYSTEM_SERVER_JARS'))

      # Insert arc-services-framework.jar before services.jar which depends
      # on it.
      upstream_installed.insert(
          upstream_installed.index('/system/framework/services.jar'),
          '/system/framework/arc-services-framework.jar')
      # Insert cmds.jar before arc-services-fromework.jar which depends on it.
      upstream_installed.insert(
          upstream_installed.index(
              '/system/framework/arc-services-framework.jar'),
          '/system/framework/cmds.jar')
      _BootclasspathComputer._string = ':'.join(upstream_installed)
      _BootclasspathComputer._installed_jars = upstream_installed
      _BootclasspathComputer._classes = [
          build_common.get_build_path_for_jar(
              os.path.splitext(os.path.basename(j))[0],
              subpath='classes.jar')
          for j in upstream_installed]

  @staticmethod
  def get_string():
    """Return string representation of runtime bootclasspath.

    This is something like /system/framework/core.jar:...."""
    _BootclasspathComputer._compute()
    return _BootclasspathComputer._string

  @staticmethod
  def get_installed_jars():
    """Returns array of installed bootclasspath jars."""
    _BootclasspathComputer._compute()
    return _BootclasspathComputer._installed_jars

  @staticmethod
  def get_classes():
    """Returns array of bootclasspath classes.jar files."""
    _BootclasspathComputer._compute()
    return _BootclasspathComputer._classes


class NinjaGenerator(ninja_syntax.Writer):
  """Encapsulate ninja file generation.

  Simplify ninja file generation by naming, creating, and tracking
  all ninja files.  This removes boilerplate code required to
  create new ninja files.
  """

  _EXTRACT_TEST_LIST_PATH = 'src/build/util/test/extract_test_list.py'
  _GENERATE_FILE_FROM_TEMPLATE_PATH = (
      'src/packaging/generate_file_from_template.py')
  _PRETTY_PRINT_JSON_PATH = 'src/build/util/pretty_print_json.py'

  # Default implicit dependencies.
  _default_implicit = []

  def __new__(type, *args, **kargs):
    obj = super(NinjaGenerator, type).__new__(type, *args, **kargs)
    if OPTIONS.is_ninja_generator_logging():
      # Installs the debugingo into the class instance.
      # [-1] is __new__().
      # [-2] is the caller of ninja generators.
      obj._debuginfo = traceback.format_stack()[-2]
    return obj

  def __init__(self, module_name, ninja_name=None,
               host=False, generate_path=True, base_path=None,
               implicit=None, target_groups=None,
               extra_notices=None, notices_only=False,
               use_global_scope=False):
    if ninja_name is None:
      ninja_name = module_name
      # Ensure the base ninja filename is only made of alphanumeric characters
      # or a short list of other allowed characters. Convert anything else into
      # an underscore.
      ninja_name = re.sub(r'[^\w\-+_.]', '_', ninja_name)
    self._module_name = module_name
    self._ninja_name = ninja_name
    self._is_host = host
    if generate_path:
      ninja_path = NinjaGenerator._get_generated_ninja_path(ninja_name,
                                                            self._is_host)
    else:
      ninja_path = ninja_name
    super(NinjaGenerator, self).__init__(StringIO.StringIO())
    ninja_generator_runner.register_ninja(self)
    self._ninja_path = ninja_path
    self._base_path = base_path
    self._notices_only = notices_only
    self._implicit = (build_common.as_list(implicit) +
                      NinjaGenerator._default_implicit)
    if not self._is_host:
      self._implicit.extend(toolchain.get_tool(OPTIONS.target(), 'deps'))
    self._target_groups = NinjaGenerator._canonicalize_set(target_groups)
    self._build_rule_list = []
    self._root_dir_install_targets = []
    self._build_dir_install_targets = []
    self._notices = notices.Notices()
    self._test_lists = []
    self._test_info_list = []
    self._output_path_list = set()
    if extra_notices:
      if OPTIONS.is_notices_logging():
        print 'Adding extra notices to %s: %s' % (module_name, extra_notices)
      self._notices.add_sources(extra_notices)
    # TODO(crbug.com/366751): remove notice_archive hack when possible
    self._notice_archive = None

    # This Ninja will be imported to the top-level ninja by "include" statement
    # instead of "subninja" if |_use_global_scope| is True.  So that all
    # variables and rules are available in all subninjas.
    # TODO(tzik): Shared rules needs to be in the global scope to support
    # Ninja-1.5.3 or older. Move them to where the rule is used once we fully
    # moved to a newer Ninja.
    self._use_global_scope = use_global_scope

    if OPTIONS.is_ninja_generator_logging():
      for line in self._debuginfo.split('\n'):
        self.comment(line)
      if self._base_path:
        self.comment('base_path: ' + self._base_path)

  @staticmethod
  def emit_common_rules(n):
    n.rule('copy_symbols_file',
           'src/build/symbol_tool.py --clean $in > $out',
           description='copy_symbols_file $in $out')
    n.rule('cp',
           'cp $in $out',
           description='cp $in $out')
    n.rule('dump_defined_symbols',
           'src/build/symbol_tool.py --dump-defined $in > $out',
           description='dump_defined_symbols $in')
    n.rule('dump_undefined_symbols',
           'src/build/symbol_tool.py --dump-undefined $in > $out',
           description='dump_undefined_symbols $in')
    n.rule('install',
           'rm -f $out; cp $in $out',
           description='install $out')
    n.rule('strip',
           '%s $in -o $out' % toolchain.get_tool(OPTIONS.target(), 'strip'),
           description='strip $out')
    n.rule('mkdir_empty',
           'mkdir -p $out && touch $out',
           description='make empty $out')
    # TODO(crbug.com/242783): Would be nice we can make directories readonly.
    n.rule('readonly_install',
           'rm -f $out; cp $in $out; chmod -w $out',
           description='install $out as readonly')
    n.rule('touch',
           'touch $out')
    n.rule('verify_disallowed_symbols',
           ('src/build/symbol_tool.py --verify $in $disallowed_symbols && '
            'touch $out'),
           description='verify_disallowed_symbols $out')
    # $command must create $out on success.
    # restat=True, so that Ninja record the mtime of the target to prevent
    # rerunning the command in the next Ninja invocation.
    n.rule('run_shell_command',
           command='$command || (rm $out; exit 1)',
           description='execute $command', restat=True)

    # Rule to make the list of inputs.
    n.rule('make_list',
           command='echo "$in_newline" > $out',
           description='make_list $out')

    # Rule to make the list of external symbols in a shared library.
    # Setting restat to True so that ninja can stop building its dependents
    # when the content is not modified.
    n.rule('mktoc',
           'src/build/make_table_of_contents.py $target $in $out',
           description='make_table_of_contents $in',
           restat=True)

    # Rule to make a list of tests from .apk. This is shared with
    # AtfNinjaGenerator and ApkFromSdkNinjaGenerator.
    n.rule('extract_test_list',
           ('src/build/run_python %s '
            '--apk=$in --output=$out.tmp && mv $out.tmp $out' %
            NinjaGenerator._EXTRACT_TEST_LIST_PATH),
           description='Extract test method list from $in')

    n.rule('build_test_info',
           'mkdir -p %s && %s $test_info > $out' % (
               build_common.get_unittest_info_path(),
               NinjaGenerator._PRETTY_PRINT_JSON_PATH),
           description='Build test info $out')

    n.rule('generate_from_template',
           command=('%s $keyvalues $in > $out || (rm -f $out; exit 1)' %
                    NinjaGenerator._GENERATE_FILE_FROM_TEMPLATE_PATH),
           description='generate_from_template $out')

  @staticmethod
  def _canonicalize_set(target_groups):
    canon = set(build_common.as_list(target_groups))
    if len(canon) == 0:
      canon.add(_TargetGroups.DEFAULT)
    else:
      canon.add(_TargetGroups.ALL)
    return canon

  def emit(self):
    """Emits the contents of ninja script to the file."""
    with open(self._ninja_path, 'w') as f:
      f.write(self.output.getvalue())

  def add_flags(self, key, *values):
    values = [pipes.quote(x) for x in values]
    self.variable(key, '$%s %s' % (key, ' '.join(values)))
    return self

  def is_host(self):
    return self._is_host

  def get_module_name(self):
    return self._module_name

  def get_base_path(self):
    return self._base_path

  def get_build_path(self, name):
    return os.path.join(self.get_intermediates_dir(), name)

  def get_ninja_path(self):
    return self._ninja_path

  def get_output_path_list(self):
    return self._output_path_list

  @staticmethod
  def _add_bionic_stdlibs(flags, is_so, is_system_library):
    # We link crt(begin|end)(_so).o into everything except runnable-ld.so.
    if is_so:
      flags.insert(0, '$crtbegin_for_so')
      flags.append(build_common.get_bionic_crtend_so_o())
    elif not is_system_library:
      flags.insert(0, build_common.get_bionic_crtbegin_o())
      flags.append(build_common.get_bionic_crtend_o())

  @staticmethod
  def _add_target_library_flags(target, flags,
                                is_so=False, is_system_library=False):
    if OPTIONS.is_bare_metal_build() or target == 'host':
      # We intentionally do not set --thread flag of gold. This
      # feature seems to be flaky for us. See crbug.com/366358
      flags.extend(['-fuse-ld=gold'])
    if target == 'host':
      flags.extend(['-lpthread', '-ldl', '-lrt'])
    else:
      CNinjaGenerator._add_bionic_stdlibs(flags, is_so, is_system_library)

  def get_ldflags(self, is_host=False):
    ldflags = ['$commonflags', '-Wl,-z,noexecstack']

    if not OPTIONS.is_debug_info_enabled():
      ldflags.append('-Wl,--strip-all')

    if not is_host:
      if not OPTIONS.is_nacl_build():
        # Clang ignores '-pthread' and warns it's unused when '-nostdlib' is
        # specified.
        ldflags.append('-pthread')
      ldflags.append('-nostdlib')
    return ' '.join(ldflags)

  @staticmethod
  def _get_target_ld_flags(target, is_so=False, is_system_library=False):
    flags = []

    # This should be specified before $ldflags so we can overwrite it
    # for no-elf-hash-table-library.so.
    if target != 'host' and OPTIONS.is_bare_metal_build():
      # Goobuntu's GCC uses --hash-style=gnu by default, but the
      # Bionic loader cannot handle GNU hash.
      flags.append('-Wl,--hash-style=sysv')

    if is_so:
      flag_variable = '$hostldflags' if target == 'host' else '$ldflags'
      flags.extend(['-shared', flag_variable, '-Wl,-Bsymbolic', '@$out.files'])
    else:
      if (target != 'host' and OPTIONS.is_bare_metal_build() and
          not is_system_library):
        flags.append('-pie')
      flags.append('$in')

    flags.extend(['-Wl,--start-group,--whole-archive',
                  '$my_whole_archive_libs',
                  '-Wl,--end-group,--no-whole-archive',
                  '-Wl,--start-group',
                  '$my_static_libs',
                  '$my_shared_libs',
                  '-Wl,--end-group',
                  '$ldadd'])

    # --build-id is expected by 'perf report' tool to more reliably identify
    # original binaries when it looks for symbol information.
    # Additionally this flag is needed to match up symbol uploads for
    # breakpad.
    flags.append('-Wl,--build-id')

    # This is needed so that symbols in the main executables can be
    # referenced in loaded shared libraries.
    flags.append('-rdynamic')

    # Force ET_EXEC to export _Unwind_GetIP for Bionic build. Because
    # libc_malloc_debug_leak.so has an undefined reference to this
    # symbol, it cannot be dlopen'ed if the main binary does not have
    # this symbol.
    # TODO(crbug.com/283798): We can remove this if we decide to
    # create libgcc.so instead of libgcc.a.
    # TODO(crbug.com/319020): Bare Metal ARM would require another symbol.
    if not is_so and target != 'host' and not OPTIONS.is_arm():
      flags.append('-Wl,-u,_Unwind_GetIP')

    NinjaGenerator._add_target_library_flags(
        target, flags, is_so=is_so, is_system_library=is_system_library)

    # Make sure we have crtbegin as the first object and crtend as the
    # last object for Bionic build.
    if (target != 'host' and (is_so or not is_system_library)):
      assert re.search(r'/crtbegin.o|\$crtbegin_for_so', flags[0])
      assert re.search(r'/crtendS?\.o', flags[-1])

    return ' '.join(flags)

  @staticmethod
  def _rebase_to_build_dir(path):
    return os.path.join(build_common.get_build_dir(), path.lstrip(os.sep))

  def install_to_root_dir(self, output, inputs):
    top_dir = output.lstrip(os.path.sep).split(os.path.sep)[0]
    if top_dir not in ['dev', 'proc', 'sys', 'system', 'usr', 'vendor']:
      raise Exception(output + ' does not start with known top dir')
    root_path = build_common.get_android_fs_path(output)
    self.build(root_path, 'readonly_install', inputs)
    self._root_dir_install_targets.append(output)

  def install_to_build_dir(self, output, inputs):
    out_path = self._rebase_to_build_dir(output)
    self.build(out_path, 'install', inputs)
    # Generate stripped binaries as well for remote execution.
    if OPTIONS.is_debug_info_enabled():
      if os.path.splitext(out_path)[1] in ['.nexe', '.so']:
        self.build_stripped(out_path)
    self._build_dir_install_targets.append('/system/' + output.lstrip(os.sep))

  def is_installed(self):
    return self._build_dir_install_targets or self._root_dir_install_targets

  def find_all_files(self, base_paths, suffix, **kwargs):
    return build_common.find_all_files(base_paths, suffixes=suffix, **kwargs)

  def find_all_contained_files(self, suffix, **kwargs):
    return build_common.find_all_files([self._base_path], suffix, **kwargs)

  def _validate_outputs(self, rule, outputs):
    if rule == 'phony':
      # Builtin phony rule does not output any files.
      return
    for o in outputs:
      if (not o.startswith(build_common.OUT_DIR) and
          not o == 'build.ninja'):
        raise Exception('Output %s in invalid location' % o)
      if o.startswith(build_common.get_staging_root()):
        raise Exception('Output %s must not go to staging directory' % o)

  def add_notice_sources(self, sources):
    sources_including_tracking = sources[:]
    for s in sources:
      if (s.startswith(build_common.OUT_DIR) and
          not s.startswith(build_common.get_staging_root())):
        continue
      if not os.path.exists(s):
        continue
      with open_dependency(s, 'r', ignore_dependency=True) as f:
        tracking_file = analyze_diffs.compute_tracking_path(None, s, f)
        if tracking_file:
          sources_including_tracking.append(tracking_file)
    if OPTIONS.is_notices_logging():
      print 'Adding notice sources to %s: %s' % (self.get_module_name(),
                                                 sources_including_tracking)
    self._notices.add_sources(sources_including_tracking)

  def build(self, outputs, rule, inputs=None, variables=None,
            implicit=None, order_only=None, use_staging=True, **kwargs):
    outputs = build_common.as_list(outputs)
    all_inputs = build_common.as_list(inputs)
    in_real_path = []
    updated_inputs = []
    self._validate_outputs(rule, outputs)
    for i in all_inputs:
      if use_staging and staging.is_in_staging(i):
        in_real_path.append(staging.as_real_path(i))
        updated_inputs.append(staging.as_staging(i))
      else:
        in_real_path.append(i)
        updated_inputs.append(i)
    self.add_notice_sources(updated_inputs)
    if variables is None:
      variables = {}
    implicit = self._implicit + build_common.as_list(implicit)
    # Give a in_real_path for displaying to the user.  Realistically
    # if there are more than 5 inputs they'll be truncated when displayed
    # so truncate them now to save space in ninja files.
    variables['in_real_path'] = ' '.join(in_real_path[:5])
    self._output_path_list.update(outputs)
    self._build_rule_list.append(
        (self._target_groups, set(outputs),
         set(build_common.as_list(implicit)) | set(all_inputs)))

    self._check_implicit(rule, implicit)
    self._check_order_only(implicit, order_only)
    self._check_target_independent_does_not_depend_on_target(
        outputs,
        updated_inputs + implicit + build_common.as_list(order_only),
        variables)
    return super(NinjaGenerator, self).build(outputs,
                                             rule,
                                             implicit=implicit,
                                             order_only=order_only,
                                             inputs=updated_inputs,
                                             variables=variables,
                                             **kwargs)

  def build_stripped(self, obj):
    """Create stripped version of |obj| used for remote execution."""
    stripped_path = build_common.get_stripped_path(obj)
    assert stripped_path, 'build_stripped takes path under out/target/<target>'
    self.build(stripped_path, 'strip', inputs=obj)

  @staticmethod
  def _get_generated_ninja_path(ninja_base, is_host):
    basename = ninja_base + ('_host.ninja' if is_host else '.ninja')
    return os.path.join(
        build_common.get_generated_ninja_dir(), basename)

  @staticmethod
  def _get_name_and_driver(rule_prefix, target):
    return (rule_prefix + '.' + target,
            toolchain.get_tool(target, rule_prefix))

  def emit_compiler_rule(self, rule_prefix, target, flag_name,
                         supports_deps=True, extra_flags=None,
                         compiler_includes=None):
    extra_flags = build_common.as_list(extra_flags)
    rule_name, driver_name = NinjaGenerator._get_name_and_driver(rule_prefix,
                                                                 target)
    if flag_name is None:
      flag_name = rule_prefix + 'flags'
    # We unfortunately need to avoid using -MMD due to the bug described
    # here: http://gcc.gnu.org/bugzilla/show_bug.cgi?id=28435 .
    # This means we will capture dependencies of changed system headers
    # (which is good since some of these we could be changing, and is
    # bad since some we will never change and it will slow down null
    # builds.)  The trade off is moot since we must have missing
    # headers result in errors.
    is_clang = rule_prefix.startswith('clang')
    if ((is_clang and toolchain.get_clang_version(target) >= [3, 6, 0]) or
        (not is_clang and toolchain.get_gcc_version(target) >= [4, 8, 0])):
      # gcc 4.8 and clang-3.6 have a new check warning
      # "-Wunused-local-typedefs", but most sources are not ready for this.
      # So we disable this warning for now.
      extra_flags.append('-Wno-unused-local-typedefs')

    flags = '$' + flag_name + ' ' + ' '.join(extra_flags)
    if compiler_includes is not None:
      flags = '$' + compiler_includes + ' ' + flags

    if supports_deps:
      self.rule(rule_name,
                deps='gcc',
                depfile='$out.d',
                command='%s -MD -MF $out.d %s -c $in -o $out' %
                        (driver_name, flags),
                description=rule_name + ' $in_real_path')
    else:
      self.rule(rule_name,
                command='%s %s -c $in -o $out' % (driver_name, flags),
                description=rule_name + ' $in_real_path')

  def emit_linker_rule(self, rule_prefix, target, flag_name):
    rule_name, driver_name = NinjaGenerator._get_name_and_driver(rule_prefix,
                                                                 target)
    common_args = NinjaGenerator._get_target_ld_flags(
        target, is_so=False,
        is_system_library=('_system_library' in rule_prefix))
    self.rule(rule_name,
              command=(driver_name + ' $' + flag_name + ' -o $out ' +
                       common_args),
              description=rule_name + ' $out')

  def emit_ar_rule(self, rule_prefix, target):
    rule_name, driver_name = NinjaGenerator._get_name_and_driver(rule_prefix,
                                                                 target)
    self.rule(rule_name,
              command='rm -f $out && ' + driver_name + ' rcsT $out $in',
              description='archive $out')

  @staticmethod
  def get_symbols_path():
    return os.path.join(build_common.get_build_dir(), 'gen_symbols')

  def _check_order_only(self, implicit, order_only):
    """Checks if order_only dependency is used properly."""
    def _is_header(f):
      # .inc is a header file for .S or a generated header file by llvm-tblgen.
      # .gen is also a generated header file by llvm-tblgen.
      return os.path.splitext(f)[1] in ['.gen', '.h', '.inc']
    # Checking if |self| is CNinjaGenerator or its sub class is necessary
    # because for non-C/C++ generators, having header files in implicit is
    # sometimes valid. 'lint' rule is a good example.
    if isinstance(self, CNinjaGenerator) and implicit:
      implicit_headers = filter(lambda f: _is_header(f), implicit)
      if len(implicit_headers):
        raise Exception('C/C++/ASM headers should not be in implicit=. Use '
                        'order_only= instead: ' + str(implicit_headers))

    if order_only:
      non_headers = filter(lambda f: not _is_header(f), order_only)
      if len(non_headers):
        raise Exception('Only C/C++/ASM headers should be in order_only=. Use '
                        'implicit= instead: ' + str(non_headers))

  def _check_implicit(self, rule, implicit):
    """Checks that there are no implicit dependencies on third party paths.

    When a file in third party directory is inadvertently set as implicit,
    modifying the corresponding file in mods directory does not trigger
    rebuild. This check is for avoiding such incorrect implicit dependencies
    on files in third party directories.
    """
    # It is valid for lint and python test rules to have implicit dependencies
    # on third party paths.
    if rule in ('lint', 'run_python_test'):
      return
    # The list of paths for which implicit dependency check is skipped.
    implicit_check_skip_patterns = (
        # phony rule has implicit dependency on this.
        'build.ninja',
        # Files in canned directory are not staged and OK to be in implicit.
        'canned/*',
        # phony rule has implicit dependency on this.
        'default',
        # Files in mods are OK to be implicit because they are ensured to
        # trigger rebuild when they are modified unlike files in third party
        # directories.
        'internal/mods/*',
        'mods/*',
        # Files in out/ are generated files or in staging directory. It is
        # valid for them to be in implicit.
        'out/*',
        # Files in src are not overlaid by any files, so it is OK for the files
        # to be implicit.
        'src/*',
    )
    for dep in implicit:
      if os.path.isabs(dep):
        dep = os.path.relpath(dep, build_common.get_arc_root())
      if not any(fnmatch.fnmatch(dep, pattern) for pattern in
                 implicit_check_skip_patterns):
        raise Exception('%s in rule: %s\n'
                        'Avoid third_party/ paths in implicit dependencies; '
                        'use staging paths instead.' % (dep, rule))

  def _check_target_independent_does_not_depend_on_target(self, outputs,
                                                          inputs, variables):
    target_dir = build_common.get_build_dir()
    target_independent_outputs = [f for f in outputs if target_dir not in f]
    if not target_independent_outputs:
      return

    target_dependent_inputs = [
        f for f in inputs if build_common.get_build_dir() in f]
    if target_dependent_inputs:
      logging.info(
          'Target independent files (%s) depend on '
          'files in target directory (%s).' %
          (' '.join(target_independent_outputs),
           ' '.join(target_dependent_inputs)))

    target_dependent_variables = [
        '%s=%s' % (k, v) for k, v in variables.iteritems()
        if target_dir in str(v)]
    if target_dependent_variables:
      logging.info(
          'Target independent files (%s) depend on '
          'target specific variables (%s).' %
          (' '.join(target_independent_outputs),
           ' '.join(target_dependent_variables)))

  def _check_symbols(self, object_files, disallowed_symbol_files):
    for object_file in object_files:
      # Dump all undefined symbols in the |object_file|.
      undefined_symbol_file = os.path.join(
          self.get_symbols_path(), os.path.basename(object_file) + '.undefined')
      self.build([undefined_symbol_file], 'dump_undefined_symbols', object_file,
                 implicit='src/build/symbol_tool.py')
      for disallowed_symbol_file in disallowed_symbol_files:
        # Check the content of the |undefined_symbol_file|.
        disallowed_symbol_file_full = os.path.join(
            self.get_symbols_path(), disallowed_symbol_file)
        out_path = undefined_symbol_file + '.checked.' + disallowed_symbol_file
        self.build([out_path],
                   'verify_disallowed_symbols', undefined_symbol_file,
                   variables={'disallowed_symbols':
                              disallowed_symbol_file_full},
                   implicit=[disallowed_symbol_file_full,
                             'src/build/symbol_tool.py'])

  @staticmethod
  def get_production_shared_libs(ninja_list):
    """Returns production shared libs in the given ninja_list."""
    production_shared_libs = []
    for ninja in ninja_list:
      if not isinstance(ninja, SharedObjectNinjaGenerator):
        continue
      for path in ninja.production_shared_library_list:
        production_shared_libs.append(build_common.get_build_dir() + path)
    return production_shared_libs

  def get_notices_install_path(self):
    """Pick a name for describing this generated artifact in NOTICE.html."""
    if self._build_dir_install_targets:
      result = self._build_dir_install_targets[0]
    elif self._root_dir_install_targets:
      result = self._root_dir_install_targets[0]
    else:
      return None
    return result.lstrip(os.sep) + '.txt'

  # TODO(crbug.com/366751): remove notice_archive hack when possible
  def set_notice_archive(self, notice_archive):
    self._notice_archive = notice_archive

  def get_notice_archive(self):
    return self._notice_archive

  def get_included_module_names(self):
    """Return the list of NinjaGenerator module_names built into this module.

    This is necessary for licensing.  If a module is built into this module
    (with static linking, for instance), this module inherits the licenses of
    the included module."""
    return []

  def _build_test_list(self, final_package_path, rule, test_list_name,
                       implicit):
    test_list_path = build_common.get_integration_test_list_path(
        test_list_name)
    self._test_lists.append(test_list_path)
    self.build([test_list_path],
               rule,
               inputs=final_package_path,
               implicit=implicit)

  def build_all_test_lists(self, ninja_list):
    all_test_lists = []
    for ninja in ninja_list:
      all_test_lists.extend(ninja._test_lists)
    all_test_lists.sort()
    self.build([build_common.get_all_integration_test_lists_path()],
               'make_list',
               all_test_lists)

  def get_test_info_path(self, test_path, counter):
    test_name = os.path.basename(test_path)
    filename = '%s.%d.json' % (test_name, counter)
    return build_common.get_unittest_info_path(filename)

  def _build_test_info(self, test_path, counter, test_info):
    test_info_path = self.get_test_info_path(test_path, counter)
    self._test_info_list.append(test_info_path)

    test_info_str = json.dumps(test_info, sort_keys=True)
    # Escape the string for shell
    test_info_str = pipes.quote(test_info_str)
    # Escape the string for ninja
    test_info_str = ninja_syntax.escape(test_info_str)
    self.build([test_info_path],
               'build_test_info',
               [],
               variables={'test_info': test_info_str},
               implicit=[NinjaGenerator._PRETTY_PRINT_JSON_PATH])

  def build_all_unittest_info(self, ninja_list):
    unittest_info_list = []
    for ninja in ninja_list:
      unittest_info_list.extend(ninja._test_info_list)
    self.build([build_common.get_all_unittest_info_path()],
               'make_list',
               unittest_info_list)


class CNinjaGenerator(NinjaGenerator):
  """Encapsulates ninja file generation for C and C++ files.

  Valid values for |force_compiler| are None, 'gcc' and 'clang'. None implies
  the module is compiled with the default compiler on the platform.
  """

  def __init__(self, module_name, ninja_name=None, enable_logtag_emission=True,
               force_compiler=None,
               enable_cxx11=False, enable_libcxx=False,
               **kwargs):
    super(CNinjaGenerator, self).__init__(module_name, ninja_name, **kwargs)
    # This is set here instead of TopLevelNinjaGenerator because the ldflags
    # depend on module name.
    self.variable('ldflags', self.get_ldflags(is_host=self._is_host))
    self._intermediates_dir = os.path.join(
        build_common.get_build_dir(is_host=self._is_host),
        'intermediates', self._ninja_name)
    if enable_logtag_emission:
      self.emit_logtag_flags()
    if not self._is_host:
      self.emit_globally_exported_include_dirs()
      if ('base_path' in kwargs and
          kwargs['base_path'].startswith('android/frameworks/')):
        self.emit_framework_common_flags()
        # android/frameworks/* is usually compiled with -w (disable warnings),
        # but for some white-listed paths, we can use -Werror.
        use_w_error = ['android/frameworks/base',
                       'android/frameworks/base/services/jni/arc',
                       'android/frameworks/native/arc/binder']
        if kwargs['base_path'] in use_w_error:
          self.add_compiler_flags('-Werror')
        else:
          # Show warnings when --show-warnings=all or yes is specified.
          self.add_compiler_flags(*OPTIONS.get_warning_suppression_cflags())
      if ('base_path' in kwargs and
          kwargs['base_path'].startswith('android/')):
        self.add_include_paths('android/bionic/libc/include')
    self._enable_libcxx = enable_libcxx
    if enable_libcxx:
      self.add_include_paths('android/external/libcxx/include')
      self.add_compiler_flags('-D_USING_LIBCXX')

    assert force_compiler in (None, 'gcc', 'clang')
    if force_compiler is None:
      self._enable_clang = not self._is_host and OPTIONS.is_nacl_build()
    else:
      self._enable_clang = (force_compiler == 'clang')

    if enable_cxx11:
      # TODO(crbug.com/487964): Enable C++11 by default.
      gcc_version = toolchain.get_gcc_version(
          'host' if self._is_host else OPTIONS.target())
      assert self._enable_clang or gcc_version >= [4, 7, 0]
      self.add_cxx_flags('-std=gnu++11')

    # We need 4-byte alignment to pass host function pointers to arm code.
    if (not self._is_host and not OPTIONS.is_nacl_build() and
        not self._enable_clang):
      self.add_compiler_flags('-falign-functions=4')
    self._object_list = []
    self._shared_deps = []
    self._static_deps = []
    self._whole_archive_deps = []

  def __del__(self):
    if OPTIONS.verbose():
      print 'Generated', self._ninja_name
    if self._object_list:
      print ('Warning: %s builds these objects but does nothing '
             'with them: %s' % (self._ninja_name, ' '.join(self._object_list)))

  def get_intermediates_dir(self):
    return self._intermediates_dir

  @staticmethod
  def add_to_variable(variables, flag_name, addend):
    if flag_name not in variables:
      variables[flag_name] = '$%s %s' % (flag_name, addend)
    else:
      variables[flag_name] += ' ' + addend

  def add_objects(self, object_list):
    self._object_list += object_list
    return self

  def _consume_objects(self):
    object_list = self._object_list
    self._object_list = []
    return object_list

  def build_default(self, files, base_path='', **kwargs):
    if base_path == '':
      base_path = self._base_path
    self.add_objects(build_default(
        self, base_path, files, **kwargs))
    return self

  def find_all_sources(self, **kwargs):
    return self.find_all_contained_files(_PRIMARY_EXTENSIONS, **kwargs)

  def build_default_all_sources(self, implicit=None, order_only=None,
                                exclude=None, **kwargs):
    all_sources = self.find_all_sources(exclude=exclude, **kwargs)
    return self.build_default(all_sources, implicit=implicit,
                              order_only=order_only, base_path=None, **kwargs)

  # prioritize_ctors causes us to change an object file, as if all of its
  # constructors had been declared with:
  # __attribute__((init_priority(<priority>))).
  def prioritize_ctors(self, input, priority):
    if priority < 101:
      # GNU ld docs say priorities less than 101 are reserved.
      raise Exception('Illegal priority %d' % priority)
    output = os.path.join(os.path.dirname(input),
                          '%s.prio%d.o' % (os.path.basename(input), priority))
    # Recent GNU gcc/ld put global constructor function pointers in
    # a section named .init_array.  If those constructors have
    # priorities associated with them the name of the section is
    # .init_array.<priority>.
    init_array_suffix = '.%05d' % priority
    # Old GNU gcc/ld use .ctors.<value> where value is that number
    # subtracted from 65535.
    ctors_suffix = '.%05d' % (65535 - priority)
    # Note that we do not need to modify .fini_array and .dtors for
    # C++ global destructors since they use atexit() instead of
    # special sections.
    return self.build(output, 'prioritize_ctors', input,
                      variables={'init_array_suffix': init_array_suffix,
                                 'ctors_suffix': ctors_suffix})

  def add_compiler_flags(self, *flags):
    flag_variable = 'hostcflags' if self._is_host else 'cflags'
    self.add_flags(flag_variable, *flags)
    self.add_asm_flag(*flags)
    self.add_cxx_flags(*flags)
    return self

  def add_asm_flag(self, *flags):
    flag_variable = 'hostasmflags' if self._is_host else 'asmflags'
    self.add_flags(flag_variable, *flags)
    return self

  # Same as add_compiler_flag but applies to C files only.
  def add_c_flags(self, *flags):
    flag_variable = 'hostcflags' if self._is_host else 'cflags'
    self.add_flags(flag_variable, *flags)
    return self

  # Same as add_compiler_flag but applies to C++ files only.
  def add_cxx_flags(self, *flags):
    flag_variable = 'hostcxxflags' if self._is_host else 'cxxflags'
    self.add_flags(flag_variable, *flags)
    return self

  def add_ld_flags(self, *flags):
    flag_variable = 'hostldflags' if self._is_host else 'ldflags'
    self.add_flags(flag_variable, *flags)
    return self

  # Passed library flags can be any style:
  #  -lerty
  #  path/to/liberty.so
  #  path/to/liberty.a
  def add_libraries(self, *flags):
    flag_variable = 'hostldadd' if self._is_host else 'ldadd'
    self.add_flags(flag_variable, *flags)

  # Avoid using -l since this can allow the linker to use a system
  # shared library instead of the library we have built.
  def _add_lib_vars(self, variables):
    joined_static_libs = ' '.join(self._static_deps)
    joined_whole_archive_libs = ' '.join(self._whole_archive_deps)
    joined_shared_libs = ' '.join(self._shared_deps)
    return dict({'my_static_libs': joined_static_libs,
                 'my_shared_libs': joined_shared_libs,
                 'my_whole_archive_libs': joined_whole_archive_libs}.items() +
                variables.items())

  def _add_library_deps(self, deps, as_whole_archive):
    for dep in deps:
      if dep.endswith('.so'):
        list = self._shared_deps
      elif dep.endswith('.a'):
        if as_whole_archive:
          list = self._whole_archive_deps
        else:
          list = self._static_deps
      else:
        raise Exception('Unexpected lib dependency: ' + dep)
      if os.path.sep not in dep:
        dep = build_common.get_build_path_for_library(
            dep, is_host=self._is_host)
      if dep not in list:
        list.append(dep)
    return self

  def add_library_deps(self, *deps):
    return self._add_library_deps(deps, False)

  def add_whole_archive_deps(self, *deps):
    return self._add_library_deps(deps, True)

  def add_include_paths(self, *paths):
    self.add_compiler_flags(*['-I' + staging.as_staging(x) for x in paths])
    return self

  def add_system_include_paths(self, *paths):
    """Adds -isystem includes. These should be avoided whenever possible
    due to warning masking that happens in code."""
    flags = []
    for path in paths:
      flags.extend(['-isystem', staging.as_staging(path)])
    self.add_compiler_flags(*flags)
    return self

  def add_defines(self, *defines):
    self.add_compiler_flags(*['-D' + x for x in defines])
    return self

  def get_object_path(self, src_path):
    """Generate a object path for the given source file.

    This path, relative to the intermediates directory for this ninja
    file, where the object files will be stored.  We need the same
    namespacing from the input directory structures, so we use the
    source container directory here in generating the path, but we
    just hash it to avoid having prohibitively long build paths.  We
    also carefully use the real path instead of the staging path.  The
    distinction is that we want the build path to change when a file
    flips from being overlaid to upstream and vice versa in order to
    prompt a rebuild.
    """
    real_src_container = os.path.dirname(staging.as_real_path(src_path))
    build_container = _compute_hash_fingerprint(real_src_container)
    path = os.path.join(build_container, os.path.basename(src_path))
    return os.path.splitext(path)[0] + '.o'

  @staticmethod
  def get_archasmflags():
    if OPTIONS.is_arm():
      archasmflags = (
          # Some external projects like libpixelflinger expect this macro.
          '-D__ARM_HAVE_NEON')
    elif OPTIONS.is_bare_metal_i686():
      archasmflags = '-msse2'
    else:
      archasmflags = ''

    archasmflags += ' -nostdinc -D__ANDROID__ '
    return archasmflags

  @staticmethod
  def _get_bionic_fpu_arch():
    if OPTIONS.is_i686():
      return 'i387'
    elif OPTIONS.is_x86_64():
      return 'amd64'
    elif OPTIONS.is_arm():
      return 'arm'
    assert False, 'Unsupported CPU architecture: ' + OPTIONS.target()

  @staticmethod
  def get_clang_includes():
    if OPTIONS.is_nacl_build():
      clang_include = ' -isystem ' + toolchain.get_pnacl_include_dir()
    else:
      clang_include = ' -isystem ' + toolchain.get_clang_include_dir()

    # We need to specify bionic includes right after clang includes, otherwise
    # include_next tricks used by headers like <limits.h> don't work.
    return (clang_include +
            ' -isystem ' + staging.as_staging('android/bionic/libc/include'))

  @staticmethod
  def get_gcc_includes():
    gcc_raw_version = toolchain.get_gcc_raw_version(OPTIONS.target())

    if OPTIONS.is_nacl_build():
      gcc_include = os.path.join(
          toolchain.get_nacl_toolchain_root(),
          'lib/gcc/x86_64-nacl/%s/include' % gcc_raw_version)
    else:
      if OPTIONS.is_arm():
        # Ubuntu 14.04 has this diriectory for cross-compile headers.
        if os.path.exists('/usr/lib/gcc-cross'):
          gcc_include = (
              '/usr/lib/gcc-cross/arm-linux-gnueabihf/%s/include' %
              gcc_raw_version)
        else:
          gcc_include = ('/usr/lib/gcc/arm-linux-gnueabihf/%s/include' %
                         gcc_raw_version)
      else:
        gcc_include = ('/usr/lib/gcc/x86_64-linux-gnu/%s/include' %
                       gcc_raw_version)
    return (
        ' -isystem ' + gcc_include +
        ' -isystem ' + '%s-fixed' % gcc_include)

  @staticmethod
  def get_archcflags():
    archcflags = ''
    # If the build target uses linux x86 ABIs, stack needs to be aligned at
    # 16 byte boundary, although recent compiler outputs 16 byte aligned code.
    if OPTIONS.is_bare_metal_i686():
      # The flag comes from $ANDROID/build/core/combo/TARGET_linux-x86.mk. We
      # need this because the Android code has legacy assembly functions that
      # align the stack to a 4-byte boundary which is not compatible with SSE.
      # TODO(crbug.com/394688): The performance overhead should be
      # measured, and consider removing this flag.
      archcflags += ' -mstackrealign'

    if OPTIONS.is_bare_metal_build():
      archcflags += ' -fstack-protector'
    if OPTIONS.is_nacl_x86_64():
      # clang 3.4 or nacl-gcc doesn't define __ILP32__ but clang 3.5 defines it.
      # Make it consistent.
      archcflags += ' -D__ILP32__=1'

    archcflags += (
        # TODO(crbug.com/243244): It might be probably a bad idea to
        # include files in libc/kernel from non libc code.
        # Check if they are really necessary once we can compile
        # everything with bionic.
        ' -isystem ' + staging.as_staging(
            'android/bionic/libc/kernel/uapi') +
        ' -isystem ' + staging.as_staging(
            'android/bionic/libc/kernel/uapi/asm-%s' %
            build_common.get_bionic_arch_name()) +
        ' -isystem ' + staging.as_staging(
            'android/bionic/libc/arch-%s/include' %
            build_common.get_bionic_arch_name()) +
        ' -isystem ' + staging.as_staging('android/bionic/libc/include') +
        ' -isystem ' + staging.as_staging('android/bionic/libm/include') +
        ' -isystem ' + staging.as_staging(
            'android/bionic/libc/arch-nacl/syscalls') +
        ' -isystem ' + staging.as_staging(
            'android/bionic/libm/include/%s' %
            CNinjaGenerator._get_bionic_fpu_arch()) +
        # Build gmock using the TR1 tuple library in gtest because tuple
        # implementation is not included in STLport.
        ' -DGTEST_HAS_TR1_TUPLE=1' +
        ' -DGTEST_USE_OWN_TR1_TUPLE=1')

    return archcflags

  @staticmethod
  def get_commonflags():
    archcommonflags = []
    if OPTIONS.is_arm():
      archcommonflags.extend([
          # Our target ARM device is either a15 or a15+a7 big.LITTLE. Note that
          # a7 is 100% ISA compatible with a15.
          # Unlike Android, we must use the hard-fp ABI since the ARM toolchains
          # for Chrome OS and NaCl does not support soft-fp.
          '-mcpu=cortex-a15',
          '-mfloat-abi=softfp'
      ])
      # The toolchains for building Android use -marm by default while the
      # toolchains for Bare Metal do not, so set -marm explicitly as the default
      # mode.
      if OPTIONS.is_bare_metal_build():
        archcommonflags.append('-marm')
    elif OPTIONS.is_i686():
      archcommonflags.append('-m32')

    archcommonflags.append(os.getenv('LDFLAGS', ''))
    # We always use -fPIC even for Bare Metal mode, where we create
    # PIE for executables. To determine whether -fPIC or -fPIE is
    # appropriate, we need to know if we are building objects for an
    # executable or a shared object. This is hard to tell especially
    # for ArchiveNinjaGenerator. Though -fPIC -pie is not supported
    # officially, it should be safe in practice. There are two
    # differences between -fPIC and -fPIE:
    # 1. GCC uses dynamic TLS model for -fPIC, while it uses static
    # TLS model for -fPIE. This is not an issue because we do not
    # support TLS based on __thread, and dynamic TLS model always
    # works even for code for which static TLS model is more
    # appropriate. See also: http://www.akkadia.org/drepper/tls.pdf.
    # 2. GCC uses PLT even for locally defined symbols if -fPIC is
    # specified. This makes no difference for us because the linker
    # will remove the call to PLT as we specify -Bsymbolic anyway.
    archcommonflags.append('-fPIC')
    return ' '.join(archcommonflags)

  @staticmethod
  def get_asmflags():
    return ('$commonflags ' +
            CNinjaGenerator.get_archasmflags() +
            '-pthread -Wall ' + CNinjaGenerator._get_debug_cflags() +
            '-DANDROID -DANDROID_SMP=1 '
            # GCC sometimes predefines the _FORTIFY_SOURCE macro which is
            # not compatible with our function wrapping system. Undefine
            # the macro to turn off the feature. (crbug.com/226930)
            '-U_FORTIFY_SOURCE '
            '-DARC_TARGET=\\"' + OPTIONS.target() + '\\" ' +
            '-DARC_TARGET_PATH=\\"' + build_common.get_build_dir() +
            '\\" ' +
            '-DHAVE_ARC ' +
            CNinjaGenerator.get_targetflags() +
            # Since Binder is now 64-bit aware, we need to add this flag in
            # every module that includes Binder headers. Rather than doing that,
            # add a global flag.
            '-DBINDER_IPC_32BIT ')

  @staticmethod
  def get_cflags():
    cflags = ('$asmflags' +
              # These flags also come from TARGET_linux-x86.mk.
              # * -fno-short-enums is the default, but add it just in case.
              # * Although -Wstrict-aliasing is mostly no-op since we add
              #   -fno-strict-aliasing in the next line, we keep this since
              #   this might detect unsafe '-fstrict-aliasing' in the
              #   future when it is added by mistake.
              ' -fno-short-enums -Wformat-security -Wstrict-aliasing=2'
              # These flags come from $ANDROID/build/core/combo/select.mk.
              # ARC, Android, Chromium, and third_party libraries do not
              # throw exceptions at all.
              ' -fno-exceptions -fno-strict-aliasing'
              # Include dirs are parsed left-to-right. Prefer overriden
              # headers in our mods/ directory to those in third_party/.
              # Android keeps all platform-specific defines in
              # AndroidConfig.h.
              ' -include ' +
              build_common.get_android_config_header(is_host=False) +
              ' ' + CNinjaGenerator.get_archcflags())

    if OPTIONS.is_debug_info_enabled() or OPTIONS.is_debug_code_enabled():
      # We do not care the binary size when debug info or code is enabled.
      # Emit .eh_frame for better backtrace. Note that _Unwind_Backtrace,
      # which is used by libunwind, depends on this.
      cflags += ' -funwind-tables'
    elif not OPTIONS.is_nacl_build():
      # Bare Metal build does not require the eh_frame section. Like Chromium,
      # remove the section to reduce the size of the text by 1-2%. Do not use
      # the options for NaCl because they do not reduce the size of the NaCl
      # binaries.
      cflags += ' -fno-unwind-tables -fno-asynchronous-unwind-tables'

    # Note: Do not add -fno-threadsafe-statics for now since we cannot be sure
    # that Android and third-party libraries we use do not depend on the C++11's
    # thread safe variable initialization feature (either intentionally or
    # accidentally) objdump reports that we have more than 2000 function-scope
    # static variables in total and that is too many to check. Neither select.mk
    # nor TARGET_linux-x86.mk has -fno-threadsafe-statics.

    cflags += (' -I' + staging.as_staging('src') +
               ' -I' + staging.as_staging('android_libcommon') +
               ' -I' + staging.as_staging('android') +
               # Allow gtest/gtest_prod.h to be included by anything.
               ' -I' + staging.as_staging(
                   'android/external/chromium_org/testing/gtest/include'))

    return cflags

  @staticmethod
  def get_cxxflags():
    # We specify '-nostdinc' as an archasmflags, but it does not remove C++
    # standard include paths for clang. '-nostdinc++' works to remove the paths
    # for both gcc and clang.
    cxx_flags = ' -nostdinc++'
    # This is necessary because STLport includes headers like
    # libstdc++/include/new.
    cxx_flags += (' -isystem ' + staging.as_staging('android/bionic'))
    if OPTIONS.enable_atrace():
      cxx_flags += ' -DARC_ANDROID_TRACE'
    if OPTIONS.enable_valgrind():
      # By default, STLport uses its custom allocator which does never
      # release the memory and valgrind thinks there is leaks. We tell
      # STLport to use new/delete instead of the custom allocator.
      # See http://stlport.sourceforge.net/FAQ.shtml#leaks
      cxx_flags += ' -D_STLP_USE_NEWALLOC'
    # Add STLport headers into the system search path by default to be
    # compatible with Android toolchains.
    # On modules that use libc++ via enable_libcxx=True, libc++ headers are
    # added into the normal search path so that libc++ headers are used
    # preferentially.
    cxx_flags += (' -isystem ' +
                  staging.as_staging('android/external/stlport/stlport'))
    # ARC, Android, PPAPI libraries, and the third_party libraries (except
    # ICU) do not use RTTI at all. Note that only g++ supports the flags.
    # gcc does not.
    # C++ system include paths should be specified before C system
    # include paths.
    return cxx_flags + ' $cflags -fno-rtti'

  @staticmethod
  def get_targetflags():
    targetflags = ''
    if OPTIONS.is_nacl_build():
      targetflags += '-DTARGET_ARC_NATIVE_CLIENT '
    elif OPTIONS.is_bare_metal_build():
      targetflags += '-DTARGET_ARC_BARE_METAL '

    if OPTIONS.is_bare_metal_i686():
      targetflags += '-DTARGET_ARC_BARE_METAL_X86 '
    elif OPTIONS.is_bare_metal_arm():
      targetflags += '-DTARGET_ARC_BARE_METAL_ARM '
    elif OPTIONS.is_nacl_x86_64():
      targetflags += '-DTARGET_ARC_NATIVE_CLIENT_X86_64 '
    return targetflags

  @staticmethod
  def get_hostasmflags():
    return ('-DHAVE_ARC_HOST -DANDROID_SMP=1 ' +
            CNinjaGenerator.get_targetflags())

  @staticmethod
  def get_hostcflags():
    # The host C flags are kept minimal as relevant flags, such as -Wall, are
    # provided from MakefileNinjaTranslator, and most of the host binaries
    # are built via MakefileNinjaTranslator.
    hostcflags = (CNinjaGenerator._get_debug_cflags() +
                  ' $hostasmflags' +
                  ' -I' + staging.as_staging('src') +
                  ' -I' + staging.as_staging('android_libcommon') +
                  ' -I' + staging.as_staging('android') +
                  # Allow gtest/gtest_prod.h to be included by anything.
                  ' -I' + staging.as_staging(
                      'android/external/chromium_org/testing/gtest/include'))
    return hostcflags

  @staticmethod
  def get_hostcxxflags():
    hostcxx_flags = ''
    # See the comment in get_cxxflags() about RTTI.
    return hostcxx_flags + ' $hostcflags -fno-rtti'

  @staticmethod
  def _get_gccflags():
    flags = []
    # In addition to -mstackrealign, we need to set
    # -mincoming-stack-boundary flag, that the incoming alignment is
    # at 4 byte boundary. Because it takes log_2(alignment bytes) so,
    # we set '2' which means 4 byte alignemnt.
    # Note this is needed only for GCC. Clang re-aligns the stack even
    # without this flag and it does not have this flag.
    # TODO(crbug.com/394688): The performance overhead should be
    # measured, and consider removing this flag.
    if OPTIONS.is_bare_metal_i686():
      flags.append('-mincoming-stack-boundary=2')
      # Usually long double is 80bit under BMM x86, but we need to force it to
      # 64bit. Unfortunately this flag is not supported by clang yet.
      # See mods/fork/bionic-long-double for more details.
      flags.append('-mlong-double-64')
    if OPTIONS.is_arm():
      flags.extend(['-mthumb-interwork', '-mfpu=neon-vfpv4', '-Wno-psabi'])
    if OPTIONS.is_nacl_i686():
      # For historical reasons by default x86-32 NaCl produces code for quite
      # exotic CPU: 80386 with SSE instructions (but without SSE2!).
      # Let's use something more realistic.
      flags.extend(['-march=pentium4', '-mtune=core2'])
      # Use '-Wa,-mtune=core2' to teach assemler to use long Nops for padding.
      # This produces slightly faster code on all CPUs newer than Pentium4.
      flags.append('-Wa,-mtune=core2')
    if OPTIONS.is_nacl_x86_64():
      flags.append('-m64')
    return flags

  @staticmethod
  def _get_gxxflags():
    return []

  @staticmethod
  def _get_clangflags():
    flags = ['-Wheader-hygiene', '-Wstring-conversion']
    if OPTIONS.is_arm():
      flags.extend(['-target', 'arm-linux-gnueabi'])
    if OPTIONS.is_nacl_i686():
      # NaCl clang ensures the stack pointer is aligned to 16 byte
      # boundaries and assumes other objects do the same. Dalvik for
      # i686 violates this assumption so we need to re-align the stack
      # at the beginning of all functions built by PNaCl clang.
      flags.append('-mstackrealign')
    return flags

  @staticmethod
  def _get_clangxxflags():
    return []

  @staticmethod
  def _get_debug_cflags():
    debug_flags = ''
    if not OPTIONS.is_debug_code_enabled():
      # Add NDEBUG to get rid of all *LOGV, *LOG_FATAL_IF, and *LOG_ASSERT calls
      # from our build.
      debug_flags += '-DNDEBUG -UDEBUG '
    if OPTIONS.is_debug_info_enabled():
      debug_flags += '-g '
    return debug_flags

  @staticmethod
  def emit_optimization_flags(n, force_optimizations=False):
    cflags = []
    gccflags = []
    ldflags = []
    if OPTIONS.is_optimized_build() or force_optimizations:
      cflags = get_optimization_cflags()
      gccflags = get_gcc_optimization_cflags()
      # Unlike Chromium where gold is available, do not use '-Wl,-O1' since it
      # slows down the linker a lot. Do not use '-Wl,--gc-sections' either
      # (crbug.com/231034).
      if OPTIONS.is_debug_code_enabled():
        # Even when forcing optimizations we keep the frame pointer for
        # debugging.
        # TODO(crbug.com/122623): Re-enable -fno-omit-frame-pointer for
        # nacl_x86_64 once the underlying compiler issue is fixed.
        # We are affected in experiencing odd gtest/gmock failures.
        #
        # TODO(crbug.com/378161): Re-enable -fno-omit-frame-pointer for
        # ARM GCC 4.8 once the underlying compiler issue is fixed.
        gcc_version = toolchain.get_gcc_version(OPTIONS.target())
        if not (OPTIONS.is_nacl_x86_64() or
                (OPTIONS.is_arm() and gcc_version >= [4, 8, 0])):
          cflags += ['-fno-omit-frame-pointer']
    else:
      cflags = ['-O0']

    n.variable('cflags', '$cflags ' + ' '.join(cflags))
    n.variable('cxxflags', '$cxxflags ' + ' '.join(cflags))
    if gccflags:
      n.variable('gccflags', '$gccflags ' + ' '.join(gccflags))
      n.variable('gxxflags', '$gxxflags ' + ' '.join(gccflags))
    if ldflags:
      n.variable('ldflags', '$ldflags ' + ' '.join(ldflags))

  @staticmethod
  def emit_target_rules_(n):
    target = OPTIONS.target()
    extra_flags = []
    if OPTIONS.is_nacl_build():
      extra_flags = ['$naclflags']
    n.emit_compiler_rule('cxx', target, flag_name='cxxflags',
                         extra_flags=extra_flags + ['$gxxflags'],
                         compiler_includes='gccsystemincludes')
    n.emit_compiler_rule('cc', target, flag_name='cflags',
                         extra_flags=extra_flags + ['$gccflags'],
                         compiler_includes='gccsystemincludes')
    n.emit_compiler_rule('clangxx', target, flag_name='cxxflags',
                         extra_flags=extra_flags + ['$clangxxflags'],
                         compiler_includes='clangsystemincludes')
    n.emit_compiler_rule('clang', target, flag_name='cflags',
                         extra_flags=extra_flags + ['$clangflags'],
                         compiler_includes='clangsystemincludes')
    if OPTIONS.is_nacl_build():
      # GNU extensions of asm languages, e.g. altmacro, are missing on Clang.
      # Use gas instead of integrated Clang assembler by adding
      # -no-integrated-as flag.
      n.emit_compiler_rule('asm_with_preprocessing', target,
                           flag_name='asmflags',
                           extra_flags=(extra_flags +
                                        ['$gccflags', '-no-integrated-as']))
      # Add -Qunused-arguments to suppress warnings for unused preprocessor
      # flags.
      n.emit_compiler_rule('asm', target, flag_name='asmflags',
                           supports_deps=False,
                           extra_flags=(extra_flags +
                                        ['$gccflags', '-Qunused-arguments',
                                         '-no-integrated-as']))
    else:
      n.emit_compiler_rule('asm_with_preprocessing', target,
                           flag_name='asmflags',
                           extra_flags=extra_flags + ['$gccflags'])
      n.emit_compiler_rule('asm', target, flag_name='asmflags',
                           supports_deps=False,
                           extra_flags=extra_flags + ['$gccflags'])
    n.emit_ar_rule('ar', target)
    for rule_suffix in ['', '_system_library']:
      for compiler_prefix in ['', 'clang.']:
        n.emit_linker_rule(compiler_prefix + 'ld' + rule_suffix, target,
                           'ldflags')
        common_linkso_args = NinjaGenerator._get_target_ld_flags(
            target, is_so=True, is_system_library=bool(rule_suffix))
        tool = compiler_prefix + 'ld'
        n.rule('%slinkso%s.%s' % (compiler_prefix, rule_suffix, target),
               '%s -o $out %s $extra_flags' % (toolchain.get_tool(target, tool),
                                               common_linkso_args),
               description='linkso.%s $out' % target,
               rspfile='$out.files',
               rspfile_content='$in_newline')

    n.rule('prioritize_ctors',
           ('cp $in $out && ' +
            toolchain.get_tool(target, 'objcopy') +
            ' --rename-section .ctors=.ctors$ctors_suffix'
            ' --rename-section .rela.ctors=.rela.ctors$ctors_suffix '
            ' --rename-section .init_array=.init_array$init_array_suffix'
            ' --rename-section '
            '.rela.init_array=.rela.init_array$init_array_suffix '
            '$out'))

  @staticmethod
  def emit_host_rules_(n):
    n.emit_compiler_rule('cxx', 'host', flag_name='hostcxxflags')
    n.emit_compiler_rule('cc', 'host', flag_name='hostcflags')
    n.emit_compiler_rule('clangxx', 'host', flag_name='hostcxxflags')
    n.emit_compiler_rule('clang', 'host', flag_name='hostcflags')
    n.emit_compiler_rule('asm_with_preprocessing', 'host',
                         flag_name='hostasmflags')
    n.emit_compiler_rule('asm', 'host', flag_name='hostasmflags',
                         supports_deps=False)
    n.emit_ar_rule('ar', 'host')
    n.emit_linker_rule('ld', 'host', 'hostldflags')
    linkso_args = NinjaGenerator._get_target_ld_flags(
        'host', is_so=True, is_system_library=False)
    n.rule('linkso.host',
           '%s -o $out %s' % (toolchain.get_tool('host', 'ld'),
                              linkso_args),
           description='linkso.host $out',
           rspfile='$out.files',
           rspfile_content='$in_newline')

  @staticmethod
  def emit_common_rules(n):
    n.variable('asmflags', CNinjaGenerator.get_asmflags())
    n.variable('gccsystemincludes', CNinjaGenerator.get_gcc_includes())
    n.variable('clangsystemincludes', CNinjaGenerator.get_clang_includes())
    n.variable('cflags', CNinjaGenerator.get_cflags())
    n.variable('cxxflags', CNinjaGenerator.get_cxxflags())
    n.variable('hostasmflags', CNinjaGenerator.get_hostasmflags())
    n.variable('hostcflags', CNinjaGenerator.get_hostcflags())
    n.variable('hostcxxflags', CNinjaGenerator.get_hostcxxflags())

    # Native Client gcc seems to emit stack protector related symbol references
    # under some circumstances, but the related library does not seem to be
    # present in the NaCl toolchain.  Disabling for now.
    n.variable('naclflags', '-fno-stack-protector')

    # Allow Bionic's config.py to change crtbegin for libc.so. See
    # mods/android/bionic/config.py for detail.
    n.variable('crtbegin_for_so', build_common.get_bionic_crtbegin_so_o())

    CNinjaGenerator.emit_optimization_flags(n)
    n.variable('gccflags', ' '.join(CNinjaGenerator._get_gccflags()))
    n.variable('gxxflags',
               '$gccflags ' + ' '.join(CNinjaGenerator._get_gxxflags()))
    n.variable('clangflags', ' '.join(CNinjaGenerator._get_clangflags()))
    n.variable('clangxxflags',
               '$clangflags ' + ' '.join(CNinjaGenerator._get_clangxxflags()))

    CNinjaGenerator.emit_target_rules_(n)
    CNinjaGenerator.emit_host_rules_(n)

    if OPTIONS.is_nacl_build():
      # Native Client validation test
      n.rule('run_ncval_test',
             (toolchain.get_tool(OPTIONS.target(), 'ncval') +
              ' $in ' + build_common.get_test_output_handler()),
             description='NaCl validate $in')

  def _get_rule_name(self, rule_prefix):
    if self._notices_only:
      return 'phony'
    if self._is_host:
      return rule_prefix + '.host'
    return rule_prefix + '.' + OPTIONS.target()

  def _get_toc_file_for_so(self, so_file):
    if self._is_host:
      return so_file + '.TOC'
    basename_toc = os.path.basename(so_file) + '.TOC'
    return os.path.join(build_common.get_load_library_path(), basename_toc)

  def cxx(self, name, **kwargs):
    rule = 'clangxx' if self._enable_clang else 'cxx'
    return self.build(
        self.get_build_path(self.get_object_path(name)),
        self._get_rule_name(rule), name, **kwargs)

  def cc(self, name, **kwargs):
    rule = 'clang' if self._enable_clang else 'cc'
    return self.build(
        self.get_build_path(self.get_object_path(name)),
        self._get_rule_name(rule), name, **kwargs)

  def asm(self, name, **kwargs):
    return self.build(
        self.get_build_path(self.get_object_path(name)),
        self._get_rule_name('asm'), name, **kwargs)

  def asm_with_preprocessing(self, name, **kwargs):
    return self.build(
        self.get_build_path(self.get_object_path(name)),
        self._get_rule_name('asm_with_preprocessing'), name, **kwargs)

  def get_ncval_test_output(self, binfile):
    return binfile + '.ncval'

  def ncval_test(self, binfiles):
    for binfile in build_common.as_list(binfiles):
      self.build(self.get_ncval_test_output(binfile), 'run_ncval_test', binfile)

  def add_libchromium_base_compile_flags(self):
    self.add_include_paths('android/external/chromium_org')
    self.add_compiler_flags('-include', staging.as_staging(
        'src/common/chromium_build_config.h'))

  def add_ppapi_compile_flags(self):
    self.add_include_paths('chromium-ppapi',
                           'chromium-ppapi/ppapi/lib/gl/include',
                           'out/staging')

  def add_ppapi_link_flags(self):
    self.add_library_deps('libchromium_ppapi.so')

  def emit_logtag_flags(self):
    logtag = self._module_name
    self.add_defines(r'LOG_TAG="%s"' % logtag)

  # TODO(crbug.com/322776): Remove when these are detected properly by
  # make_to_ninja.py and emitted to each ninja file.
  def emit_globally_exported_include_dirs(self):
    paths = ['android/external/skia/include/config',
             'android/external/skia/include/core',
             'android/external/skia/include/effects',
             'android/external/skia/include/gpu',
             'android/external/skia/include/images',
             'android/external/skia/include/pdf',
             'android/external/skia/include/pipe',
             'android/external/skia/include/ports',
             'android/external/skia/include/utils',
             'android/external/skia/include/lazy',
             'android/ndk/sources/android/cpufeatures']
    self.add_include_paths(*paths)

  def emit_framework_common_flags(self):
    self.add_defines('NO_MALLINFO=1', 'SK_RELEASE')
    if OPTIONS.is_java_methods_logging():
      self.add_defines('LOG_JAVA_METHODS=1')
    paths = ['android/frameworks/av/include',
             'android/frameworks/base/core/jni',
             'android/frameworks/base/core/jni/android/graphics',
             'android/frameworks/base/include',
             'android/frameworks/base/libs/hwui',
             'android/frameworks/base/native/include',
             'android/frameworks/base/services',
             'android/frameworks/base/services/surfaceflinger',
             'android/frameworks/native/opengl/include',
             'android/frameworks/native/opengl/libs',
             'android/frameworks/native/include',
             'android/system/core/include',
             'android/libnativehelper/include',
             'android/libnativehelper/include/nativehelper',
             'android/external/harfbuzz_ng/src',
             'android/external/icu4c/common',
             'android/libcore/include',
             'android/hardware/libhardware/include',
             'android/external/skia/include',
             'android/external/skia/include/core',
             'android/external/skia/include/effects',
             'android/external/skia/include/images',
             'android/external/skia/include/utils',
             'android/external/skia/src/ports',
             'android/external/sqlite/android',
             'android/external/sqlite/dist']
    self.add_include_paths(*paths)

  def emit_ld_wrap_flags(self):
    ld_wrap_flags = ' '.join(['-Wl,--wrap=' + x for x
                              in wrapped_functions.get_wrapped_functions()])
    self.variable('ldflags', '$ldflags ' + ld_wrap_flags)

  def emit_gl_common_flags(self, hidden_visibility=True):
    self.add_defines('GL_GLEXT_PROTOTYPES', 'EGL_EGLEXT_PROTOTYPES')
    self.add_include_paths('android/bionic/libc/private')
    if hidden_visibility:
      self.add_cxx_flags('-fvisibility=hidden')

  def get_included_module_names(self):
    module_names = []
    for dep in self._static_deps + self._whole_archive_deps:
      module_name = dep
      if os.path.sep in module_name:
        module_name = os.path.splitext(os.path.basename(module_name))[0]
      if (module_name == 'libgcc' or
          (module_name == 'libgcc_eh' and OPTIONS.is_nacl_build())):
        # libgcc and libgcc_eh are not built for nacl mode and even in BMM where
        # we generate it, the code remains permissively licensed.
        continue
      module_names.append(module_name)
    return module_names

  def is_clang_enabled(self):
    return self._enable_clang


class RegenDependencyComputer(object):
  """This class knows which files, when changed, require rerunning configure."""

  def __init__(self):
    self._computed = False
    self._input = None
    self._output = None

  def _compute(self):
    # Any change to one of these files requires rerunning
    # configure.
    self._input = build_common.find_all_files(
        ['src', 'mods'], filenames='config.py',
        use_staging=False, include_tests=True)

    self._input += get_configuration_dependencies()

    self._output = [OPTIONS.get_configure_options_file()]

    # We do not support running the downloaded or built Chrome with an ARM
    # target on a dev machine.  We do not download/build Chrome in the
    # open source repository.
    if not open_source.is_open_source_repo() and not OPTIONS.is_arm():
      self._output += [build_common.get_chrome_prebuilt_stamp_file()]

    # Remove the options_file from the list of output dependencies. The option
    # file is only written if it changes to avoid triggering subsequent builds,
    # but if we list it here and it is not actually written out it will trigger
    # the regeneration step every time as ninja will think it is out of date.
    self._output.remove(OPTIONS.get_configure_options_file())

  def get_output_dependencies(self):
    if not self._computed:
      self._compute()
    return self._output

  def get_input_dependencies(self):
    if not self._computed:
      self._compute()
    return self._input

  @staticmethod
  def verify_is_output_dependency(path):
    dependencies = \
        TopLevelNinjaGenerator._REGEN_DEPENDENCIES.get_output_dependencies()
    path = os.path.relpath(os.path.realpath(path), build_common.get_arc_root())
    if path not in dependencies:
      raise Exception('Please add %s to regen input dependencies' % path)

  @staticmethod
  def verify_is_input_dependency(path):
    dependencies = \
        TopLevelNinjaGenerator._REGEN_DEPENDENCIES.get_input_dependencies()
    path = os.path.relpath(os.path.realpath(path), build_common.get_arc_root())
    if path not in dependencies:
      raise Exception('Please add %s to regen input dependencies' % path)


class TopLevelNinjaGenerator(NinjaGenerator):
  """Encapsulate top-level ninja file generation."""

  _REGEN_DEPENDENCIES = RegenDependencyComputer()

  def __init__(self, module_name, generate_path=False, **kwargs):
    super(TopLevelNinjaGenerator, self).__init__(
        module_name, generate_path=generate_path, **kwargs)
    # Emit regeneration rules as high as possible in the top level ninja
    # so that if configure.py fails and writes a partial ninja file and
    # we fix configure.py, the regeneration rule will most likely be
    # in the partial build.ninja.
    self._emit_ninja_regeneration_rules()
    self._emit_common_rules()

  def _get_depfile_path(self):
    return self._ninja_path + '.dep'

  # TODO(crbug.com/177699): Improve ninja regeneration rule generation.
  def _emit_ninja_regeneration_rules(self):
    # Add rule/target to regenerate all ninja files we built this time
    # if configure.py changes.  We purposefully avoid specifying
    # the parameters to configure directly in the ninja file.  Otherwise
    # the act of running configure to change parameters generates
    # a ninja regeneration rule whose parameters differ, resulting in
    # ninja wanting to immediately re-run configure.
    self.rule('regen_ninja',
              './configure $$(cat %s)' % OPTIONS.get_configure_options_file(),
              description='Regenerating ninja files due to dependency',
              depfile=self._get_depfile_path(),
              generator=True)
    # Use the paths from the regen computer, but transform them to staging
    # paths as we want to make sure we get mods/ paths when appropriate.
    output_dependencies = (
        [self._ninja_path] +
        TopLevelNinjaGenerator._REGEN_DEPENDENCIES.get_output_dependencies())
    self.build(output_dependencies,
               'regen_ninja', 'src/build/configure.py',
               use_staging=False)

  def _set_commonflags(self):
    self.variable('commonflags', CNinjaGenerator.get_commonflags())

  def _emit_common_rules(self):
    self._set_commonflags()

    ApkFromSdkNinjaGenerator.emit_common_rules(self)
    ApkNinjaGenerator.emit_common_rules(self)
    AtfNinjaGenerator.emit_common_rules(self)
    CNinjaGenerator.emit_common_rules(self)
    JarNinjaGenerator.emit_common_rules(self)
    JavaNinjaGenerator.emit_common_rules(self)
    JavaScriptNinjaGenerator.emit_common_rules(self)
    JavaScriptTestNinjaGenerator.emit_common_rules(self)
    NaClizeNinjaGenerator.emit_common_rules(self)
    NinjaGenerator.emit_common_rules(self)
    NoticeNinjaGenerator.emit_common_rules(self)
    PythonTestNinjaGenerator.emit_common_rules(self)
    TblgenNinjaGenerator.emit_common_rules(self)
    TestNinjaGenerator.emit_common_rules(self)

  def emit_subninja_rules(self, ninja_list):
    for ninja in ninja_list:
      if ninja._ninja_path != self.get_module_name():
        if ninja._use_global_scope:
          self.include(ninja._ninja_path)
        else:
          self.subninja(ninja._ninja_path)

  def emit_target_groups_rules(self, ninja_list):
    all_target_groups = _TargetGroups()

    # Build example APKs.
    all_target_groups.define_target_group('examples', 'default')
    # Run lint on all source files.
    all_target_groups.define_target_group('lint')

    for ninja in ninja_list:
      for build_rule in ninja._build_rule_list:
        all_target_groups.record_build_rule(*build_rule)
    all_target_groups.emit_rules(self)

  def emit_depfile(self):
    input_dependencies = map(
        staging.third_party_to_staging,
        TopLevelNinjaGenerator._REGEN_DEPENDENCIES.get_input_dependencies())
    file_util.write_atomically(
        self._get_depfile_path(),
        '%s: %s' % (self._ninja_path, ' '.join(input_dependencies)))

  @staticmethod
  def cleanup_out_directories(ninja_list):
    output_paths = set()
    for ninja in ninja_list:
      output_paths |= ninja.get_output_path_list()
      output_paths.add(ninja.get_ninja_path())
    out_dir_prefix = build_common.OUT_DIR + os.path.sep
    output_paths = set(
        path for path in output_paths if path.startswith(out_dir_prefix))

    def remove_files_not_built_in_dir(dir_path):
      if os.path.isdir(dir_path):
        for file_path in os.listdir(dir_path):
          file_path = os.path.join(dir_path, file_path)
          if file_path not in output_paths and not os.path.isdir(file_path):
            if OPTIONS.verbose():
              print 'Removing not-built artifact:', file_path
            os.remove(file_path)

    # TODO(crbug.com/524667): Clean the out directory of all stale artifacts,
    # not just those in specific directories mentioned here. The exception would
    # be not removing out/target/<other-target> when other-target !=
    # current-target.

    # Clean out any ninja files that were not generated.
    remove_files_not_built_in_dir(build_common.get_generated_ninja_dir())

    # Extra unit test files in this directory are problematic. Clean out
    # anything that is not going to be built.
    remove_files_not_built_in_dir(build_common.get_unittest_info_path())

    # Remove binaries in the stripped directory when they are unnecessary to
    # prevent stale binaries from being used for remote execution.
    remove_files_not_built_in_dir(build_common.get_stripped_dir())
    remove_files_not_built_in_dir(
        build_common.get_runtime_platform_specific_path(
            build_common.get_runtime_out_dir(), OPTIONS.target()))


class ArchiveNinjaGenerator(CNinjaGenerator):
  """Simple archive (static library) generator."""

  def __init__(self, module_name, instances=1, disallowed_symbol_files=None,
               **kwargs):
    super(ArchiveNinjaGenerator, self).__init__(
        module_name, ninja_name=module_name + '_a', **kwargs)
    if disallowed_symbol_files:
      self._disallowed_symbol_files = disallowed_symbol_files
    else:
      self._disallowed_symbol_files = ['disallowed_symbols.defined']
    self._instances = instances

  def archive(self, **kwargs):
    if self._shared_deps or self._static_deps or self._whole_archive_deps:
      raise Exception('Cannot use dependencies with an archive')
    archive_a = self.get_build_path(self._module_name + '.a')
    # Make sure |archive_a| does not contain a |_disallowed_symbol_files|
    # symbol, but the check is unnecessary for the host (i.e. it does not
    # matter if the disallowed symbols are included in the host library).
    if not self._notices_only and not self._is_host:
      self._check_symbols([archive_a], self._disallowed_symbol_files)
    return self.build(archive_a,
                      self._get_rule_name('ar'),
                      inputs=self._consume_objects(), **kwargs)

  @staticmethod
  def verify_usage(archive_ninja_list, shared_ninja_list, exec_ninja_list,
                   test_ninja_list):
    stl_error_list = []

    binary_ninja_list = shared_ninja_list + exec_ninja_list + test_ninja_list
    for ninja in binary_ninja_list:
      # Check if libc++ dependent modules link with libc++.so correctly.
      needed_objects = [os.path.basename(x) for x in ninja._shared_deps]
      host_or_target = 'host' if ninja.is_host() else 'target'
      if ninja._enable_libcxx:
        if 'libstlport.so' in needed_objects:
          stl_error_list.append(
              '%s for %s is built with libc++, but needs libstlport.so.' % (
                  ninja._module_name, host_or_target))
        if 'libc++.so' not in needed_objects:
          stl_error_list.append(
              '%s for %s is built with libc++, but does not need libc++.so.' % (
                  ninja._module_name, host_or_target))
      else:
        # Do not check libstlport.so since it may not be used actually.
        if 'libc++.so' in needed_objects:
          stl_error_list.append(
              '%s for %s is built with STLport, but needs libc++.so.' % (
                  ninja._module_name, host_or_target))

    all_ninja_list = archive_ninja_list + binary_ninja_list
    libcxx_dependent_module_set = set([x._module_name for x in all_ninja_list if
                                       x._enable_libcxx])
    archive_module_set = set([x._module_name for x in archive_ninja_list])

    # Following modules in the white list do not use libc++, but also do not
    # use any ABI affecting features. So, using it with both STLport and libc++
    # is believed to be safe.
    # We can not create the white list automatically since STLport headers
    # are visible by default without any additional search paths.
    white_list = [
        'libcommon_real_syscall_aliases',
        'libcompiler_rt',
        'libcutils',
        'libcutils_static',
        'libppapi_mocks',
        'libutils_static',
        'libz',
        'libz_static',
        'libziparchive',
        'libziparchive-host']

    for ninja in all_ninja_list:
      # Check if each module depends only on modules that use the same STL
      # library.
      ninja_use_libcxx = ninja._module_name in libcxx_dependent_module_set
      for module_name in ninja.get_included_module_names():
        if module_name in white_list or module_name not in archive_module_set:
          continue
        module_use_libcxx = module_name in libcxx_dependent_module_set
        if ninja_use_libcxx != module_use_libcxx:
          host_or_target = 'host' if ninja.is_host() else 'target'
          ninja_libcxx_usage = 'uses' if ninja_use_libcxx else 'does not use'
          module_libcxx_usage = 'uses' if module_use_libcxx else 'does not use'
          stl_error_list.append(
              '%s for %s %s libc++, but dependent %s %s libc++.' % (
                  ninja._module_name, host_or_target, ninja_libcxx_usage,
                  module_name, module_libcxx_usage))

    if stl_error_list:
      raise Exception(
          'Dangerous mixed usages of STLport and libc++ found:\n  ' +
          '\n  '.join(stl_error_list) +
          '\n\n*** A module should not depend on a static library that may use '
          'different STL library.***\n')

    usage_dict = collections.defaultdict(list)
    for ninja in shared_ninja_list + exec_ninja_list:
      for module_name in ninja.get_included_module_names():
        # Use is_host() in the key as the accounting should be done
        # separately for the target and the host.
        key = (module_name, ninja.is_host())
        usage_dict[key].append(ninja._module_name)

    count_error_list = []
    for ninja in archive_ninja_list:
      usage_list = usage_dict[(ninja._module_name, ninja.is_host())]
      if ninja.is_host():
        # For host archives, tracking the number of used count is not
        # important. We only check if an archive is used at least once.
        if usage_list:
          continue
        count_error_list.append('%s for host is not used' % ninja._module_name)
      else:
        if len(usage_list) == ninja._instances:
          continue
        count_error_list.append(
            '%s for target (allowed: %d, actual: %s)' % (
                ninja._module_name, ninja._instances, usage_list))
    if count_error_list:
      raise Exception(
          'Archives used unexpected number of times:\n  ' +
          '\n  '.join(count_error_list))


class SharedObjectNinjaGenerator(CNinjaGenerator):
  """Create a shared object ninja file."""

  # Whether linking of new shared objects is enabled
  _ENABLED = True

  def __init__(self, module_name, install_path='/lib', dt_soname=None,
               disallowed_symbol_files=None, is_system_library=False,
               link_crtbegin=True, use_clang_linker=False, is_for_test=False,
               **kwargs):
    super(SharedObjectNinjaGenerator, self).__init__(
        module_name, ninja_name=module_name + '_so', **kwargs)
    # No need to install the shared library for the host.
    self._install_path = None if self._is_host else install_path
    self._dt_soname = dt_soname
    if disallowed_symbol_files:
      self._disallowed_symbol_files = disallowed_symbol_files
    else:
      self._disallowed_symbol_files = ['libchromium_base.a.defined',
                                       'disallowed_symbols.defined']
    if not is_system_library:
      self.emit_ld_wrap_flags()
    self._is_system_library = is_system_library
    # For libc.so, we must not set syscall wrappers.
    if not is_system_library and not self._is_host:
      self._shared_deps.extend(
          # If |enable_libcxx| is set, use libc++.so, otherwise use stlport.
          build_common.get_bionic_shared_objects(
              use_stlport=not self._enable_libcxx,
              use_libcxx=self._enable_libcxx))
      self._shared_deps.append(
          os.path.join(build_common.get_load_library_path(),
                       'libposix_translation.so'))
    self.production_shared_library_list = []
    self._link_crtbegin = link_crtbegin
    if OPTIONS.is_nacl_build() and not self._is_host:
      self._is_clang_linker_enabled = True
    else:
      self._is_clang_linker_enabled = use_clang_linker
    self._is_for_test = is_for_test

  @classmethod
  def disable_linking(cls):
    """Disables further linking of any shared libraries"""
    cls._ENABLED = False

  def _link_shared_object(self, output, inputs=None, variables=None,
                          allow_undefined=False, implicit=None, **kwargs):
    flag_variable = 'hostldflags' if self._is_host else 'ldflags'
    if not SharedObjectNinjaGenerator._ENABLED:
      raise Exception('Linking of additional shared libraries is not allowed')
    variables = self._add_lib_vars(build_common.as_dict(variables))
    if not self._link_crtbegin:
      variables['crtbegin_for_so'] = ''
    implicit = (build_common.as_list(implicit) + self._static_deps +
                self._whole_archive_deps)
    if self._notices_only or self._is_host:
      implicit += self._shared_deps
    else:
      implicit += map(self._get_toc_file_for_so, self._shared_deps)

    if not self._is_host:
      implicit.extend([build_common.get_bionic_crtbegin_so_o(),
                       build_common.get_bionic_crtend_so_o()])
      if OPTIONS.is_debug_code_enabled() and not self._is_system_library:
        implicit.append(build_common.get_bionic_libc_malloc_debug_leak_so())
    if not allow_undefined:
      CNinjaGenerator.add_to_variable(variables, flag_variable, '-Wl,-z,defs')
    # Here, dt_soname is not file basename, but internal library name that is
    # specified against linker.
    dt_soname = self._dt_soname if self._dt_soname else self._get_soname()
    # For the host, do not add -soname. If soname is added, LD_LIBRARY_PATH
    # needs to be set for runnning host executables, which is inconvenient.
    if not self._is_host:
      CNinjaGenerator.add_to_variable(variables, flag_variable,
                                      '-Wl,-soname=' + dt_soname)
    prefix = 'clang.' if self._is_clang_linker_enabled else ''
    suffix = ('_system_library' if
              self._is_system_library and not self.is_host() else '')
    return self.build(output,
                      self._get_rule_name('%slinkso%s' % (prefix, suffix)),
                      inputs, variables=variables, implicit=implicit, **kwargs)

  def _get_soname(self):
    return self._module_name + '.so'

  def link(self, allow_undefined=True, **kwargs):
    # TODO(kmixter): Once we have everything in shared objects we
    # can make the default to complain if undefined references exist
    # in them.  Until then we silently assume they are all found
    # at run-time against the main plugin.
    basename_so = self._get_soname()
    intermediate_so = self._link_shared_object(
        self.get_build_path(basename_so),
        self._consume_objects(),
        allow_undefined=allow_undefined,
        **kwargs)
    # When processing notices_only targets, short-circuit the rest of the
    # function to add logic to only one place instead of three (NaCl validation,
    # install, and symbol checking).
    # TODO(crbug.com/364344): Once Renderscript is built from source, remove.
    if self._notices_only:
      return intermediate_so
    if self._is_host and OPTIONS.is_arm():
      # nm for ARM can't dump host binary, ignore building a TOC file then.
      return intermediate_so
    if OPTIONS.is_nacl_build() and not self._is_host:
      self.ncval_test(intermediate_so)
    mktoc_target = 'host' if self._is_host else OPTIONS.target()
    if self._install_path is not None:
      install_so = os.path.join(self._install_path, basename_so)
      self.install_to_build_dir(install_so, intermediate_so)
      if not self._is_for_test:
        self.production_shared_library_list.append(install_so)

      # Create TOC file next to the installed shared library.
      self.build(self._get_toc_file_for_so(install_so),
                 'mktoc', self._rebase_to_build_dir(install_so),
                 implicit='src/build/make_table_of_contents.py',
                 variables={'target': mktoc_target})
    else:
      # Create TOC file next to the intermediate shared library if the shared
      # library is not to be installed. E.g. host binaries are not installed.
      self.build(self.get_build_path(basename_so + '.TOC'),
                 'mktoc', intermediate_so,
                 implicit='src/build/make_table_of_contents.py',
                 variables={'target': mktoc_target})

    # Make sure |intermediate_so| contain neither 'disallowed_symbols.defined'
    # symbols nor libchromium_base.a symbols, but the check is unnecessary for
    # the host (i.e. it does not matter if the disallowed symbols are included
    # in the host library).
    if OPTIONS.is_debug_info_enabled() and not self._is_host:
      self._check_symbols(intermediate_so, self._disallowed_symbol_files)
    return intermediate_so


class ExecNinjaGenerator(CNinjaGenerator):
  """ Create a binary ninja file."""

  _NACL_TEXT_SEGMENT_ADDRESS = '0x1000000'

  def __init__(self, module_name, install_path=None, is_system_library=False,
               **kwargs):
    super(ExecNinjaGenerator, self).__init__(module_name, **kwargs)
    # TODO(nativeclient:3734): We also use is_system_library
    # temporarily for building bare_metal_loader, but will stop using
    # it this way once that work is upstreamed.
    self._is_system_library = is_system_library
    self._install_path = install_path

    if OPTIONS.is_nacl_build() and not self._is_host:
      self.add_ld_flags('-dynamic',
                        '-Wl,-Ttext-segment=' + self._NACL_TEXT_SEGMENT_ADDRESS)

    if not is_system_library and not self._is_host:
      if OPTIONS.is_arm():
        # On Bare Metal ARM, we need to expose all symbols in libgcc
        # so that NDK can use them.
        self._whole_archive_deps.extend(get_libgcc_for_bionic())
      else:
        self._static_deps.extend(get_libgcc_for_bionic())
      self._shared_deps.extend(
          # If |enable_libcxx| is set, use libc++.so, otherwise use stlport.
          build_common.get_bionic_shared_objects(
              use_stlport=not self._enable_libcxx,
              use_libcxx=self._enable_libcxx))

  def link(self, variables=None, implicit=None, **kwargs):
    implicit = (build_common.as_list(implicit) + self._static_deps +
                self._whole_archive_deps)
    if self._notices_only or self._is_host:
      implicit += self._shared_deps
    else:
      implicit += map(self._get_toc_file_for_so, self._shared_deps)

    if not self._is_host:
      implicit.extend([build_common.get_bionic_crtbegin_o(),
                       build_common.get_bionic_crtend_o()])
      if OPTIONS.is_debug_code_enabled() and not self._is_system_library:
        implicit.append(build_common.get_bionic_libc_malloc_debug_leak_so())
    variables = self._add_lib_vars(build_common.as_dict(variables))
    bin_path = os.path.join(self._intermediates_dir, self._module_name)
    if OPTIONS.is_nacl_build() and not self._is_host:
      rule_prefix = 'clang.'
    else:
      rule_prefix = ''
    rule_body = 'ld_system_library' if self._is_system_library else 'ld'
    intermediate_bin = self.build(
        bin_path,
        self._get_rule_name(rule_prefix + rule_body),
        self._consume_objects(),
        implicit=implicit,
        variables=variables,
        **kwargs)
    if OPTIONS.is_debug_info_enabled() and not self._is_host:
      self.build_stripped(bin_path)
    if OPTIONS.is_nacl_build() and not self._is_host:
      self.ncval_test(intermediate_bin)
    if self._install_path is not None:
      install_exe = os.path.join(self._install_path, self._module_name)
      self.install_to_build_dir(install_exe, intermediate_bin)
    return intermediate_bin

  @staticmethod
  def get_nacl_text_segment_address():
    return ExecNinjaGenerator._NACL_TEXT_SEGMENT_ADDRESS


class TblgenNinjaGenerator(NinjaGenerator):
  """Encapsulates ninja file generation for .td files using LLVM tblgen"""

  def __init__(self, module_name, **kwargs):
    super(TblgenNinjaGenerator, self).__init__(module_name, **kwargs)
    self._llvm_path = staging.as_staging('android/external/llvm')
    self._flags = ['-I=%s' % os.path.join(self._llvm_path, 'include')]

  def generate(self, output, arguments='-gen-intrinsic', arch=None):
    name = os.path.splitext(os.path.basename(output))[0]
    flags = self._flags
    if name == 'Intrinsics':
      source = os.path.join(self._llvm_path, 'include', 'llvm', 'IR',
                            'Intrinsics.td')
    else:
      assert arch, 'arch should be specified.'
      arch_include_path = os.path.join(self._llvm_path, 'lib/Target', arch)
      flags.append('-I=%s' % arch_include_path)
      source = os.path.join(arch_include_path, arch + '.td')
    implicit = [toolchain.get_tool(OPTIONS.target(), 'llvm_tblgen')]
    self.build(output, self._get_rule_name('llvm_tblgen'), source,
               variables={'flags': ' '.join(flags),
                          'arguments': arguments},
               implicit=implicit)

  @staticmethod
  def emit_common_rules(n):
    n.rule('llvm_tblgen',
           (toolchain.get_tool(OPTIONS.target(), 'llvm_tblgen') +
            ' $flags $in -o $out $arguments'),
           description='tblgen $in $out $arguments')

  def _get_rule_name(self, rule_prefix):
    if self._notices_only:
      return 'phony'
    return rule_prefix


# TODO(crbug.com/376952): Do licensing checks during build using ninja
# metadata to give us full information about included files.
class NoticeNinjaGenerator(NinjaGenerator):
  @staticmethod
  def emit_common_rules(n):
    # Concatenate a list of notice files into a file NOTICE file which
    # ends up being shown to the user.  We take care to show the path
    # to each notices file as it makes the notices more intelligible,
    # removing internal details like out/staging path prefix and our
    # ARC MOD TRACK markers that allow us to track a differently-named
    # notice file in upstream code.
    n.rule('notices_install',
           command='rm -f $out; (for f in $in; do echo;'
           'echo "==> $$f <==" | sed -e "s?out/staging/??g"; echo; '
           'grep -v "ARC MOD TRACK" $$f; done) > $out || '
           '(rm -f $out; exit 1)',
           description='notices_install $out')

    # Unpack and merge a notice tarball into final NOTICE_FILES tree.
    n.rule('notices_unpack',
           command='mkdir -p $out_dir && tar xf $in -C $out_dir && touch $out',
           description='notices_unpack $in')

  def _is_possibly_staged_path_open_sourced(self, path):
    """Check if the given path is open sourced, allowing for staging.

    We fall back to open_source module normally, but if in staging we have
    to fall back to the real path.  If we are given a directory in staging
    we only consider it open sourced if its third party and mods equivalents
    are both completely open sourced."""
    if path.startswith(build_common.get_staging_root()):
      path = staging.as_real_path(path)
      if path.startswith(build_common.get_staging_root()):
        third_party_path, mods_path = staging.get_composite_paths(path)
        return (open_source.is_open_sourced(third_party_path) and
                open_source.is_open_sourced(mods_path))
    return open_source.is_open_sourced(path)

  def _verify_open_sourcing(self, n, error_message):
    problem_examples = []
    for root in n.get_gpl_roots():
      raise Exception('GPL code is being binary distributed from %s' %
                      ','.join([n.get_license_root_example(r)
                               for r in n.get_gpl_roots()]))
    for root in n.get_source_required_roots():
      if not self._is_possibly_staged_path_open_sourced(root):
        problem_examples.append(n.get_license_root_example(root))
    if problem_examples:
      raise Exception('%s in %s' % (error_message,
                                    ','.join(n.get_source_required_examples())))

  def _build_notice(self, n, module_to_ninja_map, notice_files_dir):
    # Avoid updating n._notices with later add_notices call.
    notices = copy.deepcopy(n._notices)
    if OPTIONS.is_notices_logging():
      print 'Binary installed', n.get_module_name(), notices
    self._verify_open_sourcing(
        notices,
        '%s has targets in the binary distribution, is not open sourced, '
        'but has a restrictive license' % n._module_name)
    queue = n.get_included_module_names()
    # All included modules are now going to be binary distributed.  We need
    # to check that they are open sourced if required.  We also need to
    # check that they are not introducing a LGPL or GPL license into
    # a package that was not licensed with these.
    while queue:
      module_name = queue.pop(0)
      assert module_name in module_to_ninja_map, (
          '"%s" depended by "%s" directly or indirectly is not defined.' %
          (module_name, n._module_name))
      included_ninja = module_to_ninja_map[module_name]
      included_notices = included_ninja._notices
      if OPTIONS.is_notices_logging():
        print 'Included', module_name, included_notices
      self._verify_open_sourcing(
          included_notices,
          '%s has targets in the binary distribution, but %s has a '
          'restrictive license and is not open sourced' %
          (n._module_name, module_name))

      # It is an error to include GPL or LPGL code in something that does not
      # use that license.
      gpl_included_by_non_gpl_code = (included_notices.has_lgpl_or_gpl() and
                                      not notices.has_lgpl_or_gpl())

      # TODO(crbug.com/474819): Remove this special case whitelist.
      # webview_library is marked to be covered by the LGPL and MPL. 'webview'
      # is marked to be covered by the BSD license.  Since 'webview' includes
      # 'webview_library', this results in the check above triggering. But this
      # given that both sets of code from from the AOSP repositories, there
      # should be no conflict. We either have added bad license information for
      # one or both, or we have to improve the logic here in some other way to
      # more generally allow this.
      if n._module_name == 'webview' and module_name == 'webview_library':
        gpl_included_by_non_gpl_code = False

      if gpl_included_by_non_gpl_code:
        raise Exception(
            '%s (%s) cannot be included into %s (%s)' %
            (module_name, included_notices.get_most_restrictive_license_kind(),
             n._module_name, notices.get_most_restrictive_license_kind()))
      notices.add_notices(included_notices)
      queue.extend(included_ninja.get_included_module_names())
    # Note: We sort the notices file list so the generated output is consistent,
    # and diff_ninjas can be used.
    notice_files = sorted(notices.get_notice_files())
    assert notice_files, 'Ninja %s has no associated NOTICE' % n._ninja_name
    notices_install_path = n.get_notices_install_path()
    notice_path = os.path.join(notice_files_dir, notices_install_path)
    self.build(notice_path, 'notices_install', notice_files)

  def _merge_notice_archive(self, n, module_to_ninja_map, notice_files_dir):
    assert not n.get_included_module_names()
    notices_stamp = os.path.join(build_common.get_target_common_dir(),
                                 n._module_name + '.notices.stamp')
    self.build(notices_stamp, 'notices_unpack', n.get_notice_archive(),
               variables={'out_dir': build_common.get_notice_files_dir()})

  def build_notices(self, ninja_list):
    """Generate NOTICE_FILES directory based on ninjas' notices and deps."""
    module_to_ninja_map = {}
    for n in ninja_list:
      module_to_ninja_map[n._module_name] = n

    notice_files_dir = build_common.get_notice_files_dir()

    for n in ninja_list:
      if not n.is_installed():
        continue
      if n.get_notice_archive():
        # TODO(crbug.com/366751): remove notice_archive hack when possible
        self._merge_notice_archive(n, module_to_ninja_map, notice_files_dir)
      else:
        self._build_notice(n, module_to_ninja_map, notice_files_dir)


class TestNinjaGenerator(ExecNinjaGenerator):
  """Create a googletest/googlemock executable ninja file."""

  def __init__(self, module_name, is_system_library=False,
               use_default_main=True, enable_libcxx=False,
               run_without_test_library=False, **kwargs):
    super(TestNinjaGenerator, self).__init__(
        module_name, is_system_library=is_system_library,
        enable_libcxx=enable_libcxx, **kwargs)
    if OPTIONS.is_bare_metal_build() and is_system_library:
      self.add_library_deps('libgmock_glibc.a', 'libgtest_glibc.a')
    else:
      if enable_libcxx:
        self.add_library_deps('libchromium_base_libc++.a',
                              'libcommon_libc++.a',
                              'libpluginhandle_libc++.a')
      else:
        self.add_library_deps('libchromium_base.a',
                              'libcommon.a',
                              'libpluginhandle.a')
      if use_default_main:
        # Since there are no use cases, we do not build libc++ version of
        # libcommon_test_main.a.
        assert not enable_libcxx
        self.add_library_deps('libcommon_test_main.a',
                              'libgmock.a',
                              'libgtest.a')
    self._run_without_test_library = run_without_test_library
    self.add_library_deps('libcommon_real_syscall_aliases.a')
    self.add_include_paths(staging.as_staging('testing/gmock/include'))
    self._run_counter = 0
    self._disabled_tests = []
    self._qemu_disabled_tests = []
    self._enabled_tests = []
    if OPTIONS.is_arm():
      self._qemu_disabled_tests.append('*.QEMU_DISABLED_*')

  @staticmethod
  def _get_toplevel_run_test_variables():
    """Get the variables for running unit tests defined in toplevel ninja."""
    variables = {
        'runner': toolchain.get_tool(OPTIONS.target(), 'runner'),
        'runner_without_test_library': toolchain.get_tool(
            OPTIONS.target(), 'runner_without_test_library'),
        'valgrind_runner': toolchain.get_tool(OPTIONS.target(),
                                              'valgrind_runner'),
        'valgrind_runner_without_test_library': toolchain.get_tool(
            OPTIONS.target(), 'valgrind_runner_without_test_library'),
    }
    if OPTIONS.is_bare_metal_arm():
      variables['qemu_arm'] = ' '.join(toolchain.get_qemu_arm_args())
    return variables

  @staticmethod
  def _get_toplevel_run_test_rules():
    """Get the rules for running unit tests defined in toplevel ninja."""
    # rule name -> (command, test output handler, description)
    rules = {
        # NOTE: When $runner is empty, there will be an extra space in front of
        # the test invocation.
        'run_test': (
            '$runner $in $argv',
            build_common.get_test_output_handler(),
            'run_test $test_name'),
        'run_gtest': (
            '$runner $in $argv $gtest_options',
            build_common.get_test_output_handler(use_crash_analyzer=True),
            'run_gtest $test_name'),
        'run_gtest_without_test_library': (
            '$runner_without_test_library $in $argv $gtest_options',
            build_common.get_test_output_handler(use_crash_analyzer=True),
            'run_gtest $test_name'),
        'run_gtest_with_valgrind': (
            '$valgrind_runner $in $argv $gtest_options',
            build_common.get_test_output_handler(),
            'run_gtest_with_valgrind $test_name'),
        'run_gtest_with_valgrind_and_without_test_library': (
            '$valgrind_runner_without_test_library $in $argv $gtest_options',
            build_common.get_test_output_handler(),
            'run_gtest_with_valgrind $test_name')
    }
    if OPTIONS.is_bare_metal_build():
      rules['run_gtest_glibc'] = (
          '$qemu_arm $in $argv $gtest_options',
          build_common.get_test_output_handler(use_crash_analyzer=True),
          'run_gtest_glibc $test_name')
    return rules

  @staticmethod
  def emit_common_rules(n):
    pool_name = 'unittest_pool'
    n.pool(pool_name, multiprocessing.cpu_count())
    variables = TestNinjaGenerator._get_toplevel_run_test_variables()
    for key, value in variables.iteritems():
      n.variable(key, value)
    rules = TestNinjaGenerator._get_toplevel_run_test_rules()
    for name, (command, output_handler, description) in rules.iteritems():
      n.rule(name, '%s %s' % (command, output_handler), description=description,
             pool=pool_name)

  def _save_test_info(self, test_path, counter, rule, variables):
    """Save information needed to run unit tests remotely as JSON file."""
    rules = TestNinjaGenerator._get_toplevel_run_test_rules()
    merged_variables = TestNinjaGenerator._get_toplevel_run_test_variables()
    merged_variables.update(variables)
    merged_variables['in'] = test_path
    merged_variables['disabled_tests'] = self._disabled_tests
    merged_variables['qemu_disabled_tests'] = self._qemu_disabled_tests
    merged_variables['enabled_tests'] = self._enabled_tests

    test_info = {
        'variables': merged_variables,
        'command': rules[rule][0],
    }
    self._build_test_info(self._module_name, counter, test_info)

  def find_all_contained_test_sources(self):
    all_sources = self.find_all_files(self._base_path,
                                      ['_test' + x
                                       for x in _PRIMARY_EXTENSIONS],
                                      include_tests=True)
    for basename in ['tests', 'test_util']:
      subdir = os.path.join(self._base_path, basename)
      if os.path.exists(subdir):
        all_sources += self.find_all_files(subdir, _PRIMARY_EXTENSIONS,
                                           include_tests=True)
    return list(set(all_sources))

  def build_default_all_test_sources(self):
    return self.build_default(self.find_all_contained_test_sources(),
                              base_path=None)

  def add_disabled_tests(self, *disabled_tests):
    """Add tests to be disabled."""
    # Disallow setting both enabled_tests and disabled_tests.
    assert not self._enabled_tests
    self._disabled_tests += list(disabled_tests)

  def add_qemu_disabled_tests(self, *qemu_disabled_tests):
    """Add tests to be disabled only on QEMU."""
    # Disallow setting both enabled_tests and qemu_disabled_tests.
    assert not self._enabled_tests
    self._qemu_disabled_tests += list(qemu_disabled_tests)

  def add_enabled_tests(self, *enabled_tests):
    """Add tests to be enabled.

    When you use this function, you must not use add_disabled_tests
    and add_qemu_disabled_tests.
    """
    # Disallow setting both enabled_tests and *disabled_tests.
    assert not self._disabled_tests
    # Only '*.QEMU_DISABLED_*' is allowed.
    assert len(self._qemu_disabled_tests) < 2
    self._enabled_tests += list(enabled_tests)

  def link(self, **kwargs):
    # Be very careful here.  If you have no objects because of
    # a path being wrong, the test will link and run successfully...
    # which is kind of bad if you really think about it.
    assert self._object_list, ('Module %s has no objects to link' %
                               self._module_name)
    return super(TestNinjaGenerator, self).link(**kwargs)

  def _get_test_rule_name(self, enable_valgrind):
    if enable_valgrind and OPTIONS.enable_valgrind():
      if self._run_without_test_library:
        return 'run_gtest_with_valgrind_and_without_test_library'
      return 'run_gtest_with_valgrind'
    elif OPTIONS.is_bare_metal_build() and self._is_system_library:
      return 'run_gtest_glibc'
    elif self._run_without_test_library:
      return 'run_gtest_without_test_library'
    else:
      return 'run_gtest'

  def run(self, tests, argv=None, enable_valgrind=True, implicit=None,
          rule=None):
    assert tests
    self._run_counter += 1
    if OPTIONS.run_tests():
      for test_path in tests:
        self._run_one(test_path, argv, enable_valgrind, implicit, rule)
    return self

  def _run_one(self, test_path, argv=None, enable_valgrind=True, implicit=None,
               rule=None):
    # TODO(crbug.com/378196): Create a script to build qemu-arm from stable
    # sources and run that built version here.
    if open_source.is_open_source_repo() and OPTIONS.is_arm():
      return
    variables = {'test_name': self._module_name}
    if argv:
      variables['argv'] = argv

    if self._enabled_tests:
      # Disallow setting both enabled_tests and *disabled_tests.
      assert not self._disabled_tests
      # Only '*.QEMU_DISABLED_*' is allowed.
      assert len(self._qemu_disabled_tests) < 2
    variables['gtest_options'] = unittest_util.build_gtest_options(
        self._enabled_tests, self._disabled_tests + self._qemu_disabled_tests)

    implicit = build_common.as_list(implicit)
    # All tests should have an implicit dependency against the fake
    # libposix_translation.so to run under sel_ldr.
    implicit.append(os.path.join(build_common.get_load_library_path_for_test(),
                                 'libposix_translation.so'))
    # When you run a test, you need to install .so files.
    for deps in self._shared_deps:
      implicit.append(os.path.join(build_common.get_load_library_path(),
                                   os.path.basename(deps)))
    if OPTIONS.is_nacl_build() and not self._is_host:
      implicit.append(self.get_ncval_test_output(test_path))
    implicit.append(build_common.get_bionic_runnable_ld_so())
    if OPTIONS.enable_valgrind():
      implicit.append('src/build/valgrind/memcheck/suppressions.txt')
    if not rule:
      rule = self._get_test_rule_name(enable_valgrind)
    test_result_prefix = os.path.join(os.path.dirname(test_path),
                                      self._module_name)
    self.build(test_result_prefix + '.results.' + str(self._run_counter), rule,
               inputs=test_path, variables=variables, implicit=implicit)

    self._save_test_info(test_path, self._run_counter, rule, variables)


class PpapiTestNinjaGenerator(TestNinjaGenerator):
  """Create a test executable that has PPAPI mocking. """

  def __init__(self, module_name, implicit=None, **kwargs):
    # Force an implicit dependency on libppapi_mocks.a in order to assure
    # that all of the auto-generated headers for the source files that
    # comprise that library are generated before any tests might want to
    # include them.
    libppapi_mocks_build_path = build_common.get_build_path_for_library(
        'libppapi_mocks.a')
    implicit = [libppapi_mocks_build_path] + build_common.as_list(implicit)
    super(PpapiTestNinjaGenerator, self).__init__(module_name,
                                                  implicit=implicit,
                                                  **kwargs)
    self.add_ppapi_compile_flags()
    self.add_ppapi_link_flags()
    # ppapi_mocks/background_thread.h uses Chromium's condition variable.
    self.add_libchromium_base_compile_flags()
    self.add_library_deps('libppapi_mocks.a')
    self.add_include_paths('src/ppapi_mocks',
                           self.get_ppapi_mocks_generated_dir())

  @staticmethod
  def get_ppapi_mocks_generated_dir():
    return os.path.join(build_common.get_build_dir(), 'ppapi_mocks')


# TODO(crbug.com/395058): JavaNinjaGenerator handles aapt processing, but
# it is Android specific rule and should be placed outside this class.
# It will be better that JarNinjaGenerator contains it and ApkNinjaGenerator
# inherits JarNinjaGenerator. Once we can remove canned jar files, and use
# make_to_ninja for existing some modules that use JarNinjaGenerator directly,
# JarNinjaGenerator can be renamed as JavaLibraryNinjaGenerator.
class JavaNinjaGenerator(NinjaGenerator):

  # Map from module name to path to compiled classes.
  _module_to_compiled_class_path = {}

  # Resource includes (passed to aapt) to use for all APKs.
  _default_resource_includes = []

  """Implements a simple java ninja generator."""
  def __init__(self, module_name, base_path=None,
               source_subdirectories=None, exclude_aidl_files=None,
               include_aidl_files=None, classpath_files=None,
               resource_subdirectories=None, resource_includes=None,
               resource_class_names=None, manifest_path=None,
               require_localization=False, aapt_flags=None, use_multi_dex=False,
               link_framework_aidl=False, extra_packages=None,
               extra_dex2oat_flags=None, **kwargs):
    super(JavaNinjaGenerator, self).__init__(module_name, base_path=base_path,
                                             **kwargs)

    # Generate paths to all source code files (not just .java files)
    self._source_paths = [
        os.path.join(self._base_path or '', path)
        for path in build_common.as_list(source_subdirectories)]

    exclude_aidl_files = frozenset(
        os.path.join(self._base_path, path)
        for path in build_common.as_list(exclude_aidl_files))
    self._exclude_aidl_files = exclude_aidl_files
    include_aidl_files = frozenset(
        os.path.join(self._base_path, path)
        for path in build_common.as_list(include_aidl_files))
    self._include_aidl_files = include_aidl_files

    # Information for the aidl tool.
    self._preprocessed_aidl_files = []
    if link_framework_aidl:
      self._preprocessed_aidl_files = [toolchain.get_framework_aidl()]

    # Specific information for the javac compiler.
    self._javac_source_files = []
    self._javac_stamp_files = []
    self._javac_source_files_hashcode = None
    self._javac_classpath_files = build_common.as_list(classpath_files)
    self._javac_classpath_dirs = []
    self._java_source_response_file = self._get_build_path(subpath='java.files')
    self._jar_files_to_extract = []

    self._resource_paths = []
    self._resource_includes = (JavaNinjaGenerator._default_resource_includes +
                               build_common.as_list(resource_includes))
    if resource_class_names is None:
      self._resource_class_names = ['R']
    else:
      self._resource_class_names = resource_class_names

    if resource_subdirectories is not None:
      self._resource_paths = [
          os.path.join(self._base_path or '', path)
          for path in build_common.as_list(resource_subdirectories)]

    if manifest_path is None:
      manifest_path = 'AndroidManifest.xml'
    manifest_staging_path = staging.as_staging(
        os.path.join(self._base_path or '', manifest_path))
    if os.path.exists(manifest_staging_path):
      self._manifest_path = manifest_staging_path
    else:
      self._manifest_path = None

    self._require_localization = require_localization

    if extra_packages is None:
      self._extra_packages = []
    else:
      self._extra_packages = extra_packages
      flags = []
      if aapt_flags:
        flags.extend(aapt_flags)
      flags.append('--auto-add-overlay')
      if extra_packages:
        flags.extend(['--extra-packages', ':'.join(extra_packages)])
      aapt_flags = flags
    self._extra_dex2oat_flags = extra_dex2oat_flags

    self._aapt_flags = aapt_flags
    self._use_multi_dex = use_multi_dex

  @staticmethod
  def emit_common_rules(n):
    n.variable('aapt', toolchain.get_tool('java', 'aapt'))
    n.variable('aidl', toolchain.get_tool('java', 'aidl'))
    n.variable('dex2oat', ('src/build/filter_dex2oat_warnings.py ' +
                           toolchain.get_tool('java', 'dex2oat')))
    n.variable('java-event-log-tags',
               toolchain.get_tool('java', 'java-event-log-tags'))
    n.variable('javac', ('src/build/filter_java_warnings.py ' +
                         toolchain.get_tool('java', 'javac')))
    n.variable('jflags', ('-J-Xmx1024M -source 1.7 -target 1.7 '
                          '-Xmaxerrs 9999999 -encoding UTF-8 -g'))
    n.variable('aidlflags', '-b')
    n.variable('aaptflags', '-m')

    n.rule('javac',
           ('rm -rf $out_class_path && '
            'mkdir -p $out_class_path && '
            '$javac $jflags @$response_file -d $out_class_path && '
            'touch $out'),
           description='javac $module_name ($count files)',
           rspfile='$response_file',
           rspfile_content='$in_newline')
    n.rule('aidl',
           '$aidl -d$out.d $aidlflags $in $out',
           depfile='$out.d',
           description='aidl $out')
    # Aapt is very loud about warnings for missing comments for public
    # symbols that we cannot suppress.  Only show these when there is an
    # actual error.  Note also that we do not use the
    # --generate-dependencies flag to aapt.  While it does generate a
    # Makefile-style dependency file, that file will have multiple
    # targets and ninja does not support depfiles with multiple targets.
    n.rule('aapt_package',
           # aapt generates a broken APK if it already exists.
           ('rm -f $out; ' +
            toolchain.get_tool('java', 'aapt') +
            ' package $aaptflags -M $manifest ' +
            '$input_path > $tmpfile 2>&1 || ' +
            '(cat $tmpfile; exit 1)'),
           description='aapt package $out')
    n.rule('llvm_rs_cc',
           ('LD_LIBRARY_PATH=$toolchaindir '
            '$toolchaindir/llvm-rs-cc -o $resout -p $srcout $args '
            '-I $clangheader -I $scriptheader $in > $log 2>&1 || '
            '(cat $log; rm $log; exit 1)'),
           description='llvm-rs-cc $resout $srcout')
    # Remove classes*.dex from the file.
    n.rule('aapt_remove_dexes',
           ('cp $in $out && '
            '$aapt remove $out `$aapt list $out |grep -e "classes[0-9]*.dex"`'),
           description='aapt remove .dex from $out')
    n.rule('eventlogtags',
           '$java-event-log-tags -o $out $in /dev/null',
           description='eventlogtag $out')
    n.rule('dex2oat',
           ('rm -f $out; '
            '$dex2oat $dex2oatflags $warning_grep'),
           description='dex2oat $out')
    n.rule('zip',
           command=('TMPD=`mktemp -d` TMPF="$$TMPD/tmp.zip"; '
                    '(cd $zip_working_dir && '
                    'zip --quiet $zip_flags $$TMPF $in $zip_pattern && '
                    'cd - > /dev/null && cp $$TMPF $out && '
                    '(rm -f $$TMPF; rmdir $$TMPD)) '
                    '|| (rm -f $out $$TMPF; rmdir $$TMPD; exit 1)'),
           description='zipping $desc')

  @staticmethod
  def add_default_resource_include(resource_include):
    JavaNinjaGenerator._default_resource_includes.append(
        resource_include)

  def add_built_jars_to_classpath(self, *jars):
    self._javac_classpath_files.extend([
        build_common.get_build_path_for_jar(jar, subpath='classes.jar')
        for jar in jars])

  def _add_java_files(self, java_files):
    if not java_files:
      return

    # Transform all paths to be relative to staging.
    java_files = [staging.as_staging(java_file) for java_file in java_files]

    self._javac_source_files_hashcode = None
    self._javac_stamp_files = []
    self._javac_source_files.extend(java_files)
    return self

  def add_java_files(self, files, base_path=''):
    if base_path is not None:
      if base_path == '':
        base_path = self._base_path
      files = [os.path.join(base_path, f) for f in files]
    self._add_java_files(files)

  @staticmethod
  def _extract_pattern_as_java_file_path(path, pattern, class_name=None,
                                         extension='.java',
                                         ignore_dependency=False):
    """Extracts a dotted package name using the indicated pattern from a file.
    Converts the dotted package name to a relative file path, which is then
    returned."""
    package_name = _extract_pattern_from_file(path, pattern, ignore_dependency)
    package_path = package_name.replace('.', '/')
    if class_name is None:
      # Take the name of the file we read from as the name of the class that it
      # represents.
      class_name = os.path.splitext(os.path.split(path)[1])[0]
    return os.path.join(package_path, class_name + extension)

  @staticmethod
  def _change_extension(path, new_extension, old_extension=None):
    """Change the extension on the path to new_extension. If old_extension is
    given, the given path's extension must match first."""
    base, ext = os.path.splitext(path)
    if old_extension and ext == old_extension:
      return base + new_extension
    return path

  def _get_source_files_hashcode(self):
    if self._javac_source_files_hashcode is None:
      real_srcs = ' '.join(staging.as_real_path(src_path) for src_path in
                           self._javac_source_files)
      self._javac_source_files_hashcode = _compute_hash_fingerprint(real_srcs)
    return self._javac_source_files_hashcode

  def _get_compiled_class_path(self):
    # We have a computed intermediate path for the .class files, based on the
    # hash of all the "real" paths of all the source files. That way if even
    # a single file is overlaid (or un-overlaid), all previous intermediates
    # for the jar are invalidated.  This function must not be called until
    # all source files are added.
    return self._get_build_path(subpath=self._get_source_files_hashcode())

  def _get_stamp_file_path_for_compiled_classes(self):
    return self._get_build_path(subpath=(self._get_source_files_hashcode() +
                                         '.javac.stamp'))

  @staticmethod
  def get_compiled_class_path_for_module(module):
    return JavaNinjaGenerator._module_to_compiled_class_path[module]

  def _build_eventlogtags(self, output_path, input_file):
    # To properly map the logtag inputs to outputs, we need to know the
    # package name.
    re_pattern = 'option java_package ([^;\n]+)'
    java_path = JavaNinjaGenerator._extract_pattern_as_java_file_path(
        input_file, re_pattern, ignore_dependency=True)
    output_file = os.path.join(output_path, java_path)
    return self.build([output_file], 'eventlogtags', inputs=[input_file])

  def _build_aidl(self, output_path, input_file):
    # To properly map the aidl inputs to outputs, we need to know the
    # package name.
    re_pattern = 'package (.+);'
    java_path = JavaNinjaGenerator._extract_pattern_as_java_file_path(
        input_file, re_pattern, ignore_dependency=True)
    output_file = os.path.join(output_path, java_path)
    return self.build([output_file], 'aidl', inputs=[input_file])

  def _build_javac(self, implicit=None):
    if implicit is None:
      implicit = []
    jflags = _VariableValueBuilder('jflags')
    jflags.append_optional_path_list('-bootclasspath',
                                     self._get_minimal_bootclasspath())
    jflags.append_optional_path_list('-classpath',
                                     self._javac_classpath_files +
                                     self._javac_classpath_dirs)

    java_source_files = sorted(self._javac_source_files)

    if not java_source_files:
      raise Exception('No Java source files specified')

    variables = dict(out_class_path=self._get_compiled_class_path(),
                     response_file=self._java_source_response_file,
                     count=len(java_source_files),
                     module_name=self._module_name,
                     jflags=jflags)

    self._module_to_compiled_class_path[self._module_name] = (
        self._get_compiled_class_path())

    self._javac_stamp_files.append(
        self._get_stamp_file_path_for_compiled_classes())
    return self.build(self._javac_stamp_files, 'javac',
                      inputs=java_source_files,
                      implicit=(self._get_minimal_bootclasspath() +
                                self._javac_classpath_files +
                                implicit),
                      variables=variables)

  def _build_aapt(self, outputs=None, output_apk=None, inputs=None,
                  implicit=None, input_path=None, out_base_path=None):
    outputs = build_common.as_list(outputs)
    implicit = build_common.as_list(implicit)

    resource_paths = [staging.as_staging(path)
                      for path in build_common.as_list(self._resource_paths)]

    aaptflags = _VariableValueBuilder('aaptflags')
    aaptflags.append_flag('-f')
    if self._require_localization:
      aaptflags.append_flag('-z')
    aaptflags.append_flag_pattern('-S %s', resource_paths)
    if self._resource_includes:
      aaptflags.append_flag_pattern('-I %s', self._resource_includes)

    if out_base_path:
      aaptflags.append_flag('-m')
      aaptflags.append_flag('-J ' + out_base_path)

    if output_apk:
      aaptflags.append_flag('-F ' + output_apk)
      outputs.append(output_apk)

    if self._aapt_flags:
      for flag in self._aapt_flags:
        aaptflags.append_flag(pipes.quote(flag))

    implicit += [self._manifest_path]
    implicit += build_common.as_list(self._resource_includes)

    variables = dict(
        aaptflags=aaptflags,
        input_path=input_path or '',
        manifest=self._manifest_path,
        tmpfile=self._get_package_build_path(subpath='aapt_errors'))

    return self.build(outputs=outputs, rule='aapt_package', inputs=inputs,
                      implicit=implicit, variables=variables)

  def _build_llvm_rs_cc(self):
    """Generates renderscript source code and llvm bit code if exists.

    This function does nothing and returns empty array if there is no
    renderscript source files.
    """
    input_files = self.find_all_files(
        base_paths=[self._base_path], suffix=['rs'])
    if not input_files:
      return []

    intermediate_dir = build_common.get_build_path_for_apk(self._module_name)
    rsout_dir = os.path.join(intermediate_dir, 'src', 'renderscript')
    rsout_resdir = os.path.join(rsout_dir, 'res', 'raw')

    rsout_res_files = []
    for f in input_files:
      basename = re.sub('\.rs$', '.bc', os.path.basename(f))
      rsout_res_files.append(os.path.join(rsout_resdir, basename))
    # The output files have "ScriptC_" prefix, e.g. gray.rs will be converted to
    # ScriptC_gray.java.
    rsout_src_files = []
    for f in input_files:
      basename = re.sub('^(.*)\.rs$', r'ScriptC_\1.java', os.path.basename(f))
      directory = os.path.dirname(f.replace(self._base_path, rsout_dir))
      rsout_src_files.append(os.path.join(directory, basename))

    variables = {
        'log': os.path.join(intermediate_dir, 'build.log'),
        'toolchaindir': toolchain.get_android_sdk_build_tools_dir(),
        'resout': rsout_resdir,
        'srcout': os.path.join(rsout_dir, 'src'),
        'args': '-target-api 18 -Wall '
                '-Werror -rs-package-name=android.support.v8.renderscript',
        'clangheader': toolchain.get_clang_include_dir(),
        'scriptheader': os.path.join('third_party', 'android', 'frameworks',
                                     'rs', 'scriptc')
    }
    self.add_generated_files(base_paths=[], files=rsout_src_files)
    self.add_resource_paths([os.path.join(build_common.get_arc_root(),
                                          os.path.dirname(rsout_resdir))])
    # Needed for packaging multiple resources.
    self.add_flags('aaptflags', '--auto-add-overlay')

    return self.build(rsout_res_files + rsout_src_files, 'llvm_rs_cc',
                      input_files, variables=variables)

  def _build_and_add_all_generated_sources(self, implicit=None):
    # |implicit| is unused here but it is used in the inherited class.
    self.build_and_add_logtags()
    self.build_and_add_aidl_generated_java()

  def build_and_add_resources(self, implicit=None):
    """Emits a build rule to process the resource files, generating R.java, and
    adds the generated file to the list to include in the package."""

    # Skip if we don't appear to be configured to have any resources.
    if not self._resource_paths or not self._manifest_path:
      return

    if implicit is None:
      implicit = []

    resource_files = self.find_all_files(self._resource_paths, ['.xml'])
    resource_files = [staging.as_staging(path) for path in resource_files]
    self.add_notice_sources(resource_files)

    out_resource_path = build_common.get_build_path_for_apk(
        self._module_name, subpath='R')

    # Attempt to quickly extract the value of the package name attribute from
    # the manifest, without resorting to an actual XML parser.
    re_pattern = 'package="(.+?)"'

    java_files = []
    for c in self._resource_class_names:
      java_path = JavaNinjaGenerator._extract_pattern_as_java_file_path(
          self._manifest_path, re_pattern, class_name=c, ignore_dependency=True)
      java_files.append(os.path.join(out_resource_path, java_path))

      for extra_package in self._extra_packages:
        java_files.append(os.path.join(out_resource_path,
                                       extra_package.replace('.', '/'),
                                       '%s.java' % c))

    self._build_aapt(outputs=java_files, implicit=resource_files + implicit,
                     out_base_path=out_resource_path)

    self._add_java_files(java_files)

    return self

  def build_and_add_logtags(self, logtag_files=None):
    """Emits code to convert .logtags to .java, and adds the generated .java
    files to the list to include in the package."""
    if logtag_files is None:
        logtag_files = self.find_all_files(self._source_paths, ['.logtags'])

    logtag_files = [staging.as_staging(logtag_file)
                    for logtag_file in logtag_files]
    out_eventlog_path = self._get_build_path(subpath='eventlogtags')

    java_files = []
    for logtag_file in logtag_files:
      java_files += self._build_eventlogtags(output_path=out_eventlog_path,
                                             input_file=logtag_file)

    self._add_java_files(java_files)

  def build_and_add_aidl_generated_java(self):
    """Emits code to convert .aidl to .java, and adds the generated .java files
    to the list to include in the package."""
    aidl_files = []
    all_aidl_files = self.find_all_files(self._source_paths, ['.aidl'])
    all_aidl_files.extend(staging.as_staging(x)
                          for x in self._include_aidl_files)

    for aidl_file in all_aidl_files:
      if aidl_file not in self._exclude_aidl_files:
        aidl_file = staging.as_staging(aidl_file)
        with open_dependency(aidl_file, 'r', ignore_dependency=True) as f:
          if not re.search('parcelable', f.read()):
            aidl_files.append(aidl_file)

    aidl_files = [staging.as_staging(x) for x in aidl_files]

    out_aidl_path = self._get_build_path(subpath='aidl')

    # For any package, all the aidl invocations should have the same include
    # path arguments, so emit it directly to the subninja.
    aidlflags = _VariableValueBuilder('aidlflags')
    aidlflags.append_flag_pattern('-I%s', [staging.as_staging(path)
                                           for path in self._source_paths])
    aidlflags.append_flag_pattern(
        '-p%s',
        [staging.as_staging(path) for path in self._preprocessed_aidl_files])
    self.variable('aidlflags', aidlflags)

    java_files = []
    for aidl_file in aidl_files:
      java_files += self._build_aidl(output_path=out_aidl_path,
                                     input_file=aidl_file)

    self._add_java_files(java_files)

  def add_aidl_flags(self, *flags):
    self.add_flags('aidlflags', *flags)
    return self

  def add_aidl_include_paths(self, *paths):
    self.add_aidl_flags(*['-I' + staging.as_staging(x) for x in paths])
    return self

  def add_all_java_sources(self, include_tests=False,
                           exclude_source_files=None):
    """Adds the default java source code found in the source paths to the list
    to include in the list of sources to be built."""
    return self._add_java_files(self.find_all_files(
        self._source_paths,
        ['.java'],
        exclude=exclude_source_files,
        include_tests=include_tests))

  def add_generated_files(self, base_paths, files):
    """Adds other generated source files to the list of sources to be built."""
    base_paths = [staging.as_staging(base_path) for base_path in base_paths]
    return self._add_java_files(files)

  def add_extracted_jar_contents(self, *jar_files):
    """Embeds jar_files into the current target (either a jar file or an apk
    package) to emulate Android.mk's LOCAL_STATIC_JAVA_LIBRARIES=."""
    self._jar_files_to_extract.extend(jar_files)
    self.add_built_jars_to_classpath(*jar_files)

  def _get_stamp_file(self, jar_file):
    return self._get_build_path(subpath=(self._get_source_files_hashcode() +
                                         '.' + jar_file + '.unzip.stamp'))

  def _get_package_build_path(self, subpath=None, is_target=False):
    return build_common.get_build_path_for_apk(
        self._module_name, subpath=subpath, is_target=is_target)

  def _extract_jar_contents(self):
    stamp_files = []
    for index, jar_file in enumerate(self._jar_files_to_extract):
      unzip_stamp_file = self._get_stamp_file(jar_file)
      implicit = self._javac_stamp_files
      if index > 0:
        # Add the previous stamp file to implicit to serialize the series of
        # unzip operations. With this, in case when two or more jar files
        # have exactly the same .class file, the last jar file's is used in
        # a deterministic manner.
        # TODO(yusukes): Check if this is really necessary.
        previous_unzip_stamp_file = self._get_stamp_file(
            self._jar_files_to_extract[index - 1])
        implicit.append(previous_unzip_stamp_file)
      # We unzip into the same directory as was used for compiling
      # java files unique to this jar.  The implicit dependency makes sure
      # that we do not unzip until all compilation is complete (as the
      # compilation blows away this directory and recreates it).
      self.build(unzip_stamp_file, 'unzip',
                 build_common.get_build_path_for_jar(
                     jar_file, subpath='classes.jar'),
                 implicit=implicit,
                 variables={'out_dir': self._get_compiled_class_path()})
      stamp_files.append(unzip_stamp_file)
    return stamp_files

  def build_all_added_sources(self, implicit=None):
    """Compiles the java code into .class files."""
    if implicit is None:
      implicit = []
    self._build_javac(implicit=implicit)
    return self

  def build_default_all_sources(self, include_tests=False,
                                exclude_source_files=None,
                                implicit=None):
    """Find and builds all generated and explicit sources, generating .class
    files."""
    if exclude_source_files is None:
      # Any package-info.java is expected to be an almost empty file with just
      # a package declaration, and which does not generate a .class file when
      # compiled with javac.
      exclude_source_files = ['package-info.java']

    if implicit is None:
      implicit = []
    implicit = implicit + self._build_llvm_rs_cc()
    self._build_and_add_all_generated_sources(implicit=implicit)
    self.add_all_java_sources(include_tests=include_tests,
                              exclude_source_files=exclude_source_files)
    return self.build_all_added_sources(implicit=implicit)

  def _get_sentinel_install_path(self, install_path):
    """Generate a sentinel path for use with dexopt.

    A sentinel path is passed to dexopt to indicate both the
    build-time path and run-time path of a file with one string.  A
    "/./" path element indicates the division point.  So the sentinel
    path to /system/framework/foo.jar would be
    out/target/$TARGET/root/./system/framework/foo.jar.

    See dalvik/vm/Misc.h for more info on sentinel paths.
    """
    return build_common.get_android_fs_path('.' + install_path)

  def _dex2oat(self, apk_install_path, apk_path_in, apk_path_out,
               extra_flags=None):
    """Run dex2oat against apk or jar."""
    dex2oatflags = build_common.get_dex2oat_for_apk_flags(
        apk_path=apk_path_in,
        apk_install_path=apk_install_path,
        output_odex_path=self._output_odex_file)
    if extra_flags:
      dex2oatflags += build_common.as_list(extra_flags)

    boot_image_dir = os.path.join(build_common.get_android_fs_root(),
                                  'system/framework',
                                  build_common.get_art_isa())
    implicit = [
        toolchain.get_tool('java', 'dex2oat'),
        os.path.join(boot_image_dir, 'boot.art'),
        os.path.join(boot_image_dir, 'boot.oat')]
    self.build(self._output_odex_file, 'dex2oat', apk_path_in,
               {'dex2oatflags': dex2oatflags}, implicit=implicit)

    remove_dexes_rule = 'aapt_remove_dexes'
    if not OPTIONS.enable_art_aot():
      # When running in fully interpreted, non-boot image mode, ART needs all
      # the .jar and .apk files to still have the .dex file inside them. If that
      # is the case, just copy the intermediate files to their final destination
      # unchanged.
      remove_dexes_rule = 'cp'
    self.build(apk_path_out, remove_dexes_rule, apk_path_in,
               implicit=staging.third_party_to_staging(
                   toolchain.get_tool('java', 'aapt')))
    if OPTIONS.is_nacl_build():
      self.build(self._output_odex_file + '.ncval', 'run_ncval_test',
                 self._output_odex_file)

  def _install_odex_to_android_root(self, odex_path, archive_in_fs):
    """Installs the odex to the related path of corresponding jar or apk.

    If the apk (or jar) is installed to /dir/to/name.apk or /dir/to/name.jar,
    the corresponding oat file must be installed to /dir/to/$isa/name.odex

    Args:
      odex_src_path: odex file to be installed.
      archive_in_fs: Android filesystem path of the apk or jar.
    """
    dirname, basename = os.path.split(archive_in_fs)
    filename, extension = os.path.splitext(basename)
    assert extension in ['.apk', '.jar']
    super(JavaNinjaGenerator, self).install_to_root_dir(
        os.path.join(dirname, build_common.get_art_isa(),
                     filename + '.odex'),
        odex_path)

  def _build_test_list_for_apk(self, final_package_path):
    self._build_test_list(final_package_path,
                          rule='extract_test_list',
                          test_list_name=self._module_name,
                          implicit=['src/build/run_python',
                                    NinjaGenerator._EXTRACT_TEST_LIST_PATH])

  def get_included_module_names(self):
    module_names = []
    for dep in self._jar_files_to_extract:
      module_name = dep
      if os.path.sep in module_name:
        module_name = os.path.splitext(os.path.basename(module_name))[0]
      module_names.append(module_name)
    return module_names


class JarNinjaGenerator(JavaNinjaGenerator):
  def __init__(self, module_name, install_path=None, dex_preopt=True,
               canned_jar_dir=None, core_library=False, java_resource_dirs=None,
               java_resource_files=None, static_library=False,
               jar_packages=None, jarjar_rules=None, dx_flags=None,
               built_from_android_mk=False, **kwargs):
    # TODO(crbug.com/393099): Once all rules are generated via make_to_ninja,
    # |core_library| can be removed because |dx_flags| translated from
    # LOCAL_DX_FLAGS in Android.mk is automatically set to the right flag.
    super(JarNinjaGenerator, self).__init__(module_name,
                                            ninja_name=module_name + '_jar',
                                            **kwargs)
    assert (not static_library or not dex_preopt)
    assert (not core_library or not dx_flags), (
        'core_library and dx_flags can not be set simultaneously')
    self._install_path = install_path

    # TODO(crbug.com/390856): Remove |canned_jar_dir|.
    self._canned_jar_dir = canned_jar_dir
    self._output_pre_jarjar_jar = self._get_build_path(
        subpath='classes-full-debug.jar')
    self._output_classes_jar = self._get_build_path(subpath='classes.jar')
    self._output_javalib_jar = self._get_build_path(subpath='javalib.jar')
    self._output_javalib_noresources_jar = self._get_build_path(
        subpath='javalib_noresources.jar')
    if OPTIONS.enable_art_aot() and dex_preopt:
      assert install_path, 'Dex-preopt only makes sense for installed jar'
      self._dex_preopt = True
      self._output_odex_file = self._get_build_path(
          is_target=True,
          subpath='javalib.odex')
    else:
      self._dex_preopt = False
      self._output_odex_file = None

    self._is_core_library = core_library
    self._java_resource_dirs = [
        os.path.join(self._base_path, path)
        for path in build_common.as_list(java_resource_dirs)]
    self._java_resource_files = [
        os.path.join(self._base_path, path)
        for path in build_common.as_list(java_resource_files)]
    self._is_static_library = static_library

    self._jar_packages = jar_packages
    self._jar_stamp_file_dependencies = []

    # Note that the javalib.jar which has no dex really is not target
    # specific, but upstream Android build system puts it under target,
    # so we follow their example.
    self._output_jar = self._get_build_path(
        is_target=self._dex_preopt,
        subpath='javalib.jar')

    self._install_jar = None
    if self._install_path:
      self._install_jar = os.path.join(self._install_path,
                                       self._module_name + '.jar')

    self._jarjar_rules = jarjar_rules
    self._dx_flags = dx_flags
    self._built_from_android_mk = built_from_android_mk

  @staticmethod
  def emit_common_rules(n):
    n.variable('dx', toolchain.get_tool('java', 'dx'))
    n.variable('dxflags', '-JXms16M -JXmx1536M --dex')
    n.variable('jar', toolchain.get_tool('java', 'jar'))
    n.variable('jarjar', toolchain.get_tool('java', 'jarjar'))
    n.variable('java', toolchain.get_tool('java', 'java'))

    # ARC uses a system default cp command instead of 'acp' provided in
    # android/build/tools/acp/ to avoid an unnecessary tool build.
    n.rule('acp', 'mkdir -p $out_dir && cp -fp $in $out',
           description='mkdir -p $out_dir && cp -fp $in $out')
    n.rule('jar',
           '$jar -cf $out -C $in_class_path .',
           description='jar $out')
    n.rule('jar_update',
           '(cp $in $out && $jar -uf $out $jar_command) || (rm $out; exit 1)',
           description='jar_update $out')
    n.rule('jarjar',
           '$java -jar $jarjar process $rules $in $out',
           description='java -jar jarjar.jar process $rules $in $out')
    n.rule('unzip',
           'unzip -qou $in -d $out_dir && touch $out',
           description='unzip $in to $out_dir')
    n.rule('remove_non_matching_files',
           ('(set -f && find $in_dir -mindepth 1 -type d '
            '`for i in $match; do echo -not -path $in_dir/\\$$i; '
            'done` | xargs rm -rf && set +f && touch $out) || '
            '(rm $out; set +f; exit 1)'),
           description='removing files not matching $in_dir/$match')
    n.rule('dx',
           '$dx $dxflags --output=$out $in_path',
           description='dx $out')

  def _get_build_path(self, subpath=None, is_target=False):
    return build_common.get_build_path_for_jar(self._module_name,
                                               subpath=subpath,
                                               is_target=is_target)

  def _get_minimal_bootclasspath(self):
    """Provides a minimal bootclasspath for building these java files.

    The bootclasspath defines the core library and other required class
    files that every Java file will have access to.  Without providing
    a -bootclasspath option, the Java compiler would instead consult its
    built-in core libraries, whereas Android uses a separate Apache
    core library (as well as API frameworks, etc).  When compiling, every jar
    in the bootclasspath must be found and fully compiled (not being built
    in parallel).  This means that we need to set up implicit dependencies,
    and it also means that we must build the jars in the bootclasspath
    sequentially in the order of the bootclasspath.  The minimal
    bootclasspath is thus the entire bootclasspath when generating
    code for non-bootclasspath jars, or if generating for a bootclasspath
    jar, the bootclasspath up until that jar.
    """
    if self._built_from_android_mk:
      # Returns only core's classes.jar as the real Android build does.
      # This is calculated in android/build/core/base_rules.mk.
      core_libart = _BootclasspathComputer.get_classes()[0]
      assert core_libart == build_common.get_build_path_for_jar(
          'core-libart', subpath='classes.jar'), (
              'Expected core-libart at the front of the bootclass path, but '
              'found "%s" instead.' % core_libart)

      # On building core-libart, it should not depend on core-libart itself.
      return _truncate_list_at([core_libart], self._output_classes_jar)

    if self._module_name == 'framework':
      return _truncate_list_at(_BootclasspathComputer.get_classes(),
                               build_common.get_build_path_for_jar(
                                   'framework',
                                   subpath='classes.jar'))
    return _truncate_list_at(_BootclasspathComputer.get_classes(),
                             self._output_classes_jar)

  def _build_classes_jar(self):
    if self._canned_jar_dir:
      self.build(self._output_classes_jar, 'cp',
                 os.path.join(self._canned_jar_dir, 'classes.jar'))
      return
    variables = dict(in_class_path=self._get_compiled_class_path())
    implicit = self._javac_stamp_files
    implicit.extend(self._extract_jar_contents())
    if self._jar_packages:
      jar_packages_stamp_file = self._get_build_path(
          subpath=(self._get_source_files_hashcode() + '.jar_packages.stamp'))
      in_dir = self._get_build_path(subpath=self._get_source_files_hashcode())
      self.build(jar_packages_stamp_file, 'remove_non_matching_files',
                 implicit=implicit,
                 variables={'match': self._jar_packages,
                            'in_dir': in_dir})
      implicit.append(jar_packages_stamp_file)
    if self._jarjar_rules:
      self.build([self._output_classes_jar], 'jarjar',
                 inputs=[self._output_pre_jarjar_jar],
                 implicit=[self._jarjar_rules],
                 variables={'rules': self._jarjar_rules})
      output_classes_jar = self._output_pre_jarjar_jar
    else:
      output_classes_jar = self._output_classes_jar
    return self.build([output_classes_jar], 'jar',
                      implicit=implicit,
                      variables=variables)

  def _build_javalib_jar_from_classes_jar(self):
    variables = {'in_path': self._output_classes_jar}
    if self._is_core_library:
      variables['dxflags'] = '$dxflags --core-library'
    if self._use_multi_dex:
      variables['dxflags'] = '$dxflags --multi-dex'
    if self._dx_flags:
      variables['dxflags'] = '$dxflags ' + self._dx_flags
    if self._java_resource_dirs or self._java_resource_files:
      dx_out = [self._output_javalib_noresources_jar]
    else:
      dx_out = [self._output_javalib_jar]

    output = self.build(dx_out, 'dx',
                        implicit=[self._output_classes_jar],
                        variables=variables)

    if self._java_resource_dirs or self._java_resource_files:
      jar_command = ''
      # See android/build/core/base_rules.mk, LOCAL_JAVA_RESOURCE_DIRS.
      excludes = ['.svn', '.java', 'package.html', 'overview.html', '.swp',
                  '.DS_Store', '~']
      # Exclude ARC specific files, too.
      excludes.extend(['OWNERS', 'README.txt'])
      staging_root = build_common.get_staging_root()
      for d in self._java_resource_dirs:
        # Resource directories that are generated via make_to_ninja point to
        # staging directories.
        resources = build_common.find_all_files(
            d, exclude=excludes,
            use_staging=not d.startswith(staging_root))
        for r in resources:
          rel_path = os.path.relpath(r, d)
          jar_command += ' -C %s %s' % (staging.as_staging(d), rel_path)
      for f in self._java_resource_files:
        path, filename = os.path.split(f)
        jar_command += ' -C %s %s' % (staging.as_staging(path), filename)
      assert jar_command
      output = self.build([self._output_javalib_jar], 'jar_update',
                          dx_out,
                          variables={'jar_command': jar_command})
    return output

  def _build_javalib_jar(self):
    if self._canned_jar_dir:
      return self.build(self._output_javalib_jar, 'cp',
                        os.path.join(self._canned_jar_dir, 'javalib.jar'))
    if self._is_static_library:
      return self.build(self._output_javalib_jar, 'cp',
                        self._output_classes_jar)

    return self._build_javalib_jar_from_classes_jar()

  @staticmethod
  def get_javalib_jar_path(module_name):
    # javalib.jar is created by |archive()|
    return os.path.join(build_common.get_build_path_for_jar(module_name),
                        'javalib.jar')

  def archive(self):
    """Builds JAR, dex code, and optional odex and classes jar."""
    classes = self._build_classes_jar()
    self._build_javalib_jar()
    if self._dex_preopt:
      self._dex2oat(self._install_jar, self._output_javalib_jar,
                    self._output_jar)
    return classes

  def install(self):
    """Installs the archive/output jar to its install location."""
    super(JarNinjaGenerator, self).install_to_root_dir(self._install_jar,
                                                       self._output_jar)
    if self._dex_preopt:
      self._install_odex_to_android_root(self._output_odex_file,
                                         self._install_jar)
    return self

  def build_test_list(self):
    return self._build_test_list_for_apk(
        JarNinjaGenerator.get_javalib_jar_path(self._module_name))


class ApkFromSdkNinjaGenerator(NinjaGenerator):
  """Builds an APK using the Android SDK directly."""

  def __init__(self, module_name, base_path=None, install_path=None,
               use_ndk=False, use_clang=False, use_gtest=False, **kwargs):
    super(ApkFromSdkNinjaGenerator, self).__init__(
        module_name,
        ninja_name=module_name + '_apk',
        base_path=base_path,
        **kwargs)
    if install_path is None:
      install_path = \
          ApkFromSdkNinjaGenerator.get_install_path_for_module(module_name)
    self._install_path = install_path
    self._use_ndk = use_ndk
    self._use_clang = use_clang

    # If use_gtest is set, some dependencies to use gtest are automatically
    # added to the build. See also build_default_all_sources() below.
    self._use_gtest = use_gtest

  @staticmethod
  def get_install_path_for_module(module_name):
    # Get the installation path, which will always be non-target specific
    # because even if there is NDK, we build all NDK targets.
    return os.path.join(build_common.get_build_path_for_apk(
        module_name), module_name + '.apk')

  @staticmethod
  def emit_common_rules(n):
    dbg = '' if OPTIONS.disable_debug_code() else '--debug'
    n.rule('build_using_sdk',
           ('src/build/run_python %s --build_path=$build_path --apk=$out %s ' +
            '--source_path=$source_path $args > $log 2>&1 || ' +
            '(cat $log; exit 1)') % ('src/build/build_using_sdk.py', dbg),
           description='build_using_sdk.py $out')

    n.rule('extract_google_test_list',
           ('src/build/run_python %s --language=c++ $in > $out.tmp && '
            'mv $out.tmp $out' %
            build_common.get_extract_google_test_list_path()),
           description='Extract googletest style test methods from $in')

  def build_default_all_sources(self, implicit=None):
    files = self.find_all_contained_files(None, include_tests=True)
    build_path = os.path.dirname(self._install_path)
    build_script = os.path.join(build_common.get_arc_root(),
                                'src', 'build', 'build_using_sdk.py')
    implicit = build_common.as_list(implicit)
    implicit += map(staging.third_party_to_staging,
                    build_common.get_android_sdk_ndk_dependencies())
    implicit += [build_script]

    if self._use_gtest:
      # Add dependency to googletest library.
      gtest_dependencies = [
          'android/external/chromium_org/testing/gtest/Android.mk']
      gtest_dependencies.extend(build_common.find_all_files(
          base_paths=['android/external/chromium_org/testing/gtest/include',
                      'android/external/chromium_org/testing/gtest/src'],
          include_tests=True))

      # Add src/integration_tests/common, which include an adapter code to
      # use gtest via ATF.
      gtest_dependencies.extend(build_common.find_all_files(
          base_paths=['src/integration_tests/common'],
          include_tests=True))

      # Implicit path must be staging paths relative to the ARC root.
      implicit.extend(staging.as_staging(path) for path in gtest_dependencies)

    args = ''
    if self._use_ndk:
      args = '--use_ndk'
    if self._use_clang:
      args += ' --use_clang'

    variables = {
        'build_path': build_path,
        'log': os.path.join(build_path, 'build.log'),
        'source_path': staging.as_staging(self.get_base_path()),
        'args': args
    }
    return self.build([self._install_path], 'build_using_sdk', inputs=files,
                      variables=variables, implicit=implicit)

  def build_test_list(self):
    return self._build_test_list(
        ApkFromSdkNinjaGenerator.get_final_package_for_apk(self._module_name),
        rule='extract_test_list',
        test_list_name=self._module_name,
        implicit=['src/build/run_python',
                  NinjaGenerator._EXTRACT_TEST_LIST_PATH])

  @staticmethod
  def get_final_package_for_apk(apk_name):
    return build_common.get_build_path_for_apk(
        apk_name, subpath=apk_name + '.apk')

  def build_google_test_list(self, sources=None):
    if sources is None:
      sources = self.find_all_contained_files('_test.cc', include_tests=True)
    self._build_test_list(
        sources,
        rule='extract_google_test_list',
        test_list_name=self._module_name,
        implicit=[build_common.get_extract_google_test_list_path()])


class ApkNinjaGenerator(JavaNinjaGenerator):
  def __init__(self, module_name, base_path=None, source_subdirectories=None,
               install_path=None, canned_classes_apk=None, install_lazily=False,
               resource_subdirectories=None, **kwargs):
    # Set the most common defaults for APKs.
    if source_subdirectories is None:
      source_subdirectories = ['src']

    if resource_subdirectories is None:
      if os.path.exists(
          staging.as_staging(os.path.join(base_path or '', 'res'))):
        resource_subdirectories = ['res']

    super(ApkNinjaGenerator, self).__init__(
        module_name,
        ninja_name=module_name + '_apk',
        base_path=base_path,
        source_subdirectories=source_subdirectories,
        resource_subdirectories=resource_subdirectories,
        **kwargs)

    self._install_path = install_path

    self._aapt_input_path = self._get_build_path(subpath='apk')
    self._output_classes_dex = os.path.join(self._aapt_input_path,
                                            'classes.dex')
    if self._install_path:
      self._apk_install_path = os.path.join(self._install_path,
                                            self._module_name + '.apk')
    else:
      self._apk_install_path = None

    self._dex_preopt = OPTIONS.enable_art_aot() and install_path is not None
    if self._dex_preopt:
      self._output_odex_file = self._get_build_path(
          subpath='package.odex', is_target=True)

    self._canned_classes_apk = canned_classes_apk
    self._install_lazily = install_lazily

  @staticmethod
  def emit_common_rules(n):
    n.rule('zipalign',
           toolchain.get_tool('java', 'zipalign') + ' -f 4 $in $out',
           description='zipalign $out')

  def _get_build_path(self, subpath=None, is_target=False):
    return self._get_package_build_path(subpath, is_target)

  @staticmethod
  def get_final_package_for_apk(module_name, dex_preopt=False):
    # Note that the dex-preopt'ed package.apk without classes.dex is
    # technically not target specific, but upstream Android build
    # system puts it under target, so we follow their example.
    return build_common.get_build_path_for_apk(
        module_name,
        is_target=dex_preopt,
        subpath='package.apk')

  def get_final_package(self):
    return ApkNinjaGenerator.get_final_package_for_apk(self._module_name,
                                                       self._dex_preopt)

  def add_resource_paths(self, paths):
    self._resource_paths += paths

  def _build_classes_dex_from_class_files(self, outputs):
    stamp_files = self._extract_jar_contents()
    variables = dict(in_path=self._get_compiled_class_path())
    return self.build(outputs, 'dx',
                      implicit=self._javac_stamp_files + stamp_files,
                      variables=variables)

  def add_apk_dep(self, n):
    """Indicate that the generated APK depends on the given APK.

    This is primarily for use in building Test APKs.  Calling this
    makes every class in the APK in |n| accessible to every class in the
    APK we are generating.  We implement this by augmenting the
    generated APK's classpath and creating implicit dependencies on
    all the dependent APKs.
    """
    assert isinstance(n, ApkNinjaGenerator)
    module_name = n._module_name
    self._javac_classpath_dirs.append(
        JavaNinjaGenerator.get_compiled_class_path_for_module(module_name))
    self._implicit.append(
        ApkNinjaGenerator.get_final_package_for_apk(
            module_name, dex_preopt=n._dex_preopt))

  def _get_minimal_bootclasspath(self):
    """Provides a minimal bootclasspath for building these java files.

    The bootclasspath defines the core library and other required class
    files that every Java file will have access to.  Without providing
    a -bootclasspath option, the Java compiler would instead consult its
    built-in core libraries, whereas Android uses a separate Apache
    core library (as well as API frameworks, etc).  We prevent APKs from
    accessing jars they should not need (such as service related jars)
    by not including any jars that appear after framework in the
    bootclasspath list.

    Currently APKs are being compiled using our custom built jars which
    contain many internal classes. In the future we could create a jar
    that contains only stubs for a stricter subset of classes that should
    be accessible to APKs (like the Android SDK does with android.jar).
    """
    return _truncate_list_at(
        _BootclasspathComputer.get_classes(),
        build_common.get_build_path_for_jar('framework',
                                            subpath='classes.jar'),
        is_inclusive=True)

  def _build_and_add_all_generated_sources(self, implicit=None):
    super(ApkNinjaGenerator, self)._build_and_add_all_generated_sources()
    if implicit is None:
      implicit = []
    self.build_and_add_resources(implicit=implicit)

  def _build_zipalign(self, aligned_apk, unaligned_apk):
    return self.build(aligned_apk, 'zipalign', unaligned_apk)

  def _build_classes_apk(self, output_apk):
    """Builds the .apk file from the .class files, and optionally installs it
    to the target root/app subdirectory."""
    self._build_classes_dex_from_class_files(outputs=[self._output_classes_dex])

    # Bundle up everything as an unsigned/unpredexopted/unaligned .apk
    self._build_aapt(output_apk=output_apk,
                     implicit=[self._output_classes_dex],
                     input_path=self._aapt_input_path)
    return self

  def package(self):
    original_apk = self._get_build_path(subpath='package.apk.original')
    # Unaligned APK.  In case of pre-dexopt, it ends up with no .dex, too.
    unaligned_apk = self._get_build_path(subpath='package.apk.unaligned')

    # Build the apk, or use the canned one.
    if self._canned_classes_apk:
      self.build(original_apk, 'cp', self._canned_classes_apk)
    else:
      self._build_classes_apk(original_apk)

    # Optionally pre-dexopt the apk.  Will remove *.dex from the apk.
    if self._dex_preopt:
      self._dex2oat(self._apk_install_path, original_apk, unaligned_apk,
                    self._extra_dex2oat_flags)
    else:
      self.build(unaligned_apk, 'cp', original_apk)

    # Finally, optimize the .apk layout to avoid memory copy.  See also
    # ensureAlighment in frameworks/base/libs/androidfw/Asset.cpp.
    self._build_zipalign(self.get_final_package(), unaligned_apk)
    return self.get_final_package()

  def install(self):
    super(ApkNinjaGenerator, self).install_to_root_dir(self._apk_install_path,
                                                       self.get_final_package())
    if self._dex_preopt:
      self._install_odex_to_android_root(self._output_odex_file,
                                         self._apk_install_path)

    if self._install_lazily:
      # To retrieve intent-filter and provider in bootstrap, copy
      # AndroidManifest.xml as <module name>.xml.
      manifest_path = staging.as_staging(
          os.path.join(self._base_path, 'AndroidManifest.xml'))
      install_manifest_path = os.path.join(self._install_path,
                                           '%s.xml' % self._module_name)
      super(ApkNinjaGenerator, self).install_to_root_dir(
          install_manifest_path, manifest_path)
    return self


class AtfNinjaGenerator(ApkNinjaGenerator):
  def __init__(self, module_name, **kwargs):
    super(AtfNinjaGenerator, self).__init__(module_name, **kwargs)
    self.add_built_jars_to_classpath('android.test.runner')

  @staticmethod
  def emit_common_rules(n):
    n.rule('strip_apk_signature',
           'cp $in $out && zip -q -d $out META-INF/*',
           description='strip_apk_signature $out')

  def build_default_all_test_sources(self):
    return self.build_default_all_sources(include_tests=True)

  def build_test_list(self):
    return self._build_test_list_for_apk(self.get_final_package())


class AaptNinjaGenerator(NinjaGenerator):
  """Implements a simple aapt package generator."""

  def __init__(self, module_name, base_path, manifest, intermediates,
               install_path=None, **kwargs):
    super(AaptNinjaGenerator, self).__init__(
        module_name, base_path=base_path, **kwargs)
    self._manifest = manifest
    self._intermediates = intermediates
    self._install_path = install_path
    self._resource_paths = []
    self._assets_path = None

  def add_resource_paths(self, paths):
    self._resource_paths += paths

  def add_aapt_flag(self, value):
    self.add_flags('aaptflags', value)

  def get_resource_generated_path(self):
    return build_common.get_build_path_for_apk(self._module_name,
                                               subpath='R')

  def package(self, **kwargs):
    basename_apk = self._module_name + '.apk'
    resource_generated = self.get_resource_generated_path()

    extra_flags = ''
    implicit_depends = []

    if not self._resource_paths:
      path = os.path.join(self._base_path, 'res')
      if os.path.exists(path):
        self._resource_paths = [path]
    self.add_notice_sources([os.path.join(p, 'file')
                             for p in self._resource_paths])
    for path in self._resource_paths:
      extra_flags += ' -S ' + path
      implicit_depends += build_common.find_all_files(
          [path], use_staging=False, include_tests=True)

    if not self._assets_path:
      path = os.path.join(self._base_path, 'assets')
      if os.path.exists(path):
        self._assets_path = path
    if self._assets_path:
      extra_flags += ' -A ' + self._assets_path
      implicit_depends += build_common.find_all_files(
          [self._assets_path], use_staging=False, include_tests=True)

    apk_path = os.path.join(resource_generated, basename_apk)
    apk_path_unaligned = apk_path + '.unaligned'
    # -z requires localization.
    # -u forces aapt to update apk file, otherwise the file may not be touched.
    extra_flags += ' -z -u -F ' + apk_path_unaligned
    extra_flags += ' -J ' + resource_generated

    result_files = map(lambda x: os.path.join(resource_generated, x),
                       self._intermediates)
    result_files += [apk_path_unaligned]

    manifest = staging.as_staging(os.path.join(self._base_path, self._manifest))
    implicit_depends.append(manifest)
    self.build(
        result_files, 'aapt_package', [],
        variables={'aaptflags': '$aaptflags ' + extra_flags,
                   'manifest': manifest,
                   'tmpfile': os.path.join(resource_generated, 'errors')},
        implicit=implicit_depends)

    # Align for faster mmap.
    self.build(apk_path, 'zipalign', apk_path_unaligned)

    if self._install_path is not None:
      relpath = os.path.join(self._install_path, basename_apk)
      self.install_to_root_dir(relpath, apk_path)
    return apk_path


class PythonTestNinjaGenerator(NinjaGenerator):
  """Implements a python unittest runner generator."""

  # ARC has its main package of Python code here.
  _ARC_PYTHON_PATH = 'src/build'

  @staticmethod
  def emit_common_rules(n):
    # We run the test using the -m option to get consistent behavior with
    # imports. If we ran it with "python $in", the path to the file would be
    # automatically added to sys.path, when normally that path may not be in it.
    n.rule('run_python_test',
           ('src/build/run_python -m unittest discover'
            ' --verbose $test_path $test_name $base_run_path ' +
            build_common.get_test_output_handler()),
           description='run_python_test $in')

  def run(self, python_test, implicit=None):
    """Runs a single Python test.

    The Python module dependencies of the test are discovered automatically (at
    configure time) by examining the tree of imports it makes.

    Args:
        python_test: The path to the test file, such as
            'src/build/util/some_util_test.py'.
        implicit: An additional list of implicit dependencies for this test, so
            that it is run if any of them are changed.
    """

    # Get the list of Python files that are imported, excluding files from
    # outside the ARC directories.
    python_dependencies = python_deps.find_deps(python_test)

    # The Python test file is included in the returned list. Remove it since we
    # are interested in the implicit dependencies, and the test is an
    # explicit dependency.
    python_dependencies.remove(python_test)

    # Add the discovered python dependencies to the list of dependencies.
    implicit = (build_common.as_list(implicit) + python_dependencies +
                ['src/build/run_python'])

    # Generate an output file that holds the results (and so it can be updated
    # by the build system when dirty).
    results_file = os.path.join(
        build_common.get_target_common_dir(), 'test_results',
        self._ninja_name + '.results')

    # To run the test cleanly, we have to specify the base run path, as well as
    # the relative name of the module in that path. For ARC, any test under
    # _ARC_PYTHON_PATH is treated as part of the main python package rooted
    # there. Otherwise we treat files outside that path as a local package
    # rooted at the containing directory.
    if python_test.startswith(PythonTestNinjaGenerator._ARC_PYTHON_PATH + '/'):
      base_run_path = PythonTestNinjaGenerator._ARC_PYTHON_PATH
    else:
      base_run_path = os.path.dirname(python_test)

    test_path, test_name = os.path.split(python_test)
    variables = {'base_run_path': base_run_path, 'test_name': test_name,
                 'test_path': test_path}

    # Write out the build rule.
    return self.build(
        results_file, 'run_python_test', inputs=python_test,
        implicit=sorted(implicit), variables=variables, use_staging=False)


class NaClizeNinjaGenerator(NinjaGenerator):
  """NaClize *.S files and write them as <module_name>_gen_sources/*.S"""

  _SCRIPT_PATH = staging.as_staging('src/build/naclize_i686.py')

  def __init__(self, base_name, **kwargs):
    assert OPTIONS.is_nacl_i686()
    super(NaClizeNinjaGenerator, self).__init__(
        base_name + '_gen_i686_asm_sources', **kwargs)
    self._base_name = base_name

  def generate(self, asm_files):
    source_dir = NaClizeNinjaGenerator.get_gen_source_dir(self._base_name)
    generated_file_list = []
    for f in asm_files:
      output = os.path.join(source_dir, os.path.basename(f))
      self.build([output], 'naclize_i686', staging.as_staging(f),
                 implicit=[NaClizeNinjaGenerator._SCRIPT_PATH])
      generated_file_list.append(output)

    self.build(NaClizeNinjaGenerator.get_gen_source_stamp(self._base_name),
               'touch', implicit=generated_file_list)
    return generated_file_list

  @staticmethod
  def get_gen_source_dir(base_name):
    return os.path.join(build_common.get_build_dir(),
                        base_name + '_gen_sources')

  @staticmethod
  def get_gen_source_stamp(base_name):
    # We create this file after all assembly files are generated. We can save
    # the size of a ninja file by depending on this stamp file instead of all
    # generated assembly files. Without this proxy file, the ninja file will be
    # increased. In case of libc_common.a, it is about 3 times bigger.
    return os.path.join(
        NaClizeNinjaGenerator.get_gen_source_dir(base_name), 'STAMP')

  @staticmethod
  def emit_common_rules(n):
    n.rule('naclize_i686',
           command=(
               'src/build/run_python %s $in > $out' %
               NaClizeNinjaGenerator._SCRIPT_PATH),
           description='naclize_i686 $out')


class JavaScriptNinjaGenerator(NinjaGenerator):
  """Runs closure compiler to minify the javascript files."""

  _SCRIPT_PATH = 'src/build/minify_js.py'
  _COMPILER_JAR = staging.as_staging('closure_compiler/compiler.jar')

  @staticmethod
  def emit_common_rules(n):
    # Minify and create source mappings for the js files to save loading time.
    n.rule('minify_js',
           command=('%s --java-path %s --out $out_min_js --out-map $out_map $in'
                    % (JavaScriptNinjaGenerator._SCRIPT_PATH,
                       toolchain.get_tool('java', 'java'))),
           description='minify_js $in')

  def minify(self, sources, out_min_js):
    out_map = '%s.map' % out_min_js
    self.build([out_min_js, out_map], 'minify_js', sources,
               implicit=[JavaScriptNinjaGenerator._SCRIPT_PATH,
                         JavaScriptNinjaGenerator._COMPILER_JAR],
               variables={'out_min_js': out_min_js, 'out_map': out_map})


def _generate_python_test_ninja_for_test(python_test, implicit_map):
  PythonTestNinjaGenerator(python_test).run(
      python_test, implicit_map.get(python_test, []))


def generate_python_test_ninjas_for_path(base_path, exclude=None,
                                         implicit_map=None):
  """Generates ninja files for all Python tests found under the indicated path.

  The Python module dependencies of each test are discovered automatically (at
  configure time) by examining the tree of imports it makes.

  Args:
      base_path: The base path to find all Python tests under.
      exclude: (Optional) A list of files to exclude.
      implicit_map: (Optional) A mapping of test paths to extra dependencies for
          that test.
  """
  implicit_map = build_common.as_dict(implicit_map)
  python_tests = build_common.find_all_files(
      base_path, suffixes='_test.py', include_tests=True, exclude=exclude,
      use_staging=False)
  ninja_generator_runner.request_run_in_parallel(
      *[(_generate_python_test_ninja_for_test, python_test, implicit_map)
        for python_test in python_tests])


class JavaScriptTestNinjaGenerator(JavaScriptNinjaGenerator):
  _TEST_DEPENDENCIES = [
      'testing/chrome_test/chrome_test.js',
      build_common.get_generated_metadata_js_file(),
      'src/packaging/runtime/common.js',
      'src/packaging/runtime/promise_wrap.js',
      'src/packaging/runtime/tests/test_base.js',
  ]

  def __init__(self, test_name, **kwargs):
    super(JavaScriptTestNinjaGenerator, self).__init__(
        'test_template_' + test_name, **kwargs)
    self._test_name = test_name
    self._test_files = JavaScriptTestNinjaGenerator._TEST_DEPENDENCIES[:]

  def _generate_test_runner_html(self, out_path, script_src):
    self.build(
        out_path,
        'generate_from_template',
        'src/packaging/test_template/test_runner.html',
        variables={
            'keyvalues': pipes.quote('script_src=%s' % script_src)
        },
        implicit=[NinjaGenerator._GENERATE_FILE_FROM_TEMPLATE_PATH])

  def add_test_files_in_directory(self, tests_directory):
    test_js_files = build_common.find_all_files(
        tests_directory, suffixes=['.js'], include_tests=True)
    self.add_test_files(test_js_files)

  def add_test_files(self, files):
    for f in files:
      if f in self._test_files:
        continue
      self._test_files.append(f)

  def generate_test_template(self):
    out_dir = build_common.get_build_path_for_gen_test_template(self._test_name)

    gen_min_js = os.path.join(out_dir, 'gen_test.min.js')
    # Note: This creates mapping file under out directory, too.
    self.minify(self._test_files, gen_min_js)

    # Generate main HTML page for test runner.
    generated_test_runner = os.path.join(out_dir, 'test_runner.html')
    self._generate_test_runner_html(generated_test_runner,
                                    os.path.basename(gen_min_js))

    # Copy needed files to |out_dir|.
    resources = build_common.find_all_files('src/packaging/test_template',
                                            exclude=['test_runner.html'])
    resources.extend(['src/packaging/app_template/manifest.json',
                      'src/packaging/app_template/icon.png'])
    copied_files = []
    for path in resources:
      out_file = os.path.join(out_dir, os.path.basename(path))
      self.build(out_file, 'cp', path)
      copied_files.append(out_file)

    self.build(os.path.join(out_dir, '_locales'), 'mkdir_empty')
    messages_json = os.path.join(out_dir, '_locales', 'messages.json')
    self.build(messages_json, 'cp',
               'src/packaging/app_template/_locales/messages.json')
    self.build(os.path.join(out_dir, 'BUILD_STAMP'), 'touch',
               implicit=([generated_test_runner, gen_min_js, messages_json] +
                         copied_files))

    # Build a test name list.
    self._build_test_list(
        self._test_files,
        'gen_js_test_list',
        test_list_name='test_template_' + self._test_name,
        implicit=[build_common.get_extract_google_test_list_path()])

  @staticmethod
  def emit_common_rules(n):
    n.rule(
        'gen_js_test_list',
        command=('src/build/run_python %s --language=javascript $in > $out.tmp '
                 '&& mv $out.tmp $out' %
                 build_common.get_extract_google_test_list_path()),
        description='Generate JavaScript test method list')


def build_default(n, root, files, **kwargs):
  build_out = []
  for one_file in files:
    path = one_file
    if root is not None:
      path = os.path.join(root, one_file)
    if one_file.endswith('.c'):
      build_out += n.cc(path, **kwargs)
    elif one_file.endswith('.cc') or one_file.endswith('.cpp'):
      build_out += n.cxx(path, **kwargs)
    elif one_file.endswith('.S'):
      build_out += n.asm_with_preprocessing(path, **kwargs)
    elif one_file.endswith('.s'):
      build_out += n.asm(path, **kwargs)
    else:
      raise Exception('No default rule for file ' + one_file)
  return build_out


def get_optimization_cflags():
  # These flags come from $ANDROID/build/core/combo/TARGET_linux-x86.mk.
  # Removed -ffunction-sections for working around crbug.com/231034. Also
  # removed -finline-limit=300 to fix crbug.com/243405.
  #
  # We also removed -fno-inline-functions-called-once as this was not
  # giving any value for ARC. There were no performance/binary size
  # regressions by removing this flag.
  return ['-O2']


def get_gcc_optimization_cflags():
  # Clang does not support them so they are GCC only.
  return ['-finline-functions', '-funswitch-loops']


# TODO(crbug.com/177699): Remove ignore_dependency option (we never
# should ignore dependencies) as part of dynamically generating
# the regen rules.
def open_dependency(path, access, ignore_dependency=False):
  """Open a file that configure depends on to generate build rules.

  Any file that we depend on to generate rules needs to be listed as
  a dependency for rerunning configure.  Set ignore_dependency to
  true if there are a bunch of files that are being added as
  dependencies which we do not yet reflect in
  TopLevelNinjaGenerator._regen_{input,output}_dependencies.
  """
  if not ignore_dependency:
    if 'w' in access:
      RegenDependencyComputer.verify_is_output_dependency(path)
    else:
      RegenDependencyComputer.verify_is_input_dependency(path)
  return open(path, access)


def _compute_hash_fingerprint(input):
  return hashlib.sha256(input).hexdigest()[0:8]


# TODO(kmixter): This function is used far too much with
# ignore_dependency=True.  Every path passed here should technically be
# listed as a regen dependency of configure.py. Currently we are using
# this function to parse every single eventlogtag, aidl, and
# AndroidManifest.xml file for package paths to determine file names.
# In many cases these package names are just used for generated file
# paths which do not really need to match package paths.  Fix this.
def _extract_pattern_from_file(path, pattern, ignore_dependency=False):
  """Given a path to a file, and a pattern, extract the string matched by the
  pattern from the file. Useful to grab a little bit of data from a file
  without writing a custom parser for that file type."""
  with open_dependency(path, 'r', ignore_dependency) as f:
    try:
      return re.search(pattern, f.read()).groups(1)[0]
    except Exception:
      raise Exception('Error matching pattern "%s" in "%s"' % (
          pattern, path))


def _truncate_list_at(my_list, my_terminator, is_inclusive=False):
  if my_terminator not in my_list:
    return my_list
  addend = 0
  if is_inclusive:
    addend = 1
  return my_list[:my_list.index(my_terminator) + addend]


def get_bootclasspath():
  return _BootclasspathComputer.get_string()
