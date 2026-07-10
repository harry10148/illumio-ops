# Port/Service Filter 與物件瀏覽 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FilterBar 新增「服務」與「Port」類別（PCE service 物件 pill＋手動 port 語法 pill），並為所有物件類別加上案 C 混合瀏覽（空輸入下拉快查＋modal 物件庫）。

**Architecture:** 沿用既有 filter-selector 骨架：新 filter key（`services`/`ex_services` 存 href、`ports`/`ex_ports` 存 token 字串）進 capability matrix 走 native，查詢時經 `service_ports_cache` 展開成 PCE `services.include/exclude` 條目；cache 讀取路徑在組裝層展開、df_filter 比對；suggest/browse 端點由 `filter_object_cache` module 快取供貨。

**Tech Stack:** Flask blueprint、cachetools TTLCache、pandas、vanilla JS（CSP no-inline、data-on-* dispatcher）、questionary、pytest。

**Spec:** `docs/superpowers/specs/2026-07-10-port-service-filter-and-browse-design.md`

## Global Constraints

- 一律不用 emoji；commit message 用英文 conventional commits。
- 程式註解風格跟隨各檔案既有寫法（多為繁中）。
- CSP：JS 不得有 inline handler（`onclick=` 禁止），事件走 `data-on-*`/`data-action` 委派、handler 掛 `window.*`。
- i18n：每個新 `data-i18n` 鍵必須同時進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`。
- 過長內容 ellipsis 處理，不可無聲截斷（專案報表規範）。
- 舊 filter key（scalar `port`/`proto`/`ex_port`/`port_range(s)`）讀取端保留，零遷移。
- 完成每個 task 後跑該 task 的測試；合併前跑全套 `pytest -q`。

---

### Task 1: 共用 port token 解析器 `src/port_token.py`

port token（`80`、`443/tcp`、`1000-2000`、`1000-2000/tcp`）解析有 4 個消費者（labels payload 組裝、df_filter、CLI picker、GUI 後端驗證），抽成無依賴純模組；`LabelResolver._parse_port_range_entry` 改為委派並藉此獲得「單一 port＋proto 別名」新能力。

**Files:**
- Create: `src/port_token.py`
- Modify: `src/api/labels.py:101-133`（`_parse_port_range_entry` 改委派）
- Test: `tests/test_port_token.py`

**Interfaces:**
- Produces: `parse_port_token(value, default_proto=None) -> dict | None`。回傳 `{"port": int}`、`{"port": int, "proto": int}`、`{"port": int, "to_port": int[, "proto": int]}`、`{"proto": int}`（tuple/list 形式僅範圍）；無法解析回 `None`。proto 接受數字與別名 `tcp/udp/icmp/icmpv6`（大小寫不敏感）。port 界限 1-65535。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_port_token.py
"""parse_port_token：port token（單一/範圍/proto 別名）解析的行為契約。"""
import pytest

from src.port_token import parse_port_token


@pytest.mark.parametrize("text,expected", [
    ("80", {"port": 80}),
    ("443/tcp", {"port": 443, "proto": 6}),
    ("53/UDP", {"port": 53, "proto": 17}),
    ("53/17", {"port": 53, "proto": 17}),
    ("1000-2000", {"port": 1000, "to_port": 2000}),
    ("1000-2000/tcp", {"port": 1000, "to_port": 2000, "proto": 6}),
    ("2000-1000/tcp", {"port": 1000, "to_port": 2000, "proto": 6}),  # 顛倒自動校正（沿用舊行為）
    ("8080-8080", {"port": 8080}),  # 退化範圍收斂成單一 port
])
def test_valid_tokens(text, expected):
    assert parse_port_token(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "0", "65536", "80/xyz", "80-", "-80", "1-70000", "80//tcp"])
def test_invalid_tokens(text):
    assert parse_port_token(text) is None


def test_tuple_forms_preserved():
    # 舊 _parse_port_range_entry 的 list/tuple 形式必須保留
    assert parse_port_token((80, 90)) == {"port": 80, "to_port": 90}
    assert parse_port_token((80, 90, 6)) == {"port": 80, "to_port": 90, "proto": 6}
    assert parse_port_token((80, 90, "udp")) == {"port": 80, "to_port": 90, "proto": 17}
    assert parse_port_token((1, 2, 3, 4)) is None


def test_colon_range_form_preserved():
    # 舊語法 "80-90:6"（: 分隔 proto，僅限含 - 的範圍）保留
    assert parse_port_token("80-90:6") == {"port": 80, "to_port": 90, "proto": 6}


def test_default_proto():
    assert parse_port_token("80-90", default_proto=6) == {"port": 80, "to_port": 90, "proto": 6}


def test_labels_delegation():
    from src.api.labels import LabelResolver
    assert LabelResolver._parse_port_range_entry("443/tcp") == {"port": 443, "proto": 6}
    assert LabelResolver._parse_port_range_entry("80-90", default_proto=17) == {"port": 80, "to_port": 90, "proto": 17}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_port_token.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.port_token'`

- [ ] **Step 3: 實作 `src/port_token.py`**

```python
"""Port token 解析（純函式、零依賴）。

消費者：labels 的 native payload 組裝、report/df_filter 的 cache 路徑比對、
CLI object_picker 的手動輸入驗證。語法：'80'、'443/tcp'、'1000-2000'、
'1000-2000/tcp'、'80-90:6'（舊 : 分隔僅限範圍）；proto 收數字或別名。
"""
from __future__ import annotations

PROTO_NAME_TO_NUM = {"tcp": 6, "udp": 17, "icmp": 1, "icmpv6": 58}


def _coerce_proto(proto):
    if proto in (None, ""):
        return None, True
    if isinstance(proto, str) and proto.strip().lower() in PROTO_NAME_TO_NUM:
        return PROTO_NAME_TO_NUM[proto.strip().lower()], True
    try:
        return int(proto), True
    except (TypeError, ValueError):
        return None, False


def parse_port_token(value, default_proto=None):
    """token → services.include/exclude 條目 dict；無法解析回 None。

    回傳形狀：{"port": n}、{"port": n, "proto": p}、
    {"port": n, "to_port": m[, "proto": p]}。port 界限 1-65535。
    """
    proto = default_proto
    if isinstance(value, (list, tuple)):
        if len(value) == 2:
            start, end = value
        elif len(value) == 3:
            start, end, proto = value
        else:
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        range_part = text
        if "/" in text:
            range_part, proto_part = text.split("/", 1)
            proto = proto_part
        elif ":" in text and text.count(":") == 1 and "-" in text:
            range_part, proto_part = text.split(":", 1)
            proto = proto_part
        if "-" in range_part:
            start, end = [part.strip() for part in range_part.split("-", 1)]
        else:
            start = end = range_part.strip()  # 單一 port（'80'、'443/tcp'）
    try:
        start = int(start)
        end = int(end)
    except (TypeError, ValueError):
        return None
    if start > end:
        start, end = end, start
    if not (1 <= start <= 65535 and 1 <= end <= 65535):
        return None
    entry = {"port": start} if start == end else {"port": start, "to_port": end}
    proto_num, ok = _coerce_proto(proto)
    if not ok:
        return None
    if proto_num is not None:
        entry["proto"] = proto_num
    return entry
```

- [ ] **Step 4: `labels.py` 改委派**

把 `src/api/labels.py` 的 `_parse_port_range_entry`（`@staticmethod`，line 101-133）整個函式體換成：

```python
    @staticmethod
    def _parse_port_range_entry(value, default_proto=None):
        from src.port_token import parse_port_token
        return parse_port_token(value, default_proto=default_proto)
```

- [ ] **Step 5: 跑測試與相關迴歸**

Run: `pytest tests/test_port_token.py -q && pytest tests/ -q -k "traffic_query or analyzer_object or df_filter"`
Expected: 全 PASS（`port_range(s)` 既有測試不受影響——新行為是超集）

- [ ] **Step 6: Commit**

```bash
git add src/port_token.py src/api/labels.py tests/test_port_token.py
git commit -m "feat: add shared port token parser with single-port and proto-alias support"
```

---

### Task 2: service 快取擴充與 `resolve_service_entries`

`service_ports_cache` 現況只收有 port 的 `service_ports` 條目（`labels.py:251-272`，`if port_defs:` 守門）。擴充成完整條目來源，並提供查詢時展開的解析入口。

**Files:**
- Modify: `src/api/labels.py:247-272`（update_label_cache 的 services 迴圈）
- Modify: `src/api/labels.py`（`resolve_service_str` 後新增 `resolve_service_entries` 方法）
- Test: `tests/test_service_entries.py`

**Interfaces:**
- Consumes: `self._client.service_ports_cache`（dict：href → entry dicts）、`self._client.label_cache`、既有的快取填充路徑（`update_label_cache`；查詢側消費者呼叫 `resolve_service_entries` 前由 ApiClient 既有 lazy-refresh 邏輯保證已填——與 `resolve_service_str` 同前提，不另發明 ensure 機制）。
- Produces: `LabelResolver.resolve_service_entries(value) -> list[dict] | None`。輸入 service href（draft 或 active 形皆可）；回傳 `services.include` 條目清單（`{"port",...}`、`{"proto",...}`、`{"windows_service_name",...}`、`{"process_name",...}`）；快取查無（被刪/未知）回 `None`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_service_entries.py
"""service_ports_cache 完整條目擴充 + resolve_service_entries 行為契約。"""
from unittest.mock import MagicMock

from src.api.labels import LabelResolver


def _resolver_with_cache(cache):
    client = MagicMock()
    client.service_ports_cache = cache
    return LabelResolver(client)


def test_resolve_service_entries_hit():
    r = _resolver_with_cache({"/orgs/1/sec_policy/draft/services/9": [{"port": 80, "proto": 6}]})
    assert r.resolve_service_entries("/orgs/1/sec_policy/draft/services/9") == [{"port": 80, "proto": 6}]


def test_resolve_service_entries_miss_returns_none():
    r = _resolver_with_cache({})
    assert r.resolve_service_entries("/orgs/1/sec_policy/active/services/404") is None


def test_cache_build_includes_windows_and_protocol_only_entries():
    """update_label_cache 的 services 段落改用 _service_entry_defs 建條目：
    windows_services 與純 proto 條目都要進 service_ports_cache。"""
    svc = {
        "name": "Mixed",
        "href": "/orgs/1/sec_policy/draft/services/7",
        "service_ports": [
            {"port": 443, "proto": 6},
            {"proto": 1},  # ICMP：無 port
        ],
        "windows_services": [
            {"service_name": "wuauserv"},
            {"process_name": "svchost.exe"},
            {"port": 3389, "proto": 6, "service_name": "TermService"},
        ],
    }
    defs = LabelResolver._service_entry_defs(svc)
    assert {"port": 443, "proto": 6} in defs
    assert {"proto": 1} in defs
    assert {"windows_service_name": "wuauserv"} in defs
    assert {"process_name": "svchost.exe"} in defs
    # 名稱優先於 port（同一 windows 條目不重複展開）
    assert {"windows_service_name": "TermService"} in defs
    assert len(defs) == 5


