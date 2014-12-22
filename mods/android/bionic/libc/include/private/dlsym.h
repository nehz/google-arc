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

#ifndef _ANDROID_BIONIC_LIBC_PRIVATE_DLSYM_WITH_RETURN_ADDRESS_H
#define _ANDROID_BIONIC_LIBC_PRIVATE_DLSYM_WITH_RETURN_ADDRESS_H

__BEGIN_DECLS

// This function is dlsym with an extra argument that tells the return
// address of the "real" caller which is used to determine the library
// lookup chain when |handle| is RTLD_NEXT. It is only for ARC's internal
// use (called by __wrap_dlsym) and a NDK trampoline is not provided.
void* __dlsym_with_return_address(
    void* handle, const char* symbol, void* ret_addr);

__END_DECLS

#endif  // _ANDROID_BIONIC_LIBC_PRIVATE_DLSYM_WITH_RETURN_ADDRESS_H
