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

#include <irt.h>
#include <irt_syscalls.h>
#include <pthread.h>

#include "common/alog.h"

namespace {

pthread_once_t g_getentropy_once = PTHREAD_ONCE_INIT;
struct nacl_irt_random g_irt_random;

void InitNaClIrtRandom() {
  __nacl_irt_query(NACL_IRT_RANDOM_v0_1, &g_irt_random, sizeof(g_irt_random));
  ALOG_ASSERT(g_irt_random.get_random_bytes);
}

}  // namespace

extern "C" __LIBC_HIDDEN__ int getentropy(void *buf, size_t len) {
  pthread_once(&g_getentropy_once, InitNaClIrtRandom);
  size_t nread;
  if (g_irt_random.get_random_bytes(buf, len, &nread) != 0 ||
      nread != len) {
    errno = EIO;
    return -1;
  }
  return 0;
}
