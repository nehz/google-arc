# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import string

from src.build import build_common
from src.build import make_to_ninja
from src.build import ninja_generator
from src.build import ninja_generator_runner
from src.build import open_source
from src.build import staging
from src.build import toolchain
from src.build.build_options import OPTIONS


_LOADER_TEXT_SECTION_START_ADDRESS = '0x20000'

_ARM_ASM_FILES = [
    # TODO(crbug.com/446400): L-rebase: Choose better optimized versions
    # of string functions.
    # 'android/bionic/libc/arch-arm/bionic/memcmp.S',
    # 'android/bionic/libc/arch-arm/bionic/memcpy.S',
    'android/bionic/libc/arch-arm/generic/bionic/memset.S',
]

_I686_ASM_FILES = [
    # Note: bzero internally uses memset. These should be enabled or disabled
    # as a pair.
    # 'android/bionic/libc/arch-x86/atom/string/sse2-memset-atom.S',
    # 'android/bionic/libc/arch-x86/atom/string/sse2-bzero-atom.S',
    'android/bionic/libc/arch-x86/atom/string/sse2-strchr-atom.S',
    # For saving register context for waiting threads.
    'android/bionic/libc/arch-x86/bionic/save_reg_context.S',
]

# The list of libc modules linked to the linker.
_LINKER_MODULES = [
    'libc_aeabi',  # __aeabi_memcpy etc.
    'libc_bionic',  # logging functions
    'libc_common',
    'libc_openbsd',  # strcmp, strcpy, exit etc.
]


def _add_bare_metal_flags_to_make_to_ninja_vars(vars):
  if ((vars.is_c_library() or vars.is_executable()) and
      OPTIONS.is_bare_metal_build()):
    vars.get_asmflags().append('-DBARE_METAL_BIONIC')
    vars.get_cflags().append('-DBARE_METAL_BIONIC')
    vars.get_cxxflags().append('-DBARE_METAL_BIONIC')


def _add_bare_metal_flags_to_ninja_generator(n):
  if OPTIONS.is_bare_metal_build():
    n.add_defines('BARE_METAL_BIONIC')


def _get_gen_source_dir():
  return ninja_generator.NaClizeNinjaGenerator.get_gen_source_dir('bionic')


def _get_gen_source_stamp():
  return ninja_generator.NaClizeNinjaGenerator.get_gen_source_stamp('bionic')


def _get_asm_source(f):
  # For NaCl, we need to use naclized version of aseembly code.
  if OPTIONS.is_nacl_build():
    f = os.path.join(_get_gen_source_dir(), os.path.basename(f))
  return f


def _remove_assembly_source(sources):
  asm_sources = filter(lambda s: s.endswith('.S'), sources)
  for asm in asm_sources:
    sources.remove(asm)


def _get_crt_cc():
  if OPTIONS.is_nacl_build():
    return toolchain.get_tool(OPTIONS.target(), 'clang')
  else:
    return toolchain.get_tool(OPTIONS.target(), 'cc')


def _get_crt_cxx():
  if OPTIONS.is_nacl_build():
    return toolchain.get_tool(OPTIONS.target(), 'clangxx')
  else:
    return toolchain.get_tool(OPTIONS.target(), 'cxx')


def _generate_naclized_i686_asm_ninja():
  if not OPTIONS.is_nacl_i686():
    return
  n = ninja_generator.NaClizeNinjaGenerator('bionic')
  n.generate(_I686_ASM_FILES)


def _filter_libc_common_for_arm(vars, sources):
  for f in _ARM_ASM_FILES:
    sources.append(_get_asm_source(f))
  if OPTIONS.is_bare_metal_build():
    # For direct syscalls used internally.
    sources.append('android/bionic/libc/arch-arm/bionic/syscall.S')
  else:
    # Generated assembly files are included from other assembly file.
    # So, we need to make additional dependency by using a stamp file.
    # Order-only dependency should be sufficient for this case
    # because all dependencies should be handled properly once .d
    # files are generated. However, we have a strict check for
    # order-only dependencies (see NinjaGenerator._check_deps)
    # so we use implicit dependencies here for now. As we do not
    # update assembly code often, this will not harm our iteration
    # cycle much.
    # TODO(crbug.com/318433): Use order-only dependencies.
    vars.get_implicit_deps().append(_get_gen_source_stamp())


def _filter_libc_common_for_i686(vars, sources):
  for f in _I686_ASM_FILES:
    sources.append(_get_asm_source(f))
  if OPTIONS.is_nacl_i686():
    # Assembly code requires cache.h.
    vars.get_includes().append('android/bionic/libc/arch-x86/atom/string')
  if OPTIONS.is_bare_metal_build():
    # For direct syscalls used internally.
    sources.append('android/bionic/libc/arch-x86/bionic/syscall.S')
  else:
    # See the comment in _filter_libc_common_for_arm.
    # TODO(crbug.com/318433): Use order-only dependencies.
    vars.get_implicit_deps().append(_get_gen_source_stamp())
  # It seems newlib's memset is slightly faster than the
  # assembly implementation (0.16[sec/GB] vs 0.19[sec/GB]).
  sources.append('nacl-newlib/newlib/libc/string/memset.c')
  sources.append('android/bionic/libc/string/bzero.c')
  # TODO(crbug.com/268485): Confirm ARC can ignore non-SSSE3 x86 devices
  vars.get_cflags().append('-DUSE_SSSE3=1')


def _filter_libc_common_for_x86_64(vars, sources):
  sources.extend([
      'android/bionic/libc/arch-nacl/bionic/nacl_read_tp.c',
      # TODO(crbug.com/446400): L-rebase: Enable assembly versions.
      'android/bionic/libc/string/bzero.c',
      'android/bionic/libc/bionic/time64.c',
      # Newlib's memset is much faster than Bionic's
      # memset.c. (0.13[sec/GB] vs 0.51[sec/GB])
      'nacl-newlib/newlib/libc/string/memset.c',

      # As we support ARM NDKs even on NaCl x86-64, we provide legacy
      # APIs.
      'android/bionic/libc/bionic/legacy_32_bit_support.cpp'])
  sources.append('android/bionic/libc/arch-x86_64/bionic/save_reg_context.S')


def _remove_unnecessary_defines(vars):
  """Cleans up unnecessary C/C++ defines."""
  # We always use hard-float.
  vars.remove_c_or_cxxflag('-DSOFTFLOAT')
  # Remove debug related macros since they should be controlled by
  # ./configure.
  vars.remove_c_or_cxxflag('-DNDEBUG')
  vars.remove_c_or_cxxflag('-UDEBUG')


