---
title: REST API
audience: [api, developer, security]
last_verified: 2026-06-26
verified_against:
  - src/gui/routes/auth.py
  - src/gui/routes/admin.py
  - src/gui/routes/dashboard.py
  - src/gui/routes/events.py
  - src/gui/routes/reports.py
  - src/gui/routes/rules.py
  - src/gui/routes/rule_scheduler.py
  - src/gui/routes/actions.py
  - src/gui/routes/config.py
  - src/gui/__init__.py
  - src/siem/web.py
  - src/pce_cache/web.py
  - v4.1.0 (branch review/audit-and-docs-rebuild)
related_docs:
  - cli.md
  - glossary.md
  - ../operations-manual_zh.md
  - ../event-rules_zh.md
---

> 🌐 **[English](rest-api.md)** | [繁體中文](rest-api_zh.md)
> 📍 [INDEX](../INDEX.md) › Reference › REST API
> 🔍 Last verified **2026-06-26** against **v4.1.0** — see frontmatter for sources

# REST API

All endpoints listed here are served by the illumio-ops Flask GUI
(`src/gui/` + `src/siem/web.py` + `src/pce_cache/web.py`).

The GUI listens on **port 5001** and serves **HTTPS** whenever
`web_gui.tls.enabled` is set — the default for production and offline-bundle
installs. The base URL is therefore:

```
https://127.0.0.1:5001
```

With TLS disabled the same port falls back to `http://`. Self-signed installs
need `curl -k` (or `--cacert`) to skip certificate verification.

---

## Auth model

The GUI uses **session-cookie authentication** backed by Flask-Login and
Flask-WTF CSRF protection. There is no standalone API key.

Authentication is enforced **globally** by a `before_request` gate in
`src/gui/__init__.py` (not by per-route decorators). Every route requires a
valid session **except** these public paths:

- `GET /api/csrf-token`
- `GET /login`
- `POST /api/login`
- `POST /logout`

(`/static/` assets are also exempt from session auth.) A separate IP-allowlist
check runs first on **all** paths — requests from non-allowlisted addresses are
dropped at the socket with a TCP RST (no HTTP response).

Every authenticated call must present:

1. **Session cookie** — obtained by `POST /api/login`; `HttpOnly`,
   `SameSite=Strict`, `Secure` (on TLS installs). Default lifetime: 8 hours
   (configurable via `web_gui.session_lifetime_seconds`).
2. **CSRF token** — required on every state-mutating request (`POST`, `PUT`,
   `DELETE`). Send it in the `X-CSRFToken` **or** `X-CSRF-Token` request header
   (both are accepted). Fetch a fresh token from `GET /api/csrf-token`.

`POST /api/login` is **CSRF-exempt** and rate-limited to **5 requests/minute**.

**Login flow:**

```bash
BASE="https://127.0.0.1:5001"          # add -k to curl for self-signed TLS

# 1. Fetch CSRF token (before first POST)
CSRF=$(curl -sk -c cookies.txt "$BASE/api/csrf-token" | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# 2. Login
curl -sk -b cookies.txt -c cookies.txt "$BASE/api/login" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"username":"illumio","password":"<password>"}'

# 3. Use session cookie for subsequent calls
curl -sk -b cookies.txt "$BASE/api/status"
```

**Error on invalid/expired CSRF token** — `400` with body:
```json
{ "ok": false, "code": "csrf_error", "error": "...", "csrf_token": "<new_token>" }
```
The response includes a refreshed token; retry the original request with it.

> **No API-key auth.** PCE-direct API keys are Illumio PCE credentials (stored
> per profile), not illumio-ops GUI credentials.

---

## Endpoints by area

All paths are relative to the base URL. Unless noted as **public** above, every
endpoint requires an authenticated session. Where a route carries its own
rate limit (beyond the global 300/min), it is shown in the Notes column.

### Auth & session

| Method | Path | Notes |
|--------|------|-------|
| `GET`  | `/api/csrf-token` | Fresh CSRF token. **Public.** |
| `GET`  | `/` | SPA shell (`index.html`). Renders HTML, not JSON. |
| `GET`  | `/login` | Login page (`login.html`). HTML. **Public.** |
| `POST` | `/api/login` | Authenticate; sets session cookie. **Public**, CSRF-exempt, 5/min. |
| `POST` | `/logout` | Clear session; `302` redirect to `/login`. **Public.** |

**`POST /api/login`** — request body:
```json
{ "username": "illumio", "password": "<password>" }
```
Response on success — `{ "ok": true, "csrf_token": "...", "must_change_password": false }`.
Response on failure — `401` `{ "ok": false, "error": "..." }`.

