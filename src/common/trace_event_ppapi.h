// Copyright (c) 2013 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef COMMON_TRACE_EVENT_PPAPI_H_
#define COMMON_TRACE_EVENT_PPAPI_H_

struct PPB_Trace_Event_Dev_0_2;
typedef struct PPB_Trace_Event_Dev_0_2 PPB_Trace_Event_Dev;

namespace arc {
namespace trace {

void Init(const PPB_Trace_Event_Dev* iface);

void SetThreadName(const char* name);
const unsigned char* GetCategoryEnabled(const char* category_name);
void AddTraceEvent(
    char phase,
    const unsigned char* category_enabled,
    const char* name,
    uint64_t id,
    int num_args,
    const char** arg_names,
    const unsigned char* arg_types,
    const uint64_t* arg_values,
    unsigned char flags);
void AddTraceEventWithThreadIdAndTimestamp(
    char phase,
    const unsigned char* category_enabled,
    const char* name,
    uint64_t id,
    int thread_id,
    uint64_t timestamp,
    int num_args,
    const char** arg_names,
    const unsigned char* arg_types,
    const uint64_t* arg_values,
    unsigned char flags);

}  // namespace trace
}  // namespace arc

#endif  // COMMON_TRACE_EVENT_PPAPI_H_
