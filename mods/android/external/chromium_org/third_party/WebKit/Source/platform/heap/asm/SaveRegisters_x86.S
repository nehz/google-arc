// ARC MOD TRACK "third_party/android/external/chromium_org/third_party/WebKit/Source/platform/heap/asm/SaveRegisters_x86.asm"
// ARC MOD BEGIN
// Work around linter and yasm syntax.
#if 0
// ARC MOD END
;; Copyright (C) 2013 Google Inc. All rights reserved.
;;
;; Redistribution and use in source and binary forms, with or without
;; modification, are permitted provided that the following conditions are
;; met:
;;
;;     * Redistributions of source code must retain the above copyright
;; notice, this list of conditions and the following disclaimer.
;;     * Redistributions in binary form must reproduce the above
;; copyright notice, this list of conditions and the following disclaimer
;; in the documentation and/or other materials provided with the
;; distribution.
;;     * Neither the name of Google Inc. nor the names of its
;; contributors may be used to endorse or promote products derived from
;; this software without specific prior written permission.
;;
;; THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
;; "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
;; LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
;; A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
;; OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
;; SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
;; LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
;; DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
;; THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
;; (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
;; OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
;;
// ARC MOD BEGIN FORK
// ARC does not support yasm. Convert this file to GAS syntax.
#endif

// typedef void (*PushAllRegistersCallback)(SafePointBarrier*, ThreadState*, intptr_t*);
// extern "C" void pushAllRegisters(SafePointBarrier*, ThreadState*, PushAllRegistersCallback)

.hidden pushAllRegisters
.globl pushAllRegisters

pushAllRegisters:
    // Push all callee-saves registers to get them
    // on the stack for conservative stack scanning.
    // We maintain 16-byte alignment at calls (required on
    // Mac). There is a 4-byte return address on the stack
    // and we push 28 bytes which maintains 16-byte alignment
    // at the call.
    pushl %ebx
    pushl %ebp
    pushl %esi
    pushl %edi
    // Pass the two first arguments unchanged and the
    // stack pointer after pushing callee-save registers
    // to the callback.
    movl 28(%esp), %ecx
    pushl %esp
    pushl 28(%esp)
    pushl 28(%esp)
#if !defined(__native_client__)
    call *%ecx
#else
    naclcall %ecx
#endif // defined(__native_client__)
    // Pop arguments and the callee-saved registers.
    // None of the callee-saved registers were modified
    // so we do not need to restore them.
    addl $28, %esp
#if !defined(__native_client__)
    ret
#else
    naclret
#endif  // defined(__native_client__)

// ARC MOD END FORK
