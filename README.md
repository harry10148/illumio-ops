# illumio-ops

![Version](https://img.shields.io/badge/Version-v4.0.0--secure--modern--saas-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** is an agentless monitoring and automation companion for **Illumio Core (PCE)**, communicating exclusively via the PCE REST API. It fills the operational gaps left by the PCE Web Console: scheduled traffic/audit/VEN-status reports, multi-channel alerting (Email, LINE, Webhook), SIEM forwarding, safe rule scheduling, workload quarantine, and multi-PCE management — all without deploying agents or touching workloads.

---

## Quick Start

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json   # edit api.url / api.key / api.secret
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Persistent daemon + Web GUI at https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

First login: `illumio` / `illumio` (forced password change on first use).

For air-gapped installs, systemd/NSSM service setup, and Windows deployment, see **[docs/getting-started.md](docs/getting-started.md)**.

---

## Documentation

All documentation lives in [docs/](docs/). Start at [INDEX.md](docs/INDEX.md).

Chinese (繁體中文): [INDEX_zh.md](docs/INDEX_zh.md).

---

## Highlights

- **Four execution modes** — background daemon, interactive CLI, standalone Web GUI, or combined monitor + GUI (`--monitor-gui`)
- **24 automated security rules** — B-series (ransomware/coverage), L-series (lateral movement/exfiltration), R-series (Draft policy alignment)
- **15-module traffic reports** + audit, policy usage, and VEN status reports; HTML / CSV / PDF / XLSX output
- **SIEM forwarder** — CEF, JSON, RFC5424 syslog, Splunk HEC over UDP/TCP/TLS/HTTPS with per-destination DLQ
- **Full i18n** — English and Traditional Chinese (繁體中文) across CLI, Web GUI, reports, and alerts

---

## Project Structure

```text
illumio-ops/
├── illumio-ops.py          # Entry point — dispatcher routes to click subcommands or legacy argparse
├── src/
│   ├── main.py                 # Legacy argparse path (--monitor / --gui / --report); delegates to src/cli for new flags
│   ├── api_client.py           # PCE REST API (async jobs, native filters, O(1) streaming)
│   ├── api/                    # PCE API helpers (async jobs, labels, traffic queries)
│   ├── analyzer.py             # Rule engine (flow matching, event analysis, state mgmt)
│   ├── cli/                    # Click subcommands + shared output / exit-code helpers (root, monitor, gui_cmd, report, rule, workload, cache, siem, status, config, menus/)
│   ├── gui/                    # Flask Web GUI package — shell + Blueprint routes (auth/admin/dashboard/events/reports/rules/rule_scheduler/actions/config) — ~70 routes total
│   ├── config.py               # ConfigManager (Argon2id GUI password, atomic writes)
│   ├── reporter.py             # Multi-channel alert dispatch (SMTP, LINE, Webhook)
│   ├── i18n/                   # i18n engine (engine.py + JSON data) — EN/ZH_TW with ~2,800 string keys
│   ├── events/                 # Event pipeline (catalog, normalize, dedup, throttle)
│   ├── report/                 # Report engine (15 traffic modules + audit + policy usage + R3 intelligence add-ons)
│   ├── scheduler/              # Report-schedule cron jobs
│   ├── settings/               # Interactive settings wizards (split from legacy settings.py)
│   ├── pce_cache/              # SQLite WAL cache + ingestors
│   ├── siem/                   # SIEM forwarder (CEF/JSON/Syslog, UDP/TCP/TLS/HEC)
│   ├── alerts/                 # Alert plugins (mail, LINE, webhook)
│   ├── templates/              # Flask HTML templates (login, index)
│   └── static/                 # Vendored fonts (Space Grotesk / Inter / JetBrains Mono), JS, CSS
├── config/                     # config.json, alerts.json, report_config.yaml, rule_schedules.json
├── docs/                       # EN + ZH_TW documentation
├── tests/                      # ~178 test files (~970 tests)
├── deploy/                     # systemd (Ubuntu/RHEL) + NSSM (Windows) service configs
└── scripts/                    # Utility scripts (offline bundle build, install/uninstall, preflight)
```

---

## Deployment Notes / 部署注意事項

> Audit reference: `docs/security-audit-2026-05-22.md` L-11 through L-14.

### L-11: Reverse Proxy

This service does **not** automatically configure Flask `ProxyFix`. When deployed behind a reverse proxy (nginx, Apache, Traefik):

- You **must** apply `ProxyFix` middleware before the app starts, trusting exactly 1 hop.
- Without it, IP allowlisting breaks — all requests appear to originate from the proxy's IP.

Example (add before the cheroot server starts in `src/gui/__init__.py`):

```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
```

### L-12: Telegram Alert Plugin — Token Leakage via Proxy Access Logs

The Telegram Bot API embeds the token in the URL path (`https://api.telegram.org/bot<TOKEN>/sendMessage`). When deploying the Telegram alert plugin in financial, defence, or high-sensitivity environments, you **must** do one of the following:

- Prevent any forward proxy or WAF from writing full URL paths to access logs.
- Use a direct (NoProxy) connection to bypass corporate proxies.
- Switch to webhook mode (though webhooks still pass through the proxy; the URL does not contain the token).

Loguru logging includes a Telegram token regex scrubber (commit T2.14), but this cannot protect intermediate network devices.

### L-13: Server Header Fingerprinting

cheroot outputs `Server: Cheroot/<version>` by default, exposing version information to fingerprinting. If your audit policy requires header suppression:

- Strip the header at the reverse proxy with `proxy_hide_header Server;` (nginx) or equivalent.
- Alternatively, add a custom cheroot WSGI middleware to remove the header (planned enhancement).

### L-14: Production Git Workflow — autoStash and Reproducibility

`scripts/setup-prod-git.sh` enables `git config merge.autoStash=true`, which means the production host may silently stash **uncommitted local edits** during `git pull` without warning. Consequences:

- The production host may **not** be bit-for-bit reproducible against the deployed `git tag`.
- To prove production exactly matches a release tag during an audit, you must verify no stashed changes exist: `git stash list` must be empty.

**Recommendation:** After each production deployment, run `git stash list` and confirm it is empty. Consider using `scripts/setup.sh` instead of `setup-prod-git.sh` for production hosts where reproducibility must be guaranteed.

## Translations (i18n)

**Single source of truth:** `src/i18n_en.json` and `src/i18n_zh_TW.json` (~2,767 keys each). Every key has an explicit value in both files; no runtime auto-translation.

**Adding a key:**
1. Add the key to **both** JSON files. Use a strict-prefix (`gui_`, `rpt_`, `rule_`, etc. — see `src/i18n/data/strict_prefixes.json`) so a missed translation surfaces as `[MISSING:key]` instead of leaking English.
2. Reference via `t("your_key", lang=lang)`. For request-scoped contexts (web routes, report rendering), always pass `lang=`; never call `set_language()` from a handler — `tests/test_i18n_set_language_callers.py` enforces this.
3. Run `python scripts/audit_i18n_usage.py` to verify glossary respect (Cat E) and parity (Cat I).

**Glossary:** `src/i18n/data/glossary.json` lists English terms that must NOT translate to Chinese in `zh_TW` values. Includes Illumio terminology (Block/Allow/Manage/Unmanage, PCE/VEN, Workload, Service, Port, Policy, Ringfence) plus general dev jargon (SMTP, Online/Offline, App, Label, Ruleset, Enforcement). Adding a new glossary term: append to `preserve_in_zh_tw` and add forbidden Chinese substitutes to `forbidden_zh_substitutes`.

**Reports:** Use `t(key, lang=lang)` directly. The legacy `STRINGS` dict in `src/report/exporters/report_i18n.py` is now a thin compatibility wrapper (`_StringsView`) over `t()` — for new code prefer `t()`.

**Rules (config.json):** Persist `desc_key` and `rec_key`, never localized `desc`/`rec` text. The loader (`ConfigManager._resolve_rule_keys`) renders keys via `t()` at read time per the active language. The migration script `scripts/migrate_rules_to_keys.py` upgrades rules from older format.

**`t()` API:**
```python
from src.i18n import t

# Use process-global language (default)
t("rpt_kicker_traffic")

# Override per call (request-scoped, thread-safe)
t("rpt_kicker_traffic", lang="zh_TW")

# With format() substitution
t("rpt_email_traffic_subject", count=42, lang=lang)

# With explicit fallback
t("possibly_missing_key", default="N/A", lang=lang)
```

**`set_language(lang)`:** Process bootstrap only (CLI startup, ConfigManager.load). Do NOT call from request handlers, scheduler tasks, or anywhere with concurrency.

**Known open items:**
- ~90 pre-existing `zh_TW` values violate the glossary preserve-list (`Label→標籤`, `Offline→離線`, etc.). They were hidden until T8 externalized the glossary (commit ce94d9a). The `forbidden_zh_substitutes` list in `glossary.json` is the source of truth; remediation requires manual edits to `i18n_zh_TW.json`. Tracked by xfail in both `tests/test_i18n_glossary.py::test_zh_tw_values_preserve_glossary_terms` and `tests/test_i18n_audit.py::test_comprehensive_i18n_audit_is_clean`.
