# VEN Ransomware Exposure & High-Risk Open Ports — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Traffic-report mod16 "Open-Ports Attack Surface" with a new VEN-Status-Report section that uses PCE-native ransomware data to show, per VEN, its exposure severity, protection coverage, and the high-risk ports actually listening — each mapped to its owning process.

**Architecture:** A pure analysis function (`ransomware_posture`) joins per-workload `risk_details.ransomware.details[]` (which port is risky + protection state) with `services.open_service_ports[]` (which process listens) on `(port, proto)`. An enrichment module fetches+caches the per-workload data (rate-limited, 24h TTL). The VEN generator wires it; the VEN HTML exporter renders KPI + two tables. mod16 is removed entirely. mod04 (traffic-flow ransomware) is untouched.

**Tech Stack:** Python 3.12, pydantic config models, loguru, pytest. PCE REST API via existing `ApiClient`. Spec: `docs/superpowers/specs/2026-06-03-ven-ransomware-exposure-design.md`.

---

## File Structure

**Create:**
- `src/report/analysis/ransomware_posture.py` — pure analysis (JOIN, filter, KPI, sort). No I/O.
- `src/report/ransomware_posture_enrichment.py` — per-workload fetch + cache + rate limit.
- `tests/test_ransomware_posture.py` — pure-function unit tests.
- `tests/test_ransomware_posture_enrichment.py` — enrichment tests with a fake api.
- `tests/test_ven_report_ransomware.py` — generator-wiring + exporter render tests.

**Modify:**
- `src/api_client.py` — add `get_workload_risk_details(href)`.
- `src/report/ven_status_generator.py:114-121` — wire enrichment + analysis into `results`.
- `src/report/exporters/ven_html_exporter.py` — add `_ransomware_posture_section()` + call it after estate inventory.
- `src/i18n_en.json`, `src/i18n_zh_TW.json` — add `rpt_rwp_*` keys; remove `rpt_ops_*` keys.

**Delete (mod16 removal):**
- `src/report/analysis/open_ports_surface.py`, `src/report/open_ports_enrichment.py`
- `tests/test_open_ports_surface.py`, `tests/test_mod16_report.py`
- `src/config_models.py` — `AttackSurfaceSettings` class + `attack_surface` field
- `src/report/report_generator.py` — `_compute_open_ports_surface()` + its wiring
- `src/report/exporters/html_exporter.py` — mod16 nav, section, `_mod16_html()`

---

## Task 1: Remove mod16 (Open-Ports Attack Surface)

**Files:**
- Delete: `src/report/analysis/open_ports_surface.py`
- Delete: `src/report/open_ports_enrichment.py`
- Delete: `tests/test_open_ports_surface.py`
- Delete: `tests/test_mod16_report.py`
- Modify: `src/config_models.py` (remove `AttackSurfaceSettings` class lines 109-112 + field line 130)
- Modify: `src/report/report_generator.py` (remove helper lines 150-176 + wiring lines 657-661)
- Modify: `src/report/exporters/html_exporter.py` (remove nav 573-574, section 684-687, `_mod16_html()` 995-1034)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json` (remove 7 `rpt_ops_*` keys each)

- [ ] **Step 1: Delete the mod16 source + test files**

```bash
git rm src/report/analysis/open_ports_surface.py \
       src/report/open_ports_enrichment.py \
       tests/test_open_ports_surface.py \
       tests/test_mod16_report.py
```

- [ ] **Step 2: Remove `AttackSurfaceSettings` from config_models**

In `src/config_models.py`, delete this class (currently at lines 109-112):

```python
class AttackSurfaceSettings(_Base):
    enabled: bool = False
    max_workloads: int = Field(default=500, ge=1)
    cache_ttl_hours: int = Field(default=24, ge=1)
```

And delete this field line from `class ReportSettings` (currently line 130):

```python
    attack_surface: AttackSurfaceSettings = Field(default_factory=AttackSurfaceSettings)
```

- [ ] **Step 3: Remove mod16 from report_generator.py**

Delete the helper function (currently lines 150-176), the whole block from the comment `# ─── Open-Ports Attack Surface helper (mod16) ───` down to the end of `_compute_open_ports_surface` (the line `return None` plus trailing blank line):

```python
# ─── Open-Ports Attack Surface helper (mod16) ────────────────────────────────

def _compute_open_ports_surface(api, cm, top_n: int) -> "dict | None":
    ...
    except Exception as exc:
        logger.warning(f"[ReportGenerator] mod16 open-ports surface skipped: {exc}")
        return None
```

Delete the wiring block (currently lines 657-661):

```python
        # mod16 — Open-Ports Attack Surface (opt-in; no API calls when disabled)
        _ops = _compute_open_ports_surface(self.api, self.cm, top_n)
        if _ops is not None:
            results['mod16'] = _ops
```

- [ ] **Step 4: Remove mod16 from html_exporter.py**

Delete the nav-link entry (currently lines 573-574) inside the `security_risk` `_nav_links` list:

