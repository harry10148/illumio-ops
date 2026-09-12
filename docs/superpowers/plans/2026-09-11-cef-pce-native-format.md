# `cef_pce` PCE 原生 CEF 格式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 SIEM 轉拋格式 `cef_pce`／`syslog_cef_pce`，audit 事件與流量記錄的 CEF 形狀對齊 PCE 原生 syslog 輸出，並在測試機用 Graylog 逐鍵對帳驗收。

**Architecture:** 一支新的 `PceNativeCEFFormatter`（`src/siem/formatters/cef_pce.py`）實作既有 `Formatter` 介面，建構時注入 `pce_fqdn` 與 `pce_version`；dispatcher／tester 依 `format` 值選用；`mask_event` 補上 notifications 遮罩；設定模型、i18n、文件同步。既有 `cef` 不動。

**Tech Stack:** Python 3.12、orjson、pydantic v2、pytest。

**Spec:** `docs/superpowers/specs/2026-09-11-cef-pce-native-format-design.md`（格式契約 §4 是本計畫的唯一真相來源；本文重述關鍵規則但衝突時以 spec 為準）

## Global Constraints

- 既有 `cef`／`json`／`syslog_*` 格式輸出**逐位元不變**；只新增。
- 新格式的擴充欄位值不做 CEF 跳脫（`\`、`"`、`=` 原樣），只把 `\r`／`\n` 換成空白；header 欄位把 `|` 換成 `\|`。
- 鍵順序固定如 spec §4.1／§4.2；空值規則：`outcome=`、`cs2=`、`cs4=`、`cs2=`（flow state）保留空值鍵，其餘缺失即省略。
- 測試在前景執行且帶 timeout：`timeout 300 python3 -m pytest <file> -x -q`。
- 提交訊息英文 conventional commits；每個 task 結束 `git add <明確路徑>`，禁 `git add -A`。
- i18n：新／改的 `gui_*`／`sic_*` 鍵同時改 `src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`（釘選），否則 `tests/test_i18n_menu_strings.py` 會紅。
- 工作在 worktree 進行（`superpowers:using-git-worktrees`），分支 `feat/siem-cef-pce`，從 `origin/main`（≥ `64550b1e`）建立。主 checkout 目前被另一個 session 佔用（分支 `fix/email-badge-contrast`，有未提交修改），**不可在主 checkout 工作**。

---

### Task 1: Audit 事件格式器 `PceNativeCEFFormatter.format_event`

**Files:**
- Create: `src/siem/formatters/cef_pce.py`
- Test: `tests/test_cef_pce_formatter.py`
- Fixture（已存在）: `tests/fixtures/pce_native_cef_pairs.json`

**Interfaces:**
- Produces: `class PceNativeCEFFormatter(Formatter)`，`__init__(self, *, pce_fqdn: str = "", pce_version: str = "unknown")`；`format_event(self, event: dict) -> str`；`format_flow` 於 Task 2 實作（本 task 先 `raise NotImplementedError`）。
- 模組層函式（Task 2 重用）：`_rt_audit(ts: str) -> str`、`_header(sig: str, name: str, sev: int, version: str) -> str`、`_title(sig: str) -> str`、`_compact_json(obj) -> str`、`_clean(value) -> str`。

- [ ] **Step 1: 寫 golden 測試（先紅）**

```python
# tests/test_cef_pce_formatter.py
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PAIRS = json.loads((Path(__file__).parent / "fixtures" / "pce_native_cef_pairs.json").read_text("utf-8"))
PCE_VERSION = "26.2.20"
PCE_FQDN = "pce.lab.local"


def _formatter():
    from src.siem.formatters.cef_pce import PceNativeCEFFormatter
    return PceNativeCEFFormatter(pce_fqdn=PCE_FQDN, pce_version=PCE_VERSION)


def _expected_audit(pair: dict) -> str:
    """PCE 的 CEF 行，把 ops 無法知道的 dst 換成 spec §4.1 的規則值。"""
    event, cef = pair["event"], pair["cef"]
    src_ip = (event.get("action") or {}).get("src_ip")
    if not src_ip or src_ip == "FILTERED":
        cef = re.sub(r" dst=\S+ ", f" dst={PCE_FQDN} ", cef, count=1)
    return cef


@pytest.mark.parametrize("pair", PAIRS["audit"], ids=[p["cef"].split("|")[4] for p in PAIRS["audit"]])
def test_audit_event_matches_pce_native_line(pair):
    assert _formatter().format_event(pair["event"]) == _expected_audit(pair)


def test_audit_signature_omits_status_when_null():
    line = _formatter().format_event({
        "event_type": "user.pce_session_terminated", "status": None, "severity": "info",
        "timestamp": "2026-09-11T09:04:15.498Z", "pce_fqdn": PCE_FQDN,
        "created_by": {"system": {}}, "action": None, "resource_changes": [], "notifications": [],
        "href": "/orgs/1/events/x",
    })
    head, ext = line.split("|", 7)[:7], line.split("|", 7)[7]
    assert head[4] == "user.pce_session_terminated"
    assert head[5] == "User Pce Session Terminated"
    assert head[6] == "1"
    assert " outcome= cat=audit_events cs2= cs2Label=resource_changes cs4= cs4Label=notifications cn2=2 cn2Label=schema-version cs1Label=event_href cs1=/orgs/1/events/x" in ext
    assert "request=" not in ext


@pytest.mark.parametrize(("severity", "expected"), [
    ("info", 1), ("notice", 2), ("warning", 3), ("warn", 3), ("err", 4), ("error", 4),
    ("critical", 5), ("crit", 5), ("alert", 6), ("emerg", 7), ("emergency", 7), ("debug", 0), ("weird", 1),
])
def test_audit_severity_map(severity, expected):
    line = _formatter().format_event({"event_type": "x.y", "status": "success", "severity": severity,
                                      "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}})
    assert line.split("|")[6] == str(expected)


def test_audit_actor_variants():
    fmt = _formatter()
    base = {"event_type": "x.y", "status": "success", "severity": "info",
            "timestamp": "2026-01-01T00:00:00Z", "action": None}
    sa = fmt.format_event({**base, "created_by": {"service_account": {"href": "/orgs/1/service_accounts/abc", "name": "svc-ops"}}})
    assert " duid=abc duser=svc-ops " in sa
    agent_only = fmt.format_event({**base, "created_by": {"agent": {"href": "/orgs/1/agents/77", "hostname": "h1"}}})
    assert " duid=77 duser=h1 " in agent_only
    empty = fmt.format_event({**base, "created_by": {}})
    assert " duser=system " in empty and "duid=" not in empty


def test_audit_values_are_not_cef_escaped_but_newlines_are_flattened():
    line = _formatter().format_event({
        "event_type": "x.y", "status": "success", "severity": "info", "timestamp": "2026-01-01T00:00:00Z",
        "created_by": {"user": {"href": "/users/1", "username": "DOM\\user=1"}},
        "action": {"api_endpoint": "/a?b=c", "api_method": "GET", "http_status_code": 200, "src_ip": "1.2.3.4"},
        "resource_changes": [{"changes": {"desc": {"before": "a\nb", "after": "\"q\""}}}],
    })
    assert " duser=DOM\\user=1 " in line
    assert " request=/a?b=c " in line
    assert "\n" not in line
    assert '"after":"\\"q\\""' in line   # orjson 的 JSON 跳脫，不是 CEF 跳脫


def test_audit_header_pipe_is_escaped_and_version_injected():
    line = _formatter().format_event({"event_type": "a|b", "status": "success", "severity": "info",
                                      "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}})
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|a\\|b.success|A B Success|1|")


def test_audit_dvchost_falls_back_to_injected_fqdn():
    line = _formatter().format_event({"event_type": "a.b", "status": "success", "severity": "info",
                                      "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}})
    assert " dvchost=pce.lab.local duser=system dst=pce.lab.local " in line
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 python3 -m pytest tests/test_cef_pce_formatter.py -x -q`
Expected: FAIL，`ModuleNotFoundError: src.siem.formatters.cef_pce`

