// Copyright (c) 2013 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef COMMON_TRACE_EVENT_H_
#define COMMON_TRACE_EVENT_H_

#include <stdint.h>

#include <common/trace_event_ppapi.h>

#define ARC_TRACE_CATEGORY "ARC"
#define ARC_MAIN_THREAD_NAME "ArcMain"

// This header sets up macros for use by a fork of an early (and now out of
// date) version of Chromium's trace_event_internal.h to provide
// tracing through the PPB_Trace_Event_Dev interface.  The trace event PPAPI
// also has only the capabilities of that earlier Chromium trace event
// code, so there is effectively no loss of functionality.
// TODO(crbug.com/424806): Add support for instant event flags, which are
// supported in the PPAPI interface but not in trace_event_internal.h.

#define TRACE_EVENT_API_GET_CATEGORY_ENABLED \
    arc::trace::GetCategoryEnabled

// Add a trace event to the platform tracing system. Returns thresholdBeginId
// for use in a corresponding end TRACE_EVENT_API_ADD_TRACE_EVENT call.
// int TRACE_EVENT_API_ADD_TRACE_EVENT(
//                    char phase,
//                    const unsigned char* category_enabled,
//                    const char* name,
//                    unsigned long long id,
//                    int num_args,
//                    const char** arg_names,
//                    const unsigned char* arg_types,
//                    const unsigned long long* arg_values,
//                    int threshold_begin_id,
//                    long long threshold,
//                    unsigned char flags)
#define TRACE_EVENT_API_ADD_TRACE_EVENT arc::trace::AddTraceEvent

// Defines atomic operations used internally by the tracing system.
// Per comments in trace_event_internal.h these require no memory barrier,
// and the Chromium gcc versions are defined as plain int load/store.
#define TRACE_EVENT_API_ATOMIC_WORD int
#define TRACE_EVENT_API_ATOMIC_LOAD(var) (var)
#define TRACE_EVENT_API_ATOMIC_STORE(var, value) ((var) = (value))

// Defines visibility for classes in trace_event_internal.h.
#define TRACE_EVENT_API_CLASS_EXPORT

#include "common/trace_event_internal.h"

#endif  // COMMON_TRACE_EVENT_H_
