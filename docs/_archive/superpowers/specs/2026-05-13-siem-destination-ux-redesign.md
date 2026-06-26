# SIEM Destination UI/UX Redesign — Design Spec

**Date:** 2026-05-13
**Status:** Approved

---

## Problem

1. The SIEM destination modal uses raw field names as labels (`source_types:`, `batch_size (1-10000):`, `endpoint:`), making it feel developer-facing and confusing for operators.
2. The `endpoint` field stores `"host:port"` as a single string. Users have no way to know a port can be specified, and there is no default port shown per transport type.

---

## Goals

- Split `endpoint` into separate `host` and `port` fields (backend + frontend).
- Redesign the destination modal with proper labels, grouping, and smart defaults.
- Maintain full backwards compatibility: existing `endpoint: "host:port"` configs auto-migrate on load.

---

## Backend Changes (`config_models.py`)

### `SiemDestinationSettings`

Remove `endpoint: str` field. Add:

```python
host: str = ""
port: int = 514
```

Add a `@model_validator(mode='before')` that triggers when `endpoint` is present but `host` is empty:

- Syslog (`udp`/`tcp`/`tls`): parse `"host:port"` via `rpartition(":")`.
- HEC: parse URL (`https://host:port/...`) to extract host and port (default 8088).
- After migration, `endpoint` is ignored.

Port defaults by transport (applied in UI only; model stores whatever the user sets):

| Transport | Default Port |
|-----------|-------------|
| UDP       | 514         |
| TCP       | 514         |
| TLS       | 6514        |
| HEC       | 8088        |

---

## Backend Changes (`dispatcher.py`)

`_transport_for()` uses `dest_cfg.host` and `dest_cfg.port` directly — no string parsing.

HEC URL is constructed as:
```
https://{dest_cfg.host}:{dest_cfg.port}/services/collector
```

---

## Frontend Changes (`integrations.js`)

### `buildDestModal()` — full rewrite

New section structure:

1. **基本設定 / Basic**
   - 名稱 (name) — readonly when editing
   - [✓] 啟用 (enabled)
   - 轉發內容 (source_types): `[✓] Audit Events  [✓] Traffic Flows`

2. **傳輸設定 / Transport**
   - 傳輸協定 (transport): `[UDP ▼]` — onchange triggers port auto-fill + section visibility
   - 格式 (format): `[CEF ▼]`
   - 伺服器位址 (host): text input
   - Port: number input — auto-filled with transport default, user-overridable

3. **TLS 設定 / TLS** — visible when transport = `tls` or `hec`
   - [✓] 驗證 TLS 憑證 (tls_verify)
   - CA Bundle 路徑 (tls_ca_bundle): text input

4. **HEC 設定 / HEC** — visible when transport = `hec`
   - HEC Token: password input

5. **進階設定 / Advanced** — `<details>` collapsed by default
   - 批次大小 (batch_size): number 1–10000
   - 最大重試次數 (max_retries): number ≥ 0

### `siemToggleCondFields()`

Update to also auto-fill default port when transport changes, only if port hasn't been manually edited.

### `siemSaveDest()`

Send `host` and `port` instead of `endpoint`.

---

## i18n Keys

New keys in `i18n_en.json` / `i18n_zh_TW.json`:

| Key | EN | ZH |
|-----|----|----|
| `gui_siem_host` | Server Address | 伺服器位址 |
| `gui_siem_port` | Port | Port |
| `gui_siem_source_types` | Forwarding Content | 轉發內容 |
| `gui_siem_sec_basic` | Basic | 基本設定 |
| `gui_siem_sec_advanced` | Advanced | 進階設定 |
| `gui_siem_batch_size` | Batch Size | 批次大小 |
| `gui_siem_max_retries` | Max Retries | 最大重試次數 |
| `gui_siem_tls_verify` | Verify TLS Certificate | 驗證 TLS 憑證 |
| `gui_siem_ca_bundle` | CA Bundle Path | CA Bundle 路徑 |
| `gui_siem_hec_token` | HEC Token | HEC Token |
| `gui_siem_format` | Format | 格式 |
| `gui_siem_transport` | Transport | 傳輸協定 |
| `gui_siem_name` | Name | 名稱 |

---

## Backwards Compatibility

- Old config with `endpoint: "192.168.1.10:514"` → auto-parsed to `host: "192.168.1.10"`, `port: 514`.
- Old config with `endpoint: "192.168.1.10"` (no port) → `host: "192.168.1.10"`, `port: 514`.
- HEC `endpoint: "https://splunk:8088/services/collector"` → `host: "splunk"`, `port: 8088`.
- No manual migration needed; handled by `model_validator`.

---

## Out of Scope

- Traffic event port filtering (filtering which flows to forward based on dst_port) — separate feature.
- Adding new transport types.
