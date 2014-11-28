// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <elf.h>  // For ELFMAG
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "base/memory/ref_counted.h"
#include "gtest/gtest.h"
#include "posix_translation/passthrough.h"
#include "posix_translation/test_util/file_system_test_common.h"

namespace posix_translation {

namespace {

int DoFcntl(scoped_refptr<FileStream> stream, int cmd, ...) {
  va_list ap;
  va_start(ap, cmd);
  const int result = stream->fcntl(cmd, ap);
  va_end(ap);
  return result;
}

class PassthroughTest : public FileSystemTestCommon {
};

}  // namespace

TEST_F(PassthroughTest, TestHandlerOpenWithEmptyPath) {
  PassthroughHandler handler;
  int fd = dup(STDOUT_FILENO);
  scoped_refptr<FileStream> stream =
      handler.open(fd, "", O_WRONLY, 0);
  ASSERT_TRUE(stream != NULL);
  struct stat st;
  EXPECT_EQ(0, stream->fstat(&st));
}

TEST_F(PassthroughTest, TestConstructAndCloseOnDestruct) {
  int fd = dup(STDIN_FILENO);
  ASSERT_NE(-1, fd);
  {
    scoped_refptr<FileStream> stream = new PassthroughStream(fd, "", O_WRONLY,
                                                             true);
  }  // |fd| should be automatically closed here.
  errno = 0;
  EXPECT_EQ(-1, close(fd));  // should fail.
  EXPECT_EQ(EBADF, errno);
}

TEST_F(PassthroughTest, TestConstructAndNotClosedOnDestruct) {
  int fd = dup(STDIN_FILENO);
  ASSERT_NE(-1, fd);
  {
    scoped_refptr<FileStream> stream = new PassthroughStream(fd, "", O_WRONLY,
                                                             false);
    // |fd| should NOT be automatically closed here since passing
    // close_on_destruction = false.
  }
  EXPECT_EQ(0, close(fd));
}

TEST_F(PassthroughTest, TestConstructAndDestructForAnonymousMmap) {
  scoped_refptr<FileStream> stream = new PassthroughStream();
  size_t length = sysconf(_SC_PAGESIZE);
  void* new_addr = stream->mmap(NULL, length, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, 0);
  EXPECT_NE(MAP_FAILED, new_addr);
  EXPECT_EQ(0, stream->munmap(new_addr, length));
}

TEST_F(PassthroughTest, TestFcntl) {
  scoped_refptr<FileStream> stream =
      new PassthroughStream(dup(STDERR_FILENO), "", O_WRONLY, true);
  EXPECT_EQ(O_WRONLY, DoFcntl(stream, F_GETFL));
  const long new_flag = O_WRONLY | O_NONBLOCK;  // NOLINT(runtime/int)
  EXPECT_EQ(0, DoFcntl(stream, F_SETFL, new_flag));
  EXPECT_EQ(new_flag, DoFcntl(stream, F_GETFL));
}

}  // namespace posix_translation
