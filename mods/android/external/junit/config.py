# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import make_to_ninja
from src.build import open_source


def generate_ninjas():
  def _filter(vars):
    assert vars.is_java_library()
    if vars.is_static_java_library() or vars.is_host():
      return False

    return {
        'core-junit': True,
        'junit-runner': False,
        # TODO(crbug.com/468670): L-rebase: junit-targetdex exercises our dexopt
        # compile paths, which are disabled until we find how to do dex2oat in
        # ninja time.
        'junit-targetdex': False,
    }[vars.get_module_name()]

  if open_source.is_open_source_repo():
    # We currently do not build Java code in open source.
    return
  make_to_ninja.MakefileNinjaTranslator(
      'android/external/junit').generate(_filter)
