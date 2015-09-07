# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import ninja_generator
from src.build import open_source
from src.build import staging


def generate_ninjas():
  if open_source.is_open_source_repo():
    # Provide a stub.
    n = ninja_generator.SharedObjectNinjaGenerator('libui')
    n.add_notice_sources([staging.as_staging('src/NOTICE')])
    n.link()
    return

  n = ninja_generator.SharedObjectNinjaGenerator(
      'libui', base_path='android/frameworks/native/libs/ui')
  n.add_include_paths('android/system/core/libsync/include')
  n.add_library_deps(
      'libcutils.so',
      'libhardware.so',
      'liblog.so',
      'libsync.so',
      'libutils.so')
  n.build_default_all_sources()
  n.link()
