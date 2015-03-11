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

#include <gtest/gtest.h>

#include <private/pthread_context.h>

struct Args {
  Args() : should_exit(false) {}

  volatile bool should_exit;
};

static void* SleepFn(void* arg) {
    Args* args = reinterpret_cast<Args*>(arg);
    while (!args->should_exit) {
        usleep(10000);
    }
    return NULL;
}

TEST(pthread_thread_context, QEMU_DISABLED_get_thread_infos) {
    // Remember initial thread count.
    int initial_thread_count = __pthread_get_thread_count(true);
    ASSERT_GT(initial_thread_count, 0);

#if defined(BARE_METAL_BIONIC)
    // For some reason BMM_x86 does not set stack_end_from_irt,
    // and so the list of thread infos comes out as empty.
    // TODO(igorc): Find out why it also fails on defined(__arm__) devices.
    return;
#endif
#if defined(__native_client__)
    // TODO(crbug.com/465635): Disabled on defined(__native_client__) as it's
    // flaky.
    return;
#endif

    // Create a new thread.
    Args args;
    pthread_t thread;
    ASSERT_EQ(0, pthread_create(&thread, NULL, SleepFn, &args));

    // Verify data in the thread list.
    __pthread_context_info_t infos[100];
    int thread_count = __pthread_get_thread_infos(true, true, 100, infos);
    ASSERT_EQ(initial_thread_count + 1, thread_count);
    for (int i = 0; i < thread_count; ++i) {
        ASSERT_TRUE(infos[i].stack_base != NULL);
        ASSERT_GT(infos[i].stack_size, 0);
#if defined(BARE_METAL_BIONIC)
        ASSERT_EQ(infos[i].stack_size, 1024 * 1024);
#endif
    }

    args.should_exit = true;
    pthread_join(thread, NULL);
}
