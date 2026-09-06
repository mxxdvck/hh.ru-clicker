(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.core) return;

  function emit(name, detail) {
    window.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
  }

  function on(name, handler, options) {
    window.addEventListener(name, handler, options || false);
    return function () { window.removeEventListener(name, handler, options || false); };
  }

  function ensureStylesheet(id, href) {
    if (document.getElementById(id)) return;
    var link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function loadScriptOnce(id, src) {
    if (document.getElementById(id)) return;
    var script = document.createElement('script');
    script.id = id;
    script.src = src;
    script.defer = true;
    document.body.appendChild(script);
  }

  HHUI.core = {
    version: 'phase5',
    emit: emit,
    on: on,
    state: function () {
      return (typeof State !== 'undefined' && State) ? State : null;
    },
    snapshot: function () {
      var state = HHUI.core.state();
      return state ? state.lastSnapshot : null;
    },
    ensureStylesheet: ensureStylesheet,
    loadScriptOnce: loadScriptOnce
  };

  ensureStylesheet('phase5-settings-css', '/static/css/phase5-settings.css');
  loadScriptOnce('phase5-ui-settings-script', '/static/js/ui/settings.js');
  ensureStylesheet('phase5-overview-css', '/static/css/phase5-overview.css');
  loadScriptOnce('phase5-ui-overview-script', '/static/js/ui/overview.js');
  ensureStylesheet('phase5-vacancies-css', '/static/css/phase5-vacancies.css');
  loadScriptOnce('phase5-ui-vacancies-script', '/static/js/ui/vacancies.js');
})();
