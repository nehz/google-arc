#!src/build/run_python

# Copyright (C) 2014 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import sys

import open_source
from build_options import OPTIONS


def main(args):
  OPTIONS.parse_configure_file()

  # TODO(crbug.com/378196): Make qemu-arm available in open source in order to
  # run any unit tests there.
  if open_source.is_open_source_repo() and OPTIONS.is_arm():
    return 0

  for test_name in args[1:]:
    pipe = subprocess.Popen(['python', 'src/build/run_unittest.py',
                             test_name],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    out = pipe.communicate()[0]
    sys.stdout.write(out)
    if pipe.returncode:
      sys.stdout.write('FAIL (exit=%d)\n' % pipe.returncode)
      sys.stdout.write(out + '\n')
      return 1
    elif out.find('PASS\n') < 0:
      sys.stdout.write('FAIL (no PASS)\n')
      sys.stdout.write(out + '\n')
      return 1
    else:
      sys.stdout.write('OK\n')

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv))
