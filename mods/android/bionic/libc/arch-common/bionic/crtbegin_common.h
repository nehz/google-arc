// Copyright (C) 2015 The Android Open Source Project
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
// Defines the first element of ctors and dtors sections. All shared
// objects and executables should include this as the first object.

#if defined(__native_client__)

#include <private/nacl_syscalls.h>
#include <stdlib.h>

extern int __cxa_atexit(void (*func)(void *), void *arg, void *dso);
extern void __cxa_finalize(void *);

// .eh_frame does not have a watchdog for the first element.
__attribute__((section (".eh_frame")))
const int __EH_FRAME_BEGIN__[0] = {};

void __register_frame_info(const void* eh, void* obj);
void __deregister_frame_info(const void* eh);

// The _fini function could be called in two different ways. If the
// DSO is dlopen'ed and then dlclose'ed, call_destructors() in
// soinfo_unload() in linker.cpp calls this function. When the DSO
// is a DT_NEEDED one, this function is called as an atexit handler
// when the main nexe exits.
__LIBC_HIDDEN__ __attribute__((section(".fini")))
void _fini(void) {
  __deregister_frame_info(__EH_FRAME_BEGIN__);
}

__LIBC_HIDDEN__ __attribute__((unused, section(".init")))
void _init() {
  // This is the max size of "struct object" in
  // http://gcc.gnu.org/git/?p=gcc.git;a=blob;f=libgcc/unwind-dw2-fde.h;h=2bbc60a837c8e3a5d62cdd44f2ae747731f9c8f8;hb=HEAD
  // This buffer is used by libgcc. Unfortunately, it seems there are
  // no way to get the size of this struct.
  // Note that bionic/libc/arch-x86/bionic/crtbegin.S uses 24
  // (sizeof(void*) * 6) for this buffer, but we use 28 here because
  // it seems there can be one more element if
  // DWARF2_OBJECT_END_PTR_EXTENSION is enabled.
  static char buf[sizeof(void*) * 7];
  // Register the info in .eh_frame to libgcc. Though we are disabling
  // C++ exceptions, we want to do this for _Unwind_Backtrace.
  __register_frame_info(__EH_FRAME_BEGIN__, buf);
}

#endif  // defined(__native_client__)
