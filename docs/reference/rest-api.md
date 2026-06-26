---
title: REST API
audience: [api, developer, security]
last_verified: 2026-05-15
verified_against:
  - src/api/
  - src/gui/routes/
  - docs/API_Cookbook.md (legacy, audited)
  - commit 4f78332
related_docs:
  - cli.md
  - ../user-guide/siem-integration.md
  - ../architecture/overview.md
  - glossary.md
---

> 🌐 **[English](rest-api.md)** | [繁體中文](rest-api_zh.md)
> 📍 [INDEX](../INDEX.md) › Reference › REST API
> 🔍 Last verified **2026-05-15** against commit `4f78332` — see frontmatter for sources

# REST API

All endpoints listed here are served by the illumio-ops Flask GUI
(`src/gui/` + `src/siem/web.py` + `src/pce_cache/web.py`).
The default base URL is `http://127.0.0.1:5001` (TLS-enabled installs use `https://`).

---

## Auth model

The GUI uses **session-cookie authentication** backed by Flask-Login and
Flask-WTF CSRF protection. There is no standalone API key — every call
after the initial login must present:

1. **Session cookie** — obtained by `POST /api/login`; `HttpOnly`, `SameSite=Strict`,
   `Secure` (on TLS installs). Default lifetime: 8 hours (configurable via
   `web_gui.session_lifetime_seconds`).
2. **CSRF token** — required on every state-mutating request (`POST`, `PUT`, `DELETE`).
   Send the token in the `X-CSRFToken` **or** `X-CSRF-Token` request header.
   Fetch a fresh token from `GET /api/csrf-token`.

**Login flow:**

```bash
BASE="http://127.0.0.1:5001"

# 1. Fetch CSRF token (before first POST)
CSRF=$(curl -s -c cookies.txt "$BASE/api/csrf-token" | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# 2. Login
curl -s -b cookies.txt -c cookies.txt "$BASE/api/login" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"username":"illumio","password":"<password>"}'

# 3. Use session cookie for subsequent calls
curl -s -b cookies.txt "$BASE/api/status"
```

**Error on invalid/expired CSRF token** — `400` with body:
```json
{ "ok": false, "code": "csrf_error", "error": "...", "csrf_token": "<new_token>" }
```
The response includes a refreshed token; retry the original request with it.

> **No API-key auth.** The legacy `docs/API_Cookbook.md` references PCE-direct
> API keys — those are Illumio PCE credentials, not illumio-ops GUI credentials.

---

## Endpoints by area

All paths are relative to the base URL.
`login_required` means the session cookie must be present.

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/csrf-token` | Return a fresh CSRF token (no auth needed) |
| `POST` | `/api/login` | Authenticate; sets session cookie |
| `POST` | `/logout` | Invalidate session; redirect to `/login` |

**`GET /api/csrf-token`** — response:
```json
{ "csrf_token": "<token>" }
```

**`POST /api/login`** — request body:
```json
{ "username": "illumio", "password": "<password>" }
```
Response on success:
```json
{ "ok": true }
```
Response on failure: `401` `{ "ok": false, "error": "..." }`

---

### Dashboard

All dashboard endpoints require `login_required`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/status` | Daemon status + active PCE info |
| `GET`  | `/api/ui_translations` | i18n strings for the SPA |
| `GET`  | `/api/dashboard/snapshot` | Latest snapshot JSON |
| `GET`  | `/api/dashboard/audit_summary` | Audit event summary |
| `GET`  | `/api/dashboard/policy_usage_summary` | Policy usage summary |
| `GET`  | `/api/dashboard/chart/<chart_id>` | Single chart data |
| `POST` | `/api/dashboard/top10` | Top-10 flows query |
| `GET`  | `/api/dashboard/queries` | List saved dashboard queries |
| `POST` | `/api/dashboard/queries` | Add or update a dashboard query |
| `DELETE` | `/api/dashboard/queries/<idx>` | Delete dashboard query by index |

**`GET /api/dashboard/snapshot`** — response (abridged):
```json
{
  "ok": true,
  "snapshot": {
    "kpis": [{ "label": "Total Flows", "value": 12345, "label_key": "kpi_total_flows" }],
    "generated_at": "2026-05-15T10:00:00Z"
  }
}
```

```bash
curl -s -b cookies.txt "$BASE/api/dashboard/snapshot" | python3 -m json.tool
```

**`GET /api/dashboard/audit_summary`** — response:
```json
{ "ok": true, "summary": { "total": 42, "by_severity": { "err": 3, "warn": 10 } } }
```

**`GET /api/dashboard/policy_usage_summary`** — response:
```json
{ "ok": true, "summary": { "total_rules": 500, "unused": 87, "active": 413 } }
```

