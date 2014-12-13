// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.arc.jdbg;

import java.io.File;
import java.net.URI;
import java.net.URISyntaxException;

import org.eclipse.core.runtime.CoreException;
import org.eclipse.debug.core.ILaunchConfiguration;
import org.eclipse.debug.core.ILaunchConfigurationWorkingCopy;
import org.eclipse.jdt.debug.ui.launchConfigurations.JavaLaunchTab;
import org.eclipse.jface.util.IPropertyChangeListener;
import org.eclipse.jface.util.PropertyChangeEvent;
import org.eclipse.swt.events.ModifyEvent;
import org.eclipse.swt.events.ModifyListener;
import org.eclipse.swt.events.SelectionEvent;
import org.eclipse.swt.events.SelectionListener;
import org.eclipse.swt.layout.GridData;
import org.eclipse.swt.widgets.Button;
import org.eclipse.swt.widgets.Composite;
import org.eclipse.swt.widgets.DirectoryDialog;
import org.eclipse.swt.widgets.Display;
import org.eclipse.swt.widgets.Group;
import org.eclipse.swt.widgets.Text;

/**
 * Provide UI Tab that contains parameter essential for ARC debug connection.
 */
public class RemoteConnectTab extends JavaLaunchTab implements
    IPropertyChangeListener {
  private Text mProjText;
  private Button mProjButton;
  private Text mConHost;
  private Text mConPort;
  private Button mAllowTerminateButton;
  private WidgetListener mListener;

  /**
   * A listener which handles widget change events for the controls in this tab.
   */
  private class WidgetListener implements ModifyListener, SelectionListener {
    public void modifyText(ModifyEvent e) {
      updateLaunchConfigurationDialog();
    }

    public void widgetDefaultSelected(SelectionEvent e) {/* do nothing */
    }

    public void widgetSelected(SelectionEvent e) {
      Object source = e.getSource();
      if (source == mProjButton) {
        DirectoryDialog dialog = new DirectoryDialog(Display.getDefault()
            .getActiveShell());
        String result = dialog.open();
        if (result != null) {
          mProjText.setText(result);
        }
      }
    }
  }

  public RemoteConnectTab() {
    mListener = new WidgetListener();
  }

  @Override
  public void createControl(Composite parent) {
    Composite comp = UtilsUI.createComposite(parent, 1, 1, GridData.FILL_BOTH);

    UtilsUI.createVerticalSpacer(comp, 1);

    Group group = UtilsUI.createGroup(comp, "ARC Project Location", 2, 1,
        GridData.FILL_HORIZONTAL);

    mProjText = UtilsUI.createText(group, GridData.FILL_HORIZONTAL, 300);
    mProjText.addModifyListener(mListener);

    mProjButton = UtilsUI.createPushButton(group, "&Browse...", 90);
    mProjButton.addSelectionListener(mListener);

    UtilsUI.createVerticalSpacer(comp, 1);

    group = UtilsUI.createGroup(comp, "Connection", 2, 1,
        GridData.FILL_HORIZONTAL);

    UtilsUI.createLabel(group, "Host: ");
    mConHost = UtilsUI.createText(group, 0, 150);
    mConHost.addModifyListener(mListener);

    UtilsUI.createLabel(group, "Port: ");
    mConPort = UtilsUI.createText(group, 0, 150);
    mConPort.addModifyListener(mListener);

    UtilsUI.createVerticalSpacer(comp, 1);

    mAllowTerminateButton = UtilsUI.createCheckButton(comp,
        "&Allow termination of remote VM", false, 1);
    mAllowTerminateButton.addSelectionListener(mListener);

    setControl(comp);
  }

  private String getProjectLocation() {
    return mProjText.getText().trim();
  }

  private String getConnectorHost() {
    return mConHost.getText().trim();
  }

  private String getConnectorPort() {
    return mConPort.getText().trim();
  }

  @Override
  public boolean isValid(ILaunchConfiguration config) {
    // No error message means that we can proceed next (Debug).
    // If any error is set that means Debug button is grayed.
    setErrorMessage(null);
    setMessage(null);
    String name = getProjectLocation();
    if (name.length() > 0) {
      File file = new File(name);
      if (!file.exists() || !file.isDirectory()) {
        setErrorMessage("Invalid ARC Project location: " + name);
      } else {
        try {
          URI testUri = new URI("http", null, getConnectorHost(),
              Integer.parseInt(getConnectorPort()), null, null, null);
          if (testUri.getHost() == null)
            throw new URISyntaxException("", "");
        } catch (NumberFormatException ne) {
          setErrorMessage("Invalid connection: " + getConnectorHost() + ":"
              + getConnectorPort());
        } catch (URISyntaxException e) {
          setErrorMessage("Invalid connection: " + getConnectorHost() + ":"
              + getConnectorPort());
        }
      }
    } else {
      setErrorMessage("ARC Project location is not specified");
    }

    return true;
  }

  @Override
  public void setDefaults(ILaunchConfigurationWorkingCopy configuration) {
  }

  /**
   * Fill controls from configuration file
   *
   * @param configuration
   */
  private void updateProjectFromConfig(ILaunchConfiguration configuration) {
    try {
      mProjText.setText(configuration.getAttribute(Constants.KEY_PROJECT, ""));
      mConHost.setText(configuration.getAttribute(Constants.KEY_CONNECTOR_HOST,
          "localhost"));
      mConPort.setText(configuration.getAttribute(Constants.KEY_CONNECTOR_PORT,
          "8000"));
      mAllowTerminateButton.setSelection(configuration.getAttribute(
          Constants.KEY_ALLOW_TERMINATE, false));
    } catch (CoreException e) {
      setErrorMessage(e.getStatus().getMessage());
    }
  }

  @Override
  public void initializeFrom(ILaunchConfiguration configuration) {
    updateProjectFromConfig(configuration);
    super.initializeFrom(configuration);
  }

  @Override
  public void performApply(ILaunchConfigurationWorkingCopy configuration) {
    configuration.setAttribute(Constants.KEY_PROJECT, getProjectLocation());
    configuration.
        setAttribute(Constants.KEY_CONNECTOR_HOST, getConnectorHost());
    configuration.
        setAttribute(Constants.KEY_CONNECTOR_PORT, getConnectorPort());
    configuration.setAttribute(Constants.KEY_ALLOW_TERMINATE,
        mAllowTerminateButton.getSelection());
  }

  @Override
  public String getName() {
    return "ARC Connect";
  }

  @Override
  public void propertyChange(PropertyChangeEvent event) {
    updateLaunchConfigurationDialog();
  }
}
