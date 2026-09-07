(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.navigation) return;

  var GROUPS = [
    { id: 'overview', icon: '⌂', label: 'Обзор', hint: 'Состояние и активность', defaultTab: 'main', tabs: ['main', 'log'] },
    { id: 'vacancies', icon: '⌕', label: 'Вакансии', hint: 'Поиск и очередь', defaultTab: 'db', tabs: ['db', 'recoh', 'tests', 'apply'] },
    { id: 'applications', icon: '✓', label: 'Отклики', hint: 'История и HH статус', defaultTab: 'applied', tabs: ['applied', 'hh'] },
    { id: 'communications', icon: '◌', label: 'AI и общение', hint: 'Ответы и чаты', defaultTab: 'llm', tabs: ['llm', 'hedi'] },
    { id: 'resume', icon: '◫', label: 'Резюме', hint: 'Просмотры и развитие', defaultTab: 'views', tabs: ['views'] },
    { id: 'settings', icon: '⚙', label: 'Настройки', hint: 'Подключение и правила', defaultTab: 'settings', tabs: ['settings'] }
  ];

  var HASH_ALIASES = {
    activity: 'log',
    log: 'log',
    main: 'main',
    db: 'db',
    vacancies: 'db',
    recommendations: 'recoh',
    recoh: 'recoh',
    tests: 'tests',
    apply: 'apply',
    applied: 'applied',
    hh: 'hh',
    llm: 'llm',
    hedi: 'hedi',
    views: 'views',
    settings: 'settings'
  };

  var internalHashWrite = false;

  function groupById(id) {
    return GROUPS.find(function (group) { return group.id === id; }) || null;
  }

  function groupForTab(tabName) {
    return GROUPS.find(function (group) { return group.tabs.indexOf(tabName) >= 0; }) || GROUPS[0];
  }

  function legacyTab(tabName) {
    return document.querySelector('#tabs .tab[data-tab="' + tabName + '"]');
  }

  function firstAvailableTab(group) {
    if (legacyTab(group.defaultTab)) return group.defaultTab;
    for (var i = 0; i < group.tabs.length; i++) {
      if (legacyTab(group.tabs[i])) return group.tabs[i];
    }
    return 'main';
  }

  function canonicalHash(section, tabName) {
    return '#' + section + '/' + tabName;
  }

  function writeHash(section, tabName, replace) {
    var next = canonicalHash(section, tabName);
    if (window.location.hash === next) return;
    internalHashWrite = true;
    try {
      if (window.history && window.history[replace ? 'replaceState' : 'pushState']) {
        window.history[replace ? 'replaceState' : 'pushState'](null, '', next);
      } else {
        window.location.hash = next;
      }
    } finally {
      window.setTimeout(function () { internalHashWrite = false; }, 0);
    }
  }

  function setShellActive(section, tabName) {
    document.querySelectorAll('#phase5-primary-nav [data-section]').forEach(function (button) {
      var active = button.getAttribute('data-section') === section;
      button.classList.toggle('active', active);
      button.setAttribute('aria-current', active ? 'page' : 'false');
    });

    var group = groupById(section) || groupForTab(tabName);
    var title = document.getElementById('phase5-location-title');
    var hint = document.getElementById('phase5-location-hint');
    if (title) title.textContent = group.label;
    if (hint) hint.textContent = group.hint;
  }

  function emitTabChange(section, tabName, source) {
    if (HHUI.core && typeof HHUI.core.emit === 'function') {
      HHUI.core.emit('hh:tabchange', { section: section, tab: tabName, source: source || 'navigation' });
    } else {
      window.dispatchEvent(new CustomEvent('hh:tabchange', {
        detail: { section: section, tab: tabName, source: source || 'navigation' }
      }));
    }
  }

  function activateLegacy(tabName, options) {
    options = options || {};
    var tab = legacyTab(tabName);
    if (!tab) return false;
    var group = groupForTab(tabName);
    tab.click();
    setShellActive(group.id, tabName);
    if (options.writeHash !== false) writeHash(group.id, tabName, !!options.replaceHash);
    emitTabChange(group.id, tabName, options.source || 'shell');
    return true;
  }

  function navigate(section, tabName, options) {
    options = options || {};
    var group = groupById(section) || GROUPS[0];
    var target = tabName && group.tabs.indexOf(tabName) >= 0 ? tabName : firstAvailableTab(group);
    if (!activateLegacy(target, options) && target !== 'main') {
      return activateLegacy('main', options);
    }
    return true;
  }

  function parseHash(rawHash) {
    var raw = String(rawHash || '').replace(/^#/, '').trim();
    if (!raw) return { section: 'overview', tab: 'main' };

    var parts = raw.split('/').filter(Boolean);
    if (parts.length >= 2 && groupById(parts[0])) {
      var group = groupById(parts[0]);
      var requested = HASH_ALIASES[parts[1]] || parts[1];
      return {
        section: group.id,
        tab: group.tabs.indexOf(requested) >= 0 ? requested : firstAvailableTab(group)
      };
    }

    if (groupById(parts[0])) {
      var bySection = groupById(parts[0]);
      return { section: bySection.id, tab: firstAvailableTab(bySection) };
    }

    var aliasTab = HASH_ALIASES[parts[0]];
    if (aliasTab) {
      var aliasGroup = groupForTab(aliasTab);
      return { section: aliasGroup.id, tab: aliasTab };
    }
    return { section: 'overview', tab: 'main' };
  }

  function buildShell() {
    if (document.getElementById('phase5-nav-shell')) return;
    var tabs = document.getElementById('tabs');
    var header = document.getElementById('header');
    if (!tabs || !header || !tabs.parentNode) return;

    var shell = document.createElement('div');
    shell.id = 'phase5-nav-shell';
    shell.className = 'phase5-nav-shell';

    var primary = document.createElement('nav');
    primary.id = 'phase5-primary-nav';
    primary.className = 'phase5-primary-nav';
    primary.setAttribute('aria-label', 'Основные разделы');

    GROUPS.forEach(function (group) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'phase5-nav-item';
      button.setAttribute('data-section', group.id);
      button.setAttribute('data-testid', 'phase5-nav-' + group.id);
      button.innerHTML = '<span class="phase5-nav-icon" aria-hidden="true"></span>' +
        '<span class="phase5-nav-copy"><span class="phase5-nav-label"></span>' +
        '<span class="phase5-nav-hint"></span></span>';
      button.querySelector('.phase5-nav-icon').textContent = group.icon;
      button.querySelector('.phase5-nav-label').textContent = group.label;
      button.querySelector('.phase5-nav-hint').textContent = group.hint;
      button.addEventListener('click', function () {
        navigate(group.id, null, { source: 'primary-nav' });
      });
      primary.appendChild(button);
    });

    var location = document.createElement('div');
    location.className = 'phase5-location';
    location.innerHTML = '<span class="phase5-location-kicker">Подразделы</span>' +
      '<span id="phase5-location-title"></span>' +
      '<span id="phase5-location-hint"></span>';

    shell.appendChild(primary);
    shell.appendChild(location);
    tabs.parentNode.insertBefore(shell, tabs);
    tabs.classList.add('phase5-legacy-tabs');
    tabs.setAttribute('aria-label', 'Подразделы текущего интерфейса');
  }

  function bindLegacyTabs() {
    var tabs = document.getElementById('tabs');
    if (!tabs || tabs.dataset.phase5NavBound === '1') return;
    tabs.dataset.phase5NavBound = '1';
    tabs.addEventListener('click', function (event) {
      var tab = event.target && event.target.closest ? event.target.closest('.tab[data-tab]') : null;
      if (!tab) return;
      window.requestAnimationFrame(function () {
        var tabName = tab.getAttribute('data-tab') || 'main';
        var group = groupForTab(tabName);
        setShellActive(group.id, tabName);
        writeHash(group.id, tabName, true);
        emitTabChange(group.id, tabName, 'legacy-tab');
      });
    });
  }

  function syncFromActiveTab() {
    var active = document.querySelector('#tabs .tab.active[data-tab]');
    var tabName = active ? active.getAttribute('data-tab') : 'main';
    var group = groupForTab(tabName || 'main');
    setShellActive(group.id, tabName || 'main');
    return { section: group.id, tab: tabName || 'main' };
  }

  function routeInitialHash() {
    var parsed = parseHash(window.location.hash);
    navigate(parsed.section, parsed.tab, {
      writeHash: true,
      replaceHash: true,
      source: 'initial-hash'
    });
  }

  function init() {
    buildShell();
    bindLegacyTabs();
    routeInitialHash();
  }

  window.addEventListener('hashchange', function () {
    if (internalHashWrite) return;
    var parsed = parseHash(window.location.hash);
    navigate(parsed.section, parsed.tab, { writeHash: false, source: 'hashchange' });
  });

  HHUI.navigation = {
    groups: GROUPS.slice(),
    navigate: navigate,
    parseHash: parseHash,
    sync: syncFromActiveTab
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
