/* KTVDI frontend entry point. Keep module order: core -> views -> maps -> events. */
(function () {
  'use strict';
  var scripts = [
    './js/core.js',
    './js/views.js',
    './js/maps.js',
    './js/events.js'
  ];
  scripts.forEach(function (src) {
    document.write('<script src="' + src + '"><\/script>');
  });
})();
