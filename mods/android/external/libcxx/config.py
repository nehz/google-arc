# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from src.build import make_to_ninja
from src.build import open_source
from src.build.build_options import OPTIONS

_LIBCXX_PATH = 'android/external/libcxx'


def generate_ninjas():
  def _filter(vars):
    if open_source.is_open_source_repo() and vars.is_host():
      return False
    # Shared object version just links the static library version. To avoid a
    # module name conflict, we just build static library version as a converted
    # shared object.
    if vars.is_shared():
      return False
    make_to_ninja.Filters.convert_to_shared_lib(vars)

    # Build libc++.so as a system library so that it does not link to
    # libstlport.so, and does not emit syscall wrappers.
    vars.get_generator_args()['is_system_library'] = True
    if vars.is_target():
      # A side-effect of |is_system_library| is that it also removes the
      # dependencies on libc, libm, and libdl. We still need them, so add them
      # back.
      vars.get_shared_deps().extend(['libc', 'libm', 'libdl'])

    # Install an additional ARM version of libc++.so for Renderscript.
    if (vars.is_target() and vars.get_module_name() == 'libc++' and
        not OPTIONS.is_arm()):
      vars.set_canned_arm(True)

    vars.get_whole_archive_deps().remove('libcompiler_rt')
    vars.get_shared_deps().append('libcompiler_rt')

    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/external/libcxx').generate(_filter)
