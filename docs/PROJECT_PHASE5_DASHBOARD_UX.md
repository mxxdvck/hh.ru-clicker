# Project Phase 5 - Dashboard UX & Operations

Статус: **ТЗ / planning**  
База аудита: `main` @ `42cc87cadb8901bc840e6e7126a15f20bf7fbfbe`  
Дата фиксации: 2026-09-06

> Важно: в `docs/ARCHITECTURE.md` уже существует историческая нумерация `Phase 0-5` для mobile API migration. Этот документ относится к **проектному роудмапу 1c-career** и не переименовывает старые mobile-фазы. В задачах и ветках использовать полное имя `Project Phase 5: Dashboard UX & Operations`.

## 1. Цель фазы

Сделать Dashboard понятным для ежедневной работы, добавить недостающие операционные функции и при этом **не переписывать работающий проект с нуля**.

Phase 5 должна превратить текущий интерфейс из набора технических экранов в рабочий пульт:

- сразу понятно, работает ли бот и что он сейчас делает;
- видно, что требует внимания пользователя;
- понятно, сколько вакансий найдено, отфильтровано, ждёт отправки и уже обработано;
- видно, почему вакансия пропущена или отправлена в review;
- безопасные действия доступны быстро, рискованные действия явно подтверждаются;
- настройки сгруппированы по смыслу, а технические детали не мешают ежедневной работе;
- все функции Phase 1-4 продолжают работать без изменения их safety-контрактов.

## 2. Жёсткие ограничения

1. **Никакого полного frontend rewrite.** Не переходить в Phase 5 на React/Vue/Next/Svelte и не заменять весь `static/index.html`/`static/js/app.js` одним большим коммитом.
2. **Не ломать API.** Существующие REST endpoints и WebSocket payload считаются совместимым контрактом. Новые endpoints добавляются, старые не удаляются и не переименовываются.
3. **Не ломать DOM-контракт.** Существующие `id`, используемые `app.js`, feature-модулями и E2E, сохраняются до отдельного cleanup после миграции.
4. **Не менять safety-логику Phase 1-4 ради UX.** UI не имеет права обходить `apply_safety`, application ledger, LLM policy, questionnaire fail-closed, human review и лимиты.
5. **Не сливать UX и бизнес-логику.** Новая визуальная оболочка должна читать/вызывать существующие безопасные backend-функции, а не дублировать их в JS.
6. **Каждый подэтап обратим.** Новая навигация/overview включаются отдельным UI-флагом или изолированным слоем, чтобы можно было откатить UI без отката ядра.
7. **Каждый подэтап проходит полный regression gate до merge.**

## 3. Текущий baseline

После Project Phase 4:

- `main`: `42cc87c`;
- backend CI: 1237 passed, 1 Windows-only test skipped;
- E2E: 101 passed;
- Ruff, compileall, public repo validator: green.

Ключевые размеры текущего frontend:

- `static/index.html` ~92 KB;
- `static/js/app.js` ~392 KB;
- `static/css/style.css` ~30 KB;
- `static/css/theme-autoclicker.css` ~17 KB;
- основная логика backend сосредоточена в большом `app/manager.py`;
- рядом существуют отдельные `static/js/features/*`, но они часто зависят от глобалов и monkey-patch существующих render-функций.

Это означает, что безопасная стратегия - **strangler/incremental migration**, а не rewrite.

## 4. Результаты аудита текущего UX/UI

### 4.1 Навигация перегружена

В верхнем меню сейчас 11 равноправных вкладок:

`Главная / Лог / Отклики / Тесты / База / HH Статус / Просмотры / Отклик / LLM Ответы / HH Хэдди / Настройки`.

Проблема: пользователь должен знать внутреннюю архитектуру проекта, чтобы понять, куда идти. База, тесты, ручной отклик, отклики и HH-статус являются частями одной рабочей воронки, но сейчас выглядят как независимые продукты.

### 4.2 Header перегружен и смешивает статусы с действиями

Header одновременно показывает connection, found/sent/storage/tests, resume views/invites/shows, uptime, debug error, language, pause, apply mode и дополнительные counters из feature-модуля.

Проблемы:

- слишком много цифр одинаковой визуальной важности;
- часть элементов является кнопками без очевидного affordance, например apply-mode badge;
- критический статус может потеряться среди декоративных counters.

