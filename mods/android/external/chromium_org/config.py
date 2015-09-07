# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build libwebviewchromium code."""

import os

from src.build import build_common
from src.build import make_to_ninja
from src.build import ninja_generator_runner
from src.build import staging
from src.build.build_options import OPTIONS

# The stlport include path. The extra '.' is injected by the Android makefile
# scripts and is needed to match.
_STLPORT_INCLUDE_PATH = 'android/./external/stlport/stlport'

# Some modules are built twice in -t=nx. Use this set to keep track of the
# already-seen modules.
_SEEN_MODULES = {}


def _update_flags(vars, cflags_to_add, flags_to_remove):
  for cflag in cflags_to_add:
    vars.get_cflags().append(cflag)
  for flag in flags_to_remove:
    if flag in vars.get_asmflags():
      vars.get_asmflags().remove(flag)
    if flag in vars.get_cflags():
      vars.get_cflags().remove(flag)
    if flag in vars.get_cxxflags():
      vars.get_cxxflags().remove(flag)
    if flag in vars.get_ldflags():
      vars.get_ldflags().remove(flag)


def _filter_cflags_for_chromium_org(vars):
  append_cflags = []
  # TODO(http://crbug.com/509945): Use Gold once it's ready.
  strip_flags = ['-fuse-ld=gold', '-march=pentium4', '-finline-limit=64']
  if OPTIONS.is_arm():
    # ARM clang does not support these flags.
    strip_flags.extend(['-fno-partial-inlining', '-fno-early-inlining',
                        '-fno-tree-copy-prop', '-fno-tree-loop-optimize',
                        '-fno-move-loop-invariants',
                        '-Wa,-mimplicit-it=always'])
  if not OPTIONS.is_bare_metal_build():
    # nacl-clang supports -Oz, which is more aggressive than -Os.
    strip_flags.append('-Os')
  # TODO(crbug.com/346783): Remove this once we NaCl'ize PageAllocator.cpp.
  # It is only necessary for NaCl, but we do this for linux as well
  # to minimize platform differences.
  append_cflags.append('-DMEMORY_TOOL_REPLACES_ALLOCATOR')
  _update_flags(vars, append_cflags, strip_flags)
  # -finline-limit=32 experimentally provides the smallest binary across
  # the ni and nx targets.  Also specify -finline-functions so all functions
  # are candidates for inlining.
  size_opts = ['-finline-limit=32', '-finline-functions']
  if not OPTIONS.is_bare_metal_build():
    # -Oz is not valid for asmflags, so just add it for C and C++.
    vars.get_conlyflags().append('-Oz')
    vars.get_cxxflags().append('-Oz')
  # With these flags, compilers will not emit .eh_frame* sections and
  # the size of libwebviewchromium.so reduces from 84MB to 75MB on L.
  # As these options disables libgcc's _Unwind_Backtrace, we keep
  # using them for non-production build. Note GDB and breakpad can
  # produce backtraces without .eh_frame.
  #
  # It is intentional this condition is inconsistent with
  # ninja_generator.py and make_to_ninja.py. Removing .eh_frame from
  # production binary did not make a significant difference for file
  # size of L. We would rather prefer keeping .eh_frame for
  # _Unwind_Backtrace.
  if not OPTIONS.is_debug_code_enabled():
    size_opts += ['-fno-unwind-tables', '-fno-asynchronous-unwind-tables']
  vars.get_cflags()[:] = vars.get_cflags() + size_opts
  # dlopen fails for the following undefined reference without -mthumb
  # _ZN7WebCore26feLightingConstantsForNeonEv
  # TODO(crbug.com/358333): Investigate if this is actually needed.
  if OPTIONS.is_arm():
    vars.get_cflags().append('-mthumb')
  # OpenSSL makes wrong assumption that sizeof(long) == 8 under x86_64.
  # Remove the x86_64-specific include path to fall back to x86 config.
  # Note that this include path is set in many modules depending on OpenSSL,
  # not limited to third_party_openssl_openssl_gyp.a itself.
  if OPTIONS.is_nacl_x86_64():
    openssl_x64_include = (
        'android/external/chromium_org/third_party/openssl/config/x64')
    includes = vars.get_includes()
    if openssl_x64_include in includes:
      includes.remove(openssl_x64_include)


