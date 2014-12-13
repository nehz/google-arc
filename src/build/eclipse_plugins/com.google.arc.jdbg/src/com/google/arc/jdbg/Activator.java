// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.arc.jdbg;

import org.eclipse.core.runtime.Status;
import org.eclipse.jface.resource.ImageDescriptor;
import org.eclipse.ui.plugin.AbstractUIPlugin;
import org.osgi.framework.BundleContext;

/**
 * The activator class controls the plug-in life cycle
 */
public class Activator extends AbstractUIPlugin {

  // The plug-in ID.
  public static final String mPluginID = "com.google.arc.jdbg"; //$NON-NLS-1$

  // The shared instance.
  private static Activator mPlugin;

  // Net commander to receive external commands.
  private NetCommander mCommander;

  public Activator() {
  }

  static void logError(Throwable e) {
    if (mPlugin == null) {
      e.printStackTrace();
    } else {
      mPlugin.getLog().log(
          new Status(Status.ERROR, mPluginID, Status.ERROR, e.getMessage(), e));
    }
  }

  @Override
  public void start(BundleContext context) throws Exception {
    super.start(context);
    mPlugin = this;

    // Create and activate commander on plugin start.
    // Note current plugin is marked as load on startup.
    mCommander = new NetCommander();
    mCommander.start();
  }

  @Override
  public void stop(BundleContext context) throws Exception {
    // Stop commander if it exists
    if (mCommander != null) {
      mCommander.stopCommander();
      mCommander = null;
    }
    mPlugin = null;
    super.stop(context);
  }

  /**
   * Returns the shared instance.
   *
   * @return the shared instance
   */
  public static Activator getDefault() {
    return mPlugin;
  }

  /**
   * Returns an image descriptor for the image file at the given plug-in
   * relative path.
   *
   * @param path the path
   * @return the image descriptor
   */
  public static ImageDescriptor getImageDescriptor(String path) {
    return imageDescriptorFromPlugin(mPluginID, path);
  }
}
