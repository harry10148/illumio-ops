# Filter 物件選擇器 Phase 1：查詢層擴充 + 同 key OR 修正 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 filter 詞彙表支援 IP List / Workload 物件，並把多 label 語意修正為「同 key OR、跨 key AND」（對齊 PCE 原生，已於 2026-07-03 以真實 PCE 實測證實：同 inner group `[[A,B]]` 回 0 筆、分組 `[[A],[B]]` 回聯集 505 筆）。

**Architecture:** 三條查詢消費路徑同步升級——(1) native async payload builder（`src/api/traffic_query.py`）、(2) client-side fallback（`_flow_matches_filters`）、(3) cache DataFrame 路徑（`src/report/df_filter.py`，iplist/workload 需經 `LabelResolver` 預先展開成 CIDR/IP 清單）。不改任何 HTTP 介面與 config schema。

**Tech Stack:** Python 3.10+、pytest、pandas、SQLAlchemy（僅讀）、既有 `ApiClient`/`LabelResolver`/`TrafficQueryBuilder` 結構。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md`（§4.2、§2.2）

## Global Constraints

- 程式內註解用繁體中文，commit message 用英文 conventional commits（repo 慣例）。
- 絕不使用 emoji。
- 只動本計畫列出的檔案；不「順手」重構鄰近程式。
- 每個 Task 結尾跑該 Task 的測試 + commit；Task 7 跑全量 `python3 -m pytest tests/ -x -q`（基準：2237 passed）。
- 測試建 client 一律沿用 `tests/test_api_client.py` 的樣式：`ApiClient(MagicMock cm)` + 預填 `_label_href_cache` 等 dict + `update_label_cache = MagicMock()`（避免測試打網路）。
- label href cache 的鍵格式是 `"key:value"`（冒號），filter 輸入接受 `key=value` 與 `key:value` 兩種寫法（`_normalize_label_filter` 已處理）。

---

### Task 1: 同 key label OR 展開（native payload builder）

**Files:**
- Modify: `src/api/traffic_query.py`（新增模組層 helper + 改 `_build_native_traffic_payload` 的 label include 處理，現行單一 group 邏輯在 268-288 行）
- Test: `tests/test_traffic_query_label_or.py`（新檔）

**Interfaces:**
- Produces: 模組層函式 `group_label_specs_by_key(values: list) -> "OrderedDict[str, list]"`（Task 2、3 重用同名語意但各自實作於所在模組，不 import 共享——三個檔案分屬不同層，避免跨層依賴）。
- Produces: payload 行為——同側同 key 多 label 展開為多個 include group（笛卡兒積），Task 7 的回歸依賴此行為。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_traffic_query_label_or.py
"""同 key label OR 展開：native payload 需產生 OR-of-AND 巢狀群組。

實測基準（2026-07-03 真實 PCE）：[[A,B]] 同組=AND（0 筆）、[[A],[B]] 分組=OR。
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


def _mk_client():
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "k", "secret": "s", "verify_ssl": True}}
    c = ApiClient(cm)
    c._label_href_cache = {
        "app:erp": "/orgs/1/labels/11",
        "app:web": "/orgs/1/labels/12",
        "env:prod": "/orgs/1/labels/21",
    }
    c.update_label_cache = MagicMock(return_value=None)
    td = tempfile.TemporaryDirectory()
    c._state_file = os.path.join(td.name, "state.json")
    c._td = td  # 保活
    return c


class TestSameKeyLabelOrExpansion(unittest.TestCase):
    def setUp(self):
        self.client = _mk_client()

    def _build(self, filters):
        payload, spec = self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z", "2026-04-01T01:00:00Z", ["allowed"], filters=filters)
        return payload, spec

    def test_same_key_two_labels_expand_to_or_groups(self):
        payload, _ = self._build({"src_labels": ["app=erp", "app=web"]})
        self.assertEqual(payload["sources"]["include"], [
            [{"label": {"href": "/orgs/1/labels/11"}}],
            [{"label": {"href": "/orgs/1/labels/12"}}],
        ])

    def test_cross_key_stays_and_within_group(self):
        payload, _ = self._build({"src_labels": ["app=erp", "env=prod"]})
        self.assertEqual(payload["sources"]["include"], [
            [{"label": {"href": "/orgs/1/labels/11"}},
             {"label": {"href": "/orgs/1/labels/21"}}],
        ])

    def test_mixed_same_and_cross_key_cartesian(self):
        payload, _ = self._build({"src_labels": ["app=erp", "app=web", "env=prod"]})
        self.assertEqual(payload["sources"]["include"], [
            [{"label": {"href": "/orgs/1/labels/11"}},
             {"label": {"href": "/orgs/1/labels/21"}}],
            [{"label": {"href": "/orgs/1/labels/12"}},
             {"label": {"href": "/orgs/1/labels/21"}}],
        ])

    def test_dst_side_expands_too(self):
        payload, _ = self._build({"dst_labels": ["app=erp", "app=web"]})
        self.assertEqual(len(payload["destinations"]["include"]), 2)

    def test_unresolvable_label_still_falls_back_whole_family(self):
        payload, spec = self._build({"src_labels": ["app=erp", "app=nosuch"]})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_labels", spec.fallback_filters)

    def test_cartesian_cap_falls_back(self):
        # 超過 100 組合 → 整個 family 降級 fallback，不送爆量 payload
        cache = {f"k{i}:v{j}": f"/orgs/1/labels/{i*100+j}" for i in range(3) for j in range(6)}
        self.client._label_href_cache = cache
        vals = [f"k{i}=v{j}" for i in range(3) for j in range(6)]  # 6*6*6=216 組合
        payload, spec = self._build({"src_labels": vals})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_labels", spec.fallback_filters)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_traffic_query_label_or.py -v`
