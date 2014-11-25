// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef POSIX_TRANSLATION_WRAP_H_
#define POSIX_TRANSLATION_WRAP_H_

namespace arc {

// Initializes IRT hooks to intercept system calls.
void InitIRTHooks();

}  // namespace arc

#endif  // POSIX_TRANSLATION_WRAP_H_
