// ARC MOD TRACK "third_party/nacl-glibc/sysdeps/nacl/mmap.c"

#include <sys/types.h>
#include <sys/mman.h>
#include <errno.h>

#include <irt_syscalls.h>
// ARC MOD BEGIN
#include <nacl_mman.h>
// ARC MOD END

// ARC MOD BEGIN
// Return void* instead of __ptr_t and rename __mmap to mmap64.
void* mmap64(void* addr, size_t len, int bionic_prot, int bionic_flags,
             int fd, off64_t offset) {
// ARC MOD END
  // ARC MOD BEGIN
  // Disallow mmap with both PROT_WRITE and PROT_EXEC so that we can
  // make sure only whitelisted code creates writable executable
  // pages. To create RWX pages, use arc::MprotectRWX explicitly.
  // TODO(hamaji): Write a test for this code path.
  if ((bionic_prot & PROT_WRITE) && (bionic_prot & PROT_EXEC)) {
    errno = EPERM;
    return MAP_FAILED;
  }
  int prot = 0;
  if (bionic_prot & PROT_READ)
    prot |= NACL_ABI_PROT_READ;
  if (bionic_prot & PROT_WRITE)
    prot |= NACL_ABI_PROT_WRITE;
  if (bionic_prot & PROT_EXEC)
    prot |= NACL_ABI_PROT_EXEC;
  int flags = 0;
  if (bionic_flags & MAP_SHARED)
    flags |= NACL_ABI_MAP_SHARED;
  if (bionic_flags & MAP_PRIVATE)
    flags |= NACL_ABI_MAP_PRIVATE;
  if (bionic_flags & MAP_FIXED)
    flags |= NACL_ABI_MAP_FIXED;
  if (bionic_flags & MAP_ANONYMOUS)
    flags |= NACL_ABI_MAP_ANONYMOUS;
  // ARC MOD END
  int result = __nacl_irt_mmap (&addr, len, prot, flags, fd, offset);
  if (result != 0) {
    errno = result;
    return MAP_FAILED;
  }
  return addr;
}
// ARC MOD BEGIN
// Add mmap symbol (32-bit version).
void* __mmap(void* addr, size_t size, int prot, int flags, int fd,
             off_t offset) {
  return mmap64(addr, size, prot, flags, fd, offset);
}
// ARC MOD END
weak_alias (__mmap, mmap)
