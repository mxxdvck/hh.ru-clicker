# Project Phase 5 - Dashboard UX & Operations

Status: implementation complete, final release gate pending.

## Goal

Phase 5 turns the existing dashboard into a clearer operations console without rewriting the working application engine. Phase 1-4 safety, apply, quota, questionnaire, LLM and persistence behavior remains authoritative.

The redesign is incremental. Existing backend routes, WebSocket commands, durable application state and critical legacy DOM contracts stay compatible while new UI modules are layered on top.

## Delivered scope

### 5A - Baseline and regression harness

- Stable `data-testid` markers for critical controls.
- Keyboard-accessible legacy tabs and ARIA state.
- Reduced-motion support.
- Desktop/mobile regression coverage.
- Machine-readable contract for critical DOM, API and WS commands.

### 5B - Navigation shell

- Six primary sections: Overview, Vacancies, Applications, AI & communication, Resume, Settings.
- Existing legacy panels remain available under the new shell.
- Deep-link and legacy navigation compatibility is preserved.
- New UI code uses the `HHUI` event layer instead of adding more global render patches.

### 5C - Settings information architecture

- Search across settings.
- Semantic groups instead of one long configuration page.
- Clear distinction between instant-save controls and form-save controls.
- Existing control IDs and save handlers are preserved.

### 5D - Overview and Action Center

- Runtime status, per-account quota math and operational health on one screen.
- Persisted review count survives process restart.
- OAuth/cookie/limit/pause problems are actionable items.
- Account health exposes current phase, vacancy, resume touch and LLM state.
- Unknown metrics display `нет данных` instead of a fabricated zero.

### 5E - Vacancy workspace

- Existing safe-search preview becomes a selectable workspace.
- Apply one, apply selected or apply the exact full saved shortlist.
- Selected vacancy IDs are validated against the current server-side safe queue.
- Applying a saved shortlist does not trigger another search.
- Existing dedupe, quota, questionnaire, safety and transport gates remain active.
- Preview metadata includes source query, publication time, schedule, tests, HR/chat capability and related HH metadata when already available.

### 5F - Applications and funnel

- New operational summary read-model without breaking the existing conversion endpoint.
- Current cycle, historical outcome and durable ledger are displayed as separate data windows.
- Durable states include applying, applied, already, interrupted, transient failure and permanent failure.
- Partial account failures do not masquerade as complete aggregate totals.
- REST summaries are cached instead of being fetched on every fast WS snapshot.

### 5G - Review Center

- Persisted policy-review drafts are collected in one workspace.
- Filters by account, category and source.
- Shows employer message, draft, policy reason and source metadata.
- Safe manual actions are copy draft and open HH chat.
- There is deliberately no Send anyway, Approve or Force action that bypasses Phase 4 policy.

### 5H - Incremental frontend decomposition

- Phase 5 modules live under `static/js/ui/`.
- `hh:snapshot`, `hh:tabchange`, account-card and WS events replace selected legacy monkey-patches.
- Skills, counters, mode controls and WS indicators no longer replace global render functions.
- Architecture tests prevent those removed wrappers from being reintroduced accidentally.

### 5I - Responsive and accessibility polish

- Tested at 390, 768 and 1440 pixel viewports.
- Primary Phase 5 surfaces avoid page-level horizontal overflow.
- Touch targets and focus visibility are improved.
- Reduced-motion behavior remains supported.
- Existing dark visual identity is retained while operational UI uses a readable system font and calmer hierarchy.

## Compatibility and safety invariants

Phase 5 must not weaken earlier phases. In particular:

- Daily and run limits remain backend-enforced.
- Search-only bypass stays narrow and only applies to the already collected safe queue.
- Browser-selected vacancy IDs are never trusted without server-side queue validation.
- Questionnaire and LLM policy remain fail-closed.
- Review-only categories cannot acquire a frontend policy bypass.
- Durable application ledger remains the source of truth for apply outcomes.
- Existing critical WS commands and API routes remain covered by baseline contract tests.

## Frontend architecture rule

New feature work should prefer `HHUI.core` events and modules under `static/js/ui/`. Do not add another wrapper that reassigns a legacy global renderer when an explicit event can express the same integration.

The old `app.js` remains for compatibility and is intentionally not rewritten in Phase 5. Decomposition is incremental so that working apply/runtime behavior is not coupled to a visual redesign.

## Release gate

Before merging Phase 5 to `main`, all of the following must pass on the final SHA:

- public repository validator;
- Ruff correctness checks;
- Python compileall;
- JavaScript syntax checks for Phase 5 and touched feature modules;
- full backend pytest suite;
- full Chromium E2E suite;
- PR merge-commit CI against current `main`.

The final release report must state what was delivered, what was intentionally left as compatibility debt, and why.
