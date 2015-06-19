# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Script to generate mods/android/frameworks/base/compiled-methods.

"""
In order to generate all the files needed to run this script:

* Obtain the list of compilable methods:
  - Compile ARC in debug mode without method whitelist:
    `./configure -t=nx --disable-method-whitelist && ninja -j200`
  - Extract the symbols from boot.oat:
    `nm -a out/target/nacl_x86_64_dbg_intermediates/boot_art/boot.oat` and save
    that to a file.
* Obtain the list of methods used during boot:
  - Compile ARC without AOT:
    `./configure -t=nx --disable-art-aot --logging=java-methods && ninja -j200`
  - Run HelloAndroid and redirect stderr to a file.
* Profile several Android applications:
  - Compile ARC in release mode:
    `./configure -t=nx --official-build && ninja -j200`
  - Follow `docs/profiling.md`, "Profiling Java code" section to obtain
    profiles and process the results.
* After compiling boot.oat with the updated whitelist, be sure to update the
  address at which the image will be loaded in mods/android/art/config.py.
"""

import argparse
import collections
import re
import sys

_JAVA_METHOD_ENTER = re.compile('^java_methods:\s+\d+\s+->\s+(.*?)$')

_SYMBOL_RE = re.compile(r'^([0-9a-f]+) T (.*?)(?: \[ DEDUPED \])?$')

_TRACE_RE = re.compile(r'^\s+(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+\[\d+\]\s+' +
                       r'([^ \t]+)\s+\(([^)]*)\)([^ \t]+)')

_TYPE_SIGNATURE_TO_JAVA_TYPE = {'B': 'byte',
                                'C': 'char',
                                'D': 'double',
                                'F': 'float',
                                'I': 'int',
                                'J': 'long',
                                'S': 'short',
                                'V': 'void',
                                'Z': 'boolean'}


def _parse_java_type_signature(s, idx=0):
  type_signature = s[idx]
  java_type = _TYPE_SIGNATURE_TO_JAVA_TYPE.get(type_signature)
  if java_type is not None:
    return (java_type, idx + 1)
  elif type_signature == 'L':
    semicolon = s.find(';', idx)
    return (s[idx + 1:semicolon].replace('/', '.'), semicolon + 1)
  else:
    assert type_signature == '[', s
    result, idx = _parse_java_type_signature(s, idx + 1)
    return (result + '[]', idx)


def _parse_java_type_signature_list(s):
  typelist = []
  idx = 0
  l = len(s)
  while idx < l:
    typename, idx = _parse_java_type_signature(s, idx)
    typelist.append(typename)
  return typelist


def _read_symbol_file(symbol_file):
  method_addresses = collections.defaultdict(list)
  compilable_methods = set()
  with open(symbol_file) as f:
    for line in f:
      address, method_name = _SYMBOL_RE.match(line).groups()
      compilable_methods.add(method_name)
      method_addresses[address].append(method_name)
  return compilable_methods, method_addresses


def _deduplicate_methods(method_addresses):
  """Obtain a set of all de-duplicated methods.

  ART has a mechanism to save space by emitting identical code just once and
  making all symbols/callers point to that version. That means that for no
  additional cost, we can have more methods be compiled. In practice, only about
  10% of the methods returned by this function will actually emit code, for a
  grand total of about 1MB."""
  compiled_methods = set()
  for address, method_names in method_addresses.iteritems():
    if len(method_names) > 1:
      # This function only considers duplicated methods, so an address should
      # have more than one assigned methods to be considered in this step.
      compiled_methods.update(method_names)
  return compiled_methods


def _read_boot_methods(boot_methods_file):
  """Parse a logfile to obtain all methods called during boot.

  Given that ARC tries to optimize boot time significantly, every single Java
  function that is called during boot time should be compiled (if possible).
  This parses a log, generated with --logging=java-methods, to create a set of
  methods that will always be invoked no matter the application being run."""
  boot_methods = set()
  with open(boot_methods_file) as f:
    for line in f:
      match = _JAVA_METHOD_ENTER.match(line)
      if not match:
        continue
      boot_methods.add(match.group(1))
  return boot_methods


def _read_profile(profile):
  """Read an Android profile summary to optimize for costly methods.

  In addition to optimize for boot time, some expensive runtime methods should
  also be included in the boot image. Currently we can add all methods found in
  all profiles without going above the size budget."""
  profile_methods = set()
  with open(profile) as f:
    for line in f:
      match = _TRACE_RE.match(line)
      if not match:
        continue
      calls, exclusive, aggregate, name, params, return_type = match.groups()
      calls = int(calls)
      exclusive = float(exclusive)
      aggregate = float(aggregate)
      params = _parse_java_type_signature_list(params)
      return_type = _parse_java_type_signature_list(return_type)[0]
      profile_methods.add('%s %s(%s)' % (return_type, name, ', '.join(params)))
  return profile_methods


def _write_methods(output, methods, name, emitted_methods):
  filtered_methods = (methods - emitted_methods)
  if filtered_methods:
    print >> output, '# %s' % name
    for method in sorted(filtered_methods):
      print >> output, method
    emitted_methods.update(filtered_methods)


def _generate_whitelist_file(parsed_args):
  print >> parsed_args.output, '# Generated with generate_method_whitelist.py.'
  print >> parsed_args.output, '# Do not edit.'
  compilable_methods, method_addresses = _read_symbol_file(
      parsed_args.symbol_file)
  emitted_methods = set()
  deduplicated_methods = _deduplicate_methods(method_addresses)
  _write_methods(parsed_args.output, deduplicated_methods,
                 'Deduplicated methods', emitted_methods)
  boot_methods = _read_boot_methods(parsed_args.boot_methods_file)
  _write_methods(parsed_args.output, boot_methods & compilable_methods,
                 'Boot methods', emitted_methods)
  profile_methods = set()
  for profile in parsed_args.profiles:
    profile_methods |= _read_profile(profile)
  _write_methods(parsed_args.output, profile_methods & compilable_methods,
                 'Profile methods', emitted_methods)


def _open_output(value):
  return open(value, 'w')


def _parse_args(argv):
  parser = argparse.ArgumentParser()
  parser.add_argument('--output', default=sys.stdout, type=_open_output,
                      help='Write the generated whitelist to a file. '
                      'The default is stdout')
  parser.add_argument('symbol_file', metavar='<symbol-file>',
                      help='A file with all the symbols in boot.oat. This can '
                      'be generated by compiling ARC in debug mode and then '
                      'running `nm -a <path to>/boot.oat`.')
  parser.add_argument('boot_methods_file', metavar='<boot-methods-file>',
                      help='A file with all the methods called during boot. '
                      'This can be generated by compiling ARC with the '
                      '--disable-art-aot and --logging=java-methods flags '
                      'and then launching HelloAndroid.')
  parser.add_argument('profiles', metavar='<profile>', nargs='*', default=[],
                      help='A file with a Java profile for an application. '
                      'This can be generated by compiling ARC in release mode '
                      'and launching it with the --java-trace-startup=<N> flag.'
                      'The trace then needs to be grabbed from the device '
                      'with `adb` and the trace needs to be processed with '
                      '`dmtracedump`. See `docs/profiling.md` for more info.')
  return parser.parse_args(argv)


def main():
  parsed_args = _parse_args(sys.argv[1:])
  return _generate_whitelist_file(parsed_args)


if __name__ == '__main__':
  sys.exit(main())
