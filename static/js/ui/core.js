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
    }
  };
})();
