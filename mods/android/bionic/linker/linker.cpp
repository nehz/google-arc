/*
 * Copyright (C) 2008, 2009 The Android Open Source Project
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *  * Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
 * OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

// Private C library headers.
#include "private/bionic_tls.h"
#include "private/KernelArgumentBlock.h"
#include "private/ScopedPthreadMutexLocker.h"
#include "private/ScopedFd.h"

// ARC MOD BEGIN
// Add includes.
#if defined(HAVE_ARC)
#include <irt_syscalls.h>
#include <nacl_dyncode.h>
#include <private/at_sysinfo.h>
#include <private/dl_dst_lib.h>
#include <private/inject_arc_linker_hooks.h>
#include <private/irt_query_marker.h>
// TODO(crbug.com/354290): Remove this include. This is only for GDB hack.
#if defined(BARE_METAL_BIONIC)
#include <sys/syscall.h>
#endif
// TODO(crbug.com/465216): Remove Bare Metal i686 from this #if.
#if ((defined(BARE_METAL_BIONIC) && defined(__i386__)) ||       \
     (defined(__native_client__) && defined(__x86_64__)))
#include <private/get_tls_for_art.h>
#endif
#endif
// ARC MOD END
#include "linker.h"
#include "linker_debug.h"
#include "linker_environ.h"
#include "linker_phdr.h"
// ARC MOD BEGIN
// Add a function prototype.
#if defined(__native_client__)
void phdr_table_get_nacl_gapped_layout_info(
    const ElfW(Phdr)* phdr_table,
    size_t phdr_count,
    size_t* code_first,
    size_t* code_size,
    size_t* data_first,
    size_t* data_size);

// These symbols are provided by a modified linker script.
// See out/target/nacl_*/runnable-ld.lds generated from
// bionic/linker/arch/nacl/gen_runnable_ld_lds.py.
// __init_array is a symbol that points the start of .init_array section.
// __init_array_end points the end of .init_array section. They are used to
// calculate soinfo.init_array and soinfo.init_array_count to call
// CallConstructors().
extern linker_function_t __init_array;
extern linker_function_t __init_array_end;

#if defined(__x86_64__)
// See bionic/libc/include/private/get_tls_for_art.
__attribute__((section(".get_tls_for_art")))
get_tls_fn_t get_tls_for_art = &__get_tls;
#endif
#endif  // __native_client__

// Add the forward declaration for load_main_binary.
#if defined(HAVE_ARC)
static soinfo* load_main_binary(KernelArgumentBlock& args);
#endif

static void* (*g_resolve_symbol)(const char* symbol);
static int (*g_is_statically_linked)(const char* filename);

// TODO(crbug.com/364344): Remove /vendor/lib.
const char kVendorLibDir[] = "/vendor/lib/";
// ARC MOD END
#include "linker_allocator.h"

/* >>> IMPORTANT NOTE - READ ME BEFORE MODIFYING <<<
 *
 * Do NOT use malloc() and friends or pthread_*() code here.
 * Don't use printf() either; it's caused mysterious memory
 * corruption in the past.
 * The linker runs before we bring up libc and it's easiest
 * to make sure it does not depend on any complex libc features
 *
 * open issues / todo:
 *
 * - cleaner error reporting
 * - after linking, set as much stuff as possible to READONLY
 *   and NOEXEC
 */
// ARC MOD BEGIN
// For showing some performance stats when --logging=bionic-loader is
// specified.
#if defined(BIONIC_LOADER_LOGGING)

template <int line_number>
class ScopedElapsedTimePrinter {
public:
  ScopedElapsedTimePrinter(const char* category, const char* name)
    : category_(category), name_(name) {
    gettimeofday(&t0_, NULL);
  }

  ~ScopedElapsedTimePrinter() {
    timeval t1;
    gettimeofday(&t1, NULL);
    const int elapsed =
      (((long long)t1.tv_sec * 1000000LL) + (long long)t1.tv_usec) -
      (((long long)t0_.tv_sec * 1000000LL) + (long long)t0_.tv_usec);
    cumulative_ += elapsed;
    PRINT("LINKER TIME: %s %s: %d us (%d ms cumulative for line:%d)",
          category_, name_, elapsed, cumulative_ / 1000, line_number);
  }

private:
  static int cumulative_;  // held per |line_number|

  const char* category_;
  const char* name_;
  timeval t0_;
};

template <int line_number>
int ScopedElapsedTimePrinter<line_number>::cumulative_ = 0;

#else  // BIONIC_LOADER_LOGGING

template <int line_number>
class ScopedElapsedTimePrinter {
public:
  ScopedElapsedTimePrinter(const char* category, const char* name) {}
};

#endif  // BIONIC_LOADER_LOGGING
// ARC MOD END

#if defined(__LP64__)
#define SEARCH_NAME(x) x
#else
// Nvidia drivers are relying on the bug:
// http://code.google.com/p/android/issues/detail?id=6670
// so we continue to use base-name lookup for lp32
static const char* get_base_name(const char* name) {
  const char* bname = strrchr(name, '/');
  return bname ? bname + 1 : name;
}
#define SEARCH_NAME(x) get_base_name(x)
#endif

static bool soinfo_link_image(soinfo* si, const android_dlextinfo* extinfo);
static ElfW(Addr) get_elf_exec_load_bias(const ElfW(Ehdr)* elf);

static LinkerAllocator<soinfo> g_soinfo_allocator;
static LinkerAllocator<LinkedListEntry<soinfo>> g_soinfo_links_allocator;

static soinfo* solist;
static soinfo* sonext;
static soinfo* somain; /* main process, always the one after libdl_info */

static const char* const kDefaultLdPaths[] = {
#if defined(__LP64__)
  "/vendor/lib64",
  "/system/lib64",
#else
  "/vendor/lib",
  "/system/lib",
#endif
  NULL
};

#define LDPATH_BUFSIZE (LDPATH_MAX*64)
#define LDPATH_MAX 8

#define LDPRELOAD_BUFSIZE (LDPRELOAD_MAX*64)
#define LDPRELOAD_MAX 8

static char g_ld_library_paths_buffer[LDPATH_BUFSIZE];
static const char* g_ld_library_paths[LDPATH_MAX + 1];

static char g_ld_preloads_buffer[LDPRELOAD_BUFSIZE];
static const char* g_ld_preload_names[LDPRELOAD_MAX + 1];

static soinfo* g_ld_preloads[LDPRELOAD_MAX + 1];

// ARC MOD BEGIN
// When you port the linker MODs to a newer Bionic release, you might want
// to initialize |g_ld_debug_verbosity| with 3 to get full debug logs (such as
// DL_ERR) from the linker. As neither sel_ldr nor nacl_helper
// propagates environment variables, you need to modify this parameter
// directly. Note that this value will be updated to -1 in
// __linker_init for --disable-debug-code build.
//
// run_unittest.py --gdb is also useful to debug crashes when porting
// the linker:
//  $ ninja out/target/nacl_x86_64_dbg/bionic_tests/loader_test
//  $ src/build/run_unittest.py bionic_fundamental_loader_test
// ARC MOD END
__LIBC_HIDDEN__ int g_ld_debug_verbosity;

__LIBC_HIDDEN__ abort_msg_t* g_abort_message = NULL; // For debuggerd.

enum RelocationKind {
    kRelocAbsolute = 0,
    kRelocRelative,
    kRelocCopy,
    kRelocSymbol,
    kRelocMax
};

#if STATS
struct linker_stats_t {
    int count[kRelocMax];
};

static linker_stats_t linker_stats;

static void count_relocation(RelocationKind kind) {
    ++linker_stats.count[kind];
}
#else
static void count_relocation(RelocationKind) {
}
#endif

#if COUNT_PAGES
static unsigned bitmask[4096];
#if defined(__LP64__)
#define MARK(offset) \
    do { \
        if ((((offset) >> 12) >> 5) < 4096) \
            bitmask[((offset) >> 12) >> 5] |= (1 << (((offset) >> 12) & 31)); \
    } while (0)
#else
#define MARK(offset) \
    do { \
        bitmask[((offset) >> 12) >> 3] |= (1 << (((offset) >> 12) & 7)); \
    } while (0)
#endif
#else
#define MARK(x) do {} while (0)
#endif

