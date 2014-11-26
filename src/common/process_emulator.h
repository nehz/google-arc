// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// PID and thread management functions.

#ifndef COMMON_PROCESS_EMULATOR_H_
#define COMMON_PROCESS_EMULATOR_H_

#include <sys/types.h>
#include <unistd.h>

#include <map>
#include <string>

#include "common/private/minimal_base.h"

template <typename T> struct DefaultSingletonTraits;

// Only for testing.
namespace posix_translation {
class ProcfsHandlerTest;
class ScopedUidSetter;
}

namespace arc {

const pid_t kInitPid = 1;
const uid_t kRootUid = 0;
const uid_t kSystemUid = 1000;  // == Process.SYSTEM_UID
const uid_t kFirstAppUid = 10000;  // == Process.FIRST_APPLICATION_UID
const gid_t kRootGid = 0;

// Returns true if |uid| is an app UID.
bool IsAppUid(uid_t uid);

struct EmulatedProcessInfo {
  EmulatedProcessInfo(pid_t p, uid_t u)
      : pid(p), uid(u) {}

  pid_t pid;
  uid_t uid;
};

// This is a singleton class that emulates threads within
// the same process belonging to different processes and having
// potentially different uids.  It causes getpid() and getuid() to
// return emulated values.  SetFirstEmulatedProcessThread must be called on a
// thread which is not yet being emulated, and then it and all of the
// threads created from it will belong to the same emulated process.
class ProcessEmulator {
 public:
  typedef int TransactionNumber;
  enum {
    kInvalidTransactionNumber = -1,
    kInitialTransactionNumber = 0
  };

  // Returns singleton instance.
  static ProcessEmulator* GetInstance();

  // Returns true if pthread_create has already been called.
  static bool IsMultiThreaded();

  // Updates the given transaction number (number of mutations to the process
  // emulation state) if it does not match the current number and returns true
  // if so.
  bool UpdateTransactionNumberIfChanged(TransactionNumber* last_number);

  // Generates new PID and assigns it to the current thread along with
  // the provided user id.  Current thread must not already belong to
  // an emulated process.
  void SetFirstEmulatedProcessThread(uid_t uid);

  // Ensures that next thread creation will use new PID and the provided UID.
  // Returns the new PID.
  pid_t PrepareNewEmulatedProcess(uid_t uid);

  // Returns PID. Unlike ::getpid() in libc, this functions does not
  // output to arc_strace.
  static pid_t GetPid();

  // Returns UID. Unlike ::getuid() in libc, this functions does not
  // output to arc_strace and is supposed to be used from inside
  // arc_strace.
  static uid_t GetUid();

  // Intercepts all pthread_create() calls and set up emulated uid and pid
  // values of the created thread.
  static void UpdateAndAllocatePthreadCreateArgsIfNewEmulatedProcess(
      void* (**start_routine)(void*),  // NOLINT(readability/casting)
      void** arg);

  // "Enter" function is called before any invocation of a Binder method
  // where pid or uid has changed its value. Both functions are
  // invoked when the caller's process is active. EnterBinderFunc
  // returns 'cookie' that will later be passed into ExitBinderFunc.
  typedef int64_t (*EnterBinderFunc)();
  typedef void (*ExitBinderFunc)(int64_t cookie);

  // Sets Binder emulation functions. This is used by Binder code to update
  // caller's pid/uid information when a service method is invoked.
  static void SetBinderEmulationFunctions(
      EnterBinderFunc enterFunc, ExitBinderFunc exitFunc);

  // Called by Dalvik when entering and exiting Binder methods. Result of
  // EnterBinderCall() indicates whether ExitBinderCall() should be called.
  static int64_t GetPidToken();
  static bool EnterBinderCall(int64_t pidToken);
  static void ExitBinderCall();

  static void SetArgV0(const char* argv);
  static bool GetInfoByPid(pid_t pid, std::string* out_argv0, uid_t* out_uid);

  // Gets the first emulated pid.  Note that by the time the function returns
  // the pid might no longer exist.  Returns 0 if no processes.
  pid_t GetFirstPid();
  // Gets the next largest valid pid.  Can handle last_pid being deleted since
  // the last call by returning another pid that has not previously been
  // returned (or 0 if all have been previously returned).
  pid_t GetNextPid(pid_t last_pid);

 private:
  friend class AppInstanceInitTest;
  friend class ChildPluginInstanceTest;
  friend struct DefaultSingletonTraits<ProcessEmulator>;
  friend class MockPlugin;
  friend class ProcessEmulatorPthreadArgUpdateTest;
  friend class ProcessEmulatorTest;
  friend class posix_translation::ProcfsHandlerTest;
  friend class posix_translation::ScopedUidSetter;
  typedef std::map<pid_t, std::string> PidStringMap;
  typedef std::map<pid_t, uid_t> PidUidMap;

  ProcessEmulator();
  ~ProcessEmulator() {}

  // For testing only: Reset this class/singleton state as much as possible.
  static void ResetForTest();

  // For testing only.
  static void SetFallbackUidForTest(uid_t uid);

  // For testing only.
  static void SetFakeThreadStateForTest(pid_t pid, uid_t uid);
  static void DestroyEmulatedProcessThreadStateForTest();

  // For testing only: Add the given emulated process.
  static void AddProcessForTest(pid_t pid, uid_t uid, const char* argv0);

  // For testing. Do not call.
  // In unit tests where |start_routine| is not actually started after
  // UpdatePthreadCreateArgsIfNewEmulatedProcess(), we need to call this
  // function with rewritten |start_routine| and |arg| to delete allocated
  // memory.
  static void DestroyPthreadCreateArgsIfAllocatedForTest(
      void* (*start_routine)(void*),  // NOLINT(readability/casting)
      void* arg);

  static pid_t AllocateNewPid(uid_t uid);
  EmulatedProcessInfo CreateNewEmulatedProcess(uid_t uid);
  void RecordTransactionLocked();

  static volatile EnterBinderFunc binder_enter_function_;
  static volatile ExitBinderFunc binder_exit_function_;

  TransactionNumber transaction_number_;
  PidStringMap argv0_per_emulated_process_;
  PidUidMap uid_per_emulated_process_;

  COMMON_DISALLOW_COPY_AND_ASSIGN(ProcessEmulator);
};

}  // namespace arc

#endif  // COMMON_PROCESS_EMULATOR_H_
