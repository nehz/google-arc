// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// A simple cross platform thread local storage implementation.
//
// This is a drop-in replacement of __thread keyword. If your compiler
// toolchain supports __thread keyword, the user of this code should
// be as fast as the code which uses __thread. Chrome's
// base::ThreadLocalPointer and base::ThreadLocalStorage cannot be as
// fast as __thread.
// TODO(crbug.com/249345): If pthread_getspecific is slow for our use,
// expose bionic's internal TLS and stop using pthread_getspecific
// based implementation.
//
// Usage:
//
// Before (linux):
//
// __thread Foo* foo;
// foo = new Foo();
// foo->func();
//
//
// After:
//
// DEFINE_THREAD_LOCAL(Foo*, foo);
// foo.Set(new Foo());
// foo.Get()->func();
//

#ifndef COMMON_THREAD_LOCAL_H_
#define COMMON_THREAD_LOCAL_H_

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

#include "common/alog.h"

namespace arc {

// Thread local storage implementation which uses pthread.
// Note that this class will be used as a global variable just like
// thread local storage based on __thread keyword. So, we must not use
// fancy stuff such as ALOG from constructor and destructor of this
// class.
template <class Type>
class ThreadLocal {
 public:
  ThreadLocal() {
    if (pthread_key_create(&key_, NULL)) {
      perror("pthread_key_create");
      abort();
    }
  }

  ~ThreadLocal() {
    if (pthread_key_delete(key_)) {
      perror("pthread_key_delete");
      abort();
    }
  }

  Type Get() const {
    return reinterpret_cast<Type>(pthread_getspecific(key_));
  }

  void Set(Type v) {
    if (int error = pthread_setspecific(key_, reinterpret_cast<void *>(v))) {
      LOG_ALWAYS_FATAL("Failed to set a TLS: error=%d", error);
    }
  }

 private:
  pthread_key_t key_;
};

#define DEFINE_THREAD_LOCAL(Type, name) arc::ThreadLocal<Type> name;

}  // namespace arc

#endif  // COMMON_THREAD_LOCAL_H_