// You shouldn't try to call memory-allocating functions in the dynamic linker.
// Guard against the most obvious ones.
#define DISALLOW_ALLOCATION(return_type, name, ...) \
    return_type name __VA_ARGS__ \
    { \
        __libc_fatal("ERROR: " #name " called from the dynamic linker!\n"); \
    }
DISALLOW_ALLOCATION(void*, malloc, (size_t u __unused));
DISALLOW_ALLOCATION(void, free, (void* u __unused));
DISALLOW_ALLOCATION(void*, realloc, (void* u1 __unused, size_t u2 __unused));
DISALLOW_ALLOCATION(void*, calloc, (size_t u1 __unused, size_t u2 __unused));

static char tmp_err_buf[768];
static char __linker_dl_err_buf[768];

char* linker_get_error_buffer() {
  return &__linker_dl_err_buf[0];
}

size_t linker_get_error_buffer_size() {
  return sizeof(__linker_dl_err_buf);
}

/*
 * This function is an empty stub where GDB locates a breakpoint to get notified
 * about linker activity.
 */
extern "C" void __attribute__((noinline)) __attribute__((visibility("default"))) rtld_db_dlactivity();

static pthread_mutex_t g__r_debug_mutex = PTHREAD_MUTEX_INITIALIZER;
// ARC MOD BEGIN
// Cast rtld_db_dlactivity to Elf64_Addr on x86-64 NaCl.
#if defined(__native_client__) && defined(__x86_64__)
static r_debug _r_debug = {1, NULL, reinterpret_cast<Elf64_Addr>(&rtld_db_dlactivity),
                           r_debug::RT_CONSISTENT, 0};
#else
// ARC MOD END
static r_debug _r_debug = {1, NULL, reinterpret_cast<uintptr_t>(&rtld_db_dlactivity), r_debug::RT_CONSISTENT, 0};
// ARC MOD BEGIN
#endif
// ARC MOD END
static link_map* r_debug_tail = 0;

static void insert_soinfo_into_debug_map(soinfo* info) {
    // Copy the necessary fields into the debug structure.
    link_map* map = &(info->link_map_head);
    // ARC MOD BEGIN
    // TODO(crbug.com/465619): L-rebase: Verify if this new data is
    // compatible with minidump. See also 'git show 914cd7f7'.
    // ARC MOD END
    map->l_addr = info->load_bias;
    map->l_name = reinterpret_cast<char*>(info->name);
    map->l_ld = info->dynamic;

    /* Stick the new library at the end of the list.
     * gdb tends to care more about libc than it does
     * about leaf libraries, and ordering it this way
     * reduces the back-and-forth over the wire.
     */
    if (r_debug_tail) {
        r_debug_tail->l_next = map;
        map->l_prev = r_debug_tail;
        map->l_next = 0;
    } else {
        _r_debug.r_map = map;
        map->l_prev = 0;
        map->l_next = 0;
    }
    r_debug_tail = map;
}

static void remove_soinfo_from_debug_map(soinfo* info) {
    link_map* map = &(info->link_map_head);

    if (r_debug_tail == map) {
        r_debug_tail = map->l_prev;
    }

    if (map->l_prev) {
        map->l_prev->l_next = map->l_next;
    }
    if (map->l_next) {
        map->l_next->l_prev = map->l_prev;
    }
}

// ARC MOD BEGIN
// See linker_notify.S.
#if defined(BARE_METAL_BIONIC)
extern "C"
void __bare_metal_notify_gdb_of_load(const char* name, ElfW(Addr) base);
#endif  // BARE_METAL_BIONIC
// ARC MOD END
static void notify_gdb_of_load(soinfo* info) {
    // ARC MOD BEGIN
    // Always copy the necessary fields into the debug
    // structure. The original Bionic loader fills these fields in
    // insert_soinfo_into_debug_map, but we do not call this function
    // for ET_EXEC or Bare Metal mode. The behavior of the original
    // Bionic loader is OK because info->link_map is not used on normal
    // Linux. The loader does not need to tell the information of the
    // main binary to GDB.
    // TODO(crbug.com/323864): Enable this on NaCl. Currently this is
    // excluded to workaround the issue of minidumps not being generated.
#if defined(BARE_METAL_BIONIC)
    link_map* map = &(info->link_map_head);
    map->l_addr = info->base;
    if (!map->l_name) {
      // main binary's argv[0] is /lib/main.nexe, here it's main.nexe,
      // keep /lib/main.nexe here.  For shared libraries, it is NULL,
      // so give it some value.
      map->l_name = info->name;
    }
    map->l_ld = (ElfW(Dyn)*)info->dynamic;

    __bare_metal_notify_gdb_of_load(info->name, info->base);
#else
    // ARC MOD END
    if (info->flags & FLAG_EXE) {
        // GDB already knows about the main executable
        return;
    }

    ScopedPthreadMutexLocker locker(&g__r_debug_mutex);

    _r_debug.r_state = r_debug::RT_ADD;
    rtld_db_dlactivity();

    insert_soinfo_into_debug_map(info);

    _r_debug.r_state = r_debug::RT_CONSISTENT;
    rtld_db_dlactivity();
    // ARC MOD BEGIN
#endif
    // ARC MOD END
}

static void notify_gdb_of_unload(soinfo* info) {
    // ARC MOD BEGIN
    // Ask the Bare Metal loader to interact with GDB.
#if defined(BARE_METAL_BIONIC)
    // We do not support notifying module unload to GDB yet.
#else
    // ARC MOD END
    if (info->flags & FLAG_EXE) {
        // GDB already knows about the main executable
        return;
    }

    ScopedPthreadMutexLocker locker(&g__r_debug_mutex);

    _r_debug.r_state = r_debug::RT_DELETE;
    rtld_db_dlactivity();

    remove_soinfo_from_debug_map(info);

    _r_debug.r_state = r_debug::RT_CONSISTENT;
    rtld_db_dlactivity();
    // ARC MOD BEGIN
#endif
    // ARC MOD END
}

void notify_gdb_of_libraries() {
  // ARC MOD BEGIN
  // Ask the Bare Metal loader to interact with GDB.
#if defined(BARE_METAL_BIONIC)
    // We do not support notifying all module updates to GDB yet.
#else
  // ARC MOD END
  _r_debug.r_state = r_debug::RT_ADD;
  rtld_db_dlactivity();
  _r_debug.r_state = r_debug::RT_CONSISTENT;
  rtld_db_dlactivity();
  // ARC MOD BEGIN
#endif
  // ARC MOD END
}

LinkedListEntry<soinfo>* SoinfoListAllocator::alloc() {
  return g_soinfo_links_allocator.alloc();
}

void SoinfoListAllocator::free(LinkedListEntry<soinfo>* entry) {
  g_soinfo_links_allocator.free(entry);
}

static void protect_data(int protection) {
  g_soinfo_allocator.protect_all(protection);
  g_soinfo_links_allocator.protect_all(protection);
}

static soinfo* soinfo_alloc(const char* name, struct stat* file_stat) {
  if (strlen(name) >= SOINFO_NAME_LEN) {
    DL_ERR("library name \"%s\" too long", name);
    return NULL;
  }

  soinfo* si = g_soinfo_allocator.alloc();

  // Initialize the new element.
  memset(si, 0, sizeof(soinfo));
  strlcpy(si->name, name, sizeof(si->name));
  si->flags = FLAG_NEW_SOINFO;

  if (file_stat != NULL) {
    si->set_st_dev(file_stat->st_dev);
    si->set_st_ino(file_stat->st_ino);
  }

  sonext->next = si;
  sonext = si;

  TRACE("name %s: allocated soinfo @ %p", name, si);
  return si;
}

static void soinfo_free(soinfo* si) {
    if (si == NULL) {
        return;
    }

    if (si->base != 0 && si->size != 0) {
      // ARC MOD BEGIN
      // When NaCl is in use, the linker maps text and data separately.
      // The following code unmaps the latter.
#if defined(__native_client__)
      size_t code_first = 0;
      size_t code_size = 0;
      size_t data_first = 0;
      size_t data_size = 0;
      phdr_table_get_nacl_gapped_layout_info(si->phdr,
                                             si->phnum,
                                             &code_first,
                                             &code_size,
                                             &data_first,
                                             &data_size);
      TRACE("soinfo_unload: munmap data: %p-%p\n",
            (char *)data_first, (char *)data_first + data_size);
      munmap((char *)data_first, data_size);
      TRACE("soinfo_unload: munmap text: %p-%p\n",
            (char *)si->base, (char *)si->base + si->size);
#else
      TRACE("soinfo_unload: munmap: %p-%p\n",
            (char *)si->base, (char *)si->base + si->size);
#endif
      // ARC MOD END
      munmap(reinterpret_cast<void*>(si->base), si->size);
    }

    soinfo *prev = NULL, *trav;

    TRACE("name %s: freeing soinfo @ %p", si->name, si);

    for (trav = solist; trav != NULL; trav = trav->next) {
        if (trav == si)
            break;
        prev = trav;
    }
    if (trav == NULL) {
        /* si was not in solist */
        DL_ERR("name \"%s\" is not in solist!", si->name);
        return;
    }

    // clear links to/from si
    si->remove_all_links();

    /* prev will never be NULL, because the first entry in solist is
       always the static libdl_info.
    */
    prev->next = si->next;
    if (si == sonext) {
        sonext = prev;
    }

    g_soinfo_allocator.free(si);
}


static void parse_path(const char* path, const char* delimiters,
                       const char** array, char* buf, size_t buf_size, size_t max_count) {
  if (path == NULL) {
    return;
  }

  size_t len = strlcpy(buf, path, buf_size);

  size_t i = 0;
  char* buf_p = buf;
  while (i < max_count && (array[i] = strsep(&buf_p, delimiters))) {
    if (*array[i] != '\0') {
      ++i;
    }
  }

  // Forget the last path if we had to truncate; this occurs if the 2nd to
  // last char isn't '\0' (i.e. wasn't originally a delimiter).
  if (i > 0 && len >= buf_size && buf[buf_size - 2] != '\0') {
    array[i - 1] = NULL;
  } else {
    array[i] = NULL;
  }
}

static void parse_LD_LIBRARY_PATH(const char* path) {
  parse_path(path, ":", g_ld_library_paths,
             g_ld_library_paths_buffer, sizeof(g_ld_library_paths_buffer), LDPATH_MAX);
}

static void parse_LD_PRELOAD(const char* path) {
  // We have historically supported ':' as well as ' ' in LD_PRELOAD.
  parse_path(path, " :", g_ld_preload_names,
             g_ld_preloads_buffer, sizeof(g_ld_preloads_buffer), LDPRELOAD_MAX);
}

#if defined(__arm__)

/* For a given PC, find the .so that it belongs to.
 * Returns the base address of the .ARM.exidx section
 * for that .so, and the number of 8-byte entries
 * in that section (via *pcount).
 *
 * Intended to be called by libc's __gnu_Unwind_Find_exidx().
 *
 * This function is exposed via dlfcn.cpp and libdl.so.
 */
_Unwind_Ptr dl_unwind_find_exidx(_Unwind_Ptr pc, int* pcount) {
    unsigned addr = (unsigned)pc;

    for (soinfo* si = solist; si != 0; si = si->next) {
        if ((addr >= si->base) && (addr < (si->base + si->size))) {
            *pcount = si->ARM_exidx_count;
            return (_Unwind_Ptr)si->ARM_exidx;
        }
    }
    *pcount = 0;
    return NULL;
}

#endif

/* Here, we only have to provide a callback to iterate across all the
 * loaded libraries. gcc_eh does the rest. */
int dl_iterate_phdr(int (*cb)(dl_phdr_info* info, size_t size, void* data), void* data) {
    int rv = 0;
    for (soinfo* si = solist; si != NULL; si = si->next) {
        dl_phdr_info dl_info;
        dl_info.dlpi_addr = si->link_map_head.l_addr;
        dl_info.dlpi_name = si->link_map_head.l_name;
        dl_info.dlpi_phdr = si->phdr;
        dl_info.dlpi_phnum = si->phnum;
        rv = cb(&dl_info, sizeof(dl_phdr_info), data);
        if (rv != 0) {
            break;
        }
    }
    return rv;
}

static ElfW(Sym)* soinfo_elf_lookup(soinfo* si, unsigned hash, const char* name) {
  ElfW(Sym)* symtab = si->symtab;
  const char* strtab = si->strtab;

  TRACE_TYPE(LOOKUP, "SEARCH %s in %s@%p %x %zd",
             name, si->name, reinterpret_cast<void*>(si->base), hash, hash % si->nbucket);

  for (unsigned n = si->bucket[hash % si->nbucket]; n != 0; n = si->chain[n]) {
    ElfW(Sym)* s = symtab + n;
    if (strcmp(strtab + s->st_name, name)) continue;

    /* only concern ourselves with global and weak symbol definitions */
    switch (ELF_ST_BIND(s->st_info)) {
      case STB_GLOBAL:
      case STB_WEAK:
        // ARC MOD BEGIN
        // We treat STB_GNU_UNIQUE as STB_GLOBAL.
        // TODO(crbug.com/306079): Check if this is OK and implement
        // STB_GNU_UNIQUE support if necessary.
#define STB_GNU_UNIQUE 10
      case STB_GNU_UNIQUE:
        // ARC MOD END
        if (s->st_shndx == SHN_UNDEF) {
          continue;
        }

        TRACE_TYPE(LOOKUP, "FOUND %s in %s (%p) %zd",
                 name, si->name, reinterpret_cast<void*>(s->st_value),
                 static_cast<size_t>(s->st_size));
        return s;
      case STB_LOCAL:
        continue;
      default:
        __libc_fatal("ERROR: Unexpected ST_BIND value: %d for '%s' in '%s'",
            ELF_ST_BIND(s->st_info), name, si->name);
    }
  }

  TRACE_TYPE(LOOKUP, "NOT FOUND %s in %s@%p %x %zd",
             name, si->name, reinterpret_cast<void*>(si->base), hash, hash % si->nbucket);


  return NULL;
}

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

static ElfW(Sym)* soinfo_do_lookup(soinfo* si, const char* name, soinfo** lsi, soinfo* needed[]) {
    unsigned elf_hash = elfhash(name);
    ElfW(Sym)* s = NULL;

    if (si != NULL && somain != NULL) {
        /*
         * Local scope is executable scope. Just start looking into it right away
         * for the shortcut.
         */

        if (si == somain) {
            s = soinfo_elf_lookup(si, elf_hash, name);
            if (s != NULL) {
                *lsi = si;
                goto done;
            }

            /* Next, look for it in the preloads list */
            for (int i = 0; g_ld_preloads[i] != NULL; i++) {
                s = soinfo_elf_lookup(g_ld_preloads[i], elf_hash, name);
                if (s != NULL) {
                    *lsi = g_ld_preloads[i];
                    goto done;
                }
            }
        } else {
            /* Order of symbol lookup is controlled by DT_SYMBOLIC flag */

            /*
             * If this object was built with symbolic relocations disabled, the
             * first place to look to resolve external references is the main
             * executable.
             */

            if (!si->has_DT_SYMBOLIC) {
                // ARC MOD BEGIN bionic-linker-symbol-lookup-order
                // For real Android apps, the main binary is app_process,
                // which has no meaningful symbol and no lookup is done
                // here. This code path would exist for non-app
                // executables. On the other hand, arc.nexe has a lot of
                // symbols. To emulate the behavior for app_process, we
                // resolve no symbol here.
                // TODO(crbug.com/368131): Add an integration test for this.
#if !defined(HAVE_ARC)
                // ARC MOD END
                DEBUG("%s: looking up %s in executable %s",
                      si->name, name, somain->name);
                s = soinfo_elf_lookup(somain, elf_hash, name);
                if (s != NULL) {
                    *lsi = somain;
                    goto done;
                }
                // ARC MOD BEGIN bionic-linker-symbol-lookup-order
#endif
                // ARC MOD END

                /* Next, look for it in the preloads list */
                for (int i = 0; g_ld_preloads[i] != NULL; i++) {
                    s = soinfo_elf_lookup(g_ld_preloads[i], elf_hash, name);
                    if (s != NULL) {
                        *lsi = g_ld_preloads[i];
                        goto done;
                    }
                }
            }

            /* Look for symbols in the local scope (the object who is
             * searching). This happens with C++ templates on x86 for some
             * reason.
             *
             * Notes on weak symbols:
             * The ELF specs are ambiguous about treatment of weak definitions in
             * dynamic linking.  Some systems return the first definition found
             * and some the first non-weak definition.   This is system dependent.
             * Here we return the first definition found for simplicity.  */

            s = soinfo_elf_lookup(si, elf_hash, name);
            if (s != NULL) {
                *lsi = si;
                goto done;
            }

            /*
             * If this object was built with -Bsymbolic and symbol is not found
             * in the local scope, try to find the symbol in the main executable.
             */

            if (si->has_DT_SYMBOLIC) {
                // ARC MOD BEGIN bionic-linker-symbol-lookup-order
#if !defined(HAVE_ARC)
                // ARC MOD END
                DEBUG("%s: looking up %s in executable %s after local scope",
                      si->name, name, somain->name);
                s = soinfo_elf_lookup(somain, elf_hash, name);
                if (s != NULL) {
                    *lsi = somain;
                    goto done;
                }
                // ARC MOD BEGIN bionic-linker-symbol-lookup-order
#endif
                // ARC MOD END

                /* Next, look for it in the preloads list */
                for (int i = 0; g_ld_preloads[i] != NULL; i++) {
                    s = soinfo_elf_lookup(g_ld_preloads[i], elf_hash, name);
                    if (s != NULL) {
                        *lsi = g_ld_preloads[i];
                        goto done;
                    }
                }
            }
        }
    }

    for (int i = 0; needed[i] != NULL; i++) {
        DEBUG("%s: looking up %s in %s",
              si->name, name, needed[i]->name);
        s = soinfo_elf_lookup(needed[i], elf_hash, name);
        if (s != NULL) {
            *lsi = needed[i];
            goto done;
        }
    }

done:
    if (s != NULL) {
        TRACE_TYPE(LOOKUP, "si %s sym %s s->st_value = %p, "
                   "found in %s, base = %p, load bias = %p",
                   si->name, name, reinterpret_cast<void*>(s->st_value),
                   (*lsi)->name, reinterpret_cast<void*>((*lsi)->base),
                   reinterpret_cast<void*>((*lsi)->load_bias));
        return s;
    }

    return NULL;
}

// Another soinfo list allocator to use in dlsym. We don't reuse
// SoinfoListAllocator because it is write-protected most of the time.
static LinkerAllocator<LinkedListEntry<soinfo>> g_soinfo_list_allocator_rw;
class SoinfoListAllocatorRW {
 public:
  static LinkedListEntry<soinfo>* alloc() {
    return g_soinfo_list_allocator_rw.alloc();
  }

  static void free(LinkedListEntry<soinfo>* ptr) {
    g_soinfo_list_allocator_rw.free(ptr);
  }
};

// This is used by dlsym(3).  It performs symbol lookup only within the
// specified soinfo object and its dependencies in breadth first order.
ElfW(Sym)* dlsym_handle_lookup(soinfo* si, soinfo** found, const char* name) {
  LinkedList<soinfo, SoinfoListAllocatorRW> visit_list;
  LinkedList<soinfo, SoinfoListAllocatorRW> visited;
  visit_list.push_back(si);
  soinfo* current_soinfo;
  while ((current_soinfo = visit_list.pop_front()) != nullptr) {
    if (visited.contains(current_soinfo)) {
      continue;
    }

    ElfW(Sym)* result = soinfo_elf_lookup(current_soinfo, elfhash(name), name);

    if (result != nullptr) {
      *found = current_soinfo;
      visit_list.clear();
      visited.clear();
      return result;
    }
    visited.push_back(current_soinfo);

    current_soinfo->get_children().for_each([&](soinfo* child) {
      visit_list.push_back(child);
    });
  }

  visit_list.clear();
  visited.clear();
  return nullptr;
}

/* This is used by dlsym(3) to performs a global symbol lookup. If the
   start value is null (for RTLD_DEFAULT), the search starts at the
   beginning of the global solist. Otherwise the search starts at the
   specified soinfo (for RTLD_NEXT).
 */
ElfW(Sym)* dlsym_linear_lookup(const char* name, soinfo** found, soinfo* start) {
  unsigned elf_hash = elfhash(name);

  if (start == NULL) {
    start = solist;
  }

  ElfW(Sym)* s = NULL;
  for (soinfo* si = start; (s == NULL) && (si != NULL); si = si->next) {
    s = soinfo_elf_lookup(si, elf_hash, name);
    if (s != NULL) {
      *found = si;
      break;
    }
  }

  if (s != NULL) {
    TRACE_TYPE(LOOKUP, "%s s->st_value = %p, found->base = %p",
               name, reinterpret_cast<void*>(s->st_value), reinterpret_cast<void*>((*found)->base));
  }

  return s;
}

soinfo* find_containing_library(const void* p) {
  ElfW(Addr) address = reinterpret_cast<ElfW(Addr)>(p);
  for (soinfo* si = solist; si != NULL; si = si->next) {
    if (address >= si->base && address - si->base < si->size) {
      return si;
    }
  }
  return NULL;
}

ElfW(Sym)* dladdr_find_symbol(soinfo* si, const void* addr) {
  // ARC MOD BEGIN UPSTREAM bionic-fix-dladdr--main-binary
  // Use si->load_bias instead of si->base. This si->base works for
  // shared objects but does not work for the main binary. The load
  // bias of a main binary is not as same as si->base of the main
  // binary unless the binary is a PIE. For example, si->load_bias
  // of a NaCl main binary is 0 but its base is 0x10000.
  ElfW(Addr) soaddr = reinterpret_cast<ElfW(Addr)>(addr) - si->load_bias;
  // ARC MOD END UPSTREAM

  // Search the library's symbol table for any defined symbol which
  // contains this address.
  for (size_t i = 0; i < si->nchain; ++i) {
    ElfW(Sym)* sym = &si->symtab[i];
    if (sym->st_shndx != SHN_UNDEF &&
        soaddr >= sym->st_value &&
        soaddr < sym->st_value + sym->st_size) {
      return sym;
    }
  }

  return NULL;
}

// ARC MOD BEGIN
#if defined(HAVE_ARC)
static int open_library_nacl(const char* name) {
  ScopedElapsedTimePrinter<__LINE__> printer(
      "Called open_library_nacl for", name);
  char buf[512];
  // Once __inject_arc_linker_hooks has been called, we only use
  // posix_translation based file descriptors, so we do not use
  // __nacl_irt_open_resource.
  if (g_resolve_symbol) {
    // If |name| contains a slash, we have already tried to open this
    // file in open_library().
    if (strchr(name, '/'))
      return -1;
    __libc_format_buffer(buf, sizeof(buf), "/system/lib/%s", name);
    return open(buf, O_RDONLY);
  } else {
    // If the name is a basename (does not start with /), prepend /lib/ to the
    // path because that is what nacl_irt_open_resource expects.
    if (name && name[0] != '/') {
      __libc_format_buffer(buf, sizeof(buf), DL_DST_LIB "/%s", name);
      name = buf;
    }
    // When the path starts with DL_DST_LIB, the file is specified by
    // NaCl's NMF, which can be accessed only by open_resource IRT
    // call. For this case, we need to call __nacl_irt_open_resource
    // without trying stat for this file.
    if (!memcmp(DL_DST_LIB "/", name, sizeof(DL_DST_LIB))) {
      int fd;
      if (__nacl_irt_open_resource(name, &fd) != 0)
        return -1;
      return fd;
    }
    return -1;
  }
}
#endif

// ARC MOD END
// ARC MOD BEGIN bionic-linker-ndk-detection
// Add |is_in_vendor_lib| argument.
// TODO(crbug.com/364344): Remove /vendor/lib.
static int open_library_on_path(const char* name, const char* const paths[],
                                int* is_in_vendor_lib) {
// ARC MOD END
  char buf[512];
  for (size_t i = 0; paths[i] != NULL; ++i) {
    int n = __libc_format_buffer(buf, sizeof(buf), "%s/%s", paths[i], name);
    if (n < 0 || n >= static_cast<int>(sizeof(buf))) {
      PRINT("Warning: ignoring very long library path: %s/%s", paths[i], name);
      continue;
    }
    int fd = TEMP_FAILURE_RETRY(open(buf, O_RDONLY | O_CLOEXEC));
    if (fd != -1) {
      // ARC MOD BEGIN bionic-linker-ndk-detection
      // Unlike the MOD in load_library, we do not need to check files
      // in /data/app-lib as this path is not in LD_LIBRARY_PATH.
      if (!strcmp(paths[i], kVendorLibDir)) {
        *is_in_vendor_lib = 1;
      }
      // ARC MOD END
      return fd;
    }
  }
  return -1;
}

// ARC MOD BEGIN bionic-linker-ndk-detection
// Add |is_in_vendor_lib| argument.
// TODO(crbug.com/364344): Remove /vendor/lib.
static int open_library(const char* name, int* is_in_vendor_lib) {
// ARC MOD END
  // ARC MOD BEGIN
  // Note on which code path is used for which case:
  //
  // 1. DT_NEEDED specified by arc.nexe: We use
  //   __nacl_irt_open_resource() directly from open_library_nacl.
  // 2. dlopen for binaries in arc.nmf (e.g., libEGL_emulation.so):
  //    If a fullpath is not specified, we prepend /system/lib and
  //    call open() from open_library_nacl or open_library. As
  //    __inject_arc_linker_hooks replaces __nacl_irt_open, this is
  //    handled by posix_translation and it calls
  //    __nacl_irt_open_resource().
  // 3. dlopen for NDK binaries (NDK direct execution mode only): We
  //    call open() from open_library. This will be handled by
  //    posix_translation and PepperFileHandler handles this.
  // 4. DT_NEEDED specified by unit tests: We use open() in
  //    open_library_on_path. Note that we rely on LD_LIBRARY_PATH
  //    specified by our unit test runner.
  // 5. dlopen from unit tests: Like 4, we use open in
  //    open_library_on_path(). __inject_arc_linker_hooks has been
  //    already called so the implementation of __nacl_irt_open is
  //    hooked, but it ends up calling real open() for unit tests.
  //
  // ARC MOD END
  TRACE("[ opening %s ]", name);

  // If the name contains a slash, we should attempt to open it directly and not search the paths.
  if (strchr(name, '/') != NULL) {
    int fd = TEMP_FAILURE_RETRY(open(name, O_RDONLY | O_CLOEXEC));
    if (fd != -1) {
      return fd;
    }
    // ...but nvidia binary blobs (at least) rely on this behavior, so fall through for now.
    // ARC MOD BEGIN
    // We always need to try open_library_nacl. So we will never
    // return here. Although we do not need this MOD right now as we
    // do not define __LP64__, this "return -1" is likely to be
    // removed in future, so we explicitly have !HAVE_ARC here.
#if defined(__LP64__) && !defined(HAVE_ARC)
    // ARC MOD END
    return -1;
#endif
  }
  // ARC MOD BEGIN
#if defined(HAVE_ARC)
  int naclfd = open_library_nacl(name);
  if (naclfd != -1)
    return naclfd;
  // Note: Our unit tests need open_library_on_path calls below since
  // the test binaries have DT_NEEDED entries like "libc.so" and such
  // DT_NEEDED libraries live in a path like
  // "out/target/nacl_i686_opt/lib/", not in "/lib". Also note that
  // open_library_on_path does nothing as |g_ld_library_paths| is
  // empty on production ARC and therefore is fast.
  return open_library_on_path(name, g_ld_library_paths, is_in_vendor_lib);

  // We have already tried /system/lib by __nacl_irt_open_resource
  // (before __inject_arc_linker_hooks) or __nacl_irt_open (after
  // __inject_arc_linker_hooks, so retrying with kDefaultLdPaths does
  // not make sense for us. Not to call open_resource IRT which
  // synchronizes with the renderer, disable the slow fallback path.
#else
  // ARC MOD END
  // Otherwise we try LD_LIBRARY_PATH first, and fall back to the built-in well known paths.
  // ARC MOD BEGIN bionic-linker-ndk-detection
  int fd = open_library_on_path(name, g_ld_library_paths, is_in_vendor_lib);
  // ARC MOD END
  if (fd == -1) {
    // ARC MOD BEGIN bionic-linker-ndk-detection
    fd = open_library_on_path(name, kDefaultLdPaths, is_in_vendor_lib);
    // ARC MOD END
  }
  return fd;
  // ARC MOD BEGIN
#endif
  // ARC MOD END
}

static soinfo* load_library(const char* name, int dlflags, const android_dlextinfo* extinfo) {
    int fd = -1;
    ScopedFd file_guard(-1);
    // ARC MOD BEGIN bionic-linker-ndk-detection
    int is_in_vendor_lib = 0;
    // ARC MOD END

    if (extinfo != NULL && (extinfo->flags & ANDROID_DLEXT_USE_LIBRARY_FD) != 0) {
      fd = extinfo->library_fd;
    } else {
      // Open the file.
      // ARC MOD BEGIN bionic-linker-ndk-detection
      // Pass |is_in_vendor_lib| to open_library.
      // TODO(crbug.com/364344): Remove /vendor/lib.
      fd = open_library(name, &is_in_vendor_lib);
      // ARC MOD END
      if (fd == -1) {
        DL_ERR("library \"%s\" not found", name);
        return NULL;
      }

      file_guard.reset(fd);
    }

    ElfReader elf_reader(name, fd);

    struct stat file_stat;
    if (TEMP_FAILURE_RETRY(fstat(fd, &file_stat)) != 0) {
      DL_ERR("unable to stat file for the library %s: %s", name, strerror(errno));
      return NULL;
    }

    // Check for symlink and other situations where
    // file can have different names.
    for (soinfo* si = solist; si != NULL; si = si->next) {
      if (si->get_st_dev() != 0 &&
          si->get_st_ino() != 0 &&
          si->get_st_dev() == file_stat.st_dev &&
          si->get_st_ino() == file_stat.st_ino) {
        TRACE("library \"%s\" is already loaded under different name/path \"%s\" - will return existing soinfo", name, si->name);
        return si;
      }
    }

    if ((dlflags & RTLD_NOLOAD) != 0) {
      return NULL;
    }

    // Read the ELF header and load the segments.
    if (!elf_reader.Load(extinfo)) {
        return NULL;
    }

    // ARC MOD BEGIN
    // SEARCH_NAME() returns the base name for 32-bit platforms.
    // For compatibility, we keep this behavior, and provide library search
    // paths to GDB so that GDB can find the libraries from their base names.
    // See src/build/run_under_gdb.py.
    // ARC MOD END
    soinfo* si = soinfo_alloc(SEARCH_NAME(name), &file_stat);
    if (si == NULL) {
        return NULL;
    }
    si->base = elf_reader.load_start();
    si->size = elf_reader.load_size();
    si->load_bias = elf_reader.load_bias();
    si->phnum = elf_reader.phdr_count();
    si->phdr = elf_reader.loaded_phdr();
    // ARC MOD BEGIN
#if defined(HAVE_ARC)
    // Linux kernel sends the entry point using AT_ENTRY, but sel_ldr
    // does not send this info. Take this occasion and fill the field.
    const ElfW(Ehdr)& header = elf_reader.header();
    if (header.e_entry)
      si->entry = header.e_entry + elf_reader.load_bias();
    if (!si->phdr)
      DL_ERR("Cannot locate a program header in \"%s\".", name);
    // ARC MOD END
    // ARC MOD BEGIN bionic-linker-ndk-detection
    // Set is_ndk appropriately. NDK libraries in APKs are in
    // /data/app-lib/<app-name>.
    const char kNdkLibraryDir[] = "/data/app-lib/";
    si->is_ndk = (is_in_vendor_lib ||
                  !strncmp(name, kNdkLibraryDir, sizeof(kNdkLibraryDir) - 1) ||
                  !strncmp(name, kVendorLibDir, sizeof(kVendorLibDir) - 1));
#endif
    // ARC MOD END

    // At this point we know that whatever is loaded @ base is a valid ELF
    // shared library whose segments are properly mapped in.
    TRACE("[ load_library base=%p size=%zu name='%s' ]",
          reinterpret_cast<void*>(si->base), si->size, si->name);

    // ARC MOD BEGIN
    // Set |somain| and FLAG_EXE for the main binary. They are
    // needed to be set in soinfo_link_image. In the upstream Bionic
    // loader, this is done in __linker_init_post_relocation before
    // soinfo_link_image is called. See the comment for
    // load_main_binary for this difference.
    // Also we fill _r_debug here to insert somain first.
#if defined(HAVE_ARC)
    if (!somain) {
      TRACE("[ Setting %s as somain ]", si->name);
      somain = si;
      somain->flags |= FLAG_EXE;

      link_map* map = &(si->link_map_head);

      map->l_addr = 0;
      map->l_name = const_cast<char*>(name);
      map->l_prev = NULL;
      map->l_next = NULL;

      _r_debug.r_map = map;
      r_debug_tail = map;
    }
#endif
    // ARC MOD END
    if (!soinfo_link_image(si, extinfo)) {
      // ARC MOD BEGIN
      // We do not have the size of data segments so we cannot unmap
      // data segments.
      // TODO(crbug.com/257546): Unmap data segments.
      // ARC MOD END
      soinfo_free(si);
      return NULL;
    }

    return si;
}

static soinfo *find_loaded_library_by_name(const char* name) {
  const char* search_name = SEARCH_NAME(name);
  for (soinfo* si = solist; si != NULL; si = si->next) {
    if (!strcmp(search_name, si->name)) {
      return si;
    }
  }
  return NULL;
}

static soinfo* find_library_internal(const char* name, int dlflags, const android_dlextinfo* extinfo) {
  if (name == NULL) {
    return somain;
  }

  soinfo* si = find_loaded_library_by_name(name);

  // Library might still be loaded, the accurate detection
  // of this fact is done by load_library
  if (si == NULL) {
    TRACE("[ '%s' has not been found by name.  Trying harder...]", name);
    si = load_library(name, dlflags, extinfo);
  }

  if (si != NULL && (si->flags & FLAG_LINKED) == 0) {
    DL_ERR("recursive link to \"%s\"", si->name);
    return NULL;
  }

  return si;
}

static soinfo* find_library(const char* name, int dlflags, const android_dlextinfo* extinfo) {
  soinfo* si = find_library_internal(name, dlflags, extinfo);
  if (si != NULL) {
    si->ref_count++;
  }
  return si;
}

static void soinfo_unload(soinfo* si) {
  if (si->ref_count == 1) {
    TRACE("unloading '%s'", si->name);
    si->CallDestructors();

    if ((si->flags | FLAG_NEW_SOINFO) != 0) {
      si->get_children().for_each([&] (soinfo* child) {
        TRACE("%s needs to unload %s", si->name, child->name);
        soinfo_unload(child);
      });
    } else {
      for (ElfW(Dyn)* d = si->dynamic; d->d_tag != DT_NULL; ++d) {
        if (d->d_tag == DT_NEEDED) {
          const char* library_name = si->strtab + d->d_un.d_val;
          TRACE("%s needs to unload %s", si->name, library_name);
          soinfo* needed = find_library(library_name, RTLD_NOLOAD, NULL);
          if (needed != NULL) {
            soinfo_unload(needed);
          } else {
            // Not found: for example if symlink was deleted between dlopen and dlclose
            // Since we cannot really handle errors at this point - print and continue.
            PRINT("warning: couldn't find %s needed by %s on unload.", library_name, si->name);
          }
        }
      }
    }

    notify_gdb_of_unload(si);
    si->ref_count = 0;
    soinfo_free(si);
  } else {
    si->ref_count--;
    TRACE("not unloading '%s', decrementing ref_count to %zd", si->name, si->ref_count);
  }
}

void do_android_get_LD_LIBRARY_PATH(char* buffer, size_t buffer_size) {
  // Use basic string manipulation calls to avoid snprintf.
  // snprintf indirectly calls pthread_getspecific to get the size of a buffer.
  // When debug malloc is enabled, this call returns 0. This in turn causes
  // snprintf to do nothing, which causes libraries to fail to load.
  // See b/17302493 for further details.
  // Once the above bug is fixed, this code can be modified to use
  // snprintf again.
  size_t required_len = strlen(kDefaultLdPaths[0]) + strlen(kDefaultLdPaths[1]) + 2;
  if (buffer_size < required_len) {
    __libc_fatal("android_get_LD_LIBRARY_PATH failed, buffer too small: buffer len %zu, required len %zu",
                 buffer_size, required_len);
  }
  char* end = stpcpy(buffer, kDefaultLdPaths[0]);
  *end = ':';
  strcpy(end + 1, kDefaultLdPaths[1]);
}

void do_android_update_LD_LIBRARY_PATH(const char* ld_library_path) {
  if (!get_AT_SECURE()) {
    parse_LD_LIBRARY_PATH(ld_library_path);
  }
}

soinfo* do_dlopen(const char* name, int flags, const android_dlextinfo* extinfo) {
  if ((flags & ~(RTLD_NOW|RTLD_LAZY|RTLD_LOCAL|RTLD_GLOBAL|RTLD_NOLOAD)) != 0) {
    DL_ERR("invalid flags to dlopen: %x", flags);
    return NULL;
  }
  if (extinfo != NULL && ((extinfo->flags & ~(ANDROID_DLEXT_VALID_FLAG_BITS)) != 0)) {
    DL_ERR("invalid extended flags to android_dlopen_ext: %" PRIx64, extinfo->flags);
    return NULL;
  }
  protect_data(PROT_READ | PROT_WRITE);
  soinfo* si = find_library(name, flags, extinfo);
  if (si != NULL) {
    si->CallConstructors();
  }
  protect_data(PROT_READ);
  return si;
}

void do_dlclose(soinfo* si) {
  protect_data(PROT_READ | PROT_WRITE);
  soinfo_unload(si);
  protect_data(PROT_READ);
}

#if defined(USE_RELA)
static int soinfo_relocate(soinfo* si, ElfW(Rela)* rela, unsigned count, soinfo* needed[]) {
  // ARC MOD BEGIN
  // Initialize |s| by NULL.
  ElfW(Sym)* s = NULL;
  // ARC MOD END
  // ARC MOD BEGIN
  // Initialize |lsi| by NULL to remove GCC -O2 warnings.
  soinfo* lsi = NULL;
  // ARC MOD END
  for (size_t idx = 0; idx < count; ++idx, ++rela) {
    unsigned type = ELFW(R_TYPE)(rela->r_info);
    unsigned sym = ELFW(R_SYM)(rela->r_info);
    ElfW(Addr) reloc = static_cast<ElfW(Addr)>(rela->r_offset + si->load_bias);
    ElfW(Addr) sym_addr = 0;
    const char* sym_name = NULL;

    DEBUG("Processing '%s' relocation at index %zd", si->name, idx);
    if (type == 0) { // R_*_NONE
      continue;
    }
    if (sym != 0) {
      sym_name = reinterpret_cast<const char*>(si->strtab + si->symtab[sym].st_name);
      // ARC MOD BEGIN bionic-linker-symbol-lookup-order
      // We must not look up local symbols. RESOLVE_MAP in
      // nacl-glibc/elf/dl-reloc.c handles local symbols similarly.
      //
      // We treat all symbols in the Bionic loader as
      // local. When we are relocating the Bionic loader, it
      // cannot use lookup() because libdl_info in dlfcn.c is
      // not relocated yet. Upstream Bionic may not have this
      // issue because it uses RTLD_LOCAL semantics.
      //
      // We also modified code in else clause for ARC. See the
      // comment in the else clause for detail.
      if(ELFW(ST_BIND)(si->symtab[sym].st_info) == STB_LOCAL ||
         // TODO(yusukes): Check if this is still necessary.
         (si->flags & FLAG_LINKER) == FLAG_LINKER) {
        s = &si->symtab[sym];
        lsi = si;
      } else {
#if defined(HAVE_ARC)
        // If |g_resolve_symbol| is injected, try this first.
        if (g_resolve_symbol) {
          sym_addr = reinterpret_cast<ElfW(Addr)>(
              g_resolve_symbol(sym_name));
          if (sym_addr) {
            goto symbol_found;
          }
        }

        // Then look up the symbol following Android's default
        // semantics.
        s = soinfo_do_lookup(si, sym_name, &lsi, needed);
        // When the symbol is not found, we still need to
        // look up the main binary, as we link some shared
        // objects (e.g., liblog.so) into arc.nexe
        // TODO(crbug.com/400947): Remove this code once we have
        // stopped converting .so files to .a.
        if (!s)
          s = soinfo_do_lookup(somain, sym_name, &lsi, needed);
#else
        s = soinfo_do_lookup(si, sym_name, &lsi, needed);
#endif
      }
      // ARC MOD END
      if (s == NULL) {
        // We only allow an undefined symbol if this is a weak reference...
        s = &si->symtab[sym];
        if (ELF_ST_BIND(s->st_info) != STB_WEAK) {
          DL_ERR("cannot locate symbol \"%s\" referenced by \"%s\"...", sym_name, si->name);
          return -1;
        }

        /* IHI0044C AAELF 4.5.1.1:

           Libraries are not searched to resolve weak references.
           It is not an error for a weak reference to remain unsatisfied.

           During linking, the value of an undefined weak reference is:
           - Zero if the relocation type is absolute
           - The address of the place if the relocation is pc-relative
           - The address of nominal base address if the relocation
             type is base-relative.
         */

        switch (type) {
#if defined(__aarch64__)
        case R_AARCH64_JUMP_SLOT:
        case R_AARCH64_GLOB_DAT:
        case R_AARCH64_ABS64:
        case R_AARCH64_ABS32:
        case R_AARCH64_ABS16:
        case R_AARCH64_RELATIVE:
          /*
           * The sym_addr was initialized to be zero above, or the relocation
           * code below does not care about value of sym_addr.
           * No need to do anything.
           */
          break;
#elif defined(__x86_64__)
        case R_X86_64_JUMP_SLOT:
        case R_X86_64_GLOB_DAT:
        case R_X86_64_32:
        case R_X86_64_64:
        case R_X86_64_RELATIVE:
          // No need to do anything.
          break;
        case R_X86_64_PC32:
          sym_addr = reloc;
          break;
#endif
        default:
          DL_ERR("unknown weak reloc type %d @ %p (%zu)", type, rela, idx);
          return -1;
        }
      } else {
        // We got a definition.
        sym_addr = static_cast<ElfW(Addr)>(s->st_value + lsi->load_bias);
      }
      // ARC MOD BEGIN
      // Add symbol_found label.
#if defined(HAVE_ARC)
   symbol_found:
#endif
      // ARC MOD END
      count_relocation(kRelocSymbol);
    } else {
      s = NULL;
    }

    switch (type) {
#if defined(__aarch64__)
    case R_AARCH64_JUMP_SLOT:
        count_relocation(kRelocAbsolute);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO JMP_SLOT %16llx <- %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), sym_name);
        *reinterpret_cast<ElfW(Addr)*>(reloc) = (sym_addr + rela->r_addend);
        break;
    case R_AARCH64_GLOB_DAT:
        count_relocation(kRelocAbsolute);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO GLOB_DAT %16llx <- %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), sym_name);
        *reinterpret_cast<ElfW(Addr)*>(reloc) = (sym_addr + rela->r_addend);
        break;
    case R_AARCH64_ABS64:
        count_relocation(kRelocAbsolute);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO ABS64 %16llx <- %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), sym_name);
        *reinterpret_cast<ElfW(Addr)*>(reloc) += (sym_addr + rela->r_addend);
        break;
    case R_AARCH64_ABS32:
        count_relocation(kRelocAbsolute);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO ABS32 %16llx <- %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), sym_name);
        if ((static_cast<ElfW(Addr)>(INT32_MIN) <= (*reinterpret_cast<ElfW(Addr)*>(reloc) + (sym_addr + rela->r_addend))) &&
            ((*reinterpret_cast<ElfW(Addr)*>(reloc) + (sym_addr + rela->r_addend)) <= static_cast<ElfW(Addr)>(UINT32_MAX))) {
            *reinterpret_cast<ElfW(Addr)*>(reloc) += (sym_addr + rela->r_addend);
        } else {
            DL_ERR("0x%016llx out of range 0x%016llx to 0x%016llx",
                   (*reinterpret_cast<ElfW(Addr)*>(reloc) + (sym_addr + rela->r_addend)),
                   static_cast<ElfW(Addr)>(INT32_MIN),
                   static_cast<ElfW(Addr)>(UINT32_MAX));
            return -1;
        }
        break;
    case R_AARCH64_ABS16:
        count_relocation(kRelocAbsolute);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO ABS16 %16llx <- %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), sym_name);
        if ((static_cast<ElfW(Addr)>(INT16_MIN) <= (*reinterpret_cast<ElfW(Addr)*>(reloc) + (sym_addr + rela->r_addend))) &&
            ((*reinterpret_cast<ElfW(Addr)*>(reloc) + (sym_addr + rela->r_addend)) <= static_cast<ElfW(Addr)>(UINT16_MAX))) {
            *reinterpret_cast<ElfW(Addr)*>(reloc) += (sym_addr + rela->r_addend);
        } else {
            DL_ERR("0x%016llx out of range 0x%016llx to 0x%016llx",
                   (*reinterpret_cast<ElfW(Addr)*>(reloc) + (sym_addr + rela->r_addend)),
                   static_cast<ElfW(Addr)>(INT16_MIN),
                   static_cast<ElfW(Addr)>(UINT16_MAX));
            return -1;
        }
        break;
    case R_AARCH64_PREL64:
        count_relocation(kRelocRelative);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO REL64 %16llx <- %16llx - %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), rela->r_offset, sym_name);
        *reinterpret_cast<ElfW(Addr)*>(reloc) += (sym_addr + rela->r_addend) - rela->r_offset;
        break;
    case R_AARCH64_PREL32:
        count_relocation(kRelocRelative);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO REL32 %16llx <- %16llx - %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), rela->r_offset, sym_name);
        if ((static_cast<ElfW(Addr)>(INT32_MIN) <= (*reinterpret_cast<ElfW(Addr)*>(reloc) + ((sym_addr + rela->r_addend) - rela->r_offset))) &&
            ((*reinterpret_cast<ElfW(Addr)*>(reloc) + ((sym_addr + rela->r_addend) - rela->r_offset)) <= static_cast<ElfW(Addr)>(UINT32_MAX))) {
            *reinterpret_cast<ElfW(Addr)*>(reloc) += ((sym_addr + rela->r_addend) - rela->r_offset);
        } else {
            DL_ERR("0x%016llx out of range 0x%016llx to 0x%016llx",
                   (*reinterpret_cast<ElfW(Addr)*>(reloc) + ((sym_addr + rela->r_addend) - rela->r_offset)),
                   static_cast<ElfW(Addr)>(INT32_MIN),
                   static_cast<ElfW(Addr)>(UINT32_MAX));
            return -1;
        }
        break;
    case R_AARCH64_PREL16:
        count_relocation(kRelocRelative);
        MARK(rela->r_offset);
        TRACE_TYPE(RELO, "RELO REL16 %16llx <- %16llx - %16llx %s\n",
                   reloc, (sym_addr + rela->r_addend), rela->r_offset, sym_name);
        if ((static_cast<ElfW(Addr)>(INT16_MIN) <= (*reinterpret_cast<ElfW(Addr)*>(reloc) + ((sym_addr + rela->r_addend) - rela->r_offset))) &&
            ((*reinterpret_cast<ElfW(Addr)*>(reloc) + ((sym_addr + rela->r_addend) - rela->r_offset)) <= static_cast<ElfW(Addr)>(UINT16_MAX))) {
            *reinterpret_cast<ElfW(Addr)*>(reloc) += ((sym_addr + rela->r_addend) - rela->r_offset);
        } else {
            DL_ERR("0x%016llx out of range 0x%016llx to 0x%016llx",
                   (*reinterpret_cast<ElfW(Addr)*>(reloc) + ((sym_addr + rela->r_addend) - rela->r_offset)),
                   static_cast<ElfW(Addr)>(INT16_MIN),
                   static_cast<ElfW(Addr)>(UINT16_MAX));
            return -1;
        }
        break;

    case R_AARCH64_RELATIVE:
        count_relocation(kRelocRelative);
        MARK(rela->r_offset);
        if (sym) {
            DL_ERR("odd RELATIVE form...");
            return -1;
        }
        TRACE_TYPE(RELO, "RELO RELATIVE %16llx <- %16llx\n",
                   reloc, (si->base + rela->r_addend));
        *reinterpret_cast<ElfW(Addr)*>(reloc) = (si->base + rela->r_addend);
        break;

    case R_AARCH64_COPY:
        /*
         * ET_EXEC is not supported so this should not happen.
         *
         * http://infocenter.arm.com/help/topic/com.arm.doc.ihi0044d/IHI0044D_aaelf.pdf
         *
         * Section 4.7.1.10 "Dynamic relocations"
         * R_AARCH64_COPY may only appear in executable objects where e_type is
         * set to ET_EXEC.
         */
        DL_ERR("%s R_AARCH64_COPY relocations are not supported", si->name);
        return -1;
    case R_AARCH64_TLS_TPREL64:
        TRACE_TYPE(RELO, "RELO TLS_TPREL64 *** %16llx <- %16llx - %16llx\n",
                   reloc, (sym_addr + rela->r_addend), rela->r_offset);
        break;
    case R_AARCH64_TLS_DTPREL32:
        TRACE_TYPE(RELO, "RELO TLS_DTPREL32 *** %16llx <- %16llx - %16llx\n",
                   reloc, (sym_addr + rela->r_addend), rela->r_offset);
        break;
