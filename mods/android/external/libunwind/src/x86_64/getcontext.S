/* libunwind - a platform-independent unwind library
   Copyright (C) 2008 Google, Inc
	Contributed by Paul Pluzhnikov <ppluzhnikov@google.com>
   Copyright (C) 2010 Konstantin Belousov <kib@freebsd.org>

This file is part of libunwind.

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.  */

#include "ucontext_i.h"

/*  int _Ux86_64_getcontext (ucontext_t *ucp)

  Saves the machine context in UCP necessary for libunwind.  
  Unlike the libc implementation, we don't save the signal mask
  and hence avoid the cost of a system call per unwind.
  
*/

/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
// The mods replace UC_MCONTEXT_GREGS_RXX(%rdi) by MCONTEXT(GREGS_RXX).
#if defined __native_client__
#define MCONTEXT(x)    %nacl:UC_MCONTEXT_##x(%r15,%rdi)
#define retq naclret
#else
#define MCONTEXT(x)    UC_MCONTEXT_##x(%rdi)
#endif
/* ARC MOD END UPSTREAM */
	.global _Ux86_64_getcontext
/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
// NaCl requires functions aligned on 32-byte boundaries.
        .balign 32
/* ARC MOD END UPSTREAM libunwind-support-nacl */
	.type _Ux86_64_getcontext, @function
_Ux86_64_getcontext:
	.cfi_startproc

	/* Callee saved: RBX, RBP, R12-R15  */
/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
	movq %r12, MCONTEXT(GREGS_R12)
	movq %r13, MCONTEXT(GREGS_R13)
	movq %r14, MCONTEXT(GREGS_R14)
	movq %r15, MCONTEXT(GREGS_R15)
	movq %rbp, MCONTEXT(GREGS_RBP)
	movq %rbx, MCONTEXT(GREGS_RBX)

	/* Save argument registers (not strictly needed, but setcontext 
	   restores them, so don't restore garbage).  */
	movq %r8,  MCONTEXT(GREGS_R8)
	movq %r9,  MCONTEXT(GREGS_R9)
	movq %rdi, MCONTEXT(GREGS_RDI)
	movq %rsi, MCONTEXT(GREGS_RSI)
	movq %rdx, MCONTEXT(GREGS_RDX)
	movq %rax, MCONTEXT(GREGS_RAX)
	movq %rcx, MCONTEXT(GREGS_RCX)
/* ARC MOD END UPSTREAM */
/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
// #if defined __linux__
#if defined __native_client__
/* TODO(crbug.com/462399): L-rebase: Process fpregs_mem. */
#elif defined __linux__
/* ARC MOD END UPSTREAM */
	/* Save fp state (not needed, except for setcontext not
	   restoring garbage).  */
	leaq UC_MCONTEXT_FPREGS_MEM(%rdi),%r8
	movq %r8, UC_MCONTEXT_FPREGS_PTR(%rdi)
	fnstenv (%r8)
	stmxcsr FPREGS_OFFSET_MXCSR(%r8)
#elif defined __FreeBSD__
	fxsave UC_MCONTEXT_FPSTATE(%rdi)
	movq $UC_MCONTEXT_FPOWNED_FPU,UC_MCONTEXT_OWNEDFP(%rdi)
	movq $UC_MCONTEXT_FPFMT_XMM,UC_MCONTEXT_FPFORMAT(%rdi)
	/* Save rflags and segment registers, so that sigreturn(2)
	does not complain. */
	pushfq
	.cfi_adjust_cfa_offset 8
	popq UC_MCONTEXT_RFLAGS(%rdi)
	.cfi_adjust_cfa_offset -8
	movl $0, UC_MCONTEXT_FLAGS(%rdi)
	movw %cs, UC_MCONTEXT_CS(%rdi)
	movw %ss, UC_MCONTEXT_SS(%rdi)
#if 0
	/* Setting the flags to 0 above disables restore of segment
	   registers from the context */
	movw %ds, UC_MCONTEXT_DS(%rdi)
	movw %es, UC_MCONTEXT_ES(%rdi)
	movw %fs, UC_MCONTEXT_FS(%rdi)
	movw %gs, UC_MCONTEXT_GS(%rdi)
#endif
	movq $UC_MCONTEXT_MC_LEN_VAL, UC_MCONTEXT_MC_LEN(%rdi)
#else
#error Port me
#endif

	leaq 8(%rsp), %rax /* exclude this call.  */
/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
	movq %rax, MCONTEXT(GREGS_RSP)

	movq 0(%rsp), %rax
	movq %rax, MCONTEXT(GREGS_RIP)
/* ARC MOD END UPSTREAM */

	xorq	%rax, %rax
	retq
	.cfi_endproc
	.size _Ux86_64_getcontext, . - _Ux86_64_getcontext

/*  int _Ux86_64_getcontext_trace (ucontext_t *ucp)

  Saves limited machine context in UCP necessary for libunwind.
  Unlike _Ux86_64_getcontext, saves only the parts needed for
  fast trace. If fast trace fails, caller will have to get the
  full context.
*/

	.global _Ux86_64_getcontext_trace
/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
// NaCl requires functions aligned on 32-byte boundaries.
        .balign 32
/* ARC MOD END UPSTREAM libunwind-support-nacl */
	.hidden _Ux86_64_getcontext_trace
	.type _Ux86_64_getcontext_trace, @function
_Ux86_64_getcontext_trace:
	.cfi_startproc

	/* Save only RBP, RBX, RSP, RIP - exclude this call. */
/* ARC MOD BEGIN UPSTREAM libunwind-support-nacl */
	movq %rbp, MCONTEXT(GREGS_RBP)
	movq %rbx, MCONTEXT(GREGS_RBX)

	leaq 8(%rsp), %rax
	movq %rax, MCONTEXT(GREGS_RSP)

	movq 0(%rsp), %rax
	movq %rax, MCONTEXT(GREGS_RIP)
/* ARC MOD END UPSTREAM */

	xorq	%rax, %rax
	retq
	.cfi_endproc
	.size _Ux86_64_getcontext_trace, . - _Ux86_64_getcontext_trace

      /* We do not need executable stack.  */
      .section        .note.GNU-stack,"",@progbits