def _filter_libc_common(vars):
  sources = vars.get_sources()
  _remove_assembly_source(sources)

  # libc_common is used from both the loader and libc.so. Functions
  # which are necessary for the bionic loader must be in this list.
  sources.extend([
      # TODO(crbug.com/243244): If possible, move arch-nacl/ files into a
      # separate archive and build them with -Werror.
      'android/bionic/libc/arch-nacl/bionic/__set_tls.c',
      'android/bionic/libc/arch-nacl/bionic/clone.cpp',
      'android/bionic/libc/arch-nacl/syscalls/__exit.cpp',
      'android/bionic/libc/arch-nacl/syscalls/__getcwd.c',
      'android/bionic/libc/arch-nacl/syscalls/__getdents64.c',
      'android/bionic/libc/arch-nacl/syscalls/__openat.c',
      'android/bionic/libc/arch-nacl/syscalls/_exit.c',
      'android/bionic/libc/arch-nacl/syscalls/clock_getres.c',
      'android/bionic/libc/arch-nacl/syscalls/clock_gettime.c',
      'android/bionic/libc/arch-nacl/syscalls/close.c',
      'android/bionic/libc/arch-nacl/syscalls/dup.c',
      'android/bionic/libc/arch-nacl/syscalls/dup2.c',
      'android/bionic/libc/arch-nacl/syscalls/enosys.c',
      'android/bionic/libc/arch-nacl/syscalls/fdatasync.c',
      'android/bionic/libc/arch-nacl/syscalls/fstat.c',
      'android/bionic/libc/arch-nacl/syscalls/fsync.c',
      'android/bionic/libc/arch-nacl/syscalls/futex.c',
      'android/bionic/libc/arch-nacl/syscalls/getpid.c',
      'android/bionic/libc/arch-nacl/syscalls/gettid.cpp',
      'android/bionic/libc/arch-nacl/syscalls/gettimeofday.c',
      'android/bionic/libc/arch-nacl/syscalls/getuid.c',
      'android/bionic/libc/arch-nacl/syscalls/kill.cpp',
      'android/bionic/libc/arch-nacl/syscalls/lseek.c',
      'android/bionic/libc/arch-nacl/syscalls/lseek64.c',
      'android/bionic/libc/arch-nacl/syscalls/lstat.c',
      'android/bionic/libc/arch-nacl/syscalls/mkdir.c',
      'android/bionic/libc/arch-nacl/syscalls/mmap.c',
      'android/bionic/libc/arch-nacl/syscalls/mprotect.c',
      'android/bionic/libc/arch-nacl/syscalls/munmap.c',
      'android/bionic/libc/arch-nacl/syscalls/nacl_stat.c',
      'android/bionic/libc/arch-nacl/syscalls/nacl_timespec.c',
      'android/bionic/libc/arch-nacl/syscalls/nacl_timeval.c',
      'android/bionic/libc/arch-nacl/syscalls/poll.c',
      'android/bionic/libc/arch-nacl/syscalls/prctl.cpp',
      'android/bionic/libc/arch-nacl/syscalls/read.c',
      'android/bionic/libc/arch-nacl/syscalls/recvfrom.c',
      'android/bionic/libc/arch-nacl/syscalls/rmdir.c',
      'android/bionic/libc/arch-nacl/syscalls/sendto.c',
      'android/bionic/libc/arch-nacl/syscalls/setpriority.c',
      'android/bionic/libc/arch-nacl/syscalls/socketpair.c',
      'android/bionic/libc/arch-nacl/syscalls/stat.c',
      'android/bionic/libc/arch-nacl/syscalls/tgkill.cpp',
      'android/bionic/libc/arch-nacl/syscalls/unlink.c',
      'android/bionic/libc/arch-nacl/syscalls/write.c',
      'android/bionic/libc/arch-nacl/syscalls/writev.c',
      'android/bionic/libc/arch-nacl/tmp/raw_print.c',
      # TODO(crbug.com/352917): Use assembly version on Bare Metal ARM.
      'android/bionic/libc/bionic/memcmp.c',
      'android/bionic/libc/bionic/memcpy.cpp',
      'android/bionic/libc/bionic/property_service.c',
      'android/bionic/libc/bionic/pthread_context.cpp',
      'android/bionic/libc/bionic/ffs.cpp'])
  if OPTIONS.is_nacl_build():
    # They define SFI NaCl specific functions for dynamic code.
    sources.extend([
        'android/bionic/libc/arch-nacl/syscalls/nacl_dyncode_create.c',
        'android/bionic/libc/arch-nacl/syscalls/nacl_dyncode_delete.c',
        # TODO(crbug.com/238463): Drop this.
        'android/bionic/libc/arch-nacl/syscalls/nacl_list_mappings.c'])

  if OPTIONS.is_arm():
    # TODO(crbug.com/352917): Use assembly version on Bare Metal ARM.
    sources.extend([
        'android/bionic/libc/bionic/__memcpy_chk.cpp'])
  elif OPTIONS.is_x86_64():
    sources.extend([
        'android/bionic/libc/bionic/memmove.c'])
  elif OPTIONS.is_i686():
    sources.extend([
        'android/bionic/libc/bionic/memchr.c',
        'android/bionic/libc/bionic/memrchr.c',
        'android/bionic/libc/bionic/memmove.c',
        'android/bionic/libc/bionic/strnlen.c',
        'android/bionic/libc/bionic/strrchr.cpp'])

  if OPTIONS.is_arm():
    _filter_libc_common_for_arm(vars, sources)
  elif OPTIONS.is_i686():
    _filter_libc_common_for_i686(vars, sources)
  elif OPTIONS.is_x86_64():
    _filter_libc_common_for_x86_64(vars, sources)
  if OPTIONS.is_x86_64():
    # ndk_cruft is only for 32 bit architectures which has ABI that we
    # want to correct in the newer 64 bit architectures. However, for
    # ARC, we are running ARM 32-bit NDK binaries even in x86-64, and
    # we need the same binary interface.
    sources.append('android/bionic/libc/bionic/ndk_cruft.cpp')
  vars.get_includes().append('android/bionic/libc/arch-nacl/syscalls')
  _remove_unnecessary_defines(vars)
  vars.get_cflags().append('-ffunction-sections')
  vars.get_cflags().append('-fdata-sections')
  return True


def _filter_libc_netbsd(vars):
  # This library has some random functions grabbed from
  # NetBSD. Functions defined in this library includes file tree
  # functions (ftw and nftw), signal printers (e.g., psignal),
  # regexp functions (e.g., regcomp), nice and strxfrm.
  vars.remove_c_or_cxxflag('-w')
  # libc/upstream-netbsd/netbsd-compat.h defines _GNU_SOURCE for you.
  vars.remove_c_or_cxxflag('-D_GNU_SOURCE')
  _remove_unnecessary_defines(vars)
  sources = vars.get_sources()
  if OPTIONS.is_x86_64():
    # LP64 does not have these symbols in upstream but we need to stay
    # compatible with ARM for NDK-translation.
    sources.extend([
        'android/bionic/libc/upstream-netbsd/common/lib/libc/hash/sha1/sha1.c'])
  return True


def _filter_libc_openbsd(vars):
  # strcmp etc taken from openbsd, and exit.
  vars.remove_c_or_cxxflag('-w')
  vars.get_conlyflags().append('-Wno-sign-compare')
  vars.get_conlyflags().append('-Wno-unused-parameter')
  sources = vars.get_sources()
  sources.extend([
      'android/bionic/libc/upstream-openbsd/lib/libc/string/strcmp.c',
      'android/bionic/libc/upstream-openbsd/lib/libc/string/strcpy.c'])
  if OPTIONS.is_x86():
    # TODO(crbug.com/446400): L-rebase: use assembly versions of string
    # operations for NaCl x86-64.
    sources.extend([
        'android/bionic/libc/upstream-openbsd/lib/libc/string/stpcpy.c',
        'android/bionic/libc/upstream-openbsd/lib/libc/string/stpncpy.c',
        'android/bionic/libc/upstream-openbsd/lib/libc/string/strcat.c',
        'android/bionic/libc/upstream-openbsd/lib/libc/string/strlen.c',
        'android/bionic/libc/upstream-openbsd/lib/libc/string/strncmp.c',
        'android/bionic/libc/upstream-openbsd/lib/libc/string/strncpy.c'])
  if OPTIONS.is_x86_64():
    # TODO(crbug.com/446400): L-rebase: use assembly versions of string
    # operations instead.
    sources.extend([
        'android/bionic/libc/upstream-openbsd/lib/libc/string/strncat.c'])
  _remove_unnecessary_defines(vars)
  return True


def _filter_libc_gdtoa(vars):
  # OpenBSD gdtoa libraries. Contains strtod etc.
  vars.remove_c_or_cxxflag('-w')
  vars.get_conlyflags().append('-Wno-sign-compare')
  if OPTIONS.is_x86_64():
    # TODO(crbug.com/446400): L-rebase: long double is same size as double.
    vars.get_sources().remove(
        'android/bionic/libc/upstream-openbsd/lib/libc/gdtoa/strtorQ.c')
  _remove_unnecessary_defines(vars)
  return True