### 4.3 Settings смешивает ежедневные и инженерные операции

В одном экране находятся:

- статус поиска работы;
- skills и анализ резюме;
- proxy/TLS/IP;
- OTP/mobile client;
- browser sessions/cookies;
- WebSocket;
- search filters;
- limits;
- URL pool;
- templates;
- questionnaire;
- LLM providers и system prompt;
- диагностика;
- backup/restore;
- JSON snapshot и wipe.

Проблема не в количестве возможностей, а в отсутствии уровней сложности. Обычный пользователь видит инфраструктуру раньше, чем основные рабочие настройки.

### 4.4 Слишком много вложенных `<details>`

Accordion/details активно используются, в том числе внутри других sections. Это прячет важные настройки и делает поиск нужного пункта сложным.

Правило Phase 5: **не использовать nested accordion**. Основные настройки должны быть видимыми по смысловым группам, а `details` оставлять только для коротких вторичных технических блоков.

### 4.5 Визуальная тема создаёт дополнительный шум

`theme-autoclicker.css` добавляет neon glow, CRT scanlines, grid background, moving scan animation, uppercase buttons и сильные hover/glow эффекты.

Технический dark-стиль можно сохранить как идентичность проекта, но:

- motion должен отключаться через `prefers-reduced-motion`;
- основной текст должен быть спокойнее;
- monospace оставить для ID, логов и технических значений, а не для всего интерфейса;
- основной статус должен читаться без цвета и glow.

### 4.6 Frontend сильно связан через глобалы

`app.js` содержит i18n, fetch wrapper, global State, WebSocket, renderAll, account UI, data tabs, manual apply, LLM и settings.

Feature scripts загружаются после него и часто:

- оборачивают `window.renderHeader`/другие globals;
- инжектят DOM;
- сами подключают CSS;
- читают `State.lastSnapshot` напрямую.

Это работает, но любое массовое переименование создаёт высокий regression risk.

### 4.7 Рендер запускается очень часто

Backend broadcast loop отправляет snapshot примерно каждые 300 ms. Каждый `state_update` вызывает `renderAll(snap)`.

В E2E прямо зафиксирована особенность: карточки аккаунтов получают часть данных только после повторного snapshot.

Phase 5 не меняет WS protocol первым шагом, но должна уменьшить лишнюю DOM-работу через coalescing и selective rendering.

### 4.8 Непоследовательная семантика сохранения настроек

Часть toggles сохраняется немедленно через `sendCmd(set_config)`, а часть settings изменяется локально и требует `Применить`/`Сохранить`.

Пользователь не понимает:

- что уже сохранено;
- что ещё pending;
- какое изменение действует мгновенно;
- требует ли изменение restart.

### 4.9 `/api/apply/check` имеет неожиданный side effect

UI говорит `Проверить / Откликнуться`, а endpoint `/api/apply/check` при вакансии без questionnaire может сразу отправить отклик.

В Project Phase 5 должен появиться настоящий preview, который никогда не отправляет application. Старый endpoint оставить для backward compatibility.

### 4.10 Данные уже есть, но представлены разрозненно

Текущий backend уже предоставляет:

- per-account `search_preview` и `filter_stats` в WS snapshot;
- `/api/applied`;
- `/api/tests`;
- `/api/vacancies`;
- `/api/interviews` и `/api/interviews/summary`;
- HR activity;
- preflight;
- extended counters;
- conversion;
- durable application ledger с `applying/applied/interrupted/...`;
- run/day limits и crash reconciliation.

Следовательно, Phase 5 не должна создавать вторую независимую систему состояния. Нужен тонкий dashboard read-model поверх уже существующих источников.

## 5. Целевая информационная архитектура

Не более **6 основных destinations**.

### 1. Обзор

Ежедневный control center:

- состояние бота;
- аккаунты;
- дневной лимит и остаток;
- найдено / готово / отправлено;
- review;
- ошибки;
- новые сообщения/приглашения;
- Action Center;
- последние действия.

### 2. Вакансии

Subviews:

- Найденные / очередь;
- База;
- Требуют questionnaire/test;
- Ручной отклик.

### 3. Отклики

Subviews:

- Отправленные;
- Воронка;
- HR activity/ranking;
- Интервью/ответы;
- причины ошибок/пропусков.

### 4. AI и коммуникации

Subviews:

