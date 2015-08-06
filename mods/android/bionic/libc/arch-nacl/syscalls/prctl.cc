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
#include <stdarg.h>
#include <string.h>
#include <sys/system_properties.h>

#include "common/trace_event.h"
#include "private/bionic_prctl.h"

namespace {
// Should hold arc::trace::SetThreadName.
typedef void (*SetThreadNameType)(const char* name);
SetThreadNameType g_trace_set_thread_name = NULL;
}

namespace arc {
namespace trace {
// Let libcommon initialization to tell us about SetThreadName so that
// prctl can use SetThreadName.
void RegisterTraceSetThreadName(SetThreadNameType f) {
  g_trace_set_thread_name = f;
}
}
}

extern "C" int prctl(int option, ...) {
  switch(option) {
    case PR_GET_DUMPABLE: {
      // Just return what android.os.cts.SecurityFeaturesTest expects. We don't
      // need to care about leaking user's data in coredump, which is not
      // supported on ARC anyway.
      char buf[PROP_VALUE_MAX];
      if (__system_property_get("ro.debuggable", buf) > 0 && strcmp(buf, "0") == 0)
        return 0;
      return 1;
    }
    case PR_SET_VMA:
      // Pretend to succeed for PR_SET_VMA because it is called by jemalloc and
      // we don't want to set errno randomly on memory allocation.
      // It should be okay because the option is used only for better memory usage
      // tracking. See the original commit at:
      // https://android.googlesource.com/kernel/x86_64/+/6ebfe5864ae6
      // Note this is an Android-kernel only feature.
      return 0;
#if !defined(BUILDING_LINKER)
    case PR_SET_NAME:
      if (g_trace_set_thread_name) {
        va_list vl;
        va_start(vl, option);
        const char* thread_name = reinterpret_cast<const char*>(va_arg(vl, long));
        // Tell Chrome tracing about this thread name at least.
        (*g_trace_set_thread_name)(thread_name);
        va_end(vl);
      }
      return 0;
#endif
  }
  errno = ENOSYS;
  return -1;
}
