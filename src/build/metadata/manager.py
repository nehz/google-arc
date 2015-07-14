# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Parses metadata definitions in definitions.json

import json
import re

_METADATA_FILE_LOCATION = 'src/build/metadata/definitions.json'


class MetadataDefinition(object):
  def __init__(self, json_dict):
    self.name = json_dict['name']
    self.default_value = json_dict['defaultValue']
    self._command_argument_name = json_dict.get('commandArugmentName')
    self.allowed_values = json_dict.get('allowedValues')
    self.short_option_name = json_dict.get('shortOptionName')
    self.short_value_mapping = json_dict.get('shortValueMapping')
    self.help = json_dict.get('help')
    self.developer_only = json_dict.get('developerOnly', False)
    self.external_only = json_dict.get('externalOnly', False)
    self.plugin = json_dict.get('plugin', False)
    self.child_plugin = json_dict.get('childPlugin', False)

  @property
  def command_argument_name(self):
    if self._command_argument_name:
      return self._command_argument_name
    else:
      return re.sub('([A-Z])', r'-\1', self.name).lower()

  @property
  def python_name(self):
    return re.sub('-', '_', self.command_argument_name)


def get_metadata_definitions():
  with open(_METADATA_FILE_LOCATION, 'r') as f:
    metadata_json = json.load(f)

  return map(MetadataDefinition, metadata_json)