- [ ] **Step 3: 實作**

```python
# src/siem/formatters/cef_pce.py
"""CEF that mirrors the PCE's own syslog export (`cef_pce`).

Evidence: tests/fixtures/pce_native_cef_pairs.json — real pairs joined on
event_href between the ops cache and pce.lab.local's syslog (PCE 26.2.20,
2026-09-11), plus a 3,000-line scan of the PCE stream in Graylog.  Every
rule below that the scan could not observe is marked ASSUMPTION.

Why a second CEF formatter instead of changing `cef`: the Signature ID
changes shape (event_type.status), severities change, and empty values
(`outcome=`) are emitted on purpose — any SOC rule written against the old
line would break, so the old line stays available.

Values are NOT CEF-escaped.  The PCE does not escape them either
(`suser=NT AUTHORITY\\SYSTEM` goes out verbatim) and cs2/cs4 carry JSON the
SOC must be able to parse as-is.  Only CR/LF are flattened, and `|` only in
the header.
"""
from __future__ import annotations

from datetime import datetime, timezone

import orjson

from src.siem.formatters.base import Formatter

# audit: info→1 / warning→3 / err→4 observed; the rest are ASSUMPTION
# (monotone fill between observed points, never observed on a real PCE).
_AUDIT_SEVERITY = {
    "debug": 0, "info": 1, "informational": 1, "notice": 2,
    "warning": 3, "warn": 3, "err": 4, "error": 4,
    "critical": 5, "crit": 5, "alert": 6, "emerg": 7, "emergency": 7,
}
# flows: allowed→1 / unknown→1 / potentially_blocked→3 observed;
# blocked→5 is ASSUMPTION (the LEEF export documents sev=5 for it).
_FLOW_SEVERITY = {"allowed": 1, "unknown": 1, "potentially_blocked": 3, "blocked": 5}
_FLOW_PD_NUMERIC = {0: "allowed", 1: "potentially_blocked", 2: "blocked"}
_PROTO = {6: "tcp", 17: "udp", 1: "icmp"}
_STATE = {"active": "A", "snapshot": "S", "closed": "C", "timed_out": "T", "new": "N"}  # new→N ASSUMPTION
_TRAFCLASS = {"unicast": "U", "broadcast": "B", "multicast": "M"}


def _clean(value) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")


def _header_field(value: str) -> str:
    return _clean(value).replace("|", "\\|")


def _title(sig: str) -> str:
    words = [w for w in sig.replace(".", " ").replace("_", " ").split() if w]
    return " ".join(w[:1].upper() + w[1:].lower() for w in words)


def _header(sig: str, name: str, sev: int, version: str) -> str:
    return f"CEF:0|Illumio|PCE|{_header_field(version)}|{_header_field(sig)}|{_header_field(name)}|{sev}|"


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rt_audit(ts: str) -> str:
    dt = _parse_ts(ts)
    if dt is None:
        return ""
    return dt.strftime("%b %d %Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d} +0000"


def _rt_flow(ts: str) -> str:
    dt = _parse_ts(ts)
    return dt.strftime("%b %d %Y %H:%M:%S") if dt else ""


def _compact_json(obj) -> str:
    return orjson.dumps(obj).decode("utf-8")


def _href_tail(href) -> str:
    return str(href or "").rstrip("/").rsplit("/", 1)[-1]


def _actor(created_by) -> tuple[str, str]:
    """(duid, duser). duid == "" means omit the key."""
    cb = created_by if isinstance(created_by, dict) else {}
    if "system" in cb or not cb:
        return "", "system"
    if isinstance(cb.get("user"), dict):
        u = cb["user"]
        return _href_tail(u.get("href")), str(u.get("username") or u.get("name") or "")
    if isinstance(cb.get("agent"), dict):
        agent = cb["agent"]
        ven = cb.get("ven") if isinstance(cb.get("ven"), dict) else {}
        return _href_tail((ven or {}).get("href") or agent.get("href")), str(agent.get("hostname") or "")
    for key in ("container_cluster", "service_account"):
        if isinstance(cb.get(key), dict):
            return _href_tail(cb[key].get("href")), str(cb[key].get("name") or "")
    return "", "system"


class PceNativeCEFFormatter(Formatter):
    def __init__(self, *, pce_fqdn: str = "", pce_version: str = "unknown"):
        self._pce_fqdn = pce_fqdn
        self._pce_version = pce_version or "unknown"

    # ── audit events ────────────────────────────────────────────────────
    def format_event(self, event: dict) -> str:
        event_type = str(event.get("event_type") or "unknown")
        status = event.get("status")
        sig = f"{event_type}.{status}" if status else event_type
        sev = _AUDIT_SEVERITY.get(str(event.get("severity") or "info").lower(), 1)
        head = _header(sig, _title(sig), sev, self._pce_version)

        dvchost = str(event.get("pce_fqdn") or self._pce_fqdn)
        action = event.get("action") if isinstance(event.get("action"), dict) else None
        src_ip = (action or {}).get("src_ip")
        dst = src_ip if src_ip and src_ip != "FILTERED" else dvchost
        duid, duser = _actor(event.get("created_by"))

        ext: list[str] = []
        rt = _rt_audit(str(event.get("timestamp") or ""))
        if rt:
            ext.append(f"rt={rt}")
        ext.append(f"dvchost={_clean(dvchost)}")
        if duid:
            ext.append(f"duid={_clean(duid)}")
        ext.append(f"duser={_clean(duser)}")
        ext.append(f"dst={_clean(dst)}")
        ext.append(f"outcome={_clean(status or '')}")
        ext.append("cat=audit_events")
        if action is not None:
            if action.get("api_endpoint") is not None:
                ext.append(f"request={_clean(action['api_endpoint'])}")
            if action.get("api_method") is not None:
                ext.append(f"requestMethod={_clean(action['api_method'])}")
            if action.get("http_status_code") is not None:
                ext.append(f"reason={_clean(action['http_status_code'])}")
        rc = event.get("resource_changes") or []
        ext.append(f"cs2={_clean(_compact_json(rc)) if rc else ''}")
        ext.append("cs2Label=resource_changes")
        notes = event.get("notifications") or []
        ext.append(f"cs4={_clean(_compact_json(notes)) if notes else ''}")
        ext.append("cs4Label=notifications")
        ext.append("cn2=2")
        ext.append("cn2Label=schema-version")
        ext.append("cs1Label=event_href")
        ext.append(f"cs1={_clean(event.get('href') or event.get('pce_event_id') or '')}")
        return head + " ".join(ext)

    def format_flow(self, flow: dict) -> str:  # Task 2
        raise NotImplementedError
```