### Dashboard

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/status` | Daemon/version status, active PCE, per-rule cooldowns. Health endpoint (always 200). |
| `GET`  | `/api/ui_translations` | i18n strings for the SPA |
| `GET`  | `/api/dashboard/overview` | Dashboard overview (state-file snapshot) |
| `GET`  | `/api/dashboard/snapshot` | Latest snapshot JSON |
| `GET`  | `/api/dashboard/audit_summary` | Audit event summary |
| `GET`  | `/api/dashboard/policy_usage_summary` | Policy usage summary |
| `GET`  | `/api/dashboard/chart/<chart_id>` | Single chart spec (`traffic_timeline`, `policy_decisions`, `ven_status`, `rule_hits`, …) |
| `POST` | `/api/dashboard/top10` | Top-10 flows query (30/hour) |
| `GET`  | `/api/dashboard/queries` | List saved dashboard queries |
| `POST` | `/api/dashboard/queries` | Add or update a dashboard query |
| `DELETE` | `/api/dashboard/queries/<idx>` | Delete dashboard query by index |

**`GET /api/status`** — response (abridged):
```json
{
  "version": "4.1.0",
  "api_url": "https://pce.example.com:8443",
  "rules_count": 12,
  "health_check": true,
  "language": "en",
  "timezone": "local",
  "cooldowns": [{ "id": 1, "name": "PCE error alert", "remaining_mins": 0 }],
  "event_watermark": "2026-06-26T10:00:00Z"
}
```

```bash
curl -sk -b cookies.txt "$BASE/api/status" | python3 -m json.tool
```

### Events

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/events/viewer` | Fetch + normalize recent PCE events |
| `GET`  | `/api/events/shadow_compare` | Compare live events against rules (shadow mode) |
| `GET`  | `/api/events/rule_test` | Show which rules a live event would match |
| `GET`  | `/api/event-catalog` | Available PCE event types (for rule building) |

### Alert rules

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/rules` | List all alert rules |
| `POST` | `/api/rules/event` | Create an event-based rule |
| `POST` | `/api/rules/system` | Create a system-health rule |
| `POST` | `/api/rules/traffic` | Create a traffic-based rule |
| `POST` | `/api/rules/bandwidth` | Create a bandwidth rule |
| `GET`  | `/api/rules/<idx>` | Get single rule |
| `PUT`  | `/api/rules/<idx>` | Update a rule |
| `DELETE` | `/api/rules/<idx>` | Delete a rule |
| `GET`  | `/api/rules/<idx>/highlight` | Syntax-highlighted JSON of a rule (`{ "html": ... }`) |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/reports` | List all generated report files |
| `POST` | `/api/reports/generate` | Trigger traffic report generation (async job) |
| `GET`  | `/api/reports/jobs/<job_id>` | Ad-hoc report job status |
| `POST` | `/api/audit_report/generate` | Trigger audit report (10/hour) |
| `POST` | `/api/policy_diff_report/generate` | Trigger policy-diff report (10/hour) |
| `POST` | `/api/policy_resolver_report/generate` | Trigger policy-resolver report (10/hour) |
| `POST` | `/api/app_report/generate` | Trigger per-application report (10/hour) |
| `POST` | `/api/ven_status_report/generate` | Trigger VEN status report |
| `POST` | `/api/policy_usage_report/generate` | Trigger policy usage report |
| `GET`  | `/api/labels` | List PCE labels by key (`?key=app\|env\|role\|loc`, 60/hour) |
| `GET`  | `/reports/<filename>` | Download a report file |
| `DELETE` | `/api/reports/<filename>` | Delete a single report file |
| `POST` | `/api/reports/bulk-delete` | Delete multiple report files |
| `GET`  | `/api/report-schedules` | List report schedules |
| `POST` | `/api/report-schedules` | Create a report schedule |
| `PUT`  | `/api/report-schedules/<id>` | Update a report schedule |
| `DELETE` | `/api/report-schedules/<id>` | Delete a report schedule |
| `POST` | `/api/report-schedules/<id>/toggle` | Enable/disable a schedule |
| `POST` | `/api/report-schedules/<id>/run` | Run a schedule immediately |
| `GET`  | `/api/report-schedules/<id>/history` | Schedule run history |

**`POST /api/reports/generate`** — request body:
```json
{ "type": "traffic", "days": 7 }
```
Long-running reports return a `job_id`; poll `GET /api/reports/jobs/<job_id>`
until the job reports completion.

```bash
curl -sk -b cookies.txt -X POST "$BASE/api/reports/generate" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"type":"traffic","days":7}'
```

### Workloads & quarantine actions

