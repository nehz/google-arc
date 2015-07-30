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

#include "ucontext_i.h"

#include <ucontext.h>
#include <stdint.h>

#include "gtest/gtest.h"

TEST(UContext, OffsetTest) {
  ucontext_t uc;
  uintptr_t base_address = reinterpret_cast<uintptr_t>(&uc);

#define OFFSET_OF(x) (reinterpret_cast<uintptr_t>(&x) - base_address)
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R8]), UC_MCONTEXT_GREGS_R8);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R9]), UC_MCONTEXT_GREGS_R9);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R10]), UC_MCONTEXT_GREGS_R10);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R11]), UC_MCONTEXT_GREGS_R11);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R12]), UC_MCONTEXT_GREGS_R12);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R13]), UC_MCONTEXT_GREGS_R13);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R14]), UC_MCONTEXT_GREGS_R14);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_R15]), UC_MCONTEXT_GREGS_R15);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RDI]), UC_MCONTEXT_GREGS_RDI);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RSI]), UC_MCONTEXT_GREGS_RSI);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RBP]), UC_MCONTEXT_GREGS_RBP);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RBX]), UC_MCONTEXT_GREGS_RBX);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RDX]), UC_MCONTEXT_GREGS_RDX);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RAX]), UC_MCONTEXT_GREGS_RAX);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RCX]), UC_MCONTEXT_GREGS_RCX);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RSP]), UC_MCONTEXT_GREGS_RSP);
  EXPECT_EQ(OFFSET_OF(uc.uc_mcontext.gregs[REG_RIP]), UC_MCONTEXT_GREGS_RIP);
  EXPECT_EQ(OFFSET_OF(uc.uc_sigmask), UC_SIGMASK);

  base_address = reinterpret_cast<uintptr_t>(&uc.__fpregs_mem);
  EXPECT_EQ(OFFSET_OF(uc.__fpregs_mem.mxcsr), FPREGS_OFFSET_MXCSR);
}
