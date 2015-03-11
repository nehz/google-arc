// Copyright (C) 2015 The Android Open Source Project
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
// Saves and clears register context on the current thread.
// For use with blocking IRT calls.

#include <errno.h>
#include <pthread.h>

#include "private/pthread_context.h"

#include "bionic_atomic_inline.h"
#include "pthread_internal.h"

extern "C" {

__LIBC_HIDDEN__ void __pthread_save_context_regs(
        void* regs, int size) {
    pthread_internal_t* thread = __get_thread();
    memcpy(thread->context_regs, regs, size);
    thread->has_context_regs = 1;
    ANDROID_MEMBAR_FULL();
}

__LIBC_HIDDEN__ void __pthread_clear_context_regs() {
    pthread_internal_t* thread = __get_thread();
    thread->has_context_regs = 0;
    ANDROID_MEMBAR_FULL();
}

static bool obtain_lock(bool try_lock) {
    if (try_lock) {
        // Ideally, we could also check that the mutex is async-safe:
        //   ((gThreadListLock & MUTEX_TYPE_MASK) == MUTEX_TYPE_BITS_NORMAL)
        if (pthread_mutex_trylock(&gThreadListLock))
            return false;
    } else {
        pthread_mutex_lock(&gThreadListLock);
    }
    return true;
}

int __pthread_get_thread_count(bool try_lock) {
    if (!obtain_lock(try_lock))
        return -1;

    int count = 0;
    pthread_internal_t* thread = gThreadList;
    while (thread) {
        ++count;
        thread = thread->next;
    }

    pthread_mutex_unlock(&gThreadListLock);
    return count;
}

int __pthread_get_thread_infos(
        bool try_lock, bool include_current,
        int max_info_count, __pthread_context_info_t* infos) {
    if (!obtain_lock(try_lock))
        return -1;

    int idx = 0;
    pthread_internal_t* cur_thread = __get_thread();
    for (pthread_internal_t* thread = gThreadList;
         thread && idx < max_info_count; thread = thread->next) {
        __pthread_context_info_t* info = infos + idx;
        if (!include_current && thread == cur_thread)
            continue;

        // Copy the stack boundaries.
#if defined(BARE_METAL_BIONIC)
        // TODO(crbug.com/372248): Remove the use of stack_end_from_irt.
        if (!thread->stack_end_from_irt)
          continue;
        // Value from chrome/src/components/nacl/loader/nonsfi/irt_thread.cc.
        static const int kIrtStackSize = 1024 * 1024;
        info->stack_base = thread->stack_end_from_irt - kIrtStackSize;
        info->stack_size = kIrtStackSize;
#else
        if (!thread->attr.stack_base)
          continue;
        info->stack_base =
            reinterpret_cast<char*>(thread->attr.stack_base) +
            thread->attr.guard_size;
        info->stack_size = thread->attr.stack_size - thread->attr.guard_size;
#endif

        // Copy registers, then do a second (racy) read of has_context_regs.
        if (thread->has_context_regs) {
            memcpy(info->context_regs, thread->context_regs,
                   sizeof(info->context_regs));
            ANDROID_MEMBAR_FULL();
            info->has_context_regs = thread->has_context_regs;
        } else {
            info->has_context_regs = 0;
        }

        ++idx;
    }

    pthread_mutex_unlock(&gThreadListLock);
    return idx;
}

}  // extern "C"
