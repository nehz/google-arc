// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.arc.jdbg;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.StringTokenizer;

import org.eclipse.core.runtime.CoreException;
import org.eclipse.debug.core.DebugPlugin;
import org.eclipse.debug.core.ILaunchConfiguration;
import org.eclipse.debug.core.ILaunchConfigurationType;
import org.eclipse.debug.core.ILaunchConfigurationWorkingCopy;
import org.eclipse.debug.core.ILaunchManager;
import org.eclipse.debug.ui.DebugUITools;
import org.eclipse.swt.widgets.Display;
import org.eclipse.ui.PlatformUI;
import org.eclipse.ui.WorkbenchException;

/**
 * This class provides functionality of receiving commands to start debugging
 * via unix domain socket. Its main cycle runs in separate thread.
 */
public class NetCommander extends Thread {
  private Process mNcProcess = null;
  private InputStream mNcProcessStream = null;
  private final Object mNcProcessLock = new Object();
  private boolean mStopRequest = false;

  /**
   * Stop commander. If currently listening incoming command close
   * communication stream.
   */
  public synchronized void stopCommander() {
    if (isAlive()) {
      try {
        synchronized (mNcProcessLock) {
          mStopRequest = true;
          if (mNcProcessStream != null) {
            try {
              mNcProcessStream.close();
            } catch (IOException e) {
              Activator.logError(e);
            }
          }
          if (mNcProcess != null) {
            // This breaks waiting for process input at thread loop
            mNcProcess.destroy();
          }
        }
        join();
      } catch (InterruptedException e) {
        Activator.logError(e);
      }
    }
  }

  /**
   * Launch ARC remote debugger based on received command.
   */
  private static class Launcher extends Thread {
    private final String mCmdToProcess;

    public Launcher(String cmd) {
      mCmdToProcess = cmd;
    }

    @Override
    public void run() {
      try {
        StringTokenizer st = new StringTokenizer(mCmdToProcess, ":");
        if (st.countTokens() != 4) {
          throw new IOException("Invalid cmd: " + mCmdToProcess);
        }

        String project = st.nextToken();
        String hostName = st.nextToken();
        String port = st.nextToken();
        String timeout = st.nextToken();

        ILaunchManager manager = DebugPlugin.getDefault().getLaunchManager();
        String cfg_name = project + "_" + hostName + "_" + port;
        cfg_name = cfg_name.replace('/', '_');
        ILaunchConfigurationType type = manager.
            getLaunchConfigurationType("com.google.arc.jdbg.remoteconnect");
        ILaunchConfigurationWorkingCopy workingCopy = type.newInstance(null,
            cfg_name);

        workingCopy.setAttribute(Constants.KEY_PROJECT, project);
        workingCopy.setAttribute(Constants.KEY_CONNECTOR_HOST, hostName);
        workingCopy.setAttribute(Constants.KEY_CONNECTOR_PORT, port);
        workingCopy.setAttribute(Constants.KEY_CONNECT_TIMEOUT, timeout);
        workingCopy.setAttribute(Constants.KEY_ALLOW_TERMINATE, true);

        ILaunchConfiguration configuration = workingCopy.doSave();

        DebugUITools.launch(configuration, ILaunchManager.DEBUG_MODE);

        // Switch eclipse to debug perspective automatically
        Display.getDefault().syncExec(new Runnable() {
          public void run() {
            try {
              PlatformUI.getWorkbench().showPerspective(
                  "org.eclipse.debug.ui.DebugPerspective",
                  PlatformUI.getWorkbench().getActiveWorkbenchWindow());
            } catch (WorkbenchException e) {
              Activator.logError(e);
            }
          }
        });

      } catch (IOException e) {
        Activator.logError(e);
      } catch (CoreException e) {
        Activator.logError(e);
      }
    }
  }

  @Override
  public void run() {
    try {
      while (true) {
        synchronized (mNcProcessLock) {
          if (mStopRequest) {
            break;
          }

          // Use unix domain socket for communication.
          String[] args = new String[] { "nc", "-l", "-U",
              "/tmp/google-arc-dbg-remoteconnect" };
          ProcessBuilder pb = new ProcessBuilder(args);
          mNcProcess = pb.start();
          mNcProcessStream = mNcProcess.getInputStream();
        }
        BufferedReader br = new BufferedReader(new InputStreamReader(
            mNcProcessStream));
        // This puts thread to waiting state until next command is received
        // or stopCommander destroys the process.
        String cmd = br.readLine();
        if (cmd != null) {
          (new Launcher(cmd)).start();
        }
      }
    } catch (IOException e) {
      Activator.logError(e);
    }
  }
}
