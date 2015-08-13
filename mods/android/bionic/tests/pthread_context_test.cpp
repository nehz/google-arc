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

#include <pthread.h>

#include <gtest/gtest.h>

#include <bionic/libc/private/ScopedPthreadMutexLocker.h>
#include <private/pthread_context.h>
#include <thread_context.h>

namespace {

// Tests that need to create a thread and be cleaned up later.
class PthreadThreadContextThreadTest : public testing::Test {
 public:
  PthreadThreadContextThreadTest()
      : thread_(), thread_has_started_(false),
        thread_should_exit_(false) {
    pthread_mutex_init(&mu_, NULL);
    pthread_cond_init(&cond_, NULL);
  }

  virtual ~PthreadThreadContextThreadTest() {
    pthread_cond_destroy(&cond_);
    pthread_mutex_destroy(&mu_);
  }

  virtual void SetUp() {
    ASSERT_EQ(1, __pthread_get_thread_count(true));

    // Create a new thread and wait until it goes into futex_wait loop,
    // which is instrumented to export thread context information.
    {
      ScopedPthreadMutexLocker lock(&mu_);
      ASSERT_EQ(0, pthread_create(&thread_, NULL, WaitFn, this));
      while (!thread_has_started_)
        pthread_cond_wait(&cond_, &mu_);
    }
  }

  virtual void TearDown() {
    // Let the thread finish.
    {
      ScopedPthreadMutexLocker lock(&mu_);
      thread_should_exit_ = true;
      pthread_cond_signal(&cond_);
    }
    pthread_join(thread_, NULL);
  }


  static void* WaitFn(void* arg) {
    PthreadThreadContextThreadTest* self =
        static_cast<PthreadThreadContextThreadTest*>(arg);
    {
      ScopedPthreadMutexLocker lock(&self->mu_);
      self->thread_has_started_ = true;
      pthread_cond_signal(&self->cond_);

      while (!self->thread_should_exit_)
        pthread_cond_wait(&self->cond_, &self->mu_);
    }
    return NULL;
  }

  static bool HasContextRegs() {
    __pthread_context_info_t info;
    info.has_context_regs = true;
    __pthread_get_current_thread_info(&info);
    return info.has_context_regs;
  }

 protected:
  pthread_t thread_;
  bool thread_has_started_;
  bool thread_should_exit_;
  pthread_mutex_t mu_;
  pthread_cond_t cond_;
};

TEST_F(PthreadThreadContextThreadTest, get_thread_infos) {
  // Verify data in the thread list.
  __pthread_context_info_t infos[100];
  int thread_count = __pthread_get_thread_infos(true, true, 100, infos);
  ASSERT_EQ(2, thread_count);
  for (int i = 0; i < thread_count; ++i) {
    SCOPED_TRACE(i);
    ASSERT_TRUE(infos[i].stack_base != NULL);
    EXPECT_GT(infos[i].stack_size, 0);
  }
}

TEST_F(PthreadThreadContextThreadTest, get_thread_contexts) {
  // We want the other thread to be inside futex call inside
  // pthread_cond_wait(). The other option is to let the other thread
  // __nanosleep.  This is not reliable but better than nothing.
  //
  // This might turn out to be flaky, if so we should wait longer here.
  usleep(100000);

  // __nanosleep call would clear the context_regs.
  ASSERT_FALSE(HasContextRegs());
  SAVE_CONTEXT_REGS();
  ASSERT_TRUE(HasContextRegs());

  // Verify data in the thread list.
  __pthread_context_info_t infos[100];
  int thread_count = __pthread_get_thread_infos(true, true, 100, infos);
  ASSERT_EQ(2, thread_count);
  for (int i = 0; i < thread_count; ++i) {
    SCOPED_TRACE(i);
    ASSERT_TRUE(infos[i].stack_base != NULL);
    EXPECT_GT(infos[i].stack_size, 0);
#if defined(__x86_64__)
    ASSERT_TRUE(infos[i].has_context_regs);
    EXPECT_NE(0, infos[i].context_regs[REG_RIP]);
#elif defined(__i386__)
    ASSERT_TRUE(infos[i].has_context_regs);
    EXPECT_NE(0, infos[i].context_regs[REG_EIP]);
#elif defined(__arm__)
    ASSERT_TRUE(infos[i].has_context_regs);
    EXPECT_NE(0, infos[i].context_regs[15]);
#else
    EXPECT_FALSE(infos[i].has_context_regs);
#endif
  }
  CLEAR_CONTEXT_REGS();
}


TEST(PthreadThreadContextSinglethreadTest, get_cur_thread_context) {
  __pthread_context_info_t info;
  info.has_context_regs = true;
  __pthread_get_current_thread_info(&info);
  ASSERT_FALSE(info.has_context_regs);

  SAVE_CONTEXT_REGS();
  memset(&info, 0, sizeof(info));
  __pthread_get_current_thread_info(&info);
#if defined(__x86_64__)
  ASSERT_TRUE(info.has_context_regs);
  EXPECT_NE(0, info.context_regs[REG_RIP]);
#elif defined(__i386__)
  ASSERT_TRUE(info.has_context_regs);
  EXPECT_NE(0, info.context_regs[REG_EIP]);
#elif defined(__arm__)
  ASSERT_TRUE(info.has_context_regs);
  EXPECT_NE(0, info.context_regs[15]);
#else
  EXPECT_FALSE(info.has_context_regs);
#endif

  CLEAR_CONTEXT_REGS();
  info.has_context_regs = true;
  __pthread_get_current_thread_info(&info);
  ASSERT_FALSE(info.has_context_regs);
}

}  // anonymous namespace