- [ ] **Step 4: 跑測試確認通過**

Run: `timeout 300 python3 -m pytest tests/test_cef_pce_formatter.py -x -q`
Expected: 全綠（19 組 golden ＋ 7 個規則測試）。若某組 golden 紅，先印兩行 diff（`difflib.ndiff`）確認是規則漏了還是 fixture 特例，**不可**為了過測試把該組從 fixture 拿掉。

- [ ] **Step 5: 注入缺陷確認守門有效**

暫時把 `ext.append("cn2=2")` 註解掉，跑 Step 4 命令，Expected: 19 組 golden 全紅；還原後再綠。

- [ ] **Step 6: Commit**

```bash
git add src/siem/formatters/cef_pce.py tests/test_cef_pce_formatter.py tests/fixtures/pce_native_cef_pairs.json
git commit -m "feat(siem): cef_pce formatter mirrors the PCE's own audit-event CEF"
```

---

### Task 2: 流量格式器 `PceNativeCEFFormatter.format_flow`

**Files:**
- Modify: `src/siem/formatters/cef_pce.py`（取代 `format_flow` 的 `NotImplementedError`）
- Test: `tests/test_cef_pce_formatter.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_header`、`_title`、`_rt_flow`、`_compact_json`、`_clean`、`_FLOW_SEVERITY`、`_FLOW_PD_NUMERIC`、`_PROTO`、`_STATE`、`_TRAFCLASS`。
- Produces: `format_flow(self, flow: dict) -> str`；接受 raw PCE API 形（巢狀 `src`/`dst`/`service`）與 flat 官方 log 形（`src_ip`、`pd`、`un`、`pn`…），與既有 `CEFFormatter.format_flow` 的輸入相容。

- [ ] **Step 1: 寫測試（先紅）**

