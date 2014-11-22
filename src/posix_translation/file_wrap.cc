/* Copyright 2014 The Chromium Authors. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Wrappers for various file system calls.
 */

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <nacl_stat.h>
#include <poll.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/vfs.h>
#include <unistd.h>
#include <utime.h>

#include <string>
#include <vector>

#include "base/basictypes.h"
#include "base/safe_strerror_posix.h"
#include "base/strings/string_piece.h"
#include "base/strings/string_util.h"
#include "common/arc_strace.h"
#include "common/alog.h"
#include "common/danger.h"
#include "common/dlfcn_injection.h"
#include "common/export.h"
#include "common/file_util.h"
#include "common/logd_write.h"
#include "common/memory_state.h"
#include "common/options.h"
#include "common/process_emulator.h"
#include "common/thread_local.h"
#include "common/trace_event.h"
#include "posix_translation/libc_dispatch_table.h"
#include "posix_translation/virtual_file_system.h"

// A macro to wrap an IRT function. Note that the macro does not wrap IRT
// calls made by the Bionic loader. For example, wrapping mmap with DO_WRAP
// does not hook the mmap IRT calls in phdr_table_load_segments() in
// mods/android/bionic/linker/linker_phdr.c. This is because the loader has
// its own set of IRT function pointers that are not visible from non-linker
// code.
#define DO_WRAP(name)                                   \
  __nacl_irt_ ## name ## _real = __nacl_irt_ ## name;   \
  __nacl_irt_ ## name  = __nacl_irt_ ## name ## _wrap

