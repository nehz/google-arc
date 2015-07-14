// Copyright (C) 2014 The Android Open Source Project
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
// Stub definitions for undefined functions.
//
// TODO(crbug.com/452355): Remove this file.
//

#define DEFINE_STUB(name)                       \
  int name() {                                  \
    print_str("*** " #name " is called ***\n"); \
    return 0;                                   \
  }

DEFINE_STUB(__bionic_clone)
DEFINE_STUB(__cxa_bad_typeid)
DEFINE_STUB(__getcpu)
DEFINE_STUB(__getpriority)
DEFINE_STUB(__reboot)
DEFINE_STUB(__rt_sigtimedwait)
DEFINE_STUB(__sched_getaffinity)
DEFINE_STUB(__setuid)
DEFINE_STUB(__timer_create)
DEFINE_STUB(__timer_delete)
DEFINE_STUB(__timer_getoverrun)
DEFINE_STUB(__timer_gettime)
DEFINE_STUB(__timer_settime)
DEFINE_STUB(__waitid)
// TODO(yusukes): L's Bionic does not export 'futex' symbol.
DEFINE_STUB(futex)
DEFINE_STUB(futimes)
DEFINE_STUB(getxattr)
DEFINE_STUB(mknod)
DEFINE_STUB(pipe2)
DEFINE_STUB(setresuid)
DEFINE_STUB(setreuid)
DEFINE_STUB(signalfd4)
DEFINE_STUB(times)
DEFINE_STUB(utimensat)
DEFINE_STUB(wait4)

// TODO(crbug.com/414583): L-rebase: Temporarily missing symbols, reenable.
// TODO(crbug.com/449063): L-rebase: Add __wrap_* for some of them.
#if defined(__arm__)
DEFINE_STUB(__arm_fadvise64_64)
#endif
DEFINE_STUB(__accept4)
DEFINE_STUB(__connect)
DEFINE_STUB(__epoll_pwait)
DEFINE_STUB(__fadvise64)
DEFINE_STUB(__rt_sigsuspend)
DEFINE_STUB(__signalfd4)
DEFINE_STUB(__socket)
DEFINE_STUB(accept4)
DEFINE_STUB(dup3)
DEFINE_STUB(epoll_create1)
DEFINE_STUB(faccessat)
DEFINE_STUB(fgetxattr)
DEFINE_STUB(flistxattr)
DEFINE_STUB(fremovexattr)
DEFINE_STUB(fsetxattr)
DEFINE_STUB(fstatat64)
DEFINE_STUB(getsid)
DEFINE_STUB(inotify_init1)
DEFINE_STUB(lgetxattr)
DEFINE_STUB(linkat)
DEFINE_STUB(listxattr)
DEFINE_STUB(llistxattr)
DEFINE_STUB(lremovexattr)
DEFINE_STUB(lsetxattr)
DEFINE_STUB(mknodat)
DEFINE_STUB(ppoll)
DEFINE_STUB(pselect)
DEFINE_STUB(readahead)
DEFINE_STUB(readlinkat)
DEFINE_STUB(recvmmsg)
DEFINE_STUB(removexattr)
DEFINE_STUB(sched_setaffinity)
DEFINE_STUB(sendfile64)
DEFINE_STUB(sendmmsg)
DEFINE_STUB(setfsgid)
DEFINE_STUB(setfsuid)
DEFINE_STUB(setns)
DEFINE_STUB(setxattr)
DEFINE_STUB(splice)
DEFINE_STUB(swapoff)
DEFINE_STUB(swapon)
DEFINE_STUB(symlinkat)
DEFINE_STUB(tee)
DEFINE_STUB(timerfd_create)
DEFINE_STUB(timerfd_gettime)
DEFINE_STUB(timerfd_settime)
DEFINE_STUB(vmsplice)