```python
                (_nav_link('open_ports', 'rpt_ops_section', 'Open-Ports Attack Surface')
                 if self._r.get('mod16') else ''),
```

Delete the section block (currently lines 684-687) in the `body` concatenation:

```python
            (self._section('open_ports', 'rpt_ops_section', 'Open-Ports Attack Surface',
                           self._mod16_html(),
                           'rpt_ops_intro', 'Shows static open listening Ports on managed Workloads — the attack surface complement to observed traffic.') + '\n'
             if self._r.get('mod16') else '') +
```

Delete the entire `_mod16_html(self)` method (currently lines 995-1034, from `def _mod16_html(self):` up to but not including `def _mod05_html(self):`).

- [ ] **Step 5: Remove `rpt_ops_*` i18n keys**

From BOTH `src/i18n_en.json` and `src/i18n_zh_TW.json`, delete these 7 keys (keep the JSON valid — remove the whole line incl. trailing comma handling):

```
"rpt_ops_hosts", "rpt_ops_intro", "rpt_ops_port", "rpt_ops_proto",
"rpt_ops_section", "rpt_ops_summary", "rpt_ops_wl_count"
```

- [ ] **Step 6: Catch any stragglers**

Run: `grep -rn "open_ports\|mod16\|attack_surface\|AttackSurface\|rpt_ops_\|_compute_open_ports" src/ tests/`
Expected: NO matches. If any remain (e.g., an import or a settings reference), remove them.

- [ ] **Step 7: Run full suite to confirm green after removal**

Run: `python3 -m pytest tests/ -q`
Expected: PASS (no collection errors, no failures from dangling mod16 references).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(report): remove mod16 Open-Ports Attack Surface (superseded by VEN ransomware posture)"
```

---

## Task 2: Add `get_workload_risk_details` to ApiClient

**Files:**
- Modify: `src/api_client.py` (add method next to `get_workload`, ~line 605)
- Test: `tests/test_ransomware_posture_enrichment.py` (created in Task 4 will exercise it; add a focused unit test here)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_risk_details.py`:

```python
"""Unit test for ApiClient.get_workload_risk_details."""
from unittest.mock import MagicMock
from src.api_client import ApiClient


def _client():
    api = ApiClient.__new__(ApiClient)  # bypass __init__ (no real config/network)
    api.api_cfg = {"url": "https://pce.example:8443"}
    return api


def test_get_workload_risk_details_ok(monkeypatch):
    api = _client()
    captured = {}

    def fake_request(url, timeout=10):
        captured["url"] = url
        return 200, b'{"risk_details": {"ransomware": {"details": []}}}'

    api._request = fake_request
    out = api.get_workload_risk_details("/orgs/1/workloads/abc")
    assert captured["url"] == "https://pce.example:8443/api/v2/orgs/1/workloads/abc/risk_details"
    assert out["risk_details"]["ransomware"]["details"] == []


def test_get_workload_risk_details_error_returns_empty():
    api = _client()
    api._request = lambda url, timeout=10: (404, b"not found")
    assert api.get_workload_risk_details("/orgs/1/workloads/missing") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_api_risk_details.py -v`
Expected: FAIL with `AttributeError: 'ApiClient' object has no attribute 'get_workload_risk_details'`.

- [ ] **Step 3: Implement the method**

In `src/api_client.py`, immediately after the `get_workload` method (after its closing `return {}` near line 604), add:

```python
    def get_workload_risk_details(self, href: str) -> dict:
        """Fetch a workload's ransomware risk details. Returns {} on error.

        GET /api/v2{href}/risk_details — payload is
        ``{"risk_details": {"ransomware": {"details": [...], ...} | null}}``.
        """
        try:
            url = f"{self.api_cfg['url']}/api/v2{href}/risk_details"
            status, body = self._request(url, timeout=10)
            if status == 200:
                return orjson.loads(body)
            logger.error(f"Get Workload Risk Details Failed: {status} for {href}")
            return {}
        except Exception as e:
            logger.error(f"Get Workload Risk Details Error: {e}")
            return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_api_risk_details.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/api_client.py tests/test_api_risk_details.py
git commit -m "feat(api): add get_workload_risk_details (PCE ransomware risk_details)"
```

---

## Task 3: Pure analysis module `ransomware_posture`

**Files:**
- Create: `src/report/analysis/ransomware_posture.py`
- Test: `tests/test_ransomware_posture.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ransomware_posture.py`:

