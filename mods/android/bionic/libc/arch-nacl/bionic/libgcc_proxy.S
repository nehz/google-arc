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

/* This file contains hidden symbols in libgcc_eh.a that are used by DSOs.
 * Original symbols are prefixed with "__real" in android/bionic/config.py and
 * re-exposed as a default symbol from this file.
 * The lines that begin with "define_proxy" are processed in config.py to export
 * the symbols.
 */

.macro define_proxy name
  .balign 32
  .global \name
  .type \name, @function
  \name:
    jmp __real\name
.endm

.section .text
define_proxy __register_frame_info
define_proxy __deregister_frame_info
define_proxy _Unwind_GetLanguageSpecificData
define_proxy _Unwind_Resume
define_proxy _Unwind_RaiseException
define_proxy _Unwind_DeleteException
define_proxy _Unwind_GetRegionStart
define_proxy _Unwind_SetIP
define_proxy _Unwind_GetIP
define_proxy _Unwind_SetGR
define_proxy _Unwind_Backtrace
