# Integrations UI (Cache + SIEM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new top-level `Integrations` GUI tab (4 sub-tabs: Overview / Cache / SIEM / DLQ), mirrored CLI interactive menus, and the backend endpoints required to fully manage `pce_cache.*` and `siem.*` settings from the UI — closing the Phase 13 gap where the backend was complete but frontend/CLI were missing.

**Architecture:** New per-module settings endpoints (`/api/cache/settings`, `/api/siem/forwarder`, `/api/siem/destinations/<name>/test`, `/api/siem/dlq/export`, `/api/daemon/restart`) layered onto existing `siem.web` and `pce_cache.web` Flask blueprints. A reusable `save_section()` helper validates via pydantic and atomic-writes to `config.json`. Any save that could affect scheduling returns `requires_restart: true`; the GUI shows a banner with a `[Restart Monitor]` button that works when `_GUI_OWNS_DAEMON=True`.

**Tech Stack:** Python 3.11 · Flask · Flask-Login · Pydantic v2 · SQLAlchemy · APScheduler · Click (CLI) · Vanilla JS + existing project CSS · pytest.

**Spec:** `docs/superpowers/specs/2026-04-25-integrations-ui-cache-siem-design.md`

**Baseline:** 582 passed + 1 skipped. Target after this plan: ~607 passed + 1 skipped.

---

## Security Note for Frontend Tasks

**All dynamic/user-derived content injected into the DOM MUST be escaped.** Use the `escapeAttr()` helper introduced in Task 14 for attribute and text content when using template literals. Static markup literals (no interpolation of runtime data) may use template-literal assignment. For any user-submitted strings (destination names, endpoints, DLQ payload fields, error messages from API), route through `escapeAttr()` before interpolating. This plan follows that convention in every frontend task.

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `src/gui/__init__.py` | Package marker (empty). |
| `src/gui/settings_helpers.py` | `save_section(cm, key, data, model)` — validate, merge, atomic-write. |
| `src/siem/tester.py` | `send_test_event(dest_cfg) -> TestResult` shared by CLI + HTTP. |
| `src/pce_cache_cli.py` | Interactive menu `manage_pce_cache_menu(cm)`. |
| `src/siem_cli.py` | Interactive menu `manage_siem_menu(cm)` (with DLQ submenu). |
| `src/static/js/integrations.js` | Frontend logic for all 4 Integrations sub-panes. |
| `tests/test_settings_helpers.py`, `tests/test_siem_tester.py`, `tests/test_cache_web.py`, `tests/test_siem_forwarder_api.py`, `tests/test_siem_test_endpoint.py`, `tests/test_siem_dlq_export.py`, `tests/test_daemon_restart_api.py`, `tests/test_pce_cache_menu.py`, `tests/test_siem_menu.py`, `tests/test_config_validators.py`, `tests/test_integrations_e2e.py` | New test files. |

### Modified files

| Path | Change |
|------|--------|
| `src/config_models.py` | `@field_validator` for `TrafficFilterSettings.exclude_src_ips` (IP format) and `.ports` (1–65535). |
| `src/cli/siem.py:21-55` | Refactor `siem_test` to call `send_test_event()`. |
| `src/siem/web.py` | Add `/forwarder` (GET/PUT), `/destinations/<name>/test` (POST), `/dlq/export` (GET). |
| `src/pce_cache/web.py` | Add `/settings` (GET/PUT). |
| `src/gui.py` | Module-level `_GUI_OWNS_DAEMON` / `_DAEMON_SCHEDULER` / `_DAEMON_RESTART_FN`; `/api/daemon/restart` route. |
| `src/main.py` | Menu entries for Cache / SIEM; wire restart hook in `run_daemon_with_gui`. |
| `src/templates/index.html` | `Integrations` tab button before Settings; `#p-integrations` panel with 4 sub-panes. |
| `src/static/js/*.js` (tab switcher) | Register `integrations` in `switchTab()` dispatch. |
| `src/i18n_en.json`, `src/i18n_zh_TW.json` | +~60 keys (introduced task-by-task). |
| `src/__init__.py` | Bump `__version__`. |

---

## Task 1: IP validator on `TrafficFilterSettings.exclude_src_ips`

**Files:**
- Modify: `src/config_models.py` (class `TrafficFilterSettings`, line ~154)
- Create: `tests/test_config_validators.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_validators.py`:

```python
import pytest
from pydantic import ValidationError
from src.config_models import TrafficFilterSettings


def test_exclude_src_ips_accepts_ipv4():
    cfg = TrafficFilterSettings(exclude_src_ips=["10.0.0.1", "192.168.1.5"])
    assert cfg.exclude_src_ips == ["10.0.0.1", "192.168.1.5"]


def test_exclude_src_ips_accepts_ipv6():
    cfg = TrafficFilterSettings(exclude_src_ips=["::1", "2001:db8::1"])
    assert cfg.exclude_src_ips == ["::1", "2001:db8::1"]


def test_exclude_src_ips_rejects_garbage():
    with pytest.raises(ValidationError) as excinfo:
        TrafficFilterSettings(exclude_src_ips=["not-an-ip"])
    assert "exclude_src_ips" in str(excinfo.value)


def test_exclude_src_ips_rejects_partial_ip():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(exclude_src_ips=["10.0.0"])


def test_exclude_src_ips_empty_list_ok():
    cfg = TrafficFilterSettings(exclude_src_ips=[])
    assert cfg.exclude_src_ips == []
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python3 -m pytest tests/test_config_validators.py -v`
Expected: FAIL for `test_exclude_src_ips_rejects_garbage` (validator not yet present).

- [ ] **Step 3: Implement the validator**

In `src/config_models.py`, add `import ipaddress` at top if absent, then in `class TrafficFilterSettings`:

```python
    @field_validator("exclude_src_ips")
    @classmethod
    def _validate_ips(cls, v: list[str]) -> list[str]:
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError as e:
                raise ValueError(f"exclude_src_ips: {ip!r} is not a valid IP address") from e
        return v
```

- [ ] **Step 4: Run tests — PASS**

Run: `python3 -m pytest tests/test_config_validators.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config_models.py tests/test_config_validators.py
git commit -m "feat(config): validate exclude_src_ips as IPv4/IPv6"
```

---

## Task 2: Port range validator on `TrafficFilterSettings.ports`

**Files:**
- Modify: `src/config_models.py`
- Extend: `tests/test_config_validators.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config_validators.py`:

```python
def test_ports_accepts_valid_range():
    cfg = TrafficFilterSettings(ports=[22, 443, 65535, 1])
    assert cfg.ports == [22, 443, 65535, 1]


def test_ports_rejects_zero():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(ports=[0, 80])


def test_ports_rejects_too_high():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(ports=[65536])


def test_ports_rejects_negative():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(ports=[-1])
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_config_validators.py::test_ports_rejects_zero -v`

- [ ] **Step 3: Implement validator**

Append to `class TrafficFilterSettings`:

```python
    @field_validator("ports")
    @classmethod
    def _validate_ports(cls, v: list[int]) -> list[int]:
        for p in v:
            if not (1 <= p <= 65535):
                raise ValueError(f"ports: {p} is out of range (1-65535)")
        return v
```

- [ ] **Step 4: Run — PASS (9 total)**

Run: `python3 -m pytest tests/test_config_validators.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/config_models.py tests/test_config_validators.py
git commit -m "feat(config): validate traffic_filter.ports as 1-65535"
```

---

## Task 3: `save_section()` helper

**Files:**
- Create: `src/gui/__init__.py`, `src/gui/settings_helpers.py`
- Create: `tests/test_settings_helpers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_helpers.py`:

```python
import json
import os
import pytest
from pydantic import BaseModel, Field
from src.config import ConfigManager
from src.gui.settings_helpers import save_section


class _DemoModel(BaseModel):
    enabled: bool = False
    count: int = Field(default=1, ge=1, le=10)


@pytest.fixture
def cm(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({}))
    os.environ["ILLUMIO_CONFIG"] = str(cfg_path)
    cm = ConfigManager(); cm.load()
    return cm


def test_save_section_happy_path(cm):
    r = save_section(cm, "demo", {"enabled": True, "count": 5}, _DemoModel)
    assert r["ok"] is True and r["requires_restart"] is True
    cm.load()
    assert cm.config["demo"] == {"enabled": True, "count": 5}


def test_save_section_validation_error(cm):
    r = save_section(cm, "demo", {"enabled": True, "count": 999}, _DemoModel)
    assert r["ok"] is False and "count" in r["errors"]


def test_save_section_atomic_on_failure(cm):
    path = os.environ["ILLUMIO_CONFIG"]
    before = open(path).read()
    save_section(cm, "demo", {"count": -5}, _DemoModel)
    assert open(path).read() == before
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

Run: `python3 -m pytest tests/test_settings_helpers.py -v`

- [ ] **Step 3: Create package + helper**

Create empty `src/gui/__init__.py`. Create `src/gui/settings_helpers.py`:

```python
"""Shared helper for per-module settings endpoints."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ValidationError


def save_section(cm, section_key: str, data: dict[str, Any],
                 pydantic_model: type[BaseModel]) -> dict[str, Any]:
    """Validate, merge into cm.config[section_key], atomic-write config.json."""
    try:
        validated = pydantic_model(**data)
    except ValidationError as e:
        return {"ok": False, "errors": _flatten_errors(e)}
    cm.config.setdefault(section_key, {})
    cm.config[section_key].update(validated.model_dump(mode="json"))
    cm.save()
    return {"ok": True, "requires_restart": True}


def _flatten_errors(exc: ValidationError) -> dict[str, str]:
    return {".".join(str(p) for p in err["loc"]): err["msg"] for err in exc.errors()}
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_settings_helpers.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/gui/__init__.py src/gui/settings_helpers.py tests/test_settings_helpers.py
git commit -m "feat(gui): add save_section() helper for per-module settings"
```

---

## Task 4: Extract `send_test_event()` into `src/siem/tester.py`

**Files:**
- Create: `src/siem/tester.py`
- Create: `tests/test_siem_tester.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_siem_tester.py`:

```python
from unittest.mock import MagicMock, patch
from src.config_models import SiemDestinationSettings
from src.siem.tester import send_test_event, TestResult


def _dest(**kw):
    base = dict(name="demo", enabled=True, transport="udp",
                format="cef", endpoint="127.0.0.1:514")
    base.update(kw); return SiemDestinationSettings(**base)


def test_send_test_event_success():
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock(); bt.return_value = tx
        r = send_test_event(_dest())
    assert isinstance(r, TestResult) and r.ok is True and r.error is None
    tx.send.assert_called_once(); tx.close.assert_called_once()


def test_send_test_event_failure():
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock(); tx.send.side_effect = RuntimeError("refused")
        bt.return_value = tx
        r = send_test_event(_dest())
    assert r.ok is False and "refused" in r.error


def test_send_test_event_hec_format():
    dest = _dest(format="json", transport="hec",
                 hec_token="abc", endpoint="https://splunk:8088")
    with patch("src.siem.tester._build_transport") as bt:
        bt.return_value = MagicMock()
        r = send_test_event(dest)
    assert r.ok is True
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_siem_tester.py -v`

- [ ] **Step 3: Create `src/siem/tester.py`**

Read `src/cli/siem.py:21-55` first to understand the existing inline test logic. Then:

```python
"""Shared synthetic-event tester for SIEM destinations."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.config_models import SiemDestinationSettings


@dataclass
class TestResult:
    ok: bool
    error: Optional[str] = None
    latency_ms: int = 0


def send_test_event(dest_cfg: SiemDestinationSettings) -> TestResult:
    started = time.monotonic()
    try:
        formatter = _build_formatter(dest_cfg.format)
        transport = _build_transport(dest_cfg)
        payload = formatter.format_event(_synthetic_event())
        transport.send(payload)
        transport.close()
        return TestResult(ok=True, latency_ms=int((time.monotonic() - started) * 1000))
    except Exception as exc:
        return TestResult(ok=False, error=str(exc),
                          latency_ms=int((time.monotonic() - started) * 1000))


