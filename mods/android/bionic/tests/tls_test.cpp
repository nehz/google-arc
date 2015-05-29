// Copyright (C) 2014 The Android Open Source Project
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

#include <gtest/gtest.h>

#include <errno.h>
#if defined(HAVE_ARC)
#include <irt_syscalls.h>
#endif
#include <private/__get_tls.h>
#include <private/get_tls_for_art.h>
#include <pthread.h>
#include <stdio.h>

TEST(tls, basic) {
  pthread_key_t key;
  ASSERT_EQ(0, pthread_key_create(&key, NULL));
  const void* ptr = &key;
  ASSERT_EQ(0, pthread_setspecific(key, ptr));
  const void* result = pthread_getspecific(key);
  EXPECT_EQ(result, ptr);
#if defined(HAVE_ARC)
  // Check if our assembly code in __get_tls() agrees with NaClSysTlsGet.
  const void** tls = reinterpret_cast<const void**>(__nacl_irt_tls_get());
  // See pthread_getspecific() in bionic/libc/bionic/pthread.c.
  EXPECT_EQ(result, tls[key]);
  EXPECT_EQ(ptr, tls[key]);
#endif
}

TEST(tls, get_tls_for_art) {
  get_tls_fn_t get_tls_for_art = NULL;
#if !defined(__native_client__) && defined(__i386__)
  get_tls_for_art = *(get_tls_fn_t*)POINTER_TO_GET_TLS_FUNC_ON_BMM_I386;
#elif defined(__native_client__) && defined(__x86_64__)
  get_tls_for_art = *(get_tls_fn_t*)POINTER_TO_GET_TLS_FUNC_ON_NACL_X86_64;
#elif ((defined(__native_client__) && defined(__i386__)) ||     \
       (!defined(__native_client__) && defined(__arm__)))
  // No fixed address for __get_tls on this target, skipping this test
  return;
#else
# error Unsupported target
#endif

  // Note we cannot test get_tls_for_art == __get_tls as
  // get_tls_for_art is a pointer to __get_tls in runnable-ld.so,
  // not in libc.so.
  EXPECT_EQ(get_tls_for_art(), __get_tls());
}
