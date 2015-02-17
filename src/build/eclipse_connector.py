# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Provides functionality to connect to external eclipse framework
# in order to debug java code.

import os
import subprocess
import time

# Activates and connect debugger at Eclipse IDE. It also checks if
# Eclipse exists and properly configured.


def connect_eclipse_debugger(port):
  devnull = open('/dev/null', 'w')
  # Touching unix domain port is to resolve the problem when the system keeps
  # port in case Eclipse was not closed normally using an exit command. In this
  # case, sending command to unix domain socket may not return error.
  netcmd = "nc -z -U /tmp/google-arc-dbg-remoteconnect"
  subprocess.call(netcmd, shell=True, stdout=devnull, stderr=devnull)
  # check if we can pass command to command port which can be opened if
  # eclipse with helper plugin com.google.arc.jdbg loaded. Command being sent
  # to eclipse command port has format
  #     arc_project:host_name:port:timeout_to_connect.
  netcmd = "echo \"" + os.getcwd() + ":localhost:" + str(port) + ":20\" "\
           "| nc -U /tmp/google-arc-dbg-remoteconnect"
  if (subprocess.call(netcmd, shell=True, stdout=devnull, stderr=devnull) == 0):
    # Nothing to do else. We have passed command successfully.
    return True

  # Running eclipse with plugin was not found. locate it.
  if (subprocess.call("which eclipse", shell=True,
                      stdout=devnull, stderr=devnull) != 0):
    print "Unable to locate Eclipse IDE on your machine. You may\n"\
          "automatically install it: sudo apt-get install eclipse.\n"\
          "Alternatively you may download latest version from\n"\
          "http://www.eclipse.org/downloads/. Please note, that eclipse\n"\
          "comes in different packages and you need one that includes java\n"\
          "development support. After manual installation make sure that you\n"\
          "added eclipse into path environment variable."
    return False

  # Start eclipse and specify our folder that contains compiled plugin to load.
  eclipsecmd = "eclipse -vmargs "\
               "-Dorg.eclipse.equinox.p2.reconciler.dropins.directory=" + \
               os.getcwd() + "/canned/host/bin/eclipse_plugins"
  process = subprocess.Popen(eclipsecmd, shell=True,
                             stdout=devnull, stderr=devnull)

  # Make sure process started. Note python 2.7 does not support
  # communicate with timeouts, so use loop to check process status.
  # In first 30 seconds we wait with no user interaction and after
  # we ask user confirmation to continue waiting.
  i = 0
  trycnt = 15
  while True:
    if i < trycnt:
      time.sleep(2)
    process.poll()
    if process.returncode is not None:
      if process.returncode == 0:
        print "Eclipse was normally closed. Cannot continue."
      else:
        print "Failed to launch Eclipse IDE. Make sure it is installed "\
              "correctly. Cannot continue."
      return False
    if (subprocess.call(netcmd, shell=True, stdout=devnull, stderr=devnull)
        == 0):
      # We successfully passed command to attach debugger.
      return True
    if i >= trycnt:
      print "Eclipse is not responding. Make sure it is not waiting with a "\
            "modal dialog. Would you like to retry?"
      while True:
        ans = raw_input("y/n: ")
        if not ans:
          break
        if ans not in ['y', 'Y', 'n', 'N']:
          print 'please enter y or n.'
          continue
        if ans == 'y' or ans == 'Y':
          break
        if ans == 'n' or ans == 'N':
          return False

    i = i + 1
  return False
