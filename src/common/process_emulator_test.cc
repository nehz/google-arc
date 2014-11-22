// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// Test memory state related classes.

#include <pthread.h>

#include "base/compiler_specific.h"
#include "common/process_emulator.h"
#include "gtest/gtest.h"

namespace arc {

static void* EmptyRoutine(void* arg) {
  return NULL;
}

class ProcessEmulatorTest : public testing::Test {
 public:
  virtual void SetUp() OVERRIDE {
    ProcessEmulator::SetIsMultiThreaded(false);
    ASSERT_FALSE(ProcessEmulator::IsMultiThreaded());
  }

  virtual void TearDown() OVERRIDE {
    ProcessEmulator::UnsetThreadStateForTesting();
  }

 protected:
  void SetFakeThreadStateForTesting() {
    ProcessEmulator::SetFakeThreadStateForTesting(111, 222);
  }
  void UnfilterPthreadCreateForTesting(
      void* (*start_routine)(void*),  // NOLINT(readability/casting)
      void* arg) {
    ProcessEmulator::UnfilterPthreadCreateForTesting(start_routine, arg);
  }
};

TEST_F(ProcessEmulatorTest, FilterPthreadCreateNoState) {
  void* (*start_routine)(void*) = &EmptyRoutine;  // NOLINT
  void* arg = reinterpret_cast<void*>(234);

  ProcessEmulator::FilterPthreadCreate(&start_routine, &arg);

  EXPECT_TRUE(ProcessEmulator::IsMultiThreaded());

  EXPECT_EQ(&EmptyRoutine, start_routine);  // NOLINT
  EXPECT_EQ(reinterpret_cast<void*>(234), arg);

  UnfilterPthreadCreateForTesting(start_routine, arg);
}

TEST_F(ProcessEmulatorTest, FilterPthreadCreateWithState) {
  SetFakeThreadStateForTesting();

  void* (*start_routine)(void*) = &EmptyRoutine;  // NOLINT
  void* arg = reinterpret_cast<void*>(234);

  ProcessEmulator::FilterPthreadCreate(&start_routine, &arg);

  EXPECT_TRUE(ProcessEmulator::IsMultiThreaded());

  EXPECT_NE(&EmptyRoutine, start_routine);  // NOLINT
  EXPECT_NE(reinterpret_cast<void*>(234), arg);

  UnfilterPthreadCreateForTesting(start_routine, arg);
}

}  // namespace arc
