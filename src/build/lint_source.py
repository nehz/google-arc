#!/usr/bin/env python

# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import cPickle
import collections
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile

import analyze_diffs
import build_common
import open_source
from util import file_util

_GROUP_ASM = 'Assembly'
_GROUP_CPP = 'C/C++'
_GROUP_CSS = 'CSS'
_GROUP_HTML = 'HTML'
_GROUP_JAVA = 'Java'
_GROUP_JS = 'Javascript'
_GROUP_PY = 'Python'

# For the report, statistics will be totaled for all files under these
# directories.
_PATH_PREFIX_GROUPS = [
    'internal/mods/',
    'mods/',
    'mods/android/',
    'mods/android/bionic/',
    'mods/android/frameworks/',
    'mods/chromium-ppapi/',
    'src/',
]

_DEFAULT_LINT_TARGET_DIR_LIST = [
    'canned',
    'mods',
    'internal/mods',
    'src',
    # TODO(crbug.com/374475): This subtree should be removed from linting.
    # There should be no ARC MOD sections in third_party, but there are in
    # some NDK directories.
    'third_party/examples',
]


class FileStatistics:
  def __init__(self, filename=None):
    self.filename = filename
    self.stats_dict = collections.defaultdict(int)

  def accumulate(self, source):
    for key, value in source.stats_dict.iteritems():
      self.stats_dict[key] += value


class Linter(object):
  """Interface (and the default implementation) to run lint.

  Provides following methods.
  - should_run(path): Returns True if the linter should run for the file.
    By default, True is returned, which means the linter should run for any
    files. Subclasses can override if necessary.
  - run(path): Applies the lint to the file. Returns True on success, otherwise
    False. All subclasses must override this method.
  """

  def __init__(self, name, target_groups=None,
               ignore_mods=False, ignore_upstream_tracking_file=True):
    """Initializes the basic linter instance.

    - name: Name of the linter. Used for the name based ignoring check whose
      rule is written in the ignore file.
    - target_groups: List of groups. Used for the file extension based
      ignoring check.
    - ignore_mods: If True, the linter will not be applied to files under
      mods/. By default: False.
    - ignore_upstream_tracking_file: If True, the linter will not be applied
      to files tracking an upstream file. By default: True.

    Please see also LinterRunner for the common ignoring rule implementation.
    """
    self._name = name
    # Use tuple as a frozen list.
    self._target_groups = tuple(target_groups) if target_groups else None
    self._ignore_mods = ignore_mods
    self._ignore_upstream_tracking_file = ignore_upstream_tracking_file

  @property
  def name(self):
    return self._name

  @property
  def target_groups(self):
    return self._target_groups

  @property
  def ignore_mods(self):
    return self._ignore_mods

  @property
  def ignore_upstream_tracking_file(self):
    return self._ignore_upstream_tracking_file

  def should_run(self, path):
    """Returns True if this linter should be applied to the file at |path|."""
    # Returns True, by default, which means this linter will be applied to
    # any files.
    return True

  def run(self, path):
    """Applies the linter to the file at |path|."""
    # All subclasses must override this function.
    raise NotImplementedError()


class CommandLineLinterBase(Linter):
  """Abstract Linter implementation to run a linter child process."""

  def __init__(self, name, error_line_filter=None, *args, **kwargs):
    """Initialize the linter.

    - error_line_filter: On subprocess error, it logs subprocess's output, but
      it sometimes contains unuseful information. This is the regexp to filter
      it.
    - remaining args are just redirected to the the base class __init__.
    """
    super(CommandLineLinterBase, self).__init__(name, *args, **kwargs)
    self._error_line_filter = (
        re.compile(error_line_filter, re.M) if error_line_filter else None)

  def run(self, path):
    command = self._build_command(path)
    try:
      subprocess.check_output(command, stderr=subprocess.STDOUT)
      return True
    except OSError:
      logging.exception('Unable to invoke %s', command)
      return False
    except subprocess.CalledProcessError as e:
      if self._error_line_filter:
        output = '\n'.join(
            m.group(1) for m in self._error_line_filter.findall(e.output))
      else:
        output = e.output
      logging.exception('Lint output errors: %s', output)
      return False

  def _build_command(self, path):
    # All subclasses must implement this.
    raise NotImplementedError()


