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

// ART assumes TLS is accessible by inline assembly without an
// inter-module function call. This is not true on NaCl x86-64 and
// Bare Metal i686. To make __get_tls easily accessible from ART, we
// put __get_tls in a fixed address on these two targets.
// TODO(crbug.com/465216): Remove Bare Metal i686 support from this
// file and update this comment.

#ifndef _ANDROID_BIONIC_LIBC_INCLUDE_PRIVATE_GET_TLS_FOR_ART_H
#define _ANDROID_BIONIC_LIBC_INCLUDE_PRIVATE_GET_TLS_FOR_ART_H

// This file should be able to be included from assembly code.
#if !defined(__ASSEMBLER__)
typedef void** (*get_tls_fn_t)();
#endif

// Define them regardless of the target architecture. Host dex2oat
// would need all of them.

// An address unlikely to be used until the Bionic loader is
// loaded. This address is obtained by observing /proc/<pid>/maps
// several times.
#define POINTER_TO_GET_TLS_FUNC_ON_BMM_I386 0x20000
#define POINTER_TO_GET_TLS_FUNC_ON_NACL_X86_64 0x10020200

#endif  // _ANDROID_BIONIC_LIBC_INCLUDE_PRIVATE_GET_TLS_FOR_ART_H
