// This file is dual licensed under the MIT and the University of Illinois Open
// Source Licenses. See LICENSE.TXT for details.

#include "../assembly.h"

// float __floatundisf(du_int a);
// ARC MOD BEGIN
// Use naclret instead of ret.
// TODO(crbug.com/414569): L-rebase: use naclize_i686.py
#if defined(__native_client__)
#define ret naclret
#endif
// ARC MOD END

#ifdef __x86_64__

#if defined(__APPLE__)
	.literal4
#elif defined(__ELF__)
// ARC MOD BEGIN
// Our compiler does not like .rodata
//	.rodata
        .section .rodata
// ARC MOD END
#else
	.section .rdata,"rd"
#endif
two:
	.single 2.0

#define REL_ADDR(_a)	(_a)(%rip)

.text
.balign 4
DEFINE_COMPILERRT_FUNCTION(__floatundisf)
	movq		$1,			%rsi
	testq		%rdi,		%rdi
	js			1f
	cvtsi2ssq	%rdi,		%xmm0
	ret
	
1:	andq		%rdi,		%rsi
	shrq		%rdi
	orq			%rsi,		%rdi
	cvtsi2ssq	%rdi,		%xmm0
	mulss	REL_ADDR(two),	%xmm0
	ret
END_COMPILERRT_FUNCTION(__floatundisf)

#endif // __x86_64__