#elif defined(__x86_64__)
    case R_X86_64_JUMP_SLOT:
      count_relocation(kRelocAbsolute);
      MARK(rela->r_offset);
      TRACE_TYPE(RELO, "RELO JMP_SLOT %08zx <- %08zx %s", static_cast<size_t>(reloc),
                 static_cast<size_t>(sym_addr + rela->r_addend), sym_name);
      *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr + rela->r_addend;
      break;
    case R_X86_64_GLOB_DAT:
      count_relocation(kRelocAbsolute);
      MARK(rela->r_offset);
      TRACE_TYPE(RELO, "RELO GLOB_DAT %08zx <- %08zx %s", static_cast<size_t>(reloc),
                 static_cast<size_t>(sym_addr + rela->r_addend), sym_name);
      *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr + rela->r_addend;
      break;
    case R_X86_64_RELATIVE:
      count_relocation(kRelocRelative);
      MARK(rela->r_offset);
      if (sym) {
        DL_ERR("odd RELATIVE form...");
        return -1;
      }
      TRACE_TYPE(RELO, "RELO RELATIVE %08zx <- +%08zx", static_cast<size_t>(reloc),
                 static_cast<size_t>(si->base));
      *reinterpret_cast<ElfW(Addr)*>(reloc) = si->base + rela->r_addend;
      break;
    case R_X86_64_32:
      count_relocation(kRelocRelative);
      MARK(rela->r_offset);
      TRACE_TYPE(RELO, "RELO R_X86_64_32 %08zx <- +%08zx %s", static_cast<size_t>(reloc),
                 static_cast<size_t>(sym_addr), sym_name);
      // ARC MOD BEGIN UPSTREAM bionic-x86-64-32bit-relocation
      // R_X86_64_32 writes a 32 bit address value to memory instead
      // of 64 bit (ElfW(Addr)).
      *reinterpret_cast<Elf32_Addr*>(reloc) = sym_addr + rela->r_addend;
      // ARC MOD END UPSTREAM
      break;
    case R_X86_64_64:
      count_relocation(kRelocRelative);
      MARK(rela->r_offset);
      TRACE_TYPE(RELO, "RELO R_X86_64_64 %08zx <- +%08zx %s", static_cast<size_t>(reloc),
                 static_cast<size_t>(sym_addr), sym_name);
      *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr + rela->r_addend;
      break;
    case R_X86_64_PC32:
      count_relocation(kRelocRelative);
      MARK(rela->r_offset);
      TRACE_TYPE(RELO, "RELO R_X86_64_PC32 %08zx <- +%08zx (%08zx - %08zx) %s",
                 static_cast<size_t>(reloc), static_cast<size_t>(sym_addr - reloc),
                 static_cast<size_t>(sym_addr), static_cast<size_t>(reloc), sym_name);
      // ARC MOD BEGIN UPSTREAM bionic-x86-64-32bit-relocation
      // R_X86_64_PC32 writes a 32 bit address value to memory instead
      // of 64 bit (ElfW(Addr)).
      *reinterpret_cast<Elf32_Addr*>(reloc) = sym_addr + rela->r_addend - reloc;
      // ARC MOD END UPSTREAM
      break;
