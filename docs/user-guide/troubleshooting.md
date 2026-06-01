---
title: Troubleshooting
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - docs/Troubleshooting.md (legacy, audited)
  - logs/
  - scripts/setup-prod-git.sh
  - commit 8dd14b7
related_docs:
  - ../getting-started.md
  - tls-and-certificates.md
  - siem-integration.md
  - reports.md
---

> **[English](troubleshooting.md)** | **[繁體中文](troubleshooting_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › Troubleshooting
> 🔍 Last verified **2026-05-15** against commit `8dd14b7` — see frontmatter for sources

# Troubleshooting

---

## Logs — where to look

All log files live under `logs/` in the install root (`/opt/illumio-ops/logs/` for production bundles).

| File | Contents | Rotation |
|---|---|---|
| `logs/illumio_ops.log` | Human-readable application log (all levels ≥ configured minimum) | 10 MB, 10 backups retained |
| `logs/illumio_ops.json.log` | Structured JSON sink — one record per line; enabled when `logging.json_sink: true` | Same rotation as text log |
| `logs/state.json` | Runtime state for report schedules and rule cooldowns | Not rotated — do not edit by hand |

**Changing the log level:**

```bash
# In config.json, set:
"logging": { "level": "DEBUG", "retention": 10, "rotation": "10 MB" }
```

Valid levels (ascending verbosity): `ERROR`, `WARNING`, `INFO`, `DEBUG`.

**Quick log tail (production systemd):**

```bash
sudo journalctl -u illumio-ops -f -n 100
# or read the file directly:
tail -f /opt/illumio-ops/logs/illumio_ops.log
```

---

## Common install issues

### `externally-managed-environment` pip error on Ubuntu/Debian

- **Symptom:** `pip install` fails with `error: externally-managed-environment`.
- **Cause:** Ubuntu 22.04+ / Debian 12+ enforce PEP 668 — direct system-wide pip installs are blocked.
- **Fix:** Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Re-activate the venv (`source venv/bin/activate`) in every new shell session before running the application.

### Missing module errors / `--monitor` won't start

- **Symptom:** `ModuleNotFoundError` on startup, or the GUI fails to launch.
- **Cause:** Dependencies not installed under the active interpreter — common when the wrong Python is on `$PATH`.
- **Fix (production offline bundle):**

```bash
/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/scripts/verify_deps.py
# If missing packages are reported, re-run the installer:
sudo ./install.sh
```

- **Fix (development):** `pip install -r requirements.txt` inside the activated venv.

### `TypeError: unsupported operand type(s) for |` at startup

- **Symptom:** Python raises `TypeError` involving the `|` operator on type hints.
- **Cause:** The active interpreter is older than Python 3.10 (union type syntax `X | Y` requires 3.10+).
- **Fix:** Use the bundle's bundled CPython 3.12 for production, or recreate the development venv with Python 3.10+.

```bash
python3 --version   # verify ≥ 3.10
```

---

## PCE connection failures

### Auth failed / API key rejected

- **Symptom:** Dashboard **PCE Status** widget shows "auth failed"; logs contain `401` or `403`.
- **Cause:** `api.key` or `api.secret` in `config.json` is wrong, or the key was revoked in the PCE Web Console.
- **Fix:** Re-mint an API key in the PCE Web Console (top-right user menu → **My API Keys** → **Add**), then update `config.json`:

```json
"api": {
  "url": "https://pce.example.com:8443",
  "key": "<auth_username from PCE>",
  "secret": "<secret from PCE>",
  "org_id": "1",
  "verify_ssl": true
}
```

Then restart the service: `sudo systemctl restart illumio-ops`.

### Connection refused / network unreachable

- **Symptom:** Logs show `ConnectionRefusedError` or `TimeoutError` connecting to the PCE URL.
- **Cause:** Network firewall, wrong port, or PCE is down.
- **Fix:**

```bash
# Test reachability from the host running illumio-ops:
curl -v --max-time 5 https://pce.example.com:8443/api/v2/health
```

Confirm port 8443 (or the configured port) is open between this host and the PCE.

### SSL verification error with lab PCE

- **Symptom:** `SSLCertVerificationError` in logs; PCE uses a self-signed cert.
- **Cause:** `api.verify_ssl` defaults to `true`.
- **Fix:** Set `"verify_ssl": false` in `config.json` for lab environments. For production, see [TLS & Certificates](tls-and-certificates.md) to install the CA bundle instead.

---

## TLS / cert mismatches

For the full certificate management workflow (self-signed, ACME/Let's Encrypt, custom CA), see **[TLS & Certificates](tls-and-certificates.md)**.

### Web GUI cert warning in browser

- **Symptom:** Browser shows "Your connection is not private" / `NET::ERR_CERT_AUTHORITY_INVALID`.
- **Cause:** Self-signed certificate — expected for new installs.
- **Fix:** Either accept the browser warning for internal use, or provision a CA-signed cert via the **Settings → TLS** panel (GUI) or `illumio-ops tls` CLI.

### Certificate expired

- **Symptom:** Log line: `TLS: certificate expires in -N days`.
- **Cause:** Auto-renew is disabled, or cert renewal failed silently.
- **Fix:**

```bash
illumio-ops tls renew
sudo systemctl restart illumio-ops
```

Enable auto-renew in Settings → TLS → **Auto-renew on startup before expiry**.

### SIEM TLS destination: handshake failure

- **Symptom:** `SSL: CERTIFICATE_VERIFY_FAILED` in SIEM dispatch logs.
- **Cause:** The SIEM server uses a private CA certificate not trusted by the system bundle.
- **Fix:** Set `ca_bundle` on the SIEM destination to the path of the CA certificate file:

```json
"siem": {
  "destinations": [
    { "type": "syslog_tls", "host": "siem.internal", "port": 6514,
      "tls_verify": true, "ca_bundle": "/etc/ssl/certs/internal-ca.pem" }
  ]
}
```

To skip verification in a lab: `"tls_verify": false` (logs a warning).

---

## Report fails to generate

### Empty report / no data

- **Symptom:** Report runs without error but all tables are empty or show zero counts.
- **Cause:** No data in the cache for the selected time window, or the window is too narrow.
- **Fix:**

```bash
illumio-ops cache backfill --source events --since 2026-01-01
illumio-ops cache backfill --source traffic --since 2026-01-01
```

Then regenerate the report with a wider `--since` / `--until` range.

### `mod_change_impact` shows `skipped: no_previous_snapshot`

- **Symptom:** Change-impact section is blank on the first run.
- **Cause:** No prior snapshot exists to diff against.
- **Fix:** Generate a second report after the first; snapshots persist for `report.snapshot_retention_days` days (default: 30).

### PDF shows boxes instead of CJK characters

- **Symptom:** PDF report renders correctly in HTML, but the PDF has empty boxes where Chinese/Japanese characters should appear.
- **Cause:** `reportlab` cannot locate a CJK font on the host.
- **Fix:**

```bash
# Debian/Ubuntu
sudo apt install fonts-noto-cjk
# RHEL/Rocky
sudo dnf install google-noto-cjk-fonts
```

Regenerate the report after installing the fonts. Prefer `--format html` if PDF CJK output remains problematic.

### Policy Usage report shows 0 hits

- **Symptom:** The Policy Usage section shows zero rule hits even though traffic exists.
- **Cause:** Only provisioned (active) rules are queried; draft rules are excluded by design.
- **Fix:** Provision draft rules in the PCE Console before running the report.

---

## SIEM destination not receiving events

### Test event fails immediately

```bash
illumio-ops siem test <destination-name>
```

Check the output for the specific error. Common causes:

| Error | Cause | Fix |
|---|---|---|
| `Connection refused` | SIEM port is wrong or listener is down | Confirm the SIEM ingest port and whether a TCP/UDP listener is active |
| `Timed out` | Firewall between illumio-ops host and SIEM | Open the required port; test with `nc -zv <host> <port>` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | TLS transport with untrusted CA | See [TLS / cert mismatches](#tls--cert-mismatches) above |
| Events sent but not appearing | Format mismatch, wrong index/source type | Verify the SIEM expects the configured format (`syslog`, `cef`, `normalized_json`) |

### TCP reconnect loop in logs

- **Symptom:** Log repeatedly shows `TCP syslog connection lost, reconnecting`.
- **Cause:** Network interruption or SIEM listener restarted; the transport reconnects automatically.
- **Fix:** This is expected transient behavior. If it persists, check network stability and SIEM listener health.

### UDP events silently dropped

- **Symptom:** UDP destination shows no errors but SIEM receives nothing.
- **Cause:** UDP has no delivery guarantee; packets are dropped silently at congested hops.
- **Fix:** Switch to `syslog_tcp` or `syslog_tls` for reliable delivery. Confirm the SIEM UDP listener is active and bound to the correct interface.

---

## Dashboard shows stale data

### KPI widgets show old values after PCE changes

- **Symptom:** Dashboard KPIs reflect data from a previous run; refreshing the browser doesn't help.
- **Cause:** The dashboard reads `logs/latest_snapshot.json`; this file is only updated when a report run completes.
- **Fix:**

```bash
illumio-ops report run --format snapshot
```

Or use **Dashboard → Refresh** in the GUI (triggers a lightweight snapshot update without a full report).

### Snapshot file missing

- **Symptom:** Dashboard shows "No snapshot available" banner.
- **Cause:** The service has never completed a successful report run, or the snapshot was deleted.
- **Fix:** Run `illumio-ops report run` once to generate an initial snapshot.

### Legacy snapshot labels appear untranslated after language switch

- **Symptom:** After switching language in Settings, some KPI labels remain in the old language.
- **Cause:** Snapshots generated before version 3.26.0 store rendered text instead of i18n keys. Legacy entries fall back gracefully but cannot be retranslated.
- **Fix:** Regenerate the snapshot: `illumio-ops report run --format snapshot`. New snapshots include `label_key` and reflect the active language immediately.

---

## i18n / language switching issues

### Language toggle in Settings has no effect

- **Symptom:** Selecting **Chinese (Traditional)** or **English** in Settings → Language and saving has no visible effect.
- **Cause:** Browser may have cached the old translation bundle.
- **Fix:** Hard-refresh the browser (`Ctrl+Shift+R` / `Cmd+Shift+R`) after saving the language setting.

### `[MISSING:some_key]` appears in the UI

- **Symptom:** A UI label displays as `[MISSING:alert_rec_xyz]`.
- **Cause:** An alert rule created before version 3.26.0 still uses the legacy plain-text fields instead of i18n keys.
- **Fix:** Run the migration script once:

```bash
# Linux (production)
sudo -u illumio-ops /opt/illumio-ops/python/bin/python3 \
    /opt/illumio-ops/scripts/migrate_rules_to_keys.py \
    --config /opt/illumio-ops/config/config.json --write
```

The script is idempotent; re-running it is safe.

### Humanized timestamps not translating

- **Symptom:** Relative time strings (e.g. "2 hours ago") remain in English after switching to zh_TW.
- **Cause:** The `humanize` library uses `zh_HK` internally for Traditional Chinese; if locale files are missing it silently falls back to English.
- **Fix:** Ensure `humanize` is installed from `requirements.txt` (the offline bundle includes it). If running from source, verify `pip show humanize` shows version ≥ 4.0.

---

## Service won't start (systemd)

### Quick diagnosis

```bash
sudo systemctl status illumio-ops -l
sudo journalctl -u illumio-ops -n 100 --no-pager
```

### Service exits immediately after start

| Symptom in journal | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError: config.json` | Config file missing or wrong `WorkingDirectory` | Confirm `/opt/illumio-ops/config/config.json` exists and is readable by the `illumio-ops` user |
| `PermissionError: logs/` or `data/` | Service user cannot write log/data directories | `sudo chown -R illumio-ops:illumio-ops /opt/illumio-ops/{data,logs,config}` |
| `ModuleNotFoundError` | Wrong Python interpreter; deps not installed | Verify `ExecStart` points to `/opt/illumio-ops/python/bin/python3` and run `verify_deps.py` |
| `json.JSONDecodeError` in config | `config.json` has a syntax error | `python3 -m json.tool /opt/illumio-ops/config/config.json` to validate; fix the error reported |
| `Address already in use` | Another process holds port 5001 (or configured port) | `ss -tlnp | grep 5001`; stop the conflicting process or change `settings.port` in config |

### Validating config before restart

```bash
illumio-ops config validate
```

This checks JSON syntax, required fields, and PCE reachability without starting the full service.

### Service unit reference

The production unit file lives at `/opt/illumio-ops/deploy/illumio-ops.service`. Key fields:

```text
User=illumio-ops
WorkingDirectory=/opt/illumio-ops
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py --monitor-gui --interval 10
```

After editing the unit file: `sudo systemctl daemon-reload && sudo systemctl restart illumio-ops`.

---

## Upgrade aborted by pull conflict

### Symptom

`git pull` during an upgrade (or automated update script) aborts with:

```text
error: Your local changes to the following files would be overwritten by merge:
    deploy/install_service.ps1
    scripts/install.sh
```

### Cause

A tracked file was edited in place on the deployment box (e.g. the install script or an ingestor module). Git refuses to overwrite local edits during a pull.

### Fix — one-time setup per deployment box

Run the provided setup script **once** after the initial clone. It enables `merge.autoStash` and `rebase.autoStash` locally so that `git pull` stashes local edits, fast-forwards, then pops them automatically:

```bash
bash scripts/setup-prod-git.sh
```

Output confirms the settings were applied:

```text
merge.autoStash=true
rebase.autoStash=true
Done. git pull will now stash local edits, fast-forward, and pop.
```

This setting is local to the deployment box; it does not affect the upstream repository or other clones.

### If a pull already failed

```bash
git stash
git pull
git stash pop
```

Review any conflicts in `git stash pop` output before proceeding with the upgrade.

---

## How to file a useful bug report

Include the following in any bug report or support request:

1. **Application version and commit:**

```bash
illumio-ops --version
git -C /opt/illumio-ops rev-parse HEAD
```

2. **Relevant log lines** — include the 20–50 lines surrounding the error:

```bash
grep -n "ERROR\|Exception\|Traceback" /opt/illumio-ops/logs/illumio_ops.log | tail -30
```

3. **Config (redacted):** Copy `config.json` and replace `api.key`, `api.secret`, and any passwords with `***REDACTED***`.

4. **System info:**

```bash
uname -a
python3 --version
systemctl status illumio-ops --no-pager -l | head -20
```

5. **Reproduction steps** — a numbered list of what you did before the error appeared.

6. **Expected vs actual behavior** — one sentence each.

> **Do not include** unredacted API keys, passwords, or customer-identifying data in bug reports.

---

## Related Docs

- [Getting Started](../getting-started.md) — initial setup issues
- [TLS & Certificates](tls-and-certificates.md) — cert error specifics
- [SIEM Integration](siem-integration.md) — destination delivery issues
- [Reports](reports.md) — report generation failures