```python
"""Tests for ransomware_posture pure analysis."""
from src.report.analysis.ransomware_posture import ransomware_posture


def _wl(href, host, sev, pct):
    return {"href": href, "hostname": host,
            "risk_summary": {"ransomware": {"workload_exposure_severity": sev,
                                            "ransomware_protection_percent": pct}}}


WORKLOADS = [
    _wl("/w/dc", "dc", "critical", 0.0),
    _wl("/w/web", "web", "high", 50.0),
    # pending: no risk_summary.ransomware
    {"href": "/w/new", "hostname": "new", "risk_summary": {"ransomware": None}},
]

ENRICH = {
    "/w/dc": {
        "open_service_ports": [
            {"port": 3389, "protocol": 6, "process_name": r"C:\Windows\System32\svchost.exe",
             "win_service_name": "TermService", "user": "SYSTEM"},
            {"port": 22, "protocol": 6, "process_name": "/usr/sbin/sshd", "user": "root"},
        ],
        "details": [
            {"port": 3389, "proto": 6, "name": "S-RDP", "severity": "critical",
             "port_status": "listening", "protection_state": "unprotected"},
            {"port": 23, "proto": 6, "name": "S-TELNET", "severity": "medium",
             "port_status": "inactive", "protection_state": "unprotected"},
        ],
    },
    "/w/web": {
        "open_service_ports": [
            {"port": 22, "protocol": 6, "process_name": "/usr/sbin/sshd", "user": "root"},
        ],
        "details": [
            {"port": 22, "proto": 6, "name": "S-SSH", "severity": "high",
             "port_status": "listening", "protection_state": "protected_open"},
        ],
    },
}


def test_kpi_counts_and_pending():
    out = ransomware_posture(WORKLOADS, ENRICH)
    assert out["kpi"]["by_exposure"]["critical"] == 1
    assert out["kpi"]["by_exposure"]["high"] == 1
    assert out["kpi"]["computed"] == 2
    assert out["kpi"]["pending"] == 1
    assert out["kpi"]["avg_protection_percent"] == 25.0


def test_listening_filter_counts_open_ports():
    out = ransomware_posture(WORKLOADS, ENRICH)
    by_host = {r["hostname"]: r for r in out["per_ven"]}
    # dc has one listening (3389) + one inactive (23) -> count 1
    assert by_host["dc"]["open_risky_count"] == 1
    assert by_host["web"]["open_risky_count"] == 1


def test_process_label_windows_uses_service_name():
    out = ransomware_posture(WORKLOADS, ENRICH)
    rdp = next(p for p in out["ports"] if p["hostname"] == "dc" and p["port"] == 3389)
    assert rdp["process"] == "TermService"           # win_service_name preferred
    assert rdp["process_full"] == r"C:\Windows\System32\svchost.exe"
    assert rdp["user"] == "SYSTEM"
    assert rdp["proto"] == "TCP"


def test_process_label_linux_uses_basename():
    out = ransomware_posture(WORKLOADS, ENRICH)
    ssh = next(p for p in out["ports"] if p["hostname"] == "web" and p["port"] == 22)
    assert ssh["process"] == "sshd"                   # basename of /usr/sbin/sshd
    assert ssh["protection_state"] == "protected_open"


def test_inactive_ports_excluded_from_detail():
    out = ransomware_posture(WORKLOADS, ENRICH)
    assert not any(p["service"] == "S-TELNET" for p in out["ports"])


def test_per_ven_sorted_by_severity_then_count():
    out = ransomware_posture(WORKLOADS, ENRICH)
    assert [r["hostname"] for r in out["per_ven"]] == ["dc", "web"]


def test_join_miss_yields_dash_process():
    wl = [_wl("/w/x", "x", "critical", 0.0)]
    enr = {"/w/x": {"open_service_ports": [],
                    "details": [{"port": 445, "proto": 6, "name": "S-SMB",
                                 "severity": "critical", "port_status": "listening",
                                 "protection_state": "unprotected"}]}}
    out = ransomware_posture(wl, enr)
    smb = out["ports"][0]
    assert smb["process"] == ""        # exporter renders this as "—"
    assert smb["user"] == ""


def test_empty_inputs_well_formed():
    out = ransomware_posture([], {})
    assert out["per_ven"] == [] and out["ports"] == []
    assert out["kpi"]["computed"] == 0 and out["kpi"]["pending"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ransomware_posture.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.analysis.ransomware_posture'`.

- [ ] **Step 3: Implement the module**

Create `src/report/analysis/ransomware_posture.py`:

