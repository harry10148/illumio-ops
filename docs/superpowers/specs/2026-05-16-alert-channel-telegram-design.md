# Alert Channel: Telegram — Design Spec

**Status:** Approved 2026-05-16
**Owner:** harry
**Phase 2 (WhatsApp):** deferred — see §7

---

## 1. Problem

Operators today receive `illumio-ops` alerts via Email (SMTP) and LINE.
LINE is constrained: 1 chat, plain text only, limited formatting. The team
already uses Telegram for ops handoffs (chat `1284061527`) and wants the
same channel for alert delivery — with richer formatting than LINE
(bold severity, monospace fields, clickable PCE console links).

## 2. Goals & Non-Goals

**Goals**
- Deliver alerts to a single Telegram chat with rich HTML formatting
  (`<b>`, `<code>`, `<a>`, emoji).
- Reuse the existing `AlertOutputPlugin` auto-registration; no changes
  to the dispatcher or other plugins.
- Zero new pip dependencies; use stdlib `urllib.request` (matches the
  LINE plugin pattern).
- Idempotent config: appending `"telegram"` to `alerts.active` enables
  dispatch; removing it disables. No migration needed.

**Non-goals**
- Multi-chat fan-out (single `chat_id` only — defer if requested).
- Forum-topic routing (`message_thread_id`) — future enhancement.
- Inline keyboard / callback handlers — alerts are fire-and-forget.
- WhatsApp integration — see §7.

## 3. Architecture

```
                          ┌──────────────────────────┐
 Reporter.send_alerts()   │  alerts.active = [       │
   subject = "..."        │    "mail",               │
   ──────────────────►    │    "telegram",  ◄── new  │
                          │    "webhook"             │
                          │  ]                       │
                          └──────────────────────────┘
                                      │
                                      │ for each name → build_output_plugin(name, cm)
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │  AlertOutputPlugin registry (auto-populated)    │
              ├──────────┬───────────┬──────────┬───────────────┤
              │  mail    │  line     │  webhook │  telegram ◄── │
              └──────────┴───────────┴──────────┴───────────────┘
                                                       │
                                                       │ .send(reporter, subject, lang="en")
                                                       ▼
                                  ┌─────────────────────────────────────┐
                                  │ TelegramAlertPlugin.send():         │
                                  │  1. Read bot_token + chat_id from   │
                                  │     cm.config["alerts"]             │
                                  │  2. message_html =                  │
                                  │     reporter._build_telegram_message│
                                  │  3. POST graph: parse_mode=HTML     │
                                  │  4. Return {channel, status, …}     │
                                  └─────────────────────────────────────┘
```

**Plugin contract (existing, unchanged):** `send(reporter, subject, *, lang) -> dict`
returning `{channel, status, target, error?}`.

## 4. Components & File Surface

| File | Change | Notes |
|---|---|---|
| `src/alerts/plugins.py` | **Add** `TelegramAlertPlugin` class (~40 LOC) | Auto-registers via `__init_subclass__` |
| `src/alerts/metadata.py` | **Add** `"telegram"` entry to `PLUGIN_METADATA` with 2 field metas (`telegram_bot_token` secret, `telegram_chat_id`) | Drives GUI rendering |
| `src/alerts/templates/telegram_digest.html.tmpl` | **New** | HTML-formatted digest template |
| `src/reporter.py` | **Add** `_build_telegram_message(subject) -> str` | Mirrors `_build_line_message`; renders the new template; HTML-escapes dynamic fields |
| `config/config.json.example` | **Add** `"telegram_bot_token": ""`, `"telegram_chat_id": ""` to `alerts` block | Operators copy on first install |
| `src/config_models.py` | **Add** two `str` fields to the `alerts` Pydantic model (default `""`) | Schema validation |
| `src/i18n/data/zh_explicit.json` | **Add** ~8 keys (display_name / description / 2 fields / 3 status messages) | Mirrors `line_alert_*` set |
| `tests/test_alerts_telegram.py` | **New** (~120 LOC) | Mock `urllib.request.urlopen`; assert payload shape, escape, error paths |
| `tests/test_gui_alert_plugins.py` | **Modify** | Add Telegram metadata-rendering assertions (mirror existing LINE assertions) |

