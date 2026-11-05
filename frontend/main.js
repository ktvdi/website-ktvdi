/* KTVDI frontend entry point. Keep module order for shared global functions. */
(function () {
  'use strict';
  var scripts = [
    './js/core.js',
    './js/views/navigation.js',
    './js/views/database.js',
    './js/views/activity.js',
    './js/views/pages/home.js',
    './js/views/pages/statistics.js',
    './js/views/pages/notifications.js',
    './js/views/pages/auth.js',
    './js/views/pages/broadcast.js',
    './js/views/pages/community.js',
    './js/views/render.js',
    './js/maps.js',
    './js/events.js'
  ];

  // main.js is an external script, so the closing script tag must be literal.
  // document.write keeps these classic scripts parser-ordered and preserves
  // the shared global-function architecture used by the existing frontend.
  scripts.forEach(function (src) {
    document.write('<script src="' + src + '"></script>');
  });
})();
