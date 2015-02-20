// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const HIGH_REVIEW_COUNT = 15;
const HIGH_REVIEW_STYLE = 'color:red';
const MEDIUM_REVIEW_COUNT = 8;
const MEDIUM_REVIEW_STYLE = 'color:orange';
const EMAIL_MATCHER_REGEXP = /<([a-z]+)@google\.com>/;
const XHR_TIMEOUT = 10000;

function getOpenReviewCount(username, callback) {
  var user = username + '%40google.com';
  var url_base = 'https://chrome-internal-review.googlesource.com/changes/';
  var query_static = '?q=status:open+project:arc%2Farc';
  var reviewer_not_owner = '+reviewer:' + user + '+-owner:' + user;
  var url = url_base + query_static + reviewer_not_owner;

  var xhr = new XMLHttpRequest();
  xhr.open('GET', url, true);
  xhr.setRequestHeader('Accept', 'application/json');
  xhr.onload = function(e) {
    if (xhr.getResponseHeader('content-type').indexOf('application/json') != -1
        && xhr.status == 200) {
      // application/json responses from Gerrit start with a magic prefix )]}'
      // See: https://gerrit-review.googlesource.com/Documentation/rest-api.html
      var response = JSON.parse(xhr.response.substring(4));
      // The number of responses to a /changes/ query is the number of changes
      // that match the query.  In this case, the number of open reviews that
      // the user is a reviewer but not owner for.
      callback(response.length);
    }
  };
  xhr.ontimeout = function() {
    callback('?? [timeout]');
  };
  xhr.onerror = function() {
    console.error('url=' + url + ' status=' + xhr.statusText);
    callback('?? [error]');
  };
  xhr.send();
}

function showReviewCounts() {
  var i;
  var anchors = document.getElementsByTagName('a');
  for (i = 0; i < anchors.length; i++) {
    var title = anchors[i].getAttribute('title');
    if (title) {
      var m = title.match(EMAIL_MATCHER_REGEXP);
      if (m) {
        getOpenReviewCount(m[1], function(anchor, num_reviews) {
          // Check if we already have added this element (we check the
          // previousSibling as well because Gerrit's JS UI can shuffle the
          // contents of these elements around by removing and appending the
          // items during a UI update.
          var mynode = anchor.nextSibling || anchor.previousSibling;
          if (!mynode || mynode.getAttribute('class') != 'review-count')
            mynode = document.createElement('span');
          mynode.setAttribute('class', 'review-count');
          if (num_reviews > HIGH_REVIEW_COUNT)
            mynode.setAttribute('style', HIGH_REVIEW_STYLE);
          else if (num_reviews > MEDIUM_REVIEW_COUNT)
            mynode.setAttribute('style', MEDIUM_REVIEW_STYLE);
          mynode.innerText = ' (' + num_reviews + ' open reviews)';
          // Remove the node in case it is in the wrong order (previousSibling).
          if (mynode.parentNode != undefined)
            anchor.parentNode.removeChild(mynode);
          anchor.parentNode.appendChild(mynode);
        }.bind(undefined, anchors[i]));
      }
    }
  }
}


var showReviewTimeout = null;

var config = { childList: true, subtree: true };
var observer = new MutationObserver(function(mutations) {
  mutations.forEach(function(mutation) {
    var i;
    // Disregard this mutation if we caused it, or we will be in a perpetual
    // mutate/respond cycle.
    for (i = 0; i < mutation.addedNodes.length; i++) {
      if (mutation.addedNodes[i].getAttribute &&
          mutation.addedNodes[i].getAttribute('class') == 'review-count') {
        return;
      }
    }
    for (i = 0; i < mutation.removedNodes.length; i++) {
      if (mutation.removedNodes[i].getAttribute &&
          mutation.removedNodes[i].getAttribute('class') == 'review-count') {
        return;
      }
    }
    if (showReviewTimeout != null) {
      window.clearTimeout(showReviewTimeout);
    }
    // Delay a little here so we can batch up many mutations to produce one
    // expensive call to showReviewCounts.
    showReviewTimeout = window.setTimeout(showReviewCounts, 200);
  });
});

observer.observe(document.getElementsByTagName('body')[0], config);