```python
"""Pure analysis: ransomware exposure & high-risk open ports from PCE-native data.

Joins per-workload ``risk_details.ransomware.details[]`` (which risky service
port is listening + its protection state) with ``services.open_service_ports[]``
(which process is listening) on ``(port, proto)``. No I/O — all data is supplied
by the caller (see ``ransomware_posture_enrichment``).
"""
from __future__ import annotations

import os

_PROTO_NAMES: dict[int, str] = {6: "TCP", 17: "UDP"}
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "fully_protected": 4,
}
_EXPOSURE_LEVELS = ("critical", "high", "medium", "low", "fully_protected")


def _proto_name(proto) -> str:
    try:
        return _PROTO_NAMES.get(int(proto), str(proto))
    except (TypeError, ValueError):
        return str(proto)


def _process_label(osp_entry: dict) -> tuple[str, str]:
    """Return (short_label, full_path). Windows → win_service_name; else basename."""
    win = (osp_entry.get("win_service_name") or "").strip()
    full = (osp_entry.get("process_name") or "").strip()
    if win:
        return win, full
    if full:
        return os.path.basename(full.replace("\\", "/")), full
    return "", ""


def _ransomware(workload: dict) -> "dict | None":
    rs = workload.get("risk_summary")
    if not isinstance(rs, dict):
        return None
    rw = rs.get("ransomware")
    return rw if isinstance(rw, dict) else None


def ransomware_posture(workloads: list[dict], enrichment: dict) -> dict:
    """Build KPI, per-VEN rows, and high-risk open-port rows.

    Args:
        workloads: managed-workload dicts; each may carry
            ``risk_summary.ransomware`` {workload_exposure_severity,
            ransomware_protection_percent}.
        enrichment: ``{href: {"open_service_ports": [...], "details": [...]}}``
            where ``details`` is ``risk_details.ransomware.details``.

    Returns:
        ``{"kpi": {...}, "per_ven": [...], "ports": [...]}``; well-formed even
        when no workload has computed ransomware data.
    """
    by_exposure = {lvl: 0 for lvl in _EXPOSURE_LEVELS}
    computed = pending = 0
    cov_sum = 0.0
    per_ven: list[dict] = []
    ports: list[dict] = []

    for wl in workloads:
        rw = _ransomware(wl)
        if rw is None:
            pending += 1
            continue
        computed += 1
        sev = rw.get("workload_exposure_severity") or ""
        if sev in by_exposure:
            by_exposure[sev] += 1
        try:
            pct = float(rw.get("ransomware_protection_percent") or 0.0)
        except (TypeError, ValueError):
            pct = 0.0
        cov_sum += pct

        href = wl.get("href", "")
        host = str(wl.get("hostname") or href)
        enr = enrichment.get(href) or {}

        # index open ports by (port, proto)
        osp_idx: dict[tuple, dict] = {}
        for e in (enr.get("open_service_ports") or []):
            if not isinstance(e, dict):
                continue
            try:
                osp_idx.setdefault((int(e["port"]), int(e["protocol"])), e)
            except (KeyError, TypeError, ValueError):
                continue

        open_risky = 0
        for d in (enr.get("details") or []):
            if not isinstance(d, dict) or d.get("port_status") != "listening":
                continue
            open_risky += 1
            try:
                key = (int(d.get("port")), int(d.get("proto")))
            except (TypeError, ValueError):
                key = (d.get("port"), d.get("proto"))
            match = osp_idx.get(key, {})
            label, full = _process_label(match)
            ports.append({
                "hostname": host,
                "port": d.get("port"),
                "proto": _proto_name(d.get("proto")),
                "service": d.get("name") or "",
                "severity": d.get("severity") or "",
                "protection_state": d.get("protection_state") or "",
                "process": label,
                "process_full": full,
                "user": (match.get("user") or "") if isinstance(match, dict) else "",
            })

        per_ven.append({
            "hostname": host,
            "severity": sev,
            "protection_percent": round(pct, 1),
            "open_risky_count": open_risky,
        })

    per_ven.sort(key=lambda r: (_SEVERITY_RANK.get(r["severity"], 9), -r["open_risky_count"]))
    ports.sort(key=lambda r: (r["hostname"], _SEVERITY_RANK.get(r["severity"], 9)))

    return {
        "kpi": {
            "by_exposure": by_exposure,
            "computed": computed,
            "pending": pending,
            "avg_protection_percent": round(cov_sum / computed, 1) if computed else 0.0,
        },
        "per_ven": per_ven,
        "ports": ports,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ransomware_posture.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/ransomware_posture.py tests/test_ransomware_posture.py
git commit -m "feat(report): add ransomware_posture pure analysis (join risk_details + open ports)"
```

---

## Task 4: Enrichment module `ransomware_posture_enrichment`

**Files:**
- Create: `src/report/ransomware_posture_enrichment.py`
- Test: `tests/test_ransomware_posture_enrichment.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ransomware_posture_enrichment.py`:

