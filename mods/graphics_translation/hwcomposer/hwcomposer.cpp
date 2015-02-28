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
#include <cutils/properties.h>
#include <gralloc/gralloc.h>
#include <hardware/hwcomposer.h>
#include <utils/Errors.h>

#include "common/options.h"
#include "common/plugin_handle.h"
#include "gralloc/graphics_buffer.h"

using arc::CompositorInterface;
typedef arc::CompositorInterface::Display Display;
typedef arc::CompositorInterface::Layer Layer;
typedef arc::CompositorInterface::Rect Rect;

struct hwc_context_t {
  hwc_context_t();
  ~hwc_context_t();

  void RegisterCallbacks(const hwc_procs_t* procs);

  struct Callbacks : public CompositorInterface::Callbacks {
    Callbacks(const hwc_procs_t* procs) : procs_(procs) {}

    virtual void Invalidate() const {
      procs_->invalidate(procs_);
    }

    virtual void Vsync(int disp, int64_t timestamp) const {
      procs_->vsync(procs_, disp, timestamp);
    }

    virtual void Hotplug(int disp, bool connected) const {
      procs_->hotplug(procs_, disp, connected ? 1 : 0);
    }

    const hwc_procs_t* procs_;
  };

  hwc_composer_device_1_t device;
  CompositorInterface::Display display;
  CompositorInterface::Callbacks* callbacks;
  CompositorInterface* compositor;
  const hwc_procs_t* procs;
  std::vector<int> fds;

  int32_t width;
  int32_t height;
  int32_t refresh;
  int32_t xdpi;
  int32_t ydpi;
};

hwc_context_t::hwc_context_t() :
#ifdef __clang__
    // Initialize const member variables in the struct. Otherwise, this file
    // does not compile with clang. Note that this is C++11 style
    // initialization.
    // TODO(crbug.com/365178): Remove the ifdef once C++11 is enabled for GCC.
    device({}),
#endif
    callbacks(NULL),
    compositor(NULL),
    procs(0),
    width(0),
    height(0),
    refresh(0),
    xdpi(0),
    ydpi(0) {
}

hwc_context_t::~hwc_context_t() {
  compositor->RegisterCallbacks(NULL);
  delete callbacks;
}

void hwc_context_t::RegisterCallbacks(const hwc_procs_t* procs) {
  Callbacks* cb = new Callbacks(procs);
  compositor->RegisterCallbacks(cb);
  delete callbacks;
  callbacks = cb;
}

static const GraphicsBuffer* GetGraphicsBuffer(buffer_handle_t handle) {
  return static_cast<const GraphicsBuffer*>(handle);
}

static Rect MakeRect(const hwc_rect_t& in) {
  const Rect r = { in.left, in.top, in.right, in.bottom };
  return r;
}

static int GetDisplayDensity() {
  // TODO(crbug.com/459280): Get this information from the RenderParams.
  char property[PROPERTY_VALUE_MAX];
  int density = 120;
  if (property_get("ro.sf.lcd_density", property, NULL)) {
    density = atoi(property);
  } else {
    ALOGE("hwcomposer: could not read lcd_density");
  }
  return 1000 * density;
}

static bool IsLayerSkippable(hwc_layer_1_t* layer) {
  if (layer->flags & HWC_SKIP_LAYER) {
    return true;
  }
  // We only handle these two types.
  if (layer->compositionType != HWC_OVERLAY &&
      layer->compositionType != HWC_BACKGROUND) {
    return true;
  }
  if (layer->compositionType == HWC_OVERLAY) {
    // Overlay layers (the majority) must have a valid handle.
    if (!GetGraphicsBuffer(layer->handle)->IsValid()) {
      return true;
    }
  }
  return false;
}

static void UpdateLayer(Layer* layer, hwc_layer_1_t* hw_layer) {
  switch(layer->type) {
    case Layer::TYPE_TEXTURE: {
      const GraphicsBuffer* buffer = GetGraphicsBuffer(hw_layer->handle);
      // The buffer is upside down, if it is rendered by software.
      const int need_flip_flags = GRALLOC_USAGE_SW_WRITE_MASK |
                                  GRALLOC_USAGE_HW_CAMERA_WRITE |
                                  GRALLOC_USAGE_ARC_SYSTEM_TEXTURE;
      layer->need_flip = buffer->GetUsage() & need_flip_flags;
      layer->texture.target = buffer->GetHostTarget();
      layer->texture.name = buffer->GetHostTexture();
      layer->context = buffer->GetHostContext();
      layer->alpha = hw_layer->planeAlpha;
      layer->is_opaque = hw_layer->blending == HWC_BLENDING_NONE ||
          hw_layer->planeAlpha == 255;
      break;
    }
    case Layer::TYPE_SOLID_COLOR: {
      const hwc_color_t& color = hw_layer->backgroundColor;
      layer->color =
          Layer::PackColor(color.r, color.g, color.b, color.a);
      break;
    }
  }
}

