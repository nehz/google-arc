# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Annotates original source code location for compiled JavaScript.

We run Closure Compiler for JavaScripts. It concateneates and compacts
all sources with renaming and manipulating white spaces, etc. As a result,
it is hard to see where the original code is.

This module provides a class to annotate the original code location for
chrome's log output.
"""

import re

import sourcemap


# Regex pattern to detect source-line info for compiled sources. This will
# match with, for example, following lines:
#
#   chrome-extension://{HASH}/gen_test.min.js:63:330
#   chrome-extension://{HASH}/_modules/{HASH}/gen_main.min.js (26)
#
# where {HASH} is a hash value for the extension.
_LINE_PATTERN = re.compile(
    r'chrome-extension://[^/]+?/(?:_modules/[^/]+/)?'
    r'(?P<compiled_path>.*?\.js)'
    r'(?::(?P<stacktrace_line>\d+):(?P<stacktrace_column>\d+)|'
    r' \((?P<logging_line>\d+)\))')


class _SourceMapDecoder(object):
  def __init__(self, compiled_file_path, sourcemap_file_path):
    with open(compiled_file_path) as stream:
      self._compiled_lines = stream.read().splitlines()
    with open(sourcemap_file_path) as stream:
      self._sourcemap_index = sourcemap.load(stream)

  def decode(self, line, column):
    """Returns the original source location for the given code location.

    In this method, line and column is 1-origin.

    Args:
      line: the line number of the compiled code.
      column: the column number of the compiled code. This is optional. If set
          to None, this method detects the column.
    """
    if column is None:
      # If column is None, this comes from the console. Search it in the line.
      # If there are many "console"s, we use first one heuristically.
      # This may return wrong column, but humans should be able to find the
      # correct one.
      index = self._compiled_lines[line - 1].find('console.')
      if index >= 0:
        column = index + 1

    if column is not None:
      # Note: sourcemap library has a problem when looking up a source position
      # for a position across line boundary in the generated code.
      # In such cases, fallback to the below logic as a work around.
      try:
        token = self._sourcemap_index.lookup(line - 1, column - 1)
      except IndexError:
        token = None
      if token:
        return '%s:%s:%s' % (token.src, token.src_line + 1, token.src_col + 1)

    # Here, failed to look up the token.
    # Try to use the first token for the line as a fallback.
    line_index = self._sourcemap_index.line_index[line - 1]
    if not line_index:
      # Still not found. Just give up.
      return None
    return self._sourcemap_index.index.get((line - 1, line_index[0]))


class SourceAnnotator(object):
  def __init__(self, source_list):
    """Initializes the annotator.

    Args:
      source_list: a list of triples (JavaScript path in the production,
          path to the compiled JavaScript, path to the sourcemap file).
    """
    self._decoder_map = {}
    for script_name, compiled_file_path, sourcemap_file_path in source_list:
      self._decoder_map[script_name] = _SourceMapDecoder(
          compiled_file_path, sourcemap_file_path)

  def annotate(self, line):
    """Annotates original source code location to the line if possible.

    The line should be the Chrome's log output. If it contains the console
    logging message or stack trace, this method returns the line with
    annotating original source code location.

    Args:
      line: Chrome's JavaScript log output.

    Returns:
      The given line with annotating the orignal source code location.
      If not found, returns the line as is.
    """
    return re.sub(_LINE_PATTERN, self._replace, line)

  def _replace(self, match):
    decoder = self._decoder_map.get(match.group('compiled_path'))
    if not decoder:
      # Do nothing.
      return match.group(0)

    if match.group(2):
      # Matched with the stack trace.
      line = int(match.group('stacktrace_line'))
      column = int(match.group('stacktrace_column'))
      suffix = ''
    else:
      # Matched with the console logging.
      line = int(match.group('logging_line'))
      column = None
      suffix = '?'
    original_location = decoder.decode(line, column)
    if not original_location:
      return match.group(0)
    return '{matched_line} ({original_location}{suffix})'.format(
        matched_line=match.group(0),
        original_location=original_location,
        suffix=suffix)