def _filter_libc_bionic(vars):
  sources = vars.get_sources()
  _remove_assembly_source(sources)

  # Bionic's mmap is a wrapper for __mmap2 (except for x86_64). Works the
  # wrapper are not necessary for NaCl and it calls madvice, which NaCl
  # does not support. We will simply define mmap without the wrapper.
  # For x86_64, mmap is directly defined in arch-x86_64/syscalls/mmap.S, which
  # is excluded by _remove_assembly_source().
  if not OPTIONS.is_x86_64():
    sources.remove('android/bionic/libc/bionic/mmap.cpp')

  # Remove implementation of syscall wrappers that we are going to
  # mark with ENOSYS.
  for x in ['android/bionic/libc/bionic/NetdClientDispatch.cpp',
            'android/bionic/libc/bionic/accept.cpp',
            'android/bionic/libc/bionic/accept4.cpp',
            'android/bionic/libc/bionic/access.cpp',
            'android/bionic/libc/bionic/chmod.cpp',
            'android/bionic/libc/bionic/chown.cpp',
            'android/bionic/libc/bionic/connect.cpp',
            'android/bionic/libc/bionic/dup2.cpp',
            'android/bionic/libc/bionic/epoll_create.cpp',
            'android/bionic/libc/bionic/epoll_wait.cpp',
            'android/bionic/libc/bionic/ffs.cpp',
            'android/bionic/libc/bionic/fork.cpp',
            'android/bionic/libc/bionic/getpid.cpp',
            'android/bionic/libc/bionic/gettid.cpp',
            'android/bionic/libc/bionic/inotify_init.cpp',
            'android/bionic/libc/bionic/lchown.cpp',
            'android/bionic/libc/bionic/link.cpp',
            'android/bionic/libc/bionic/lstat.cpp',
            'android/bionic/libc/bionic/mknod.cpp',
            'android/bionic/libc/bionic/mkdir.cpp',
            'android/bionic/libc/bionic/pause.cpp',
            'android/bionic/libc/bionic/pipe.cpp',
            'android/bionic/libc/bionic/poll.cpp',
            'android/bionic/libc/bionic/readlink.cpp',
            'android/bionic/libc/bionic/rename.cpp',
            'android/bionic/libc/bionic/rmdir.cpp',
            'android/bionic/libc/bionic/stat.cpp',
            'android/bionic/libc/bionic/socket.cpp',
            'android/bionic/libc/bionic/symlink.cpp',
            'android/bionic/libc/bionic/utimes.cpp',
            'android/bionic/libc/bionic/unlink.cpp']:
    sources.remove(x)

  if OPTIONS.is_i686():
    sources.extend([
        'android/bionic/libc/arch-x86/bionic/setjmp.S'])
    sources.remove('android/bionic/libc/arch-x86/bionic/__set_tls.c')
  if OPTIONS.is_x86_64():
    # We have our own implementation, remove arch-specific one.
    sources.remove('android/bionic/libc/arch-x86_64/bionic/__set_tls.c')
    sources.extend(
        ['android/bionic/libc/arch-x86_64/bionic/setjmp.S'])
    # Include to satisfy setjmp.S.
    vars.get_includes().insert(0, 'android/bionic/libc/arch-x86_64/include')
  if OPTIONS.is_arm():
    sources.extend(
        ['android/bionic/libc/arch-arm/bionic/setjmp.S'])
  # Use a NaCl-specific version of getentropy.
  sources.remove('android/bionic/libc/bionic/getentropy_linux.c')
  sources.append('android/bionic/libc/arch-nacl/bionic/getentropy.cpp')

  # This file is included even in SFI mode since it defines stubs for
  # functions when it is not supported by NaCl.
  sources.append('android/bionic/libc/arch-nacl/syscalls/nacl_signals.cpp')
  return True


def _filter_libc(vars):
  if vars.is_static():
    return False
  vars.get_sources().remove('android/bionic/libc/bionic/NetdClient.cpp')
  vars.get_sources().extend([
      'android/bionic/libc/arch-nacl/syscalls/clock_nanosleep.c',
      'android/bionic/libc/arch-nacl/syscalls/irt_syscalls.c',
      'android/bionic/libc/arch-nacl/syscalls/nanosleep.c',
      'android/bionic/libc/arch-nacl/syscalls/sched_yield.c',
      'android/bionic/libc/arch-nacl/tmp/libc_stubs.c',
      'android/bionic/libc/bionic/NetdClientDispatch.cpp'
  ])
  if OPTIONS.is_x86_64():
    vars.get_includes().insert(0, 'android/bionic/libc/arch-x86_64/include')
  if OPTIONS.is_bare_metal_build():
    if OPTIONS.is_arm():
      vars.get_sources().extend([
          'android/bionic/libc/arch-arm/bionic/_setjmp.S',
          'android/bionic/libc/arch-arm/bionic/sigsetjmp.S',
          'android/bionic/libc/arch-nacl/syscalls/cacheflush.c'])
    else:
      vars.get_sources().extend([
          'android/bionic/libc/arch-x86/bionic/_setjmp.S',
          'android/bionic/libc/arch-x86/bionic/sigsetjmp.S',
          'android/bionic/libc/arch-x86/generic/string/bcopy.S'])
  if OPTIONS.enable_valgrind():
    vars.get_sources().append(
        'android/bionic/libc/bionic/valgrind_supplement.c')

  vars.get_includes().append('android/bionic/libc/arch-nacl/syscalls')
  vars.get_implicit_deps().extend([build_common.get_bionic_crtbegin_so_o(),
                                   build_common.get_bionic_crtend_o()])
  # This looks weird libc depends on libdl, but the upstream
  # bionic also does the same thing. Note that libdl.so just has
  # stub functions and their actual implementations are in the
  # loader (see third_party/android/bionic/linker/dlfcn.c).
  vars.get_shared_deps().append('libdl')
  vars.get_whole_archive_deps().extend([
      'libc_aeabi',
      'libc_bionic',
      'libc_cxa',
      'libc_dns',
      'libc_freebsd',
      'libc_gdtoa',
      'libc_malloc',
      'libc_netbsd',
      'libc_openbsd',
      # We do not support stack protector on NaCl, but NDK may require a
      # symbol in this file. So, we always link this.
      'libc_stack_protector',
      'libc_tzcode',
      'libjemalloc'])
  # Let dlmalloc not use sbrk as NaCl Bionic does not provide brk/sbrk.
  vars.get_cflags().append('-DHAVE_MORECORE=0')
  _remove_unnecessary_defines(vars)
  if OPTIONS.is_arm():
    # libc/upstream-dlmalloc/malloc.c checks "linux" to check if
    # mremap is available, which we do not have. We need this fix
    # only for Bare Metal ARM because NaCl toolchain does not
    # define "linux" and Android undefines "linux" by default for
    # x86 (android/build/core/combo/TARGET_linux-x86.mk).
    vars.get_cflags().append('-Ulinux')
  vars.get_generator_args()['is_system_library'] = True
  if OPTIONS.is_arm():
    # Set False to 'link_crtbegin' because Android.mk for libc.so
    # compiles android/bionic/libc/arch-arm/bionic/crtbegin_so.c by
    # default with -DCRT_LEGACY_WORKAROUND to export the __dso_handle
    # symbol.
    #
    # __dso_handle is passed to __cxa_atexit so that libc knows which
    # atexit handler belongs to which module. In general, __dso_handle
    # should be a private symbol. Otherwise, a module (say A) can
    # depend on __dso_handle in another module (B), and the atexit
    # handler in A will not be called when the module A is unloaded.
    #
    # However, it seems the old version of Android had a bug and
    # __dso_handle was exposed. Several NDKs depend on __dso_handle
    # in libc.so. To execute such binaries directly, we need to define
    # a public __dso_handle, too. This effectively means atexit
    # handlers in such NDKs will never be called, as we will never
    # unload libc.so. This is a known upstream issue. See
    # third_party/android/bionic/ABI-bugs.txt.
    #
    # Note it is OK not to have crtbegin_so.o as the first object when
    # we link libc.so because we are using init_array/fini_array,
    # which do not require specific watchdogs, for ARM.
    vars.get_generator_args()['link_crtbegin'] = False
  return True


def _filter_libc_cxa(vars):
  # This module is for C++ symbols (operator new(), delete)
  return True


def _filter_libc_dns(vars):
  return True


def _filter_libc_malloc(vars):
  # This module is the glue for dlmalloc or jemalloc.
  return True


def _filter_libc_malloc_debug_leak(vars):
  if vars.is_static():
    return False
  # This module should not be included for --opt --disable-debug-code,
  # and it is controlled by TARGET_BUILD_VARIANT in the Android.mk.
  assert OPTIONS.is_debug_code_enabled()
  vars.get_shared_deps().append('libdl')
  _remove_unnecessary_defines(vars)
  vars.get_generator_args()['is_system_library'] = True
  return True


def _filter_libc_freebsd(vars):
  sources = vars.get_sources()
  if OPTIONS.is_i686():
    # TODO(crbug.com/446400): L-rebase: use assembly versions of string
    # operations instead.
    sources.extend([
        'android/bionic/libc/upstream-freebsd/lib/libc/string/wcschr.c',
        'android/bionic/libc/upstream-freebsd/lib/libc/string/wcscmp.c',
        'android/bionic/libc/upstream-freebsd/lib/libc/string/wcslen.c',
        'android/bionic/libc/upstream-freebsd/lib/libc/string/wcsrchr.c'])
  return True


def _filter_libc_tzcode(vars):
  return True


def _filter_libc_stack_protector(vars):
  # Used by both libc.so and runnable-ld.so.
  vars.set_instances_count(2)
  return True


def _filter_libc_aeabi(vars):
  # For __aeabi_atexit, __aeabi_memcpy etc. for ARM.
  return True


def _filter_tzdata(vars):
  vars.set_prebuilt_install_to_root_dir(True)
  return True


def _filter_libstdcpp(vars):
  return not vars.is_static()