```python
"""Tests for ransomware_posture_enrichment (cache-then-fetch, listening filter)."""
from src.report.ransomware_posture_enrichment import refresh_ransomware_posture


class FakeApi:
    def __init__(self):
        self.workload_calls = 0
        self.rd_calls = 0

    def get_workload(self, href):
        self.workload_calls += 1
        return {"services": {"open_service_ports": [
            {"port": 3389, "protocol": 6, "process_name": "svchost.exe", "user": "SYSTEM"},
        ]}}

    def get_workload_risk_details(self, href):
        self.rd_calls += 1
        return {"risk_details": {"ransomware": {"details": [
            {"port": 3389, "proto": 6, "name": "S-RDP", "severity": "critical",
             "port_status": "listening", "protection_state": "unprotected"},
        ]}}}


def _wl(href, sev="critical"):
    return {"href": href,
            "risk_summary": {"ransomware": {"workload_exposure_severity": sev,
                                            "ransomware_protection_percent": 0.0}}}


def test_fetches_only_computed_non_fully_protected(tmp_path):
    api = FakeApi()
    wls = [
        _wl("/w/a"),                                            # computed critical -> fetch
        {"href": "/w/b", "risk_summary": {"ransomware": None}},  # pending -> skip
        _wl("/w/c", sev="fully_protected"),                      # protected -> skip
    ]
    out = refresh_ransomware_posture(api, wls,
                                     cache_path=str(tmp_path / "c.json"), now=1000.0)
    assert set(out.keys()) == {"/w/a"}
    assert api.workload_calls == 1 and api.rd_calls == 1
    assert out["/w/a"]["details"][0]["name"] == "S-RDP"
    assert out["/w/a"]["open_service_ports"][0]["port"] == 3389


def test_cache_hit_skips_api(tmp_path):
    api = FakeApi()
    cache = str(tmp_path / "c.json")
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache, now=1000.0)
    assert api.workload_calls == 1
    # second call within TTL -> no new fetch
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache, now=1000.0 + 60)
    assert api.workload_calls == 1 and api.rd_calls == 1


def test_stale_cache_refetches(tmp_path):
    api = FakeApi()
    cache = str(tmp_path / "c.json")
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache,
                               ttl_hours=24, now=1000.0)
    # 25h later -> stale -> refetch
    refresh_ransomware_posture(api, [_wl("/w/a")], cache_path=cache,
                               ttl_hours=24, now=1000.0 + 25 * 3600)
    assert api.workload_calls == 2


def test_per_workload_error_is_swallowed(tmp_path):
    class BoomApi(FakeApi):
        def get_workload_risk_details(self, href):
            raise RuntimeError("boom")
    out = refresh_ransomware_posture(BoomApi(), [_wl("/w/a")],
                                     cache_path=str(tmp_path / "c.json"), now=1.0)
    assert out["/w/a"]["details"] == []           # error -> empty, not a crash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ransomware_posture_enrichment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.ransomware_posture_enrichment'`.

- [ ] **Step 3: Implement the module**

Create `src/report/ransomware_posture_enrichment.py`:

```python
"""Enrichment + cache for ransomware posture (per-workload fetches).

For each computed, non-fully-protected workload (up to ``max_workloads``):
- Cache HIT (fresh) → reuse, no API call.
- Cache MISS / stale → ``api.get_workload`` (open_service_ports) +
  ``api.get_workload_risk_details`` (ransomware.details), rate-limited.

Per-workload API errors are swallowed (that workload gets empty lists).
"""
from __future__ import annotations

import json
import os
import time

from loguru import logger

from src.pce_cache.rate_limiter import GlobalRateLimiter


def load_cache(cache_path: str = "data/ransomware_posture_cache.json") -> dict:
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict, cache_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


def _wants_enrichment(wl: dict) -> bool:
    rs = wl.get("risk_summary")
    rw = rs.get("ransomware") if isinstance(rs, dict) else None
    if not isinstance(rw, dict):
        return False
    return rw.get("workload_exposure_severity") != "fully_protected"


def refresh_ransomware_posture(
    api,
    workloads: list[dict],
    *,
    rate_per_minute: int = 400,
    max_workloads: int = 500,
    cache_path: str = "data/ransomware_posture_cache.json",
    ttl_hours: int = 24,
    now: "float | None" = None,
) -> dict:
    """Return ``{href: {"open_service_ports": [...], "details": [...]}}``."""
    if now is None:
        now = time.time()
    ttl_seconds = ttl_hours * 3600
    cache = load_cache(cache_path)
    limiter = GlobalRateLimiter(rate_per_minute)

    targets = [w for w in workloads if _wants_enrichment(w)]
    if len(targets) > max_workloads:
        logger.warning(
            "[ransomware_posture] {} eligible workloads exceed cap {}; truncating",
            len(targets), max_workloads,
        )
        targets = targets[:max_workloads]

    out: dict = {}
    for wl in targets:
        href = wl.get("href", "")
        cached = cache.get(href)
        if (isinstance(cached, dict)
                and (now - cached.get("fetched_at", 0)) < ttl_seconds):
            out[href] = {"open_service_ports": cached.get("open_service_ports", []),
                         "details": cached.get("details", [])}
            continue

        limiter.acquire(timeout=60.0)
        try:
            full = api.get_workload(href)
            osp = (full.get("services") or {}).get("open_service_ports") or [] if full else []
        except Exception:
            osp = []

        limiter.acquire(timeout=60.0)
        try:
            rd = api.get_workload_risk_details(href)
            rw = (rd.get("risk_details") or {}).get("ransomware") if rd else None
            details = (rw.get("details") or []) if isinstance(rw, dict) else []
        except Exception:
            details = []

        cache[href] = {"open_service_ports": list(osp), "details": list(details),
                       "fetched_at": now}
        out[href] = {"open_service_ports": list(osp), "details": list(details)}

    _save_cache(cache, cache_path)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ransomware_posture_enrichment.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/report/ransomware_posture_enrichment.py tests/test_ransomware_posture_enrichment.py
git commit -m "feat(report): add ransomware_posture enrichment (cache + rate-limited per-workload fetch)"
```

---

## Task 5: Wire into VenStatusGenerator