def _synthetic_event() -> dict:
    return {"event_type": "siem.test", "severity": "info", "status": "success",
            "pce_fqdn": "illumio-ops-test", "pce_event_id": "test-0000",
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _build_formatter(fmt: str):
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.json_line import JSONLineFormatter
    return CEFFormatter() if fmt.startswith("cef") else JSONLineFormatter()


def _build_transport(dest_cfg: SiemDestinationSettings):
    """Build live transport. Deferred imports so tests can monkey-patch this symbol."""
    from src.siem.transports.udp import UdpTransport
    from src.siem.transports.tcp import TcpTransport
    from src.siem.transports.tls import TlsTransport
    from src.siem.transports.hec import HecTransport
    t = dest_cfg.transport
    if t == "udp": return UdpTransport(dest_cfg.endpoint)
    if t == "tcp": return TcpTransport(dest_cfg.endpoint)
    if t == "tls": return TlsTransport(dest_cfg.endpoint,
                                       tls_verify=dest_cfg.tls_verify,
                                       ca_bundle=dest_cfg.tls_ca_bundle)
    if t == "hec": return HecTransport(dest_cfg.endpoint, token=dest_cfg.hec_token,
                                       tls_verify=dest_cfg.tls_verify)
    raise ValueError(f"unsupported transport: {t}")
```

> **Note:** If actual transport class constructors differ from this sketch, adjust the `_build_transport` body. Keep the `send_test_event()` signature and `TestResult` shape stable — later tasks depend on them.

- [ ] **Step 4: Run tests — PASS**

Run: `python3 -m pytest tests/test_siem_tester.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/siem/tester.py tests/test_siem_tester.py
git commit -m "feat(siem): extract send_test_event() for reuse by CLI and HTTP"
```

---

## Task 5: Refactor `src/cli/siem.py::siem_test` to use the shared helper

**Files:**
- Modify: `src/cli/siem.py:21-55`

- [ ] **Step 1: Baseline existing CLI tests**

Run: `python3 -m pytest tests/test_siem_cli.py -v`  — record the PASS count.

- [ ] **Step 2: Replace the inline body**

In `src/cli/siem.py`, replace the body of `siem_test` (lines 21-55):

```python
@siem_group.command("test")
@click.argument("destination")
def siem_test(destination: str):
    """Send a synthetic test event to DESTINATION and report success/fail."""
    from src.config import ConfigManager
    from src.siem.tester import send_test_event

    cm = ConfigManager()
    siem_cfg = cm.models.siem
    dest_names = [d.name for d in siem_cfg.destinations if d.enabled]
    if destination not in dest_names:
        console.print(f"[red]Destination '{destination}' not found or disabled.[/red]")
        raise SystemExit(1)
    dest_cfg = next(d for d in siem_cfg.destinations if d.name == destination)

    result = send_test_event(dest_cfg)
    if result.ok:
        console.print(f"[green]✓ Test event sent to '{destination}' ({result.latency_ms} ms)[/green]")
    else:
        console.print(f"[red]✗ Test failed for '{destination}': {result.error}[/red]")
        raise SystemExit(1)
```

- [ ] **Step 3: Rerun existing tests — no regression**

Run: `python3 -m pytest tests/test_siem_cli.py -v`  — same PASS count.

- [ ] **Step 4: Commit**

```bash
git add src/cli/siem.py
git commit -m "refactor(siem): use shared send_test_event() in CLI"
```

---

## Task 6: `GET/PUT /api/cache/settings`

**Files:**
- Modify: `src/pce_cache/web.py`
- Create: `tests/test_cache_web.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cache_web.py`:

```python
import json, os, tempfile
import pytest
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt, h = hash_password("pw")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s"},
                       "pce_cache": {"enabled": False,
                                     "db_path": str(tmp_path / "cache.sqlite")}}, f)
        os.environ["ILLUMIO_CONFIG"] = path
        cm = ConfigManager(); cm.load()
        from src.gui import _create_app
        app = _create_app(cm); app.config["TESTING"] = True
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "pw"},
                   follow_redirects=True)
            yield c
    finally:
        os.unlink(path)


def test_get_cache_settings(client):
    resp = client.get("/api/cache/settings")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["enabled"] is False
    assert "traffic_filter" in body and "traffic_sampling" in body


def test_put_cache_settings_happy(client, tmp_path):
    resp = client.put("/api/cache/settings", json={
        "enabled": True, "db_path": str(tmp_path / "cache.sqlite"),
        "events_retention_days": 60, "traffic_raw_retention_days": 5,
        "traffic_agg_retention_days": 60,
        "events_poll_interval_seconds": 300, "traffic_poll_interval_seconds": 3600,
        "rate_limit_per_minute": 400, "async_threshold_events": 10000,
        "traffic_filter": {"actions": ["blocked"], "workload_label_env": ["prod"],
                           "ports": [443], "protocols": ["TCP"],
                           "exclude_src_ips": ["10.0.0.1"]},
        "traffic_sampling": {"sample_ratio_allowed": 1, "max_rows_per_batch": 10000}})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True and b["requires_restart"] is True


def test_put_cache_invalid_ip(client):
    resp = client.put("/api/cache/settings",
                      json={"traffic_filter": {"exclude_src_ips": ["not-an-ip"]}})
    assert resp.status_code == 422
    assert resp.get_json()["ok"] is False


def test_put_cache_bad_poll_interval(client):
    resp = client.put("/api/cache/settings",
                      json={"events_poll_interval_seconds": 5})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run — expect FAIL (404)**

Run: `python3 -m pytest tests/test_cache_web.py -v`

- [ ] **Step 3: Add endpoints to `src/pce_cache/web.py`**

Append after the existing `/backfill` and `/status` routes:

```python
@bp.route("/settings", methods=["GET"])
@login_required
def get_cache_settings():
    from src.config import ConfigManager
    return jsonify(ConfigManager().models.pce_cache.model_dump(mode="json"))


@bp.route("/settings", methods=["PUT"])
@login_required
def put_cache_settings():
    from src.config import ConfigManager
    from src.config_models import PceCacheSettings
    from src.gui.settings_helpers import save_section
    cm = ConfigManager()
    incoming = request.get_json(silent=True) or {}
    # Allow partial PUT: merge with current before validating.
    current = cm.models.pce_cache.model_dump(mode="json")
    current.update(incoming)
    result = save_section(cm, "pce_cache", current, PceCacheSettings)
    return jsonify(result), (200 if result["ok"] else 422)
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_cache_web.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/web.py tests/test_cache_web.py
git commit -m "feat(cache): GET/PUT /api/cache/settings endpoints"
```

---

## Task 7: `GET/PUT /api/siem/forwarder`

**Files:**
- Modify: `src/siem/web.py`
- Create: `tests/test_siem_forwarder_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_siem_forwarder_api.py`:

```python
import json, os, tempfile
import pytest
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt, h = hash_password("pw")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s"},
                       "siem": {"enabled": False, "dispatch_tick_seconds": 5,
                                "dlq_max_per_dest": 10000}}, f)
        os.environ["ILLUMIO_CONFIG"] = path
        cm = ConfigManager(); cm.load()
        from src.gui import _create_app
        app = _create_app(cm); app.config["TESTING"] = True
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "pw"},
                   follow_redirects=True)
            yield c
    finally:
        os.unlink(path)


def test_get_forwarder(client):
    resp = client.get("/api/siem/forwarder")
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["enabled"] is False
    assert "destinations" not in b  # served via /api/siem/destinations


def test_put_forwarder_happy(client):
    resp = client.put("/api/siem/forwarder",
                      json={"enabled": True, "dispatch_tick_seconds": 10,
                            "dlq_max_per_dest": 5000})
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True and b["requires_restart"] is True


def test_put_forwarder_invalid(client):
    resp = client.put("/api/siem/forwarder", json={"dispatch_tick_seconds": 0})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_siem_forwarder_api.py -v`

- [ ] **Step 3: Add endpoints to `src/siem/web.py`**

```python
@bp.route("/forwarder", methods=["GET"])
@login_required
def get_forwarder():
    from src.config import ConfigManager
    s = ConfigManager().models.siem
    return jsonify({"enabled": s.enabled,
                    "dispatch_tick_seconds": s.dispatch_tick_seconds,
                    "dlq_max_per_dest": s.dlq_max_per_dest})


@bp.route("/forwarder", methods=["PUT"])
@login_required
def put_forwarder():
    from src.config import ConfigManager
    from src.config_models import SiemForwarderSettings
    from src.gui.settings_helpers import save_section
    cm = ConfigManager()
    incoming = request.get_json(silent=True) or {}
    current = cm.models.siem.model_dump(mode="json")
    for k in ("enabled", "dispatch_tick_seconds", "dlq_max_per_dest"):
        if k in incoming:
            current[k] = incoming[k]
    result = save_section(cm, "siem", current, SiemForwarderSettings)
    return jsonify(result), (200 if result["ok"] else 422)
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_siem_forwarder_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/siem/web.py tests/test_siem_forwarder_api.py
git commit -m "feat(siem): GET/PUT /api/siem/forwarder endpoints"
```

---

## Task 8: `POST /api/siem/destinations/<name>/test`

**Files:**
- Modify: `src/siem/web.py`
- Create: `tests/test_siem_test_endpoint.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_siem_test_endpoint.py`:

```python
import json, os, tempfile
from unittest.mock import patch
import pytest
from src.config import ConfigManager, hash_password
from src.siem.tester import TestResult


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt, h = hash_password("pw")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s"},
                       "siem": {"enabled": True, "destinations": [{
                           "name": "demo", "enabled": True, "transport": "udp",
                           "format": "cef", "endpoint": "127.0.0.1:514"}]}}, f)
        os.environ["ILLUMIO_CONFIG"] = path
        cm = ConfigManager(); cm.load()
        from src.gui import _create_app
        app = _create_app(cm); app.config["TESTING"] = True
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "pw"},
                   follow_redirects=True)
            yield c
    finally:
        os.unlink(path)


def test_test_endpoint_success(client):
    with patch("src.siem.web.send_test_event",
               return_value=TestResult(ok=True, latency_ms=12)):
        resp = client.post("/api/siem/destinations/demo/test")
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is True and b["latency_ms"] == 12


def test_test_endpoint_failure(client):
    with patch("src.siem.web.send_test_event",
               return_value=TestResult(ok=False, error="refused", latency_ms=5)):
        resp = client.post("/api/siem/destinations/demo/test")
    assert resp.status_code == 200
    b = resp.get_json()
    assert b["ok"] is False and b["error"] == "refused"


def test_test_endpoint_unknown(client):
    resp = client.post("/api/siem/destinations/nosuch/test")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_siem_test_endpoint.py -v`

- [ ] **Step 3: Add endpoint**

At top of `src/siem/web.py`: `from src.siem.tester import send_test_event`

```python
@bp.route("/destinations/<name>/test", methods=["POST"])
@login_required
def test_destination(name: str):
    from src.config import ConfigManager
    dest = next((d for d in ConfigManager().models.siem.destinations
                 if d.name == name), None)
    if dest is None:
        return jsonify({"ok": False, "error": "destination not found"}), 404
    r = send_test_event(dest)
    return jsonify({"ok": r.ok, "error": r.error, "latency_ms": r.latency_ms}), 200
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_siem_test_endpoint.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/siem/web.py tests/test_siem_test_endpoint.py
git commit -m "feat(siem): POST /destinations/<name>/test endpoint"
```

---

## Task 9: `GET /api/siem/dlq/export` CSV

**Files:**
- Modify: `src/siem/web.py`
- Create: `tests/test_siem_dlq_export.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_siem_dlq_export.py`:

```python
import csv, io, json, os, tempfile
from datetime import datetime, timezone
import pytest
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt, h = hash_password("pw")
        db_path = str(tmp_path / "cache.sqlite")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s"},
                       "pce_cache": {"enabled": True, "db_path": db_path},
                       "siem": {"enabled": True, "destinations": [{
                           "name": "demo", "enabled": True, "transport": "udp",
                           "format": "cef", "endpoint": "127.0.0.1:514"}]}}, f)
        os.environ["ILLUMIO_CONFIG"] = path
        cm = ConfigManager(); cm.load()
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.models import DeadLetter
        engine = create_engine(f"sqlite:///{db_path}")
        init_schema(engine)
        with sessionmaker(engine)() as s:
            s.add(DeadLetter(destination="demo", event_id="evt-1",
                             reason="timeout", payload='{"k":"v"}',
                             failed_at=datetime.now(timezone.utc)))
            s.commit()
        from src.gui import _create_app
        app = _create_app(cm); app.config["TESTING"] = True
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "pw"},
                   follow_redirects=True)
            yield c
    finally:
        os.unlink(path)


def test_dlq_export_all(client):
    resp = client.get("/api/siem/dlq/export")
    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert rows[0] == ["id", "destination", "event_id", "reason",
                       "failed_at", "payload_summary"]
    assert len(rows) >= 2
    assert rows[1][1] == "demo" and rows[1][3] == "timeout"


def test_dlq_export_filtered(client):
    resp = client.get("/api/siem/dlq/export?destination=nosuch")
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert len(rows) == 1  # header only
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_siem_dlq_export.py -v`

- [ ] **Step 3: Add endpoint**

```python
@bp.route("/dlq/export", methods=["GET"])
@login_required
def dlq_export():
    from flask import Response
    import csv, io
    from sqlalchemy import select
    from src.pce_cache.models import DeadLetter

    destination = request.args.get("destination", "").strip()
    reason = request.args.get("reason", "").strip()
    Session = _get_sf()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "destination", "event_id", "reason",
                "failed_at", "payload_summary"])
    with Session() as s:
        q = select(DeadLetter)
        if destination:
            q = q.where(DeadLetter.destination == destination)
        if reason:
            q = q.where(DeadLetter.reason.like(f"%{reason}%"))
        for row in s.scalars(q):
            payload_str = row.payload or ""
            summary = (payload_str[:120] + "…") if len(payload_str) > 120 else payload_str
            w.writerow([row.id, row.destination, row.event_id,
                        row.reason, row.failed_at.isoformat(), summary])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=dlq.csv"})
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_siem_dlq_export.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/siem/web.py tests/test_siem_dlq_export.py
git commit -m "feat(siem): CSV export of DLQ with filters"
```

---

## Task 10: `POST /api/daemon/restart` + `_GUI_OWNS_DAEMON`

**Files:**
- Modify: `src/gui.py`
- Modify: `src/main.py` (`run_daemon_with_gui`)
- Create: `tests/test_daemon_restart_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_daemon_restart_api.py`:

```python
import json, os, tempfile
from unittest.mock import MagicMock
import pytest
import src.gui as gui_module
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt, h = hash_password("pw")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s"}}, f)
        os.environ["ILLUMIO_CONFIG"] = path
        cm = ConfigManager(); cm.load()
        from src.gui import _create_app
        app = _create_app(cm); app.config["TESTING"] = True
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "pw"},
                   follow_redirects=True)
            yield c
    finally:
        os.unlink(path)
        gui_module._GUI_OWNS_DAEMON = False
        gui_module._DAEMON_SCHEDULER = None
        gui_module._DAEMON_RESTART_FN = None


def test_restart_not_owned_returns_409(client):
    gui_module._GUI_OWNS_DAEMON = False
    resp = client.post("/api/daemon/restart")
    assert resp.status_code == 409
    assert "external" in resp.get_json()["error"].lower()


def test_restart_owned_calls_hook(client):
    gui_module._GUI_OWNS_DAEMON = True
    fn = MagicMock(return_value=MagicMock())
    gui_module._DAEMON_RESTART_FN = fn
    resp = client.post("/api/daemon/restart")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    fn.assert_called_once()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_daemon_restart_api.py -v`

