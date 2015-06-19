/*
 * Copyright (C) 2010 The Android Open Source Project
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

#ifndef ANDROID_CUTILS_ATOMIC_X86_H
#define ANDROID_CUTILS_ATOMIC_X86_H

#include <stdint.h>

#ifndef ANDROID_ATOMIC_INLINE
// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
#define ANDROID_ATOMIC_INLINE static inline
// ARC MOD END UPSTREAM
#endif

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void android_compiler_barrier(void)
// ARC MOD END UPSTREAM
{
    __asm__ __volatile__ ("" : : : "memory");
}

#if ANDROID_SMP == 0
// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void android_memory_barrier(void)
// ARC MOD END UPSTREAM
{
    android_compiler_barrier();
}
#else
// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void android_memory_barrier(void)
// ARC MOD END UPSTREAM
{
    __asm__ __volatile__ ("mfence" : : : "memory");
}
#endif

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_acquire_load(volatile const int32_t *ptr)
{
    int32_t value = *ptr;
    android_compiler_barrier();
    return value;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_release_load(volatile const int32_t *ptr)
{
    android_memory_barrier();
    return *ptr;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void
// ARC MOD END UPSTREAM
android_atomic_acquire_store(int32_t value, volatile int32_t *ptr)
{
    *ptr = value;
    android_memory_barrier();
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void
// ARC MOD END UPSTREAM
android_atomic_release_store(int32_t value, volatile int32_t *ptr)
{
    android_compiler_barrier();
    *ptr = value;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int
// ARC MOD END UPSTREAM
android_atomic_cas(int32_t old_value, int32_t new_value, volatile int32_t *ptr)
{
    int32_t prev;
    __asm__ __volatile__ ("lock; cmpxchgl %1, %2"
                          : "=a" (prev)
                          : "q" (new_value), "m" (*ptr), "0" (old_value)
                          : "memory");
    return prev != old_value;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int
// ARC MOD END UPSTREAM
android_atomic_acquire_cas(int32_t old_value,
                           int32_t new_value,
                           volatile int32_t *ptr)
{
    /* Loads are not reordered with other loads. */
    return android_atomic_cas(old_value, new_value, ptr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int
// ARC MOD END UPSTREAM
android_atomic_release_cas(int32_t old_value,
                           int32_t new_value,
                           volatile int32_t *ptr)
{
    /* Stores are not reordered with other stores. */
    return android_atomic_cas(old_value, new_value, ptr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_add(int32_t increment, volatile int32_t *ptr)
{
    __asm__ __volatile__ ("lock; xaddl %0, %1"
                          : "+r" (increment), "+m" (*ptr)
                          : : "memory");
    /* increment now holds the old value of *ptr */
    return increment;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_inc(volatile int32_t *addr)
{
    return android_atomic_add(1, addr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_dec(volatile int32_t *addr)
{
    return android_atomic_add(-1, addr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_and(int32_t value, volatile int32_t *ptr)
{
    int32_t prev, status;
    do {
        prev = *ptr;
        status = android_atomic_cas(prev, prev & value, ptr);
    } while (__builtin_expect(status != 0, 0));
    return prev;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t
// ARC MOD END UPSTREAM
android_atomic_or(int32_t value, volatile int32_t *ptr)
{
    int32_t prev, status;
    do {
        prev = *ptr;
        status = android_atomic_cas(prev, prev | value, ptr);
    } while (__builtin_expect(status != 0, 0));
    return prev;
}

#endif /* ANDROID_CUTILS_ATOMIC_X86_H */