def test_service_entry_defs_empty_service():
    assert LabelResolver._service_entry_defs({"name": "Empty", "href": "/x", "service_ports": []}) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_service_entries.py -q`
Expected: FAIL，`AttributeError: ... no attribute 'resolve_service_entries'`（及 `_service_entry_defs`）

- [ ] **Step 3: 實作**

(a) 在 `labels.py` 的 `_parse_port_range_entry` 附近新增 staticmethod：

```python
    @staticmethod
    def _service_entry_defs(svc):
        """service 物件 → services.include 條目清單（查詢用完整形，含
        windows_services 與純 proto 條目；空 service 回 []）。"""
        defs = []
        for sp in svc.get("service_ports") or []:
            p = sp.get("port")
            if p:
                pd = {"port": p}
                if sp.get("proto") is not None:
                    pd["proto"] = sp["proto"]
                if sp.get("to_port"):
                    pd["to_port"] = sp["to_port"]
                defs.append(pd)
            elif sp.get("proto") is not None:
                defs.append({"proto": sp["proto"]})
        for w in svc.get("windows_services") or []:
            if w.get("service_name"):
                defs.append({"windows_service_name": w["service_name"]})
            elif w.get("process_name"):
                defs.append({"process_name": w["process_name"]})
            elif w.get("port"):
                pd = {"port": w["port"]}
                if w.get("proto") is not None:
                    pd["proto"] = w["proto"]
                defs.append(pd)
        return defs
```

(b) `update_label_cache` 的 services 迴圈（`labels.py:248-272`）：**顯示字串邏輯（`ports` list 與 `val`）保持不動**，把 `port_defs` 的組裝改為呼叫 `_service_entry_defs(i)`：

```python
                if s_services == 200 and d_services:
                    for i in d_services:
                        name = i.get('name')
                        ports = []
                        for svc in i.get('service_ports', []):
                            p = svc.get('port')
                            if p:
                                proto = "UDP" if svc.get('proto') == 17 else "TCP"
                                top = f"-{svc['to_port']}" if svc.get('to_port') else ""
                                ports.append(f"{proto}/{p}{top}")
                        port_str = f" ({','.join(ports)})" if ports else ""
                        val = f"{name}{port_str}"
                        c.label_cache[i['href']] = val
                        c.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        # 查詢用完整條目（含 windows_services、純 proto；filter
                        # 的 service 展開與 per-rule query 共用）
                        port_defs = LabelResolver._service_entry_defs(i)
                        if port_defs:
                            c.service_ports_cache[i['href']] = port_defs
                            c.service_ports_cache[i['href'].replace('/draft/', '/active/')] = port_defs
```

(c) `resolve_service_str` 方法後新增：

```python
    def resolve_service_entries(self, value):
        """service href → services.include/exclude 條目清單（filter 的
        services/ex_services key 查詢時展開用）。查無（物件被刪、快取未含）
        回 None，由呼叫端走 unresolved 降級。"""
        c = self._client
        return c.service_ports_cache.get(str(value).strip())
```

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_service_entries.py -q && pytest tests/ -q -k "label or service"`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/labels.py tests/test_service_entries.py
git commit -m "feat: cache full service entry definitions and add resolve_service_entries"
```

---

### Task 3: 查詢層 `ports`/`ex_ports`（native＋fallback）

**Files:**
- Modify: `src/api/traffic_query.py:53-63`（capability matrix）、`:436-467`（services 組裝區）、`_flow_matches_filters`（`:803-825` port 區與 `:885-891` ex_port 區之後）
- Test: `tests/test_traffic_query_ports_services.py`（新檔，本 task 先建 ports 部分）

**Interfaces:**
- Consumes: `parse_port_token`（Task 1）。
- Produces: filter key `ports`/`ex_ports`（list[str] token）→ `payload["services"]["include"/"exclude"]` 條目；fallback 路徑 `_flow_matches_filters` 支援同名 key（include：條目間 OR、無一命中即 False；exclude：任一命中即 False；無法解析的 token 使該 key 整體 unresolved——native 端；fallback 端 include 遇全數無法解析視為不命中（fail-closed）、exclude 略過無法解析值）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_traffic_query_ports_services.py
"""ports/ex_ports 與 services/ex_services filter key 的 native payload 與 fallback 行為。"""
from unittest.mock import MagicMock, patch

import pytest

from src.api_client import ApiClient


@pytest.fixture
def client():
    cm = MagicMock()
    cm.config = {"pce": {"fqdn": "pce", "port": 8443, "org_id": 1,
                         "api_key": "k", "api_secret": "s"}}
    with patch.object(ApiClient, "__init__", lambda self, cm: None):
        c = ApiClient(cm)
    # 最小可用內部狀態（比照 tests/test_analyzer_object_filters.py 的裸建樣式）
    from src.api.labels import LabelResolver
    from src.api.traffic_query import TrafficQueryBuilder
    c.label_cache = {}
    c.service_ports_cache = {}
    c._labels = LabelResolver(c)
    c._traffic = TrafficQueryBuilder(c)
    return c


def _payload(client, filters):
    return client._traffic._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"], filters)


def test_ports_include_tokens(client):
    p = _payload(client, {"ports": ["80", "443/tcp", "1000-2000/udp"]})
    assert {"port": 80} in p["services"]["include"]
    assert {"port": 443, "proto": 6} in p["services"]["include"]
    assert {"port": 1000, "to_port": 2000, "proto": 17} in p["services"]["include"]


def test_ex_ports_exclude_tokens(client):
    p = _payload(client, {"ex_ports": ["22", "3389/tcp"]})
    assert {"port": 22} in p["services"]["exclude"]
    assert {"port": 3389, "proto": 6} in p["services"]["exclude"]


def test_ports_invalid_token_unresolved(client):
    p = _payload(client, {"ports": ["80", "notaport"]})
    assert p["services"]["include"] == []
    diag = client.last_traffic_query_diagnostics
    assert "ports" in diag["unresolved_native_filters"]


def test_ports_capability_native(client):
    spec = client._traffic.build_traffic_query_spec({"ports": ["80"], "ex_ports": ["22"]})
    assert "ports" in spec.native_filters and "ex_ports" in spec.native_filters
```

（fallback 的 `_flow_matches_filters` 斷言依該函式在檔內的實際呼叫形式補進同檔，樣式仿 `tests/test_analyzer_object_filters.py` 既有 fallback 測試：構造 `flow = {"src": {...}, "dst": {...}, "service": {"port": 443, "proto": 6}}`，斷言 `{"ports": ["443/tcp"]}` 命中、`{"ports": ["80"]}` 不命中、`{"ex_ports": ["443"]}` 剔除。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_traffic_query_ports_services.py -q`
Expected: FAIL（`ports` 進 fallback、payload 無條目）

注意：若 fixture 的裸建樣式與 `_build_native_traffic_payload` 對 client 內部狀態的實際需求不合（如 diagnostics 屬性初始化），以 `tests/test_analyzer_object_filters.py` 的既有 fixture 為準修 fixture，不改產品碼語意。

- [ ] **Step 3: 實作**

(a) capability matrix（`_TRAFFIC_FILTER_CAPABILITIES`，接在 `ex_port` 之後）：

```python
    "ports": {"execution": "native", "min_pce_version": "21.2", "notes": "Port tokens (80, 443/tcp, 1000-2000/tcp) pushed to services.include."},
    "ex_ports": {"execution": "native", "min_pce_version": "21.2", "notes": "Port tokens pushed to services.exclude."},
```

(b) `_build_native_traffic_payload`：在 `ex_port` 區塊（`:436-444`）之後插入：

```python
        for key, target in (("ports", "include"), ("ex_ports", "exclude")):
            values = native_filters.get(key)
            if not values:
                continue
            entries = values if isinstance(values, (list, tuple)) else [values]
            parsed_entries = []
            unresolved = False
            for entry in entries:
                parsed = parse_port_token(entry)
                if not parsed:
                    unresolved = True
                    break
                parsed_entries.append(parsed)
            if unresolved:
                _record_unresolved(key, spec.native_filters.get(key))
            else:
                payload["services"][target].extend(parsed_entries)
                _record_consumed(key, spec.native_filters.get(key))
            _consume_keys((key,))
```

檔頭 import 區加：`from src.port_token import parse_port_token`。

(c) `_flow_matches_filters`：在既有 `port_filter` 區塊（`:803`）後加 include 比對、在 `ex_port` 區塊（`:885`）後加 exclude 比對：

```python
        ports_inc = filters.get('ports')
        if ports_inc:
            ports_inc = ports_inc if isinstance(ports_inc, list) else [ports_inc]
            tokens = [t_ for t_ in (parse_port_token(v) for v in ports_inc) if t_]
            # fail-closed：有條件但全數無法解析 → 不命中
            if not any(_port_entry_hit(svc, flow, t_) for t_ in tokens):
                return False
```

```python
        ports_exc = filters.get('ex_ports')
        if ports_exc:
            ports_exc = ports_exc if isinstance(ports_exc, list) else [ports_exc]
            for t_ in (parse_port_token(v) for v in ports_exc):
                if t_ and _port_entry_hit(svc, flow, t_):
                    return False
```

module 層新增 helper（放在 `_flow_matches_filters` 所屬類別/函式可及處，與 `_iplist_hit` 等既有 helper 同層）：

```python
def _port_entry_hit(svc, flow, entry):
    """flow 的 service port/proto 是否命中一個 parse_port_token 條目。"""
    try:
        flow_port = svc.get('port') or flow.get('dst_port')
        flow_proto = svc.get('proto') or flow.get('proto')
        if "port" in entry:
            if flow_port is None:
                return False
            p = int(flow_port)
            if not (entry["port"] <= p <= entry.get("to_port", entry["port"])):
                return False
        if entry.get("proto") is not None:
            if flow_proto is None or int(flow_proto) != int(entry["proto"]):
                return False
        return True
    except (TypeError, ValueError):
        return False
```

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_traffic_query_ports_services.py -q && pytest tests/ -q -k "traffic or analyzer"`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/traffic_query.py tests/test_traffic_query_ports_services.py
git commit -m "feat: add ports/ex_ports filter keys with native and fallback matching"
```

---

### Task 4: 查詢層 `services`/`ex_services`（href 查詢時展開）

**Files:**
- Modify: `src/api/traffic_query.py`（capability matrix、`_build_native_traffic_payload` services 區、`_flow_matches_filters`、module 常數）
- Test: `tests/test_traffic_query_ports_services.py`（擴充）

**Interfaces:**
- Consumes: `labels.resolve_service_entries(href)`（Task 2）、`_port_entry_hit`（Task 3）。
- Produces: filter key `services`/`ex_services`（list[str] href）→ 展開條目進 `services.include/exclude`；`_SERVICE_EXPANSION_CAP = 200` 超限整 key 降級；查無 href 或空展開走 `_record_unresolved`。

- [ ] **Step 1: 寫失敗測試（附加到 Task 3 測試檔）**

```python
SVC_HREF = "/orgs/1/sec_policy/active/services/10"


def test_services_expand_to_entries(client):
    client.service_ports_cache[SVC_HREF] = [
        {"port": 80, "proto": 6}, {"port": 443, "proto": 6},
        {"windows_service_name": "wuauserv"},
    ]
    p = _payload(client, {"services": [SVC_HREF]})
    assert {"port": 80, "proto": 6} in p["services"]["include"]
    assert {"port": 443, "proto": 6} in p["services"]["include"]
    assert {"windows_service_name": "wuauserv"} in p["services"]["include"]


def test_ex_services_expand_to_exclude(client):
    client.service_ports_cache[SVC_HREF] = [{"port": 22, "proto": 6}]
    p = _payload(client, {"ex_services": [SVC_HREF]})
    assert {"port": 22, "proto": 6} in p["services"]["exclude"]