**Files:**
- Modify: `src/report/ven_status_generator.py` (after line 119, inside `generate()`)
- Test: `tests/test_ven_report_ransomware.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ven_report_ransomware.py`:

```python
"""VenStatusGenerator wires ransomware posture into module_results."""
from __future__ import annotations

import types
from unittest.mock import MagicMock


def _wl(href, host, sev):
    return {
        "href": href, "hostname": host,
        "os_id": "win-x86_64-server", "enforcement_mode": "selective",
        "interfaces": [], "labels": [],
        "agent": {"status": {"status": "active", "hours_since_last_heartbeat": 0.1,
                             "security_policy_sync_state": "synced",
                             "last_heartbeat_on": "2026-06-01T00:00:00Z",
                             "agent_version": "21.5"}},
        "risk_summary": {"ransomware": {"workload_exposure_severity": sev,
                                        "ransomware_protection_percent": 0.0}},
    }


_WORKLOADS = [_wl("/w/dc", "dc", "critical")]


def _make_cm():
    return types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})


def _make_api():
    api = MagicMock()
    api.fetch_managed_workloads.return_value = _WORKLOADS
    api.get_workload.return_value = {"services": {"open_service_ports": [
        {"port": 3389, "protocol": 6, "process_name": "svchost.exe",
         "win_service_name": "TermService", "user": "SYSTEM"}]}}
    api.get_workload_risk_details.return_value = {"risk_details": {"ransomware": {"details": [
        {"port": 3389, "proto": 6, "name": "S-RDP", "severity": "critical",
         "port_status": "listening", "protection_state": "unprotected"}]}}}
    return api


def _generate(tmp_path, api):
    from src.report.ven_status_generator import VenStatusGenerator
    gen = VenStatusGenerator(_make_cm(), api_client=api)
    return gen.generate(output_dir=str(tmp_path))


def test_ransomware_posture_key_present(tmp_path):
    result = _generate(tmp_path, _make_api())
    assert "ransomware_posture" in result.module_results
    rp = result.module_results["ransomware_posture"]
    assert rp["kpi"]["by_exposure"]["critical"] == 1
    assert rp["per_ven"][0]["hostname"] == "dc"
    assert rp["ports"][0]["process"] == "TermService"


def test_skipped_when_pce_lacks_risk_summary(tmp_path):
    api = _make_api()
    # PCE < 23.5: list carries no ransomware risk_summary
    api.fetch_managed_workloads.return_value = [
        {**_WORKLOADS[0], "risk_summary": None}]
    result = _generate(tmp_path, api)
    assert "ransomware_posture" not in result.module_results
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ven_report_ransomware.py -v`
Expected: FAIL — `assert "ransomware_posture" in result.module_results` is False (not yet wired).

- [ ] **Step 3: Implement the wiring**

In `src/report/ven_status_generator.py`, immediately after the estate-inventory block (currently lines 116-119, before `print(t("rpt_ven_analysis_done"...))` on line 121), insert:

```python
        # Ransomware posture (PCE-native; only when the PCE populates risk_summary)
        if any((w.get("risk_summary") or {}).get("ransomware") for w in workloads):
            from src.report import ransomware_posture_enrichment
            from src.report.analysis import ransomware_posture as _rwp
            _rpm = (self.cm.config.get("pce_cache") or {}).get("rate_limit_per_minute", 400)
            _enr = ransomware_posture_enrichment.refresh_ransomware_posture(
                self.api, workloads, rate_per_minute=_rpm)
            results["ransomware_posture"] = _rwp.ransomware_posture(workloads, _enr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ven_report_ransomware.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/report/ven_status_generator.py tests/test_ven_report_ransomware.py
git commit -m "feat(report): wire ransomware posture into VEN status generator"
```

---

## Task 6: Render section in ven_html_exporter + i18n

**Files:**
- Modify: `src/report/exporters/ven_html_exporter.py` (add `_ransomware_posture_section()`; call after `_estate_inventory_section()` at line 174)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json` (add `rpt_rwp_*` keys)
- Test: append a render test to `tests/test_ven_report_ransomware.py`

- [ ] **Step 1: Add i18n keys (both files, identical key set)**

Add these keys to `src/i18n_en.json` (place alphabetically among the other `rpt_*` keys):

```json
  "rpt_rwp_avg_coverage": "Average protection coverage",
  "rpt_rwp_computed": "Computed workloads",
  "rpt_rwp_coverage": "Protection %",
  "rpt_rwp_host": "Hostname",
  "rpt_rwp_intro": "PCE-native ransomware posture: each VEN's exposure severity, protection coverage, and the high-risk ports actually listening with their owning process.",
  "rpt_rwp_open_ports": "High-Risk Open Ports",
  "rpt_rwp_pending": "Pending (not yet computed)",
  "rpt_rwp_portproto": "Port/Proto",
  "rpt_rwp_ports_title": "High-Risk Open Ports Detail",
  "rpt_rwp_process": "Process",
  "rpt_rwp_protection": "Protection",
  "rpt_rwp_section": "Ransomware Exposure & High-Risk Open Ports",
  "rpt_rwp_service": "Service",
  "rpt_rwp_severity": "Severity",
  "rpt_rwp_user": "User",
  "rpt_rwp_ven_title": "VEN Risk Ranking",
