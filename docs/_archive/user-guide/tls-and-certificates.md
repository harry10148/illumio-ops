---
title: TLS and Certificates
audience: [operator, security]
last_verified: 2026-05-15
verified_against:
  - src/gui/routes/config.py
  - src/gui/_helpers.py
  - src/static/js/settings.js
  - src/config/ (models)
  - commit 86d550e
  - commit c089e58
  - commit 7baf6de
  - commit d056a51
related_docs:
  - multi-pce.md
  - troubleshooting.md
  - siem-integration.md
  - ../contributing/release-process.md
---

> **[English](tls-and-certificates.md)** | [繁體中文](tls-and-certificates_zh.md)
> 📍 [INDEX](../INDEX.md) › User Guide › TLS & Certificates
> 🔍 Last verified **2026-05-15** against commit `d056a51` — see frontmatter for sources

# TLS and Certificates

This page covers the HTTPS configuration of the **illumio-ops web GUI** (the Flask
server itself) and how illumio-ops verifies the **PCE's TLS certificate** when it
makes API calls.  These are two distinct trust relationships.

---

## Default self-signed cert

When `web_gui.tls.enabled` is `true` and `web_gui.tls.self_signed` is `true` (the
factory default), illumio-ops generates a self-signed certificate on the **first
server start** if none already exists.

| Detail | Value |
|---|---|
| Generated path | `config/tls/self_signed.pem` |
| Key path | `config/tls/self_signed_key.pem` (same directory) |
| Validity | 397 days |
| Algorithm | ECDSA-P256 (RSA-2048 fallback) |

The UI reflects the current state via `GET /api/tls/status`.  If no cert file is
found yet the status panel shows:

> _"No certificate found. It will be generated on next server start."_

**config.json defaults (web_gui.tls block):**

```json
"tls": {
  "enabled": true,
  "self_signed": true,
  "cert_file": "",
  "key_file": "",
  "auto_renew": true,
  "auto_renew_days": 30
}
```

To **disable HTTPS** (e.g. behind a reverse proxy that terminates TLS), set
`"enabled": false`.

---

## Generating a CSR

> Verified against commit `86d550e` — `src/gui/_helpers.py (_generate_csr)`,
> `src/gui/routes/config.py (POST /api/tls/generate-csr)`, `src/static/js/settings.js`.

Use this flow to obtain a CA-signed certificate for production deployments.

### Steps

1. Navigate to **Settings → TLS / HTTPS**.
2. Uncheck **"Use self-signed certificate"** to reveal the custom-cert panel.
3. Expand **"Generate CSR (Certificate Signing Request)"**.
4. Fill in the form fields:

   | Field | Required | Notes |
   |---|---|---|
   | Common Name (CN) | Yes | FQDN browsers will use, e.g. `ops.example.com` |
   | Organization (O) | No | Legal entity name |
   | Organizational Unit (OU) | No | Department / team |
   | Country (C) | No | 2-letter ISO code, e.g. `TW` |
   | SAN DNS | No | Comma-separated additional DNS names |
   | SAN IP | No | Comma-separated IP SANs |
   | Key algorithm | — | RSA-2048 or ECDSA-P256 |

5. Click **"Generate CSR"**.
6. The backend calls `POST /api/tls/generate-csr`, which:
   - Generates a new private key (`RSA-2048` or `ECDSA-P256`).
   - Writes the private key to `config/tls/csr_key.pem` with permissions `0o600`.
   - Returns the CSR PEM in the response body.
7. Copy the CSR PEM and send it to your CA.
8. After clicking "Generate CSR", the **"Import CA-signed Certificate"** panel
   automatically expands (commit `c089e58`), guiding you to the next step.

> **Security note:** `config/tls/csr_key.pem` must never leave the server.
> Only the CSR (not the private key) is sent to the CA.

---

## Importing a signed cert

> Verified against commit `86d550e` — `POST /api/tls/import-cert`,
> `_import_signed_cert()` in `src/gui/_helpers.py`.

After your CA returns the signed certificate:

1. In **Settings → TLS / HTTPS**, expand **"Import CA-signed Certificate"**.
   (This panel opens automatically if you just generated a CSR.)
2. Paste the full certificate PEM (including `-----BEGIN CERTIFICATE-----`).
3. Click **"Import Certificate"**.
4. The backend calls `POST /api/tls/import-cert`, which:
   - Parses the PEM and validates it against the stored `config/tls/csr_key.pem`.
   - On success, writes the cert to the path configured in `cert_file`, and updates
     `config.json` to point `cert_file` / `key_file` at the new files.
5. The UI shows:

   > _"Certificate imported. Restart the server to apply."_

6. Restart illumio-ops to load the new certificate.

**If you have an intermediate/chain cert,** concatenate it after the leaf cert in
the same PEM before pasting.

---

## Cert rotation

Changes to TLS certificates (both self-signed renew and CA-cert import) take effect
only after a **server restart**.  The GUI always shows a banner after any cert change:

> _"TLS settings saved. Restart the server to apply."_

### Self-signed auto-renew

When `web_gui.tls.auto_renew` is `true` (default), illumio-ops checks the self-signed
cert on **every startup**.  If days remaining ≤ `auto_renew_days` (default `30`), the
cert is regenerated automatically before the server begins accepting requests.

