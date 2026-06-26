# SIEM Destination UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `endpoint` into `host`+`port` in the backend model and rewrite the destination modal with proper labels, sections, and smart port defaults.

**Architecture:** Three sequential layers — (1) model + migration validator, (2) dispatcher simplification, (3) frontend modal rewrite with i18n. Each layer is independently testable before the next is started.

**Tech Stack:** Python/Pydantic v2, Flask, vanilla JS (no framework), pytest

---

## File Map

| File | Change |
|------|--------|
| `src/config_models.py` | Remove `endpoint`, add `host`/`port`, add `model_validator` for migration |
| `src/siem/dispatcher.py` | Update `_transport_for()` to use `host`/`port` directly |
| `src/static/js/integrations.js` | Rewrite `buildDestModal()`, `siemToggleCondFields()`, `siemSaveDest()` |
| `src/i18n_en.json` | Add new i18n keys |
| `src/i18n_zh_TW.json` | Add new i18n keys (zh_TW) |
| `tests/test_siem_config_migration.py` | New — model validator migration tests |
| `tests/test_siem_dispatcher.py` | Update `_transport_for` tests to use `host`/`port` |

---

## Task 1: Model — add `host`/`port`, migration validator

**Files:**
- Modify: `src/config_models.py:215-228`
- Create: `tests/test_siem_config_migration.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_siem_config_migration.py`:

```python
"""Tests for SiemDestinationSettings host/port migration from legacy endpoint field."""
import pytest


def _make(raw: dict):
    from src.config_models import SiemDestinationSettings
    return SiemDestinationSettings.model_validate(raw)


def test_new_config_host_port():
    d = _make({"name": "s", "transport": "udp", "host": "10.0.0.1", "port": 514})
    assert d.host == "10.0.0.1"
    assert d.port == 514


def test_migrate_endpoint_host_port():
    d = _make({"name": "s", "transport": "udp", "endpoint": "10.0.0.1:514"})
    assert d.host == "10.0.0.1"
    assert d.port == 514


def test_migrate_endpoint_host_only():
    d = _make({"name": "s", "transport": "udp", "endpoint": "10.0.0.1"})
    assert d.host == "10.0.0.1"
    assert d.port == 514


def test_migrate_endpoint_hec_url():
    d = _make({"name": "h", "transport": "hec", "endpoint": "https://splunk.corp:8088/services/collector"})
    assert d.host == "splunk.corp"
    assert d.port == 8088


def test_migrate_endpoint_hec_url_no_port():
    d = _make({"name": "h", "transport": "hec", "endpoint": "https://splunk.corp/services/collector"})
    assert d.host == "splunk.corp"
    assert d.port == 8088


def test_port_default_is_514():
    d = _make({"name": "s", "transport": "udp", "host": "10.0.0.1"})
    assert d.port == 514


def test_host_new_wins_over_endpoint():
    # If both present, host/port take precedence over endpoint
    d = _make({"name": "s", "transport": "udp", "host": "10.0.0.2", "port": 999, "endpoint": "10.0.0.1:514"})
    assert d.host == "10.0.0.2"
    assert d.port == 999
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_siem_config_migration.py -v
```

Expected: all 8 tests FAIL (no `host`/`port` fields yet)

- [ ] **Step 3: Update `SiemDestinationSettings` in `src/config_models.py`**

First, add `model_validator` to the pydantic import line (currently line 17):

```python
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
```

Then replace the `SiemDestinationSettings` class (lines 215–228):

