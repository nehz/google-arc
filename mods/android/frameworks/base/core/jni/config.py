# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import build_common
from src.build import make_to_ninja
from src.build import ninja_generator
from src.build import open_source
from src.build import staging
from src.build.build_options import OPTIONS


def generate_ninjas():
  if open_source.is_open_source_repo():
    # Provide a stub.
    n = ninja_generator.SharedObjectNinjaGenerator('libandroid_runtime')
    n.add_notice_sources([staging.as_staging('src/NOTICE')])
    n.link()
    return

  def _filter(vars):
    if OPTIONS.is_nacl_build():
      # The flag is valid only for C/ObjC but not for C++ on NaCl gcc.
      vars.remove_c_or_cxxflag('-Wno-int-to-pointer-cast')
    # TODO(crbug.com/327496): Move this to generic functionality of
    # make_to_ninja.
    intermediates_dir = (
        make_to_ninja.MakefileNinjaTranslator.get_intermediate_headers_dir())
    vars.get_includes().append(intermediates_dir)
    # TODO(crbug.com/414569): L-rebase: These include directories do not seem to
    # be being added. Fix that.
    vars.get_includes().append('android/frameworks/av/media/img_utils/include')
    vars.get_includes().append('android/external/skia/include/pathops')
    vars.get_includes().append('android/system/core/libprocessgroup/include')
    vars.get_implicit_deps().extend(
        [intermediates_dir + '/' + i for i in [
            'libsonivox/eas.h',
            'libsonivox/eas_types.h',
            'libsonivox/eas_reverb.h',
            'libsonivox/jet.h']])
    # Exclude ZygoteInit for which we have stubbed out jni registrations.
    vars.get_sources().remove('android/frameworks/base/core/jni/'
                              'com_android_internal_os_ZygoteInit.cpp')
    # Exclude GLES31+ functionality since we do not currently support it.
    vars.get_sources().remove('android/frameworks/base/core/jni/'
                              'android_opengl_GLES31.cpp')
    vars.get_sources().remove('android/frameworks/base/core/jni/'
                              'android_opengl_GLES31Ext.cpp')
    # Add ARC specific JNIs.
    vars.get_sources().extend([
        'android/frameworks/base/core/jni/org_chromium_arc_internal_Tracing.cpp'])  # noqa

    if OPTIONS.disable_hwui():
      # Defining this enables support for hardware accelerated rendering in the
      # user interface code, such as when an application uses a TextureView. The
      # primary effect is to use libhwui.  It is enabled by default in the
      # Android.mk file, we disable it here when not enabling hwui.
      vars.get_cflags().remove('-DUSE_OPENGL_RENDERER')
    if build_common.use_ndk_direct_execution():
      vars.get_cflags().append('-DUSE_NDK_DIRECT_EXECUTION')
    deps = vars.get_shared_deps()
    excluded_libs = (
        'libprocessgroup',     # Not built
        'libhardware_legacy',  # Not built
        'libnetutils',         # Not built
        'libselinux',          # Not built
        'libusbhost',          # Not built (only for MTP)
        'libwpa_client')       # Not built
    deps[:] = [x for x in deps if x not in excluded_libs]
    return True
  path = 'android/frameworks/base/core/jni'
  make_to_ninja.MakefileNinjaTranslator(path).generate(_filter)
