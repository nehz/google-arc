// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.arc.jdbg;

import org.eclipse.debug.ui.AbstractLaunchConfigurationTabGroup;
import org.eclipse.debug.ui.CommonTab;
import org.eclipse.debug.ui.ILaunchConfigurationDialog;
import org.eclipse.debug.ui.ILaunchConfigurationTab;
import org.eclipse.debug.ui.sourcelookup.SourceLookupTab;

/**
 * Root configuration for UI ARC remote connect configuration.
 */
public class RemoteConnectTabGroup extends AbstractLaunchConfigurationTabGroup {
  public void createTabs(ILaunchConfigurationDialog dialog, String mode) {
    ILaunchConfigurationTab[] tabs = new ILaunchConfigurationTab[] {
        new RemoteConnectTab(), new SourceLookupTab(), new CommonTab()};
    setTabs(tabs);
  }
}