class CppLinter(CommandLineLinterBase):
  """Linter for C/C++ source/header files."""

  def __init__(self):
    super(CppLinter, self).__init__(
        'cpplint', target_groups=[_GROUP_CPP], ignore_mods=True,
        # Strip less information lines.
        error_line_filter='^(?:(?!Done processing|Total errors found:))(.*)')

  def _build_command(self, path):
    return ['third_party/tools/depot_tools/cpplint.py', '--root=src', path]


class JsLinter(CommandLineLinterBase):
  """Linter for JavaScript files."""

  def __init__(self):
    super(JsLinter, self).__init__(
        'gjslint', target_groups=[_GROUP_JS],
        # Strip the path to the arc root directory.
        error_line_filter=(
            '^' + re.escape(build_common.get_arc_root()) + '/(.*)'))

  def _build_command(self, path):
    # gjslint is run with the following options:
    #
    #  --unix_mode
    #      Lists the filename with each error line, which is what most linters
    #      here do.
    #
    #  --jslint_error=all
    #      Includes all the extra error checks. Some of these are debatable, but
    #      it seemed easiest to enable everything, and then disable the ones we
    #      do not find useful.
    #
    #  --disable=<error numbers>
    #      Disable specific checks by error number. The ones we disable are:
    #
    #      * 210 "Missing docs for parameter" (no @param doc comment)
    #      * 213 "Missing type in @param tag"
    #      * 217 "Missing @return JsDoc in function with non-trivial return"
    #
    #  --custom_jsdoc_tags=<tags>
    #      Indicates extra jsdoc tags that should be allowed, and not have an
    #      error generated for them. By default closure does NOT support the
    #      full set of jsdoc tags, including "@public". This is how we can use
    #      them without gjslint complaining.
    return ['src/build/gjslint', '--unix_mode', '--jslint_error=all',
            '--disable=210,213,217', '--custom_jsdoc_tags=public', path]


class PyLinter(CommandLineLinterBase):
  """Linter for python."""

  _DISABLED_LINT_LIST = [
      'E111',  # indentation is not a multiple of four
      'E114',  # indentation is not a multiple of four (comment)
      'E115',  # expected an indented block (comment)
      'E116',  # unexpected indentation (comment)
      'E121',  # continuation line under-indented for hanging indent
      'E122',  # continuation line missing indentation or outdented
      'E125',  # continuation line with same indent as next logical line
      'E129',  # visually indented line with same indent as next logical line
      'E251',  # unexpected spaces around keyword / parameter equals
      'E265',  # block comment should start with '# '
      'E402',  # module level import not at top of file
      'E713',  # test for membership should be 'not in'
      'E714',  # test for object identity should be 'is not'
      'E731',  # do not assign a lambda expression, use a def
      'W602',  # deprecated form of raising exception
      'W801',  # list comprehension redefines 'lib' from line 49
  ]

  def __init__(self):
    super(PyLinter, self).__init__('flake8', target_groups=[_GROUP_PY])

  def _build_command(self, path):
    return ['src/build/flake8',
            '--ignore=' + ','.join(PyLinter._DISABLED_LINT_LIST),
            '--max-line-length=80',
            path]


class CopyrightLinter(CommandLineLinterBase):
  """Linter to check copyright notice."""

  def __init__(self):
    super(CopyrightLinter, self).__init__(
        'copyright',
        target_groups=[_GROUP_ASM, _GROUP_CPP, _GROUP_CSS, _GROUP_HTML,
                       _GROUP_JAVA, _GROUP_JS, _GROUP_PY])

  def should_run(self, path):
    # TODO(crbug.com/411195): Clean up all copyrights so we can turn this on
    # everywhere.  Currently our priority is to have the open sourced
    # copyrights all be consistent.
    return path.startswith('src/') or open_source.is_open_sourced(path)

  def _build_command(self, path):
    return ['src/build/check_copyright.py', path]


