// Copyright 2015 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "common/ndk_support/mmap.h"

#include <pthread.h>
#include <stdint.h>
#include <sys/mman.h>
#include <unistd.h>

#include "common/scoped_pthread_mutex_locker.h"

namespace arc {

namespace {

uintptr_t g_mmap_hint_addr = 0x70000000;

}  // namespace

void* MmapForNdk(void* addr, size_t length, int prot, int flags,
                 int fd, off_t offset) {
  if (!addr && !(flags & MAP_FIXED)) {
    // We use 0x70000000 as the first hint address. Then, the next
    // hint address will be increased by |length|, so this function
    // will likely keep satisfying the limitation of old Bionic's
    // loader which some NDKs have. On SFI NaCl, just keeping
    // specifying 0x70000000 works but it does not work on Bare Metal
    // mode. As SFI NaCl may change its internal implementation in
    // future, it would be better to always update the address hint
    // which is more likely used.
    //
    // Such NDK apps call mmap with NULL |addr| only twice at their
    // start-ups. On SFI NaCl these addresses are always not used.
    // TODO(hamaji): Check if ASLR on BMM does never use this region
    // and update the comment and/or code.
    //
    // Essentially this way we emulate Android's mmap() behavior
    // better, by hinting where it shall allocate, if application has
    // no preferences.
    addr = reinterpret_cast<char*>(
        __sync_fetch_and_add(&g_mmap_hint_addr,
                             (length + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)));
  }
  return mmap(addr, length, prot, flags, fd, offset);
}

}  // namespace arc