def test_services_unknown_href_unresolved(client):
    p = _payload(client, {"services": ["/orgs/1/sec_policy/active/services/404"]})
    assert p["services"]["include"] == []
    assert "services" in client.last_traffic_query_diagnostics["unresolved_native_filters"]


def test_services_expansion_cap(client):
    client.service_ports_cache[SVC_HREF] = [{"port": i} for i in range(1, 302)]
    p = _payload(client, {"services": [SVC_HREF]})
    assert p["services"]["include"] == []
    assert "services" in client.last_traffic_query_diagnostics["unresolved_native_filters"]


def test_services_fallback_flow_match(client):
    client.service_ports_cache[SVC_HREF] = [{"port": 443, "proto": 6}]
    flow = {"src": {}, "dst": {}, "service": {"port": 443, "proto": 6}}
    assert client._traffic._flow_matches_filters(flow, {"services": [SVC_HREF]})
    assert not client._traffic._flow_matches_filters(flow, {"ex_services": [SVC_HREF]})
```

（`_flow_matches_filters` 的實際呼叫簽章以檔內定義為準；若為 module 函式或帶額外參數，照 `tests/test_analyzer_object_filters.py` 既有用法調整呼叫。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_traffic_query_ports_services.py -q`
Expected: 新增測試 FAIL

- [ ] **Step 3: 實作**

(a) capability matrix 加：

```python
    "services": {"execution": "native", "min_pce_version": "21.2", "notes": "Service hrefs expanded via service_ports_cache into services.include."},
    "ex_services": {"execution": "native", "min_pce_version": "21.2", "notes": "Service hrefs expanded via service_ports_cache into services.exclude."},
```

(b) module 常數（`_LABEL_OR_EXPANSION_CAP` 旁）：

```python
_SERVICE_EXPANSION_CAP = 200  # service 展開條目數上限，超過整 key 降級 fallback
```

(c) `_build_native_traffic_payload`：Task 3 的 ports 區塊之後插入：

```python
        for key, target in (("services", "include"), ("ex_services", "exclude")):
            values = native_filters.get(key)
            if not values:
                continue
            hrefs = values if isinstance(values, (list, tuple)) else [values]
            expanded = []
            unresolved = False
            for href in hrefs:
                entries = labels.resolve_service_entries(href)
                if not entries:
                    # 查無（被刪）或空 service：不送空條件，走 unresolved 降級
                    unresolved = True
                    break
                expanded.extend(entries)
            if unresolved or len(expanded) > _SERVICE_EXPANSION_CAP:
                if len(expanded) > _SERVICE_EXPANSION_CAP:
                    logger.warning(
                        "Service expansion exceeds cap ({} > {}); falling back to client-side",
                        len(expanded), _SERVICE_EXPANSION_CAP)
                _record_unresolved(key, spec.native_filters.get(key))
            else:
                payload["services"][target].extend(expanded)
                _record_consumed(key, spec.native_filters.get(key))
            _consume_keys((key,))
```

(d) `_flow_matches_filters`：Task 3 的 ports 比對之後加（`self`/client 取得依該函式實際形式；名稱型條目在 fallback 無法比對 → 略過該條目，僅以 port/proto 條目比對；整個 service 只有名稱型條目時 include 視為不命中——fail-closed）：

```python
        for key, is_exclude in (("services", False), ("ex_services", True)):
            vals = filters.get(key)
            if not vals:
                continue
            vals = vals if isinstance(vals, list) else [vals]
            hit = False
            for href in vals:
                entries = self._client._labels.resolve_service_entries(href) or []
                port_entries = [e for e in entries if "port" in e or "proto" in e]
                if any(_port_entry_hit(svc, flow, e) for e in port_entries):
                    hit = True
                    break
            if is_exclude and hit:
                return False
            if not is_exclude and not hit:
                return False
```

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_traffic_query_ports_services.py -q && pytest tests/ -q -k "traffic or analyzer"`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/traffic_query.py tests/test_traffic_query_ports_services.py
git commit -m "feat: add services/ex_services filter keys with query-time expansion"
```

---

### Task 5: cache 讀取路徑（df 展開＋df_filter 比對）

**Files:**
- Modify: `src/api/labels.py`（`expand_object_filters_for_df`，`:509` 起）
- Modify: `src/report/df_filter.py`（新 `_port_entries_mask` 與 `apply_df_traffic_filters` 接線）
- Test: `tests/test_df_filter.py`（擴充）、`tests/test_object_filter_df_expand.py`（擴充）

**Interfaces:**
- Consumes: `resolve_service_entries`（Task 2）、`parse_port_token`（Task 1）。
- Produces: `expand_object_filters_for_df` 新增內部 key `_svc_port_entries` / `_ex_svc_port_entries`（list[dict]，僅 port/proto 型條目；名稱型條目略過並 log warning）；`df_filter` 消費 `ports`/`ex_ports`（token 字串）與上述內部 key。

- [ ] **Step 1: 寫失敗測試**

`tests/test_df_filter.py` 附加（既有測試建 df 的樣式照檔內慣例，欄位含 `port`/`proto`）：

```python
def _ports_df():
    import pandas as pd
    return pd.DataFrame([
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 80, "proto": "TCP"},
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "proto": "TCP"},
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 1500, "proto": "UDP"},
    ])


def test_ports_tokens_include_or():
    from src.report.df_filter import apply_df_traffic_filters
    out = apply_df_traffic_filters(_ports_df(), {"ports": ["80", "1000-2000/udp"]})
    assert sorted(out["port"].tolist()) == [80, 1500]


def test_ex_ports_exclude():
    from src.report.df_filter import apply_df_traffic_filters
    out = apply_df_traffic_filters(_ports_df(), {"ex_ports": ["443/tcp"]})
    assert 443 not in out["port"].tolist()


def test_svc_port_entries_internal_keys():
    from src.report.df_filter import apply_df_traffic_filters
    out = apply_df_traffic_filters(_ports_df(), {"_svc_port_entries": [{"port": 443, "proto": 6}]})
    assert out["port"].tolist() == [443]
    out2 = apply_df_traffic_filters(_ports_df(), {"_ex_svc_port_entries": [{"port": 443, "proto": 6}]})
    assert 443 not in out2["port"].tolist()


def test_ports_include_all_invalid_fail_closed():
    from src.report.df_filter import apply_df_traffic_filters
    out = apply_df_traffic_filters(_ports_df(), {"ports": ["nonsense"]})
    assert out.empty
```

`tests/test_object_filter_df_expand.py` 附加（mock client 樣式照檔內既有測試）：

```python
def test_expand_services_to_port_entries():
    # 依檔內既有 mock client 樣式構造 client：service_ports_cache 帶
    # {"/x/services/1": [{"port": 443, "proto": 6}, {"windows_service_name": "w"}]}
    # 呼叫 labels.expand_object_filters_for_df({"services": ["/x/services/1"]})
    # 斷言：結果含 _svc_port_entries == [{"port": 443, "proto": 6}]（名稱型條目被略過）
    ...
```

（以檔內既有 fixture 寫完整；斷言如註解所列，不得留 `...` 進最終測試碼。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_df_filter.py tests/test_object_filter_df_expand.py -q`
Expected: 新增測試 FAIL

- [ ] **Step 3: 實作**

(a) `labels.py` `expand_object_filters_for_df`：在 `obj_keys` 檢查前加 services 展開（同函式「淺拷貝、底線內部 key」慣例）：

```python
        svc_keys = (("services", "_svc_port_entries"), ("ex_services", "_ex_svc_port_entries"))
        has_svc = any(filters.get(k) for k, _ in svc_keys) if filters else False
```

並把既有「無物件 key 即原樣回傳」條件改為 `if not filters or (not any(...) and not has_svc): return filters`。展開段（與 iplist/workload 展開同一個回傳 dict 組裝處）：

```python
        for key, internal in svc_keys:
            vals = filters.get(key)
            if not vals:
                continue
            vals = vals if isinstance(vals, list) else [vals]
            entries = []
            for href in vals:
                for e in (self.resolve_service_entries(href) or []):
                    if "port" in e or "proto" in e:
                        entries.append(e)
                    else:
                        logger.warning(
                            "Cache path cannot match name-based service entry {}; skipped", e)
            if entries:
                out[internal] = entries
```

（`out` 為該函式既有的淺拷貝結果 dict 名稱，照檔內實際變數名。）

(b) `df_filter.py`：`_PROTO_ALIAS` 下方新增：

```python
def _port_entries_mask(df: pd.DataFrame, entries: list) -> pd.Series:
    """parse_port_token/service 展開條目清單 → 條目間 OR 的命中 mask。"""
    m = pd.Series(False, index=df.index)
    if "port" not in df.columns:
        return m
    ports = pd.to_numeric(df["port"], errors="coerce")
    for e in entries:
        em = pd.Series(True, index=df.index)
        if "port" in e:
            em &= ports.ge(e["port"]) & ports.le(e.get("to_port", e["port"]))
        if e.get("proto") is not None and "proto" in df.columns:
            want = _PROTO_ALIAS.get(str(e["proto"]), str(e["proto"])).upper()
            em &= df["proto"].astype(str).str.upper() == want
        if "port" not in e and e.get("proto") is None:
            continue  # 空條目不得全命中
        m |= em
    return m
```

`apply_df_traffic_filters` 的既有 `port`/`ex_port` 區塊（`:158-169`）之後接線：

```python
    from src.port_token import parse_port_token

    ports_inc = [s for s in (filters.get("ports") or []) if s]
    if ports_inc:
        tokens = [t for t in (parse_port_token(v) for v in ports_inc) if t]
        mask &= _port_entries_mask(df, tokens)  # 全數無法解析 → tokens 空 → mask False（fail-closed）
    for v in (filters.get("ex_ports") or []):
        t = parse_port_token(v)
        if t:
            mask &= ~_port_entries_mask(df, [t])

    svc_inc = filters.get("_svc_port_entries")
    if svc_inc:
        mask &= _port_entries_mask(df, svc_inc)
    svc_exc = filters.get("_ex_svc_port_entries")
    if svc_exc:
        mask &= ~_port_entries_mask(df, svc_exc)
```

（import 移至檔頭 import 區。）

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_df_filter.py tests/test_object_filter_df_expand.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/labels.py src/report/df_filter.py tests/test_df_filter.py tests/test_object_filter_df_expand.py
git commit -m "feat: cache-path service expansion and port token matching in df_filter"
```

---

### Task 6: suggest 端點與 filter_object_cache 的 service 類型

**Files:**
- Modify: `src/gui/filter_object_cache.py`（`_service_summary`、`search_cached_objects`、`_match_named` 摘要參數化）
- Modify: `src/gui/routes/filter_objects.py:11-12`（`_CACHED_TYPES`/`_ALL_TYPES`）
- Test: `tests/test_filter_object_cache.py`、`tests/test_gui_filter_suggest.py`（擴充）

