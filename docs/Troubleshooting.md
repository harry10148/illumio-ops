# Troubleshooting

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
<!-- END:doc-map -->

> **[English](Troubleshooting.md)** | **[繁體中文](Troubleshooting_zh.md)**

---

This page is the single hub for common operational issues. Per-feature docs (User Manual, PCE Cache, SIEM Integration) keep their own troubleshooting fragments; this page consolidates them and adds cross-cutting items.

## 1. Installation & Service

| Symptom | Likely cause | Fix |
|---|---|---|
| `externally-managed-environment` pip error on Ubuntu/Debian | PEP 668 blocks system-wide `pip install` on Ubuntu 22.04+ / Debian 12+ | Create a venv: `python3 -m venv venv && source venv/bin/activate && venv/bin/pip install -r requirements.txt`. Re-activate the venv in every new shell. |
| Web GUI / `--monitor` won't start, missing module errors | Dependencies not installed under the active interpreter | **Production (offline bundle)**: run `/opt/illumio_ops/python/bin/python3 /opt/illumio_ops/scripts/verify_deps.py` to identify the missing package, then re-run `sudo ./install.sh` from the bundle. **Development**: `pip install -r requirements.txt` (use a venv on Ubuntu 22.04+ / Debian 12+). |
| systemd: `illumio-ops` service exits immediately | Bad `config.json`, unwritable `data/` or `logs/` paths, or missing PCE credentials | `sudo systemctl status illumio-ops -l` and `sudo journalctl -u illumio-ops -n 100`. Run `illumio-ops config validate` against the install root. Confirm the `illumio_ops` system user owns `/opt/illumio_ops/{data,logs,config}`. |
| Windows: `IllumioOps` service stops immediately after start | NSSM cannot find the bundled Python, `config.json` invalid, or service account lacks rights to install dir | Check `C:\illumio_ops\logs\illumio_ops.log`; verify `nssm.exe get IllumioOps Application` points at the bundled `python\python.exe`; re-run `.\install.ps1` as Administrator. |
| Windows: `nssm.exe not found` during install | NSSM not in PATH or missing from bundle `deploy\` | Download NSSM from https://nssm.cc/download, place `nssm.exe` in PATH or in the bundle `deploy\` folder, re-run `.\install.ps1`. |
| After upgrade: old config still loaded | `install.sh` / `install.ps1` deliberately preserves the entire `config/` tree | Diff against the new template: `diff /opt/illumio_ops/config/config.json.example /opt/illumio_ops/config/config.json` and merge new keys manually. |
| `--purge` accidentally removed config | `uninstall.sh --purge` is documented as destructive and removes `config/` | Restore from backup. Without `--purge`, the default uninstall always preserves `config/`. |
| `report_config.yaml` reset after upgrade | The installer replaces the bundled `report_config.yaml` (which may carry new analysis parameters) | Back up before upgrading: `sudo cp config/report_config.yaml config/report_config.yaml.bak`, run `sudo ./install.sh`, then merge your changes back. |

## 2. PCE Connectivity

| Symptom | Likely cause | Fix |
|---|---|---|
| `verify_ssl` / SSL verification errors | PCE uses a self-signed or private-CA certificate | Either set `api.verify_ssl: false` (lab only), or place the PCE CA bundle on disk and point `api.verify_ssl` at the CA file path. |
| `401 Unauthorized` from PCE | Wrong `api.key` / `api.secret`, expired key, or insufficient role | Regenerate the API Key in PCE Console (**User Menu → My API Keys → Add**). Minimum role: `read_only` for monitoring; `owner` for quarantine operations. |
| `Connection refused` / connection timeout | PCE host unreachable, wrong port, proxy or firewall blocking | Verify `api.url` includes the port (default `:8443`); test with `curl -kv https://pce.lab.local:8443/api/v2/health`; check egress proxy / corporate firewall rules. |
| `410 Gone` on traffic queries | Async query result expired on the PCE side | Re-run the query — async traffic results are short-lived and cleaned up by the PCE. |
| `429 Too Many Requests` from PCE | Hit the 500 req/min PCE rate limit | The system auto-retries with exponential backoff. If persistent, lower `pce_cache.rate_limit_per_minute` (default 400) to 200–300, or reduce report/alert frequency. |
| PCE profile switch has no effect | `ApiClient` not reinitialized after the change | Use the GUI **Activate** button or the CLI profile-switch flow — both trigger reinitialization. Editing `config.json` by hand without reload will not take effect. |

## 3. Web GUI Login