**Out of scope for this spec:** dashboard "test alert" button — handled by existing `actions.py` which iterates `alerts.active` dynamically (works automatically once plugin is registered).

## 5. Message Format

Telegram `sendMessage` with `parse_mode=HTML`:

```html
🔴 <b>CRITICAL</b> · ransomware exposure detected

App: <code>web-prod</code> | Env: <code>prod</code>
Risk: 87/100 ↑ from 72

🔗 <a href="https://pce.acme.com/...">Open in PCE Console</a>
⏱ 2026-05-16 14:23 (UTC+8)
```

**Allowed HTML tags** (Telegram subset): `<b>`, `<i>`, `<u>`, `<s>`, `<code>`,
`<pre>`, `<a href>`. **Escape rule:** `html.escape(value, quote=False)` for every
dynamic field — covers `&`, `<`, `>`. Validate at template-render time, not
at API-call time, so escape failures surface during unit tests.

**Digest pattern:** one `sendMessage` per dispatch cycle, batching all
alerts in the current queue (matches LINE digest behavior — see
`line_digest.txt.tmpl`). Each alert becomes one block separated by a thin
divider line. Telegram hard limit is 4096 chars per `text` field; the
template enforces a safe 3500-char ceiling and truncates oldest entries
first with a `… +N more` footer.

**`disable_web_page_preview=true`** — prevents Telegram from auto-fetching
PCE URL previews (PCE is internal, preview would fail; also reduces noise).

## 6. Testing

| Test | Mechanism | Catches |
|---|---|---|
| `test_telegram_plugin_skipped_when_unconfigured` | Empty token/chat_id | Status = `skipped` with `missing configuration` |
| `test_telegram_plugin_success_returns_target` | Mock `urlopen` → 200 | Payload structure (`chat_id`, `text`, `parse_mode`, `disable_web_page_preview`) |
| `test_telegram_html_escape_in_dynamic_fields` | Alert with `app_name = "ops<script>"` | Renders `ops&lt;script&gt;` in body |
| `test_telegram_digest_truncates_over_3500_chars` | 50 alerts | Body ends with `…` and stays ≤ 3500 chars |
| `test_telegram_plugin_fails_on_4xx` | Mock `urlopen` → 400 | Status = `failed`, error captures response |
| `test_telegram_plugin_fails_on_timeout` | Mock `urlopen` → `URLError` | Status = `failed`, error captures exception |
| `test_gui_alert_plugins::test_telegram_metadata_rendered` | GUI metadata endpoint | Frontend can render the new plugin's config form |
| `test_i18n_keys_present` (existing) | Audit run | New i18n keys exist in both en/zh_TW |

No integration test against the real Telegram API — covered manually
during deployment with the existing `actions.py` "send test alert" button.

## 7. Future Work (Phase 2)

**WhatsApp** — deferred until ops are willing to invest in Meta Business
account setup (24-hour template approval, Phone Number ID provisioning).
When activated, the same plugin pattern applies; the most likely path is
**Meta WhatsApp Cloud API** (free tier 1k msg/mo, no third-party
dependency, but requires pre-approved message templates for alerts since
alerts are unsolicited push outside the 24h customer-initiated window).

**Multi-chat fan-out** — change `telegram_chat_id` → `telegram_chat_ids`
(list) when ops requests broadcasting (e.g. one chat per env or severity).

**Forum-topic routing** — add `telegram_topic_map` config: `{"critical":
123, "high": 456}` → set `message_thread_id` per alert severity. Requires
target group enabled as forum.

## 8. Risk & Rollback

- **Risk: malformed HTML rejected by Telegram (`Bad Request: can't parse
  entities`).** Mitigated by escape-at-render unit tests and a stripped
  fallback (`parse_mode=null` retry on `400 can't parse`).
- **Risk: bot token leak.** Token is stored in `config.json` which is
  already in `.gitignore` and chmod-600 by `install.sh`. GUI input field
  is `secret=True` → masked.
- **Rollback:** remove `"telegram"` from `alerts.active`. Plugin code can
  remain — registry is idempotent.

## 9. Open Questions

None at design-approval time. Implementation plan will be drafted next
via the `superpowers:writing-plans` skill.