**Interfaces:**
- Consumes: `ApiClient.get_services()`（既有，`src/api_client.py:828`；預設 active）。
- Produces: suggest 回應多 `service` 類別：`{"items": [{"name", "href", "summary"}], "truncated": bool}`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_filter_object_cache.py` 附加（mock api 樣式照檔內既有）：

```python
def test_search_service_with_summary():
    api = MagicMock()
    api.get_services.return_value = [
        {"name": "Web-Ports", "href": "/s/1",
         "service_ports": [{"port": 80, "proto": 6}, {"port": 443, "proto": 6}]},
        {"name": "RDP", "href": "/s/2",
         "service_ports": [{"port": 3389, "proto": 6}],
         "windows_services": [{"service_name": "TermService"}]},
    ]
    from src.gui.filter_object_cache import invalidate_object_cache, search_cached_objects
    invalidate_object_cache()
    out = search_cached_objects(api, "web", ["service"], 10)
    assert out["service"]["items"] == [
        {"name": "Web-Ports", "href": "/s/1", "summary": "tcp/80, tcp/443"}]


def test_service_summary_truncates_with_ellipsis():
    from src.gui.filter_object_cache import _service_summary
    svc = {"service_ports": [{"port": p, "proto": 6} for p in (1, 2, 3, 4, 5)]}
    s = _service_summary(svc)
    assert s.endswith(", …") and s.count(",") == 3  # 3 段 + 省略
```

`tests/test_gui_filter_suggest.py` 附加：types 含 `service` 時回 service 群組、離線降級 `pce_unreachable`（照檔內既有離線測試樣式）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_filter_object_cache.py tests/test_gui_filter_suggest.py -q`
Expected: 新增測試 FAIL

- [ ] **Step 3: 實作**

(a) `filter_object_cache.py`：`_ip_list_summary` 下方新增，並把 `_match_named` 的 `with_summary` 參數改為 `summary_fn=None`（呼叫端同步改：iplist 傳 `summary_fn=_ip_list_summary`）：

```python
_PROTO_NUM_TO_NAME = {6: "tcp", 17: "udp", 1: "icmp", 58: "icmpv6"}


def _service_summary(svc: dict) -> str:
    """service 條目組顯示摘要，最多 3 段，超出以 … 提示（不無聲截斷）。"""
    parts = []
    for sp in svc.get("service_ports") or []:
        p = sp.get("port")
        proto = _PROTO_NUM_TO_NAME.get(sp.get("proto"), str(sp.get("proto") or ""))
        if p:
            top = f"-{sp['to_port']}" if sp.get("to_port") else ""
            parts.append(f"{proto}/{p}{top}" if proto else f"{p}{top}")
        elif sp.get("proto") is not None:
            parts.append(proto)
    for w in svc.get("windows_services") or []:
        n = w.get("service_name") or w.get("process_name")
        if n:
            parts.append(n)
    return ", ".join(parts[:3]) + (", …" if len(parts) > 3 else "")
```

```python
def _match_named(objs, q, limit, summary_fn=None):
    ql = q.lower()
    hits = []
    for o in objs:
        name = o.get("name", "")
        if ql in name.lower():
            item = {"name": name, "href": o.get("href")}
            if summary_fn:
                item["summary"] = summary_fn(o)
            hits.append(item)
    return hits[:limit], len(hits) > limit
```

`search_cached_objects` 加：

```python
    if "service" in types:
        objs = _get_or_fill(api, "services", lambda a: a.get_services())
        items, trunc = _match_named(objs, q, limit, summary_fn=_service_summary)
        out["service"] = {"items": items, "truncated": trunc}
```

(b) `filter_objects.py`：

```python
_CACHED_TYPES = ("label", "label_group", "iplist", "service")
```

（`_ALL_TYPES` 組合式不變。）

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_filter_object_cache.py tests/test_gui_filter_suggest.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/gui/filter_object_cache.py src/gui/routes/filter_objects.py tests/test_filter_object_cache.py tests/test_gui_filter_suggest.py
git commit -m "feat: add service type to suggest endpoint and object cache"
```

---

### Task 7: browse 端點

**Files:**
- Modify: `src/gui/filter_object_cache.py`（`browse_cached_objects`、`cached_type_totals`）
- Modify: `src/gui/routes/filter_objects.py`（新 route）
- Test: `tests/test_gui_filter_browse.py`（新檔）

**Interfaces:**
- Produces:
  - `GET /api/filter-objects/browse?type=_totals` → `{"ok": true, "totals": {"label": N, "label_group": N, "iplist": N, "service": N}}`
  - `GET /api/filter-objects/browse?type=label&offset=0&limit=20` → `{"ok": true, "items": [...], "total": N, "truncated": bool, "groups": [{"key": "Net", "count": 14}, ...]}`（label 依 key 排序分組；items 帶 `key`；其他類別無 `groups`、item 形同 suggest）
  - `type=workload` → `{"ok": true, "browseable": false, "items": [], "total": null}`
  - 未知 type → 400；快取抓取失敗 → `{"ok": false, "error": "pce_unreachable"}` 與 502。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_gui_filter_browse.py
"""GET /api/filter-objects/browse：分頁、label 分組、totals、workload 不可瀏覽。

Flask app/client fixture 與 mock ApiClient 樣式沿用 tests/test_gui_filter_suggest.py。"""
# （fixture 照 test_gui_filter_suggest.py 複製；mock get_all_labels 回 46 筆
#   跨 2 個 key、get_services 回 3 筆、get_ip_lists 回 2 筆、get_label_groups 回 0 筆）


def test_browse_totals(client_fixture):
    r = client_fixture.get("/api/filter-objects/browse?type=_totals")
    body = r.get_json()
    assert body["ok"] and body["totals"]["label"] == 46 and body["totals"]["service"] == 3


def test_browse_label_grouped_and_paged(client_fixture):
    r = client_fixture.get("/api/filter-objects/browse?type=label&offset=0&limit=20")
    body = r.get_json()
    assert body["total"] == 46 and len(body["items"]) == 20 and body["truncated"] is True
    assert {g["key"] for g in body["groups"]} == {"Net", "role"}
    # 排序穩定：offset 接續不重複
    r2 = client_fixture.get("/api/filter-objects/browse?type=label&offset=20&limit=20")
    names1 = {i["name"] for i in body["items"]}
    names2 = {i["name"] for i in r2.get_json()["items"]}
    assert not names1 & names2


def test_browse_service_items_have_summary(client_fixture):
    r = client_fixture.get("/api/filter-objects/browse?type=service&offset=0&limit=20")
    assert all("summary" in i for i in r.get_json()["items"])


def test_browse_workload_not_browseable(client_fixture):
    body = client_fixture.get("/api/filter-objects/browse?type=workload").get_json()
    assert body["ok"] and body["browseable"] is False


def test_browse_unknown_type_400(client_fixture):
    assert client_fixture.get("/api/filter-objects/browse?type=bogus").status_code == 400
```

（fixture 名稱與建構照 `test_gui_filter_suggest.py` 實際寫法；上列僅斷言契約。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_gui_filter_browse.py -q`
Expected: FAIL（404 no route）

- [ ] **Step 3: 實作**

(a) `filter_object_cache.py` 新增：

```python
_TYPE_FETCHERS = {
    "label": ("labels", lambda a: a.get_all_labels()),
    "iplist": ("ip_lists", lambda a: a.get_ip_lists()),
    "label_group": ("label_groups", lambda a: a.get_label_groups()),
    "service": ("services", lambda a: a.get_services()),
}


def cached_type_totals(api) -> dict[str, int]:
    """各 cached 類別總數（chip 顯示用；快取長度，零 PCE 額外成本）。"""
    return {t: len(_get_or_fill(api, key, fn)) for t, (key, fn) in _TYPE_FETCHERS.items()}


def browse_cached_objects(api, btype: str, offset: int, limit: int) -> dict:
    """單一類別全量瀏覽分頁。label 依 (key, value) 排序並附 groups 統計；
    其他類別依 name 排序。item 形狀與 suggest 一致。"""
    key, fn = _TYPE_FETCHERS[btype]
    objs = _get_or_fill(api, key, fn)
    if btype == "label":
        objs = sorted(objs, key=lambda l: ((l.get("key") or ""), (l.get("value") or "")))
        groups: dict[str, int] = {}
        for l in objs:
            groups[l.get("key") or ""] = groups.get(l.get("key") or "", 0) + 1
        items = [{"name": f"{l.get('key', '')}={l.get('value', '')}",
                  "key": l.get("key"), "value": l.get("value"), "href": l.get("href")}
                 for l in objs[offset:offset + limit]]
        return {"items": items, "total": len(objs), "truncated": offset + limit < len(objs),
                "groups": [{"key": k, "count": n} for k, n in groups.items()]}
    objs = sorted(objs, key=lambda o: o.get("name") or "")
    summary_fn = _ip_list_summary if btype == "iplist" else (_service_summary if btype == "service" else None)
    items = []
    for o in objs[offset:offset + limit]:
        item = {"name": o.get("name", ""), "href": o.get("href")}
        if summary_fn:
            item["summary"] = summary_fn(o)
        items.append(item)
    return {"items": items, "total": len(objs), "truncated": offset + limit < len(objs)}
```

(b) `filter_objects.py` 新 route（同藍圖、同限流）：

```python
    @bp.route('/api/filter-objects/browse', methods=['GET'])
    @limiter.limit("240 per hour")
    def api_filter_objects_browse():
        btype = (request.args.get('type') or '').strip()
        try:
            offset = max(0, int(request.args.get('offset', 0)))
        except (ValueError, TypeError):
            offset = 0
        try:
            limit = max(1, min(100, int(request.args.get('limit', 20))))
        except (ValueError, TypeError):
            limit = 20

        if btype == 'workload':
            return jsonify({"ok": True, "browseable": False, "items": [], "total": None})

        from src.api_client import ApiClient
        from src.gui.filter_object_cache import browse_cached_objects, cached_type_totals
        cm.load()
        api = ApiClient(cm)

        if btype == '_totals':
            try:
                return jsonify({"ok": True, "totals": cached_type_totals(api)})
            except Exception:
                return jsonify({"ok": False, "error": "pce_unreachable"}), 502
        if btype not in _CACHED_TYPES:
            return jsonify({"ok": False, "error": "unknown_type"}), 400
        try:
            return jsonify({"ok": True, **browse_cached_objects(api, btype, offset, limit)})
        except Exception:
            return jsonify({"ok": False, "error": "pce_unreachable"}), 502
```

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_gui_filter_browse.py tests/test_gui_filter_suggest.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/gui/filter_object_cache.py src/gui/routes/filter_objects.py tests/test_gui_filter_browse.py
git commit -m "feat: add filter-objects browse endpoint with pagination and label grouping"
```

---

### Task 8: FilterBar 服務/Port 類別（pill、直輸、序列化）

**Files:**
- Modify: `src/static/js/filter-bar.js`
- Modify: `src/static/css/app.css`（`objfb-dot-service`、`objfb-dot-port` 色點，沿用既有 dot 樣式 token）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_component_object_filter_bar.py`（擴充；靜態文字斷言，同檔既有樣式）

**Interfaces:**
- Consumes: suggest 端點 `service` 類別（Task 6）。
- Produces: pill cat `service`（`{cat:'service', name, href, dir:null, neg}`）與 `port`（`{cat:'port', name:'443/tcp', dir:null, neg}`）；`getFilters()` 輸出 `services`/`ex_services`（href list）、`ports`/`ex_ports`（token list）；`setFilters()` 支援新 key 與舊 scalar `port`/`proto`/`ex_port` 回填。

- [ ] **Step 1: 寫失敗測試（靜態斷言）**

`tests/test_component_object_filter_bar.py` 附加：

```python
def test_filter_bar_service_port_categories_defined():
    src = _JS.read_text(encoding="utf-8")
    assert "gui_fb_cat_service" in src and "gui_fb_cat_port" in src
    assert "objfb-dot-service" in src and "objfb-dot-port" in src