#endif

    default:
      DL_ERR("unknown reloc type %d @ %p (%zu)", type, rela, idx);
      return -1;
    }
  }
  return 0;
}

#else // REL, not RELA.

static int soinfo_relocate(soinfo* si, ElfW(Rel)* rel, unsigned count, soinfo* needed[]) {
    // ARC MOD BEGIN
    // Initialize |s| by NULL.
    ElfW(Sym)* s = NULL;
    // ARC MOD END
    // ARC MOD BEGIN
    // Initialize |lsi| by NULL to remove GCC -O2 warnings.
    soinfo* lsi = NULL;
    // ARC MOD END

    for (size_t idx = 0; idx < count; ++idx, ++rel) {
        unsigned type = ELFW(R_TYPE)(rel->r_info);
        // TODO: don't use unsigned for 'sym'. Use uint32_t or ElfW(Addr) instead.
        unsigned sym = ELFW(R_SYM)(rel->r_info);
        ElfW(Addr) reloc = static_cast<ElfW(Addr)>(rel->r_offset + si->load_bias);
        ElfW(Addr) sym_addr = 0;
        const char* sym_name = NULL;

        DEBUG("Processing '%s' relocation at index %zd", si->name, idx);
        if (type == 0) { // R_*_NONE
            continue;
        }
        if (sym != 0) {
            sym_name = reinterpret_cast<const char*>(si->strtab + si->symtab[sym].st_name);
            // ARC MOD BEGIN
            // We must not look up local symbols. RESOLVE_MAP in
            // nacl-glibc/elf/dl-reloc.c handles local symbols similarly.
            //
            // We treat all symbols in the Bionic loader as
            // local. When we are relocating the Bionic loader, it
            // cannot use lookup() because libdl_info in dlfcn.c is
            // not relocated yet. Upstream Bionic may not have this
            // issue because it uses RTLD_LOCAL semantics.
            //
            // We also modified code in else clause for ARC. See the
            // comment in the else clause for detail.
            if(ELFW(ST_BIND)(si->symtab[sym].st_info) == STB_LOCAL ||
               // TODO(yusukes): Check if this is still necessary.
               (si->flags & FLAG_LINKER) == FLAG_LINKER) {
              s = &si->symtab[sym];
              lsi = si;
            } else {
#if defined(HAVE_ARC)
              // If |g_resolve_symbol| is injected, try this first for NDK.
              if (si->is_ndk && g_resolve_symbol) {
                  sym_addr = reinterpret_cast<Elf32_Addr>(
                      g_resolve_symbol(sym_name));
                  if (sym_addr) {
                      goto symbol_found;
                  }
              }
              // ARC MOD END
              // ARC MOD BEGIN
              // Then look up the symbol following Android's default
              // semantics.
              s = soinfo_do_lookup(si, sym_name, &lsi, needed);
              // When the symbol is not found, we still need to
              // look up the main binary, as we link some shared
              // objects (e.g., liblog.so) into arc.nexe
              // TODO(crbug.com/400947): Remove this code once we have
              // stopped converting .so files to .a.
              if (!s)
                  s = soinfo_do_lookup(somain, sym_name, &lsi, needed);
#else
              s = soinfo_do_lookup(si, sym_name, &lsi, needed);
#endif
            }
            // ARC MOD END
            if (s == NULL) {
                // We only allow an undefined symbol if this is a weak reference...
                s = &si->symtab[sym];
                if (ELF_ST_BIND(s->st_info) != STB_WEAK) {
                    DL_ERR("cannot locate symbol \"%s\" referenced by \"%s\"...", sym_name, si->name);
                    return -1;
                }

                /* IHI0044C AAELF 4.5.1.1:

                   Libraries are not searched to resolve weak references.
                   It is not an error for a weak reference to remain
                   unsatisfied.

                   During linking, the value of an undefined weak reference is:
                   - Zero if the relocation type is absolute
                   - The address of the place if the relocation is pc-relative
                   - The address of nominal base address if the relocation
                     type is base-relative.
                  */

                switch (type) {
#if defined(__arm__)
                case R_ARM_JUMP_SLOT:
                case R_ARM_GLOB_DAT:
                case R_ARM_ABS32:
                case R_ARM_RELATIVE:    /* Don't care. */
                    // sym_addr was initialized to be zero above or relocation
                    // code below does not care about value of sym_addr.
                    // No need to do anything.
                    break;
#elif defined(__i386__)
                case R_386_JMP_SLOT:
                case R_386_GLOB_DAT:
                case R_386_32:
                case R_386_RELATIVE:    /* Don't care. */
                    // sym_addr was initialized to be zero above or relocation
                    // code below does not care about value of sym_addr.
                    // No need to do anything.
                    break;
                case R_386_PC32:
                    sym_addr = reloc;
                    break;
#endif

#if defined(__arm__)
                case R_ARM_COPY:
                    // Fall through. Can't really copy if weak symbol is not found at run-time.
#endif
                default:
                    DL_ERR("unknown weak reloc type %d @ %p (%zu)", type, rel, idx);
                    return -1;
                }
            } else {
                // We got a definition.
                sym_addr = static_cast<ElfW(Addr)>(s->st_value + lsi->load_bias);
            }
            // ARC MOD BEGIN
            // Add symbol_found label.
#if defined(HAVE_ARC)
        symbol_found:
#endif
            // ARC MOD END
            count_relocation(kRelocSymbol);
        } else {
            s = NULL;
        }

        switch (type) {
#if defined(__arm__)
        case R_ARM_JUMP_SLOT:
            count_relocation(kRelocAbsolute);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO JMP_SLOT %08x <- %08x %s", reloc, sym_addr, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr;
            break;
        case R_ARM_GLOB_DAT:
            count_relocation(kRelocAbsolute);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO GLOB_DAT %08x <- %08x %s", reloc, sym_addr, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr;
            break;
        case R_ARM_ABS32:
            count_relocation(kRelocAbsolute);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO ABS %08x <- %08x %s", reloc, sym_addr, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) += sym_addr;
            break;
        case R_ARM_REL32:
            count_relocation(kRelocRelative);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO REL32 %08x <- %08x - %08x %s",
                       reloc, sym_addr, rel->r_offset, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) += sym_addr - rel->r_offset;
            break;
        case R_ARM_COPY:
            /*
             * ET_EXEC is not supported so this should not happen.
             *
             * http://infocenter.arm.com/help/topic/com.arm.doc.ihi0044d/IHI0044D_aaelf.pdf
             *
             * Section 4.7.1.10 "Dynamic relocations"
             * R_ARM_COPY may only appear in executable objects where e_type is
             * set to ET_EXEC.
             */
            DL_ERR("%s R_ARM_COPY relocations are not supported", si->name);
            return -1;
#elif defined(__i386__)
        case R_386_JMP_SLOT:
            count_relocation(kRelocAbsolute);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO JMP_SLOT %08x <- %08x %s", reloc, sym_addr, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr;
            break;
        case R_386_GLOB_DAT:
            count_relocation(kRelocAbsolute);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO GLOB_DAT %08x <- %08x %s", reloc, sym_addr, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) = sym_addr;
            break;
        case R_386_32:
            count_relocation(kRelocRelative);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO R_386_32 %08x <- +%08x %s", reloc, sym_addr, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) += sym_addr;
            break;
        case R_386_PC32:
            count_relocation(kRelocRelative);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO R_386_PC32 %08x <- +%08x (%08x - %08x) %s",
                       reloc, (sym_addr - reloc), sym_addr, reloc, sym_name);
            *reinterpret_cast<ElfW(Addr)*>(reloc) += (sym_addr - reloc);
            break;
#elif defined(__mips__)
        case R_MIPS_REL32:
#if defined(__LP64__)
            // MIPS Elf64_Rel entries contain compound relocations
            // We only handle the R_MIPS_NONE|R_MIPS_64|R_MIPS_REL32 case
            if (ELF64_R_TYPE2(rel->r_info) != R_MIPS_64 ||
                ELF64_R_TYPE3(rel->r_info) != R_MIPS_NONE) {
                DL_ERR("Unexpected compound relocation type:%d type2:%d type3:%d @ %p (%zu)",
                       type, (unsigned)ELF64_R_TYPE2(rel->r_info),
                       (unsigned)ELF64_R_TYPE3(rel->r_info), rel, idx);
                return -1;
            }
#endif
            count_relocation(kRelocAbsolute);
            MARK(rel->r_offset);
            TRACE_TYPE(RELO, "RELO REL32 %08zx <- %08zx %s", static_cast<size_t>(reloc),
                       static_cast<size_t>(sym_addr), sym_name ? sym_name : "*SECTIONHDR*");
            if (s) {
                *reinterpret_cast<ElfW(Addr)*>(reloc) += sym_addr;
            } else {
                *reinterpret_cast<ElfW(Addr)*>(reloc) += si->base;
            }
            break;
#endif

#if defined(__arm__)
        case R_ARM_RELATIVE:
#elif defined(__i386__)
        case R_386_RELATIVE:
#endif
            count_relocation(kRelocRelative);
            MARK(rel->r_offset);
            if (sym) {
                DL_ERR("odd RELATIVE form...");
                return -1;
            }
            TRACE_TYPE(RELO, "RELO RELATIVE %p <- +%p",
                       reinterpret_cast<void*>(reloc), reinterpret_cast<void*>(si->base));
            *reinterpret_cast<ElfW(Addr)*>(reloc) += si->base;
            break;

        default:
            DL_ERR("unknown reloc type %d @ %p (%zu)", type, rel, idx);
            return -1;
        }
    }
    return 0;
}
#endif

