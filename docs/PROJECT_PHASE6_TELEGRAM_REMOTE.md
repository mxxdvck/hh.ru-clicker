# Project Phase 6 - Telegram Remote

Status: 6A foundation in progress.

## Goal

Add a small Telegram control surface for the existing HH bot without creating a second application engine and without weakening Phase 1-5 safety.

Telegram is a remote UI. Business decisions remain in `BotManager`, the durable application ledger and the Phase 4 LLM policy. A Telegram command may call an existing safe operation, but it must not reimplement vacancy filtering, quota checks, questionnaire logic, auto-send policy or HH transport.

## Architecture decisions

- Bot API long polling, not webhook. The local dashboard does not need a public HTTPS endpoint.
- No Telegram framework dependency. Phase 6 uses the existing `requests` dependency and a small transport module.
- Off by default and fail-closed.
- Secret token exists only in environment variables, never in `data/config.json`, dashboard snapshots or logs.
- Only explicitly allowlisted **private** chat ids are accepted. Groups/channels are rejected even when their numeric id is supplied.
- Unauthorized chats receive no response.
- Exceptions are logged by type only because a `requests` exception can contain the token-bearing Bot API URL.
- Telegram message text uses no HTML/Markdown parse mode, so HH/employer text cannot inject Telegram markup.

## Environment

```text
HH_BOT_TELEGRAM_ENABLED=0
HH_BOT_TELEGRAM_TOKEN=
HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS=
```

`HH_BOT_TELEGRAM_ALLOWED_CHAT_IDS` is a comma-separated list of positive private-chat ids. A malformed item invalidates the whole allowlist rather than silently widening access.

## Delivery slices

### 6A - Secure read-only foundation

- [x] Long-polling transport with bounded network timeouts and stoppable daemon worker.
- [x] Explicit private-chat allowlist.
- [x] `/status` read model.
- [x] `/accounts` read model.
- [x] `/help` / `/start`.
- [x] Unit tests for opt-in, allowlist and unauthorized-chat behavior.
- [ ] Runtime lifecycle wiring and CI gate.

### 6B - Safe controls

Planned only after 6A is green:

- global pause/resume;
- per-account pause/resume;
- approve current safe-search shortlist or an exact validated subset;
- confirmation tokens for mutating actions.

All of these must call existing `BotManager` methods. In particular safe-search approval must call `apply_search_results(idx, vacancy_ids=...)`, which already validates ids against the current server-side queue. There will be no `force apply` command.

### 6C - Notifications

- quota/hard-stop events;
- cookie/OAuth health problems;
- LLM review-required items;
- completed safe-search queue ready for approval;
- deduplicated delivery so restart/reconnect does not spam old events.

### 6D - Review workbench

- show pending policy-review drafts;
- copy/open-HH workflow from the dashboard mirrored as Telegram-safe actions;
- no `send anyway`, no bypass of Phase 4 policy.

### 6E - Release gate

- full backend tests;
- Chromium E2E regression suite;
- secret/log redaction audit;
- shutdown/restart test;
- user guide and troubleshooting update.

## Non-goals

Phase 6 does not move the HH bot itself into Telegram, expose the dashboard to the internet, or replace the existing WebSocket/dashboard architecture. It is deliberately a thin remote-control layer over the same authoritative runtime.
