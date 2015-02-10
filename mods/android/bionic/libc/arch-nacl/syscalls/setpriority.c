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

#include <errno.h>
#include <sys/resource.h>

#include <irt_syscalls.h>
#include <nacl_nice.h>

int setpriority(int which, int who, int prio) {
  if (which != PRIO_PROCESS) {
    if (which != PRIO_PGRP && which != PRIO_USER)
      errno = EINVAL;
    else
      errno = EPERM;  // PRIO_PGRP and PRIO_USER are not supported.
    return -1;
  }

  // Handle PRIO_PROCESS;
  if (who != 0 && who != gettid()) {
    errno = ESRCH;
    return -1;
  }

  // Convert POSIX |prio| into NaCl's.
  int nacl_prio = NICE_NORMAL;
  if (prio > 0)
    nacl_prio = NICE_BACKGROUND;
  else if (prio < 0)
    nacl_prio = NICE_REALTIME;

  const int result = __nacl_irt_thread_nice(nacl_prio);
  if (result) {
    errno = result;
    return -1;
  }
  return 0;
}