```

Add the same keys to `src/i18n_zh_TW.json` with these values:

```json
  "rpt_rwp_avg_coverage": "平均保護覆蓋率",
  "rpt_rwp_computed": "已計算 workload",
  "rpt_rwp_coverage": "保護覆蓋%",
  "rpt_rwp_host": "主機名稱",
  "rpt_rwp_intro": "以 PCE 原生勒索防護資料盤點：每台 VEN 的曝險等級、保護覆蓋率，以及實際在聽的高風險埠與其執行程序。",
  "rpt_rwp_open_ports": "高風險開放埠數",
  "rpt_rwp_pending": "尚未計算",
  "rpt_rwp_portproto": "埠/協定",
  "rpt_rwp_ports_title": "高風險開放埠明細",
  "rpt_rwp_process": "程序",
  "rpt_rwp_protection": "保護狀態",
  "rpt_rwp_section": "勒索軟體曝險與高風險開放埠",
  "rpt_rwp_service": "服務",
  "rpt_rwp_severity": "嚴重度",
  "rpt_rwp_user": "使用者",
  "rpt_rwp_ven_title": "VEN 風險排序",
```

- [ ] **Step 2: Write the failing render test**

Append to `tests/test_ven_report_ransomware.py`:

```python
def test_section_renders_tables(tmp_path):
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    result = _generate(tmp_path, _make_api())
    html_out = VenHtmlExporter(result.module_results, df=result.dataframe,
                               lang="en").export(str(tmp_path))
    page = open(html_out, encoding="utf-8").read()
    assert "Ransomware Exposure &amp; High-Risk Open Ports" in page or \
           "Ransomware Exposure & High-Risk Open Ports" in page
    assert "TermService" in page          # process short label rendered
    assert "ransomware-posture" in page   # section id present


def test_section_absent_without_data(tmp_path):
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    api = _make_api()
    api.fetch_managed_workloads.return_value = [
        {**_WORKLOADS[0], "risk_summary": None}]
    result = _generate(tmp_path, api)
    html_out = VenHtmlExporter(result.module_results, df=result.dataframe,
                               lang="en").export(str(tmp_path))
    page = open(html_out, encoding="utf-8").read()
    assert "ransomware-posture" not in page
```

- [ ] **Step 3: Run render test to verify it fails**

Run: `python3 -m pytest tests/test_ven_report_ransomware.py::test_section_renders_tables -v`
Expected: FAIL — section markup not present (method not yet added / not called).

- [ ] **Step 4: Add the render method**

In `src/report/exporters/ven_html_exporter.py`, add this method immediately after `_estate_inventory_section` (after its `return "".join(parts)` at line 316):

```python
    def _ransomware_posture_section(self) -> str:
        """Render the Ransomware Exposure & High-Risk Open Ports section."""
        m = self._r.get("ransomware_posture")
        if not isinstance(m, dict):
            return ""
        per_ven = m.get("per_ven") or []
        if not per_ven:
            return ""
        _l = self._lang
        kpi = m.get("kpi") or {}
        ports = m.get("ports") or []

        by_exp = kpi.get("by_exposure") or {}
        pills = "".join(
            f'<div class="summary-pill"><span class="summary-pill-label">{html.escape(lvl)}</span>'
            f'<span class="summary-pill-value">{by_exp.get(lvl, 0)}</span></div>'
            for lvl in ("critical", "high", "medium", "low", "fully_protected")
        )
        kpi_html = (
            f'<div class="summary-pills">{pills}</div>'
            f'<p class="section-intro">{t("rpt_rwp_avg_coverage", lang=_l)}: '
            f'<strong>{kpi.get("avg_protection_percent", 0)}%</strong> · '
            f'{t("rpt_rwp_computed", lang=_l)}: <strong>{kpi.get("computed", 0)}</strong> · '
            f'{t("rpt_rwp_pending", lang=_l)}: <strong>{kpi.get("pending", 0)}</strong></p>'
        )

        ven_rows = "".join(
            f'<tr><td>{html.escape(str(r["hostname"]))}</td>'
            f'<td>{html.escape(str(r["severity"]))}</td>'
            f'<td>{r["protection_percent"]}%</td>'
            f'<td>{r["open_risky_count"]}</td></tr>'
            for r in per_ven
        )
        ven_table = (
            f'<h3>{t("rpt_rwp_ven_title", lang=_l)}</h3>'
            f'<table class="data-table"><thead><tr>'
            f'<th>{t("rpt_rwp_host", lang=_l)}</th>'
            f'<th>{t("rpt_rwp_severity", lang=_l)}</th>'
            f'<th>{t("rpt_rwp_coverage", lang=_l)}</th>'
            f'<th>{t("rpt_rwp_open_ports", lang=_l)}</th>'
            f'</tr></thead><tbody>{ven_rows}</tbody></table>'
        )

        port_table = ""
        if ports:
            port_rows = "".join(
                f'<tr><td>{html.escape(str(p["hostname"]))}</td>'
                f'<td>{html.escape(str(p["port"]))}/{html.escape(str(p["proto"]))}</td>'
                f'<td>{html.escape(str(p["service"]))}</td>'
                f'<td>{html.escape(str(p["severity"]))}</td>'
                f'<td>{html.escape(str(p["protection_state"]))}</td>'
                f'<td title="{html.escape(str(p["process_full"]))}">'
                f'{html.escape(str(p["process"])) or "—"}</td>'
                f'<td>{html.escape(str(p["user"])) or "—"}</td></tr>'
                for p in ports
            )
            port_table = (
                f'<h3>{t("rpt_rwp_ports_title", lang=_l)}</h3>'
                f'<table class="data-table"><thead><tr>'
                f'<th>{t("rpt_rwp_host", lang=_l)}</th>'
                f'<th>{t("rpt_rwp_portproto", lang=_l)}</th>'
                f'<th>{t("rpt_rwp_service", lang=_l)}</th>'
                f'<th>{t("rpt_rwp_severity", lang=_l)}</th>'
                f'<th>{t("rpt_rwp_protection", lang=_l)}</th>'
                f'<th>{t("rpt_rwp_process", lang=_l)}</th>'
                f'<th>{t("rpt_rwp_user", lang=_l)}</th>'
                f'</tr></thead><tbody>{port_rows}</tbody></table>'
            )

        return (
            f'<section id="ransomware-posture" class="card">'
            f'<h2>{t("rpt_rwp_section", lang=_l)}</h2>'
            f'<p class="section-intro">{t("rpt_rwp_intro", lang=_l)}</p>'
            f'{kpi_html}{ven_table}{port_table}</section>\n'
        )
