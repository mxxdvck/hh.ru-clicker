(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.settings) return;

  var GROUPS = [
    { id: 'all', label: 'Все' },
    { id: 'career', label: 'Карьера' },
    { id: 'connection', label: 'Подключение' },
    { id: 'search', label: 'Поиск и отклики' },
    { id: 'templates', label: 'Шаблоны' },
    { id: 'ai', label: 'AI / LLM' },
    { id: 'advanced', label: 'Расширенные' }
  ];

  var state = {
    group: 'all',
    query: '',
    searchOpenState: null
  };

  function normalize(value) {
    return String(value || '')
      .toLocaleLowerCase('ru-RU')
      .replace(/ё/g, 'е')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function panel() {
    return document.getElementById('settings-panel');
  }

  function topSections() {
    var root = panel();
    if (!root) return [];
    return Array.prototype.filter.call(root.children, function (node) {
      return node && node.matches && node.matches('details.q-section');
    });
  }

  function summaryText(section) {
    var summary = section.querySelector(':scope > summary');
    return normalize(summary ? summary.textContent : '');
  }

  function classify(section) {
    var id = section.id || '';
    var text = summaryText(section);

    if (id === 'job-status-section' || id === 'skills-section' || id === 'analyze-section') return 'career';
    if (id === 'proxy-section' || id === 'mobile-auth-section') return 'connection';
    if (id === 'llm-section') return 'ai';
    if (id === 'ws-realtime-section') return 'advanced';

    if (/браузерн.*сесси|обновить куки/.test(text)) return 'connection';
    if (/параметры бота|фильтры и автоматизация|пул поисковых запросов/.test(text)) return 'search';
    if (/шаблоны писем|шаблонные ответы/.test(text)) return 'templates';
    if (/llm|ai \/ llm|авто-ответ/.test(text)) return 'ai';
    if (/диагностик|websocket|json-редактор|продвинут/.test(text)) return 'advanced';
    return 'advanced';
  }

  function groupLabel(id) {
    var match = GROUPS.find(function (group) { return group.id === id; });
    return match ? match.label : 'Расширенные';
  }

  function indexSection(section) {
    var text = normalize(section.textContent || '');
    section.dataset.settingsSearch = text;
    return text;
  }

  function annotateSections() {
    topSections().forEach(function (section) {
      var group = classify(section);
      section.dataset.settingsGroup = group;
      indexSection(section);

      var summary = section.querySelector(':scope > summary');
      if (summary && !summary.querySelector('.phase5-settings-section-tag')) {
        var tag = document.createElement('span');
        tag.className = 'phase5-settings-section-tag';
        tag.textContent = groupLabel(group);
        summary.appendChild(tag);
      }

      section.querySelectorAll('details.session-block').forEach(function (nested) {
        nested.classList.add('phase5-settings-nested');
      });
    });
  }

  function buildToolbar() {
    var root = panel();
    if (!root || document.getElementById('phase5-settings-toolbar')) return;

    var toolbar = document.createElement('div');
    toolbar.id = 'phase5-settings-toolbar';
    toolbar.className = 'phase5-settings-toolbar';
    toolbar.setAttribute('data-testid', 'phase5-settings-toolbar');

    var head = document.createElement('div');
    head.className = 'phase5-settings-toolbar-head';

    var titleWrap = document.createElement('div');
    var title = document.createElement('h2');
    title.className = 'phase5-settings-title';
    title.textContent = 'Настройки';
    var hint = document.createElement('div');
    hint.className = 'phase5-settings-save-hint';
    hint.setAttribute('data-testid', 'phase5-settings-save-hint');
    hint.textContent = 'Переключатели и поля с мгновенным сохранением применяются сразу. Блоки с кнопкой «Сохранить» или «Применить» требуют отдельного подтверждения.';
    titleWrap.appendChild(title);
    titleWrap.appendChild(hint);

    var results = document.createElement('span');
    results.id = 'phase5-settings-results';
    results.className = 'phase5-settings-results';
    results.setAttribute('aria-live', 'polite');

    head.appendChild(titleWrap);
    head.appendChild(results);

    var searchRow = document.createElement('div');
    searchRow.className = 'phase5-settings-search-row';

    var search = document.createElement('input');
    search.id = 'phase5-settings-search';
    search.className = 'phase5-settings-search';
    search.type = 'search';
    search.placeholder = 'Поиск: прокси, лимит, LLM, куки, график...';
    search.autocomplete = 'off';
    search.setAttribute('data-testid', 'phase5-settings-search');
    search.setAttribute('aria-label', 'Поиск по настройкам');

    var clear = document.createElement('button');
    clear.id = 'phase5-settings-clear';
    clear.className = 'phase5-settings-clear';
    clear.type = 'button';
    clear.textContent = 'Очистить';
    clear.disabled = true;
    clear.setAttribute('data-testid', 'phase5-settings-clear');

    search.addEventListener('input', function () {
      setQuery(search.value);
    });
    clear.addEventListener('click', function () {
      search.value = '';
      setQuery('');
      search.focus();
    });

    searchRow.appendChild(search);
    searchRow.appendChild(clear);

    var filters = document.createElement('div');
    filters.id = 'phase5-settings-filters';
    filters.className = 'phase5-settings-filter-row';
    filters.setAttribute('aria-label', 'Группы настроек');

    GROUPS.forEach(function (group) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'phase5-settings-chip' + (group.id === 'all' ? ' active' : '');
      button.textContent = group.label;
      button.dataset.group = group.id;
      button.setAttribute('data-testid', 'phase5-settings-group-' + group.id);
      button.setAttribute('aria-pressed', group.id === 'all' ? 'true' : 'false');
      button.addEventListener('click', function () { setGroup(group.id); });
      filters.appendChild(button);
    });

    toolbar.appendChild(head);
    toolbar.appendChild(searchRow);
    toolbar.appendChild(filters);

    var empty = document.createElement('div');
    empty.id = 'phase5-settings-empty';
    empty.className = 'phase5-settings-empty';
    empty.textContent = 'Ничего не найдено. Попробуйте другой запрос или выберите «Все».';
    empty.setAttribute('data-testid', 'phase5-settings-empty');

    root.insertBefore(toolbar, root.firstChild);
    root.insertBefore(empty, toolbar.nextSibling);
  }

  function matchesQuery(section, query) {
    if (!query) return true;
    var haystack = section.dataset.settingsSearch || indexSection(section);
    var words = normalize(query).split(' ').filter(Boolean);
    return words.every(function (word) { return haystack.indexOf(word) >= 0; });
  }

  function captureOpenState() {
    state.searchOpenState = topSections().map(function (section) {
      return { section: section, open: !!section.open };
    });
  }

  function restoreOpenState() {
    if (!state.searchOpenState) return;
    state.searchOpenState.forEach(function (entry) {
      if (entry.section && entry.section.isConnected) entry.section.open = entry.open;
    });
    state.searchOpenState = null;
  }

  function applyFilters() {
    var visible = 0;
    var query = normalize(state.query);
    topSections().forEach(function (section) {
      var groupOk = state.group === 'all' || section.dataset.settingsGroup === state.group;
      var queryOk = matchesQuery(section, query);
      var show = groupOk && queryOk;
      section.hidden = !show;
      if (show) {
        visible += 1;
        if (query) section.open = true;
      }
    });

    document.querySelectorAll('#phase5-settings-filters .phase5-settings-chip').forEach(function (button) {
      var active = button.dataset.group === state.group;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });

    var results = document.getElementById('phase5-settings-results');
    if (results) results.textContent = visible + ' ' + (visible === 1 ? 'раздел' : 'разделов');

    var empty = document.getElementById('phase5-settings-empty');
    if (empty) empty.classList.toggle('visible', visible === 0);

    var clear = document.getElementById('phase5-settings-clear');
    if (clear) clear.disabled = !state.query;
  }

  function setQuery(value) {
    var next = String(value || '');
    var hadQuery = !!normalize(state.query);
    var hasQuery = !!normalize(next);
    if (!hadQuery && hasQuery) captureOpenState();
    state.query = next;
    if (hadQuery && !hasQuery) restoreOpenState();
    applyFilters();
  }

  function setGroup(group) {
    var exists = GROUPS.some(function (item) { return item.id === group; });
    state.group = exists ? group : 'all';
    applyFilters();
  }

  function focusSearch() {
    var search = document.getElementById('phase5-settings-search');
    if (!search) return false;
    search.focus();
    search.select();
    return true;
  }

  function isSettingsActive() {
    var settingsPanel = document.getElementById('panel-settings');
    return !!(settingsPanel && settingsPanel.classList.contains('active'));
  }

  function bindKeyboardShortcut() {
    if (document.documentElement.dataset.phase5SettingsShortcut === '1') return;
    document.documentElement.dataset.phase5SettingsShortcut = '1';
    document.addEventListener('keydown', function (event) {
      if (!isSettingsActive()) return;
      var target = event.target;
      var editable = target && (target.matches('input, textarea, select') || target.isContentEditable);
      if (editable) return;
      if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'k') {
        event.preventDefault();
        focusSearch();
      }
    });
  }

  function init() {
    var root = panel();
    if (!root) return;
    root.classList.add('phase5-settings-ia');
    annotateSections();
    buildToolbar();
    bindKeyboardShortcut();
    applyFilters();
  }

  HHUI.settings = {
    groups: GROUPS.slice(),
    setGroup: setGroup,
    setQuery: setQuery,
    focusSearch: focusSearch,
    refresh: function () {
      annotateSections();
      applyFilters();
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
