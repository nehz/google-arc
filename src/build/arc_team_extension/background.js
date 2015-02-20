// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/* Watches the buildbot status, updates the UI, and sends notifications as
 * appropriate.
 */


/** @const */
const _UPDATE_INTERVAL = 60000;
const _REQUEST_TIMEOUT = 10000;
const _BADGE_TEXT = 'arc';
const _BADGE_COLOR = [63, 63, 63, 255];
const _BUILDBOT_SERVER = 'http://chromegw.corp.google.com/i/client.arc';
const _BUILDBOT_BUILDER_STATUS_URL = _BUILDBOT_SERVER + '/json/builders/';
const _TREE_STATUS = 'http://arc-tree-status.appspot.com/status';
const _NOTIFY_INTERVAL = 1200000;
const _NOTIFICATION_ID = '1';
const _NUM_BUILDS_TO_LOOK_AT = 5;

// Single global timer for updating the status.
var timer = null;

// We want to notify the user at a change
var last_known_status_icon = 'status-good-unlocked.png';
var last_notification_time = 0;
var last_status_update_time = 0;

// Keep track of notifications so we only show one active at a time.
var last_notification = null;

function sendGetRequest(url, onsuccess, callback) {
  var xhr = new XMLHttpRequest();
  xhr.open('GET', url);
  xhr.timeout = _REQUEST_TIMEOUT;
  xhr.onload = function(e) {
    try {
      var result = onsuccess(xhr.response,
                             xhr.getResponseHeader('content-type'));
      callback(result);
    } catch (err) {
      console.log('Exception: ' + err + ' url=' + url);
      callback();
    }
  };
  xhr.ontimeout = function() {
    console.log('Timeout url=' + url);
    callback();
  };
  xhr.onerror = function(e) {
    console.log('Error url=' + url + ' status=' + xhr.statusText);
    callback();
  };
  xhr.send();
}

function checkTreeStatus(status, callback) {
  sendGetRequest(_TREE_STATUS, function(response) {
    if (response[0] == '0')
      status.treeIsClosed = true;
    else if (response[0] == '1')
      status.treeIsOpen = true;
    return null;
  }, callback);
}

function getBuilders(callback) {
  sendGetRequest(
      _BUILDBOT_BUILDER_STATUS_URL,
      function(response, contentType) {
        if (contentType.indexOf('application/json') == -1) {
          console.log('getBuilders: Invalid content type ' + contentType);
          return null;
        }
        var parsed_response = JSON.parse(response);
        // Specifically only return bots that are marked as tree closers.  We do
        // not want, for instance, the periodic builders to keep us red all day
        // if an overnight build failed.
        var closers = [];
        for (var b in parsed_response) {
          var category = parsed_response[b]['category'];
          if (category) {
            var categories = category.split('|');
            if (categories.indexOf('closer') >= 0)
              closers.push(b);
          }
        }
        return closers;
      },
      callback);
}

function checkBuild(builder, status, buildIndex, callback) {
  // We limit our checks to the last _NUM_BUILDS_TO_LOOK_AT.
  if (buildIndex < -_NUM_BUILDS_TO_LOOK_AT) {
    callback(false);
    return;
  }
  var url = _BUILDBOT_BUILDER_STATUS_URL +
      encodeURIComponent(builder) + '/builds/' + buildIndex;
  sendGetRequest(url, function(response, contentType) {
    if (contentType.indexOf('application/json') == -1) {
      console.log('checkBuild: Invalid content type ' + contentType);
      return false;
    }
    response = JSON.parse(response);
    if (response.currentStep != null) {
      console.log('skipping in progress build for builder "' + builder + '"');
      checkBuild(builder, status, buildIndex - 1, callback);
      return true;  // ignore this callback call
    }
    console.log(response);
    if (response.text && response.text.length >= 2) {
      if (response.text[0] == 'build' &&
          response.text[1] == 'successful') {
        status.good += 1;
      } else {
        status.bad += 1;
      }
    } else {
      status.bad += 1;
    }
    return false;
  }, callback);
}

function checkBuilder(builder, status, callback) {
  // Check the last build and fall back to the build before that if
  // the last build is in progress.
  checkBuild(builder, status, -1, callback);
}