| Symptom | Likely cause | Fix |
|---|---|---|
| Cannot log in to Web GUI on first start | Initial password not yet read | Read `web_gui._initial_password` from `config/config.json`, or check the console banner / `logs/illumio_ops.log` at startup. Default username is `illumio`. |
| Lost password / locked out | Forgot password after first-login change | Stop the service, clear `web_gui.password` (and `web_gui._initial_password` if present) in `config/config.json`, restart — a new initial password is generated and the force-change flow re-arms. |
| Every endpoint returns `423 Locked` | First-login force-change flow is active (`web_gui.must_change_password: true`) | Log in and complete the flow at **Settings → Web GUI Security**. All other endpoints are intentionally locked until a new password is set. |
| `429 Too Many Requests` on the login page | Login rate limit (5 attempts per IP per minute) tripped | Wait 60 seconds, or restart the service to clear the in-memory limiter. Persistent 429s indicate a brute-force attempt — review `logs/illumio_ops.log`. |
| `403 Forbidden` after correct login | Source IP not in `web_gui.allowed_ips` allowlist | Add the client IP or CIDR (e.g. `192.168.1.50` or `10.0.0.0/24`) to `web_gui.allowed_ips`. An empty list permits all sources. The allowlist honours `X-Forwarded-For` when the GUI is behind a proxy. |
| Web GUI login fails after uninstall + reinstall | Old `config.json` with stale Argon2id `web_gui.password` was preserved across reinstall | The hashed password persists across upgrades; log in with the password you used previously. To re-arm the initial-password flow, clear `web_gui.password` and `web_gui._initial_password` in `config/config.json`. |
| Cannot reach `https://<host>:5000` (TLS handshake failure) | Client TLS version below `web_gui.tls.min_version` (default `TLSv1.2`), or self-signed cert rejected by browser | Verify the client supports the configured `min_version`. For self-signed certs, accept the browser warning or distribute the auto-generated cert from `data/web_gui_cert.pem` to clients. |
| CSRF token errors on POST/PUT/DELETE | Stale tab / missing `X-CSRF-Token` header | Refresh the page; the token is delivered via the `X-CSRF-Token` response header and a `<meta>` tag, and must accompany all state-changing requests. |

## 4. Reports

| Symptom | Likely cause | Fix |
|---|---|---|
| Empty report | Data not yet in cache and the API window is too narrow | Run `illumio-ops cache backfill --source events --since YYYY-MM-DD` (and `--source traffic`), or widen `--since` / `--until` on the report command. |
| Report shows all VENs as online | Cached state is stale or PCE response missing `hours_since_last_heartbeat` | Confirm your PCE version returns `hours_since_last_heartbeat`; check the raw PCE API response for `agent.status` fields. |
| Policy Usage report shows 0 hits | Only active (provisioned) rules are queried | Provision draft rules in the PCE Console; draft-only rules are intentionally excluded. |
| `mod_change_impact` shows `skipped: no_previous_snapshot` | First report run, or the prior snapshot was pruned by retention | Generate a second report after the first. Snapshots persist for `report.snapshot_retention_days` days. |
| PDF rendering: missing CJK glyphs / boxes | `reportlab` cannot find a CJK font on the host | Install a CJK font (e.g. `fonts-noto-cjk` on Debian/Ubuntu, `google-noto-cjk-fonts` on RHEL). PDFs are static English summaries by design — prefer `--format html` / `--format xlsx` for full localized content. |
| Email not sent | SMTP `enable_auth: false` but the server requires auth, or wrong credentials | Toggle `smtp.enable_auth: true`, set `smtp.user` and either `smtp.password` or the `ILLUMIO_SMTP_PASSWORD` environment variable. Verify with **CLI Menu 1. Alert Rules → 6. Send Test Alert**. |
| `Destination not found` on `siem test` | Destination name typo, or `enabled: false` on the destination | Confirm `siem.destinations[].name` exactly matches the CLI argument; ensure `enabled: true` on that destination. |

## 5. PCE Cache