```python
# 追加到 tests/test_cef_pce_formatter.py

_KEY_RE = re.compile(r"(?:^| )([A-Za-z0-9_]+)=")


def _keys(ext: str) -> list[str]:
    return _KEY_RE.findall(ext)


@pytest.mark.parametrize("pair", PAIRS["flows"], ids=[f"{p['flow']['src']['ip']}>{p['flow']['dst']['ip']}" for p in PAIRS["flows"]])
def test_flow_key_order_matches_pce_reference(pair):
    """同 5-tuple 但非同一筆實例：只比鍵順序（去掉 ops 沒有的 in/out/cn1）。"""
    line = _formatter().format_flow(pair["flow"])
    ours = _keys(line.split("|", 7)[7])
    ref = [k for k in _keys(pair["pce_cef_reference"].split("|", 7)[7]) if k not in ("in", "out", "cn1", "cn1Label")]
    # PCE 只在有 process 資訊時帶 user/proc；我們的實例可能沒有，比對時以雙方交集的鍵順序驗證
    common = [k for k in ref if k in ours]
    assert [k for k in ours if k in common] == common
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|flow_")


def test_flow_full_line_raw_api_shape():
    flow = {
        "src": {"ip": "172.16.15.130", "workload": {"hostname": "pce.lab.local", "href": "/orgs/1/workloads/da7a",
                "labels": [{"key": "env", "value": "Server"}, {"key": "app", "value": "Illumio"}]}},
        "dst": {"ip": "172.16.15.100", "workload": {"hostname": "dc", "href": "/orgs/1/workloads/743a",
                "labels": [{"key": "role", "value": "DomainController"}]}},
        "network": {"name": "Corporate"},
        "service": {"port": 53, "proto": 17, "process_name": "dns.exe", "user_name": "NT AUTHORITY\\SYSTEM"},
        "num_connections": 1502, "policy_decision": "potentially_blocked", "state": "active",
        "flow_direction": "inbound", "dst_bi": 211039, "dst_bo": 222295,
        "timestamp_range": {"last_detected": "2026-09-11T09:11:55Z", "first_detected": "2026-09-11T00:00:48Z"},
        "transmission": "unicast",
    }
    line = _formatter().format_flow(flow)
    assert line == (
        "CEF:0|Illumio|PCE|26.2.20|flow_potentially_blocked|Flow Potentially Blocked|3|"
        "act=potentially_blocked cat=flow_summary deviceDirection=0 dpt=53 src=172.16.15.130 dst=172.16.15.100 "
        "proto=udp cnt=1502 rt=Sep 11 2026 09:11:55 duser=NT AUTHORITY\\SYSTEM dproc=dns.exe "
        "cn2=211039 cn2Label=dbi cn3=222295 cn3Label=dbo cs2=A cs2Label=state "
        "shost=pce.lab.local cs5=/orgs/1/workloads/da7a cs5Label=src_href "
        'cs3={"env":"Server","app":"Illumio"} cs3Label=src_labels '
        "dhost=dc cs6=/orgs/1/workloads/743a cs6Label=dst_href "
        'cs4={"role":"DomainController"} cs4Label=dst_labels dvchost=pce.lab.local '
        'msg={"trafclass_code":"U","network":"Corporate"}'
    )


def test_flow_outbound_puts_process_on_source_side_and_emits_icmp_and_counters():
    flow = {
        "src": {"ip": "10.0.0.1", "workload": {"hostname": "", "href": "/orgs/1/workloads/aaa", "labels": []}},
        "dst": {"ip": "10.0.0.2"},
        "service": {"port": 0, "proto": 1, "process_name": "ping", "user_name": "root"},
        "num_connections": 1, "policy_decision": "unknown", "state": "snapshot", "flow_direction": "outbound",
        "icmp_type": 8, "icmp_code": 0, "interval_sec": 600, "dst_tbi": 10, "dst_tbo": 20,
        "dst_dbi": 1, "dst_dbo": 2, "ddms": 5, "tdms": 7, "pd_qualifier": 0,
        "network": {"name": "Corporate"}, "timestamp": "2026-09-11T09:01:23Z",
    }
    line = _formatter().format_flow(flow)
    assert line == (
        "CEF:0|Illumio|PCE|26.2.20|flow_unknown|Flow Unknown|1|"
        "act=unknown cat=flow_summary deviceDirection=1 dpt=0 src=10.0.0.1 dst=10.0.0.2 proto=icmp cnt=1 "
        "in=10 out=20 rt=Sep 11 2026 09:01:23 suser=root sproc=ping cn1=600 cn1Label=interval_sec "
        "cn2=1 cn2Label=dbi cn3=2 cn3Label=dbo cs2=S cs2Label=state "
        "shost= cs5=/orgs/1/workloads/aaa cs5Label=src_href dvchost=pce.lab.local "
        'msg={"icmp_type":8,"icmp_code":0,"trafclass_code":"U","ddms":5,"tdms":7,"network":"Corporate","pd_qualifier":0}'
    )


def test_flow_flat_shape_numeric_pd_and_service_name():
    flow = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "dst_port": 445, "proto": "tcp", "pd": 2,
            "count": 3, "dir": "I", "state": "C", "un": "System", "pn": "System", "service_name": "SMB",
            "class": "U", "network": "Corporate", "timestamp": "2026-09-11T09:11:54Z"}
    line = _formatter().format_flow(flow)
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|flow_blocked|Flow Blocked|5|")
    assert " duser=System destinationServiceName=SMB dproc=System " in line
    assert " cs2=C cs2Label=state dvchost=pce.lab.local msg=" in line


def test_flow_masked_user_is_forwarded_redacted():
    from src.siem.mask import mask_flow
    flow = {"src": {"ip": "1.1.1.1"}, "dst": {"ip": "2.2.2.2"},
            "service": {"port": 22, "proto": 6, "user_name": "alice", "process_name": "ssh"},
            "policy_decision": "allowed", "flow_direction": "outbound", "num_connections": 1,
            "timestamp_range": {"last_detected": "2026-09-11T09:11:54Z"}}
    line = _formatter().format_flow(mask_flow(flow, mask_pii=True))
    assert " suser=[REDACTED] sproc=[REDACTED] " in line
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 python3 -m pytest tests/test_cef_pce_formatter.py -x -q -k flow`
Expected: FAIL，`NotImplementedError`

- [ ] **Step 3: 實作 `format_flow`**