```python
class SiemDestinationSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    transport: str = "udp"  # udp|tcp|tls|hec
    format: str = "cef"    # cef|json|syslog_cef|syslog_json
    host: str = ""
    port: int = Field(default=514, ge=1, le=65535)
    tls_verify: bool = True
    tls_ca_bundle: Optional[str] = None
    hec_token: Optional[str] = None
    batch_size: int = Field(default=100, ge=1, le=10000)
    source_types: list[str] = Field(default_factory=lambda: ["audit", "traffic"])
    max_retries: int = Field(default=10, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _migrate_endpoint(cls, values: dict) -> dict:
        """Migrate legacy endpoint: "host:port" or HEC URL → host + port."""
        if not isinstance(values, dict):
            return values
        endpoint = values.get("endpoint", "")
        if not endpoint or values.get("host"):
            return values
        transport = values.get("transport", "udp")
        if transport == "hec":
            from urllib.parse import urlparse
            parsed = urlparse(endpoint)
            values["host"] = parsed.hostname or endpoint
            values["port"] = parsed.port or 8088
        else:
            host, _, port_str = endpoint.rpartition(":")
            if host and port_str.isdigit():
                values["host"] = host
                values["port"] = int(port_str)
            else:
                values["host"] = endpoint
        return values
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_siem_config_migration.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Run full config test suite to check no regressions**

```bash
python -m pytest tests/test_config_models.py tests/test_config_load_validation.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/config_models.py tests/test_siem_config_migration.py
git commit -m "feat(siem): replace endpoint with host+port fields, auto-migrate legacy config"
```

---

## Task 2: Dispatcher — use `host`/`port` directly

**Files:**
- Modify: `src/siem/dispatcher.py:154-173`
- Modify: `tests/test_siem_dispatcher.py` (update any dest_cfg fixtures that use `endpoint`)

- [ ] **Step 1: Check existing dispatcher tests for `endpoint` usage**

```bash
grep -n "endpoint" /home/harry/rd/illumio-ops/tests/test_siem_dispatcher.py
```

Note which lines use `endpoint=` so you can update them in Step 4.

- [ ] **Step 2: Write a new failing test in `tests/test_siem_dispatcher.py`**

Add at the end of the file:

```python
def test_transport_for_udp_uses_host_port():
    from src.siem.dispatcher import _transport_for
    from src.config_models import SiemDestinationSettings
    cfg = SiemDestinationSettings(name="t", transport="udp", host="10.0.0.5", port=1514)
    t = _transport_for(cfg)
    from src.siem.transports.syslog_udp import SyslogUDPTransport
    assert isinstance(t, SyslogUDPTransport)
    assert t._host == "10.0.0.5"
    assert t._port == 1514


def test_transport_for_hec_constructs_url():
    from src.siem.dispatcher import _transport_for
    from src.config_models import SiemDestinationSettings
    cfg = SiemDestinationSettings(name="h", transport="hec", host="splunk.corp", port=8088, hec_token="tok")
    t = _transport_for(cfg)
    from src.siem.transports.splunk_hec import SplunkHECTransport
    assert isinstance(t, SplunkHECTransport)
```

- [ ] **Step 3: Run new tests to verify they fail**

```bash
python -m pytest tests/test_siem_dispatcher.py::test_transport_for_udp_uses_host_port tests/test_siem_dispatcher.py::test_transport_for_hec_constructs_url -v
```

Expected: FAIL (old `_transport_for` uses `endpoint`, not `host`/`port`)

- [ ] **Step 4: Update `_transport_for()` in `src/siem/dispatcher.py`**

Replace lines 154–173:

```python
def _transport_for(dest_cfg):
    """Build transport from SiemDestinationSettings."""
    transport_type = dest_cfg.transport.lower()
    host = dest_cfg.host
    port = dest_cfg.port
    if transport_type == "udp":
        from src.siem.transports.syslog_udp import SyslogUDPTransport
        return SyslogUDPTransport(host, port)
    elif transport_type == "tcp":
        from src.siem.transports.syslog_tcp import SyslogTCPTransport
        return SyslogTCPTransport(host, port)
    elif transport_type == "tls":
        from src.siem.transports.syslog_tls import SyslogTLSTransport
        return SyslogTLSTransport(host, port, tls_verify=dest_cfg.tls_verify)
    elif transport_type == "hec":
        from src.siem.transports.splunk_hec import SplunkHECTransport
        url = f"https://{host}:{port}/services/collector"
        return SplunkHECTransport(url, token=dest_cfg.hec_token or "")
    raise ValueError(f"Unknown transport: {transport_type}")
