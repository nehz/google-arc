# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import make_to_ninja
import staging


def generate_ninjas():
  def _filter(vars):
    if vars.is_host() or vars.is_static():
      return False
    if vars.is_prebuilt():
      vars.set_prebuilt_install_to_root_dir(True)
      return not vars.is_prebuilt_for_host()
    # ICU uses RTTI. Note that we originally tried to handle this flag via
    # LOCAL_RTTI_FLAG in the constructor of MakeVars, but it turned out to be
    # difficult as -frtti is removed later in _remove_feature_flags().
    vars.get_cxxflags().append('-frtti')
    # In order to get RTTI working, the right typeinfo header must be included
    # to make gcc happy. Apparently, type_info definition in bionic libstdc++ is
    # not complete enough and it complains.
    vars.get_cxxflags().append(
        '-I' + staging.as_staging('android/abi/cpp/include'))
    return True
  make_to_ninja.MakefileNinjaTranslator(
      'android/external/icu/icu4c').generate(_filter)
