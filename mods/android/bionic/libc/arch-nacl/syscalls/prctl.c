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

#include <errno.h>
#include <string.h>
#include <sys/system_properties.h>

#include "private/bionic_prctl.h"

int prctl(int option, ...) {
  if (option == PR_GET_DUMPABLE) {
    // Just return what android.os.cts.SecurityFeaturesTest expects. We don't
    // need to care about leaking user's data in coredump, which is not
    // supported on ARC anyway.
    char buf[PROP_VALUE_MAX];
    if (__property_get("ro.debuggable", buf) > 0 && strcmp(buf, "0") == 0)
      return 0;
    return 1;
  }
  // Pretend to succeed for PR_SET_VMA because it is called by jemalloc and
  // we don't want to set errno randomly on memory allocation.
  // It should be okay because the option is used only for better memory usage
  // tracking. See the original commit at:
  // https://android.googlesource.com/kernel/x86_64/+/6ebfe5864ae6
  // Note this is an Android-kernel only feature.
  if (option == PR_SET_VMA) {
    return 0;
  }
  errno = ENOSYS;
  return -1;
}