| Method | Path | Description |
|--------|------|-------------|
| `GET` / `POST` | `/api/workloads` | Search workloads (GET → query params, POST → JSON body) |
| `POST` | `/api/init_quarantine` | Create the quarantine label/policy scaffold in the PCE |
| `POST` | `/api/quarantine/search` | Search workloads eligible for quarantine |
| `POST` | `/api/quarantine/apply` | Quarantine a single workload |
| `POST` | `/api/quarantine/bulk_apply` | Quarantine multiple workloads |
| `POST` | `/api/workloads/accelerate` | Raise the traffic update rate for given workload hrefs |
| `POST` | `/api/actions/run` | Trigger a named action |
| `POST` | `/api/actions/debug` | Debug action (dev only) |
| `POST` | `/api/actions/test-alert` | Fire a test alert dispatch |
| `POST` | `/api/actions/test-connection` | Test PCE connectivity |
| `POST` | `/api/actions/best-practices` | Apply best-practice rules |
| `POST` | `/api/actions/reset-watermark` | Clear event watermark + alert cooldowns (debug, 10/hour) |
| `GET`  | `/api/traffic/trend` | Per-day flow counts for the last 7 days, split by policy decision |

### Settings / config

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/settings` | Full settings payload (secrets redacted) |
| `POST` | `/api/settings` | Update settings |
| `GET`  | `/api/security` | Web GUI security config |
| `POST` | `/api/security` | Update web GUI security (username, password, allowed IPs) |
| `GET`  | `/api/alert-plugins` | List available alert plugin metadata |
| `GET`  | `/api/pce-profiles` | List PCE profiles |
| `POST` | `/api/pce-profiles` | Add / update / activate / delete a PCE profile |
| `GET`  | `/api/tls/status` | TLS certificate status |
| `POST` | `/api/tls/config` | Set TLS config (enable/disable) |
| `POST` | `/api/tls/renew` | Renew self-signed certificate |
| `POST` | `/api/tls/generate-csr` | Generate a CSR (20/hour) |
| `POST` | `/api/tls/import-cert` | Import a signed certificate (20/hour) |

**`GET /api/settings`** — response keys (all secrets are `"***REDACTED***"`):
```json
{
  "api": {}, "email": {}, "smtp": {}, "alerts": {},
  "settings": { "language": "en", "dashboard_queries": [] },
  "report": { "output_dir": "reports" },
  "pce_profiles": [], "active_pce_id": null
}
```

**`POST /api/pce-profiles`** — action-based body:
```json
{ "action": "add", "name": "Prod PCE", "url": "https://pce.example.com:8443",
  "org_id": "1", "key": "<api_key>", "secret": "<api_secret>", "verify_ssl": true }
```
Other actions: `"update"`, `"activate"`, `"delete"` (each requires `id`).

### Rule scheduler

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/rule_scheduler/status` | Scheduler daemon status |
| `GET`  | `/api/rule_scheduler/rulesets` | Browse PCE rulesets (`?q=&page=&size=`) |
| `GET`  | `/api/rule_scheduler/rulesets/<rs_id>` | Single ruleset detail |
| `GET`  | `/api/rule_scheduler/rules/search` | Search rules in the PCE |
| `GET`  | `/api/rule_scheduler/schedules` | List all rule schedules |
| `POST` | `/api/rule_scheduler/schedules` | Create a rule schedule |
| `GET`  | `/api/rule_scheduler/schedules/<href>` | Get a single schedule |
| `POST` | `/api/rule_scheduler/schedules/delete` | Delete a schedule |
| `POST` | `/api/rule_scheduler/check` | Dry-run schedule check |
| `GET`  | `/api/rule_scheduler/logs` | Scheduler log entries |

### SIEM destinations

Blueprint prefix: `/api/siem`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/siem/destinations` | List all SIEM destinations |
| `POST` | `/api/siem/destinations` | Create a destination |
| `PUT`  | `/api/siem/destinations/<name>` | Update a destination |
| `DELETE` | `/api/siem/destinations/<name>` | Delete a destination |
| `POST` | `/api/siem/destinations/<name>/test` | Send a test event |
| `GET`  | `/api/siem/status` | Forwarder / dispatch queue status |
| `GET`  | `/api/siem/forwarder` | Forwarder config |
| `PUT`  | `/api/siem/forwarder` | Update forwarder config |
| `GET`  | `/api/siem/dlq` | Dead-letter queue list (`?dest=&limit=`) |
| `GET`  | `/api/siem/dlq/<id>` | Single DLQ entry detail |
| `POST` | `/api/siem/dlq/replay` | Replay DLQ entries |
| `POST` | `/api/siem/dlq/purge` | Purge DLQ |
| `GET`  | `/api/siem/dlq/export` | Export DLQ as CSV |

**`POST /api/siem/destinations`** — minimal body:
```json
{ "name": "siem-udp", "transport": "udp", "host": "syslog.internal",
  "port": 514, "source_types": ["audit"] }