def test_filter_bar_serializes_services_and_ports_keys():
    src = _JS.read_text(encoding="utf-8")
    for key in ("services", "ex_services", "ports", "ex_ports"):
        assert f"'{key}'" in src or f"`${{ex}}{key.removeprefix('ex_')}`" in src, key


def test_filter_bar_port_like_validator_present():
    src = _JS.read_text(encoding="utf-8")
    assert "_objfbIsPortLike" in src


def test_filter_bar_dirless_cats():
    src = _JS.read_text(encoding="utf-8")
    assert "_OBJFB_DIRLESS" in src


def test_filter_bar_service_i18n_keys_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_cat_service", "gui_fb_cat_port", "gui_fb_add_port"):
        assert k in en and k in zh
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -q`
Expected: 新增測試 FAIL

- [ ] **Step 3: 實作 filter-bar.js**

(a) `_objfbIsIpLike` 下方加：

```js
// port token：80 / 443/tcp / 1000-2000 / 1000-2000/udp（proto 也收數字）
function _objfbIsPortLike(s) {
  const m = String(s).trim().toLowerCase().match(/^(\d{1,5})(?:-(\d{1,5}))?(?:\/(tcp|udp|icmp|icmpv6|\d{1,3}))?$/);
  if (!m) return false;
  const lo = +m[1], hi = m[2] ? +m[2] : +m[1];
  return lo >= 1 && lo <= 65535 && hi >= 1 && hi <= 65535;
}
```

(b) 預設 cats（`createFilterBar`）改為：

```js
  const cats = opts.cats || ['label', 'label_group', 'iplist', 'workload', 'ip', 'service', 'port'];
```

(c) `_OBJFB_CATS` 加兩類、加 dirless 集合；`_OBJFB_SUGGEST_CATS` 加 `service`：

```js
  service: { i18n: 'gui_fb_cat_service', dot: 'objfb-dot-service', fallback: 'Services' },
  port:    { i18n: 'gui_fb_cat_port',    dot: 'objfb-dot-port',    fallback: 'Port' },
```

```js
// 無方向類別：pill 不帶 src/dst/any、序列化不吃 dir、popover 不顯示方向列
const _OBJFB_DIRLESS = new Set(['service', 'port']);
```

```js
const _OBJFB_SUGGEST_CATS = ['label', 'label_group', 'iplist', 'workload', 'service'];
```

(d) `_objfbAddPill`：`dir: _OBJFB_DIRLESS.has(obj.cat) ? null : state.addDir`。

(e) `_objfbSerialize`：`for` 迴圈開頭（`any` 判斷之前）加：

```js
    if (p.cat === 'service') { push(`${ex}services`, p.href || p.name); continue; }
    if (p.cat === 'port')    { push(`${ex}ports`, p.name); continue; }
```

(f) `_objfbDeserialize`：`for (const dir ...)` 之前加（dirless pill 的 dir 一律 null）：

```js
  for (const h of asList(d['services'])) add('service', h, null, false, { href: h });
  for (const h of asList(d['ex_services'])) add('service', h, null, true, { href: h });
  for (const tok of asList(d['ports'])) add('port', tok, null, false);
  for (const tok of asList(d['ex_ports'])) add('port', tok, null, true);
  // 舊 scalar port/proto/ex_port 回填成 port pill（讀取相容，零遷移）
  if (d['port']) {
    const protoName = { '6': 'tcp', '17': 'udp' }[String(d['proto'] || '')] || null;
    add('port', protoName ? `${d['port']}/${protoName}` : String(d['port']), null, false);
  }
  if (d['ex_port']) add('port', String(d['ex_port']), null, true);
```

(g) `_objfbBuildPill`：dir 標籤改為 dirless 時省略：

```js
  if (p.dir !== null) {
    const dirTag = document.createElement('span');
    dirTag.className = 'objfb-pill-dir';
    dirTag.textContent = _OBJFB_DIR_TAG[p.dir] || p.dir;
    el.appendChild(dirTag);
  }
```

（`className` 的 `objfb-any` 判斷維持 `p.dir === 'any'`，null 不受影響。）

(h) `_objfbOpenPop`：方向列包在 `if (!_OBJFB_DIRLESS.has(p.cat)) { ... }` 內（`dirRow` 整段），包含/排除與移除列不變。

(i) `_objfbRenderDropdown`：IP 置頂候選判斷後加 port 置頂候選：

```js
  if (_objfbIsPortLike(q) && state.cats.includes('port') && (!state.scopeCat || state.scopeCat === 'service' || state.scopeCat === 'port')) {
    _objfbAddDdGroup(state, [{ cat: 'port', name: q.trim() }], 'gui_fb_add_port', 'Add Port');
  }
