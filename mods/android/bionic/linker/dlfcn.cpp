/*
 * Copyright (C) 2007 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "linker.h"
// ARC MOD BEGIN
#include "linker_debug.h"
// ARC MOD END

#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <android/dlext.h>

#include <bionic/pthread_internal.h>
#include "private/bionic_tls.h"
#include "private/ScopedPthreadMutexLocker.h"
#include "private/ThreadLocalBuffer.h"
// ARC MOD BEGIN
// Add includes for ARC linker functions.
#include <private/dlsym.h>
#include <private/inject_arc_linker_hooks.h>
#if defined(__native_client__)
#include <private/nacl_dyncode_alloc.h>
#endif
// ARC MOD END

/* This file hijacks the symbols stubbed out in libdl.so. */

static pthread_mutex_t g_dl_mutex = PTHREAD_RECURSIVE_MUTEX_INITIALIZER;

static const char* __bionic_set_dlerror(char* new_value) {
  char** dlerror_slot = &reinterpret_cast<char**>(__get_tls())[TLS_SLOT_DLERROR];

  const char* old_value = *dlerror_slot;
  *dlerror_slot = new_value;
  return old_value;
}

static void __bionic_format_dlerror(const char* msg, const char* detail) {
  char* buffer = __get_thread()->dlerror_buffer;
  strlcpy(buffer, msg, __BIONIC_DLERROR_BUFFER_SIZE);
  if (detail != NULL) {
    strlcat(buffer, ": ", __BIONIC_DLERROR_BUFFER_SIZE);
    strlcat(buffer, detail, __BIONIC_DLERROR_BUFFER_SIZE);
  }

  __bionic_set_dlerror(buffer);
}

const char* dlerror() {
  const char* old_value = __bionic_set_dlerror(NULL);
  return old_value;
}

void android_get_LD_LIBRARY_PATH(char* buffer, size_t buffer_size) {
  ScopedPthreadMutexLocker locker(&g_dl_mutex);
  do_android_get_LD_LIBRARY_PATH(buffer, buffer_size);
}

void android_update_LD_LIBRARY_PATH(const char* ld_library_path) {
  ScopedPthreadMutexLocker locker(&g_dl_mutex);
  do_android_update_LD_LIBRARY_PATH(ld_library_path);
}

static void* dlopen_ext(const char* filename, int flags, const android_dlextinfo* extinfo) {
  ScopedPthreadMutexLocker locker(&g_dl_mutex);
  soinfo* result = do_dlopen(filename, flags, extinfo);
  if (result == NULL) {
    __bionic_format_dlerror("dlopen failed", linker_get_error_buffer());
    return NULL;
  }
  return result;
}

void* android_dlopen_ext(const char* filename, int flags, const android_dlextinfo* extinfo) {
  return dlopen_ext(filename, flags, extinfo);
}

void* dlopen(const char* filename, int flags) {
  return dlopen_ext(filename, flags, NULL);
}

// ARC MOD BEGIN
// Expose __dlsym_with_return_address for __wrap_dlsym.
// See android/bionic/libc/include/private/dlsym.h for details.
void* __dlsym_with_return_address(
    void* handle, const char* symbol, void* ret_addr) {
// ARC MOD END
  ScopedPthreadMutexLocker locker(&g_dl_mutex);

#if !defined(__LP64__)
  if (handle == NULL) {
    __bionic_format_dlerror("dlsym library handle is null", NULL);
    return NULL;
  }
#endif

  if (symbol == NULL) {
    __bionic_format_dlerror("dlsym symbol name is null", NULL);
    return NULL;
  }

  soinfo* found = NULL;
  ElfW(Sym)* sym = NULL;
  if (handle == RTLD_DEFAULT) {
    sym = dlsym_linear_lookup(symbol, &found, NULL);
  } else if (handle == RTLD_NEXT) {
    // ARC MOD BEGIN
    // Expose __dlsym_with_return_address for __wrap_dlsym.
    // See android/bionic/libc/include/private/dlsym.h for details.
    // void* caller_addr = __builtin_return_address(0);
    // soinfo* si = find_containing_library(caller_addr);
    soinfo* si = find_containing_library(ret_addr);
    // ARC MOD END

    sym = NULL;
    if (si && si->next) {
      sym = dlsym_linear_lookup(symbol, &found, si->next);
    }
  } else {
    sym = dlsym_handle_lookup(reinterpret_cast<soinfo*>(handle), &found, symbol);
  }

  if (sym != NULL) {
    unsigned bind = ELF_ST_BIND(sym->st_info);

    if ((bind == STB_GLOBAL || bind == STB_WEAK) && sym->st_shndx != 0) {
      return reinterpret_cast<void*>(sym->st_value + found->load_bias);
    }

    __bionic_format_dlerror("symbol found but not global", symbol);
    return NULL;
  } else {
    __bionic_format_dlerror("undefined symbol", symbol);
    return NULL;
  }
}
// ARC MOD BEGIN
// Expose __dlsym_with_return_address for __wrap_dlsym.
// See android/bionic/libc/include/private/dlsym.h for details.
void* dlsym(void* handle, const char* symbol) {
  return __dlsym_with_return_address(
      handle, symbol, __builtin_return_address(0));
}
// ARC MOD END