def _dispatch_libc_sub_filters(vars):
  # Any libraries/executables except libc.so and the loader should *NEVER*
  # be linked into libc_common because libc_common has global variables
  # which require proper initialization (e.g. IRT function pointers in
  # irt_syscalls.c).
  # TODO(crbug.com/243244): Consider using -Wsystem-headers.
  return {
      'libc': _filter_libc,
      'libc_aeabi': _filter_libc_aeabi,
      'libc_bionic': _filter_libc_bionic,
      'libc_common': _filter_libc_common,
      'libc_cxa': _filter_libc_cxa,
      'libc_dns': _filter_libc_dns,
      'libc_freebsd': _filter_libc_freebsd,
      'libc_malloc': _filter_libc_malloc,
      'libc_malloc_debug_leak': _filter_libc_malloc_debug_leak,
      'libc_netbsd': _filter_libc_netbsd,
      'libc_openbsd': _filter_libc_openbsd,
      'libc_gdtoa': _filter_libc_gdtoa,
      'libc_stack_protector': _filter_libc_stack_protector,
      'libc_tzcode': _filter_libc_tzcode,
      'libstdc++': _filter_libstdcpp,
      'tzdata': _filter_tzdata,
  }.get(vars.get_module_name(), lambda vars: False)(vars)


def _generate_libc_ninja():
  def _filter(vars, is_for_linker=False):
    if (vars.is_c_library() and OPTIONS.is_nacl_build() and
        not vars.is_clang_enabled()):
      vars.enable_clang()
      vars.enable_cxx11()
    if not _dispatch_libc_sub_filters(vars):
      return False

    # tzdata is not a C/C++ module.
    if vars.get_module_name() != 'tzdata':
      vars.get_cflags().append('-W')
      vars.get_cflags().append('-Werror')
    _add_bare_metal_flags_to_make_to_ninja_vars(vars)
    if is_for_linker:
      module_name = vars.get_module_name()
      if module_name not in _LINKER_MODULES:
        return False
      if (module_name in ('libc_bionic', 'libc_aeabi') and
          OPTIONS.is_bare_metal_arm()):
        # If we specify -fstack-protector, the ARM compiler emits code
        # which requires relocation even for the code to be executed
        # before the self relocation. As we would like to use logging
        # functions in libc_bionic before the self relocation, we disable
        # the stack smashing protector for libc_bionic for now.
        # TODO(crbug.com/342292): Enable stack protector for the Bionic
        # loader on Bare Metal ARM.
        vars.get_cflags().append('-fno-stack-protector')
        vars.get_cxxflags().append('-fno-stack-protector')
      vars.set_module_name(module_name + '_linker')
      # The loader does not need to export any symbols.
      vars.get_cflags().append('-fvisibility=hidden')
      vars.get_cxxflags().append('-fvisibility=hidden')
      # We need to control the visibility using GCC's pragma based on
      # this macro. See bionic/libc/arch-nacl/syscalls/irt_syscalls.h.
      vars.get_cflags().append('-DBUILDING_LINKER')
      vars.get_cxxflags().append('-DBUILDING_LINKER')
    return True

  make_to_ninja.MakefileNinjaTranslator('android/bionic/libc').generate(
      lambda vars: _filter(vars, is_for_linker=False))
  make_to_ninja.MakefileNinjaTranslator('android/bionic/libc').generate(
      lambda vars: _filter(vars, is_for_linker=True))


def _generate_libm_ninja():
  def _filter(vars):
    if vars.is_shared():
      return False
    make_to_ninja.Filters.convert_to_shared_lib(vars)
    _add_bare_metal_flags_to_make_to_ninja_vars(vars)
    vars.get_cflags().append('-W')
    vars.get_cflags().append('-Werror')
    vars.get_cflags().append('-fno-builtin')
    # Disable extended precision in nacl-i686. Some libm code (e.g.
    # STRICT_ASSIGN macro) does not work correctly with extended precision.
    # TODO(crbug.com/450887): Remove this flag once we migrate to a toolchain
    # that generates SSE instructions instead of FPU ones.
    if OPTIONS.is_nacl_i686():
      vars.get_cflags().append('-ffloat-store')
    sources = vars.get_sources()
    _remove_assembly_source(sources)
    if OPTIONS.is_arm():
      vars.get_includes().append('android/bionic/libc/arch-arm/include')
    elif OPTIONS.is_i686():
      vars.get_includes().append('android/bionic/libc/arch-x86/include')
    elif OPTIONS.is_x86_64():
      vars.get_includes().append('android/bionic/libc/arch-x86_64/include')
      # Android.mk assumes 128bit long double under amd64, but it's actually
      # 64bit under NaCl x86_64. Here we exclude long double math function
      # definitions. See mods/fork/bionic-long-double for details.
      for x in [
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/invtrig.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/k_cosl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/k_sinl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/k_tanl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/s_exp2l.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/s_expl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/s_logl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/ld128/s_nanl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_acosl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_acoshl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_asinl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_atan2l.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_atanhl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_fmodl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_hypotl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_remainderl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/e_sqrtl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_asinhl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_atanl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_cbrtl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_ceill.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_copysignl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_cosl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_fabsl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_floorl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_fmal.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_fmaxl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_fminl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_modfl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_frexpl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_ilogbl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_llrintl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_llroundl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_logbl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_lrintl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_lroundl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_nextafterl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_nexttoward.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_nexttowardf.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_remquol.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_rintl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_roundl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_scalbnl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_sinl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_tanl.c',
          'android/bionic/libm/upstream-freebsd/lib/msun/src/s_truncl.c']:
        sources.remove(x)
    vars.get_generator_args()['is_system_library'] = True
    vars.get_shared_deps().append('libc')
    return True

  make_to_ninja.MakefileNinjaTranslator('android/bionic/libm').generate(_filter)


def _generate_libdl_ninja():
  def _filter(vars):
    _add_bare_metal_flags_to_make_to_ninja_vars(vars)
    vars.get_implicit_deps().extend([build_common.get_bionic_crtbegin_so_o(),
                                     build_common.get_bionic_crtend_so_o()])
    vars.remove_c_or_cxxflag('-w')
    vars.get_cflags().append('-W')
    vars.get_cflags().append('-Werror')
    if vars.is_clang_enabled():
      vars.get_cflags().append('-Wno-unused-parameter')
    vars.get_generator_args()['is_system_library'] = True
    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/bionic/libdl').generate(_filter)


# The "fundamental test" tests the features of the loader and the
# initialization process of libc. As we may want to test various kinds
# of objects with various kinds of setup, you can specify any command
# to build and test them. If you can use googletest, you should add
# tests to normal bionic_test instead (mods/android/bionic/tests).
class BionicFundamentalTest(object):
  ALL_OUTPUT_BINARIES = []

  @staticmethod
  def get_src_dir():
    return staging.as_staging('android/bionic/tests/fundamental')

  @staticmethod
  def get_out_dir():
    return os.path.join(build_common.get_build_dir(), 'bionic_tests')

  def __init__(self, test_binary_name, inputs, output, build_commands):
    self._test_binary_name = test_binary_name
    self._build_commands = build_commands
    out = os.path.join(BionicFundamentalTest.get_out_dir(), test_binary_name)
    asmflags = ninja_generator.CNinjaGenerator.get_archasmflags()
    if OPTIONS.is_bare_metal_build():
      asmflags += ' -DBARE_METAL_BIONIC '
    cflags = (ninja_generator.CNinjaGenerator.get_gcc_includes() +
              ninja_generator.CNinjaGenerator.get_archcflags())
    cxxflags = ninja_generator.CNinjaGenerator.get_cxxflags()
    cflags = asmflags + cflags + ' $commonflags -g -fPIC -Wall -W -Werror '
    cxxflags = cflags + cxxflags
    ldflags = ('-Wl,-rpath-link=' + build_common.get_load_library_path() +
               ' -Wl,--hash-style=sysv')
    # Use -Bsymbolic to have similar configuration as other NaCl
    # executables in ARC.
    soflags = '-shared -Wl,-Bsymbolic'
    if OPTIONS.is_arm():
      # For ARM, we need to link libgcc.a into shared objects. See the comment
      # in SharedObjectNinjaGenerator.
      # TODO(crbug.com/283798): Build libgcc by ourselves and remove this.
      soflags += ' ' + ' '.join(
          ninja_generator.get_libgcc_for_bionic())
    text_segment_address = (ninja_generator.ExecNinjaGenerator.
                            get_nacl_text_segment_address())
    if OPTIONS.is_bare_metal_build():
      execflags = '-pie'
      ldflags += ' -fuse-ld=gold'
    else:
      # This is for nacl-clang. See src/build/ninja_generator.py for detail.
      execflags = '-dynamic -Wl,-Ttext-segment=' + text_segment_address

    self._variables = {
        'cc': _get_crt_cc(),
        'cxx': _get_crt_cxx(),
        'name': self._test_binary_name,
        'lib_dir': build_common.get_load_library_path(),
        'in_dir': BionicFundamentalTest.get_src_dir(),
        'out_dir': BionicFundamentalTest.get_out_dir(),
        'out': out,
        'crtbegin_exe': build_common.get_bionic_crtbegin_o(),
        'crtbegin_so': build_common.get_bionic_crtbegin_so_o(),
        'crtend_exe': build_common.get_bionic_crtend_o(),
        'crtend_so': build_common.get_bionic_crtend_so_o(),
        'cflags': cflags,
        'cxxflags': cxxflags,
        'ldflags': ldflags,
        'soflags': soflags,
        'execflags': execflags
    }
    self._inputs = map(self._expand_vars, inputs)
    self._output = self._expand_vars(output)

  def _expand_vars(self, s):
    return string.Template(s).substitute(self._variables)

  def emit(self, n):
    BionicFundamentalTest.ALL_OUTPUT_BINARIES.append(self._output)

    rule_name = 'build_bionic_' + self._test_binary_name
    commands = []
    for command in self._build_commands:
      assert command
      command = self._expand_vars(' '.join(command))
      commands.append(command)
    n.rule(rule_name, command=' && '.join(commands),
           description=rule_name + ' $in')
    n.build(self._output, rule_name, self._inputs,
            implicit=build_common.get_bionic_objects())
    if OPTIONS.is_debug_info_enabled():
      n.build_stripped(self._output)


