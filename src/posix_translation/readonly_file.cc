// Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "posix_translation/readonly_file.h"

#include <arpa/inet.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>

#include "base/strings/string_piece.h"
#include "base/strings/string_util.h"
#include "base/synchronization/lock.h"
#include "common/arc_strace.h"
#include "posix_translation/dir.h"
#include "posix_translation/directory_file_stream.h"
#include "posix_translation/nacl_manifest_file.h"
#include "posix_translation/statfs.h"

namespace posix_translation {

ReadonlyFileHandler::ReadonlyFileHandler(const std::string& image_filename,
                                         size_t read_ahead_size,
                                         FileSystemHandler* underlying_handler)
    : FileSystemHandler("ReadonlyFileHandler"),
      image_filename_(image_filename),
      read_ahead_size_(read_ahead_size),
      underlying_handler_(underlying_handler),
      image_stream_(NULL),
      directory_mtime_(0) {
  if (!underlying_handler)
    ALOGW("NULL underlying handler is passed");  // this is okay for unit tests
  ALOG_ASSERT(read_ahead_size_ > 0);
}

ReadonlyFileHandler::~ReadonlyFileHandler() {
  // Destructing |image_stream_| without holding the VirtualFileSystem::mutex_
  // lock is safe because |image_stream_| is the only object that manipulates
  // the ref counter in the file stream obtained from |underlying_handler|.
}

bool ReadonlyFileHandler::ParseReadonlyFsImage() {
  ALOG_ASSERT(image_stream_);

  struct stat buf = {};
  if (image_stream_->fstat(&buf)) {
    ALOGE("fstat %s failed", image_filename_.c_str());
    return false;
  }

  void* addr = image_stream_->mmap(
      NULL, buf.st_size, PROT_READ, MAP_PRIVATE, 0);
  if (addr == MAP_FAILED) {
    ALOGE("mmap %s failed", image_filename_.c_str());
    return false;
  }
  image_reader_.reset(new ReadonlyFsReader(static_cast<uint8_t*>(addr)));

  // Unmap the image immediately so that it will not take up virtual address
  // space. However, keep the stream open for later use.
  if (image_stream_->munmap(addr, buf.st_size) < 0) {
    ALOGE("munmap %p with size=%llu failed",
          addr, static_cast<uint64_t>(buf.st_size));
    return false;
  }
  directory_mtime_ = buf.st_mtime;

  return true;
}

scoped_refptr<FileStream> ReadonlyFileHandler::CreateFileLocked(
    const std::string& pathname, int oflag) {
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  sys->mutex().AssertAcquired();

  ReadonlyFsReader::Metadata metadata;
  if (!image_reader_->GetMetadata(pathname, &metadata)) {
    errno = ENOENT;
    return NULL;
  }
  if (oflag & O_DIRECTORY) {
    errno = ENOTDIR;
    return NULL;
  }

  return new ReadonlyFile(image_stream_, read_ahead_size_, pathname,
                          metadata.offset, metadata.size, metadata.mtime,
                          oflag);
}

bool ReadonlyFileHandler::IsInitialized() const {
  if (!underlying_handler_)
    return true;  // for testing.
  return image_stream_ && underlying_handler_->IsInitialized();
}

void ReadonlyFileHandler::Initialize() {
  ALOG_ASSERT(!IsInitialized());
  ALOG_ASSERT(underlying_handler_);
  if (!underlying_handler_->IsInitialized())
    underlying_handler_->Initialize();
  image_stream_ =
      underlying_handler_->open(-1, image_filename_.c_str(), O_RDONLY, 0);
  if (!image_stream_) {
    ALOGE("Failed to open %s", image_filename_.c_str());
    return;
  }
  ARC_STRACE_REPORT("parsing an image file: %s", image_filename_.c_str());
  if (!ParseReadonlyFsImage()) {
    ALOG_ASSERT(false, "Failed to parse %s", image_filename_.c_str());
    image_stream_ = NULL;
  }
}

scoped_refptr<FileStream> ReadonlyFileHandler::open(
    int fd, const std::string& pathname, int oflag, mode_t cmode) {
  const bool is_directory = image_reader_->IsDirectory(pathname);
  if (oflag & (O_WRONLY | O_RDWR)) {
    errno = (is_directory ? EISDIR : EACCES);
    return NULL;
  }
  if (is_directory) {
    return new DirectoryFileStream(
        "readonly", pathname, this, directory_mtime_);
  }
  return CreateFileLocked(pathname, oflag);
}

Dir* ReadonlyFileHandler::OnDirectoryContentsNeeded(const std::string& name) {
  return image_reader_->OpenDirectory(name);
}

int ReadonlyFileHandler::stat(const std::string& pathname, struct stat* out) {
  // Since ReadonlyFileHandler::open() is always fast, emulate stat with fstat.
  scoped_refptr<FileStream> file = this->open(-1, pathname, O_RDONLY, 0);
  if (file)
    return file->fstat(out);
  errno = ENOENT;
  return -1;
}

int ReadonlyFileHandler::statfs(const std::string& pathname,
                                struct statfs* out) {
  if (image_reader_->Exist(pathname)) {
    if (base::StringPiece(pathname).starts_with("/proc"))
      return DoStatFsForProc(out);
    else
      return DoStatFsForSystem(out);
  }
  errno = ENOENT;
  return -1;
}

int ReadonlyFileHandler::mkdir(const std::string& pathname, mode_t mode) {
  if (image_reader_->Exist(pathname)) {
    errno = EEXIST;
    return -1;
  }
  errno = EACCES;
  return -1;
}

int ReadonlyFileHandler::rename(const std::string& oldpath,
                                const std::string& newpath) {
  if (!image_reader_->Exist(oldpath) || newpath.empty()) {
    errno = ENOENT;
    return -1;
  }
  if (oldpath == newpath)
    return 0;
  errno = EACCES;
  return -1;
}

int ReadonlyFileHandler::truncate(const std::string& pathname, off64_t length) {
  if (!image_reader_->Exist(pathname))
    errno = ENOENT;
  else
    errno = EACCES;
  return -1;
}

int ReadonlyFileHandler::unlink(const std::string& pathname) {
  if (!image_reader_->Exist(pathname))
    errno = ENOENT;
  else
    errno = EACCES;
  return -1;
}

int ReadonlyFileHandler::utimes(const std::string& pathname,
                                const struct timeval times[2]) {
  errno = EROFS;
  return -1;
}

ssize_t ReadonlyFileHandler::readlink(const std::string& pathname,
                                      std::string* resolved) {
  ReadonlyFsReader::Metadata metadata;
  // This function can be called before ParseReadonlyFsImage().
  if (image_reader_ &&
      image_reader_->GetMetadata(pathname, &metadata) &&
      metadata.file_type == ReadonlyFsReader::kSymbolicLink) {
    *resolved = metadata.link_target;
    return resolved->size();
  }
  errno = EINVAL;
  return -1;
}

//------------------------------------------------------------------------------

ReadonlyFile::ReadonlyFile(scoped_refptr<FileStream> image_stream,
                           size_t read_ahead_size,
                           const std::string& pathname,
                           off_t file_offset, size_t file_size, time_t mtime,
                           int oflag)
  : FileStream(oflag, pathname),
    write_mapped_(false), image_stream_(image_stream),
    read_ahead_buf_max_size_(read_ahead_size), read_ahead_buf_offset_(0),
    offset_in_image_(file_offset), size_(file_size), mtime_(mtime), pos_(0) {
  ALOG_ASSERT(image_stream_);
  ALOG_ASSERT(!pathname.empty());
  ARC_STRACE_REPORT(
      "%s is at offset 0x%08llx", pathname.c_str(), offset_in_image_);
}

ReadonlyFile::~ReadonlyFile() {}

int ReadonlyFile::madvise(void* addr, size_t length, int advice) {
  if (advice != MADV_DONTNEED)
    return FileStream::madvise(addr, length, advice);

  // Note: We should have |write_mapped_| here rather than in NaClManifestFile
  // because the underlying stream is shared by all ReadonlyFile streams.

  if (write_mapped_) {
    // madvise(MADV_DONTNEED) is called against a region possibly mapped with
    // PROT_WRITE and MAP_PRIVATE (yes, creating a writable map backed by a
    // read-only file is possible). Since there is no reliable way to determine
    // mmap parameters (e.g. a file offset which corresponds to the |addr|) for
    // emulating MADV_DONTNEED, returns -1 with EINVAL.
    // TODO(crbug.com/425955): Remove this restriction once the bug is fixed.
    // See the other TODO(crbug.com/425955) below for more details.
    ALOGW("MADV_DONTNEED is called against a writable region backed by a "
          "read-only file %s (address=%p). This is not supported.",
          pathname().c_str(), addr);
    errno = EINVAL;
    return -1;
  }

  // Since both the mapping and the file are read-only, returning 0 for
  // MADV_DONTNEED without mapping the underlying file again is safe. However,
  // this does not properly reduce the resident memory usage.
  // TODO(crbug.com/425955): For better resident memory usage, do either of
  // the following: (1) Add mprotect IRT to SFI and non-SFI NaCl and just call
  // it, or (2) add a way to query the current prot, flags, and file offset of
  // the |addr| (likely by improving the MemoryRegion class), and call mmap IRT
  // again with these parameters plus MAP_FIXED. Both ways can be applied to
  // nacl_manifest_file.cc (which is almost always mapped with PROT_WRITE to
  // make .bss work) and pepper_file.cc (which is writable persistent file
  // system) too.
  ALOGW("MADV_DONTNEED is called against a read-only file %s (address=%p). "
        "Returning 0 without releasing resident memory pages.",
        pathname().c_str(), addr);
  return 0;
}

void* ReadonlyFile::mmap(
    void* addr, size_t length, int prot, int flags, off_t offset) {
  // TODO(crbug.com/326219): Implement a real proc file system and remove this
  // check.
  if (StartsWithASCII(pathname(), "/proc/", true)) {
    errno = EIO;
    return MAP_FAILED;
  }
  write_mapped_ |= prot & PROT_WRITE;
  // Note: We should check neither |length| nor |offset| here to be consistent
  // with Linux kernel's behavior. The kernel allows |length| and |offset|
  // values greater than the size of the file as long as the |length| fits in
  // the virtual address space and the |offset| is multiples of the page size.
  // Mapped pages that do not have backing file are treated like PROT_NONE pages
  // (i.e. SIGBUS when touched). We are not always able to raise SIGBUS
  // (instead, subsequent files in the image might be accessed), but this is
  // much better than returing MAP_FAILED here in terms of app compatibility.
  return image_stream_->mmap(
      addr, length, prot, flags, offset + offset_in_image_);
}

int ReadonlyFile::mprotect(void* addr, size_t length, int prot) {
  write_mapped_ |= prot & PROT_WRITE;
  return image_stream_->mprotect(addr, length, prot);
}

int ReadonlyFile::munmap(void* addr, size_t length) {
  return image_stream_->munmap(addr, length);
}

ssize_t ReadonlyFile::read(void* buf, size_t count) {
  const ssize_t read_size = PreadImpl(buf, count, pos_, true /* read-ahead */);
  if (read_size > 0)
    pos_ += read_size;
  return read_size;
}

ssize_t ReadonlyFile::write(const void* buf, size_t count) {
  errno = EINVAL;
  return -1;
}

ssize_t ReadonlyFile::pread(void* buf, size_t count, off64_t offset) {
  return PreadImpl(buf, count, offset, false /* no read-ahead */);
}

ssize_t ReadonlyFile::PreadImpl(void* buf, size_t count, off64_t offset,
                                bool can_read_ahead) {
  // Since the image file which |image_stream_| points to is much larger
  // than |size_|, we need to adjust |count| so that pread() below does
  // not read the next file in the image.
  const ssize_t read_max = size_ - offset;
  if (read_max <= 0)
    return 0;
  const size_t read_size = std::min<size_t>(count, read_max);

  // Check if [offset, offset + read_size) is inside the read-ahead cache.
  if (read_ahead_buf_offset_ <= offset &&
      offset < read_ahead_buf_offset_ + read_ahead_buf_.size() &&
      offset + read_size <= read_ahead_buf_offset_ + read_ahead_buf_.size()) {
    ARC_STRACE_REPORT("Cache hit: pread %zu bytes from the read ahead cache",
                        read_size);
    const off_t offset_in_cache = offset - read_ahead_buf_offset_;
    memcpy(buf, &read_ahead_buf_[0] + offset_in_cache, read_size);
    return read_size;
  }

  // When |read_size| is large enough, do not try to use |read_ahead_buf_| to
  // avoid unnecessary memcpy.
  const int64_t pread_offset_in_image = offset_in_image_ + offset;
  if ((read_size >= read_ahead_buf_max_size_) || !can_read_ahead) {
    ARC_STRACE_REPORT("pread %zu bytes from the image at offset 0x%08llx",
                        read_size, pread_offset_in_image);
    return image_stream_->pread(buf, read_size, pread_offset_in_image);
  }

  // We should not read beyond the end of the file even though the underlying
  // handler may allow it. Therefore the min() call.
  read_ahead_buf_.resize(read_ahead_buf_max_size_);
  const size_t read_ahead_size =
      std::min<size_t>(read_ahead_buf_max_size_, read_max);
  ARC_STRACE_REPORT("Cache miss: "
                      "pread-ahead %zu bytes from the image at offset 0x%08llx",
                      read_ahead_size, pread_offset_in_image);

  // Note: The underlying pread() is allowed to return a value smaller than
  // |read_ahead_size| although it does not do that in practice.
  const ssize_t pread_result = image_stream_->pread(
      &read_ahead_buf_[0], read_ahead_size, pread_offset_in_image);
  if (pread_result <= 0) {
    if (pread_result < 0 && errno == EINTR)
      read_ahead_buf_.clear();
    return pread_result;  // except the EINTR case, the cache remains intact
  }

  // Update the read-ahead cache.
  ARC_STRACE_REPORT("Update the read ahead cache: "
                    "%zd bytes from the image at offset 0x%08llx",
                    pread_result, pread_offset_in_image);
  read_ahead_buf_.resize(pread_result);
  read_ahead_buf_offset_ = offset;

  // Call min() again not to overflow the |buf| buffer.
  const size_t copy_size = std::min<size_t>(read_size, pread_result);
  memcpy(buf, &read_ahead_buf_[0], copy_size);
  return copy_size;
}

off64_t ReadonlyFile::lseek(off64_t offset, int whence) {
  switch (whence) {
    case SEEK_SET:
      pos_ = offset;
      return pos_;
    case SEEK_CUR:
      pos_ += offset;
      return pos_;
    case SEEK_END:
      pos_ = size_ + offset;
      return pos_;
    default:
      errno = EINVAL;
      return -1;
  }
  return 0;
}

int ReadonlyFile::fdatasync() {
  return this->fsync();
}

int ReadonlyFile::fstat(struct stat* out) {
  memset(out, 0, sizeof(struct stat));
  ALOG_ASSERT(!pathname().empty());
  out->st_ino = inode();
  out->st_mode = S_IFREG;
  out->st_nlink = 1;
  out->st_size = size_;
  out->st_mtime = mtime_;
  out->st_blksize = 4096;
  // TODO(crbug.com/242337): Fill other fields.
  return 0;
}

int ReadonlyFile::fsync() {
  // TODO(crbug.com/236900): Hard-coding "/proc" here does not look very good.
  // Revisit this when we implement /proc/self/maps. Note that ARC does not
  // handle /proc/self/exe with this class.
  if (StartsWithASCII(pathname(), "/proc/", true)) {
    errno = EINVAL;
    return -1;
  }
  return 0;
}

int ReadonlyFile::ioctl(int request, va_list ap) {
  if (request == FIONREAD) {
    // According to "man ioctl_list", FIONREAD stores its value as an int*.
    int* argp = va_arg(ap, int*);
    *argp = size_ - pos_;
    return 0;
  }
  ALOGE("ioctl command %d not supported\n", request);
  errno = EINVAL;
  return -1;
}

bool ReadonlyFile::IsSelectWriteReady() const {
  return false;
}

const char* ReadonlyFile::GetStreamType() const {
  return "readonly";
}

size_t ReadonlyFile::GetSize() const {
  // Note: sys->mutex() must be held here.
  return size_;
}

}  // namespace posix_translation
