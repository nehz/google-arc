/*
 * Copyright (C) 2015 The Android Open Source Project
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
 * limitations under the License
 */

#include <signal.h>
#include <stdlib.h>

#include "common/alog.h"
#include "nacl_signals.h"
#include "private/kernel_sigset_t.h"

extern "C" {

__LIBC_HIDDEN__ int __nacl_signal_action(
    int bionic_signum, const struct sigaction* bionic_new_action,
    struct sigaction* bionic_old_action, size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_mask(int how, const kernel_sigset_t* set,
                                       kernel_sigset_t* oldset, size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_pending(kernel_sigset_t* set, size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_suspend(const kernel_sigset_t* set,
                                          size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_timedwait(const kernel_sigset_t* set,
                                            siginfo_t* info,
                                            const struct timespec* timeout,
                                            size_t sigsetsize);

#if !defined(__LP64__)
// Compatibility function for non-LP64 sigaction.
// All ARC targets are non-LP64 (so the above #if is a no-op), but this function
// is only defined/used when __LP64__ is not #defined, so using the same
// conditional compilation here for consistency.
int __sigaction(int bionic_signum, const struct sigaction* bionic_new_action,
                struct sigaction* bionic_old_action) {
  return __nacl_signal_action(bionic_signum, bionic_new_action,
                              bionic_old_action,
                              // Android's 32-bit ABI is broken. sigaction(),
                              // the only caller of this function, uses sigset_t
                              // instead of kernel_sigset_t since there is no
                              // version of struct sigaction that uses 64 bits
                              // for the sigset.
                              // See android/bionic/libc/bionic/sigaction.cpp.
                              sizeof(sigset_t));
}
#endif

__strong_alias(__rt_sigaction, __nacl_signal_action);
__strong_alias(__rt_sigpending, __nacl_signal_pending);
__strong_alias(__rt_sigprocmask, __nacl_signal_mask);
__strong_alias(__rt_sigsuspend, __nacl_signal_suspend);
__strong_alias(__rt_sigtimedwait, __nacl_signal_timedwait);
__strong_alias(tkill, __nacl_signal_send);

}

// TODO(crbug.com/496991): Implement these functions
int __nacl_signal_action(int bionic_signum,
                         const struct sigaction* bionic_new_action,
                         struct sigaction* bionic_old_action, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_mask(int how, const kernel_sigset_t* set,
                       kernel_sigset_t* oldset, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_pending(kernel_sigset_t* set, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_send(int tid, int bionic_signum) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_suspend(const kernel_sigset_t* set, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_timedwait(const kernel_sigset_t* set, siginfo_t* info,
                            const struct timespec* timeout,
                            size_t sigsetsize) {
  errno = ENOSYS;
  return -1;
}