class UpstreamLinter(Linter):
  """Linter to check the contents of upstream note in mods/upstream."""

  def __init__(self):
    super(UpstreamLinter, self).__init__('upstreamlint')

  def should_run(self, path):
    # mods/upstream directory is not yet included in open source so we cannot
    # run this linter.
    if open_source.is_open_source_repo():
      return False
    return path.startswith(analyze_diffs.UPSTREAM_BASE_PATH + os.path.sep)

  def run(self, path):
    # TODO(20150228): This implementation has a bug (if '=' is contained the
    # description, the calculation of the number of description does not work
    # properly.)
    description_line_count = 0
    vars = {}
    with open(path) as f:
      lines = f.read().splitlines()
    for line in lines:
      line = line.strip()
      pos = line.find('=')
      if pos != -1:
        vars[line[:pos].strip()] = line[pos + 1:].strip()
      elif line and not vars:
        description_line_count += 1

    if 'ARC_COMMIT' in vars and vars['ARC_COMMIT'] == '':
      logging.error('Upstream file has empty commit info: %s', path)
      return False
    if 'UPSTREAM' not in vars:
      logging.error('Upstream file has no upstream info: %s', path)
      return False
    if description_line_count == 0 and not vars['UPSTREAM']:
      logging.error(
          'Upstream file has no upstream URL and no description: %s', path)
      return False
    return True


class LicenseLinter(Linter):
  """Linter to check MODULE_LICENSE_TODO files."""

  def __init__(self):
    super(LicenseLinter, self).__init__('licenselint')

  def should_run(self, path):
    # Accept only MODULE_LICENSE_TODO file.
    return os.path.basename(path) == 'MODULE_LICENSE_TODO'

  def run(self, path):
    with open(path) as f:
      content = f.read()
    if not content.startswith('crbug.com/'):
      logging.error('MODULE_LICENSE_TODO must contain a crbug.com link for '
                    'resolving the todo: %s', path)
      return False
    return True


class DiffLinter(CommandLineLinterBase):
  """Linter to apply analyze_diffs.py."""

  def __init__(self, output_dir):
    """Create DiffLinter instance.

    - output_dir: If specified (i.e it is not None), analyze_diffs.py
      generates the output file under the directory.
      Note that it is the caller's responsibility to remove the generated
      files.
    """
    super(DiffLinter, self).__init__(
        'analyze_diffs', ignore_upstream_tracking_file=False)
    self._output_dir = output_dir

  def _build_command(self, path):
    command = ['src/build/analyze_diffs.py', path]
    if self._output_dir:
      # Create a tempfile as a placeholder of the output.
      # In latter phase, the file is processed by iterating the files in the
      # |output_dir|. It is caller's responsibility to remove the file.
      # Note that analyze_diffs.py creates .d file automatically if output_file
      # is specified. To figure out it, we use '.out' extension.
      with tempfile.NamedTemporaryFile(
          prefix=os.path.basename(path), suffix='.out',
          dir=self._output_dir, delete=False) as output_file:
        command.append(output_file.name)
    return command