static void UpdateDisplay(Display* display,
                          hwc_display_contents_1_t* hw_display) {
  std::vector<Layer>::iterator layers_it = display->layers.begin();
  for (size_t i = 0; i != hw_display->numHwLayers; ++i) {
    hwc_layer_1_t* layer = &hw_display->hwLayers[i];
    if (!IsLayerSkippable(layer)) {
      UpdateLayer(&(*layers_it++), layer);
    }
  }
  if (layers_it != display->layers.end()) {
    ALOGE("Unexpected number of layers updated");
  }
}

static Layer MakeLayer(hwc_layer_1_t* hw_layer) {
  Layer layer;
  switch(hw_layer->compositionType) {
    case HWC_OVERLAY: {
      const GraphicsBuffer* buffer = GetGraphicsBuffer(hw_layer->handle);
      layer.size.width = buffer->GetWidth();
      layer.size.height = buffer->GetHeight();
      layer.type = Layer::TYPE_TEXTURE;
      layer.source = MakeRect(hw_layer->sourceCropi);
      layer.dest = MakeRect(hw_layer->displayFrame);
      layer.transform = hw_layer->transform;
      break;
    }
    case HWC_BACKGROUND: {
      layer.type = Layer::TYPE_SOLID_COLOR;
      break;
    }
    default: {
      ALOGE("Unexpected layer type: %d", hw_layer->compositionType);
      // Make sure we have a deterministic value, a solid black layer.
      layer.type = Layer::TYPE_SOLID_COLOR;
      layer.color = Layer::PackColor(0, 0, 0, 255);
      return layer;
    }
  }
  UpdateLayer(&layer, hw_layer);
  return layer;
}

static Display MakeDisplay(hwc_context_t* context,
                           hwc_display_contents_1_t* hw_display) {
  Display display;
  display.size.width = context->width;
  display.size.height = context->height;

  display.layers.reserve(hw_display->numHwLayers);
  for (size_t i = 0; i != hw_display->numHwLayers; ++i) {
    hwc_layer_1_t* layer = &hw_display->hwLayers[i];
    if (!IsLayerSkippable(layer)) {
      display.layers.push_back(MakeLayer(layer));
    }
  }
  return display;
}

static int hwc_prepare(hwc_composer_device_1_t* dev, size_t numDisplays,
                       hwc_display_contents_1_t** displays) {
  ALOGD("HWC_PREPARE");
  if (displays && displays[0]) {
    // ARC Only supports the primary display.
    if (displays[0]->flags & HWC_GEOMETRY_CHANGED) {
      for (size_t i = 0; i < displays[0]->numHwLayers; i++) {
        hwc_layer_1_t* layer = &displays[0]->hwLayers[i];
        switch (layer->compositionType) {
          case HWC_FRAMEBUFFER:
            layer->compositionType = HWC_OVERLAY;
            break;
          case HWC_BACKGROUND:
          case HWC_FRAMEBUFFER_TARGET:
          case HWC_OVERLAY:
            break;
          default:
            ALOGE("hwcomposor: Invalid compositionType %d",
                    layer->compositionType);
            break;
        }
      }
    }
    return 0;
  }
  return -1;
}

static int hwc_set(hwc_composer_device_1_t* dev, size_t numDisplays,
                   hwc_display_contents_1_t** displays) {
  ALOGD("HWC_SET");
  hwc_context_t* context = reinterpret_cast<hwc_context_t*>(dev);
  if (displays && displays[0]) {
    if (displays[0]->flags & HWC_GEOMETRY_CHANGED) {
      context->display = MakeDisplay(context, displays[0]);
      context->fds.reserve(1 + context->display.layers.size());
    } else {
      UpdateDisplay(&context->display, displays[0]);
    }

    int ret = context->compositor->Set(context->display, &context->fds);
    std::vector<int>::const_iterator it = context->fds.begin();
    displays[0]->retireFenceFd = *it++;
    for(size_t i = 0; i != displays[0]->numHwLayers; ++i) {
      hwc_layer_1_t* layer = &displays[0]->hwLayers[i];
      if (!IsLayerSkippable(layer)) {
        layer->releaseFenceFd = *it++;
      }
    }
    return ret;
  }
  return -1;
}

static int hwc_event_control(hwc_composer_device_1* dev, int disp,
                             int event, int enabled) {
  if (event != HWC_EVENT_VSYNC) {
    ALOGE("eventControl: Wrong event type: %d", event);
    return -EINVAL;
  }
  if (enabled != 0 && enabled != 1) {
    ALOGE("eventControl: Enabled should be 0 or 1");
    return -EINVAL;
  }
  if (disp == 0) {
    hwc_context_t* context = reinterpret_cast<hwc_context_t*>(dev);
    context->compositor->EnableVsync(enabled);
  }
  return 0;
}