```python
    # 取代 Task 1 的 stub
    def format_flow(self, flow: dict) -> str:
        svc = flow.get("service") if isinstance(flow.get("service"), dict) else {}
        src = flow.get("src") if isinstance(flow.get("src"), dict) else {}
        dst = flow.get("dst") if isinstance(flow.get("dst"), dict) else {}
        src_wl = src.get("workload") if isinstance(src.get("workload"), dict) else None
        dst_wl = dst.get("workload") if isinstance(dst.get("workload"), dict) else None

        pd_raw = _first(flow.get("pd"), flow.get("policy_decision"))
        if isinstance(pd_raw, bool):
            pd_raw = None
        if isinstance(pd_raw, int):
            pd = _FLOW_PD_NUMERIC.get(pd_raw, "unknown")
        else:
            pd = str(pd_raw or "unknown")
            if pd not in _FLOW_SEVERITY:
                pd = "unknown"
        head = _header(f"flow_{pd}", _title(f"flow_{pd}"), _FLOW_SEVERITY[pd], self._pce_version)

        dir_raw = str(_first(flow.get("flow_direction"), flow.get("dir")) or "")
        outbound = dir_raw in ("outbound", "O")
        proto_raw = _first(flow.get("proto"), flow.get("protocol"), svc.get("proto"))
        proto = proto_raw if isinstance(proto_raw, str) else _PROTO.get(int(proto_raw), str(proto_raw)) if proto_raw is not None else ""
        port = _first(flow.get("dst_port"), flow.get("port"), svc.get("port"), 0)
        ts = _first(flow.get("timestamp"), flow.get("last_detected"),
                    (flow.get("timestamp_range") or {}).get("last_detected"), "")

        ext: list[str] = [f"act={pd}", "cat=flow_summary", f"deviceDirection={1 if outbound else 0}",
                          f"dpt={port}", f"src={_clean(_first(flow.get('src_ip'), src.get('ip'), ''))}",
                          f"dst={_clean(_first(flow.get('dst_ip'), dst.get('ip'), ''))}", f"proto={_clean(proto)}"]
        cnt = _first(flow.get("count"), flow.get("num_connections"), flow.get("flow_count"))
        if cnt is not None:
            ext.append(f"cnt={cnt}")
        tbi, tbo = flow.get("dst_tbi"), flow.get("dst_tbo")
        if tbi is not None and tbo is not None:
            ext.append(f"in={tbi}")
            ext.append(f"out={tbo}")
        rt = _rt_flow(str(ts or ""))
        if rt:
            ext.append(f"rt={rt}")
        user = _first(svc.get("user_name"), flow.get("un"))
        proc = _first(svc.get("process_name"), flow.get("pn"))
        svc_name = _first(svc.get("name"), flow.get("service_name"))
        if user:
            ext.append(f"{'suser' if outbound else 'duser'}={_clean(user)}")
        if svc_name:
            ext.append(f"destinationServiceName={_clean(svc_name)}")
        if proc:
            ext.append(f"{'sproc' if outbound else 'dproc'}={_clean(proc)}")
        if flow.get("interval_sec") is not None:
            ext.append(f"cn1={flow['interval_sec']}")
            ext.append("cn1Label=interval_sec")
        dbi = _first(flow.get("dst_dbi"), flow.get("dst_bi"))
        dbo = _first(flow.get("dst_dbo"), flow.get("dst_bo"))
        if dbi is not None and dbo is not None:
            ext += [f"cn2={dbi}", "cn2Label=dbi", f"cn3={dbo}", "cn3Label=dbo"]
        state = str(flow.get("state") or "")
        ext.append(f"cs2={_STATE.get(state, state if len(state) == 1 else '')}")
        ext.append("cs2Label=state")
        if src_wl is not None:
            ext.append(f"shost={_clean(_first(flow.get('src_hostname'), src_wl.get('hostname'), src_wl.get('name'), ''))}")
            ext.append(f"cs5={_clean(_first(flow.get('src_href'), src_wl.get('href'), ''))}")
            ext.append("cs5Label=src_href")
            labels = _labels_obj(_first(flow.get("src_labels"), src_wl.get("labels")))
            if labels:
                ext.append(f"cs3={_clean(_compact_json(labels))}")
                ext.append("cs3Label=src_labels")
        if dst_wl is not None:
            ext.append(f"dhost={_clean(_first(flow.get('dst_hostname'), dst_wl.get('hostname'), dst_wl.get('name'), ''))}")
            ext.append(f"cs6={_clean(_first(flow.get('dst_href'), dst_wl.get('href'), ''))}")
            ext.append("cs6Label=dst_href")
            labels = _labels_obj(_first(flow.get("dst_labels"), dst_wl.get("labels")))
            if labels:
                ext.append(f"cs4={_clean(_compact_json(labels))}")
                ext.append("cs4Label=dst_labels")
        ext.append(f"dvchost={_clean(flow.get('pce_fqdn') or self._pce_fqdn)}")

        msg: dict = {}
        if flow.get("icmp_type") is not None or flow.get("type") is not None:
            msg["icmp_type"] = _first(flow.get("icmp_type"), flow.get("type"), svc.get("icmp_type"))
            msg["icmp_code"] = _first(flow.get("icmp_code"), flow.get("code"), svc.get("icmp_code"))
        cls = flow.get("class") or _TRAFCLASS.get(str(flow.get("transmission") or "").lower(), "U")
        msg["trafclass_code"] = cls
        for k in ("ddms", "tdms"):
            if flow.get(k) is not None:
                msg[k] = flow[k]
        net = flow.get("network")
        net_name = net if isinstance(net, str) else (net or {}).get("name")
        if net_name:
            msg["network"] = net_name
        if flow.get("pd_qualifier") is not None:
            msg["pd_qualifier"] = flow["pd_qualifier"]
        ext.append(f"msg={_clean(_compact_json(msg))}")
        return head + " ".join(ext)


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _labels_obj(labels) -> dict:
    if isinstance(labels, dict):
        return {str(k): str(v) for k, v in labels.items() if k and v}
    out: dict = {}
    for lbl in labels or []:
        if isinstance(lbl, dict) and lbl.get("key") and lbl.get("value"):
            out[str(lbl["key"])] = str(lbl["value"])
    return out
```

（`_first` 與 `_labels_obj` 放模組層，位置在 `class` 之前。）

- [ ] **Step 4: 跑測試確認通過**

Run: `timeout 300 python3 -m pytest tests/test_cef_pce_formatter.py -x -q`
Expected: 全綠。

- [ ] **Step 5: Commit**

```bash
git add src/siem/formatters/cef_pce.py tests/test_cef_pce_formatter.py
git commit -m "feat(siem): cef_pce flow lines follow the PCE flow_summary shape"
```

---

### Task 3: notifications 遮罩

**Files:**
- Modify: `src/siem/mask.py`（`mask_event` 加 `_mask_notifications`）
- Test: `tests/test_siem_mask_pii.py`（追加）

**Interfaces:**
- Consumes: 既有 `mask_event(event, *, mask_pii)`。
- Produces: 行為擴充，簽章不變。`cs4` 內的 `info.user.{username,name,email}` 與 `info.src_ip` 變 `[REDACTED]`。

- [ ] **Step 1: 寫測試（先紅）**