- [ ] **Step 3: Add module-level state + route in `src/gui.py`**

Near the top of `src/gui.py`:

```python
# Daemon-restart hook state. Set by run_daemon_with_gui() in src/main.py.
_GUI_OWNS_DAEMON: bool = False
_DAEMON_SCHEDULER = None
_DAEMON_RESTART_FN = None
```

Inside `_create_app()`, alongside other routes:

```python
@app.route('/api/daemon/restart', methods=['POST'])
@login_required
def api_daemon_restart():
    import src.gui as _self
    if not _self._GUI_OWNS_DAEMON:
        return jsonify({"ok": False,
                        "error": "Daemon is managed externally; restart via systemctl or your service manager."}), 409
    if _self._DAEMON_RESTART_FN is None:
        return jsonify({"ok": False, "error": "restart hook not installed"}), 500
    try:
        _self._DAEMON_SCHEDULER = _self._DAEMON_RESTART_FN()
        return jsonify({"ok": True}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
```

- [ ] **Step 4: Install the hook in `src/main.py::run_daemon_with_gui`**

Locate `run_daemon_with_gui(interval_minutes, port)` (around line 112 per `git grep -n 'def run_daemon_with_gui' src/main.py`). Near the top of the function body, before the Flask app starts, install:

```python
import src.gui as gui_module
from src.scheduler import build_scheduler

def _restart():
    if gui_module._DAEMON_SCHEDULER is not None:
        try:
            gui_module._DAEMON_SCHEDULER.shutdown(wait=False)
        except Exception:
            logger.exception("scheduler shutdown failed (continuing)")
    cm.load()  # re-read config.json
    new_sched = build_scheduler(cm, interval_minutes=interval_minutes)
    new_sched.start()
    return new_sched

gui_module._GUI_OWNS_DAEMON = True
gui_module._DAEMON_RESTART_FN = _restart
gui_module._DAEMON_SCHEDULER = _restart()  # first boot uses same path
```

> Reuse the rest of the existing `run_daemon_with_gui` body unchanged (Flask setup, thread start, signal handlers). Read git blame on the function before editing to avoid clobbering.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_daemon_restart_api.py -v`
Run: `python3 -m pytest tests/ -q`  — ensure nothing else regresses.

- [ ] **Step 6: Commit**

```bash
git add src/gui.py src/main.py tests/test_daemon_restart_api.py
git commit -m "feat(daemon): /api/daemon/restart endpoint (GUI-owned daemon)"
```

---

## Task 11: `manage_pce_cache_menu(cm)` interactive CLI

**Files:**
- Create: `src/pce_cache_cli.py`
- Create: `tests/test_pce_cache_menu.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pce_cache_menu.py`:

```python
import builtins, json, os
from unittest.mock import patch
import pytest
from src.config import ConfigManager


@pytest.fixture
def cm(tmp_path):
    p = tmp_path / "config.json"; p.write_text(json.dumps({}))
    os.environ["ILLUMIO_CONFIG"] = str(p)
    cm = ConfigManager(); cm.load()
    return cm


def _seq(values):
    it = iter(values)
    return lambda _p="": next(it)


def test_menu_back_exits(cm, capsys):
    from src.pce_cache_cli import manage_pce_cache_menu
    with patch.object(builtins, "input", _seq(["0"])):
        manage_pce_cache_menu(cm)
    assert "PCE Cache Menu" in capsys.readouterr().out


def test_menu_edit_settings_persists(cm):
    """Option 2, accept defaults except events_retention_days=60."""
    from src.pce_cache_cli import manage_pce_cache_menu
    # Sequence: choose 2 → 9 prompts (bool, db_path, 3 retention, 2 poll, rate, async)
    # Pass blanks except events_retention_days as "60".
    inputs = ["2", "", "", "60", "", "", "", "", "", "", "0"]
    with patch.object(builtins, "input", _seq(inputs)):
        manage_pce_cache_menu(cm)
    cm.load()
    assert cm.config.get("pce_cache", {}).get("events_retention_days") == 60


def test_menu_invalid_choice(cm, capsys):
    from src.pce_cache_cli import manage_pce_cache_menu
    with patch.object(builtins, "input", _seq(["99", "0"])):
        manage_pce_cache_menu(cm)
    out = capsys.readouterr().out.lower()
    assert "invalid" in out or "please" in out
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_pce_cache_menu.py -v`

- [ ] **Step 3: Create `src/pce_cache_cli.py`**

```python
"""Interactive menu for PCE Cache (distinct from click subcommands in src/cli/cache.py)."""
from __future__ import annotations

from src.config_models import PceCacheSettings
from src.gui.settings_helpers import save_section


MENU = (
    "PCE Cache Menu:\n"
    "  1. View status\n"
    "  2. Edit settings (basic / retention / polling / throughput)\n"
    "  3. Edit traffic filter\n"
    "  4. Edit traffic sampling\n"
    "  5. Backfill (interactive)\n"
    "  6. Run retention now\n"
    "  0. Back\n"
)


def manage_pce_cache_menu(cm) -> None:
    while True:
        print(MENU)
        choice = input("> ").strip()
        if choice == "0":
            return
        elif choice == "1":
            _view_status(cm)
        elif choice == "2":
            _edit_core_settings(cm)
        elif choice == "3":
            _edit_traffic_filter(cm)
        elif choice == "4":
            _edit_traffic_sampling(cm)
        elif choice == "5":
            _run_backfill(cm)
        elif choice == "6":
            _run_retention(cm)
        else:
            print("invalid choice; please enter 0-6")


def _prompt(name, current, cast=str):
    raw = input(f"  {name} [{current}]: ").strip()
    if raw == "":
        return current
    if cast is bool:
        return raw.lower() in ("1", "true", "y", "yes")
    try:
        return cast(raw)
    except ValueError:
        print(f"  invalid {name}; keeping {current}")
        return current


def _edit_core_settings(cm):
    c = cm.models.pce_cache.model_dump(mode="json")
    c["enabled"] = _prompt("enabled", c["enabled"], bool)
    c["db_path"] = _prompt("db_path", c["db_path"])
    c["events_retention_days"] = _prompt("events_retention_days", c["events_retention_days"], int)
    c["traffic_raw_retention_days"] = _prompt("traffic_raw_retention_days", c["traffic_raw_retention_days"], int)
    c["traffic_agg_retention_days"] = _prompt("traffic_agg_retention_days", c["traffic_agg_retention_days"], int)
    c["events_poll_interval_seconds"] = _prompt("events_poll_interval_seconds", c["events_poll_interval_seconds"], int)
    c["traffic_poll_interval_seconds"] = _prompt("traffic_poll_interval_seconds", c["traffic_poll_interval_seconds"], int)
    c["rate_limit_per_minute"] = _prompt("rate_limit_per_minute", c["rate_limit_per_minute"], int)
    c["async_threshold_events"] = _prompt("async_threshold_events", c["async_threshold_events"], int)
    _persist(cm, c)


def _edit_traffic_filter(cm):
    c = cm.models.pce_cache.model_dump(mode="json")
    tf = c.setdefault("traffic_filter", {})
    for key in ("actions", "protocols", "workload_label_env", "exclude_src_ips"):
        cur = tf.get(key, [])
        raw = input(f"  {key} (comma, [{','.join(str(x) for x in cur)}]): ").strip()
        if raw:
            tf[key] = [x.strip() for x in raw.split(",") if x.strip()]
    cur_ports = tf.get("ports", [])
    raw = input(f"  ports (comma, [{','.join(str(p) for p in cur_ports)}]): ").strip()
    if raw:
        try:
            tf["ports"] = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("  invalid ports; keeping previous")
    _persist(cm, c)


def _edit_traffic_sampling(cm):
    c = cm.models.pce_cache.model_dump(mode="json")
    ts = c.setdefault("traffic_sampling", {})
    ts["sample_ratio_allowed"] = _prompt("sample_ratio_allowed", ts.get("sample_ratio_allowed", 1), int)
    ts["max_rows_per_batch"] = _prompt("max_rows_per_batch", ts.get("max_rows_per_batch", 200000), int)
    _persist(cm, c)


def _persist(cm, data):
    result = save_section(cm, "pce_cache", data, PceCacheSettings)
    if result["ok"]:
        print("[!] Settings saved. Restart monitor to apply scheduling changes.")
    else:
        print("[x] Validation error:")
        for path, msg in result["errors"].items():
            print(f"    {path}: {msg}")


def _view_status(cm):
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
    cfg = cm.models.pce_cache
    print(f"  enabled: {cfg.enabled}")
    print(f"  db_path: {cfg.db_path}")
    try:
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        with sessionmaker(engine)() as s:
            n_ev = s.scalar(select(func.count()).select_from(PceEvent)) or 0
            n_tr = s.scalar(select(func.count()).select_from(PceTrafficFlowRaw)) or 0
            print(f"  events rows: {n_ev}")
            print(f"  traffic_raw rows: {n_tr}")
    except Exception as exc:
        print(f"  (status unavailable: {exc})")


def _run_backfill(cm):
    start = input("  start (YYYY-MM-DD): ").strip()
    end = input("  end (YYYY-MM-DD): ").strip()
    if not start or not end:
        print("  cancelled"); return
    try:
        from src.pce_cache.backfill import BackfillRunner
        from src.api_client import ApiClient
        api = ApiClient.from_config(cm)
        BackfillRunner(cm=cm, api=api).run(start=start, end=end)
        print("  backfill complete")
    except Exception as exc:
        print(f"  backfill failed: {exc}")


def _run_retention(cm):
    try:
        from sqlalchemy import create_engine
        from src.pce_cache.retention import RetentionWorker
        from src.pce_cache.schema import init_schema
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        RetentionWorker(engine=engine, cfg=cfg).run_once()
        print("  retention complete")
    except Exception as exc:
        print(f"  retention failed: {exc}")
```

> **Note:** `BackfillRunner`, `RetentionWorker`, `ApiClient.from_config` signatures may differ. Open those modules and adjust. Keep the menu text and options stable.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_pce_cache_menu.py -v`
(Adjust the number of empty inputs in `test_menu_edit_settings_persists` if actual prompt count differs.)

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache_cli.py tests/test_pce_cache_menu.py
git commit -m "feat(cache): interactive CLI menu manage_pce_cache_menu()"
```

---

## Task 12: `manage_siem_menu(cm)` interactive CLI (with DLQ submenu)

**Files:**
- Create: `src/siem_cli.py`
- Create: `tests/test_siem_menu.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_siem_menu.py`:

```python
import builtins, json, os
from unittest.mock import patch
import pytest
from src.config import ConfigManager


@pytest.fixture
def cm(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"siem": {"enabled": True, "destinations": []}}))
    os.environ["ILLUMIO_CONFIG"] = str(p)
    cm = ConfigManager(); cm.load()
    return cm


def _seq(values):
    it = iter(values)
    return lambda _p="": next(it)


def test_menu_list_empty(cm, capsys):
    from src.siem_cli import manage_siem_menu
    with patch.object(builtins, "input", _seq(["3", "", "0"])):
        manage_siem_menu(cm)
    assert "destinations" in capsys.readouterr().out.lower()


def test_menu_add_destination(cm):
    """Option 4: add minimal destination."""
    from src.siem_cli import manage_siem_menu
    inputs = ["4",
              "demo", "true", "udp", "cef", "127.0.0.1:514",
              "", "", "", "", "", "",   # tls_verify, ca_bundle, hec_token, batch, source_types, max_retries
              "0"]
    with patch.object(builtins, "input", _seq(inputs)):
        manage_siem_menu(cm)
    cm.load()
    dests = cm.config.get("siem", {}).get("destinations", [])
    assert any(d.get("name") == "demo" for d in dests)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `python3 -m pytest tests/test_siem_menu.py -v`

- [ ] **Step 3: Create `src/siem_cli.py`**

