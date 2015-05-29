/*
 * Copyright (C) 2014 The Android Open Source Project
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
 * limitations under the License.
 */

#if defined(BARE_METAL_BIONIC)

// Define a function which is called when a new binary is loaded by
// the Bionic loader. src/build/util/bare_metal_gdb.py sets a
// breakpoint to this function and executes GDB's add-symbol-file
// command to let GDB read the newly loaded binaries.

// We implement this function by assembly to make sure we do not
// create a stack frame. If we use a C function to create this
// function, a compiler may or may not generate code for creating
// a stack frame. By always not creating a stack frame, we can
// simplify the implementation of bare_metal_gdb.py for i386.

// Note: When we define a whole function with inline assembler,
// our clang seems to wrongfully remove the definition of the
// function even if it is called, in ARM. That is why we do not
// define __bare_metal_notify_gdb_of_load in linker.cpp.

.globl __bare_metal_notify_gdb_of_load
__bare_metal_notify_gdb_of_load:
        // GDB seems to be sometimes confused when we set a breakpoint
        // to the instruction which returns from a function.
        nop
# if defined(__arm__)
        bx lr
# elif defined(__i386__) || defined(__x86_64__)
        ret
# else
#  error "Unsupported architecture!"
# endif

#endif  // BARE_METAL_BIONIC