class LinterRunner(object):
  """Takes a list of Linters, and runs them."""

  _EXTENSION_GROUP_MAP = {
      '.asm': _GROUP_ASM,
      '.c': _GROUP_CPP,
      '.cc': _GROUP_CPP,
      '.cpp': _GROUP_CPP,
      '.css': _GROUP_CSS,
      '.h': _GROUP_CPP,
      '.hpp': _GROUP_CPP,
      '.html': _GROUP_HTML,
      '.java': _GROUP_JAVA,
      '.js': _GROUP_JS,
      '.py': _GROUP_PY,
      '.s': _GROUP_ASM,
  }

  def __init__(self, linter_list, ignore_rule=None):
    self._linter_list = linter_list
    self._ignore_rule = ignore_rule or {}

  def run(self, path):
    # In is_tracking_an_upstream_file, the path is opened.
    # To avoid invoking it many times for a file, we cache the result, and
    # pass it to Linter.should_run() method via an argument.
    is_tracking_upstream = analyze_diffs.is_tracking_an_upstream_file(path)
    group = LinterRunner._EXTENSION_GROUP_MAP.get(
        os.path.splitext(path)[1].lower())
    result = True
    for linter in self._linter_list:
      # Common rule to check if linter should be applied to the file.
      if (linter.name in self._ignore_rule.get(path, []) or
          (linter.target_groups and group not in linter.target_groups) or
          (linter.ignore_upstream_tracking_file and is_tracking_upstream) or
          (linter.ignore_mods and path.startswith('mods/'))):
        continue
      # Also, check each linter specific rule.
      if not linter.should_run(path):
        continue

      logging.info('%- 10s: %s', linter.name, path)
      result &= linter.run(path)

    if not result:
      logging.error('%s: has lint errors', path)
    return result


def _run_lint(target_file_list, ignore_rule, output_dir):
  """Applies all linters to the target_file_list.

  - target_file_list: List of the target files' paths.
  - ignore_rule: Linter ignoring rule map. Can be None.
  - output_dir: Directory to store the analyze_diffs.py's output data.
    If specified, it is callers' responsibility to remove the generated
    files, if necessary.
  """
  runner = LinterRunner(
      [CppLinter(), JsLinter(), PyLinter(), CopyrightLinter(),
       UpstreamLinter(), LicenseLinter(), DiffLinter(output_dir)],
      ignore_rule)
  result = True
  for path in target_file_list:
    result &= runner.run(path)
  return result


def _process_analyze_diffs_output(output_dir):
  """Processes analyze_diffs.py's output, and returns a list of FileStatistics.
  """
  result = []
  for path in os.listdir(output_dir):
    if os.path.splitext(path)[1] != '.out':
      continue
    with open(os.path.join(output_dir, path), mode='rb') as stream:
      output = cPickle.load(stream)
    source_path = output['our_path']
    added = output['added_lines']
    removed = output['removed_lines']

    file_statistics = FileStatistics(source_path)
    stats_dict = file_statistics.stats_dict
    stats_dict['Files'] = 1
    if output['tracking_path'] is None:
      assert removed == 0, repr(output)
      stats_dict['New files'] = 1
      stats_dict['New lines'] = added
    else:
      stats_dict['Patched files'] = 1
      stats_dict['Patched lines added'] = added
      stats_dict['Patched lines removed'] = removed
    result.append(file_statistics)
  return result


def _walk(path):
  """List all files under |path|, including subdirectories."""
  filelist = []
  for root, dirs, files in os.walk(path):
    filelist.extend(os.path.join(root, f) for f in files)
  return filelist


def _should_ignore(filename):
  """Returns True if any linter should not apply to the file."""
  extension = os.path.splitext(filename)[1]
  basename = os.path.basename(filename)
  if os.path.isdir(filename):
    return True
  if os.path.islink(filename):
    return True
  if build_common.is_common_editor_tmp_file(basename):
    return True
  if extension == '.pyc':
    return True
  if filename.startswith('src/build/tests/analyze_diffs/'):
    return True
  if filename.startswith('docs/'):
    return True
  return False


def _filter_files(files):
  if not files:
    files = []  # In case of None.
    for lint_target_dir in _DEFAULT_LINT_TARGET_DIR_LIST:
      files.extend(_walk(lint_target_dir))
  return [x for x in files if not _should_ignore(x)]


def get_all_files_to_check():
  return _filter_files(None)


def read_ignore_rule(path):
  """Reads the mapping of paths to lint checks to ignore from a file.

  The ignore file is expected to define a simple mapping between file paths
  and the lint rules to ignore (the <List Class>.NAME attributes). Hash
  characters ('#') can be used for comments, as well as blank lines for
  readability.

  A typical # filter in the file should look like:

    # Exclude src/xyzzy.cpp from the checks "gnusto" and "rezrov"
    "src/xyzzy.cpp": ["gnusto", "rezrov"]
  """
  if not path:
    return {}

  result = json.loads('\n'.join(file_util.read_metadata_file(path)))

  # Quick verification.
  # Make sure everything exists in the non-open source repo.  (We do
  # not run this check on the open source repo since not all files are
  # currently open sourced.)
  if not open_source.is_open_source_repo():
    unknown_path_list = [key for key in result if not os.path.exists(key)]
    assert not unknown_path_list, (
        'The key in \'%s\' contains unknown files: %s' % (
            path, unknown_path_list))
  return result


