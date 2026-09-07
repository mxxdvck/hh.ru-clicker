(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.vacancies) return;

  var accountUi = Object.create(null);
  var query = '';
  var accountFilter = 'all';
  var showHidden = false;
  var lastSnapshot = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function snapshot() {
    return HHUI.core && typeof HHUI.core.snapshot === 'function' ? HHUI.core.snapshot() : null;
  }

  function previewOf(account) {
    return Array.isArray(account && account.search_preview) ? account.search_preview : [];
  }

  function isReady(account, config) {
    return !!(config && config.search_only_mode === true && account && account.paused && account.paused_reason === 'search_only');
  }

  function idsOf(account) {
    return previewOf(account).map(function (item) { return String(item && item.id || '').trim(); }).filter(Boolean);
  }

  function uiState(account, ready) {
    var idx = String(account.idx);
    var ids = idsOf(account);
    var signature = String(ready) + ':' + ids.join('|');
    var state = accountUi[idx];
    if (!state || state.signature !== signature) {
      state = { signature: signature, selected: Object.create(null), hidden: Object.create(null) };
      if (ready) ids.forEach(function (id) { state.selected[id] = true; });
      accountUi[idx] = state;
    }
    return state;
  }

  function optionalNumber(value) {
    if (value === null || value === undefined || value === '') return null;
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function salary(item) {
    var from = optionalNumber(item && item.salary_from);
    var to = optionalNumber(item && item.salary_to);
    if (from === null && to === null) return 'зарплата не указана';
    if (from !== null && to !== null) return from.toLocaleString('ru-RU') + ' - ' + to.toLocaleString('ru-RU');
    if (from !== null) return 'от ' + from.toLocaleString('ru-RU');
    return 'до ' + to.toLocaleString('ru-RU');
  }

  function vacancyUrl(item) {
    var fallback = 'https://hh.ru/vacancy/' + encodeURIComponent(String(item && item.id || ''));
    try {
      var url = new URL(String(item && item.url || fallback), window.location.href);
      return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : fallback;
    } catch (_) { return fallback; }
  }

  function freshness(item) {
    var raw = String(item && item.published_at || '').trim();
    if (!raw) return 'свежесть: нет данных';
    var ts = Date.parse(raw);
    if (!Number.isFinite(ts)) return 'опубликовано: ' + raw;
    var hours = Math.max(0, Math.floor((Date.now() - ts) / 3600000));
    if (hours < 24) return 'опубликовано ' + hours + 'ч назад';
    return 'опубликовано ' + Math.floor(hours / 24) + 'д назад';
  }

  function sourceLabel(item) {
    var queryText = String(item && item.source_query || '').trim();
    return queryText ? 'поиск: ' + queryText : 'источник: текущая очередь';
  }

  function matches(item, account) {
    if (accountFilter !== 'all' && String(account.idx) !== accountFilter) return false;
    if (!query) return true;
    var hay = [item && item.id, item && item.title, item && item.company, account.short, account.name]
      .map(function (value) { return String(value || '').toLowerCase(); }).join(' ');
    return hay.indexOf(query) >= 0;
  }

  function selectedGroups(snap) {
    var config = (snap && snap.config) || {};
    var groups = Object.create(null);
    (snap && snap.accounts || []).forEach(function (account) {
      var ready = isReady(account, config);
      if (!ready) return;
      var state = uiState(account, ready);
      var ids = idsOf(account).filter(function (id) { return state.selected[id] && !state.hidden[id]; });
      if (ids.length) groups[String(account.idx)] = ids;
    });
    return groups;
  }

  function selectionCount(groups) {
    return Object.keys(groups).reduce(function (sum, key) { return sum + groups[key].length; }, 0);
  }

  function submitGroups(groups) {
    var keys = Object.keys(groups);
    var total = selectionCount(groups);
    if (!total || !keys.length) return;
    var ok = window.confirm('Откликнуться именно на выбранные ' + total + ' вакансий в ' + keys.length + ' аккаунт(ах)? Повторного поиска не будет. Все лимиты и safety-проверки останутся включены.');
    if (!ok) return;
    keys.forEach(function (idx) {
      if (typeof window.sendCmd === 'function') {
        window.sendCmd({ type: 'apply_search_results', idx: Number(idx), vacancy_ids: groups[idx].slice() });
      }
    });
  }

  function buildRoot() {
    var panel = document.getElementById('panel-db');
    if (!panel) return null;
    var root = document.getElementById('phase5-vacancy-workspace');
    if (root) return root;
    root = el('section', 'phase5-vacancy-workspace');
    root.id = 'phase5-vacancy-workspace';
    root.setAttribute('data-testid', 'phase5-vacancy-workspace');
    root.setAttribute('aria-label', 'Безопасный список вакансий');
    panel.insertBefore(root, panel.firstChild);
    return root;
  }

  function toolbar(root, snap) {
    var head = el('div', 'phase5-vacancy-head');
    var copy = el('div', 'phase5-vacancy-head-copy');
    copy.appendChild(el('h2', 'phase5-vacancy-title', 'Безопасный список вакансий'));
    copy.appendChild(el('div', 'phase5-vacancy-subtitle', 'Текущие результаты safe search. Отклик идёт по этому списку без повторного поиска.'));
    head.appendChild(copy);

    var controls = el('div', 'phase5-vacancy-controls');
    var search = document.createElement('input');
    search.type = 'search';
    search.value = query;
    search.placeholder = 'Поиск по вакансии, компании или ID';
    search.setAttribute('data-testid', 'phase5-vacancy-search');
    search.addEventListener('input', function () { query = search.value.trim().toLowerCase(); render(lastSnapshot || snapshot()); });
    controls.appendChild(search);

    var select = document.createElement('select');
    select.setAttribute('data-testid', 'phase5-vacancy-account-filter');
    var all = document.createElement('option');
    all.value = 'all';
    all.textContent = 'Все аккаунты';
    select.appendChild(all);
    (snap && snap.accounts || []).forEach(function (account) {
      var option = document.createElement('option');
      option.value = String(account.idx);
      option.textContent = account.short || account.name || ('Аккаунт #' + account.idx);
      select.appendChild(option);
    });
    select.value = accountFilter;
    select.addEventListener('change', function () { accountFilter = select.value; render(lastSnapshot || snapshot()); });
    controls.appendChild(select);

    var hiddenToggle = el('button', 'phase5-vacancy-secondary', showHidden ? 'Скрытые: показываются' : 'Показать скрытые');
    hiddenToggle.type = 'button';
    hiddenToggle.setAttribute('data-testid', 'phase5-vacancy-hidden-toggle');
    hiddenToggle.addEventListener('click', function () { showHidden = !showHidden; render(lastSnapshot || snapshot()); });
    controls.appendChild(hiddenToggle);

    var groups = selectedGroups(snap || {});
    var apply = el('button', 'phase5-vacancy-apply', 'Откликнуться на выбранные (' + selectionCount(groups) + ')');
    apply.type = 'button';
    apply.disabled = selectionCount(groups) === 0;
    apply.setAttribute('data-testid', 'phase5-vacancy-apply-selected');
    apply.addEventListener('click', function () { submitGroups(selectedGroups(lastSnapshot || snapshot() || {})); });
    controls.appendChild(apply);
    head.appendChild(controls);
    root.appendChild(head);
  }

  function metaChip(text, kind) {
    var chip = el('span', 'phase5-vacancy-chip', text);
    if (kind) chip.setAttribute('data-kind', kind);
    return chip;
  }

  function renderVacancyRow(list, account, item, state, ready) {
    var id = String(item && item.id || '').trim();
    if (!id || !matches(item, account)) return;
    var hidden = !!state.hidden[id];
    if (hidden && !showHidden) return;

    var row = el('article', 'phase5-vacancy-row' + (hidden ? ' is-hidden' : ''));
    row.setAttribute('data-vacancy-id', id);
    row.setAttribute('data-account-idx', String(account.idx));
    row.setAttribute('data-testid', 'phase5-vacancy-' + account.idx + '-' + id);

    var choose = document.createElement('input');
    choose.type = 'checkbox';
    choose.checked = !!state.selected[id] && !hidden;
    choose.disabled = !ready || hidden;
    choose.setAttribute('aria-label', 'Выбрать вакансию ' + id);
    choose.addEventListener('change', function () {
      state.selected[id] = choose.checked;
      render(lastSnapshot || snapshot());
    });
    row.appendChild(choose);

    var body = el('div', 'phase5-vacancy-body');
    var title = document.createElement('a');
    title.className = 'phase5-vacancy-name';
    title.href = vacancyUrl(item);
    title.target = '_blank';
    title.rel = 'noopener noreferrer';
    title.textContent = item.title || ('Вакансия ' + id);
    body.appendChild(title);
    body.appendChild(el('div', 'phase5-vacancy-company', item.company || 'Компания не указана'));

    var meta = el('div', 'phase5-vacancy-meta');
    meta.appendChild(metaChip(salary(item)));
    meta.appendChild(metaChip(ready ? 'прошла фильтры + дедуп' : 'safe-list не подтверждён', ready ? 'safe' : 'waiting'));
    meta.appendChild(metaChip(sourceLabel(item)));
    meta.appendChild(metaChip(freshness(item)));
    if (Array.isArray(item.schedules) && item.schedules.length) meta.appendChild(metaChip('график: ' + item.schedules.join(', ')));
    if (item.has_test) meta.appendChild(metaChip('тест / опрос', 'waiting'));
    else if (item.response_letter_required) meta.appendChild(metaChip('нужно письмо', 'waiting'));
    else meta.appendChild(metaChip('опрос: проверится перед отправкой'));
    if (item.hr_online) meta.appendChild(metaChip('HR: ' + String(item.hr_online)));
    if (item.chat_write_possibility) meta.appendChild(metaChip('чат: ' + String(item.chat_write_possibility)));
    if (item.quick_responses_allowed === true) meta.appendChild(metaChip('quick response', 'safe'));
    if (item.accredited_it_employer === true) meta.appendChild(metaChip('IT-аккредитация', 'safe'));
    body.appendChild(meta);
    row.appendChild(body);

    var actions = el('div', 'phase5-vacancy-actions');
    var open = el('a', 'phase5-vacancy-secondary', 'Открыть HH');
    open.href = vacancyUrl(item);
    open.target = '_blank';
    open.rel = 'noopener noreferrer';
    actions.appendChild(open);

    if (hidden) {
      var restore = el('button', 'phase5-vacancy-secondary', 'Вернуть');
      restore.type = 'button';
      restore.addEventListener('click', function () {
        delete state.hidden[id];
        if (ready) state.selected[id] = true;
        render(lastSnapshot || snapshot());
      });
      actions.appendChild(restore);
    } else {
      var hide = el('button', 'phase5-vacancy-secondary', 'Скрыть');
      hide.type = 'button';
      hide.title = 'Скрывает только в этом интерфейсе и снимает выбор';
      hide.addEventListener('click', function () {
        state.hidden[id] = true;
        delete state.selected[id];
        render(lastSnapshot || snapshot());
      });
      actions.appendChild(hide);

      var one = el('button', 'phase5-vacancy-apply-one', 'Откликнуться');
      one.type = 'button';
      one.disabled = !ready;
      one.setAttribute('data-testid', 'phase5-vacancy-apply-one-' + account.idx + '-' + id);
      one.addEventListener('click', function () {
        var groups = Object.create(null);
        groups[String(account.idx)] = [id];
        submitGroups(groups);
      });
      actions.appendChild(one);
    }
    row.appendChild(actions);
    list.appendChild(row);
  }

  function renderAccount(root, account, config) {
    var preview = previewOf(account);
    if (!preview.length) return 0;
    var ready = isReady(account, config);
    var state = uiState(account, ready);
    var section = el('section', 'phase5-vacancy-account');
    section.setAttribute('data-testid', 'phase5-vacancy-account-' + account.idx);

    var head = el('div', 'phase5-vacancy-account-head');
    var title = el('div', 'phase5-vacancy-account-name', account.short || account.name || ('Аккаунт #' + account.idx));
    head.appendChild(title);
    head.appendChild(metaChip(ready ? 'Готово к подтверждению' : 'Список не готов к отправке', ready ? 'safe' : 'waiting'));
    section.appendChild(head);

    var queueTotal = Math.max(Number(account.total_vacancies) || 0, preview.length);
    var truncated = queueTotal > preview.length;
    var hint = ready
      ? 'Выберите вакансии и подтвердите отклик. Новый поиск не запускается.'
      : 'Отправка доступна только после завершённого safe search, когда аккаунт стоит на паузе «search_only».';
    if (truncated) {
      hint += ' Показаны первые ' + preview.length + ' из ' + queueTotal + ': выбор относится только к показанным вакансиям.';
    }
    section.appendChild(el('div', 'phase5-vacancy-account-hint', hint));
    if (truncated) {
      var allQueue = el('button', 'phase5-vacancy-secondary', 'Откликнуться на весь список (' + queueTotal + ')');
      allQueue.type = 'button';
      allQueue.disabled = !ready;
      allQueue.setAttribute('data-testid', 'phase5-vacancy-apply-all-' + account.idx);
      allQueue.addEventListener('click', function () {
        if (!ready) return;
        var ok = window.confirm('Откликнуться на весь текущий safe-search список из ' + queueTotal + ' вакансий? Повторного поиска не будет. Все лимиты и safety-проверки останутся включены.');
        if (ok && typeof window.sendCmd === 'function') window.sendCmd({ type: 'apply_search_results', idx: Number(account.idx) });
      });
      section.appendChild(allQueue);
    }

    var list = el('div', 'phase5-vacancy-list');
    preview.forEach(function (item) { renderVacancyRow(list, account, item, state, ready); });
    if (!list.children.length) list.appendChild(el('div', 'phase5-vacancy-empty', 'По текущему фильтру вакансий не видно. Измените поиск или включите показ скрытых.'));
    section.appendChild(list);
    root.appendChild(section);
    return preview.length;
  }

  function render(snap) {
    snap = snap || snapshot();
    if (!snap) return;
    lastSnapshot = snap;
    var root = buildRoot();
    if (!root) return;
    root.textContent = '';
    toolbar(root, snap);

    var body = el('div', 'phase5-vacancy-workspace-body');
    var config = snap.config || {};
    var total = 0;
    (snap.accounts || []).forEach(function (account) {
      total += renderAccount(body, account, config);
    });
    if (!total) {
      var empty = el('div', 'phase5-vacancy-empty');
      empty.appendChild(el('strong', '', 'Безопасный список пока пуст.'));
      empty.appendChild(document.createTextNode(' Сначала запустите safe search. После завершения найденные вакансии появятся здесь и останутся тем же списком до явного подтверждения.'));
      body.appendChild(empty);
    }
    root.appendChild(body);
  }

  function init() {
    render(snapshot());
    if (HHUI.core && typeof HHUI.core.on === 'function') {
      HHUI.core.on('hh:snapshot', function (event) { render(event.detail && event.detail.snapshot); });
      HHUI.core.on('hh:tabchange', function (event) {
        if (event.detail && event.detail.section === 'vacancies') render(snapshot());
      });
    }
  }

  HHUI.vacancies = {
    render: render,
    selectedGroups: function () { return selectedGroups(lastSnapshot || snapshot() || {}); },
    applySelected: function () { submitGroups(selectedGroups(lastSnapshot || snapshot() || {})); }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
