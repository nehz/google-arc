// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "common/ndk_support/arm_syscall.h"

#include <errno.h>
#include <linux/futex.h>
#include <stdarg.h>
#include <stdint.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "common/alog.h"
#include "common/arc_strace.h"

namespace arc {

namespace {

#if defined(USE_NDK_DIRECT_EXECUTION)
void RunCacheFlush(va_list ap) {
  int32_t start = va_arg(ap, int32_t);
  int32_t end = va_arg(ap, int32_t);
  uint32_t op = va_arg(ap, uint32_t);
  switch (op) {
    // Invalidate i-cache.
    case 0:
      ALOGI("icache flush: %p-%p",
            reinterpret_cast<void*>(start), reinterpret_cast<void*>(end));
      if (cacheflush(start, end, 0) != 0)
        ALOGE("cacheflush failed.");
      break;
    default:
      LOG_ALWAYS_FATAL("CacheFlush op 0x%x not supported\n", op);
  }
}
#endif

int RunArmKernelSyscallImpl(int arm_sysno, va_list ap) {
  switch (arm_sysno) {
    case 178:  // rt_sigqueueinfo
      return -ENOSYS;
    case 186:  // sigaltstack
      return -ENOSYS;
    case 224: {  // gettid
      // Forward the call to __wrap_syscall in posix_translation.
      int result = syscall(__NR_gettid);  // always succeeds
      LOG_ALWAYS_FATAL_IF(result < 0);
      return result;
    }
    case 240: {  // futex
      // Forward the call to __wrap_syscall in posix_translation.
      const int saved_errno = errno;
      int* addr = va_arg(ap, int*);
      int op = va_arg(ap, int);
      int val = va_arg(ap, int);
      timespec* timeout = va_arg(ap, timespec*);
      int* addr2 = va_arg(ap, int*);
      int val3 = va_arg(ap, int);

      int result = syscall(__NR_futex, addr, op, val, timeout, addr2, val3);
      if (result >= 0 && (op == FUTEX_WAKE || op == FUTEX_WAKE_PRIVATE))
        return result;  // woken threads

      if (result) {
        result = -errno;
        errno = saved_errno;
      }
      return result;
    }
    case 241:  // sched_setaffinity
      ALOGI("sched_setaffinity is not supported, returning 0");
      return 0;  // pretend to succeed.
    case 307:  // shmget
      return -ENOSYS;
    case kCacheFlushSysno:  // cacheflush
#if defined(USE_NDK_DIRECT_EXECUTION)
      RunCacheFlush(ap);
#else
      LOG_ALWAYS_FATAL("cacheflush must be handled in NDK translation");
#endif
      return 0;
    default:
      break;
  }
  LOG_ALWAYS_FATAL("ARM syscall %s not supported\n",
                   arc::GetArmSyscallStr(arm_sysno).c_str());
  return -ENOSYS;  // not reached
}

}  // namespace

int RunArmKernelSyscall(int arm_sysno, ...) {
  // This function handles syscall (svc instructions) in ARM NDK binaries. This
  // is for NDK translation. Since this is just for emulating svc, |errno| is
  // never updated.
  ARC_STRACE_ENTER("arm_kernel_syscall", "%s, ...",
                   arc::GetArmSyscallStr(arm_sysno).c_str());
  va_list ap;
  va_start(ap, arm_sysno);
  const int result = RunArmKernelSyscallImpl(arm_sysno, ap);
  va_end(ap);
  if (result == -ENOSYS)
    ARC_STRACE_ALWAYS_WARN_NOTIMPLEMENTED();
  ARC_STRACE_RETURN_INT(result, false);
}

#if defined(USE_NDK_DIRECT_EXECUTION)
int RunArmLibcSyscall(int arm_sysno, ...) {
  // This function handles syscall() libc calls in ARM NDK binaries. Unlike
  // RunArmKernelSyscall, this updates |errno| as needed.
  ARC_STRACE_ENTER("arm_libc_syscall", "%s, ...",
                   arc::GetArmSyscallStr(arm_sysno).c_str());
  va_list ap;
  va_start(ap, arm_sysno);
  int result = RunArmKernelSyscallImpl(arm_sysno, ap);
  va_end(ap);

  // This matches with the behavior of Bionic. See
  // third_party/android/bionic/libc/arch-arm/bionic/syscall.S.
  if (-4096 < result && result < 0) {
    errno = -result;
    result = -1;
  }
  if (result == -1 && errno == ENOSYS)
    ARC_STRACE_ALWAYS_WARN_NOTIMPLEMENTED();
  ARC_STRACE_RETURN(result);
}
#endif

}  // namespace arc
