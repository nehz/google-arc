// ARC MOD TRACK "third_party/android/external/chromium_org/third_party/WebKit/Source/platform/heap/asm/SaveRegisters_x86.asm"
// ARC MOD BEGIN FORK
// ARC does not support yasm. Convert this file to GAS syntax.
// Copyright (C) 2013 Google Inc. All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are
// met:
//
//     * Redistributions of source code must retain the above copyright
// notice, this list of conditions and the following disclaimer.
//     * Redistributions in binary form must reproduce the above
// copyright notice, this list of conditions and the following disclaimer
// in the documentation and/or other materials provided with the
// distribution.
//     * Neither the name of Google Inc. nor the names of its
// contributors may be used to endorse or promote products derived from
// this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
// A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
// OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
// SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
// LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
// DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
// THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
//

// typedef void (*PushAllRegistersCallback)(SafePointBarrier*, ThreadState*, intptr_t*);
// extern "C" void pushAllRegisters(SafePointBarrier*, ThreadState*, PushAllRegistersCallback)

.hidden pushAllRegisters
.globl pushAllRegisters

pushAllRegisters:
    // Push all callee-saves registers to get them
    // on the stack for conservative stack scanning.
    // We maintain 16-byte alignment at calls (required on Mac).
    // There is an 8-byte return address on the stack and we push
    // 56 bytes which maintains 16-byte stack alignment
    // at the call.
    pushq $0
    pushq %rbx
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    // Pass the two first arguments unchanged (rdi, rsi)
    // and the stack pointer after pushing callee-saved
    // registers to the callback.
    movq %rdx, %r8
    movq %rsp, %rdx
#if !defined(__native_client__)
    call *%r8
#else
    naclcall %r8d, %r15
#endif  // defined(__native_client__)
    // Pop the callee-saved registers. None of them were
    // modified so no restoring is needed.
#if !defined(__native_client__)
    addq $56, %rsp
    ret
#else
    naclasp $56, %r15
    // This bundle lock is required to keep the NaCl validator happy.
    // It does not add extra padding.
.bundle_lock
    naclret
.bundle_unlock
#endif  // defined(__native_client__)

// ARC MOD END FORK
