// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// PID and thread management functions.

#ifndef COMMON_PROCESS_EMULATOR_H_
#define COMMON_PROCESS_EMULATOR_H_

#include <sys/types.h>
#include <unistd.h>

#include <string>

template <typename T> struct DefaultSingletonTraits;

// Only for testing.
namespace posix_translation {
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

// This is a singleton class that emulates threads within
// the same process belonging to different processes and having
// potentially different uids.  It causes getpid() and getuid() to
// return emulated values.  CreateEmulatedProcess must be called on a
// thread which is not yet being emulated, and then it and all of the
// threads created from it will belong to the same emulated process.
class ProcessEmulator {
 public:
  // Returns singleton instance.
  static ProcessEmulator* GetInstance();

  // Returns true if pthread_create has already been called.
  static bool IsMultiThreaded();

  // Generates new PID and assigns it to the current thread along with
  // the provided user id.  Current thread must not already belong to
  // an emulated process.
  void CreateEmulatedProcess(uid_t uid);

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
  static void FilterPthreadCreate(
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

 private:
  friend class AppInstanceInitTest;
  friend class ChildPluginInstanceTest;
  friend struct DefaultSingletonTraits<ProcessEmulator>;
  friend class MockPlugin;
  friend class ProcessEmulatorTest;
  friend class posix_translation::ScopedUidSetter;

  ProcessEmulator();
  ~ProcessEmulator() {}

  // For testing. Do not call.
  static void SetIsMultiThreaded(bool is_multi_threaded);

  // For testing. Do not call.
  static void SetFallbackUidForTesting(uid_t uid);

  // For testing. Do not call.
  static void SetFakeThreadStateForTesting(pid_t pid, uid_t uid);
  static void UnsetThreadStateForTesting();

  // For testing. Do not call.
  // In unit tests where |start_routine| is not acutally started after
  // FilterPthreadCreate(), we need to call this function with rewritten
  // |start_routine| and |arg| to delete allocated memory.
  static void UnfilterPthreadCreateForTesting(
      void* (*start_routine)(void*),  // NOLINT(readability/casting)
      void* arg);

  static volatile EnterBinderFunc binder_enter_function_;
  static volatile ExitBinderFunc binder_exit_function_;

  ProcessEmulator(const ProcessEmulator&);
  void operator=(const ProcessEmulator&);
};

}  // namespace arc

#endif  // COMMON_PROCESS_EMULATOR_H_