int dladdr(const void* addr, Dl_info* info) {
  ScopedPthreadMutexLocker locker(&g_dl_mutex);

  // Determine if this address can be found in any library currently mapped.
  soinfo* si = find_containing_library(addr);
  if (si == NULL) {
    return 0;
  }

  memset(info, 0, sizeof(Dl_info));

  info->dli_fname = si->name;
  // Address at which the shared object is loaded.
  info->dli_fbase = reinterpret_cast<void*>(si->base);

  // Determine if any symbol in the library contains the specified address.
  ElfW(Sym)* sym = dladdr_find_symbol(si, addr);
  if (sym != NULL) {
    info->dli_sname = si->strtab + sym->st_name;
    info->dli_saddr = reinterpret_cast<void*>(si->load_bias + sym->st_value);
  }

  return 1;
}

int dlclose(void* handle) {
  ScopedPthreadMutexLocker locker(&g_dl_mutex);
  do_dlclose(reinterpret_cast<soinfo*>(handle));
  // dlclose has no defined errors.
  return 0;
}

// name_offset: starting index of the name in libdl_info.strtab
#define ELF32_SYM_INITIALIZER(name_offset, value, shndx) \
    { name_offset, \
      reinterpret_cast<Elf32_Addr>(reinterpret_cast<void*>(value)), \
      /* st_size */ 0, \
      (shndx == 0) ? 0 : (STB_GLOBAL << 4), \
      /* st_other */ 0, \
      shndx, \
    }

// ARC MOD BEGIN
// We will redefine ELF64_SYM_INITIALIZER later on because our ELF64
// header has a 32 bit pointer.
#if defined(__native_client__) && defined(__x86_64__)
// Modified for Elf64_Sym_NaCl.
#define ELF64_SYM_INITIALIZER(name_offset, value, shndx) \
  { name_offset, \
    (shndx == 0) ? 0 : (STB_GLOBAL << 4), \
    /* st_other */ 0, \
    shndx, \
    reinterpret_cast<Elf32_Addr>(reinterpret_cast<void*>(value)), \
    /* st_value_padding */ 0, \
    /* st_size */ 0 }
#else
// ARC MOD END
#define ELF64_SYM_INITIALIZER(name_offset, value, shndx) \
    { name_offset, \
      (shndx == 0) ? 0 : (STB_GLOBAL << 4), \
      /* st_other */ 0, \
      shndx, \
      reinterpret_cast<Elf64_Addr>(reinterpret_cast<void*>(value)), \
      /* st_size */ 0, \
    }
// ARC MOD BEGIN
#endif
// ARC MOD END
#if defined(__arm__)
// ARC MOD BEGIN
// Add ARC linker functions.
  // 0000000 00011111 111112 22222222 2333333 3333444444444455555555556666666 6667777777777888888888899999 9999900000000001 1111111112222222222 333333333344444444445 55555555566666666667777777 7778888888888999999999900000
  // 0123456 78901234 567890 12345678 9012345 6789012345678901234567890123456 7890123456789012345678901234 5678901234567890 1234567890123456789 012345678901234567890 12345678901234567890123456 7890123456789012345678901234
#  define ANDROID_LIBDL_STRTAB \
    "dlopen\0dlclose\0dlsym\0dlerror\0dladdr\0android_update_LD_LIBRARY_PATH\0android_get_LD_LIBRARY_PATH\0dl_iterate_phdr\0android_dlopen_ext\0dl_unwind_find_exidx\0__inject_arc_linker_hooks\0__dlsym_with_return_address\0"
// ARC MOD END
#elif defined(__aarch64__) || defined(__i386__) || defined(__mips__) || defined(__x86_64__)
// ARC MOD BEGIN
// Add ARC linker functions.
  // 0000000 00011111 111112 22222222 2333333 3333444444444455555555556666666 6667777777777888888888899999 9999900000000001 1111111112222222222 33333333334444444444555555 5555666666666677777777777888 888888999999999900
  // 0123456 78901234 567890 12345678 9012345 6789012345678901234567890123456 7890123456789012345678901234 5678901234567890 1234567890123456789 01234567890123456789012345 6789012345678901234567890123 456789012345678901
