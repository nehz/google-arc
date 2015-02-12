# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import copy
import glob
import imp
import os.path
import re
import sys

from build_options import OPTIONS
from util.test import suite_runner_config_flags as flags


DEFAULT_OUTPUT_TIMEOUT = 300

# For use in the suite configuration files, to identify a default configuration
# to use for a list of related suites.
SUITE_DEFAULTS = 'SUITE-DEFAULTS'


class _SuiteRunConfiguration(object):
  _BUG_PATTERN = re.compile(r'crbug.com/\d+$')

  def __init__(self, name, config=None):
    self._name = name
    self._config = config if config else {}

  def validate(self):
    validators = dict(
        flags=self._validate_flags,
        deadline=self._validate_deadline,
        bug=self._validate_bug,
        configurations=self._validate_configurations,
        suite_test_expectations=self._validate_suite_test_expectations,
        metadata=self._validate_metadata)

    for key, value in self._config.iteritems():
      validators[key](value)

    return self

  def _validate_flags(self, value):
    assert isinstance(value, flags.ExclusiveFlagSet), (
        'Not a recognized flag: %s' % value)

  def _validate_deadline(self, value):
    assert isinstance(value, int) and int > 0, (
        'Not a valid integer: %s' % value)

  def _validate_bug(self, value):
    for bug_url in value.split(','):
      assert self._BUG_PATTERN.match(bug_url.strip()), (
          'Not a valid bug url (crbug.com/NNNNNN): %s' % bug_url)

  def _validate_configurations(self, configuration_list):
    if configuration_list is None:
      return
    assert isinstance(configuration_list, list), (
        'configurations is not a list')
    for configuration in configuration_list:
      self._validate_configuration(configuration)

  def _validate_suite_test_expectations(self, class_config_dict):
    if class_config_dict is None:
      return
    assert isinstance(class_config_dict, dict), (
        'suite_test_expectations is not a dictionary')
    for outer_name, outer_expectation in class_config_dict.iteritems():
      assert isinstance(outer_name, basestring), (
          'suite_test_expectations %s is not a string' % outer_name)
      if isinstance(outer_expectation, flags.ExclusiveFlagSet):
        pass  # Not much more to validate.
      elif isinstance(outer_expectation, dict):
        for inner_name, inner_expectation in outer_expectation.iteritems():
          assert isinstance(inner_name, basestring), (
              'suite_test_expectations %s.%s is not a string' % (
                  outer_name, outer_expectation))
          assert isinstance(inner_expectation, flags.ExclusiveFlagSet), (
              'suite_test_expectations %s.%s is not an expectation flag '
              'combination' % (outer_name, inner_name, inner_expectation))
      else:
        assert False, (
            'suite_test_expectations %s needs to be a dictionary or an '
            'expectation flag combination' % outer_name)

  def _validate_enable_if(self, value):
    assert isinstance(value, bool), (
        'configuration enable_if is not a boolean')

  def _validate_metadata(self, value):
    if value is None:
      return
    assert isinstance(value, dict), (
        'metadata is not a dictionary')

  def _validate_test_order(self, value):
    assert isinstance(value, collections.OrderedDict), (
        'test_order is not a collections.OrderedDict')
    for k, v in value.iteritems():
      assert isinstance(k, basestring), (
          '"%s" is not a string.' % k)
      unused = int(v)  # Ensure conversion  # NOQA

  def _validate_configuration(self, config_dict):
    assert isinstance(config_dict, dict), (
        'configuration is not a dictionary')

    validators = dict(
        bug=self._validate_bug,
        deadline=self._validate_deadline,
        enable_if=self._validate_enable_if,
        flags=self._validate_flags,
        test_order=self._validate_test_order,
        suite_test_expectations=self._validate_suite_test_expectations)

    for key, value in config_dict.iteritems():
      validators[key](value)

  def evaluate(self, defaults=None):
    # TODO(lpique): Combine validation and evaluation. We only need to walk
    # through the data once.
    self.validate()

    output = dict(bug=None, deadline=DEFAULT_OUTPUT_TIMEOUT,
                  flags=flags.PASS, test_order=collections.OrderedDict(),
                  suite_test_expectations={})
    if defaults:
      # We need to make a deep copy so that we do not modify any dictionary or
      # array data in place and affect the default values for subsequent use.
      output.update(copy.deepcopy(defaults))

    evaluators = dict(
        flags=self._eval_flags,
        deadline=self._eval_deadline,
        bug=self._eval_bug,
        configurations=self._eval_configurations,
        suite_test_expectations=self._eval_suite_test_expectations,
        metadata=self._eval_metadata)

    for key, value in self._config.iteritems():
      evaluators[key](output, value)

    return output

  def _eval_flags(self, output, value):
    output['flags'] |= value

  def _eval_deadline(self, output, value):
    output['deadline'] = value

  def _eval_bug(self, output, value):
    output['bug'] = value

  def _eval_suite_test_expectations(self, output, config_dict):
    expectations = output['suite_test_expectations']
    for outer_name, outer_expectation in config_dict.iteritems():
      if isinstance(outer_expectation, dict):
        for inner_name, inner_expectation in outer_expectation.iteritems():
          test_name = '%s#%s' % (outer_name, inner_name)
          expectations[test_name] = flags.PASS | inner_expectation
      else:
        expectations[outer_name] = flags.PASS | outer_expectation

  def _eval_enable_if(self, output, value):
    # We don't expect this configuration section to be evaluated at all unless
    # it has already been evaluated as enabled!
    assert value

  def _eval_metadata(self, output, value):
    output['metadata'] = value

  def _eval_test_order(self, output, value):
    test_order = output['test_order']
    for k, v in value.iteritems():
      test_order[k] = v

  def _eval_configurations(self, output, configuration_list):
    if configuration_list is None:
      return

    evaluators = dict(
        bug=self._eval_bug,
        deadline=self._eval_deadline,
        enable_if=self._eval_enable_if,
        flags=self._eval_flags,
        test_order=self._eval_test_order,
        suite_test_expectations=self._eval_suite_test_expectations)

    for configuration in configuration_list:
      if configuration.get('enable_if', True):
        for key, value in configuration.iteritems():
          evaluators[key](output, value)

  _eval_config_expected_failing_tests = _eval_suite_test_expectations
  _eval_config_flags = _eval_flags
  _eval_config_bug = _eval_bug
  _eval_config_deadline = _eval_deadline