```python
"""Interactive menu for SIEM Forwarder (distinct from click subcommands in src/cli/siem.py)."""
from __future__ import annotations

from src.config_models import SiemDestinationSettings, SiemForwarderSettings
from src.gui.settings_helpers import save_section


MENU = (
    "SIEM Forwarder Menu:\n"
    "  1. View status\n"
    "  2. Edit forwarder config\n"
    "  3. List destinations\n"
    "  4. Add destination\n"
    "  5. Edit destination\n"
    "  6. Delete destination\n"
    "  7. Test destination\n"
    "  8. DLQ management\n"
    "  0. Back\n"
)

DLQ_MENU = (
    "  DLQ Management:\n"
    "    a. List entries\n"
    "    b. Replay selected\n"
    "    c. Purge selected\n"
    "    d. Purge ALL by destination\n"
    "    e. Export to CSV\n"
    "    0. Back\n"
)


def manage_siem_menu(cm):
    while True:
        print(MENU)
        choice = input("> ").strip()
        if choice == "0": return
        elif choice == "1": _view_status(cm)
        elif choice == "2": _edit_forwarder(cm)
        elif choice == "3": _list_destinations(cm)
        elif choice == "4": _add_destination(cm)
        elif choice == "5": _edit_destination(cm)
        elif choice == "6": _delete_destination(cm)
        elif choice == "7": _test_destination(cm)
        elif choice == "8": _dlq_submenu(cm)
        else: print("invalid choice")


def _prompt(name, current, cast=str):
    raw = input(f"  {name} [{current}]: ").strip()
    if raw == "": return current
    if cast is bool: return raw.lower() in ("1", "true", "y", "yes")
    try: return cast(raw)
    except ValueError:
        print(f"  invalid {name}; keeping {current}")
        return current


def _view_status(cm):
    s = cm.models.siem
    print(f"  enabled: {s.enabled}")
    print(f"  dispatch_tick_seconds: {s.dispatch_tick_seconds}")
    print(f"  dlq_max_per_dest: {s.dlq_max_per_dest}")
    print(f"  destinations: {len(s.destinations)}")


def _edit_forwarder(cm):
    c = cm.models.siem.model_dump(mode="json")
    c["enabled"] = _prompt("enabled", c["enabled"], bool)
    c["dispatch_tick_seconds"] = _prompt("dispatch_tick_seconds", c["dispatch_tick_seconds"], int)
    c["dlq_max_per_dest"] = _prompt("dlq_max_per_dest", c["dlq_max_per_dest"], int)
    r = save_section(cm, "siem", c, SiemForwarderSettings)
    _report(r)


def _report(r):
    if r["ok"]:
        print("[!] Settings saved. Restart monitor to apply.")
    else:
        for path, msg in r["errors"].items():
            print(f"    {path}: {msg}")


def _list_destinations(cm):
    for d in cm.models.siem.destinations:
        status = "[enabled]" if d.enabled else "[disabled]"
        print(f"  - {d.name} ({d.transport}/{d.format}) -> {d.endpoint} {status}")
    input("  (press Enter)")


def _prompt_destination(existing=None):
    existing = existing or {}
    name = _prompt("name", existing.get("name", ""))
    enabled = _prompt("enabled", existing.get("enabled", True), bool)
    transport = _prompt("transport (udp/tcp/tls/hec)", existing.get("transport", "udp"))
    format_ = _prompt("format (cef/json/syslog_cef/syslog_json)", existing.get("format", "cef"))
    endpoint = _prompt("endpoint", existing.get("endpoint", ""))
    tls_verify = _prompt("tls_verify", existing.get("tls_verify", True), bool)
    tls_ca_bundle = _prompt("tls_ca_bundle", existing.get("tls_ca_bundle") or "")
    hec_token = _prompt("hec_token", existing.get("hec_token") or "")
    batch_size = _prompt("batch_size", existing.get("batch_size", 100), int)
    raw = input(f"  source_types (comma, [{','.join(existing.get('source_types', ['audit','traffic']))}]): ").strip()
    source_types = ([x.strip() for x in raw.split(",") if x.strip()]
                    if raw else existing.get("source_types", ["audit", "traffic"]))
    max_retries = _prompt("max_retries", existing.get("max_retries", 10), int)
    return {"name": name, "enabled": enabled, "transport": transport,
            "format": format_, "endpoint": endpoint, "tls_verify": tls_verify,
            "tls_ca_bundle": tls_ca_bundle or None,
            "hec_token": hec_token or None,
            "batch_size": batch_size, "source_types": source_types,
            "max_retries": max_retries}


def _add_destination(cm):
    data = _prompt_destination()
    try:
        SiemDestinationSettings(**data)
    except Exception as exc:
        print(f"  validation error: {exc}"); return
    siem = cm.models.siem.model_dump(mode="json")
    siem.setdefault("destinations", []).append(data)
    _report(save_section(cm, "siem", siem, SiemForwarderSettings))


def _edit_destination(cm):
    name = input("  destination to edit: ").strip()
    siem = cm.models.siem.model_dump(mode="json")
    dests = siem.get("destinations", [])
    for i, d in enumerate(dests):
        if d.get("name") == name:
            dests[i] = _prompt_destination(d)
            siem["destinations"] = dests
            _report(save_section(cm, "siem", siem, SiemForwarderSettings))
            return
    print("  not found")


def _delete_destination(cm):
    name = input("  destination to delete: ").strip()
    if input(f"  confirm delete '{name}'? (yes/no): ").strip().lower() != "yes":
        print("  cancelled"); return
    siem = cm.models.siem.model_dump(mode="json")
    siem["destinations"] = [d for d in siem.get("destinations", []) if d.get("name") != name]
    _report(save_section(cm, "siem", siem, SiemForwarderSettings))


def _test_destination(cm):
    from src.siem.tester import send_test_event
    name = input("  destination to test: ").strip()
    dest = next((d for d in cm.models.siem.destinations if d.name == name), None)
    if dest is None:
        print("  not found"); return
    r = send_test_event(dest)
    if r.ok: print(f"  ✓ succeeded ({r.latency_ms} ms)")
    else:    print(f"  ✗ failed: {r.error}")


def _dlq_submenu(cm):
    while True:
        print(DLQ_MENU)
        c = input("  > ").strip().lower()
        if c == "0": return
        elif c == "a": _dlq_list(cm)
        elif c == "b": _dlq_bulk(cm, action="replay")
        elif c == "c": _dlq_bulk(cm, action="purge")
        elif c == "d": _dlq_purge_all(cm)
        elif c == "e": _dlq_export(cm)


def _dlq_engine(cm):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{cm.models.pce_cache.db_path}")
    init_schema(engine)
    return sessionmaker(engine)


def _dlq_list(cm):
    from sqlalchemy import select
    from src.pce_cache.models import DeadLetter
    with _dlq_engine(cm)() as s:
        for row in s.scalars(select(DeadLetter).limit(50)):
            print(f"  [{row.id}] {row.destination} evt={row.event_id} "
                  f"reason={row.reason} failed_at={row.failed_at.isoformat()}")


def _dlq_bulk(cm, action):
    ids = input(f"  DLQ ids to {action} (comma): ").strip()
    if not ids: return
    from src.siem.dlq import DeadLetterQueue
    dlq = DeadLetterQueue(cm)
    for i in [int(x) for x in ids.split(",")]:
        (dlq.replay if action == "replay" else dlq.purge)(i)
    print(f"  {action} submitted")


def _dlq_purge_all(cm):
    name = input("  destination: ").strip()
    if input(f"  type '{name}' to confirm: ").strip() != name:
        print("  cancelled"); return
    from src.siem.dlq import DeadLetterQueue
    DeadLetterQueue(cm).purge_by_destination(name)
    print("  purged all")


def _dlq_export(cm):
    import csv
    from sqlalchemy import select
    from src.pce_cache.models import DeadLetter
    path = input("  output path (e.g. dlq.csv): ").strip()
    if not path: return
    with open(path, "w") as f:
        w = csv.writer(f)
        w.writerow(["id", "destination", "event_id", "reason", "failed_at", "payload_summary"])
        with _dlq_engine(cm)() as s:
            for row in s.scalars(select(DeadLetter)):
                p = row.payload or ""
                summary = (p[:120] + "…") if len(p) > 120 else p
                w.writerow([row.id, row.destination, row.event_id, row.reason,
                            row.failed_at.isoformat(), summary])
    print(f"  exported to {path}")
```

> **Note:** `DeadLetterQueue(cm)` and its methods (`replay(id)`, `purge(id)`, `purge_by_destination(name)`) are sketches. Open `src/siem/dlq.py` and adjust call signatures to the real interface.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_siem_menu.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/siem_cli.py tests/test_siem_menu.py
git commit -m "feat(siem): interactive CLI menu manage_siem_menu() with DLQ submenu"
```

---

## Task 13: Wire new menus into `src/main.py`

**Files:**
- Modify: `src/main.py` (main menu function)

- [ ] **Step 1: Locate main menu**

Run: `grep -nE 'def |Main menu|settings_menu\(cm\)' src/main.py | head`  — find the function that prints numbered main-menu options and dispatches on input.

- [ ] **Step 2: Insert entries before Settings**

Modify that function. Example (adjust numeric labels to match actual):

```python
# New menu items (insert before the Settings option):
print("  N. Manage PCE Cache")
print("  N+1. Manage SIEM Forwarder")
# ...

elif choice == "N":
    from src.pce_cache_cli import manage_pce_cache_menu
    manage_pce_cache_menu(cm)
elif choice == "N+1":
    from src.siem_cli import manage_siem_menu
    manage_siem_menu(cm)
```

(Replace `N` and `N+1` with the actual next-available integers in the existing menu, and shift `Settings` one number down if needed.)

- [ ] **Step 3: Smoke-test**

Run: `python3 illumio_ops.py`  → enter N (Cache) then 0 (back); enter N+1 (SIEM) then 0. Both menus appear and return cleanly.

- [ ] **Step 4: Full pytest**

Run: `python3 -m pytest tests/ -q`
Expected: previous passing count + 5 (or more) new tests.

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat(cli): wire new Cache/SIEM menus into main menu"
```

---

## Task 14: Integrations top-level tab + sub-tab switcher

**Files:**
- Modify: `src/templates/index.html` (tab bar + panel)
- Create: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add the tab button to `src/templates/index.html`**

Insert, before the existing `<button ...data-tab="settings"...>` (around line 193):

```html
<button class="tab" type="button" role="tab" aria-selected="false"
        aria-controls="p-integrations" data-tab="integrations"
        onclick="switchTab('integrations')" data-i18n="gui_tab_integrations">
  <svg class="icon"><use href="#icon-settings"></use></svg> Integrations
</button>
```

- [ ] **Step 2: Add the panel skeleton**

Immediately before the existing `<div class="panel" id="p-settings">` (around line 956), add the panel. **Only static markup — no user data interpolated here**:

```html
<div class="panel" id="p-integrations">
  <div class="sub-tab-bar" style="display:flex;gap:8px;margin-bottom:16px;border-bottom:2px solid var(--border);padding-bottom:10px;">
    <button class="btn sub-tab active" onclick="integrationsSwitch('overview')"
            data-i18n="gui_it_overview">Overview</button>
    <button class="btn sub-tab" onclick="integrationsSwitch('cache')"
            data-i18n="gui_it_cache">Cache</button>
    <button class="btn sub-tab" onclick="integrationsSwitch('siem')"
            data-i18n="gui_it_siem">SIEM</button>
    <button class="btn sub-tab" onclick="integrationsSwitch('dlq')"
            data-i18n="gui_it_dlq">DLQ</button>
  </div>
  <div id="it-pane-overview" class="it-pane"></div>
  <div id="it-pane-cache" class="it-pane" style="display:none;"></div>
  <div id="it-pane-siem" class="it-pane" style="display:none;"></div>
  <div id="it-pane-dlq" class="it-pane" style="display:none;"></div>
</div>

<script src="{{ url_for('static', filename='js/integrations.js') }}"></script>
```

- [ ] **Step 3: Create `src/static/js/integrations.js`**

Bootstrap file with the switcher, shared helpers, and placeholder renderers. Subsequent tasks replace each renderer body:

```javascript
// Integrations tab: switcher + shared helpers + per-pane renderers.
(function () {
  'use strict';

  // Escape user-provided text before inserting into markup.
  // Used throughout this module — NEVER inline user data without this.
  function escapeAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  window.escapeAttr = escapeAttr;

  function integrationsSwitch(name) {
    ['overview', 'cache', 'siem', 'dlq'].forEach(function (n) {
      var pane = document.getElementById('it-pane-' + n);
      if (pane) pane.style.display = (n === name) ? '' : 'none';
    });
    document.querySelectorAll('#p-integrations .sub-tab').forEach(function (btn) {
      btn.classList.toggle('active',
        btn.getAttribute('onclick') && btn.getAttribute('onclick').indexOf("'" + name + "'") >= 0);
    });
    if (name === 'overview') renderOverview();
    else if (name === 'cache') renderCache();
    else if (name === 'siem') renderSiem();
    else if (name === 'dlq') renderDlq();
  }
  window.integrationsSwitch = integrationsSwitch;

  // Hook into the project's existing switchTab to auto-render Overview on first visit.
  var originalSwitchTab = window.switchTab;
  if (typeof originalSwitchTab === 'function') {
    window.switchTab = function (name) {
      var r = originalSwitchTab.apply(this, arguments);
      if (name === 'integrations') integrationsSwitch('overview');
      return r;
    };
  }

  // Placeholder renderers — later tasks replace each body.
  async function renderOverview() {}
  async function renderCache() {}
  async function renderSiem() {}
  async function renderDlq() {}

  // Expose for later tasks.
  window._integrations = {
    renderOverview: function () { return renderOverview(); },
    renderCache: function () { return renderCache(); },
    renderSiem: function () { return renderSiem(); },
    renderDlq: function () { return renderDlq(); },
    setRender: function (name, fn) {
      if (name === 'overview') renderOverview = fn;
      else if (name === 'cache') renderCache = fn;
      else if (name === 'siem') renderSiem = fn;
      else if (name === 'dlq') renderDlq = fn;
    },
  };
})();
```

- [ ] **Step 4: Add initial i18n keys to both JSON files**

In `src/i18n_en.json` and `src/i18n_zh_TW.json`, add:

```
gui_tab_integrations   → "Integrations" / "整合"
gui_it_overview        → "Overview" / "總覽"
gui_it_cache           → "Cache" / "快取"
gui_it_siem            → "SIEM" / "SIEM"
gui_it_dlq             → "DLQ" / "DLQ"
gui_it_loading         → "Loading..." / "載入中..."
```

- [ ] **Step 5: i18n audit + manual smoke**

Run: `python3 scripts/audit_i18n_usage.py`
Run: `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v`
Manual: `python3 illumio_ops.py --gui`, click Integrations tab, click each sub-tab; no JS console errors; panes toggle visibility.

- [ ] **Step 6: Commit**

```bash
git add src/templates/index.html src/static/js/integrations.js \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): Integrations tab shell with 4 sub-tabs and switcher"
```

---

## Task 15: Cache sub-tab — status card + core settings form

**Files:**
- Modify: `src/static/js/integrations.js` (install `renderCache`)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

**Reference spec §6.4 for the full layout.** All dynamic values must pass through `escapeAttr()`.

- [ ] **Step 1: Add i18n keys**