Expected: `test_same_key_two_labels_expand_to_or_groups` FAIL（現行產生單一 group `[[erp, web]]`）；`test_cross_key_stays_and_within_group` 可能 PASS（現行本來就同組）——這是預期的，其餘至少 3 個 FAIL。

- [ ] **Step 3: 實作**

在 `src/api/traffic_query.py` 模組層（`_TRAFFIC_FILTER_CAPABILITIES` 定義之後）新增：

```python
_LABEL_OR_EXPANSION_CAP = 100  # 笛卡兒積組數上限，超過即整族降級 fallback


def group_label_specs_by_key(values):
    """把 label filter 字串依維度 key 分組（同 key OR、跨 key AND 的前置）。

    "key=value" 與 "key:value" 皆可；無法解析 key 的字串各自成一組
    （鍵用位置序號佔位）——維持舊有 AND 語意，不猜測。
    回傳 dict（插入序即維度序，Python 3.7+ dict 保序）。
    """
    grouped = {}
    for i, raw in enumerate(values):
        text = str(raw).strip()
        key = None
        for sep in ("=", ":"):
            if sep in text:
                key = text.split(sep, 1)[0].strip().lower()
                break
        if not key:
            key = f"__pos{i}"
        grouped.setdefault(key, []).append(text)
    return grouped
```

改 `_build_native_traffic_payload` 的 include 迴圈（268-288 行）：把 label 家族從通用 `include_specs` 抽出，`include_specs` 移除 `(("src_label", "src_labels"), ...)` 與 `(("dst_label", "dst_labels"), ...)` 兩列，改在迴圈前插入專屬處理：

```python
        import itertools

        # 同 key OR、跨 key AND（對齊 PCE 原生；spec §2.2 實測依據）：
        # 依 key 分組 → 每 key 內各值為 OR 選項 → 跨 key 笛卡兒積展開成
        # 多個 include group（外層 OR、內層 AND）。
        for keys, side in ((("src_label", "src_labels"), "sources"),
                           (("dst_label", "dst_labels"), "destinations")):
            values, used_keys = _pop_many(keys)
            if not values:
                continue
            grouped = group_label_specs_by_key(values)
            per_key_actors = []
            unresolved = False
            n_combos = 1
            for specs_for_key in grouped.values():
                actors = []
                for value in specs_for_key:
                    item = labels._resolve_label_filter_to_actor(value)
                    if item is None:
                        unresolved = True
                        break
                    actors.append(item)
                if unresolved:
                    break
                per_key_actors.append(actors)
                n_combos *= len(actors)
            if unresolved or n_combos > _LABEL_OR_EXPANSION_CAP:
                if n_combos > _LABEL_OR_EXPANSION_CAP:
                    logger.warning(
                        "Label OR expansion exceeds cap ({} > {}); falling back to client-side",
                        n_combos, _LABEL_OR_EXPANSION_CAP)
                for key in used_keys:
                    _record_unresolved(key, spec.native_filters.get(key))
                _consume_keys(used_keys)
                continue
            for combo in itertools.product(*per_key_actors):
                payload[side]["include"].append(labels._dedupe_query_group(list(combo)))
            for key in used_keys:
                _record_consumed(key, spec.native_filters.get(key))
            _consume_keys(used_keys)
```

注意：`import itertools` 放檔案頂部的既有 import 區，不要放函式內。

- [ ] **Step 4: 跑新測試 + 既有 builder 測試**

Run: `python3 -m pytest tests/test_traffic_query_label_or.py tests/test_api_client.py -v`
Expected: 全 PASS。特別注意 `test_build_native_payload_pushes_supported_filters` —— 該測試 `src_label` 單值 + `src_ams`，`_append_ams` 會把 ams 附掛到每個 include group，單值單 group 行為不變，應仍 PASS。若 FAIL，檢查 label 專屬處理是否在 `_append_actor_groups`/`_append_ams`（290-293 行）**之前**執行（順序必須維持）。

- [ ] **Step 5: Commit**

```bash
git add src/api/traffic_query.py tests/test_traffic_query_label_or.py
git commit -m "fix(traffic_query): expand same-key labels to OR groups in native payload

Same-key labels previously joined one include group (AND) which a live
PCE returns 0 flows for; now same-key=OR, cross-key=AND via cartesian
expansion (capped at 100 groups, falls back to client-side beyond)."
```

---

### Task 2: client-side fallback 同 key any 語意

**Files:**
- Modify: `src/api/traffic_query.py`（`_flow_matches_filters`，692-697 行的 src/dst_labels 迴圈）
- Test: `tests/test_traffic_query_fallback_semantics.py`（新檔）

**Interfaces:**
- Consumes: `TrafficQueryBuilder._flow_matches_filters(flow: dict, filters: dict) -> bool`（staticmethod；若實際是 instance method，測試改為建 `_mk_client()` 後呼叫）。
- Produces: fallback 語意——`src_labels`/`dst_labels` 同 key any、跨 key all。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_traffic_query_fallback_semantics.py
"""client-side fallback 的同 key OR 語意（與 native 路徑對齊）。"""
from src.api.traffic_query import TrafficQueryBuilder


def _flow(src_labels=(), dst_labels=()):
    def side(labels):
        return {"workload": {"labels": [{"key": k, "value": v} for k, v in labels]}}
    return {"src": side(src_labels), "dst": side(dst_labels), "service": {}}


def _match(flow, filters):
    return TrafficQueryBuilder._flow_matches_filters(flow, filters)


def test_same_key_two_values_is_or():
    flow = _flow(src_labels=[("app", "erp")])
    assert _match(flow, {"src_labels": ["app=erp", "app=web"]}) is True


