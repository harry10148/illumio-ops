---
title: Alerts and Quarantine
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/alerts/
  - src/alerts/templates/
  - src/events/matcher.py
  - src/events/throttle.py
  - src/config.py
  - src/gui/routes/actions.py
  - src/static/js/quarantine.js
  - python illumio-ops.py rule --help
  - commit 58103c4
related_docs:
  - dashboard.md
  - siem-integration.md
  - rule-scheduler.md
  - ../architecture/i18n-contract.md
---

> 🌐 **[English](alerts-and-quarantine.md)** | [繁體中文](alerts-and-quarantine_zh.md)
> 📍 [INDEX](../INDEX.md) › User Guide › Alerts & Quarantine
> 🔍 Last verified **2026-05-15** against commit `58103c4` — see frontmatter for sources

# Alerts and Quarantine

---

## Alert types

Rules fall into two top-level types based on their `"type"` field in `config/alerts.json`.

### Event rules (`"type": "event"`)

Each row maps a `name_key` to the PCE event type(s) it watches.

| `name_key` | Display name | PCE event pattern |
|---|---|---|
| `rule_agent_tampering` | Agent Tampering Detected | `agent.tampering` |
| `rule_agent_suspend` | Agent Suspended | `agent.suspend` |
| `rule_agent_clone` | Agent Clone Detected | `agent.clone_detected` |
| `rule_agent_heartbeat` | Agent Missed Heartbeats | `system_task.agent_missed_heartbeats_check` |
| `rule_agent_offline` | Agent Marked Offline | `system_task.agent_offline_check` |
| `rule_lost_agent` | Lost Agent Found | `lost_agent.found` |
| `rule_login_failed` | Login Failures | `user.sign_in,user.login` (status=failure) |
| `rule_api_auth_failed` | API Authentication Failed | `request.authentication_failed` |
| `rule_api_authz_failed` | API Authorisation Failed | `request.authorization_failed` |
| `rule_api_key_change` | API Key Created / Deleted | `api_key.create,api_key.delete` |
| `rule_policy_fail` | Policy Refresh Failure | `agent.refresh_policy` (status=failure) |
| `rule_ruleset_change` | Rule Set Changed | `rule_set.create,rule_set.update,rule_set.delete` |
| `rule_policy_provision` | Security Policy Provisioned | `sec_policy.create` |
| `rule_sec_rule_change` | Security Rule Changed | `sec_rule.create,sec_rule.update,sec_rule.delete` |
| `rule_bulk_unpair` | Bulk Workload Unpair | `workloads.unpair,agents.unpair` |
| `rule_auth_settings_change` | Authentication Settings Changed | `authentication_settings.update` |

### Traffic rules (`"type": "traffic"`)

| `name_key` | Display name | Trigger |
|---|---|---|
| `rule_high_blocked` | High Blocked Traffic volume | ≥ 25 blocked flows in 10 min window |

> [!TODO] @harry: confirm whether `rule_pce_health` (`"type": "system"`) appears in a default
> `alerts.json` install or only via custom addition — `src/config.py` defines it in i18n but it
> is not listed in `_best_practice_rules`.

---

## Configuring alert rules

### Via the Web UI (Settings → Alerts)

1. Navigate to **Settings › Alerts** (or deep-link `?stab=alerts`).
2. Each rule card shows its name, trigger condition, and current throttle.
3. Use **Edit** (pencil icon) to change threshold, cooldown, throttle, or filter fields.
4. Click **Load Best Practices** to append or replace rules with the canonical set from
   `src/config.py:_best_practice_rules()`. The mode dropdown offers:
   - `append_missing` — adds only rules not already present (default).
   - `replace` — replaces the full rule set with the canonical set.

### Via `config/alerts.json` directly

The daemon stores rules in `config/alerts.json` (not inside `config.json`). The file is
written atomically with mode `0o600`.

A minimal event rule:

```json
{
  "rules": [
    {
      "id": 1,
      "type": "event",
      "name_key": "rule_agent_tampering",
      "filter_key": "event_type",
      "filter_value": "agent.tampering",
      "filter_status": "all",
      "filter_severity": "all",
      "threshold_type": "immediate",
      "threshold_count": 1,
      "threshold_window": 10,
      "cooldown_minutes": 30,
      "throttle": ""
    }
  ]
}
```

Key fields:

| Field | Description |
|---|---|
| `name_key` | i18n key; display name is resolved at load time via `_resolve_rule_keys()` |
| `filter_value` | Comma-separated PCE event types; supports regex and pipe-separated alternation |
| `filter_status` | `"all"`, `"success"`, `"failure"`, or negation prefix `"!"` |
| `filter_severity` | `"all"`, `"err"`, `"warning"`, `"info"`, etc. |
| `threshold_type` | `"immediate"` (fire on first match) or `"count"` (N events in window) |
| `throttle` | Rate-limit format `"N/Tm"`, e.g. `"1/15m"` = at most once per 15 minutes |
| `match_fields` | Optional dict of nested PCE event field paths → match patterns |

### Via the CLI

```bash
# List all configured rules (1-based index)
python3 illumio-ops.py rule list

# Interactively edit rule at index 3
python3 illumio-ops.py rule edit 3
```

---

## Notification channels

Illumio PCE Ops ships three output plugins. All are configured in **Settings › Alerts**
(sub-tab **Channels**) or directly in `config.json` (not `alerts.json`).

### Email (SMTP) — plugin `mail`

Sends an HTML email rendered from `src/alerts/templates/mail_wrapper.html.tmpl`.

Required fields: `sender`, `recipients` (comma-separated), `smtp.host`, `smtp.port`.
Optional: `smtp.user`, `smtp.password`, `smtp.enable_tls` (STARTTLS), `smtp.enable_auth`.

Test from UI: **Settings › Alerts › Test** button, or
```bash
# POST to the test-alert endpoint (requires running Web GUI)
curl -s -X POST http://localhost:8443/api/actions/test-alert \
  -H 'Content-Type: application/json' \
  -d '{"channel": "mail"}'
```

### LINE Messaging API — plugin `line`

Sends a compact text digest rendered from `src/alerts/templates/line_digest.txt.tmpl`.

Required fields: `alerts.line_channel_access_token`, `alerts.line_target_id`
(User ID starting with `U`, room ID, or group ID).

### Webhook — plugin `webhook`

POSTs JSON rendered from `src/alerts/templates/webhook_payload.json.tmpl` to any HTTP endpoint.
Expects 2xx response; non-2xx is logged as a failure.

Required field: `alerts.webhook_url`.

> [!TODO] @harry: confirm whether there is a SIEM forwarder plugin distinct from the webhook
> plugin, or whether SIEM forwarding is covered by `illumio-ops.py siem` (the `siem` CLI
> subcommand is present but not wired to the alert plugin registry). Cross-ref
> [SIEM Integration](siem-integration.md).

---

## Quarantine workflow

Quarantine applies a PCE label (`key=Quarantine`, value `Mild` / `Moderate` / `Severe`) to one
or more workloads. The label is created automatically on first use via `/api/init_quarantine`.

Only workload objects (managed and unmanaged) can receive quarantine labels. Container workload
profiles and other resource types are not supported.

### Manual quarantine (single workload)

1. Find the workload in the **Quarantine** tab or via the workload search.
2. Click the severity button: **Mild**, **Moderate**, or **Severe**.
3. Confirm in the modal — the UI calls `POST /api/quarantine/apply` with `{ href, level }`.
4. The backend fetches the target label href via `check_and_create_quarantine_labels()`,
   strips any existing Quarantine label, and appends the new one via the PCE API.

### Bulk quarantine

1. Select multiple workloads via checkboxes.
2. Choose a severity and confirm — the UI calls `POST /api/quarantine/bulk_apply`
   with `{ hrefs: [...], level }`. Concurrent PCE updates are used for throughput.

### Removing quarantine

Re-apply a different level, or edit the workload labels in PCE directly to remove the
`Quarantine` label.

### Auto-quarantine

> [!TODO] @harry: auto-quarantine (automatic label application triggered by an alert rule
> firing) was not found wired in `src/gui/routes/actions.py` or `src/config.py` as of
> commit `58103c4`. If this feature exists, it may be in a branch not merged at this SHA.
> Verify before documenting.

---

## Accelerate Workload button

The **Accelerate** button appears in the per-workload row of the Quarantine tab and in the
bulk action bar. It is fully implemented as of commit `58103c4`.