def _filter_ldflags_for_libwebviewchromium(vars):
  if OPTIONS.is_bare_metal_build() or OPTIONS.is_nacl_build():
    # We need to pass in --no-keep-memory or ld runs out of memory linking.
    vars.get_ldflags().append('-Wl,--no-keep-memory')
  # --no-undefined allows undefined symbols to be present in the linked .so
  # without errors, which is what we want so they are resolved at runtime.
  vars.get_ldflags().remove('-Wl,--no-undefined')

  # TODO(crbug.com/489972): Suppress warnings caused by hidden skia symbols.
  vars.get_ldflags().remove('-Wl,--fatal-warnings')

  for idx, flag in enumerate(vars.get_ldflags()):
    if 'android_exports.lst' in flag:
      version_script = os.path.join(build_common.get_target_common_dir(),
                                    'android_gen_sources/GYP',
                                    'shared_intermediates/android_exports.lst')
      vars.get_ldflags()[idx] = '-Wl,--version-script=' + version_script

  if OPTIONS.is_nacl_build():
    # This causes libdl.so to be dropped for some reason, even when it provides
    # the reference to the required dlerror function. Remove it.
    vars.get_ldflags().remove('-Wl,--as-needed')


def _filter_deps_for_libwebviewchromium(vars, skip):
  # Link android/external/libvpx instead of one from chromium_org.
  vars.get_static_deps().append('libvpx')
  for s in skip:
    vars.get_static_deps().remove(s)


def _filter_sources_for_chromium_org(vars):
  # Strip out protobuf python generators.  These are canned in GYP along with
  # their header output.
  source_pattern_blacklist = ['_pb2.py', 'rule_trigger']
  # Exclude OS compatibility files exporting libc symbols that were missing in
  # old Android Bionic, but are conflicting with those in KitKat Bionic.
  source_pattern_blacklist.append('os_compat')
  sources = vars.get_sources()
  for pattern in source_pattern_blacklist:
    sources[:] = [s for s in sources if pattern not in s]


def _filter_params_for_v8(vars):
  # Switch V8 to always emit ARM code and use simulator to run that on
  # x86 NaCl.
  # Also disable snapshots as they are not working in ARC yet.
  if OPTIONS.is_nacl_build():
    if '-DV8_TARGET_ARCH_IA32' in vars.get_cflags():
      vars.get_cflags().remove('-DV8_TARGET_ARCH_IA32')
    if '-DV8_TARGET_ARCH_X64' in vars.get_cflags():
      vars.get_cflags().remove('-DV8_TARGET_ARCH_X64')
    vars.get_cflags().append('-DV8_TARGET_ARCH_ARM')
    vars.get_cflags().append('-D__ARM_ARCH_7__')
  sources = vars.get_sources()
  new_sources = []
  v8_src = 'android/external/chromium_org/v8/src/'
  for path in sources:
    if OPTIONS.is_nacl_build():
      if path.startswith(v8_src + 'x64/'):
        path = v8_src + 'arm/' + os.path.basename(path).replace('x64', 'arm')
      if path.startswith(v8_src + 'ia32/'):
        path = v8_src + 'arm/' + os.path.basename(path).replace('ia32', 'arm')
    if path.endswith('/snapshot.cc'):
      path = 'android/external/chromium_org/v8/src/snapshot-empty.cc'
    new_sources.append(path)
  if not OPTIONS.is_arm() and OPTIONS.is_nacl_build():
    new_sources.append(v8_src + 'arm/constants-arm.cc')
    new_sources.append(v8_src + 'arm/simulator-arm.cc')
  vars.get_sources()[:] = new_sources


