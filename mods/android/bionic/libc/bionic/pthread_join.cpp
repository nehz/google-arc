/*
 * Copyright (C) 2008 The Android Open Source Project
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

#include <errno.h>
// ARC MOD BEGIN
// For __nacl_irt_sched_yield, abort, munmap, and write.
#if defined(HAVE_ARC)
#include <irt_syscalls.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
#endif
// ARC MOD END

#include "private/bionic_futex.h"
#include "pthread_accessor.h"

int pthread_join(pthread_t t, void** return_value) {
  if (t == pthread_self()) {
    return EDEADLK;
  }

  pid_t tid;
  volatile int* tid_ptr;
  {
    pthread_accessor thread(t);
    if (thread.get() == NULL) {
      return ESRCH;
    }

    if ((thread->attr.flags & PTHREAD_ATTR_FLAG_DETACHED) != 0) {
      return EINVAL;
    }

    if ((thread->attr.flags & PTHREAD_ATTR_FLAG_JOINED) != 0) {
      return EINVAL;
    }

    // Okay, looks like we can signal our intention to join.
    thread->attr.flags |= PTHREAD_ATTR_FLAG_JOINED;
    tid = thread->tid;
    tid_ptr = &thread->tid;
  }

  // We set the PTHREAD_ATTR_FLAG_JOINED flag with the lock held,
  // so no one is going to remove this thread except us.

  // Wait for the thread to actually exit, if it hasn't already.
  while (*tid_ptr != 0) {
    // ARC MOD BEGIN
    // Use __nacl_irt_sched_yield instead of __futex_wait.
    // __nacl_irt_thread_exit does not give us a notice with
    // futex_wait, so we will yield and poll until thread completes.
    //
    // Note that nacl-glibc's has similar code in nptl/pthread_join.c
    // and sysdeps/nacl/lowlevellock.h.
#if defined(HAVE_ARC)
    __nacl_irt_sched_yield();
#else
    // ARC MOD END
    __futex_wait(tid_ptr, tid, NULL);
    // ARC MOD BEGIN
#endif
    // ARC MOD END
  }

  // Take the lock again so we can pull the thread's return value
  // and remove the thread from the list.
  pthread_accessor thread(t);

  if (return_value) {
    *return_value = thread->return_value;
  }
  // ARC MOD BEGIN
  // Unmap stack if PTHREAD_ATTR_FLAG_USER_STACK is not
  // set. Upstream bionic unmaps the stack in thread which are about
  // to exit, but we cannot do this on NaCl because the stack should
  // be available when we call __nacl_irt_thread_exit. Instead, we
  // unmap the stack from the thread which calls pthread_join.
#if defined(HAVE_ARC)
  if (!thread->user_allocated_stack() &&
      thread->attr.stack_base) {
    if (munmap(thread->attr.stack_base, thread->attr.stack_size) != 0) {
      static const int kStderrFd = 2;
      static const char kMsg[] = "failed to unmap the stack!\n";
      write(kStderrFd, kMsg, sizeof(kMsg) - 1);
      abort();
    }
    // Clear the pointer to unmapped stack so pthread_join from
    // other threads will not try to unmap this region again.
    thread->attr.stack_base = NULL;
    thread->attr.stack_size = 0;
    thread->tls = NULL;
  }
#endif  // HAVE_ARC
  // ARC MOD END

  _pthread_internal_remove_locked(thread.get());
  return 0;
}
