---
title: Multi-PCE
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/settings/manager.py
  - src/config.py
  - src/config_models.py
  - config/config.json.example
  - src/gui/routes/config.py
  - src/static/js/settings.js
  - src/cli/
  - python illumio-ops.py --help
  - commit 11a4ffc
related_docs:
  - tls-and-certificates.md
  - dashboard.md
  - settings-and-pce-cache.md
  - ../reference/cli.md
---

> 🌐 **[English](multi-pce.md)** | **[繁體中文](multi-pce_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › Multi-PCE
> 🔍 Last verified **2026-05-15** against commit `11a4ffc` — see frontmatter for sources

# Multi-PCE

Illumio-Ops stores PCE connection details as a list of **profiles** in
`config/config.json`.  Only one profile is *active* at a time — every feature
(monitoring, reports, rules, SIEM cache) operates against that single active
profile.  You can store multiple profiles and switch between them without
editing the file by hand.

> [!NOTE]
> **Current support level: multi-PCE with manual profile switching.**
> Profiles are stored and the Web GUI Settings page lets you add, activate, and
> delete them.  There is no automatic polling of multiple PCEs simultaneously;
> only the active profile is monitored at any given moment.

---

## When to use multiple PCEs

Store more than one profile when your environment has any of the following:

| Scenario | Example |
|---|---|
| Separate lab and production PCEs | `lab.pce.example.com` + `pce.example.com` |
| Federated tenants / Illumio Cloud SaaS | One org per tenant, distinct API keys |
| Staged rollout | Old PCE version alongside upgraded PCE |
| DR / failover pair | Active site + standby site |

Because only one profile is active at a time, multi-profile operation is
sequential: monitor one PCE for a period, then activate another and repeat.
Simultaneous monitoring of two PCEs in a single running process is not
currently implemented.

---

## Adding a PCE

### Via the Web GUI (recommended)

1. Open **Settings → PCE Profiles** in the sidebar.
2. Click **Add Profile** and fill in:
   - **Name** — a human-readable label (required)
   - **URL** — full base URL including port, e.g. `https://pce.example.com:8443` (required)
   - **Org ID** — defaults to `1`
   - **API Key** and **API Secret** — from the PCE user's API key page
   - **Verify SSL** — uncheck only for self-signed certs in a lab environment
3. Click **Save**.  The profile appears in the table immediately.
4. To make it the active profile, click **Activate** next to its row.
   The header chip updates to show the new PCE URL.

### Via `config/config.json` directly

Add an object to the `pce_profiles` array and update `active_pce_id`:

```json
{
  "pce_profiles": [
    {
      "id": 1000000000001,
      "name": "Production PCE",
      "url": "https://pce.example.com:8443",
      "org_id": "1",
      "key": "api_xxxxxxxxxxxxxx",
      "secret": "your-api-secret-here",
      "verify_ssl": true
    },
    {
      "id": 1000000000002,
      "name": "Lab PCE",
      "url": "https://lab-pce.example.com:8443",
      "org_id": "1",
      "key": "api_yyyyyyyyyyyyyy",
      "secret": "lab-secret-here",
      "verify_ssl": false
    }
  ],
  "active_pce_id": 1000000000001
}
```

The `id` field must be a unique integer.  The CLI interactive shell uses
`int(time.time() * 1000)` (millisecond epoch) when auto-assigning IDs.

Restart the process (or reload via the GUI) after editing the file manually.

### No dedicated CLI subcommand

`python3 illumio-ops.py --help` shows no `pce` subcommand.  Profile
management from the command line is available only through the interactive
**shell** menu (`python3 illumio-ops.py shell`) under **Settings → API
credentials**, which edits the active profile's fields.  Adding a new profile
from the CLI requires direct `config.json` editing or the Web GUI.

---

## PCE switcher

### Web GUI switcher (implemented)

The **Settings → PCE Profiles** table in `settings.js` renders an **Activate**
button for every non-active profile.  Clicking it calls:

```
POST /api/pce-profiles  { "action": "activate", "id": <profile-id> }
```

`ConfigManager.activate_pce_profile()` in `src/config.py` then:
1. Sets `active_pce_id` to the chosen profile ID.
2. Copies `url`, `org_id`, `key`, `secret`, `verify_ssl` from that profile
   into the top-level `api` block (which the running API client reads).
3. Saves `config.json`.

The header chip (`<span class="pce-host">`) updates immediately via a page
reload triggered by `loadSettings()`.

> [!NOTE]
> **No dashboard PCE-switcher widget.**  B1.4 audit confirmed that
> `index.html` contains no `pce_switcher` element or `switchPce` call.
> Switching is done exclusively from the **Settings** page, not from the
> dashboard.

### After switching

The monitoring daemon reads `active_pce_id` at next poll cycle.  If the daemon
is running, it picks up the change on the next interval without a restart.
If the profile switch has no effect, verify that the **Activate** button was
used (not just **Save** on the edit form) — only `activate` copies credentials
into the `api` block.  See also the troubleshooting note in
`docs/User_Manual.md` §6: *"PCE profile switch has no effect → ApiClient not
reinitialized → Use the GUI Activate button or CLI profile switch, which
triggers reinitialization."*

---

## Per-PCE settings vs shared

| Setting | Scope | Where stored |
|---|---|---|
| `url` | Per-PCE profile | `pce_profiles[*].url` |
| `org_id` | Per-PCE profile | `pce_profiles[*].org_id` |
| `key` / `secret` | Per-PCE profile | `pce_profiles[*].key/secret` |
| `verify_ssl` | Per-PCE profile | `pce_profiles[*].verify_ssl` |
| Alert rules | **Global** — shared across all profiles | `config/alerts.json` |
| Report schedules | **Global** — run against active profile | `config.json › report_schedules` |
| Email / SMTP | **Global** | `config.json › email / smtp` |
| Web GUI credentials & TLS | **Global** | `config.json › web_gui` |
| PCE cache | **Global** path; data is tagged by active profile | `config.json › pce_cache` |
| SIEM forwarder | **Global** config; targets active profile | `config.json › siem` |
| Timezone / language / theme | **Global** | `config.json › settings` |

Switching the active profile does **not** reset existing rules or report
schedules.  All rules continue to apply to whatever PCE is currently active.

---

## Authentication & TLS per PCE

Each profile carries its own `verify_ssl` flag.  There is no per-profile TLS
CA bundle field in the current schema (`PceProfile` in `src/config_models.py`
has only `id`, `url`, `org_id`, `key`, `secret`, `name`, and `verify_ssl`).

If a PCE uses a private CA:

- Set `verify_ssl: true` (do not disable verification).
- Install the CA certificate into the system trust store on the host running
  illumio-ops, so Python's `requests` library can validate it automatically.
- Alternatively, use the `REQUESTS_CA_BUNDLE` environment variable to point
  to a specific bundle file.

The **Web GUI's own TLS** (HTTPS for the operator browser session) is separate
from PCE TLS and is configured under `web_gui.tls` — see
[TLS & Certificates](tls-and-certificates.md).

> [!NOTE]
> Per-PCE CA bundle / client-cert fields are not yet in the schema.  If you
> need per-profile CA pinning, track issue or add a `ca_bundle` key under
> `extra=allow` (the model accepts unknown fields) and point your code to it.

---

## Reports across PCEs

The report engine (`src/reporter.py`) calls `_active_pce_url()` at generation
time, which reads `active_pce_id` → looks up the matching profile's `url`.
**Reports are always generated for the single active profile.**

To produce reports for two PCEs:

1. Activate profile A → run `python3 illumio-ops.py report …` → save output.
2. Activate profile B → run again → save output.

There is no built-in "run report against all profiles and merge" feature.
Scheduled reports (`report_schedules`) likewise target the active profile at
the time the scheduler fires.

> [!TODO]
> Multi-PCE parallel report generation (fan-out) is not implemented.  A future
> enhancement could add a `--all-profiles` flag to the `report` subcommand.

---

## Related Docs

- [TLS & Certificates](tls-and-certificates.md) — per-PCE TLS configuration
- [Dashboard](dashboard.md) — how dashboard surfaces multi-PCE state today
- [Settings & PCE Cache](settings-and-pce-cache.md) — per-PCE cache management
- [CLI Reference](../reference/cli.md) — PCE-management commands (if any)
