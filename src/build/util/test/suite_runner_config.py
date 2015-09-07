# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import glob
import imp
import os.path
import re
import sys

from src.build import build_common
from src.build.build_options import OPTIONS
from src.build.util.test import flags

# For use in the suite configuration files, to identify a default configuration
# to use for a list of related suites.
SUITE_DEFAULTS = 'SUITE-DEFAULTS'

# Default timeout is 300 secs.
_DEFAULT_OUTPUT_TIMEOUT = 300

# 'bug' field must be matched with the following pattern.
_BUG_PATTERN = re.compile(r'crbug.com/\d+$')


def _validate(raw_config):
  """Validates raw_config dict.

  Here is the check list.
  - Types.
  - Whether there are unknown field names or not.
  - Nested structure of suite_test_expectations.
  - 'configurations' field must be at top-level.
  - bug's format check.
  """
  if raw_config is None:
    return
  _validate_internal(raw_config, True)


def _validate_internal(raw_config, is_root):
  validator_map = {
      'flags': _validate_flags,
      'deadline': _validate_deadline,
      'bug': _validate_bug,
      'suite_test_expectations': _validate_suite_test_expectations,
      'metadata': _validate_metadata,
      'test_order': _validate_test_order,
  }

  if is_root:
    validator_map['configurations'] = _validate_configurations
  else:
    validator_map['enable_if'] = _validate_enable_if

  unknown_field_list = [
      name for name in raw_config if name not in validator_map]
  assert not unknown_field_list, (
      'Unknown fields are found in the test config: %s' % (
          str(unknown_field_list)))

  # Apply validator to all the fields.
  for name, value in raw_config.iteritems():
    validator_map[name](value)


def _validate_flags(value):
  assert isinstance(value, flags.FlagSet), (
      'Not a recognized flag: %s' % value)


def _validate_deadline(value):
  assert isinstance(value, int) and value > 0, (
      'Not a valid integer: %s' % value)


def _validate_bug(value):
  for bug_url in value.split(','):
    assert _BUG_PATTERN.match(bug_url.strip()), (
        'Not a valid bug url (crbug.com/NNNNNN): %s' % bug_url)


def _validate_suite_test_expectations(value):
  assert isinstance(value, dict), (
      'suite_test_expectations is not a dict: %s' % value)

  for outer_name, outer_expectation in value.iteritems():
    # The key must be a string.
    assert isinstance(outer_name, basestring), (
        'suite_test_expectations %s is not a string' % outer_name)

    # The value must be an flags.FlagSet or a dict.
    if isinstance(outer_expectation, flags.FlagSet):
      assert '*' == outer_name or '*' not in outer_name, (
          'suite_test_expectations pattern "%s" is not allowed. Only "*" is '
          'allowed.' % outer_name)
      assert outer_name.count('#') <= 1, (
          'suite_test_expectations pattern "%s" is not allowed. The "#" '
          'character is only expected at most once.' % outer_name)
      continue
    assert isinstance(outer_expectation, dict), (
        'suite_test_expectations %s needs to be either a dict or an '
        'expectation flag set: %s' % (outer_name, outer_expectation))
    assert '*' not in outer_name, (
        'suite_test_expectations "%s" is not a valid name (no asterisks '
        'allowed)' % outer_name)
    for inner_name, inner_expectation in outer_expectation.iteritems():
      # Inner dict must be a map from string to an expectation flag set.
      assert isinstance(inner_name, basestring), (
          'suite_test_expectations %s#%s is not a string' % (
              outer_name, inner_name))
      assert isinstance(inner_expectation, flags.FlagSet), (
          'suite_test_expectations %s#%s is not an expectation flag set: '
          '%s' % (outer_name, inner_name, inner_expectation))
      assert '*' == inner_name or '*' not in inner_name, (
          'suite_test_expectations pattern "%s#%s" is not allowed. Only "%s#*" '
          'is allowed.' % (outer_name, inner_name, outer_name))
      assert '#' not in inner_name, (
          'suite_test_expectations pattern "%s#%s" is not allowed. The "#" '
          'character is only expected at most once.' % (
              outer_name, inner_name))


