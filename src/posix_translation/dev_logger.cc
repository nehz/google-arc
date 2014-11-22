// Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "posix_translation/dev_logger.h"

#include <errno.h>
#include <string.h>

#include "base/bind.h"
#include "base/compiler_specific.h"
#include "common/logger.h"
#include "posix_translation/dir.h"
#include "posix_translation/statfs.h"
#include "posix_translation/virtual_file_system.h"

namespace posix_translation {

namespace {

using arc::Logger;

bool GetLogIdFromPath(const std::string& pathname, arc_log_id_t* log_id) {
  if (pathname == "/dev/log/events") {
    *log_id = ARC_LOG_ID_EVENTS;
    return true;
  }
  if (pathname == "/dev/log/main") {
    *log_id = ARC_LOG_ID_MAIN;
    return true;
  }
  if (pathname == "/dev/log/radio") {
    *log_id = ARC_LOG_ID_RADIO;
    return true;
  }
  if (pathname == "/dev/log/system") {
    *log_id = ARC_LOG_ID_SYSTEM;
    return true;
  }
  return false;
}

int DoStatLocked(const std::string& pathname, struct stat* out) {
  memset(out, 0, sizeof(struct stat));
  out->st_ino =
      VirtualFileSystem::GetVirtualFileSystem()->GetInodeLocked(pathname);
  out->st_mode = S_IFCHR | 0666;
  out->st_nlink = 1;
  out->st_blksize = 4096;
  // st_uid, st_gid, st_size, st_blocks should be zero.

  // TODO(crbug.com/242337): Fill st_dev if needed.
  out->st_rdev = DeviceHandler::GetDeviceId(pathname);
  return 0;
}


class DevLogger : public DeviceStream {
 public:
  DevLogger(const std::string& pathname, int oflag, arc_log_id_t log_id);

  bool is_block() const { return !(oflag() & O_NONBLOCK); }

  virtual int ioctl(int request, va_list ap) OVERRIDE;
  virtual int fcntl(int cmd, va_list ap) OVERRIDE;
  virtual int fstat(struct stat* out) OVERRIDE;
  virtual ssize_t read(void* buf, size_t count) OVERRIDE;
  virtual ssize_t write(const void* buf, size_t count) OVERRIDE;
  virtual bool IsSelectReadReady() const OVERRIDE;
  virtual int16_t GetPollEvents() const OVERRIDE;
  virtual const char* GetStreamType() const OVERRIDE;

 protected:
  virtual ~DevLogger();

 private:
  friend class DevLoggerDevice;

  static void ReadReady();

  arc::LoggerReader* reader_;
  int version_;

  DISALLOW_COPY_AND_ASSIGN(DevLogger);
};

DevLogger::DevLogger(
    const std::string& pathname, int oflag, arc_log_id_t log_id)
    : DeviceStream(oflag, pathname),
      reader_(Logger::GetInstance()->CreateReader(log_id)),
      version_(1) {
}

DevLogger::~DevLogger() {
  Logger::GetInstance()->ReleaseReader(reader_);
  // Wake up the reading thread.
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  sys->Broadcast();
}

int DevLogger::ioctl(int request, va_list ap) {
  int ret = 0;

  switch (request) {
    case LOGGER_GET_LOG_BUF_SIZE:
      ret = Logger::GetInstance()->GetBufferSize(reader_);
      break;
    case LOGGER_GET_LOG_LEN:
      ret = Logger::GetInstance()->GetLogLength(reader_);
      break;
    case LOGGER_GET_NEXT_ENTRY_LEN:
      ret = Logger::GetInstance()->GetNextEntryLength(reader_);
      break;
    case LOGGER_FLUSH_LOG:
      Logger::GetInstance()->FlushBuffer(reader_);
      ret = 0;
      break;
    case LOGGER_GET_VERSION:
      ret = version_;
      break;
    case LOGGER_SET_VERSION: {
      int* out = va_arg(ap, int*);
      if (*out != 1 && *out != 2) {
        errno = EINVAL;
        ret =  -1;
      } else {
        version_  = *out;
      }
      break;
    }
    default:
      errno = EINVAL;
      return -1;
  }
  return ret;
}

int DevLogger::fcntl(int cmd, va_list ap) {
  // TODO(penghuang): Setting O_NONBLOCK via fcntl is a no-op.
  return FileStream::fcntl(cmd, ap);
}

int DevLogger::fstat(struct stat* out) {
  return DoStatLocked(pathname(), out);
}

ssize_t DevLogger::read(void* buf, size_t count) {
  ssize_t result;
  if (!is_block()) {
    result = Logger::GetInstance()->ReadLogEntry(reader_,
        static_cast<struct logger_entry*>(buf), count);
    if (result < 0) {
      errno = -result;
      return -1;
    }
    return result;
  } else {
    result = Logger::GetInstance()->ReadLogEntry(reader_,
        static_cast<struct logger_entry*>(buf), count);
    if (result == -EAGAIN) {
      Logger::GetInstance()->WaitForReadReady(reader_, &DevLogger::ReadReady);
      VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
      while (result == -EAGAIN) {
        sys->Wait();
        result = Logger::GetInstance()->ReadLogEntry(reader_,
            static_cast<struct logger_entry*>(buf), count);
      }
    }
    if (result >= 0)
      return result;

    errno = -result;
    return -1;
  }
}

ssize_t DevLogger::write(const void* buf, size_t count) {
  errno = EPERM;
  return -1;
}

const char* DevLogger::GetStreamType() const {
  return "dev_logger";
}

bool DevLogger::IsSelectReadReady() const {
  return Logger::GetInstance()->IsReadReady(reader_);
}

int16_t DevLogger::GetPollEvents() const {
  return (IsSelectReadReady() ? POLLIN : 0) | POLLOUT;
}

void DevLogger::ReadReady() {
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  sys->Broadcast();
}

}  // namespace

DevLoggerHandler::DevLoggerHandler()
    : DeviceHandler("DevLoggerHandler") {
}

DevLoggerHandler::~DevLoggerHandler() {
}

scoped_refptr<FileStream> DevLoggerHandler::open(
    int fd, const std::string& pathname, int oflag, mode_t cmode) {
  if (oflag & O_DIRECTORY) {
    errno = ENOTDIR;
    return NULL;
  }
  arc_log_id_t log_id;
  if (!GetLogIdFromPath(pathname, &log_id)) {
    errno = ENOENT;
    return NULL;
  }
  return new DevLogger(pathname, oflag, log_id);
}

int DevLoggerHandler::stat(const std::string& pathname, struct stat* out) {
  arc_log_id_t log_id;
  if (!GetLogIdFromPath(pathname, &log_id)) {
    errno = ENOENT;
    return -1;
  }
  return DoStatLocked(pathname, out);
}

}  // namespace posix_translation