function checkBuildStatus(status, callback) {
  getBuilders(function(builders_to_check) {
    if (!builders_to_check) {
      callback();
      return;
    }
    var builders = builders_to_check.length;
    for (var b in builders_to_check) {
      checkBuilder(builders_to_check[b], status, function(ignore) {
        if (ignore) {
          return;
        }
        builders--;
        if (builders == 0) {
          status.buildIsGreen = status.good == builders_to_check.length;
          status.buildIsRed = (!status.buildIsGreen &&
                               (status.good + status.bad) ==
                                   builders_to_check.length);
          callback();
        }
      });
    }
  });
}

function getCurrentStatus(callback) {
  var status = {
    good: 0,
    bad: 0,
    buildIsGreen: false,
    buildIsRed: false,
    treeIsOpen: false,
    treeIsClosed: false
  };
  checkTreeStatus(status, function() {
    checkBuildStatus(status, function() {
      callback(status);
    });
  });
}

function getIconForStatus(status) {
  var build_state = 'status-unknown';
  var tree_state = 'lock-unknown';

  if (status.buildIsGreen) {
    build_state = 'status-good';
  }
  if (status.buildIsRed) {
    build_state = 'status-bad';
  }

  if (status.treeIsOpen) {
    tree_state = 'unlocked';
  }
  if (status.treeIsClosed) {
    tree_state = 'locked';
  }

  return build_state + '-' + tree_state + '.png';
}

function getNotificationMessageForStatus(status) {
  var build_state = 'Build: UNKNOWN';
  var tree_state = 'Tree: UNKNOWN';

  if (status.buildIsGreen) {
    build_state = 'Build: green';
  }
  if (status.buildIsRed) {
    build_state = 'Build: RED';
  }

  if (status.treeIsOpen) {
    tree_state = 'Tree: open';
  }
  if (status.treeIsClosed) {
    tree_state = 'Tree: CLOSED';
  }

  var timestamp = new Date().toLocaleTimeString();

  // The formatting is limited.  \n, spaces become single space.
  return build_state + ' / ' + tree_state + ' -- ' + timestamp;
}

function isStatusGood(status) {
  return status.buildIsGreen && status.treeIsOpen;
}

function createNotificationNew(status) {
  var options = {
    type: 'basic',
    iconUrl: getIconForStatus(status),
    title: 'ARC Buildbot Watcher',
    message: getNotificationMessageForStatus(status)
  };

  chrome.notifications.create(_NOTIFICATION_ID, options, function() {});
}

// TODO(2013/07/10): Remove this function as webkitNotifications.* is
// deprecated, once chrome.notifications.* is known to be available on
// stable (not currently sure).
function createNotificationOld(status) {
  var notification_template = 'notify_broken.html';
  if (status.buildIsGreen)
    notification_template = 'notify_green.html';

  if (last_notification) {
    last_notification.cancel();
  }
  last_notification =
      webkitNotifications.createHTMLNotification(notification_template);
  last_notification.show();
}

function updateNotifications(status) {
  var good = isStatusGood(status);
  var icon = getIconForStatus(status);

  // If we are good and last notified the user we are good, then there is no
  // reason to notify further.
  if (good && (icon == last_known_status_icon))
    return;

  // If we are not not good and have an unchanged icon state, then rate limit
  // the notifications.
  // the notifications.
  if (!good && (icon == last_known_status_icon) &&
      (Date.now() - last_notification_time < _NOTIFY_INTERVAL))
    return;

  // Detect the new notification API, and fall back to the old one if not
  // available.
  if (chrome.notifications) {
    createNotificationNew(status);
  } else {
    createNotificationOld(status);
  }

  last_known_status_icon = icon;
  last_notification_time = Date.now();
}

function updateBrowserActionIcon(status) {
  chrome.browserAction.setBadgeBackgroundColor({color: _BADGE_COLOR});
  chrome.browserAction.setBadgeText({text: _BADGE_TEXT});
  chrome.browserAction.setIcon({path: getIconForStatus(status)});
}

function update() {
  if (timer != null) {
    clearTimeout(timer);
    timer = null;
  }
  timer = setTimeout(update, _UPDATE_INTERVAL);
  var time = Date.now();
  getCurrentStatus(function(status) {
    if (time < last_status_update_time) {
      return;
    }
    last_status_update_time = time;
    console.log(getNotificationMessageForStatus(status));
    updateBrowserActionIcon(status);
    updateNotifications(status);
  });
}

update();