def _validate_configurations(value):
  assert isinstance(value, list), ('configurations is not a list: %s' % value)
  # Recursively validate the elements.
  for config in value:
    _validate_internal(config, False)


def _validate_metadata(value):
  assert isinstance(value, dict), ('metadata is not a dictionary: %s', value)


def _validate_enable_if(value):
  assert isinstance(value, bool), (
      'configuration enable_if is not a boolean: %s', value)


def _validate_test_order(value):
  assert isinstance(value, dict), ('test_order is not a dict: %s', value)
  for name, order in value.iteritems():
    assert isinstance(name, basestring), (
        'test_order\'s key is not a string: %s' % name)
    assert isinstance(order, int), (
        'test_order\'s %s value is not an int: %s' % (name, order))


def _evaluate(raw_config, defaults=None):
  """Flatten the raw_config based on the configuration"""
  _validate(raw_config)

  result = {
      'flags': flags.FlagSet(flags.PASS),
      'bug': None,
      'deadline': _DEFAULT_OUTPUT_TIMEOUT,
      'test_order': {},
      'suite_test_expectations': {},
      'metadata': {},
  }
  if defaults:
    # We need to make a deep copy so that we do not modify any dictionary or
    # array data in place and affect the default values for subsequent use.
    result.update(copy.deepcopy(defaults))

  if not raw_config:
    return result

  # Merge configurations.
  _merge_config(raw_config, result)

  # Apply conditional configurations.
  for configuration in raw_config.get('configurations', []):
    if not configuration.get('enable_if', True):
      continue
    _merge_config(configuration, result)

  return result


def _merge_config(raw_config, output):
  """Merges the |raw_config| into |output|.

  Merges values in raw_config (if exists) into output. Here is the strategy:
  - flags: Use expectation.FlagSet#override.
  - bug, deadline: simply overwrite by raw_config's.
  - metadata, test_order, suite_test_expectations: merge by dict.update().
  Note that: just before the merging, the nested suite_test_expectations
  dict is flattened.
  """
  if 'flags' in raw_config:
    output['flags'] = output['flags'].override_with(raw_config['flags'])
  if 'bug' in raw_config:
    output['bug'] = raw_config['bug']
  if 'deadline' in raw_config:
    output['deadline'] = raw_config['deadline']
  if 'metadata' in raw_config:
    output['metadata'].update(raw_config['metadata'])
  if 'test_order' in raw_config:
    output['test_order'].update(raw_config['test_order'])
  if 'suite_test_expectations' in raw_config:
    output['suite_test_expectations'].update(
        _evaluate_suite_test_expectations(
            raw_config['suite_test_expectations']))


def _evaluate_suite_test_expectations(raw_dict):
  """Flatten the (possibly-nested) suite_test_expectations dict."""
  result = {}
  for outer_name, outer_expectation in raw_dict.iteritems():
    if isinstance(outer_expectation, flags.FlagSet):
      result[outer_name] = (
          flags.FlagSet(flags.PASS).override_with(outer_expectation))
      continue
    for inner_name, inner_expectation in outer_expectation.iteritems():
      result['%s#%s' % (outer_name, inner_name)] = (
          flags.FlagSet(flags.PASS).override_with(inner_expectation))
  return result