def default_run_configuration():
  return _SuiteRunConfiguration(None, config={
      'flags': flags.PASS,
      'suite_test_expectations': {},
      'deadline': 300,  # Seconds
      'configurations': [{
          'enable_if': OPTIONS.weird(),
          'flags': flags.FLAKY,
      }],
      'metadata': {}
  }).evaluate()


def make_suite_run_configs(raw_config):
  def _deferred():
    global_defaults = default_run_configuration()
    raw_config_dict = raw_config()

    # Locate the defaults up front so they can be used to initialize
    # everything else.
    defaults = raw_config_dict.get(SUITE_DEFAULTS)
    if defaults is not None:
      del raw_config_dict[SUITE_DEFAULTS]
      defaults = _SuiteRunConfiguration(
          None, config=defaults).evaluate(defaults=global_defaults)
    else:
      defaults = global_defaults

    # Evaluate the runner configuration of everything we might want to run.
    configs = {}
    for package_name, package_config in raw_config_dict.iteritems():
      configs[package_name] = _SuiteRunConfiguration(
          package_name, config=package_config).evaluate(defaults=defaults)
    return configs

  return _deferred  # Defer to pick up runtime configuration options properly.


# TODO(crbug.com/384028): The class will eventually eliminate the need for
# make_suite_run_configs and default_run_configuration above, and make it
# easier to clean up _SuiteRunConfiguration too.
class SuiteExpectationsLoader(object):
  def __init__(self, base_path):
    self._base_path = base_path
    self._cache = {}

  def _get_raw_expectations_dict(self, suite_name):
    suite_expectations_path = os.path.join(self._base_path, suite_name + '.py')
    if not os.path.exists(suite_expectations_path):
      return {}
    with open(suite_expectations_path) as suite_expectations:
      sys.dont_write_bytecode = True
      config_module = imp.load_source('', suite_expectations_path,
                                      suite_expectations)
      sys.dont_write_bytecode = False
      return config_module.get_expectations()

  def get(self, suite_name):
    parent_config = None
    components = suite_name.split('.')
    for i in xrange(1 + len(components)):
      partial_name = '.'.join(components[:i]) if i else 'defaults'
      config = self._cache.get(partial_name)
      if config is None:
        raw_expectations_dict = self._get_raw_expectations_dict(partial_name)
        config = _SuiteRunConfiguration(
            partial_name,
            config=raw_expectations_dict).evaluate(defaults=parent_config)
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


def load_from_suite_definitions(definitions_base_path, expectations_base_path):
  """Loads all the suite definitions from a given path.

  |definitions_base_path| gives the path to the python files to load.
  |expectations_base_path| gives the path to the expectation files to load,
  which are matched up with each suite automatically.
  """
  expectations_loader = SuiteExpectationsLoader(expectations_base_path)
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