def _filter_sources_for_openssl(vars):
  if OPTIONS.is_nacl_build():
    # Disable asm enabling defines.
    flags_to_remove = ['-DAES_ASM', '-DGHASH_ASM', '-DMD5_ASM',
                       '-DOPENSSL_BN_ASM_PART_WORDS', '-DOPENSSL_BN_ASM_GF2m',
                       '-DOPENSSL_BN_ASM_MONT', '-DOPENSSL_CPUID_OBJ',
                       '-DSHA1_ASM', '-DSHA256_ASM', '-DSHA512_ASM']
    cflags_to_add = ['-DOPENSSL_NO_ASM', '-DOPENSSL_NO_INLINE_ASM']
    _update_flags(vars, cflags_to_add, flags_to_remove)
    sources = vars.get_sources()
    # Drop asm sources, which don't work under NaCl for now. These asm files
    # are for i686 or x86_64.
    sources[:] = filter(lambda s: not s.endswith('.S') and '/asm/' not in s,
                        sources)
    # Build C implementations instead.
    replacement_sources = [
        'aes/aes_cbc.c',
        'aes/aes_core.c',
        'bn/bn_asm.c',
        'mem_clr.c']
    if OPTIONS.is_i686():
      replacement_sources.extend([
          'bf/bf_enc.c',
          'des/des_enc.c',
          'des/fcrypt_b.c'])
    if OPTIONS.is_x86_64():
      replacement_sources.extend([
          'rc4/rc4_enc.c',
          'rc4/rc4_skey.c'])
    for s in replacement_sources:
      sources.append(
          'android/external/chromium_org/third_party/openssl/openssl/crypto/'
          + s)
    if OPTIONS.is_x86_64():
      # Replace the sources that does not seem to work under NaCl x86_64.
      # Especially chacha_vec.c includes code that assumes the bit size of
      # size_t is 64 bit, which is not true under NaCl x86_64.
      sources.remove('android/external/chromium_org/third_party/openssl/'
                     'openssl/crypto/chacha/chacha_vec.c')
      sources.append('android/external/chromium_org/third_party/openssl/'
                     'openssl/crypto/chacha/chacha_enc.c')
      sources.remove('android/external/chromium_org/third_party/openssl/'
                     'openssl/crypto/poly1305/poly1305_vec.c')
      sources.append('android/external/chromium_org/third_party/openssl/'
                     'openssl/crypto/poly1305/poly1305.c')


def _filter_sources_for_opus(vars):
  # TODO(crbug.com/414569): L-Rebase: This ARM-specific assembly file can be
  # generated using a perl script, similar to how libvpx uses ads2gas.pl. For
  # now, the generated file will be added directly to the mods/ directory, but
  # we should centralize all gnu assembler-conversion somewhere.
  if OPTIONS.is_arm():
    sources = vars.get_sources()
    pitch_correction_asm = 'celt_pitch_xcorr_arm_gnu.S'
    sources.remove(os.path.join(vars.get_android_gen_path(),
                                pitch_correction_asm))
    sources.append(os.path.join(vars.get_path(), 'third_party', 'opus', 'src',
                                'celt', 'arm', pitch_correction_asm))
  # Opus complains when not building with optimization. Always enable them.
  vars.force_optimization()


def _filter_sources_for_webkit_asm(vars):
  # Add one arch-specific assembly.
  sources = vars.get_sources()
  path = os.path.join(vars.get_path(),
                      'third_party/WebKit/Source/platform/heap/asm')
  if OPTIONS.is_i686():
    sources.append(os.path.join(path, 'SaveRegisters_x86.S'))
  elif OPTIONS.is_x86_64():
    sources.append(os.path.join(path, 'SaveRegisters_x86_64.S'))


def _get_chromium_modules_to_skip(vars):
  skip = [
      # Sandbox libraries are not used, and require extra mods.
      'sandbox_sandbox_services_gyp',
      'sandbox_seccomp_bpf_gyp',
      # We are building libvpx elsewhere.
      'third_party_libvpx_libvpx_gyp']
  if OPTIONS.is_x86():
    skip.extend([
        # These are x86 specific asm builds which are optional.
        'media_media_asm_gyp',
        'media_media_mmx_gyp',
        'media_media_sse2_gyp',
        # TODO(crbug.com/441473): L-Rebase: These modules require yasm.
        'third_party_libvpx_libvpx_intrinsics_mmx_gyp',
        'third_party_libvpx_libvpx_intrinsics_sse2_gyp',
        'third_party_libvpx_libvpx_intrinsics_ssse3_gyp'])
  return skip