def _read_test_config(path, on_bot, use_gpu, remote_host_type):
  """Reads the file, and eval() it with the test config context."""
  if not os.path.exists(path):
    return {}

  with open(path) as stream:
    content = stream.read()
  test_context = {
      '__builtin__': None,  # Do not inherit the current context.

      # Expectation flags.
      'PASS': flags.FlagSet(flags.PASS),
      'FLAKY': flags.FlagSet(flags.FLAKY),
      'FAIL': flags.FlagSet(flags.FAIL),
      'TIMEOUT': flags.FlagSet(flags.TIMEOUT),
      'NOT_SUPPORTED': flags.FlagSet(flags.NOT_SUPPORTED),
      'LARGE': flags.FlagSet(flags.LARGE),

      # OPTIONS is commonly used for the conditions.
      'OPTIONS': OPTIONS,

      # Variables which can be used to check runtime configurations.
      'ON_BOT': on_bot,
      'USE_GPU': use_gpu,
      'USE_NDK_DIRECT_EXECUTION': build_common.use_ndk_direct_execution(),

      # Platform information of the machine on which the test runs for
      # remote execution. If it is not the remote execution, all variables
      # below will be False.
      'ON_CYGWIN': remote_host_type == 'cygwin',
      'ON_MAC': remote_host_type == 'mac',
      'ON_CHROMEOS': remote_host_type == 'chromeos',
  }

  try:
    raw_config = eval(content, test_context)
  except Exception as e:
    e.args = (e.args[0] + '\neval() failed: ' + path,) + e.args[1:]
    raise

  try:
    _validate(raw_config)
  except Exception as e:
    e.args = (e.args[0] + '\nValidation failed: ' + path,) + e.args[1:]
    raise
  return raw_config


def default_run_configuration():
  return _evaluate({
      'configurations': [{
          'enable_if': OPTIONS.weird(),
          'flags': flags.FlagSet(flags.FLAKY),
      }]})


def make_suite_run_configs(raw_config):
  def _deferred():
    defaults = default_run_configuration()
    raw_config_dict = raw_config()

    # Locate the defaults up front so they can be used to initialize
    # everything else.
    suite_defaults = raw_config_dict.get(SUITE_DEFAULTS)
    if suite_defaults:
      defaults = _evaluate(suite_defaults, defaults=defaults)

    # Evaluate the runner configuration of everything we might want to run.
    return dict((package_name, _evaluate(config, defaults=defaults))
                for package_name, config in raw_config_dict.iteritems())

  return _deferred  # Defer to pick up runtime configuration options properly.


# TODO(crbug.com/384028): The class will eventually eliminate the need for
# make_suite_run_configs and default_run_configuration above.
class SuiteExpectationsLoader(object):
  def __init__(self, base_path, on_bot, use_gpu, remote_host_type):
    self._base_path = base_path
    self._on_bot = on_bot
    self._use_gpu = use_gpu
    self._remote_host_type = remote_host_type
    self._cache = {}

  def get(self, suite_name):
    parent_config = None
    components = suite_name.split('.')
    for i in xrange(1 + len(components)):
      partial_name = '.'.join(components[:i]) if i else 'defaults'
      config = self._cache.get(partial_name)
      if config is None:
        raw_config = _read_test_config(
            os.path.join(self._base_path, partial_name),
            self._on_bot, self._use_gpu, self._remote_host_type)
        config = _evaluate(raw_config, defaults=parent_config)
        self._cache[partial_name] = config
      parent_config = config
    return config


def get_suite_definitions_module(suite_filename):
  with open(suite_filename) as suite_definitions:
    sys.dont_write_bytecode = True
    definitions_module = imp.load_source(
        '', suite_filename, suite_definitions)
    sys.dont_write_bytecode = False
    return definitions_module


def load_from_suite_definitions(definitions_base_path,
                                expectations_base_path,
                                on_bot,
                                use_gpu,
                                remote_host_type):
  """Loads all the suite definitions from a given path.

  |definitions_base_path| gives the path to the python files to load.
  |expectations_base_path| gives the path to the expectation files to load,
  which are matched up with each suite automatically.
  """
  expectations_loader = SuiteExpectationsLoader(
      expectations_base_path, on_bot, use_gpu, remote_host_type)
  runners = []

  definition_files = glob.glob(os.path.join(definitions_base_path, '*.py'))

  # Filter out anything that is a unit test of a definition file.
  definition_files = [name for name in definition_files
                      if not name.endswith(('_test.py', '/config.py'))]

  for suite_filename in definition_files:
    definitions_module = get_suite_definitions_module(suite_filename)
    runners += definitions_module.get_integration_test_runners(
        expectations_loader)
  return runners