### Manual renew

From **Settings → TLS / HTTPS**, click **"Renew Certificate"**.  A confirmation
dialog warns that a restart is required.  Only available for self-signed certs
(renewing a CA-issued cert requires re-running the CSR flow).

### CA-issued cert rotation

1. Generate a new CSR (or provide the new cert directly if using the same key).
2. Import the new signed PEM via the import panel.
3. Restart the server.

No in-process reload is performed — a full process restart is required for all cert
changes.

---

## Days remaining display

> Verified against commit `7baf6de` — `humanizeDays()` in `src/static/js/settings.js`,
> i18n keys `gui_tls_days_*` in `src/i18n_en.json` and `src/i18n_zh_TW.json`.

The **Settings → TLS / HTTPS** status panel shows the certificate expiry as a
humanized string rather than a raw day count.

**Format rules (English):**

| Range | Format |
|---|---|
| ≥ 1 year | `N days (about Yy Mm)` |
| < 1 year | `N days (about M months)` |

**Examples:**

```
1804 days (about 4y 11m)
 365 days (about 12 months)
  45 days (about 1 months)
```

The helper `humanizeDays(n)` in `settings.js` produces the label via i18n keys:

| Key | English value |
|---|---|
| `gui_tls_days_humanized` | `{n} days (about {label})` |
| `gui_tls_days_label_years` | `{y}y {m}m` |
| `gui_tls_days_label_months` | `{m} months` |

For zh_TW the same keys produce `N 天（約 Y 年 M 個月）`.

The raw days value is still available for API consumers via
`GET /api/tls/status` → `days_remaining`.

---

## PCE-side TLS verification

This section covers how illumio-ops **verifies the PCE's certificate** when making
Illumio API calls — separate from the GUI's own TLS cert.

### Per-profile `verify_ssl`

Each PCE profile in `config.json` has a `verify_ssl` boolean:

```json
{
  "pce_profiles": [
    {
      "name": "Production PCE",
      "url": "https://pce.example.com:8443",
      "verify_ssl": true
    }
  ]
}
```

| Value | Behaviour |
|---|---|
| `true` (default) | Full certificate chain validation against the system CA bundle |
| `false` | Skip verification (development / lab PCEs with self-signed certs) |

> **Warning:** Setting `verify_ssl: false` in production exposes API traffic to
> MITM attacks.  Use a proper CA bundle instead.

### Custom CA bundle

> [!NOTE] **Audited 2026-05-15**: PCE profiles have **no** custom-CA-bundle field today.
> `tls_ca_bundle` exists in `src/config_models.py:224` but is **SIEM-only** (used by
> `src/siem/transports/syslog_tls.py` for syslog-TLS destinations). For PCE-side TLS, the
> only available controls are `verify_ssl: true|false` plus the system trust store.
> If you need a custom CA for a private PCE, install it into the system trust store on the
> illumio-ops host (e.g. `/etc/pki/ca-trust/source/anchors/` on RHEL).

### Lab / self-signed PCE

For lab PCEs using a self-signed certificate, the recommended approach is:

```json
"verify_ssl": false
```

Set this in `config.json` after copying the example config.  Without it, the first
connection attempt fails with an SSL verification error.

---

## Troubleshooting cert errors

### Browser shows "NET::ERR_CERT_AUTHORITY_INVALID"

The web GUI is using the default self-signed cert.  This is expected for new installs.
Options:
- Accept the browser security exception (development only).
- Import a CA-signed cert via the CSR workflow above.
- Deploy behind a TLS-terminating reverse proxy.

### "Certificate imported. Restart the server to apply." — but still shows old cert

The server has not been restarted.  New certs are only loaded on startup.  Restart
the process and hard-refresh the browser.

### Import fails with "key mismatch" error

The PEM you pasted does not match the private key generated during CSR creation
(`config/tls/csr_key.pem`).  This happens if:
- A new CSR was generated between the CA signing and the import.
- The cert was signed against a different key.

Re-generate the CSR, re-submit to the CA, and import the new cert.

### Status shows "EXPIRED" or "EXPIRING SOON"

- **Self-signed:** Click **"Renew Certificate"** and restart the server.  With
  `auto_renew: true`, renewal happens automatically on the next startup if days
  remaining ≤ `auto_renew_days`.
- **CA-issued:** Run the CSR flow to get a new cert from your CA, then import it.

### `ssl.SSLError: certificate verify failed` in illumio-ops logs

illumio-ops cannot verify the PCE's TLS certificate.  Set `verify_ssl: false` for
the affected PCE profile, or add the PCE's CA cert to the system trust store.

### `gui_tls_no_cert` message persists after first start

The `config/tls/` directory may not be writable.  Check permissions:

```bash
ls -la config/tls/
# Expected: directory owned by the user running illumio-ops, mode 0755+
```

---

## Related Docs

- [Multi-PCE](multi-pce.md) — per-PCE TLS settings
- [Troubleshooting](troubleshooting.md) — cert error diagnostics
- [SIEM Integration](siem-integration.md) — syslog-TLS deployments
- [Release Process](../contributing/release-process.md) — TLS during upgrade
