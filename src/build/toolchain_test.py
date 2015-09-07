# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittest for toolchain.py."""

import unittest

from src.build import toolchain

_PLAIN_CLANG_VERSION_STRING = (
    'clang version 3.7.0\nTarget: x86_64-pc-linux-gnu\nThread model: posix')
_PNACL_CLANG_VERSION_STRING = (
    'clang version 3.6.0 (https://chromium.googlesource.com/a/native_client/pna'
    'cl-clang.git 8517045d75bd917d810f6e7eace416b681a52684) (https://chromium.g'
    'ooglesource.com/a/native_client/pnacl-llvm.git cbd15047352d090dd522c89afe0'
    '57fb83b5b699b) nacl-version=ab8a5c605e1502be0605783bfe477d1a3d315817\n'
    'Target: le32-unknown-nacl\nThread model: posix')
_UBUNTU_CLANG_VERSION_STRING = (
    'Ubuntu clang version 3.4-1ubuntu3 (tags/RELEASE_34/final) '
    '(based on LLVM 3.4)\nTarget: x86_64-pc-linux-gnu\nThread model: posix')


def _parse(version_string):
  toolchain._CLANG_RAW_VERSION_CACHE['testing'] = version_string
  return toolchain.get_clang_version('testing')


class ToolchainUnittest(unittest.TestCase):
  def testVersionStringParsing(self):
    self.assertEquals([3, 7, 0], _parse(_PLAIN_CLANG_VERSION_STRING))
    self.assertEquals([3, 6, 0], _parse(_PNACL_CLANG_VERSION_STRING))
    self.assertEquals([3, 4, 0], _parse(_UBUNTU_CLANG_VERSION_STRING))


if __name__ == '__main__':
  unittest.main()
