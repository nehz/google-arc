// Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef POSIX_TRANSLATION_LOCAL_SOCKET_H_
#define POSIX_TRANSLATION_LOCAL_SOCKET_H_

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>

#include <deque>
#include <string>
#include <vector>

#include "base/basictypes.h"
#include "base/compiler_specific.h"
#include "common/circular_buffer.h"
#include "posix_translation/socket_stream.h"

namespace posix_translation {

// These are socket(AF_UNIX,...), socketpair(), or pipe() SocketStreams.  Note
// that pipes are not truly sockets, but we implement them with a common class.
// The socket may be not-yet-connected, connected, or no-longer-connected.
// Remember that SocketStreams can be SOCK_STREAM or SOCK_DGRAM type.
// TODO(crbug.com/447833): Split pipe and socket implementations.
class LocalSocket : public SocketStream {
 public:
  enum StreamDir {
    READ_ONLY,
    WRITE_ONLY,
    READ_WRITE
  };

  enum ConnectState {
    SOCKET_NEW,
    SOCKET_CONNECTING,
    SOCKET_CONNECTED,
    SOCKET_LISTENING,
    SOCKET_ERROR,
  };

  LocalSocket(int oflag, int socket_type, StreamDir stream_dir);

  bool is_block() { return !(oflag() & O_NONBLOCK); }

  void set_peer(scoped_refptr<LocalSocket> peer);

  // LocalSocket can work on main thread because it does not use Pepper file IO
  // for its implementation.
  virtual bool IsAllowedOnMainThread() const OVERRIDE;

  virtual int accept(sockaddr* addr, socklen_t* addrlen) OVERRIDE;
  virtual int bind(const sockaddr* addr, socklen_t addrlen) OVERRIDE;
  virtual int connect(const sockaddr* addr, socklen_t addrlen) OVERRIDE;
  virtual int listen(int backlog) OVERRIDE;
  virtual int getsockopt(int level, int optname, void* optval,
                         socklen_t* optlen) OVERRIDE;

  virtual off64_t lseek(off64_t offset, int whence) OVERRIDE;
  virtual ssize_t read(void* buf, size_t count) OVERRIDE;
  virtual ssize_t recv(void* buf, size_t len, int flags) OVERRIDE;
  virtual ssize_t recvfrom(void* buf, size_t len, int flags, sockaddr* addr,
                           socklen_t* addrlen) OVERRIDE;
  virtual int recvmsg(struct msghdr* msg, int flags) OVERRIDE;
  virtual ssize_t send(const void* buf, size_t len, int flags) OVERRIDE;
  virtual ssize_t sendto(const void* buf, size_t len, int flags,
                         const sockaddr* dest_addr, socklen_t addrlen) OVERRIDE;
  virtual int sendmsg(const struct msghdr* msg, int flags) OVERRIDE;
  virtual ssize_t write(const void* buf, size_t count) OVERRIDE;

  virtual int ioctl(int request, va_list ap) OVERRIDE;

  virtual bool IsSelectReadReady() const OVERRIDE;
  virtual bool IsSelectWriteReady() const OVERRIDE;
  virtual bool IsSelectExceptionReady() const OVERRIDE;
  virtual int16_t GetPollEvents() const OVERRIDE;

  virtual const char* GetStreamType() const OVERRIDE;

  virtual std::string GetBoundAbstractName() const {
    return abstract_name_;
  }

 protected:
  virtual ~LocalSocket();
  virtual void OnLastFileRef() OVERRIDE;
  bool ConvertSockaddrToAbstractName(const sockaddr* addr,
                                     socklen_t addrlen,
                                     std::string* out_name);

 private:
  // Very limited control message support (SCM_RIGHTS passing file descriptors).
  typedef std::deque<std::vector<int> > ControlMessageFDQueue;
  typedef std::deque<std::vector<char> > MessageQueue;

  bool CanWrite() const;
  int HandleSendmsgLocked(const struct msghdr* msg);
  bool HandleConnectLocked(LocalSocket* listening);
  void WaitForLocalSocketConnect();
  void WaitForOpenedConnectToAccept();

  // SOCK_STREAM, SOCK_DGRAM, etc.
  int socket_type_;

  // Local socket's connectedness state.  For socketpair and pipe LocalSockets
  // it will always be connected.
  ConnectState connect_state_;

  // All true sockets are bi-directional (READ_WRITE), but this class also
  // implements pipes which will set this to READ_ONLY or WRITE_ONLY according
  // to which stream this is.
  StreamDir stream_dir_;

  // Only valid for listening sockets.  Reference to LocalSocket's with
  // pending connects() to this listening socket, with a maximum length of
  // connection_backlog_, as provided to the listen() call.
  std::deque<scoped_refptr<LocalSocket> > connection_queue_;
  size_t connection_backlog_;

  arc::CircularBuffer buffer_;
  scoped_refptr<LocalSocket> peer_;
  MessageQueue queue_;
  ControlMessageFDQueue cmsg_fd_queue_;
  std::string abstract_name_;
  // Credentials of creator if this socket.
  ucred my_cred_;
  // Credentials of peer this socket is currently (or was previously)
  // connected to.
  ucred peer_cred_;

  DISALLOW_COPY_AND_ASSIGN(LocalSocket);
};

}  // namespace posix_translation
#endif  // POSIX_TRANSLATION_LOCAL_SOCKET_H_
