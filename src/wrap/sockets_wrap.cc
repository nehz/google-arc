/* Copyright 2014 The Chromium Authors. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 *
 * Simple wrappers for various socket calls.
 */

#include <errno.h>
#include <netdb.h>
#include <stdarg.h>
#include <stdio.h>
#include <sys/epoll.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>

#include "common/arc_strace.h"
#include "common/danger.h"
#include "common/plugin_handle.h"
#include "common/virtual_file_system_interface.h"
#include "wrap/file_wrap_private.h"

extern "C" {
#define wrap_accept_func __wrap_accept
#define wrap_bind_func __wrap_bind
#define wrap_connect_func __wrap_connect
#define wrap_epoll_create_func __wrap_epoll_create
#define wrap_epoll_create1_func __wrap_epoll_create1
#define wrap_epoll_ctl_func __wrap_epoll_ctl
#define wrap_epoll_pwait_func __wrap_epoll_pwait
#define wrap_epoll_wait_func __wrap_epoll_wait
#define wrap_freeaddrinfo_func __wrap_freeaddrinfo
#define wrap_gai_strerror_func __wrap_gai_strerror
#define wrap_getaddrinfo_func __wrap_getaddrinfo
#define wrap_gethostbyaddr_func __wrap_gethostbyaddr
#define wrap_gethostbyname_func __wrap_gethostbyname
#define wrap_gethostbyname_r_func __wrap_gethostbyname_r
#define wrap_gethostbyname2_func __wrap_gethostbyname2
#define wrap_getnameinfo_func __wrap_getnameinfo
#define wrap_getpeername_func __wrap_getpeername
#define wrap_getsockname_func __wrap_getsockname
#define wrap_getsockopt_func __wrap_getsockopt
#define wrap_listen_func __wrap_listen
#define wrap_pipe_func __wrap_pipe
#define wrap_pipe2_func __wrap_pipe2
#define wrap_pselect_func __wrap_pselect
#define wrap_recv_func __wrap_recv
#define wrap_recvfrom_func __wrap_recvfrom
#define wrap_recvmsg_func __wrap_recvmsg
#define wrap_select_func __wrap_select
#define wrap_send_func __wrap_send
#define wrap_sendmsg_func __wrap_sendmsg
#define wrap_sendto_func __wrap_sendto
#define wrap_setsockopt_func __wrap_setsockopt
#define wrap_shutdown_func __wrap_shutdown
#define wrap_socket_func __wrap_socket
#define wrap_socketpair_func __wrap_socketpair

int wrap_accept_func(int sockfd, struct sockaddr* addr, socklen_t* addrlen);
int wrap_bind_func(int sockfd, const struct sockaddr* addr, socklen_t addrlen);
int wrap_connect_func(int sockfd, const struct sockaddr* addr,
                      socklen_t addrlen);
int wrap_epoll_create_func(int size);
int wrap_epoll_create1_func(int flags);
int wrap_epoll_ctl_func(int epfd, int op, int fd, struct epoll_event* event);
int wrap_epoll_pwait_func(int epfd, struct epoll_event* events, int maxevents,
                          int timeout, const sigset_t* sigmask);
int wrap_epoll_wait_func(int epfd, struct epoll_event* events, int maxevents,
                         int timeout);
void wrap_freeaddrinfo_func(struct addrinfo* res);
const char* wrap_gai_strerror_func(int errcode);
int wrap_getaddrinfo_func(const char* node, const char* service,
                          const struct addrinfo* hints, struct addrinfo** res);
struct hostent* wrap_gethostbyaddr_func(
    const void* addr, socklen_t len, int type);
struct hostent* wrap_gethostbyname_func(const char* hostname);
struct hostent* wrap_gethostbyname2_func(const char* hostname, int family);
int wrap_gethostbyname_r_func(const char* hostname, struct hostent* ret,
                         char* buf, size_t buflen,
                         struct hostent** result, int* h_errnop);
int wrap_getnameinfo_func(const struct sockaddr* sa, socklen_t salen,
                          char* host, size_t hostlen,
                          char* serv, size_t servlen, int flags);
int wrap_getpeername_func(int sockfd, struct sockaddr* addr,
                          socklen_t* addrlen);
int wrap_getsockname_func(int sockfd, struct sockaddr* addr,
                          socklen_t* addrlen);
int wrap_getsockopt_func(int sockfd, int level, int optname,
                         void* optval, socklen_t* optlen);
int wrap_listen_func(int sockfd, int backlog);
int wrap_pipe_func(int pipefd[2]);
int wrap_pipe2_func(int pipefd[2], int flags);
int wrap_pselect_func(int nfds, fd_set* readfds, fd_set* writefds,
                      fd_set* exceptfds, const struct timespec* timeout,
                      const sigset_t* sigmask);
ssize_t wrap_recv_func(int sockfd, void* buf, size_t len, int flags);
ssize_t wrap_recvfrom_func(int sockfd, void* buf, size_t len, int flags,
                           struct sockaddr* src_addr, socklen_t* addrlen);
ssize_t wrap_recvmsg_func(int sockfd, struct msghdr* msg, int flags);
int wrap_select_func(int nfds, fd_set* readfds, fd_set* writefds,
                     fd_set* exceptfds, struct timeval* timeout);
ssize_t wrap_send_func(int sockfd, const void* buf, size_t len, int flags);
ssize_t wrap_sendto_func(int sockfd, const void* buf, size_t len, int flags,
                         const struct sockaddr* dest_addr, socklen_t addrlen);
ssize_t wrap_sendmsg_func(int sockfd, const struct msghdr* msg, int flags);
int wrap_setsockopt_func(int sockfd, int level, int optname,
                         const void* optval, socklen_t optlen);
int wrap_shutdown_func(int sockfd, int how);
int wrap_socket_func(int domain, int type, int protocol);
int wrap_socketpair_func(int domain, int type, int protocol, int sv[2]);
}  // extern "C"