// ARC MOD BEGIN
// Add __inject_arc_linker_hooks and nacl_irt_open_resource_invalid.
static int nacl_irt_open_resource_invalid(const char* name, int* fd) {
  DL_ERR("We must not call __nacl_irt_open_resource after "
         "__inject_arc_linker_hooks: name=%s", name);
  exit(1);
}

void __inject_arc_linker_hooks(__arc_linker_hooks* hooks) {
  // TODO(crbug.com/427212): Stop using the injected functions for
  // non-NDK shared objects loaded by dlopen.
  if (g_resolve_symbol) {
    DL_ERR("The linker hooks are already installed.");
    exit(-1);
  }
  if (!hooks->nacl_irt_close ||
      !hooks->nacl_irt_mmap ||
      !hooks->nacl_irt_munmap ||
      !hooks->nacl_irt_open ||
      !hooks->nacl_irt_read ||
      !hooks->nacl_irt_write ||
      !hooks->nacl_irt_fstat ||
      !hooks->resolve_symbol) {
    DL_ERR("All fields in hooks must be filled.");
    exit(-1);
  }

  g_resolve_symbol = hooks->resolve_symbol;
  g_is_statically_linked = hooks->is_statically_linked;
  __nacl_irt_close = hooks->nacl_irt_close;
  __nacl_irt_mmap = hooks->nacl_irt_mmap;
  __nacl_irt_munmap = hooks->nacl_irt_munmap;
  __nacl_irt_open = hooks->nacl_irt_open;
  __nacl_irt_read = hooks->nacl_irt_read;
  __nacl_irt_write = hooks->nacl_irt_write;
  __nacl_irt_fstat = hooks->nacl_irt_fstat;
  // We will not call __nacl_irt_open_resource in the Bionic loader
  // after this not to mix NaCl FD with posix_translation FD.
  __nacl_irt_open_resource = nacl_irt_open_resource_invalid;
}
// ARC MOD END
#if defined(__mips__)
static bool mips_relocate_got(soinfo* si, soinfo* needed[]) {
    ElfW(Addr)** got = si->plt_got;
    if (got == NULL) {
        return true;
    }
    unsigned local_gotno = si->mips_local_gotno;
    unsigned gotsym = si->mips_gotsym;
    unsigned symtabno = si->mips_symtabno;
    ElfW(Sym)* symtab = si->symtab;

    // got[0] is the address of the lazy resolver function.
    // got[1] may be used for a GNU extension.
    // Set it to a recognizable address in case someone calls it (should be _rtld_bind_start).
    // FIXME: maybe this should be in a separate routine?
    if ((si->flags & FLAG_LINKER) == 0) {
        size_t g = 0;
        got[g++] = reinterpret_cast<ElfW(Addr)*>(0xdeadbeef);
        if (reinterpret_cast<intptr_t>(got[g]) < 0) {
            got[g++] = reinterpret_cast<ElfW(Addr)*>(0xdeadfeed);
        }
        // Relocate the local GOT entries.
        for (; g < local_gotno; g++) {
            got[g] = reinterpret_cast<ElfW(Addr)*>(reinterpret_cast<uintptr_t>(got[g]) + si->load_bias);
        }
    }

    // Now for the global GOT entries...
    ElfW(Sym)* sym = symtab + gotsym;
    got = si->plt_got + local_gotno;
    for (size_t g = gotsym; g < symtabno; g++, sym++, got++) {
        // This is an undefined reference... try to locate it.
        const char* sym_name = si->strtab + sym->st_name;
        soinfo* lsi;
        ElfW(Sym)* s = soinfo_do_lookup(si, sym_name, &lsi, needed);
        if (s == NULL) {
            // We only allow an undefined symbol if this is a weak reference.
            s = &symtab[g];
            if (ELF_ST_BIND(s->st_info) != STB_WEAK) {
                DL_ERR("cannot locate \"%s\"...", sym_name);
                return false;
            }
            *got = 0;
        } else {
            // FIXME: is this sufficient?
            // For reference see NetBSD link loader
            // http://cvsweb.netbsd.org/bsdweb.cgi/src/libexec/ld.elf_so/arch/mips/mips_reloc.c?rev=1.53&content-type=text/x-cvsweb-markup
            *got = reinterpret_cast<ElfW(Addr)*>(lsi->load_bias + s->st_value);
        }
    }
    return true;
}
#endif

void soinfo::CallArray(const char* array_name __unused, linker_function_t* functions, size_t count, bool reverse) {
  if (functions == NULL) {
    return;
  }

  TRACE("[ Calling %s (size %zd) @ %p for '%s' ]", array_name, count, functions, name);

  int begin = reverse ? (count - 1) : 0;
  int end = reverse ? -1 : count;
  int step = reverse ? -1 : 1;

  for (int i = begin; i != end; i += step) {
    TRACE("[ %s[%d] == %p ]", array_name, i, functions[i]);
    // ARC MOD BEGIN
    // The loader passes __nacl_irt_query to the main executable
    // using the function in init_array of libc.so. The loader
    // does this only for the function immediately after the magic
    // number. Currently, init_array is used only on ARM. We use
    // .init in other platforms. See bionic/linker/linker.h for
    // why we need to pass __nacl_irt_query in this way.
    if (!reverse && functions[i] == NEXT_CTOR_FUNC_NEEDS_IRT_QUERY_MARKER) {
      TRACE("[ Calling func @ 0x%08x with __nacl_irt_query]\n",
            (unsigned)functions[i + 1]);
      ((void (*)(__nacl_irt_query_fn_t))functions[++i])(__nacl_irt_query);
    } else
    // ARC MOD END
    CallFunction("function", functions[i]);
  }

  TRACE("[ Done calling %s for '%s' ]", array_name, name);
}

void soinfo::CallFunction(const char* function_name __unused, linker_function_t function) {
  if (function == NULL || reinterpret_cast<uintptr_t>(function) == static_cast<uintptr_t>(-1)) {
    return;
  }

  TRACE("[ Calling %s @ %p for '%s' ]", function_name, function, name);
  function();
  TRACE("[ Done calling %s @ %p for '%s' ]", function_name, function, name);

  // The function may have called dlopen(3) or dlclose(3), so we need to ensure our data structures
  // are still writable. This happens with our debug malloc (see http://b/7941716).
  protect_data(PROT_READ | PROT_WRITE);
}

void soinfo::CallPreInitConstructors() {
  // DT_PREINIT_ARRAY functions are called before any other constructors for executables,
  // but ignored in a shared library.
  CallArray("DT_PREINIT_ARRAY", preinit_array, preinit_array_count, false);
}

void soinfo::CallConstructors() {
  if (constructors_called) {
    return;
  }

  // We set constructors_called before actually calling the constructors, otherwise it doesn't
  // protect against recursive constructor calls. One simple example of constructor recursion
  // is the libc debug malloc, which is implemented in libc_malloc_debug_leak.so:
  // 1. The program depends on libc, so libc's constructor is called here.
  // 2. The libc constructor calls dlopen() to load libc_malloc_debug_leak.so.
  // 3. dlopen() calls the constructors on the newly created
  //    soinfo for libc_malloc_debug_leak.so.
  // 4. The debug .so depends on libc, so CallConstructors is
  //    called again with the libc soinfo. If it doesn't trigger the early-
  //    out above, the libc constructor will be called again (recursively!).
  constructors_called = true;

  // ARC MOD BEGIN
  // Print the elapsed time for calling init functions.
  ScopedElapsedTimePrinter<__LINE__> printer("Called constructors for", name);
  // ARC MOD END
  if ((flags & FLAG_EXE) == 0 && preinit_array != NULL) {
    // The GNU dynamic linker silently ignores these, but we warn the developer.
    PRINT("\"%s\": ignoring %zd-entry DT_PREINIT_ARRAY in shared library!",
          name, preinit_array_count);
  }

  get_children().for_each([] (soinfo* si) {
    // ARC MOD BEGIN
    // We may not be able to find DT_NEEDED specified by NDK's
    // shared objects, because ARC links a lot of libraries to
    // the main binary. For example, NDK apps may have DT_NEEDED
    // which expects libz.so exists, but ARC does not have
    // libz.so. We build libz.a and link it to the main binary.
    //
    // For such DT_NEEDED in NDK objects, find_loaded_library()
    // may return NULL. We must not try calling CallConstructors()
    // for them.
    //
    // TODO(crbug.com/414569): L-rebase: Is this necessary or sufficient ?
#if defined(HAVE_ARC)
    if (si)
#endif
    // ARC MOD END
    si->CallConstructors();
  });

  TRACE("\"%s\": calling constructors", name);

  // DT_INIT should be called before DT_INIT_ARRAY if both are present.
  // ARC MOD BEGIN
#if defined(HAVE_ARC)
  // The loader passes __nacl_irt_query to the main executable
  // here. See bionic/linker/linker.h for detail.
  if (init_func != NULL &&
      reinterpret_cast<uintptr_t>(init_func) != static_cast<uintptr_t>(-1)) {
    // Show trace logs as CallFunction does.
    TRACE("[ Calling DT_INIT @ %p for '%s' ]", init_func, name);
    init_func(__nacl_irt_query);
    TRACE("[ Done calling DT_INIT @ %p for '%s' ]", init_func, name);
    protect_data(PROT_READ | PROT_WRITE);
  }
#else
  // ARC MOD END
  CallFunction("DT_INIT", init_func);
  // ARC MOD BEGIN
#endif
  // ARC MOD END
  CallArray("DT_INIT_ARRAY", init_array, init_array_count, false);
}

void soinfo::CallDestructors() {
  TRACE("\"%s\": calling destructors", name);

  // DT_FINI_ARRAY must be parsed in reverse order.
  CallArray("DT_FINI_ARRAY", fini_array, fini_array_count, true);

  // DT_FINI should be called after DT_FINI_ARRAY if both are present.
  CallFunction("DT_FINI", fini_func);

  // This is needed on second call to dlopen
  // after library has been unloaded with RTLD_NODELETE
  constructors_called = false;
}

