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
  movq \x, %nacl:\y(%r15, %rdi)
.endm

#define retq naclret


// void BionicInternalSaveRegContext(uint64_t[17])
// Saves register context necessary for traversing the stack in a minidump.
.global BionicInternalSaveRegContext
.type BionicInternalSaveRegContext, @function
BionicInternalSaveRegContext:
  .cfi_startproc

  // The ordering matches the one specified in ucontext.h.
  store_reg %r8,  0x00
  store_reg %r9,  0x08
  store_reg %r10, 0x10
  store_reg %r11, 0x18
  store_reg %r12, 0x20
  store_reg %r13, 0x28
  store_reg %r14, 0x30
  store_reg %r15, 0x38
  store_reg %rdi, 0x40
  store_reg %rsi, 0x48
  store_reg %rbp, 0x50
  store_reg %rbx, 0x58
  store_reg %rdx, 0x60
  store_reg %rax, 0x68
  store_reg %rcx, 0x70

  // Store caller's RSP.
  leaq 8(%rsp), %rax
  store_reg %rax, 0x78

  // Store caller's RIP.
  movq 0(%rsp), %rax
  store_reg %rax, 0x80

  retq

  .cfi_endproc
  .size BionicInternalSaveRegContext, . - BionicInternalSaveRegContext

.section .note.GNU-stack, "", @progbits