#  define ANDROID_LIBDL_STRTAB \
    "dlopen\0dlclose\0dlsym\0dlerror\0dladdr\0android_update_LD_LIBRARY_PATH\0android_get_LD_LIBRARY_PATH\0dl_iterate_phdr\0android_dlopen_ext\0__inject_arc_linker_hooks\0__dlsym_with_return_address\0nacl_dyncode_alloc\0"
// ARC MOD END
#else
#  error Unsupported architecture. Only arm, arm64, mips, mips64, x86 and x86_64 are presently supported.
#endif

// ARC MOD BEGIN
// 64bit NaCl uses ELF64 but its pointer type is 32bit. This means we
// cannot initialize a 64bit integer in Elf64_Sym (st_value) by a
// pointer. Specifically, on x86-64 NaCl, we cannot compile code like
//
// Elf64_Sym sym = { st_value: (Elf64_Addr)&sym };
//
// So, we define another struct Elf64_Sym_NaCl. This is very similar
// to Elf64_Sym, but its st_value is divided into two 32bit integers
// (i.e., st_value and st_value_padding). This is only used to define
// |libdl_symtab| below. |libdl_symtab| will be passed to
// libdl_info.symtab in this file. Other code will not use this and
// use normal Elf64_Sym instead.
#if defined(__native_client__) && defined(__x86_64__)
struct Elf64_Sym_NaCl {
  Elf64_Word st_name;
  unsigned char st_info;
  unsigned char st_other;
  Elf64_Half st_shndx;
  // Put lower bits first because we are little endian.
  unsigned st_value;
  // We will not fill this field, so this will be initialized to zero.
  unsigned st_value_padding;
  Elf64_Xword st_size;
};

// Static assertions for the layout of Elf64_Sym_NaCl.
#define STATIC_ASSERT(cond, name) \
  struct StaticAssert_ ## name { char name[(cond) ? 1 : -1]; }
STATIC_ASSERT(sizeof(Elf64_Sym_NaCl) == sizeof(Elf64_Sym),
              SizeOf_Elf64_Sym_NaCl);
STATIC_ASSERT(offsetof(Elf64_Sym_NaCl, st_value) ==
              offsetof(Elf64_Sym, st_value),
              OffsetOf_st_value);
STATIC_ASSERT(offsetof(Elf64_Sym_NaCl, st_size) ==
              offsetof(Elf64_Sym, st_size),
              OffsetOf_st_size);

