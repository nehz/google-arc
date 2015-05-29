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

struct Args {
  Args()
      : has_started(false),
        should_exit(false) {
    pthread_mutex_init(&mu, NULL);
    pthread_cond_init(&cond, NULL);
  }
  ~Args() {
    pthread_cond_destroy(&cond);
    pthread_mutex_destroy(&mu);
  }

  bool has_started;
  bool should_exit;
  pthread_mutex_t mu;
  pthread_cond_t cond;
};

static void* WaitFn(void* arg) {
  Args* args = static_cast<Args*>(arg);
  {
    ScopedPthreadMutexLocker lock(&args->mu);
    args->has_started = true;
    pthread_cond_signal(&args->cond);

    while (!args->should_exit)
      pthread_cond_wait(&args->cond, &args->mu);
  }
  return NULL;
}

TEST(pthread_thread_context, get_thread_infos) {
  ASSERT_EQ(1, __pthread_get_thread_count(true));

  Args args;
  // Create a new thread and wait until it finishes its
  // initialization.
  // TODO(crbug.com/372248): Remove the wait. This synchronization is
  // only for Bare Metal mode. On Bare Metal mode, pthread_context
  // uses |stack_end_from_irt| in pthread_internal_t to find the
  // location of a stack. Unlike other pthread attributes, this is
  // filled by the created thread, not by the creator. So, there is a
  // race. pthread_context may read an uninitialized value in
  // |stack_end_from_irt|.
  pthread_t thread;
  {
    ScopedPthreadMutexLocker lock(&args.mu);
    ASSERT_EQ(0, pthread_create(&thread, NULL, WaitFn, &args));
    while (!args.has_started)
      pthread_cond_wait(&args.cond, &args.mu);
  }

  // Verify data in the thread list.
  __pthread_context_info_t infos[100];
  int thread_count = __pthread_get_thread_infos(true, true, 100, infos);
  ASSERT_EQ(2, thread_count);
  for (int i = 0; i < thread_count; ++i) {
    ASSERT_TRUE(infos[i].stack_base != NULL);
    ASSERT_GT(infos[i].stack_size, 0);
#if defined(BARE_METAL_BIONIC)
    ASSERT_EQ(infos[i].stack_size, 1024 * 1024);
#endif
  }

  // Let the thread finish.
  {
    ScopedPthreadMutexLocker lock(&args.mu);
    args.should_exit = true;
    pthread_cond_signal(&args.cond);
  }
  pthread_join(thread, NULL);
}

TEST(pthread_thread_context, get_cur_thread_context) {
  __pthread_context_info_t info;
  info.has_context_regs = true;
  __pthread_get_current_thread_info(&info);
  ASSERT_FALSE(info.has_context_regs);

  SAVE_CONTEXT_REGS();
  memset(&info, 0, sizeof(info));
  __pthread_get_current_thread_info(&info);
#if defined(__x86_64__)
  ASSERT_TRUE(info.has_context_regs);
  ASSERT_NE(0, info.context_regs[REG_RIP]);
#elif defined(__arm__)
  ASSERT_TRUE(info.has_context_regs);
  ASSERT_NE(0, info.context_regs[15]);
#else
  ASSERT_FALSE(info.has_context_regs);
#endif

  CLEAR_CONTEXT_REGS();
  info.has_context_regs = true;
  __pthread_get_current_thread_info(&info);
  ASSERT_FALSE(info.has_context_regs);
}
