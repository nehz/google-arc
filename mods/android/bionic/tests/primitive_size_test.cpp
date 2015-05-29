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
// An ARC specific test which checks the size of some primitive
// types.
//

#include <float.h>
#include <gtest/gtest.h>

#include "bionic/libc/include/link.h"

TEST(primitive_size, int) {
  EXPECT_EQ(4, static_cast<int>(sizeof(int)));
}

TEST(primitive_size, long) {
  EXPECT_EQ(4, static_cast<int>(sizeof(long)));
}

TEST(primitive_size, pointer) {
  EXPECT_EQ(4, static_cast<int>(sizeof(void*)));
}

TEST(primitive_size, long_double) {
  // TODO(crbug.com/432441): Use 64-bit long-double even on Bare Metal
  // i686. See mods/fork/bionic-long-double for more detail.
#if defined(BARE_METAL_BIONIC) && defined(__i386__)
  EXPECT_EQ(12, static_cast<int>(sizeof(long double)));
  EXPECT_EQ(64, LDBL_MANT_DIG);
#else
  EXPECT_EQ(8, static_cast<int>(sizeof(long double)));
  EXPECT_EQ(53, LDBL_MANT_DIG);
#endif
}

TEST(primitive_size, elfw_addr) {
  struct r_debug r;
#if defined(__x86_64__)
  // Needs to be 64bits even on NaCl x86-64
  // See mods/android/bionic/libc/include/link.h and
  // third_party/nacl-glibc/elf/link.h
  EXPECT_EQ(8U, sizeof(r.r_brk));
  EXPECT_EQ(8U, sizeof(r.r_ldbase));
#else
  EXPECT_EQ(4U, sizeof(r.r_brk));
  EXPECT_EQ(4U, sizeof(r.r_ldbase));
#endif
}
