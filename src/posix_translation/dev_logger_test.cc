// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <sys/sysmacros.h>

#include "base/compiler_specific.h"
#include "base/synchronization/lock.h"
#include "common/logger.h"  // LOGGER_FLUSH_LOG etc.
#include "gtest/gtest.h"
#include "posix_translation/dev_logger.h"
#include "posix_translation/test_util/file_system_background_test_common.h"

namespace posix_translation {

// We use random numbers for this test.
const int kLoggerMajorId = 42;
const int kEventsMinorId = 43;
const int kMainMinorId = 44;
const int kRadioMinorId = 45;
const int kSystemMinorId = 46;

class DevLoggerTest : public FileSystemBackgroundTestCommon<DevLoggerTest> {
 public:
  DECLARE_BACKGROUND_TEST(TestBlockingModeWithCondWait);

  DevLoggerTest() {}
  virtual ~DevLoggerTest() {}

 protected:
  virtual void SetUp() OVERRIDE;
  int CallIoctl(scoped_refptr<FileStream> stream, int request, ...);

  scoped_ptr<FileSystemHandler> handler_;

 private:
  DISALLOW_COPY_AND_ASSIGN(DevLoggerTest);
};

void DevLoggerTest::SetUp() {
  FileSystemBackgroundTestCommon<DevLoggerTest>::SetUp();
  handler_.reset(new DevLoggerHandler);
  ASSERT_TRUE(handler_->IsInitialized());

  DeviceHandler::AddDeviceId(
      "/dev/log/events", kLoggerMajorId, kEventsMinorId);
  DeviceHandler::AddDeviceId(
      "/dev/log/main", kLoggerMajorId, kMainMinorId);
  DeviceHandler::AddDeviceId(
      "/dev/log/radio", kLoggerMajorId, kRadioMinorId);
  DeviceHandler::AddDeviceId(
      "/dev/log/system", kLoggerMajorId, kSystemMinorId);
}

int DevLoggerTest::CallIoctl(
    scoped_refptr<FileStream> stream, int request, ...) {
  va_list ap;
  va_start(ap, request);
  const int ret = stream->ioctl(request, ap);
  va_end(ap);
  return ret;
}

TEST_F(DevLoggerTest, TestInit) {
}

TEST_F(DevLoggerTest, TestOnDirectoryContentsNeeded) {
  base::AutoLock lock(mutex());
  // readdir/getdents are not supported.
  EXPECT_EQ(NULL, handler_->OnDirectoryContentsNeeded("/"));
}

TEST_F(DevLoggerTest, TestStat) {
  base::AutoLock lock(mutex());
  struct stat st = {};
  EXPECT_EQ(0, handler_->stat("/dev/log/events", &st));
  EXPECT_NE(0U, st.st_ino);
  EXPECT_EQ(S_IFCHR | 0666U, st.st_mode);
  EXPECT_EQ(makedev(kLoggerMajorId, kEventsMinorId), st.st_rdev);

  EXPECT_EQ(-1, handler_->stat("/dev/log/unknown_path", &st));
  EXPECT_EQ(ENOENT, errno);
}

TEST_F(DevLoggerTest, TestStatfs) {
  base::AutoLock lock(mutex());
  struct statfs st = {};
  EXPECT_EQ(0, handler_->statfs("/dev/log/main", &st));
  EXPECT_NE(0, static_cast<int>(st.f_type));  // check something is filled.
}

TEST_F(DevLoggerTest, TestOpen) {
  base::AutoLock lock(mutex());
  scoped_refptr<FileStream> stream;

  // Confirm that we can open the following paths.
  stream = handler_->open(-1 /* fd */, "/dev/log/events", O_RDONLY, 0);
  EXPECT_TRUE(stream);
  stream = handler_->open(-1, "/dev/log/main", O_RDONLY, 0);
  EXPECT_TRUE(stream);
  stream = handler_->open(-1, "/dev/log/radio", O_RDONLY, 0);
  EXPECT_TRUE(stream);
  stream = handler_->open(-1, "/dev/log/system", O_RDONLY, 0);
  EXPECT_TRUE(stream);

  // Try to open it as a directory, which should fail.
  errno = 0;
  stream =
    handler_->open(-1, "/dev/log/events", O_RDONLY | O_DIRECTORY, 0);
  EXPECT_EQ(ENOTDIR, errno);
  EXPECT_FALSE(stream);

  // Try to open with bad paths.
  errno = 0;
  stream = handler_->open(-1, "/dev/log/event", O_RDONLY, 0);
  EXPECT_EQ(ENOENT, errno);
  EXPECT_FALSE(stream);
  errno = 0;
  stream = handler_->open(-1, "/dev/log/systems", O_RDONLY, 0);
  EXPECT_EQ(ENOENT, errno);
  EXPECT_FALSE(stream);
  errno = 0;
  stream = handler_->open(-1, "/dev/log/unknown_path", O_RDONLY, 0);
  EXPECT_EQ(ENOENT, errno);
  EXPECT_FALSE(stream);
}

TEST_F(DevLoggerTest, TestIoctl) {
  base::AutoLock lock(mutex());
  scoped_refptr<FileStream> stream;

  stream = handler_->open(-1, "/dev/log/main", O_RDONLY | O_NONBLOCK, 0);
  ASSERT_TRUE(stream);

  // Flush should be the first one.
  ASSERT_EQ(0, CallIoctl(stream, LOGGER_FLUSH_LOG));

  EXPECT_LT(0, CallIoctl(stream, LOGGER_GET_LOG_BUF_SIZE));
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_GET_LOG_LEN));
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_GET_NEXT_ENTRY_LEN));
  EXPECT_EQ(1, CallIoctl(stream, LOGGER_GET_VERSION));
  int new_version = 2;
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_SET_VERSION, &new_version));
  EXPECT_EQ(2, CallIoctl(stream, LOGGER_GET_VERSION));
  new_version = 1;
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_SET_VERSION, &new_version));
  EXPECT_EQ(1, CallIoctl(stream, LOGGER_GET_VERSION));

  // Try unsupported ioctl.
  int dummy = 0;
  EXPECT_EQ(-1, CallIoctl(stream, FIONREAD, &dummy));
  EXPECT_EQ(EINVAL, errno);
}

