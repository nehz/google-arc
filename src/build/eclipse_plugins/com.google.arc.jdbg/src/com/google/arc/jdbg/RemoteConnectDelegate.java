// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.arc.jdbg;

import java.io.File;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

import org.eclipse.core.runtime.CoreException;
import org.eclipse.core.runtime.IProgressMonitor;
import org.eclipse.core.runtime.NullProgressMonitor;
import org.eclipse.debug.core.ILaunch;
import org.eclipse.debug.core.ILaunchConfiguration;
import org.eclipse.debug.core.model.IDebugTarget;
import org.eclipse.debug.core.model.ISourceLocator;
import org.eclipse.debug.core.sourcelookup.ISourceContainer;
import org.eclipse.debug.core.sourcelookup.ISourceLookupDirector;
import org.eclipse.debug.core.sourcelookup.containers.DirectorySourceContainer;
import org.eclipse.jdt.launching.AbstractJavaLaunchConfigurationDelegate;
import org.eclipse.jdt.launching.IJavaLaunchConfigurationConstants;
import org.eclipse.jdt.launching.IVMConnector;
import org.eclipse.jdt.launching.JavaRuntime;

import com.google.system.SourceRootBuilder;

/**
 * This class handle launch requests that refer to ARC remote debugging.
 */
public class RemoteConnectDelegate extends
    AbstractJavaLaunchConfigurationDelegate {

  @Override
  public void launch(ILaunchConfiguration configuration, String mode,
      ILaunch launch, IProgressMonitor monitor) throws CoreException {
    if (monitor == null) {
      monitor = new NullProgressMonitor();
    }

    monitor.beginTask("Connecting to ARC jdb: " + configuration.getName(), 4);
    // check for cancellation
    if (monitor.isCanceled()) {
      return;
    }
    try {
      monitor.subTask("Validating launch parameters");

      IVMConnector connector = JavaRuntime.getVMConnector(
          IJavaLaunchConfigurationConstants.ID_SOCKET_ATTACH_VM_CONNECTOR);
      if (connector == null) {
        abort("Connector is not available", null,
            IJavaLaunchConfigurationConstants.ERR_CONNECTOR_NOT_AVAILABLE);
      }

      String arcProj = configuration.getAttribute(Constants.KEY_PROJECT,
          (String)null);
      if (arcProj == null) {
        abort("ARC project root is not set", null, -100);
      }
      File root = new File(arcProj);
      if (!root.isDirectory()) {
        abort("ARC root '" + root.getAbsolutePath() + "' does not exist", null,
            -101);
      }

      Map<String, String> argMap = new HashMap<String, String>();
      String hostname = configuration.getAttribute(
          Constants.KEY_CONNECTOR_HOST, "localhost");
      String port = configuration.getAttribute(
          Constants.KEY_CONNECTOR_PORT, "8000");
      argMap.put("hostname", hostname);
      argMap.put("port", port);
      argMap.put("timeout", "20000");

      // check for cancellation
      if (monitor.isCanceled()) {
        return;
      }

      monitor.worked(1);

      monitor.subTask("Waiting for port to be opened");

      String waitTimeout = configuration.
          getAttribute(Constants.KEY_CONNECT_TIMEOUT, (String) null);
      if (waitTimeout != null) {
        long waitMs = 0;
        try {
          waitMs = 1000 * Integer.parseInt(waitTimeout);
        } catch(NumberFormatException e) {
        }

        long endTime = System.currentTimeMillis() + waitMs;
        while (System.currentTimeMillis() < endTime) {
          if (monitor.isCanceled()) {
            return;
          }
          try {
            ProcessBuilder pb = new ProcessBuilder(
                new String[] {"nc", "-z", hostname, port});
            Process ncProcess = pb.start();
            int retCode = ncProcess.waitFor();
            if (retCode == 0)
              break;
            Thread.sleep(1000);
          } catch (Throwable e) {
            Activator.logError(e);
            break;
          }
        }
      }

      monitor.worked(1);

      monitor.subTask("Preparing source folders");
      // set the default source locator if required
      setDefaultSourceLocator(launch, configuration);

      ISourceLocator slocator = launch.getSourceLocator();
      if (slocator != null && slocator instanceof ISourceLookupDirector) {
        // Set additional source root folder based on out/staging structure
        ISourceLookupDirector slocatordir = (ISourceLookupDirector) slocator;
        ISourceContainer[] containersold = slocatordir.getSourceContainers();

        String[] sources = null;
        try {
          sources = SourceRootBuilder.buildRoot(arcProj + "/out/staging");
        } catch (IOException e) {
          abort("Cannot resolve java source roots: " + e.toString(), null,
              -101);
        }

        ISourceContainer[] containersnew = new ISourceContainer[
            containersold.length + sources.length];
        System.arraycopy(containersold, 0, containersnew, 0,
            containersold.length);

        for (int i = 0; i < sources.length; ++i) {
          File file = new File(root, "/out/staging/" + sources[i]);
          DirectorySourceContainer c =
              new DirectorySourceContainer(file, false);
          containersnew[containersold.length + i] = c;
        }
        slocatordir.setSourceContainers(containersnew);
      }

      monitor.worked(1);

      // connect to remote VM.
      connector.connect(argMap, monitor, launch);

      // check for cancellation.
      if (monitor.isCanceled()) {
        IDebugTarget[] debugTargets = launch.getDebugTargets();
        for (int i = 0; i < debugTargets.length; i++) {
          IDebugTarget target = debugTargets[i];
          if (target.canDisconnect()) {
            target.disconnect();
          }
        }
        return;
      }
    } finally {
      monitor.done();
    }
  }
}
