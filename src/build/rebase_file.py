#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Automates rebasing our patched files against upstream Android code."""

import argparse
import sys

import util.rebase.constants
import util.rebase.mod

_EPILOG = r"""
This script performs the following operations:

  1. Locate the base code being modified, for both the old version and the
     current (newer) version.

  2. Validate that the modification is correct for the old version of the base
     code.

  3. If necessary, "git mv" the modification to the new location.

  4. Perform a three way merge of the mod, the old base code, and the new base
     code to generate a new mod (rebase the mod).

  5. Validate that the new modification is correct for the new version of the
     base code.

  Note that the newly rebased modification still needs to be compiled and
  tested.  Everything might merge and verify cleanly only for there to be some
  other error (such as a variable being renamed in the base code).

Usage Examples:

  1. Rebase BootAnimation.cpp in place, upgrading from android-5.0.0_r7 to the
     current version.

    %(prog)s --from android-5.0.0_r7 \
        mods/frameworks/base/cmds/bootanimation/BootAnimation.cpp

  2. Rebase the modification to Surface.h, moving it to a new subdirectory to
     match the base file being moved as well from android-4.4_r1 to the current
     version.

    %(prog)s --from android-4.4_r1 \
        mods/frameworks/native/include/gui/Surface.h \
        mods/frameworks/base/include/surfaceflinger/Surface.h
""".strip()


def main():
  parser = argparse.ArgumentParser(
      description=__doc__, epilog=_EPILOG,
      formatter_class=argparse.RawTextHelpFormatter)

  parser.add_argument('--from', dest='old_revision', required=True,
                      help='The old Android revision tag.')
  parser.add_argument('old_path')
  parser.add_argument('new_path', nargs='?')
  args = parser.parse_args()

  mod = util.rebase.mod.get_arc_android_mod(args.old_path)
  mod.rebase(args.old_revision, force_new_mod_path=args.new_path)

  if mod.status == util.rebase.constants.RESULT_OK:
    print 'Merged files automatically, no manual work needed'
  elif mod.status == util.rebase.contants.RESULT_MOD_INCORRECT_FOR_OLD_VERSION:
    sys.exit(
        'analyze_diffs reported errors for "%s". The old version you specified '
        'may not match the version of the code the modification is actually '
        'supposed to track.' % (
            args.old_path))
  elif mod.status == (
      util.rebase.contants.RESULT_MOD_ANDROID_SUBMODULE_NOT_IDENTIFIED):
    sys.exit(
        'The tracked source code appears to have moved, and the new location '
        'for the base code modified by "%s" was not identified.' % (
            mod.new_mod_path))
  elif mod.status == util.rebase.contants.RESULT_MOD_EXISTS_AT_NEW_LOCATION:
    sys.exit(
        'A file exists at the new location for the mod "%s".' % (
            mod.new_mod_path))
  elif mod.status == util.rebase.constants.RESULT_REBASE_RESULT_NO_UPSTREAM:
    sys.exit(
        'The original source file for %s was unable to be located. You will '
        'need to manually move the mod or otherwise fix it up to identify the '
        'correct file.' % (
            args.old_path))
  elif mod.status == util.rebase.constants.RESULT_NO_CLEAN_MERGE:
    sys.exit(
        'The merge of "%s" did not complete cleanly. You will need to manually '
        'edit it to fix it.' % (
            mod.new_mod_path))
  elif mod.status == util.rebase.constants.RESULT_DIFFS_AFTER_MERGE:
    sys.exit(
        'The merge of "%s" completed cleanly, but analyze_diffs reported '
        'errors.' % (
            mod.new_mod_path))

if __name__ == '__main__':
  sys.exit(main())
