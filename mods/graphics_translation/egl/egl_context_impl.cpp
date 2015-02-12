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
#include "graphics_translation/egl/egl_context_impl.h"

#include <unistd.h>

#include "common/alog.h"
#include "graphics_translation/egl/egl_config_impl.h"
#include "graphics_translation/egl/egl_display_impl.h"
#include "graphics_translation/egl/egl_surface_impl.h"
#include "graphics_translation/egl/egl_thread_info.h"
#include "graphics_translation/egl/native.h"
#include "graphics_translation/gles/gles_context.h"

GlesContext* GetCurrentGlesContext() {
  EglThreadInfo& info = EglThreadInfo::GetInstance();
  ContextPtr ctx = info.GetCurrentContext();
  if (!ctx) {
    if (!info.SetReportedNoContextError()) {
      ALOGE("There is no current context for the OpenGL ES API (reported once "
            "per thread)");
    }
    return NULL;
  }
  return ctx->GetGlesContext();
}

EGLContext EglContextImpl::Create(EGLDisplay dpy, EGLConfig cfg,
                                  EGLContext shared, EGLint version,
                                  EGLint* out_error) {
  LOG_ALWAYS_FATAL_IF(out_error == NULL);
  *out_error = EGL_SUCCESS;

  EglDisplayImpl* d = EglDisplayImpl::GetDisplay(dpy);
  if (shared) {
    ContextPtr other = d->GetContexts().Get(shared);
    if (other->display != dpy) {
      ALOGE("Invalid shared context");
      *out_error = EGL_BAD_CONTEXT;
      return EGL_NO_CONTEXT;
    }
  }

  if (version != kGles11 && version != kGles20) {
    ALOGE("Version must be 1 or 2: %d", version);
    *out_error = EGL_BAD_ATTRIBUTE;
    return EGL_NO_CONTEXT;
  }

  ContextPtr ctx(new EglContextImpl(dpy, cfg, shared, (GlesVersion)version));
  if (!ctx) {
    *out_error = EGL_BAD_ALLOC;
    return EGL_NO_CONTEXT;
  }

  return d->GetContexts().Register(ctx);
}

EglContextImpl::EglContextImpl(EGLDisplay dpy, EGLConfig cfg,
                               EGLContext shared, GlesVersion version) :
    display(dpy),
    config(cfg),
    key_(0),
    native_context_(NULL),
    gles_(NULL),
    surface_(NULL),
    current_tid_(0) {
  EglDisplayImpl* d = EglDisplayImpl::GetDisplay(dpy);
  key_ = d->GetContexts().GenerateKey();

  const NativeConfig* native_config = d->GetConfig(cfg)->GetNativeConfig();

  ContextPtr global = d->GetGlobalContext();
  NativeContext* global_native_context =
      global ? global->native_context_ : NULL;
  native_context_ = Native::CreateContext(native_config, global_native_context);
  LOG_ALWAYS_FATAL_IF(!native_context_, "Could not create native context.");

  GlesContext* share_gles = NULL;
  if (shared) {
    share_gles = d->GetContexts().Get(shared)->GetGlesContext();
  }

  void* context = Native::GetUnderlyingContext(native_context_);
  const UnderlyingApis* apis = Native::GetUnderlyingApis(native_context_);
  gles_ = new GlesContext(reinterpret_cast<int32_t>(key_), version, share_gles,
                          context, apis);
}

EglContextImpl::~EglContextImpl() {
  // Cleanup share group and GLES context while advertising this context
  // as current. This is needed for some destructors that use pass through.
  EglThreadInfo& info = EglThreadInfo::GetInstance();
  ContextPtr prev_ctx = info.GetCurrentContext();
  LOG_ALWAYS_FATAL_IF(prev_ctx.Ptr() == this);
  ContextPtr this_ctx(this);
  info.SetCurrentContext(this_ctx);

  delete gles_;
  gles_ = NULL;

  // Prevent double-destruction, and restore the original context as current.
  info.SetCurrentContext(prev_ctx);
  this_ctx.Detach();

  Native::DestroyContext(native_context_);
  native_context_ = NULL;
}

void EglContextImpl::SetSurface(SurfacePtr s) {
  if (s != surface_) {
    // Keep the current surfaces "alive" until we are done switching surfaces.
    // Otherwise, GL function calls in the surface's destructor can result in
    // the wrong context being modified.
    SurfacePtr prev_surface = surface_;
    if (surface_) {
      surface_->BindToContext(NULL);
    }
    surface_ = s;
    if (surface_) {
      surface_->BindToContext(this);
    }
  }
  gles_->OnMakeCurrent();
}

void EglContextImpl::ClearSurface() {
  if (surface_) {
    surface_->BindToContext(NULL);
  }
  surface_.Reset();
}

void EglContextImpl::Flush() {
  gles_->Flush();
}

bool EglContextImpl::BindImageToTexture(EglImagePtr image) {
  return gles_->BindImageToTexture(GL_TEXTURE_2D, image);
}

bool EglContextImpl::BindImageToRenderbuffer(EglImagePtr image) {
  return gles_->BindImageToRenderbuffer(image);
}

bool EglContextImpl::SetCurrent() {
  const int tid = gettid();
  if (current_tid_ != 0 && current_tid_ != tid) {
    ALOGE("Context [%p] is current on thread [%d]", this, current_tid_);
    // TODO(crbug.com/442577): Temporarily returning true instead of false
    // until the bug can be fixed correctly.
    return true;
  }
  current_tid_ = tid;
  return true;
}

void EglContextImpl::ClearCurrent() {
  current_tid_ = 0;
}
