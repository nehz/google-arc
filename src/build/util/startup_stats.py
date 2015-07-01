# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections

from util import statistics

_RAW_STAT_VARS = ['pre_plugin_time_ms',
                  'pre_embed_time_ms',
                  'plugin_load_time_ms',
                  'on_resume_time_ms',
                  'app_virt_mem',
                  'app_res_mem',
                  'app_pdirt_mem']
_DERIVED_STAT_VARS = ['boot_time_ms']
_ALL_STAT_VARS = _RAW_STAT_VARS + _DERIVED_STAT_VARS


class StartupStats:
  def __init__(self):
    for name in _RAW_STAT_VARS:
      setattr(self, name, None)

  def is_complete(self):
    """Returns True when all variables are assigned."""
    return all(getattr(self, name) is not None
               for name in _RAW_STAT_VARS)

  @property
  def boot_time_ms(self):
    return self.pre_plugin_time_ms + self.on_resume_time_ms


def _build_raw_stats(stats_list):
  """Builds a dict from stat key to a list of stat values."""
  raw_stats = collections.defaultdict(list)
  for stats in stats_list:
    assert stats.is_complete()
    for name in _ALL_STAT_VARS:
      raw_stats[name].append(getattr(stats, name))
  return raw_stats


def print_raw_stats(stats):
  """Prints the VRAWPERF= line of the given |stats|."""
  print 'VRAWPERF=%s' % dict(_build_raw_stats([stats]))


def print_aggregated_stats(stats_list):
  """Prints the aggregated stats of given |stats_list|."""
  # Skip incomplete stats (probably crashed during this run).  We collect
  # enough runs to make up for an occasional missed run.
  stat_list = [stats for stats in stats_list if stats.is_complete()]

  raw_stats = _build_raw_stats(stats_list)

  # Builds a dict from key to (median, 90-percentile).
  aggregated_stats = {
      key: statistics.compute_percentiles(value, (50, 90))
      for key, value in raw_stats.iteritems()
  }

  # If there is more than 1 stats, print the VPERF= and VRAWPERF= lines.
  if len(stats_list) > 1:
    # Print VPERF= lines.
    for name in _ALL_STAT_VARS:
      unit = 'ms' if name.endswith('_ms') else 'MB'
      median, p90 = aggregated_stats[name]
      print 'VPERF=%(name)s: %(median).2f%(unit)s 90%%=%(p90).2f' % {
          'name': name,
          'unit': unit,
          'median': median,
          'p90': p90,
      }

    # Print VRAWPERF= line.
    print 'VRAWPERF=%s' % dict(raw_stats)

  # Note: since each value is the median for each data set, they are not
  # guaranteed to add up.
  print ('\nPERF=boot:%dms (preEmbed:%dms + pluginLoad:%dms + onResume:%dms),'
         '\n     virt:%dMB, res:%dMB, pdirt:%dMB, runs:%d\n' % (
             aggregated_stats['boot_time_ms'][0],
             aggregated_stats['pre_embed_time_ms'][0],
             aggregated_stats['plugin_load_time_ms'][0],
             aggregated_stats['on_resume_time_ms'][0],
             aggregated_stats['app_virt_mem'][0],
             aggregated_stats['app_res_mem'][0],
             aggregated_stats['app_pdirt_mem'][0],
             len(stat_list)))