void soinfo::add_child(soinfo* child) {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return;
  }

  this->children.push_front(child);
  child->parents.push_front(this);
}

void soinfo::remove_all_links() {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return;
  }

  // 1. Untie connected soinfos from 'this'.
  children.for_each([&] (soinfo* child) {
    child->parents.remove_if([&] (const soinfo* parent) {
      return parent == this;
    });
  });

  parents.for_each([&] (soinfo* parent) {
    parent->children.for_each([&] (const soinfo* child) {
      return child == this;
    });
  });

  // 2. Once everything untied - clear local lists.
  parents.clear();
  children.clear();
}

void soinfo::set_st_dev(dev_t dev) {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return;
  }

  st_dev = dev;
}

void soinfo::set_st_ino(ino_t ino) {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return;
  }

  st_ino = ino;
}

dev_t soinfo::get_st_dev() {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return 0;
  }

  return st_dev;
};

ino_t soinfo::get_st_ino() {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return 0;
  }

  return st_ino;
}

// This is a return on get_children() in case
// 'this->flags' does not have FLAG_NEW_SOINFO set.
static soinfo::soinfo_list_t g_empty_list;

soinfo::soinfo_list_t& soinfo::get_children() {
  if ((this->flags & FLAG_NEW_SOINFO) == 0) {
    return g_empty_list;
  }

  return this->children;
}

/* Force any of the closed stdin, stdout and stderr to be associated with
   /dev/null. */
static int nullify_closed_stdio() {
    int dev_null, i, status;
    int return_value = 0;

    dev_null = TEMP_FAILURE_RETRY(open("/dev/null", O_RDWR));
    if (dev_null < 0) {
        DL_ERR("cannot open /dev/null: %s", strerror(errno));
        return -1;
    }
    TRACE("[ Opened /dev/null file-descriptor=%d]", dev_null);

    /* If any of the stdio file descriptors is valid and not associated
       with /dev/null, dup /dev/null to it.  */
    for (i = 0; i < 3; i++) {
        /* If it is /dev/null already, we are done. */
        if (i == dev_null) {
            continue;
        }

        TRACE("[ Nullifying stdio file descriptor %d]", i);
        status = TEMP_FAILURE_RETRY(fcntl(i, F_GETFL));

        /* If file is opened, we are good. */
        if (status != -1) {
            continue;
        }

        /* The only error we allow is that the file descriptor does not
           exist, in which case we dup /dev/null to it. */
        if (errno != EBADF) {
            DL_ERR("fcntl failed: %s", strerror(errno));
            return_value = -1;
            continue;
        }

        /* Try dupping /dev/null to this stdio file descriptor and
           repeat if there is a signal.  Note that any errors in closing
           the stdio descriptor are lost.  */
        status = TEMP_FAILURE_RETRY(dup2(dev_null, i));
        if (status < 0) {
            DL_ERR("dup2 failed: %s", strerror(errno));
            return_value = -1;
            continue;
        }
    }

    /* If /dev/null is not one of the stdio file descriptors, close it. */
    if (dev_null > 2) {
        TRACE("[ Closing /dev/null file-descriptor=%d]", dev_null);
        status = TEMP_FAILURE_RETRY(close(dev_null));
        if (status == -1) {
            DL_ERR("close failed: %s", strerror(errno));
            return_value = -1;
        }
    }

    return return_value;
}

static bool soinfo_link_image(soinfo* si, const android_dlextinfo* extinfo) {
    /* "base" might wrap around UINT32_MAX. */
    ElfW(Addr) base = si->load_bias;
    const ElfW(Phdr)* phdr = si->phdr;
    int phnum = si->phnum;
    bool relocating_linker = (si->flags & FLAG_LINKER) != 0;

    /* We can't debug anything until the linker is relocated */
    if (!relocating_linker) {
        INFO("[ linking %s ]", si->name);
        DEBUG("si->base = %p si->flags = 0x%08x", reinterpret_cast<void*>(si->base), si->flags);
    }

    /* Extract dynamic section */
    size_t dynamic_count;
    ElfW(Word) dynamic_flags;
    phdr_table_get_dynamic_section(phdr, phnum, base, &si->dynamic,
                                   &dynamic_count, &dynamic_flags);
    if (si->dynamic == NULL) {
        if (!relocating_linker) {
            DL_ERR("missing PT_DYNAMIC in \"%s\"", si->name);
        }
        return false;
    } else {
        if (!relocating_linker) {
            DEBUG("dynamic = %p", si->dynamic);
        }
    }
    // ARC MOD BEGIN UPSTREAM bionic-set-l_ld-in-main-binary
    if (si->flags & FLAG_EXE)
        si->link_map_head.l_ld = reinterpret_cast<ElfW(Dyn)*>(si->dynamic);
    // ARC MOD END UPSTREAM

#if defined(__arm__)
    (void) phdr_table_get_arm_exidx(phdr, phnum, base,
                                    &si->ARM_exidx, &si->ARM_exidx_count);
#endif

    // Extract useful information from dynamic section.
    uint32_t needed_count = 0;
    for (ElfW(Dyn)* d = si->dynamic; d->d_tag != DT_NULL; ++d) {
        DEBUG("d = %p, d[0](tag) = %p d[1](val) = %p",
              d, reinterpret_cast<void*>(d->d_tag), reinterpret_cast<void*>(d->d_un.d_val));
        switch (d->d_tag) {
        case DT_HASH:
            si->nbucket = reinterpret_cast<uint32_t*>(base + d->d_un.d_ptr)[0];
            si->nchain = reinterpret_cast<uint32_t*>(base + d->d_un.d_ptr)[1];
            si->bucket = reinterpret_cast<uint32_t*>(base + d->d_un.d_ptr + 8);
            si->chain = reinterpret_cast<uint32_t*>(base + d->d_un.d_ptr + 8 + si->nbucket * 4);
            break;
        case DT_STRTAB:
            si->strtab = reinterpret_cast<const char*>(base + d->d_un.d_ptr);
            break;
        case DT_SYMTAB:
            si->symtab = reinterpret_cast<ElfW(Sym)*>(base + d->d_un.d_ptr);
            break;
#if !defined(__LP64__)
        case DT_PLTREL:
            // ARC MOD BEGIN
            // NaCl x86-64 uses ELF64 so we should expect Elf64_Rela.
#if defined(__native_client__) && defined(__x86_64__)
            if (d->d_un.d_val != DT_RELA) {
                DL_ERR("unsupported DT_REL in \"%s\"", si->name);
                return false;
            }
#else
            // ARC MOD END
            if (d->d_un.d_val != DT_REL) {
                DL_ERR("unsupported DT_RELA in \"%s\"", si->name);
                return false;
            }
            // ARC MOD BEGIN
#endif
            // ARC MOD END
            break;
#endif
        case DT_JMPREL:
#if defined(USE_RELA)
            si->plt_rela = reinterpret_cast<ElfW(Rela)*>(base + d->d_un.d_ptr);
#else
            si->plt_rel = reinterpret_cast<ElfW(Rel)*>(base + d->d_un.d_ptr);
#endif
            break;
        case DT_PLTRELSZ:
#if defined(USE_RELA)
            si->plt_rela_count = d->d_un.d_val / sizeof(ElfW(Rela));
#else
            si->plt_rel_count = d->d_un.d_val / sizeof(ElfW(Rel));
#endif
            break;
#if defined(__mips__)
        case DT_PLTGOT:
            // Used by mips and mips64.
            si->plt_got = reinterpret_cast<ElfW(Addr)**>(base + d->d_un.d_ptr);
            break;
#endif
        case DT_DEBUG:
            // Set the DT_DEBUG entry to the address of _r_debug for GDB
            // if the dynamic table is writable
// FIXME: not working currently for N64
// The flags for the LOAD and DYNAMIC program headers do not agree.
// The LOAD section containng the dynamic table has been mapped as
// read-only, but the DYNAMIC header claims it is writable.
#if !(defined(__mips__) && defined(__LP64__))
            if ((dynamic_flags & PF_W) != 0) {
                d->d_un.d_val = reinterpret_cast<uintptr_t>(&_r_debug);
            }
            break;
#endif
#if defined(USE_RELA)
         case DT_RELA:
            si->rela = reinterpret_cast<ElfW(Rela)*>(base + d->d_un.d_ptr);
            break;
         case DT_RELASZ:
            si->rela_count = d->d_un.d_val / sizeof(ElfW(Rela));
            break;
        case DT_REL:
            DL_ERR("unsupported DT_REL in \"%s\"", si->name);
            return false;
        case DT_RELSZ:
            DL_ERR("unsupported DT_RELSZ in \"%s\"", si->name);
            return false;
#else
        case DT_REL:
            si->rel = reinterpret_cast<ElfW(Rel)*>(base + d->d_un.d_ptr);
            break;
        case DT_RELSZ:
            si->rel_count = d->d_un.d_val / sizeof(ElfW(Rel));
            break;
         case DT_RELA:
            DL_ERR("unsupported DT_RELA in \"%s\"", si->name);
            return false;
#endif
        case DT_INIT:
            // ARC MOD BEGIN
            // The type of si->init_func was changed. See
            // bionic/linker/linker.h for detail.
#if defined(HAVE_ARC)
            si->init_func = (void (*)(__nacl_irt_query_fn_t))(base + d->d_un.d_ptr);
#else
            // ARC MOD END
            si->init_func = reinterpret_cast<linker_function_t>(base + d->d_un.d_ptr);
            // ARC MOD BEGIN
#endif
            // ARC MOD END
            DEBUG("%s constructors (DT_INIT) found at %p", si->name, si->init_func);
            break;
        case DT_FINI:
            si->fini_func = reinterpret_cast<linker_function_t>(base + d->d_un.d_ptr);
            DEBUG("%s destructors (DT_FINI) found at %p", si->name, si->fini_func);
            break;
        case DT_INIT_ARRAY:
            si->init_array = reinterpret_cast<linker_function_t*>(base + d->d_un.d_ptr);
            DEBUG("%s constructors (DT_INIT_ARRAY) found at %p", si->name, si->init_array);
            break;
        case DT_INIT_ARRAYSZ:
            // ARC MOD BEGIN
            // Use sizeof(void*) instead of ElfW(Addr) which is Elf64_Addr.
            // As x86-64 NaCl uses ELF64, we need to use 64bit integers to
            // access addresses in ELF structures. However, for init_array,
            // fini_array, and preinit_array, NaCl uses 32bit integers to
            // store addresses.
            si->init_array_count = ((unsigned)d->d_un.d_val) / sizeof(void*);
            // ARC MOD END
            break;
        case DT_FINI_ARRAY:
            si->fini_array = reinterpret_cast<linker_function_t*>(base + d->d_un.d_ptr);
            DEBUG("%s destructors (DT_FINI_ARRAY) found at %p", si->name, si->fini_array);
            break;
        case DT_FINI_ARRAYSZ:
            // ARC MOD BEGIN
            // See the comment for DT_INIT_ARRAYSZ.
            si->fini_array_count = ((unsigned)d->d_un.d_val) / sizeof(void*);
            // ARC MOD END
            break;
        case DT_PREINIT_ARRAY:
            si->preinit_array = reinterpret_cast<linker_function_t*>(base + d->d_un.d_ptr);
            DEBUG("%s constructors (DT_PREINIT_ARRAY) found at %p", si->name, si->preinit_array);
            break;
        case DT_PREINIT_ARRAYSZ:
            // ARC MOD BEGIN
            // See the comment for DT_INIT_ARRAYSZ.
            // si->preinit_array_count = ((unsigned)d->d_un.d_val) / sizeof(ElfW(Addr));
            si->preinit_array_count = ((unsigned)d->d_un.d_val) / sizeof(void*);
            // ARC MOD END
            break;
        case DT_TEXTREL:
#if defined(__LP64__)
            DL_ERR("text relocations (DT_TEXTREL) found in 64-bit ELF file \"%s\"", si->name);
            return false;
#else
            si->has_text_relocations = true;
            break;
#endif
        case DT_SYMBOLIC:
            si->has_DT_SYMBOLIC = true;
            break;
        case DT_NEEDED:
            ++needed_count;
            break;
        case DT_FLAGS:
            if (d->d_un.d_val & DF_TEXTREL) {
#if defined(__LP64__)
                DL_ERR("text relocations (DF_TEXTREL) found in 64-bit ELF file \"%s\"", si->name);
                return false;
#else
                si->has_text_relocations = true;
#endif
            }
            if (d->d_un.d_val & DF_SYMBOLIC) {
                si->has_DT_SYMBOLIC = true;
            }
            break;
#if defined(__mips__)
        case DT_STRSZ:
        case DT_SYMENT:
        case DT_RELENT:
             break;
        case DT_MIPS_RLD_MAP:
            // Set the DT_MIPS_RLD_MAP entry to the address of _r_debug for GDB.
            {
              r_debug** dp = reinterpret_cast<r_debug**>(base + d->d_un.d_ptr);
              *dp = &_r_debug;
            }
            break;
        case DT_MIPS_RLD_VERSION:
        case DT_MIPS_FLAGS:
        case DT_MIPS_BASE_ADDRESS:
        case DT_MIPS_UNREFEXTNO:
            break;

        case DT_MIPS_SYMTABNO:
            si->mips_symtabno = d->d_un.d_val;
            break;

        case DT_MIPS_LOCAL_GOTNO:
            si->mips_local_gotno = d->d_un.d_val;
            break;

        case DT_MIPS_GOTSYM:
            si->mips_gotsym = d->d_un.d_val;
            break;
#endif

        default:
            DEBUG("Unused DT entry: type %p arg %p",
                  reinterpret_cast<void*>(d->d_tag), reinterpret_cast<void*>(d->d_un.d_val));
            break;
        }
    }

    DEBUG("si->base = %p, si->strtab = %p, si->symtab = %p",
          reinterpret_cast<void*>(si->base), si->strtab, si->symtab);

    // Sanity checks.
    if (relocating_linker && needed_count != 0) {
        DL_ERR("linker cannot have DT_NEEDED dependencies on other libraries");
        return false;
    }
    if (si->nbucket == 0) {
        DL_ERR("empty/missing DT_HASH in \"%s\" (built with --hash-style=gnu?)", si->name);
        return false;
    }
    if (si->strtab == 0) {
        DL_ERR("empty/missing DT_STRTAB in \"%s\"", si->name);
        return false;
    }
    if (si->symtab == 0) {
        DL_ERR("empty/missing DT_SYMTAB in \"%s\"", si->name);
        return false;
    }

    // If this is the main executable, then load all of the libraries from LD_PRELOAD now.
    if (si->flags & FLAG_EXE) {
        memset(g_ld_preloads, 0, sizeof(g_ld_preloads));
        size_t preload_count = 0;
        for (size_t i = 0; g_ld_preload_names[i] != NULL; i++) {
            soinfo* lsi = find_library(g_ld_preload_names[i], 0, NULL);
            if (lsi != NULL) {
                g_ld_preloads[preload_count++] = lsi;
            } else {
                // As with glibc, failure to load an LD_PRELOAD library is just a warning.
                DL_WARN("could not load library \"%s\" from LD_PRELOAD for \"%s\"; caused by %s",
                        g_ld_preload_names[i], si->name, linker_get_error_buffer());
            }
        }
    }

    soinfo** needed = reinterpret_cast<soinfo**>(alloca((1 + needed_count) * sizeof(soinfo*)));
    soinfo** pneeded = needed;

    for (ElfW(Dyn)* d = si->dynamic; d->d_tag != DT_NULL; ++d) {
        if (d->d_tag == DT_NEEDED) {
            const char* library_name = si->strtab + d->d_un.d_val;
            DEBUG("%s needs %s", si->name, library_name);
            // ARC MOD BEGIN
            // We may not be able to find DT_NEEDED specified by NDK's
            // shared objects, because ARC links a lot of libraries to
            // the main binary. For example, NDK apps may have
            // DT_NEEDED which expects libz.so exists, but ARC does
            // not have libz.so. We build libz.a and link it to the
            // main binary.
#if defined(HAVE_ARC)
            if (g_is_statically_linked && g_is_statically_linked(library_name))
              continue;
#endif
            // ARC MOD END
            soinfo* lsi = find_library(library_name, 0, NULL);
            if (lsi == NULL) {
                strlcpy(tmp_err_buf, linker_get_error_buffer(), sizeof(tmp_err_buf));
                DL_ERR("could not load library \"%s\" needed by \"%s\"; caused by %s",
                       library_name, si->name, tmp_err_buf);
                return false;
            }

            si->add_child(lsi);
            *pneeded++ = lsi;
        }
    }
    // ARC MOD BEGIN
    // Valgrind injects vgpreload_*.so and they require a few symbols
    // in libc.so. However, they do not have DT_NEEDED entry. With
    // glibc loader's semantics, symbols will be properly resolved
    // from libc.so but with Bionic, we need an explicit DT_NEEDED
    // entry for libc.so.
#if defined(RUNNING_ON_VALGRIND)
    if (!strcmp(si->name, "vgpreload_core-x86-linux.so") ||
        !strcmp(si->name, "vgpreload_memcheck-x86-linux.so"))
        *pneeded++ = find_library("libc.so", 0, NULL);
#endif
    // ARC MOD END
    *pneeded = NULL;

#if !defined(__LP64__)
    if (si->has_text_relocations) {
        // Make segments writable to allow text relocations to work properly. We will later call
        // phdr_table_protect_segments() after all of them are applied and all constructors are run.
        DL_WARN("%s has text relocations. This is wasting memory and prevents "
                "security hardening. Please fix.", si->name);
        if (phdr_table_unprotect_segments(si->phdr, si->phnum, si->load_bias) < 0) {
            DL_ERR("can't unprotect loadable segments for \"%s\": %s",
                   si->name, strerror(errno));
            return false;
        }
    }
#endif

#if defined(USE_RELA)
    if (si->plt_rela != NULL) {
        // ARC MOD BEGIN
        // Print the elapsed time for relocating symbols.
        ScopedElapsedTimePrinter<__LINE__> printer("Relocated plt symbols for", si->name);
        // ARC MOD END
        DEBUG("[ relocating %s plt ]\n", si->name);
        if (soinfo_relocate(si, si->plt_rela, si->plt_rela_count, needed)) {
            return false;
        }
    }
    if (si->rela != NULL) {
        // ARC MOD BEGIN
        // Print the elapsed time for relocating symbols.
        ScopedElapsedTimePrinter<__LINE__> printer("Relocated symbols for", si->name);
        // ARC MOD END
        DEBUG("[ relocating %s ]\n", si->name);
        if (soinfo_relocate(si, si->rela, si->rela_count, needed)) {
            return false;
        }
    }
#else
    if (si->plt_rel != NULL) {
        // ARC MOD BEGIN
        // Print the elapsed time for relocating symbols.
        ScopedElapsedTimePrinter<__LINE__> printer("Relocated plt symbols for", si->name);
        // ARC MOD END
        DEBUG("[ relocating %s plt ]", si->name);
        if (soinfo_relocate(si, si->plt_rel, si->plt_rel_count, needed)) {
            return false;
        }
    }
    if (si->rel != NULL) {
        // ARC MOD BEGIN
        // Print the elapsed time for relocating symbols.
        ScopedElapsedTimePrinter<__LINE__> printer("Relocated symbols for", si->name);
        // ARC MOD END
        DEBUG("[ relocating %s ]", si->name);
        if (soinfo_relocate(si, si->rel, si->rel_count, needed)) {
            return false;
        }
    }
#endif

#if defined(__mips__)
    if (!mips_relocate_got(si, needed)) {
        return false;
    }
#endif

    si->flags |= FLAG_LINKED;
    DEBUG("[ finished linking %s ]", si->name);

#if !defined(__LP64__)
    if (si->has_text_relocations) {
        // All relocations are done, we can protect our segments back to read-only.
        if (phdr_table_protect_segments(si->phdr, si->phnum, si->load_bias) < 0) {
            DL_ERR("can't protect segments for \"%s\": %s",
                   si->name, strerror(errno));
            return false;
        }
    }
#endif

    /* We can also turn on GNU RELRO protection */
    if (phdr_table_protect_gnu_relro(si->phdr, si->phnum, si->load_bias) < 0) {
        DL_ERR("can't enable GNU RELRO protection for \"%s\": %s",
               si->name, strerror(errno));
        return false;
    }

    /* Handle serializing/sharing the RELRO segment */
    if (extinfo && (extinfo->flags & ANDROID_DLEXT_WRITE_RELRO)) {
      if (phdr_table_serialize_gnu_relro(si->phdr, si->phnum, si->load_bias,
                                         extinfo->relro_fd) < 0) {
        DL_ERR("failed serializing GNU RELRO section for \"%s\": %s",
               si->name, strerror(errno));
        return false;
      }
    } else if (extinfo && (extinfo->flags & ANDROID_DLEXT_USE_RELRO)) {
      if (phdr_table_map_gnu_relro(si->phdr, si->phnum, si->load_bias,
                                   extinfo->relro_fd) < 0) {
        DL_ERR("failed mapping GNU RELRO section for \"%s\": %s",
               si->name, strerror(errno));
        return false;
      }
    }

    notify_gdb_of_load(si);
    return true;
}

