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

#include "pthread_internal.h"

#include "private/bionic_futex.h"
#include "private/bionic_tls.h"
#include "private/ScopedPthreadMutexLocker.h"

/* ARC MOD BEGIN */

#include <sys/mman.h>
#include <stdlib.h>
#include <unistd.h>
/* ARC MOD END */
pthread_internal_t* g_thread_list = NULL;
pthread_mutex_t g_thread_list_lock = PTHREAD_MUTEX_INITIALIZER;

void _pthread_internal_remove_locked(pthread_internal_t* thread) {
  if (thread->next != NULL) {
    thread->next->prev = thread->prev;
  }
  if (thread->prev != NULL) {
    thread->prev->next = thread->next;
  } else {
    g_thread_list = thread->next;
  }

  // The main thread is not heap-allocated. See __libc_init_tls for the declaration,
  // and __libc_init_common for the point where it's added to the thread list.
  if ((thread->attr.flags & PTHREAD_ATTR_FLAG_MAIN_THREAD) == 0) {
    free(thread);
  }
}

void _pthread_internal_add(pthread_internal_t* thread) {
  ScopedPthreadMutexLocker locker(&g_thread_list_lock);

  // We insert at the head.
  thread->next = g_thread_list;
  thread->prev = NULL;
  if (thread->next != NULL) {
    thread->next->prev = thread;
  }
  g_thread_list = thread;
}

pthread_internal_t* __get_thread(void) {
  return reinterpret_cast<pthread_internal_t*>(__get_tls()[TLS_SLOT_THREAD_ID]);
}

// Initialize 'ts' with the difference between 'abstime' and the current time
// according to 'clock'. Returns -1 if abstime already expired, or 0 otherwise.
int __timespec_from_absolute(timespec* ts, const timespec* abstime, clockid_t clock) {
  clock_gettime(clock, ts);
  ts->tv_sec  = abstime->tv_sec - ts->tv_sec;
  ts->tv_nsec = abstime->tv_nsec - ts->tv_nsec;
  if (ts->tv_nsec < 0) {
    ts->tv_sec--;
    ts->tv_nsec += 1000000000;
  }
  if ((ts->tv_nsec < 0) || (ts->tv_sec < 0)) {
    return -1;
  }
  return 0;
}
/* ARC MOD BEGIN */
#if defined(HAVE_ARC)
// On NaCl and Bare Metal, a thread stack and pthread_internal_t struct for
// a detached thread must be released after the thread completely finishes.
// Define two functions for that. Details below:
// _pthread_internal_prepend_detached_threads_locked is called when
// pthread_exit is called for a detached thread to add the thread to
// |g_detached_finished_thread_list|. _pthread_internal_free_detached_threads
// is called every time when pthread_exit is called (regardless of whether
// or not the exiting thread is detached) to actually unmap the threads' stack.
// _pthread_internal_free_detached_threads also returns a list of
// pthread_internal_t structures for such detached threads so that the caller
// of _pthread_internal_free_detached_threads (which is pthread_exit) can free
// the structures when g_thread_list_lock is not locked.

static pthread_internal_t* g_detached_finished_thread_list = NULL;

void _pthread_internal_free_detached_threads(
    pthread_internal_t** out_ready_to_free_list) {
  ScopedPthreadMutexLocker locker(&g_thread_list_lock);
  // Dead-lock warning! Do NOT allocate/deallocate memory in this function.
  // crbug.com/469105

  size_t ready_to_free_index = 0;
  pthread_internal_t* thread = g_detached_finished_thread_list;
  while (thread) {
    volatile pid_t* pkernel_id = &(thread->tid);
    pthread_internal_t* next = thread->next;
    // NaCl service runtime writes zero to |tid| when the thread
    // completely finishes.
    if (*pkernel_id == 0) {
      if (!thread->user_allocated_stack() && thread->attr.stack_base) {
        if (munmap(thread->attr.stack_base,
                   thread->attr.stack_size) != 0) {
          static const int kStderrFd = 2;
          static const char kMsg[] = "failed to unmap the stack!\n";
          write(kStderrFd, kMsg, sizeof(kMsg) - 1);
          abort();
        }
      }

      // The following code is very similar to the one in
      // _pthread_internal_remove_locked().
      if (next)
        next->prev = thread->prev;
      if (thread->prev)
        thread->prev->next = next;
      else
        g_detached_finished_thread_list = next;

      if ((thread->attr.flags & PTHREAD_ATTR_FLAG_MAIN_THREAD) == 0) {
        // |thread| is ready to be freed, but calling free() is not allowed
        // here. Return the address of the struct to the caller.
        thread->next = *out_ready_to_free_list;  // insert at the head.
        thread->prev = NULL;
        if (thread->next != NULL) {
          thread->next->prev = thread;
        }
        *out_ready_to_free_list = thread;
      }
    }
    thread = next;
  }
}

void _pthread_internal_prepend_detached_threads_locked(pthread_internal_t* thread) {
  // Dead-lock warning! Do NOT allocate/deallocate memory in this function.
  // crbug.com/469105

  if (thread->tid == 0)  // sanity check.
    abort();

  // _pthread_internal_remove_locked frees the thread's resources unless it is
  // the main thread.  Since we need |thread| to be alive until pthread_exit
  // is called, we temporarily add the flag that indicates that the thread is
  // the main thread, and hence should not be freed.
  // _pthread_internal_free_detached_threads will eventually take care of
  // actually freeing the thread when it is safe to do so.
  const uint32_t orig_flags = thread->attr.flags;
  thread->attr.flags |= PTHREAD_ATTR_FLAG_MAIN_THREAD;
  // Remove |thread| from |g_thread_list|. |thread| will NOT be freed because
  // of the ATTR_FLAG_MAIN flag added above.
  _pthread_internal_remove_locked(thread);
  thread->attr.flags = orig_flags;

  // ... and then add it to |g_detached_finished_thread_list|.
  thread->next = g_detached_finished_thread_list;
  thread->prev = NULL;
  if (thread->next)
    thread->next->prev = thread;
  g_detached_finished_thread_list = thread;
}
#endif  // HAVE_ARC
/* ARC MOD END */
