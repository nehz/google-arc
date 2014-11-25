// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// Defines libc compatible functions to override Bionic's. This allows
// ::close(), ::fdatasync(), ::fstat(), etc. call in both posix_translation/
// and base/ code to call directly into the original (non-hooked) IRT without
// looping back to posix_translation.

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "common/alog.h"

extern "C" {
int real_close(int fd);
int real_fstat(int fd, struct stat* buf);
off64_t real_lseek64(int fd, off64_t offset, int whence);
int real_open(const char* pathname, int oflag, mode_t cmode);
ssize_t real_read(int fd, void* buf, size_t count);
ssize_t real_write(int fd, const void* buf, size_t count);
}  // extern "C"

namespace posix_translation {

extern "C" {
int close(int fd) {
  return real_close(fd);
}
int fstat(int fd, struct stat* buf) {
  return real_fstat(fd, buf);
}
off64_t lseek64(int fd, off64_t offset, int whence) {
  return real_lseek64(fd, offset, whence);
}
int open(const char* pathname, int flags, mode_t mode) {
  return real_open(pathname, flags, mode);
}
ssize_t read(int fd, void* buf, size_t count) {
  return real_read(fd, buf, count);
}
ssize_t write(int fd, const void* buf, size_t count) {
  return real_write(fd, buf, count);
}

// These FILE* functions are referenced in libchromium_base.a. For example,
// some functions in base/logging.cc which posix_translation never calls depends
// on fopen. Calling into these Bionic functions from libposix_translation.so
// is not safe because these functions call into IRT and (hooked) IRT calls back
// libposix_translation.so. To avoid hard-to-debug deadlocks, abort() early,
// just in case.

int fclose(FILE* fp) {
  ALOG_ASSERT(false);
  errno = ENOSYS;
  return EOF;
}
int fflush(FILE* stream) {
  ALOG_ASSERT(false);
  errno = ENOSYS;
  return EOF;
}
FILE* fopen(const char* path, const char* mode) {
  ALOG_ASSERT(false, "path=%s", path);
  errno = ENOSYS;
  return NULL;
}
int fprintf(FILE* stream, const char* format, ...) {
  ALOG_ASSERT(false, "format=%s", format);
  return -1;
}
int fputs(const char* str, FILE* stream) {
  ALOG_ASSERT(false, "%s", str);
  return EOF;
}
int puts(const char* str) {
  ALOG_ASSERT(false, "%s", str);
  return EOF;
}
}  // extern "C"

}  // namespace posix_translation