```

`_objfbKeydown` 的 Enter 無候選分支同步：在 `_objfbIsIpLike` 判斷前加 `if (_objfbIsPortLike(q) && s.cats.includes('port')) { window._objfbPickItem(id, { cat: 'port', name: q }); return; }`（注意 `80` 不會撞 IP regex——IP 需 4 段點分）。

(j) 同側同 key or 分隔的 `prevKeyDir` 邏輯不適用 dirless pill（`derivedKey` 只算 label，已天然跳過，無需改）。

(k) `app.css`：在既有 `objfb-dot-*` 定義區塊加兩色點（沿用既有 token 變數樣式、色值選未用過的既有調色盤變數）：

```css
.objfb-dot-service { background: var(--accent-purple, #8e6fc0); }
.objfb-dot-port    { background: var(--accent-teal, #3fa7a0); }
```

(l) i18n 兩檔各加（zh_TW 值）：

```json
"gui_fb_cat_service": "服務",
"gui_fb_cat_port": "Port",
"gui_fb_add_port": "加入 Port",
```

（en 值：`"Services"`、`"Port"`、`"Add Port"`。）

- [ ] **Step 4: 語法檢查與測試**

Run: `node --check src/static/js/filter-bar.js && pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/static/js/filter-bar.js src/static/css/app.css src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(gui): add service and port pill categories to filter bar"
```

---

### Task 9: FilterBar 空輸入瀏覽（chips＋分組清單＋載入更多）

**Files:**
- Modify: `src/static/js/filter-bar.js`（`_objfbUpdateDropdown` 空輸入分支重寫、新增 browse fetch/render、`_objfbBrowseMore` handler）
- Modify: `src/static/css/app.css`（`.objfb-chip`、`.objfb-dd-more`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_component_object_filter_bar.py`（擴充）

**Interfaces:**
- Consumes: browse 端點（Task 7）。
- Produces: 空輸入且無 scope → 類別 chip 列（含 totals）；空輸入且有 scope → 該類別瀏覽清單（label 依 key 插組頭）＋「載入更多」；`state._totals`（session 內快取一次）、`state._browse = {type, items, total, offset, groups}`。

- [ ] **Step 1: 寫失敗測試（靜態斷言）**

```python
def test_filter_bar_browse_wiring_present():
    src = _JS.read_text(encoding="utf-8")
    assert "/api/filter-objects/browse" in src
    assert "window._objfbBrowseMore" in src
    assert "gui_fb_load_more" in src and "gui_fb_type_to_search" in src


def test_filter_bar_browse_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_load_more", "gui_fb_type_to_search", "gui_fb_browse_error"):
        assert k in en and k in zh
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -q`
Expected: 新增測試 FAIL

- [ ] **Step 3: 實作**

(a) `_objfbUpdateDropdown` 的 `if (!q)` 分支重寫：

```js
  if (!q) {
    if (state._abort) { state._abort.abort(); state._abort = null; }
    state._suggest = null;
    state._suggestQ = null;
    if (state.scopeCat && state.scopeCat !== 'ip' && state.scopeCat !== 'port') {
      _objfbRenderBrowse(state);   // 有 scope：空輸入即瀏覽該類別
      return;
    }
    _objfbRenderCatChips(state);   // 無 scope：類別 chip 列（含 totals）
    return;
  }
```

(b) 新函式（放 `_objfbUpdateDropdown` 下方）：

```js
/* ── 空輸入瀏覽（案 C）：無 scope 顯示類別 chip（含各類總數），點 chip 設
 * scope 進入該類別的全量分頁清單；label 依 key 插入組頭。totals 每實例
 * 快取一次（TTL 交給後端 module cache）。 ── */
function _objfbRenderCatChips(state) {
  const dd = state.els.dd;
  dd.innerHTML = '';
  state.ddItems = [];
  const catsWrap = document.createElement('div');
  catsWrap.className = 'objfb-dd-cats';
  for (const c of state.cats.filter((c) => c !== 'ip' && c !== 'port')) {
    const meta = _OBJFB_CATS[c];
    if (!meta) continue;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'objfb-cat-btn';
    const dot = document.createElement('i');
    dot.className = 'objfb-cat-dot ' + meta.dot;
    b.appendChild(dot);
    const label = document.createElement('span');
    if (meta.i18n) label.setAttribute('data-i18n', meta.i18n);
    label.textContent = meta.fallback;
    b.appendChild(label);
    const n = state._totals && state._totals[c];
    if (typeof n === 'number') {
      const cnt = document.createElement('span');
      cnt.className = 'objfb-chip-cnt';
      cnt.textContent = ` (${n})`;
      b.appendChild(cnt);
    }
    b.setAttribute('data-on-click', '_objfbSetScope');
    b.dataset.args = JSON.stringify([state.id, c]);
    catsWrap.appendChild(b);
  }
  dd.appendChild(catsWrap);
  const note = document.createElement('div');
  note.className = 'objfb-dd-note';
  note.setAttribute('data-i18n', 'gui_fb_scope_hint');
  dd.appendChild(note);
  _objfbApplyI18n(dd);
  dd.classList.add('open');
  state.actIdx = -1;
  if (!state._totals) {
    fetch('/api/filter-objects/browse?type=_totals', { credentials: 'same-origin' })
      .then(r => r.json())
      .then(body => {
        if (body.ok && body.totals) {
          state._totals = body.totals;
          if (state.els && !state.els.input.value.trim() && !state.scopeCat) _objfbRenderCatChips(state);
        }
      })
      .catch(() => {});
  }
}

function _objfbRenderBrowse(state, append) {
  const cat = state.scopeCat;
  const dd = state.els.dd;
  if (cat === 'workload') {
    dd.innerHTML = '';
    state.ddItems = [];
    _objfbAddDdNote(dd, 'gui_fb_type_to_search', 'Type to search');
    _objfbApplyI18n(dd);
    dd.classList.add('open');
    return;
  }
  const offset = append && state._browse && state._browse.type === cat ? state._browse.items.length : 0;
  fetch(`/api/filter-objects/browse?type=${cat}&offset=${offset}&limit=20`, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(body => {
      if (!state.els || state.els.input.value.trim() || state.scopeCat !== cat) return; // 已改變，放棄
      if (!body.ok) throw new Error(body.error || 'browse');
      const prev = (append && state._browse && state._browse.type === cat) ? state._browse.items : [];
      state._browse = { type: cat, items: prev.concat(body.items), total: body.total, groups: body.groups || null };
      _objfbRenderBrowseList(state);
    })
    .catch(() => {
      if (!state.els) return;
      dd.innerHTML = '';
      state.ddItems = [];
      _objfbAddDdNote(dd, 'gui_fb_browse_error', 'Browse unavailable');
      _objfbApplyI18n(dd);
      dd.classList.add('open');
    });
}

function _objfbRenderBrowseList(state) {
  const dd = state.els.dd;
  const b = state._browse;
  dd.innerHTML = '';
  state.ddItems = [];
  let prevKey = null;
  let batch = [];
  const flush = () => {
    if (!batch.length) return;
    const hdrText = b.type === 'label' ? prevKey : null;
    if (hdrText !== null) {
      const h = document.createElement('div');
      h.className = 'objfb-dd-hdr';
      h.textContent = hdrText;
      dd.appendChild(h);
    }
    _objfbAddDdGroupItems(state, batch);
    batch = [];
  };
  for (const it of b.items) {
    const k = b.type === 'label' ? (it.key || '') : null;
    if (b.type === 'label' && k !== prevKey) { flush(); prevKey = k; }
    batch.push(Object.assign({ cat: b.type }, it));
  }
  flush();
  if (b.items.length < b.total) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'objfb-dd-more';
    more.setAttribute('data-i18n', 'gui_fb_load_more');
    more.textContent = 'Load more';
    const cnt = document.createElement('span');
    cnt.textContent = ` (${b.items.length}/${b.total})`;
    more.appendChild(cnt);
    more.setAttribute('data-on-click', '_objfbBrowseMore');
    more.dataset.args = JSON.stringify([state.id]);
    dd.appendChild(more);
  }
  _objfbApplyI18n(dd);
  state.actIdx = state.ddItems.length ? 0 : -1;
  _objfbMarkActive(state);
  dd.classList.add('open');
}

// 不帶組頭的 items 渲染（_objfbAddDdGroup 拆出共用；原函式改呼叫此函式）
function _objfbAddDdGroupItems(state, items) {
  const dd = state.els.dd;
  for (const o of items) {
    const el = document.createElement('div');
    el.className = 'objfb-dd-item';
    el.setAttribute('role', 'option');
    const meta = _OBJFB_CATS[o.cat];
    const dot = document.createElement('i');
    dot.className = 'objfb-cat-dot ' + (meta ? meta.dot : 'objfb-dot-ip');
    el.appendChild(dot);
    const txt = document.createElement('span');
    txt.textContent = o.summary ? `${o.name} — ${o.summary}` : o.name;
    el.appendChild(txt);
    el.setAttribute('data-on-click', '_objfbPickItem');
    el.dataset.args = JSON.stringify([state.id, o]);
    dd.appendChild(el);
    state.ddItems.push({ o, el });
  }
}

window._objfbBrowseMore = function (id) {
  const s = _objfbInstances[id];
  if (s) _objfbRenderBrowse(s, true);
};
```

同步重構：既有 `_objfbAddDdGroup` 內的 item 迴圈改為呼叫 `_objfbAddDdGroupItems(state, items)`（組頭部分保留）。

(c) `_objfbPickItem` 在瀏覽模式選取後 input 為空 → `_objfbUpdateDropdown` 自然重進瀏覽清單，但 `state._browse` 已有資料會重新 fetch offset 0——可接受（後端有 module cache）。不做額外狀態保留（YAGNI）。

(d) `app.css` 加：

```css
.objfb-chip-cnt { opacity: .55; font-size: 11px; }
.objfb-dd-more { display: block; width: 100%; text-align: center; padding: 6px; border: none; background: none; color: var(--accent, #4a7dbd); cursor: pointer; font-size: 12px; border-top: 1px dashed var(--border, #8884); }
```

(e) i18n 兩檔各加（zh / en）：

```json
"gui_fb_load_more": "載入更多",
"gui_fb_type_to_search": "請輸入關鍵字搜尋",
"gui_fb_browse_error": "瀏覽暫時無法使用，請直接輸入搜尋",
```

（en：`"Load more"`、`"Type a keyword to search"`、`"Browse unavailable; type to search instead"`。）

- [ ] **Step 4: 語法檢查與測試**

Run: `node --check src/static/js/filter-bar.js && pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/static/js/filter-bar.js src/static/css/app.css src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(gui): empty-input category browse with chips and load-more in filter bar"
```

---

### Task 10: Modal 物件庫

**Files:**
- Create: `src/static/js/object-browser.js`
- Modify: `src/templates/index.html`（modal 骨架＋`<script>` 引入，位置比照其他 modal 與 script 標籤）
- Modify: `src/static/js/filter-bar.js`（下拉底部「在視窗中瀏覽全部…」入口）
- Modify: `src/static/css/app.css`、`src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_component_object_browser.py`（新檔，靜態斷言）

**Interfaces:**
- Consumes: browse／suggest 端點、`_objfbInstances`（依 fbId 取回實例）、`_objfbAddPill`。
- Produces: `window.openObjectBrowser(fbId)`；modal 內：類別分頁（依該實例 cats，排除 ip/port）、搜尋框（打字走 suggest、清空回 browse 分頁）、表格勾選多選、方向段（來源/目的/任一；service 分頁隱藏）、「加入」把勾選項逐一 `_objfbAddPill`（service 強制 dir null）後關閉。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_component_object_browser.py
"""Modal 物件庫（object-browser.js）的靜態契約，樣式同 test_component_object_filter_bar.py。"""
import json
from pathlib import Path

_JS = Path("src/static/js/object-browser.js")
_FB = Path("src/static/js/filter-bar.js")
_INDEX = Path("src/templates/index.html")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


def test_object_browser_exists_and_exports():
    src = _JS.read_text(encoding="utf-8")
    assert "window.openObjectBrowser" in src
    assert "onclick=" not in src  # CSP


def test_object_browser_modal_markup_present():
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="modal-obj-browser"' in html
    assert "object-browser.js" in html


def test_filter_bar_has_browser_entry():
    src = _FB.read_text(encoding="utf-8")
    assert "gui_fb_browse_all" in src and "openObjectBrowser" in src


def test_object_browser_i18n_bilingual():
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_browse_all", "gui_ob_title", "gui_ob_add", "gui_ob_selected",
              "gui_ob_search_ph", "gui_ob_page", "gui_ob_dir_hint"):
        assert k in en and k in zh
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_browser.py -q`
Expected: FAIL

- [ ] **Step 3: 實作**

(a) `index.html`：比照既有 modal（如 `modal-qt-filters`）加骨架（內容區由 JS 填充；按鈕走 `data-action`/`data-on-click`）：

```html
    <div class="modal" id="modal-obj-browser">
      <div class="modal-content" style="max-width:720px">
        <h2 data-i18n="gui_ob_title">Select filter objects</h2>
        <div id="ob-body"></div>
        <div class="modal-actions">
          <button class="btn btn-secondary" data-action="closeModal" data-args='["modal-obj-browser"]'
            data-i18n="gui_cancel">Cancel</button>
          <button class="btn" id="ob-add-btn" data-on-click="_obAddSelected" data-i18n="gui_ob_add">Add</button>
        </div>
      </div>
    </div>
```

script 引入（與 filter-bar.js 同區、順序在其後）：`<script defer src="/static/js/object-browser.js"></script>`（路徑寫法照 index.html 既有 script 標籤，含版本 query 參數則跟隨）。

(b) `object-browser.js` 完整內容：

```js
'use strict';
/* Modal 物件庫（案 C 深挖入口）：類別分頁 + 搜尋 + 分頁表格 + 勾選多選。
 * 開啟：window.openObjectBrowser(fbId)（filter-bar 下拉底部入口）。
 * 資料：空搜尋走 /api/filter-objects/browse 分頁；有字走 suggest（limit 25）。
 * 加入：勾選項以 _objfbAddPill 逐一加為 pill（service 無方向）。CSP：無 inline。
 */
const _ob = {
  fbId: null, cat: null, q: '', offset: 0, limit: 20,
  items: [], total: 0, selected: {}, dir: 'src',
};

const _OB_PAGE_TYPES = ['label', 'label_group', 'iplist', 'workload', 'service'];

window.openObjectBrowser = function (fbId) {
  const fb = window._objfbGetInstance ? window._objfbGetInstance(fbId) : null;
  if (!fb) return;
  _ob.fbId = fbId;
  _ob.cats = _OB_PAGE_TYPES.filter(c => fb.cats.includes(c));
  _ob.cat = fb.scopeCat && _ob.cats.includes(fb.scopeCat) ? fb.scopeCat : _ob.cats[0];
  _ob.dirs = fb.dirs;
  _ob.dir = fb.addDir && fb.dirs.includes(fb.addDir) ? fb.addDir : fb.dirs[0];
  _ob.q = '';
  _ob.offset = 0;
  _ob.selected = {};
  document.getElementById('modal-obj-browser').classList.add('show');
  _obRender();
  _obFetch();
};

function _obFetch() {
  const cat = _ob.cat;
  if (cat === 'workload' && !_ob.q) {
    _ob.items = []; _ob.total = 0;
    _obRenderTable('gui_fb_type_to_search');
    return;
  }
  const url = _ob.q
    ? `/api/filter-objects/suggest?q=${encodeURIComponent(_ob.q)}&types=${cat}&limit=25`
    : `/api/filter-objects/browse?type=${cat}&offset=${_ob.offset}&limit=${_ob.limit}`;
  fetch(url, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(body => {
      if (_ob.q) {
        const r_ = (body.results || {})[cat] || {};
        _ob.items = r_.items || []; _ob.total = _ob.items.length;
      } else {
        _ob.items = body.items || []; _ob.total = body.total || 0;
      }
      _obRenderTable(null);
    })
    .catch(() => _obRenderTable('gui_fb_browse_error'));
}

function _obRender() {
  const body = document.getElementById('ob-body');
  body.innerHTML = '';
  // 類別分頁
  const tabs = document.createElement('div');
  tabs.className = 'ob-tabs';
  for (const c of _ob.cats) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-tab' + (c === _ob.cat ? ' on' : '');
    b.setAttribute('data-i18n', 'gui_fb_cat_' + c);
    b.textContent = c;
    b.setAttribute('data-on-click', '_obSetCat');
    b.dataset.args = JSON.stringify([c]);
    tabs.appendChild(b);
  }
  body.appendChild(tabs);
  // 搜尋框
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.id = 'ob-search';
  inp.className = 'ob-search';
  inp.autocomplete = 'off';
  inp.setAttribute('data-i18n-placeholder', 'gui_ob_search_ph');
  inp.setAttribute('data-on-input', '_obSearchInput');
  body.appendChild(inp);
  // 表格容器 + 分頁列 + 方向列
  const tbl = document.createElement('div');
  tbl.id = 'ob-table';
  body.appendChild(tbl);
  const foot = document.createElement('div');
  foot.id = 'ob-foot';
  foot.className = 'ob-foot';
  body.appendChild(foot);
  if (typeof window.i18nApply === 'function') window.i18nApply(body);
}

function _obRenderTable(noteKey) {
  const tbl = document.getElementById('ob-table');
  tbl.innerHTML = '';
  if (noteKey) {
    const n = document.createElement('div');
    n.className = 'objfb-dd-note';
    n.setAttribute('data-i18n', noteKey);
    tbl.appendChild(n);
  } else {
    for (const it of _ob.items) {
      const row = document.createElement('label');
      row.className = 'ob-row';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      const key = it.href || it.name;
      cb.checked = !!_ob.selected[key];
      cb.setAttribute('data-on-change', '_obToggle');
      cb.dataset.args = JSON.stringify([key, it]);
      row.appendChild(cb);
      const txt = document.createElement('span');
      txt.className = 'ob-row-txt';
      txt.textContent = it.summary ? `${it.name} — ${it.summary}` : it.name;
      row.appendChild(txt);
      tbl.appendChild(row);
    }
  }
  _obRenderFoot();
  if (typeof window.i18nApply === 'function') window.i18nApply(tbl);
}

function _obRenderFoot() {
  const foot = document.getElementById('ob-foot');
  foot.innerHTML = '';
  // 分頁（僅 browse 模式）
  if (!_ob.q && _ob.total > _ob.limit) {
    const pager = document.createElement('span');
    pager.className = 'ob-pager';
    const prev = document.createElement('button');
    prev.type = 'button'; prev.textContent = '‹';
    prev.disabled = _ob.offset <= 0;
    prev.setAttribute('data-on-click', '_obPage');
    prev.dataset.args = JSON.stringify([-1]);
    const next = document.createElement('button');
    next.type = 'button'; next.textContent = '›';
    next.disabled = _ob.offset + _ob.limit >= _ob.total;
    next.setAttribute('data-on-click', '_obPage');
    next.dataset.args = JSON.stringify([1]);
    const info = document.createElement('span');
    info.setAttribute('data-i18n', 'gui_ob_page');
    info.textContent = 'Page';
    const nums = document.createElement('span');
    nums.textContent = ` ${Math.floor(_ob.offset / _ob.limit) + 1} / ${Math.ceil(_ob.total / _ob.limit)}（${_ob.total}）`;
    pager.appendChild(prev); pager.appendChild(info); pager.appendChild(nums); pager.appendChild(next);
    foot.appendChild(pager);
  }
  // 已選數 + 方向段（service 分頁隱藏方向）
  const right = document.createElement('span');
  right.className = 'ob-foot-right';
  const selCnt = document.createElement('span');
  selCnt.setAttribute('data-i18n', 'gui_ob_selected');
  selCnt.textContent = 'Selected';
  const selNum = document.createElement('span');
  selNum.textContent = ` ${Object.keys(_ob.selected).length}`;
  right.appendChild(selCnt); right.appendChild(selNum);
  if (_ob.cat !== 'service') {
    const seg = document.createElement('span');
    seg.className = 'ob-dir-seg';
    for (const d of _ob.dirs) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-dir-btn' + (_ob.dir === d ? ' on' : '');
      b.setAttribute('data-i18n', 'gui_fb_dir_' + d);
      b.textContent = d;
      b.setAttribute('data-on-click', '_obSetDir');
      b.dataset.args = JSON.stringify([d]);
      seg.appendChild(b);
    }
    right.appendChild(seg);
  } else {
    const hint = document.createElement('span');
    hint.className = 'ob-dir-hint';
    hint.setAttribute('data-i18n', 'gui_ob_dir_hint');
    right.appendChild(hint);
  }
  foot.appendChild(right);
  if (typeof window.i18nApply === 'function') window.i18nApply(foot);
}

window._obSetCat = function (c) { _ob.cat = c; _ob.q = ''; _ob.offset = 0; _ob.selected = {}; _obRender(); _obFetch(); };
window._obSetDir = function (d) { _ob.dir = d; _obRenderFoot(); };
window._obPage = function (delta) { _ob.offset = Math.max(0, _ob.offset + delta * _ob.limit); _obFetch(); };
window._obToggle = function (key, it) {
  if (_ob.selected[key]) delete _ob.selected[key];
  else _ob.selected[key] = it;
  _obRenderFoot();
};
window._obSearchInput = function () {
  const v = document.getElementById('ob-search').value.trim();
  _ob.q = v;
  _ob.offset = 0;
  if (!_ob._deb) _ob._deb = window.debounce(_obFetch, 250);
  _ob._deb();
};
window._obAddSelected = function () {
  const fb = window._objfbGetInstance ? window._objfbGetInstance(_ob.fbId) : null;
  if (fb) {
    const prevDir = fb.addDir;
    fb.addDir = _ob.dir;
    for (const it of Object.values(_ob.selected)) {
      window._objfbAddPillPublic(fb, Object.assign({ cat: _ob.cat }, it));
    }
    fb.addDir = prevDir;
  }
  closeModal('modal-obj-browser');
};
```

(c) `filter-bar.js` 配套：

- 提供實例存取與 addPill 公開包裝（掛 window，供 object-browser 用）：

```js
window._objfbGetInstance = function (id) { return _objfbInstances[id] || null; };
window._objfbAddPillPublic = function (state, obj) { _objfbAddPill(state, obj); };
```

- `_objfbRenderCatChips` 與 `_objfbRenderBrowseList` 末端（`dd.classList.add('open')` 前）都加入口列：

```js
  const browseAll = document.createElement('button');
  browseAll.type = 'button';
  browseAll.className = 'objfb-dd-more';
  browseAll.setAttribute('data-i18n', 'gui_fb_browse_all');
  browseAll.textContent = 'Browse all…';
  browseAll.setAttribute('data-on-click', '_objfbOpenBrowser');
  browseAll.dataset.args = JSON.stringify([state.id]);
  dd.appendChild(browseAll);
```

```js
window._objfbOpenBrowser = function (id) {
  const s = _objfbInstances[id];
  if (s) { s.els.dd.classList.remove('open'); window.openObjectBrowser(id); }
};
```

(d) `app.css`（沿用既有 modal/token 變數）：

```css
.ob-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border, #8884); margin-bottom: 8px; }
.ob-tab { padding: 4px 12px; border: none; background: none; cursor: pointer; opacity: .6; }
.ob-tab.on { opacity: 1; border-bottom: 2px solid var(--accent, #4a7dbd); }
.ob-search { width: 100%; margin-bottom: 6px; }
#ob-table { max-height: 320px; overflow-y: auto; }
.ob-row { display: flex; gap: 8px; padding: 4px 6px; align-items: center; cursor: pointer; }
.ob-row:hover { background: var(--hover, rgba(74,125,189,.08)); }
.ob-row-txt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ob-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 12px; }
.ob-dir-btn { padding: 2px 8px; }
.ob-dir-btn.on { background: var(--accent, #4a7dbd); color: #fff; }
```

(e) i18n 兩檔各加（zh / en）：

```json
"gui_fb_browse_all": "在視窗中瀏覽全部…",
"gui_ob_title": "選取 filter 物件",
"gui_ob_add": "加入",
"gui_ob_selected": "已選",
"gui_ob_search_ph": "搜尋此類別…",
"gui_ob_page": "頁",
"gui_ob_dir_hint": "服務條件不分來源/目的",
```

（en：`"Browse all…"`、`"Select filter objects"`、`"Add"`、`"Selected"`、`"Search this category…"`、`"Page"`、`"Service conditions are direction-less"`。）

- [ ] **Step 4: 語法檢查與測試**

Run: `node --check src/static/js/object-browser.js && node --check src/static/js/filter-bar.js && pytest tests/test_component_object_browser.py tests/test_component_object_filter_bar.py tests/test_csp_compliance.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/static/js/object-browser.js src/static/js/filter-bar.js src/templates/index.html src/static/css/app.css src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_browser.py
git commit -m "feat(gui): add object browser modal for bulk filter selection"
```

---

### Task 11: GUI 落點接線（qt-port 移除、rules cats）

**Files:**
- Modify: `src/templates/index.html:2419-2427`（port/proto form-row）、`:2455-2460`（ex_port form-row）
- Modify: `src/static/js/quarantine.js:277-279`、`:293-295`
- Modify: `src/static/js/rules.js:32,39`
- Test: `tests/test_component_object_filter_bar.py`（擴充）

**Interfaces:**
- Consumes: FilterBar 新類別（Task 8）。後端 `/api/quarantine/search` 讀 `ports`/`ex_ports`/`services`/`ex_services`（查詢層已支援，Analyzer 端 filters dict 直通——執行時驗證，若 analyzer 有白名單過濾則把 4 個新 key 加入白名單）。
- Produces: 流量分析器 port 條件全走 pill；traffic/bandwidth 規則 modal 開放 service/port 類別。

- [ ] **Step 1: 寫失敗測試**

```python
def test_qt_port_fields_removed():
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="qt-port"' not in html and 'id="qt-expt"' not in html and 'id="qt-proto"' not in html


def test_quarantine_js_no_qt_port_reads():
    src = Path("src/static/js/quarantine.js").read_text(encoding="utf-8")
    assert "qt-port" not in src and "qt-expt" not in src and "qt-proto" not in src


def test_rules_filter_bars_allow_service_port():
    src = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    assert src.count("'service', 'port'") >= 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -q`
Expected: 新增測試 FAIL

- [ ] **Step 3: 實作**

(a) `index.html`：刪除 Filters fieldset 裡的 port/proto `form-row`（`qt-port`、`qt-proto` 兩個 form-group）與 Excludes fieldset 裡的 `qt-expt` form-group；Excludes fieldset 若因此變空則整個 fieldset 一併移除。`gui_qt_object_filters` 的 label 文案改鍵值（兩語）提及 Services/Ports：zh `「來源 / 目的 / 任一（Label、IP、Workload、IP List、服務、Port）」`、en 對應。

(b) `quarantine.js` `runTrafficAnalyzer`：刪除三行讀值（`:277-279`）與三行 payload 組裝（`:293-295`）；`Object.assign(payload, _ensureQtFilterBar().getFilters())` 既有行不動（pill 序列化已含新 key）。

(c) `rules.js`：兩處 cats 改為：

```js
    _trFb = createFilterBar(document.getElementById('tr-filter-bar'), { cats: ['label', 'iplist', 'workload', 'ip', 'service', 'port'] });
```

```js
    _bwFb = createFilterBar(document.getElementById('bw-filter-bar'), { cats: ['label', 'iplist', 'workload', 'ip', 'service', 'port'] });
```

(d) 驗證後端直通：grep `/api/quarantine/search` 的 route handler（`src/gui/routes/` 下）確認 filters 是否白名單制；若是，將 `services`/`ex_services`/`ports`/`ex_ports` 加入白名單（照該檔既有 key 清單樣式）。即時報表/排程報表/儲存查詢的 filters 傳遞同樣检查一次（Phase 4 已做直通的路徑預期不需改）。

- [ ] **Step 4: 跑測試**

Run: `pytest tests/test_component_object_filter_bar.py tests/test_gui_rules_filters.py -q && node --check src/static/js/quarantine.js && node --check src/static/js/rules.js`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/templates/index.html src/static/js/quarantine.js src/static/js/rules.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): replace scalar port fields with filter pills across traffic entry points"
```

---

### Task 12: CLI object_picker 服務/Port 類別與落點

**Files:**
- Modify: `src/cli/object_picker.py`
- Modify: `src/cli/menus/traffic.py`（port scalar 步驟改 picker）、`src/cli/menus/bandwidth.py`（同）、`src/pce_cache_cli.py`（traffic filter 編輯加類別）
- Modify: `src/i18n/`（CLI 文案鍵，照 `cli_pick_*` 既有鍵所在檔案）
- Test: `tests/test_cli_object_picker.py`（若無此檔則新建；已有 picker 測試檔則擴充）

**Interfaces:**
- Consumes: `ApiClient.get_services()`、`parse_port_token`、`_service_summary`（自 `src.gui.filter_object_cache` import——純函式無 Flask 依賴）。
- Produces: `_CAT_ORDER` 增 `service`/`port`；`pick_objects` 回傳 dict 可含 `services`（href list）/`ports`（token list）；新函式 `picked_to_service_filters(picked, exclude=False) -> dict`（`services`/`ports` 或 `ex_services`/`ex_ports`）；`legacy_service_to_preselected(rule, exclude=False) -> dict | None`（讀新 list key 與舊 scalar `port`/`proto`/`ex_port`）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_cli_object_picker.py（新檔或擴充既有）
"""object_picker 的 service/port 類別與序列化契約（非 TTY 路徑 + 純函式）。"""
from unittest.mock import MagicMock, patch

from src.cli.object_picker import (
    _CAT_ORDER, _load_candidates, pick_objects,
    picked_to_service_filters, legacy_service_to_preselected,
)


def test_cat_order_has_service_and_port():
    assert "service" in _CAT_ORDER and "port" in _CAT_ORDER


def test_load_candidates_service():
    api = MagicMock()
    api.get_services.return_value = [
        {"name": "Web", "href": "/s/1", "service_ports": [{"port": 80, "proto": 6}]}]
    cands = _load_candidates(api, "service")
    assert cands == [("Web (tcp/80)", "/s/1")]


def test_picked_to_service_filters():
    picked = {"services": ["/s/1"], "ports": ["443/tcp"]}
    assert picked_to_service_filters(picked) == {"services": ["/s/1"], "ports": ["443/tcp"]}
    assert picked_to_service_filters(picked, exclude=True) == {
        "ex_services": ["/s/1"], "ex_ports": ["443/tcp"]}


def test_legacy_service_to_preselected_scalar_port():
    rule = {"port": 443, "proto": 6}
    assert legacy_service_to_preselected(rule) == {"ports": ["443/tcp"]}
    assert legacy_service_to_preselected({"ex_port": 22}, exclude=True) == {"ports": ["22"]}
    assert legacy_service_to_preselected({"services": ["/s/1"], "ports": ["80"]}) == {
        "services": ["/s/1"], "ports": ["80"]}


def test_non_tty_port_validation(monkeypatch):
    # 非 TTY input() 降級路徑：非法 token 被過濾
    import src.cli.object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["80, notaport, 443/tcp", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = pick_objects(MagicMock(), cats=("port", "service"), title="t")
    assert out == {"ports": ["80", "443/tcp"]}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_cli_object_picker.py -q`
Expected: FAIL

- [ ] **Step 3: 實作 object_picker.py**

(a) 常數：

```python
_CAT_ORDER = ("label", "label_group", "iplist", "workload", "ip", "service", "port")

_CAT_TITLES = {
    "label": "Label",
    "label_group": "Label Group",
    "iplist": "IP List",
    "workload": "Workload",
    "ip": "IP/CIDR (manual)",
    "service": "Service",
    "port": "Port (manual)",
}

_CAT_RESULT_KEY = {"label": "labels", "label_group": "label_groups",
                   "iplist": "iplists", "workload": "workloads", "ip": "ips",
                   "service": "services", "port": "ports"}
```

(b) `_load_candidates` 加：

```python
    if cat == "service":
        from src.gui.filter_object_cache import _service_summary
        out = []
        for s in api.get_services():
            summary = _service_summary(s)
            display = f"{s['name']} ({summary})" if summary else s["name"]
            out.append((display, s["href"]))
        return out
```

(c) 手動 port 驗證：`_manual_text_entry` 與 `_pick_non_tty` 的 `if cat == "ip":` 過濾旁各加：

```python
        if cat == "port":
            from src.port_token import parse_port_token
            values = [v for v in values if parse_port_token(v)]
```

(d) `_pick_tty`：`if cat == "ip":` 分支改為 `if cat in ("ip", "port"):`（兩者皆走 `_manual_text_entry`）。

(e) 檔尾新函式：

```python
def picked_to_service_filters(picked, exclude=False):
    """pick_objects 回傳 dict → 無方向的 service/port filter key（只含非空）。"""
    prefix = "ex_" if exclude else ""
    out = {}
    if picked.get("services"):
        out[f"{prefix}services"] = picked["services"]
    if picked.get("ports"):
        out[f"{prefix}ports"] = picked["ports"]
    return out


def legacy_service_to_preselected(rule, exclude=False):
    """規則 dict → service/port 類別的 preselected（新 list key 優先，
    舊 scalar port/proto/ex_port 轉 token；零遷移讀取相容）。"""
    if not rule:
        return None
    result = {}
    if exclude:
        if rule.get("ex_services"):
            result["services"] = _as_list(rule["ex_services"])
        ports = _as_list(rule.get("ex_ports"))
        if not ports and rule.get("ex_port"):
            ports = [str(rule["ex_port"])]
        if ports:
            result["ports"] = ports
        return result or None
    if rule.get("services"):
        result["services"] = _as_list(rule["services"])
    ports = _as_list(rule.get("ports"))
    if not ports and rule.get("port"):
        proto_name = {6: "tcp", 17: "udp"}.get(rule.get("proto"))
        ports = [f"{rule['port']}/{proto_name}" if proto_name else str(rule["port"])]
    if ports:
        result["ports"] = ports
    return result or None
```

- [ ] **Step 4: 跑 picker 測試**

Run: `pytest tests/test_cli_object_picker.py -q`
Expected: PASS

- [ ] **Step 5: 落點接線**

(a) `src/cli/menus/traffic.py`：第 2 步（`_wizard_step(2, 5, ...)` 區、`port_in`/`proto_in` 的 `safe_input` 段落）整段替換為 picker 呼叫（`_pick`＝檔內既有的 pick_objects 包裝，import 區加 `picked_to_service_filters, legacy_service_to_preselected`）：

```python
    _wizard_step(2, 5, t("wiz_traffic_filters"))
    print(f"\n{Colors.CYAN}{t('advanced_filters')}{Colors.ENDC}")
    print(f"{Colors.DARK_GRAY}{t('hint_return')}{Colors.ENDC}")

    svc_picked = _pick(
        api, cats=("service", "port"), title=t("wiz_svc_include"),
        preselected=legacy_service_to_preselected(edit_rule) if edit_rule else None,
    )
    if svc_picked is None:
        return
    ex_svc_picked = _pick(
        api, cats=("service", "port"), title=t("wiz_svc_exclude"),
        preselected=legacy_service_to_preselected(edit_rule, exclude=True) if edit_rule else None,
    )
    if ex_svc_picked is None:
        return
```

規則組裝處（`new_rule.update(picked_to_flat_filters(...))` 四行之後）加：

```python
    new_rule.update(picked_to_service_filters(svc_picked, exclude=False))
    new_rule.update(picked_to_service_filters(ex_svc_picked, exclude=True))
```

舊 `port`/`proto` scalar 不再寫入 new_rule（讀取端相容已由 legacy 轉換覆蓋；若檔內後續步驟仍引用 `port_in`/`proto_in` 變數，一併移除該引用）。i18n 新鍵 `wiz_svc_include`（zh「服務 / Port 條件（包含）」）、`wiz_svc_exclude`（zh「服務 / Port 條件（排除）」）、en 對應，加進 CLI 鍵所在 i18n 檔。

(b) `src/cli/menus/bandwidth.py`：同 (a) 樣式（該檔 picker 呼叫結構與 traffic.py 一致，port scalar 步驟同樣替換）。

(c) `src/pce_cache_cli.py:91` 附近的 traffic filter picker 呼叫：cats tuple 加 `"service", "port"`，結果合併處加 `picked_to_service_filters`（照該檔既有合併樣式）。

- [ ] **Step 6: 跑測試與 CLI 煙霧**

Run: `pytest tests/test_cli_object_picker.py tests/ -q -k "cli or menu" && python -c "import src.cli.menus.traffic, src.cli.menus.bandwidth, src.pce_cache_cli"`
Expected: 全 PASS、import 無錯

- [ ] **Step 7: Commit**

```bash
git add src/cli/object_picker.py src/cli/menus/traffic.py src/cli/menus/bandwidth.py src/pce_cache_cli.py src/i18n_en.json src/i18n_zh_TW.json tests/test_cli_object_picker.py
git commit -m "feat(cli): add service and port categories to object picker and wizards"
```

---

### Task 13: E2E、i18n 稽核與全套迴歸

**Files:**
- Modify: Playwright E2E 測試（照專案既有 E2E 測試所在位置與樣式；若既有 E2E 為手動腳本則沿用該形式）
- Test: 全套

**Interfaces:** 無新介面；驗收閘門。

- [ ] **Step 1: E2E 情境（Playwright，照既有 E2E 慣例撰寫）**

1. 流量分析器 filter modal：點輸入框（空輸入）→ 出現類別 chip（含數字）→ 點「服務」→ 出現分組清單 → 點「載入更多」→ 清單增長 → 點一項成 pill。
2. 打 `443/tcp` → 出現「加入 Port」→ Enter 成 pill → 點 pill → popover 無方向列、可切排除。
3. 下拉底部「在視窗中瀏覽全部…」→ modal 開啟 → 切「Labels」分頁 → 勾 2 項 → 加入 → 2 個 pill 出現。
4. 手動 IP/CIDR 迴歸：打 `10.0.0.0/24` → 「加入 IP/CIDR」候選存在 → 成 pill（覆蓋本案的 IP 輸入確認需求）。
5. 送出查詢：pill 組合送 `/api/quarantine/search`，斷言 request payload 含 `services`/`ports` key。

- [ ] **Step 2: i18n 稽核**

Run: 專案既有 i18n 稽核測試（`pytest tests/ -q -k i18n`）
Expected: PASS（新鍵雙語齊全、JS 引用鍵皆存在）

- [ ] **Step 3: 全套迴歸**

Run: `pytest -q`
Expected: 全 PASS，無 skip 異常增加

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add e2e coverage for service/port pills and object browse"
```

---

## 交付後驗證（部署階段，不在本計畫 task 內）

依專案慣例部署測試機（172.16.15.106）後，以真實 PCE 走一遍：選 service 物件查流量、手動 port（三種語法）、手動 IP/CIDR；逐頁檢查 pill/摘要無截斷溢出，結果附在回報裡（CLAUDE.md 報表規範）。

## Self-Review 紀錄

- Spec 覆蓋：§4.1(Task 6)、§4.2(Task 7)、§4.3(Tasks 1-4)、§4.4(Task 5)、§5.1(Task 8)、§5.2(Tasks 9-10)、§5.3(各 task 內嵌 i18n)、§6(Task 12)、§8 錯誤處理（Tasks 3-5 unresolved/cap、Task 7 502、Task 9 browse_error、Task 8 非法 token 不出候選）、§9 測試（Tasks 各 step＋Task 13）。
- 型別一致：`parse_port_token` 回傳 dict 形狀在 Tasks 3/4/5/12 一致；`resolve_service_entries` 回 `list|None` 在 Tasks 2/4/5 一致；filter key 名稱 `services`/`ex_services`/`ports`/`ex_ports` 貫穿 8/11/12。
- 已知現場調整點（實作者須以檔案現況為準）：`_flow_matches_filters` 的實際簽章與 helper 所在層、`expand_object_filters_for_df` 的結果變數名、E2E 測試形式、`/api/quarantine/search` 是否白名單制（Task 11 Step 3d）。
