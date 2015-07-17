# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for logging."""

import logging
import pipes


# Log header format. See setup()'s comment for details.
_MSG_FORMAT = (
    '%(levelinitial)s/%(asctime)s.%(msecs)03d000 %(process)d-%(thread)d '
    '%(module)s:%(lineno)s] %(message)s')
_DATE_FORMAT = '%m%d %H:%M:%S'


class _LevelInitialCharacterFilter(logging.Filter):
  """Sets up |levelinitial| field of the logging.LogRecord.

  This class translates the logging.LogRecord.levelno to levelinital,
  which is used in the _MSG_FORMAT.
  """
  _INITIAL_CHARACTER_DICT = {
      logging.DEBUG: 'D',
      logging.INFO: 'I',
      logging.WARNING: 'W',
      logging.ERROR: 'E',
      logging.FATAL: 'F',
  }

  def filter(self, record):
    """Translates the levelno to levelinitial.

    Args:
      record: LogRecord for filtering.
    Returns:
      Always True. See logging.Filter.filter() for more details.
    """
    record.levelinitial = (
        _LevelInitialCharacterFilter._INITIAL_CHARACTER_DICT.get(
            record.levelno, record.levelname[0]))
    return True


def setup(level=logging.WARNING):
  """Initializes the default logging module.

  After invoking this function, the header of the logging message is
  something similar to glog style, as follows:

  I/MMDD HH:mm:SS.USEC PID-TID MODULENAME:LINENO] LOGGING_MESSAGE.

  Note: the difference is as follows:
  - The resolution of the fraction part of "second" is msec (in google-glog,
    it is usec). I.e., it always shows 6 digits, but trailing three digits are
    always zero.
  - PID is also shown, in addition to TID.
  - MODULENAME is used, instead of filename.

  cf) https://github.com/google/glog/blob/master/src/logging.cc#L1615
    (google-glog, LogSink::ToString()).

  Args:
    level: Minimum logging level.
  """
  logging.basicConfig(level=level, format=_MSG_FORMAT, datefmt=_DATE_FORMAT)
  logger = logging.getLogger()
  logger.addFilter(_LevelInitialCharacterFilter())


def format_commandline(args, cwd=None, env=None):
  """Formats the command line string in the form to run on shell.

  Args:
    args: Command line arguments, including the command itself.
        It must be a list of string.
    cwd: Working directory for the command. Can be None for unspecified.
    env: Dict of environment variables. Can be None for unspecified.
  Returns:
    Formatted command line string.
  """
  result = []

  # If cwd was specified, emulate it with a pushd and popd.
  if cwd:
    result.extend(['pushd', cwd, ';'])
  if env:
    result.extend('%s=%s' % item for item in env.iteritems())
  result.extend(pipes.quote(arg) for arg in args)
  if cwd:
    result.extend([';', 'popd'])

  return ' '.join(result)
