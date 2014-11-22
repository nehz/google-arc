// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef POSIX_TRANSLATION_CPU_INFO_FILE_H_
#define POSIX_TRANSLATION_CPU_INFO_FILE_H_

#include <string>

#include "base/basictypes.h"
#include "base/compiler_specific.h"
#include "common/export.h"
#include "posix_translation/file_system_handler.h"

namespace posix_translation {

// A handler for /proc/cpuinfo. This handler returns a file based on the actual
// online processor count.
class ARC_EXPORT CpuInfoFileHandler : public FileSystemHandler {
 public:
  // |header|, |body|, and |footer| are used for generating the content of the
  // cpuinfo file. |body| must contain "$1" and is repeated N times (where N is
  // the number of CPUs online). Both |header| and |footer| can be empty when
  // they are not needed.
  // Example:
  // When N is 2, |header| is "H", |body| is "B$1", and |footer| is "F", the
  // content of the file will be "HB0B1F".
  CpuInfoFileHandler(const std::string& header,
                     const std::string& body,
                     const std::string& footer);
  virtual ~CpuInfoFileHandler();

  // FileSystemHandler overrides:
  virtual Dir* OnDirectoryContentsNeeded(const std::string& name) OVERRIDE;
  virtual scoped_refptr<FileStream> open(
      int fd, const std::string& pathname, int oflag, mode_t cmode) OVERRIDE;
  virtual int stat(const std::string& pathname, struct stat* out) OVERRIDE;
  virtual int statfs(const std::string& pathname, struct statfs* out) OVERRIDE;

 private:
  const std::string header_;
  const std::string body_;
  const std::string footer_;

  DISALLOW_COPY_AND_ASSIGN(CpuInfoFileHandler);
};

}  // namespace posix_translation
#endif  // POSIX_TRANSLATION_CPU_INFO_FILE_H_
