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
// Saves and clears register context on the current thread.
// For use with blocking IRT calls.

#ifndef _IRT_CONTEXT_H
#define _IRT_CONTEXT_H

#if defined(__cplusplus)
extern "C" {
#endif

extern void __pthread_save_context_regs(void* regs, int size);
extern void __pthread_clear_context_regs();


#define CLEAR_CONTEXT_REGS()  __pthread_clear_context_regs()


#if defined(__x86_64__)

extern void BionicInternalSaveRegContext(uint64_t*);

#define SAVE_CONTEXT_REGS()                                     \
  {                                                             \
    uint64_t regs_tmp[17];                                      \
    BionicInternalSaveRegContext(regs_tmp);                     \
    __pthread_save_context_regs(regs_tmp, sizeof(regs_tmp));    \
  }

#elif defined(__i386__)

extern void BionicInternalSaveRegContext(uint32_t*);

#define SAVE_CONTEXT_REGS()                                     \
  {                                                             \
    uint32_t regs_tmp[15];                                      \
    BionicInternalSaveRegContext(regs_tmp);                     \
    __pthread_save_context_regs(regs_tmp, sizeof(regs_tmp));    \
  }


#elif defined(__arm__)

#ifndef __thumb__

// Use inline assembly to save correct LR register state.
#define BionicInternalSaveRegContext(ctx)                       \
  (({                                                           \
  register char* stm_base asm ("r12") = ctx;                    \
  __asm__ __volatile__ (                                        \
    "stmia %[base], {r0-r15}"                                   \
    : : [base] "r" (stm_base) : "memory");                      \
  }))

#else  // __thumb__

#define BionicInternalSaveRegContext(ctx)                       \
  (({                                                           \
  register char* stm_base asm ("r12") = ctx;                    \
  __asm__ __volatile__ (                                        \
    ".align 2\nbx pc\nnop\n.code 32\n"                          \
    "stmia %[base], {r0-r15}\n"                                 \
    "orr %[base], pc, #1\nbx %[base]"                           \
    : [base] "+r" (stm_base) : : "memory", "cc");               \
  }))

#endif  // !__thumb__


#define SAVE_CONTEXT_REGS()                                     \
  {                                                             \
    uint32_t regs_tmp[16];                                      \
    BionicInternalSaveRegContext((char*)regs_tmp);              \
    __pthread_save_context_regs(regs_tmp, sizeof(regs_tmp));    \
  }

#else  // !defined(__arm__)

#define SAVE_CONTEXT_REGS()  ;

#endif

#if defined(__cplusplus)
}
#endif

#endif  // _IRT_CONTEXT_H