// ARC MOD BEGIN
// add_vdso() is not called in NaCl and Bare Metal.
#if !defined(HAVE_ARC)
// ARC MOD END
/*
 * This function add vdso to internal dso list.
 * It helps to stack unwinding through signal handlers.
 * Also, it makes bionic more like glibc.
 */
static void add_vdso(KernelArgumentBlock& args __unused) {
#if defined(AT_SYSINFO_EHDR)
  ElfW(Ehdr)* ehdr_vdso = reinterpret_cast<ElfW(Ehdr)*>(args.getauxval(AT_SYSINFO_EHDR));
  if (ehdr_vdso == NULL) {
    return;
  }

  soinfo* si = soinfo_alloc("[vdso]", NULL);

  si->phdr = reinterpret_cast<ElfW(Phdr)*>(reinterpret_cast<char*>(ehdr_vdso) + ehdr_vdso->e_phoff);
  si->phnum = ehdr_vdso->e_phnum;
  si->base = reinterpret_cast<ElfW(Addr)>(ehdr_vdso);
  si->size = phdr_table_get_load_size(si->phdr, si->phnum);
  si->load_bias = get_elf_exec_load_bias(ehdr_vdso);

  soinfo_link_image(si, NULL);
#endif
}
// ARC MOD BEGIN
#endif
// ARC MOD END

/*
 * This is linker soinfo for GDB. See details below.
 */
static soinfo linker_soinfo_for_gdb;

// ARC MOD BEGIN
// We disable debug info related stuff. On NaCl, gdb will interact
// with the loader in the host so we need to do nothing for it.
#if !defined(HAVE_ARC)
// ARC MOD END
/* gdb expects the linker to be in the debug shared object list.
 * Without this, gdb has trouble locating the linker's ".text"
 * and ".plt" sections. Gdb could also potentially use this to
 * relocate the offset of our exported 'rtld_db_dlactivity' symbol.
 * Don't use soinfo_alloc(), because the linker shouldn't
 * be on the soinfo list.
 */
static void init_linker_info_for_gdb(ElfW(Addr) linker_base) {
#if defined(__LP64__)
  strlcpy(linker_soinfo_for_gdb.name, "/system/bin/linker64", sizeof(linker_soinfo_for_gdb.name));
#else
  strlcpy(linker_soinfo_for_gdb.name, "/system/bin/linker", sizeof(linker_soinfo_for_gdb.name));
#endif
  linker_soinfo_for_gdb.flags = FLAG_NEW_SOINFO;
  linker_soinfo_for_gdb.base = linker_base;

  /*
   * Set the dynamic field in the link map otherwise gdb will complain with
   * the following:
   *   warning: .dynamic section for "/system/bin/linker" is not at the
   *   expected address (wrong library or version mismatch?)
   */
  ElfW(Ehdr)* elf_hdr = reinterpret_cast<ElfW(Ehdr)*>(linker_base);
  ElfW(Phdr)* phdr = reinterpret_cast<ElfW(Phdr)*>(linker_base + elf_hdr->e_phoff);
  phdr_table_get_dynamic_section(phdr, elf_hdr->e_phnum, linker_base,
                                 &linker_soinfo_for_gdb.dynamic, NULL, NULL);
  insert_soinfo_into_debug_map(&linker_soinfo_for_gdb);
}
// ARC MOD BEGIN
#endif  // !__native_client__
// ARC MOD END
// ARC MOD BEGIN
// Temporary support of GDB.
#if defined(BARE_METAL_BIONIC)
static const char kBareMetalGdbDir[] = "/tmp/bare_metal_gdb/";

// This function is called in very early stage of process initialization to
// wait for GDB to attach to this process and install necessary breakpoints.
static void maybe_wait_gdb_attach() {
  // First check existence of a lock directory. Return if it does not exist.
  // Note that it's safe to call open syscall here even under Bare Metal's
  // seccomp sandbox; it just returns EPERM instead of killing the process.
  int fd = TEMP_FAILURE_RETRY(
      syscall(__NR_open, kBareMetalGdbDir, O_RDONLY | O_DIRECTORY));
  if (fd < 0) {
    return;
  }
  syscall(__NR_close, fd);

  // Existence of the lock directory indicates that the user wants to debug
  // this process. Touch a PID marker file under the directory, print PID to
  // stderr, and wait for the file to be removed.
  // Note that it's safe to call getpid here because successful open syscall
  // above means seccomp sandbox is disabled.
  int pid = TEMP_FAILURE_RETRY(syscall(__NR_getpid));
  if (pid < 0) {
    DL_ERR("tried communicating with gdb, but getpid failed.\n");
    exit(-1);
  }
  char lock_file[64];
  __libc_format_buffer(
      lock_file, sizeof(lock_file), "%s%d", kBareMetalGdbDir, pid);
  fd = TEMP_FAILURE_RETRY(
      syscall(__NR_open, lock_file, O_WRONLY | O_CREAT, 0755));
  if (fd < 0) {
    DL_ERR("tried communicating with gdb, but failed to touch a lock file.\n");
    exit(-1);
  }
  syscall(__NR_close, fd);

  // Notify that we are ready to be attached by gdb.
  // Note that this message is hard-coded in build scripts.
  __libc_format_fd(2, "linker: waiting for gdb (%d)\n", pid);

  for (;;) {
    fd = TEMP_FAILURE_RETRY(syscall(__NR_open, lock_file, O_RDONLY));
    if (fd < 0) {
      if (errno != ENOENT) {
        DL_ERR("tried communicating with gdb, but failed to watch "
               "a lock file: %s.\n",
               strerror(errno));
        exit(-1);
      }
      break;
    }
    syscall(__NR_close, fd);
  }
}
#endif  // BARE_METAL_BIONIC
// ARC MOD END

/*
 * This code is called after the linker has linked itself and
 * fixed it's own GOT. It is safe to make references to externs
 * and other non-local data at this point.
 */
