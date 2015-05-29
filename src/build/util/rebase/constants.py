# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Various constants used by the rebase code."""

import os.path

ANDROID_SUBMODULE_PATH = 'third_party/android'
ANDROID_MODS_PATH = 'mods/android'

ARC_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), '../../../..'))


# These are the status codes indicating the rebase state of each mod.
RESULT_OK = 0
RESULT_MOD_INCORRECT_FOR_OLD_VERSION = -1
RESULT_MOD_ANDROID_SUBMODULE_NOT_IDENTIFIED = -2
RESULT_MOD_EXISTS_AT_NEW_LOCATION = -3
RESULT_REBASE_RESULT_NO_UPSTREAM = -4
RESULT_NO_CLEAN_MERGE = -5
RESULT_DIFFS_AFTER_MERGE = -6