def _filter_target_modules(vars):
  skip = _get_chromium_modules_to_skip(vars)
  module_name = vars.get_module_name()
  if module_name in skip:
    return False
  if module_name in _SEEN_MODULES:
    return False
  _SEEN_MODULES[module_name] = True
  if module_name == 'libwebviewchromium':
    _filter_deps_for_libwebviewchromium(vars, skip)
    _filter_ldflags_for_libwebviewchromium(vars)
  elif module_name.startswith('v8_tools_gyp_'):
    _filter_params_for_v8(vars)
  elif module_name == 'third_party_harfbuzz_ng_harfbuzz_ng_gyp':
    build_common.filter_params_for_harfbuzz(vars)
  elif module_name == 'third_party_openssl_openssl_gyp':
    _filter_sources_for_openssl(vars)
  elif module_name == 'third_party_opus_opus_gyp':
    _filter_sources_for_opus(vars)
  elif (module_name ==
        'third_party_WebKit_Source_platform_blink_heap_asm_stubs_gyp'):
    _filter_sources_for_webkit_asm(vars)
  _filter_cflags_for_chromium_org(vars)
  _filter_sources_for_chromium_org(vars)
  return True


# This is the ninja that generates libwebviewchromium.
def _generate_chromium_org_ninja(group):
  def _filter(vars):
    if vars.is_host():
      return False

    if vars.is_java_library():
      return False

    assert vars.is_target()

    vars.enable_clang()
    vars.enable_cxx11()
    vars.get_shared_deps().append('libcompiler_rt')

    # Force optimization since libwebviewchromium.so is too huge to fit in
    # memory space for NaCl debug build. See: http://crbug.com/475268
    if OPTIONS.is_nacl_build:
      vars.force_optimization()

    # Both stlport and Bionic libstdc++ are in the include path. We need to move
    # stlport to the very beginning of the list so it can have priority over
    # libstdc++.
    if _STLPORT_INCLUDE_PATH in vars.get_includes():
      vars.get_includes().remove(_STLPORT_INCLUDE_PATH)
      vars.get_sys_includes().insert(0,
                                     staging.as_staging(_STLPORT_INCLUDE_PATH))
    vars.get_cflags().extend([
        # Add a deref() function to ref-counted classes so they can be used with
        # the Chromium wrappers for ref-counted objects.
        '-DSK_REF_CNT_MIXIN_INCLUDE="SkRefCnt_android.h"',
        # Lower the priority of the external/skia includes so that the
        # chromium_org/third_party/skia includes are used.
        '-isystem',
        staging.as_staging('android/external/skia/include/core')])

    # Since all arch-specific .asm files are built as part of a previous
    # compilation step in Android, all the .o files they produce are listed as
    # source files in Android.mk. Some auto-generated .js files are also
    # included in this list. Remove them from the list of sources.
    def _exclude_js_and_o(filename):
      return os.path.splitext(filename)[1] not in ('.js', '.o')

    vars.get_sources()[:] = filter(_exclude_js_and_o, vars.get_sources())
    return _filter_target_modules(vars)

  # Split Android.mk to multiple build groups since it takes 40 seconds to
  # run in a single step.
  # See mods/android/external/chromium_org/GypAndroid.linux-{arm|x86(_64)}.mk.
  make_to_ninja.MakefileNinjaTranslator(
      'android/external/chromium_org',
      extra_env_vars={'CHROMIUM_ORG_BUILD_GROUP': group}).generate(_filter)


def _generate_webview_ninja():
  def _filter(vars):
    # TODO(crbug.com/390856): Build Java libraries from source.
    if vars.is_java_library() or vars.is_package():
      return False
    # WebViewShell is a simple APK that loads a webview, not needed for ARC.
    # UbWebViewJankTests is only a test, not needed for ARC.
    skip = ['WebViewShell', 'UbWebViewJankTests', 'webview-janktesthelper']
    if vars.get_module_name() in skip:
      return False
    vars.enable_clang()
    vars.enable_cxx11()
    return True

  env = {
      'res_overrides': '',
      'version_build_number': '',
      'R_file_stamp': ''}
  make_to_ninja.MakefileNinjaTranslator(
      'android/frameworks/webview', extra_env_vars=env).generate(_filter)


def generate_ninjas():
  ninja_generator_runner.request_run_in_parallel(
      (_generate_chromium_org_ninja, 0),
      (_generate_chromium_org_ninja, 1),
      (_generate_chromium_org_ninja, 2),
      _generate_webview_ninja)