static int hwc_get_display_configs(hwc_composer_device_1* dev, int disp,
                                   uint32_t* configs, size_t* numConfigs) {
  if (disp != 0) {
    return android::BAD_INDEX;
  }
  if (*numConfigs < 1) {
    return android::NO_ERROR;
  }
  // Config[0] will be passed in to getDisplayAttributes as the disp parameter.
  // The ARC display supports only 1 configuration.
  configs[0] = 0;
  *numConfigs = 1;
  return android::NO_ERROR;
}

static int hwc_get_display_attributes(hwc_composer_device_1* dev,
                                      int disp, uint32_t config,
                                      const uint32_t* attributes,
                                      int32_t* values) {
  if (disp != 0 || config != 0) {
    return android::BAD_INDEX;
  }

  hwc_context_t* context = reinterpret_cast<hwc_context_t*>(dev);
  while (*attributes != HWC_DISPLAY_NO_ATTRIBUTE) {
    switch (*attributes) {
      case HWC_DISPLAY_VSYNC_PERIOD:
        *values = context->refresh;
        break;
      case HWC_DISPLAY_WIDTH:
        *values = context->width;
        break;
      case HWC_DISPLAY_HEIGHT:
        *values = context->height;
        break;
      case HWC_DISPLAY_DPI_X:
        *values = context->xdpi;
        break;
      case HWC_DISPLAY_DPI_Y:
        *values = context->ydpi;
        break;
      default:
        ALOGE("Unknown attribute value 0x%02x", *attributes);
    }
    ++attributes;
    ++values;
  }
  return android::NO_ERROR;
}

static void hwc_register_procs(hwc_composer_device_1* dev,
                               hwc_procs_t const* procs) {
  hwc_context_t* context = reinterpret_cast<hwc_context_t*>(dev);
  context->RegisterCallbacks(procs);
}

static int hwc_blank(hwc_composer_device_1* dev, int disp, int blank) {
  return 0;
}

static int hwc_query(hwc_composer_device_1* dev, int what, int* value) {
  return 0;
}

static int hwc_device_close(hw_device_t* dev) {
  hwc_context_t* context = reinterpret_cast<hwc_context_t*>(dev);
  delete context;
  return 0;
}

static int hwc_device_open(const hw_module_t* module, const char* name,
                           hw_device_t** device) {
  arc::PluginHandle handle;
  if (!handle.GetRenderer() || !handle.GetRenderer()->GetCompositor()) {
    return -ENODEV;
  }

  int status = -EINVAL;
  if (!strcmp(name, HWC_HARDWARE_COMPOSER)) {
    arc::RendererInterface::RenderParams params;
    handle.GetRenderer()->GetRenderParams(&params);

    const int density = GetDisplayDensity();
    hwc_context_t* dev = new hwc_context_t();
    dev->device.common.tag = HARDWARE_DEVICE_TAG;
    dev->device.common.version = HWC_DEVICE_API_VERSION_1_2;
    dev->device.common.module = const_cast<hw_module_t*>(module);
    dev->device.common.close = hwc_device_close;
    dev->device.prepare = hwc_prepare;
    dev->device.set = hwc_set;
    dev->device.eventControl = hwc_event_control;
    dev->device.blank = hwc_blank;
    dev->device.query = hwc_query;
    dev->device.getDisplayConfigs = hwc_get_display_configs;
    dev->device.getDisplayAttributes = hwc_get_display_attributes;
    dev->device.registerProcs = hwc_register_procs;
    dev->compositor = handle.GetRenderer()->GetCompositor();
    dev->width = params.width;
    dev->height = params.height;
    // TODO(crbug.com/459280): Get this information from the RenderParams.
    dev->refresh =
        static_cast<int32_t>(1e9 / arc::Options::GetInstance()->fps_limit);
    dev->xdpi = density;
    dev->ydpi = density;
    *device = &dev->device.common;
    status = 0;
  }
  return status;
}

static hw_module_methods_t hwc_module_methods = {
  // TODO(crbug.com/365178): Switch to ".member = value" style.
  open : hwc_device_open
};

hwc_module_t HAL_MODULE_INFO_SYM = {
  // TODO(crbug.com/365178): Switch to ".member = value" style.
  common : {
    tag : HARDWARE_MODULE_TAG,
    version_major : 1,
    version_minor : 0,
    id : HWC_HARDWARE_MODULE_ID,
    name : "Hardware Composer Module",
    author: "chromium.org",
    methods : &hwc_module_methods,
  }
};
