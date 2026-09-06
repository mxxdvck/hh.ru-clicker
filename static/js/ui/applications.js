(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.applications) return;

  var CACHE_MS = 30000;
  var cache = Object.create(null);
  var lastSnapshot = null;
  var accountFilter = 'all';

  function snapshot() {
    return HHUI.core && typeof HHUI.core.snapshot === 'function'
      ? HHUI.core.snapshot() : null;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function panel() {
    return document.getElementById('panel-applied');
  }

  function accountsOf(snap) {
    return Array.isArray(snap && snap.accounts) ? snap.accounts : [];
  }

  function selectedAccounts(snap) {
    var accounts = accountsOf(snap);
    if (accountFilter === 'all') return accounts;
    return accounts.filter(function (account) {
      return String(account.idx) === accountFilter;
    });
  }

  function getCached(idx) {
    var entry = cache[String(idx)];
    return entry && entry.data ? entry.data : null;
  }

  function formatValue(value) {
    return value === null || value === undefined ? 'нет данных' : String(value);
  }

  function sumKnown(values) {
    if (!values.length || values.some(function (value) { return value === null || value === undefined; })) return null;
    return values.reduce(function (sum, value) { return sum + Number(value || 0); }, 0);
  }

  function aggregate(snap) {
    var accounts = selectedAccounts(snap);
    var summaries = accounts.map(function (account) { return getCached(account.idx); });
    var settled = summaries.filter(Boolean);
    var ready = settled.filter(function (item) { return item.ok !== false; });
    var errors = settled.length - ready.length;
    var ledgerKeys = ['applying', 'applied', 'already', 'interrupted', 'failed_transient', 'failed_permanent'];
    var ledger = Object.create(null);
    ledgerKeys.forEach(function (key) {
      ledger[key] = ready.reduce(function (sum, item) {
        return sum + Number(item.ledger && item.ledger.statuses && item.ledger.statuses[key] || 0);
      }, 0);
    });

    var applied = sumKnown(ready.map(function (item) { return item.outcome && item.outcome.applied; }));
    var interviews = sumKnown(ready.map(function (item) { return item.outcome && item.outcome.interviews; }));
    var conversion = applied && interviews !== null ? Math.round(interviews * 1000 / applied) / 10 : (applied === 0 ? 0 : null);
    return {
      accounts: accounts,
      loaded: ready.length,
      settled: settled.length,
      errors: errors,
      found: sumKnown(ready.map(function (item) { return item.cycle && item.cycle.found; })),
      filtered: sumKnown(ready.map(function (item) { return item.cycle && item.cycle.filtered; })),
      queue: sumKnown(ready.map(function (item) { return item.cycle && item.cycle.queue; })),
      sentToday: sumKnown(ready.map(function (item) { return item.cycle && item.cycle.sent_today; })),
      applied: applied,
      viewed: sumKnown(ready.map(function (item) { return item.outcome && item.outcome.viewed; })),
      interviews: interviews,
      conversion: conversion,
      ledger: ledger
    };
  }

  function ensureRoot() {
    var target = panel();
    if (!target) return null;
    var root = document.getElementById('phase5-applications-summary');
    if (root) return root;
    root = el('section', 'phase5-applications-summary');
    root.id = 'phase5-applications-summary';
    root.setAttribute('data-testid', 'phase5-applications-summary');
    root.setAttribute('aria-label', 'Воронка и надёжность откликов');
    target.insertBefore(root, target.firstChild);
    return root;
  }

  function metric(label, value, note, kind) {
    var card = el('div', 'phase5-app-metric');
    if (kind) card.setAttribute('data-kind', kind);
    card.appendChild(el('div', 'phase5-app-metric-label', label));
    card.appendChild(el('div', 'phase5-app-metric-value', formatValue(value)));
    if (note) card.appendChild(el('div', 'phase5-app-metric-note', note));
    return card;
  }

  function section(title, note) {
    var block = el('section', 'phase5-app-block');
    var head = el('div', 'phase5-app-block-head');
    head.appendChild(el('div', 'phase5-app-block-title', title));
    if (note) head.appendChild(el('div', 'phase5-app-block-note', note));
    block.appendChild(head);
    return block;
  }

  function renderHeader(root, snap, data) {
    var header = el('div', 'phase5-app-head');
    var copy = el('div', 'phase5-app-head-copy');
    copy.appendChild(el('h2', 'phase5-app-title', 'Отклики и результат'));
    copy.appendChild(el('div', 'phase5-app-subtitle', 'Текущий цикл, фактические результаты и durable-состояние отправки.'));
    header.appendChild(copy);

    var controls = el('div', 'phase5-app-controls');
    var select = document.createElement('select');
    select.setAttribute('data-testid', 'phase5-app-account-filter');
    var all = document.createElement('option');
    all.value = 'all';
    all.textContent = 'Все аккаунты';
    select.appendChild(all);
    accountsOf(snap).forEach(function (account) {
      var option = document.createElement('option');
      option.value = String(account.idx);
      option.textContent = account.short || account.name || ('Аккаунт #' + account.idx);
      select.appendChild(option);
    });
    select.value = accountFilter;
    select.addEventListener('change', function () {
      accountFilter = select.value;
      render(lastSnapshot || snapshot());
      ensureLoaded(lastSnapshot || snapshot(), false);
    });
    controls.appendChild(select);

    var refresh = el('button', 'phase5-app-refresh', 'Обновить');
    refresh.type = 'button';
    refresh.setAttribute('data-testid', 'phase5-app-refresh');
    refresh.addEventListener('click', function () { ensureLoaded(lastSnapshot || snapshot(), true); });
    controls.appendChild(refresh);
    header.appendChild(controls);
    root.appendChild(header);
  }

  function resolved(data, value) {
    return data.accounts.length && data.settled === data.accounts.length && data.errors === 0 ? value : null;
  }

  function renderCycle(root, data) {
    var block = section('Текущий цикл', 'Live snapshot. Эти числа относятся к текущему рабочему циклу.');
    var grid = el('div', 'phase5-app-grid');
    grid.appendChild(metric('Найдено', resolved(data, data.found), 'до фильтрации'));
    grid.appendChild(metric('Прошло фильтры', resolved(data, data.filtered), 'accepted'));
    grid.appendChild(metric('Safe queue', resolved(data, data.queue), 'текущая очередь'));
    grid.appendChild(metric('Отправлено сегодня', resolved(data, data.sentToday), 'по выбранным аккаунтам'));
    block.appendChild(grid);
    root.appendChild(block);
  }

  function renderOutcome(root, data) {
    var block = section('Результат', 'История откликов и статистика HH. Окно данных отличается от текущего цикла.');
    var grid = el('div', 'phase5-app-grid');
    grid.appendChild(metric('Отклики', resolved(data, data.applied), 'локальная история', 'safe'));
    grid.appendChild(metric('Просмотрено HH', resolved(data, data.viewed), 'нет данных, пока HH-статистика не загружена'));
    grid.appendChild(metric('Интервью', resolved(data, data.interviews), 'local + HH counter', 'safe'));
    var conv = resolved(data, data.conversion);
    grid.appendChild(metric('Конверсия', conv === null ? null : conv + '%', 'интервью / отклики'));
    block.appendChild(grid);
    root.appendChild(block);
  }

  function renderReliability(root, data) {
    var block = section('Надёжность отправки', 'Durable ledger. Здесь видны незавершённые и проблемные состояния.');
    var grid = el('div', 'phase5-app-grid phase5-app-grid-reliability');
    var complete = data.accounts.length && data.settled === data.accounts.length && data.errors === 0;
    var value = function (key) { return complete ? Number(data.ledger[key] || 0) : null; };
    grid.appendChild(metric('В отправке', value('applying'), 'зарезервировано', 'info'));
    grid.appendChild(metric('Interrupted', value('interrupted'), 'требует reconciliation', value('interrupted') ? 'danger' : 'safe'));
    grid.appendChild(metric('Transient fail', value('failed_transient'), 'может быть повторено позже', value('failed_transient') ? 'warning' : 'safe'));
    grid.appendChild(metric('Permanent fail', value('failed_permanent'), 'не ретраить автоматически', value('failed_permanent') ? 'danger' : 'safe'));
    grid.appendChild(metric('Already', value('already'), 'HH уже видел отклик'));
    grid.appendChild(metric('Applied ledger', value('applied'), 'durable confirmed', 'safe'));
    block.appendChild(grid);
    root.appendChild(block);
  }

  function renderStatus(root, data) {
    var status = el('div', 'phase5-app-data-note');
    status.setAttribute('data-testid', 'phase5-app-data-note');
    if (!data.accounts.length) {
      status.textContent = 'Нет аккаунтов для расчёта.';
    } else if (data.errors) {
      status.textContent = 'Не удалось загрузить фактические данные для ' + data.errors + ' аккаунт(ов). Агрегированные значения скрыты.';
    } else if (data.settled !== data.accounts.length) {
      status.textContent = 'Загружаю фактические данные: ' + data.settled + '/' + data.accounts.length + ' аккаунтов.';
    } else {
      status.textContent = 'Важно: текущий цикл и итоговая история имеют разные окна данных. Не трактуйте всю строку как одну сквозную конверсию.';
    }
    root.appendChild(status);
  }

  function loadAccount(account, force) {
    var key = String(account.idx);
    var current = cache[key];
    if (!force && current && current.data && Date.now() - current.at < CACHE_MS) {
      return Promise.resolve(current.data);
    }
    if (!force && current && current.promise) return current.promise;

    var promise = fetch('/api/account/' + encodeURIComponent(key) + '/operations_summary')
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data || data.ok === false) throw new Error(data && data.error || 'Недоступно');
        cache[key] = { at: Date.now(), data: data, promise: null };
        return data;
      })
      .catch(function (error) {
        cache[key] = { at: Date.now(), data: { ok: false, error: String(error && error.message || error) }, promise: null };
        return cache[key].data;
      });
    cache[key] = { at: current && current.at || 0, data: current && current.data || null, promise: promise };
    return promise;
  }

  function ensureLoaded(snap, force) {
    snap = snap || snapshot();
    if (!snap) return Promise.resolve();
    var accounts = selectedAccounts(snap);
    return Promise.all(accounts.map(function (account) { return loadAccount(account, !!force); }))
      .then(function () { render(lastSnapshot || snap); });
  }

  function render(snap) {
    snap = snap || snapshot();
    if (!snap) return;
    lastSnapshot = snap;
    var root = ensureRoot();
    if (!root) return;
    root.textContent = '';
    var data = aggregate(snap);
    renderHeader(root, snap, data);
    renderCycle(root, data);
    renderOutcome(root, data);
    renderReliability(root, data);
    renderStatus(root, data);
  }

  function init() {
    lastSnapshot = snapshot();
    render(lastSnapshot);
    if (HHUI.core && typeof HHUI.core.on === 'function') {
      HHUI.core.on('hh:snapshot', function (event) {
        lastSnapshot = event.detail && event.detail.snapshot || snapshot();
        render(lastSnapshot);
      });
      HHUI.core.on('hh:tabchange', function (event) {
        var detail = event.detail || {};
        if (detail.section === 'applications' && detail.tab === 'applied') {
          render(lastSnapshot || snapshot());
          ensureLoaded(lastSnapshot || snapshot(), false);
        }
      });
    }
    var applied = document.getElementById('panel-applied');
    if (applied && applied.classList.contains('active')) ensureLoaded(lastSnapshot, false);
  }

  HHUI.applications = {
    render: render,
    refresh: function () { return ensureLoaded(lastSnapshot || snapshot(), true); }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
