(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.review) return;

  var CACHE_MS = 30000;
  var cache = { at: 0, rows: null, promise: null, error: '' };
  var accountFilter = '';
  var categoryFilter = '';
  var sourceFilter = '';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function panel() {
    return document.getElementById('panel-llm');
  }

  function isReview(row) {
    if (!row || row.status !== 'draft') return false;
    var source = String(row.llm_source || '').toLowerCase();
    var reason = String(row.llm_review_reason || '').trim();
    return source.indexOf('review') >= 0 || !!reason;
  }

  function reviewRows() {
    return (Array.isArray(cache.rows) ? cache.rows : []).filter(isReview);
  }

  function filteredRows() {
    return reviewRows().filter(function (row) {
      if (accountFilter && String(row.acc || '') !== accountFilter) return false;
      if (categoryFilter && String(row.llm_category || 'review') !== categoryFilter) return false;
      if (sourceFilter && String(row.llm_source || '') !== sourceFilter) return false;
      return true;
    });
  }

  function uniqueValues(rows, key, fallback) {
    var seen = Object.create(null);
    rows.forEach(function (row) {
      var value = String(row[key] || fallback || '').trim();
      if (value) seen[value] = true;
    });
    return Object.keys(seen).sort(function (a, b) { return a.localeCompare(b, 'ru'); });
  }

  function ensureRoot() {
    var target = panel();
    if (!target) return null;
    var root = document.getElementById('phase5-review-center');
    if (root) return root;
    root = el('section', 'phase5-review-center');
    root.id = 'phase5-review-center';
    root.setAttribute('data-testid', 'phase5-review-center');
    root.setAttribute('aria-label', 'Ответы, требующие ручной проверки');
    target.insertBefore(root, target.firstChild);
    return root;
  }

  function option(value, label) {
    var node = document.createElement('option');
    node.value = value;
    node.textContent = label;
    return node;
  }

  function addFilters(head, rows) {
    var controls = el('div', 'phase5-review-controls');

    var acc = document.createElement('select');
    acc.setAttribute('data-testid', 'phase5-review-account-filter');
    acc.appendChild(option('', 'Все аккаунты'));
    uniqueValues(rows, 'acc').forEach(function (value) { acc.appendChild(option(value, value)); });
    acc.value = accountFilter;
    acc.addEventListener('change', function () { accountFilter = acc.value; render(); });
    controls.appendChild(acc);

    var cat = document.createElement('select');
    cat.setAttribute('data-testid', 'phase5-review-category-filter');
    cat.appendChild(option('', 'Все категории'));
    uniqueValues(rows, 'llm_category', 'review').forEach(function (value) { cat.appendChild(option(value, value)); });
    cat.value = categoryFilter;
    cat.addEventListener('change', function () { categoryFilter = cat.value; render(); });
    controls.appendChild(cat);

    var source = document.createElement('select');
    source.setAttribute('data-testid', 'phase5-review-source-filter');
    source.appendChild(option('', 'Все источники'));
    uniqueValues(rows, 'llm_source', 'review').forEach(function (value) { source.appendChild(option(value, value)); });
    source.value = sourceFilter;
    source.addEventListener('change', function () { sourceFilter = source.value; render(); });
    controls.appendChild(source);

    var refresh = el('button', 'phase5-review-refresh', 'Обновить');
    refresh.type = 'button';
    refresh.setAttribute('data-testid', 'phase5-review-refresh');
    refresh.addEventListener('click', function () { load(true); });
    controls.appendChild(refresh);
    head.appendChild(controls);
  }

  function hhChatUrl(row) {
    var id = String(row && row.neg_id || '').trim();
    return id ? 'https://hh.ru/chat/' + encodeURIComponent(id) : '';
  }

  function copyDraft(text, button) {
    var value = String(text || '');
    if (!value) return;
    var done = function () {
      var old = button.textContent;
      button.textContent = 'Скопировано';
      window.setTimeout(function () { button.textContent = old; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done).catch(function () {});
      return;
    }
    var area = document.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); done(); } catch (_) {}
    area.remove();
  }

  function metaChip(text, kind) {
    var chip = el('span', 'phase5-review-chip', text);
    if (kind) chip.setAttribute('data-kind', kind);
    return chip;
  }

  function reviewCard(row) {
    var card = el('article', 'phase5-review-card');
    card.setAttribute('data-testid', 'phase5-review-card');
    card.setAttribute('data-review-source', String(row.llm_source || ''));
    card.setAttribute('data-review-category', String(row.llm_category || 'review'));

    var top = el('div', 'phase5-review-card-top');
    var title = el('div', 'phase5-review-card-title', row.employer || 'Работодатель');
    top.appendChild(title);
    var meta = el('div', 'phase5-review-card-meta');
    meta.appendChild(metaChip(row.acc || 'аккаунт'));
    meta.appendChild(metaChip(row.llm_category || 'review', 'warning'));
    meta.appendChild(metaChip(row.llm_source || 'review'));
    top.appendChild(meta);
    card.appendChild(top);

    if (row.vacancy_title) card.appendChild(el('div', 'phase5-review-vacancy', row.vacancy_title));
    var reason = String(row.llm_review_reason || '').trim();
    card.appendChild(el('div', 'phase5-review-reason', reason || 'Policy требует ручной проверки перед отправкой.'));

    if (row.employer_last_msg) {
      var employer = el('div', 'phase5-review-message');
      employer.appendChild(el('div', 'phase5-review-label', 'Сообщение работодателя'));
      employer.appendChild(el('div', 'phase5-review-text', String(row.employer_last_msg)));
      card.appendChild(employer);
    }

    if (row.llm_reply) {
      var draft = el('div', 'phase5-review-message');
      draft.appendChild(el('div', 'phase5-review-label', 'Черновик ответа'));
      draft.appendChild(el('div', 'phase5-review-text phase5-review-draft', String(row.llm_reply)));
      card.appendChild(draft);
    }

    var actions = el('div', 'phase5-review-actions');
    if (row.llm_reply) {
      var copy = el('button', 'phase5-review-copy', 'Копировать черновик');
      copy.type = 'button';
      copy.setAttribute('data-testid', 'phase5-review-copy');
      copy.addEventListener('click', function () { copyDraft(row.llm_reply, copy); });
      actions.appendChild(copy);
    }
    var chat = hhChatUrl(row);
    if (chat) {
      var link = el('a', 'phase5-review-open', 'Открыть чат HH');
      link.href = chat;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.setAttribute('data-testid', 'phase5-review-open-chat');
      actions.appendChild(link);
    }
    card.appendChild(actions);

    var date = String(row.last_seen || row.first_seen || '').replace('T', ' ').slice(0, 16);
    if (date) card.appendChild(el('div', 'phase5-review-date', date));
    return card;
  }

  function render() {
    var root = ensureRoot();
    if (!root) return;
    root.textContent = '';
    var reviews = reviewRows();
    var accounts = uniqueValues(reviews, 'acc');
    var categories = uniqueValues(reviews, 'llm_category', 'review');
    var sources = uniqueValues(reviews, 'llm_source', 'review');
    if (accountFilter && accounts.indexOf(accountFilter) < 0) accountFilter = '';
    if (categoryFilter && categories.indexOf(categoryFilter) < 0) categoryFilter = '';
    if (sourceFilter && sources.indexOf(sourceFilter) < 0) sourceFilter = '';
    var visible = filteredRows();

    var head = el('div', 'phase5-review-head');
    var copy = el('div', 'phase5-review-head-copy');
    copy.appendChild(el('h2', 'phase5-review-title', 'Нужно проверить'));
    copy.appendChild(el('div', 'phase5-review-subtitle', 'Только ответы, которые safety-policy запретила отправлять автоматически.'));
    head.appendChild(copy);
    addFilters(head, reviews);
    root.appendChild(head);

    var count = el('div', 'phase5-review-count', visible.length + ' на проверку');
    count.setAttribute('data-testid', 'phase5-review-count');
    root.appendChild(count);

    var body = el('div', 'phase5-review-list');
    if (cache.error) {
      body.appendChild(el('div', 'phase5-review-empty phase5-review-error', 'Не удалось загрузить review: ' + cache.error));
    } else if (!cache.rows) {
      body.appendChild(el('div', 'phase5-review-empty', 'Загружаю persisted review…'));
    } else if (!reviews.length) {
      body.appendChild(el('div', 'phase5-review-empty', 'Сейчас нет ответов, требующих ручной проверки.'));
    } else if (!visible.length) {
      body.appendChild(el('div', 'phase5-review-empty', 'По выбранным фильтрам review-записей нет.'));
    } else {
      visible.forEach(function (row) { body.appendChild(reviewCard(row)); });
    }
    root.appendChild(body);
  }

  function load(force) {
    if (!force && cache.rows && Date.now() - cache.at < CACHE_MS) {
      render();
      return Promise.resolve(cache.rows);
    }
    if (!force && cache.promise) return cache.promise;

    var promise = fetch('/api/interviews?status=draft&limit=5000')
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (rows) {
        cache.rows = Array.isArray(rows) ? rows : [];
        cache.at = Date.now();
        cache.promise = null;
        cache.error = '';
        render();
        return cache.rows;
      })
      .catch(function (error) {
        cache.rows = [];
        cache.at = Date.now();
        cache.promise = null;
        cache.error = String(error && error.message || error || 'Недоступно');
        render();
        return [];
      });
    cache.promise = promise;
    return promise;
  }

  function init() {
    render();
    if (HHUI.core && typeof HHUI.core.on === 'function') {
      HHUI.core.on('hh:tabchange', function (event) {
        var detail = event.detail || {};
        if (detail.section === 'communications' && detail.tab === 'llm') load(false);
      });
      HHUI.core.on('hh:snapshot', function () {
        var target = panel();
        if (target && target.classList.contains('active')) load(false);
      });
    }
    var target = panel();
    if (target && target.classList.contains('active')) load(false);
  }

  HHUI.review = {
    render: render,
    refresh: function () { return load(true); },
    rows: function () { return reviewRows().slice(); }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
