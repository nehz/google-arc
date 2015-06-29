# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build a fake libandroid.so for open source repo."""

import ninja_generator
import open_source
import staging


def generate_ninjas():
  if open_source.is_open_source_repo():
    # Provide a stub.
    n = ninja_generator.SharedObjectNinjaGenerator('libandroid')
    n.add_notice_sources([staging.as_staging('src/NOTICE')])
    n.link()
