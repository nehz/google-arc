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

#ifndef ANDROID_CUTILS_ATOMIC_ARM_H
#define ANDROID_CUTILS_ATOMIC_ARM_H

#include <stdint.h>

#ifndef ANDROID_ATOMIC_INLINE
// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
#define ANDROID_ATOMIC_INLINE static inline
// ARC MOD END UPSTREAM
#endif

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void android_compiler_barrier()
// ARC MOD END UPSTREAM
{
    __asm__ __volatile__ ("" : : : "memory");
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE void android_memory_barrier()
// ARC MOD END UPSTREAM
{
#if ANDROID_SMP == 0
    android_compiler_barrier();
#else
    __asm__ __volatile__ ("dmb" : : : "memory");
#endif
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int32_t android_atomic_acquire_load(volatile const int32_t *ptr)
{
    int32_t value = *ptr;
    android_memory_barrier();
    return value;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int32_t android_atomic_release_load(volatile const int32_t *ptr)
{
    android_memory_barrier();
    return *ptr;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
void android_atomic_acquire_store(int32_t value, volatile int32_t *ptr)
{
    *ptr = value;
    android_memory_barrier();
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
void android_atomic_release_store(int32_t value, volatile int32_t *ptr)
{
    android_memory_barrier();
    *ptr = value;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int android_atomic_cas(int32_t old_value, int32_t new_value,
                       volatile int32_t *ptr)
{
    int32_t prev, status;
    do {
        __asm__ __volatile__ ("ldrex %0, [%3]\n"
                              "mov %1, #0\n"
                              "teq %0, %4\n"
#ifdef __thumb2__
                              "it eq\n"
#endif
                              "strexeq %1, %5, [%3]"
                              : "=&r" (prev), "=&r" (status), "+m"(*ptr)
                              : "r" (ptr), "Ir" (old_value), "r" (new_value)
                              : "cc");
    } while (__builtin_expect(status != 0, 0));
    return prev != old_value;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int android_atomic_acquire_cas(int32_t old_value, int32_t new_value,
                               volatile int32_t *ptr)
{
    int status = android_atomic_cas(old_value, new_value, ptr);
    android_memory_barrier();
    return status;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int android_atomic_release_cas(int32_t old_value, int32_t new_value,
                               volatile int32_t *ptr)
{
    android_memory_barrier();
    return android_atomic_cas(old_value, new_value, ptr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int32_t android_atomic_add(int32_t increment, volatile int32_t *ptr)
{
    int32_t prev, tmp, status;
    android_memory_barrier();
    do {
        __asm__ __volatile__ ("ldrex %0, [%4]\n"
                              "add %1, %0, %5\n"
                              "strex %2, %1, [%4]"
                              : "=&r" (prev), "=&r" (tmp),
                                "=&r" (status), "+m" (*ptr)
                              : "r" (ptr), "Ir" (increment)
                              : "cc");
    } while (__builtin_expect(status != 0, 0));
    return prev;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t android_atomic_inc(volatile int32_t *addr)
// ARC MOD END UPSTREAM
{
    return android_atomic_add(1, addr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE int32_t android_atomic_dec(volatile int32_t *addr)
// ARC MOD END UPSTREAM
{
    return android_atomic_add(-1, addr);
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int32_t android_atomic_and(int32_t value, volatile int32_t *ptr)
{
    int32_t prev, tmp, status;
    android_memory_barrier();
    do {
        __asm__ __volatile__ ("ldrex %0, [%4]\n"
                              "and %1, %0, %5\n"
                              "strex %2, %1, [%4]"
                              : "=&r" (prev), "=&r" (tmp),
                                "=&r" (status), "+m" (*ptr)
                              : "r" (ptr), "Ir" (value)
                              : "cc");
    } while (__builtin_expect(status != 0, 0));
    return prev;
}

// ARC MOD BEGIN UPSTREAM libcutils-fix-link-failure
ANDROID_ATOMIC_INLINE
// ARC MOD END UPSTREAM
int32_t android_atomic_or(int32_t value, volatile int32_t *ptr)
{
    int32_t prev, tmp, status;
    android_memory_barrier();
    do {
        __asm__ __volatile__ ("ldrex %0, [%4]\n"
                              "orr %1, %0, %5\n"
                              "strex %2, %1, [%4]"
                              : "=&r" (prev), "=&r" (tmp),
                                "=&r" (status), "+m" (*ptr)
                              : "r" (ptr), "Ir" (value)
                              : "cc");
    } while (__builtin_expect(status != 0, 0));
    return prev;
}

#endif /* ANDROID_CUTILS_ATOMIC_ARM_H */