TEST_F(DevLoggerTest, TestNonBlockingMode) {
  base::AutoLock lock(mutex());
  scoped_refptr<FileStream> stream;

  stream = handler_->open(-1, "/dev/log/events", O_RDONLY | O_NONBLOCK, 0);
  ASSERT_TRUE(stream);

  // Flush the log and then test IsSelectReadReady().
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_FLUSH_LOG));
  EXPECT_FALSE(stream->IsSelectReadReady());

  // Call fstat().
  struct stat st = {};
  EXPECT_EQ(0, stream->fstat(&st));
  EXPECT_NE(0U, st.st_ino);
  EXPECT_EQ(S_IFCHR | 0666U, st.st_mode);
  EXPECT_EQ(makedev(kLoggerMajorId, kEventsMinorId), st.st_rdev);

  // Call read(). Confirm it will not block.
  errno = 0;
  char buf[128] = {};
  ssize_t result = stream->read(buf, sizeof(buf));
  EXPECT_EQ(EWOULDBLOCK, errno);
  EXPECT_EQ(-1, result);

  // Write something to the log.
  const char kTag[] = "Test";
  const char kMsg[] = "Test log1";
  arc::Logger* logger = arc::Logger::GetInstance();
  logger->Log(ARC_LOG_ID_EVENTS, ARC_LOG_DEBUG, kTag, kMsg);
  const ssize_t kPayloadSize = 1 + sizeof(kTag) + sizeof(kMsg);
  const ssize_t kEntrySize = kPayloadSize + sizeof(struct logger_entry);
  EXPECT_EQ(kEntrySize, CallIoctl(stream, LOGGER_GET_LOG_LEN));
  EXPECT_EQ(kEntrySize, CallIoctl(stream, LOGGER_GET_NEXT_ENTRY_LEN));

  // Call read().
  EXPECT_TRUE(stream->IsSelectReadReady());
  errno = 0;
  result = stream->read(buf, sizeof(buf));
  EXPECT_EQ(0, errno);
  EXPECT_EQ(kEntrySize, result);

  // Call write() which should always fail.
  result = stream->write(buf, 1);
  EXPECT_EQ(EPERM, errno);
  EXPECT_EQ(-1, result);
}

