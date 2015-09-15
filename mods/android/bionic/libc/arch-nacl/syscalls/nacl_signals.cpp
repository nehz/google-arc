/*
 * Copyright (C) 2015 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License
 */

#include <irt_syscalls.h>
#include <nacl_timespec.h>
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>

#include "common/alog.h"
#include "irt.h"
#include "nacl_signals.h"
#include "private/bionic_tls.h"
#include "private/kernel_sigset_t.h"
#include "private/libc_logging.h"

extern "C" {

__LIBC_HIDDEN__ int __nacl_signal_action(
    int bionic_signum, const struct sigaction* bionic_new_action,
    struct sigaction* bionic_old_action, size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_mask(int how, const kernel_sigset_t* set,
                                       kernel_sigset_t* oldset, size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_pending(kernel_sigset_t* set, size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_suspend(const kernel_sigset_t* set,
                                          size_t sigsize);

__LIBC_HIDDEN__ int __nacl_signal_timedwait(const kernel_sigset_t* set,
                                            siginfo_t* info,
                                            const struct timespec* timeout,
                                            size_t sigsetsize);

#if !defined(__LP64__)
// Compatibility function for non-LP64 sigaction.
// All ARC targets are non-LP64 (so the above #if is a no-op), but this function
// is only defined/used when __LP64__ is not #defined, so using the same
// conditional compilation here for consistency.
int __sigaction(int bionic_signum, const struct sigaction* bionic_new_action,
                struct sigaction* bionic_old_action) {
  return __nacl_signal_action(bionic_signum, bionic_new_action,
                              bionic_old_action,
                              // Android's 32-bit ABI is broken. sigaction(),
                              // the only caller of this function, uses sigset_t
                              // instead of kernel_sigset_t since there is no
                              // version of struct sigaction that uses 64 bits
                              // for the sigset.
                              // See android/bionic/libc/bionic/sigaction.cpp.
                              sizeof(sigset_t));
}
#endif

__strong_alias(__rt_sigaction, __nacl_signal_action);
__strong_alias(__rt_sigpending, __nacl_signal_pending);
__strong_alias(__rt_sigprocmask, __nacl_signal_mask);
__strong_alias(__rt_sigsuspend, __nacl_signal_suspend);
__strong_alias(__rt_sigtimedwait, __nacl_signal_timedwait);
__strong_alias(tkill, __nacl_signal_send);

}

#if !defined(BARE_METAL_BIONIC)

int __nacl_signal_action(int bionic_signum,
                         const struct sigaction* bionic_new_action,
                         struct sigaction* bionic_old_action, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_mask(int how, const kernel_sigset_t* set,
                       kernel_sigset_t* oldset, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_pending(kernel_sigset_t* set, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_send(int tid, int bionic_signum) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_suspend(const kernel_sigset_t* set, size_t sigsize) {
  errno = ENOSYS;
  return -1;
}

int __nacl_signal_timedwait(const kernel_sigset_t* set, siginfo_t* info,
                            const struct timespec* timeout,
                            size_t sigsetsize) {
  errno = ENOSYS;
  return -1;
}

#else

namespace {

// The representation of the per-thread async-signal state. This structure
// contains both the blocked signal and the pending signal masks. We are limited
// to just 16 distinct signals since this structure needs to be exactly 32 bits
// for it to work correctly with atomics in both x86_32 and ARM. This means that
// the Linux/Bionic signal numbers need to be mapped to NaCl signal numbers. Any
// signal number not in the map will be ignored.
typedef union {
  volatile int32_t state;
  struct {
    uint16_t signal_mask;
    uint16_t pending_mask;
  };
} signal_state_t;
static_assert(sizeof(signal_state_t) == sizeof(signal_state_t::state),
              "signal_state_t does not fit on an int32_t.");

// Per-signal global async-signal action structure. Once again, we are
// constrained in size to be able to modify this structure using atomics to
// avoid having to resort to async-signal-unsafe mutexes.
typedef union {
  volatile uint64_t value;
  struct {
    __sighandler_t handler;
    uint16_t flags;
    uint16_t mask;
  };
} signal_action_t;
static_assert(sizeof(signal_action_t) == sizeof(signal_action_t::value),
              "signal_action_t does not fit on an int64_t.");

// This is the list of Bionic signal numbers that NaCl recognizes. The index of
// each signal number into this list is the NaCl signal number. That means that,
// unlike in Linux, 0 is a valid NaCl signal number.
constexpr int g_signal_mapping[] = {
  SIGQUIT,  // Used in ART to dump stack traces.
  SIGILL,   // Used in mono.
  SIGTRAP,  // Used in the debugger.
  SIGABRT,  // Used in tests, ART and bionic.
  SIGBUS,   // Used in mono.
  SIGFPE,   // Used in mono.
  SIGKILL,  // Used commonly.
  SIGUSR1,  // Used in tests and in ART to force garbage collection.
  SIGSEGV,  // Used in tests.
  SIGALRM,  // Used in tests.
  SIGCONT,  // Also used in the debugger.
  SIGSTOP,  // Also used in the debugger.
  SIGXCPU,  // Used in ligbc.
  SIGPWR,   // Used in libgc.
  (__SIGRTMIN + 0)  // Used in mono and in posix_timers.cpp.
};
constexpr uint32_t kNaclNumSignals = (sizeof(g_signal_mapping) /
                                      sizeof(g_signal_mapping[0]));
static_assert(kNaclNumSignals <= 8 * sizeof(signal_state_t::signal_mask),
              "Amount of signals exceeds available signals");

// Since the size of the field to store flags is only 16 bits (as opposed to
// Linux where it is an int), we also need to redefine the flags.
#define NACL_SIGINFO 1u
#define NACL_NODEFER 2u
#define NACL_ONSTACK 4u

// Constants to be able to process these two signal numbers which are not
// blockable and will always cause process termination.
#define NACL_SIGKILL 6
static_assert(g_signal_mapping[NACL_SIGKILL] == SIGKILL,
              "NACL_SIGKILL does not correspond to SIGKILL");
#define NACL_SIGSTOP 11
static_assert(g_signal_mapping[NACL_SIGSTOP] == SIGSTOP,
              "NACL_SIGSTOP does not correspond to SIGSTOP");

// nacl_irt_tid_t is supposed to be an opaque structure, but we rely on the fact
// that it is equal to the Linux tid of the thread.
#define MAX_THREAD_ID ((1 << 16) - 1)

// Global live thread map.
template<size_t length>
class AtomicBitset {
 public:
  AtomicBitset() {
    // Thread 1 is always considered to be alive.
    set(1, true);
  }

  bool get(size_t index) const {
    size_t mask = get_mask(index);
    index = get_index(index);
    uint32_t value = __atomic_load_n(&data_[index], __ATOMIC_ACQUIRE);
    return (value & mask) != 0;
  }

  void set(size_t index, bool value) {
    size_t mask = get_mask(index);
    index = get_index(index);
    if (value)
      __atomic_or_fetch(&data_[index], mask, __ATOMIC_ACQ_REL);
    else
      __atomic_and_fetch(&data_[index], ~mask, __ATOMIC_ACQ_REL);
  }

 private:
  size_t get_mask(size_t index) const {
    return 1U << (index & 0x3F);
  }

  size_t get_index(size_t index) const {
    return index >> 5;
  }

  // Round the number of uint32_t up.
  static constexpr uint32_t size_ = (length + (length % 4)) >> 5;
  volatile uint32_t data_[size_];
};

AtomicBitset<MAX_THREAD_ID + 1> g_live_threads;

// Global per-thread signal state.
signal_state_t g_threads[MAX_THREAD_ID + 1] = {};

// Global per-signal actions.
signal_action_t g_signal_actions[kNaclNumSignals] = {};

// Utility functions to convert between NaCl and Bionic async-signal-related
// structures.
int nacl_signum_to_bionic(int nacl_signum) {
  if (nacl_signum < 0 || nacl_signum >= kNaclNumSignals)
    return -1;
  return g_signal_mapping[nacl_signum];
}

int bionic_signum_to_nacl(int bionic_signum) {
  for (uint32_t nacl_signum = 0; nacl_signum < kNaclNumSignals;
       nacl_signum++) {
    if (bionic_signum == g_signal_mapping[nacl_signum])
      return nacl_signum;
  }
  return -1;
}

void bionic_to_nacl_mask(const uint32_t bionic_set[],
                         uint16_t* nacl_mask, size_t sigsize) {

  *nacl_mask = 0;
  for (int bionic_signum = 0; bionic_signum < 8 * sigsize; bionic_signum++) {
    if (bionic_set[bionic_signum >> 5] & (1u << (bionic_signum & 0x1F))) {
      int nacl_signum = bionic_signum_to_nacl(bionic_signum + 1);
      if (nacl_signum != -1)
      *nacl_mask |= (1u << nacl_signum);
    }
  }
}

void bionic_sigset_to_nacl_mask(const sigset_t* bionic_set,
                                uint16_t* nacl_mask) {
  bionic_to_nacl_mask(reinterpret_cast<const uint32_t*>(bionic_set),
                       nacl_mask, sizeof(sigset_t));
}

void bionic_kernel_sigset_to_nacl_mask(const kernel_sigset_t* bionic_set,
                                       uint16_t* nacl_mask) {
  bionic_to_nacl_mask(bionic_set->kernel,
                      nacl_mask, sizeof(kernel_sigset_t));
}

void nacl_mask_to_bionic(const uint16_t* nacl_mask,
                         uint32_t bionic_set[], size_t sigsize) {
  memset(bionic_set, 0, sigsize);
  for (int nacl_signum = 0; nacl_signum < kNaclNumSignals; nacl_signum++) {
    if (*nacl_mask & (1u << nacl_signum)) {
      int bionic_signum = nacl_signum_to_bionic(nacl_signum) - 1;
      if (nacl_signum != -1 && bionic_signum < 8 * sigsize)
        bionic_set[bionic_signum >> 5] |= (1u << (bionic_signum & 0x1F));
    }
  }
}

void nacl_mask_to_bionic_sigset(const uint16_t* nacl_mask,
                                sigset_t* bionic_set) {
  nacl_mask_to_bionic(nacl_mask, reinterpret_cast<uint32_t*>(bionic_set),
                      sizeof(sigset_t));
}

void nacl_mask_to_bionic_kernel_sigset(const uint16_t* nacl_mask,
                                       kernel_sigset_t* bionic_set) {
  nacl_mask_to_bionic(nacl_mask, bionic_set->kernel, sizeof(kernel_sigset_t));
}

void sigaction_to_signal_action(const struct sigaction* sigaction,
                                signal_action_t* action) {
  action->handler = sigaction->sa_handler;
  action->flags = 0;
  if (sigaction->sa_flags & SA_SIGINFO)
    action->flags |= NACL_SIGINFO;
  if (sigaction->sa_flags & SA_NODEFER)
    action->flags |= NACL_NODEFER;
  if (sigaction->sa_flags & SA_ONSTACK)
    action->flags |= NACL_ONSTACK;
  bionic_sigset_to_nacl_mask(&sigaction->sa_mask, &action->mask);
}

void signal_action_to_sigaction(const signal_action_t* action,
                                struct sigaction* sigaction) {
  sigaction->sa_handler = action->handler;
  sigaction->sa_flags = 0;
  if (action->flags & NACL_SIGINFO)
    sigaction->sa_flags |= SA_SIGINFO;
  if (action->flags & NACL_NODEFER)
    sigaction->sa_flags |= SA_NODEFER;
  if (action->flags & NACL_ONSTACK)
    sigaction->sa_flags |= SA_ONSTACK;
  nacl_mask_to_bionic_sigset(&action->mask, &sigaction->sa_mask);
}

// NaCl's userspace global signal handler. This is typically called on the
// delivery of a signal, but it can also be voluntarily called when manually
// requesting the delivery of a signal for the current thread instead of having
// to actually deliver it.  NaCl does not support sigaltstack anyways, so the
// effect would be indistinguishable.
void run_signal_handler(int tid, int nacl_signum) {
  signal_action_t action;

  __atomic_load(&g_signal_actions[nacl_signum].value, &action.value,
                __ATOMIC_RELAXED);

  int bionic_signum = nacl_signum_to_bionic(nacl_signum);
  if (action.handler == SIG_IGN ||
      (action.handler == SIG_DFL && bionic_signum == SIGCHLD)) {
    // Ignored signals and the default signal handler for SIGCHLD do nothing.
    return;
  }
  if (action.handler == SIG_DFL) {
    // The default signal handler for all signals (except SIGCHLD) terminates
    // the process.
    static const int kStderrFd = 2;
    char buffer[64];
    __libc_format_buffer(buffer, sizeof(buffer),
                         "Default handler for signal %x\n", bionic_signum);
    write(kStderrFd, buffer, strlen(buffer));
    _exit(-bionic_signum);
  }

  // Finally, run the handler.
  signal_state_t* thread = &g_threads[tid];
  signal_state_t old_state, new_state;
  uint32_t original_mask;
  do {
    new_state.state = old_state.state = thread->state;
    original_mask = old_state.signal_mask;
    new_state.signal_mask |= action.mask;
    if (!(action.flags & NACL_NODEFER)) {
      // NODEFER was not active, so we should also block the current signal.
      new_state.signal_mask |= (1u << nacl_signum);
    }
  } while(!__sync_bool_compare_and_swap(&thread->state, old_state.state,
                                        new_state.state));
  if (action.flags & NACL_SIGINFO) {
    siginfo_t siginfo = { 0 };
    siginfo.si_signo = bionic_signum;
    siginfo.si_code = SI_TKILL;
    ((void(*)(int, siginfo_t* , void* ))action.handler)(bionic_signum, &siginfo,
                                                        NULL);
  } else {
    ((void(*)(int))action.handler)(bionic_signum);
  }
  do {
    new_state.state = old_state.state = thread->state;
    new_state.signal_mask = original_mask;
  } while(!__sync_bool_compare_and_swap(&thread->state, old_state.state,
                                        new_state.state));
}

// The actual NaCl signal handler. This only calls run_signal_handler for every
// pending, unblocked signal this thread has.
void signal_handler(struct NaClExceptionContext* context) {
  int tid = gettid();
  signal_state_t* thread = &g_threads[tid];
  int nacl_signum = -1;
  while (true) {
    signal_state_t old_state, new_state;
    do {
      new_state.state = old_state.state = thread->state;
      // Choose only the first signal in the set.
      nacl_signum = __builtin_ffs(old_state.pending_mask &
                                  ~old_state.signal_mask) - 1;
      if (nacl_signum == -1)
        break;
      new_state.pending_mask &= ~(1u << nacl_signum);
    } while(!__sync_bool_compare_and_swap(&thread->state, old_state.state,
                                          new_state.state));
    if (nacl_signum == -1)
      break;
    run_signal_handler(tid, nacl_signum);
  }
  // Wake any thread waiting for signal delivery.
  int count = 0;
  __nacl_irt_futex_wake(&thread->state, INT32_MAX, &count);
}

}  // namespace

// This function needs to be called before any other signal-related function is
// called. This was not implemented by using a pthread_once in each
// signal-related function since it is async-signal unsafe.
void __nacl_signal_install_handler() {
  __nacl_irt_async_signal_handler(signal_handler);
}

// Initialize the thread state of a newly created thread. This function needs to
// be called before the actual thread function is called to ensure that it has
// the same signal/pending mask of the thread that created it. This is needed
// for POSIX compliance.
int __nacl_signal_thread_init(pid_t tid) {
  int ptid = gettid();
  g_threads[tid].state = g_threads[ptid].state;
  g_threads[tid].pending_mask = 0;
  g_live_threads.set(tid, true);
  return 0;
}

// Mark the thread identified by |tid| as not being alive anymore.
int __nacl_signal_thread_deinit(pid_t tid) {
  g_live_threads.set(tid, false);
  return 0;
}

// The following are implementations of the POSIX signal-related libc functions.
// The caller can pass the parameters as-is and we will handle all conversions.
// This is done to avoid adding mods in a lot of places, and we also avoid doing
// conversion work if we are not running in BMM.
int __nacl_signal_action(int bionic_signum,
                         const struct sigaction* bionic_new_action,
                         struct sigaction* bionic_old_action,
                         size_t sigsize) {
  // This is the only function that accepts both 32- and 64-bit signal sets.
  if (sizeof(kernel_sigset_t) != sigsize && sizeof(sigset_t) != sigsize) {
    errno = EINVAL;
    return -1;
  }
  int nacl_signum = bionic_signum_to_nacl(bionic_signum);
  if (bionic_signum == SIGKILL || bionic_signum == SIGSTOP ||
      nacl_signum == -1) {
    errno = EINVAL;
    return -1;
  }
  int tid = gettid();

  signal_action_t new_action, old_action;
  if (bionic_new_action != NULL) {
    sigaction_to_signal_action(bionic_new_action, &new_action);
    old_action.value = __atomic_exchange_n(&g_signal_actions[nacl_signum].value,
                                           new_action.value, __ATOMIC_RELAXED);
  } else {
    old_action.value = g_signal_actions[nacl_signum].value;
  }
  if (bionic_old_action != NULL) {
    signal_action_to_sigaction(&old_action, bionic_old_action);
  }
  errno = 0;
  return 0;
}

int __nacl_signal_send(int tid, int bionic_signum) {
  if (tid < 0 || tid > MAX_THREAD_ID) {
    errno = EINVAL;
    return -1;
  }
  if (!g_live_threads.get(tid)) {
    errno = ESRCH;
    return -1;
  }
  if (bionic_signum == 0) {
    // Signal 0 is a special case: It only checks if the thread exists.
    return 0;
  }
  int nacl_signum = bionic_signum_to_nacl(bionic_signum);
  if (nacl_signum == -1) {
    errno = EINVAL;
    return -1;
  }

  signal_state_t* thread = &g_threads[tid];
  signal_state_t old_state, new_state;
  do {
    new_state.state = old_state.state = thread->state;
    new_state.pending_mask |= (1u << nacl_signum);
  } while(!__sync_bool_compare_and_swap(&thread->state,
                                        old_state.state, new_state.state));
  if (old_state.pending_mask & (1u << nacl_signum)) {
    // Signal was already pending, nothing to do.
  } else {
    if (!(new_state.signal_mask & (1u << nacl_signum))) {
      return __nacl_irt_async_signal_send_async_signal(
          tid == 1 ? NACL_IRT_MAIN_THREAD_TID : tid);
    } else {
      int count = 0;
      __nacl_irt_futex_wake(&thread->state, INT32_MAX, &count);
    }
  }
  errno = 0;
  return 0;
}

int __nacl_signal_mask(int how, const kernel_sigset_t* set,
                       kernel_sigset_t* oldset, size_t sigsize) {
  if (sizeof(kernel_sigset_t) != sigsize) {
    errno = EINVAL;
    return -1;
  }
  int tid = gettid();
  if (set == NULL) {
    // No action needed, just return the oldset.
    if (oldset != NULL) {
      nacl_mask_to_bionic_kernel_sigset(&g_threads[tid].signal_mask, oldset);
    }
    return 0;
  }
  uint16_t nacl_mask = 0;
  bionic_kernel_sigset_to_nacl_mask(set, &nacl_mask);
  nacl_mask &= ~(NACL_SIGKILL | NACL_SIGSTOP);
  signal_state_t old_state, new_state;
  uint32_t delivered = 0;
  uint32_t pending = 0;
  do {
    new_state.state = old_state.state = g_threads[tid].state;
    switch(how) {
      case SIG_BLOCK:
        new_state.signal_mask |= nacl_mask;
        break;
      case SIG_SETMASK:
        new_state.signal_mask = nacl_mask;
        break;
      case SIG_UNBLOCK:
        new_state.signal_mask &= ~nacl_mask;
        break;
    }
    // Signals that are pending and are currently blocked but not previously.
    pending = new_state.pending_mask &
        (new_state.signal_mask & ~old_state.signal_mask);
    if (pending) {
      // We should wait until there are no pending, but deliverable signals.
      while (g_threads[tid].state == old_state.state) {
        __nacl_irt_futex_wait_abs(&g_threads[tid].state, old_state.state, NULL);
      }
      continue;
    }
    // Signals that are pending and were previously blocked but not anymore.
    delivered = new_state.pending_mask &
        (~new_state.signal_mask & old_state.signal_mask);
  } while(!__sync_bool_compare_and_swap(&g_threads[tid].state,
                                        old_state.state, new_state.state));
  if (oldset != NULL) {
    nacl_mask_to_bionic_kernel_sigset(&old_state.signal_mask, oldset);
  }
  for (int nacl_signum = 0; nacl_signum < kNaclNumSignals; nacl_signum++) {
    if (delivered & (1u << nacl_signum))
      run_signal_handler(tid, nacl_signum);
  }
  errno = 0;
  return 0;
}

int __nacl_signal_pending(kernel_sigset_t* set, size_t sigsize) {
  if (sizeof(kernel_sigset_t) != sigsize) {
    errno = EINVAL;
    return -1;
  }
  if (set == NULL) {
    errno = EFAULT;
    return -1;
  }
  int tid = gettid();
  nacl_mask_to_bionic_kernel_sigset(&g_threads[tid].pending_mask, set);
  errno = 0;
  return 0;
}

int __nacl_signal_suspend(const kernel_sigset_t* set, size_t sigsize) {
  if (sizeof(kernel_sigset_t) != sigsize) {
    errno = EINVAL;
    return -1;
  }
  if (set == NULL) {
    errno = EFAULT;
    return -1;
  }
  uint16_t nacl_mask, original_mask;
  bionic_kernel_sigset_to_nacl_mask(set, &nacl_mask);
  // We will be waiting for any signal _not_ in the input mask.
  nacl_mask = ~nacl_mask;
  nacl_mask &= ~(NACL_SIGKILL | NACL_SIGSTOP);
  int tid = gettid();
  signal_state_t old_state, new_state;

  uint32_t delivered = 0;
  do {
    do {
      new_state.state = old_state.state = g_threads[tid].state;
      delivered = old_state.pending_mask & nacl_mask;
      if (!delivered) {
        original_mask = old_state.signal_mask;
        new_state.signal_mask |= nacl_mask;
      } else {
        new_state.pending_mask &= ~delivered;
      }
    } while(!__sync_bool_compare_and_swap(&g_threads[tid].state,
                                          old_state.state, new_state.state));

    if (!delivered) {
      // There were no pending signals that needed to be delivered, so wait
      // until there is any change in the thread state. It might not be one of
      // the signals we are interested in, so we loop until we see one of those.
      __nacl_irt_futex_wait_abs(&g_threads[tid].state, new_state.state, NULL);
      // Finally restore the mask to what it was before this function was
      // called.
      do {
        new_state.state = old_state.state = g_threads[tid].state;
        new_state.signal_mask = original_mask;
      } while(!__sync_bool_compare_and_swap(&g_threads[tid].state,
                                            old_state.state, new_state.state));
    }
  } while (!delivered);

  for (int nacl_signum = 0; nacl_signum < kNaclNumSignals; nacl_signum++) {
    if (delivered & (1u << nacl_signum)) {
      run_signal_handler(tid, nacl_signum);
    }
  }

  errno = EINTR;
  return -1;
}

int __nacl_signal_timedwait(const kernel_sigset_t* set, siginfo_t* info,
                            const struct timespec* timeout,
                            size_t sigsize) {
  if (sizeof(kernel_sigset_t) != sigsize) {
    errno = EINVAL;
    return -1;
  }
  if (set == NULL) {
    errno = EFAULT;
    return -1;
  }
  uint16_t nacl_mask, original_mask;
  bionic_kernel_sigset_to_nacl_mask(set, &nacl_mask);
  int tid = gettid();
  signal_state_t old_state, new_state;

  uint32_t delivered = 0;
  struct nacl_abi_timespec abs_timeout;
  if (timeout != NULL) {
    __nacl_irt_clock_gettime(CLOCK_REALTIME, &abs_timeout);
    abs_timeout.tv_sec += timeout->tv_sec;
    abs_timeout.tv_nsec += timeout->tv_nsec;
    const int32_t kSecToNsec = 1000000000LL;
    while (abs_timeout.tv_nsec >= kSecToNsec) {
      abs_timeout.tv_sec++;
      abs_timeout.tv_nsec -= kSecToNsec;
    }
  }

  do {
    do {
      new_state.state = old_state.state = g_threads[tid].state;
      delivered = old_state.pending_mask & nacl_mask;
      if (delivered == 0) {
        // No signals delivered. Add the set of signals we are interested on to
        // the masked signals.
        original_mask = old_state.signal_mask;
        new_state.signal_mask |= nacl_mask;
      } else {
        // Preserve only the least-significant bit in the delivered mask.
        delivered &= (1u << __builtin_ctz(delivered));
        new_state.pending_mask &= ~delivered;
      }
    } while(!__sync_bool_compare_and_swap(&g_threads[tid].state,
                                          old_state.state, new_state.state));
    if (delivered == 0) {
      // No interesting signal was pending, so sleep until the state changes
      // before checking again.
      int retval = __nacl_irt_futex_wait_abs(&g_threads[tid].state,
                                             new_state.state,
                                             timeout == NULL ?  NULL :
                                             &abs_timeout);
      // After we wake up, restore the mask to its original state.
      do {
        new_state.state = old_state.state = g_threads[tid].state;
        new_state.signal_mask = original_mask;
      } while(!__sync_bool_compare_and_swap(&g_threads[tid].state,
                                            old_state.state, new_state.state));

      if (retval == ETIMEDOUT)
        break;
    }
  } while (delivered == 0);

  if (delivered == 0) {
    // The operation timed out.
    errno = EAGAIN;
    return -1;
  }

  int nacl_signum = __builtin_ctz(delivered);
  int bionic_signum = nacl_signum_to_bionic(nacl_signum);
  if (info != NULL) {
    memset(info, 0, sizeof(siginfo_t));
    info->si_signo = bionic_signum;
    info->si_code = SI_TKILL;
  }
  errno = 0;
  return bionic_signum;
}

#endif