Add to both JSON files (EN / zh-TW):
```
gui_cache_status              "Cache Status" / "快取狀態"
gui_cache_enabled             "Enabled" / "啟用"
gui_cache_db_path             "DB path" / "資料庫路徑"
gui_cache_events_lag          "Events lag (s)" / "事件延遲（秒）"
gui_cache_traffic_lag         "Traffic lag (s)" / "流量延遲（秒）"
gui_cache_last_events         "Last events ingest" / "最後事件寫入"
gui_cache_last_traffic        "Last traffic ingest" / "最後流量寫入"
gui_cache_settings            "Settings" / "設定"
gui_cache_sec_basic           "Basic" / "基本"
gui_cache_sec_retention       "Retention (days)" / "保留（天）"
gui_cache_sec_polling         "Polling (seconds)" / "輪詢（秒）"
gui_cache_sec_throughput      "Throughput" / "吞吐量"
gui_backfill                  "Backfill" / "回填"
gui_retention_now             "Retention now" / "立即執行保留"
gui_save                      "Save" / "儲存"
```

- [ ] **Step 2: Implement `renderCache`**

Inside `src/static/js/integrations.js`, replace the placeholder. The function fetches `/api/cache/settings` + `/api/cache/status`, builds HTML via a template literal, and wires the Save button. **All user-derived strings go through `escapeAttr()`** (db_path, timestamps). Numeric values are cast via `Number()`.

Core logic:

```javascript
window._integrations.setRender('cache', async function renderCache() {
  const el = document.getElementById('it-pane-cache');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  const [stRes, cfgRes] = await Promise.all([
    fetch('/api/cache/status'), fetch('/api/cache/settings')
  ]);
  const status = await stRes.json();
  const s = await cfgRes.json();

  // Build sections in parts. Each part uses escapeAttr() for dynamic strings.
  const header = buildCacheStatusCards(status, s);
  const form = buildCacheForm(s);
  el.innerHTML = header + form + '<div id="cache-banner" style="display:none;margin-top:12px;"></div>';
  el.dataset.settings = JSON.stringify(s);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function buildCacheStatusCards(status, s) {
  const dbPath = escapeAttr(s.db_path);
  const evLag = status.events_lag_sec == null ? '—' : Number(status.events_lag_sec);
  const trLag = status.traffic_lag_sec == null ? '—' : Number(status.traffic_lag_sec);
  const lastEv = escapeAttr(status.last_event_ingested_at || '—');
  return `
    <div class="cards" style="margin-bottom:16px;">
      <div class="card"><div class="label" data-i18n="gui_cache_enabled">Enabled</div>
        <div class="value">${s.enabled ? '✓' : '—'}</div></div>
      <div class="card"><div class="label" data-i18n="gui_cache_events_lag">Events lag (s)</div>
        <div class="value">${evLag}</div></div>
      <div class="card"><div class="label" data-i18n="gui_cache_traffic_lag">Traffic lag (s)</div>
        <div class="value">${trLag}</div></div>
      <div class="card"><div class="label" data-i18n="gui_cache_last_events">Last events ingest</div>
        <div class="value" style="font-size:.8rem;">${lastEv}</div></div>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:16px;">
      <button class="btn" onclick="cacheBackfill()" data-i18n="gui_backfill">Backfill</button>
      <button class="btn" onclick="cacheRetentionNow()" data-i18n="gui_retention_now">Retention now</button>
    </div>`;
}

function buildCacheForm(s) {
  // All fields are typed (number/bool); no free-text interpolation except db_path.
  const dbPath = escapeAttr(s.db_path);
  return `
    <form id="cache-form" class="rs-glass">
      <h3 data-i18n="gui_cache_sec_basic">Basic</h3>
      <label><input type="checkbox" name="enabled" ${s.enabled ? 'checked' : ''}>
        <span data-i18n="gui_cache_enabled">Enabled</span></label>
      <div><label><span data-i18n="gui_cache_db_path">DB path</span>:
        <input name="db_path" value="${dbPath}"></label></div>

      <h3 data-i18n="gui_cache_sec_retention">Retention (days)</h3>
      <div><label>events_retention_days:
        <input type="number" name="events_retention_days" min="1" value="${Number(s.events_retention_days)}"></label></div>
      <div><label>traffic_raw_retention_days:
        <input type="number" name="traffic_raw_retention_days" min="1" value="${Number(s.traffic_raw_retention_days)}"></label></div>
      <div><label>traffic_agg_retention_days:
        <input type="number" name="traffic_agg_retention_days" min="1" value="${Number(s.traffic_agg_retention_days)}"></label></div>

      <h3 data-i18n="gui_cache_sec_polling">Polling (seconds)</h3>
      <div><label>events_poll_interval_seconds:
        <input type="number" name="events_poll_interval_seconds" min="30" value="${Number(s.events_poll_interval_seconds)}"></label></div>
      <div><label>traffic_poll_interval_seconds:
        <input type="number" name="traffic_poll_interval_seconds" min="60" value="${Number(s.traffic_poll_interval_seconds)}"></label></div>

      <h3 data-i18n="gui_cache_sec_throughput">Throughput</h3>
      <div><label>rate_limit_per_minute:
        <input type="number" name="rate_limit_per_minute" min="10" max="500" value="${Number(s.rate_limit_per_minute)}"></label></div>
      <div><label>async_threshold_events:
        <input type="number" name="async_threshold_events" min="1" max="10000" value="${Number(s.async_threshold_events)}"></label></div>

      <div id="cache-form-extra"></div>
      <div style="text-align:right;margin-top:12px;">
        <button type="button" class="btn btn-primary" onclick="cacheSave()" data-i18n="gui_save">Save</button>
      </div>
    </form>`;
}

async function cacheSave() {
  const form = document.getElementById('cache-form');
  const data = Object.fromEntries(new FormData(form));
  const existing = JSON.parse(document.getElementById('it-pane-cache').dataset.settings);
  const payload = Object.assign({}, existing, {
    enabled: form.elements['enabled'].checked,
    db_path: data.db_path,
    events_retention_days: Number(data.events_retention_days),
    traffic_raw_retention_days: Number(data.traffic_raw_retention_days),
    traffic_agg_retention_days: Number(data.traffic_agg_retention_days),
    events_poll_interval_seconds: Number(data.events_poll_interval_seconds),
    traffic_poll_interval_seconds: Number(data.traffic_poll_interval_seconds),
    rate_limit_per_minute: Number(data.rate_limit_per_minute),
    async_threshold_events: Number(data.async_threshold_events),
    traffic_filter: (typeof window.collectTrafficFilter === 'function')
        ? window.collectTrafficFilter() : existing.traffic_filter,
    traffic_sampling: (typeof window.collectTrafficSampling === 'function')
        ? window.collectTrafficSampling() : existing.traffic_sampling,
  });
  const resp = await fetch('/api/cache/settings', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const body = await resp.json();
  const banner = document.getElementById('cache-banner');
  if (body.ok) {
    showRestartBanner(banner);
  } else {
    banner.style.display = 'block';
    // Build error list via DOM methods to avoid injecting server-provided strings as HTML.
    banner.textContent = 'Validation error:';
    const ul = document.createElement('ul');
    Object.entries(body.errors || {}).forEach(([k, v]) => {
      const li = document.createElement('li');
      li.textContent = k + ': ' + v;
      ul.appendChild(li);
    });
    banner.appendChild(ul);
  }
}

// Placeholders — real implementation in Task 24.
function showRestartBanner(target) {
  target.style.display = 'block';
  target.textContent = 'Settings saved. Restart monitor to apply scheduling changes.';
}

async function cacheBackfill() {
  const start = prompt('Start date (YYYY-MM-DD)');
  const end = prompt('End date (YYYY-MM-DD)');
  if (!start || !end) return;
  await fetch('/api/cache/backfill', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({start, end}),
  });
  alert('Backfill submitted');
}

async function cacheRetentionNow() {
  alert('Run "Retention now" via CLI; HTTP trigger not yet implemented.');
}
```

- [ ] **Step 3: i18n audit + manual smoke**

Run: `python3 scripts/audit_i18n_usage.py`
Run: `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v`
Manual: open Integrations → Cache. Cards render, form populated, Save with invalid IP → error list (text-only). Save with valid values → banner.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): Cache sub-tab status cards and core settings form"
```

---

## Task 16: Cache sub-tab — `traffic_filter` field UI

**Files:**
- Modify: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add i18n keys**

```
gui_cache_sec_traffic_filter   "Traffic Filter" / "流量過濾"
gui_cache_tf_actions           "Actions" / "動作"
gui_cache_tf_workload_env      "Workload label env" / "工作負載環境標籤"
gui_cache_tf_ports             "Ports" / "埠"
gui_cache_tf_protocols         "Protocols" / "協定"
gui_cache_tf_exclude_ips       "Exclude src IPs" / "排除來源 IP"
gui_err_invalid_ip             "Invalid IP address" / "無效 IP 位址"
gui_err_port_range             "Port must be 1-65535" / "埠須為 1-65535"
```

- [ ] **Step 2: Append Traffic Filter section after form loads**

Inside the `renderCache` callback (or as a subsequent call after it populates), append to `#cache-form-extra`. All existing list values from `s.traffic_filter.*` come from backend (already pydantic-validated), but still escape before injecting:

```javascript
function renderTrafficFilter(s) {
  const tf = s.traffic_filter || {};
  const actions = ['blocked', 'potentially_blocked', 'allowed'];
  const protocols = ['TCP', 'UDP', 'ICMP'];
  const envVals = (tf.workload_label_env || []).map(escapeAttr).join(',');
  const portVals = (tf.ports || []).map(Number).join(',');
  const ipVals = (tf.exclude_src_ips || []).map(escapeAttr).join(',');

  const html =
    `<h3 data-i18n="gui_cache_sec_traffic_filter">Traffic Filter</h3>
     <div><span data-i18n="gui_cache_tf_actions">Actions</span>: ` +
    actions.map(a => `<label><input type="checkbox" name="tf-action" value="${a}"${(tf.actions || []).includes(a) ? ' checked' : ''}> ${a}</label>`).join(' ') +
    `</div>
     <div><span data-i18n="gui_cache_tf_protocols">Protocols</span>: ` +
    protocols.map(p => `<label><input type="checkbox" name="tf-protocol" value="${p}"${(tf.protocols || []).includes(p) ? ' checked' : ''}> ${p}</label>`).join(' ') +
    `</div>
     <div><label><span data-i18n="gui_cache_tf_workload_env">Workload label env</span>:
        <input id="tf-env" value="${envVals}"></label></div>
     <div><label><span data-i18n="gui_cache_tf_ports">Ports</span>:
        <input id="tf-ports" value="${portVals}" placeholder="22,443,..."></label></div>
     <div><label><span data-i18n="gui_cache_tf_exclude_ips">Exclude src IPs</span>:
        <input id="tf-ips" value="${ipVals}" placeholder="10.0.0.1,..."></label></div>
     <div id="tf-validation-hints" style="color:var(--danger);font-size:.8rem;"></div>`;

  document.getElementById('cache-form-extra').innerHTML = html;
}

window.collectTrafficFilter = function () {
  const pick = sel => Array.from(document.querySelectorAll(sel)).map(el => el.value);
  const parse = (id) => (document.getElementById(id)?.value || '')
    .split(',').map(x => x.trim()).filter(Boolean);
  return {
    actions: pick('input[name="tf-action"]:checked'),
    workload_label_env: parse('tf-env'),
    ports: parse('tf-ports').map(Number).filter(n => Number.isFinite(n)),
    protocols: pick('input[name="tf-protocol"]:checked'),
    exclude_src_ips: parse('tf-ips'),
  };
};

function validateIp(s) {
  return /^((\d{1,3}\.){3}\d{1,3}|[\da-fA-F:]+)$/.test(s);
}

function validateTrafficFilterHints() {
  const hints = [];
  const ips = (document.getElementById('tf-ips')?.value || '').split(',').map(s => s.trim()).filter(Boolean);
  ips.forEach(ip => { if (!validateIp(ip)) hints.push('Invalid IP: ' + ip); });
  const ports = (document.getElementById('tf-ports')?.value || '').split(',').map(s => s.trim()).filter(Boolean);
  ports.forEach(p => {
    const n = Number(p);
    if (!Number.isInteger(n) || n < 1 || n > 65535) hints.push('Invalid port: ' + p);
  });
  const el = document.getElementById('tf-validation-hints');
  if (el) el.textContent = hints.join(' · ');
}

document.addEventListener('input', e => {
  if (e.target && ['tf-ips', 'tf-ports'].includes(e.target.id)) validateTrafficFilterHints();
});
```

Call `renderTrafficFilter(s)` inside the renderCache after `el.dataset.settings = JSON.stringify(s)`.

- [ ] **Step 3: i18n audit + manual smoke**

Load Cache tab: checkbox groups reflect saved actions/protocols; comma lists populate envs/ports/IPs; typing an invalid IP shows red hint. Save → persists.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): Cache traffic_filter full-field UI with client hints"
```

---

## Task 17: Cache sub-tab — `traffic_sampling`

**Files:**
- Modify: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add i18n keys**

```
gui_cache_sec_traffic_sampling   "Traffic Sampling" / "流量抽樣"
gui_cache_ts_ratio               "sample_ratio_allowed" / "sample_ratio_allowed"
gui_cache_ts_max_rows            "max_rows_per_batch" / "max_rows_per_batch"
```

- [ ] **Step 2: Append sampling section after the filter**

In `renderTrafficFilter(s)` (or a follow-up call):

```javascript
function renderTrafficSampling(s) {
  const ts = s.traffic_sampling || {};
  const ratio = Number(ts.sample_ratio_allowed || 1);
  const maxRows = Number(ts.max_rows_per_batch || 200000);
  const html =
    `<h3 data-i18n="gui_cache_sec_traffic_sampling">Traffic Sampling</h3>
     <div><label>sample_ratio_allowed (>=1):
       <input type="number" id="ts-ratio" min="1" value="${ratio}"></label></div>
     <div><label>max_rows_per_batch (1-200000):
       <input type="number" id="ts-max" min="1" max="200000" value="${maxRows}"></label></div>`;
  document.getElementById('cache-form-extra').insertAdjacentHTML('beforeend', html);
}