```

- [ ] **Step 5: Fix any existing test fixtures using `endpoint=`**

For each line found in Step 1, change:
```python
# old
SiemDestinationSettings(name="x", transport="udp", endpoint="10.0.0.1:514")
# new
SiemDestinationSettings(name="x", transport="udp", host="10.0.0.1", port=514)
```

- [ ] **Step 6: Run full SIEM test suite**

```bash
python -m pytest tests/test_siem_dispatcher.py tests/test_siem_config_migration.py tests/test_siem_forwarder_api.py tests/test_siem_web.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/siem/dispatcher.py tests/test_siem_dispatcher.py
git commit -m "feat(siem): simplify _transport_for to use host/port fields directly"
```

---

## Task 3: i18n — add new keys

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

- [ ] **Step 1: Add keys to `src/i18n_en.json`**

Find the `"gui_siem_sec_basic"` line (currently `"Basic"`) and replace the block of `gui_siem_sec_*` keys with the expanded set. Insert after `"gui_siem_sec_basic": "Basic",`:

```json
  "gui_siem_sec_advanced": "Advanced",
  "gui_siem_host": "Server Address",
  "gui_siem_port": "Port",
  "gui_siem_source_types": "Forwarding Content",
  "gui_siem_format": "Format",
  "gui_siem_transport": "Transport",
  "gui_siem_name": "Name",
  "gui_siem_batch_size": "Batch Size",
  "gui_siem_max_retries": "Max Retries",
  "gui_siem_tls_verify": "Verify TLS Certificate",
  "gui_siem_ca_bundle": "CA Bundle Path",
  "gui_siem_hec_token": "HEC Token",
  "gui_siem_th_host": "Host",
  "gui_siem_th_port": "Port",
```

Also update `"gui_siem_th_endpoint": "Endpoint"` → `"gui_siem_th_endpoint": "Host"` (table column header)

- [ ] **Step 2: Add keys to `src/i18n_zh_TW.json`**

Same location (after `"gui_siem_sec_basic"`):

```json
  "gui_siem_sec_advanced": "進階設定",
  "gui_siem_host": "伺服器位址",
  "gui_siem_port": "Port",
  "gui_siem_source_types": "轉發內容",
  "gui_siem_format": "格式",
  "gui_siem_transport": "傳輸協定",
  "gui_siem_name": "名稱",
  "gui_siem_batch_size": "批次大小",
  "gui_siem_max_retries": "最大重試次數",
  "gui_siem_tls_verify": "驗證 TLS 憑證",
  "gui_siem_ca_bundle": "CA Bundle 路徑",
  "gui_siem_hec_token": "HEC Token",
  "gui_siem_th_host": "主機",
  "gui_siem_th_port": "Port",
```

Also update `"gui_siem_th_endpoint": "端點"` → `"gui_siem_th_endpoint": "主機"`

- [ ] **Step 3: Validate JSON syntax**

```bash
python3 -c "import json; json.load(open('src/i18n_en.json')); print('EN OK')"
python3 -c "import json; json.load(open('src/i18n_zh_TW.json')); print('ZH OK')"
```

Expected: `EN OK` and `ZH OK`

- [ ] **Step 4: Commit**

```bash
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(siem): add i18n keys for host/port fields and improved modal labels"
```

---

## Task 4: Frontend modal rewrite

**Files:**
- Modify: `src/static/js/integrations.js` — `buildDestModal()`, `siemToggleCondFields()`, `siemSaveDest()`

- [ ] **Step 1: Replace `buildDestModal()` (lines ~651–707)**

The default port lookup table and the function:

```javascript
var _SIEM_DEFAULT_PORTS = { udp: 514, tcp: 514, tls: 6514, hec: 8088 };

