#!src/build/run_python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import os
import os.path
import subprocess
import sys


_SOURCE_PATHS = ['out/staging/src/packaging/runtime/',
                 'out/target/common/packaging_gen_sources/']


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('input_files', metavar='<input_files>', nargs='+',
                      help='Input javascript files.')
  parser.add_argument('--java-path', metavar='<java_path>',
                      help='Path of Java executable.')
  parser.add_argument('--out', metavar='<out>',
                      help='Output of minimized Javascript.')
  parser.add_argument('--out-map', metavar='<out_map>',
                      help='Output of source map.')
  args = parser.parse_args()

  # TODO(crbug.com/310447): Check if our JS code is compatible with
  # https://developers.google.com/closure/compiler/docs/api-tutorial3#dangers
  # and enable ADVANCED_OPTIMIZATIONS if possible.
  closure_compiler_args = [
      args.java_path, '-jar', 'third_party/closure_compiler/compiler.jar',
      '--compilation_level', 'SIMPLE_OPTIMIZATIONS',
      '--language_in', 'ECMASCRIPT5',
      '--warning_level', 'QUIET',  # we already have another JS linter
      '--js_output_file', args.out,
      '--create_source_map', args.out_map]
  for in_file in args.input_files:
    closure_compiler_args += ['--js', in_file]

  ret = subprocess.call(closure_compiler_args)
  if ret != 0:
    return ret

  with open(args.out_map, 'r+') as map_file:
    map_contents = map_file.read()

    # Fix the paths since Chrome expects all files to be relative to the current
    # directory.
    for source_path in _SOURCE_PATHS:
      map_contents = map_contents.replace(source_path, '')

    map_file.seek(0)
    map_file.truncate()
    map_file.write(map_contents)

  with open(args.out, 'a') as out_file:
    # Add the mapping url to the combined, minified JS file.
    out_file.write("//# sourceMappingURL=%s\n" % os.path.basename(args.out_map))

  return 0


if __name__ == '__main__':
    sys.exit(main())