static Elf64_Sym_NaCl g_libdl_symtab[] = {
#else
// ARC MOD END
static ElfW(Sym) g_libdl_symtab[] = {
// ARC MOD BEGIN
#endif
// ARC MOD END
  // Total length of libdl_info.strtab, including trailing 0.
  // This is actually the STH_UNDEF entry. Technically, it's
  // supposed to have st_name == 0, but instead, it points to an index
  // in the strtab with a \0 to make iterating through the symtab easier.
  ELFW(SYM_INITIALIZER)(sizeof(ANDROID_LIBDL_STRTAB) - 1, NULL, 0),
  ELFW(SYM_INITIALIZER)(  0, &dlopen, 1),
  ELFW(SYM_INITIALIZER)(  7, &dlclose, 1),
  ELFW(SYM_INITIALIZER)( 15, &dlsym, 1),
  ELFW(SYM_INITIALIZER)( 21, &dlerror, 1),
  ELFW(SYM_INITIALIZER)( 29, &dladdr, 1),
  ELFW(SYM_INITIALIZER)( 36, &android_update_LD_LIBRARY_PATH, 1),
  ELFW(SYM_INITIALIZER)( 67, &android_get_LD_LIBRARY_PATH, 1),
  ELFW(SYM_INITIALIZER)( 95, &dl_iterate_phdr, 1),
  ELFW(SYM_INITIALIZER)(111, &android_dlopen_ext, 1),
#if defined(__arm__)
  ELFW(SYM_INITIALIZER)(130, &dl_unwind_find_exidx, 1),
  // ARC MOD BEGIN
  // Add ARC linker functions.
  ELFW(SYM_INITIALIZER)(151, &__inject_arc_linker_hooks, 1),
  ELFW(SYM_INITIALIZER)(177, &__dlsym_with_return_address, 1),
#else
  ELFW(SYM_INITIALIZER)(130, &__inject_arc_linker_hooks, 1),
  ELFW(SYM_INITIALIZER)(156, &__dlsym_with_return_address, 1),
#if defined(__native_client__)
  ELFW(SYM_INITIALIZER)(184, &nacl_dyncode_alloc, 1),
#endif
  // ARC MOD END
#endif
};

// Fake out a hash table with a single bucket.
//
// A search of the hash table will look through g_libdl_symtab starting with index 1, then
// use g_libdl_chains to find the next index to look at. g_libdl_chains should be set up to
// walk through every element in g_libdl_symtab, and then end with 0 (sentinel value).
//
// That is, g_libdl_chains should look like { 0, 2, 3, ... N, 0 } where N is the number
// of actual symbols, or nelems(g_libdl_symtab)-1 (since the first element of g_libdl_symtab is not
// a real symbol). (See soinfo_elf_lookup().)
//
// Note that adding any new symbols here requires stubbing them out in libdl.
// ARC MOD BEGIN bionic-linker-libdl-large-buckets
// We use large buckets for libdl to reduce hash conflicts. This will be
// initialized later in init_libdl_buckets(). Make sure the bucket size is
// a prime.
static unsigned g_libdl_buckets[1031];
// ARC MOD END
#if defined(__arm__)
// ARC MOD BEGIN
// Size now varies because __inject_arc_linker_hooks and
// __dlsym_with_return_address have been added.
static unsigned g_libdl_chains[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
#elif defined(__native_client__)
// Size now varies because __inject_arc_linker_hooks,
// __dlsym_with_return_address, and nacl_dyncode_alloc have been added.
static unsigned g_libdl_chains[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
// ARC MOD END
#else
// ARC MOD BEGIN
// Size now varies because __inject_arc_linker_hooks and
// __dlsym_with_return_address have been added.
static unsigned g_libdl_chains[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
// ARC MOD END
#endif

// ARC MOD BEGIN bionic-linker-libdl-large-buckets
// elfhash is copied from linker.cpp.
static unsigned elfhash(const char* _name) {
    const unsigned char* name = reinterpret_cast<const unsigned char*>(_name);
    unsigned h = 0, g;

    while (*name) {
        h = (h << 4) + *name++;
        g = h & 0xf0000000;
        h ^= g;
        h ^= g >> 24;
    }
    return h;
}

static void init_libdl_buckets() {
  const int num_buckets = sizeof(g_libdl_buckets) / sizeof(g_libdl_buckets[0]);
  const int num_symbols = sizeof(g_libdl_symtab) / sizeof(g_libdl_symtab[0]);
  for (int i = 1; i < num_symbols; ++i) {
    const char* name = &ANDROID_LIBDL_STRTAB[g_libdl_symtab[i].st_name];
    int bucket = elfhash(name) % num_buckets;
    if (g_libdl_buckets[bucket] != 0) {
      PRINT("FATAL ERROR: hash collision for libdl symtabs."
            "Consider changing g_libdl_buckets size.");
      exit(1);
    }
    g_libdl_buckets[bucket] = i;
  }
}

// ARC MOD END
// Defined as global because we do not yet have access
// to synchronization functions __cxa_guard_* needed
// to define statics inside functions.
static soinfo __libdl_info;

// This is used by the dynamic linker. Every process gets these symbols for free.
soinfo* get_libdl_info() {
  if (__libdl_info.name[0] == '\0') {
    // initialize
    strncpy(__libdl_info.name, "libdl.so", sizeof(__libdl_info.name));
    __libdl_info.flags = FLAG_LINKED | FLAG_NEW_SOINFO;
    __libdl_info.strtab = ANDROID_LIBDL_STRTAB;
    // ARC MOD BEGIN
#if defined(__native_client__) && defined(__x86_64__)
    // Add a cast for x86-64.
    __libdl_info.symtab = reinterpret_cast<Elf64_Sym*>(g_libdl_symtab);
#else
    // ARC MOD END
    __libdl_info.symtab = g_libdl_symtab;
    // ARC MOD BEGIN
#endif
    // ARC MOD END
    // ARC MOD BEGIN bionic-linker-libdl-large-buckets
    init_libdl_buckets();
    // ARC MOD END
    __libdl_info.nbucket = sizeof(g_libdl_buckets)/sizeof(unsigned);
    __libdl_info.nchain = sizeof(g_libdl_chains)/sizeof(unsigned);
    __libdl_info.bucket = g_libdl_buckets;
    __libdl_info.chain = g_libdl_chains;
    __libdl_info.has_DT_SYMBOLIC = true;
    // ARC MOD BEGIN
    __libdl_info.is_ndk = false;
    // ARC MOD END
  }

  return &__libdl_info;
}