```python
def test_mask_redacts_notification_user_and_src_ip():
    from src.siem.mask import mask_event, REDACTED
    event = {"event_type": "user.login", "notifications": [
        {"notification_type": "user.pce_session_created", "info": {"user": {"href": "/users/11", "username": "admin@lab.local"}}},
        {"notification_type": "request.authentication_failed", "info": {"api_endpoint": "/api/v2/users/login", "src_ip": "192.168.20.30"}},
        {"notification_type": "x", "info": None},
        "not-a-dict",
    ]}
    out = mask_event(event, mask_pii=True)
    assert out["notifications"][0]["info"]["user"]["username"] == REDACTED
    assert out["notifications"][0]["info"]["user"]["href"] == "/users/11"
    assert out["notifications"][1]["info"]["src_ip"] == REDACTED
    assert out["notifications"][1]["info"]["api_endpoint"] == "/api/v2/users/login"
    assert event["notifications"][0]["info"]["user"]["username"] == "admin@lab.local"  # caller untouched
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 python3 -m pytest tests/test_siem_mask_pii.py -x -q -k notification`
Expected: FAIL（username 未被遮）

- [ ] **Step 3: 實作**

```python
def _mask_notifications(event: dict[str, Any]) -> None:
    """cs4 (cef_pce) forwards notifications verbatim; the PCE puts the
    acting user's email and the client IP inside `info`, same PII as
    created_by / action."""
    notes = event.get("notifications")
    if not isinstance(notes, list):
        return
    for entry in notes:
        if not isinstance(entry, dict):
            continue
        info = entry.get("info")
        if not isinstance(info, dict):
            continue
        user = info.get("user")
        if isinstance(user, dict):
            for key in ("username", "name", "email"):
                if user.get(key):
                    user[key] = REDACTED
        if info.get("src_ip"):
            info["src_ip"] = REDACTED
```

在 `mask_event` 的 `_mask_changes(masked)` 之後加 `_mask_notifications(masked)`；模組 docstring 的三項清單補第 4 項 `notifications[].info.{user, src_ip}`。

- [ ] **Step 4: 跑測試確認通過**

Run: `timeout 300 python3 -m pytest tests/test_siem_mask_pii.py -x -q`
Expected: 全綠。

- [ ] **Step 5: Commit**

```bash
git add src/siem/mask.py tests/test_siem_mask_pii.py
git commit -m "fix(siem): PII masking also covers notifications forwarded verbatim"
```

---

### Task 4: 接線：設定模型、dispatcher／tester、排程注入、i18n、文件

**Files:**
- Modify: `src/config_models.py:329`（`format` Literal）
- Modify: `src/siem/dispatcher.py:232-290`（`_formatter_for`、`build_dispatcher`）
- Modify: `src/scheduler/jobs.py:590`（呼叫 `build_dispatcher`）
- Modify: `src/siem/tester.py:48-58`（`_build_formatter`）
- Modify: `src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`（`gui_siem_format_help`、`sic_dest_config_help`）
- Modify: `docs/guide/siem.md:44-56`、`docs/guide/configuration.md:351`
- Test: `tests/test_siem_dispatcher.py`（追加）、`tests/test_config_models.py`（追加）

**Interfaces:**
- Consumes: Task 1／2 的 `PceNativeCEFFormatter(pce_fqdn=, pce_version=)`。
- Produces: `build_dispatcher(dest_cfg, session_factory, dlq_max_per_dest=10000, *, pce_fqdn: str = "", pce_version: str = "unknown")`；`_formatter_for(dest_cfg, *, pce_fqdn="", pce_version="unknown")`；`src/siem/tester.py::_build_formatter(fmt, *, pce_fqdn="", pce_version="unknown")`；新增 `src/siem/dispatcher.py::pce_identity(cm, api) -> tuple[str, str]`（回 `(fqdn, version)`）。

- [ ] **Step 1: 寫測試（先紅）**

```python
# tests/test_config_models.py 追加
@pytest.mark.parametrize("fmt", ["cef_pce", "syslog_cef_pce"])
def test_siem_destination_accepts_pce_native_formats(fmt):
    from src.config_models import SiemDestinationSettings
    assert SiemDestinationSettings(name="g", host="h", port=5514, format=fmt).format == fmt


# tests/test_siem_dispatcher.py 追加
def test_formatter_for_pce_native_formats_injects_identity():
    from src.config_models import SiemDestinationSettings
    from src.siem.dispatcher import _formatter_for
    from src.siem.formatters.cef_pce import PceNativeCEFFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    plain = _formatter_for(SiemDestinationSettings(name="g", host="h", port=1, format="cef_pce"),
                           pce_fqdn="pce.lab.local", pce_version="26.2.20")
    assert isinstance(plain, PceNativeCEFFormatter)
    assert plain.format_event({"event_type": "a.b", "status": "success", "severity": "info",
                               "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}}
                              ).startswith("CEF:0|Illumio|PCE|26.2.20|a.b.success|")
    wrapped = _formatter_for(SiemDestinationSettings(name="g", host="h", port=1, format="syslog_cef_pce"),
                             pce_fqdn="pce.lab.local", pce_version="26.2.20")
    assert isinstance(wrapped, SyslogWrappedFormatter)
    assert isinstance(wrapped._inner, PceNativeCEFFormatter)


def test_pce_identity_uses_api_host_and_product_version():
    from unittest.mock import MagicMock
    from src.siem.dispatcher import pce_identity
    cm = MagicMock(); cm.config = {"api": {"url": "https://pce.lab.local:8443"}}
    api = MagicMock(); api._api_get.return_value = (200, {"version": "26.2.20-2063"})
    assert pce_identity(cm, api) == ("pce.lab.local", "26.2.20-2063")
    api._api_get.side_effect = RuntimeError("down")
    assert pce_identity(cm, api) == ("pce.lab.local", "unknown")
    assert pce_identity(cm, None) == ("pce.lab.local", "unknown")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 python3 -m pytest tests/test_config_models.py tests/test_siem_dispatcher.py -x -q -k "pce_native or pce_identity"`
Expected: FAIL（Literal 不接受 `cef_pce`）

- [ ] **Step 3: 實作**

`src/config_models.py`：

```python
    format: Literal["cef", "json", "syslog_cef", "syslog_json", "cef_pce", "syslog_cef_pce"] = "cef"
```