def test_same_key_no_value_matches_rejects():
    flow = _flow(src_labels=[("app", "hr")])
    assert _match(flow, {"src_labels": ["app=erp", "app=web"]}) is False


def test_cross_key_still_and():
    flow = _flow(src_labels=[("app", "erp")])  # 缺 env=prod
    assert _match(flow, {"src_labels": ["app=erp", "env=prod"]}) is False
    flow2 = _flow(src_labels=[("app", "erp"), ("env", "prod")])
    assert _match(flow2, {"src_labels": ["app=erp", "env=prod"]}) is True


def test_dst_side_same_semantics():
    flow = _flow(dst_labels=[("env", "prod")])
    assert _match(flow, {"dst_labels": ["env=prod", "env=dr"]}) is True


def test_unparseable_spec_must_match_individually():
    # 無 key 可解析的字串維持舊語意：該條件必須自行成立（AND）
    flow = _flow(src_labels=[("app", "erp")])
    assert _match(flow, {"src_labels": ["app=erp", "garbage"]}) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_traffic_query_fallback_semantics.py -v`
Expected: `test_same_key_two_values_is_or` 與 `test_dst_side_same_semantics` FAIL（現行 AND）；其餘 PASS。若 `_flow_matches_filters` 不是 staticmethod 導致 import/呼叫錯誤，依實際簽名調整 `_match`（可能需要 `TrafficQueryBuilder.__dict__["_flow_matches_filters"]` 取原函式或建 client 實例）。

- [ ] **Step 3: 實作**

把 692-697 行的兩個迴圈：

```python
        for lbl in (filters.get('src_labels') or []):
            if lbl and not _label_match(src, lbl):
                return False
        for lbl in (filters.get('dst_labels') or []):
            if lbl and not _label_match(dst, lbl):
                return False
```

改為（`group_label_specs_by_key` 為 Task 1 加入的模組層函式，同檔可直接用）：

```python
        # 同 key any、跨 key all —— 與 native 路徑的 OR 展開語意一致（spec §2.2）
        for fkey, side_obj in (("src_labels", src), ("dst_labels", dst)):
            specs = [s for s in (filters.get(fkey) or []) if s]
            if not specs:
                continue
            for group in group_label_specs_by_key(specs).values():
                if not any(_label_match(side_obj, s) for s in group):
                    return False
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_traffic_query_fallback_semantics.py tests/test_analyzer_with_mock_api.py -v`
Expected: 全 PASS（analyzer 測試守既有行為不回歸）。

- [ ] **Step 5: Commit**

```bash
git add src/api/traffic_query.py tests/test_traffic_query_fallback_semantics.py
git commit -m "fix(traffic_query): same-key any semantics in client-side label fallback"
```

---

### Task 3: df_filter 同 key any 語意

**Files:**
- Modify: `src/report/df_filter.py`（`_label_mask`，23-42 行）
- Test: `tests/test_df_filter.py`（既有檔案，新增測試）

**Interfaces:**
- Produces: `_label_mask(df, side, specs)` 新語意——同 key 內 OR、跨 key AND；函式簽名不變，`apply_df_traffic_filters` 呼叫端零改動。

- [ ] **Step 1: 寫失敗測試（加到 tests/test_df_filter.py 檔尾）**

先看檔案開頭既有的 df fixture 建法（該檔已有建 DataFrame 的 helper/樣式，沿用之；下方以標準欄位自建為例）：

```python
import pandas as pd

from src.report.df_filter import apply_df_traffic_filters


def _df_two_apps():
    return pd.DataFrame([
        {"src_app": "erp", "src_env": "prod", "dst_app": "", "dst_env": "",
         "src_extra_labels": {}, "dst_extra_labels": {},
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.9", "port": 443, "proto": "TCP"},
        {"src_app": "web", "src_env": "prod", "dst_app": "", "dst_env": "",
         "src_extra_labels": {}, "dst_extra_labels": {},
         "src_ip": "10.0.0.2", "dst_ip": "10.0.0.9", "port": 443, "proto": "TCP"},
        {"src_app": "hr", "src_env": "dr", "dst_app": "", "dst_env": "",
         "src_extra_labels": {}, "dst_extra_labels": {},
         "src_ip": "10.0.0.3", "dst_ip": "10.0.0.9", "port": 443, "proto": "TCP"},
    ])


def test_same_key_labels_or_in_df_path():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app=erp", "app=web"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1", "10.0.0.2"]


def test_cross_key_labels_still_and_in_df_path():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app=erp", "env=prod"]})
    assert list(out["src_ip"]) == ["10.0.0.1"]