- Review queue;
- LLM ответы;
- HH quick replies;
- HH Хэдди.

### 5. Резюме

Subviews:

- Просмотры;
- статус поиска;
- skills/verifications;
- анализ резюме;
- поднятие резюме.

### 6. Настройки

Группы:

- Быстрая настройка;
- Аккаунты и вход;
- Поиск и отклики;
- AI и ответы;
- Шаблоны;
- Подключение;
- Продвинутое/диагностика.

`Лог` перестаёт быть обязательной основной вкладкой и становится Activity/Log drawer или вторичным экраном, доступным из Overview и Advanced. Legacy `data-tab="log"` сохраняется как alias во время миграции.

## 6. Новые функции Phase 5

### F5.1 Action Center - «Нужно внимание»

Единый блок с приоритетами:

- review LLM;
- questionnaire review;
- expired cookies/OAuth;
- account paused by errors;
- HH daily limit;
- interrupted application ledger records;
- failed preflight;
- новые приглашения/непрочитанные recruiter chats.

Каждый item обязан иметь:

- severity;
- account;
- короткую причину;
- конкретное действие;
- deep-link в нужный экран.

### F5.2 Понятный дневной KPI

На Overview показывать:

- applied today;
- effective daily limit;
- remaining today;
- run used / run limit;
- found;
- filtered;
- queued;
- review;
- errors.

Не путать session counters и durable daily counters. Источник истины для откликов - application ledger + существующая conservative reconciliation.

### F5.3 Account Health Card

Для каждого аккаунта:

- active/paused;
- current client mode `web/mobile/auto`;
- OAuth status;
- cookies/session health;
- WS realtime state;
- current phase;
- current vacancy;
- today applied/remaining;
- errors in row;
- next resume touch;
- LLM enabled/review state.

Primary actions:

- Start/Resume;
- Pause;
- Apply saved/search results when allowed;
- Open attention issue.

Secondary actions убирать в `More/Details`.

### F5.4 Vacancy Queue / Shortlist Workspace

Использовать существующий `search_preview`, vacancy DB и saved safe-search flow.

Для vacancy row/card показывать:

- title/company/salary;
- account;
- source/search query;
- freshness;
- safe/review/filtered state;
- skip reason;
- questionnaire/test marker;
- HR activity, если уже загружено;
- applied/dedup state.

Actions:

- открыть HH;
- apply one;
- выбрать несколько;
- apply selected;
- skip/hide;
- открыть причину review.

Bulk apply всегда показывает число выбранных вакансий и требует подтверждение.

### F5.5 Explainable filtering

`filter_stats` и причины title/salary/schedule/dedup/preflight должны стать человекочитаемыми.

Минимальные категории причин:

- title include/exclude;
- salary;
- work format;
- already applied/dedup;
- questionnaire/manual review;
- employer/preflight;
- quota/limit;
- search-only;
- transient/permanent error.

Нужны фильтр `Почему пропущено` и короткая подсказка, как изменить соответствующую настройку.

### F5.6 Application Funnel

Воронка по аккаунту и периоду:

`found -> passed filters -> queued -> attempted -> applied -> viewed/interview/rejected`.

Не выдумывать промежуточные цифры. Если backend не может доказать этап, UI показывает `нет данных`, а не 0.

### F5.7 Review Center

Центральный экран human review для результатов Phase 4:

- `llm_review`;
- `quick_reply_review`;
- `robot_review`;
- questionnaire review;
- другие persisted review sources.

Фильтры:

- account;
- category;
- source;
- age;
- reason.

Actions:

- Copy;
- Open HH chat/vacancy;
- mark reviewed/dismiss if backend supports it;
- безопасная повторная генерация только явно пользователем.

Risky review никогда не получает кнопку `Send automatically` в обход policy.

### F5.8 Настоящий Manual Apply Preview

Добавить новый additive endpoint, например:

`POST /api/apply/preview`

Он должен быть side-effect free относительно отправки application и возвращать:

- vacancy ID/title/company;
- account/resume;
- already applied/dedup;
- quota status;
- preflight;
- questionnaire presence/questions metadata;
- expected apply method;
- warnings.

После preview пользователь отдельно нажимает `Отправить отклик`.

Старые `/api/apply/check` и `/api/apply/submit` не удалять в Phase 5.

### F5.9 Search Settings

В Settings добавить поиск по названию/описанию настройки.

