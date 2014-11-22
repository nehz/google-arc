// Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "posix_translation/local_socket.h"

#include <string.h>

#include <algorithm>

#include "common/alog.h"
#include "posix_translation/virtual_file_system.h"

namespace posix_translation {

LocalSocket::LocalSocket(int oflag, int socket_type,
                         LocalSocketType local_socket_type)
    : SocketStream(AF_UNIX, oflag), socket_type_(socket_type),
      local_socket_type_(local_socket_type) {
  // 224K is the default SO_SNDBUF/SO_RCVBUF in the linux kernel.
  if (socket_type == SOCK_STREAM && local_socket_type != WRITE_ONLY)
    buffer_.set_capacity(224*1024);
}

LocalSocket::~LocalSocket() {
}

bool LocalSocket::IsAllowedOnMainThread() const {
  return true;
}

void LocalSocket::OnLastFileRef() {
  if (peer_) {
    peer_->peer_ = NULL;
    peer_ = NULL;
    VirtualFileSystem::GetVirtualFileSystem()->Broadcast();
  }
}

void LocalSocket::set_peer(scoped_refptr<LocalSocket> peer) {
  // Always called by VirtualFileSystem.
  ALOG_ASSERT(peer != NULL);
  peer_ = peer;
}

off64_t LocalSocket::lseek(off64_t offset, int whence) {
  errno = ESPIPE;
  return -1;
}

ssize_t LocalSocket::read(void* buf, size_t count) {
  return this->recv(buf, count, 0);
}

ssize_t LocalSocket::recv(void* buf, size_t len, int flags) {
  return this->recvfrom(buf, len, flags, NULL, NULL);
}

ssize_t LocalSocket::recvfrom(void* buf, size_t len, int flags, sockaddr* addr,
                              socklen_t* addrlen) {
  if (addr || addrlen) {
    errno = EINVAL;
    return -1;
  }
  if (len == 0)
    return 0;

  struct msghdr msg = {};
  struct iovec iov;

  iov.iov_base = buf;
  iov.iov_len = len;
  msg.msg_iov = &iov;
  msg.msg_iovlen = 1;
  return this->recvmsg(&msg, 0);
}

ssize_t LocalSocket::recvmsg(struct msghdr* msg, int flags) {
  if (local_socket_type_ == WRITE_ONLY) {
    // Reading from write socket of a pipe is not allowed.
    errno = EBADF;
    return -1;
  }

  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  if (is_block() && !(flags & MSG_DONTWAIT)) {
    while (peer_ && !IsSelectReadReady()) {
      sys->Wait();
    }
  }

  ssize_t bytes_read = 0;
  if (socket_type_ == SOCK_STREAM) {
    if (buffer_.size() > 0) {
      for (size_t i = 0; i < msg->msg_iovlen && buffer_.size() > 0; ++i) {
        bytes_read += buffer_.read(static_cast<char*>(msg->msg_iov[i].iov_base),
                                   msg->msg_iov[i].iov_len);
      }
    }
  } else {
    if (!queue_.empty()) {
      const std::vector<char>& dgram = queue_.front();
      std::vector<char>::const_iterator iter = dgram.begin();
      size_t left = dgram.size();
      for (size_t i = 0; i < msg->msg_iovlen && left > 0; ++i) {
        size_t len = std::min(msg->msg_iov[i].iov_len, left);
        std::copy(iter, iter + len,
                  static_cast<char*>(msg->msg_iov[i].iov_base));
        left -= len;
        iter += len;
      }
      if (left > 0)
        msg->msg_flags |= MSG_TRUNC;
      bytes_read = dgram.size() - left;
      queue_.pop_front();
    }
  }

  // If no bytes are read in recvmsg, control messages are not returned either.
  if (bytes_read > 0 && !cmsg_fd_queue_.empty()) {
    std::vector<int>& fds = cmsg_fd_queue_.front();
    size_t sizeof_int = sizeof(int);  // NOLINT(runtime/sizeof)

    socklen_t cmsg_len = CMSG_LEN(fds.size() * sizeof_int);
    while (CMSG_SPACE(cmsg_len) > msg->msg_controllen && !fds.empty()) {
      // Cleanup file descriptors that are not passed back to the client so we
      // do not leak them.  Close the last ones first so it acts like a FIFO.
      // This is not part of any spec, but just makes the most intuitive sense.
      int fd = fds.back();
      sys->CloseLocked(fd);
      fds.pop_back();
      cmsg_len = CMSG_LEN(fds.size() * sizeof_int);
      msg->msg_flags |= MSG_CTRUNC;
    }

    if (msg->msg_controllen) {
      struct cmsghdr* cmsg = CMSG_FIRSTHDR(msg);
      cmsg->cmsg_level = SOL_SOCKET;
      cmsg->cmsg_type = SCM_RIGHTS;
      cmsg->cmsg_len = cmsg_len;
      memcpy(CMSG_DATA(cmsg), &fds[0], fds.size() * sizeof_int);
    }
    cmsg_fd_queue_.pop_front();
  }

  if (bytes_read > 0) {
    // Notify any listeners waiting to write on the peer.
    if (peer_)
      peer_->NotifyListeners();
    return bytes_read;
  }

  if (!peer_) {
    // The other end of the socketpair has been closed, returns EOF(0).
    return 0;
  }
  errno = EAGAIN;

  return -1;
}

ssize_t LocalSocket::send(const void* buf, size_t len, int flags) {
  return this->sendto(buf, len, flags, NULL, 0);
}

ssize_t LocalSocket::sendto(const void* buf, size_t len, int flags,
                            const sockaddr* dest_addr, socklen_t addrlen) {
  if (dest_addr || addrlen) {
    errno = EINVAL;
    return -1;
  }

  if (len == 0)
    return 0;

  struct msghdr msg = {};
  struct iovec iov;

  // This is passed in as a member of a const struct msghdr below, so casting
  // away constness is ok here.
  iov.iov_base = const_cast<void*>(buf);
  iov.iov_len = len;
  msg.msg_iov = &iov;
  msg.msg_iovlen = 1;
  return this->sendmsg(&msg, 0);
}

ssize_t LocalSocket::sendmsg(const struct msghdr* msg, int flags) {
  if (local_socket_type_ == READ_ONLY) {
    errno = EBADF;
    return -1;
  }

  if (peer_)
    return peer_->HandleSendmsgLocked(msg);
  errno = ECONNRESET;
  return -1;
}

ssize_t LocalSocket::write(const void* buf, size_t count) {
  return this->send(buf, count, 0);
}

int LocalSocket::ioctl(int request, va_list ap) {
  if (request == FIONREAD) {
    int* out = va_arg(ap, int*);
    if (socket_type_ == SOCK_STREAM) {
      *out = buffer_.size();
    } else {
      if (!queue_.empty())
        *out = queue_.front().size();
      else
        *out = 0;
    }
    return 0;
  } else {
    errno = EINVAL;
    return -1;
  }
}

bool LocalSocket::IsSelectReadReady() const {
  if (socket_type_ == SOCK_STREAM)
    return buffer_.size() > 0 || !peer_;
  else
    return !queue_.empty();
}

bool LocalSocket::IsSelectWriteReady() const {
  if (local_socket_type_ == READ_ONLY || peer_ == NULL)
    return false;
  return peer_->CanWrite();
}

bool LocalSocket::IsSelectExceptionReady() const {
  return !peer_;
}

int16_t LocalSocket::GetPollEvents() const {
  // Currently we use IsSelect*Ready() family temporarily (and wrongly).
  // TODO(crbug.com/359400): Fix the implementation.
  return ((IsSelectReadReady() ? POLLIN : 0) |
          (IsSelectWriteReady() ? POLLOUT : 0) |
          (IsSelectExceptionReady() ? POLLERR : 0));
}

bool LocalSocket::CanWrite() const {
  if (socket_type_ == SOCK_STREAM)
    return buffer_.size() < buffer_.capacity();
  return true;
}

ssize_t LocalSocket::HandleSendmsgLocked(const struct msghdr* msg) {
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  sys->mutex().AssertAcquired();

  const struct iovec* buf = msg->msg_iov;
  size_t len = msg->msg_iovlen;

  ssize_t bytes_sent = 0;
  size_t bytes_attempted = 0;
  if (len > 0) {
    if (socket_type_ == SOCK_STREAM) {
      for (size_t i = 0; i < len; ++i) {
        bytes_attempted += buf[i].iov_len;
        bytes_sent += buffer_.write(static_cast<const char*>(buf[i].iov_base),
                                    buf[i].iov_len);
      }
    } else {
      queue_.resize(queue_.size() + 1);
      for (size_t i = 0; i < len; ++i) {
        const char* begin = static_cast<const char*>(buf[i].iov_base);
        const char* end = begin + buf[i].iov_len;
        queue_.back().insert(queue_.back().end(), begin, end);
        bytes_attempted += buf[i].iov_len;
        bytes_sent += buf[i].iov_len;
      }
    }
  }

  // If we did not send any bytes, do not process any control messages either.
  if (bytes_sent && msg->msg_controllen > 0) {
    size_t sizeof_int = sizeof(int);  // NOLINT(runtime/sizeof)
    // The CMSG macros cannot deal with const msghdrs, so cast away constness
    // for this section, but make all access to the underlying data through
    // const local variables.
    struct msghdr* nonconst_msg = const_cast<struct msghdr*>(msg);
    cmsg_fd_queue_.resize(cmsg_fd_queue_.size() + 1);
    std::vector<int>& fds = cmsg_fd_queue_.back();
    for (struct cmsghdr* cmsg = CMSG_FIRSTHDR(nonconst_msg);
         cmsg;
         cmsg = CMSG_NXTHDR(nonconst_msg, cmsg)) {
      // We only support one control message, specifically of type
      // SCM_RIGHTS to send file descriptors.
      ALOG_ASSERT(cmsg->cmsg_level == SOL_SOCKET);
      ALOG_ASSERT(cmsg->cmsg_type == SCM_RIGHTS);
      if (cmsg->cmsg_level == SOL_SOCKET &&
          cmsg->cmsg_type == SCM_RIGHTS &&
          cmsg->cmsg_len >= CMSG_LEN(0)) {
        size_t payload_len = cmsg->cmsg_len - CMSG_LEN(0);
        ALOG_ASSERT(payload_len % sizeof_int == 0);
        const int *wire_fds = reinterpret_cast<const int*>(CMSG_DATA(cmsg));
        size_t wire_fds_len = payload_len / sizeof_int;
        // Dup the file descriptors before adding them to the control message.
        // This emulates what happens in Posix when sending file descriptors in
        // the same process (as webviewchromium does).
        for (size_t i = 0; i < wire_fds_len; ++i)
          fds.push_back(sys->DupLocked(wire_fds[i], -1));
      }
    }
  }

  if (bytes_sent > 0) {
    sys->Broadcast();
    NotifyListeners();
  }

  if (bytes_sent == 0 && bytes_attempted != 0) {
    errno = EAGAIN;
    return -1;
  }

  return bytes_sent;
}

const char* LocalSocket::GetStreamType() const {
  return "local_socket";
}

}  // namespace posix_translation
