// Copyright 2015 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef COMMON_NDK_SUPPORT_MMAP_H_
#define COMMON_NDK_SUPPORT_MMAP_H_

#include <unistd.h>

namespace arc {

// When |addr| is NULL, this mmap automatically fills a hint address
// to return values in certain range. Some old NDK applications
// require this behavior because they have a copy of old Bionic
// loader.
// https://android.googlesource.com/platform/bionic/+/gingerbread/linker/linker.c
// TODO(olonho): investigate why even with hint 0 linker expects memory
// in certain range. Short ARM branches?
void* MmapForNdk(void* addr, size_t length, int prot, int flags,
                 int fd, off_t offset);

}  // namespace arc

#endif  // COMMON_NDK_SUPPORT_MMAP_H_
