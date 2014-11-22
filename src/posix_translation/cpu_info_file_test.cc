// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <time.h>
#include <unistd.h>

#include "base/basictypes.h"
#include "base/memory/scoped_ptr.h"
#include "base/strings/stringprintf.h"
#include "gtest/gtest.h"
#include "posix_translation/cpu_info_file.h"
#include "posix_translation/test_util/file_system_test_common.h"
#include "posix_translation/test_util/sysconf_util.h"

namespace posix_translation {

namespace {

const char kHeader[] = "HHH";
const char kBody[] = "!$1!";
const char kFooter[] = "FFF";

// The number of physical/online CPUs in this test. See also:
// cpu_info_test.cc.
static int kNumConfigured = 4;
static int kNumOnline = 2;

class CpuInfoFileHandlerTest : public FileSystemTestCommon {
 protected:
  CpuInfoFileHandlerTest()
      : num_configured_(kNumConfigured), num_online_(kNumOnline),
        handler_(new CpuInfoFileHandler(kHeader, kBody, kFooter)) {
  }

  ScopedNumProcessorsConfiguredSetting num_configured_;
  ScopedNumProcessorsOnlineSetting num_online_;
  scoped_ptr<FileSystemHandler> handler_;

 private:
  DISALLOW_COPY_AND_ASSIGN(CpuInfoFileHandlerTest);
};

}  // namespace

TEST_F(CpuInfoFileHandlerTest, TestInit) {
}

TEST_F(CpuInfoFileHandlerTest, TestStatFile) {
  struct stat st;
  EXPECT_EQ(0, handler_->stat("/cpuinfo", &st));
  EXPECT_TRUE(S_ISREG(st.st_mode));

  // Confirm that stat() always fills the current time in st_mtime.
  EXPECT_NE(0, static_cast<time_t>(st.st_mtime));
  EXPECT_NEAR(time(NULL), st.st_mtime, 60.0 /* seconds */);

  EXPECT_EQ(-1, handler_->stat("/cpuinf", &st));
  EXPECT_EQ(ENOENT, errno);
  EXPECT_EQ(-1, handler_->stat("/cpuinf0", &st));
  EXPECT_EQ(ENOENT, errno);
}

TEST_F(CpuInfoFileHandlerTest, TestOpenFile) {
  scoped_refptr<FileStream> stream =
      handler_->open(-1, "/cpuinfo", O_RDONLY, 0);
  ASSERT_TRUE(stream);
  // Confirm that mmap() is NOT suppored.
  EXPECT_EQ(MAP_FAILED,
            stream->mmap(NULL, 1, PROT_READ, MAP_PRIVATE, 0));
  EXPECT_EQ(EIO, errno);

  EXPECT_FALSE(handler_->open(-1, "/cpuinf", O_RDONLY, 0));
  EXPECT_EQ(ENOENT, errno);
  EXPECT_FALSE(handler_->open(-1, "/cpuinf0", O_RDONLY, 0));
  EXPECT_EQ(ENOENT, errno);
}

TEST_F(CpuInfoFileHandlerTest, TestRead) {
  scoped_refptr<FileStream> stream =
      handler_->open(-1, "/cpuinfo", O_RDONLY, 0);
  ASSERT_TRUE(stream);
  char buf[128] = {};  // for easier \0 termination.
  EXPECT_LT(0, stream->read(buf, sizeof(buf)));
  EXPECT_STREQ("HHH!0!!1!FFF", buf);

  // Test the case where only one CPU is online.
  {
    ScopedNumProcessorsOnlineSetting num_online(1);
    memset(buf, 0, sizeof(buf));
    EXPECT_EQ(0, stream->lseek(0, SEEK_SET));
    EXPECT_LT(0, stream->read(buf, sizeof(buf)));
    EXPECT_STREQ("HHH!0!FFF", buf);
  }
}

TEST_F(CpuInfoFileHandlerTest, TestFstat) {
  scoped_refptr<FileStream> stream =
      handler_->open(-1, "/cpuinfo", O_RDONLY, 0);
  ASSERT_TRUE(stream);

  struct stat st;
  EXPECT_EQ(0, stream->fstat(&st));
  EXPECT_TRUE(S_ISREG(st.st_mode));

  // Confirm that fstat() always fills the current time in st_mtime too.
  EXPECT_NE(0, static_cast<time_t>(st.st_mtime));
  EXPECT_NEAR(time(NULL), st.st_mtime, 60.0 /* seconds */);
}

}  // namespace posix_translation
