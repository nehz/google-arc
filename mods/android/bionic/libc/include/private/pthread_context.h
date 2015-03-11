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
// Defines functions to access current list of threads and register contexts.

#ifndef _ANDROID_BIONIC_LIBC_PRIVATE_PTHREAD_CONTEXT_H
#define _ANDROID_BIONIC_LIBC_PRIVATE_PTHREAD_CONTEXT_H

#include <stdint.h>
#include <sys/cdefs.h>

__BEGIN_DECLS

#define PTHREAD_MAX_SAVED_REGS  32

#if defined(__x86_64__)
typedef uint64_t PthreadRegValue;
#else
typedef uint32_t PthreadRegValue;
#endif

typedef struct __pthread_context_info_t {
    // stack_base and stack_size exclude guard areas.
    void* stack_base;
    int stack_size;
    int has_context_regs;
    // The actual number of saved registers depends on architecture.
    PthreadRegValue context_regs[PTHREAD_MAX_SAVED_REGS];
} __pthread_context_info_t;

// Returns the count of live threads. |try_lock| will use a "try" operation
// on the global pthread lock, making this function async-signal-safe.
// Returns -1 in case of failure.
int __pthread_get_thread_count(bool try_lock);

// Stores thread information in the |infos| array. |try_lock| will use a "try"
// operation on the global pthread lock, making this function
// async-signal-safe. Returns the number of threads stored.
// Returns -1 in case of failure.
int __pthread_get_thread_infos(
    bool try_lock, bool include_current,
    int max_info_count, __pthread_context_info_t* infos);

__END_DECLS

#endif  // _ANDROID_BIONIC_LIBC_PRIVATE_PTHREAD_CONTEXT_H