window.collectTrafficSampling = function () {
  return {
    sample_ratio_allowed: Number(document.getElementById('ts-ratio')?.value || 1),
    max_rows_per_batch: Number(document.getElementById('ts-max')?.value || 200000),
  };
};
```

Call `renderTrafficSampling(s)` in `renderCache` after `renderTrafficFilter(s)`.

- [ ] **Step 3: i18n audit + manual smoke**

Run: `python3 scripts/audit_i18n_usage.py`. Load Cache; sampling fields show; change, Save, reload → persists.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): Cache traffic_sampling section"
```

---

## Task 18: SIEM sub-tab — forwarder form + destinations table

**Files:**
- Modify: `src/static/js/integrations.js` (install `renderSiem`)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_siem_forwarder        "Forwarder" / "轉發器"
gui_siem_enabled          "Enabled" / "啟用"
gui_siem_dispatch_tick    "dispatch_tick_seconds" / "dispatch_tick_seconds"
gui_siem_dlq_max          "dlq_max_per_dest" / "dlq_max_per_dest"
gui_siem_destinations     "Destinations" / "目的地"
gui_siem_add              "Add Destination" / "新增目的地"
gui_siem_th_name          "Name" / "名稱"
gui_siem_th_transport     "Transport" / "傳輸"
gui_siem_th_format        "Format" / "格式"
gui_siem_th_endpoint      "Endpoint" / "端點"
gui_siem_th_status        "Status" / "狀態"
gui_siem_th_actions       "Actions" / "操作"
gui_siem_test             "Test" / "測試"
gui_siem_edit             "Edit" / "編輯"
gui_siem_delete           "Delete" / "刪除"
gui_confirm_delete        "Delete this destination?" / "刪除此目的地？"
```

- [ ] **Step 2: Install `renderSiem`**

```javascript
window._integrations.setRender('siem', async function renderSiem() {
  const el = document.getElementById('it-pane-siem');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  const [fw, destsBody, status] = await Promise.all([
    fetch('/api/siem/forwarder').then(r => r.json()),
    fetch('/api/siem/destinations').then(r => r.json()),
    fetch('/api/siem/status').then(r => r.json()),
  ]);
  const dests = destsBody.destinations || destsBody || [];

  el.innerHTML = buildSiemForwarderForm(fw) + buildSiemDestinationsSection();

  const tbody = document.getElementById('siem-dest-tbody');
  const perDest = (status.per_destination) || {};
  tbody.innerHTML = dests.map(d => buildSiemRow(d, perDest[d.name] || {})).join('') ||
    '<tr><td colspan="6" style="color:var(--dim);">(none)</td></tr>';
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function buildSiemForwarderForm(fw) {
  return `
    <section class="rs-glass" style="margin-bottom:16px;">
      <h3 data-i18n="gui_siem_forwarder">Forwarder</h3>
      <label><input type="checkbox" id="siem-enabled" ${fw.enabled ? 'checked' : ''}>
        <span data-i18n="gui_siem_enabled">Enabled</span></label>
      <div><label data-i18n="gui_siem_dispatch_tick">dispatch_tick_seconds</label>:
        <input type="number" id="siem-tick" min="1" value="${Number(fw.dispatch_tick_seconds)}"></div>
      <div><label data-i18n="gui_siem_dlq_max">dlq_max_per_dest</label>:
        <input type="number" id="siem-dlq-max" min="100" value="${Number(fw.dlq_max_per_dest)}"></div>
      <button class="btn btn-primary" onclick="siemSaveForwarder()" data-i18n="gui_save">Save</button>
    </section>`;
}

function buildSiemDestinationsSection() {
  return `
    <section class="rs-glass">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3 data-i18n="gui_siem_destinations">Destinations</h3>
        <button class="btn" onclick="siemOpenDestModal()" data-i18n="gui_siem_add">+ Add</button>
      </div>
      <table style="width:100%;font-size:.85rem;">
        <thead><tr>
          <th data-i18n="gui_siem_th_name">Name</th>
          <th data-i18n="gui_siem_th_transport">Transport</th>
          <th data-i18n="gui_siem_th_format">Format</th>
          <th data-i18n="gui_siem_th_endpoint">Endpoint</th>
          <th data-i18n="gui_siem_th_status">Status</th>
          <th data-i18n="gui_siem_th_actions">Actions</th>
        </tr></thead>
        <tbody id="siem-dest-tbody"></tbody>
      </table>
    </section>
    <div id="siem-banner" style="margin-top:12px;"></div>
    <div id="siem-modal-host"></div>`;
}

function buildSiemRow(d, st) {
  const dot = st.failed > 0 ? '🔴' : (st.pending > 0 ? '🟡' : '🟢');
  const nameEnc = encodeURIComponent(d.name);
  const dim = d.enabled ? '' : ' <span style="color:var(--dim);">(disabled)</span>';
  // All string values are escaped before interpolating into the row.
  return `<tr>
    <td>${escapeAttr(d.name)}${dim}</td>
    <td>${escapeAttr(d.transport)}</td>
    <td>${escapeAttr(d.format)}</td>
    <td>${escapeAttr(d.endpoint)}</td>
    <td>${dot}</td>
    <td>
      <button class="btn" onclick="siemTestDest('${nameEnc}')" data-i18n="gui_siem_test">Test</button>
      <button class="btn" onclick="siemOpenDestModal('${nameEnc}')" data-i18n="gui_siem_edit">Edit</button>
      <button class="btn btn-danger" onclick="siemDeleteDest('${nameEnc}')" data-i18n="gui_siem_delete">Delete</button>
    </td>
  </tr>`;
}

async function siemSaveForwarder() {
  const payload = {
    enabled: document.getElementById('siem-enabled').checked,
    dispatch_tick_seconds: Number(document.getElementById('siem-tick').value),
    dlq_max_per_dest: Number(document.getElementById('siem-dlq-max').value),
  };
  const resp = await fetch('/api/siem/forwarder', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const body = await resp.json();
  const banner = document.getElementById('siem-banner');
  if (body.ok) showRestartBanner(banner);
  else {
    banner.textContent = 'Validation error: ' + JSON.stringify(body.errors || body.error);
  }
}

async function siemDeleteDest(nameEnc) {
  const name = decodeURIComponent(nameEnc);
  if (!confirm(window.t ? window.t('gui_confirm_delete') : 'Delete this destination?')) return;
  await fetch('/api/siem/destinations/' + encodeURIComponent(name), {method: 'DELETE'});
  window._integrations.renderSiem();
}
```

- [ ] **Step 3: i18n audit + manual smoke**

Load Integrations → SIEM. Form with saved values; destinations table lists existing. Status dot reflects `/api/siem/status`.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): SIEM sub-tab forwarder form and destinations table"
```

---

## Task 19: SIEM destination Modal (CRUD + conditional TLS/HEC)

**Files:**
- Modify: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_siem_modal_title_add    "Add destination" / "新增目的地"
gui_siem_modal_title_edit   "Edit destination" / "編輯目的地"
gui_siem_sec_basic          "Basic" / "基本"
gui_siem_sec_transport      "Transport" / "傳輸"
gui_siem_sec_tls            "TLS" / "TLS"
gui_siem_sec_hec            "HEC" / "HEC"
gui_siem_sec_batch          "Batch" / "批次"
gui_cancel                  "Cancel" / "取消"
gui_siem_test_inline        "Test Connection" / "測試連線"
```

- [ ] **Step 2: Implement modal open / save / close**

```javascript
async function siemOpenDestModal(nameEnc) {
  const name = nameEnc ? decodeURIComponent(nameEnc) : null;
  let dest = {name: '', enabled: true, transport: 'udp', format: 'cef',
              endpoint: '', tls_verify: true, tls_ca_bundle: '', hec_token: '',
              batch_size: 100, source_types: ['audit', 'traffic'], max_retries: 10};
  if (name) {
    const body = await fetch('/api/siem/destinations').then(r => r.json());
    const all = body.destinations || body || [];
    dest = Object.assign(dest, all.find(d => d.name === name) || {});
  }
  document.getElementById('siem-modal-host').innerHTML = buildDestModal(dest, name);
  siemToggleCondFields();
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

function buildDestModal(dest, editName) {
  const nameVal = escapeAttr(dest.name);
  const endpoint = escapeAttr(dest.endpoint);
  const caBundle = escapeAttr(dest.tls_ca_bundle || '');
  const hecToken = escapeAttr(dest.hec_token || '');
  const readonly = editName ? ' readonly' : '';
  const editAttr = editName ? escapeAttr(editName) : '';
  const titleKey = editName ? 'gui_siem_modal_title_edit' : 'gui_siem_modal_title_add';
  const options = (list, cur) => list.map(v =>
    `<option${v === cur ? ' selected' : ''}>${v}</option>`).join('');
  return `
    <div class="modal-backdrop" onclick="siemCloseModal(event)">
      <div class="modal" onclick="event.stopPropagation()">
        <h2 data-i18n="${titleKey}">${editName ? 'Edit' : 'Add'} destination</h2>

        <h3 data-i18n="gui_siem_sec_basic">Basic</h3>
        <label>name: <input id="md-name" value="${nameVal}"${readonly}></label>
        <label><input type="checkbox" id="md-enabled" ${dest.enabled ? 'checked' : ''}>
          <span data-i18n="gui_siem_enabled">Enabled</span></label>
        <div>source_types:
          <label><input type="checkbox" name="md-st" value="audit"${(dest.source_types || []).includes('audit') ? ' checked' : ''}> audit</label>
          <label><input type="checkbox" name="md-st" value="traffic"${(dest.source_types || []).includes('traffic') ? ' checked' : ''}> traffic</label>
        </div>

        <h3 data-i18n="gui_siem_sec_transport">Transport</h3>
        <label>transport:
          <select id="md-transport" onchange="siemToggleCondFields()">${options(['udp','tcp','tls','hec'], dest.transport)}</select></label>
        <label>format:
          <select id="md-format">${options(['cef','json','syslog_cef','syslog_json'], dest.format)}</select></label>
        <label>endpoint: <input id="md-endpoint" value="${endpoint}"></label>

        <div id="md-tls-section">
          <h3 data-i18n="gui_siem_sec_tls">TLS</h3>
          <label><input type="checkbox" id="md-tls-verify" ${dest.tls_verify ? 'checked' : ''}> tls_verify</label>
          <label>tls_ca_bundle: <input id="md-tls-ca" value="${caBundle}"></label>
        </div>

        <div id="md-hec-section">
          <h3 data-i18n="gui_siem_sec_hec">HEC</h3>
          <label>hec_token: <input type="password" id="md-hec-token" value="${hecToken}"></label>
        </div>

        <h3 data-i18n="gui_siem_sec_batch">Batch</h3>
        <label>batch_size (1-10000): <input type="number" id="md-batch" min="1" max="10000" value="${Number(dest.batch_size)}"></label>
        <label>max_retries (>=0): <input type="number" id="md-retries" min="0" value="${Number(dest.max_retries)}"></label>

        <div id="md-banner" style="margin-top:10px;color:var(--danger);"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
          <button class="btn" onclick="siemCloseModal()" data-i18n="gui_cancel">Cancel</button>
          <button class="btn" onclick="siemTestDestInline()" data-i18n="gui_siem_test_inline">Test Connection</button>
          <button class="btn btn-primary" onclick="siemSaveDest('${editAttr}')" data-i18n="gui_save">Save</button>
        </div>
      </div>
    </div>`;
}

function siemToggleCondFields() {
  const t = document.getElementById('md-transport').value;
  document.getElementById('md-tls-section').style.display =
    (t === 'tls' || t === 'hec') ? '' : 'none';
  document.getElementById('md-hec-section').style.display =
    (t === 'hec') ? '' : 'none';
}

function siemCloseModal() {
  document.getElementById('siem-modal-host').innerHTML = '';
}

async function siemSaveDest(editName) {
  const sourceTypes = Array.from(document.querySelectorAll('input[name="md-st"]:checked'))
    .map(el => el.value);
  const payload = {
    name: editName || document.getElementById('md-name').value.trim(),
    enabled: document.getElementById('md-enabled').checked,
    transport: document.getElementById('md-transport').value,
    format: document.getElementById('md-format').value,
    endpoint: document.getElementById('md-endpoint').value.trim(),
    tls_verify: document.getElementById('md-tls-verify').checked,
    tls_ca_bundle: document.getElementById('md-tls-ca').value.trim() || null,
    hec_token: document.getElementById('md-hec-token').value || null,
    batch_size: Number(document.getElementById('md-batch').value),
    max_retries: Number(document.getElementById('md-retries').value),
    source_types: sourceTypes.length ? sourceTypes : ['audit', 'traffic'],
  };
  let resp;
  if (editName) {
    resp = await fetch('/api/siem/destinations/' + encodeURIComponent(editName), {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
  } else {
    resp = await fetch('/api/siem/destinations', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
  }
  const body = await resp.json();
  if (resp.ok && body.ok !== false) {
    siemCloseModal();
    window._integrations.renderSiem();
    showRestartBanner(document.getElementById('siem-banner'));
  } else {
    document.getElementById('md-banner').textContent =
      'Save failed: ' + (body.error || JSON.stringify(body.errors || body));
  }
}
```

- [ ] **Step 3: i18n audit + manual smoke**

Cycle transport (udp→tcp→tls→hec); TLS shows for tls/hec, HEC only for hec. Add/Edit/Delete work and persist.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): SIEM destination modal with conditional TLS/HEC sections"
```

---

## Task 20: SIEM Test Connection (row button + inline modal button)

**Files:**
- Modify: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_siem_test_ok       "Test succeeded" / "測試成功"
gui_siem_test_fail     "Test failed" / "測試失敗"
gui_siem_test_latency  "latency" / "延遲"
```

- [ ] **Step 2: Implement test functions**

```javascript
async function siemTestDest(nameEnc) {
  const name = decodeURIComponent(nameEnc);
  const resp = await fetch('/api/siem/destinations/' + encodeURIComponent(name) + '/test',
                           {method: 'POST'});
  const body = await resp.json();
  const msg = body.ok
    ? '✓ Test succeeded (' + body.latency_ms + ' ms)'
    : '✗ Test failed: ' + body.error;
  alert(msg);
}

async function siemTestDestInline() {
  const banner = document.getElementById('md-banner');
  banner.textContent = 'Testing…';
  const name = document.getElementById('md-name').value.trim();
  if (!name) { banner.textContent = 'Enter name, then Save, then Test.'; return; }
  const resp = await fetch('/api/siem/destinations/' + encodeURIComponent(name) + '/test',
                           {method: 'POST'});
  const body = await resp.json();
  if (resp.status === 404) {
    banner.textContent = 'Destination not yet saved. Save first, then Test.';
  } else if (body.ok) {
    banner.style.color = 'var(--ok, green)';
    banner.textContent = '✓ OK (' + body.latency_ms + ' ms)';
  } else {
    banner.style.color = 'var(--danger)';
    banner.textContent = '✗ ' + body.error;
  }
}
```

Note: `siemTestDestInline` requires the destination to be saved first (by design — the test endpoint operates on persisted destinations). Users who need to test ad-hoc should save with a placeholder name first.

- [ ] **Step 3: Manual smoke**

Point a new destination at a closed port → Test fails. Start `nc -u -l 5514`, retarget → Test succeeds with latency.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): SIEM Test Connection row and inline buttons"
```

---

## Task 21: DLQ sub-tab — list + filters + pagination

**Files:**
- Modify: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_dlq_title            "Dead Letter Queue" / "失敗佇列"
gui_dlq_filter_dest      "Destination" / "目的地"
gui_dlq_filter_reason    "Reason contains" / "原因包含"
gui_dlq_filter_all       "All" / "全部"
gui_dlq_search           "Search" / "搜尋"
gui_dlq_th_dest          "Dest" / "目的地"
gui_dlq_th_event_id      "Event ID" / "事件 ID"
gui_dlq_th_reason        "Reason" / "原因"
gui_dlq_th_failed_at     "Failed At" / "失敗時間"
gui_dlq_view             "View" / "檢視"
gui_dlq_replay           "Replay" / "重送"
gui_dlq_empty            "(no DLQ entries)" / "(無項目)"
```

- [ ] **Step 2: Install `renderDlq`**

```javascript
let _dlqPage = 1;
const DLQ_PAGE_SIZE = 50;

window._integrations.setRender('dlq', async function renderDlq() {
  const el = document.getElementById('it-pane-dlq');
  if (!el) return;
  el.innerHTML = buildDlqSkeleton();
  await populateDlqDestinations();
  await dlqSearch();
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function buildDlqSkeleton() {
  return `
    <h3 data-i18n="gui_dlq_title">Dead Letter Queue</h3>
    <div style="display:flex;gap:10px;margin-bottom:10px;align-items:end;flex-wrap:wrap;">
      <label><span data-i18n="gui_dlq_filter_dest">Destination</span>:
        <select id="dlq-dest"><option value="" data-i18n="gui_dlq_filter_all">All</option></select></label>
      <label><span data-i18n="gui_dlq_filter_reason">Reason contains</span>:
        <input id="dlq-reason"></label>
      <button class="btn" onclick="dlqSearch()" data-i18n="gui_dlq_search">Search</button>
    </div>
    <div id="dlq-bulk-bar"></div>
    <table style="width:100%;font-size:.85rem;">
      <thead><tr><th></th>
        <th data-i18n="gui_dlq_th_dest">Dest</th>
        <th data-i18n="gui_dlq_th_event_id">Event ID</th>
        <th data-i18n="gui_dlq_th_reason">Reason</th>
        <th data-i18n="gui_dlq_th_failed_at">Failed At</th>
        <th></th>
      </tr></thead>
      <tbody id="dlq-tbody"></tbody>
    </table>
    <div id="dlq-pager" style="margin-top:8px;"></div>
    <div id="dlq-modal-host"></div>`;
}

async function populateDlqDestinations() {
  const body = await fetch('/api/siem/destinations').then(r => r.json());
  const dests = body.destinations || body || [];
  const sel = document.getElementById('dlq-dest');
  dests.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.name;
    opt.textContent = d.name;
    sel.appendChild(opt);
  });
}

async function dlqSearch() {
  _dlqPage = 1;
  await _dlqLoadPage();
}

async function _dlqLoadPage() {
  const dest = document.getElementById('dlq-dest').value;
  const reason = document.getElementById('dlq-reason').value.trim();
  const q = new URLSearchParams();
  if (dest) q.set('destination', dest);
  if (reason) q.set('reason', reason);
  q.set('limit', String(DLQ_PAGE_SIZE));
  q.set('offset', String((_dlqPage - 1) * DLQ_PAGE_SIZE));
  const body = await fetch('/api/siem/dlq?' + q.toString()).then(r => r.json());
  const entries = body.entries || body || [];
  const tbody = document.getElementById('dlq-tbody');
  tbody.innerHTML = entries.map(buildDlqRow).join('') ||
    '<tr><td colspan="6" style="color:var(--dim);" data-i18n="gui_dlq_empty">(no DLQ entries)</td></tr>';
  document.getElementById('dlq-pager').innerHTML =
    'Page ' + _dlqPage + ' · ' +
    '<button class="btn" onclick="_dlqPage=Math.max(1,_dlqPage-1);_dlqLoadPage()">‹</button>' +
    ' <button class="btn" onclick="_dlqPage++;_dlqLoadPage()">›</button>';
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

function buildDlqRow(e) {
  const id = Number(e.id);  // numeric coercion
  return `<tr>
    <td><input type="checkbox" class="dlq-chk" value="${id}"></td>
    <td>${escapeAttr(e.destination)}</td>
    <td>${escapeAttr(e.event_id)}</td>
    <td>${escapeAttr(e.reason)}</td>
    <td>${escapeAttr(e.failed_at)}</td>
    <td>
      <button class="btn" onclick="dlqView(${id})" data-i18n="gui_dlq_view">View</button>
      <button class="btn" onclick="dlqReplay([${id}])" data-i18n="gui_dlq_replay">Replay</button>
    </td>
  </tr>`;
}
```

- [ ] **Step 3: Manual smoke**

Insert a row via CLI or `sqlite3 $DB "INSERT INTO dead_letters ..."`. Load DLQ tab; row appears. Filter by destination → only matching rows.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): DLQ list with filters and pagination"
```

---

## Task 22: DLQ — bulk actions + CSV export + View modal

**Files:**
- Modify: `src/static/js/integrations.js`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_dlq_select_all         "Select All" / "全選"
gui_dlq_replay_selected    "Replay Selected" / "重送所選"
gui_dlq_purge_selected     "Purge Selected" / "清除所選"
gui_dlq_purge_all          "Purge ALL for destination" / "清除目的地全部"
gui_dlq_export             "Export CSV" / "匯出 CSV"
gui_dlq_modal_title        "DLQ entry detail" / "失敗項目詳情"
gui_dlq_confirm_purge_all  "Type the destination name to confirm Purge ALL" / "輸入目的地名稱確認清除全部"
gui_close                  "Close" / "關閉"
```

- [ ] **Step 2: Populate bulk bar + action handlers**

Append to `renderDlq`, after `buildDlqSkeleton()`, inject the bulk bar:

```javascript
// Inject bulk bar into #dlq-bulk-bar slot (static markup, safe):
document.getElementById('dlq-bulk-bar').innerHTML = `
  <div style="display:flex;gap:8px;margin-bottom:8px;">
    <button class="btn" onclick="dlqSelectAll()" data-i18n="gui_dlq_select_all">Select All</button>
    <button class="btn" onclick="dlqReplaySelected()" data-i18n="gui_dlq_replay_selected">Replay Selected</button>
    <button class="btn btn-warn" onclick="dlqPurgeSelected()" data-i18n="gui_dlq_purge_selected">Purge Selected</button>
    <button class="btn btn-danger" onclick="dlqPurgeAll()" data-i18n="gui_dlq_purge_all">Purge ALL</button>
    <button class="btn" onclick="dlqExport()" data-i18n="gui_dlq_export">Export CSV</button>
  </div>`;
```

Action functions:

```javascript
function dlqSelectAll() {
  document.querySelectorAll('.dlq-chk').forEach(c => { c.checked = true; });
}
function _dlqSelectedIds() {
  return Array.from(document.querySelectorAll('.dlq-chk:checked')).map(c => Number(c.value));
}
async function dlqReplaySelected() {
  const ids = _dlqSelectedIds();
  if (!ids.length) return;
  await dlqReplay(ids);
}
async function dlqReplay(ids) {
  await fetch('/api/siem/dlq/replay', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids}),
  });
  dlqSearch();
}
async function dlqPurgeSelected() {
  const ids = _dlqSelectedIds();
  if (!ids.length) return;
  if (!confirm('Purge ' + ids.length + ' entries?')) return;
  await fetch('/api/siem/dlq/purge', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids}),
  });
  dlqSearch();
}
async function dlqPurgeAll() {
  const dest = document.getElementById('dlq-dest').value;
  if (!dest) { alert('Pick a destination first.'); return; }
  const typed = prompt(window.t ? window.t('gui_dlq_confirm_purge_all')
                       : 'Type the destination name to confirm Purge ALL:', '');
  if (typed !== dest) return;
  await fetch('/api/siem/dlq/purge', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({destination: dest, all: true}),
  });
  dlqSearch();
}
function dlqExport() {
  const dest = document.getElementById('dlq-dest').value;
  const reason = document.getElementById('dlq-reason').value.trim();
  const q = new URLSearchParams();
  if (dest) q.set('destination', dest);
  if (reason) q.set('reason', reason);
  const a = document.createElement('a');
  a.href = '/api/siem/dlq/export?' + q.toString();
  a.download = 'dlq.csv';
  document.body.appendChild(a); a.click(); a.remove();
}

async function dlqView(id) {
  const body = await fetch('/api/siem/dlq?id=' + Number(id)).then(r => r.json());
  const entry = (body.entries || [])[0] || body;
  const host = document.getElementById('dlq-modal-host');
  // Build the modal via DOM methods (user payload may contain arbitrary chars).
  host.innerHTML = ''; // clear
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.addEventListener('click', () => { host.innerHTML = ''; });
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.addEventListener('click', e => e.stopPropagation());
  const title = document.createElement('h3');
  title.setAttribute('data-i18n', 'gui_dlq_modal_title');
  title.textContent = 'DLQ entry detail';
  modal.appendChild(title);
  [['Destination', entry.destination], ['Event ID', entry.event_id],
   ['Reason', entry.reason], ['Failed at', entry.failed_at]].forEach(([k, v]) => {
    const d = document.createElement('div');
    const b = document.createElement('b'); b.textContent = k;
    d.appendChild(b); d.append(': ' + (v || ''));
    modal.appendChild(d);
  });
  const pre = document.createElement('pre');
  pre.style.cssText = 'background:var(--bg3);padding:10px;overflow:auto;max-height:400px;';
  pre.textContent = entry.payload || '';
  modal.appendChild(pre);
  const row = document.createElement('div');
  row.style.textAlign = 'right';
  const btn = document.createElement('button');
  btn.className = 'btn';
  btn.setAttribute('data-i18n', 'gui_close');
  btn.textContent = 'Close';
  btn.addEventListener('click', () => { host.innerHTML = ''; });
  row.appendChild(btn);
  modal.appendChild(row);
  backdrop.appendChild(modal);
  host.appendChild(backdrop);
  if (typeof window.i18nApply === 'function') window.i18nApply();
}
```

> **Note:** `POST /api/siem/dlq/purge` payload shape depends on existing `src/siem/web.py::purge_dlq`. Open that handler and match the expected body. If only per-id purge is supported, implement Purge ALL client-side by first GET-ing all IDs for the destination, then POSTing them. Keep the typed-confirmation UX either way.

- [ ] **Step 3: Manual smoke**

- Select 1-2 rows, Replay Selected → they vanish after server replay.
- Purge Selected with confirm → gone.
- Export CSV → file downloads with filtered rows.
- View → modal shows payload; Close works.
- Purge ALL requires typing destination name.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): DLQ bulk replay/purge, CSV export, View modal"
```

---

## Task 23: Overview sub-tab — 4 status cards + recent events

**Files:**
- Modify: `src/static/js/integrations.js` (install `renderOverview`)
- Modify: `src/templates/index.html` (add card color CSS if missing)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_ov_cache_lag         "Cache Lag" / "快取延遲"
gui_ov_ingest_recency    "Ingest Recency" / "寫入近期"
gui_ov_siem_queue        "SIEM Queue" / "SIEM 佇列"
gui_ov_dlq_total         "DLQ Total" / "DLQ 總數"
gui_ov_recent_events     "Recent dispatch events" / "近期分派事件"
gui_ov_no_events         "(no recent events)" / "(無近期事件)"
```

- [ ] **Step 2: Install `renderOverview`**

```javascript
window._integrations.setRender('overview', async function renderOverview() {
  const el = document.getElementById('it-pane-overview');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';
  const [cache, siem] = await Promise.all([
    fetch('/api/cache/status').then(r => r.json()),
    fetch('/api/siem/status').then(r => r.json()),
  ]);

  const evLag = cache.events_lag_sec;
  const trLag = cache.traffic_lag_sec;
  const pending = Number(siem.total_pending || 0);
  const sent = Number(siem.total_sent || 0);
  const failed = Number(siem.total_failed || 0);
  const dlq = Number(siem.total_dlq || 0);

  const lagClass = (v, threshold) =>
    v == null ? 'card-neutral' :
    (v < threshold ? 'card-ok' :
      (v < 2 * threshold ? 'card-warn' : 'card-err'));
  const evClass = lagClass(evLag, 300);
  const siemClass = failed > 0 ? 'card-warn' : 'card-ok';
  const dlqClass = dlq > 0 ? 'card-warn' : 'card-ok';

  el.innerHTML = `
    <div class="cards">
      <div class="card ${evClass}">
        <div class="label" data-i18n="gui_ov_cache_lag">Cache Lag</div>
        <div class="value">events: ${evLag == null ? '—' : Number(evLag)} s<br>traffic: ${trLag == null ? '—' : Number(trLag)} s</div>
      </div>
      <div class="card">
        <div class="label" data-i18n="gui_ov_ingest_recency">Ingest Recency</div>
        <div class="value" style="font-size:.85rem;">
          events: ${escapeAttr(cache.last_event_ingested_at || '—')}<br>
          traffic: ${escapeAttr(cache.last_traffic_ingested_at || '—')}
        </div>
      </div>
      <div class="card ${siemClass}">
        <div class="label" data-i18n="gui_ov_siem_queue">SIEM Queue</div>
        <div class="value">pending: ${pending}<br>sent: ${sent}<br>failed: ${failed}</div>
      </div>
      <div class="card ${dlqClass}">
        <div class="label" data-i18n="gui_ov_dlq_total">DLQ Total</div>
        <div class="value">${dlq}</div>
      </div>
    </div>
    <h3 style="margin-top:16px;" data-i18n="gui_ov_recent_events">Recent dispatch events</h3>
    <ul id="ov-recent"></ul>`;

  const recent = (siem.recent || []).slice(0, 10);
  const ul = document.getElementById('ov-recent');
  if (!recent.length) {
    const li = document.createElement('li');
    li.style.color = 'var(--dim)';
    li.setAttribute('data-i18n', 'gui_ov_no_events');
    li.textContent = '(no recent events)';
    ul.appendChild(li);
  } else {
    recent.forEach(r => {
      const li = document.createElement('li');
      const code = document.createElement('code');
      code.textContent = r.destination || '';
      li.appendChild(code);
      li.append(' — ' + (r.status || '') + ' — ' + (r.timestamp || ''));
      ul.appendChild(li);
    });
  }
  if (typeof window.i18nApply === 'function') window.i18nApply();
});
```

- [ ] **Step 3: Add card color CSS (if missing)**

Check if `.card-ok` / `.card-warn` / `.card-err` / `.card-neutral` are already defined:

Run: `grep -n "card-ok\|card-warn" src/templates/index.html src/static/css/*.css 2>/dev/null`

If absent, add to the main `<style>` block in `index.html`:

```css
.card-ok      { border-left: 4px solid #299B65; }
.card-warn    { border-left: 4px solid var(--warn, #E6A700); }
.card-err     { border-left: 4px solid #F43F51; }
.card-neutral { border-left: 4px solid var(--border); }
```

- [ ] **Step 4: Manual smoke + i18n audit**

Load Integrations → Overview. Four cards colored per thresholds; recent events list renders.

Run: `python3 scripts/audit_i18n_usage.py`

- [ ] **Step 5: Commit**

```bash
git add src/static/js/integrations.js src/templates/index.html \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): Overview sub-tab with 4 status cards and recent events"
```

> **Note:** If `/api/siem/status` does not return `total_pending/total_sent/total_failed/total_dlq/recent` keys, either extend `src/siem/web.py::dispatch_status` to aggregate them, or adapt the JS to the existing response shape (preserving existing consumers).

---

## Task 24: Restart banner component

**Files:**
- Modify: `src/static/js/integrations.js` (replace placeholder `showRestartBanner`)
- Modify: `src/templates/index.html` (banner CSS if missing)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys**

```
gui_restart_required_banner          "Settings saved. Restart monitor to apply scheduling changes." / "設定已儲存。請重啟 monitor 以套用排程變更。"
gui_restart_monitor_btn              "Restart Monitor" / "重啟 Monitor"
gui_restart_success                  "Monitor restarted successfully." / "Monitor 已成功重啟。"
gui_restart_failed                   "Restart failed" / "重啟失敗"
gui_daemon_external_restart_hint     "Daemon is managed externally; restart from your service manager." / "Daemon 由外部管理，請從服務管理器重啟。"
gui_dismiss                          "Dismiss" / "關閉"
```

- [ ] **Step 2: Banner CSS (if missing)**

```css
.banner {
  padding: 10px 14px;
  background: var(--warn-bg, #3a2e00);
  border: 1px solid var(--warn, #E6A700);
  border-radius: var(--radius, 6px);
  display: flex; align-items: center; gap: 12px;
}
.banner .btn:last-of-type { margin-left: auto; }
```

- [ ] **Step 3: Replace placeholder `showRestartBanner` with real implementation**

```javascript
function showRestartBanner(target) {
  target.style.display = 'block';
  target.innerHTML = ''; // reset
  const wrap = document.createElement('div');
  wrap.className = 'banner';
  const span = document.createElement('span');
  span.setAttribute('data-i18n', 'gui_restart_required_banner');
  span.textContent = 'Settings saved. Restart monitor to apply scheduling changes.';
  const restartBtn = document.createElement('button');
  restartBtn.className = 'btn btn-primary';
  restartBtn.setAttribute('data-i18n', 'gui_restart_monitor_btn');
  restartBtn.textContent = 'Restart Monitor';
  restartBtn.addEventListener('click', () => doDaemonRestart(restartBtn, span));
  const dismissBtn = document.createElement('button');
  dismissBtn.className = 'btn';
  dismissBtn.setAttribute('data-i18n', 'gui_dismiss');
  dismissBtn.textContent = 'Dismiss';
  dismissBtn.addEventListener('click', () => { target.style.display = 'none'; });
  wrap.appendChild(span);
  wrap.appendChild(restartBtn);
  wrap.appendChild(dismissBtn);
  target.appendChild(wrap);
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

async function doDaemonRestart(btn, msgSpan) {
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = '…';
  try {
    const resp = await fetch('/api/daemon/restart', {method: 'POST'});
    const body = await resp.json();
    if (resp.status === 409) {
      msgSpan.textContent = window.t
        ? window.t('gui_daemon_external_restart_hint')
        : 'Daemon is managed externally; restart from your service manager.';
      btn.style.display = 'none';
      return;
    }
    if (body.ok) {
      btn.textContent = '✓';
      setTimeout(() => { btn.parentElement.parentElement.style.display = 'none'; }, 1500);
    } else {
      btn.textContent = original;
      btn.disabled = false;
      alert('Restart failed: ' + body.error);
    }
  } catch (exc) {
    btn.textContent = original;
    btn.disabled = false;
    alert('Error: ' + exc);
  }
}
```

- [ ] **Step 4: Manual smoke**

- Run `python3 illumio_ops.py --monitor --gui-port 8080` (GUI-integrated mode). Change Cache setting → Save → banner → Restart Monitor → daemon restarts (watch logs) → banner disappears.
- Run `python3 illumio_ops.py --gui` (no monitor) → banner Restart Monitor → 409 → message mutates to external-management hint, button hides.

- [ ] **Step 5: Commit**

```bash
git add src/static/js/integrations.js src/templates/index.html \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): restart-required banner with daemon-restart button"
```

---

## Task 25: End-to-end integration test

**Files:**
- Create: `tests/test_integrations_e2e.py`

- [ ] **Step 1: Write the test**

```python
import json, os, tempfile
from unittest.mock import MagicMock
import pytest
import src.gui as gui_module
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        salt, h = hash_password("pw")
        with open(path, "w") as f:
            json.dump({"web_gui": {"username": "admin", "password_hash": h,
                                    "password_salt": salt, "secret_key": "s"},
                       "pce_cache": {"enabled": False},
                       "siem": {"enabled": False, "destinations": []}}, f)
        os.environ["ILLUMIO_CONFIG"] = path
        cm = ConfigManager(); cm.load()
        from src.gui import _create_app
        app = _create_app(cm); app.config["TESTING"] = True
        with app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "pw"},
                   follow_redirects=True)
            yield c, path
    finally:
        os.unlink(path)
        gui_module._GUI_OWNS_DAEMON = False
        gui_module._DAEMON_SCHEDULER = None
        gui_module._DAEMON_RESTART_FN = None


def test_save_then_restart_roundtrip(client, tmp_path):
    c, path = client
    resp = c.put("/api/cache/settings", json={
        "enabled": True, "events_retention_days": 42,
        "db_path": str(tmp_path / "cache.sqlite"),
    })
    assert resp.status_code == 200
    assert resp.get_json()["requires_restart"] is True

    with open(path) as f:
        cfg = json.load(f)
    assert cfg["pce_cache"]["enabled"] is True
    assert cfg["pce_cache"]["events_retention_days"] == 42

    gui_module._GUI_OWNS_DAEMON = True
    fn = MagicMock(return_value=MagicMock())
    gui_module._DAEMON_RESTART_FN = fn
    resp = c.post("/api/daemon/restart")
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    fn.assert_called_once()
```

- [ ] **Step 2: Run — PASS**

Run: `python3 -m pytest tests/test_integrations_e2e.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_integrations_e2e.py
git commit -m "test(integrations): end-to-end save → restart roundtrip"
```

---

## Task 26: Final audit, version bump, walkthrough

**Files:**
- Modify: `src/__init__.py`

- [ ] **Step 1: Full i18n audit**

Run: `python3 scripts/audit_i18n_usage.py`
Expected: A–I = 0 findings. If any text is un-keyed, locate and add to both JSON files.

Run: `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v`

- [ ] **Step 2: Full pytest**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: previous baseline (582 passed + 1 skipped) + ~25 new tests (target ~607 passed, 1 skipped).

- [ ] **Step 3: Bump version**

Edit `src/__init__.py`:

```python
__version__ = "3.14.0-integrations-ui"
```

(Check recent `src/__init__.py` commits for naming convention and adjust if the project uses a different next-tag pattern.)

- [ ] **Step 4: GUI walkthrough checklist**

Start: `python3 illumio_ops.py --monitor --gui-port 8080` (or the project's equivalent for GUI-integrated daemon).

- [ ] `Integrations` tab sits between `Rule Scheduler` and `Settings`.
- [ ] Overview: four cards, colors correct; recent events list renders.
- [ ] Cache: status cards + all form sections including Traffic Filter (checkbox groups, comma inputs, IP/port hints) + Traffic Sampling.
  - [ ] Save valid → banner.
  - [ ] Save invalid IP → inline errors (no banner, no DB write).
  - [ ] Backfill button prompts and POSTs.
- [ ] SIEM: forwarder form saves. "+ Add" modal — TLS visible only for tls/hec, HEC only for hec.
  - [ ] Add + Edit + Delete persist.
  - [ ] Row Test button alerts ✓/✗.
- [ ] DLQ: filters work; Select All, Replay Selected, Purge Selected with confirm, Purge ALL with typed confirm, Export CSV downloads, View modal shows payload.
- [ ] Restart banner: `[Restart Monitor]` works when GUI owns daemon; 409-path mutates message otherwise.
- [ ] Language switch EN ↔ zh-TW: all new labels translate (any missing label shows the raw key; fix it).

CLI walkthrough:
- [ ] `python3 illumio_ops.py` → main menu shows "Manage PCE Cache" and "Manage SIEM Forwarder" before "Settings".
- [ ] PCE Cache menu: View status, Edit settings (persists), Edit traffic filter, Backfill prompts.
- [ ] SIEM menu: List / Add / Edit / Delete / Test destination, DLQ submenu (list / replay / purge / purge all / export CSV).

- [ ] **Step 5: Commit**

```bash
git add src/__init__.py
git commit -m "chore: bump version to 3.14.0-integrations-ui"
```

(Tagging `v3.14.0-integrations-ui` is optional here; usually done on merge to main.)

---

## Self-Review Checklist

- [ ] Spec §2 (Goals G1-G7) — each covered:
  - G1 (Cache settings in GUI) → Tasks 15-17
  - G2 (CLI parity) → Tasks 11-13
  - G3 (SIEM CRUD + test) → Tasks 8, 18-20, 12
  - G4 (DLQ list/filter/replay/purge/export) → Tasks 9, 21-22, 12
  - G5 (validated endpoints with errors + `requires_restart`) → Tasks 3, 6-7
  - G6 (Restart Monitor button, conditional) → Tasks 10, 24
  - G7 (i18n in both JSON files) → Every frontend task
- [ ] Spec §3 Non-Goals (no migration of other sections, no hot-reload, no RBAC) — NOT in any task ✓
- [ ] Spec §10 test plan — 11 new test files + extension to config_validators (Task 1). Plus test_integrations_e2e.
- [ ] All innerHTML-assigning code uses either static markup or pre-escaped values via `escapeAttr()`. DOM-method construction used where payload content is uncontrolled (DLQ View modal).
- [ ] Type consistency:
  - `send_test_event()` signature + `TestResult.ok/error/latency_ms` (Tasks 4, 5, 8, 12, 20) — consistent
  - `save_section()` signature + return shape `{ok, requires_restart, errors?}` (Tasks 3, 6, 7, 11, 12) — consistent
  - `_GUI_OWNS_DAEMON` / `_DAEMON_RESTART_FN` / `_DAEMON_SCHEDULER` (Tasks 10, 24, 25) — consistent
  - `integrationsSwitch` / `renderOverview/Cache/Siem/Dlq` / `collectTrafficFilter/Sampling` / `escapeAttr` — consistent
- [ ] No TBD/TODO/placeholders — every step shows actual commands/code.
- [ ] Pytest runs after every backend task (Steps labelled "Run tests — PASS"). Frontend tasks verify via manual walkthrough + i18n audit.