Например ввод `лимит`, `LLM`, `proxy`, `анкета`, `удалёнка` оставляет подходящие cards/sections и показывает путь группы.

### F5.10 First-run / Recovery guidance

Не строить отдельный wizard-продукт. На Overview показывать компактный checklist, если система не готова:

1. Добавить/авторизовать аккаунт;
2. выбрать режим;
3. проверить search URL;
4. настроить лимит;
5. запустить safe search;
6. включить Auto safe только осознанно.

Checklist исчезает после готовности и доступен повторно из Help.

## 7. UX/UI требования

### U5.1 Visual hierarchy

На каждом экране только один Primary CTA. Остальные действия secondary/danger.

### U5.2 Статусы

Каждый важный status кодируется минимум двумя признаками:

- текст + icon;
- цвет используется только как дополнительный канал.

### U5.3 Motion

`prefers-reduced-motion: reduce` полностью отключает:

- moving background scan;
- pulse animations;
- non-essential transitions/glow animations.

По умолчанию уменьшить декоративный motion даже без reduced-motion.

### U5.4 Typography

- интерфейс и объяснения - system sans stack;
- monospace - IDs, HTTP, logs, keys fingerprint, raw diagnostics;
- убрать обязательный uppercase со всех кнопок;
- сохранить техническую dark-палитру.

### U5.5 Touch targets / keyboard

- interactive target не меньше 24x24 CSS px или эквивалентно разнесён;
- visible `:focus-visible`;
- sticky header не закрывает focused control;
- tab order соответствует визуальному порядку;
- основные actions доступны клавиатурой.

### U5.6 Responsive

Обязательные smoke breakpoints:

- 390px;
- 768px;
- 1280px;
- 1440+ desktop.

На mobile:

- header сворачивается;
- primary nav не превращается в 11 горизонтальных tabs;
- tables имеют scroll или critical card view;
- primary actions не уходят за viewport.

### U5.7 Status messages

Async success/warning/error должны использовать semantic live region (`role="status"`/`aria-live`) там, где сообщение меняется без навигации.

### U5.8 Empty states

Не `Нет данных` без контекста. Empty state объясняет:

- почему пусто;
- что должно появиться;
- какое действие возможно сейчас.

## 8. Settings UX contract

### 8.1 Три уровня сложности

**Основное** - используется ежедневно.  
**Дополнительное** - редко меняется.  
**Продвинутое** - proxy, raw JSON, low-level mobile config, diagnostics, destructive actions.

### 8.2 Не смешивать save semantics

В одном card нельзя одновременно иметь часть полей instant-save, а часть pending без явной маркировки.

Допустимые паттерны:

- toggle instant-save -> после ответа backend показать `Сохранено`;
- form edits -> dirty indicator + одна кнопка `Сохранить`;
- restart-required -> явный badge `нужен перезапуск`.

### 8.3 Dangerous actions

`wipe`, restore backup, delete account, bulk apply и аналогичные действия требуют confirmation с описанием последствий.

### 8.4 Accordion policy

- никаких accordion внутри accordion;
- важные ежедневные настройки не прятать;
- `details` использовать только для вторичного краткого content;
- длинные группы разделять headings/anchors/subviews.

## 9. Frontend architecture - постепенная декомпозиция

### 9.1 Compatibility facade

До конца Phase 5 сохранять:

- `window.State`;
- `window.sendCmd`;
- существующие global entrypoints из inline `onclick`;
- существующие DOM `id`;
- текущую форму WS `state_update`.

### 9.2 Новый UI namespace

Добавить явный слой, например:

```text
static/js/ui/
  core.js
  events.js
  navigation.js
  overview.js
  vacancies.js
  applications.js
  review.js
  settings.js
```

Экспортировать стабильный namespace `window.HHUI` или использовать ES modules с compatibility adapters.

### 9.3 Event contract

Вместо новых monkey-patches глобальных render-функций использовать явные события:

- `hh:snapshot`;
- `hh:tabchange`;
- `hh:config-saved`;
- `hh:account-changed`;
- `hh:review-changed`.

Старые feature-модули мигрировать по одному. Не переписывать все восемь одновременно.

### 9.4 CSS migration

Ввести постепенно:

- tokens;
- button classes;
- status badges;
- cards;
- form controls;
- layout utilities.