def _generate_bionic_fundamental_test_runners(n):
  rule_name = 'run_bionic_fundamental_test'
  script_name = os.path.join(BionicFundamentalTest.get_src_dir(),
                             'run_bionic_fundamental_test.py')
  n.rule(rule_name,
         command=script_name + ' $test_name' +
         build_common.get_test_output_handler(use_crash_analyzer=True),
         description=rule_name + ' $test_name')

  test_out_dir = BionicFundamentalTest.get_out_dir()
  tests = []
  # This uses NaCl syscalls directly and is not compatible with Bare
  # Metal mode.
  if OPTIONS.is_nacl_build():
    # If this passes, the loader is working.
    tests.append(('loader_test', [], [], {}))
  # (name, extra LD_LIBRARY_PATH, extra argv, extra envs)
  tests.extend([
      # If this passes, IRT calls are ready.
      ('write_test', [], [], {}),
      # If this passes, stdio and malloc are ready.
      ('printf_test', [], [], {}),
      # If this passes, arguments and environment variables are OK.
      ('args_test', [], ['foobar'], {}),
      # If this passes, .ctors and .dtors are working.
      ('structors_test', [], [], {}),
      # If this passes, symbols are available for subsequently loaded binaries.
      ('resolve_parent_sym_test', [test_out_dir], [], {}),
      # If this passes, .ctors and .dtors with DT_NEEDED are working.
      ('so_structors_test', [test_out_dir], [], {}),
      # If this passes, .ctors and .dtors with dlopen are working.
      ('dlopen_structors_test', [test_out_dir], [], {}),
      # If this passes, dlopen fails properly when there is a missing symbol.
      ('dlopen_error_test', [test_out_dir], [], {})
  ])

  for test_name, library_paths, test_argv, test_env in tests:
    test_binary_basename = re.sub(r'-.*', '', test_name)
    test_binary = os.path.join(test_out_dir, test_binary_basename)
    runner = toolchain.get_target_runner(extra_library_paths=library_paths,
                                         extra_envs=test_env)
    qemu_arm = (' '.join(toolchain.get_qemu_arm_args())
                if OPTIONS.is_arm() else '')
    test_name = 'bionic_fundamental.' + test_name
    variables = {
        'runner': ' '.join(runner),
        'in': test_binary,
        'argv': ' '.join(test_argv),
        'qemu_arm': qemu_arm
    }
    test_info = {
        'variables': variables,
        'command': '$qemu_arm $runner $in $argv'
    }
    test_path = os.path.join(test_out_dir, test_name)
    n._build_test_info(test_path, 1, test_info)
    test_info_path = n.get_test_info_path(test_path, 1)

    result = os.path.join(test_out_dir, test_name + '.result')
    test_deps = (BionicFundamentalTest.ALL_OUTPUT_BINARIES +
                 [script_name, test_info_path])
    n.build(result, rule_name, implicit=test_deps,
            variables={'test_name': test_name})


