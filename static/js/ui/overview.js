(function () {
  'use strict';

  var HHUI = window.HHUI = window.HHUI || {};
  if (HHUI.overview) return;

  var reviewSummary = null;
  var reviewFetchedAt = 0;
  var reviewInflight = null;
  var lastSnapshot = null;
  var renderFrame = 0;
  var REVIEW_TTL_MS = 60000;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function number(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function sumKnown(items, field) {
    if (!items.length) return null;
    var total = 0;
    for (var i = 0; i < items.length; i++) {
      var n = number(items[i] && items[i][field]);
      if (n === null) return null;
      total += n;
    }
    return total;
  }

  function fmt(value) {
    return value === null || value === undefined ? 'нет данных' : Number(value).toLocaleString('ru-RU');
  }

  function accountsOf(snapshot) {
    return Array.isArray(snapshot && snapshot.accounts)
      ? snapshot.accounts.filter(function (account) { return account && !account._deleted; })
      : [];
  }

  function effectiveMode(account, config) {
    return String((account && account.mode) || (config && config.default_client_mode) || 'web');
  }

  function fallbackReviewCount(snapshot) {
    var rows = Array.isArray(snapshot && snapshot.llm_log) ? snapshot.llm_log : [];
    return rows.filter(function (row) {
      return row && !row.sent && String(row.source || '').indexOf('review') >= 0;
    }).length;
  }

  function reviewCount(snapshot) {
    var persisted = number(reviewSummary && reviewSummary.reviews);
    var fallback = fallbackReviewCount(snapshot);
    return persisted === null ? fallback : Math.max(fallback, Math.max(0, persisted));
  }

  function fetchReviewSummary(force) {
    var fresh = reviewFetchedAt && Date.now() - reviewFetchedAt < REVIEW_TTL_MS;
    if (!force && fresh) return Promise.resolve(reviewSummary);
    if (reviewInflight) return reviewInflight;

    reviewInflight = fetch('/api/interviews/summary')
      .then(function (response) {
        if (!response.ok) throw new Error('summary HTTP ' + response.status);
        return response.json();
      })
      .then(function (data) {
        reviewSummary = data && typeof data === 'object' ? data : null;
        reviewFetchedAt = Date.now();
        scheduleRender(lastSnapshot || currentSnapshot());
        return reviewSummary;
      })
      .catch(function () {
        reviewFetchedAt = Date.now();
        return reviewSummary;
      })
      .finally(function () { reviewInflight = null; });
    return reviewInflight;
  }

  function currentSnapshot() {
    return HHUI.core && typeof HHUI.core.snapshot === 'function'
      ? HHUI.core.snapshot()
      : null;
  }

  function kpis(snapshot) {
    var config = (snapshot && snapshot.config) || {};
    var accounts = accountsOf(snapshot);
    var stats = (snapshot && snapshot.global_stats) || {};
    var queues = (snapshot && snapshot.vacancy_queues) || {};

    var dailyUsed = sumKnown(accounts, 'daily_sent');
    var dailyPerAccount = number(config.daily_apply_limit);
    var dailyEffective = dailyPerAccount !== null && dailyPerAccount > 0
      ? dailyPerAccount * accounts.length
      : null;
    var dailyRemaining = dailyEffective !== null && dailyUsed !== null
      ? Math.max(0, dailyEffective - dailyUsed)
      : null;

    var runUsed = sumKnown(accounts, 'sent');
    var runPerAccount = number(config.run_apply_limit);
    var runEffective = runPerAccount !== null && runPerAccount > 0
      ? runPerAccount * accounts.length
      : null;

    var queued = 0;
    var queueKnown = false;
    Object.keys(queues).forEach(function (key) {
      var remaining = number(queues[key] && queues[key].remaining);
      if (remaining !== null) {
        queueKnown = true;
        queued += remaining;
      }
    });

    return [
      {
        id: 'today',
        label: 'Отклики сегодня',
        value: dailyUsed === null ? null : dailyUsed,
        note: dailyPerAccount && accounts.length
          ? 'лимит ' + dailyPerAccount + ' на аккаунт'
          : 'лимит не задан'
      },
      {
        id: 'remaining',
        label: 'Осталось сегодня',
        value: dailyPerAccount && accounts.length ? dailyRemaining : 'Без лимита',
        note: dailyEffective !== null ? 'общий доступный лимит ' + dailyEffective : ''
      },
      {
        id: 'run',
        label: 'Этот запуск',
        value: runUsed,
        note: runEffective !== null ? 'лимит запуска ' + runEffective : 'без лимита запуска'
      },
      {
        id: 'found',
        label: 'Найдено',
        value: number(stats.total_found),
        note: 'счётчик текущей сессии'
      },
      {
        id: 'queued',
        label: 'В очереди',
        value: queueKnown ? queued : null,
        note: 'готовы к дальнейшей обработке'
      },
      {
        id: 'filtered',
        label: 'Отфильтровано',
        value: null,
        note: 'агрегат пока не доказуем snapshot-ом'
      },
      {
        id: 'review',
        label: 'На проверке',
        value: reviewCount(snapshot),
        note: 'persisted review + live fallback'
      },
      {
        id: 'errors',
        label: 'Ошибки',
        value: number(stats.total_errors),
        note: 'счётчик текущей сессии'
      }
    ];
  }

  function modeInfo(snapshot) {
    var config = (snapshot && snapshot.config) || {};
    var accounts = accountsOf(snapshot);
    var allPaused = !!(snapshot && snapshot.paused) || (accounts.length > 0 && accounts.every(function (a) { return !!a.paused; }));
    if (allPaused) return { kind: 'paused', text: '⏸ Все на паузе' };
    if (config.search_only_mode === true) return { kind: 'search', text: '⌕ Только безопасный поиск' };
    return { kind: 'active', text: '● Отклики разрешены' };
  }

  function navigate(section, tab) {
    if (HHUI.navigation && typeof HHUI.navigation.navigate === 'function') {
      HHUI.navigation.navigate(section, tab || null, { source: 'overview-action' });
    }
  }

  function openSettings(group, sectionId) {
    navigate('settings', 'settings');
    window.setTimeout(function () {
      if (HHUI.settings && typeof HHUI.settings.setGroup === 'function') HHUI.settings.setGroup(group || 'all');
      if (sectionId) {
        var target = document.getElementById(sectionId);
        if (target) {
          target.hidden = false;
          if ('open' in target) target.open = true;
          target.scrollIntoView({ block: 'start' });
        }
      }
    }, 0);
  }

  function attentionItems(snapshot) {
    var config = (snapshot && snapshot.config) || {};
    var accounts = accountsOf(snapshot);
    var items = [];
    var persistedReviews = reviewCount(snapshot);

    if (!accounts.length) {
      items.push({
        key: 'no-accounts', severity: 'high', title: 'Нет подключённых аккаунтов',
        reason: 'Без аккаунта поиск и отклики не запустятся.', action: 'Открыть вход',
        run: function () { openSettings('connection', 'mobile-auth-section'); }
      });
    }

    if (persistedReviews > 0) {
      items.push({
        key: 'review', severity: 'warning', title: persistedReviews + ' ответов требуют проверки',
        reason: 'Auto safe не отправил их автоматически. Review сохраняется между перезапусками.',
        action: 'Проверить', run: function () { navigate('communications', 'llm'); }
      });
    }

    accounts.forEach(function (account) {
      var name = account.short || account.name || ('Аккаунт #' + account.idx);
      var mode = effectiveMode(account, config);
      var oauth = account.oauth_status || {};
      var dailyLimit = number(config.daily_apply_limit);
      var dailySent = number(account.daily_sent);
      var hhLimit = number(account.hh_daily_limit) || number(config.hh_daily_limit);
      var hhUsed = number(account.hh_today_applies);

      if (account.cookies_expired) {
        items.push({
          key: 'cookies-' + account.idx, severity: 'high', title: name + ': cookies истекли',
          reason: 'Web-сессия HH требует обновления cookies.', action: 'Исправить',
          run: function () { openSettings('connection'); }
        });
      }

      if ((config.use_oauth_apply === true || mode === 'oauth') && !oauth.has_token) {
        items.push({
          key: 'oauth-' + account.idx, severity: 'high', title: name + ': нет OAuth-токена',
          reason: 'Выбран режим, которому нужен OAuth для отправки откликов.', action: 'Открыть вход',
          run: function () { openSettings('connection', 'mobile-auth-section'); }
        });
      }

      if (account.hard_stopped) {
        items.push({
          key: 'hard-stop-' + account.idx, severity: 'high', title: name + ': работа остановлена',
          reason: account.paused_reason || 'Аккаунт требует ручного вмешательства перед продолжением.',
          action: 'К аккаунту', run: function () { scrollToLegacyAccount(account.idx); }
        });
      } else if (account.paused) {
        items.push({
          key: 'paused-' + account.idx, severity: 'warning', title: name + ': на паузе',
          reason: account.paused_reason || 'Аккаунт временно не обрабатывает вакансии.',
          action: 'К аккаунту', run: function () { scrollToLegacyAccount(account.idx); }
        });
      }

      if (account.limit_exceeded || (dailyLimit && dailySent !== null && dailySent >= dailyLimit)) {
        items.push({
          key: 'daily-limit-' + account.idx, severity: 'warning', title: name + ': дневной лимит исчерпан',
          reason: dailySent !== null && dailyLimit ? dailySent + ' из ' + dailyLimit + ' откликов.' : 'Лимит отмечен backend-ом.',
          action: 'Лимиты', run: function () { openSettings('search'); }
        });
      }

      if (hhLimit && hhUsed !== null && hhUsed >= hhLimit) {
        items.push({
          key: 'hh-limit-' + account.idx, severity: 'warning', title: name + ': достигнут лимит HH',
          reason: hhUsed + ' из ' + hhLimit + ' по счётчику HH.', action: 'HH статус',
          run: function () { navigate('applications', 'hh'); }
        });
      }

      if (number(account.hh_unread_by_employer) > 0) {
        items.push({
          key: 'unread-' + account.idx, severity: 'info', title: name + ': новые сообщения работодателей',
          reason: account.hh_unread_by_employer + ' чатов ждут внимания.', action: 'Открыть AI',
          run: function () { navigate('communications', 'llm'); }
        });
      }

      if (number(account.resume_invitations_new) > 0 || number(account.resume_new_invitations_total) > 0) {
        var invitations = Math.max(number(account.resume_invitations_new) || 0, number(account.resume_new_invitations_total) || 0);
        items.push({
          key: 'invite-' + account.idx, severity: 'info', title: name + ': новые приглашения',
          reason: invitations + ' новых приглашений по резюме.', action: 'HH статус',
          run: function () { navigate('applications', 'hh'); }
        });
      }
    });

    var weight = { high: 0, warning: 1, info: 2 };
    items.sort(function (a, b) { return (weight[a.severity] || 9) - (weight[b.severity] || 9); });
    return items;
  }

  function scrollToLegacyAccount(idx) {
    navigate('overview', 'main');
    window.setTimeout(function () {
      var target = document.getElementById('card-' + idx);
      if (target) target.scrollIntoView({ block: 'center' });
    }, 0);
  }

  function buildRoot() {
    var panel = document.getElementById('panel-main');
    if (!panel) return null;
    var existing = document.getElementById('phase5-overview');
    if (existing) return existing;

    var root = el('section', 'phase5-overview');
    root.id = 'phase5-overview';
    root.setAttribute('data-testid', 'phase5-overview');
    root.setAttribute('aria-label', 'Операционный обзор');
    panel.insertBefore(root, panel.firstChild);
    return root;
  }

  function renderKpis(container, snapshot) {
    var grid = el('div', 'phase5-kpi-grid');
    grid.setAttribute('data-testid', 'phase5-kpi-grid');
    kpis(snapshot).forEach(function (item) {
      var card = el('div', 'phase5-kpi-card');
      card.setAttribute('data-kpi', item.id);
      card.setAttribute('data-testid', 'phase5-kpi-' + item.id);
      card.appendChild(el('div', 'phase5-kpi-label', item.label));
      var value = el('div', 'phase5-kpi-value');
      if (item.value === null || item.value === undefined) {
        value.textContent = 'нет данных';
        value.classList.add('phase5-unknown');
      } else if (typeof item.value === 'number') {
        value.textContent = fmt(item.value);
      } else {
        value.textContent = String(item.value);
      }
      card.appendChild(value);
      card.appendChild(el('div', 'phase5-kpi-note', item.note || ''));
      grid.appendChild(card);
    });
    container.appendChild(grid);
  }

  function renderAttention(container, snapshot) {
    var card = el('section', 'phase5-overview-card');
    card.setAttribute('data-testid', 'phase5-action-center');
    var head = el('div', 'phase5-overview-card-head');
    head.appendChild(el('div', 'phase5-overview-card-title', 'Нужно внимание'));
    var items = attentionItems(snapshot);
    head.appendChild(el('span', 'phase5-overview-count', items.length));
    card.appendChild(head);

    var list = el('div', 'phase5-attention-list');
    if (!items.length) {
      var empty = el('div', 'phase5-overview-empty', 'Сейчас нет подтверждённых проблем, требующих ручного действия. Новые review, лимиты и проблемы с авторизацией появятся здесь автоматически.');
      empty.setAttribute('data-testid', 'phase5-action-center-empty');
      list.appendChild(empty);
    } else {
      items.forEach(function (item) {
        var row = el('div', 'phase5-attention-item');
        row.dataset.severity = item.severity;
        row.dataset.actionKey = item.key;
        row.appendChild(el('span', 'phase5-severity-dot'));
        var copy = el('div');
        copy.appendChild(el('div', 'phase5-attention-title', item.title));
        copy.appendChild(el('div', 'phase5-attention-reason', item.reason));
        row.appendChild(copy);
        var button = el('button', 'phase5-action-btn', item.action);
        button.type = 'button';
        button.addEventListener('click', item.run);
        row.appendChild(button);
        list.appendChild(row);
      });
    }
    card.appendChild(list);
    container.appendChild(card);
  }

  function healthState(account) {
    if (account.hard_stopped || account.cookies_expired) return { state: 'error', text: '● Нужна помощь' };
    if (account.paused || number(account.consecutive_errors) > 0) return { state: 'warning', text: '● Внимание' };
    return { state: 'ok', text: '● В норме' };
  }

  function renderHealth(container, snapshot) {
    var config = (snapshot && snapshot.config) || {};
    var accounts = accountsOf(snapshot);
    var card = el('section', 'phase5-overview-card');
    card.setAttribute('data-testid', 'phase5-account-health');
    var head = el('div', 'phase5-overview-card-head');
    head.appendChild(el('div', 'phase5-overview-card-title', 'Аккаунты'));
    head.appendChild(el('span', 'phase5-overview-count', accounts.length));
    card.appendChild(head);

    var list = el('div', 'phase5-health-list');
    if (!accounts.length) {
      list.appendChild(el('div', 'phase5-overview-empty', 'Аккаунтов пока нет. Добавьте или авторизуйте аккаунт в настройках подключения.'));
    }

    accounts.forEach(function (account) {
      var row = el('div', 'phase5-health-card');
      row.setAttribute('data-account-idx', account.idx);
      row.setAttribute('data-testid', 'phase5-health-account-' + account.idx);

      var main = el('div', 'phase5-health-main');
      main.appendChild(el('div', 'phase5-health-name', account.name || account.short || ('Аккаунт #' + account.idx)));
      var hs = healthState(account);
      var status = el('span', 'phase5-health-state', hs.text);
      status.dataset.state = hs.state;
      main.appendChild(status);
      row.appendChild(main);

      var mode = effectiveMode(account, config);
      var oauth = account.oauth_status || {};
      var dailySent = number(account.daily_sent);
      var dailyLimit = number(config.daily_apply_limit);
      var remaining = dailyLimit && dailySent !== null ? Math.max(0, dailyLimit - dailySent) : null;
      var meta = el('div', 'phase5-health-meta');
      [
        ['Режим', mode],
        ['Сегодня', dailySent === null ? 'нет данных' : dailySent + (dailyLimit ? ' / ' + dailyLimit : '')],
        ['Осталось', remaining === null ? (dailyLimit ? 'нет данных' : 'без лимита') : remaining],
        ['OAuth', oauth.has_token ? 'есть' : 'нет'],
        ['WS', account.ws_status || 'по статусу ниже'],
        ['Ошибки подряд', number(account.consecutive_errors) === null ? 'нет данных' : account.consecutive_errors]
      ].forEach(function (pair) {
        var span = el('span');
        span.appendChild(el('strong', '', pair[0] + ': '));
        span.appendChild(document.createTextNode(String(pair[1])));
        meta.appendChild(span);
      });
      row.appendChild(meta);

      var action = el('button', 'phase5-action-btn', 'Открыть управление');
      action.type = 'button';
      action.style.marginTop = '8px';
      action.addEventListener('click', function () { scrollToLegacyAccount(account.idx); });
      row.appendChild(action);
      list.appendChild(row);
    });

    card.appendChild(list);
    container.appendChild(card);
  }

  function render(snapshot) {
    if (!snapshot) return;
    lastSnapshot = snapshot;
    var root = buildRoot();
    if (!root) return;
    root.replaceChildren();

    var top = el('div', 'phase5-overview-top');
    var copy = el('div');
    copy.appendChild(el('h2', 'phase5-overview-title', 'Операционный обзор'));
    copy.appendChild(el('div', 'phase5-overview-subtitle', 'Что происходит сейчас, сколько лимита осталось и где действительно нужно вмешательство.'));
    top.appendChild(copy);
    var mode = modeInfo(snapshot);
    var badge = el('div', 'phase5-mode-badge', mode.text);
    badge.dataset.kind = mode.kind;
    badge.setAttribute('data-testid', 'phase5-overview-mode');
    top.appendChild(badge);
    root.appendChild(top);

    renderKpis(root, snapshot);

    var columns = el('div', 'phase5-overview-columns');
    renderAttention(columns, snapshot);
    renderHealth(columns, snapshot);
    root.appendChild(columns);
  }

  function scheduleRender(snapshot) {
    if (snapshot) lastSnapshot = snapshot;
    if (renderFrame) return;
    renderFrame = window.requestAnimationFrame(function () {
      renderFrame = 0;
      render(lastSnapshot || currentSnapshot());
    });
  }

  function init() {
    scheduleRender(currentSnapshot());
    fetchReviewSummary(false);
    if (HHUI.core && typeof HHUI.core.on === 'function') {
      HHUI.core.on('hh:snapshot', function (event) {
        scheduleRender(event && event.detail && event.detail.snapshot ? event.detail.snapshot : currentSnapshot());
      });
      HHUI.core.on('hh:tabchange', function (event) {
        var detail = event && event.detail;
        if (detail && detail.section === 'overview') fetchReviewSummary(false);
      });
    }
  }

  HHUI.overview = {
    render: scheduleRender,
    refreshReview: function () { return fetchReviewSummary(true); },
    getReviewSummary: function () { return reviewSummary; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
