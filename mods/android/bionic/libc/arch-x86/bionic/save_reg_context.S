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

.macro store_reg x, y
  movl \x, \y(%edi)
.endm

// void __pthread_internal_save_reg_context(uint32_t[15])
// Saves register context necessary for traversing the stack in a minidump.
.global __pthread_internal_save_reg_context
.type __pthread_internal_save_reg_context, @function
__pthread_internal_save_reg_context:
  .cfi_startproc
  pushl %edi
  .cfi_adjust_cfa_offset 4
  mov 8(%esp), %edi

  // The ordering matches the one specified in ucontext.h.
  // We're not efficient here because first four registers are segment registers.
  store_reg %esi,  0x14
  store_reg %ebp,  0x18
  store_reg %ebx,  0x20
  store_reg %edx,  0x24
  store_reg %ecx,  0x28
  store_reg %eax,  0x2c

  // edi
  mov 0(%esp), %eax
  store_reg %eax,  0x10

  // Store caller's ESP.
  // Hmm... really?
  leal 8(%esp), %eax
  store_reg %eax, 0x1c

  // Store caller's EIP.
  movl 4(%esp), %eax
  store_reg %eax, 0x38

  popl %edi
  .cfi_adjust_cfa_offset -4
  ret

  .cfi_endproc
  .size __pthread_internal_save_reg_context, . - __pthread_internal_save_reg_context

.section .note.GNU-stack, "", @progbits