These rows are reused from [PCE Cache § Troubleshooting](./PCE_Cache.md#troubleshooting). Refer to that page for the full cache lifecycle.

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cache database not configured` | `pce_cache.enabled: false` or `pce_cache.db_path` is wrong / unwritable | Set `pce_cache.enabled: true` and verify `db_path` (default `data/pce_cache.sqlite`) is writable by the runtime user. |
| `429` errors flooding the log | PCE rate limit hit | Lower `pce_cache.rate_limit_per_minute` (default 400) to 200–300. |
| Cache DB growing fast | `traffic_raw_retention_days` (default 7) too high for your flow volume | Drop `traffic_raw_retention_days` to 3–5. Aggregated rows (`pce_traffic_flows_agg`) remain at `traffic_agg_retention_days`. |
| Watermark not advancing | Events ingest error | Search `logs/illumio_ops.log` for `Events ingest failed`; check PCE API reachability and credentials. |
| `Cache DB locked` errors | Multiple processes writing to the same SQLite file | Ensure only one `--monitor` / `--monitor-gui` process runs against a given `db_path`. |
| `Global rate limiter timeout` in log | PCE budget exhausted | Lower `pce_cache.rate_limit_per_minute` and review whether multiple clients share the same PCE API Key. |
| Cache lag warnings (`cache_lag_monitor`) | Ingestor stalled longer than `3 × max(events_poll_interval, traffic_poll_interval)` seconds | Inspect `logs/illumio_ops.log` for ingestor errors; check PCE reachability and rate limit headroom. |

## 6. SIEM Dispatch

| Symptom | Likely cause | Fix |
|---|---|---|
| DLQ growing | Destination unreachable or format mismatch (Splunk index, sourcetype, schema) | List dead-lettered events with `illumio-ops siem dlq --dest <name>`. Fix the root cause, then `illumio-ops siem replay --dest <name> --limit 1000`. |
| Splunk HEC `400 Bad Request` | Wrong index / sourcetype / token, or payload doesn't match the configured `format` | Verify `hec_token`, the destination index in Splunk, and the `format` field (`json` vs `cef`). Compare against the format samples in [SIEM Integration § Format Samples](./SIEM_Integration.md#format-samples). |
| TCP/TLS connection refused | Wrong `endpoint` (`host:port`), firewall blocking, or syslog server not listening | Confirm `endpoint` in the destination config; test with `nc -vz <host> <port>` or `openssl s_client -connect <host>:<port>` for TLS. |
| TLS verify failure | Custom PKI not trusted by the system CA store | Set `tls_ca_bundle` on the destination to the path of your CA bundle. Set `tls_verify: false` only for development. |
| `Destination not found` on `siem test` | Destination name typo or `enabled: false` | Confirm `siem.destinations[].name` matches the argument; ensure `enabled: true`. |
| SIEM forwarder enabled but no rows dispatched | PCE cache disabled (forwarder reads from `pce_cache.sqlite`), or `siem.enabled: false` | Set `pce_cache.enabled: true` first, then `siem.enabled: true`. Check `illumio-ops siem status` for per-destination dispatch counts. |
| Rows stuck in `pending` after restart | Known preview-status gap: payload-build failures can leave rows in persistent `pending` (see SIEM_Integration § Status warning) | Inspect `logs/illumio_ops.log` for formatter errors; manually clear stuck rows from `siem_dispatch` if needed. |

## 7. Logs & Diagnostics

- **Log files** live under `logs/` in the install root:
  - `logs/illumio_ops.log` — human-readable text, rotated at 10 MB, 10 backups retained.
  - `logs/illumio_ops.json.log` — structured JSON sink (one record per line), enabled when `logging.json_sink: true`. Suitable for shipping to Splunk / Elastic / Loki.
  - `logs/state.json` — runtime state for report schedules and rule cooldowns; do not edit by hand.
- **Enable DEBUG logging** by setting `logging.level: DEBUG` in `config/config.json`, then restart the service. DEBUG output is verbose — revert to `INFO` once the issue is captured.
- **Inspect the live config** with `illumio-ops config show` (sensitive fields redacted) or limit to a section: `illumio-ops config show --section web_gui`.
- **Validate the config** before restart with `illumio-ops config validate` — non-zero exit indicates a pydantic validation error; the message names the offending field. Compare against `config/config.json.example` for new keys after upgrades.
- **Cache diagnostics**: `illumio-ops cache status` (row counts and last-ingested timestamps), `illumio-ops cache retention` (current TTL policy), `illumio-ops cache retention --run` (purge now).
- **SIEM diagnostics**: `illumio-ops siem status` (per-destination dispatch counts), `illumio-ops siem test <name>` (synthetic event), `illumio-ops siem dlq --dest <name>` (list dead-lettered rows).
- **systemd / Windows service logs**: `sudo journalctl -u illumio-ops -n 200 -f` on Linux; Event Viewer → Application logs (filter source `IllumioOps`) on Windows.

## See also

- [User Manual § 3 Web GUI Security](./User_Manual.md#3-web-gui-security)
- [User Manual § 10 Troubleshooting](./User_Manual.md#10-troubleshooting) — the per-feature troubleshooting table this page consolidates from
- [PCE Cache § Troubleshooting](./PCE_Cache.md#troubleshooting)
- [SIEM Integration § DLQ Operator Guide](./SIEM_Integration.md#dlq-operator-guide)
- [Installation](./Installation.md) — platform install, upgrade, uninstall, offline bundle
