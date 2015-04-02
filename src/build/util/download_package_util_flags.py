# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Defines extra command line flags for use with download_package_util."""


def add_extra_flags(parser):
  """Adds extra flags to a argparse.ArgumentParser instance.

  The extra flags can be used to used to configure how the downloaded files are
  cached.
  """

  parser.add_argument(
      '--download-cache-path', default='cache', metavar='path',
      help='Specifies the path to a download cache to use for downloads.')

  parser.add_argument(
      '--download-cache-size', default=3, type=int,
      help=('Specifies the number of versions for each download to keep in the '
            'download cache. The default of three means to keep the three most '
            'recently downloaded versions of each.'))