def test_same_key_or_with_custom_dimension():
    df = _df_two_apps()
    df.at[0, "src_extra_labels"] = {"Net": "Server-A"}
    df.at[2, "src_extra_labels"] = {"Net": "Server-B"}
    out = apply_df_traffic_filters(df, {"src_labels": ["Net=Server-A", "Net=Server-B"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1", "10.0.0.3"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_df_filter.py -v -k "same_key or cross_key"`
Expected: `test_same_key_labels_or_in_df_path` 與 `test_same_key_or_with_custom_dimension` FAIL（現行 AND 給空結果）；`test_cross_key_labels_still_and_in_df_path` PASS。

- [ ] **Step 3: 實作**

改 `_label_mask`（docstring 一併更新）：

```python
def _label_mask(df: pd.DataFrame, side: str, specs: list[str]) -> pd.Series:
    """同 key 內 OR、跨 key AND（對齊 PCE 原生語意，spec §2.2）。"""
    def one(spec: str) -> pd.Series:
        k, v = spec.split("=", 1)
        k, v = k.strip(), v.strip()
        col = f"{side}_{k}"
        if col in df.columns:
            return df[col].astype(str) == v
        exc = f"{side}_extra_labels"
        if exc in df.columns:
            return df[exc].apply(
                lambda d, _k=k, _v=v: isinstance(d, dict) and d.get(_k) == _v)
        return pd.Series(False, index=df.index)

    by_key: dict[str, list[str]] = {}
    for spec in specs:
        if "=" not in spec:
            continue
        by_key.setdefault(spec.split("=", 1)[0].strip(), []).append(spec)

    m = pd.Series(True, index=df.index)
    for group in by_key.values():
        gm = pd.Series(False, index=df.index)
        for spec in group:
            gm |= one(spec)
        m &= gm
    return m
```

- [ ] **Step 4: 跑整個 df_filter 測試檔**

Run: `python3 -m pytest tests/test_df_filter.py -v`
Expected: 全 PASS（既有排除/`query_operator` 測試不回歸；`ex_*` 走同一 `_label_mask`，同 key OR 後取反 = 「命中任一同 key 排除值即剔除」，語意不變）。

- [ ] **Step 5: Commit**

```bash
git add src/report/df_filter.py tests/test_df_filter.py
git commit -m "fix(df_filter): same-key OR / cross-key AND label semantics in cache path"
```

---

### Task 4: iplist / workload 新 native filter keys

**Files:**
- Modify: `src/api/labels.py`（`_resolve_ip_filter_to_actor` 之後新增兩個 resolver，381-403 行後）
- Modify: `src/api/traffic_query.py`（capability matrix 37-92 行 + include_specs 251-258 行 + exclude_specs 259-266 行）
- Test: `tests/test_traffic_query_object_actors.py`（新檔）

**Interfaces:**
- Produces: `LabelResolver._resolve_iplist_filter_to_actor(value) -> dict | None`（回 `{"ip_list": {"href": ...}}`）與 `LabelResolver._resolve_workload_filter_to_actor(value) -> dict | None`（回 `{"workload": {"href": ...}}`）。
- Produces: filter keys `src_iplist`/`src_iplists`/`dst_iplist`/`dst_iplists`/`ex_*` 同族、`src_workload`/`src_workloads`/`dst_workload`/`dst_workloads`/`ex_*` 同族——Phase 2 的 suggest 端點與 Phase 3 的 pill 序列化依賴這些 key 名。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_traffic_query_object_actors.py
"""IP List / Workload 物件 filter keys 的 native actor 解析。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


class TestObjectActorKeys(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self.client._iplist_href_cache = {
            "prod-subnets": "/orgs/1/sec_policy/draft/ip_lists/7"}
        self.client.update_label_cache = MagicMock(return_value=None)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def _build(self, filters):
        return self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z", "2026-04-01T01:00:00Z", ["allowed"], filters=filters)

    def test_src_iplist_by_name_resolves_to_ip_list_actor(self):
        payload, spec = self._build({"src_iplist": "prod-subnets"})
        self.assertEqual(payload["sources"]["include"], [
            [{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}}]])
        self.assertIn("src_iplist", spec.consumed_native_filters)

    def test_dst_iplists_by_href_list(self):
        payload, _ = self._build(
            {"dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/9"]})
        self.assertEqual(payload["destinations"]["include"], [
            [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/9"}}]])

    def test_src_workload_href(self):
        payload, _ = self._build({"src_workload": "/orgs/1/workloads/abc-123"})
        self.assertEqual(payload["sources"]["include"], [
            [{"workload": {"href": "/orgs/1/workloads/abc-123"}}]])

    def test_workload_non_href_falls_back(self):
        payload, spec = self._build({"src_workload": "prod-web-01"})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_workload", spec.fallback_filters)

    def test_ex_dst_iplist_goes_to_exclude(self):
        payload, _ = self._build({"ex_dst_iplist": "prod-subnets"})
        self.assertEqual(payload["destinations"]["exclude"], [
            {"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}}])

    def test_iplist_ignores_ip_literal(self):
        payload, spec = self._build({"src_iplist": "10.0.0.1"})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_iplist", spec.fallback_filters)
```

註：`spec.consumed_native_filters` 屬性名以 `TrafficQuerySpec` dataclass 實際欄位為準（見 `traffic_query.py:95` 附近）；若名稱不同（例如 `consumed`），先讀 dataclass 再調整斷言。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_traffic_query_object_actors.py -v`
Expected: 全部 FAIL——未知 key 會被 `build_traffic_query_spec` 歸類（讀 `build_traffic_query_spec` 對未註冊 key 的處置：進 fallback 或 report_only；斷言錯誤訊息會顯示實際行為）。

- [ ] **Step 3: 實作 resolvers（src/api/labels.py，_resolve_ip_filter_to_actor 之後）**

```python
    def _resolve_iplist_filter_to_actor(self, iplist_filter):
        """IP List 物件 filter → actor。接受 dict{href|name}、href 字串或名稱。
        刻意不接受 IP literal——那是 src_ip 家族的職責。"""
        c = self._client
        if not iplist_filter:
            return None
        if isinstance(iplist_filter, dict):
            href = iplist_filter.get("href")
            if href and "/ip_lists/" in str(href):
                return {"ip_list": {"href": str(href).strip()}}
            iplist_filter = iplist_filter.get("name") or ""
        candidate = str(iplist_filter).strip()
        if not candidate or self._is_ip_literal(candidate):
            return None
        if self._is_href(candidate):
            if "/ip_lists/" in candidate:
                return {"ip_list": {"href": candidate}}
            return None
        self._ensure_query_lookup_cache()
        href = c._iplist_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = c._iplist_href_cache.get(candidate)
        if href:
            return {"ip_list": {"href": href}}
        return None

    def _resolve_workload_filter_to_actor(self, workload_filter):
        """Workload 物件 filter → actor。只接受 href（dict 或字串）；
        名稱搜尋交給 suggest 端點在選取當下轉 href。"""
        if not workload_filter:
            return None
        if isinstance(workload_filter, dict):
            workload_filter = workload_filter.get("href") or ""
        candidate = str(workload_filter).strip()
        if candidate and self._is_href(candidate) and "/workloads/" in candidate:
            return {"workload": {"href": candidate}}
        return None
```

註：`_iplist_href_cache` 的鍵大小寫格式以 `update_label_cache`（labels.py:190-281）實際寫入為準——先讀該段確認是原名還是 lowercase，測試 fixture 鍵要一致。

- [ ] **Step 4: 註冊 capability + specs（src/api/traffic_query.py）**

capability matrix（92 行 `}` 前）加入：

```python
    "src_iplist": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list href and pushed to sources.include."},
    "src_iplists": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list hrefs and pushed to sources.include."},
    "dst_iplist": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list href and pushed to destinations.include."},
    "dst_iplists": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list hrefs and pushed to destinations.include."},
    "ex_src_iplist": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list href and pushed to sources.exclude."},
    "ex_src_iplists": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list hrefs and pushed to sources.exclude."},
    "ex_dst_iplist": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list href and pushed to destinations.exclude."},
    "ex_dst_iplists": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to ip_list hrefs and pushed to destinations.exclude."},
    "src_workload": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload href pushed to sources.include."},
    "src_workloads": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload hrefs pushed to sources.include."},
    "dst_workload": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload href pushed to destinations.include."},
    "dst_workloads": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload hrefs pushed to destinations.include."},
    "ex_src_workload": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload href pushed to sources.exclude."},
    "ex_src_workloads": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload hrefs pushed to sources.exclude."},
    "ex_dst_workload": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload href pushed to destinations.exclude."},
    "ex_dst_workloads": {"execution": "native", "min_pce_version": "21.2", "notes": "Workload hrefs pushed to destinations.exclude."},
```

`include_specs`（251-258 行）加入四列：

```python
            (("src_iplist", "src_iplists"), "sources", labels._resolve_iplist_filter_to_actor),
            (("dst_iplist", "dst_iplists"), "destinations", labels._resolve_iplist_filter_to_actor),
            (("src_workload", "src_workloads"), "sources", labels._resolve_workload_filter_to_actor),
            (("dst_workload", "dst_workloads"), "destinations", labels._resolve_workload_filter_to_actor),
```

`exclude_specs`（259-266 行）加入四列（`ex_` 前綴同型）。

- [ ] **Step 5: 跑測試確認通過**

Run: `python3 -m pytest tests/test_traffic_query_object_actors.py tests/test_api_client.py -v`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add src/api/labels.py src/api/traffic_query.py tests/test_traffic_query_object_actors.py
git commit -m "feat(traffic_query): native ip_list and workload actor filter keys"
```

---

### Task 5: any_iplist / any_workload fallback keys + 側別 fallback 比對

**Files:**
- Modify: `src/api/traffic_query.py`（capability matrix + `_flow_matches_filters`）
- Test: `tests/test_traffic_query_fallback_semantics.py`（Task 2 建立的檔案，追加）

**Interfaces:**
- Produces: fallback keys `any_iplist`/`any_workload`/`ex_any_iplist`/`ex_any_workload`（單值，與既有 `any_label` 一致）；`_flow_matches_filters` 對 residual 的 `src_iplist(s)`/`src_workload(s)` 等 key 的比對能力（native 解析失敗降級時使用）。

- [ ] **Step 1: 寫失敗測試（追加到 tests/test_traffic_query_fallback_semantics.py）**

```python
def _flow_with_objects(src_iplists=(), dst_iplists=(), src_wl_href="", dst_wl_href=""):
    def side(ipls, href):
        d = {"ip_lists": [{"name": n, "href": h} for n, h in ipls]}
        if href:
            d["workload"] = {"href": href, "labels": []}
        return d
    return {"src": side(src_iplists, src_wl_href),
            "dst": side(dst_iplists, dst_wl_href), "service": {}}


def test_any_iplist_matches_either_side():
    flow = _flow_with_objects(dst_iplists=[("prod-subnets", "/orgs/1/sec_policy/active/ip_lists/7")])
    assert _match(flow, {"any_iplist": "prod-subnets"}) is True
    assert _match(flow, {"any_iplist": "corp-vpn"}) is False


def test_any_workload_matches_either_side_by_href():
    flow = _flow_with_objects(src_wl_href="/orgs/1/workloads/abc")
    assert _match(flow, {"any_workload": "/orgs/1/workloads/abc"}) is True
    assert _match(flow, {"any_workload": "/orgs/1/workloads/zzz"}) is False


def test_ex_any_iplist_rejects_when_hit():
    flow = _flow_with_objects(src_iplists=[("corp-vpn", "/orgs/1/sec_policy/active/ip_lists/3")])
    assert _match(flow, {"ex_any_iplist": "corp-vpn"}) is False
    assert _match(flow, {"ex_any_iplist": "other"}) is True


def test_residual_src_iplist_side_specific():
    flow = _flow_with_objects(src_iplists=[("corp-vpn", "/orgs/1/sec_policy/active/ip_lists/3")])
    assert _match(flow, {"src_iplists": ["corp-vpn"]}) is True
    assert _match(flow, {"dst_iplists": ["corp-vpn"]}) is False


def test_residual_src_workload_side_specific():
    flow = _flow_with_objects(src_wl_href="/orgs/1/workloads/abc")
    assert _match(flow, {"src_workloads": ["/orgs/1/workloads/abc"]}) is True
    assert _match(flow, {"dst_workloads": ["/orgs/1/workloads/abc"]}) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_traffic_query_fallback_semantics.py -v`
Expected: 新增 5 個測試 FAIL（未知 key 現行被忽略 → `_match` 誤回 True 的斷言會抓到）。

- [ ] **Step 3: 實作**

capability matrix 加入：

```python
    "any_iplist": {"execution": "fallback", "notes": "Either-side ip_list membership requires client-side filtering."},
    "any_workload": {"execution": "fallback", "notes": "Either-side workload match requires client-side filtering."},
    "ex_any_iplist": {"execution": "fallback", "notes": "Either-side ip_list exclusion requires client-side filtering."},
    "ex_any_workload": {"execution": "fallback", "notes": "Either-side workload exclusion requires client-side filtering."},
```

`_flow_matches_filters` 內、`_ip_match` 定義之後新增兩個 helper：

```python
        def _iplist_hit(side: dict, value: str) -> bool:
            for ipl in side.get('ip_lists', []) or []:
                if ipl.get('name') == value or ipl.get('href') == value:
                    return True
            return False

        def _workload_hit(side: dict, value: str) -> bool:
            return (side.get('workload') or {}).get('href') == value
```

`any_ip` 處理（725-728 行）之後加入側別 residual 與 any/ex_any 比對：

```python
        # 物件 filter 的 residual 比對（native 解析失敗降級、或 any_* 天生 fallback）
        for fkey, side_obj, hit in (
            ("src_iplist", src, _iplist_hit), ("src_iplists", src, _iplist_hit),
            ("dst_iplist", dst, _iplist_hit), ("dst_iplists", dst, _iplist_hit),
            ("src_workload", src, _workload_hit), ("src_workloads", src, _workload_hit),
            ("dst_workload", dst, _workload_hit), ("dst_workloads", dst, _workload_hit),
        ):
            vals = filters.get(fkey)
            if not vals:
                continue
            vals = vals if isinstance(vals, list) else [vals]
            if not any(hit(side_obj, v) for v in vals if v):
                return False

        for fkey, hit in (("any_iplist", _iplist_hit), ("any_workload", _workload_hit)):
            v = filters.get(fkey)
            if v and not (hit(src, v) or hit(dst, v)):
                return False
        for fkey, hit in (("ex_any_iplist", _iplist_hit), ("ex_any_workload", _workload_hit)):
            v = filters.get(fkey)
            if v and (hit(src, v) or hit(dst, v)):
                return False
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_traffic_query_fallback_semantics.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/api/traffic_query.py tests/test_traffic_query_fallback_semantics.py
git commit -m "feat(traffic_query): any/side-specific ip_list and workload fallback matching"
```

---

### Task 6: cache DataFrame 路徑的物件展開

**Files:**
- Modify: `src/api/labels.py`（新增 `expand_object_filters_for_df`）
- Modify: `src/api_client.py`（facade 委派一行，比照既有 `search_workloads` 委派樣式）
- Modify: `src/report/df_filter.py`（消費展開後的 CIDR 清單 keys）
- Modify: `src/report/report_generator.py`（`_fetch_traffic_df` 內兩處 `apply_df_traffic_filters` 呼叫前展開，240-280 行）
- Test: `tests/test_object_filter_df_expand.py`（新檔）+ `tests/test_df_filter.py`（追加）

**Interfaces:**
- Produces: `ApiClient.expand_object_filters_for_df(filters: dict) -> dict`——回傳淺拷貝，新增內部 keys `_src_object_cidrs`/`_dst_object_cidrs`/`_ex_src_object_cidrs`/`_ex_dst_object_cidrs`/`_any_object_cidrs`（list[str]，IP 或 CIDR）。iplist 依 `get_ip_lists()` 的 `ip_ranges`（`from_ip`/`to_ip`）換算 CIDR，workload 依 `get_workload(href)` 的 `interfaces[].address` 與 `public_ip`。
- Produces: `apply_df_traffic_filters` 消費上述 `_*_object_cidrs` keys（底線前綴 = 內部展開結果，不進儲存格式）。

- [ ] **Step 1: 寫展開器的失敗測試**

```python
# tests/test_object_filter_df_expand.py
"""iplist/workload filter → CIDR/IP 清單展開（df 路徑用；df 無 href 欄位）。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


class TestExpandObjectFiltersForDf(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")
        self.client.get_ip_lists = MagicMock(return_value=[
            {"name": "prod-subnets", "href": "/orgs/1/sec_policy/active/ip_lists/7",
             "ip_ranges": [{"from_ip": "10.10.0.0/16"},
                           {"from_ip": "10.20.0.1", "to_ip": "10.20.0.3"}]},
        ])
        self.client.get_workload = MagicMock(return_value={
            "href": "/orgs/1/workloads/abc",
            "public_ip": "203.0.113.5",
            "interfaces": [{"address": "10.1.2.3"}, {"address": "fe80::1"}],
        })

    def tearDown(self):
        self._td.cleanup()

    def test_iplist_name_expands_to_cidrs(self):
        out = self.client.expand_object_filters_for_df({"src_iplist": "prod-subnets"})
        cidrs = out["_src_object_cidrs"]
        assert "10.10.0.0/16" in cidrs
        # from/to range 以 summarize_address_range 換算
        assert "10.20.0.1/32" in cidrs and "10.20.0.2/31" in cidrs

    def test_workload_href_expands_to_ips(self):
        out = self.client.expand_object_filters_for_df(
            {"dst_workload": "/orgs/1/workloads/abc"})
        assert "10.1.2.3" in out["_dst_object_cidrs"]
        assert "203.0.113.5" in out["_dst_object_cidrs"]

    def test_unknown_iplist_yields_no_key(self):
        out = self.client.expand_object_filters_for_df({"src_iplist": "nosuch"})
        assert "_src_object_cidrs" not in out

    def test_no_object_keys_passthrough(self):
        f = {"src_labels": ["app=erp"]}
        out = self.client.expand_object_filters_for_df(f)
        assert out == f

    def test_any_iplist_expands_to_any_cidrs(self):
        out = self.client.expand_object_filters_for_df({"any_iplist": "prod-subnets"})
        assert "10.10.0.0/16" in out["_any_object_cidrs"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_object_filter_df_expand.py -v`
Expected: 全 FAIL（AttributeError: no attribute `expand_object_filters_for_df`）。

- [ ] **Step 3: 實作展開器（src/api/labels.py，LabelResolver 類內）**

```python
    def expand_object_filters_for_df(self, filters):
        """iplist/workload 物件 filter → CIDR/IP 清單（cache df 路徑用）。

        df 的統一 schema 沒有 workload href / ip_lists 欄位（api_parser
        flatten 只留 ip/hostname/labels），物件條件必須先展開成 IP 集合
        再交給 df_filter 的 CIDR mask。回傳淺拷貝；展開結果放底線前綴
        內部 key，不進任何儲存格式。
        """
        import ipaddress

        c = self._client
        obj_keys = {
            "_src_object_cidrs": ("src_iplist", "src_iplists", "src_workload", "src_workloads"),
            "_dst_object_cidrs": ("dst_iplist", "dst_iplists", "dst_workload", "dst_workloads"),
            "_ex_src_object_cidrs": ("ex_src_iplist", "ex_src_iplists", "ex_src_workload", "ex_src_workloads"),
            "_ex_dst_object_cidrs": ("ex_dst_iplist", "ex_dst_iplists", "ex_dst_workload", "ex_dst_workloads"),
            "_any_object_cidrs": ("any_iplist", "any_workload"),
        }
        if not filters or not any(
                filters.get(k) for keys in obj_keys.values() for k in keys):
            return filters

        def _iplist_cidrs(value):
            value = str(value).strip()
            for ipl in (c.get_ip_lists() or []):
                if ipl.get("name") == value or ipl.get("href") == value:
                    out = []
                    for r in ipl.get("ip_ranges", []) or []:
                        frm = r.get("from_ip")
                        to = r.get("to_ip")
                        if not frm:
                            continue
                        if not to or "/" in frm:
                            out.append(frm)
                            continue
                        try:
                            nets = ipaddress.summarize_address_range(
                                ipaddress.ip_address(frm), ipaddress.ip_address(to))
                            out.extend(str(n) for n in nets)
                        except ValueError:
                            logger.warning("Bad ip_range in {}: {}-{}", value, frm, to)
                    return out
            return []

        def _workload_ips(value):
            value = str(value).strip()
            if "/workloads/" not in value:
                return []
            wl = c.get_workload(value) or {}
            ips = [i.get("address") for i in wl.get("interfaces", []) or [] if i.get("address")]
            if wl.get("public_ip"):
                ips.append(wl["public_ip"])
            return ips

        out = dict(filters)
        for dest, keys in obj_keys.items():
            cidrs = []
            for k in keys:
                vals = filters.get(k)
                if not vals:
                    continue
                vals = vals if isinstance(vals, list) else [vals]
                for v in vals:
                    if not v:
                        continue
                    cidrs.extend(_iplist_cidrs(v) if "iplist" in k else _workload_ips(v))
            if cidrs:
                out[dest] = cidrs
        return out
```

facade 委派（`src/api_client.py`，`search_workloads` 附近同風格）：

```python
    def expand_object_filters_for_df(self, filters: dict) -> dict:
        """iplist/workload filter 展開成 CIDR/IP 清單（df 路徑用）。"""
        return self._labels.expand_object_filters_for_df(filters)
```

（`labels.py` 檔頭若無 `logger` import，比照該檔既有 logging 慣例補上。）

- [ ] **Step 4: 跑展開器測試**

Run: `python3 -m pytest tests/test_object_filter_df_expand.py -v`
Expected: 全 PASS。

- [ ] **Step 5: df_filter 消費 `_*_object_cidrs` — 先寫失敗測試（追加 tests/test_df_filter.py）**

```python
def test_object_cidrs_include_src():
    out = apply_df_traffic_filters(_df_two_apps(), {"_src_object_cidrs": ["10.0.0.0/31"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1"]


def test_object_cidrs_exclude_dst():
    out = apply_df_traffic_filters(_df_two_apps(), {"_ex_dst_object_cidrs": ["10.0.0.9"]})
    assert out.empty


def test_object_cidrs_any_side():
    out = apply_df_traffic_filters(_df_two_apps(), {"_any_object_cidrs": ["10.0.0.2"]})
    assert list(out["src_ip"]) == ["10.0.0.2"]
```

Run: `python3 -m pytest tests/test_df_filter.py -v -k object_cidrs`
Expected: 3 FAIL（key 被忽略）。

- [ ] **Step 6: df_filter 實作**

`apply_df_traffic_filters` 內、port 處理之前加入（重用既有 `_ip_mask`）：

```python
    def _cidrs_mask(col: str, values: list) -> pd.Series:
        gm = pd.Series(False, index=df.index)
        for v in values:
            gm |= _ip_mask(df, col, str(v))
        return gm

    for fkey, col, negate in (
        ("_src_object_cidrs", "src_ip", False),
        ("_dst_object_cidrs", "dst_ip", False),
        ("_ex_src_object_cidrs", "src_ip", True),
        ("_ex_dst_object_cidrs", "dst_ip", True),
    ):
        vals = filters.get(fkey)
        if vals and col in df.columns:
            m = _cidrs_mask(col, vals)
            mask &= ~m if negate else m

    any_cidrs = filters.get("_any_object_cidrs")
    if any_cidrs and "src_ip" in df.columns and "dst_ip" in df.columns:
        mask &= _cidrs_mask("src_ip", any_cidrs) | _cidrs_mask("dst_ip", any_cidrs)
```

Run: `python3 -m pytest tests/test_df_filter.py -v`
Expected: 全 PASS。

- [ ] **Step 7: report_generator 接線**

`_fetch_traffic_df`（`src/report/report_generator.py:231`）在 `pds = ...` 行之後加：

```python
        # iplist/workload 物件條件展開成 CIDR（df 無 href 欄位；spec §4.2）
        if filters and self.api is not None:
            filters = self.api.expand_object_filters_for_df(filters)
```

兩處 `apply_df_traffic_filters(df..., filters)` 呼叫（251、280 行）自動吃到展開後 filters，無需再改。

接線測試（追加到 `tests/test_object_filter_df_expand.py`）：

```python
    def test_report_generator_expands_before_df_filter(self):
        from src.report.report_generator import ReportGenerator
        rg = ReportGenerator.__new__(ReportGenerator)  # 不跑完整 __init__
        rg.api = self.client
        rg._cache = None
        # _fetch_traffic_df 在 cache 缺席時直接走 API 路徑；驗證展開器在
        # 該路徑一樣被呼叫（filters 傳給 fetch_traffic_for_report 前已含展開 key）
        captured = {}
        def fake_fetch(start_time_str, end_time_str, filters=None, compute_draft=False):
            captured.update(filters or {})
            return []
        self.client.fetch_traffic_for_report = fake_fetch
        rg._parse_api = lambda flows: __import__("pandas").DataFrame()
        import datetime as dt
        rg._fetch_traffic_df(dt.datetime(2026, 7, 1), dt.datetime(2026, 7, 2),
                             filters={"src_iplist": "prod-subnets"}, use_cache=False)
        assert "_src_object_cidrs" in captured
```

註：若 `_fetch_traffic_df` 的 API fallback 路徑簽名不符（`compute_draft` 等參數），以實際 233-290 行為準調整 fake。展開後的 `_` 前綴 key 對 native builder 是未知 key——確認 `build_traffic_query_spec` 對未註冊 key 的處置是「忽略或 report_only」而不會 raise；若會進 fallback residual，`_flow_matches_filters` 不認識 `_` 前綴 key、直接忽略，行為無害。

Run: `python3 -m pytest tests/test_object_filter_df_expand.py -v`
Expected: 全 PASS。

- [ ] **Step 8: Commit**

```bash
git add src/api/labels.py src/api_client.py src/report/df_filter.py \
        src/report/report_generator.py tests/test_object_filter_df_expand.py tests/test_df_filter.py
git commit -m "feat(report): expand ip_list/workload object filters to CIDRs for cache df path"
```

---

### Task 7: 全量回歸 + capability 一致性檢查

**Files:**
- Test: 全部
- Modify（僅若回歸需要）: 本計畫已列檔案

**Interfaces:**
- Consumes: Task 1-6 全部產出。

- [ ] **Step 1: 全量測試**

Run: `python3 -m pytest tests/ -q`
Expected: 基準 2237 passed + 本計畫新增（約 25+）全 PASS、0 failed。任何 FAIL：先讀該測試守的行為，判斷是「測試守舊語意需更新」還是「實作破壞既有行為」——只有前者可以改既有測試，且 commit message 要說明語意變更依據（spec §2.2 實測）。

- [ ] **Step 2: capability matrix 文件一致性**

Run: `grep -c "execution" src/api/traffic_query.py`
確認新增 key 都有註冊；再跑 `python3 -m pytest tests/ -q -k "capabilit or matrix"`（若有既有 matrix 測試）確認同步。

- [ ] **Step 3: 以真實樣本驗證（可選但建議，測試機有 PCE）**

用 scratchpad 驗證腳本的同款查詢重跑一次確認同 key OR 修正生效：兩個同 key label 經 `_build_native_traffic_payload` 後 `sources.include` 應為兩個 group，實際查詢筆數應約等於個別聯集（參考基準：487+18=505）。

- [ ] **Step 4: Commit（若有調整）+ 回報**

```bash
git status --short   # 應乾淨或只剩本計畫檔案
```

回報內容：全量測試數字、語意變更摘要（同 key OR）、新 filter keys 清單（Phase 2/3 會用）。

---

## Self-Review 紀錄

- **Spec 覆蓋**：§4.2-1（capability 註冊）→ Task 4/5；§4.2-2（三路徑同 key OR）→ Task 1/2/3；§4.2-3（iplist href 解析、workload href 直傳）→ Task 4；§4.2-4（query_operator）既有支援，無需任務；df 路徑物件條件（§3 架構圖第三層）→ Task 6。
- **Placeholder 掃描**：無 TBD/TODO；所有程式碼步驟含完整程式碼。
- **型別一致性**：`group_label_specs_by_key`（Task 1 定義、Task 2 重用同檔函式）；`_resolve_iplist_filter_to_actor`/`_resolve_workload_filter_to_actor`（Task 4 定義、include/exclude specs 引用同名）；`expand_object_filters_for_df`（Task 6 labels.py 定義、api_client.py 委派、report_generator 呼叫同名）；`_*_object_cidrs` 五個 key 名在 Task 6 三個檔案間一致。
- **已知不確定點（已在任務內標註處置）**：`TrafficQuerySpec` 欄位名（Task 4 Step 1 註）、`_iplist_href_cache` 鍵大小寫（Task 4 Step 3 註）、`_flow_matches_filters` 是否 staticmethod（Task 2 Step 2 註）、`build_traffic_query_spec` 對未知 key 的處置（Task 6 Step 7 註）——實作者依註記現場確認，不盲寫。
