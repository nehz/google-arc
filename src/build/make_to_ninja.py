# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Converts Android.mk files into ninja files

# TODO(igorc): Support codegen rules. Perhaps needs a rework to parse resulting
# commands rather than dumping variable names.

import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile

import build_common
import dependency_inspection
import ninja_generator
import staging
import toolchain
from build_common import StampFile
from build_options import OPTIONS
from ninja_generator import AaptNinjaGenerator
from ninja_generator import ArchiveNinjaGenerator
from ninja_generator import ExecNinjaGenerator
from ninja_generator import JarNinjaGenerator
from ninja_generator import NinjaGenerator
from ninja_generator import SharedObjectNinjaGenerator
from ninja_generator import TestNinjaGenerator
from util import file_util


# The directory inside Android build/ where all shared scripts reside.
_CORE_DIRNAME = 'core'

BUILD_TYPE_HOST_DALVIK_JAVA_LIBRARY = 'host_dalvik_java_library'
BUILD_TYPE_HOST_SHARED = 'host_shared_library'
BUILD_TYPE_HOST_STATIC = 'host_static_library'
BUILD_TYPE_HOST_EXECUTABLE = 'host_executable'
BUILD_TYPE_JAVA_LIBRARY = 'java_library'
BUILD_TYPE_PACKAGE = 'package'
BUILD_TYPE_TARGET_SHARED = 'shared_library'
BUILD_TYPE_TARGET_STATIC = 'static_library'
BUILD_TYPE_TARGET_EXECUTABLE = 'executable'
BUILD_TYPE_TARGET_TEST_EXECUTABLE = 'test_executable'
BUILD_TYPE_NOTICES_SHARED = 'shared_notices'
BUILD_TYPE_NOTICES_STATIC = 'static_notices'
BUILD_TYPE_PREBUILT = 'prebuilt'

_ARC_ROOT = os.path.abspath('.')

_MAKE_TO_NINJA_SUBDIR = os.path.join(build_common.get_target_common_dir(),
                                     'make_to_ninja')
_MAKE_TO_NINJA_DIR = os.path.join(_ARC_ROOT, _MAKE_TO_NINJA_SUBDIR)
_MAKE_TO_NINJA_BIN_DIR = os.path.join(_MAKE_TO_NINJA_DIR, 'bin')
_MAKE_BUILD_DIR = os.path.join(_MAKE_TO_NINJA_DIR, 'build')

_ANDROID_TARGET_GEN_SOURCES_DIR = os.path.join(
    build_common.get_target_common_dir(), 'android_gen_sources')
_ANDROID_HOST_GEN_SOURCES_DIR = os.path.join(
    build_common.get_host_common_dir(), 'android_gen_sources')
_INTERMEDIATE_HEADERS_DIR = os.path.join(build_common.get_target_common_dir(),
                                         'intermediate_headers')

_CANNED_GEN_SOURCES_TAR = os.path.join(
    'canned', 'target', 'android', 'generated', 'gen_sources.tar.gz')

_VARS_PREFIX = '=== VARIABLES FOR: '
_VAR_PREFIX = '=== VARIABLE '
_READING_MAKEFILE_RE = re.compile('Reading makefile `([^\']+)\'')

_TARGET_MAKEFILE = 'TARGET_MAKEFILE'

# Android build system (make) will use default behavior (empty values)
# when variables are not set. We are enabling those as warnings and turning
# them into script errors. This allows us to produce warnings when new unknown
# variables are touched.

# Provide default empty values for variables that are not set explicitly.
# We do not define all the variables and functions required to evaluate
# all Android.mk files as it's the default and it does not seem to affect
# the correctness of the variables we care about. Here we whitelist
# a set of variables and functions that appear to be OK to referenced
# in Android.mk files without being defined.
#
# TODO(crbug.com/442224): Do not centralize too much value names to the
# whitelist |_DEFAULT_VARS|. If an empty value is only for a few components,
# |extra_env_vars| may be the solution.
#
# Use _IGNORED_VAR_PREFIXES, _IGNORED_VARS for those that do not need
# to be defined.
_DEFAULT_VARS = [
    '2ND_HOST_TOOLCHAIN_PREFIX',
    '_include_stack',  # for _import_node
    'ADDITIONAL_BUILD_PROPERTIES',
    'ALL_PRODUCTS',
    'all_res_assets',
    'ALTERNATE_JAVAC',
    'ANDROID_BUILD_FROM_SOURCE',
    'ANDROID_BUILD_PATHS',
    'ARCH_ARM_HAVE_32_BYTE_CACHE_LINES',  # for arm
    'ARCH_ARM_HAVE_TLS_REGISTER',
    'ARCH_ARM_USE_NON_NEON_MEMCPY',  # for arm
    'ARCH_X86_HAVE_SSE2',  # for art
    'ARCH_X86_HAVE_SSE3',  # for art
    'ARCH_X86_HAVE_SSSE3',
    'ARCH_X86_HAVE_SSE4',
    'ARCH_X86_HAVE_SSE4_1',
    'ARCH_X86_HAVE_SSE4_2',
    'ARCH_X86_HAVE_AVX',
    'ARCH_X86_HAVE_AES_NI',
    'ART_BUILD_HOST',  # for art
    'ART_BUILD_TARGET',  # for art
    'ART_CPP_EXTENSION',  # for art
    'art_dont_bother',  # for art
    'ART_HOST_CLANG',  # for art
    'ART_HOST_GTEST_EXECUTABLES',  # for art
    'ART_TARGET_CFLAGS_x86',  # for art
    'ART_TARGET_CLANG',  # for art
    'ART_TARGET_CLANG_',  # for art
    'ART_TARGET_GTEST_EXECUTABLES',  # for art
    'ART_TEST_TARGET_RUN_TEST_OPTIMIZING_NO_PREBUILD32_RULES',
    'ART_TEST_TARGET_RUN_TEST_OPTIMIZING_PREBUILD32_RULES',
    'ART_TEST_HOST_RUN_TEST_OPTIMIZING_NO_PREBUILD32_RULES',
    'ART_TEST_HOST_RUN_TEST_OPTIMIZING_PREBUILD32_RULES',
    'ART_TEST_HOST_RUN_TEST_OPTIMIZING_NO_PREBUILD64_RULES',
    'ART_TEST_HOST_RUN_TEST_OPTIMIZING_PREBUILD64_RULES',
    'ART_USE_HSPACE_COMPACT',  # for art
    'ART_USE_PORTABLE_COMPILER',  # for art
    'ART_SEA_IR_MODE',  # for art
    'BOARD_CUSTOM_MKBOOTIMG',
    'BOARD_MALLOC_ALIGNMENT',  # for arm
    'BUILD_ARM_FOR_X86',
    'BUILD_ENV_SEQUENCE_NUMBER',
    'BUILD_EXECUTABLE_SUFFIX',
    'BUILD_FDO_INSTRUMENT',  # for arm
    'BUILD_FDO_OPTIMIZE',
    'build_host',
    'BUILD_HOST_64bit',
    'BUILD_HOST_DALVIK_JAVA_LIBRARY',  # for art
    'BUILD_HOST_static',
    'BUILD_TINY_ANDROID',  # for no-elf-hash-table-library.so
    'CALLED_FROM_SETUP',
    'CLANG_CONFIG_x86_64_EXTRA_CPPFLAGS',
    'CLANG_CONFIG_x86_EXTRA_CPPFLAGS',
    'clcore_LLVM_LD',
    'common_ASFLAGS',  # for libpng
    'common_c_includes',
    'common_cflags',
    'common_cflags_host',
    'common_conlyflags',
    'common_conlyflags_host',
    'common_conlyflags_target',
    'common_cppflags',
    'common_SHARED_LIBRARIES',
    'core_cflags',
    'core_cppflags',
    'CUSTOM_JAVA_COMPILER',
    'CUSTOM_KERNEL_HEADERS',
    'CUSTOM_LOCALES',
    'DALVIKVM_FLAGS',  # for art
    'DEBUG_BIONIC_LIBC',
    'DEBUG_DALVIK_VM',
    'DEBUG_V8',
    'DEFAULT_APP_TARGET_SDK',
    'DEFAULT_DEX_PREOPT_BUILT_IMAGE',  # for art
    'DEFAULT_DEX_PREOPT_BUILT_IMAGE_FILENAME',  # for art
    'DEFAULT_DEX_PREOPT_IMAGE',  # for art
    'DEFAULT_DEX_PREOPT_INSTALLED_IMAGE',  # for art
    'DEFAULT_GOAL',
    'DEX2OAT_IMAGE_XMS',  # for art
    'DEX2OAT_IMAGE_XMX',  # for art
    'DEX2OAT_TARGET_ARCH',  # for art
    'DEX2OAT_XMS',  # for art
    'DEX2OAT_XMX',  # for art
    'DEX2OATD_DEPENDENCY',  # for art
    'DEXPREOPT_BOOT_JAR_DIR',  # for art
    'DEXPREOPT_BOOT_JARS',  # for art
    'DIST_DIR',
    'DONT_INSTALL_DEX_FILES',
    'EMMA_INSTRUMENT',
    'ENABLE_AUTOFILL',
    'ENABLE_INCREMENTALJAVAC',
    'ENABLE_JSC_JIT',
    'ENABLE_SVG',  # TODO(igorc): Does WebKit need it
    'ENABLE_V8_SNAPSHOT',  # TODO(igorc): Does WebKit need it
    'ENABLE_WTF_USE_ACCELERATED_COMPOSITING',
    'FORCE_ARM_DEBUGGING',  # for arm
    'FORCE_BUILD_LLVM_COMPONENTS',
    'full_classes_compiled_jar',  # for Java library
    'full_classes_jar',  # for Java library
    'full_classes_jarjar_jar',  # for Java library
    'full_java_libs',  # for Java library
    'GENERATE_DEX_DEBUG',
    'HAVE_SELINUX',
    'HOST_ACP_UNAVAILABLE',
    'HOST_BUILD_TYPE',
    'HOST_CUSTOM_LD_COMMAND',
    'HOST_EXECUTABLES_SUFFIX',
    'HOST_LIBRARY_PATH',  # for art
    'HOST_PREFER_32_BIT',  # for art
    'HOST_RUN_RANLIB_AFTER_COPYING',
    'HOST_TOOLCHAIN_PREFIX',
    # From development/tools/emulator/opengl/system/
    # GLESv1_enc/Android.mk
    'intermediates',
    # For java lib in frameworks/webview
    'intermediates.COMMON',
    'INTERNAL_MODIFIER_TARGETS',
    'LEGACY_USE_JAVA6',
    'LIBART_LDFLAGS',  # for art
    'LIBART_TARGET_BOOT_JARS',  # for art
    'LIBART_TARGET_LDFLAGS_arm',  # for art
    'LIBART_TARGET_LDFLAGS_arm64',  # for art
    'LIBART_TARGET_LDFLAGS_mips',  # for art
    'LIBART_TARGET_LDFLAGS_x86',  # for art
    'LIBART_TARGET_LDFLAGS_x86_64',  # for art
    'LIBCORE_SKIP_TESTS',
    'LLVM_DEVICE_BUILD_MK',  # for art
    'LLVM_ENABLE_ASSERTION',  # for llvm
    'LLVM_GEN_INTRINSICS_MK',  # for art
    'LLVM_HOST_BUILD_MK',  # for art
    'libm_arm_cflags',  # for Bionic
    'libm_x86_cflags',  # for Bionic
    'libc_arch_dynamic_src_files',
    'libc_static_common_src_files',
    'libcutils_c_includes',
    'local_c_includes',  # for libssl
    'LOCAL_CFLAGS_',  # for bionic
    'LOCAL_CLANG',
    'local_javac_flags',  # libsqlite_jni has this
    'LOCAL_REQUIRED_MODULES_',
    # if --enable-art is not specified, this temporary variable
    # never gets set and make fails.
    'local-generated-sources-dir',
    'log_c_includes',
    'log_shared_libraries',
    'MAKECMDGOALS',
    'MALLOC_IMPL',  # for art, TODO: is jemalloc ok?
    'MINIMAL_NEWWAVELABS',
    'NO_FALLBACK_FONT',
    'NUM_FRAMEBUFFER_SURFACE_BUFFERS',
    'NULL',
    'ONE_SHOT_MAKEFILE',
    'OUT_DIR',
    'OUT_DIR_COMMON_BASE',
    'OVERRIDE_RUNTIMES',
    'PLATFORM_SDK_VERSION',
    'PLATFORM_VERSION',
    'PLATFORM_VERSION_CODENAME',
    'PRESENT_TIME_OFFSET_FROM_VSYNC_NS',
    'PRINT_BUILD_CONFIG',
    'PRODUCTS',
    'PV_INCLUDES',  # Private include dirs
    'REQUIRES_EH',  # for llvm
    'REQUIRES_RTTI',  # for llvm
    'SDK_ONLY',
    'SF_VSYNC_EVENT_PHASE_OFFSET_NS',
    'should-install-to-system',
    'SHOW_COMMANDS',
    'SOUND_TRIGGER_USE_STUB_MODULE',
    'STRIP',
    'TARGET_BOARD_KERNEL_HEADERS',
    'TARGET_BOARD_PLATFORM',
    'TARGET_BOOTLOADER_BOARD_NAME',
    'TARGET_BUILD_APPS',
    'TARGET_BUILD_PDK',
    'TARGET_BUILD_TYPE',
    'target_c_flags',  # for libssl
    'target_c_includes',  # for libssl
    'TARGET_CPU_ABI2',
    'TARGET_CPU_ABI_LIST',
    'TARGET_CPU_ABI_LIST_64_BIT',
    'TARGET_CPU_ABI_LIST_32_BIT',
    'TARGET_DEFAULT_JAVA_LIBRARIES',
    'TARGET_DISABLE_TRIPLE_BUFFERING',
    'TARGET_FDO_PROFILE_PATH',  # for arm
    'TARGET_FORCE_HWC_FOR_VIRTUAL_DISPLAYS',
    'TARGET_GCC_VERSION_EXP',
    'TARGET_HAS_BIGENDIAN',
    'TARGET_IS_64_BIT',
    'TARGET_RUN_RANLIB_AFTER_COPYING',
    'TARGET_RUNNING_WITHOUT_SYNC_FRAMEWORK',
    'TARGET_SIMULATOR',
    'target_src_files',  # for libssl
    'TARGET_USE_PRIVATE_LIBM',
    'TARGET_USES_LOGD',
    'TARGET_TOOLS_PREFIX',
    'TEST_ART_BROKEN_TARGET_PREBUILD_RUN_TESTS',  # for art
    'TEST_ART_HOST_RUN_TEST_DEFAULT_TARGETS',  # for art
    'TEST_ART_HOST_RUN_TEST_INTERPRETER_TARGETS',  # for art
    'TEST_ART_TARGET_RUN_TEST_DEFAULT_TARGETS',  # for art
    'TEST_ART_TARGET_RUN_TEST_TARGETS',  # for art
    'TMPDIR',  # for art
    'TOOL_CFLAGS',
    'TOP_DIR',
    'USE_CCACHE',
    'USE_CUSTOM_AUDIO_POLICY',
    'USE_MINGW',
    'VSYNC_EVENT_PHASE_OFFSET_NS',
    'WEBCORE_INSTRUMENTATION',
    'WITH_ADDRESS_SANITIZER',
    'WITH_ART_USE_OPTIMIZING_COMPILER',  # for art
    'WITH_COPYING_GC',
    'WITH_DEXPREOPT',
    'WITH_HOST_DALVIK',
    'WITH_MALLOC_CHECK_LIBC_A',
    'WITH_MALLOC_LEAK_CHECK',
    'WITH_STATIC_ANALYZER',
    'WITH_SYNTAX_CHECK',
    'WITHOUT_CLANG',
    'WITHOUT_HOST_CLANG',  # for art
    'WITHOUT_TARGET_CLANG',
    'xlink_attrs',
    'xml_attrs',
    'xmlns_attrs',
]

