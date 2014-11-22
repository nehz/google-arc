// Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef POSIX_TRANSLATION_LOCAL_SOCKET_H_
#define POSIX_TRANSLATION_LOCAL_SOCKET_H_

#include <fcntl.h>
#include <sys/socket.h>

#include <deque>
#include <vector>

#include "base/basictypes.h"
#include "base/compiler_specific.h"
#include "common/circular_buffer.h"
#include "posix_translation/socket_stream.h"

namespace posix_translation {

class LocalSocket : public SocketStream {
 public:
  enum LocalSocketType {
    READ_ONLY,
    WRITE_ONLY,
    READ_WRITE
  };

  LocalSocket(int oflag, int socket_type,
              LocalSocketType local_socket_type);

  bool is_block() { return !(oflag() & O_NONBLOCK); }

  void set_peer(scoped_refptr<LocalSocket> peer);

  // LocalSocket can work on main thread because it does not use Pepper file IO
  // for its implementation.
  virtual bool IsAllowedOnMainThread() const OVERRIDE;

  virtual off64_t lseek(off64_t offset, int whence) OVERRIDE;
  virtual ssize_t read(void* buf, size_t count) OVERRIDE;
  virtual ssize_t recv(void* buf, size_t len, int flags) OVERRIDE;
  virtual ssize_t recvfrom(void* buf, size_t len, int flags, sockaddr* addr,
                           socklen_t* addrlen) OVERRIDE;
  virtual ssize_t recvmsg(struct msghdr* msg, int flags) OVERRIDE;
  virtual ssize_t send(const void* buf, size_t len, int flags) OVERRIDE;
  virtual ssize_t sendto(const void* buf, size_t len, int flags,
                         const sockaddr* dest_addr, socklen_t addrlen) OVERRIDE;
  virtual ssize_t sendmsg(const struct msghdr* msg, int flags) OVERRIDE;
  virtual ssize_t write(const void* buf, size_t count) OVERRIDE;

  virtual int ioctl(int request, va_list ap) OVERRIDE;

  virtual bool IsSelectReadReady() const OVERRIDE;
  virtual bool IsSelectWriteReady() const OVERRIDE;
  virtual bool IsSelectExceptionReady() const OVERRIDE;
  virtual int16_t GetPollEvents() const OVERRIDE;

  virtual const char* GetStreamType() const OVERRIDE;

 protected:
  virtual ~LocalSocket();
  virtual void OnLastFileRef() OVERRIDE;

 private:
  // Very limited control message support (SCM_RIGHTS passing file descriptors).
  typedef std::deque<std::vector<int> > ControlMessageFDQueue;
  typedef std::deque<std::vector<char> > MessageQueue;

  bool CanWrite() const;
  ssize_t HandleSendmsgLocked(const struct msghdr* msg);

  int socket_type_;
  arc::CircularBuffer buffer_;
  LocalSocketType local_socket_type_;
  scoped_refptr<LocalSocket> peer_;
  MessageQueue queue_;
  ControlMessageFDQueue cmsg_fd_queue_;

  DISALLOW_COPY_AND_ASSIGN(LocalSocket);
};

}  // namespace posix_translation
#endif  // POSIX_TRANSLATION_LOCAL_SOCKET_H_
