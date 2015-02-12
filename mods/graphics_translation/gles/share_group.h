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
#ifndef GRAPHICS_TRANSLATION_GLES_SHARE_GROUP_H_
#define GRAPHICS_TRANSLATION_GLES_SHARE_GROUP_H_

#include <map>
#include <utility>

#include "graphics_translation/gles/buffer_data.h"
#include "graphics_translation/gles/framebuffer_data.h"
#include "graphics_translation/gles/mutex.h"
#include "graphics_translation/gles/program_data.h"
#include "graphics_translation/gles/renderbuffer_data.h"
#include "graphics_translation/gles/shader_data.h"
#include "graphics_translation/gles/texture_data.h"

class GlesContext;
class NamespaceImpl;

// The ShareGroup manages the names and objects associated with a GLES context.
// Instances of this class can be shared between multiple contexts.
// (Specifically, when a context is created, a shared context can also be
// set, in which case both contexts will "share" this share group.)  All
// operations on this class are serialized through a lock so it is thread safe.
// Though most of the functions (ex. GenName) can operate on any object type,
// only a specific subset of the functionality is made public by explicitly
// providing functions for a given type (ex. GenBufferName).  This is to
// allow us to catch problematic usage at compile time rather than asserting
// at runtime.
class ShareGroup {
 public:
  explicit ShareGroup(GlesContext* context);

  // Generates a new object global and local name and returns its local name
  // value.
  void GenBuffers(int n, ObjectLocalName* names) {
    return GenNames(BUFFER, n, names);
  }
  void GenFramebuffers(int n, ObjectLocalName* names) {
    return GenNames(FRAMEBUFFER, n, names);
  }
  void GenRenderbuffers(int n, ObjectLocalName* names) {
    return GenNames(RENDERBUFFER, n, names);
  }
  void GenTextures(int n, ObjectLocalName* names) {
    return GenNames(TEXTURE, n, names);
  }
  void GenPrograms(int n, ObjectLocalName* names) {
    return GenNames(PROGRAM, n, names);
  }
  void GenVertexShaders(int n, ObjectLocalName* names) {
    return GenNames(VERTEX_SHADER, n, names);
  }
  void GenFragmentShaders(int n, ObjectLocalName* names) {
    return GenNames(FRAGMENT_SHADER, n, names);
  }

  // Create an object of the specified type with the given local name.
  BufferDataPtr CreateBufferData(ObjectLocalName name) {
    return GetObject(BUFFER, name, true).Cast<BufferData>();
  }
  FramebufferDataPtr CreateFramebufferData(ObjectLocalName name) {
    return GetObject(FRAMEBUFFER, name, true).Cast<FramebufferData>();
  }
  RenderbufferDataPtr CreateRenderbufferData(ObjectLocalName name) {
    return GetObject(RENDERBUFFER, name, true).Cast<RenderbufferData>();
  }
  TextureDataPtr CreateTextureData(ObjectLocalName name) {
    return GetObject(TEXTURE, name, true).Cast<TextureData>();
  }
  ProgramDataPtr CreateProgramData(ObjectLocalName name) {
    return GetObject(PROGRAM, name, true).Cast<ProgramData>();
  }
  ShaderDataPtr CreateVertexShaderData(ObjectLocalName name) {
    return GetObject(VERTEX_SHADER, name, true).Cast<ShaderData>();
  }
  ShaderDataPtr CreateFragmentShaderData(ObjectLocalName name) {
    return GetObject(FRAGMENT_SHADER, name, true).Cast<ShaderData>();
  }