# Ignore these when make complains that such variables are not
# defined.  These prefixes are used for many variables - we cannot
# pre-define all of them. See comments for _DEFAULT_VARS for more
# info.  There's too many variables generated with this pattern, so we
# ignore the default values too.
_IGNORED_VAR_PREFIXES = [
    # WTF?
    '_nic.PRODUCTS.',
    'PRODUCTS.',
    'libunwind',
    # for bionic tests
    'libBionic',
    'fortify1-tests',
    'fortify2-tests',
    # for libbacktrace
    'backtrace',
    'libbacktrace',
    # for libicu4c
    'optional_android_logging_',
    # for art/build/Android.gtest.mk
    'ART_GTEST_',
    # base_rules.mk introduces ALL_MODULE_TAGS.<tag>, and
    # ALL_MODULES.<local module>.<attribute>. See, 'Register with ALL_MODULES'
    # section in base_rules.mk.
    'ALL_MODULE_TAGS.',
    'ALL_MODULES.',
    # LLVM
    'DISABLE_LLVM',
]

_IGNORED_VAR_PREFIXES_RE = re.compile(
    '^' + '|'.join([re.escape(w) for w in _IGNORED_VAR_PREFIXES]))

# Ignore missing these variables, as opposed to setting empty values
# in _DEFAULT_VARS.
_IGNORED_VARS_RE = [
    # (1), (2), ... are variable name for the arguments of a function
    # call. Some callers may not pass that parameter in and
    # it is normal and make would use empty value.
    # Ignore such warnings.
    '1', '2', '3', '4', '5', '6', '7', '8',
    # Android has a capability to build for two architectures at the
    # same time, but for ARC we do not have a second architecture to
    # target.
    '2ND_DEFAULT_DEX_PREOPT_BUILT_IMAGE_FILENAME',
    '2ND_HOST_IS_64_BIT',
    '2ND_HOST_OUT_SHARED_LIBRARIES',  # for ART
    '2ND_TARGET_CORE_DEX_FILES',
    '2ND_TARGET_CORE_IMG_OUT',
    '2ND_TARGET_IS_64_BIT',
    '2ND_TARGET_TOOLS_PREFIX',
    'LOCAL_2ND_ARCH',
    'LOCAL_2ND_ARCH_VAR_PREFIX',
    'TARGET_2ND_ARCH',
    'TARGET_2ND_ARCH_VAR_PREFIX',
    'TARGET_2ND_CPU_ABI2',
    'TARGET_2ND_CPU_VARIANT',
    'TARGET_PREFER_32_BIT',  # undef and 32-bit support is ignored.
    'TARGET_PREFER_32_BIT_APPS',
    'TARGET_PREFER_32_BIT_EXECUTABLES',
    'TARGET_SUPPORTS_32_BIT_APPS',
    'TARGET_SUPPORTS_64_BIT_APPS',  # default is to assume 32 bit.
    # LMP makefiles use <module>_xxx_<arch> to override specific
    # configs.
    '[-_a-z]*_c_includes',
    '[-_a-z]*_c_includes_host',
    '[-_a-z]*_c_includes_target',
    '[-_a-z]*_cflags',
    '[-_a-z]*_cflags_[_a-z0-9]*',
    '[-_a-z]*_clang_host',
    '[-_a-z]*_clang_target',
    '[-_a-z]*_conlyflags',
    '[-_a-z]*_conlyflags_host',
    '[-_a-z]*_conlyflags_target',
    '[-_a-z]*_cppflags',
    '[-_a-z]*_cppflags_host',
    '[-_a-z]*_cppflags_target',
    '[-_a-z]*_force_static_executable',
    '[-_a-z]*_install_to_out_data',
    '[-_a-z]*_ldflags',
    '[-_a-z]*_ldflags_host',
    '[-_a-z]*_ldflags_target',
    '[-_a-z]*_ldflags_arm',
    '[-_a-z]*_ldlibs',
    '[-_a-z]*_ldlibs_host',
    '[-_a-z]*_ldlibs_target',
    '[-_a-z]*_library_ldflags',
    '[-_a-z]*_library_ldflags_target',
    '[-_a-z]*_shared_libraries',
    '[-_a-z]*_shared_libraries_host',
    '[-_a-z]*_shared_libraries_target',
    '[-_a-z]*_src_files_[_a-z0-9]*',
    '[-_a-z]*_static_libraries',
    '[-_a-z]*_static_libraries_host',
    '[-_a-z]*_static_libraries_target',
]

_IGNORED_WARNING_RE = re.compile(
    "warning: undefined variable (`(%s)|`(%s)')" % (
        '|'.join([re.escape(w) for w in _IGNORED_VAR_PREFIXES]),
        '|'.join([w for w in _IGNORED_VARS_RE])))

_INITIALIZED = False


def _create_dir_for_file(name):
  dir_name = os.path.dirname(name)
  file_util.makedirs_safely(dir_name)


def _open_for_write(name, executable=None):
  name = os.path.join(_MAKE_TO_NINJA_DIR, name)
  _create_dir_for_file(name)
  f = open(name, 'w')
  if executable:
    mask = os.stat(name).st_mode
    os.chmod(name, mask | stat.S_IXUSR | stat.S_IXGRP)
  return f


def _open_for_write_in_build(name, executable=None):
  return _open_for_write(os.path.join('build', name), executable)


def _create_print_vars_makefile(build_type):
  file_name = os.path.join(_CORE_DIRNAME, build_type + '.mk')
  with _open_for_write_in_build(file_name) as f:
    contents = """
.PHONY: printvars
printvars:
  $(info %s $(%s))
  $(foreach V,$(sort $(.VARIABLES)), \
    $(if \
      $(filter-out \
        environment%% default automatic, \
        $(origin $V)), \
      $(info %s$V=$(value $V)) \
    ) \
  )
""" % (_VARS_PREFIX + build_type, _TARGET_MAKEFILE, _VAR_PREFIX)
    f.write(contents)


def _create_main_makefile(file_name, extra_env_vars):
  if OPTIONS.is_debug_code_enabled():
    debug = 'true'
    ndebug = 'false'
  else:
    debug = 'false'
    ndebug = 'true'
  _ENV_VARS = {
      'ANDROID_BUILD_TOP': _ARC_ROOT,
      # TODO(crbug.com/233769): Renderscript is not enabled.
      'ANDROID_ENABLE_RENDERSCRIPT': 'false',
      # For art
      'ART_BUILD_HOST_DEBUG': debug,
      'ART_BUILD_HOST_NDEBUG': ndebug,
      'ART_BUILD_TARGET_DEBUG': debug,
      'ART_BUILD_TARGET_NDEBUG': ndebug,
      # Set to a fixed value to prevent mk from generating one each time.
      # Build number is passed to aapt and so becomes a dependency.
      'BUILD_NUMBER': 'eng.eng.20141104.000000',
      # Directory for including most of the shared make files.
      'BUILD_SYSTEM': os.path.join(_MAKE_BUILD_DIR, _CORE_DIRNAME),
      # Assume all our processors are cortex-a15 that have hardware div
      # instruction
      'DEX2OAT_TARGET_INSTRUCTION_SET_FEATURES': 'div',
      'HOST_OUT_GEN': os.path.join(build_common.get_build_dir(), 'gen-host'),
      'LLVM_SUPPORTED_ARCH': 'arm arm64 mips mips64 x86 x86_64',
      'LOCAL_SDL_CONFIG': 'echo',
      # This is supposed to be a private, temporary variable, but it is leaking.
      'my_32_64_bit_suffix': 32,
      # Build webviewchromium.
      'PRODUCT_PREBUILT_WEBVIEWCHROMIUM': 'no',
      # Support "complex" scripts in WebKit.
      'SUPPORT_COMPLEX_SCRIPTS': 'true',
      'TARGET_BUILD_JAVA_SUPPORT_LEVEL': 'platform',
      'TARGET_BUILD_VARIANT': build_common.get_build_type(),
      # Assume that we always have SMP processors.
      'TARGET_CPU_SMP': 'true',
      'TARGET_OUT_GEN': os.path.join(build_common.get_build_dir(), 'gen'),
      # Top-level Android directory used to reference include files.
      'TOP': _MAKE_TO_NINJA_DIR + os.path.sep,
      'TOPDIR': _MAKE_TO_NINJA_DIR + os.path.sep,
      # Use a 32-bit keystore, even in 64 bit builds.
      'USE_32_BIT_KEYSTORE': 'true',
      'USE_LEGACY_AUDIO_POLICY': '1',
      # User name for inclusion in build id.
      'USER': 'eng',  # Some anonymous name
      # SEA mode. See, art/build/Android.common.mk.
      'WITH_ART_SEA_IR_MODE': 'false',
      # Smart mode. See, art/build/Android.common.mk.
      'WITH_ART_SMALL_MODE': 'false',
      # Portable mode using LLVM. See, art/build/Android.common.mk.
      'WITH_ART_USE_PORTABLE_COMPILER': 'false',
      # Some scripts add includes off of 'base'. Provided by binary.mk.
      # TODO(igorc): try to use binary.mk instead.
      'base': os.path.join(_MAKE_TO_NINJA_DIR, 'frameworks', 'base')}
  if OPTIONS.is_arm():
    arm_vars = {
        'arch': 'arm',  # for art
        'ART_SUPPORTED_ARCH': 'arm',
        'ARCH_ARM_HAVE_ARMV7A': 'true',
        # When this is set to true, we also have to use '-mfpu=neon'
        'ARCH_ARM_HAVE_NEON': 'true',
        # external/skia checks the variable.
        'ARCH_ARM_HAVE_VFP': 'true',
        # libbcc (dependency of art) checks for this.
        'ARCH_ARM_HAVE_VFP_D32': 'true',
        # For Bionic.
        '_LIBC_ARCH_CPU_VARIANT_HAS_MEMCPY': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS_MEMSET': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS_STRCAT': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS_STRCMP': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS_STRCPY': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS_STRLEN': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS___STRCAT_CHK': 'true',
        '_LIBC_ARCH_CPU_VARIANT_HAS___STRCPY_CHK': 'true',
        'TARGET_ARCH': 'arm',
        'TARGET_ARCH_ABI': 'armeabi-v7a',  # For libyuv.
        # For Bionic.
        'TARGET_CPU_VARIANT': 'cortex-a15',
        'TARGET_PRODUCT': 'full',
        'TARGET_ARCH_VARIANT': 'armv7-a-neon',  # for Dalvik
        'WITH_JIT': 'true',
    }
    _ENV_VARS.update(arm_vars)
  elif OPTIONS.is_x86_64():
    # NOTE: For Native Client x86_64, we want to use the 32-bit x86
    # defines in general, consistent with the use of 32-bit
    # int/long/pointer types and the NaCl strategy for source-code
    # portability.  We are taking the approach of setting architecture
    # to x86_64 and then fix up things later. This works because most
    # of the code that require 64-bit pointer in Android code base are
    # guarded by #if defined(__LP64__).
    x86_64_vars = {
        'arch': 'x86_64',  # for art
        'ART_SUPPORTED_ARCH': 'x86_64',
        'ARCH_ARM_HAVE_ARMV7A': 'false',
        'ARCH_ARM_HAVE_NEON': 'false',
        'ARCH_ARM_HAVE_VFP': 'false',
        'TARGET_ARCH': 'x86_64',
        'TARGET_ARCH_ABI': 'x86_64',
        'BOARD_MALLOC_ALIGNMENT': '16',
        'TARGET_ARCH_VARIANT': 'x86_64',
        'TARGET_CPU_VARIANT': 'x86_64',
        'TARGET_PRODUCT': 'full_x86_64',
        'WITH_JIT': 'false'}  # Android enables this by default on ARM only.
    _ENV_VARS.update(x86_64_vars)
  else:
    x86_vars = {
        'arch': 'x86',  # for art
        'ART_SUPPORTED_ARCH': 'x86',
        'ARCH_ARM_HAVE_ARMV7A': 'false',
        'ARCH_ARM_HAVE_NEON': 'false',
        'ARCH_ARM_HAVE_VFP': 'false',
        # Select 'x86' if the target is *_i686 since the default is 'arm'.
        'TARGET_ARCH': 'x86',
        'TARGET_ARCH_ABI': 'x86',
        # TODO(igorc): Consider switching to x86-atom build to use faster
        # Dalvik interpreter. This will likely require NaCl-related changes.
        'TARGET_ARCH_VARIANT': 'x86',
        # For Bionic. An empty string is not allowed.
        'TARGET_CPU_VARIANT': 'x86',
        # Build generic_x86, same way as we do for canned files.
        'TARGET_PRODUCT': 'full_x86',
        'WITH_JIT': 'false'}  # Android enables this by default on ARM only.
    _ENV_VARS.update(x86_vars)

  abs_path = os.path.abspath(file_name)

  main_makefile = []
  # The real build/core/main.mk sets up various variables before
  # calling config.mk. We try to set most of the same vars here.
  main_makefile.extend('%s:=%s' % item for item in _ENV_VARS.iteritems())
  if extra_env_vars:
    main_makefile.extend('%s:=%s' % item for item in extra_env_vars.iteritems())
  main_makefile.extend('%s:=' % name for name in _DEFAULT_VARS)
  main_makefile.extend([
      'PWD:=.\n',
      'include $(BUILD_SYSTEM)/config.mk',
      'include $(BUILD_SYSTEM)/definitions.mk',
      '%s:=%s' % (_TARGET_MAKEFILE, file_name),
      # Support direct use of sub-makefiles
      # (they may expect LOCAL_PATH from parent)
      'LOCAL_PATH:=$(dir %s)' % abs_path,
      'include %s' % abs_path,
      '.PHONY: droid',
      'droid:'])
  return '\n'.join(main_makefile)