`src/siem/dispatcher.py`：

```python
def pce_identity(cm, api) -> tuple[str, str]:
    """(fqdn, version) the cef_pce formatter stamps on every line. Best
    effort: the PCE's own syslog carries its real version, we ask
    /product_version once per dispatcher build and fall back to 'unknown'."""
    from urllib.parse import urlsplit
    url = str(((getattr(cm, "config", None) or {}).get("api") or {}).get("url") or "")
    fqdn = urlsplit(url).hostname or ""
    version = "unknown"
    if api is not None:
        try:
            status, body = api._api_get("/product_version")
            if status == 200 and isinstance(body, dict) and body.get("version"):
                version = str(body["version"])
        except Exception as exc:  # noqa: BLE001 — identity is cosmetic, never blocks dispatch
            logger.warning("product_version lookup failed, cef_pce header will say 'unknown': {}", exc)
    return fqdn, version


def _formatter_for(dest_cfg, *, pce_fqdn: str = "", pce_version: str = "unknown"):
    """Build formatter from SiemDestinationSettings."""
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.cef_pce import PceNativeCEFFormatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    fmt = dest_cfg.format
    if fmt == "cef":
        return CEFFormatter()
    if fmt == "syslog_cef":
        return SyslogWrappedFormatter(CEFFormatter())
    if fmt == "cef_pce":
        return PceNativeCEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version)
    if fmt == "syslog_cef_pce":
        return SyslogWrappedFormatter(PceNativeCEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version))
    if fmt == "syslog_json":
        return SyslogWrappedFormatter(NormalizedJSONFormatter())
    return NormalizedJSONFormatter()
```

`build_dispatcher` 簽章加 `*, pce_fqdn: str = "", pce_version: str = "unknown"` 並傳給 `_formatter_for`。

`src/scheduler/jobs.py:590` 附近：在建 dispatcher 前取一次 identity（該 job 已持有 `cm`；`api` 用 job 內既有的 ApiClient 變數，若該作用域沒有 ApiClient 就傳 `None`——先 `grep -n "ApiClient\|api = " src/scheduler/jobs.py` 確認）：

```python
                from src.siem.dispatcher import pce_identity
                fqdn, version = pce_identity(cm, api)
                ...
                with build_dispatcher(dest_cfg, sf, dlq_max_per_dest=siem_cfg.dlq_max_per_dest,
                                      pce_fqdn=fqdn, pce_version=version) as dispatcher:
```

`src/siem/tester.py::_build_formatter(fmt, *, pce_fqdn="", pce_version="unknown")` 加同樣兩個分支；`send_test_event` 呼叫處傳 `pce_fqdn=urlsplit(cm.config["api"]["url"]).hostname`（tester 若沒有 `cm`，就維持預設 `""`，並在 `_synthetic_event` 補 `"pce_fqdn": "illumio-ops-test"` 已存在的值即可）。

i18n（三個檔同鍵）：

- `gui_siem_format_help`（zh_TW）：在既有句尾加「cef_pce：對齊 PCE 原生 syslog 的 CEF（Signature ID 為 event_type.status、cs2/cs4 帶完整 resource_changes/notifications）。syslog_cef_pce：RFC5424 + cef_pce。」；en 對應英文。
- `sic_dest_config_help`：`format` 清單加兩行 `cef_pce     = CEF shaped like the PCE's own syslog export.` / `syslog_cef_pce = RFC5424 header + cef_pce.`（zh 對應）。

文件：`docs/guide/siem.md` 格式表加兩列，並加一節「`cef_pce` 與 PCE 直送的已知差異」（版本欄、`dst` fallback、流量 `in/out/cn1` 省略、流量為聚合語意）；`docs/guide/configuration.md:351` 的列舉加兩值。

- [ ] **Step 4: 跑測試與閘門**

```bash
timeout 600 python3 -m pytest tests/test_config_models.py tests/test_siem_dispatcher.py tests/test_siem_runtime.py tests/test_siem_e2e.py tests/test_cef_pce_formatter.py tests/test_i18n_menu_strings.py tests/test_i18n_quality.py -x -q
python3 scripts/audit_i18n_usage.py | tail -2
python3 scripts/check_doc_links.py | tail -1
```

Expected: 全綠、`Total: 0 finding(s)`、`OK — all local links resolve`。

- [ ] **Step 5: Commit**

```bash
git add src/config_models.py src/siem/dispatcher.py src/siem/tester.py src/scheduler/jobs.py src/i18n_zh_TW.json src/i18n_en.json src/i18n/data/zh_explicit.json docs/guide/siem.md docs/guide/configuration.md tests/test_config_models.py tests/test_siem_dispatcher.py
git commit -m "feat(siem): cef_pce and syslog_cef_pce destination formats"
```

---

### Task 5: 全套驗證、真機對帳、合併

**Files:**
- Create: `tools/siem_cef_diff.py`（Graylog 對帳腳本）
- 無 src 修改。

**Interfaces:**
- Consumes: Graylog API `http://172.16.15.105:9000`（token 由 `op read op://Lab/garylog/credential` 取得，只注入子行程）；測試機 `illumio-ops-test`（`/root/illumio-ops/config/config.json` 的 `siem.destinations[graylog].format`）。

- [ ] **Step 1: 全套測試**

Run: `timeout 1800 python3 -m pytest --tb=short -q 2>&1 | tail -5`
Expected: 0 failed（既有 e2e 若因環境無 Playwright 而 skip 可接受；任何 failed 回到對應 task）。

- [ ] **Step 2: 寫對帳腳本**

