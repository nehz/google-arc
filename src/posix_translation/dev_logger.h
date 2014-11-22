// Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef POSIX_TRANSLATION_DEV_LOGGER_H_
#define POSIX_TRANSLATION_DEV_LOGGER_H_

#include <string>

#include "base/memory/scoped_ptr.h"
#include "base/compiler_specific.h"
#include "common/export.h"
#include "posix_translation/device_file.h"
#include "posix_translation/file_system_handler.h"

namespace posix_translation {

class ARC_EXPORT DevLoggerHandler : public DeviceHandler {
 public:
  DevLoggerHandler();
  virtual ~DevLoggerHandler();

  virtual scoped_refptr<FileStream> open(
      int fd, const std::string& pathname, int oflag, mode_t cmode) OVERRIDE;
  virtual int stat(const std::string& pathname, struct stat* out) OVERRIDE;

 private:
  DISALLOW_COPY_AND_ASSIGN(DevLoggerHandler);
};

}  // namespace posix_translation
#endif  // POSIX_TRANSLATION_DEV_LOGGER_H_