```

- [ ] **Step 5: Call the section in the body**

In `src/report/exporters/ven_html_exporter.py` at line 174, change:

```python
            + self._estate_inventory_section()
```

to:

```python
            + self._estate_inventory_section()
            + self._ransomware_posture_section()
```

- [ ] **Step 6: Run render tests to verify they pass**

Run: `python3 -m pytest tests/test_ven_report_ransomware.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add src/report/exporters/ven_html_exporter.py src/i18n_en.json src/i18n_zh_TW.json tests/test_ven_report_ransomware.py
git commit -m "feat(report): render ransomware posture section in VEN report + i18n"
```

---

## Task 7: Final verification

- [ ] **Step 1: Full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS (all green, no skips related to this work).

- [ ] **Step 2: i18n parity check**

Run: `python3 -c "import json; a=set(json.load(open('src/i18n_en.json'))); b=set(json.load(open('src/i18n_zh_TW.json'))); print('only_en', sorted(x for x in a-b if x.startswith('rpt_rwp') or x.startswith('rpt_ops'))); print('only_zh', sorted(x for x in b-a if x.startswith('rpt_rwp') or x.startswith('rpt_ops')))"`
Expected: `only_en []` and `only_zh []` (all `rpt_rwp_*` present in both; no `rpt_ops_*` remaining).

- [ ] **Step 3: No mod16 residue**

Run: `grep -rn "open_ports\|mod16\|attack_surface\|rpt_ops_" src/ tests/`
Expected: NO matches.

- [ ] **Step 4: Live smoke test against lab PCE (optional, manual)**

Run a VEN report against the lab PCE and confirm the new section renders with real data:
`python3 -c "from src.config import ConfigManager; from src.api_client import ApiClient; from src.report.ven_status_generator import VenStatusGenerator; cm=ConfigManager(); g=VenStatusGenerator(cm, api_client=ApiClient(cm)); r=g.generate(output_dir='reports/'); print('ransomware_posture' in r.module_results, len(r.module_results.get('ransomware_posture',{}).get('ports',[])))"`
Expected: `True <n>` where n>0 (lab has computed critical workloads).

- [ ] **Step 5: Final commit (if any cleanup)**

```bash
git add -A
git commit -m "test(report): final verification for VEN ransomware posture"
```

---

## Notes for the implementer

- **Branch first:** this plan modifies `main`-tracked files; create a feature branch before Task 1.
- **TDD discipline:** within each task, write the test, watch it fail, implement, watch it pass, commit. Don't batch.
- **Process label rule** (Task 3 `_process_label`): Windows `svchost.exe` is generic — `win_service_name` (e.g. `TermService`) is preferred precisely to disambiguate it; Linux entries have no `win_service_name` so fall back to the basename of the full path. Validated 100% join hit on lab PCE 25.2.40.
- **Graceful degradation** (Task 5 guard): if the PCE doesn't populate `risk_summary.ransomware` on any workload (Core < 23.5, or feature off), the `ransomware_posture` key is never written and the exporter renders nothing — no error.
- **Cost:** per-VEN severity/coverage is free from the single `fetch_managed_workloads()` call; only the high-risk-port detail costs 2 calls/workload (get_workload + risk_details), rate-limited and cached 24h, capped at 500 eligible workloads with a log when truncated.
```
