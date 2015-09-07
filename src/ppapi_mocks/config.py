# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import pipes

from src.build import build_common
from src.build import ninja_generator
from src.build import staging

_CONTAINER_DIR = 'ppapi_mocks'
_MY_DIR = 'src/ppapi_mocks'


def _get_ppapi_mocks_generated_dir():
  return os.path.join(build_common.get_build_dir(), _CONTAINER_DIR)


def _add_ppapi_mock_compile_flags(n):
  n.add_ppapi_compile_flags()
  n.add_libchromium_base_compile_flags()
  n.add_include_paths(staging.as_staging('testing/gmock/include'),
                      _MY_DIR,
                      _get_ppapi_mocks_generated_dir())


def _get_ppapi_include_dirs():
  chrome_host_path = os.path.relpath(
      build_common.get_chrome_ppapi_root_path(), 'third_party')
  return [chrome_host_path,
          os.path.join(chrome_host_path, 'ppapi/lib/gl/include')]


def _generate_libppapi_mocks():
  rule_name = 'gen_ppapi_mock'
  # libart-gtest depends on libppapi_mocks.
  n = ninja_generator.ArchiveNinjaGenerator('libppapi_mocks',
                                            instances=0,
                                            force_compiler='clang',
                                            enable_cxx11=True)
  ppapi_dir = staging.as_staging('chromium-ppapi/ppapi')
  api_dir = os.path.join(ppapi_dir, 'api')
  script_path = os.path.join(_MY_DIR, 'gen_ppapi_mock.py')
  out_dir = os.path.join(
      ninja_generator.PpapiTestNinjaGenerator.get_ppapi_mocks_generated_dir(),
      _CONTAINER_DIR)
  log_file = os.path.join(out_dir, 'log.txt')
  stamp_file = os.path.join(out_dir, 'STAMP')

  command = ['src/build/run_python', pipes.quote(script_path),
             '--wnone',  # Suppress all warnings.
             '--range=start,end',  # Generate code for all revisions.
             '--ppapicgen',  # Generate PpapiMock source files.
             '--ppapihgen',  # Generate PpapiMock header files.
             '--srcroot', pipes.quote(api_dir),
             '--dstroot', pipes.quote(out_dir),
             '>', '$log_file',
             '|| (cat $log_file; rm $log_file; exit 1)']
  n.rule(rule_name,
         command=('(' + ' '.join(command) + ') && touch $stamp'),
         description=rule_name)

  generated_files = []
  idl_list = n.find_all_files('chromium-ppapi/ppapi/api', '.idl')
  for idl_path in idl_list:
    if 'finish_writing_these' in idl_path:
      # Files under ppapi/api/private/finish_writing_these/ directory are not
      # found by the parser of the idl generator library.
      continue
    path_stem = os.path.splitext(os.path.basename(idl_path))[0]
    # We are interested in only PPB files.
    if not path_stem.startswith('ppb_'):
      continue
    generated_files.append(os.path.join(out_dir, path_stem + '.cc'))
    generated_files.append(os.path.join(out_dir, path_stem + '.h'))

  n.build(generated_files + [stamp_file], rule_name, idl_list,
          variables={'log_file': pipes.quote(log_file),
                     'stamp': pipes.quote(stamp_file)},
          implicit=([script_path, 'src/build/run_python'] +
                    [staging.as_staging(idl_path) for idl_path in idl_list]))

  _add_ppapi_mock_compile_flags(n)
  n.build_default(
      [path for path in generated_files if path.endswith('.cc')] +
      n.find_all_files([_MY_DIR], '.cc', include_tests=True),
      implicit=[stamp_file])
  n.archive()


def generate_ninjas():
  _generate_libppapi_mocks()
