// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.system;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;

/**
 * This is utility class to build roots of Java sources. It accepts root folder
 * and produces array of roots that can be used to resolve sources for Java
 * classes.
 */
public class SourceRootBuilder {
  public static String[] buildRoot(String rootFolder) throws IOException {
    BufferedReader fileReader = null;
    try {
      ProcessBuilder pb = new ProcessBuilder(new String[] {
          "find",
          rootFolder,
          "-name", "*.java"
      });

      Process process = pb.start();
      BufferedReader reader = new BufferedReader(
          new InputStreamReader(process.getInputStream()));

      if (!rootFolder.endsWith("/")) {
        rootFolder += "/";
      }
      int rootFolderLength = rootFolder.length();
      ArrayList<String> sourceRoots = new ArrayList<String>();
      while (true) {
        String javaFile = reader.readLine();
        if (javaFile == null) {
          break; // Reach end
        }
        // System.out.println(javaFile);

        fileReader = new BufferedReader(new FileReader(javaFile));

        boolean found = false; // Package declaration was found
        while (true) {
          String line = fileReader.readLine();
          if (line == null) {
            break;  // EOF
          }
          line = line.trim();
          if (!line.startsWith("package")) {
            continue;
          }
          line = line.substring(7);
          if (!line.startsWith(" ") && !line.startsWith("\t")) {
            continue;
          }
          line = line.trim();
          int endIdx = line.indexOf(';');
          if (endIdx <= 0) {
            continue;
          }
          String packageName = line.substring(0, endIdx).trim();
          String ending = "/" + packageName.replace('.', '/');
          String javaPackage = javaFile.substring(
              0, javaFile.lastIndexOf('/'));
          if (javaPackage.endsWith(ending)) {
            String sourceRoot = javaPackage.substring(
                0, javaPackage.length() - ending.length());
            sourceRoot = sourceRoot.substring(rootFolderLength);
            if (!sourceRoots.contains(sourceRoot)) {
              sourceRoots.add(sourceRoot);
            }
          } else {
            System.err.println("Cannot process: " + javaFile);
            System.err.println("\t" + line);
            System.err.println("\t" + javaPackage);
            System.err.println("\t" + packageName);
          }
          found = true;
          break;
        }

        if (!found) {
          System.err.println("Package is not found at: " + javaFile);
        }
      }

      return sourceRoots.toArray(new String[sourceRoots.size()]);
    } finally {
      if (fileReader != null) {
        fileReader.close();
      }
    }
  }

  public static void main(String[] args) {
    if (args.length != 1) {
      System.err.println("Please provide root folder as argument");
      return;
    }
    try {
      String[] roots = buildRoot(args[0]);
      for (int i = 0; i < roots.length; ++i)
        System.out.println(roots[i]);
    } catch (IOException e) {
      e.printStackTrace();
    }
  }
}