TEST_F(DevLoggerTest, TestBlockingMode) {
  base::AutoLock lock(mutex());
  scoped_refptr<FileStream> stream;

  stream = handler_->open(-1, "/dev/log/system", O_RDONLY, 0);
  ASSERT_TRUE(stream);

  // Flush the log and then test IsSelectReadReady().
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_FLUSH_LOG));
  EXPECT_FALSE(stream->IsSelectReadReady());

  // Call fstat().
  struct stat st = {};
  EXPECT_EQ(0, stream->fstat(&st));
  EXPECT_NE(0U, st.st_ino);
  EXPECT_EQ(S_IFCHR | 0666U, st.st_mode);

  // Write something to the log.
  const char kTag[] = "Test";
  const char kMsg[] = "Test log2";
  arc::Logger* logger = arc::Logger::GetInstance();
  logger->Log(ARC_LOG_ID_SYSTEM, ARC_LOG_DEBUG, kTag, kMsg);
  const ssize_t kPayloadSize = 1 + sizeof(kTag) + sizeof(kMsg);
  const ssize_t kEntrySize = kPayloadSize + sizeof(struct logger_entry);
  EXPECT_EQ(kEntrySize, CallIoctl(stream, LOGGER_GET_LOG_LEN));
  EXPECT_EQ(kEntrySize, CallIoctl(stream, LOGGER_GET_NEXT_ENTRY_LEN));

  // Call read().
  ASSERT_TRUE(stream->IsSelectReadReady());
  errno = 0;
  char buf[128] = {};
  ssize_t result = stream->read(buf, sizeof(buf));
  EXPECT_EQ(0, errno);
  EXPECT_EQ(kEntrySize, result);

  // Call write() which should always fail.
  result = stream->write(buf, 1);
  EXPECT_EQ(EPERM, errno);
  EXPECT_EQ(-1, result);

  // Cleaning things up.
  CallIoctl(stream, LOGGER_FLUSH_LOG);
}

TEST_F(DevLoggerTest, TestReadWithTinyBuf) {
  base::AutoLock lock(mutex());
  scoped_refptr<FileStream> stream;

  stream = handler_->open(-1, "/dev/log/radio", O_RDONLY, 0);
  ASSERT_TRUE(stream);
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_FLUSH_LOG));

  // Write something to the log.
  const char kTag[] = "Test";
  const char kMsg[] = "Test log3";
  arc::Logger* logger = arc::Logger::GetInstance();
  logger->Log(ARC_LOG_ID_RADIO, ARC_LOG_DEBUG, kTag, kMsg);
  const ssize_t kPayloadSize = 1 + sizeof(kTag) + sizeof(kMsg);
  const ssize_t kEntrySize = kPayloadSize + sizeof(struct logger_entry);

  // Call read() with 1 byte buffer. This should fail.
  char c;
  errno = 0;
  ssize_t result = stream->read(&c, 1);
  EXPECT_EQ(EINVAL, errno);
  EXPECT_EQ(-1, result);

  // Call read() with a tight buffer.
  char buf[kEntrySize] = {};
  errno = 0;
  result = stream->read(buf, sizeof(buf));
  EXPECT_EQ(0, errno);
  EXPECT_EQ(kEntrySize, result);

  // Cleaning things up.
  CallIoctl(stream, LOGGER_FLUSH_LOG);
}

namespace {

const char kTag[] = "Test";
const char kMsg[] = "Test log4";

void* Signal(void* data) {
  // Lock the mutex to ensure that stream->read() is called first.
  base::AutoLock lock(*static_cast<base::Lock*>(data));

  // Write something to the log to wake up the background thread.
  arc::Logger* logger = arc::Logger::GetInstance();
  logger->Log(ARC_LOG_ID_SYSTEM, ARC_LOG_DEBUG, kTag, kMsg);

  return NULL;
}

}  // namespace

TEST_BACKGROUND_F(DevLoggerTest, TestBlockingModeWithCondWait) {
  base::AutoLock lock(mutex());
  scoped_refptr<FileStream> stream;

  stream = handler_->open(-1, "/dev/log/system", O_RDONLY, 0);  // blocking
  ASSERT_TRUE(stream);

  // Flush the log and then test IsSelectReadReady().
  EXPECT_EQ(0, CallIoctl(stream, LOGGER_FLUSH_LOG));
  EXPECT_FALSE(stream->IsSelectReadReady());

  // Start another thread.
  pthread_t p;
  pthread_create(&p, NULL, Signal, &mutex());

  // Call read(). The thread will suspend until the Signal() thread calls
  // Log().
  const ssize_t kPayloadSize = 1 + sizeof(kTag) + sizeof(kMsg);
  const ssize_t kEntrySize = kPayloadSize + sizeof(struct logger_entry);
  errno = 0;
  char buf[128] = {};
  ssize_t result = stream->read(buf, sizeof(buf));
  EXPECT_EQ(0, errno);
  EXPECT_EQ(kEntrySize, result);

  // Cleaning things up.
  pthread_join(p, NULL);
  CallIoctl(stream, LOGGER_FLUSH_LOG);
}

}  // namespace posix_translation