// A macro to define an IRT wrapper and a function pointer to store
// the real IRT function. Note that initializing __nacl_irt_<name>_real
// with __nacl_irt_<name> by default is not a good idea because it requires
// a static initializer.
#define IRT_WRAPPER(name, ...)                              \
  extern int (*__nacl_irt_ ## name)(__VA_ARGS__);           \
  static int (*__nacl_irt_ ## name ## _real)(__VA_ARGS__);  \
  int (__nacl_irt_ ## name ## _wrap)(__VA_ARGS__)

// A helper macro to show both DIR pointer and its file descriptor in
// ARC strace.
#define PRETIFY_DIRP(dirp) (dirp) ? dirfd(dirp) : -1, (dirp)

// Note about large file support in ARC:
//
// Unlike glibc, Bionic does not support _LARGEFILE64_SOURCE and
// _FILE_OFFSET_BITS=64 macros. Instead, it always provides both foo() and
// foo64() functions. It is user code's responsibility to call foo64()
// explicitly instead of foo() when large file support is necessary.
// Note that Android's JNI code properly calls these 64-bit variants.
//
// For Bionic, we should provide both
//    __wrap_foo(type_t param1, another_type_t param2);
// and
//    __wrap_foo64(type64_t param1, another_type64_t param2);
// functions because both could be called.

extern "C" {
// sorted by syscall name.
ARC_EXPORT int __wrap_access(const char* pathname, int mode);
ARC_EXPORT int __wrap_chdir(const char* path);
ARC_EXPORT int __wrap_chown(const char* path, uid_t owner, gid_t group);
ARC_EXPORT int __wrap_closedir(DIR* dirp);
ARC_EXPORT int __wrap_dirfd(DIR* dirp);
ARC_EXPORT int __wrap_dlclose(void* handle);
ARC_EXPORT void* __wrap_dlopen(const char* filename, int flag);
ARC_EXPORT void* __wrap_dlsym(void* handle, const char* symbol);
ARC_EXPORT DIR* __wrap_fdopendir(int fd);
ARC_EXPORT char* __wrap_getcwd(char* buf, size_t size);
ARC_EXPORT int __wrap_open(const char* pathname, int flags, ...);
ARC_EXPORT DIR* __wrap_opendir(const char* name);
ARC_EXPORT struct dirent* __wrap_readdir(DIR* dirp);
ARC_EXPORT int __wrap_readdir_r(
    DIR* dirp, struct dirent* entry,
    struct dirent** result);
ARC_EXPORT ssize_t __wrap_readlink(const char* path, char* buf, size_t bufsiz);
ARC_EXPORT char* __wrap_realpath(const char* path, char* resolved_path);
ARC_EXPORT int __wrap_remove(const char* pathname);
ARC_EXPORT int __wrap_rename(const char* oldpath, const char* newpath);
ARC_EXPORT void __wrap_rewinddir(DIR* dirp);
ARC_EXPORT int __wrap_rmdir(const char* pathname);
ARC_EXPORT int __wrap_scandir(
    const char* dirp, struct dirent*** namelist,
    int (*filter)(const struct dirent*),
    int (*compar)(const struct dirent**, const struct dirent**));
ARC_EXPORT int __wrap_statfs(const char* path, struct statfs* stat);
ARC_EXPORT int __wrap_statvfs(const char* path, struct statvfs* stat);
ARC_EXPORT int __wrap_symlink(const char* oldp, const char* newp);
ARC_EXPORT mode_t __wrap_umask(mode_t mask);
ARC_EXPORT int __wrap_unlink(const char* pathname);
ARC_EXPORT int __wrap_utime(const char* filename, const struct utimbuf* times);
ARC_EXPORT int __wrap_utimes(
    const char* filename,
    const struct timeval times[2]);

// Bionic's off_t is 32bit but bionic also provides 64 bit version of
// functions which take off64_t. We need to define the wrapper of
// the 64 bit versions as well.
ARC_EXPORT int __wrap_ftruncate(int fd, off_t length);
ARC_EXPORT off_t __wrap_lseek(int fd, off_t offset, int whence);
ARC_EXPORT int __wrap_truncate(const char* path, off_t length);

ARC_EXPORT int __wrap_ftruncate64(int fd, off64_t length);
ARC_EXPORT off64_t __wrap_lseek64(int fd, off64_t offset, int whence);
ARC_EXPORT ssize_t __wrap_pread(int fd, void* buf, size_t count, off_t offset);
ARC_EXPORT ssize_t __wrap_pwrite(
    int fd, const void* buf, size_t count, off_t offset);
ARC_EXPORT ssize_t __wrap_pread64(
    int fd, void* buf, size_t count, off64_t offset);
ARC_EXPORT ssize_t __wrap_pwrite64(
    int fd, const void* buf, size_t count, off64_t offset);
ARC_EXPORT int __wrap_truncate64(const char* path, off64_t length);

// sorted by syscall name.
ARC_EXPORT int __wrap_close(int fd);
ARC_EXPORT int __wrap_creat(const char* pathname, mode_t mode);
ARC_EXPORT int __wrap_fcntl(int fd, int cmd, ...);
ARC_EXPORT FILE* __wrap_fdopen(int fildes, const char* mode);
ARC_EXPORT int __wrap_fdatasync(int fd);
ARC_EXPORT int __wrap_flock(int fd, int operation);
ARC_EXPORT int __wrap_fsync(int fd);
ARC_EXPORT int __wrap_ioctl(int fd, int request, ...);
ARC_EXPORT int __wrap_madvise(void* addr, size_t length, int advice);
ARC_EXPORT void* __wrap_mmap(
    void* addr, size_t length, int prot, int flags, int fd, off_t offset);
ARC_EXPORT int __wrap_mprotect(const void* addr, size_t length, int prot);
ARC_EXPORT int __wrap_munmap(void* addr, size_t length);
ARC_EXPORT int __wrap_poll(struct pollfd* fds, nfds_t nfds, int timeout);
ARC_EXPORT ssize_t __wrap_read(int fd, void* buf, size_t count);
ARC_EXPORT ssize_t __wrap_readv(int fd, const struct iovec* iov, int iovcnt);
ARC_EXPORT ssize_t __wrap_write(int fd, const void* buf, size_t count);
ARC_EXPORT ssize_t __wrap_writev(int fd, const struct iovec* iov, int iovcnt);

static int real_close(int fd);
static int real_fstat(int fd, struct stat *buf);
static char* real_getcwd(char *buf, size_t size);
static off64_t real_lseek64(int fd, off64_t offset, int whence);
static int real_lstat(const char *pathname, struct stat *buf);
static int real_mkdir(const char *pathname, mode_t mode);
static int real_open(const char *pathname, int oflag, mode_t cmode);
static ssize_t real_read(int fd, void *buf, size_t count);
static int real_stat(const char *pathname, struct stat *buf);
static ssize_t real_write(int fd, const void *buf, size_t count);
}  // extern "C"

using posix_translation::VirtualFileSystem;

namespace {

// Counts the depth of __wrap_write() calls to avoid infinite loop back.
DEFINE_THREAD_LOCAL(int, g_wrap_write_nest_count);

// Helper function for converting from nacl_abi_stat to stat.
void NaClAbiStatToStat(struct nacl_abi_stat* nacl_stat, struct stat* st) {
  st->st_dev = nacl_stat->nacl_abi_st_dev;
  st->st_mode = nacl_stat->nacl_abi_st_mode;
  st->st_nlink = nacl_stat->nacl_abi_st_nlink;
  st->st_uid = nacl_stat->nacl_abi_st_uid;
  st->st_gid = nacl_stat->nacl_abi_st_gid;
  st->st_rdev = nacl_stat->nacl_abi_st_rdev;
  st->st_size = nacl_stat->nacl_abi_st_size;
  st->st_blksize = nacl_stat->nacl_abi_st_blksize;
  st->st_blocks = nacl_stat->nacl_abi_st_blocks;
  st->st_atime = nacl_stat->nacl_abi_st_atime;
  st->st_atime_nsec = 0;
  st->st_mtime = nacl_stat->nacl_abi_st_mtime;
  st->st_mtime_nsec = 0;
  st->st_ctime = nacl_stat->nacl_abi_st_ctime;
  st->st_ctime_nsec = 0;
  st->st_ino = nacl_stat->nacl_abi_st_ino;
}

// Helper function for converting from stat to nacl_abi_stat.
void StatToNaClAbiStat(struct stat* st, struct nacl_abi_stat* nacl_stat) {
  nacl_stat->nacl_abi_st_dev = st->st_dev;
  nacl_stat->nacl_abi_st_mode= st->st_mode;
  nacl_stat->nacl_abi_st_nlink = st->st_nlink;
  nacl_stat->nacl_abi_st_uid = st->st_uid;
  nacl_stat->nacl_abi_st_gid = st->st_gid;
  nacl_stat->nacl_abi_st_rdev = st->st_rdev;
  nacl_stat->nacl_abi_st_size = st->st_size;
  nacl_stat->nacl_abi_st_blksize = st->st_blksize;
  nacl_stat->nacl_abi_st_blocks = st->st_blocks;
  nacl_stat->nacl_abi_st_atime = st->st_atime;
  nacl_stat->nacl_abi_st_mtime = st->st_mtime;
  nacl_stat->nacl_abi_st_ctime = st->st_ctime;
  nacl_stat->nacl_abi_st_ino = st->st_ino;
}

// Helper function for stripping "/system/lib/" prefix from |path| if exists.
const char* StripSystemLibPrefix(const char* path) {
  const char kSystemLib[] = "/system/lib/";
  return !StartsWithASCII(path, kSystemLib, true) ?
      path : path + sizeof(kSystemLib) - 1;
}

// Controls syscall interception. If set to true, file syscalls are just passed
// through to libc.
//
// A mutex lock is not necessary here since |g_pass_through_enabled| is set by
// the main thread before the first pthread_create() call is made. It is ensured
// that a non-main thread can see correct |g_pass_through_enabled| value because
// pthread_create() call to create the thread itself is a memory barrier.
//
// TODO(crbug.com/423063): We should be able to remove this after
// libwrap/libposix_translation merge is finished.
bool g_pass_through_enabled = false;

VirtualFileSystem* GetFileSystem() {
  if (g_pass_through_enabled) {
    return NULL;
  }
  return VirtualFileSystem::GetVirtualFileSystem();
}

}  // namespace

// sorted by syscall name.

int __wrap_access(const char* pathname, int mode) {
  ARC_STRACE_ENTER("access", "\"%s\", %s",
                   SAFE_CSTR(pathname),
                   arc::GetAccessModeStr(mode).c_str());
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    result = file_system->access(pathname, mode);
  } else {
    std::string newpath(pathname);
    result = access(newpath.c_str(), mode);
  }
  if (result == -1 && errno != ENOENT) {
    DANGERF("path=%s mode=%d: %s",
            SAFE_CSTR(pathname), mode, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

int __wrap_chdir(const char* path) {
  ARC_STRACE_ENTER("chdir", "\"%s\"", SAFE_CSTR(path));
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    result = file_system->chdir(path);
  } else {
    DANGERF("chdir: not supported");
    errno = ENOSYS;
  }
  ARC_STRACE_RETURN(result);
}

int __wrap_chown(const char* path, uid_t owner, gid_t group) {
  ARC_STRACE_ENTER("chown", "\"%s\", %u, %u", SAFE_CSTR(path), owner, group);
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->chown(path, owner, group);
  else
    errno = ENOSYS;
  ARC_STRACE_RETURN(result);
}

// Wrap this just for ARC strace.
int __wrap_closedir(DIR* dirp) {
  ARC_STRACE_ENTER("closedir", "%d, %p", PRETIFY_DIRP(dirp));
  int result = closedir(dirp);
  ARC_STRACE_RETURN(result);
}

// Wrap this just for ARC strace.
int __wrap_dirfd(DIR* dirp) {
  ARC_STRACE_ENTER("dirfd", "%p", dirp);
  int result = dirfd(dirp);
  ARC_STRACE_RETURN(result);
}

int __wrap_dlclose(void* handle) {
  ARC_STRACE_ENTER("dlclose", "%p \"%s\"",
                   handle, arc::GetDlsymHandleStr(handle).c_str());
  int result = dlclose(handle);
  if (!result)
    ARC_STRACE_UNREGISTER_DSO_HANDLE(handle);
  // false since dlclose never sets errno.
  ARC_STRACE_RETURN_INT(result, false);
}

void* __wrap_dlopen(const char* filename, int flag) {
  ARC_STRACE_ENTER("dlopen", "\"%s\", %s",
                   SAFE_CSTR(filename),
                   arc::GetDlopenFlagStr(flag).c_str());
  // dlopen is known to be slow under NaCl.
  TRACE_EVENT2(ARC_TRACE_CATEGORY, "wrap_dlopen",
               "filename", TRACE_STR_COPY(SAFE_CSTR(filename)),
               "flag", flag);
  if (filename && (
      (filename[0] != '/' && arc::IsStaticallyLinkedSharedObject(filename)) ||
      (filename[0] == '/' && arc::IsStaticallyLinkedSharedObject(
          StripSystemLibPrefix(filename))))) {
    // ARC statically links some libraries into the main
    // binary. When an app dlopen such library, we should return the
    // handle of the main binary so that apps can find symbols.
    // TODO(crbug.com/400947): Remove this temporary hack once we have stopped
    //                         converting shared objects to archives.
    filename = NULL;
  }
  void* result = dlopen(filename, flag);
  if (result)
    ARC_STRACE_REGISTER_DSO_HANDLE(result, filename);

  // false since dlopen never sets errno.
  ARC_STRACE_RETURN_PTR(result, false);
}

void* __wrap_dlsym(void* handle, const char* symbol) {
  ARC_STRACE_ENTER("dlsym", "%p \"%s\", \"%s\"",
                   handle,
                   arc::GetDlsymHandleStr(handle).c_str(),
                   SAFE_CSTR(symbol));
  void* result = dlsym(handle, symbol);
  // false since dlsym never sets errno.
  ARC_STRACE_RETURN_PTR(result, false);
}

// Wrap this just for ARC strace.
DIR* __wrap_fdopendir(int fd) {
  ARC_STRACE_ENTER_FD("fdopendir", "%d", fd);
  DIR* dirp = fdopendir(fd);
  ARC_STRACE_RETURN_PTR(dirp, !dirp);
}

char* __wrap_getcwd(char* buf, size_t size) {
  ARC_STRACE_ENTER("getcwd", "%p, %zu", buf, size);
  char* result = NULL;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->getcwd(buf, size);
  else
    result = real_getcwd(buf, size);
  ARC_STRACE_REPORT("result=\"%s\"", SAFE_CSTR(result));
  ARC_STRACE_RETURN_PTR(result, false);
}

extern "C" {
IRT_WRAPPER(getdents, int fd, struct dirent* dirp, size_t count,
            size_t* nread) {
  // We intentionally use Bionic's dirent instead of NaCl's. See
  // bionic/libc/arch-nacl/syscalls/getdents.c for detail.
  ARC_STRACE_ENTER_FD("getdents", "%d, %p, %u, %p", fd, dirp, count, nread);
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->getdents(fd, dirp, count);
  else
    errno = ENOSYS;
  if (result >= 0) {
    *nread = result;
    ARC_STRACE_REPORT("nread=\"%zu\"", *nread);
  }
  ARC_STRACE_RETURN_IRT_WRAPPER(result >= 0 ? 0 : errno);
}

IRT_WRAPPER(getcwd, char* buf, size_t size) {
  return __wrap_getcwd(buf, size) ? 0 : errno;
}
}  // extern "C"

IRT_WRAPPER(lstat, const char* path, struct nacl_abi_stat* buf) {
  ARC_STRACE_ENTER("lstat", "\"%s\", %p",
                   SAFE_CSTR(path), buf);
  int result;
  struct stat st;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    result = file_system->lstat(path, &st);
  } else {
    std::string newpath(path);
    result = real_lstat(newpath.c_str(), &st);
  }
  if (result == -1) {
    if (errno != ENOENT) {
      DANGERF("path=%s: %s", SAFE_CSTR(path), safe_strerror(errno).c_str());
    }
  } else {
    StatToNaClAbiStat(&st, buf);
    ARC_STRACE_REPORT("buf=%s", arc::GetNaClAbiStatStr(buf).c_str());
  }
  ARC_STRACE_RETURN_IRT_WRAPPER(result == 0 ? 0 : errno);
}

IRT_WRAPPER(mkdir, const char* pathname, mode_t mode) {
  ARC_STRACE_ENTER("mkdir", "\"%s\", 0%o", SAFE_CSTR(pathname), mode);
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->mkdir(pathname, mode);
  else
    result = real_mkdir(pathname, mode);
  if (result == -1 && errno != EEXIST) {
    DANGERF("path=%s mode=%d: %s",
            SAFE_CSTR(pathname), mode, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN_IRT_WRAPPER(result == 0 ? 0 : errno);
}

int __wrap_open(const char* pathname, int flags, ...) {
  va_list argp;
  va_start(argp, flags);
  mode_t mode = 0;
  if (flags & O_CREAT) {
    // Passing mode_t to va_arg with bionic makes compile fail.
    // As bionic's mode_t is short, the value is promoted when it was
    // passed to this vaarg function and fetching it as a short value
    // is not valid. This definition can be bad if mode_t is a 64bit
    // value, but such environment might not exist.
    COMPILE_ASSERT(sizeof(mode) <= sizeof(int),  // NOLINT(runtime/sizeof)
                   mode_t_is_too_big);
    mode = va_arg(argp, int);
  }
  va_end(argp);

  ARC_STRACE_ENTER("open", "\"%s\", %s, 0%o",
                   SAFE_CSTR(pathname),
                   arc::GetOpenFlagStr(flags).c_str(), mode);
  int fd = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system &&
      arc::IsStaticallyLinkedSharedObject(StripSystemLibPrefix(pathname))) {
    // CtsSecurityTest verifies some libraries are ELF format. To pass that
    // check, returns FD of runnable-ld.so instead.
    // TODO(crbug.com/400947): Remove this temporary hack once we have stopped
    //                         converting shared objects to archives.
    ALOGE("open is called for %s. Opening runnable-ld.so instead.", pathname);
    fd = file_system->open("/system/lib/runnable-ld.so", flags, mode);
  } else if (file_system) {
    fd = file_system->open(pathname, flags, mode);
  } else {
    fd = real_open(pathname, flags, mode);
  }
  if (fd == -1 && errno != ENOENT) {
    DANGERF("pathname=%s flags=%d: %s",
            SAFE_CSTR(pathname), flags, safe_strerror(errno).c_str());
  }
  ARC_STRACE_REGISTER_FD(fd, SAFE_CSTR(pathname));
  ARC_STRACE_RETURN(fd);
}

// Wrap this just for ARC strace.
DIR* __wrap_opendir(const char* name) {
  ARC_STRACE_ENTER("opendir", "%s", SAFE_CSTR(name));
  DIR* dirp = opendir(name);
  ARC_STRACE_RETURN_PTR(dirp, !dirp);
}

// Wrap this just for ARC strace.
struct dirent* __wrap_readdir(DIR* dirp) {
  ARC_STRACE_ENTER_FD("readdir", "%d, %p", PRETIFY_DIRP(dirp));
  struct dirent* ent = readdir(dirp);  // NOLINT(runtime/threadsafe_fn)
  ARC_STRACE_RETURN_PTR(ent, false);
}

// Wrap this just for ARC strace.
int __wrap_readdir_r(DIR* dirp, struct dirent* entry, struct dirent** ents) {
  ARC_STRACE_ENTER_FD("readdir_r", "%d, %p, %p, %p",
                      PRETIFY_DIRP(dirp), entry, ents);
  int result = readdir_r(dirp, entry, ents);
  ARC_STRACE_RETURN(result);
}

ssize_t __wrap_readlink(const char* path, char* buf, size_t bufsiz) {
  ARC_STRACE_ENTER("readlink", "\"%s\", %p, %zu",
                   SAFE_CSTR(path), buf, bufsiz);
  ssize_t result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->readlink(path, buf, bufsiz);
  else
    result = readlink(path, buf, bufsiz);
  if (result == -1) {
    DANGERF("path=%s bufsiz=%zu: %s",
            SAFE_CSTR(path), bufsiz, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

char* __wrap_realpath(const char* path, char* resolved_path) {
  ARC_STRACE_ENTER("realpath", "\"%s\", %p", SAFE_CSTR(path), resolved_path);
  char* result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->realpath(path, resolved_path);
  else
    result = realpath(path, resolved_path);
  if (!result) {
    DANGERF("path=%s resolved_path=%p: %s",
            SAFE_CSTR(path), resolved_path, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN_PTR(result, !result);
}

int __wrap_remove(const char* pathname) {
  ARC_STRACE_ENTER("remove", "\"%s\"", SAFE_CSTR(pathname));
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->remove(pathname);
  else
    result = remove(pathname);
  if (result == -1 && errno != ENOENT)
    DANGERF("path=%s: %s", SAFE_CSTR(pathname), safe_strerror(errno).c_str());
  ARC_STRACE_RETURN(result);
}

int __wrap_rename(const char* oldpath, const char* newpath) {
  ARC_STRACE_ENTER("rename", "\"%s\", \"%s\"",
                   SAFE_CSTR(oldpath), SAFE_CSTR(newpath));
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->rename(oldpath, newpath);
  else
    result = rename(oldpath, newpath);
  if (result == -1) {
    DANGERF("oldpath=%s newpath=%s: %s",
            SAFE_CSTR(oldpath), SAFE_CSTR(newpath),
            safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

// Wrap this just for ARC strace.
void __wrap_rewinddir(DIR* dirp) {
  ARC_STRACE_ENTER_FD("rewinddir", "%d, %p", PRETIFY_DIRP(dirp));
  rewinddir(dirp);
  ARC_STRACE_RETURN_VOID();
}

// Wrap this just for ARC strace.
int __wrap_scandir(
    const char* dirp, struct dirent*** namelist,
    int (*filter)(const struct dirent*),
    int (*compar)(const struct dirent**, const struct dirent**)) {
  ARC_STRACE_ENTER("scandir", "%s, %p, %p, %p",
                   SAFE_CSTR(dirp), namelist, filter, compar);
  int result = scandir(dirp, namelist, filter, compar);
  ARC_STRACE_RETURN(result);
}

int __wrap_statfs(const char* pathname, struct statfs* stat) {
  ARC_STRACE_ENTER("statfs", "\"%s\", %p", SAFE_CSTR(pathname), stat);
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->statfs(pathname, stat);
  else
    result = statfs(pathname, stat);
  if (result == -1 && errno != ENOENT)
    DANGERF("path=%s: %s", SAFE_CSTR(pathname), safe_strerror(errno).c_str());
  ARC_STRACE_REPORT(
      "stat={type=%lld bsize=%lld blocks=%llu bfree=%llu bavail=%llu "
      "files=%llu ffree=%llu fsid=%d,%d namelen=%lld frsize=%lld "
      // Note: Unlike glibc and older Bionic, f_spare[] in Bionic 4.4 has
      // only 4 elements, not 5.
      "spare=%lld,%lld,%lld,%lld}",
      static_cast<int64_t>(stat->f_type),
      static_cast<int64_t>(stat->f_bsize),
      stat->f_blocks, stat->f_bfree,
      stat->f_bavail, stat->f_files, stat->f_ffree,
      stat->f_fsid.__val[0], stat->f_fsid.__val[1],
      static_cast<int64_t>(stat->f_namelen),
      static_cast<int64_t>(stat->f_frsize),
      static_cast<int64_t>(stat->f_spare[0]),
      static_cast<int64_t>(stat->f_spare[1]),
      static_cast<int64_t>(stat->f_spare[2]),
      static_cast<int64_t>(stat->f_spare[3]));
  ARC_STRACE_RETURN(result);
}

int __wrap_statvfs(const char* pathname, struct statvfs* stat) {
  ARC_STRACE_ENTER("statvfs", "\"%s\", %p", SAFE_CSTR(pathname), stat);
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->statvfs(pathname, stat);
  else
    result = statvfs(pathname, stat);
  ARC_STRACE_REPORT(
      "stat={bsize=%llu frsize=%llu blocks=%llu bfree=%llu bavail=%llu "
      "files=%llu ffree=%llu favail=%llu fsid=%llu flag=%llu namemax=%llu}",
      static_cast<int64_t>(stat->f_bsize),
      static_cast<int64_t>(stat->f_frsize),
      static_cast<int64_t>(stat->f_blocks),
      static_cast<int64_t>(stat->f_bfree),
      static_cast<int64_t>(stat->f_bavail),
      static_cast<int64_t>(stat->f_files),
      static_cast<int64_t>(stat->f_ffree),
      static_cast<int64_t>(stat->f_favail),
      static_cast<int64_t>(stat->f_fsid),
      static_cast<int64_t>(stat->f_flag),
      static_cast<int64_t>(stat->f_namemax));
  ARC_STRACE_RETURN(result);
}

int __wrap_symlink(const char* oldp, const char* newp) {
  ARC_STRACE_ENTER("symlink", "\"%s\", \"%s\"",
                   SAFE_CSTR(oldp), SAFE_CSTR(newp));
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    result = file_system->symlink(oldp, newp);
  } else {
    errno = EPERM;
    result = -1;
  }
  if (!result)
    ALOGE("Added a non-persistent symlink from %s to %s", newp, oldp);
  ARC_STRACE_RETURN(result);
}

template <typename OffsetType>
static int TruncateImpl(const char* pathname, OffsetType length) {
  ARC_STRACE_ENTER("truncate", "\"%s\", %lld",
                   SAFE_CSTR(pathname), static_cast<int64_t>(length));
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->truncate(pathname, length);
  else
    errno = ENOSYS;
  if (result == -1) {
    DANGERF("path=%s length=%lld: %s",
            SAFE_CSTR(pathname), static_cast<int64_t>(length),
            safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

int __wrap_truncate(const char* pathname, off_t length) {
  return TruncateImpl(pathname, length);
}

int __wrap_truncate64(const char* pathname, off64_t length) {
  return TruncateImpl(pathname, length);
}

int __wrap_unlink(const char* pathname) {
  ARC_STRACE_ENTER("unlink", "\"%s\"", SAFE_CSTR(pathname));
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->unlink(pathname);
  else
    result = unlink(pathname);
  if (result == -1 && errno != ENOENT)
    DANGERF("path=%s: %s", SAFE_CSTR(pathname), safe_strerror(errno).c_str());
  ARC_STRACE_RETURN(result);
}

int __wrap_utimes(const char* filename, const struct timeval times[2]) {
  ARC_STRACE_ENTER("utimes", "\"%s\", %p", SAFE_CSTR(filename), times);
  int result = 0;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    result = file_system->utimes(filename, times);
  } else {
    DANGERF("utimes: filename=%s times=%p", SAFE_CSTR(filename), times);
    // NB: Returning -1 breaks some NDK apps.
  }
  if (result == -1 && errno != ENOENT) {
    DANGERF("path=%s: %s",
            SAFE_CSTR(filename), safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

IRT_WRAPPER(stat, const char* pathname, struct nacl_abi_stat* buf) {
  ARC_STRACE_ENTER("stat", "\"%s\", %p", SAFE_CSTR(pathname), buf);
  int result;
  struct stat st;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->stat(pathname, &st);
  else
    result = real_stat(pathname, &st);
  if (result == -1) {
    if (errno != ENOENT) {
      DANGERF("path=%s: %s", SAFE_CSTR(pathname), safe_strerror(errno).c_str());
    }
  } else {
    StatToNaClAbiStat(&st, buf);
    ARC_STRACE_REPORT("buf=%s", arc::GetNaClAbiStatStr(buf).c_str());
  }
  ARC_STRACE_RETURN_IRT_WRAPPER(result == 0 ? 0 : errno);
}

int __wrap_close(int fd) {
  ARC_STRACE_ENTER_FD("close", "%d", fd);
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->close(fd);
  else
    result = real_close(fd);
  if (result == -1) {
    // Closing with a bad file descriptor may be indicating a double
    // close, which is more dangerous than it seems since everything
    // shares one address space and we reuse file descriptors quickly.
    // It can cause a newly allocated file descriptor in another
    // thread to now be unallocated.
    // We just use DANGERF() instead of LOG_FATAL_IF() because
    // cts.CtsNetTestCases:android.net.rtp.cts.AudioStreamTest#testDoubleRelease
    // hits the case.
    if (errno == EBADF)
      DANGERF("Close of bad file descriptor may indicate double close");
    DANGERF("fd=%d: %s", fd, safe_strerror(errno).c_str());
  }
  if (!result)
    ARC_STRACE_UNREGISTER_FD(fd);
  ARC_STRACE_RETURN(result);
}

int __wrap_creat(const char* pathname, mode_t mode) {
  ARC_STRACE_ENTER("creat", "\"%s\", 0%o", SAFE_CSTR(pathname), mode);
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    result = file_system->open(pathname, O_CREAT | O_WRONLY | O_TRUNC,
                                        mode);
  } else {
    errno = ENOSYS;
  }
  ARC_STRACE_REGISTER_FD(result, SAFE_CSTR(pathname));
  ARC_STRACE_RETURN(result);
}

IRT_WRAPPER(dup, int oldfd, int* newfd) {
  ARC_STRACE_ENTER_FD("dup", "%d", oldfd);
  int fd = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    fd = file_system->dup(oldfd);
  } else {
    fd = dup(oldfd);
  }
  if (fd == -1)
    DANGERF("oldfd=%d: %s", oldfd, safe_strerror(errno).c_str());
  *newfd = fd;
  ARC_STRACE_RETURN_IRT_WRAPPER(fd >= 0 ? 0 : errno);
}

IRT_WRAPPER(dup2, int oldfd, int newfd) {
  ARC_STRACE_ENTER_FD("dup2", "%d, %d", oldfd, newfd);
  int fd = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system) {
    fd = file_system->dup2(oldfd, newfd);
  } else {
    DANGERF("oldfd=%d newfd=%d", oldfd, newfd);
    errno = EBADF;
  }
  if (fd == -1) {
    DANGERF("oldfd=%d newfd=%d: %s",
            oldfd, newfd, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN_IRT_WRAPPER(fd >= 0 ? 0 : errno);
}

// Although Linux has fcntl64 syscall, user code does not use it directly.
// Therefore, we do not have to wrap the 64bit variant.
int __wrap_fcntl(int fd, int cmd, ...) {
  // TODO(crbug.com/241955): Support variable args?
  ARC_STRACE_ENTER_FD("fcntl", "%d, %s, ...",
                      fd, arc::GetFcntlCommandStr(cmd).c_str());
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();

  if (file_system) {
    va_list ap;
    va_start(ap, cmd);
    result = file_system->fcntl(fd, cmd, ap);
    va_end(ap);
  } else {
    DANGER();
    errno = EINVAL;
  }

  if (result == -1)
    DANGERF("fd=%d cmd=%d: %s", fd, cmd, safe_strerror(errno).c_str());
  ARC_STRACE_RETURN(result);
}

int __wrap_fdatasync(int fd) {
  ARC_STRACE_ENTER_FD("fdatasync", "%d", fd);
  int result = 0;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->fdatasync(fd);
  ARC_STRACE_RETURN(result);
}

int __wrap_fsync(int fd) {
  ARC_STRACE_ENTER_FD("fsync", "%d", fd);
  int result = 0;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->fsync(fd);
  ARC_STRACE_RETURN(result);
}

IRT_WRAPPER(fstat, int fd, struct nacl_abi_stat *buf) {
  ARC_STRACE_ENTER_FD("fstat", "%d, %p", fd, buf);
  int result;
  struct stat st;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->fstat(fd, &st);
  else
    result = real_fstat(fd, &st);
  if (result) {
    result = errno;
    DANGERF("fd=%d: %s", fd, safe_strerror(errno).c_str());
  } else {
    StatToNaClAbiStat(&st, buf);
    ARC_STRACE_REPORT("buf=%s", arc::GetNaClAbiStatStr(buf).c_str());
  }
  ARC_STRACE_RETURN_IRT_WRAPPER(result);
}

template <typename OffsetType>
static int FtruncateImpl(int fd, OffsetType length) {
  ARC_STRACE_ENTER_FD("ftruncate", "%d, %lld",
                      fd, static_cast<int64_t>(length));
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->ftruncate(fd, length);
  else
    result = ftruncate64(fd, length);
  if (result == -1) {
    DANGERF("fd=%d length=%lld: %s", fd, static_cast<int64_t>(length),
            safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

int __wrap_ftruncate(int fd, off_t length) {
  return FtruncateImpl(fd, length);
}

int __wrap_ftruncate64(int fd, off64_t length) {
  return FtruncateImpl(fd, length);
}

int __wrap_ioctl(int fd, int request, ...) {
  // TODO(crbug.com/241955): Pretty-print variable args?
  ARC_STRACE_ENTER_FD("ioctl", "%d, %s, ...",
                      fd, arc::GetIoctlRequestStr(request).c_str());
  int result = -1;
  va_list ap;
  va_start(ap, request);
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->ioctl(fd, request, ap);
  else
    errno = EINVAL;
  va_end(ap);
  if (result == -1)
    DANGERF("fd=%d request=%d: %s", fd, request, safe_strerror(errno).c_str());
  ARC_STRACE_RETURN(result);
}

template <typename OffsetType>
static OffsetType LseekImpl(int fd, OffsetType offset, int whence) {
  ARC_STRACE_ENTER_FD("lseek", "%d, %lld, %s",
                      fd, static_cast<int64_t>(offset),
                      arc::GetLseekWhenceStr(whence).c_str());
  OffsetType result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->lseek(fd, offset, whence);
  else
    result = real_lseek64(fd, offset, whence);
  if (result == -1) {
    DANGERF("fd=%d offset=%lld whence=%d: %s",
            fd, static_cast<int64_t>(offset), whence,
            safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

off64_t __wrap_lseek64(int fd, off64_t offset, int whence) {
  return LseekImpl(fd, offset, whence);
}

int __wrap_madvise(void* addr, size_t length, int advice) {
  ARC_STRACE_ENTER("madvise", "%p, %zu, %s", addr, length,
                   arc::GetMadviseAdviceStr(advice).c_str());
  int result = -1;
  int saved_errno = errno;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->madvise(addr, length, advice);
  if (result != 0) {
    DANGERF("errno=%d addr=%p length=%zu advice=%d: %s",
            errno, addr, length, advice, safe_strerror(errno).c_str());
    if (!file_system || (errno == ENOSYS && advice != MADV_REMOVE)) {
      // TODO(crbug.com/362862): Stop special-casing ENOSYS once the bug is
      // fixed.
      // Note: We should call mprotect IRT here once the IRT is supported and
      // crbug.com/36282 is still open.
      errno = saved_errno;
      result = 0;
    }
  }
  ARC_STRACE_RETURN(result);
}

// NB: Do NOT use off64_t for |offset|. It is not compatible with Bionic.
// Bionic's mmap() does not support large file, and it does not provide
// mmap64() either.
void* __wrap_mmap(
    void* addr, size_t length, int prot, int flags, int fd, off_t offset) {
  ARC_STRACE_ENTER("mmap", "%p, %zu(0x%zx), %s, %s, %d \"%s\", 0x%llx",
                   addr, length, length,
                   arc::GetMmapProtStr(prot).c_str(),
                   arc::GetMmapFlagStr(flags).c_str(),
                   fd, arc::GetFdStr(fd).c_str(),
                   static_cast<int64_t>(offset));
  // WRITE + EXEC mmap is not allowed.
  if ((prot & PROT_WRITE) && (prot & PROT_EXEC)) {
    ALOGE("mmap with PROT_WRITE + PROT_EXEC! "
          "addr=%p length=%zu prot=%d flags=%d fd=%d offset=%lld",
          addr, length, prot, flags, fd, static_cast<int64_t>(offset));
    // However, with Bare Metal, our JIT engines or NDK apps may want WX mmap.
#if defined(__native_client__)
    ALOG_ASSERT(false, "PROT_WRITE + PROT_EXEC mmap is not allowed");
    // This mmap call gracefully fails in release build.
#endif
  } else if (prot & PROT_EXEC) {
    // There are two reasons we will see PROT_EXEC:
    // - The Bionic loader use PROT_EXEC to map dlopen-ed files. Note
    //   that we inject posix_translation based file operations to the
    //   Bionic loader. See src/common/dlfcn_injection.cc for detail.
    // - On Bare Metal ARM, v8 uses PROT_EXEC to run JIT-ed code directly.
    //
    // But it is still an interesting event. So, we log this by ALOGI.
    ALOGI("mmap with PROT_EXEC! "
          "addr=%p length=%zu prot=%d flags=%d fd=%d offset=%lld",
          addr, length, prot, flags, fd, static_cast<int64_t>(offset));
  }

  if (prot & ~(PROT_READ | PROT_WRITE | PROT_EXEC))
    ALOGE("mmap with an unorthodox prot: %d", prot);
  // We do not support MAP_NORESERVE but this flag is used often and
  // we can safely ignore it.
  const int supported_flag = (MAP_SHARED | MAP_PRIVATE | MAP_FIXED |
                              MAP_ANONYMOUS | MAP_NORESERVE);
  if (flags & ~supported_flag)
    ALOGE("mmap with an unorthodox flags: %d", flags);

  void* result = MAP_FAILED;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->mmap(addr, length, prot, flags, fd, offset);
  else
    result = mmap(addr, length, prot, flags, fd, offset);
#if defined(USE_VERBOSE_MEMORY_VIEWER)
  if (result != MAP_FAILED)
    arc::MemoryMappingBacktraceMap::GetInstance()->
        MapCurrentStackFrame(result, length);
#endif

  // Overwrite |errno| to emulate Bionic's behavior. See the comment in
  // mods/android/bionic/libc/unistd/mmap.c.
  if (result && (flags & (MAP_PRIVATE | MAP_ANONYMOUS))) {
    if ((result != MAP_FAILED) &&
        (flags & MAP_PRIVATE) && (flags & MAP_ANONYMOUS)) {
      // In this case, madvise(MADV_MERGEABLE) in mmap.c will likely succeed.
      // Do not update |errno|.
    } else {
      // Overwrite |errno| with EINVAL even when |result| points to a valid
      // address.
      errno = EINVAL;
    }
  }

  if (result == MAP_FAILED) {
    DANGERF("addr=%p length=%zu prot=%d flags=%d fd=%d offset=%lld: %s",
            addr, length, prot, flags, fd, static_cast<int64_t>(offset),
            safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN_PTR(result, result == MAP_FAILED);
}

int __wrap_mprotect(const void* addr, size_t len, int prot) {
  ARC_STRACE_ENTER("mprotect", "%p, %zu(0x%zx), %s", addr, len, len,
                   arc::GetMmapProtStr(prot).c_str());
#if defined(__native_client__)
  // PROT_EXEC mprotect is not allowed on NaCl, where all executable
  // pages are validated through special APIs.
  if (prot & PROT_EXEC) {
    ALOGE("mprotect with PROT_EXEC! addr=%p length=%zu prot=%d",
          addr, len, prot);
    ALOG_ASSERT(false, "mprotect with PROT_EXEC is not allowed");
    // This mmap call gracefully fails in release build.
  }
#else
  if ((prot & PROT_WRITE) && (prot & PROT_EXEC)) {
    // TODO(crbug.com/365349): Currently, it seems Dalvik JIT is
    // enabled on Bare Metal ARM. Disable it and increase the
    // verbosity of this ALOG.
    ALOGV("mprotect with PROT_WRITE + PROT_EXEC! addr=%p length=%zu prot=%d",
          addr, len, prot);
  }
#endif

  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  const int errno_orig = errno;
  // mprotect in Bionic defines the first argument is const void*, but
  // POSIX does it as void*. We use const void* for wrap, and use void* for
  // posix_translation.
  if (file_system)
    result = file_system->mprotect(const_cast<void*>(addr), len, prot);
  if (!file_system || (result != 0 && errno == ENOSYS)) {
    // TODO(crbug.com/362862): Stop falling back to real mprotect on ENOSYS and
    // do this only for unit tests.
    ARC_STRACE_REPORT("falling back to real mprotect");
    result = mprotect(addr, len, prot);
    if (!result && errno == ENOSYS)
      errno = errno_orig;  // restore |errno| overwritten by posix_translation
  }
  ARC_STRACE_RETURN(result);
}

int __wrap_munmap(void* addr, size_t length) {
  ARC_STRACE_ENTER("munmap", "%p, %zu(0x%zx)", addr, length, length);
  ARC_STRACE_REPORT("RANGE (%p-%p)",
                    addr, reinterpret_cast<char*>(addr) + length);
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  const int errno_orig = errno;
  if (file_system)
    result = file_system->munmap(addr, length);
  if (!file_system || (result != 0 && errno == ENOSYS)) {
    // TODO(crbug.com/362862): Stop falling back to real munmap on ENOSYS and
    // do this only for unit tests.
    ARC_STRACE_REPORT("falling back to real munmap");
    result = munmap(addr, length);
    if (!result && errno == ENOSYS)
      errno = errno_orig;  // restore |errno| overwritten by posix_translation
  }
#if defined(USE_VERBOSE_MEMORY_VIEWER)
  if (result == 0)
    arc::MemoryMappingBacktraceMap::GetInstance()->Unmap(addr, length);
#endif
  ARC_STRACE_RETURN(result);
}

int __wrap_poll(struct pollfd* fds, nfds_t nfds, int timeout) {
  ARC_STRACE_ENTER("poll", "%p, %lld, %d",
                   fds, static_cast<int64_t>(nfds), timeout);
  if (arc::StraceEnabled()) {
    for (nfds_t i = 0; i < nfds; ++i) {
      ARC_STRACE_REPORT("polling fd %d \"%s\" for %s",
                        fds[i].fd, arc::GetFdStr(fds[i].fd).c_str(),
                        arc::GetPollEventStr(fds[i].events).c_str());
    }
  }
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->poll(fds, nfds, timeout);
  else
    result = poll(fds, nfds, timeout);
  if (result == -1) {
    DANGERF("fds=%p nfds=%u timeout=%d[ms]: %s",
            fds, nfds, timeout, safe_strerror(errno).c_str());
  } else if (arc::StraceEnabled()) {
    for (int i = 0; i < result; ++i) {
      if (!fds[i].revents)
        continue;
      ARC_STRACE_REPORT("fd %d \"%s\" is ready for %s",
                        fds[i].fd, arc::GetFdStr(fds[i].fd).c_str(),
                        arc::GetPollEventStr(fds[i].revents).c_str());
    }
  }
  ARC_STRACE_RETURN(result);
}

template <typename OffsetType>
static ssize_t PreadImpl(int fd, void* buf, size_t count, OffsetType offset) {
  ARC_STRACE_ENTER_FD("pread", "%d, %p, %zu, %lld",
                      fd, buf, count, static_cast<int64_t>(offset));
  ssize_t result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->pread(fd, buf, count, offset);
  else
    result = pread64(fd, buf, count, offset);
  if (result == -1) {
    DANGERF("fd=%d buf=%p count=%zu offset=%lld: %s",
            fd, buf, count, static_cast<int64_t>(offset),
            safe_strerror(errno).c_str());
  }
  if (result >= 0)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, result).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t __wrap_pread(int fd, void* buf, size_t count, off_t offset) {
  return PreadImpl(fd, buf, count, offset);
}

ssize_t __wrap_pread64(int fd, void* buf, size_t count, off64_t offset) {
  return PreadImpl(fd, buf, count, offset);
}

template <typename OffsetType>
static ssize_t PwriteImpl(int fd, const void* buf, size_t count,
                          OffsetType offset) {
  ARC_STRACE_ENTER_FD("pwrite", "%d, %p, %zu, %lld",
                      fd, buf, count, static_cast<int64_t>(offset));
  ssize_t result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->pwrite(fd, buf, count, offset);
  else
    result = pwrite64(fd, buf, count, offset);
  if (result == -1) {
    DANGERF("fd=%d buf=%p count=%zu offset=%lld: %s",
            fd, buf, count, static_cast<int64_t>(offset),
            safe_strerror(errno).c_str());
  }
  if (errno != EFAULT)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, count).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t __wrap_pwrite(int fd, const void* buf, size_t count, off_t offset) {
  return PwriteImpl(fd, buf, count, offset);
}

ssize_t __wrap_pwrite64(int fd, const void* buf, size_t count,
                        off64_t offset) {
  return PwriteImpl(fd, buf, count, offset);
}

ssize_t __wrap_read(int fd, void* buf, size_t count) {
  ARC_STRACE_ENTER_FD("read", "%d, %p, %zu", fd, buf, count);
  ssize_t result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->read(fd, buf, count);
  else
    result = real_read(fd, buf, count);
  if (result == -1 && errno != EAGAIN) {
    DANGERF("fd=%d buf=%p count=%zu: %s",
            fd, buf, count, safe_strerror(errno).c_str());
  }
  if (result >= 0)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, result).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t __wrap_readv(int fd, const struct iovec* iov, int iovcnt) {
  // TODO(crbug.com/241955): Stringify |iov|?
  ARC_STRACE_ENTER_FD("readv", "%d, %p, %d", fd, iov, iovcnt);
  ssize_t result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->readv(fd, iov, iovcnt);
  else
    result = readv(fd, iov, iovcnt);
  if (result == -1) {
    DANGERF("fd=%d iov=%p iovcnt=%d: %s",
            fd, iov, iovcnt, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

int __wrap_rmdir(const char* pathname) {
  ARC_STRACE_ENTER("rmdir", "\"%s\"", SAFE_CSTR(pathname));
  int result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->rmdir(pathname);
  else
    result = rmdir(pathname);
  if (result == -1 && errno != ENOENT)
    DANGERF("path=%s: %s", SAFE_CSTR(pathname), safe_strerror(errno).c_str());
  ARC_STRACE_RETURN(result);
}

int __wrap_utime(const char* filename, const struct utimbuf* times) {
  ARC_STRACE_ENTER("utime", "\"%s\", %p", SAFE_CSTR(filename), times);
  int result = -1;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->utime(filename, times);
  else
    errno = ENOSYS;
  if (result == -1 && errno != ENOENT) {
    DANGERF("path=%s: %s",
            SAFE_CSTR(filename), safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

ssize_t __wrap_write(int fd, const void* buf, size_t count) {
  const int wrap_write_nest_count = g_wrap_write_nest_count.Get();
  if (wrap_write_nest_count) {
    // Calling write() to a stdio descriptor inside __wrap_write may cause
    // infinite wrap loop. Here, we show a warning, and just return.
    // It may happen when a chromium base DCHECK fails, e.g. inside AutoLock.
    ALOGE("write() for stdio is called inside __wrap_write(): "
          "fd=%d count=%zu buf=%p msg='%s'",
          fd, count, buf,
          std::string(static_cast<const char*>(buf), count).c_str());
    return 0;
  } else {
    ARC_STRACE_ENTER_FD("write", "%d, %p, %zu", fd, buf, count);
    g_wrap_write_nest_count.Set(wrap_write_nest_count + 1);
    int result;
    VirtualFileSystem* file_system = GetFileSystem();
    if (file_system)
      result = file_system->write(fd, buf, count);
    else
      result = real_write(fd, buf, count);
    if (errno != EFAULT)
      ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, count).c_str());
    g_wrap_write_nest_count.Set(wrap_write_nest_count);
    if (result == -1) {
      DANGERF("fd=%d buf=%p count=%zu: %s",
              fd, buf, count, safe_strerror(errno).c_str());
    }
    ARC_STRACE_RETURN(result);
  }
}

ssize_t __wrap_writev(int fd, const struct iovec* iov, int iovcnt) {
  // TODO(crbug.com/241955): Output the first N bytes in |iov|.
  // TODO(crbug.com/241955): Stringify |iov|?
  ARC_STRACE_ENTER_FD("writev", "%d, %p, %d", fd, iov, iovcnt);
  ssize_t result;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    result = file_system->writev(fd, iov, iovcnt);
  else
    result = writev(fd, iov, iovcnt);
  if (result == -1) {
    DANGERF("fd=%d iov=%p iovcnt=%d: %s",
            fd, iov, iovcnt, safe_strerror(errno).c_str());
  }
  ARC_STRACE_RETURN(result);
}

mode_t __wrap_umask(mode_t mask) {
  ARC_STRACE_ENTER("umask", "0%o", mask);
  mode_t return_umask;
  VirtualFileSystem* file_system = GetFileSystem();
  if (file_system)
    return_umask = file_system->umask(mask);
  else
    return_umask = umask(mask);
  ARC_STRACE_RETURN(return_umask);
}

extern "C" {
// The following is an example call stach when close() is called:
//
// our_function_that_calls_close()
//   close()  // in Bionic
//     __nacl_irt_close()  // function pointer call
//        __nacl_irt_close_wrap()  // this function
//          __wrap_close()  // in file_wrap.cc
//             FileSystem::close()  // in posix_translation
//
// Also note that code in posix_translation/ is always able to call into the
// original IRT by calling real_close() defined in file_wrap.cc.
IRT_WRAPPER(close, int fd) {
  int result = __wrap_close(fd);
  return !result ? 0 : errno;
}

// See native_client/src/trusted/service_runtime/include/sys/fcntl.h
#define NACL_ABI_O_SYNC 010000

IRT_WRAPPER(open, const char *pathname, int oflag, mode_t cmode, int *newfd) {
  // |oflag| is mostly compatible between NaCl and Bionic, O_SYNC is
  // the only exception.
  int bionic_oflag = oflag;
  if ((bionic_oflag & NACL_ABI_O_SYNC)) {
    bionic_oflag &= ~NACL_ABI_O_SYNC;
    bionic_oflag |= O_SYNC;
  }
  *newfd = __wrap_open(pathname, bionic_oflag, cmode);
  return *newfd >= 0 ? 0 : errno;
}

IRT_WRAPPER(read, int fd, void *buf, size_t count, size_t *nread) {
  ssize_t result = __wrap_read(fd, buf, count);
  *nread = result;
  return result >= 0 ? 0 : errno;
}

IRT_WRAPPER(seek, int fd, off64_t offset, int whence, off64_t *new_offset) {
  *new_offset = __wrap_lseek64(fd, offset, whence);
  return *new_offset >= 0 ? 0 : errno;
}

IRT_WRAPPER(write, int fd, const void *buf, size_t count, size_t *nwrote) {
  ssize_t result = __wrap_write(fd, buf, count);
  *nwrote = result;
  return result >= 0 ? 0 : errno;
}

// We implement IRT wrappers using __wrap_* functions. As the wrap
// functions or posix_translation/ may call real functions, we
// define them using real IRT interfaces.

int real_close(int fd) {
  ALOG_ASSERT(__nacl_irt_close_real);
  int result = __nacl_irt_close_real(fd);
  if (result) {
    errno = result;
    return -1;
  }
  return 0;
}

int real_fstat(int fd, struct stat *buf) {
  ALOG_ASSERT(__nacl_irt_fstat_real);
  struct nacl_abi_stat nacl_buf;
  int result = __nacl_irt_fstat_real(fd, &nacl_buf);
  if (result) {
    errno = result;
    return -1;
  }
  NaClAbiStatToStat(&nacl_buf, buf);
  return 0;
}

char* real_getcwd(char *buf, size_t size) {
  ALOG_ASSERT(__nacl_irt_getcwd_real);
  // Note: If needed, you can implement it with __nacl_irt_getcwd_real in the
  // same way as android/bionic/libc/bionic/getcwd.cpp. __nacl_irt_getcwd_real
  // and __getcwd (in Bionic) has the same interface.
  ALOG_ASSERT(false, "not implemented");
  return NULL;
}

int real_lstat(const char *pathname, struct stat *buf) {
  ALOG_ASSERT(__nacl_irt_lstat_real);
  struct nacl_abi_stat nacl_buf;
  int result = __nacl_irt_lstat_real(pathname, &nacl_buf);
  if (result) {
    errno = result;
    return -1;
  }
  NaClAbiStatToStat(&nacl_buf, buf);
  return 0;
}

int real_mkdir(const char *pathname, mode_t mode) {
  ALOG_ASSERT(__nacl_irt_mkdir_real);
  int result = __nacl_irt_mkdir_real(pathname, mode);
  if (result) {
    errno = result;
    return -1;
  }
  return 0;
}

int real_open(const char *pathname, int oflag, mode_t cmode) {
  ALOG_ASSERT(__nacl_irt_open_real);
  int newfd;
  // |oflag| is mostly compatible between NaCl and Bionic, O_SYNC is
  // the only exception.
  int nacl_oflag = oflag;
  if ((nacl_oflag & O_SYNC)) {
    nacl_oflag &= ~O_SYNC;
    nacl_oflag |= NACL_ABI_O_SYNC;
  }
  int result = __nacl_irt_open_real(pathname, nacl_oflag, cmode, &newfd);
  if (result) {
    errno = result;
    return -1;
  }
  return newfd;
}

ssize_t real_read(int fd, void *buf, size_t count) {
  ALOG_ASSERT(__nacl_irt_read_real);
  size_t nread;
  int result = __nacl_irt_read_real(fd, buf, count, &nread);
  if (result) {
    errno = result;
    return -1;
  }
  return nread;
}

int real_stat(const char *pathname, struct stat *buf) {
  ALOG_ASSERT(__nacl_irt_stat_real);
  struct nacl_abi_stat nacl_buf;
  int result = __nacl_irt_stat_real(pathname, &nacl_buf);
  if (result) {
    errno = result;
    return -1;
  }
  NaClAbiStatToStat(&nacl_buf, buf);
  return 0;
}

off64_t real_lseek64(int fd, off64_t offset, int whence) {
  ALOG_ASSERT(__nacl_irt_seek_real);
  off64_t nacl_offset;
  int result = __nacl_irt_seek_real(fd, offset, whence, &nacl_offset);
  if (result) {
    errno = result;
    return -1;
  }
  return nacl_offset;
}

ssize_t real_write(int fd, const void *buf, size_t count) {
  ALOG_ASSERT(__nacl_irt_write_real);
  size_t nwrote;
  int result = __nacl_irt_write_real(fd, buf, count, &nwrote);
  if (result) {
    errno = result;
    return -1;
  }
  return nwrote;
}
}  // extern "C"

namespace {

void direct_stderr_write(const void* buf, size_t count) {
  ALOG_ASSERT(__nacl_irt_write_real);
  size_t nwrote;
  __nacl_irt_write_real(STDERR_FILENO, buf, count, &nwrote);
}

}  // namespace

namespace arc {

// The call stack gets complicated when IRT is hooked. See the comment near
// IRT_WRAPPER(close) for more details.
ARC_EXPORT void InitIRTHooks(bool pass_through) {
  // This function must be called by the main thread before the first
  // pthread_create() call is made. See the comment for g_pass_through_enabled
  // above.
  ALOG_ASSERT(!arc::ProcessEmulator::IsMultiThreaded());

  DO_WRAP(close);
  DO_WRAP(dup);
  DO_WRAP(dup2);
  DO_WRAP(fstat);
  DO_WRAP(getcwd);
  DO_WRAP(getdents);
  DO_WRAP(lstat);
  DO_WRAP(mkdir);
  DO_WRAP(open);
  DO_WRAP(read);
  DO_WRAP(seek);
  DO_WRAP(stat);
  DO_WRAP(write);

  g_pass_through_enabled = pass_through;

  // We have replaced __nacl_irt_* above. Then, we need to inject them
  // to the Bionic loader.
  InitDlfcnInjection();

  SetLogWriter(direct_stderr_write);
}

// This table is exported to higher levels to define how they should dispatch
// through to libc.
const LibcDispatchTable g_libc_dispatch_table = {
  real_close,
  real_fstat,
  real_lseek64,
  real_open,
  real_read,
  real_write,
};

}  // namespace arc