---

### Reports

All report endpoints require `login_required`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/reports` | List all generated report files |
| `POST` | `/api/reports/generate` | Trigger traffic report generation |
| `POST` | `/api/audit_report/generate` | Trigger audit report generation |
| `POST` | `/api/ven_status_report/generate` | Trigger VEN status report |
| `POST` | `/api/policy_usage_report/generate` | Trigger policy usage report |
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

**`POST /api/policy_usage_report/generate`** — request body:
```json
{ "start_date": "2026-04-01", "end_date": "2026-05-01" }
```
Response:
```json
{ "ok": true, "files": ["policy_usage_2026-05-01.html"], "record_count": 1200, "kpis": {} }
```

```bash
# Trigger a traffic report
curl -s -b cookies.txt -X POST "$BASE/api/reports/generate" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"type":"traffic","days":7}'
```

---

### SIEM Destinations

Blueprint prefix: `/api/siem`. All endpoints require `login_required`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/siem/destinations` | List all SIEM destinations |
| `POST` | `/api/siem/destinations` | Create a destination |
| `PUT`  | `/api/siem/destinations/<name>` | Update a destination |
| `DELETE` | `/api/siem/destinations/<name>` | Delete a destination |
| `POST` | `/api/siem/destinations/<name>/test` | Send a test event |
| `GET`  | `/api/siem/status` | Forwarder queue status |
| `GET`  | `/api/siem/forwarder` | Forwarder config |
| `PUT`  | `/api/siem/forwarder` | Update forwarder config |
| `GET`  | `/api/siem/dlq` | Dead-letter queue contents |
| `POST` | `/api/siem/dlq/replay` | Replay DLQ entries |
| `POST` | `/api/siem/dlq/purge` | Purge DLQ |
| `GET`  | `/api/siem/dlq/export` | Export DLQ as file |

**`GET /api/siem/destinations`** — response:
```json
{
  "destinations": [
    {
      "name": "splunk-hec",
      "transport": "hec",
      "host": "splunk.internal",
      "port": 8088,
      "enabled": true,
      "source_types": ["audit", "traffic"]
    }
  ]
}
```

**`POST /api/siem/destinations`** — minimal body:
```json
{
  "name": "siem-udp",
  "transport": "udp",
  "host": "syslog.internal",
  "port": 514,
  "source_types": ["audit"]
}
```

```bash
# List SIEM destinations
curl -s -b cookies.txt "$BASE/api/siem/destinations"

# Send test event to a destination
curl -s -b cookies.txt -X POST "$BASE/api/siem/destinations/splunk-hec/test" \
  -H "X-CSRFToken: $CSRF"
```

---

### Alerts (Alert Rules)

All endpoints require `login_required`.

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
| `GET`  | `/api/event-catalog` | Available PCE event types (for rule building) |
| `POST` | `/api/actions/test-alert` | Fire a test alert dispatch |

**`GET /api/rules`** — response (abridged):
```json
{
  "ok": true,
  "rules": [
    { "idx": 0, "type": "event", "enabled": true, "name": "PCE error alert" }
  ]
}
```

```bash
# List alert rules
curl -s -b cookies.txt "$BASE/api/rules"
```

---

### Cache (PCE Cache)

Blueprint prefix: `/api/cache`. All endpoints require `login_required`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/cache/status` | Cache DB status and row counts |
| `GET`  | `/api/cache/settings` | Current cache settings |
| `PUT`  | `/api/cache/settings` | Update cache settings |
| `POST` | `/api/cache/backfill` | Trigger a manual backfill |
| `POST` | `/api/cache/retention/run` | Run retention cleanup immediately |

**`GET /api/cache/status`** — response (abridged):
```json
{
  "ok": true,
  "enabled": true,
  "events_rows": 45000,
  "traffic_raw_rows": 8200,
  "traffic_agg_rows": 120000,
  "db_size_mb": 38.4
}
```

```bash
curl -s -b cookies.txt "$BASE/api/cache/status"
```

---

### Settings / Config

All config endpoints require `login_required` unless noted.

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
| `POST` | `/api/tls/generate-csr` | Generate a CSR |
| `POST` | `/api/tls/import-cert` | Import a signed certificate |

**`GET /api/settings`** — response keys (all secrets are `"***REDACTED***"`):
```json
{
  "api": {},
  "email": {},
  "smtp": {},
  "alerts": {},
  "settings": { "language": "en", "dashboard_queries": [] },
  "report": { "output_dir": "reports" },
  "pce_profiles": [],
  "active_pce_id": null
}
```

**`POST /api/pce-profiles`** — action-based body:
```json
{ "action": "add", "name": "Prod PCE", "url": "https://pce.example.com:8443",
  "org_id": "1", "key": "<api_key>", "secret": "<api_secret>", "verify_ssl": true }
