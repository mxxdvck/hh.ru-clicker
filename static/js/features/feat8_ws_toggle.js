/*
 * Feature 8: WebSocket toggle + Project Phase 5 baseline compatibility layer.
 *
 * This file is already loaded after app.js and the inline websocket helpers,
 * which makes it a safe additive place for Phase 5 accessibility/bootstrap
 * work without rewriting index.html or the main render pipeline.
 */
(function () {
  'use strict';

  if (window.__FEAT8_WS_TOGGLE__) return;
  window.__FEAT8_WS_TOGGLE__ = true;

  var DOT_CHAR = '\u25CF';
  var lastStatus = null;

  function safe(fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
  }

  function wrapGlobal(name, makeWrapper) {
    var orig = window[name];
    if (typeof orig !== 'function' || orig.__feat8_wrapped) return;
    var wrapped = makeWrapper(orig);
    try { wrapped.__feat8_wrapped = true; } catch (e) { /* noop */ }
    window[name] = wrapped;
  }

  function dotClassForStatus(status) {
    if (status === 'connected') return 'feat8-dot-connected';
    if (status === 'connecting' || status === 'reconnecting') return 'feat8-dot-pending';
    if (status === 'error' || status === 'no_token') return 'feat8-dot-error';
    return 'feat8-dot-off';
  }

  function statusForIdx(idx, badgeText) {
    var accs = safe(function () { return lastStatus && lastStatus.accounts; }, null);
    if (accs && accs[idx] && typeof accs[idx].status === 'string' && accs[idx].status) {
      return accs[idx].status;
    }
    return (badgeText || '').trim();
  }

  function updateIndicators() {
    var list = document.getElementById('ws-acc-list');
    if (!list) return;
    var badges = list.querySelectorAll('[id^="ws-badge-"]');
    for (var i = 0; i < badges.length; i++) {
      var badge = badges[i];
      var idx = badge.id.slice('ws-badge-'.length);
      var status = statusForIdx(idx, badge.textContent);
      var dot = document.createElement('span');
      dot.className = 'feat8-dot ' + dotClassForStatus(status);
      dot.setAttribute('data-feat8-idx', idx);
      dot.title = 'WS-слушатель: ' + (status || 'неизвестно');
      dot.textContent = DOT_CHAR;
      badge.insertAdjacentElement('afterend', dot);
    }
  }

  function snapshotConfigValue(snapshot) {
    return safe(function () {
      var snap = snapshot || (window.State && window.State.lastSnapshot);
      return snap && snap.config ? snap.config.use_websocket_realtime : undefined;
    }, undefined);
  }

  function syncGlobalCheckbox(snapshot) {
    var cb = document.getElementById('feat8-ws-global-cb');
    if (!cb) return;
    var val = snapshotConfigValue(snapshot);
    if (typeof val === 'boolean' && cb.checked !== val) cb.checked = val;
  }

  function injectGlobalToggle() {
    var section = document.getElementById('ws-realtime-section');
    if (!section || document.getElementById('feat8-ws-global-cb')) return;
    var flagEl = document.getElementById('ws-global-flag');
    var block = flagEl && flagEl.parentElement;
    if (!block) return;

    var label = document.createElement('label');
    label.className = 'feat8-global-label';

    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'feat8-ws-global-cb';
    cb.addEventListener('change', function () {
      safe(function () {
        if (typeof window.sendCmd === 'function') {
          window.sendCmd({
            type: 'set_config',
            key: 'use_websocket_realtime',
            value: cb.checked
          });
        }
      }, null);
    });

    var text = document.createElement('span');
    text.className = 'feat8-global-text';
    text.textContent = 'Глобально use_websocket_realtime';

    var hint = document.createElement('span');
    hint.className = 'feat8-global-hint';
    hint.textContent = 'слушатели стартуют после \u25B6 Вкл / рестарта бота';

    label.appendChild(cb);
    label.appendChild(text);
    label.appendChild(hint);

    var btn = block.querySelector('button');
    if (btn && btn.parentElement === block) block.insertBefore(label, btn);
    else block.appendChild(label);
    syncGlobalCheckbox();
  }

  var PHASE5_TEST_IDS = {
    'pause-btn': 'global-pause',
    'apply-mode-badge': 'apply-mode',
    'search-only-mode': 'search-only-mode',
    'daily-apply-limit': 'daily-apply-limit',
    'run-apply-limit': 'run-apply-limit',
    'use-oauth-apply': 'use-oauth-apply',
    'auto-apply-tests': 'auto-apply-tests',
    'llm-auto-send': 'llm-auto-send',
    'apply-account': 'apply-account',
    'apply-vacancy': 'apply-vacancy',
    'apply-result': 'apply-result',
    'apply-questionnaire': 'apply-questionnaire'
  };

  function syncTabAria() {
    var tabs = document.querySelectorAll('#tabs .tab[data-tab]');
    for (var i = 0; i < tabs.length; i++) {
      var tab = tabs[i];
      tab.setAttribute('aria-selected', tab.classList.contains('active') ? 'true' : 'false');
    }
  }

  function enhanceTabs() {
    var tabsRoot = document.getElementById('tabs');
    if (!tabsRoot) return;
    tabsRoot.setAttribute('role', 'tablist');
    tabsRoot.setAttribute('aria-label', 'Основная навигация');

    var tabs = tabsRoot.querySelectorAll('.tab[data-tab]');
    for (var i = 0; i < tabs.length; i++) {
      var tab = tabs[i];
      var name = tab.getAttribute('data-tab') || '';
      tab.setAttribute('role', 'tab');
      tab.setAttribute('tabindex', '0');
      tab.setAttribute('aria-controls', 'panel-' + name);
      tab.setAttribute('data-testid', 'legacy-tab-' + name);
    }
    syncTabAria();

    if (tabsRoot.dataset.phase5KeyboardBound === '1') return;
    tabsRoot.dataset.phase5KeyboardBound = '1';

    tabsRoot.addEventListener('click', function () {
      window.requestAnimationFrame(syncTabAria);
    });

    tabsRoot.addEventListener('keydown', function (event) {
      var tab = event.target && event.target.closest
        ? event.target.closest('.tab[data-tab]')
        : null;
      if (!tab) return;

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        tab.click();
        return;
      }

      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      var items = Array.prototype.slice.call(tabsRoot.querySelectorAll('.tab[data-tab]'));
      var current = items.indexOf(tab);
      if (current < 0 || !items.length) return;
      var delta = event.key === 'ArrowRight' ? 1 : -1;
      var next = items[(current + delta + items.length) % items.length];
      next.focus();
      next.click();
    });
  }

  function addCriticalTestIds() {
    Object.keys(PHASE5_TEST_IDS).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.setAttribute('data-testid', PHASE5_TEST_IDS[id]);
    });
  }

  function installPhase5Baseline() {
    document.documentElement.classList.add('phase5-a11y');
    enhanceTabs();
    addCriticalTestIds();
  }

  function emitPhase5Snapshot(snapshot) {
    safe(function () {
      var snap = snapshot;
      if (!snap && typeof State !== 'undefined' && State) snap = State.lastSnapshot;
      if (!snap) return;
      if (window.HHUI && HHUI.core && typeof HHUI.core.emit === 'function') {
        HHUI.core.emit('hh:snapshot', { snapshot: snap });
      }
    }, null);
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
    return new Promise(function (resolve, reject) {
      var existing = document.getElementById(id);
      if (existing) {
        if (existing.dataset.loaded === '1') resolve();
        else existing.addEventListener('load', resolve, { once: true });
        return;
      }
      var script = document.createElement('script');
      script.id = id;
      script.src = src;
      script.defer = true;
      script.addEventListener('load', function () {
        script.dataset.loaded = '1';
        resolve();
      }, { once: true });
      script.addEventListener('error', function () { reject(new Error('asset load failed: ' + src)); }, { once: true });
      document.body.appendChild(script);
    });
  }

  function loadPhase5Ui() {
    ensureStylesheet('phase5-shell-css', '/static/css/phase5-shell.css');
    return loadScriptOnce('phase5-ui-core-script', '/static/js/ui/core.js')
      .then(function () {
        return loadScriptOnce('phase5-ui-navigation-script', '/static/js/ui/navigation.js');
      })
      .catch(function (error) {
        console.error('Phase5 UI bootstrap:', error);
      });
  }

  wrapGlobal('wsFetchStatus', function (orig) {
    return function () {
      return Promise.resolve(orig.apply(this, arguments)).then(function (data) {
        if (data && data.ok && data.accounts) lastStatus = data;
        return data;
      });
    };
  });

  wrapGlobal('wsRender', function (orig) {
    return function () {
      return Promise.resolve(orig.apply(this, arguments)).then(function (res) {
        safe(updateIndicators, null);
        safe(syncGlobalCheckbox, null);
        return res;
      });
    };
  });

  wrapGlobal('renderAll', function (orig) {
    return function () {
      var res = orig.apply(this, arguments);
      safe(syncGlobalCheckbox, null);
      safe(syncTabAria, null);
      emitPhase5Snapshot();
      return res;
    };
  });

  window.WsToggle = {
    refresh: function (btn) {
      return typeof window.wsRefresh === 'function' ? window.wsRefresh(btn) : undefined;
    },
    getStatus: function () {
      return typeof window.wsFetchStatus === 'function'
        ? window.wsFetchStatus()
        : Promise.resolve({ ok: false, error: 'wsFetchStatus недоступен' });
    },
    syncSnapshot: function (snapshot) {
      safe(function () { syncGlobalCheckbox(snapshot); }, null);
      safe(syncTabAria, null);
      emitPhase5Snapshot(snapshot);
    }
  };

  function init() {
    safe(injectGlobalToggle, null);
    safe(syncGlobalCheckbox, null);
    safe(installPhase5Baseline, null);
    safe(function () { loadPhase5Ui(); }, null);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