```python
#!/usr/bin/env python3
"""Join ops (input illumio-ops) and PCE-native (input illumio) CEF lines in
Graylog on event_href and print per-key diffs.  Usage:
    OP_TOKEN="$(op read op://Lab/garylog/credential)" python3 tools/siem_cef_diff.py --hours 2
Tolerated diffs (spec §6): header version, dst when the PCE JSON had FILTERED/none, dvchost."""
from __future__ import annotations
import argparse, base64, json, os, re, sys, urllib.parse, urllib.request

G = "http://172.16.15.105:9000"
TOLERATED = {"dst", "dvchost"}


def get(tok, path, **q):
    r = urllib.request.Request(G + path + "?" + urllib.parse.urlencode(q),
                               headers={"Authorization": "Basic " + base64.b64encode(f"{tok}:token".encode()).decode(),
                                        "Accept": "application/json", "X-Requested-By": "cli"})
    return json.load(urllib.request.urlopen(r, timeout=90))


def parse(line: str) -> tuple[list[str], dict[str, str]]:
    line = line[line.index("CEF:"):]
    head = line.split("|", 7)
    ext = head[7]
    keys = re.findall(r"(?:^| )([A-Za-z0-9_]+)=", ext)
    vals = {}
    for i, k in enumerate(keys):
        start = ext.index(f"{k}=", 0 if i == 0 else ext.index(f"{keys[i-1]}=") + 1) + len(k) + 1
        end = ext.index(f" {keys[i+1]}=", start) if i + 1 < len(keys) else len(ext)
        vals[k] = ext[start:end]
    return head[:7], vals


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=int, default=2); a = ap.parse_args()
    tok = os.environ["OP_TOKEN"]
    ins = {i["title"]: i["id"] for i in get(tok, "/api/system/inputs")["inputs"]}
    ops = get(tok, "/api/search/universal/relative", query=f'gl2_source_input:{ins["illumio-ops"]} AND message:CEF* AND message:audit_events',
              range=a.hours * 3600, limit=2000)["messages"]
    pce = get(tok, "/api/search/universal/relative", query=f'gl2_source_input:{ins["illumio"]} AND message:audit_events',
              range=(a.hours + 1) * 3600, limit=5000)["messages"]
    by_href = {}
    for m in pce:
        _, v = parse(m["message"]["message"]); by_href[v.get("cs1", "")] = m["message"]["message"]
    joined = mismatched = 0
    for m in ops:
        oh, ov = parse(m["message"]["message"])
        ref = by_href.get(ov.get("cs1", ""))
        if not ref:
            continue
        joined += 1
        ph, pv = parse(ref)
        diffs = []
        if oh[4:] != ph[4:]:
            diffs.append(("header", oh[4:], ph[4:]))
        if list(ov) != list(pv):
            diffs.append(("key-order", list(ov), list(pv)))
        for k in pv:
            if k in TOLERATED:
                continue
            if ov.get(k) != pv.get(k):
                diffs.append((k, ov.get(k), pv.get(k)))
        if diffs:
            mismatched += 1
            print("MISMATCH", ov.get("cs1"))
            for d in diffs:
                print("   ", d)
    print(f"joined={joined} mismatched={mismatched}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 部署測試機並切格式**

```bash
# 在 worktree 根目錄
git log --oneline -1
rsync -a --delete --exclude config --exclude data --exclude logs --exclude reports --exclude venv --exclude .git ./ illumio-ops-test:/root/illumio-ops/
ssh illumio-ops-test 'cd /root/illumio-ops && python3 - <<EOF
import json; f="config/config.json"; c=json.load(open(f))
for d in c["siem"]["destinations"]:
    if d["name"]=="graylog": d["format"]="cef_pce"
json.dump(c,open(f,"w"),indent=2,ensure_ascii=False); print([ (d["name"],d["format"]) for d in c["siem"]["destinations"]])
EOF
systemctl restart illumio-ops && sleep 5 && systemctl is-active illumio-ops'
```

（部署方式沿用專案慣例：`grep -n "rsync" docs/superpowers/plans/2026-09-04-phase3e-workbench.md` 可看到既有的部署指令；以該指令為準。）

- [ ] **Step 4: 一小時後對帳**

Run: `sleep 3600; OP_TOKEN="$(op read op://Lab/garylog/credential)" python3 tools/siem_cef_diff.py --hours 1`
Expected: `joined>=20 mismatched=0`。有 mismatch 就回到 Task 1／2 修規則、補測試、重部署，再對帳。

- [ ] **Step 5: 守門有效性**

暫時把測試機的 `format` 改回 `cef`，等 10 分鐘再跑對帳腳本，Expected: 全部 MISMATCH（header 與 key-order）；改回 `cef_pce`。

- [ ] **Step 6: Commit、合併、CI、記錄**

```bash
git add tools/siem_cef_diff.py
git commit -m "chore(siem): Graylog join script that diffs cef_pce against the PCE's own lines"
git push -u origin feat/siem-cef-pce
# fast-forward 合併到 main（主 checkout 被佔用時用 push refspec）
git fetch origin && git rebase origin/main && git push origin HEAD:main
gh run watch --exit-status
```

把對帳結果（joined／mismatched、容許差異清單）貼進 `docs/superpowers/plans/2026-09-11-cef-pce-native-format.md` 末尾的「驗收紀錄」段。

---

## 驗收紀錄（2026-09-12）

- Task 1–4 依序交付：`bf4c1f6a`（audit 格式器＋19 組 golden）、`083c70e7`（流量）、`9a576e89`（notifications 遮罩）、`5e944824`（接線）。
- 真機發現：Graylog 7.1 CEF input 把 `rt` 帶 ` +0000` 的整行丟掉、dispatch 表仍標 sent。五種變體實送定位後改為無時區毫秒形式（`19e19ab3`），重排被丟的 33 筆。
- 對帳：`tools/siem_cef_diff.py --hours 1` → `joined=57 mismatched=0`（`bce69e6b`）。守門檢查：把 `dst` 從容許清單拿掉 → 27 筆紅、exit 1。
- PCE 會對同一 event_href 送兩行（一行帶 request/requestMethod/reason、一行不帶），腳本取欄位最多的那行。
- 追加（使用者 2026-09-12 決定）：`cef`／`syslog_cef` 改為 ArcSight 方言（`60579654`）；無 ArcSight 可實測，僅單元測試與目視。
- 全套 pytest：4822 passed；`tests/test_cache_cli.py::test_cache_flush_json_output` 在乾淨 origin/main 亦失敗（Click 8.4 CliRunner 把 stderr 併入 stdout），與本案無關。
