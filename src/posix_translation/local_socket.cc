// Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "posix_translation/local_socket.h"

#include <string.h>

#include <algorithm>
#include <string>

#include "common/alog.h"
#include "common/process_emulator.h"
#include "posix_translation/socket_util.h"
#include "posix_translation/time_util.h"
#include "posix_translation/virtual_file_system.h"

namespace posix_translation {

LocalSocket::LocalSocket(int oflag, int socket_type,
                         StreamDir stream_dir)
    : SocketStream(AF_UNIX, oflag), socket_type_(socket_type),
      connect_state_(SOCKET_NEW), stream_dir_(stream_dir),
      connection_backlog_(0) {
  // 224K is the default SO_SNDBUF/SO_RCVBUF in the linux kernel.
  if (socket_type == SOCK_STREAM && stream_dir != WRITE_ONLY)
    buffer_.set_capacity(224*1024);
  my_cred_.pid = arc::ProcessEmulator::GetPid();
  my_cred_.uid = arc::ProcessEmulator::GetUid();
  my_cred_.gid = my_cred_.uid;
  // These values are empirically what SO_PEERCRED returns when
  // there has never been a peer to the socket.
  peer_cred_.pid = 0;
  peer_cred_.uid = -1;
  peer_cred_.gid = -1;
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
    // Note that the peer_ == NULL and connect_state_ == SOCKET_CONNECTED
    // means the connection has been closed.
    VirtualFileSystem::GetVirtualFileSystem()->Broadcast();
  }
  if (!abstract_name_.empty()) {
    VirtualFileSystem::GetVirtualFileSystem()->
        GetAbstractSocketNamespace()->Bind(abstract_name_, NULL);
  }
}