**What it does:** Calls `POST /api/workloads/accelerate` with `{ hrefs, duration_minutes }`.
The backend calls `api.set_flow_reporting_frequency(hrefs)` on the PCE, increasing the
workload's traffic telemetry update rate temporarily.

**Architecture note (from `actions.py` docstring):**
> Backend is stateless: it issues exactly one PCE call per request. Persistent mode
> (re-issue every 10 min) is handled by the frontend via `setInterval`. Invalid hrefs
> are dropped and counted in `skipped_invalid`.

**Managed workloads only.** The row button is disabled (greyed out) for unmanaged workloads
with the tooltip `gui_accel_unmanaged_tip`. Bulk acceleration skips non-workload hrefs.

**Typical use:** When investigating an incident, accelerate the suspect workload to increase
visibility into its live traffic flows without modifying enforcement policy.

---

## Migration of legacy rules

Older `alerts.json` files may contain rules that lack `name_key` / `desc_key` / `rec_key`
fields (written by pre-key-based versions of the tool).

`src/config.py:_resolve_rule_keys()` runs on every `load()` call and handles three cases
automatically:

1. **Key-based rules** (have `name_key`): resolved via `t(key, lang=lang)` at load time.
   The rendered text is stripped before save by `_write_alerts_file()` — disk stores keys only.

2. **`[MISSING:key]` markers**: left by `apply_best_practices()` when an i18n key was absent
   at write time. On next load, if the key now exists in the translation file, the marker is
   replaced and `name_key` is back-filled so subsequent saves persist the key.

3. **Pure legacy literal names**: if the stored `name` / `desc` / `rec` matches a canonical
   English or Traditional Chinese translation of a known best-practice key
   (via `_LEGACY_FILTER_TO_NAME_KEY`), the rule is promoted to key-based storage.
   User-customized names that don't match any canonical translation are left untouched.

**`_LEGACY_FILTER_TO_NAME_KEY` mappings** (source: `src/config.py` lines 202–219):

```json
{
  "agent.tampering":                              "rule_agent_tampering",
  "user.sign_in,user.login":                     "rule_login_failed",
  "lost_agent.found":                            "rule_lost_agent",
  "system_task.agent_missed_heartbeats_check":   "rule_agent_heartbeat",
  "system_task.agent_offline_check":             "rule_agent_offline",
  "agent.suspend":                               "rule_agent_suspend",
  "agent.clone_detected":                        "rule_agent_clone",
  "request.authentication_failed":               "rule_api_auth_failed",
  "agent.refresh_policy":                        "rule_policy_fail",
  "rule_set.create,rule_set.update,rule_set.delete": "rule_ruleset_change",
  "sec_policy.create":                           "rule_policy_provision",
  "request.authorization_failed":               "rule_api_authz_failed",
  "api_key.create,api_key.delete":              "rule_api_key_change",
  "sec_rule.create,sec_rule.update,sec_rule.delete": "rule_sec_rule_change",
  "workloads.unpair,agents.unpair":             "rule_bulk_unpair",
  "authentication_settings.update":             "rule_auth_settings_change"
}
```

No manual migration step is required — promotion happens silently on the next load/save cycle.

---

## i18n behavior

Alert labels re-render on language switch. The mechanism follows the
[i18n Contract](../architecture/i18n-contract.md):

- **At load**: `_resolve_rule_keys()` calls `t(name_key, lang=lang)` for every rule that
  carries a `name_key`, populating the `name` / `desc` / `rec` fields in memory.
- **At save**: `_write_alerts_file()` strips the rendered `name` / `desc` / `rec` fields from
  rules that have `*_key` counterparts, so the file on disk always stores keys, never
  language-specific strings.
- **At render**: the Web GUI re-fetches `/api/status` (which includes rule labels) after a
  language switch. Plugin display names are resolved via `resolved_display_name(lang=lang)` on
  `PluginMeta` objects in `src/alerts/metadata.py`.
- **Language scope**: `lang` is taken from `config.settings.language` at load time; the GUI
  uses `window._uiLang` (resolved from the same config field via the snapshot response).

---

## Related Docs

- [Dashboard](dashboard.md) — KPIs that surface alert state
- [SIEM Integration](siem-integration.md) — forwarding alerts off-box
- [Rule Scheduler](rule-scheduler.md) — temporary rules driven by alerts
- [i18n Contract](../architecture/i18n-contract.md) — how alert labels stay in sync with language switching
