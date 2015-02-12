/*
 * Copyright (C) 2011 The Android Open Source Project
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
#ifndef GRAPHICS_TRANSLATION_GLES_SMARTPTR_H_
#define GRAPHICS_TRANSLATION_GLES_SMARTPTR_H_

#include <stdlib.h>

#if defined(HAVE_ARC)
#include "cutils/atomic.h"
#define GLES_ATOMIC_INCREMENT android_atomic_inc
#define GLES_ATOMIC_DECREMENT android_atomic_dec
#else
#error "Unsupported platform"
#endif

template <class T>
class SmartPtr {
 public:
  explicit SmartPtr(T* ptr = 0)
    : ptr_(ptr),
      count_(NULL) {
    if (ptr) {
      count_ = new int32_t(1);
    }
  }

  SmartPtr<T>(const SmartPtr<T>& rhs) {
    count_ = rhs.count_;
    ptr_ = rhs.ptr_;
    Acquire();
  }

  ~SmartPtr() {
    Release();
  }

  SmartPtr<T>& operator=(const SmartPtr<T>& rhs) {
    if (ptr_ != rhs.ptr_) {
      Release();
      count_ = rhs.count_;
      ptr_ = rhs.ptr_;
      Acquire();
    }
    return *this;
  }

  template<typename U>
  SmartPtr<U> Cast() const {
    SmartPtr<U> other;
    other.ptr_ = static_cast<U*>(ptr_);
    other.count_ = count_;
    other.Acquire();
    return other;
  }

  void Reset() {
    Release();
    count_ = NULL;
    ptr_ = NULL;
  }

  void Detach() {
    ptr_ = NULL;
  }

  T* Ptr() const {
    return ptr_;
  }

  T* operator->() const {
    return ptr_;
  }

  T& operator*() const {
    return *ptr_;
  }

  bool operator<(const SmartPtr<T>& rhs) const {
    return ptr_ < rhs.ptr_;
  }

  bool operator==(const SmartPtr<T>& rhs) const {
    return ptr_ == rhs.ptr_;
  }

  bool operator!=(const SmartPtr<T>& rhs) const {
    return ptr_ != rhs.ptr_;
  }

  // Safe-bool idiom.
  typedef void (*SafeBoolType)();
  operator SafeBoolType() const {
    return ptr_ ? &SafeBoolHelper : NULL;
  }

 private:
  // Increment the reference count on this pointer by 1.
  void Acquire() {
    if (count_) {
      GLES_ATOMIC_INCREMENT(count_);
    }
  }

  // Decrement the reference count on the pointer by 1.
  // If the reference count goes to (or below) 0, the pointer is deleted.
  void Release() {
    if (!count_) {
      return;
    }

    const int value = GLES_ATOMIC_DECREMENT(count_);
    if (value > 1) {
      return;
    }

    delete count_;
    count_ = NULL;

    delete ptr_;
    ptr_ = NULL;
  }

  static void SafeBoolHelper() {}

  template<typename U>
  friend class SmartPtr;

  T* ptr_;
  int32_t* count_;
};

#undef GLES_ATOMIC_INCREMENT
#undef GLES_ATOMIC_DECREMENT

#endif  // GRAPHICS_TRANSLATION_GLES_SMARTPTR_H_