void LocalSocket::set_peer(scoped_refptr<LocalSocket> peer) {
  // Always called by VirtualFileSystem.
  ALOG_ASSERT(peer != NULL);
  peer_ = peer;
  connect_state_ = SOCKET_CONNECTED;
  peer_cred_ = peer->my_cred_;
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

bool LocalSocket::ConvertSockaddrToAbstractName(const sockaddr* addr,
                                                socklen_t addrlen,
                                                std::string* out_name) {
  const sockaddr_un* saddr_un = reinterpret_cast<const sockaddr_un*>(addr);
  const socklen_t kSunPathOffset =
      static_cast<socklen_t>(offsetof(struct sockaddr_un, sun_path));
  if (addrlen < kSunPathOffset + 1) {
    // Technically a sun_path of length 0 is valid, but we cannot use
    // it.  And anything less than 0 is of course invalid and results
    // in EINVAL.  We combine those together.
    errno = EINVAL;
    return false;
  }
  if (saddr_un->sun_path[0] != '\0') {
    // We do not support sockets to VFS paths yet, sorry.
    errno = ENOSYS;
    return false;
  }
  socklen_t sun_path_length = addrlen - kSunPathOffset;
  out_name->assign(saddr_un->sun_path + 1, sun_path_length - 1);
  return true;
}

int LocalSocket::bind(const sockaddr* addr, socklen_t addrlen) {
  // You can call bind on a new or connected socket, Linux does not care.
  // You cannot call bind on a pipe, which is also implemented by LocalSocket,
  // because it is not a socket.  We do not catch that case here, but we
  // also do not catch this case in recv/send/recvfrom/sendto/recvmsg/sendmsg,
  // all of which require a socket.
  // TODO(crbug.com/447833): Split out pipes.
  if (addr->sa_family != AF_UNIX) {
    // Observed the error EINVAL when AF_UNIX is given to socket and
    // AF_UNIX is given to bind.
    errno = EINVAL;
    return -1;
  }
  if (!abstract_name_.empty()) {
    // Trying to bind a second name to a single socket fails.
    errno = EINVAL;
    return -1;
  }
  std::string abstract_name;
  if (!ConvertSockaddrToAbstractName(addr, addrlen, &abstract_name))
    return -1;
  int result = VirtualFileSystem::GetVirtualFileSystem()->
      GetAbstractSocketNamespace()->Bind(abstract_name, this);
  if (result == 0)
    abstract_name_ = abstract_name;
  return result;
}

int LocalSocket::listen(int backlog) {
  if (abstract_name_.empty()) {
    // Observed the error EINVAL when listen is called on an unbound
    // socket.
    errno = EINVAL;
    return -1;
  }
  connect_state_ = SOCKET_LISTENING;
  connection_backlog_ = backlog;
  return 0;
}

int LocalSocket::getsockopt(int level, int optname, void* optval,
                             socklen_t* optlen) {
  if (level == SOL_SOCKET && optname == SO_PEERCRED) {
    *optlen = std::min(*optlen, socklen_t(sizeof(peer_cred_)));
    memcpy(optval, &peer_cred_, *optlen);
    return 0;
  }
  return SocketStream::getsockopt(level, optname, optval, optlen);
}

bool LocalSocket::HandleConnectLocked(LocalSocket* connecting) {
  if (connect_state_ != SOCKET_LISTENING) {
    ALOGW("LocalSocket::connect failed - receiving socket not listening");
    return false;
  }
  if (connection_backlog_ == connection_queue_.size()) {
    ALOGW("LocalSocket::connect failed - queue for %s full",
          abstract_name_.c_str());
    return false;
  }
  connection_queue_.push_back(connecting);
  if (connection_queue_.size() == 1) {
    // In case we are already blocking on an accept, wake it up now...
    VirtualFileSystem::GetVirtualFileSystem()->Broadcast();
    // and also notify any polls/selects listening to it.
    NotifyListeners();
  }
  return true;
}

void LocalSocket::WaitForLocalSocketConnect() {
  // The accept() call will set the peer and tell us when to proceed.
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  connect_state_ = SOCKET_CONNECTING;
  while (connect_state_ == SOCKET_CONNECTING) {
    sys->Wait();
  }
}

int LocalSocket::connect(const sockaddr* addr, socklen_t addrlen) {
  if (connect_state_ == SOCKET_CONNECTED ||
      connect_state_ == SOCKET_LISTENING) {
    errno = EISCONN;
    return -1;
  }
  if (addr->sa_family != AF_UNIX) {
    // Observed the error EINVAL when AF_UNIX is given to socket and
    // AF_UNIX is given to connect.
    errno = EINVAL;
    return -1;
  }
  if (!is_block()) {
    ALOGE("Non-blocking local socket connect not supported.\n");
    errno = ENOSYS;
    return -1;
  }
  std::string abstract_name;
  if (!ConvertSockaddrToAbstractName(addr, addrlen, &abstract_name))
    return -1;
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  scoped_refptr<LocalSocket> listening_socket =
      sys->GetAbstractSocketNamespace()->GetByName(abstract_name);
  if (listening_socket == NULL) {
    // Connection to unbound abstract name returns ECONNREFUSED.
    errno = ECONNREFUSED;
    return -1;
  }
  if (!listening_socket->HandleConnectLocked(this)) {
    errno = ECONNREFUSED;
    return -1;
  }
  WaitForLocalSocketConnect();
  return 0;
}

void LocalSocket::WaitForOpenedConnectToAccept() {
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  const base::TimeTicks time_limit =
      internal::TimeOutToTimeLimit(recv_timeout_);
  do {
    // Skip any queued connects which have since been closed.
    while (!connection_queue_.empty() &&
           connection_queue_.front()->IsClosed()) {
      ALOGW("LocalSocket::accept - enqueued connection was preemptively "
            "closed");
      connection_queue_.pop_front();
    }
    if (!connection_queue_.empty()) break;
  } while (!sys->WaitUntil(time_limit));
}

int LocalSocket::accept(sockaddr* addr, socklen_t* addrlen) {
  if (addr) {
    int error = internal::VerifyOutputSocketAddress(addr, addrlen);
    if (error) {
      errno = error;
      return -1;
    }
  }

  if (connect_state_ != SOCKET_LISTENING) {
    errno = EINVAL;
    return -1;
  }

  if (!is_block()) {
    ALOGE("Non-blocking local socket accept not supported.\n");
    errno = ENOSYS;
    return -1;
  }
  WaitForOpenedConnectToAccept();
  if (IsClosed()) {
    ALOGW("LocalSocket::accept - Listening socket closed while in waiting");
    errno = EBADF;
    return -1;
  }
  if (connection_queue_.empty()) {
    errno = EAGAIN;
    return -1;
  }
  // Create a peer server socket for the client socket at the head of the
  // connection queue.
  scoped_refptr<LocalSocket> server_socket =
      new LocalSocket(oflag(), SOCK_STREAM, READ_WRITE);
  VirtualFileSystem* sys = VirtualFileSystem::GetVirtualFileSystem();
  int accept_fd = sys->AddFileStreamLocked(server_socket);
  if (accept_fd < 0) {
    ALOGW("LocalSocket::accept - out of fds creating accepted fd");
    errno = EMFILE;
    return -1;
  }
  scoped_refptr<LocalSocket> client_socket = connection_queue_.front();
  connection_queue_.pop_front();
  server_socket->set_peer(client_socket);
  client_socket->set_peer(server_socket);
  sys->Broadcast();
  NotifyListeners();
  if (addr) {
    sockaddr_un output = {};
    output.sun_family = AF_UNIX;
    memcpy(addr, &output, std::min(*addrlen, socklen_t(sizeof(sa_family_t))));
    *addrlen = sizeof(sa_family_t);
  }
  return accept_fd;
}

int LocalSocket::recvmsg(struct msghdr* msg, int flags) {
  if (stream_dir_ == WRITE_ONLY) {
    // Reading from write socket of a pipe is not allowed.
    errno = EBADF;
    return -1;
  }

  if (connect_state_ != SOCKET_CONNECTED) {
    errno = EINVAL;
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

    socklen_t cmsg_len = CMSG_LEN(fds.size() * sizeof(int));  // NOLINT
    while (CMSG_SPACE(cmsg_len) > msg->msg_controllen && !fds.empty()) {
      // Cleanup file descriptors that are not passed back to the client so we
      // do not leak them.  Close the last ones first so it acts like a FIFO.
      // This is not part of any spec, but just makes the most intuitive sense.
      int fd = fds.back();
      sys->CloseLocked(fd);
      fds.pop_back();
      cmsg_len = CMSG_LEN(fds.size() * sizeof(int));  // NOLINT
      msg->msg_flags |= MSG_CTRUNC;
    }

    if (msg->msg_controllen) {
      struct cmsghdr* cmsg = CMSG_FIRSTHDR(msg);
      cmsg->cmsg_level = SOL_SOCKET;
      cmsg->cmsg_type = SCM_RIGHTS;
      cmsg->cmsg_len = cmsg_len;
      memcpy(CMSG_DATA(cmsg), &fds[0], fds.size() * sizeof(int));  // NOLINT
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

int LocalSocket::sendmsg(const struct msghdr* msg, int flags) {
  if (stream_dir_ == READ_ONLY) {
    errno = EBADF;
    return -1;
  }

  if (connect_state_ != SOCKET_CONNECTED) {
    errno = EINVAL;
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
  }
  return SocketStream::ioctl(request, ap);
}

bool LocalSocket::IsSelectReadReady() const {
  if (socket_type_ == SOCK_STREAM)
    return buffer_.size() > 0 || !peer_;
  else
    return !queue_.empty();
}

bool LocalSocket::IsSelectWriteReady() const {
  if (stream_dir_ == READ_ONLY || peer_ == NULL)
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

int LocalSocket::HandleSendmsgLocked(const struct msghdr* msg) {
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
        ALOG_ASSERT(payload_len % sizeof(int) == 0);  // NOLINT
        const int *wire_fds = reinterpret_cast<const int*>(CMSG_DATA(cmsg));
        size_t wire_fds_len = payload_len / sizeof(int);  // NOLINT
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
