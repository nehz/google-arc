# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import build_common
import os
import toolchain
from build_options import OPTIONS
from ninja_generator import ApkNinjaGenerator


class GmsCoreNinjaGenerator(ApkNinjaGenerator):
  if OPTIONS.internal_apks_source_is_internal():
    _DIST_DIR = 'out/gms-core-build/dist'
    _ORIGINAL_APK_PATH = 'out/gms-core-build/play_services.apk'
    _NOTICES_OUTPUT_PATH = 'out/gms-core-build/NOTICES.tar.gz'
  else:
    # Use archived build
    _DIST_DIR = 'out/internal-apks'
    _ORIGINAL_APK_PATH = 'out/internal-apks/play_services.apk'
    _NOTICES_OUTPUT_PATH = 'out/internal-apks/play_services_NOTICES.tar.gz'

  if OPTIONS.enable_art_aot():
    _APK_PATH = build_common.get_build_path_for_apk('play_services',
                                                    'optimized.apk')
  else:
    _APK_PATH = _ORIGINAL_APK_PATH

  APITEST_APK_PATH = os.path.join(_DIST_DIR, 'GmsCoreApiTests.apk')
  APITEST_SETUP_APK_PATH = os.path.join(_DIST_DIR, 'GmsCoreApiTestsSetup.apk')
  _PROGUARD_MAPPING = os.path.join(_DIST_DIR, 'GmsCore-proguard-mapping.txt')

  # Every build artifact of GMS Core for ninja to generate dependencies.
  _ALL_OUTPUTS = [_ORIGINAL_APK_PATH, _NOTICES_OUTPUT_PATH, APITEST_APK_PATH,
                  APITEST_SETUP_APK_PATH]
  if not OPTIONS.is_debug_code_enabled():
    _ALL_OUTPUTS.append(_PROGUARD_MAPPING)

  def __init__(self, extra_dex2oat_flags):
    super(GmsCoreNinjaGenerator, self).__init__(
        'play_services',
        install_path='/vendor/play_services',
        canned_classes_apk=GmsCoreNinjaGenerator._APK_PATH,
        extra_dex2oat_flags=extra_dex2oat_flags)

  def build_gms_core_or_use_prebuilt(self):
    if OPTIONS.enable_art_aot():
      # Rule for pre-optimizing gms-core apk.
      boot_image_dir = os.path.join(build_common.get_android_fs_root(),
                                    'system/framework',
                                    build_common.get_art_isa())
      self.rule(
          'gms_core_apk_preoptimize',
          'src/build/gms_core_apk_preoptimize.py --input $in --output $out',
          description='Preoptimizing gmscore sub apks contained in $in')
      self.build(GmsCoreNinjaGenerator._APK_PATH,
                 'gms_core_apk_preoptimize',
                 GmsCoreNinjaGenerator._ORIGINAL_APK_PATH,
                 implicit=[toolchain.get_tool('java', 'dex2oat'),
                           os.path.join(boot_image_dir, 'boot.art'),
                           os.path.join(boot_image_dir, 'boot.oat')])

    if not OPTIONS.internal_apks_source_is_internal():
      return

    flags = '--eng' if OPTIONS.is_debug_code_enabled() else ''
    build_log = os.path.join('out/gms-core-build/build.log')
    command = ('internal/build/build.py gms-core %s > %s 2>&1 || '
               '(cat %s; exit 1)') % (flags, build_log, build_log)

    if OPTIONS.internal_apks_source() == 'internal-dev':
      # Only for local development.  play-services.apk dependes on jars below to
      # build, just to use ARC specific feature like ArcMessageBridge and
      # Tracing.  This dependency is a must-have for a clean build.  But this
      # dependency can cause unrelated framework change to trigger rebuild of
      # play-services.apk, which is very slow.  With this option, eng will self
      # manages the dependency, which is almost always satisfied.
      jars = []
    else:
      # Simply make these jars the dependencies of gms-core-build, which
      # references ArcMessage and ArcMessageBridge in the jar.  Note that these
      # jars changes often and is like to cause unnecessary rebuild of gms-core,
      # which is very slow.  We may think about a way to minimize the
      # dependency.
      #
      # See also: internal/mods/gms-core/vendor/unbundled_google/packages/ \
      #     OneUp/package/Android.mk
      #     OneUp/package/generate_package.mk
      jars = [
          build_common.get_build_path_for_jar('arc-services-framework',
                                              subpath='classes.jar'),
          build_common.get_build_path_for_jar('framework',
                                              subpath='classes.jar'),
      ]

    self.build(GmsCoreNinjaGenerator._ALL_OUTPUTS,
               'run_shell_command',
               implicit=['src/build/DEPS.arc-int'] + jars,
               variables={'command': command})

  def package_and_install(self):
    self.set_notice_archive(GmsCoreNinjaGenerator._NOTICES_OUTPUT_PATH)
    self.package()
    self.install()


class GmsCoreApiTestNinjaGenerator(ApkNinjaGenerator):
  def __init__(self, **kwargs):
    super(GmsCoreApiTestNinjaGenerator, self).__init__(
        'GmsCoreApiTests', **kwargs)

  def build_test_list(self):
    return self._build_test_list_for_apk(GmsCoreNinjaGenerator.APITEST_APK_PATH)