def _create_noop_makefile(path):
  with _open_for_write_in_build(os.path.join(_CORE_DIRNAME, path)) as f:
    f.write('\n')


def _create_noop_makefiles(paths):
  for path in paths:
    _create_noop_makefile(path)


def _create_echo_script(path, output):
  with _open_for_write_in_build(path, executable=True) as f:
    f.write('echo ' + output + '\n')


def _create_tool_scripts():
  # Create a dummy script of android/build/core/find-jdk-tools-jar.sh.
  # core/config.mk checks it for host Java build, but host Java build is not
  # needed for ARC. The check passes if the script exists and echo a file path
  # that really exists.
  find_tools_script = os.path.join(_CORE_DIRNAME, 'find-jdk-tools-jar.sh')
  _create_echo_script(find_tools_script,
                      os.path.join(_MAKE_BUILD_DIR, find_tools_script))

  # Create a wrapper script of the find command that always specify '-L'.
  # Since ARC uses symlinks in the staging directory, the find command needs to
  # follow symlinks even if upstream Android.mk does not.
  with _open_for_write(os.path.join(_MAKE_TO_NINJA_BIN_DIR, 'find'),
                       executable=True) as f:
    contents = """#!/bin/sh
exec /usr/bin/find -L "$@"
"""
    f.write(contents)


def _extract_dir(tar, dst_dir, name):
  for member in tar.getmembers():
    if member.isfile() and \
       (name is None or os.path.dirname(member.name) == name):
      tar.extract(member, path=dst_dir)


def _copy_build_scripts():
  # Copy only necessary parts from core. We want to see errors if
  # a previously-unused mk becomes included - it may need to be replaced.
  # If all files under build/core are copied, 'make' command does not pass
  # because of many undefined variables.
  _copy_external_files(['build/core/android_manifest.mk',
                        'build/core/base_rules.mk',
                        'build/core/build_id.mk',
                        'build/core/clang/HOST_x86.mk',
                        'build/core/clang/HOST_x86_64.mk',
                        'build/core/clang/HOST_x86_common.mk',
                        'build/core/clang/TARGET_x86.mk',
                        'build/core/clang/TARGET_x86_64.mk',
                        'build/core/clang/TARGET_arm.mk',
                        'build/core/clang/arm.mk',
                        'build/core/clang/config.mk',
                        'build/core/clang/x86.mk',
                        'build/core/clang/x86_64.mk',
                        'build/core/clear_vars.mk',
                        'build/core/combo/HOST_linux-x86.mk',
                        'build/core/combo/HOST_linux-x86_64.mk',
                        'build/core/combo/TARGET_linux-arm.mk',
                        'build/core/combo/TARGET_linux-x86.mk',
                        'build/core/combo/TARGET_linux-x86_64.mk',
                        'build/core/combo/arch/arm/armv7-a.mk',
                        'build/core/combo/arch/x86/x86.mk',
                        'build/core/combo/arch/x86_64/x86_64.mk',
                        'build/core/combo/fdo.mk',
                        'build/core/combo/javac.mk',
                        'build/core/combo/select.mk',
                        'build/core/config.mk',
                        'build/core/configure_module_stem.mk',
                        'build/core/definitions.mk',
                        'build/core/device.mk',
                        'build/core/distdir.mk',
                        'build/core/envsetup.mk',
                        'build/core/host_dalvik_static_java_library.mk',
                        'build/core/host_static_test_lib.mk',
                        'build/core/host_test_internal.mk',
                        'build/core/java.mk',
                        'build/core/multi_prebuilt.mk',
                        'build/core/node_fns.mk',
                        'build/core/notice_files.mk',
                        'build/core/pathmap.mk',
                        'build/core/phony_package.mk',
                        'build/core/product.mk',
                        'build/core/product_config.mk',
                        'build/core/static_test_lib.mk',
                        'build/core/static_java_library.mk',
                        'build/core/target_test_internal.mk',
                        'build/core/version_defaults.mk'])

  _copy_external_dir('build/target/board')
  _copy_external_dir('build/target/product')

  _copy_external_files([
      'abi/cpp/use_rtti.mk',
      'art/build/Android.common.mk',
      'art/build/Android.executable.mk',
      'bionic/libc/arch-arm/arm.mk',
      'bionic/libc/arch-arm/cortex-a15/cortex-a15.mk',
      'bionic/libc/arch-arm/generic/generic.mk',
      'bionic/libc/arch-x86/x86.mk',
      'external/llvm/llvm-device-build.mk',
      'external/llvm/llvm-gen-intrinsics.mk',
      'external/llvm/llvm-host-build.mk',
      'external/llvm/llvm.mk',
      'external/stlport/libstlport.mk',
      'frameworks/av/drm/libdrmframework/plugins/common/include/IDrmEngine.h',
      'frameworks/av/media/libstagefright/codecs/common/Config.mk',
      'frameworks/compile/libbcc/libbcc-targets.mk',
      'frameworks/compile/slang/rs_version.mk'])


def _copy_canned_generated_sources():
  # Do nothing if a stamp file is up to date.
  stamp_file_path = os.path.join(_ANDROID_TARGET_GEN_SOURCES_DIR, 'STAMP')
  tar_stat = os.stat(_CANNED_GEN_SOURCES_TAR)
  tar_revision = '%s:%s' % (tar_stat.st_size, tar_stat.st_mtime)
  stamp_file = StampFile(tar_revision, stamp_file_path)
  if stamp_file.is_up_to_date():
    return

  # Wipe existing directory in case files are removed from the tarball.
  shutil.rmtree(_ANDROID_TARGET_GEN_SOURCES_DIR, True)
  t = tarfile.open(_CANNED_GEN_SOURCES_TAR)
  _extract_dir(t, _ANDROID_TARGET_GEN_SOURCES_DIR, None)
  t.close()

  stamp_file.update()


def _copy_external_file(stem):
  src = staging.as_staging(os.path.join('android', stem))
  dst = os.path.join(_MAKE_TO_NINJA_DIR, stem)
  _create_dir_for_file(dst)
  shutil.copyfile(src, dst)
  shutil.copymode(src, dst)

  dependency_inspection.add_files(src)


def _copy_external_files(stems):
  for stem in stems:
    _copy_external_file(stem)


def _copy_external_dir(dir_name):
  src = os.path.join(_ARC_ROOT, 'third_party', 'android', dir_name)
  dst = os.path.join(_MAKE_TO_NINJA_DIR, dir_name)
  file_util.rmtree(dst, ignore_errors=True)
  shutil.copytree(src, dst)

  dependency_inspection.add_file_listing([src], None, None, True)


# Creates common mk files and related links.
def prepare_make_to_ninja():
  shutil.rmtree(_MAKE_TO_NINJA_DIR, ignore_errors=True)
  _create_noop_makefiles([
      # TODO(crbug.com/363472): clang.mk is used to build
      # frameworks/compile/slang/BitWriter_3_2. The slang depends on clang.mk,
      # but for now only the BitWriter module is built and it does not need
      # the real clang.mk. Remove this to avoid makefile hacks as possible.
      '../../external/clang/clang.mk',
      'droiddoc.mk',  # Not supported
      'dumpvar.mk',  # No spam
      'executable_prefer_symlink.mk',  # backported from L
      'host_java_library.mk',  # Not supported
      'host_native_test.mk',  # Not supported
      'native_test.mk'])  # Not supported
  _create_print_vars_makefile(BUILD_TYPE_HOST_DALVIK_JAVA_LIBRARY)
  _create_print_vars_makefile(BUILD_TYPE_HOST_SHARED)
  _create_print_vars_makefile(BUILD_TYPE_HOST_STATIC)
  _create_print_vars_makefile(BUILD_TYPE_HOST_EXECUTABLE)
  _create_print_vars_makefile(BUILD_TYPE_JAVA_LIBRARY)
  _create_print_vars_makefile(BUILD_TYPE_PACKAGE)
  _create_print_vars_makefile(BUILD_TYPE_TARGET_SHARED)
  _create_print_vars_makefile(BUILD_TYPE_TARGET_STATIC)
  _create_print_vars_makefile(BUILD_TYPE_TARGET_EXECUTABLE)
  _create_print_vars_makefile(BUILD_TYPE_NOTICES_SHARED)
  _create_print_vars_makefile(BUILD_TYPE_NOTICES_STATIC)
  _create_print_vars_makefile(BUILD_TYPE_PREBUILT)
  _copy_build_scripts()

  _copy_external_files(['external/libcxx/libcxx.mk'])
  _copy_external_file('build/tools/findleaves.py')
  _copy_canned_generated_sources()
  _create_tool_scripts()

  file_util.makedirs_safely(_MAKE_BUILD_DIR)


def _filter_make_output(workdir, stdout, stderr, in_file):
  # Check if stderr from make contains any error info.
  errors = []
  for line in stderr.split('\n'):
    # No way and no need to predefine PRODUCTS. and similar vars.
    if not line or _IGNORED_WARNING_RE.search(line):
      continue
    errors.append('MAKE STDERR: ' + line)
  assert not errors, ('make %s exited with warnings: ' % in_file +
                      '\n'.join(errors))

  # Print and filter out "Reading makefile" lines from stdout if necessary.
  result = []
  has_logging = OPTIONS.is_make_to_ninja_logging()
  for line in stdout.split('\n'):
    match = _READING_MAKEFILE_RE.match(line)
    if match:
      if has_logging:
        print line
      submake = os.path.join(workdir, match.group(1))
      if not submake.startswith(_MAKE_TO_NINJA_DIR):
        dependency_inspection.add_files(submake)
    elif line:
      result.append(line)

  return result