Старые selectors оставлять до завершения migration конкретного экрана. Удаление obsolete CSS - отдельный cleanup commit после green E2E.

### 9.5 Новые UI components

Новый код по умолчанию создаёт user-derived content через `textContent`/DOM API. `innerHTML` допускается только для статичной/экранированной разметки.

## 10. State/render performance

Первый релиз Phase 5 сохраняет backend WS broadcast 300 ms, чтобы не менять transport и UI одновременно.

Frontend должен:

- coalesce snapshots через `requestAnimationFrame` или scheduler;
- не перерисовывать тяжёлые inactive sections;
- не запускать REST fetch на каждый snapshot;
- использовать throttle/cache для counters/HR metadata;
- сохранять ограничение log/recent/llm arrays;
- не увеличивать DOM бесконечно.

Поздний optional step: добавить additive `changed_sections`/version metadata в snapshot. Это не prerequisite UI migration.

## 11. Additive backend read-model

Не делать frontend ответственным за объединение 8 источников при каждом render.

Разрешено добавить:

### `GET /api/dashboard/summary`

Возвращает только агрегированные operational данные:

- global mode/paused/search-only;
- accounts health summary;
- daily quota used/remaining;
- queue counts;
- review count;
- active warnings;
- unread counters;
- funnel summary, если данные доказуемы.

### `GET /api/dashboard/action-center`

Опционально, если summary станет слишком большим. Должен агрегировать уже существующие statuses, а не создавать новый persistence layer.

### `POST /api/apply/preview`

Side-effect-free preview из F5.8.

Все новые endpoints должны быть additive и использовать существующую API-key middleware.

## 12. Порядок реализации

### 5A - Baseline + regression harness

- branch `phase5/dashboard-ux` от актуального `main`;
- сохранить baseline DOM/API inventory;
- добавить `data-testid` для critical actions;
- desktop + mobile smoke;
- keyboard/focus tests;
- `prefers-reduced-motion` test;
- no page errors.

**Запрещено:** менять layout до готовности этих тестов.

### 5B - Navigation shell

- новая IA с 6 destinations;
- legacy tab aliases;
- URL hash/deep-link mapping;
- existing panels пока не переписывать;
- Activity/Log доступен из shell.

### 5C - Settings IA

- search settings;
- semantic groups;
- убрать nested details;
- dangerous actions -> Advanced;
- explicit save semantics;
- сохранить старые element IDs/handlers.

### 5D - Overview + Action Center

- global status;
- daily quota;
- action center;
- simplified account health cards;
- secondary details expandable.

### 5E - Vacancy workspace

- queue/search preview;
- filter/skip reasons;
- shortlist;
- apply selected;
- dedup/applied status;
- manual true preview.

### 5F - Applications + Funnel

- sent history;
- conversion;
- HR activity;
- viewed/interview/rejected where available;
- honest unknown states.

### 5G - Review + AI workspace

- persisted review center;
- LLM status;
- Hedi subview;
- safe actions only.

### 5H - Frontend decomposition

- вынести уже стабилизированные UI domains из `app.js`;
- compatibility wrappers оставить;
- прекратить создание новых monkey-patch feature scripts.

### 5I - Visual polish + responsive/accessibility

- calm technical theme;
- reduced motion;
- typography;
- focus/targets;
- 390/768/desktop;
- consistent empty/loading/error states.

### 5J - Cleanup

Только после полного green gate:

- удалить реально dead CSS/JS wrappers;
- не удалять compatibility endpoint без отдельной deprecation-фазы;
- обновить screenshots/docs/user guide.

## 13. Testing gate

После **каждого** подэтапа:

```bash
pytest -q --ignore=tests/e2e
pytest -q tests/e2e
ruff check app tests scripts web_app.py
python -m compileall -q app web_app.py
python scripts/validate_public_repo.py
git diff --check
```

Baseline Phase 5 начинается с:

- backend: 1237 passed + 1 expected Windows-only skip;
- E2E: 101 passed.

Число тестов должно только расти, но главным условием является отсутствие regression существующих scenarios.

### Обязательные новые E2E