function buildDestModal(dest, editName) {
  var nameVal = escapeAttr(dest.name);
  var host = escapeAttr(dest.host || '');
  var port = Number(dest.port) || 514;
  var caBundle = escapeAttr(dest.tls_ca_bundle || '');
  var hecToken = escapeAttr(dest.hec_token || '');
  var readonly = editName ? ' readonly' : '';
  var editAttr = editName ? encodeURIComponent(editName).replace(/'/g, '%27') : '';
  var titleKey = editName ? 'gui_siem_modal_title_edit' : 'gui_siem_modal_title_add';
  var titleText = editName ? 'Edit' : 'Add';
  var sourceTypes = dest.source_types || [];

  function mkOpts(list, cur) {
    return list.map(function(v) {
      return '<option' + (v === cur ? ' selected' : '') + '>' + escapeAttr(v) + '</option>';
    }).join('');
  }

  return '<div class="modal-backdrop" onclick="siemCloseModal(event)">'
    + '<div class="modal" onclick="event.stopPropagation()">'
    + '<h2 data-i18n="' + titleKey + '">' + titleText + ' destination</h2>'

    + '<h3 data-i18n="gui_siem_sec_basic">Basic</h3>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_name">Name</label>'
    + '<input id="md-name" value="' + nameVal + '"' + readonly + '></div>'
    + '<div class="form-group" style="flex:0 0 auto;align-self:flex-end;padding-bottom:4px">'
    + '<label><input type="checkbox" id="md-enabled"' + (dest.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_enabled">Enabled</span></label></div>'
    + '</div>'
    + '<div class="form-group"><label data-i18n="gui_siem_source_types">Forwarding Content</label>'
    + '<div style="display:flex;gap:16px;margin-top:4px">'
    + '<label><input type="checkbox" name="md-st" value="audit"' + (sourceTypes.indexOf('audit') >= 0 ? ' checked' : '') + '> Audit Events</label>'
    + '<label><input type="checkbox" name="md-st" value="traffic"' + (sourceTypes.indexOf('traffic') >= 0 ? ' checked' : '') + '> Traffic Flows</label>'
    + '</div></div>'

    + '<h3 data-i18n="gui_siem_sec_transport">Transport</h3>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_transport">Transport</label>'
    + '<select id="md-transport" onchange="siemToggleCondFields()">' + mkOpts(['udp', 'tcp', 'tls', 'hec'], dest.transport) + '</select></div>'
    + '<div class="form-group"><label data-i18n="gui_siem_format">Format</label>'
    + '<select id="md-format">' + mkOpts(['cef', 'json', 'syslog_cef', 'syslog_json'], dest.format) + '</select></div>'
    + '</div>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_host">Server Address</label>'
    + '<input id="md-host" value="' + host + '" placeholder="192.168.1.10"></div>'
    + '<div class="form-group" style="flex:0 0 100px"><label data-i18n="gui_siem_port">Port</label>'
    + '<input type="number" id="md-port" min="1" max="65535" value="' + port + '"></div>'
    + '</div>'

    + '<div id="md-tls-section">'
    + '<h3 data-i18n="gui_siem_sec_tls">TLS</h3>'
    + '<label><input type="checkbox" id="md-tls-verify"' + (dest.tls_verify ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_tls_verify">Verify TLS Certificate</span></label>'
    + '<div class="form-group" style="margin-top:8px"><label data-i18n="gui_siem_ca_bundle">CA Bundle Path</label>'
    + '<input id="md-tls-ca" value="' + caBundle + '" placeholder="/etc/ssl/certs/ca-bundle.crt"></div>'
    + '</div>'

    + '<div id="md-hec-section">'
    + '<h3 data-i18n="gui_siem_sec_hec">HEC</h3>'
    + '<div class="form-group"><label data-i18n="gui_siem_hec_token">HEC Token</label>'
    + '<input type="password" id="md-hec-token" value="' + hecToken + '"></div>'
    + '</div>'

    + '<details style="margin-top:14px">'
    + '<summary style="cursor:pointer;font-weight:600;padding:4px 0" data-i18n="gui_siem_sec_advanced">Advanced</summary>'
    + '<div style="margin-top:10px">'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_batch_size">Batch Size</label>'
    + '<input type="number" id="md-batch" min="1" max="10000" value="' + Number(dest.batch_size) + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_siem_max_retries">Max Retries</label>'
    + '<input type="number" id="md-retries" min="0" value="' + Number(dest.max_retries) + '"></div>'
    + '</div></div>'
    + '</details>'

    + '<div id="md-banner" style="margin-top:10px;color:var(--danger);"></div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">'
    + '<button class="btn" onclick="siemCloseModal(event)" data-i18n="gui_cancel">Cancel</button>'
    + '<button class="btn" onclick="siemTestDestInline()" data-i18n="gui_siem_test_inline">Test Connection</button>'
    + '<button class="btn btn-primary" onclick="siemSaveDest(\'' + editAttr + '\')" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</div>'
    + '</div>';
}
```

- [ ] **Step 2: Replace `siemToggleCondFields()` (lines ~709–717)**

```javascript
function siemToggleCondFields() {
  var transport = document.getElementById('md-transport');
  if (!transport) return;
  var t = transport.value;
  var tlsEl = document.getElementById('md-tls-section');
  var hecEl = document.getElementById('md-hec-section');
  if (tlsEl) tlsEl.style.display = (t === 'tls' || t === 'hec') ? '' : 'none';
  if (hecEl) hecEl.style.display = (t === 'hec') ? '' : 'none';
  // Auto-fill default port only if port field is still at a known default value
  var portEl = document.getElementById('md-port');
  if (portEl) {
    var cur = Number(portEl.value);
    var defaults = Object.values(_SIEM_DEFAULT_PORTS);
    if (defaults.indexOf(cur) >= 0 || cur === 514) {
      portEl.value = _SIEM_DEFAULT_PORTS[t] || 514;
    }
  }
}
```

- [ ] **Step 3: Replace `siemSaveDest()` payload (lines ~728–739)**

Find the `var payload = {` block inside `siemSaveDest` and replace it:

```javascript
  var payload = {
    name: editName || document.getElementById('md-name').value.trim(),
    enabled: document.getElementById('md-enabled').checked,
    transport: document.getElementById('md-transport').value,
    format: document.getElementById('md-format').value,
    host: document.getElementById('md-host').value.trim(),
    port: Number(document.getElementById('md-port').value),
    tls_verify: document.getElementById('md-tls-verify').checked,
    tls_ca_bundle: document.getElementById('md-tls-ca').value.trim() || null,
    hec_token: document.getElementById('md-hec-token').value || null,
    batch_size: Number(document.getElementById('md-batch').value),
    max_retries: Number(document.getElementById('md-retries').value),
    source_types: sourceTypes.length ? sourceTypes : ['audit', 'traffic'],
  };
```

- [ ] **Step 4: Update the default dest object in `siemOpenDestModal()` (line ~630)**

```javascript
  var dest = {
    name: '', enabled: true, transport: 'udp', format: 'cef',
    host: '', port: 514, tls_verify: true, tls_ca_bundle: '', hec_token: '',
    batch_size: 100, source_types: ['audit', 'traffic'], max_retries: 10
  };
```

- [ ] **Step 5: Update the destinations table column header (line ~571)**

Change `<th data-i18n="gui_siem_th_endpoint">Endpoint</th>` to:

```javascript
    + '<th data-i18n="gui_siem_th_host">Host</th>'
    + '<th data-i18n="gui_siem_th_port">Port</th>'
```

- [ ] **Step 6: Update the table row rendering to show host + port**

Find where destinations are rendered into `tbody` (look for `escapeAttr(d.endpoint || '')`). Replace that cell with two cells:

```javascript
    + '<td>' + escapeAttr(d.host || '') + '</td>'
    + '<td>' + (d.port || 514) + '</td>'
```

- [ ] **Step 7: Syntax check**

```bash
node --check src/static/js/integrations.js && echo "JS OK"
```

Expected: `JS OK`

- [ ] **Step 8: Commit**

```bash
git add src/static/js/integrations.js
git commit -m "feat(siem): rewrite destination modal with host/port fields and improved UX"
```

---

## Task 5: Deploy and verify on test machine

**Files:** none (deploy only)

- [ ] **Step 1: Run full SIEM test suite one last time**

```bash
python -m pytest tests/test_siem_config_migration.py tests/test_siem_dispatcher.py tests/test_siem_forwarder_api.py tests/test_siem_web.py -v
```

Expected: all PASS

- [ ] **Step 2: Deploy to test machine**

```bash
scp src/config_models.py root@172.16.15.106:/root/illumio-ops/src/config_models.py
scp src/siem/dispatcher.py root@172.16.15.106:/root/illumio-ops/src/siem/dispatcher.py
scp src/static/js/integrations.js root@172.16.15.106:/root/illumio-ops/src/static/js/integrations.js
scp src/i18n_en.json root@172.16.15.106:/root/illumio-ops/src/i18n_en.json
scp src/i18n_zh_TW.json root@172.16.15.106:/root/illumio-ops/src/i18n_zh_TW.json
```

- [ ] **Step 3: Restart service**

```bash
ssh root@172.16.15.106 "systemctl restart illumio-ops && sleep 2 && systemctl is-active illumio-ops"
```

Expected: `active`

- [ ] **Step 4: Verify in browser**

Navigate to `https://172.16.15.106:5001` → Integrations → SIEM tab → click **+ Add**.

Verify:
- Modal shows "Server Address" and "Port" fields (not "endpoint")
- Changing transport auto-updates Port default (UDP→514, TLS→6514, HEC→8088)
- TLS section only visible for TLS/HEC
- HEC section only visible for HEC
- "Advanced" section is collapsed by default
- Saving a new destination succeeds
