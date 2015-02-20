// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * @fileoverview
 *
 * Bypass security restriction to show git change logs in perf dashboard.
 * Gerrit git log viewer (*.googlesource.com) emits
 * 'X-Frame-Options: SAMEORIGIN' (actually a default header from XFE/GSE),
 * so that iframe'ing change log in the perf dashboard won't work.
 *
 * Ideally X-F-O should be able to be removed from server side, since the page
 * doesn't have clickable link for clickjacking.  But security folks are
 * conservative and suggest to only remove X-F-O for specific projects but not
 * all.  It adds complexity to Gerrit code base, thus we do this in extension,
 * which team members would have installed.  Otherwise, perf dashboard user
 * will need to open the iframe in a new tab manually.
 */

function isSignInRequired(info) {
  if (info.statusLine.indexOf('302 Moved Temporarily') < 0)
    return false;
  var headers = info.responseHeaders;
  var kUrl = 'https://www.google.com/accounts/ServiceLogin';
  for (var i = 0; i < headers.length; ++i) {
    if (headers[i].name.toLowerCase() === 'location' &&
        headers[i].value.indexOf(kUrl) == 0)
      return true;
  }
  return false;
}

chrome.webRequest.onHeadersReceived.addListener(function(info) {
  // If 302 on chrome-internal.googlesource.com/arc/arc,
  if (isSignInRequired(info)) {
    // GAIA authentication cannot be done inside iframe.
    var options = {
      type: 'basic',
      iconUrl: 'lock.png',
      title: 'Sign required',
      message: 'Sign in to chrome-internal.googlesource.com, then come back.'
    };
    chrome.notifications.create('chrome-internal', options, function() {});
    window.open('https://chrome-internal.googlesource.com/arc/arc/');
    return;
  }

  var headers = info.responseHeaders;
  for (var i = 0; i < headers.length; ++i) {
    if (headers[i].name.toLowerCase() === 'x-frame-options') {
      headers.splice(i, 1);
      break;
    }
  }
  return {responseHeaders: headers};
}, {
  urls: ['https://chrome-internal.googlesource.com/arc/arc/*'],
  types: ['sub_frame']
}, ['responseHeaders', 'blocking']);