```

```bash
curl -sk -b cookies.txt "$BASE/api/siem/destinations"
```

### PCE cache

Blueprint prefix: `/api/cache`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/cache/status` | Cache DB status and row counts |
| `GET`  | `/api/cache/lag` | Ingestor lag per watermark source (`ok` / `warning` / `error`) |
| `GET`  | `/api/cache/health` | Single pipeline-health verdict (`ok` / `warn` / `error` / `unknown`) |
| `GET`  | `/api/cache/throughput` | Ingest event + traffic counts for the last 1h and 24h |
| `GET`  | `/api/cache/settings` | Current cache settings |
| `PUT`  | `/api/cache/settings` | Update cache settings |
| `POST` | `/api/cache/backfill` | Trigger a manual backfill |
| `POST` | `/api/cache/retention/run` | Run retention cleanup immediately |

**`GET /api/cache/status`** — response (abridged):
```json
{ "ok": true, "enabled": true, "events_rows": 45000,
  "traffic_raw_rows": 8200, "traffic_agg_rows": 120000, "db_size_mb": 38.4 }
```

### System / admin

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/logs` | List log modules and their entry counts |
| `GET`  | `/api/logs/<module>` | Recent log entries for a module (`?n=`, max 500) |
| `POST` | `/api/shutdown` | Graceful shutdown (5/hour; `403` in persistent mode) |
| `POST` | `/api/daemon/restart` | Restart the background daemon (5/hour; `409` if managed externally) |

---

## Pagination

**This API does not paginate by default.** Collection endpoints
(`/api/reports`, `/api/rules`, `/api/siem/destinations`, etc.) return complete
arrays in a single response. There are no `page` / `offset` / `Link` header
mechanisms on the illumio-ops GUI API.

Exceptions, where the route slices PCE-side results:

- `/api/rule_scheduler/rulesets` accepts `?page=&size=`.
- `/api/siem/dlq` accepts `?limit=` (capped at 500).
- `/api/logs/<module>` accepts `?n=` (capped at 500).

`page` / `page_size` / `limit` / `offset` on **PCE-direct** calls (Illumio PCE
REST API v2) are a separate concern and do not apply to this GUI API.

---

## Error model

All JSON error responses share the same envelope:

```json
{ "ok": false, "error": "<human-readable message>" }
```

Extended fields appear in specific cases:

| Field | When present |
|-------|-------------|
| `code` | CSRF errors (`"csrf_error"`); also `423` must-change-password gate |
| `csrf_token` | CSRF error response — carry this token into the retry |
| `description` | Rate-limit errors (HTTP 429) |

**HTTP status codes:**

| Code | Meaning |
|------|---------|
| `200` | Success |
| `400` | Bad request / validation error / CSRF error |
| `401` | Not authenticated |
| `403` | Forbidden (e.g. shutdown in persistent mode) |
| `404` | Resource not found |
| `409` | Conflict (e.g. daemon managed externally) |
| `423` | Locked — must change password before other calls |
| `429` | Rate limit exceeded |
| `500` | Internal error |

**Global rate limit:** 300 requests/minute per IP (fixed-window, in-memory).
Tighter per-route limits noted above include: `POST /api/login` 5/min;
`POST /api/shutdown` and `POST /api/daemon/restart` 5/hour; the report
generators 10/hour; `POST /api/dashboard/top10` 30/hour; `GET /api/labels`
60/hour; `POST /api/tls/generate-csr` and `POST /api/tls/import-cert` 20/hour.

---

## Versioning

**The illumio-ops GUI API is unversioned.** All endpoints use the `/api/`
prefix with no version segment (e.g. `/api/status`, not `/api/v1/status`).

The `https://<pce_host>:<port>/api/v2/orgs/<org_id>/...` pattern refers to the
**Illumio PCE REST API** — an entirely separate API served by the PCE
appliance, not by illumio-ops.

---

## Related Docs

- [CLI Reference](cli.md) — equivalent CLI commands
- [Operations Manual](../operations-manual_zh.md) — operator workflow for SIEM forwarding (§7), TLS, and day-2 operations (繁體中文)
- [Event Rules](../event-rules_zh.md) — the rule engine behind `/api/rules` and `/api/event-catalog` (繁體中文)
- [README](../../README.md) — architecture overview and request flow
- [Glossary](glossary.md) — Illumio terminology
