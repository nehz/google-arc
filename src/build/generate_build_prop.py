#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""These build properties are usually created by the Android makefile system.

Specifically the ro.build.version info is written by
$ANDROID/build/tools/buildinfo.sh whose variables are set by
$ANDROID/build/core/version_defaults.mk and various build_id.mk
files.
"""

import os
import subprocess
import sys

import build_common
import toolchain
from build_options import OPTIONS

OPTIONS.parse_configure_file()

# Note the following restrictions:
#    Property name max length:  31 characters
#    Property value max length: 91 characters
# See frameworks/base/core/java/android/os/SystemProperties.java

# Provide an option to generate different build properties for running non-CWS
# apps, such as sideloaded or via ARC Welder.  This allows WebView (Chromium) to
# send different User-Agent.
dev_mode = '--dev' in sys.argv

# Environment variables below are sorted alphabetically.

# version_defaults.mk sets this if there is no BUILD_ID set.
_BUILD_NUMBER = build_common.get_build_version()

os.environ['BUILD_DISPLAY_ID'] = _BUILD_NUMBER

# Non-tagged builds generate fingerprints that are longer than the maximum
# number of characters allowed for system property values. Split the build ID
# in version and specific build to be within the limit.
if '-' in _BUILD_NUMBER:
  tokens = _BUILD_NUMBER.split('-')
  os.environ['BUILD_ID'] = tokens[0]
  os.environ['BUILD_NUMBER'] = '-'.join(tokens[1:])
else:
  os.environ['BUILD_ID'] = _BUILD_NUMBER
  os.environ['BUILD_NUMBER'] = _BUILD_NUMBER
if OPTIONS.is_debug_code_enabled():
  os.environ['BUILD_VERSION_TAGS'] = 'test-keys'
else:
  os.environ['BUILD_VERSION_TAGS'] = 'release-keys'

# "REL" means a release build (everything else is a dev build).
os.environ['PLATFORM_VERSION_CODENAME'] = 'REL'
os.environ['PLATFORM_VERSION_ALL_CODENAMES'] = 'REL'
os.environ['PLATFORM_VERSION'] = '5.0'
# SDK has to be pinned to correct level to avoid loading
# unsupported featured from app's APK file.
os.environ['PLATFORM_SDK_VERSION'] = str(toolchain.get_android_api_level())

# By convention, ro.product.brand, ro.product.manufacturer and ro.product.name
# are always in lowercase.
os.environ['PRODUCT_BRAND'] = 'chromium'
os.environ['PRODUCT_DEFAULT_LANGUAGE'] = 'en'
os.environ['PRODUCT_DEFAULT_REGION'] = 'US'
os.environ['PRODUCT_DEFAULT_WIFI_CHANNELS'] = ''
os.environ['PRODUCT_MANUFACTURER'] = 'chromium'
os.environ['PRODUCT_MODEL'] = 'App Runtime for Chrome'
if dev_mode:
  os.environ['PRODUCT_MODEL'] += ' Dev'
os.environ['PRODUCT_NAME'] = 'arc'

os.environ['TARGET_AAPT_CHARACTERISTICS'] = 'default'
os.environ['TARGET_BOARD_PLATFORM'] = OPTIONS.target()
os.environ['TARGET_BOOTLOADER_BOARD_NAME'] = OPTIONS.target()
os.environ['TARGET_BUILD_VARIANT'] = build_common.get_build_type()
# TARGET_BUILD_TYPE is set to the value of TARGET_BUILD_VARIANT
# in build/core/Makefile upstream. We do it manually here.
os.environ['TARGET_BUILD_TYPE'] = os.environ['TARGET_BUILD_VARIANT']

# Prefer ARM v7 NDK code over v6 as v7 has hardware floating point
# and thus can be translated/simulated in fewer instructions.
os.environ['TARGET_CPU_ABI_LIST'] = 'armeabi-v7a,armeabi'
os.environ['TARGET_CPU_ABI_LIST_32_BIT'] = 'armeabi-v7a,armeabi'

# Cannot set device as "simulator" as it causes NPE in network service.
# NetworkManagementService and MountService appear to be the only places
# to check for "simulator". However NetworkManagementService would then skip
# a part of its own initialization leaving important variables set to null.
os.environ['TARGET_DEVICE'] = OPTIONS.target()
os.environ['TARGET_PRODUCT'] = 'arc'

os.environ.setdefault('USER', 'unknown')

# This cannot be ordered alphabetically due to dependencies.
#
# $(PRODUCT_BRAND)/$(TARGET_PRODUCT)/$(TARGET_DEVICE):
# $(PLATFORM_VERSION)/$(BUILD_ID)/$(BUILD_NUMBER):
# $(TARGET_BUILD_VARIANT)/$(BUILD_VERSION_TAGS)
os.environ['BUILD_FINGERPRINT'] = ''.join([
    os.environ['PRODUCT_BRAND'], '/',
    os.environ['TARGET_PRODUCT'], '/',
    os.environ['TARGET_DEVICE'], ':',
    os.environ['PLATFORM_VERSION'], '/',
    os.environ['BUILD_ID'], '/',
    os.environ['BUILD_NUMBER'], ':',
    os.environ['TARGET_BUILD_VARIANT'], '/',
    os.environ['BUILD_VERSION_TAGS']])
os.environ['PRIVATE_BUILD_DESC'] = os.environ['BUILD_FINGERPRINT']


build_info_sh = os.path.join(os.path.dirname(__file__), '..', '..',
                             'third_party', 'android', 'build', 'tools',
                             'buildinfo.sh')
print subprocess.check_output([build_info_sh])


print
print '# begin build properties added by generate_build_prop.py'

# Set up the same DNS as in config.xml to avoid errors at startup.
# Dummy network does not provide its own DNS server names.
# The value matches the default from config.xml.
print 'net.dns1=8.8.8.8'

# Normally init parses the hardware value from the kernel command line
# androidboot.hardware=* parameter.  We hardcode it here and this is
# used in determining appropriate HAL modules.
print 'ro.hardware=arc'

# Enable atrace.  See android/frameworks/base/core/java/android/os/Trace.java
# for flag definition.  Here we turn on every category when debugging code is
# enabled.
if OPTIONS.is_debug_code_enabled():
  print 'debug.atrace.tags.enableflags=' + str(int('0xffffffff', 16))

if not OPTIONS.disable_hwui():
  # This value is exposed through the Activity Manager service
  # getDeviceConfigurationInfo() call, and this value indicates that GLES2 is
  # available. The number is the major version number in the upper sixteen bits
  # followed by the minor version number in the lower sixteen bits.
  print 'ro.opengles.version=131072'

# Normally added upstream at android/build/core/main.mk. Services can restrict
# functionality based on this value (currently very few do).  Setting this
# value allows CtsOsTestCases:android.os.cts.BuildTest to pass.
secure = "0"
if build_common.get_build_type() == "user":
  secure = "1"
print 'ro.secure=' + secure

# The following three properties synchronize dex2oat's arguments at build time
# and runtime.
dex2oatFlags = build_common.get_dex2oat_target_dependent_flags_map()
print ('dalvik.vm.isa.' + build_common.get_art_isa() + '.features=' +
       dex2oatFlags['instruction-set-features'])
print 'dalvik.vm.dex2oat-filter=' + dex2oatFlags['compiler-filter']
if 'no-include-debug-symbols' in dex2oatFlags:
  print 'dalvik.vm.dex2oat-flags=--no-include-debug-symbols'

# This property tells dex2oat to compile x86 code even though we say in the
# ABI_LIST above that we only support ARM.
if OPTIONS.is_i686():
  print 'ro.dalvik.vm.isa.arm=x86'
if OPTIONS.is_x86_64():
  print 'ro.dalvik.vm.isa.arm=x86_64'

# When AOT is not enabled, make sure dex2oat does not run.
if not OPTIONS.enable_art_aot():
  print 'ro.arc.dex2oat.disabled=1'

print '# end build properties added by generate_build_prop.py'
