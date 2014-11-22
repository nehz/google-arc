// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "posix_translation/cpu_info_file.h"

#include <time.h>
#include <unistd.h>
#include <string>
#include <vector>

#include "base/basictypes.h"
#include "base/compiler_specific.h"
#include "base/strings/string_util.h"
#include "base/strings/stringprintf.h"
#include "posix_translation/readonly_memory_file.h"
#include "posix_translation/statfs.h"

namespace posix_translation {

namespace {

// A file stream for readonly files managed by CpuInfoFileHandler.
class CpuInfoFile : public ReadonlyMemoryFile {
 public:
  // Creates a ReadonlyMemoryFile stream with |header| and |footer|.
  // See CpuInfoFileHandler for more details.
  CpuInfoFile(const std::string& pathname,
              const std::string& header,
              const std::string& body,
              const std::string& footer)
      // Pass the UNIX epoch. GetContent() below updates this later.
      : ReadonlyMemoryFile(pathname, EIO, 0),
        num_online_processors_(-1),
        header_(header), body_(body), footer_(footer) {}

 protected:
  virtual ~CpuInfoFile() {}

 private:
  virtual const Content& GetContent() OVERRIDE {
    UpdateContent();
    ALOG_ASSERT(num_online_processors_ > 0);
    ALOG_ASSERT(!content_.empty());
    set_mtime(time(NULL));
    return content_;
  }

  // Updates |content_| when needed.
  void UpdateContent() {
    // The cpuinfo file should be generated based on the number of online
    // CPUs, rather than the number of configured CPUs.
    const int num_online_processors = sysconf(_SC_NPROCESSORS_ONLN);
    ALOG_ASSERT(num_online_processors > 0);

    // We should not update the content when it is unnecessary to not slow down
    // a series of short CpuInfoFile::read() operations to read through the
    // file. Otherwise, in the worst case, they can touch content_.size()
    // squared bytes of memory in total, which can be very slow.
    // TODO(crbug.com/368344): Once _SC_NPROCESSORS_ONLN is fully implemented
    // for Bare Metal ARM, we should check how often the ARM Linux kernel
    // (especially the one for Pit/Pi ARM Chromebooks) changes the number of
    // CPUs in practice.
    if (num_online_processors_ == num_online_processors)
      return;
    num_online_processors_ = num_online_processors;

    std::string s = header_;
    for (int i = 0; i < num_online_processors; ++i) {
      std::vector<std::string> subst;
      subst.push_back(base::StringPrintf("%d", i));
      s += ReplaceStringPlaceholders(body_, subst, NULL);
    }
    s += footer_;
    content_.assign(s.begin(), s.end());
  }

  int num_online_processors_;
  const std::string header_;
  const std::string body_;
  const std::string footer_;
  Content content_;

  DISALLOW_COPY_AND_ASSIGN(CpuInfoFile);
};

}  // namespace

CpuInfoFileHandler::CpuInfoFileHandler(const std::string& header,
                                       const std::string& body,
                                       const std::string& footer)
    : FileSystemHandler("CpuInfoFileHandler"),
      header_(header), body_(body), footer_(footer) {
  // |body| must contain (exactly) one placeholder, "$1".
  ALOG_ASSERT(body_.find("$1") != std::string::npos);
  ALOG_ASSERT(body_.find("$2") == std::string::npos);
}

CpuInfoFileHandler::~CpuInfoFileHandler() {
}

Dir* CpuInfoFileHandler::OnDirectoryContentsNeeded(const std::string& name) {
  return NULL;
}

scoped_refptr<FileStream> CpuInfoFileHandler::open(
    int fd, const std::string& pathname, int oflag, mode_t cmode) {
  if (!EndsWith(pathname, "/cpuinfo", true)) {
    ALOGE("Unknown path: %s. CpuInfoFileHandler might not be mounted properly.",
          pathname.c_str());
    errno = ENOENT;
    return NULL;
  }
  return new CpuInfoFile(pathname, header_, body_, footer_);
}

int CpuInfoFileHandler::stat(const std::string& pathname, struct stat* out) {
  scoped_refptr<FileStream> file = this->open(-1, pathname, O_RDONLY, 0);
  if (!file) {
    ALOGE("Unknown path: %s. CpuInfoFileHandler might not be mounted properly.",
          pathname.c_str());
    errno = ENOENT;
    return -1;
  }
  return file->fstat(out);
}

int CpuInfoFileHandler::statfs(const std::string& pathname,
                               struct statfs* out) {
  return DoStatFsForProc(out);
}

}  // namespace posix_translation