def process(target_file_list, ignore_file=None, output_file=None):
  ignore_rule = read_ignore_rule(ignore_file)
  target_file_list = _filter_files(target_file_list)

  # Create a temporary directory as the output dir of the analyze_diffs.py,
  # iff |output_file| is specified.
  output_dir = tempfile.mkdtemp(dir='out') if output_file else None
  try:
    if not _run_lint(target_file_list, ignore_rule, output_dir):
      return 1

    if output_file:
      statistic_list = _process_analyze_diffs_output(output_dir)
      with open(output_file, 'wb') as stream:
        cPickle.dump(statistic_list, stream)
  finally:
    if output_dir:
      shutil.rmtree(output_dir)
  return 0


def _all_file_statistics(files):
  for filename in files:
    with open(filename) as f:
      for file_statistics in cPickle.load(f):
        yield file_statistics


def _all_groups_for_filename(filename):
  # Output groups based on what the path starts with.
  for prefix in _PATH_PREFIX_GROUPS:
    if filename.startswith(prefix):
      yield 'Under:' + prefix + '*'


def _report_stats_for_group(group_name, stats, output_file):
  output_file.write(group_name + '\n')
  for key in sorted(stats.stats_dict.keys()):
    output_file.write('    {0:<30} {1:10,d}\n'.format(
        key, stats.stats_dict[key]))
  output_file.write('-' * 60 + '\n')


def _report_stats(top_stats, grouped_stats, output_file):
  for group_name in sorted(grouped_stats.keys()):
    _report_stats_for_group(group_name, grouped_stats[group_name], output_file)
  _report_stats_for_group('Project Total', top_stats, output_file)


def merge_results(files, output_file):
  top_stats = FileStatistics()
  grouped_stats = collections.defaultdict(FileStatistics)

  for file_statistics in _all_file_statistics(files):
    filename = file_statistics.filename
    top_stats.accumulate(file_statistics)
    for group in _all_groups_for_filename(filename):
      grouped_stats[group].accumulate(file_statistics)

  _report_stats(top_stats, grouped_stats, sys.stdout)
  with open(output_file, 'w') as output_file:
    _report_stats(top_stats, grouped_stats, output_file)


class ResponseFileArgumentParser(argparse.ArgumentParser):
  def __init__(self):
    super(ResponseFileArgumentParser, self).__init__(fromfile_prefix_chars='@')

  def convert_arg_line_to_args(self, arg_line):
    """Separate arguments by spaces instead of the default by newline.

    This matches how Ninja response files are generated.  This prevents us
    from adding source files with spaces in their paths."""
    for arg in arg_line.split():
        if not arg.strip():
            continue
        yield arg


def main():
  parser = ResponseFileArgumentParser()
  parser.add_argument('files', nargs='*', help='The list of files to lint.  If '
                      'no files provided, will lint all files.')
  parser.add_argument('--ignore', '-i', dest='ignore_file', help='A text file '
                      'containting list of files to ignore.')
  parser.add_argument('--merge', action='store_true', help='Merge results.')
  parser.add_argument('--output', '-o', help='Output file for storing results.')
  parser.add_argument('--verbose', '-v', action='store_true', help='Prints '
                      'additional output.')
  args = parser.parse_args()

  log_level = logging.DEBUG if args.verbose else logging.WARNING
  logging.basicConfig(format='%(message)s', level=log_level)

  if args.merge:
    return merge_results(args.files, args.output)
  else:
    return process(args.files, args.ignore_file, args.output)

if __name__ == '__main__':
  sys.exit(main())
