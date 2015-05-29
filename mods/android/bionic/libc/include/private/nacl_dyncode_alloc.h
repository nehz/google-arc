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
// Export nacl_dyncode_alloc to be used by user code. This is used in NDK
// translation to reserve the area where JITted code is located as well as the
// loading of .odex files in ART.

#ifndef _ANDROID_BIONIC_LIBC_PRIVATE_NACL_DYNCODE_ALLOC_H
#define _ANDROID_BIONIC_LIBC_PRIVATE_NACL_DYNCODE_ALLOC_H

#if defined(__native_client__)
__BEGIN_DECLS

void* nacl_dyncode_alloc(size_t code_size, size_t data_size,
                         size_t data_offset);

__END_DECLS
#endif

#endif  // _ANDROID_BIONIC_LIBC_PRIVATE_NACL_DYNCODE_ALLOC_H
