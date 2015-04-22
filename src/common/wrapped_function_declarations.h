// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// Forward declarations necessary to define the table of wrapped
// functions.
//

#ifndef COMMON_WRAPPED_FUNCTION_DECLARATIONS_H_
#define COMMON_WRAPPED_FUNCTION_DECLARATIONS_H_

#include <dirent.h>
#include <sys/types.h>

extern "C" {
// *_chk() are not in the source standard; they are only in the binary standard.
mode_t __umask_chk(mode_t mask);

// Bionic does not have forward declarations for them.
int getdents(unsigned int fd, struct dirent* dirp, unsigned int count);
int mkstemps(char* path, int slen);
int tgkill(int tgid, int tid, int sig);
int tkill(int tid, int sig);
int truncate64(const char* path, off_t length);
}

#endif  // COMMON_WRAPPED_FUNCTION_DECLARATIONS_H_
