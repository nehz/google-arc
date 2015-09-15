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

#ifndef _NACL_SIGNALS_H
#define _NACL_SIGNALS_H

#include <signal.h>

extern "C" {

__LIBC_HIDDEN__ void __nacl_signal_install_handler();

__LIBC_HIDDEN__ int __nacl_signal_send(int tid, int bionic_signum);

__LIBC_HIDDEN__ int __nacl_signal_thread_init(pid_t tid);

__LIBC_HIDDEN__ int __nacl_signal_thread_deinit(pid_t tid);

}  // extern "C"

#endif  /* _NACL_SIGNALS_H */
