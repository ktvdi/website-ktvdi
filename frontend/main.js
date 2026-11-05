/* KTVDI frontend entry point. Load shared state, view modules, maps, then events. */
(function () {
  'use strict';
  var scripts = [
    './js/core.js',
    './js/views/navigation.js',
    './js/views/database.js',
    './js/views/activity.js',
    './js/views/render.js',
    './js/maps.js',
    './js/events.js'
  ];
  scripts.forEach(function (src) {
    document.write('<script src="' + src + '"><\/script>');
  });
})();
