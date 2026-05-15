---
title: Rule Scheduler
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/scheduler/
  - src/gui/routes/rule_scheduler.py
  - src/rule_scheduler_cli.py
  - python illumio-ops.py rule-scheduler --help
  - commit 10b3754
related_docs:
  - alerts-and-quarantine.md
  - ../architecture/i18n-contract.md
  - ../reference/cli.md
---

> 🌐 **[English](rule-scheduler.md)** | [繁體中文](rule-scheduler_zh.md)
> 📍 [INDEX](../INDEX.md) › User Guide › Rule Scheduler
> 🔍 Last verified **2026-05-15** against commit `10b3754` — see frontmatter for sources

# Rule Scheduler

The Rule Scheduler lets operators attach time-based triggers to individual PCE
rules. A rule can be enabled for a recurring daily window (e.g. "Mon–Fri
08:00–18:00") or set to expire at a fixed UTC timestamp. The daemon evaluates
all active schedules every `check_interval_seconds` (default: 300 s) and
applies enable/disable calls to the PCE API automatically.

---

## What it does

The Rule Scheduler manages **temporary PCE rules** — rules whose `enabled`
state should change on a schedule rather than remaining permanently on or off.

Supported use-cases:

| Use-case | Trigger type |
|---|---|
| Maintenance window — allow specific traffic during a nightly batch job | Recurring |
| Incident response — temporarily enable a quarantine rule until midnight | One-shot (expire) |
| Business-hours policy — disable broad allow-rules outside working hours | Recurring |
| Post-incident cleanup — auto-disable a rule after a known future date | One-shot (expire) |

Rules are identified by their PCE **href** (e.g.
`/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99`). The scheduler tracks
state in `config/rule_schedules.json` (local JSON store, not the PCE). PCE
changes are applied via the API only when a schedule fires.

> **Note:** The scheduler does **not** provision rulesets. Rules in `DRAFT`
> provision-state are toggled in draft; an operator must provision separately.

---

## Creating a scheduled rule

### Via the Web GUI

1. Open **Rule Scheduler** in the sidebar.
2. Browse to the desired ruleset and click on a rule row.
3. Choose a schedule type:
   - **Recurring** — select days-of-week, start time, end time, and timezone.
   - **One-shot** — pick an expiry datetime; the rule is disabled at that moment.
4. Set **Action**: `allow` (enable the rule at window start, disable at end) or
   `disable` (disable the rule at window start, enable at end).
5. Click **Save Schedule**. The rule row shows a calendar badge once saved.

The UI writes to `POST /api/rule_scheduler/schedules` with a JSON body:

```json
{
  "href":       "/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99",
  "name":       "Nightly batch allow",
  "type":       "recurring",
  "action":     "allow",
  "days":       ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
  "start":      "22:00",
  "end":        "06:00",
  "timezone":   "Asia/Taipei"
}
```

For a one-shot schedule:

```json
{
  "href":      "/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99",
  "name":      "Incident quarantine",
  "type":      "expire",
  "action":    "allow",
  "expire_at": "2026-05-16T23:59",
  "timezone":  "local"
}
```

### Via the interactive shell (CLI)

The scheduler interactive UI lives in `src/rule_scheduler_cli.py` and is
reachable through the `illumio-ops shell` interactive menu.

> **TODO:** A dedicated `illumio-ops rule-scheduler` Click subcommand is
> referenced in legacy docs but is **not wired** in the current Click root
> (`src/cli/main.py`). The interactive path via `illumio-ops shell` is the
> only verified CLI entry point as of commit `10b3754`.

From the interactive shell, select **Rule Scheduler** to:
- Browse rulesets fetched live from the PCE.
- Select a rule and attach a recurring or one-shot schedule.
- List all active schedules.
- Cancel (delete) a schedule.

---

## Recurring vs one-shot

| Property | Recurring | One-shot (expire) |
|---|---|---|
| `type` field | `"recurring"` | `"expire"` |
| Required fields | `days`, `start`, `end`, `timezone` | `expire_at`, `timezone` |
| Fires | Every matching day at `start`; reverts at `end` | Once, at `expire_at` |
| After firing | Remains active for the next cycle | Schedule entry is consumed |
| PCE description tag | `[📅 Recurring: Mon,Tue,Wed… HH:MM-HH:MM (TZ) ...]` | `[⏰ Expire: YYYY-MM-DD HH:MM]` |

**Recurring** schedules use a time-window model: at `start` the rule is
set to the configured `action` state; at `end` it is reverted. If the daemon
was down during a window boundary it will catch up on the next tick (APScheduler
`coalesce=True`, `misfire_grace_time=60 s`).

**One-shot** schedules disable (or enable, per action) the rule at the given
`expire_at` datetime and are not re-evaluated afterward.

---

## Why descriptions are always English

When a schedule is saved, the daemon writes a short annotation into the PCE
rule's `description` field — for example:

```
[📅 Recurring: Mon,Tue,Wed,Thu,Fri 22:00-06:00 (Asia/Taipei) Enable in window]
```

This annotation is written with `t(key, lang='en')` regardless of the
operator's UI language. The same pattern appears in both the Flask route
(`src/gui/routes/rule_scheduler.py`) and the CLI helper
(`src/rule_scheduler_cli.py`).

**Why?**

The PCE description field is **opaque stored data**, not a UI label. It is
surfaced verbatim in:

- **Policy-usage reports** — which may be consumed by English-speaking
  auditors or fed into SIEM pipelines.
- **Audit reports** — where the description appears as a literal string in CSV
  / HTML output.
- **Cross-language sessions** — operators switching between EN and zh-TW would
  otherwise see mixed-language annotations in historical data.

Fixing the language to English at write-time ensures that the annotation is
stable and unambiguous regardless of who reads it, when, or in what locale.
This is the `t(key, lang='en')` convention defined in the
[i18n Contract](../architecture/i18n-contract.md).

---

## Listing & cancelling scheduled rules

### Web GUI

- **Rule Scheduler → Active Schedules tab** — lists all schedules with live
  PCE status (`live_enabled` from `GET /api/rule_scheduler/schedules`).
- Select one or more entries → **Delete** button → calls
  `POST /api/rule_scheduler/schedules/delete` with `{ "hrefs": [...] }`.
- Deleting a schedule also clears the annotation from the PCE rule description
  (`api.update_rule_note(href, "", remove=True)`).

### API (direct)

```bash
# List all active schedules
curl -s http://localhost:8080/api/rule_scheduler/schedules | jq .

# Get a single schedule
curl -s http://localhost:8080/api/rule_scheduler/schedules/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99 | jq .

# Delete schedules
curl -s -X POST http://localhost:8080/api/rule_scheduler/schedules/delete \
  -H 'Content-Type: application/json' \
  -d '{"hrefs":["/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99"]}'

# Manually trigger a schedule check cycle
curl -s -X POST http://localhost:8080/api/rule_scheduler/check

# Check scheduler status (interval, count)
curl -s http://localhost:8080/api/rule_scheduler/status | jq .
```

### Interactive shell

From `illumio-ops shell → Rule Scheduler`, choose **List schedules** or
**Cancel a schedule** from the sub-menu.

---

## Audit trail

### Where records go

| Destination | Content | Path |
|---|---|---|
| **Loguru daemon log** | Every tick result: `[RuleScheduler] <message>` | `logs/illumio_ops.log` (default) |
| **ModuleLog** | Same messages, queryable via GUI | in-memory ring buffer; GUI tab **Rule Scheduler → Logs** |
| **PCE rule description** | English annotation tag written at schedule-save time | Stored in PCE; visible in PCE UI and policy-usage reports |
| **Schedule store** | JSON record of every active schedule | `config/rule_schedules.json` |

### Log format

Each successful tick emits a line such as:

```
2026-05-15 22:00:03 | INFO | [RuleScheduler] rule /orgs/1/.../sec_rules/99 → enabled (recurring window start)
```

Errors are logged at `ERROR` level with a full traceback to the daemon log and
ModuleLog.

### GUI log viewer

Navigate to **Rule Scheduler → Logs** in the web UI. This calls
`GET /api/rule_scheduler/logs` and shows the in-memory ring buffer populated
by `_append_rs_logs()` during each tick.

### Daemon persistence

If `config.json` has `scheduler.persist = true` and SQLAlchemy is installed,
APScheduler uses a SQLite jobstore (path logged as
`"Scheduler using persistent SQLite jobstore: <path>"`). Otherwise it uses an
in-memory jobstore (jobs are lost on daemon restart, but rule schedules
themselves persist in `config/rule_schedules.json`).

---

## Related Docs
- [Alerts & Quarantine](alerts-and-quarantine.md) — alerts that fire rule scheduling
- [i18n Contract](../architecture/i18n-contract.md) — why scheduler descriptions stay English
- [CLI Reference](../reference/cli.md) — `illumio-ops` flags
