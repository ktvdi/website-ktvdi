/* KTVDI event modules loader. Load in the same order as the original events.js. */
(function () {
  'use strict';
  [
    './js/events/click.js',
    './js/events/inputs.js',
    './js/events/ui.js',
    './js/events/forms.js',
    './js/events/streamlit.js',
    './js/events/lifecycle.js'
  ].forEach(function (src) {
    document.write('<script src="' + src + '"></script>');
  });
})();