static ElfW(Addr) __linker_init_post_relocation(KernelArgumentBlock& args, ElfW(Addr) linker_base) {
    /* NOTE: we store the args pointer on a special location
     *       of the temporary TLS area in order to pass it to
     *       the C Library's runtime initializer.
     *
     *       The initializer must clear the slot and reset the TLS
     *       to point to a different location to ensure that no other
     *       shared library constructor can access it.
     */
  __libc_init_tls(args);
  // ARC MOD BEGIN
  // Place a pointer to __get_tls in a fixed address on Bare Metal
  // i686. Though this depends on Linux kernel's ASLR, it would be OK
  // as Bare Metal i686 with glibc is not a production target.
  // See also bionic/libc/include/private/get_tls_for_art.h.
  //
  // Also note this should be done after __libc_init_tls. Otherwise,
  // updating errno will cause a crash.
  // TODO(crbug.com/465216): Remove this after the newlib switch.
#if defined(BARE_METAL_BIONIC) && defined(__i386__)
  if (!mprotect(reinterpret_cast<void*>(POINTER_TO_GET_TLS_FUNC_ON_BMM_I386),
                PAGE_SIZE, PROT_READ)) {
    // The mprotect call above must fail. If the mprotect call
    // succeeds, this means the page is already in use.
    DL_ERR("The fixed address for ART is already in use");
    exit(1);
  }
  get_tls_fn_t* get_tls_ptr = static_cast<get_tls_fn_t*>(
      mmap(reinterpret_cast<void*>(POINTER_TO_GET_TLS_FUNC_ON_BMM_I386),
           PAGE_SIZE,
           PROT_READ | PROT_WRITE,
           MAP_ANONYMOUS | MAP_PRIVATE | MAP_FIXED,
           -1, 0));
  if (get_tls_ptr == MAP_FAILED) {
    DL_ERR("Failed to mmap a fixed address for ART");
    exit(1);
  }
  *get_tls_ptr = &__get_tls;
  // Make it read-only, just in case.
  if (mprotect(get_tls_ptr, PAGE_SIZE, PROT_READ)) {
    DL_ERR("Failed to mprotect the fixed address for ART");
    exit(1);
  }
#endif
  // ARC MOD END
  // ARC MOD BEGIN
  // Temporary support of GDB.
#if defined(BARE_METAL_BIONIC)
  // Wait for gdb attaching to this process.
  // If the main binary is /lib/main.nexe, the Bionic loader is
  // launched by nacl_helper and not by nonsfi_loader, so we should
  // wait for GDB. Note that run_unittest.py does not rely on
  // /tmp/bare_metal_gdb.
  // TODO(crbug.com/354290): Remove this hack. Use __nacl_irt_open and
  // __nacl_irt_close instead of the direct syscalls when we add more
  // restrictions to the syscall sandbox.
  if (args.argc == 1 && !strcmp(args.argv[0], "/lib/main.nexe"))
    maybe_wait_gdb_attach();
#endif  // BARE_METAL_BIONIC
  // ARC MOD END

#if TIMING
    struct timeval t0, t1;
    gettimeofday(&t0, 0);
#endif

    // Initialize environment functions, and get to the ELF aux vectors table.
    linker_env_init(args);

    // If this is a setuid/setgid program, close the security hole described in
    // ftp://ftp.freebsd.org/pub/FreeBSD/CERT/advisories/FreeBSD-SA-02:23.stdio.asc
    if (get_AT_SECURE()) {
        nullify_closed_stdio();
    }

    // ARC MOD BEGIN
    // NaCl does not have signal handlers so there is no reason we
    // need to call debugger_init, which depends on signals.
#if !defined(HAVE_ARC)
    // ARC MOD END
    debuggerd_init();
    // ARC MOD BEGIN
#endif
    // ARC MOD END

    // Get a few environment variables.
    const char* LD_DEBUG = linker_env_get("LD_DEBUG");
    if (LD_DEBUG != NULL) {
      g_ld_debug_verbosity = atoi(LD_DEBUG);
    }

    // Normally, these are cleaned by linker_env_init, but the test
    // doesn't cost us anything.
    const char* ldpath_env = NULL;
    const char* ldpreload_env = NULL;
    if (!get_AT_SECURE()) {
      ldpath_env = linker_env_get("LD_LIBRARY_PATH");
      ldpreload_env = linker_env_get("LD_PRELOAD");
      // ARC MOD BEGIN
      // Currently, we have some canned shared objects in
      // /vendor/lib. In NDK direct execution mode, we need to be able
      // to open them when they are required by NDK shared objects.
      // TODO(crbug.com/364344): Remove /vendor/lib and this MOD.
#if defined(USE_NDK_DIRECT_EXECUTION)
      if (!ldpath_env)
        ldpath_env = kVendorLibDir;
#endif
      // ARC MOD END
      // ARC MOD BEGIN
      // Use LD_LIBRARY_PATH and LD_PRELOAD (but only if we aren't setuid/setgid).
      parse_LD_LIBRARY_PATH(ldpath_env);
      parse_LD_PRELOAD(ldpreload_env);
      // ARC MOD END
    }

    INFO("[ android linker & debugger ]");

    // ARC MOD BEGIN
    // As sel_ldr does not load the main program, we load the main
    // binary by ourselves in load_main_binary.
#if defined(HAVE_ARC)
    // Load the main binary. See the comment for load_main_binary()
    // for detail.
    soinfo* si = load_main_binary(args);
#else
    // ARC MOD END
    soinfo* si = soinfo_alloc(args.argv[0], NULL);
    // ARC MOD BEGIN
    // We load the main binary ourselves.
#endif
    // ARC MOD END
    if (si == NULL) {
        exit(EXIT_FAILURE);
    }

    /* bootstrap the link map, the main exe always needs to be first */
    si->flags |= FLAG_EXE;
    link_map* map = &(si->link_map_head);

    // ARC MOD BEGIN
    // ARC fills _r_debug during load_main_binary above. Since we have already
    // relocated the main binary, _r_debug now contains some libraries.
#if !defined(HAVE_ARC)
    // ARC MOD END
    map->l_addr = 0;
    map->l_name = args.argv[0];
    map->l_prev = NULL;
    map->l_next = NULL;

    _r_debug.r_map = map;
    r_debug_tail = map;
    // ARC MOD BEGIN
#endif
    // ARC MOD END

    // ARC MOD BEGIN
    // We disable debug info related stuff. On NaCl, gdb will interact
    // with the loader in the host so we need to do nothing for it.
#if !defined(HAVE_ARC)
    // ARC MOD END
    init_linker_info_for_gdb(linker_base);

    // ARC MOD BEGIN
    // Note that we are in #if !defined(__native_client__) &&
    // !defined(BARE_METAL_BIONIC) so this code will not be used.
    //
    // We already initialized them in load_library.
    // ARC MOD END
    // Extract information passed from the kernel.
    si->phdr = reinterpret_cast<ElfW(Phdr)*>(args.getauxval(AT_PHDR));
    si->phnum = args.getauxval(AT_PHNUM);
    si->entry = args.getauxval(AT_ENTRY);

    // ARC MOD BEGIN
    // Note that we are in #if !defined(__native_client__) &&
    // !defined(BARE_METAL_BIONIC) so this code will not be used.
    //
    // On NaCl, we load the main executable in load_main_binary
    // using load_library and |si| is already initialized in
    // load_library. So, we do not need to update these fields.
    // Also, arm-nacl-gcc maps PT_PHDR at the beginning of the data
    // segment, so this check is wrong.
    // ARC MOD END
    /* Compute the value of si->base. We can't rely on the fact that
     * the first entry is the PHDR because this will not be true
     * for certain executables (e.g. some in the NDK unit test suite)
     */
    si->base = 0;
    si->size = phdr_table_get_load_size(si->phdr, si->phnum);
    si->load_bias = 0;
    for (size_t i = 0; i < si->phnum; ++i) {
      if (si->phdr[i].p_type == PT_PHDR) {
        si->load_bias = reinterpret_cast<ElfW(Addr)>(si->phdr) - si->phdr[i].p_vaddr;
        si->base = reinterpret_cast<ElfW(Addr)>(si->phdr) - si->phdr[i].p_offset;
        break;
      }
    }
    si->dynamic = NULL;
    // ARC MOD BEGIN
#endif  // !HAVE_ARC
    // ARC MOD END
    si->ref_count = 1;

    // ARC MOD BEGIN
    // NaCl does not map the ELF header for the main nexe, and our
    // main nexe is not a PIE on SFI NaCl. Just skip the check.
#if !defined(__native_client__)
    // ARC MOD END
    ElfW(Ehdr)* elf_hdr = reinterpret_cast<ElfW(Ehdr)*>(si->base);
    if (elf_hdr->e_type != ET_DYN) {
        __libc_format_fd(2, "error: only position independent executables (PIE) are supported.\n");
        exit(EXIT_FAILURE);
    }
    // ARC MOD BEGIN
#endif  // !defined(__native_client__)
    // ARC MOD END

    // Use LD_LIBRARY_PATH and LD_PRELOAD (but only if we aren't setuid/setgid).
    // ARC MOD BEGIN
    // We parse the env vars earlier.
    // parse_LD_LIBRARY_PATH(ldpath_env);
    // parse_LD_PRELOAD(ldpreload_env);
    // ARC MOD END
    // ARC MOD BEGIN
#if !defined(HAVE_ARC)
    // For ARC, main binary was loaded with load_main_binary and
    // already relocated.
    // ARC MOD END
    somain = si;

    if (!soinfo_link_image(si, NULL)) {
        __libc_format_fd(2, "CANNOT LINK EXECUTABLE: %s\n", linker_get_error_buffer());
        exit(EXIT_FAILURE);
    }
    // ARC MOD BEGIN
    // For ARC, main binary was loaded with load_main_binary and
    // already relocated.
#endif
    // ARC MOD END
    // ARC MOD BEGIN
    // Neither NaCl nor Bare Metal has VDSO.
#if !defined(HAVE_ARC)
    // ARC MOD END
    add_vdso(args);
    // ARC MOD BEGIN
#endif
    // ARC MOD END

    si->CallPreInitConstructors();

    for (size_t i = 0; g_ld_preloads[i] != NULL; ++i) {
        g_ld_preloads[i]->CallConstructors();
    }

    /* After the link_image, the si->load_bias is initialized.
     * For so lib, the map->l_addr will be updated in notify_gdb_of_load.
     * We need to update this value for so exe here. So Unwind_Backtrace
     * for some arch like x86 could work correctly within so exe.
     */
    // ARC MOD BEGIN UPSTREAM bionic-use-si-base
#if defined(__native_client__)
    // TODO(crbug.com/323864): Remove the path for __native_client__.
    map->l_addr = si->load_bias;
#else
    map->l_addr = si->base;
#endif
    // ARC MOD END UPSTREAM
    si->CallConstructors();

#if TIMING
    gettimeofday(&t1, NULL);
    PRINT("LINKER TIME: %s: %d microseconds", args.argv[0], (int) (
               (((long long)t1.tv_sec * 1000000LL) + (long long)t1.tv_usec) -
               (((long long)t0.tv_sec * 1000000LL) + (long long)t0.tv_usec)));
#endif
#if STATS
    PRINT("RELO STATS: %s: %d abs, %d rel, %d copy, %d symbol", args.argv[0],
           linker_stats.count[kRelocAbsolute],
           linker_stats.count[kRelocRelative],
           linker_stats.count[kRelocCopy],
           linker_stats.count[kRelocSymbol]);
#endif
#if COUNT_PAGES
    {
        unsigned n;
        unsigned i;
        unsigned count = 0;
        for (n = 0; n < 4096; n++) {
            if (bitmask[n]) {
                unsigned x = bitmask[n];
#if defined(__LP64__)
                for (i = 0; i < 32; i++) {
#else
                for (i = 0; i < 8; i++) {
#endif
                    if (x & 1) {
                        count++;
                    }
                    x >>= 1;
                }
            }
        }
        PRINT("PAGES MODIFIED: %s: %d (%dKB)", args.argv[0], count, count * 4);
    }
#endif

#if TIMING || STATS || COUNT_PAGES
    fflush(stdout);
#endif

    TRACE("[ Ready to execute '%s' @ %p ]", si->name, reinterpret_cast<void*>(si->entry));
    return si->entry;
}

// ARC MOD BEGIN
// This is only used for the relocation of the loader and NaCl do not
// relocate the loader for now.
#if !defined(__native_client__)
// ARC MOD END
/* Compute the load-bias of an existing executable. This shall only
 * be used to compute the load bias of an executable or shared library
 * that was loaded by the kernel itself.
 *
 * Input:
 *    elf    -> address of ELF header, assumed to be at the start of the file.
 * Return:
 *    load bias, i.e. add the value of any p_vaddr in the file to get
 *    the corresponding address in memory.
 */
static ElfW(Addr) get_elf_exec_load_bias(const ElfW(Ehdr)* elf) {
  ElfW(Addr) offset = elf->e_phoff;
  const ElfW(Phdr)* phdr_table = reinterpret_cast<const ElfW(Phdr)*>(reinterpret_cast<uintptr_t>(elf) + offset);
  const ElfW(Phdr)* phdr_end = phdr_table + elf->e_phnum;

  for (const ElfW(Phdr)* phdr = phdr_table; phdr < phdr_end; phdr++) {
    if (phdr->p_type == PT_LOAD) {
      return reinterpret_cast<ElfW(Addr)>(elf) + phdr->p_offset - phdr->p_vaddr;
    }
  }
  return 0;
}
// ARC MOD BEGIN
// This is only used for the relocation of the loader and NaCl do not
// relocate the loader for now.
#endif  // !__native_client__
// ARC MOD END

extern "C" void _start();

/*
 * This is the entry point for the linker, called from begin.S. This
 * method is responsible for fixing the linker's own relocations, and
 * then calling __linker_init_post_relocation().
 *
 * Because this method is called before the linker has fixed it's own
 * relocations, any attempt to reference an extern variable, extern
 * function, or other GOT reference will generate a segfault.
 */
// ARC MOD BEGIN
// This is called from bionic/linker/arch/nacl/begin.c in ARC.
// ARC MOD END
extern "C" ElfW(Addr) __linker_init(void* raw_args) {
  // ARC MOD BEGIN
  // Do not show messages from PRINT when --disable-debug-code is specified.
#if LINKER_DEBUG == 0
  g_ld_debug_verbosity = -1;
#endif
  // ARC MOD END
  // Initialize static variables.
  solist = get_libdl_info();
  sonext = get_libdl_info();

  KernelArgumentBlock args(raw_args);

  // ARC MOD BEGIN
  // Print total time elapsed in the loader. Note that defining TIMING would
  // not help much because the TIMING code does not count the load_library
  // call for the main.nexe below.
  ScopedElapsedTimePrinter<__LINE__> printer(
      "Loaded", (const char*)((void**)raw_args)[1]  /* == argv[0] */);

  // On real Android, the Bionic loader is a shared object and it
  // has a few relocation entries whose type is R_*_RELATIVE maybe
  // for address randomization. For NaCl, we use statically linked
  // binary as the loader so we do not need to relocate the loader.
#if !defined(__native_client__)
  // ARC MOD END
  ElfW(Addr) linker_addr = args.getauxval(AT_BASE);
  // ARC MOD BEGIN
  // AT_ENTRY is not filled yet.
#if !defined(HAVE_ARC)
  // ARC MOD END
  ElfW(Addr) entry_point = args.getauxval(AT_ENTRY);
  // ARC MOD BEGIN
#endif
  // ARC MOD END
  ElfW(Ehdr)* elf_hdr = reinterpret_cast<ElfW(Ehdr)*>(linker_addr);
  ElfW(Phdr)* phdr = reinterpret_cast<ElfW(Phdr)*>(linker_addr + elf_hdr->e_phoff);
  // ARC MOD BEGIN
#endif  // !defined(__native_client__)
  // ARC MOD END

  soinfo linker_so;
  memset(&linker_so, 0, sizeof(soinfo));

  // ARC MOD BEGIN
  // We cannot do this check yet because we do not have |entry_point|
  // yet. This check makes even less sense for us as we will not be
  // trying to run runnable-ld.so using runnable-ld.so.
#if !defined(HAVE_ARC)
  // ARC MOD END
  // If the linker is not acting as PT_INTERP entry_point is equal to
  // _start. Which means that the linker is running as an executable and
  // already linked by PT_INTERP.
  //
  // This happens when user tries to run 'adb shell /system/bin/linker'
  // see also https://code.google.com/p/android/issues/detail?id=63174
  if (reinterpret_cast<ElfW(Addr)>(&_start) == entry_point) {
    __libc_fatal("This is %s, the helper program for shared library executables.\n", args.argv[0]);
  }
  // ARC MOD BEGIN
#endif  // !defined(HAVE_ARC)
  // ARC MOD END

  strcpy(linker_so.name, "[dynamic linker]");
  // ARC MOD BEGIN
  // Skip ELF header dependent information that are not available in NaCl.
  // See also the previous comments above.
#if !defined(__native_client__)
  // ARC MOD END
  linker_so.base = linker_addr;
  linker_so.size = phdr_table_get_load_size(phdr, elf_hdr->e_phnum);
  linker_so.load_bias = get_elf_exec_load_bias(elf_hdr);
  linker_so.dynamic = NULL;
  linker_so.phdr = phdr;
  linker_so.phnum = elf_hdr->e_phnum;
  linker_so.flags |= FLAG_LINKER;

  // ARC MOD BEGIN
  // Note we relocate the Bionic loader itself only on Bare Metal
  // mode, where the Bionic loader is a PIE. On SFI NaCl, all symbols
  // are resolved statically so we do not need to run
  // |soinfo_link_image| on SFI NaCl.
  // ARC MOD END
  if (!soinfo_link_image(&linker_so, NULL)) {
    // It would be nice to print an error message, but if the linker
    // can't link itself, there's no guarantee that we'll be able to
    // call write() (because it involves a GOT reference). We may as
    // well try though...
    const char* msg = "CANNOT LINK EXECUTABLE: ";
    write(2, msg, strlen(msg));
    write(2, __linker_dl_err_buf, strlen(__linker_dl_err_buf));
    write(2, "\n", 1);
    _exit(EXIT_FAILURE);
  }

  // ARC MOD BEGIN
#else  // !defined(__native_client__)
  // Fix up linker_so for calling constructors.
  linker_so.init_array = &__init_array;
  linker_so.init_array_count = &__init_array_end - &__init_array;
#endif  // !defined(__native_client__)
  // ARC MOD END
  // Initialize the linker's own global variables
  linker_so.CallConstructors();

  // We have successfully fixed our own relocations. It's safe to run
  // the main part of the linker now.
  args.abort_message_ptr = &g_abort_message;
  // ARC MOD BEGIN
  // Fake |linker_addr| that is not declared for NaCl with NULL to get
  // __linker_init_post_relocation to work.
#if defined(__native_client__)
  ElfW(Addr) start_address = __linker_init_post_relocation(args, 0);
#else
  ElfW(Addr) start_address = __linker_init_post_relocation(args, linker_addr);
#endif
  // ARC MOD END

  protect_data(PROT_READ);

  // Return the address that the calling assembly stub should jump to.
  return start_address;
}
// ARC MOD BEGIN
// Linux kernel maps segments of the main binary before it runs the
// loader and sends the information about it using auxvals (e.g.,
// AT_PHDR). Neither NaCl nor Bare Metal service runtime does this so
// we need to load the main binary by ourselves.
#if defined(HAVE_ARC)

static soinfo* load_main_binary(KernelArgumentBlock& args) {
    if (args.argc < 1) {
        DL_ERR("no file\n");
        exit(-1);
    }

    struct soinfo* si = load_library(args.argv[0],
                                     RTLD_NOW | RTLD_LOCAL, NULL);
    if (!si) {
        DL_ERR("Failed to load %s\n", args.argv[0]);
        exit(-1);
    }

    // Note that we use Elf32_auxv even on NaCl x86-64.
    Elf32_auxv_t* auxv = args.auxv;
    // auxv[0] and auxv[1] were filled by _start for AT_SYSINFO and
    // AT_BASE, and we must not update them. See
    // bionic/linker/arch/nacl/begin.c for detail.
    if (auxv[0].a_type != AT_SYSINFO || !auxv[0].a_un.a_val) {
        DL_ERR("auxv[0] is not filled.\n");
        exit(-1);
    }
    if (auxv[1].a_type != AT_BASE) {
        DL_ERR("auxv[1].a_type is not filled.\n");
        exit(-1);
    }
    if (auxv[2].a_type != AT_NULL || auxv[2].a_un.a_val) {
        DL_ERR("auxv[2] has already been filled.\n");
        exit(-1);
    }
    int i = 2;
    auxv[i].a_type = AT_PHDR;
    auxv[i++].a_un.a_val = (uint32_t)si->phdr;
    auxv[i].a_type = AT_PHNUM;
    auxv[i++].a_un.a_val = si->phnum;
    auxv[i].a_type = AT_ENTRY;
    auxv[i++].a_un.a_val = (uint32_t)si->entry;
    auxv[i].a_type = AT_NULL;
    auxv[i++].a_un.a_val = 0;
    return si;
}

#endif
// ARC MOD END