```
Other actions: `"update"` (requires `id`), `"activate"` (requires `id`), `"delete"` (requires `id`).

```bash
# List PCE profiles
curl -s -b cookies.txt "$BASE/api/pce-profiles"
```

---

### Rule Scheduler

All endpoints require `login_required`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/rule_scheduler/status` | Scheduler daemon status |
| `GET`  | `/api/rule_scheduler/rulesets` | Browse PCE rulesets (`?q=&page=&size=`) |
| `GET`  | `/api/rule_scheduler/rulesets/<rs_id>` | Single ruleset detail |
| `GET`  | `/api/rule_scheduler/rules/search` | Search rules in PCE |
| `GET`  | `/api/rule_scheduler/schedules` | List all rule schedules |
| `POST` | `/api/rule_scheduler/schedules` | Create a rule schedule |
| `GET`  | `/api/rule_scheduler/schedules/<href>` | Get a single schedule |
| `POST` | `/api/rule_scheduler/schedules/delete` | Delete a schedule |
| `POST` | `/api/rule_scheduler/check` | Dry-run schedule check |
| `GET`  | `/api/rule_scheduler/logs` | Scheduler log entries |

---

### System / Admin

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET`  | `/api/logs/<module>` | Recent log entries for a module | `login_required` |
| `POST` | `/api/shutdown` | Graceful shutdown (rate-limited: 5/hour) | `login_required` |
| `POST` | `/api/daemon/restart` | Restart the background daemon | `login_required` |
| `POST` | `/api/actions/run` | Trigger an action by name | `login_required` |
| `POST` | `/api/actions/debug` | Debug action (dev only) | `login_required` |
| `POST` | `/api/actions/test-connection` | Test PCE connectivity | `login_required` |
| `POST` | `/api/actions/best-practices` | Apply best-practice rules | `login_required` |

---

## Pagination

**This API does not paginate.** All collection endpoints (`/api/reports`,
`/api/rules`, `/api/siem/destinations`, etc.) return complete arrays in a
single response. There are no `page` / `offset` / `Link` header mechanisms on
the illumio-ops GUI API.

The `page` / `page_size` / `limit` / `offset` parameters documented in
`docs/API_Cookbook.md` refer to **PCE-direct API** calls (Illumio PCE REST API
v2) and do **not** apply to this GUI API.

Exception: `/api/rule_scheduler/rulesets` accepts `?page=&size=` for
server-side slicing of PCE ruleset results.

---

## Error model

All JSON error responses share the same envelope:

```json
{ "ok": false, "error": "<human-readable message>" }
```

Extended fields appear in specific cases:

| Field | When present |
|-------|-------------|
| `code` | CSRF errors (`"csrf_error"`) |
| `csrf_token` | CSRF error response — carry this token into the retry |
| `description` | Rate-limit errors (HTTP 429) |

**HTTP status codes:**

| Code | Meaning |
|------|---------|
| `200` | Success |
| `400` | Bad request / validation error / CSRF error |
| `401` | Not authenticated |
| `403` | Forbidden (e.g., shutdown in persistent mode) |
| `404` | Resource not found |
| `409` | Conflict (e.g., daemon managed externally) |
| `429` | Rate limit exceeded (`{ "ok": false, "error": "rate_limit_exceeded" }`) |
| `500` | Internal error |

Global rate limit: **300 requests/minute** per IP (fixed-window, in-memory).
Specific limits: `POST /api/shutdown` and `POST /api/daemon/restart` — 5/hour.

---

## Versioning

**The illumio-ops GUI API is unversioned.** All endpoints use the `/api/`
prefix with no version segment (e.g., `/api/status`, not `/api/v1/status`).

The `https://<pce_host>:<port>/api/v2/orgs/<org_id>/...` pattern documented in
`docs/API_Cookbook.md` refers to the **Illumio PCE REST API** — an entirely
separate API served by the PCE appliance, not by illumio-ops.

> **TODO:** Add semver contract or deprecation policy if the GUI API is ever
> consumed by external tooling outside the SPA.

---

## Related Docs
- [CLI Reference](cli.md) — equivalent CLI commands
- [SIEM Integration](../_archive/user-guide/siem-integration.md) — operator workflow for SIEM destinations
- [Architecture Overview](../_archive/architecture/overview.md) — request flow & Flask routes (next task)
- [Glossary](glossary.md) — Illumio terminology