1. Primary navigation reachable keyboard/mouse.
2. Legacy tab mapping continues to work.
3. Overview renders after first/second WS snapshots without page error.
4. Action Center persists review after empty in-memory LLM log/restart simulation.
5. Settings search finds hidden/advanced setting and scrolls to it.
6. Save state is visually explicit.
7. Manual apply preview does not send application.
8. Submit occurs only after explicit second action.
9. Bulk apply confirmation shows selected count.
10. Search-only mode blocks every send CTA.
11. Mobile 390px smoke: no inaccessible primary CTA.
12. Focus is visible and not obscured by sticky header.
13. Reduced-motion disables non-essential animation.
14. No `pageerror` on all primary destinations.
15. Existing Phase 4 LLM/review tests remain green.

## 14. Performance acceptance

На типовом состоянии 1-2 accounts, 100 log entries, 100 recent rows:

- UI остаётся responsive во время 300ms WS updates;
- inactive heavy tables не пересобираются на каждый snapshot;
- repeated snapshot без meaningful changes не вызывает полный heavy rerender;
- количество DOM nodes не растёт от времени работы;
- нет overlapping duplicate REST fetch одного resource;
- после 30 минут работы нет очевидного роста памяти из-за UI queues/logs.

Не вводить искусственный FPS KPI, пока нет измерительного harness. Сначала instrumentation, потом numerical budget.

## 15. Compatibility checklist перед каждым merge

- [ ] Existing REST routes unchanged or only additively extended.
- [ ] WS `state_update` old fields preserved.
- [ ] Existing DOM IDs preserved for unmigrated code.
- [ ] Existing globals preserved or compatibility-wrapped.
- [ ] Search-only remains fail-closed.
- [ ] Apply limits remain durable and Moscow-date aware.
- [ ] LLM Auto safe cannot bypass Phase 4 policy.
- [ ] Questionnaire unresolved fields never auto-submit.
- [ ] Risky recruiter actions remain human review.
- [ ] API keys/cookies/tokens never added to UI logs.
- [ ] No new raw user content inserted through unsafe `innerHTML`.
- [ ] No unexpected outbound network in E2E.

## 16. Definition of Done Project Phase 5

Phase 5 считается завершённой только если:

1. В primary navigation не больше 6 destinations.
2. Пользователь с Overview понимает: бот работает/пауза, сколько применено сегодня, сколько осталось, есть ли проблемы и что требует внимания.
3. Critical daily actions доступны максимум за 1-2 перехода.
4. Settings разделены по пользовательскому смыслу, есть поиск, нет nested accordion maze.
5. Любая настройка ясно показывает save semantics.
6. Есть Vacancy/Shortlist workspace с explainable reasons.
7. Есть центральный Review Center.
8. Manual Apply имеет настоящий side-effect-free preview.
9. Основные экраны пригодны на 390/768/desktop.
10. Reduced motion, keyboard focus и target-size baseline выполнены.
11. `app.js` больше не является единственным местом для новой UI-функциональности; новые domains идут через явный UI layer/events.
12. Все Phase 1-4 safety contracts сохранены.
13. Backend/E2E/Ruff/compile/validator полностью green.
14. `main` получает Phase 5 только через reviewable PR после отчёта `что сделано / что не сделано / почему`.

## 17. Что НЕ входит в Phase 5

- Telegram bot/control plane - **Project Phase 6**.
- Полная миграция на SPA framework.
- Замена FastAPI/backend architecture.
- Переписывание `manager.py` только ради frontend.
- Новый cloud/SaaS deployment.
- Автоматическое обходное решение CAPTCHA/rate limits.
- Удаление старых API/DOM contracts одновременно с UX migration.

## 18. Рекомендуемая стратегия веток

- planning: `planning/phase5-dashboard-ux`;
- implementation: `phase5/dashboard-ux`;
- при больших подэтапах допустимы дочерние ветки `phase5/5a-baseline`, `phase5/5b-nav`, ...;
- `main` не используется как рабочая ветка;
- каждый merge в Phase 5 branch требует green CI;
- финальный merge в `main` только после полного Phase 5 QA и отчёта.

## 19. Внешние UX-ориентиры

При реализации ориентироваться на:

- GOV.UK Design System: accordions скрывают content, nested accordions не рекомендуется; сначала simplification/headings/anchor navigation;
- WCAG 2.2 AA: Focus Not Obscured, Target Size Minimum, predictable interaction;
- для operational dashboard приоритет над декоративностью имеют state clarity, actionability и error recovery.

Эти ориентиры не означают копирование визуального дизайна GOV.UK. Они используются как правила информационной архитектуры и доступности.