  // Retrieve the object of the specified type with the given local name.
  BufferDataPtr GetBufferData(ObjectLocalName name) {
    return GetObject(BUFFER, name, false).Cast<BufferData>();
  }
  FramebufferDataPtr GetFramebufferData(ObjectLocalName name) {
    return GetObject(FRAMEBUFFER, name, false).Cast<FramebufferData>();
  }
  RenderbufferDataPtr GetRenderbufferData(ObjectLocalName name) {
    return GetObject(RENDERBUFFER, name, false).Cast<RenderbufferData>();
  }
  TextureDataPtr GetTextureData(ObjectLocalName name) {
    return GetObject(TEXTURE, name, false).Cast<TextureData>();
  }
  ProgramDataPtr GetProgramData(ObjectLocalName name) {
    return GetObject(PROGRAM, name, false).Cast<ProgramData>();
  }
  ShaderDataPtr GetShaderData(ObjectLocalName name) {
    return GetObject(SHADER, name, false).Cast<ShaderData>();
  }

  // Deletes the object of the specified type as well as unregistering its
  // names from the ShareGroup.
  void DeleteBuffers(int n, const ObjectLocalName* names) {
    DeleteObjects(BUFFER, n, names);
  }
  void DeleteFramebuffers(int n, const ObjectLocalName* names) {
    DeleteObjects(FRAMEBUFFER, n, names);
  }
  void DeleteRenderbuffers(int n, const ObjectLocalName* names) {
    DeleteObjects(RENDERBUFFER, n, names);
  }
  void DeleteTextures(int n, const ObjectLocalName* names) {
    DeleteObjects(TEXTURE, n, names);
  }
  void DeletePrograms(int n, const ObjectLocalName* names) {
    // TODO(crbug.com/424353): Keep program name active until the program
    // is actually unused, even if it was marked as deleted.
    DeleteObjects(PROGRAM, n, names);
  }
  void DeleteShaders(int n, const ObjectLocalName* names) {
    DeleteObjects(SHADER, n, names);
  }

  // Retrieves the "global" name of an object or 0 if the object does not exist.
  ObjectGlobalName GetBufferGlobalName(ObjectLocalName local_name) {
    return GetGlobalName(BUFFER, local_name);
  }
  ObjectGlobalName GetFramebufferGlobalName(ObjectLocalName local_name) {
    return GetGlobalName(FRAMEBUFFER, local_name);
  }
  ObjectGlobalName GetRenderbufferGlobalName(ObjectLocalName local_name) {
    return GetGlobalName(RENDERBUFFER, local_name);
  }
  ObjectGlobalName GetTextureGlobalName(ObjectLocalName local_name) {
    return GetGlobalName(TEXTURE, local_name);
  }

  // Maps an object to the specified global named object.  (Note: useful when
  // creating EGLImage siblings).
  void SetTextureGlobalName(ObjectLocalName local_name,
                            ObjectGlobalName global_name) {
    SetGlobalName(TEXTURE, local_name, global_name);
  }

 private:
  typedef std::pair<ObjectType, ObjectLocalName> ObjectID;
  typedef std::map<ObjectID, ObjectDataPtr> ObjectDataMap;

  ~ShareGroup();

  ObjectDataPtr GetObject(ObjectType type, ObjectLocalName name,
                          bool create_if_needed);
  void DeleteObjects(ObjectType type, int n, const ObjectLocalName* names);

  void GenNames(ObjectType type, int n, ObjectLocalName* names);
  ObjectGlobalName GetGlobalName(ObjectType type, ObjectLocalName local_name);
  void SetGlobalName(ObjectType type, ObjectLocalName local_name,
                     ObjectGlobalName global_name);

  ObjectType ValidateType(ObjectType type) const;
  ObjectID GetObjectID(ObjectType type, ObjectLocalName name) const;
  NamespaceImpl* GetNamespace(ObjectType type);

  Mutex lock_;
  NamespaceImpl* namespace_[NUM_OBJECT_TYPES];
  ObjectDataMap objects_;
  GlesContext* context_;

  friend class SmartPtr<ShareGroup>;

  ShareGroup(const ShareGroup&);
  ShareGroup& operator=(const ShareGroup&);
};

typedef SmartPtr<ShareGroup> ShareGroupPtr;

#endif  // GRAPHICS_TRANSLATION_GLES_SHARE_GROUP_H_