// This file does not have special cases for LIBWRAP_FOR_TEST because our unit
// tests do not call these socket functions at all.

int wrap_accept_func(int sockfd, struct sockaddr* addr, socklen_t* addrlen) {
  ARC_STRACE_ENTER_FD("accept", "%d, %p, %p", sockfd, addr, addrlen);
  arc::PluginHandle handle;
  int fd = handle.GetVirtualFileSystem()->accept(sockfd, addr, addrlen);
  ARC_STRACE_REGISTER_FD(fd, "accept");
  ARC_STRACE_RETURN(fd);
}

int wrap_bind_func(int sockfd, const struct sockaddr* addr, socklen_t addrlen) {
  ARC_STRACE_ENTER_FD("bind", "%d, %s, %u",
                        sockfd, arc::GetSockaddrStr(addr).c_str(), addrlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->bind(sockfd, addr, addrlen);
  ARC_STRACE_RETURN(result);
}

int wrap_connect_func(int sockfd, const struct sockaddr* addr,
                      socklen_t addrlen) {
  ARC_STRACE_ENTER_FD("connect", "%d, %s, %u",
                        sockfd, arc::GetSockaddrStr(addr).c_str(), addrlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->connect(sockfd, addr, addrlen);
  ARC_STRACE_RETURN(result);
}

int wrap_epoll_create_func(int size) {
  ARC_STRACE_ENTER("epoll_create", "%d", size);
  arc::PluginHandle handle;
  int fd = handle.GetVirtualFileSystem()->epoll_create1(0);
  ARC_STRACE_REGISTER_FD(fd, "epoll");
  ARC_STRACE_RETURN(fd);
}

int wrap_epoll_create1_func(int flags) {
  ARC_STRACE_ENTER("epoll_create1", "%d", flags);
  arc::PluginHandle handle;
  int fd = handle.GetVirtualFileSystem()->epoll_create1(flags);
  ARC_STRACE_REGISTER_FD(fd, "epoll1");
  ARC_STRACE_RETURN(fd);
}

int wrap_epoll_ctl_func(int epfd, int op, int fd, struct epoll_event* event) {
  ARC_STRACE_ENTER_FD("epoll_ctl", "%d, %d, %d, %p", epfd, op, fd, event);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->epoll_ctl(epfd, op, fd, event);
  ARC_STRACE_RETURN(result);
}

int wrap_epoll_pwait_func(int epfd, struct epoll_event* events, int maxevents,
                          int timeout, const sigset_t* sigmask) {
  ARC_STRACE_ENTER_FD("epoll_pwait", "%d, %p, %d, %d, %p",
                        epfd, events, maxevents, timeout, sigmask);
  ALOG_ASSERT(false, "epoll_pwait is not supported");
  errno = ENOSYS;
  ARC_STRACE_RETURN(-1);
}

int wrap_epoll_wait_func(int epfd, struct epoll_event* events, int maxevents,
                         int timeout) {
  ARC_STRACE_ENTER_FD("epoll_wait", "%d, %p, %d, %d",
                        epfd, events, maxevents, timeout);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->epoll_wait(epfd, events,
                                                         maxevents, timeout);
  ARC_STRACE_RETURN(result);
}

void wrap_freeaddrinfo_func(struct addrinfo* res) {
  ARC_STRACE_ENTER("freeaddrinfo", "%p", res);
  arc::PluginHandle handle;
  handle.GetVirtualFileSystem()->freeaddrinfo(res);
  ARC_STRACE_RETURN_VOID();
}

int wrap_getnameinfo_func(const struct sockaddr* sa, socklen_t salen,
                          char* host, size_t hostlen,
                          char* serv, size_t servlen, int flags) {
  // TODO(igorc): Add GetNameInfoFlagStr() to src/common/arc_strace.[h,cc].
  ARC_STRACE_ENTER("getnameinfo", "%p, %d, %p, %zu, %p, %zu, %d",
                   sa, salen, host, hostlen, serv, servlen, flags);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->getnameinfo(
      sa, salen, host, hostlen, serv, servlen, flags);
  ARC_STRACE_RETURN(result);
}

int wrap_getaddrinfo_func(const char* node, const char* service,
                          const struct addrinfo* hints, struct addrinfo** res) {
  ARC_STRACE_ENTER("getaddrinfo", "\"%s\", \"%s\", %p, %p",
                     SAFE_CSTR(node), SAFE_CSTR(service), hints, res);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->getaddrinfo(
      node, service, hints, res);
  // TODO(crbug.com/241955): Show errno for EAI_SYSTEM?
  ARC_STRACE_RETURN(result);
}

const char* wrap_gai_strerror_func(int errcode) {
  // This code duplicates bionic/libc/netbsd/net/getaddrinfo.c.
  // TODO(crbug.com/356271): Use Bionic impl instead.
  static const char* const kErrorList[] = {
    "Success",
    "Address family for hostname not supported",    /* EAI_ADDRFAMILY */
    "Temporary failure in name resolution",         /* EAI_AGAIN      */
    "Invalid value for ai_flags",                   /* EAI_BADFLAGS   */
    "Non-recoverable failure in name resolution",   /* EAI_FAIL       */
    "ai_family not supported",                      /* EAI_FAMILY     */
    "Memory allocation failure",                    /* EAI_MEMORY     */
    "No address associated with hostname",          /* EAI_NODATA     */
    "hostname nor servname provided, or not known", /* EAI_NONAME     */
    "servname not supported for ai_socktype",       /* EAI_SERVICE    */
    "ai_socktype not supported",                    /* EAI_SOCKTYPE   */
    "System error returned in errno",               /* EAI_SYSTEM     */
    "Invalid value for hints",                      /* EAI_BADHINTS   */
    "Resolved protocol is unknown",                 /* EAI_PROTOCOL   */
    "Argument buffer overflow",                     /* EAI_OVERFLOW   */
    "Unknown error",                                /* EAI_MAX        */
  };

  ALOG_ASSERT((sizeof(kErrorList) / sizeof(kErrorList[0])) == (EAI_MAX + 1));

  if (errcode < 0 || errcode > EAI_MAX)
    errcode = EAI_MAX;
  return kErrorList[errcode];
}

struct hostent* wrap_gethostbyaddr_func(
    const void* addr, socklen_t len, int type) {
  // TODO(igorc): Add GetNetFamilyStr() to src/common/arc_strace.[h,cc].
  ARC_STRACE_ENTER("gethostbyaddr", "%p, %d, %d", addr, len, type);
  arc::PluginHandle handle;
  struct hostent* result = handle.GetVirtualFileSystem()->gethostbyaddr(
      addr, len, type);
  if (result == NULL) {
    ARC_STRACE_REPORT("h_errno=%d", h_errno);
  }
  ARC_STRACE_RETURN_PTR(result, false);
}

struct hostent* wrap_gethostbyname_func(const char* hostname) {
  ARC_STRACE_ENTER("gethostbyname", "\"%s\"", SAFE_CSTR(hostname));
  arc::PluginHandle handle;
  struct hostent* result = handle.GetVirtualFileSystem()->gethostbyname(
      hostname);
  if (result == NULL) {
    ARC_STRACE_REPORT("h_errno=%d", h_errno);
  }
  ARC_STRACE_RETURN_PTR(result, false);
}

int wrap_gethostbyname_r_func(const char* hostname, struct hostent* ret,
                              char* buf, size_t buflen,
                              struct hostent** result, int* h_errnop) {
  ARC_STRACE_ENTER("gethostbyname_r", "\"%s\"", SAFE_CSTR(hostname));
  arc::PluginHandle handle;
  int res = handle.GetVirtualFileSystem()
      ->gethostbyname_r(hostname, ret, buf, buflen, result, h_errnop);
  if (res != 0 && *h_errnop != 0) {
    ARC_STRACE_REPORT("h_errno=%d", *h_errnop);
  }
  ARC_STRACE_RETURN(res);
}

struct hostent* wrap_gethostbyname2_func(const char* hostname, int family) {
  ARC_STRACE_ENTER("gethostbyname2", "\"%s\" %d",
                     SAFE_CSTR(hostname), family);
  arc::PluginHandle handle;
  struct hostent* result = handle.GetVirtualFileSystem()
      ->gethostbyname2(hostname, family);
  if (result == NULL) {
    ARC_STRACE_REPORT("h_errno=%d", h_errno);
  }
  ARC_STRACE_RETURN_PTR(result, false);
}

int wrap_getpeername_func(int sockfd, struct sockaddr* addr,
                          socklen_t* addrlen) {
  ARC_STRACE_ENTER_FD("getpeername", "%d, %p, %p", sockfd, addr, addrlen);
  DANGERF("getpeername: sockfd=%d", sockfd);
  ARC_STRACE_REPORT("not implemented yet");
  errno = EBADF;
  ARC_STRACE_RETURN(-1);
}

int wrap_getsockname_func(int sockfd, struct sockaddr* addr,
                          socklen_t* addrlen) {
  ARC_STRACE_ENTER_FD("getsockname", "%d, %p, %p", sockfd, addr, addrlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->getsockname(
      sockfd, addr, addrlen);
  if (result == -1 && errno == EINVAL) {
    DANGER();
  }
  ARC_STRACE_RETURN(result);
}

int wrap_getsockopt_func(int sockfd, int level, int optname,
                         void* optval, socklen_t* optlen) {
  ARC_STRACE_ENTER_FD("getsockopt", "%d, %d, %d, %p, %p",
                        sockfd, level, optname, optval, optlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->getsockopt(
      sockfd, level, optname, optval, optlen);
  ARC_STRACE_RETURN(result);
}

int wrap_listen_func(int sockfd, int backlog) {
  ARC_STRACE_ENTER_FD("listen", "%d, %d", sockfd, backlog);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->listen(sockfd, backlog);
  ARC_STRACE_RETURN(result);
}

int wrap_pipe_func(int pipefd[2]) {
  ARC_STRACE_ENTER("pipe", "%p", pipefd);
  arc::PluginHandle handle;
  int result;
  result = handle.GetVirtualFileSystem()->pipe2(pipefd, 0);
  if (result >= 0) {
    ARC_STRACE_REGISTER_FD(pipefd[0], "pipe[0]");
    ARC_STRACE_REGISTER_FD(pipefd[1], "pipe[1]");
    ARC_STRACE_REPORT("pipe[0]=%d pipe[1]=%d", pipefd[0], pipefd[1]);
  }
  ARC_STRACE_RETURN(result);
}

int wrap_pipe2_func(int pipefd[2], int flags) {
  ARC_STRACE_ENTER("pipe2", "%p, %d", pipefd, flags);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->pipe2(pipefd, flags);
  if (result >= 0) {
    ARC_STRACE_REGISTER_FD(pipefd[0], "pipe2[0]");
    ARC_STRACE_REGISTER_FD(pipefd[1], "pipe2[1]");
    ARC_STRACE_REPORT("pipe[0]=%d pipe[1]=%d", pipefd[0], pipefd[1]);
  }
  ARC_STRACE_RETURN(result);
}

int wrap_pselect_func(int nfds, fd_set* readfds, fd_set* writefds,
                      fd_set* exceptfds, const struct timespec* timeout,
                      const sigset_t* sigmask) {
  ALOG_ASSERT(false, "pselect is not supported");
  errno = EAFNOSUPPORT;
  return -1;
}

ssize_t wrap_recv_func(int sockfd, void* buf, size_t len, int flags) {
  ARC_STRACE_ENTER_FD("recv", "%d, %p, %zu, %d", sockfd, buf, len, flags);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->recv(sockfd, buf, len, flags);
  if (result >= 0)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, result).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t wrap_recvfrom_func(int sockfd, void* buf, size_t len, int flags,
                           struct sockaddr* src_addr, socklen_t* addrlen) {
  ARC_STRACE_ENTER_FD("recvfrom", "%d, %p, %zu, %d, %p, %p",
                        sockfd, buf, len, flags, src_addr, addrlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->recvfrom(sockfd, buf, len, flags,
                                                       src_addr, addrlen);
  if (result == -1 && errno == EINVAL) {
    DANGER();
  }
  if (result >= 0)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, result).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t wrap_recvmsg_func(int sockfd, struct msghdr* msg, int flags) {
  ARC_STRACE_ENTER_FD("recvmsg", "%d, %p, %d", sockfd, msg, flags);
  arc::PluginHandle handle;
  ssize_t result = handle.GetVirtualFileSystem()->recvmsg(sockfd, msg, flags);
  ARC_STRACE_RETURN(result);
}

int wrap_select_func(int nfds, fd_set* readfds, fd_set* writefds,
                     fd_set* exceptfds, struct timeval* timeout) {
  ARC_STRACE_ENTER("select", "%d, %p, %p, %p, %p",
                     nfds, readfds, writefds, exceptfds, timeout);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->select(nfds, readfds, writefds,
                                                     exceptfds, timeout);
  ARC_STRACE_RETURN(result);
}

ssize_t wrap_send_func(int sockfd, const void* buf, size_t len, int flags) {
  ARC_STRACE_ENTER_FD("send", "%d, %p, %zu, %d", sockfd, buf, len, flags);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->send(sockfd, buf, len, flags);
  if (errno != EFAULT)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, result).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t wrap_sendto_func(int sockfd, const void* buf, size_t len, int flags,
                         const struct sockaddr* dest_addr, socklen_t addrlen) {
  ARC_STRACE_ENTER_FD("sendto", "%d, %p, %zu, %d, %s, %u",
                        sockfd, buf, len, flags,
                        arc::GetSockaddrStr(dest_addr).c_str(), addrlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->sendto(sockfd, buf, len, flags,
                                                     dest_addr, addrlen);
  if (result == -1 && errno == EINVAL) {
    DANGER();
  }
  if (errno != EFAULT)
    ARC_STRACE_REPORT("buf=%s", arc::GetRWBufStr(buf, result).c_str());
  ARC_STRACE_RETURN(result);
}

ssize_t wrap_sendmsg_func(int sockfd, const struct msghdr* msg, int flags) {
  ARC_STRACE_ENTER_FD("sendmsg", "%d, %p, %d", sockfd, msg, flags);
  arc::PluginHandle handle;
  ssize_t result = handle.GetVirtualFileSystem()->sendmsg(sockfd, msg, flags);
  ARC_STRACE_RETURN(result);
}

int wrap_setsockopt_func(int sockfd, int level, int optname,
                         const void* optval, socklen_t optlen) {
  ARC_STRACE_ENTER_FD("setsockopt", "%d, %d, %d, %p, %d",
                        sockfd, level, optname, optval, optlen);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->setsockopt(sockfd, level, optname,
                                                         optval, optlen);
  ARC_STRACE_RETURN(result);
}

int wrap_shutdown_func(int sockfd, int how) {
  ARC_STRACE_ENTER_FD("shutdown", "%d, %d", sockfd, how);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->shutdown(sockfd, how);
  ARC_STRACE_RETURN(result);
}

int wrap_socket_func(int domain, int type, int protocol) {
  ARC_STRACE_ENTER("socket", "%s, %s, %s",
                     arc::GetSocketDomainStr(domain).c_str(),
                     arc::GetSocketTypeStr(type).c_str(),
                     arc::GetSocketProtocolStr(protocol).c_str());
  arc::PluginHandle handle;
  int fd = handle.GetVirtualFileSystem()->socket(domain, type, protocol);
  ARC_STRACE_REGISTER_FD(fd, "socket");
  ARC_STRACE_RETURN(fd);
}

int wrap_socketpair_func(int domain, int type, int protocol, int sv[2]) {
  ARC_STRACE_ENTER("socketpair", "%s, %s, %s, %p",
                     arc::GetSocketDomainStr(domain).c_str(),
                     arc::GetSocketTypeStr(type).c_str(),
                     arc::GetSocketProtocolStr(protocol).c_str(),
                     sv);
  arc::PluginHandle handle;
  int result = handle.GetVirtualFileSystem()->socketpair(
      domain, type, protocol, sv);
  if (result >= 0) {
    ARC_STRACE_REGISTER_FD(sv[0], "socketpair[0]");
    ARC_STRACE_REGISTER_FD(sv[1], "socketpair[1]");
    ARC_STRACE_REPORT("sock[0]=%d sock[1]=%d", sv[0], sv[1]);
  }
  ARC_STRACE_RETURN(result);
}
