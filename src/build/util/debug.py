# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module contains utility to help debug across scripts."""

import inspect
import numbers
import sys
import traceback


# The number of context lines to retrieve from each frame. The variables
# included in the lines before the center of the context are printed by
# _write_argvalues.
_NUM_LINES_CODE_CONTEXT = 5


def _write_argvalues(frame, output_stream, written_vars):
  """Writes the argument info about the given frame to output_stream."""
  arg_info = inspect.getargvalues(frame)
  frameinfo = inspect.getframeinfo(frame, _NUM_LINES_CODE_CONTEXT)

  # Check the variables which appear in the lines on or before the center of
  # the context lines. Since we simply use string.find, wrong variables can be
  # picked up if the context lines happen to include the names in a different
  # meaning, but we tolerate the errors as they are not much harmful.
  # code_context can be None (e.g. built-in functions).
  code_context = frameinfo.code_context
  args = []
  if code_context:
    code_context = code_context[:len(code_context) / 2 + 1]
    code_context.reverse()
    for name, value in arg_info.locals.iteritems():
      for i, code in enumerate(code_context):
        # Record i and the variable position in the context line so the
        # variables are sorted in the dictionary order of
        # (distance from the center of context, position in the context).
        pos_in_code = code.find(name)
        if pos_in_code != -1:
          args.append(((i, pos_in_code), name, value))
          break

  # Rewrite the variables to be easier to read.
  for i, (pos, name, value) in enumerate(args):
    # Keep numbers or boolean as-is (Note: bool is a subclass of
    # numbers.Number).
    if isinstance(value, numbers.Number):
      continue
    # Enclose strings with single quotes.
    if isinstance(value, basestring):
      args[i] = (pos, name, repr(value))
      continue
    # Keep the other value considered as false as-is
    # (e.g. None, [], (), {}, set()).
    if not value:
      continue
    # Rewrite the other objects using the name in written_vars if it exists.
    for written_name, written_value in written_vars:
      if value is written_value:
        args[i] = (pos, name, '|%s|' % written_name)
        break
    else:
      written_vars.append((name, value))

  if args:
    output_stream.write('    ArgInfo: %s\n' % (
        ', '.join('%s=%s' % (name, value) for _, name, value in sorted(args))))


def write_frames(output_stream):
  """This function prints all the stack traces of running threads."""
  output_stream.write('Dumping stack trace of all threads.\n')
  for thread_id, current_frame in sys._current_frames().iteritems():
    output_stream.write('Thread ID: 0x%08X\n' % thread_id)
    frames = inspect.getouterframes(current_frame)
    written_vars = []
    # Iterate frames in reverse order to print frames in the same order as
    # the output of traceback.print_stack without limit argument.
    # Do not write the argument info of write_frames itself (frame[0]) because
    # it is not useful and can be huge.
    for i, frame in enumerate(reversed(frames[1:])):
      traceback.print_stack(frame[0], limit=1, file=output_stream)
      _write_argvalues(frame[0], output_stream, written_vars)
    output_stream.write('\n')  # Empty line to split each thread.
