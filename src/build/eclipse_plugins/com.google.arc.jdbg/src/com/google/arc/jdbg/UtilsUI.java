// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package com.google.arc.jdbg;

import org.eclipse.swt.SWT;
import org.eclipse.swt.layout.GridData;
import org.eclipse.swt.layout.GridLayout;
import org.eclipse.swt.widgets.Button;
import org.eclipse.swt.widgets.Combo;
import org.eclipse.swt.widgets.Composite;
import org.eclipse.swt.widgets.Group;
import org.eclipse.swt.widgets.Label;
import org.eclipse.swt.widgets.Layout;
import org.eclipse.swt.widgets.Text;

/**
 * Helpers for UI controls creation/manipulation.
 */
public class UtilsUI {
  public static Group createGroup(Composite parent, String caption,
      int columncnt, int hspan, int gdflags) {
    Group group = new Group(parent, SWT.NONE);
    group.setLayout(new GridLayout(columncnt, false));
    group.setText(caption);
    group.setFont(parent.getFont());
    GridData gd = new GridData(gdflags);
    gd.horizontalSpan = hspan;
    group.setLayoutData(gd);
    return group;
  }

  public static Button createCheckButton(Composite parent, String label,
      boolean checked, int hspan) {
    Button button = new Button(parent, SWT.CHECK);
    button.setFont(parent.getFont());
    button.setSelection(checked);
    button.setText(label);
    GridData gd = new GridData();
    gd.horizontalSpan = hspan;
    button.setLayoutData(gd);
    return button;
  }

  public static Combo createCombo(Composite parent, int style, int hspan,
      int fill, String[] items) {
    Combo c = new Combo(parent, style);
    c.setFont(parent.getFont());
    GridData gd = new GridData(fill);
    gd.horizontalSpan = hspan;
    c.setLayoutData(gd);
    if (items != null) {
      c.setItems(items);
    }
    c.setVisibleItemCount(30);
    c.select(0);
    return c;
  }

  public static Composite createComposite(Composite parent, int columns,
      int hspan, int fill) {
    Composite g = new Composite(parent, SWT.NONE);
    g.setLayout(new GridLayout(columns, false));
    g.setFont(parent.getFont());
    GridData gd = new GridData(fill);
    gd.horizontalSpan = hspan;
    g.setLayoutData(gd);
    return g;
  }

  public static Text createText(Composite parent, int fill, int width) {
    Text text = new Text(parent, SWT.SINGLE | SWT.BORDER);
    text.setFont(parent.getFont());
    GridData gd = new GridData(fill);
    gd.horizontalSpan = 1;
    if (width > 0)
      gd.minimumWidth = gd.widthHint = width;
    text.setLayoutData(gd);
    return text;
  }

  public static Label createLabel(Composite parent, String text) {
    Label lbl = new Label(parent, 0);
    lbl.setFont(parent.getFont());
    lbl.setText(text);
    GridData gd = new GridData(0);
    gd.horizontalSpan = 1;
    lbl.setLayoutData(gd);
    return lbl;
  }

  public static Button createPushButton(
      Composite parent, String text, int width) {
    Button button = new Button(parent, SWT.PUSH);
    button.setFont(parent.getFont());
    button.setText(text);
    GridData gd = new GridData();
    if (width > 0)
      gd.minimumWidth = gd.widthHint = width;
    button.setLayoutData(gd);
    return button;
  }

  public static void createVerticalSpacer(Composite parent, int numlines) {
    Label lbl = new Label(parent, SWT.NONE);
    GridData gd = new GridData(GridData.FILL_HORIZONTAL);
    Layout layout = parent.getLayout();
    if (layout instanceof GridLayout) {
      gd.horizontalSpan = ((GridLayout) parent.getLayout()).numColumns;
    }
    gd.heightHint = numlines;
    lbl.setLayoutData(gd);
  }
}
