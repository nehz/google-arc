// Copyright 2015 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const LOG_BASE_URL = 'https://chrome-internal.googlesource.com/arc/arc/+log/' +
                     'arc-runtime-';
const CRASH_BASE_URL = 'https://arc-omahaproxy.googleplex.com/crashlookup' +
                       '?version=';
const ARC_VERSION_COLUMN_MATCH = 'arc_version';

// Creates a replacement element for the td content we are replacing,
// it will be equivalent to: <span>$version (<a>log</a>) (<a>crashes</a>)</span>
function createModifiedVersionContainer(version) {
  var span = document.createElement('span');
  var log_a = document.createElement('a');
  log_a.setAttribute('href', LOG_BASE_URL + version);
  log_a.setAttribute('target', '_blank');
  log_a.appendChild(document.createTextNode('log'));
  var crash_a = document.createElement('a');
  crash_a.setAttribute('href', CRASH_BASE_URL + version);
  crash_a.setAttribute('target', '_blank');
  crash_a.appendChild(document.createTextNode('crashes'));


  span.appendChild(document.createTextNode(version));
  span.appendChild(document.createTextNode(' ('));
  span.appendChild(log_a);
  span.appendChild(document.createTextNode(') ('));
  span.appendChild(crash_a);
  span.appendChild(document.createTextNode(')'));
  return span;
}

function showLogAndCrashLinks() {
  var i;
  // Looks like
  // <thead id="columns">
  //   <tr>
  //     <td>os</td>
  //     ...
  //     <td>arc_version</td>
  //     <td>prev_arc_version</td>
  //     ...
  //   </tr>
  // </thead>
  var columns = document.getElementById('columns');
  var column_nodes = [];
  if (columns && columns.children.length > 0)
    column_nodes = columns.children[0].children;
  else
    // The table is populated from the result of an XHR, so it will not be ready
    // immediately.  Spin until it is.
    // TODO(crbug.com/460322): We should request DOM update events instead.
    setTimeout(showLogAndCrashLinks, 100);
  var indices_to_modify = [];
  for (i = 0; i < column_nodes.length; i++) {
    if (column_nodes[i].innerText.indexOf(ARC_VERSION_COLUMN_MATCH) > -1)
      indices_to_modify.push(i);
  }

  // Looks like:
  // <tbody id="rows">
  //   <tr>
  //     <td>cros</td>
  //     ...
  //     <td>40.4410.184.31</td> <-- we will replace these version nodes
  //     <td>40.4410.184.29</td>
  //     ...
  //  </tr>
  //  <tr>
  //    <td>win</td>
  //    ...
  //  </tr>
  // </tbody>
  var rows = document.getElementById('rows');
  var row_nodes = [];
  if (rows)
    row_nodes = rows.children;
  var version;
  var elem_to_modify;
  for (i = 0; i < row_nodes.length; i++) {
    for (j = 0; j < indices_to_modify.length; j++) {
      elem_to_modify = row_nodes[i].children[indices_to_modify[j]];
      version = elem_to_modify.innerText;
      elem_to_modify.innerHTML = '';
      elem_to_modify.appendChild(createModifiedVersionContainer(version));
    }
  }
}

showLogAndCrashLinks();