def _run_make(workdir, in_file, extra_env_vars):
  dependency_inspection.add_file_listing([workdir], None, None, True)

  target = OPTIONS.target()
  main_makefile = _create_main_makefile(in_file, extra_env_vars)
  env = {
      'CXX': toolchain.get_tool(target, 'cxx'),
      'CC': toolchain.get_tool(target, 'cc'),
      'LD': toolchain.get_tool(target, 'ld'),
      'AR': toolchain.get_tool(target, 'ar'),
      'NM': toolchain.get_tool(target, 'nm'),
      'OBJCOPY': toolchain.get_tool(target, 'objcopy'),
      'OBJDUMP': toolchain.get_tool(target, 'objdump'),
      'ADDR2LINE': toolchain.get_tool(target, 'addr2line'),
      'STRIP': toolchain.get_tool(target, 'strip'),
      # third_party/android/build/core/combo/TARGET_linux-arm.mk checks
      # a few features of the compiler using $(shell ...). As we cannot
      # prevent this by dry-run mode, we need valid PATH.
      'PATH': ':'.join([_MAKE_TO_NINJA_BIN_DIR, os.environ['PATH']])
  }

  # "--debug=v" indicates when Make reads makefiles.
  make_cmd = [
      'make', '-f', '-', '-I', _MAKE_BUILD_DIR, '--always-make',
      '--silent', '--no-print-directory', '--warn-undefined-variables',
      '--no-builtin-rules', '--debug=v']

  if OPTIONS.is_make_to_ninja_logging():
    print 'Running make like this:'
    print ('$ cd %s; cat <<"EOF" > /tmp/makefile\n%s\nEOF\ncat /tmp/makefile | '
           'env %s %s' %
           (_MAKE_TO_NINJA_DIR, main_makefile,
            ' '.join('%s=%s' % item for item in env.iteritems()),
            ' '.join(make_cmd)))

  # Run make command, and process its output.
  p = subprocess.Popen(
      make_cmd, cwd=_MAKE_TO_NINJA_DIR, env=env,
      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  return _filter_make_output(workdir, *p.communicate(main_makefile),
                             in_file=in_file)


def _filter_var_name(name):
  # If variable name starts with one of our prefixes, ignore. Too many
  # variants of these prefixed inheritance variables.
  return not _IGNORED_VAR_PREFIXES_RE.match(name)


def _add_var_if_not_empty(vars, name, value):
  if value and name and _filter_var_name(name):
    # Add variable only if it has a non-empty value, and is not one of
    # the known prefixes that generate lots of variables.
    vars[name] = value


def _parse_vars(build_lines):

  # The output we are parsing may contain multi-line values,
  # and generally looks like the following:
  # === VARIABLE LOCAL_PATH=/usr/local/google/arc/third_party/android/external/webp/src/enc  # noqa
  # === VARIABLE transform-proto-to-java=@mkdir -p $(dir $@)
  # @echo "Protoc: $@ <= $(PRIVATE_PROTO_SRC_FILES)"
  # @rm -rf $(PRIVATE_PROTO_JAVA_OUTPUT_DIR)
  # @mkdir -p $(PRIVATE_PROTO_JAVA_OUTPUT_DIR)
  # === VARIABLE transform-ranlib-copy-hack=@true

  vars = {}
  cur_var_name = ''
  cur_var_value = ''
  for line in build_lines:
    if line.startswith(_VAR_PREFIX):
      _add_var_if_not_empty(vars, cur_var_name, cur_var_value)
      line = line[len(_VAR_PREFIX):]
      idx = line.find('=')
      if idx == -1:
        raise ValueError('"=" not found in ' + line)
      cur_var_name = line[:idx]
      cur_var_value = ''
      line = line[idx + 1:]
    if cur_var_value:
      cur_var_value += '\n'
    cur_var_value += line
  _add_var_if_not_empty(vars, cur_var_name, cur_var_value)
  return vars


def _get_optional_var(build_type, vars, name, def_value):
  result = vars.get(name, None)
  result = _evaluate_var_expressions(build_type, vars, name, result)
  if result is None or result.strip() == '':
    return def_value
  return result.strip()


def _get_optional_bool(build_type, vars, name, def_bool):
  assert def_bool in [True, False]
  result = _get_optional_var(build_type, vars, name, None)
  if result == 'true':
    return True
  if result == 'false':
    return False
  assert result is None
  return def_bool


# Replaces $(var_name) expressions with corresponding variable values.
# Does not support arbitrary make function calls inside $().
# Function calls will be of the form: $(call foo-bar) and "call foo-bar"
# will be parsed here as the variable name, so it will never be found and
# any such calls will cause a ValueError to be raised.
# TODO(igorc): find a way for make to emit expanded values.
def _evaluate_var_expressions(build_type, vars, name, str):
  if str is None:
    return str
  result = ''
  start_pos = 0
  while True:
    idx = str.find('$(', start_pos)
    if idx != -1:
      idx2 = str.find(')', idx + 2)
      if idx2 == -1:
        _print_vars(build_type, vars)
        raise ValueError('"' + name + '" contains invalid value')
      var_name = str[idx + 2: idx2]
      var_value = _get_optional_var(build_type, vars, var_name, '')
      result += str[start_pos:idx]
      result += var_value
      start_pos = idx2 + 1
      continue
    result += str[start_pos:]
    break
  return result


def _get_required_var(build_type, vars, name):
  result = _get_optional_var(build_type, vars, name, None)
  if result is None:
    _print_vars(build_type, vars)
    raise ValueError('"' + name + '" was not specified')
  return result


# Prints all variables for debugging.
def _print_vars(build_type, vars):
  print 'Variables from ' + build_type
  count = 0
  for name, value in vars.items():
    print name + " = " + value
    count += 1
  print "Total variable count =", count


# TODO(crbug.com/397631): Rewrite the other build types to use this helper.
class BuildVarHelper(object):
  def __init__(self, build_type, vars):
    self._build_type = build_type
    self._vars = vars

  def get_required(self, name):
    return _get_required_var(self._build_type, self._vars, name)

  def get_optional(self, name, default=None):
    return _get_optional_var(self._build_type, self._vars, name, default)

  def get_optional_bool(self, name, default=False):
    return _get_optional_bool(self._build_type, self._vars, name, default)

  def get_optional_list(self, name, variants=None):
    result = self._get_optional_list_internal(name)
    if variants:
      for v in variants:
        result.extend(self._get_optional_list_internal('%s_%s' % (name, v)))
    return result

  def _get_optional_list_internal(self, name):
    return shlex.split(self.get_optional(name, default=''))

  def get_optional_flags(self, name, variants=None):
    return _merge_separated_flags(self.get_optional_list(name, variants))


# Merges the value for '-D' and '-I' into one element if they are contained in
# the list separately.
# e.g. ['-D', 'SOMETHING', '-I', '/foo/bar'] => ['-DSOMETHING', '-I/foo/bar']
def _merge_separated_flags(flags):
  result = []
  separated_flag = None
  for flag in flags:
    if flag in ['-D', '-I']:
      assert not separated_flag
      separated_flag = flag
      continue
    elif separated_flag:
      result.append(separated_flag + flag)
      separated_flag = None
    else:
      result.append(flag)
  assert not separated_flag
  return result


def _get_module_path(vars):
  module_path = vars.get_optional('LOCAL_MODULE_PATH')
  if module_path is not None:
    return module_path

  is_host_module = vars.get_optional_bool('LOCAL_IS_HOST_MODULE')
  module_class = vars.get_required('LOCAL_MODULE_CLASS')
  module_tags = vars.get_optional_list('LOCAL_MODULE_TAGS')
  privileged = vars.get_optional_bool('LOCAL_PRIVILEGED_MODULE')
  proprietary = vars.get_optional_bool('LOCAL_PROPRIETARY_MODULE')

  my_prefix = 'HOST_' if is_host_module else 'TARGET_'

  if is_host_module:
    partition_tag = ''
  elif proprietary:
    partition_tag = '_VENDOR'
  else:
    partition_tag = '_DATA' if 'tests' in module_tags else ''

  install_path_var = '%sOUT%s_%s' % (my_prefix, partition_tag, module_class)
  if privileged:
    install_path_var = install_path_var + '_PRIVILEGED'

  return vars.get_required(install_path_var)


def _get_prebuilt_install_type_and_path(vars):
  host_out_path = vars.get_required('HOST_OUT')
  installed_module_stem = vars.get_optional('LOCAL_INSTALLED_MODULE_STEM')
  module_class = vars.get_required('LOCAL_MODULE_CLASS')
  module_name = vars.get_required('LOCAL_MODULE')
  target_out_path = vars.get_required('TARGET_OUT')

  if installed_module_stem is None:
    module_stem = vars.get_optional('LOCAL_MODULE_STEM', default=module_name)
    module_suffix = vars.get_optional('LOCAL_MODULE_SUFFIX', '')
    installed_module_stem = module_stem + module_suffix

  is_static_library = module_class == 'STATIC_LIBRARIES'
  uninstallable = vars.get_optional_bool(
      'LOCAL_UNINSTALLABLE_MODULE', default=is_static_library)
  if uninstallable:
    return False, None

  module_path = _get_module_path(vars)

  # For ARC, remap the portion of the install path that corresponds to
  # TARGET_OUT to the ARC equivalent. This allows us to install the prebuilt
  # file directly, rather than storing an intermediate file somewhere which
  # we do not need otherwise.
  if module_path.startswith(host_out_path):
    module_path = module_path[len(host_out_path) + 1:]
    # The only clue to whether a prebuilt file is for the target or the host
    # is where the file is installed.
    prebuilt_for_host = True
  elif module_path.startswith(target_out_path):
    module_path = module_path[len(target_out_path) + 1:]
    prebuilt_for_host = False
  else:
    assert False, ('"%s" is not a known host or target path for "%s"' % (
        module_path, module_name))

  prebuilt_install_path = os.path.join(module_path, installed_module_stem)
  return prebuilt_for_host, prebuilt_install_path


class MakeVars:
  """Encapsulates variables from Android make file."""

  def __init__(self, build_type, build_file, raw_vars):
    # To make it more clear what is being used we avoid storing vars and
    # store individual pieces instead.
    self._build_type = build_type

    self._build_file = build_file

    # We store the original raw_vars produced by the mk file so that custom
    # filter_vars code can later access non-standard variables such as
    # LOCAL_JS_LIBRARY_FILES.
    vars_helper = BuildVarHelper(BUILD_TYPE_PREBUILT, raw_vars)
    self._vars_helper = vars_helper

    # The arguments passed to NinjaGenerator constructor.
    self._generator_args = {}

    # Filter function sets this to indicate which resulting codegen files
    # should be picked up by other build steps. We currently use this to list
    # Java files created by aapt.
    self._exported_intermediates = []

    # Filter function can add new custom rules and build steps here.
    self._extra_rules = []
    self._extra_builds = []
    self._extra_install_to_root = []
    self._extra_notices = []

    # If a pre-built library should be installed from the canned directory.
    # TODO(crbug.com/364344): Once Renderscript is built from source, remove.
    self._is_canned = False

    # C++ exceptions are disabled by default. Only certain modules that
    # absolutely require them (like pdfium) should set this to True
    self._enable_exceptions = False

    self._force_optimization = False

    self._path = _rel_from_root(vars_helper.get_required('LOCAL_PATH'))

    self._prebuilt_for_host = False

    if self.is_c_library() or self.is_executable():
      self._init_c_program(vars_helper)
    elif self.is_java_library():
      self._init_java_library(vars_helper)
    elif self.is_package():
      self._init_package(vars_helper)
    elif self.is_prebuilt():
      self._init_prebuilt(vars_helper)
    else:
      assert False, 'Unknown type %s in %s' % (
          self._build_type, self._build_file)

    self._is_logtag_emission_enabled = True

    self._logtag = self._module_name

  def _init_c_program(self, vars_helper):
    self._module_name = vars_helper.get_required('LOCAL_MODULE')

    if self.is_host():
      arch_variant = 'x86_64'
      arch_bit_variant = '64'
    elif OPTIONS.is_arm():
      arch_variant = 'arm'
      arch_bit_variant = '32'
    elif OPTIONS.is_x86_64():
      arch_variant = 'x86_64'
      arch_bit_variant = '64'
    else:
      arch_variant = 'x86'
      arch_bit_variant = '32'

    self._cflags = self._get_build_flags(vars_helper, 'CFLAGS',
                                         [arch_variant, arch_bit_variant])
    self._conlyflags = self._get_build_flags(vars_helper, 'CONLYFLAGS',
                                             [arch_variant])
    # For consistency with NinjaGenerator, call it cxxflags rather than
    # cppflags.
    self._cxxflags = self._get_build_flags(vars_helper, 'CPPFLAGS',
                                           [arch_variant])
    self._asmflags = self._get_build_flags(vars_helper, 'ASFLAGS',
                                           [arch_bit_variant])
    self._ldflags = self._get_build_flags(vars_helper, 'LDFLAGS',
                                          [arch_variant, arch_bit_variant])

    self._includes = vars_helper.get_optional_list(
        'LOCAL_C_INCLUDES', [arch_variant])
    self._includes.append(self._path)
    if self.is_target():
      gen_sources_dir = _ANDROID_TARGET_GEN_SOURCES_DIR
    else:
      gen_sources_dir = _ANDROID_HOST_GEN_SOURCES_DIR
    if self.is_shared():
      libraries_dir = 'SHARED_LIBRARIES'
    else:
      libraries_dir = 'STATIC_LIBRARIES'
    self._android_gen_path = os.path.join(
        gen_sources_dir, libraries_dir, self._module_name + '_intermediates')
    self._includes.append(self._android_gen_path)
    self._includes += vars_helper.get_optional_list('JNI_H_INCLUDE')

    self._sys_includes = []
    if self.is_host():
      self._sys_includes = vars_helper.get_optional_list(
          'HOST_PROJECT_INCLUDES')
    else:
      self._sys_includes = vars_helper.get_optional_list(
          'TARGET_PROJECT_INCLUDES')
      self._sys_includes += vars_helper.get_optional_list('TARGET_C_INCLUDES')

    local_sources = vars_helper.get_optional_list(
        'LOCAL_SRC_FILES', [arch_variant, arch_bit_variant])
    gen_sources = vars_helper.get_optional_list(
        'LOCAL_GENERATED_SOURCES', [arch_variant, arch_bit_variant])

    self._sources = []
    # .ipp is a header file that implements inline template methods.
    self._sources += (os.path.join(self._path, x) for x in local_sources if
                      not x.endswith('.h') and not x.endswith('.ipp'))
    self._sources += (x for x in gen_sources if not x.endswith('.h'))

    self._static_deps = vars_helper.get_optional_list('LOCAL_STATIC_LIBRARIES')
    self._whole_archive_deps = vars_helper.get_optional_list(
        'LOCAL_WHOLE_STATIC_LIBRARIES', [arch_variant, arch_bit_variant])
    self._shared_deps = vars_helper.get_optional_list('LOCAL_SHARED_LIBRARIES')
    self._addld_deps = []

    self._implicit_deps = [os.path.join(self._path, x) for x in local_sources
                           if x.endswith('.h') or x.endswith('.ipp')]

    self._copy_headers = vars_helper.get_optional_flags('LOCAL_COPY_HEADERS')
    self._copy_headers_to = vars_helper.get_optional('LOCAL_COPY_HEADERS_TO')
    if self._copy_headers_to:
      self._copy_headers_to = os.path.join(_INTERMEDIATE_HEADERS_DIR,
                                           self._copy_headers_to)

    self._clang_incompatible_flags = vars_helper.get_optional_list(
        'CLANG_CONFIG_%s_UNKNOWN_CFLAGS' % build_common.get_bionic_arch_name())
    if OPTIONS.is_nacl_build():
      # Add flags that PNaCl clang does not recognize.
      self._clang_incompatible_flags.extend([
          '-no-canonical-prefixes', '-march=i686'])

    # clang-3.5 silently ignores -finline-functions, and clang-3.6 emits a
    # warning for it.
    self._clang_incompatible_flags.append('-finline-functions')

    if vars_helper.get_optional('LOCAL_CLANG') == 'true':
      self._is_clang_enabled = True
      self._is_cxx11_enabled = True
    else:
      self._is_clang_enabled = False
      self._is_cxx11_enabled = False
    self._is_clang_linker_enabled = False
    self._is_libcxx_enabled = ('-D_USING_LIBCXX' in self._cflags)

    if (self.is_target_executable() and
        'tests' in vars_helper.get_optional_list('LOCAL_MODULE_TAGS')):
      self.set_build_type(BUILD_TYPE_TARGET_TEST_EXECUTABLE)
    self._disabled_tests = []
    self._qemu_disabled_tests = []

    # TODO(igorc): Maybe support LOCAL_SYSTEM_SHARED_LIBRARIES

  def _update_flags_for_clang(self):
    # Remove flags that are not supported by clang.
    # See also build/core/clang/{HOST|TARGET}_<arch>.mk.
    self._cflags = [x for x in self._cflags
                    if x not in self._clang_incompatible_flags]
    self._conlyflags = [x for x in self._conlyflags
                        if x not in self._clang_incompatible_flags]
    self._cxxflags = [x for x in self._cxxflags
                      if x not in self._clang_incompatible_flags]
    self._ldlags = [x for x in self._ldflags
                    if x not in self._clang_incompatible_flags]

  def _init_java_library(self, vars_helper):
    """Does initialization for jar Java library."""

    # JarNinjaGenerator assumes LOCAL_EMMA_INSTRUMENT is 'false' or undefined.
    # This is because ARC does not use the original base_rules.mk, and as a
    # result, ARC can not generate full_classes_compiled_jar_leaf variable
    # automatically. Using the original base_rules.mk will need hard works.
    assert not vars_helper.get_optional_bool('LOCAL_EMMA_INSTRUMENT')

    self._module_name = vars_helper.get_required('LOCAL_MODULE')
    self._is_static_java_library = vars_helper.get_optional_bool(
        'LOCAL_IS_STATIC_JAVA_LIBRARY')
    self._sources = vars_helper.get_optional_list('LOCAL_SRC_FILES')
    self._generated_sources = vars_helper.get_optional_list(
        'LOCAL_GENERATED_SOURCES')

    if not vars_helper.get_optional_bool('LOCAL_NO_STANDARD_LIBRARIES'):
      self._java_libraries = vars_helper.get_optional_list(
          'TARGET_DEFAULT_JAVA_LIBRARIES')
    else:
      self._java_libraries = []
    self._java_libraries.extend(vars_helper.get_optional_list(
        'LOCAL_JAVA_LIBRARIES'))
    self._static_java_libraries = vars_helper.get_optional_list(
        'LOCAL_STATIC_JAVA_LIBRARIES')

    self._java_resource_dirs = vars_helper.get_optional_list(
        'LOCAL_JAVA_RESOURCE_DIRS')

    self._jarjar_rules = vars_helper.get_optional('LOCAL_JARJAR_RULES')

    local_path = vars_helper.get_required('LOCAL_PATH')
    self._aidl_includes = [local_path, os.path.join(local_path, 'src')]
    self._aidl_includes += vars_helper.get_optional_list('LOCAL_AIDL_INCLUDES')
    self._aidl_includes += [
        staging.as_staging(os.path.join('android', x)) for x in
        vars_helper.get_optional_list('FRAMEWORKS_BASE_JAVA_SRC_DIRS')]

    local_resource_dirs = vars_helper.get_optional_list('LOCAL_RESOURCE_DIR')
    if local_resource_dirs:
      self._local_resource_dirs = [
          _get_resource_relpath(local_path, x) for x in local_resource_dirs]
    else:
      self._local_resource_dirs = None

    self._dx_flags = vars_helper.get_optional('LOCAL_DX_FLAGS')
    self._aapt_flags = vars_helper.get_optional_flags('LOCAL_AAPT_FLAGS')
    self._aapt_manifest = vars_helper.get_optional(
        'LOCAL_FULL_MANIFEST_FILE', default='AndroidManifest.xml')
    self._dex_preopt = (not self.is_static_java_library() and
                        vars_helper.get_optional_bool('LOCAL_DEX_PREOPT', True))

  def _init_package(self, vars_helper):
    """Does initialization for a package."""

    self._module_name = vars_helper.get_required('LOCAL_PACKAGE_NAME')
    self._aapt_flags = vars_helper.get_optional_flags('LOCAL_AAPT_FLAGS')
    self._aapt_manifest = vars_helper.get_optional(
        'LOCAL_MANIFEST_FILE', default='AndroidManifest.xml')
    self._local_resource_dirs = None

  def _init_prebuilt(self, vars_helper):
    """Does initialization for a prebuilt package."""

    module_name = vars_helper.get_required('LOCAL_MODULE')
    module_class = vars_helper.get_required('LOCAL_MODULE_CLASS')

    c_include_dirs = vars_helper.get_optional_list(
        'LOCAL_EXPORT_C_INCLUDE_DIRS')
    is_host_module = vars_helper.get_optional_bool('LOCAL_IS_HOST_MODULE')
    run_ranlib = vars_helper.get_optional_bool(
        'TARGET_RUN_RANLIB_AFTER_COPYING')
    strip_comments = vars_helper.get_optional_bool(
        'LOCAL_PREBUILT_STRIP_COMMENTS')
    strip_module = vars_helper.get_optional_bool('LOCAL_STRIP_MODULE')

    prebuilt_src_path = vars_helper.get_optional('LOCAL_PREBUILT_MODULE_FILE')
    if not prebuilt_src_path:
      prebuilt_src_path = os.path.join(
          vars_helper.get_required('LOCAL_PATH'),
          vars_helper.get_required('LOCAL_SRC_FILES'))

    # There are several module classes, but we only support the ones we need.
    assert module_class in ('ETC', 'JAVA_LIBRARIES', 'SHARED_LIBRARIES'), (
        'Unsupported module class "%s" for "%s"' % (module_class, module_name))
    # We do not have support for stripping comments.
    assert not strip_comments, (
        'Unexpected request to strip comments for "%s"' % module_name)
    # We do not have support for striping libraries.
    assert not strip_module, (
        'Unexpected request to strip the library for "%s"' % module_name)
    # We do not have support for running ranlib.
    assert not run_ranlib, (
        'Unexpected request to run ranlib for "%s"' % module_name)
    # We do not have support for adding C/C++ include paths
    assert len(c_include_dirs) == 0, (
        'Unexpected request to add to the C/C++ include path for '
        '"%s"' % module_name)

    prebuilt_for_host, prebuilt_install_path = (
        _get_prebuilt_install_type_and_path(vars_helper))

    intermediate_path = None
    if module_class == 'ETC':
      assert prebuilt_install_path is not None, (
          'Unexpected: ETC module "%s" is was not meant to be installed.' % (
              module_name))
    elif module_class == 'JAVA_LIBRARIES':
      intermediate_path = build_common.get_build_path_for_jar(
          module_name, subpath='classes.jar')
    elif module_class == 'SHARED_LIBRARIES':
      intermediate_path = build_common.get_intermediates_dir_for_library(
          os.path.basename(prebuilt_src_path), is_host=is_host_module)
    else:
      assert False, 'Unknown prebuilt module class "%s" for "%s"' % (
          module_class, module_name)

    self._module_name = module_name
    self._prebuilt_class = module_class
    self._prebuilt_src_path = prebuilt_src_path
    self._prebuilt_for_host = prebuilt_for_host
    self._prebuilt_intermediate_path = intermediate_path
    self._prebuilt_install_path = prebuilt_install_path
    self._prebuilt_install_to_root_dir = False

  def _get_build_flags(self, vars_helper, name, variants):
    """Gets build flags such as C flags, CPP flags.

    LOCAL_<name> is always used.
    TARGET_GLOBAL_<name> is used only if the module is for the target.
    HOST_GLOBAL_<name> is used only if the module is for the host.

    This also tries to get architecture-specific flags from
    <prefix>_<name>_<variant>.
    """
    prefixes = [
        'LOCAL',
        ('HOST' if self.is_host() else 'TARGET') + '_GLOBAL',
    ]
    flags = []
    for prefix in prefixes:
      flags.extend(
          vars_helper.get_optional_flags('%s_%s' % (prefix, name), variants))
    return flags

  def __repr__(self):
    return "%s %s" % (self.__class__.__name__, self.__dict__)

  def is_host_shared(self):
    return (self._build_type == BUILD_TYPE_HOST_SHARED)

  def is_host_static(self):
    return (self._build_type == BUILD_TYPE_HOST_STATIC)

  def is_host_executable(self):
    return (self._build_type == BUILD_TYPE_HOST_EXECUTABLE)

  def is_target_shared(self):
    return (self._build_type == BUILD_TYPE_TARGET_SHARED)

  def is_target_static(self):
    return (self._build_type == BUILD_TYPE_TARGET_STATIC)

  def is_target_executable(self):
    return (self._build_type == BUILD_TYPE_TARGET_EXECUTABLE)

  def is_target_test_executable(self):
    return (self._build_type == BUILD_TYPE_TARGET_TEST_EXECUTABLE)

  def is_host_java_library(self):
    return self._build_type == BUILD_TYPE_HOST_DALVIK_JAVA_LIBRARY

  def is_java_library(self):
    return ((self._build_type == BUILD_TYPE_JAVA_LIBRARY) or
            (self._build_type == BUILD_TYPE_HOST_DALVIK_JAVA_LIBRARY))

  def is_notices_shared(self):
    return (self._build_type == BUILD_TYPE_NOTICES_SHARED)

  def is_notices_static(self):
    return (self._build_type == BUILD_TYPE_NOTICES_STATIC)

  def is_shared(self):
    return (self.is_target_shared() or self.is_host_shared() or
            self.is_notices_shared())

  def is_static(self):
    return (self.is_target_static() or self.is_host_static() or
            self.is_notices_static())

  def is_host(self):
    return (self.is_host_shared() or self.is_host_static() or
            self.is_host_executable() or self.is_host_java_library())

  def is_target(self):
    return (self.is_target_shared() or self.is_target_static() or
            self.is_target_executable())

  def is_c_library(self):
    return self.is_shared() or self.is_static()

  def is_executable(self):
    return (self.is_target_executable() or self.is_target_test_executable() or
            self.is_host_executable())

  def is_package(self):
    return (self._build_type == BUILD_TYPE_PACKAGE)

  def is_notices(self):
    return self.is_notices_shared() or self.is_notices_static()

  def is_static_java_library(self):
    assert self.is_java_library()
    return self._is_static_java_library

  def get_enable_exceptions(self):
    return self._enable_exceptions

  def set_enable_exceptions(self, value):
    self._enable_exceptions = value
    if value:
      self.get_cxxflags().append('-fexceptions')

  def get_module_name(self):
    return self._module_name

  def set_module_name(self, value):
    if self._logtag == self._module_name:
      self._logtag = value
    self._module_name = value

  def get_build_type(self):
    return self._build_type

  def set_build_type(self, build_type):
    if (self.is_c_library() or
        (self.is_target_executable() and
         (build_type == BUILD_TYPE_TARGET_TEST_EXECUTABLE))):
      self._build_type = build_type
      return
    raise Exception('Cannot change build type of ' + self._build_type)

  def get_android_gen_path(self):
    return self._android_gen_path

  def get_path(self):
    return self._path

  def is_clang_enabled(self):
    assert self.is_c_library() or self.is_executable()
    return self._is_clang_enabled

  def is_cxx11_enabled(self):
    assert self.is_c_library() or self.is_executable()
    return self._is_cxx11_enabled

  def is_clang_linker_enabled(self):
    assert self.is_c_library() or self.is_executable()
    return self._is_clang_linker_enabled

  def _check_flags_unmodified(self):
    assert self._cflags == self._orig_cflags, (
        '{disable|enable}_clang() must be called before modifying cflags')
    assert self._conlyflags == self._orig_conlyflags, (
        '{disable|enable}_clang() must be called before modifying conlyflags')
    assert self._cxxflags == self._orig_cxxflags, (
        '{disable|enable}_clang() must be called before modifying cxxflags')
    # TODO(crbug.com/414569): L-rebase: Figure out why this assert
    # fails in libnativehelper for -t ba.
    # assert self._ldflags == self._orig_ldflags, (
    #    '{disable|enable}_clang() must be called before modifying ldflags')

  def disable_clang(self):
    assert self._is_clang_enabled
    assert self.is_c_library() or self.is_executable()
    self._check_flags_unmodified()
    self._cflags = list(self._gcc_cflags)
    self._conlyflags = list(self._gcc_conlyflags)
    self._cxxflags = list(self._gcc_cxxflags)
    self._ldflags = list(self._gcc_ldflags)
    self._is_clang_enabled = False

  def enable_clang(self):
    assert not self._is_clang_enabled
    assert self.is_c_library() or self.is_executable()
    self._check_flags_unmodified()
    self._update_flags_for_clang()
    self._is_clang_enabled = True

  def enable_cxx11(self):
    assert self.is_c_library() or self.is_executable()
    self._is_cxx11_enabled = True

  def enable_clang_linker(self):
    assert self.is_c_library() or self.is_executable()
    self._is_clang_linker_enabled = True

  def is_logtag_emission_enabled(self):
    return self._is_logtag_emission_enabled

  def disable_logtag_emission(self):
    self._is_logtag_emission_enabled = False

  def set_install_path(self, value):
    self._generator_args['install_path'] = value

  def get_generator_args(self):
    return self._generator_args

  def export_intermediates(self, files):
    self._check_package_or_java_library()
    self._exported_intermediates += files

  def get_exported_intermediates(self):
    return self._exported_intermediates

  def get_cflags(self):
    self._check_c_library_or_executable()
    return self._cflags

  def get_conlyflags(self):
    self._check_c_library_or_executable()
    return self._conlyflags

  def get_cxxflags(self):
    self._check_c_library_or_executable()
    return self._cxxflags

  def get_asmflags(self):
    self._check_c_library_or_executable()
    return self._asmflags

  def get_ldflags(self):
    self._check_c_library_or_executable()
    return self._ldflags

  def get_includes(self):
    self._check_c_library_or_executable()
    return self._includes

  def get_sys_includes(self):
    self._check_c_library_or_executable()
    return self._sys_includes

  def get_sources(self):
    self._check_c_library_or_executable_or_java()
    return self._sources

  def get_static_deps(self):
    self._check_c_library_or_executable()
    return self._static_deps

  def get_whole_archive_deps(self):
    """Returns list of static dependencies which should
    be included as whole archives."""
    self._check_c_library_or_executable()
    return self._whole_archive_deps

  def get_shared_deps(self):
    self._check_c_library_or_executable()
    return self._shared_deps

  def get_addld_deps(self):
    self._check_c_library_or_executable()
    return self._addld_deps

  def get_implicit_deps(self):
    self._check_c_library_or_executable()
    return self._implicit_deps

  def set_instances_count(self, count):
    """Sets allowable instances count for a C archive. Default is 1."""
    self._check_c_archive()
    self.get_generator_args()['instances'] = count

  def force_optimization(self):
    self._check_c_library_or_executable()
    self._force_optimization = True

  def get_aapt_flags(self):
    self._check_package_or_java_library()
    return self._aapt_flags

  def get_aapt_manifest(self):
    self._check_package_or_java_library()
    return self._aapt_manifest

  def get_copy_headers(self):
    self._check_c_library_or_executable()
    return self._copy_headers

  def get_copy_headers_to(self):
    self._check_c_library_or_executable()
    return self._copy_headers_to

  def remove_c_or_cxxflag(self, flag):
    """Removes all uses of a given C or C++ flag."""
    self._check_c_library_or_executable()
    for flags in (self._cflags, self._conlyflags, self._cxxflags):
      while flag in flags:
        flags.remove(flag)

  def replace_c_or_cxxflag(self, before, after):
    """Replaces all existing flag |before| with |after| in C or C++ flag."""
    self._check_c_library_or_executable()
    for flags in (self._cflags, self._conlyflags, self._cxxflags):
      if before in flags:
        while before in flags:
          flags.remove(before)
        flags.append(after)

  def add_disabled_tests(self, *disabled_tests):
    """Add tests to be disabled."""
    if not self.is_target_test_executable():
      raise Exception('Can only call this function for a test executable')
    self._disabled_tests += list(disabled_tests)

  def get_disabled_tests(self):
    """Get a list containing disabled tests."""
    if not self.is_target_test_executable():
      raise Exception('Can only call this function for a test executable')
    return self._disabled_tests

  def add_qemu_disabled_tests(self, *disabled_tests):
    """Add tests to be disabled on QEMU."""
    if not self.is_target_test_executable():
      raise Exception('Can only call this function for a test executable')
    self._qemu_disabled_tests += list(disabled_tests)

  def get_qemu_disabled_tests(self):
    """Get a list containing tests that are disabled only on QEMU."""
    if not self.is_target_test_executable():
      raise Exception('Can only call this function for a test executable')
    return self._qemu_disabled_tests

  def _check_c_archive(self):
    if not self.is_static():
      raise Exception('Can only call this function for a C archive')

  def _check_c_library_or_executable(self):
    if not self.is_c_library() and not self.is_executable():
      raise Exception('Can only call this function for a C library or '
                      'an executable')

  def _check_c_library_or_executable_or_java(self):
    if not (self.is_c_library() or self.is_executable() or
            self.is_java_library()):
      raise Exception('Can only call this function for a C library, an '
                      'executable, or a Java library')

  def _check_package_or_java_library(self):
    if not self.is_package() and not self.is_java_library():
      raise Exception('Can only call this function for a package or library')

  def _check_package(self):
    if not self.is_package():
      raise Exception('Can only call this function for a package')

  def get_required_raw_var(self, name):
    return self._vars_helper.get_required(name)

  def get_optional_raw_var(self, name, def_value):
    return self._vars_helper.get_optional(name, default=def_value)

  def add_extra_rule(self, name, command, desc):
    self._extra_rules.append({'name': name, 'command': command, 'desc': desc})

  def add_extra_build(self, output, rule, input):
    self._extra_builds.append({'output': output, 'rule': rule, 'input': input})

  def add_extra_notice(self, notice):
    self._extra_notices.append(notice)

  def add_extra_install_to_root(self, output, input):
    self._extra_install_to_root.append({'output': output, 'input': input})

  def _get_extra_rules(self):
    return self._extra_rules

  def _get_extra_builds(self):
    return self._extra_builds

  def _get_extra_install_to_root(self):
    return self._extra_install_to_root

  def get_extra_notices(self):
    return self._extra_notices

  def set_canned(self, canned):
    self._is_canned = canned

  def is_canned(self):
    return self._is_canned

  def get_generated_sources(self):
    assert self.is_java_library()
    return self._generated_sources

  def is_prebuilt(self):
    return (self._build_type == BUILD_TYPE_PREBUILT)

  def is_prebuilt_jar(self):
    return self._prebuilt_class == 'JAVA_LIBRARIES'

  def is_prebuilt_shared_library(self):
    return self._prebuilt_class == 'SHARED_LIBRARIES'

  def is_prebuilt_for_host(self):
    return self._prebuilt_for_host

  def get_prebuilt_src_path(self):
    return self._prebuilt_src_path

  def get_prebuilt_intermediate_path(self):
    return self._prebuilt_intermediate_path

  def get_prebuilt_install_path(self):
    return self._prebuilt_install_path

  def is_prebuilt_install_to_root_dir(self):
    return self._prebuilt_install_to_root_dir

  def set_prebuilt_install_to_root_dir(self, value):
    assert self.is_prebuilt()
    self._prebuilt_install_to_root_dir = value


def _dedup_include_paths(include_paths, all_paths):
  result = []
  for path in include_paths:
    if path and path not in all_paths:
      all_paths.add(path)
      result.append(path)
  return result


def _emit_header_copy_rules(n, vars):
  copied_headers = []
  if vars.get_copy_headers_to():
    for header in vars.get_copy_headers():
      copied_header = os.path.join(vars.get_copy_headers_to(),
                                   os.path.basename(header))
      copied_headers.append(copied_header)
      n.build(copied_header,
              'install',
              os.path.join(vars.get_path(), header))
  return copied_headers


def _emit_compile_sources_rules(n, vars):
  files = vars.get_sources()
  if vars.get_implicit_deps():
    deps = vars.get_implicit_deps()
    # .inc is a header file for .S or a generated header file by llvm-tblgen.
    # .gen is also a generated header file by llvm-tblgen.
    header_exts = ['.gen', '.h', '.inc']
    deps_h = filter(lambda f: os.path.splitext(f)[1] in header_exts, deps)
    deps_others = filter(lambda f: os.path.splitext(f)[1] not in header_exts,
                         deps)
    n.build_default(files, implicit=deps_others, order_only=deps_h)
  else:
    n.build_default(files)


def _generate_for_shared_or_executable(vars, n, copied_headers):
  for dep in vars.get_static_deps():
    n.add_library_deps(dep + '.a')
  for dep in vars.get_whole_archive_deps():
    n.add_whole_archive_deps(dep + '.a')
  for dep in vars.get_shared_deps():
    n.add_library_deps(dep + '.so')
  n.add_libraries(*vars.get_addld_deps())
  if vars.is_host_shared():
    # Check undefined symbols in host shared libraries at the link time.
    # Note that this cannot be done for target shared libraries, because
    # certain dependencies cannot be resolved while building Android shared
    # libraries for the target (ex. __android_log_print() is in libcommon.a,
    # which will be resolved when linking the main nexe).
    return n.link(allow_undefined=False, order_only=copied_headers)
  else:
    return n.link(order_only=copied_headers)


def _generate_out_libs(n, vars, copied_headers):
  if vars.is_shared() or vars.is_executable():
    return _generate_for_shared_or_executable(vars, n, copied_headers)
  else:
    return n.archive(order_only=copied_headers)


def _append_out_lib_deps(out_lib_deps, out_libs):
  if out_lib_deps is not None:
    for lib in out_libs:
      out_lib_deps.append(lib)


def _add_compiler_flags(n, vars):
  for f in vars.get_cflags():
    n.add_compiler_flags(f)
  for f in vars.get_conlyflags():
    n.add_c_flags(f)
  for f in vars.get_cxxflags():
    n.add_cxx_flags(f)
  for f in vars.get_ldflags():
    n.add_ld_flags(f)
  for f in vars.get_asmflags():
    n.add_asm_flag(f)

  if vars._force_optimization and not OPTIONS.is_optimized_build():
    ninja_generator.CNinjaGenerator.emit_optimization_flags(n, True)


def _generate_c_ninja(vars, out_lib_deps):
  extra_args = dict(vars.get_generator_args())

  extra_args['enable_logtag_emission'] = vars.is_logtag_emission_enabled()
  extra_args['extra_notices'] = vars.get_extra_notices()
  extra_args['enable_clang'] = vars.is_clang_enabled()
  extra_args['enable_cxx11'] = vars.is_cxx11_enabled()
  extra_args['notices_only'] = vars.is_notices()
  extra_args['enable_libcxx'] = vars._is_libcxx_enabled

  if vars.is_shared() or vars.is_target_executable():
    extra_args['use_clang_linker'] = vars.is_clang_linker_enabled()
    n = SharedObjectNinjaGenerator(vars.get_module_name(), host=vars.is_host(),
                                   **extra_args)
  elif vars.is_target_test_executable():
    n = TestNinjaGenerator(vars.get_module_name(), host=vars.is_host(),
                           use_default_main=False, **extra_args)
    n.add_disabled_tests(*vars.get_disabled_tests())
    n.add_qemu_disabled_tests(*vars.get_qemu_disabled_tests())
  elif vars.is_host_executable():
    n = ExecNinjaGenerator(vars.get_module_name(), host=vars.is_host(),
                           **extra_args)
  else:
    n = ArchiveNinjaGenerator(vars.get_module_name(), host=vars.is_host(),
                              **extra_args)

  # Reset any defaults that our NinjaGenerator had.
  n.variable('asmflags', '$asmflags')
  n.variable('cflags', '$cflags')
  n.variable('cxxflags', '$cxxflags')

  if vars.is_host():
    # Host targets link against glibc instead of bionic.
    ldflags_to_remove = ['-nostdlib', '-nodefaultlibs']
    for ldflag in ldflags_to_remove:
      if ldflag in vars.get_ldflags():
        vars.get_ldflags().remove(ldflag)

  _add_compiler_flags(n, vars)

  # Build lists of includes.
  all_paths = set()  # TODO(igorc): Move this to _clean_c_library_vars()
  n.add_include_paths(*_dedup_include_paths(vars.get_includes(), all_paths))
  n.add_system_include_paths(
      *_dedup_include_paths(vars.get_sys_includes(), all_paths))

  _add_extra_builds(n, vars)

  copied_headers = _emit_header_copy_rules(n, vars)
  _emit_compile_sources_rules(n, vars)

  out_libs = _generate_out_libs(n, vars, copied_headers)
  _append_out_lib_deps(out_lib_deps, out_libs)

  if vars.is_canned():
    filename = '%s.so' % vars.get_module_name()
    # TODO(crbug.com/484758): Install the file to /vendor/lib-x86 when the
    # file is for x86 (EM_386).
    n.install_to_root_dir(
        os.path.join('vendor/lib-armeabi-v7a', filename),
        os.path.join('canned/target/android/vendor/lib-neon', filename))

  if vars.is_target_test_executable():
    n.run(out_libs, enable_valgrind=OPTIONS.enable_valgrind())


def _fix_relative_resource_path(res, path):
  """Fixes a relative generated path that make_to_ninja cannot expand correctly.
  """
  res = re.sub(
      (r'/target/common/make_to_ninja/out/target/product/'
       r'generic(_x86|_x86_64)?/obj'),
      '/target/common/android_gen_sources',
      res)
  res = os.path.join(staging.as_staging(path), res)
  return os.path.abspath(res)


def _generate_java_ninja(vars):
  sources = vars.get_sources()
  java_sources = [x for x in sources if x.endswith('.java')]
  aidl_sources = [x for x in sources if x.endswith('.aidl')]
  base_path = vars.get_path()
  logtags = [
      os.path.join(base_path, x) for x in sources if x.endswith('.logtags')]
  # JarNinjaGenerator assumes |sources| contains only .java, .aidl, and
  # .logtags files.
  source_count = len(java_sources) + len(aidl_sources) + len(logtags)
  assert source_count == len(sources), sources

  # AAPT flags might contain extra packages. Extract them to let the
  # JarNinjaGenerator expose these extra dependencies.
  aapt_flags = None
  extra_packages = None
  manifest_path = None
  if vars._aapt_flags:
    aapt_flags = []
    original_aapt_flags = vars._aapt_flags
    i = 0
    while i < len(original_aapt_flags):
      if original_aapt_flags[i] == '--extra-packages':
        if not extra_packages:
          extra_packages = []
        extra_packages.append(original_aapt_flags[i + 1])
        i += 1
      else:
        aapt_flags.append(original_aapt_flags[i])
      i += 1
    framework_res_jar = build_common.get_build_path_for_apk(
        'framework-res', 'R/framework-res.apk')
    aapt_flags.extend(['-I', framework_res_jar])
    vars._aapt_flags = aapt_flags
    vars._local_resource_dirs = [
        _fix_relative_resource_path(res, vars.get_path())
        for res in vars._local_resource_dirs]
    manifest_path = vars.get_aapt_manifest()

  # Add --non-constant-id to prevent inlining constants when building a static
  # java library in the same way as static_java_library.mk.
  if vars.is_static_java_library():
    if aapt_flags is None:
      aapt_flags = []
    aapt_flags.append('--non-constant-id')

  n = JarNinjaGenerator(vars.get_module_name(), base_path=base_path,
                        install_path='/system/framework',
                        resource_subdirectories=vars._local_resource_dirs,
                        aapt_flags=aapt_flags, extra_packages=extra_packages,
                        include_aidl_files=aidl_sources,
                        dex_preopt=vars._dex_preopt,
                        java_resource_dirs=vars._java_resource_dirs,
                        static_library=vars.is_static_java_library(),
                        jarjar_rules=vars._jarjar_rules,
                        dx_flags=vars._dx_flags, built_from_android_mk=True,
                        manifest_path=manifest_path)
  n.add_aidl_include_paths(*vars._aidl_includes)
  n.add_java_files(java_sources)

  generated_sources = vars.get_generated_sources()
  if generated_sources:
    n.add_java_files(generated_sources, base_path=None)

  n.add_built_jars_to_classpath(*vars._java_libraries)
  n.add_extracted_jar_contents(*vars._static_java_libraries)
  n.build_and_add_aidl_generated_java()
  if logtags:
    n.build_and_add_logtags(logtag_files=logtags)
  n.build_and_add_resources()
  n.build_all_added_sources()
  n.archive()
  if not vars.is_static_java_library():
    n.install()


def _generate_package_ninja(vars, out_lib_deps, out_intermediates):
  module_name = vars.get_module_name()
  path = vars.get_path()
  manifest = vars.get_aapt_manifest()
  aapt_flags = vars.get_aapt_flags()
  implicit = []

  for i, flag in enumerate(aapt_flags[:-1]):
    if flag == '-I':
      implicit.append(aapt_flags[i + 1])

  intermediates = vars.get_exported_intermediates()
  extra_args = vars.get_generator_args()

  n = AaptNinjaGenerator(module_name, path, manifest, intermediates,
                         implicit=implicit, **extra_args)

  for flag in aapt_flags:
    n.add_aapt_flag(flag)

  # This is present in android/frameworks/webview/chromium/chromium.mk to
  # overlay resources from webview into framework-res.  It is another example
  # of a global Makefile variable like global include exports.
  PRODUCT_PACKAGE_OVERLAYS = ['android/frameworks/webview/chromium/overlay']

  resource_path = os.path.join(path, 'res')
  for p in PRODUCT_PACKAGE_OVERLAYS:
    p = staging.as_staging(p)
    # Overlays contain resources paths relative to ANDROID_ROOT
    relative_resource_path = os.path.relpath(
        resource_path, staging.as_staging('android'))
    overlay_path = os.path.join(p, relative_resource_path)
    if os.path.exists(overlay_path):
      n.add_resource_paths([overlay_path])
  # Order is important here.  The last resource path is considered the package's
  # resource path, while earlier resource paths are considered overlay paths.
  n.add_resource_paths([resource_path])

  _add_extra_builds(n, vars)

  n.package()

  resource_generated = n.get_resource_generated_path()
  for intermediate in intermediates:
    out_intermediates.append(os.path.join(resource_generated, intermediate))


def _generate_prebuilt_ninja(vars):
  assert not vars.is_prebuilt_for_host()
  src_path = vars.get_prebuilt_src_path()
  intermediate_path = vars.get_prebuilt_intermediate_path()
  install_path = vars.get_prebuilt_install_path()
  install_to_root_dir = vars.is_prebuilt_install_to_root_dir()

  n = NinjaGenerator(vars.get_module_name(), base_path=vars.get_path())

  n.add_notice_sources([src_path])

  if intermediate_path:
    n.build(intermediate_path, 'cp', src_path)
    n.install_to_build_dir(intermediate_path, src_path)

  if install_path is not None:
    if install_to_root_dir:
      n.install_to_root_dir("system/" + install_path, src_path)
    else:
      n.install_to_build_dir(install_path, src_path)


def _add_extra_builds(n, vars):
  for rule in vars._get_extra_rules():
    n.rule(rule['name'], command=rule['command'], description=rule['desc'])
  for build in vars._get_extra_builds():
    n.build(build['output'], build['rule'], build['input'])
  for install in vars._get_extra_install_to_root():
    n.install_to_root_dir(install['output'], install['input'])


def _rel_from_root(path):
  """Convert directory names from absolute to relative path.

  The rest of our build system can only handle relative paths.
  """
  if path.startswith(_ARC_ROOT):
    return os.path.relpath(path, _ARC_ROOT)
  return path


def _get_resource_relpath(base_path, path):
  """Convert |path| for resource directory to |base_path| relative path.

  A resource path picked up from LOCAL_RESOURCE_DIR can be an absolute path, or
  a relative path to 'android' directory. This function converts a path in these
  two cases to a relative path to |base_path|.
  """
  if os.path.isabs(path):
    abs_path = path
  else:
    abs_path = os.path.abspath(
        staging.as_staging(os.path.join('android', path)))
  return os.path.relpath(abs_path, base_path)


def _adjust_gen_output(path):
  if path.startswith(_MAKE_TO_NINJA_SUBDIR):
    path = os.path.relpath(path, _MAKE_TO_NINJA_SUBDIR)
  # The canned build files use 'generic' as a PRODUCT_DEVICE on ARMv7, and
  # 'generic_x86' on x86.
  if OPTIONS.is_arm():
    prefix = os.path.join('out', 'target', 'product', 'generic')
  elif OPTIONS.is_x86_64():
    prefix = os.path.join('out', 'target', 'product', 'generic_x86_64')
  else:
    prefix = os.path.join('out', 'target', 'product', 'generic_x86')
  for directory in ['obj', 'gen']:
    local_prefix = os.path.join(prefix, directory)
    if path.startswith(local_prefix):
      path = os.path.relpath(path, local_prefix)
      return os.path.join(_ANDROID_TARGET_GEN_SOURCES_DIR, path)

  return path


def _adjust_source_path(path):
  path = _rel_from_root(path)
  if path.startswith(_MAKE_TO_NINJA_SUBDIR):
    path = os.path.relpath(path, _MAKE_TO_NINJA_SUBDIR)
  if path.startswith(build_common.get_staging_root()):
    # Use paths relative to staging as filters and NinjaGenerator's expect it.
    path = os.path.relpath(path, build_common.get_staging_root())
  elif not path.startswith('out'):
    # Assume the paths that do not start with get_staging_root() are relative to
    # the Android top level. In such cases, we need to convert the path to
    # match the layout in staging.
    path = os.path.join('android', path)
  path = _adjust_gen_output(path)
  return path


def _substitute_android_config_include(vars):
  if vars.is_host():
    header_name = '/linux-x86/AndroidConfig.h'
  else:
    header_name = '/target_linux-x86/AndroidConfig.h'
    if not vars.is_host() and OPTIONS.is_arm():
      header_name = '/linux-arm/AndroidConfig.h'

  for i in xrange(len(vars._cflags) - 1):
    if (vars._cflags[i] == '-include' and
        vars._cflags[i + 1].endswith(header_name)):
      vars._cflags[i + 1] = build_common.get_android_config_header(
          vars.is_host())


def _remove_feature_flags(vars):
  # -fPIE should never be used.
  vars.remove_c_or_cxxflag('-fPIE')

  # This option breaks our static initializer checker.
  vars.remove_c_or_cxxflag('-fno-use-cxa-atexit')

  if not vars.get_enable_exceptions():
    # Expat adds this flag. This flag is necessary if a callback function called
    # by expat throws an exception, but our code never does that.
    vars.remove_c_or_cxxflag('-fexceptions')

  # $ANDROID/build/core/combo/TARGET_linux-x86.mk might add these flags that
  # are incompatible with global flags added by emit_common_rules() in
  # build_common.py
  vars.remove_c_or_cxxflag('-fstrict-aliasing')
  if not vars.is_host():
    # Bionic does not support stack protector. See ninja_generator.py for the
    # behavior of NaCl gcc.
    vars.remove_c_or_cxxflag('-fstack-protector')

  # We do not care the binary size when debug info or code is enabled
  # and emit .eh_frame for better backtrace. See also ninja_generator.py.
  if not(OPTIONS.is_debug_info_enabled() or OPTIONS.is_debug_code_enabled()):
    vars.remove_c_or_cxxflag('-funwind-tables')

  # Just in case, remove these flags since they are also incompatible with the
  # global flags added by emit_common_rules().
  vars.remove_c_or_cxxflag('-frtti')
  vars.remove_c_or_cxxflag('-fshort-enums')

  # Remove -ftrapv which is used in some Android.mk files by mistake (see
  # https://code.google.com/p/android/issues/detail?id=62562). We should drop
  # the flag since it slows down the code significantly, and does not work
  # properly under NaCl and BMM where POSIX signals are not supported anyway.
  vars.remove_c_or_cxxflag('-ftrapv')

  # We do not use these flags android/build/core/*/*.mk as these did
  # not give any benefit for us and recent clang does not support
  # them. See get_optimization_cflags in ninja_generator.py for detail.
  vars.remove_c_or_cxxflag('-finline-limit=300')
  vars.remove_c_or_cxxflag('-fno-inline-functions-called-once')


def _adjust_arm_flags(vars):
  vars.remove_c_or_cxxflag('-march=armv7-a')  # we use -mcpu= instead.
  vars.remove_c_or_cxxflag('-mfpu=vfpv3-d16')  # we use -mfpu=neon instead.

  if OPTIONS.is_bare_metal_build():
    # Overwrite -marm flag set in ninja_generator.py if LOCAL_ARM_MODE is set
    # in Android.mk.
    local_arm_mode = vars.get_optional_raw_var('LOCAL_ARM_MODE', None)
    if local_arm_mode:
      vars.get_cflags().append('-m' + local_arm_mode)


def _adjust_target_nacl_common_flags(vars):
  if not vars.is_clang_enabled():
    # Remove options that NaCl gcc does not recognize.
    vars.remove_c_or_cxxflag('-fno-canonical-system-headers')
    # Replace -std=gnu11, -std=gnu++11, and -std=c++11 flags with -std=gnu0x,
    # -std=gnu++0x, and -std=c++0x.
    replace_map = {
        '-std=gnu11': '-std=gnu0x',
        '-std=gnu++11': '-std=gnu++0x',
        '-std=c++11': '-std=c++0x'
    }
    for before, after in replace_map.iteritems():
      vars.replace_c_or_cxxflag(before, after)
  else:
    # Remove options that NaCl clang does not recognize.
    vars.remove_c_or_cxxflag('-no-canonical-prefixes')


def _adjust_target_nacl_i686_flags(vars):
  _adjust_target_nacl_common_flags(vars)
  if vars.is_clang_enabled():
    # Remove options that NaCl clang does not recognize.
    vars.remove_c_or_cxxflag('-march=i686')


def _adjust_target_nacl_x86_64_flags(vars):
  _adjust_target_nacl_common_flags(vars)
  vars.remove_c_or_cxxflag('-m32')
  if '-m32' in vars.get_asmflags():
    vars.get_asmflags().remove('-m32')
  if '-m32' in vars.get_ldflags():
    vars.get_ldflags().remove('-m32')
  vars.remove_c_or_cxxflag('-march=i686')
  if '-march=i686' in vars.get_asmflags():
    vars.get_asmflags().remove('-march=i686')


def _adjust_flags(vars):
  if vars.is_host():
    vars.get_cflags().append('-DHAVE_ARC_HOST')
  else:
    if OPTIONS.is_arm():
      _adjust_arm_flags(vars)

    vars.get_cflags().append('-DHAVE_ARC')

  vars.get_cflags().append('-D_GNU_SOURCE')

  _substitute_android_config_include(vars)
  _remove_feature_flags(vars)

  if not vars.is_host():
    if OPTIONS.is_nacl_i686():
      _adjust_target_nacl_i686_flags(vars)
    elif OPTIONS.is_nacl_x86_64():
      _adjust_target_nacl_x86_64_flags(vars)

    # ARC builds own standard libraries, and should not link with toolchain's
    # libc, which is glibc. Without removing them, it will link toolchain's
    # version even if -nostdlib is specified.
    # There are three way to link binaries against libFOO by Android.mk.
    #  1) LOCAL_LDFLAGS += -lFOO
    #  2) LOCAL_LDLIBS += -lFOO
    #  3) LOCAL_SHARED_LIBRARIES += libFOO
    # 1) is removed here, and 2) is just ignored in make_to_ninja.
    # 3) is replaced with a pathname of a right library built for ARC.
    ldflags = vars.get_ldflags()
    ldflags[:] = [flag for flag in ldflags if
                  flag not in ['-lc', '-ldl', '-lm']]

  if not vars.is_host() and OPTIONS.is_nacl_build():
    # TODO(crbug.com/329434): We might want to enable GNU RELRO. There
    # are two issues around GNU RELRO:
    # - NaCl Binoic loader does not handle PT_GNU_RELRO properly.
    # - This option let the linker use init_array/fini_array instead
    #   of ctors/dtors even on x86. We only support ctors/dtors on
    #   NaCl x86 right now.
    # This flag may appear multiple times.
    while '-Wl,-z,relro' in vars.get_ldflags():
      vars.get_ldflags().remove('-Wl,-z,relro')

  if OPTIONS.is_optimized_build() or vars._force_optimization:
    for flag in ['-O0', '-O1', '-O', '-O2']:
      vars.remove_c_or_cxxflag(flag)
    # -O3, -Os, -Oz, and -Ofast specified in Android.mk will remain as-is.
    # Such an optimization flag overrides -O2 added in emit_common_rules() in
    # ninja_generator.py. Remove '-O2' here too as it should already be
    # present and it would repeat the flag.
    assert '-O2' in ninja_generator.get_optimization_cflags()
  else:
    optimization_cflags = (ninja_generator.get_optimization_cflags() +
                           ninja_generator.get_gcc_optimization_cflags())
    for flag in optimization_cflags:
      vars.remove_c_or_cxxflag(flag)
    # Remove all -O* optimization flags except -O0 so that Android.mk does
    # not override -O0 added by emit_common_rules().
    for flag in ['-O1', '-O', '-O2', '-O3', '-Os', '-Oz', '-Ofast']:
      vars.remove_c_or_cxxflag(flag)

  # Remove -Werror.
  vars.get_cxxflags()[:] = [x for x in vars.get_cxxflags()
                            if not x.startswith('-Werror')]
  vars.get_cflags()[:] = [x for x in vars.get_cflags()
                          if not x.startswith('-Werror')]
  vars.get_conlyflags()[:] = [x for x in vars.get_conlyflags()
                              if not x.startswith('-Werror')]
  # Show warnings when --show-warnings=all or yes is specified.
  vars.get_cflags().extend(OPTIONS.get_warning_suppression_cflags())

  # Android.mk files add these options for ARM. crbug.com/226930
  vars.remove_c_or_cxxflag('-D_FORTIFY_SOURCE=1')
  vars.remove_c_or_cxxflag('-D_FORTIFY_SOURCE=2')
  vars.remove_c_or_cxxflag('-D_FORTIFY_SOURCE=3')


def _clean_c_library_vars(vars):
  """Performs general (module-independent) cleanup on vars for C libraries."""
  _adjust_flags(vars)

  includes = vars.get_includes()
  includes[:] = [_adjust_source_path(x) for x in includes]

  includes = vars.get_sys_includes()
  includes[:] = [_adjust_source_path(x) for x in includes]

  sources = vars.get_sources()
  for i in xrange(len(sources)):
    file = sources[i]
    file = _adjust_source_path(file)
    if file.endswith('.arm') or file.endswith('.neon'):
      # Android appears to declare arm files, but compile the original.
      file = os.path.splitext(file)[0]
    sources[i] = file

  # Save flags that may be restored by disable_clang().
  vars._gcc_cflags = list(vars._cflags)
  vars._gcc_conlyflags = list(vars._conlyflags)
  vars._gcc_cxxflags = list(vars._cxxflags)
  vars._gcc_ldflags = list(vars._ldflags)

  if vars.is_clang_enabled():
    vars._update_flags_for_clang()

  # Keep the original cflags to make sure cflags is not modified
  # before vars.disable_clang() is called.
  vars._orig_cflags = list(vars._cflags)
  vars._orig_conlyflags = list(vars._conlyflags)
  vars._orig_cxxflags = list(vars._cxxflags)
  vars._orig_ldflags = list(vars._ldflags)


def _clean_package_vars(vars):
  """Performs module-independent cleanup on vars for package modules."""
  flags = vars.get_aapt_flags()

  config = vars.get_optional_raw_var('PRODUCT_AAPT_CONFIG', '')
  if config:
    flags.append('-c')
    flags.append(config)

  flags.append('--product')
  flags.append(vars.get_required_raw_var('TARGET_AAPT_CHARACTERISTICS'))

  sdk_version = vars.get_required_raw_var('PLATFORM_SDK_VERSION')
  target_sdk = vars.get_required_raw_var('DEFAULT_APP_TARGET_SDK')
  if sdk_version != target_sdk:
    raise Exception('Unexpected difference in SDK versions: ' +
                    sdk_version + ' vs ' + target_sdk)

  # TODO(crbug.com/442994): L-Rebase: Upstream android includes the
  # framework-res package in some cases and uses --min-sdk-version and
  # --target-sdk-version in others. Since framework-res has metadata that can
  # supercede the flags, always including framework-res is safe, but we should
  # try to not do it unconditionally to be more compatible with upstream android
  # and reduce build times.
  if vars.get_module_name() != 'framework-res':
    framework_res_jar = build_common.get_build_path_for_apk(
        'framework-res', 'R/framework-res.apk')
    flags.extend(['-I', framework_res_jar])

  if '--version-code' not in flags:
    flags.append('--version-code')
    flags.append(sdk_version)

  if '--version-name' not in flags:
    platform_version = vars.get_required_raw_var('PLATFORM_VERSION')
    build = vars.get_required_raw_var('BUILD_NUMBER')
    flags.append('--version-name')
    flags.append(platform_version + '-' + build)


class Filters:
  @staticmethod
  def convert_to_static_lib(vars):
    if vars.is_host():
      return False
    if vars.is_executable():
      return False
    if vars.is_shared():
      vars.set_build_type(BUILD_TYPE_TARGET_STATIC)
    return True

  @staticmethod
  def convert_to_shared_lib(vars):
    if vars.is_host():
      vars.set_build_type(BUILD_TYPE_HOST_SHARED)
    else:
      vars.set_build_type(BUILD_TYPE_TARGET_SHARED)
    return True

  @staticmethod
  def convert_to_notices_only(vars):
    if vars.is_shared():
      vars.set_build_type(BUILD_TYPE_NOTICES_SHARED)
    else:
      vars.set_build_type(BUILD_TYPE_NOTICES_STATIC)
    return True

  @staticmethod
  def exclude_executables(vars):
    if vars.is_host():
      return False
    if vars.is_executable():
      return False
    return True

  @staticmethod
  def exclude_java(vars):
    return not vars.is_java_library()


class MakefileNinjaTranslator:
  """Converts a single make file to ninja files."""

  # Global filters that can modify module variables.
  _global_filters = []

  # Set of all known module names.
  _all_modules = set()

  # List of all make-to-ninja translators ever created.
  _all_translators = []

  def __init__(self, in_file, extra_env_vars=None):
    """Initializes MakefileNinjaTranslator.

    Keyword arguments:
    extra_env_vars -- Extra environment variables set when running "make".
    executables as shared objects.
    """
    in_file = staging.as_staging(in_file)
    workdir = None
    if os.path.isdir(in_file):
      workdir = in_file
      in_file = os.path.join(in_file, 'Android.mk')
    else:
      workdir = os.path.dirname(in_file)

    self._workdir = workdir
    self._in_file = in_file
    self._extra_env_vars = extra_env_vars
    self._filters = []
    self._done_setting_up = False
    self._done_generating = False
    self._vars_list = None
    self._modules = []
    self._out_intermediates = {}
    self._out_libs = []

    MakefileNinjaTranslator._all_translators += [self]

  @staticmethod
  def add_global_filter(filter):
    """Adds a global filter that would run before any module's filter."""
    MakefileNinjaTranslator._global_filters.append(filter)

  @staticmethod
  def get_intermediate_headers_dir():
    return _INTERMEDIATE_HEADERS_DIR

  def transform(self, filter):
    if self._done_setting_up:
      raise Exception('Cannot call transform() after generate()')
    self._filters += [filter]
    return self

  def generate(self, filter=None):
    if filter is not None:
      self.transform(filter)
    self._done_setting_up = True
    self._generate()
    return self

  def _build_vars_list(self):
    if self._vars_list is None:
      if OPTIONS.verbose():
        print 'Converting ' + self._in_file
      self._vars_list = MakefileNinjaTranslator._read_modules(
          self._workdir, self._in_file, self._extra_env_vars)

  def _apply_filters(self, vars):
    """Applies filters and returns True if all filters pass."""
    for filter in MakefileNinjaTranslator._global_filters + self._filters:
      if not filter(vars):
        return False
    return True

  def _check_optimization_flags(self, flags):
    # These optimization flags should be used only once (to override the default
    # '-O2'.) Using them twice or more is error-prone and should always be
    # avoided.
    opt_flags = filter(lambda f: f in ['-O3', '-Os', '-Oz', '-Ofast'], flags)
    if len(opt_flags) > 1:
      raise Exception(
          'Two or more optimization flags are specified for %s: %s' % (
              self._in_file, ' '.join(opt_flags)))
    # Since --opt build uses -O2 as a global flag, make_to_ninja should not
    # add extra -O2 flags.
    if OPTIONS.is_optimized_build():
      assert '-O2' in ninja_generator.get_optimization_cflags()
      if '-O2' in flags:
        raise Exception('Two or more -O2 flags are specified for %s' % (
            self._in_file))

  def _update_and_filter_vars_list(self):
    # Perform general updates and filtering to the list of vars
    for vars in self._vars_list:
      if vars.is_c_library() or vars.is_executable():
        _clean_c_library_vars(vars)
      if vars.is_package():
        _clean_package_vars(vars)
      should_generate = self._apply_filters(vars)

      if should_generate:
        if vars.is_c_library():
          self._check_optimization_flags(vars.get_cxxflags())
          self._check_optimization_flags(
              vars.get_cflags() + vars.get_conlyflags())
        self._modules.append(vars)

  def _generate_module(self, vars):
    if vars.is_c_library():
      _generate_c_ninja(vars, self._out_libs)
    elif vars.is_executable():
      _generate_c_ninja(vars, self._out_libs)
    elif vars.is_java_library():
      _generate_java_ninja(vars)
    elif vars.is_package():
      module_name = vars.get_module_name()
      if module_name in self._out_intermediates:
        raise Exception('Packages with conflicting '
                        'module names are not supported')
      out_intermediates = []
      self._out_intermediates[module_name] = out_intermediates
      _generate_package_ninja(vars, self._out_libs, out_intermediates)
    elif vars.is_prebuilt():
      _generate_prebuilt_ninja(vars)
    else:
      raise Exception('Unsupported build type: ' + vars._build_type)

  def _generate_modules(self):
    if not self._modules:
      raise Exception(
          'No modules were found or all filtered out in ' + self._in_file)
    for vars in self._modules:
      module_name = vars.get_module_name()
      if (module_name, vars.is_host()) in MakefileNinjaTranslator._all_modules:
        # TODO(igorc): Move this to build_common.
        raise Exception('Module name "%s" for %s appears twice' % (
            module_name,
            ('host' if vars.is_host() else 'target')))
      # Add is_host(), as the name conflict should be detected separately for
      # the target and the host.
      MakefileNinjaTranslator._all_modules.add((module_name, vars.is_host()))
      self._generate_module(vars)

  def _generate(self):
    if not self._done_setting_up:
      raise Exception('generate() not called for ' + self._in_file)
    if self._done_generating:
      return

    self._build_vars_list()
    self._update_and_filter_vars_list()
    self._generate_modules()
    self._done_generating = True

  def get_out_intermediates(self, module_name):
    self._generate()
    return self._out_intermediates[module_name]

  @staticmethod
  def _read_modules(workdir, file_name, extra_env_vars):
    make_output_lines = _run_make(workdir, file_name, extra_env_vars)

    vars_list = []
    build_type = ''
    build_file = ''
    build_lines = []
    for line in make_output_lines:
      if line.startswith(_VARS_PREFIX):
        if build_type:
          # Generate ninja for the previous lines
          raw_vars = _parse_vars(build_lines)
          vars_list += [MakeVars(build_type, build_file, raw_vars)]
        line = line[len(_VARS_PREFIX):]
        build_type, build_file = line.split(' ')
        build_lines = []
        continue
      build_lines.append(line)
    if build_type:
      # Generate ninja for the previous lines
      raw_vars = _parse_vars(build_lines)
      vars_list += [MakeVars(build_type, build_file, raw_vars)]
    return vars_list


def run(path):
  MakefileNinjaTranslator(path).generate(Filters.exclude_executables)


def run_for_static(path):
  MakefileNinjaTranslator(path).generate(Filters.convert_to_static_lib)


def run_for_c(path):
  def _filter(vars):
    return Filters.exclude_executables(vars) and Filters.exclude_java(vars)
  MakefileNinjaTranslator(path).generate(_filter)