def _generate_bionic_fundamental_tests():
  n = ninja_generator.NinjaGenerator('bionic_fundamental_tests')
  bionic_tests = []
  if OPTIONS.is_nacl_build():
    # This uses NaCl syscalls directly and is not compatible with Bare
    # Metal mode.
    bionic_tests.append(
        BionicFundamentalTest(
            'loader_test', ['$in_dir/$name.c'], '$out',
            [['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
              '-L$lib_dir', '-lc'] +
             ninja_generator.get_libgcc_for_bionic() +
             ['-ldl', '$$in', '-o', '$$out']]))
  bionic_tests.extend([
      BionicFundamentalTest(
          'write_test', ['$in_dir/$name.c'], '$out',
          [['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$$in', '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'printf_test', ['$in_dir/$name.c'], '$out',
          [['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$$in', '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'args_test', ['$in_dir/$name.c'], '$out',
          [['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$$in', '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'structors_test', ['$in_dir/$name.c'], '$out',
          [['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$$in', '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'resolve_parent_sym_test',
          ['$in_dir/$name.c',
           '$in_dir/${name}_first.c', '$in_dir/${name}_second.c'],
          '$out',
          [['$cc', '$cflags', '$ldflags', '-nostdlib',
            '$crtbegin_so', '-L$lib_dir', '-lc',
            '$in_dir/${name}_second.c', '$crtend_so',
            '$soflags', '-o', '$out_dir/lib${name}_second.so'],
           ['$cc', '$cflags', '$ldflags', '-nostdlib',
            '-L$out_dir', '-l${name}_second',
            '$crtbegin_so', '-L$lib_dir', '-lc',
            '$in_dir/${name}_first.c', '$crtend_so',
            '$soflags', '-o', '$out_dir/lib${name}_first.so'],
           ['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '-rdynamic', '-L$out_dir',
            '-Wl,--rpath-link=$out_dir', '-l${name}_first',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$$in', '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'so_structors_test',
          ['$in_dir/$name.c', '$in_dir/structors_test.c'],
          '$out',
          [['$cc', '$cflags', '-DFOR_SHARED_OBJECT',
            '$ldflags', '-nostdlib',
            '$crtbegin_so', '-L$lib_dir', '-lc',
            '$in_dir/structors_test.c', '$crtend_so',
            '$soflags', '-o', '$out_dir/libstructors_test.so'],
           ['$cc', '$cflags', '$ldflags', '$execflags',
            '-nostdlib', '-rdynamic',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$in_dir/$name.c',
            '-L$out_dir', '-Wl,--rpath-link=$out_dir', '-lstructors_test',
            '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'dlopen_structors_test', ['$in_dir/$name.c'], '$out',
          [['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['$$in', '-ldl', '$crtend_exe', '-o', '$$out']]),
      BionicFundamentalTest(
          'dlopen_error_test',
          ['$in_dir/$name.c',
           '$in_dir/use_undefined_sym.c', '$in_dir/use_use_undefined_sym.c'],
          '$out',
          [['$cc', '$cflags', '$ldflags', '-nostdlib',
            '$crtbegin_so', '-L$lib_dir', '-lc',
            '$in_dir/use_undefined_sym.c', '$crtend_so',
            '$soflags', '-o', '$out_dir/libuse_undefined_sym.so'],
           ['$cc', '$cflags', '$ldflags', '-nostdlib',
            '-L$out_dir', '-luse_undefined_sym',
            '$crtbegin_so', '-L$lib_dir', '-lc',
            '$in_dir/use_use_undefined_sym.c', '$crtend_so',
            '$soflags', '-o', '$out_dir/libuse_use_undefined_sym.so'],
           ['$cc', '$cflags', '$ldflags', '$execflags', '-nostdlib',
            '-rdynamic', '-L$out_dir',
            '$crtbegin_exe', '-L$lib_dir', '-lc'] +
           ninja_generator.get_libgcc_for_bionic() +
           ['-ldl', '$in_dir/$name.c', '$crtend_exe', '-o', '$$out']]),
  ])
  for test in bionic_tests:
    test.emit(n)

  _generate_bionic_fundamental_test_runners(n)


def _generate_crt_bionic_ninja():
  n = ninja_generator.CNinjaGenerator('bionic_crt')
  _add_bare_metal_flags_to_ninja_generator(n)
  # Needed to access private/__dso_handle.h from crtbegin_so.c.
  n.add_include_paths('android/bionic/libc')
  rule_name = 'build_bionic_crt'
  opt_flags = ''
  if OPTIONS.is_optimized_build():
    opt_flags = ' '.join(ninja_generator.get_optimization_cflags())
  n.rule(rule_name,
         deps='gcc',
         depfile='$out.d',
         command=(_get_crt_cc() +
                  ' $gccsystemincludes $cflags -W -Werror '
                  ' -I' + staging.as_staging('android/bionic/libc/private') +
                  ' -fPIC -g %s -MD -MF $out.d -c $in -o'
                  ' $out') % opt_flags,
         description=rule_name + ' $in')
  # crts is a list of tuples whose first element is the source code
  # and the second element is the name of the output object.
  crts = [
      ('android/bionic/libc/arch-common/bionic/crtbegin.c', 'crtbegin.o'),
      ('android/bionic/libc/arch-common/bionic/crtbegin_so.c', 'crtbeginS.o'),
      ('android/bionic/libc/arch-common/bionic/crtend.S', 'crtend.o'),
      ('android/bionic/libc/arch-common/bionic/crtend_so.S', 'crtendS.o'),
  ]
  for crt_src, crt_o in crts:
    source = staging.as_staging(crt_src)
    crt_o_path = os.path.join(build_common.get_load_library_path(), crt_o)
    n.build(crt_o_path, rule_name, source)
    if OPTIONS.is_debug_info_enabled():
      n.build_stripped(crt_o_path)


def _generate_linker_script_for_runnable_ld():
  # For Bare Metal mode, we do not modify linker script.
  if OPTIONS.is_bare_metal_build():
    return []

  rule_name = 'gen_runnable_ld_lds'
  n = ninja_generator.NinjaGenerator(rule_name)
  cc = toolchain.get_tool(OPTIONS.target(), 'clang')
  n.rule(rule_name,
         command='$in %s > $out || (rm $out; exit 1)' % cc,
         description=rule_name)
  linker_script = os.path.join(build_common.get_build_dir(), 'runnable-ld.lds')
  n.build(linker_script, rule_name, staging.as_staging(
      'android/bionic/linker/arch/nacl/gen_runnable_ld_lds.py'))
  return linker_script


def _add_runnable_ld_cflags(n):
  # Match bionic/linker/Android.mk.
  n.add_c_flags('-std=gnu11')
  n.add_cxx_flags('-std=gnu++11')
  if OPTIONS.is_arm():
    # If we specify -fstack-protector, the ARM compiler emits code
    # which requires relocation even for the code to be executed
    # before the self relocation. We disable the stack smashing
    # protector for the Bionic loader for now.
    # TODO(crbug.com/342292): Enable stack protector for the Bionic
    # loader on Bare Metal ARM.
    n.add_compiler_flags('-fno-stack-protector')
  n.add_compiler_flags(
      '-ffunction-sections', '-fdata-sections',
      # The loader does not need to export any symbols.
      '-fvisibility=hidden',
      '-W', '-Wno-unused', '-Wno-unused-parameter', '-Werror')

  # TODO(crbug.com/243244): Consider using -Wsystem-headers.
  n.add_include_paths('android/bionic/libc',
                      'android/bionic/libc/private',
                      'android/bionic/linker/arch/nacl')
  if OPTIONS.is_debug_code_enabled() or OPTIONS.is_bionic_loader_logging():
    n.add_defines('LINKER_DEBUG=1')
  else:
    n.add_defines('LINKER_DEBUG=0')
  n.add_defines('ANDROID_SMP=1')
  if OPTIONS.is_x86_64():
    n.add_c_flags('-Wno-pointer-to-int-cast')
    n.add_c_flags('-Wno-int-to-pointer-cast')
    # NaCl x86-64 looks like x86 except for the ELF header which is
    # x86-64, override the header path for linker to get the proper
    # elf declarations.
    n.add_include_paths('android/bionic/libc/arch-x86_64/include')
  if build_common.use_ndk_direct_execution():
    n.add_defines('USE_NDK_DIRECT_EXECUTION')

  if OPTIONS.is_bionic_loader_logging():
    n.add_defines('BIONIC_LOADER_LOGGING')
  _add_bare_metal_flags_to_ninja_generator(n)

  if OPTIONS.enable_valgrind():
    n.add_defines('RUNNING_ON_VALGRIND')


def _generate_runnable_ld_ninja():
  linker_script = _generate_linker_script_for_runnable_ld()

  # Not surprisingly, bionic's loader is built with a special hack to
  # Android's build system so we cannot use MakefileNinjaTranslator.
  n = ninja_generator.ExecNinjaGenerator('runnable-ld.so',
                                         base_path='android/bionic/linker',
                                         install_path='/lib',
                                         is_system_library=True,
                                         force_compiler='clang',
                                         enable_cxx11=True)
  _add_runnable_ld_cflags(n)

  for module_name in _LINKER_MODULES:
    n.add_library_deps('%s_linker.a' % module_name)
  sources = n.find_all_sources()
  _remove_assembly_source(sources)
  sources.extend(['android/bionic/libc/arch-nacl/syscalls/irt_syscalls.c',
                  'android/bionic/libc/bionic/__errno.cpp',
                  'android/bionic/libc/bionic/pthread_create.cpp',
                  'android/bionic/libc/bionic/pthread_internals.cpp',
                  'android/bionic/libc/bionic/pthread_key.cpp'])
  if OPTIONS.is_bare_metal_build():
    sources.append('android/bionic/linker/linker_notify.S')
    # Remove SFI NaCl specific dynamic code allocation.
    sources.remove('android/bionic/linker/arch/nacl/nacl_dyncode_alloc.c')
    sources.remove('android/bionic/linker/arch/nacl/nacl_dyncode_map.c')
  # NaCl has no signals so debugger support cannot be implemented.
  sources.remove('android/bionic/linker/debugger.cpp')

  # n.find_all_sources() picks up this upstream file regardless of the
  # current target. For ARM, the file is obviously irrelevant. For i686
  # and x86_64, we use our own begin.c.
  sources.remove('android/bionic/linker/arch/x86/begin.c')

  if OPTIONS.is_nacl_x86_64():
    sources.append('android/bionic/linker/get_tls_for_art.S')

  ldflags = n.get_ldflags()
  if OPTIONS.is_nacl_build():
    ldflags += (' -dynamic' +
                ' -Wl,-Ttext-segment=' + _LOADER_TEXT_SECTION_START_ADDRESS +
                ' -Wl,-T ' + linker_script)
  else:
    # We need to use recent linkers for __ehdr_start.
    ldflags += ' -pie'
  # See the comment in linker/arch/nacl/begin.c.
  ldflags += ' -Wl,--defsym=__linker_base=0'
  ldflags += ' -Wl,--gc-sections'
  if not OPTIONS.is_debug_info_enabled():
    ldflags += ' -Wl,--strip-all'
  n.add_library_deps(*ninja_generator.get_libgcc_for_bionic())
  n.add_library_deps('libc_stack_protector.a')
  n.build_default(sources, base_path=None)
  n.link(variables={'ldflags': ldflags}, implicit=linker_script)


_BIONIC_TEST_LIB_MODULES = [
    'libdlext_test',
    'libdlext_test_fd',
    'libdlext_test_norelro',
    'libdlext_test_v2',
    'libtest_atexit',
    'libtest_dlsym_weak_func',
    'libtest_simple',
    'libtest_with_dependency']


def _generate_bionic_test_lib_ninja():
  # Generate necessary libraries for tests for dlopen etc.
  def _filter(vars):
    if not vars.get_module_name() in _BIONIC_TEST_LIB_MODULES:
      return False
    if not vars.is_shared():
      return False
    # I don't need __wrap
    vars.get_generator_args()['is_system_library'] = True
    vars.get_generator_args()['is_for_test'] = True
    vars.get_shared_deps().extend([
        'libc',
        'libstlport'])
    # libtest_with_dependency.so wants DT_NEEDED to libdlext_test.so whereas
    # it does not require any symbol. This file is used in
    # dlfcn.dlsym_with_dependencies test.
    if vars.get_module_name() == 'libtest_with_dependency':
      vars.get_ldflags().append('-Wl,--no-as-needed')
    return True

  make_to_ninja.MakefileNinjaTranslator(
      'android/bionic/tests/libs').generate(_filter)

  # libdlext_test_v2.so must be a symbolic link to libdlext_test.so.
  # This file is used in dlfcn.dlopen_symlink test.
  n = ninja_generator.NinjaGenerator('libdlext_test_v2')
  orig_so = os.path.join(
      build_common.get_load_library_path(), 'libdlext_test.so')
  link_so = os.path.join(
      build_common.get_load_library_path(), 'libdlext_test_v2.so')
  command = 'ln -sf %s %s' % (os.path.basename(orig_so), link_so)
  n.build(link_so, 'run_shell_command', implicit=orig_so,
          variables={'command': command})


def _generate_bionic_tests():
  if open_source.is_open_source_repo():
    # bionic_test depends on some extra libs like libpagemap.a which have not
    # been opensourced.
    return
  # To use 64bit long double instead of usual 80bit long double under BMM x86,
  # we need to use gcc supporting -mlong-double-64.
  # See mods/fork/bionic-long-double for more details.
  compiler = 'gcc' if OPTIONS.is_bare_metal_i686() else 'clang'
  n = ninja_generator.TestNinjaGenerator('bionic_test',
                                         base_path='android/bionic/tests',
                                         force_compiler=compiler,
                                         enable_cxx11=True)
  _add_bare_metal_flags_to_ninja_generator(n)

  def relevant(f):
    if f.find('/fundamental/') >= 0:
      return False
    if re.search(r'(_benchmark|/benchmark_main)\.cpp$', f):
      return False
    if f.find('/libs/') >= 0:
      # libs are generated using MakefileNinjaTranslator in
      # _generate_bionic_test_lib_ninja
      return False
    if (OPTIONS.is_nacl_i686() and
        f == 'android/bionic/tests/stack_protector_test.cpp'):
      # This tries to access a segment register, which NaCl validator
      # does not like.
      return False
    return True

  sources = filter(relevant, n.find_all_sources(include_tests=True))
  n.build_default(sources, base_path=None)
  # Set the same flag as third_party/android/bionic/tests/Android.mk.
  # This is necessary for dlfcn_test.cpp as it calls dlsym for this symbol.
  ldflags = '$ldflags -Wl,--export-dynamic -Wl,-u,DlSymTestFunction'
  n.add_compiler_flags('-W', '-Wno-unused-parameter', '-Werror',
                       # Match libBionicStandardTests_c_includes in Android.mk
                       '-I' + staging.as_staging('android/bionic/libc'))
  # Match bionic/tests/Android.mk.
  n.add_cxx_flags('-std=gnu++11')
  # Suppress deprecation warning in phtread_context_test.cpp.
  n.add_cxx_flags('-Wno-inline-asm')
  n.add_include_paths('android/system/extras/libpagemap/include')
  n.add_library_deps('libpagemap.a')
  n.add_compiler_flags('-fno-builtin')
  if OPTIONS.is_arm():
    # TODO(crbug.com/362175): qemu-arm cannot reliably emulate threading
    # functions so run them in a real ARM device.
    qemu_disabled_tests = ['pthread.pthread_attr_setguardsize',
                           'pthread.pthread_attr_setstacksize',
                           'pthread.pthread_create',
                           'pthread.pthread_detach__leak',
                           'pthread.pthread_getcpuclockid__no_such_thread',
                           'pthread.pthread_join__multijoin',
                           'pthread.pthread_join__no_such_thread',
                           'pthread.pthread_join__race',
                           'pthread.pthread_no_join_after_detach',
                           'pthread.pthread_no_op_detach_after_join',
                           'pthread_thread_stack.pthread_create_detached',
                           'pthread_thread_stack.pthread_create_join',
                           'pthread_thread_stack.pthread_detach',
                           'string.strerror_concurrent',
                           'string.strsignal_concurrent']
    n.add_qemu_disabled_tests(*qemu_disabled_tests)
  disabled_tests = [
      # ARC does not support fork(), clone(), nor popen().
      'DlExtRelroSharingTest.ChildWritesGoodData',
      'DlExtRelroSharingTest.ChildWritesNoRelro',
      'DlExtRelroSharingTest.VerifyMemorySaving',
      'pthread.pthread_atfork',
      'pthread.pthread_key_fork',
      'sched.clone',
      'sched.clone_errno',
      'stdio.popen',
      'stdlib.at_quick_exit',
      'stdlib.quick_exit',
      'stdlib.system',
      'time.timer_create',
      'unistd._Exit',
      'unistd._exit',

      # ARC does not support alarms/timers.
      'signal.sigwait',
      'time.timer_create_EINVAL',
      'time.timer_create_NULL',
      'time.timer_create_SIGEV_SIGNAL',
      'time.timer_create_multiple',
      'time.timer_delete_from_timer_thread',
      'time.timer_delete_multiple',
      'time.timer_settime_0',
      'time.timer_settime_repeats',
      'unistd.alarm',
      'unistd.pause',

      # Needs posix_translation: file system syscalls
      # TODO(crbug.com/452355): There are some symbols for which even
      # posix_translation does not support. We should review them
      # and add __wrap_* functions in posix_translation.
      'fcntl.f_getlk64',
      'fcntl.fallocate',
      'fcntl.fallocate_EINVAL',
      'fcntl.fcntl_smoke',
      'fcntl.posix_fadvise',
      'fcntl.splice',
      'fcntl.tee',
      'fcntl.vmsplice',
      'sys_epoll.epoll_event_data',
      'sys_epoll.smoke',
      'sys_select.pselect_smoke',
      'sys_select.select_smoke',
      'sys_sendfile.sendfile',
      'sys_sendfile.sendfile64',
      'sys_socket.accept4_error',
      'sys_socket.accept4_smoke',
      'sys_socket.recvmmsg_error',
      'sys_socket.recvmmsg_smoke',
      'sys_socket.sendmmsg_error',
      'sys_socket.sendmmsg_smoke',
      'sys_stat.futimens',
      'sys_stat.futimens_EBADF',
      'sys_stat.mkfifo',
      'sys_statvfs.fstatvfs',
      'sys_statvfs.fstatvfs64',
      'sys_statvfs.statvfs',
      'sys_statvfs.statvfs64',
      'sys_vfs.fstatfs',
      'sys_vfs.fstatfs64',
      'sys_vfs.statfs',
      'sys_vfs.statfs64',
      'unistd.fdatasync',
      'unistd.fsync',
      'unistd.ftruncate',
      'unistd.ftruncate64',
      'unistd.truncate',
      'unistd.truncate64',

      # ARC does not support TTY.
      'stdlib.ptsname_r_ERANGE',
      'stdlib.pty_smoke',
      'stdlib.ttyname_r',
      'stdlib.ttyname_r_ENOTTY',
      'stdlib.ttyname_r_ERANGE',
      'stdlib.unlockpt_ENOTTY',

      # Needs posix_translation: getrlimit
      'sys_resource.smoke',

      # Needs posix_translation: getpid
      'unistd.getpid_caching_and_clone',
      'unistd.getpid_caching_and_fork',
      'unistd.getpid_caching_and_pthread_create',
      'unistd.syscall',

      # This test uses realpath. Also, this fails even with realpath
      # on SFI NaCl, because a pointer address the sandboxed process
      # is looking is different from the real address.
      'dlfcn.dladdr',

      # Needs posix_translation: utimes
      'sys_time.utimes',
      'sys_time.utimes_NULL',

      # Needs posix_translation: getaddrinfo and freeaddrinfo
      'netdb.getaddrinfo_NULL_hints',

      # Needs posix_translation: readlink in unittests does not work
      # on NaCl and Bare Metal.
      'stdlib.realpath',
      'stdlib.realpath__ENOENT',

      # ARC does not support brk/sbrk.
      'unistd.brk',
      'unistd.brk_ENOMEM',
      'unistd.sbrk_ENOMEM',
      'unistd.syscall_long',

      # We do not support pthread_setname_np.
      'pthread.pthread_setname_np__self',

      # ARC does not support eventfd.
      'eventfd.smoke',

      # TODO(crbug.com/359436): Death tests are not supported.
      'TEST_NAME_DeathTest.*',
      'atexit.exit',
      # Note: if /dev/__properties__ is not working, this test does
      # nothing so this test actually passes.
      'properties_DeathTest.read_only',
      'pthread_DeathTest.pthread_bug_37410',
      'stack_protector_DeathTest.modify_stack_protector',
      'stack_unwinding_DeathTest.unwinding_through_signal_frame',
      'stdlib.getenv_after_main_thread_exits',
      'stdlib_DeathTest.getenv_after_main_thread_exits',

      # Too slow, takes 40 seconds on -t bi on z620
      # TODO(crbug.com/446400): L-rebase: Reenable if I can make it faster, or
      # enable it for integration tests.
      'string.*'
  ]
  if OPTIONS.is_bare_metal_build():
    # nonsfi_loader always returns zero st_dev so symlink detection in
    # linker.cpp does not work well.
    disabled_tests.extend([
        'dlfcn.dlopen_symlink',
    ])
    if OPTIONS.is_i686():
      # TODO(crbug.com/469093): Fix this test.
      disabled_tests.extend([
          'stack_protector.same_guard_per_thread',
      ])
  if OPTIONS.is_nacl_build():
    disabled_tests.extend([
        # SFI NaCl does not support signals.
        'pthread.pthread_kill__0',
        'pthread.pthread_kill__in_signal_handler',
        'pthread.pthread_kill__invalid_signal',
        'pthread.pthread_kill__no_such_thread',
        'pthread.pthread_sigmask',
        'signal.raise_invalid',
        'signal.sigaction',
        'signal.sigsuspend_sigpending',

        # android_dlopen_ext() can not work as expected due to the gapped memory
        # layout of NaCl.
        'DlExtTest.Reserved',
        'DlExtTest.ReservedTooSmall',
        'DlExtTest.ReservedHint',

        # Needs posix_translation: ARC supports symlinks recently, but
        # dlopen() does not care.
        'dlfcn.dlopen_symlink',

        # Direct syscall is not supported.
        'sys_time.gettimeofday',
        'time.clock_gettime'
    ])

  if OPTIONS.enable_valgrind():
    disabled_tests.extend([
        # A few tests in these files fail under valgrind probably due
        # to a valgrind's bug around rounding mode.
        'fenv.feclearexcept_fetestexcept',
        'fenv.fesetround_fegetround_FE_DOWNWARD',
        'fenv.fesetround_fegetround_FE_TOWARDZERO',
        'math.__fpclassifyl',
        'math.__isfinitel',
        'math.__isinfl',
        'math.fpclassify',
        'math.lrint',
        'math.nearbyint',
        'math.rint',

        # Valgrind aborts when pvalloc or valloc is called.
        'malloc.pvalloc_overflow',
        'malloc.pvalloc_std',
        'malloc.valloc_std',
        # These test check malloc family sets errno appropriately, but
        # valgrind's replace_malloc does not update errno.
        'malloc.calloc_overflow',
        'malloc.malloc_overflow',
        'malloc.calloc_illegal',
        'malloc.realloc_overflow',

        # This test relies on sleep(1) and is flaky on valgrind. See
        # crbug.com/410009.
        'pthread.pthread_no_op_detach_after_join',

        # This test cannot find the main thread's stack from
        # /proc/self/maps when a process is running under valgrind.
        'pthread.pthread_attr_getstack__main_thread',

        # This test intentionally leaks memory. Valgrind may detect it.
        'pthread.pthread_detach__leak',

        # This test expects two threads are executed in
        # parallel. However, valgrind's scheduler runs the one thread
        # first and then runs the other.
        'stdatomic.ordering',

        # TODO(474636): Tolerance level is consistently too short. Even with
        # successive increases it kept causing flakiness on the tree.
        'time.clock_gettime',

        # Valgrind injects a few LD_PRELOAD binaries.
        'dl_iterate_phdr.Basic',
    ])

  n.add_disabled_tests(*disabled_tests)
  test_deps = [
      os.path.join(build_common.get_load_library_path(), '%s.so' % x) for x in
      _BIONIC_TEST_LIB_MODULES + ['no-elf-hash-table-library']]

  test_binary = n.link(variables={'ldflags': ldflags})
  n.add_disabled_tests('PthreadThreadContext*.*')
  n.run(test_binary, implicit=test_deps)

  # pthread_context_test should run only with a single thread. As
  # other pthread tests start detached threads which can affect the
  # result of this test, we use a separate TestNinjaGenerator for this
  # test.
  n = ninja_generator.TestNinjaGenerator('bionic_pthread_context_test')
  n.add_enabled_tests('PthreadThreadContext*.*')
  n.run(test_binary, implicit=test_deps)

  # Build the shared object for dlfcn.dlopen_library_with_only_gnu_hash.
  def _filter(vars):
    if vars.get_module_name() == 'no-elf-hash-table-library':
      vars.get_generator_args()['is_for_test'] = True
      return True
  env = {
      'bionic-unit-tests-static_src_files': ''
  }
  make_to_ninja.MakefileNinjaTranslator(
      'android/bionic/tests', extra_env_vars=env).generate(_filter)


def _generate_libgcc_ninja():
  # Currently, we need to generate libgcc.a only for Bare Metal mode.
  if not OPTIONS.is_bare_metal_build():
    return

  # TODO(crbug.com/283798): Build libgcc by ourselves.
  rule_name = 'generate_libgcc'
  n = ninja_generator.NinjaGenerator(rule_name)
  if OPTIONS.is_i686():
    # We use libgcc.a in Android NDK for Bare Metal mode as it is
    # compatible with Bionic.
    orig_libgcc = ('ndk/toolchains/x86-4.6/prebuilt/'
                   'linux-x86/lib/gcc/i686-linux-android/4.6/libgcc.a')
    # This libgcc has unnecessary symbols such as __CTORS__ in
    # _ctors.o. We define this symbol in crtbegin.o, so we need to
    # remove this object from the archive.
    # Functions in generic-morestack{,-thread}.o and morestack.o are not
    # needed if one is not using split stacks and it interferes with our
    # process emulation code.
    remove_object = ('_ctors.o generic-morestack.o generic-morestack-thread.o '
                     'morestack.o')
  elif OPTIONS.is_arm():
    orig_libgcc = (
        'ndk/toolchains/arm-linux-androideabi-4.6/prebuilt/'
        'linux-x86/lib/gcc/arm-linux-androideabi/4.6/armv7-a/libgcc.a')
    # This object depends on some glibc specific symbols around
    # stdio. As no objects in libgcc.a use _eprintf, we can simply
    # remove this object.
    remove_object = '_eprintf.o'
  n.rule(rule_name,
         command=('cp $in $out.tmp && ar d $out.tmp %s && mv $out.tmp $out' %
                  remove_object),
         description=rule_name + ' $out')
  n.build(ninja_generator.get_libgcc_for_bare_metal(), rule_name, orig_libgcc)


def _generate_libgcc_eh_ninja():
  if not OPTIONS.is_nacl_build():
    return

  # Create indirections to expose hidden functions in libgcc_eh.a to DSOs.
  # PNaCl toolchain has its compiler runtime and exception handling code
  # separately in libgcc.a and libgcc_eh.a.
  # Though we need to access libgcc_eh.a from DSOs for getting backtrace,
  # all symbols in libgcc_eh.a are hidden symbols.
  # To expose necessary symbols, we rename these hidden symbols to "__real"
  # prefixed ones, and define proxy functions for them.
  #
  # On the native Linux, libgcc_eh.a is linked only for statically linked
  # binaries, and libgcc_s.so is linked for dynamically linked binaries.
  # However, PNaCl toolchain doesn't support DSOs and doesn't have libgcc_s.so
  # at this time.

  # TODO(crbug.com/283798): Build libgcc by ourselves.
  n = ninja_generator.CNinjaGenerator('generate_libgcc')

  target = OPTIONS.target()
  orig_libgcc = os.path.join(toolchain.get_nacl_libgcc_dir(), 'libgcc_eh.a')

  libgcc_proxy = staging.as_staging(
      'android/bionic/libc/arch-nacl/bionic/libgcc_proxy.S')
  libgcc_proxy_rename_list = n.get_build_path('rename_list')
  gen_rename_list_rule = 'gen_rename_list'
  n.rule(gen_rename_list_rule,
         command=' '.join(['sed', '-n',
                           '\'s/^define_proxy \\(.*\\)$$/\\1 __real\\1/p\'',
                           '$in', '>', '$out']))
  n.build(libgcc_proxy_rename_list, gen_rename_list_rule, inputs=[libgcc_proxy])

  symbol_rename_rule = 'rename_symbols'
  n.rule(symbol_rename_rule,
         command=' '.join([toolchain.get_tool(target, 'objcopy'),
                           '--redefine-syms=$rename_list', '$in', '$out']))

  renamed_a = n.get_build_path('renamed.a')
  n.build(renamed_a, symbol_rename_rule, inputs=orig_libgcc,
          implicit=[libgcc_proxy_rename_list],
          variables={'rename_list': libgcc_proxy_rename_list})

  append_obj_rule = 'append_obj'
  n.rule(append_obj_rule,
         command=' '.join(['cp', '$in', '$out', '&&',
                           toolchain.get_tool(target, 'ar'),
                           'rs', '$out', '$objs']))
  objs = n.asm_with_preprocessing(libgcc_proxy)
  n.build(ninja_generator.get_libgcc_eh_for_nacl(),
          append_obj_rule, inputs=renamed_a, implicit=objs,
          variables={'objs': ' '.join(objs)})


def generate_ninjas():
  ninja_generator_runner.request_run_in_parallel(
      _generate_bionic_test_lib_ninja,
      _generate_naclized_i686_asm_ninja,
      _generate_libc_ninja,
      _generate_libm_ninja,
      _generate_libdl_ninja,
      _generate_runnable_ld_ninja,
      _generate_crt_bionic_ninja,
      _generate_libgcc_ninja,
      _generate_libgcc_eh_ninja)


def generate_test_ninjas():
  ninja_generator_runner.request_run_in_parallel(
      _generate_bionic_fundamental_tests,
      _generate_bionic_tests)
