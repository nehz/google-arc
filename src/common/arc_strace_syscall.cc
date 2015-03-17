// Copyright 2015 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "common/arc_strace.h"

#include <sys/syscall.h>
#include <string>

#include "base/strings/stringprintf.h"

#define CASE_ASSIGN_ENUM_STR(enum_sym, result)  \
  case enum_sym: result = #enum_sym ; break

namespace arc {

std::string GetArmSyscallStr(int arm_sysno) {
  std::string result;
  // Based on android/bionic/libc/kernel/arch-arm/asm/unistd.h.
  switch (arm_sysno) {
    case 1: return "__NR_exit";
    case 2: return "__NR_fork";
    case 3: return "__NR_read";
    case 4: return "__NR_write";
    case 5: return "__NR_open";
    case 6: return "__NR_close";
    case 8: return "__NR_creat";
    case 9: return "__NR_link";
    case 10: return "__NR_unlink";
    case 11: return "__NR_execve";
    case 12: return "__NR_chdir";
    case 13: return "__NR_time";
    case 14: return "__NR_mknod";
    case 15: return "__NR_chmod";
    case 16: return "__NR_lchown";
    case 19: return "__NR_lseek";
    case 20: return "__NR_getpid";
    case 21: return "__NR_mount";
    case 22: return "__NR_umount";
    case 23: return "__NR_setuid";
    case 24: return "__NR_getuid";
    case 25: return "__NR_stime";
    case 26: return "__NR_ptrace";
    case 27: return "__NR_alarm";
    case 29: return "__NR_pause";
    case 30: return "__NR_utime";
    case 33: return "__NR_access";
    case 34: return "__NR_nice";
    case 36: return "__NR_sync";
    case 37: return "__NR_kill";
    case 38: return "__NR_rename";
    case 39: return "__NR_mkdir";
    case 40: return "__NR_rmdir";
    case 41: return "__NR_dup";
    case 42: return "__NR_pipe";
    case 43: return "__NR_times";
    case 45: return "__NR_brk";
    case 46: return "__NR_setgid";
    case 47: return "__NR_getgid";
    case 49: return "__NR_geteuid";
    case 50: return "__NR_getegid";
    case 51: return "__NR_acct";
    case 52: return "__NR_umount2";
    case 54: return "__NR_ioctl";
    case 55: return "__NR_fcntl";
    case 57: return "__NR_setpgid";
    case 60: return "__NR_umask";
    case 61: return "__NR_chroot";
    case 62: return "__NR_ustat";
    case 63: return "__NR_dup2";
    case 64: return "__NR_getppid";
    case 65: return "__NR_getpgrp";
    case 66: return "__NR_setsid";
    case 67: return "__NR_sigaction";
    case 70: return "__NR_setreuid";
    case 71: return "__NR_setregid";
    case 72: return "__NR_sigsuspend";
    case 73: return "__NR_sigpending";
    case 74: return "__NR_sethostname";
    case 75: return "__NR_setrlimit";
    case 76: return "__NR_getrlimit";
    case 77: return "__NR_getrusage";
    case 78: return "__NR_gettimeofday";
    case 79: return "__NR_settimeofday";
    case 80: return "__NR_getgroups";
    case 81: return "__NR_setgroups";
    case 82: return "__NR_select";
    case 83: return "__NR_symlink";
    case 85: return "__NR_readlink";
    case 86: return "__NR_uselib";
    case 87: return "__NR_swapon";
    case 88: return "__NR_reboot";
    case 89: return "__NR_readdir";
    case 90: return "__NR_mmap";
    case 91: return "__NR_munmap";
    case 92: return "__NR_truncate";
    case 93: return "__NR_ftruncate";
    case 94: return "__NR_fchmod";
    case 95: return "__NR_fchown";
    case 96: return "__NR_getpriority";
    case 97: return "__NR_setpriority";
    case 99: return "__NR_statfs";
    case 100: return "__NR_fstatfs";
    case 102: return "__NR_socketcall";
    case 103: return "__NR_syslog";
    case 104: return "__NR_setitimer";
    case 105: return "__NR_getitimer";
    case 106: return "__NR_stat";
    case 107: return "__NR_lstat";
    case 108: return "__NR_fstat";
    case 111: return "__NR_vhangup";
    case 113: return "__NR_syscall";
    case 114: return "__NR_wait4";
    case 115: return "__NR_swapoff";
    case 116: return "__NR_sysinfo";
    case 117: return "__NR_ipc";
    case 118: return "__NR_fsync";
    case 119: return "__NR_sigreturn";
    case 120: return "__NR_clone";
    case 121: return "__NR_setdomainname";
    case 122: return "__NR_uname";
    case 124: return "__NR_adjtimex";
    case 125: return "__NR_mprotect";
    case 126: return "__NR_sigprocmask";
    case 128: return "__NR_init_module";
    case 129: return "__NR_delete_module";
    case 131: return "__NR_quotactl";
    case 132: return "__NR_getpgid";
    case 133: return "__NR_fchdir";
    case 134: return "__NR_bdflush";
    case 135: return "__NR_sysfs";
    case 136: return "__NR_personality";
    case 138: return "__NR_setfsuid";
    case 139: return "__NR_setfsgid";
    case 140: return "__NR__llseek";
    case 141: return "__NR_getdents";
    case 142: return "__NR__newselect";
    case 143: return "__NR_flock";
    case 144: return "__NR_msync";
    case 145: return "__NR_readv";
    case 146: return "__NR_writev";
    case 147: return "__NR_getsid";
    case 148: return "__NR_fdatasync";
    case 149: return "__NR__sysctl";
    case 150: return "__NR_mlock";
    case 151: return "__NR_munlock";
    case 152: return "__NR_mlockall";
    case 153: return "__NR_munlockall";
    case 154: return "__NR_sched_setparam";
    case 155: return "__NR_sched_getparam";
    case 156: return "__NR_sched_setscheduler";
    case 157: return "__NR_sched_getscheduler";
    case 158: return "__NR_sched_yield";
    case 159: return "__NR_sched_get_priority_max";
    case 160: return "__NR_sched_get_priority_min";
    case 161: return "__NR_sched_rr_get_interval";
    case 162: return "__NR_nanosleep";
    case 163: return "__NR_mremap";
    case 164: return "__NR_setresuid";
    case 165: return "__NR_getresuid";
    case 168: return "__NR_poll";
    case 169: return "__NR_nfsservctl";
    case 170: return "__NR_setresgid";
    case 171: return "__NR_getresgid";
    case 172: return "__NR_prctl";
    case 173: return "__NR_rt_sigreturn";
    case 174: return "__NR_rt_sigaction";
    case 175: return "__NR_rt_sigprocmask";
    case 176: return "__NR_rt_sigpending";
    case 177: return "__NR_rt_sigtimedwait";
    case 178: return "__NR_rt_sigqueueinfo";
    case 179: return "__NR_rt_sigsuspend";
    case 180: return "__NR_pread64";
    case 181: return "__NR_pwrite64";
    case 182: return "__NR_chown";
    case 183: return "__NR_getcwd";
    case 184: return "__NR_capget";
    case 185: return "__NR_capset";
    case 186: return "__NR_sigaltstack";
    case 187: return "__NR_sendfile";
    case 190: return "__NR_vfork";
    case 191: return "__NR_ugetrlimit";
    case 192: return "__NR_mmap2";
    case 193: return "__NR_truncate64";
    case 194: return "__NR_ftruncate64";
    case 195: return "__NR_stat64";
    case 196: return "__NR_lstat64";
    case 197: return "__NR_fstat64";
    case 198: return "__NR_lchown32";
    case 199: return "__NR_getuid32";
    case 200: return "__NR_getgid32";
    case 201: return "__NR_geteuid32";
    case 202: return "__NR_getegid32";
    case 203: return "__NR_setreuid32";
    case 204: return "__NR_setregid32";
    case 205: return "__NR_getgroups32";
    case 206: return "__NR_setgroups32";
    case 207: return "__NR_fchown32";
    case 208: return "__NR_setresuid32";
    case 209: return "__NR_getresuid32";
    case 210: return "__NR_setresgid32";
    case 211: return "__NR_getresgid32";
    case 212: return "__NR_chown32";
    case 213: return "__NR_setuid32";
    case 214: return "__NR_setgid32";
    case 215: return "__NR_setfsuid32";
    case 216: return "__NR_setfsgid32";
    case 217: return "__NR_getdents64";
    case 218: return "__NR_pivot_root";
    case 219: return "__NR_mincore";
    case 220: return "__NR_madvise";
    case 221: return "__NR_fcntl64";
    case 224: return "__NR_gettid";
    case 225: return "__NR_readahead";
    case 226: return "__NR_setxattr";
    case 227: return "__NR_lsetxattr";
    case 228: return "__NR_fsetxattr";
    case 229: return "__NR_getxattr";
    case 230: return "__NR_lgetxattr";
    case 231: return "__NR_fgetxattr";
    case 232: return "__NR_listxattr";
    case 233: return "__NR_llistxattr";
    case 234: return "__NR_flistxattr";
    case 235: return "__NR_removexattr";
    case 236: return "__NR_lremovexattr";
    case 237: return "__NR_fremovexattr";
    case 238: return "__NR_tkill";
    case 239: return "__NR_sendfile64";
    case 240: return "__NR_futex";
    case 241: return "__NR_sched_setaffinity";
    case 242: return "__NR_sched_getaffinity";
    case 243: return "__NR_io_setup";
    case 244: return "__NR_io_destroy";
    case 245: return "__NR_io_getevents";
    case 246: return "__NR_io_submit";
    case 247: return "__NR_io_cancel";
    case 248: return "__NR_exit_group";
    case 249: return "__NR_lookup_dcookie";
    case 250: return "__NR_epoll_create";
    case 251: return "__NR_epoll_ctl";
    case 252: return "__NR_epoll_wait";
    case 253: return "__NR_remap_file_pages";
    case 256: return "__NR_set_tid_address";
    case 257: return "__NR_timer_create";
    case 258: return "__NR_timer_settime";
    case 259: return "__NR_timer_gettime";
    case 260: return "__NR_timer_getoverrun";
    case 261: return "__NR_timer_delete";
    case 262: return "__NR_clock_settime";
    case 263: return "__NR_clock_gettime";
    case 264: return "__NR_clock_getres";
    case 265: return "__NR_clock_nanosleep";
    case 266: return "__NR_statfs64";
    case 267: return "__NR_fstatfs64";
    case 268: return "__NR_tgkill";
    case 269: return "__NR_utimes";
    case 270: return "__NR_arm_fadvise64_64";
    case 271: return "__NR_pciconfig_iobase";
    case 272: return "__NR_pciconfig_read";
    case 273: return "__NR_pciconfig_write";
    case 274: return "__NR_mq_open";
    case 275: return "__NR_mq_unlink";
    case 276: return "__NR_mq_timedsend";
    case 277: return "__NR_mq_timedreceive";
    case 278: return "__NR_mq_notify";
    case 279: return "__NR_mq_getsetattr";
    case 280: return "__NR_waitid";
    case 281: return "__NR_socket";
    case 282: return "__NR_bind";
    case 283: return "__NR_connect";
    case 284: return "__NR_listen";
    case 285: return "__NR_accept";
    case 286: return "__NR_getsockname";
    case 287: return "__NR_getpeername";
    case 288: return "__NR_socketpair";
    case 289: return "__NR_send";
    case 290: return "__NR_sendto";
    case 291: return "__NR_recv";
    case 292: return "__NR_recvfrom";
    case 293: return "__NR_shutdown";
    case 294: return "__NR_setsockopt";
    case 295: return "__NR_getsockopt";
    case 296: return "__NR_sendmsg";
    case 297: return "__NR_recvmsg";
    case 298: return "__NR_semop";
    case 299: return "__NR_semget";
    case 300: return "__NR_semctl";
    case 301: return "__NR_msgsnd";
    case 302: return "__NR_msgrcv";
    case 303: return "__NR_msgget";
    case 304: return "__NR_msgctl";
    case 305: return "__NR_shmat";
    case 306: return "__NR_shmdt";
    case 307: return "__NR_shmget";
    case 308: return "__NR_shmctl";
    case 309: return "__NR_add_key";
    case 310: return "__NR_request_key";
    case 311: return "__NR_keyctl";
    case 312: return "__NR_semtimedop";
    case 313: return "__NR_vserver";
    case 314: return "__NR_ioprio_set";
    case 315: return "__NR_ioprio_get";
    case 316: return "__NR_inotify_init";
    case 317: return "__NR_inotify_add_watch";
    case 318: return "__NR_inotify_rm_watch";
    case 319: return "__NR_mbind";
    case 320: return "__NR_get_mempolicy";
    case 321: return "__NR_set_mempolicy";
    case 322: return "__NR_openat";
    case 323: return "__NR_mkdirat";
    case 324: return "__NR_mknodat";
    case 325: return "__NR_fchownat";
    case 326: return "__NR_futimesat";
    case 327: return "__NR_fstatat64";
    case 328: return "__NR_unlinkat";
    case 329: return "__NR_renameat";
    case 330: return "__NR_linkat";
    case 331: return "__NR_symlinkat";
    case 332: return "__NR_readlinkat";
    case 333: return "__NR_fchmodat";
    case 334: return "__NR_faccessat";
    case 335: return "__NR_pselect6";
    case 336: return "__NR_ppoll";
    case 337: return "__NR_unshare";
    case 338: return "__NR_set_robust_list";
    case 339: return "__NR_get_robust_list";
    case 340: return "__NR_splice";
    case 341: return "__NR_arm_sync_file_range";
    case 342: return "__NR_tee";
    case 343: return "__NR_vmsplice";
    case 344: return "__NR_move_pages";
    case 345: return "__NR_getcpu";
    case 346: return "__NR_epoll_pwait";
    case 347: return "__NR_kexec_load";
    case 348: return "__NR_utimensat";
    case 349: return "__NR_signalfd";
    case 350: return "__NR_timerfd_create";
    case 351: return "__NR_eventfd";
    case 352: return "__NR_fallocate";
    case 353: return "__NR_timerfd_settime";
    case 354: return "__NR_timerfd_gettime";
    case 355: return "__NR_signalfd4";
    case 356: return "__NR_eventfd2";
    case 357: return "__NR_epoll_create1";
    case 358: return "__NR_dup3";
    case 359: return "__NR_pipe2";
    case 360: return "__NR_inotify_init1";
    case 361: return "__NR_preadv";
    case 362: return "__NR_pwritev";
    case 363: return "__NR_rt_tgsigqueueinfo";
    case 364: return "__NR_perf_event_open";
    case 365: return "__NR_recvmmsg";
    case 366: return "__NR_accept4";
    case 367: return "__NR_fanotify_init";
    case 368: return "__NR_fanotify_mark";
    case 369: return "__NR_prlimit64";
    case 370: return "__NR_name_to_handle_at";
    case 371: return "__NR_open_by_handle_at";
    case 372: return "__NR_clock_adjtime";
    case 373: return "__NR_syncfs";
    case 374: return "__NR_sendmmsg";
    case 375: return "__NR_setns";
    case 376: return "__NR_process_vm_readv";
    case 377: return "__NR_process_vm_writev";
    case 0xf0001: return "__ARM_NR_breakpoint";
    case 0xf0002: return "__ARM_NR_cacheflush";
    case 0xf0003: return "__ARM_NR_usr26";
    case 0xf0004: return "__ARM_NR_usr32";
    case 0xf0005: return "__ARM_NR_set_tls";
    default:
      break;
  }
  return base::StringPrintf("%d???", arm_sysno);
}

std::string GetSyscallStr(int sysno) {
#if defined(__arm__)
  return GetArmSyscallStr(sysno);
#else
  // Based on android/bionic/libc/kernel/arch-x86/asm/unistd_32.h.
  std::string result;
  switch (sysno) {
    CASE_ASSIGN_ENUM_STR(__NR_exit, result);
    CASE_ASSIGN_ENUM_STR(__NR_fork, result);
    CASE_ASSIGN_ENUM_STR(__NR_read, result);
    CASE_ASSIGN_ENUM_STR(__NR_write, result);
    CASE_ASSIGN_ENUM_STR(__NR_open, result);
    CASE_ASSIGN_ENUM_STR(__NR_close, result);
    CASE_ASSIGN_ENUM_STR(__NR_waitpid, result);
    CASE_ASSIGN_ENUM_STR(__NR_creat, result);
    CASE_ASSIGN_ENUM_STR(__NR_link, result);
    CASE_ASSIGN_ENUM_STR(__NR_unlink, result);
    CASE_ASSIGN_ENUM_STR(__NR_execve, result);
    CASE_ASSIGN_ENUM_STR(__NR_chdir, result);
    CASE_ASSIGN_ENUM_STR(__NR_time, result);
    CASE_ASSIGN_ENUM_STR(__NR_mknod, result);
    CASE_ASSIGN_ENUM_STR(__NR_chmod, result);
    CASE_ASSIGN_ENUM_STR(__NR_lchown, result);
    CASE_ASSIGN_ENUM_STR(__NR_break, result);
    CASE_ASSIGN_ENUM_STR(__NR_oldstat, result);
    CASE_ASSIGN_ENUM_STR(__NR_lseek, result);
    CASE_ASSIGN_ENUM_STR(__NR_getpid, result);
    CASE_ASSIGN_ENUM_STR(__NR_mount, result);
    CASE_ASSIGN_ENUM_STR(__NR_umount, result);
    CASE_ASSIGN_ENUM_STR(__NR_setuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_getuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_stime, result);
    CASE_ASSIGN_ENUM_STR(__NR_ptrace, result);
    CASE_ASSIGN_ENUM_STR(__NR_alarm, result);
    CASE_ASSIGN_ENUM_STR(__NR_oldfstat, result);
    CASE_ASSIGN_ENUM_STR(__NR_pause, result);
    CASE_ASSIGN_ENUM_STR(__NR_utime, result);
    CASE_ASSIGN_ENUM_STR(__NR_stty, result);
    CASE_ASSIGN_ENUM_STR(__NR_gtty, result);
    CASE_ASSIGN_ENUM_STR(__NR_access, result);
    CASE_ASSIGN_ENUM_STR(__NR_nice, result);
    CASE_ASSIGN_ENUM_STR(__NR_ftime, result);
    CASE_ASSIGN_ENUM_STR(__NR_sync, result);
    CASE_ASSIGN_ENUM_STR(__NR_kill, result);
    CASE_ASSIGN_ENUM_STR(__NR_rename, result);
    CASE_ASSIGN_ENUM_STR(__NR_mkdir, result);
    CASE_ASSIGN_ENUM_STR(__NR_rmdir, result);
    CASE_ASSIGN_ENUM_STR(__NR_dup, result);
    CASE_ASSIGN_ENUM_STR(__NR_pipe, result);
    CASE_ASSIGN_ENUM_STR(__NR_times, result);
    CASE_ASSIGN_ENUM_STR(__NR_prof, result);
    CASE_ASSIGN_ENUM_STR(__NR_brk, result);
    CASE_ASSIGN_ENUM_STR(__NR_setgid, result);
    CASE_ASSIGN_ENUM_STR(__NR_getgid, result);
    CASE_ASSIGN_ENUM_STR(__NR_signal, result);
    CASE_ASSIGN_ENUM_STR(__NR_geteuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_getegid, result);
    CASE_ASSIGN_ENUM_STR(__NR_acct, result);
    CASE_ASSIGN_ENUM_STR(__NR_umount2, result);
    CASE_ASSIGN_ENUM_STR(__NR_lock, result);
    CASE_ASSIGN_ENUM_STR(__NR_ioctl, result);
    CASE_ASSIGN_ENUM_STR(__NR_fcntl, result);
    CASE_ASSIGN_ENUM_STR(__NR_mpx, result);
    CASE_ASSIGN_ENUM_STR(__NR_setpgid, result);
    CASE_ASSIGN_ENUM_STR(__NR_ulimit, result);
    CASE_ASSIGN_ENUM_STR(__NR_oldolduname, result);
    CASE_ASSIGN_ENUM_STR(__NR_umask, result);
    CASE_ASSIGN_ENUM_STR(__NR_chroot, result);
    CASE_ASSIGN_ENUM_STR(__NR_ustat, result);
    CASE_ASSIGN_ENUM_STR(__NR_dup2, result);
    CASE_ASSIGN_ENUM_STR(__NR_getppid, result);
    CASE_ASSIGN_ENUM_STR(__NR_getpgrp, result);
    CASE_ASSIGN_ENUM_STR(__NR_setsid, result);
    CASE_ASSIGN_ENUM_STR(__NR_sigaction, result);
    CASE_ASSIGN_ENUM_STR(__NR_sgetmask, result);
    CASE_ASSIGN_ENUM_STR(__NR_ssetmask, result);
    CASE_ASSIGN_ENUM_STR(__NR_setreuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_setregid, result);
    CASE_ASSIGN_ENUM_STR(__NR_sigsuspend, result);
    CASE_ASSIGN_ENUM_STR(__NR_sigpending, result);
    CASE_ASSIGN_ENUM_STR(__NR_sethostname, result);
    CASE_ASSIGN_ENUM_STR(__NR_setrlimit, result);
    CASE_ASSIGN_ENUM_STR(__NR_getrlimit, result);
    CASE_ASSIGN_ENUM_STR(__NR_getrusage, result);
    CASE_ASSIGN_ENUM_STR(__NR_gettimeofday, result);
    CASE_ASSIGN_ENUM_STR(__NR_settimeofday, result);
    CASE_ASSIGN_ENUM_STR(__NR_getgroups, result);
    CASE_ASSIGN_ENUM_STR(__NR_setgroups, result);
    CASE_ASSIGN_ENUM_STR(__NR_select, result);
    CASE_ASSIGN_ENUM_STR(__NR_symlink, result);
    CASE_ASSIGN_ENUM_STR(__NR_oldlstat, result);
    CASE_ASSIGN_ENUM_STR(__NR_readlink, result);
    CASE_ASSIGN_ENUM_STR(__NR_uselib, result);
    CASE_ASSIGN_ENUM_STR(__NR_swapon, result);
    CASE_ASSIGN_ENUM_STR(__NR_reboot, result);
    CASE_ASSIGN_ENUM_STR(__NR_readdir, result);
    CASE_ASSIGN_ENUM_STR(__NR_mmap, result);
    CASE_ASSIGN_ENUM_STR(__NR_munmap, result);
    CASE_ASSIGN_ENUM_STR(__NR_truncate, result);
    CASE_ASSIGN_ENUM_STR(__NR_ftruncate, result);
    CASE_ASSIGN_ENUM_STR(__NR_fchmod, result);
    CASE_ASSIGN_ENUM_STR(__NR_fchown, result);
    CASE_ASSIGN_ENUM_STR(__NR_getpriority, result);
    CASE_ASSIGN_ENUM_STR(__NR_setpriority, result);
    CASE_ASSIGN_ENUM_STR(__NR_profil, result);
    CASE_ASSIGN_ENUM_STR(__NR_statfs, result);
    CASE_ASSIGN_ENUM_STR(__NR_fstatfs, result);
    CASE_ASSIGN_ENUM_STR(__NR_ioperm, result);
    CASE_ASSIGN_ENUM_STR(__NR_socketcall, result);
    CASE_ASSIGN_ENUM_STR(__NR_syslog, result);
    CASE_ASSIGN_ENUM_STR(__NR_setitimer, result);
    CASE_ASSIGN_ENUM_STR(__NR_getitimer, result);
    CASE_ASSIGN_ENUM_STR(__NR_stat, result);
    CASE_ASSIGN_ENUM_STR(__NR_lstat, result);
    CASE_ASSIGN_ENUM_STR(__NR_fstat, result);
    CASE_ASSIGN_ENUM_STR(__NR_olduname, result);
    CASE_ASSIGN_ENUM_STR(__NR_iopl, result);
    CASE_ASSIGN_ENUM_STR(__NR_vhangup, result);
    CASE_ASSIGN_ENUM_STR(__NR_idle, result);
    CASE_ASSIGN_ENUM_STR(__NR_vm86old, result);
    CASE_ASSIGN_ENUM_STR(__NR_wait4, result);
    CASE_ASSIGN_ENUM_STR(__NR_swapoff, result);
    CASE_ASSIGN_ENUM_STR(__NR_sysinfo, result);
    CASE_ASSIGN_ENUM_STR(__NR_ipc, result);
    CASE_ASSIGN_ENUM_STR(__NR_fsync, result);
    CASE_ASSIGN_ENUM_STR(__NR_sigreturn, result);
    CASE_ASSIGN_ENUM_STR(__NR_clone, result);
    CASE_ASSIGN_ENUM_STR(__NR_setdomainname, result);
    CASE_ASSIGN_ENUM_STR(__NR_uname, result);
    CASE_ASSIGN_ENUM_STR(__NR_modify_ldt, result);
    CASE_ASSIGN_ENUM_STR(__NR_adjtimex, result);
    CASE_ASSIGN_ENUM_STR(__NR_mprotect, result);
    CASE_ASSIGN_ENUM_STR(__NR_sigprocmask, result);
    CASE_ASSIGN_ENUM_STR(__NR_create_module, result);
    CASE_ASSIGN_ENUM_STR(__NR_init_module, result);
    CASE_ASSIGN_ENUM_STR(__NR_delete_module, result);
    CASE_ASSIGN_ENUM_STR(__NR_get_kernel_syms, result);
    CASE_ASSIGN_ENUM_STR(__NR_quotactl, result);
    CASE_ASSIGN_ENUM_STR(__NR_getpgid, result);
    CASE_ASSIGN_ENUM_STR(__NR_fchdir, result);
    CASE_ASSIGN_ENUM_STR(__NR_bdflush, result);
    CASE_ASSIGN_ENUM_STR(__NR_sysfs, result);
    CASE_ASSIGN_ENUM_STR(__NR_personality, result);
    CASE_ASSIGN_ENUM_STR(__NR_afs_syscall, result);
    CASE_ASSIGN_ENUM_STR(__NR_setfsuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_setfsgid, result);
    CASE_ASSIGN_ENUM_STR(__NR__llseek, result);
    CASE_ASSIGN_ENUM_STR(__NR_getdents, result);
    CASE_ASSIGN_ENUM_STR(__NR__newselect, result);
    CASE_ASSIGN_ENUM_STR(__NR_flock, result);
    CASE_ASSIGN_ENUM_STR(__NR_msync, result);
    CASE_ASSIGN_ENUM_STR(__NR_readv, result);
    CASE_ASSIGN_ENUM_STR(__NR_writev, result);
    CASE_ASSIGN_ENUM_STR(__NR_getsid, result);
    CASE_ASSIGN_ENUM_STR(__NR_fdatasync, result);
    CASE_ASSIGN_ENUM_STR(__NR__sysctl, result);
    CASE_ASSIGN_ENUM_STR(__NR_mlock, result);
    CASE_ASSIGN_ENUM_STR(__NR_munlock, result);
    CASE_ASSIGN_ENUM_STR(__NR_mlockall, result);
    CASE_ASSIGN_ENUM_STR(__NR_munlockall, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_setparam, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_getparam, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_setscheduler, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_getscheduler, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_yield, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_get_priority_max, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_get_priority_min, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_rr_get_interval, result);
    CASE_ASSIGN_ENUM_STR(__NR_nanosleep, result);
    CASE_ASSIGN_ENUM_STR(__NR_mremap, result);
    CASE_ASSIGN_ENUM_STR(__NR_setresuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_getresuid, result);
    CASE_ASSIGN_ENUM_STR(__NR_vm86, result);
    CASE_ASSIGN_ENUM_STR(__NR_query_module, result);
    CASE_ASSIGN_ENUM_STR(__NR_poll, result);
    CASE_ASSIGN_ENUM_STR(__NR_nfsservctl, result);
    CASE_ASSIGN_ENUM_STR(__NR_setresgid, result);
    CASE_ASSIGN_ENUM_STR(__NR_getresgid, result);
    CASE_ASSIGN_ENUM_STR(__NR_prctl, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigreturn, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigaction, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigprocmask, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigpending, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigtimedwait, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigqueueinfo, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_sigsuspend, result);
    CASE_ASSIGN_ENUM_STR(__NR_pread64, result);
    CASE_ASSIGN_ENUM_STR(__NR_pwrite64, result);
    CASE_ASSIGN_ENUM_STR(__NR_chown, result);
    CASE_ASSIGN_ENUM_STR(__NR_getcwd, result);
    CASE_ASSIGN_ENUM_STR(__NR_capget, result);
    CASE_ASSIGN_ENUM_STR(__NR_capset, result);
    CASE_ASSIGN_ENUM_STR(__NR_sigaltstack, result);
    CASE_ASSIGN_ENUM_STR(__NR_sendfile, result);
    CASE_ASSIGN_ENUM_STR(__NR_getpmsg, result);
    CASE_ASSIGN_ENUM_STR(__NR_putpmsg, result);
    CASE_ASSIGN_ENUM_STR(__NR_vfork, result);
    CASE_ASSIGN_ENUM_STR(__NR_ugetrlimit, result);
    CASE_ASSIGN_ENUM_STR(__NR_mmap2, result);
    CASE_ASSIGN_ENUM_STR(__NR_truncate64, result);
    CASE_ASSIGN_ENUM_STR(__NR_ftruncate64, result);
    CASE_ASSIGN_ENUM_STR(__NR_stat64, result);
    CASE_ASSIGN_ENUM_STR(__NR_lstat64, result);
    CASE_ASSIGN_ENUM_STR(__NR_fstat64, result);
    CASE_ASSIGN_ENUM_STR(__NR_lchown32, result);
    CASE_ASSIGN_ENUM_STR(__NR_getuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_getgid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_geteuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_getegid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setreuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setregid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_getgroups32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setgroups32, result);
    CASE_ASSIGN_ENUM_STR(__NR_fchown32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setresuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_getresuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setresgid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_getresgid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_chown32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setgid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setfsuid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_setfsgid32, result);
    CASE_ASSIGN_ENUM_STR(__NR_pivot_root, result);
    CASE_ASSIGN_ENUM_STR(__NR_mincore, result);
    CASE_ASSIGN_ENUM_STR(__NR_madvise, result);  // and madvise1
    CASE_ASSIGN_ENUM_STR(__NR_getdents64, result);
    CASE_ASSIGN_ENUM_STR(__NR_fcntl64, result);
    CASE_ASSIGN_ENUM_STR(__NR_gettid, result);
    CASE_ASSIGN_ENUM_STR(__NR_readahead, result);
    CASE_ASSIGN_ENUM_STR(__NR_setxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_lsetxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_fsetxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_getxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_lgetxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_fgetxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_listxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_llistxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_flistxattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_removexattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_lremovexattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_fremovexattr, result);
    CASE_ASSIGN_ENUM_STR(__NR_tkill, result);
    CASE_ASSIGN_ENUM_STR(__NR_sendfile64, result);
    CASE_ASSIGN_ENUM_STR(__NR_futex, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_setaffinity, result);
    CASE_ASSIGN_ENUM_STR(__NR_sched_getaffinity, result);
    CASE_ASSIGN_ENUM_STR(__NR_set_thread_area, result);
    CASE_ASSIGN_ENUM_STR(__NR_get_thread_area, result);
    CASE_ASSIGN_ENUM_STR(__NR_io_setup, result);
    CASE_ASSIGN_ENUM_STR(__NR_io_destroy, result);
    CASE_ASSIGN_ENUM_STR(__NR_io_getevents, result);
    CASE_ASSIGN_ENUM_STR(__NR_io_submit, result);
    CASE_ASSIGN_ENUM_STR(__NR_io_cancel, result);
    CASE_ASSIGN_ENUM_STR(__NR_fadvise64, result);
    CASE_ASSIGN_ENUM_STR(__NR_exit_group, result);
    CASE_ASSIGN_ENUM_STR(__NR_lookup_dcookie, result);
    CASE_ASSIGN_ENUM_STR(__NR_epoll_create, result);
    CASE_ASSIGN_ENUM_STR(__NR_epoll_ctl, result);
    CASE_ASSIGN_ENUM_STR(__NR_epoll_wait, result);
    CASE_ASSIGN_ENUM_STR(__NR_remap_file_pages, result);
    CASE_ASSIGN_ENUM_STR(__NR_set_tid_address, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 1, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 2, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 3, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 4, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 5, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 6, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 7, result);
    CASE_ASSIGN_ENUM_STR(__NR_timer_create + 8, result);
    CASE_ASSIGN_ENUM_STR(__NR_statfs64, result);
    CASE_ASSIGN_ENUM_STR(__NR_fstatfs64, result);
    CASE_ASSIGN_ENUM_STR(__NR_tgkill, result);
    CASE_ASSIGN_ENUM_STR(__NR_utimes, result);
    CASE_ASSIGN_ENUM_STR(__NR_fadvise64_64, result);
    CASE_ASSIGN_ENUM_STR(__NR_vserver, result);
    CASE_ASSIGN_ENUM_STR(__NR_mbind, result);
    CASE_ASSIGN_ENUM_STR(__NR_get_mempolicy, result);
    CASE_ASSIGN_ENUM_STR(__NR_set_mempolicy, result);
    CASE_ASSIGN_ENUM_STR(__NR_mq_open, result);
    CASE_ASSIGN_ENUM_STR(__NR_mq_open + 1, result);
    CASE_ASSIGN_ENUM_STR(__NR_mq_open + 2, result);
    CASE_ASSIGN_ENUM_STR(__NR_mq_open + 3, result);
    CASE_ASSIGN_ENUM_STR(__NR_mq_open + 4, result);
    CASE_ASSIGN_ENUM_STR(__NR_mq_open + 5, result);
    CASE_ASSIGN_ENUM_STR(__NR_kexec_load, result);
    CASE_ASSIGN_ENUM_STR(__NR_waitid, result);
    CASE_ASSIGN_ENUM_STR(__NR_add_key, result);
    CASE_ASSIGN_ENUM_STR(__NR_request_key, result);
    CASE_ASSIGN_ENUM_STR(__NR_keyctl, result);
    CASE_ASSIGN_ENUM_STR(__NR_ioprio_set, result);
    CASE_ASSIGN_ENUM_STR(__NR_ioprio_get, result);
    CASE_ASSIGN_ENUM_STR(__NR_inotify_init, result);
    CASE_ASSIGN_ENUM_STR(__NR_inotify_add_watch, result);
    CASE_ASSIGN_ENUM_STR(__NR_inotify_rm_watch, result);
    CASE_ASSIGN_ENUM_STR(__NR_migrate_pages, result);
    CASE_ASSIGN_ENUM_STR(__NR_openat, result);
    CASE_ASSIGN_ENUM_STR(__NR_mkdirat, result);
    CASE_ASSIGN_ENUM_STR(__NR_mknodat, result);
    CASE_ASSIGN_ENUM_STR(__NR_fchownat, result);
    CASE_ASSIGN_ENUM_STR(__NR_futimesat, result);
    CASE_ASSIGN_ENUM_STR(__NR_fstatat64, result);
    CASE_ASSIGN_ENUM_STR(__NR_unlinkat, result);
    CASE_ASSIGN_ENUM_STR(__NR_renameat, result);
    CASE_ASSIGN_ENUM_STR(__NR_linkat, result);
    CASE_ASSIGN_ENUM_STR(__NR_symlinkat, result);
    CASE_ASSIGN_ENUM_STR(__NR_readlinkat, result);
    CASE_ASSIGN_ENUM_STR(__NR_fchmodat, result);
    CASE_ASSIGN_ENUM_STR(__NR_faccessat, result);
    CASE_ASSIGN_ENUM_STR(__NR_pselect6, result);
    CASE_ASSIGN_ENUM_STR(__NR_ppoll, result);
    CASE_ASSIGN_ENUM_STR(__NR_unshare, result);
    CASE_ASSIGN_ENUM_STR(__NR_set_robust_list, result);
    CASE_ASSIGN_ENUM_STR(__NR_get_robust_list, result);
    CASE_ASSIGN_ENUM_STR(__NR_splice, result);
    CASE_ASSIGN_ENUM_STR(__NR_sync_file_range, result);
    CASE_ASSIGN_ENUM_STR(__NR_tee, result);
    CASE_ASSIGN_ENUM_STR(__NR_vmsplice, result);
    CASE_ASSIGN_ENUM_STR(__NR_move_pages, result);
    CASE_ASSIGN_ENUM_STR(__NR_getcpu, result);
    CASE_ASSIGN_ENUM_STR(__NR_epoll_pwait, result);
    CASE_ASSIGN_ENUM_STR(__NR_utimensat, result);
    CASE_ASSIGN_ENUM_STR(__NR_signalfd, result);
    CASE_ASSIGN_ENUM_STR(__NR_timerfd_create, result);
    CASE_ASSIGN_ENUM_STR(__NR_eventfd, result);
    CASE_ASSIGN_ENUM_STR(__NR_fallocate, result);
    CASE_ASSIGN_ENUM_STR(__NR_timerfd_settime, result);
    CASE_ASSIGN_ENUM_STR(__NR_timerfd_gettime, result);
    CASE_ASSIGN_ENUM_STR(__NR_signalfd4, result);
    CASE_ASSIGN_ENUM_STR(__NR_eventfd2, result);
    CASE_ASSIGN_ENUM_STR(__NR_epoll_create1, result);
    CASE_ASSIGN_ENUM_STR(__NR_dup3, result);
    CASE_ASSIGN_ENUM_STR(__NR_pipe2, result);
    CASE_ASSIGN_ENUM_STR(__NR_inotify_init1, result);
    CASE_ASSIGN_ENUM_STR(__NR_preadv, result);
    CASE_ASSIGN_ENUM_STR(__NR_pwritev, result);
    CASE_ASSIGN_ENUM_STR(__NR_rt_tgsigqueueinfo, result);
    CASE_ASSIGN_ENUM_STR(__NR_perf_event_open, result);
    CASE_ASSIGN_ENUM_STR(__NR_recvmmsg, result);
    CASE_ASSIGN_ENUM_STR(__NR_fanotify_init, result);
    CASE_ASSIGN_ENUM_STR(__NR_fanotify_mark, result);
    CASE_ASSIGN_ENUM_STR(__NR_prlimit64, result);
    CASE_ASSIGN_ENUM_STR(__NR_name_to_handle_at, result);
    CASE_ASSIGN_ENUM_STR(__NR_open_by_handle_at, result);
    CASE_ASSIGN_ENUM_STR(__NR_clock_adjtime, result);
    CASE_ASSIGN_ENUM_STR(__NR_syncfs, result);
    CASE_ASSIGN_ENUM_STR(__NR_sendmmsg, result);
    CASE_ASSIGN_ENUM_STR(__NR_setns, result);
    default:
      result = base::StringPrintf("%d???", sysno);
      break;
  }
  return result;
#endif
}

}  // namespace arc
