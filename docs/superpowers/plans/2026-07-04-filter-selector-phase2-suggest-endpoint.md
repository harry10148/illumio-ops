# Filter 物件選擇器 Phase 2：Suggest 端點 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `GET /api/filter-objects/suggest` 端點，供前端 filter 選擇器輸入時搜尋可用物件（Labels / Label Groups / IP Lists 走跨-request module 快取；Workloads 即時查 PCE），並關閉 Phase 1 遺留的 Phase 2 阻塞前置（`ex_any_` 物件排除在 cache/df 路徑無效）。

**Architecture:** 三層——(1) `src/gui/filter_object_cache.py` 純邏輯模組持有跨 request 的 module 層 `TTLCache`（首次全量抓 labels/ip_lists/label_groups、TTL 內子字串比對走快取，PCE 零負擔），提供 `search_cached_objects()`；(2) `src/gui/routes/filter_objects.py` 新藍圖組裝 cached 三類 + workload 即時查（name+hostname 合併去重）+ 離線降級 + 限流；(3) `src/gui/__init__.py` 註冊藍圖。ex_any_ 修復在 `df_filter.py`/`labels.py`。

**Tech Stack:** Python 3.10+、Flask 藍圖工廠、cachetools TTLCache、pytest（Flask test client + monkeypatch）、既有 `ApiClient`。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §4.1

## 設計定案（spec §4.1 執行層缺口的解法，2026-07-04 使用者核可）

- **cache 策略 = module 層 TTLCache（跨 request）**：spec §4.1 說「用 ApiClient 現有 TTLCache」，但 ApiClient 每 request 建新實例（短命），其 TTLCache 不跨 request。故 suggest 的 cached 三類改用 module 層 TTLCache（TTL 300s），首次全量抓、TTL 內複用，PCE 負擔低。這是對 spec「混合式」意圖的忠實落實，非偏離。
- **iplist summary 可做**：module cache 存 `get_ip_lists()` 完整物件（含 ip_ranges），故 iplist item 的 `summary`（ip_ranges 摘要）能提供，不留空。
- **label 跨維度**：抓全部 labels（不分 key），涵蓋自訂維度（如 `Net=`）。新增 `ApiClient.get_all_labels()`（仿 get_ip_lists）避免在 gui 層用私有 `_api_get`。

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動各 Task 列出的檔案；不順手重構。
- 新 UI 錯誤字串進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 兩檔（i18n 稽核測試會擋）。
- 端點測試沿用 `tests/test_gui_*.py` 樣式：Flask test client + `/api/login` + `tests._helpers._csrf` + `monkeypatch.setattr("src.api_client.ApiClient.<method>", ...)`。
- 藍圖工廠簽名 `make_X_blueprint(cm, csrf, limiter, login_required)`，註冊於 `src/gui/__init__.py`（reports/actions 之後同段）。
- 每 Task 結尾跑該 Task 測試 + commit；Task 4 全量 `python3 -m pytest tests/ -q`（基準以執行時 main 為準，約 2318 passed）。
- **worktree 紀律**：在隔離 worktree 執行；每個 Bash 命令以絕對 worktree 路徑 `cd` 前綴，commit 前 `git rev-parse --show-toplevel` 驗證、commit 後確認落點。

---

### Task 1: 關閉 Phase 2 阻塞前置 — ex_any_ 物件排除在 cache/df 路徑

**Files:**
- Modify: `src/api/labels.py`（`expand_object_filters_for_df` 的 `obj_keys` dict）
- Modify: `src/report/df_filter.py`（`apply_df_traffic_filters` 消費新 key）
- Test: `tests/test_object_filter_df_expand.py`（追加）+ `tests/test_df_filter.py`（追加）

**Interfaces:**
- Produces: `expand_object_filters_for_df` 新增內部 key `_ex_any_object_cidrs`（收 `ex_any_iplist`/`ex_any_workload` 展開的 CIDR/IP）；`apply_df_traffic_filters` 消費它（either-side 命中即剔除）。

**背景**：Phase 1 final review（opus）確認：`ex_any_iplist`/`ex_any_workload` 在 live 路徑（`_flow_matches_filters`）有處理，但 cache/df 路徑無——`expand_object_filters_for_df` 的 `obj_keys` 只收 `any_iplist`/`any_workload` 到 `_any_object_cidrs`，漏了 ex_any_；`df_filter` 也無消費者。導致 cache 路徑 either-side 物件排除靜默丟棄（under-filter）。必須在 Phase 2 接 UI 前關閉。

- [ ] **Step 1: 寫失敗測試（expander，追加 tests/test_object_filter_df_expand.py）**

```python
    def test_ex_any_iplist_expands_to_ex_any_cidrs(self):
        out = self.client.expand_object_filters_for_df({"ex_any_iplist": "prod-subnets"})
        assert "10.10.0.0/16" in out["_ex_any_object_cidrs"]

    def test_ex_any_workload_expands_to_ex_any_cidrs(self):
        out = self.client.expand_object_filters_for_df(
            {"ex_any_workload": "/orgs/1/workloads/abc"})
        assert "10.1.2.3" in out["_ex_any_object_cidrs"]
```

Run: `python3 -m pytest tests/test_object_filter_df_expand.py -v -k ex_any`
Expected: FAIL（`_ex_any_object_cidrs` 不存在 → KeyError）。

- [ ] **Step 2: 實作 expander（src/api/labels.py）**

`expand_object_filters_for_df` 的 `obj_keys` dict 加一列：

```python
            "_ex_any_object_cidrs": ("ex_any_iplist", "ex_any_workload"),
```

（放在既有 `"_any_object_cidrs": ("any_iplist", "any_workload"),` 之後。其餘展開迴圈邏輯不變——迴圈已按 obj_keys 通用處理。）

Run: `python3 -m pytest tests/test_object_filter_df_expand.py -v -k ex_any`
Expected: PASS。

- [ ] **Step 3: 寫失敗測試（df_filter 消費，追加 tests/test_df_filter.py）**

```python
def test_ex_any_object_cidrs_excludes_either_side():
    df = _df_two_apps()  # src_ip 10.0.0.1/2/3, dst_ip 10.0.0.9
    out = apply_df_traffic_filters(df, {"_ex_any_object_cidrs": ["10.0.0.1"]})
    # src 命中 10.0.0.1 的列被剔除
    assert "10.0.0.1" not in out["src_ip"].tolist()
    # dst 側命中也剔除
    out2 = apply_df_traffic_filters(df, {"_ex_any_object_cidrs": ["10.0.0.9"]})
    assert out2.empty  # 全部列 dst 都是 10.0.0.9
```

Run: `python3 -m pytest tests/test_df_filter.py -v -k ex_any_object`
Expected: FAIL（key 被忽略 → 未剔除）。

- [ ] **Step 4: 實作 df_filter 消費（src/report/df_filter.py）**

在 `apply_df_traffic_filters` 內、既有 `_any_object_cidrs` 處理之後加入：

```python
    ex_any_cidrs = filters.get("_ex_any_object_cidrs")
    if ex_any_cidrs and "src_ip" in df.columns and "dst_ip" in df.columns:
        # either-side 排除：來源或目的命中任一 CIDR 即剔除（對稱於 _any_object_cidrs 的包含）
        mask &= ~(_cidrs_mask("src_ip", ex_any_cidrs) | _cidrs_mask("dst_ip", ex_any_cidrs))
```

（`_cidrs_mask` 是 Phase 1 既有的區域 helper；若命名不同以現場為準。）

Run: `python3 -m pytest tests/test_df_filter.py -v -k ex_any_object`
Expected: PASS。

- [ ] **Step 5: 跑相關測試 + Commit**

Run: `python3 -m pytest tests/test_df_filter.py tests/test_object_filter_df_expand.py -q`
Expected: 全 PASS。

```bash
git add src/api/labels.py src/report/df_filter.py \
        tests/test_df_filter.py tests/test_object_filter_df_expand.py
git commit -m "fix(df_filter): expand and consume ex_any object exclusion in cache path"
```

---

### Task 2: filter_object_cache — module 層快取 + cached 三類搜尋

**Files:**
- Create: `src/gui/filter_object_cache.py`
- Modify: `src/api_client.py`（新增 `get_all_labels()`）
- Test: `tests/test_filter_object_cache.py`（新檔）+ `tests/test_api_client_get_all_labels.py`（新檔）

**Interfaces:**
- Produces: `ApiClient.get_all_labels() -> list[dict]`（全部 labels，不分 key；每筆含 key/value/href）。
- Produces: `src/gui/filter_object_cache.py`：
  - `search_cached_objects(api, q: str, types: list[str], limit: int) -> dict`——回 `{type: {"items": [...], "truncated": bool}}`（label/label_group/iplist）。type 不在 cached 三類者忽略（workload 由端點另處理）。
  - `invalidate_object_cache() -> None`（測試用，清 module cache）。

- [ ] **Step 1: get_all_labels 失敗測試（tests/test_api_client_get_all_labels.py）**

```python
import os, tempfile, unittest
from unittest.mock import MagicMock
from src.api_client import ApiClient


class TestGetAllLabels(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def test_get_all_labels_fetches_unscoped(self):
        captured = {}
        def fake_get(ep, timeout=15):
            captured["ep"] = ep
            return 200, [{"key": "Net", "value": "Server-A", "href": "/orgs/1/labels/1"}]
        self.client._api_get = fake_get
        out = self.client.get_all_labels()
        assert "/labels?max_results=" in captured["ep"]
        assert "key=" not in captured["ep"]  # 不分 key
        assert out[0]["key"] == "Net"

    def test_get_all_labels_empty_on_error(self):
        self.client._api_get = lambda ep, timeout=15: (500, None)
        assert self.client.get_all_labels() == []
```

Run: `python3 -m pytest tests/test_api_client_get_all_labels.py -v`
Expected: FAIL（無 get_all_labels）。

- [ ] **Step 2: 實作 get_all_labels（src/api_client.py，get_labels 之後）**

```python
    def get_all_labels(self) -> list[dict[str, Any]]:
        """Get every label across all dimensions (unscoped by key).

        Unlike get_labels(key) which filters one dimension, this returns all
        labels including custom dimensions (e.g. Net=) for the filter-object
        suggest cache. Returns [] on error.
        """
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/labels?max_results=10000")
        if status == 200 and data:
            return data
        logger.warning(f"get_all_labels: status={status}, returned empty list")
        return []
```

Run: `python3 -m pytest tests/test_api_client_get_all_labels.py -v`
Expected: PASS。

- [ ] **Step 3: filter_object_cache 失敗測試（tests/test_filter_object_cache.py）**

```python
from unittest.mock import MagicMock
from src.gui.filter_object_cache import search_cached_objects, invalidate_object_cache


def _api():
    api = MagicMock()
    api.get_all_labels.return_value = [
        {"key": "Net", "value": "Server-172.16.15", "href": "/orgs/1/labels/1"},
        {"key": "Net", "value": "MGMT-192.168.10", "href": "/orgs/1/labels/2"},
        {"key": "env", "value": "Production", "href": "/orgs/1/labels/3"},
    ]
    api.get_ip_lists.return_value = [
        {"name": "Prod-Subnets", "href": "/orgs/1/sec_policy/active/ip_lists/7",
         "ip_ranges": [{"from_ip": "10.10.0.0/16"}, {"from_ip": "10.11.0.0/16"}]},
        {"name": "Corp-VPN", "href": "/orgs/1/sec_policy/active/ip_lists/8",
         "ip_ranges": [{"from_ip": "172.16.8.0/22"}]},
    ]
    api.get_label_groups.return_value = [
        {"name": "PG-Prod-Apps", "href": "/orgs/1/sec_policy/active/label_groups/5"},
    ]
    return api


def setup_function():
    invalidate_object_cache()


def test_label_substring_across_dimensions():
    r = search_cached_objects(_api(), "server", ["label"], 10)
    names = [i["name"] for i in r["label"]["items"]]
    assert "Net=Server-172.16.15" in names
    assert r["label"]["items"][0]["key"] == "Net"


def test_label_case_insensitive():
    r = search_cached_objects(_api(), "PROD", ["label"], 10)
    assert any(i["value"] == "Production" for i in r["label"]["items"])


def test_iplist_has_summary():
    r = search_cached_objects(_api(), "prod", ["iplist"], 10)
    item = r["iplist"]["items"][0]
    assert item["name"] == "Prod-Subnets"
    assert item["href"].endswith("/ip_lists/7")
    assert "10.10.0.0/16" in item["summary"]


def test_label_group_name_match():
    r = search_cached_objects(_api(), "prod-apps", ["label_group"], 10)
    assert r["label_group"]["items"][0]["name"] == "PG-Prod-Apps"


def test_truncated_flag():
    r = search_cached_objects(_api(), "net", ["label"], 1)
    # "net" 比對到兩個 Net= label，limit=1 → truncated
    assert len(r["label"]["items"]) == 1
    assert r["label"]["truncated"] is True


def test_cache_reused_no_second_fetch():
    api = _api()
    search_cached_objects(api, "a", ["label"], 10)
    search_cached_objects(api, "b", ["label"], 10)
    assert api.get_all_labels.call_count == 1  # TTL 內只抓一次


def test_types_filter_only_requested():
    r = search_cached_objects(_api(), "prod", ["iplist"], 10)
    assert "iplist" in r and "label" not in r
```

Run: `python3 -m pytest tests/test_filter_object_cache.py -v`
Expected: FAIL（模組不存在）。

- [ ] **Step 4: 實作 filter_object_cache（src/gui/filter_object_cache.py）**

```python
"""Filter 物件選擇器 suggest 端點的跨-request 快取層。

ApiClient 每 request 建新實例（短命），其 TTLCache 不跨 request，故
labels/ip_lists/label_groups 這類「變動少、每次輸入都要搜」的物件改用
module 層 TTLCache：首次全量抓、TTL 內子字串比對走快取，PCE 零負擔。
workload 因數量大、變動頻繁，由端點即時查，不進此快取。
"""
from __future__ import annotations

import threading
from typing import Any

from cachetools import TTLCache

_CACHE_TTL_SECONDS = 300
_lock = threading.RLock()
# key: "labels"/"ip_lists"/"label_groups" → 完整物件清單
_cache: TTLCache = TTLCache(maxsize=8, ttl=_CACHE_TTL_SECONDS)


def invalidate_object_cache() -> None:
    """清空 module 快取（測試用 / 手動失效）。"""
    with _lock:
        _cache.clear()


def _get_or_fill(api, key: str, fetch):
    """TTL 內回快取；過期或未填則呼叫 fetch 全量抓。抓失敗且無舊值回 []。"""
    with _lock:
        if key in _cache:
            return _cache[key]
    data = fetch(api) or []
    with _lock:
        if data:
            _cache[key] = data
            return data
        # 抓到空/失敗：若有殘留舊值（TTL 剛過）回舊值勝於無
        return _cache.get(key, [])


def _ip_list_summary(ipl: dict) -> str:
    """ip_ranges 組成顯示摘要，最多 3 段。"""
    parts = []
    for r in (ipl.get("ip_ranges") or [])[:3]:
        frm = r.get("from_ip", "")
        to = r.get("to_ip")
        parts.append(f"{frm}-{to}" if to else frm)
    more = len(ipl.get("ip_ranges") or []) > 3
    return ", ".join(p for p in parts if p) + (", …" if more else "")


def _match_labels(objs, q, limit):
    ql = q.lower()
    hits = []
    for l in objs:
        key, val = l.get("key", ""), l.get("value", "")
        name = f"{key}={val}"
        if ql in name.lower() or ql in val.lower() or ql in key.lower():
            hits.append({"name": name, "key": key, "value": val, "href": l.get("href")})
    return hits[:limit], len(hits) > limit


def _match_named(objs, q, limit, with_summary=False):
    ql = q.lower()
    hits = []
    for o in objs:
        name = o.get("name", "")
        if ql in name.lower():
            item = {"name": name, "href": o.get("href")}
            if with_summary:
                item["summary"] = _ip_list_summary(o)
            hits.append(item)
    return hits[:limit], len(hits) > limit


def search_cached_objects(api, q: str, types: list[str], limit: int) -> dict[str, Any]:
    """對 cached 三類（label/label_group/iplist）做子字串比對，回分類分組結果。

    只處理 types 中屬 cached 三類者；workload 由端點另行即時查。
    """
    out: dict[str, Any] = {}
    if "label" in types:
        objs = _get_or_fill(api, "labels", lambda a: a.get_all_labels())
        items, trunc = _match_labels(objs, q, limit)
        out["label"] = {"items": items, "truncated": trunc}
    if "iplist" in types:
        objs = _get_or_fill(api, "ip_lists", lambda a: a.get_ip_lists())
        items, trunc = _match_named(objs, q, limit, with_summary=True)
        out["iplist"] = {"items": items, "truncated": trunc}
    if "label_group" in types:
        objs = _get_or_fill(api, "label_groups", lambda a: a.get_label_groups())
        items, trunc = _match_named(objs, q, limit)
        out["label_group"] = {"items": items, "truncated": trunc}
    return out
```

Run: `python3 -m pytest tests/test_filter_object_cache.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/gui/filter_object_cache.py src/api_client.py \
        tests/test_filter_object_cache.py tests/test_api_client_get_all_labels.py
git commit -m "feat(gui): module-level object cache and cached-type search for filter suggest"
```

---

### Task 3: suggest 端點藍圖（cached 三類 + workload 即時 + 離線降級）

**Files:**
- Create: `src/gui/routes/filter_objects.py`
- Modify: `src/gui/__init__.py`（註冊藍圖）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（若端點回使用者可見錯誤字串）
- Test: `tests/test_gui_filter_suggest.py`（新檔）

**Interfaces:**
- Consumes: `search_cached_objects`（Task 2）、`ApiClient.search_workloads`（既有）。
- Produces: `GET /api/filter-objects/suggest?q=&types=label,label_group,iplist,workload&limit=10` → JSON `{"ok": true, "results": {type: {...}}}`。

- [ ] **Step 1: 寫失敗測試（tests/test_gui_filter_suggest.py）**

```python
from tests._helpers import _csrf


def _login(client):
    r = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    return _csrf(r)


def test_suggest_cached_and_workload(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels",
                        lambda self: [{"key": "env", "value": "Production", "href": "/orgs/1/labels/3"}])
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self: [])

    calls = []
    def fake_search(self, params):
        calls.append(params)
        if params.get("name") == "prod":
            return [{"name": "prod-web-01", "hostname": "prod-web-01",
                     "href": "/orgs/1/workloads/1",
                     "interfaces": [{"address": "10.1.2.3"}]}]
        return []
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads", fake_search)

    r = client.get('/api/filter-objects/suggest?q=prod&types=label,workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    body = r.json["results"]
    assert any(i["value"] == "Production" for i in body["label"]["items"])
    assert body["workload"]["items"][0]["name"] == "prod-web-01"
    # workload 同時查 name 與 hostname
    assert {"name": "prod", "max_results": 10} in [
        {k: v for k, v in c.items() if k in ("name", "max_results")} for c in calls]


def test_suggest_workload_offline_degrades(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels",
                        lambda self: [{"key": "env", "value": "Prod", "href": "/orgs/1/labels/3"}])
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self: [])
    def boom(self, params):
        raise RuntimeError("pce down")
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads", boom)

    r = client.get('/api/filter-objects/suggest?q=prod&types=label,workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    # cached label 照常，workload 降級
    assert r.json["results"]["label"]["items"]
    assert r.json["results"]["workload"]["error"] == "pce_unreachable"


def test_suggest_workload_dedup_name_hostname(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads",
                        lambda self, params: [{"name": "w1", "hostname": "w1",
                                               "href": "/orgs/1/workloads/1",
                                               "interfaces": [{"address": "10.0.0.1"}]}])
    r = client.get('/api/filter-objects/suggest?q=w&types=workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    # name 查與 hostname 查回同一 workload → 去重成 1 筆
    assert len(r.json["results"]["workload"]["items"]) == 1
```

Run: `python3 -m pytest tests/test_gui_filter_suggest.py -v`
Expected: FAIL（404，端點不存在）。

- [ ] **Step 2: 實作藍圖（src/gui/routes/filter_objects.py）**

```python
"""Filter 物件選擇器 suggest 端點藍圖。

GET /api/filter-objects/suggest：輸入時搜尋可用 PCE 物件供 filter pill 選取。
Labels/Label Groups/IP Lists 走跨-request module 快取（filter_object_cache）；
Workloads 即時查（name+hostname 合併去重）；PCE 離線時 workload 降級、快取類照常。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

_CACHED_TYPES = ("label", "label_group", "iplist")
_ALL_TYPES = _CACHED_TYPES + ("workload",)
_MAX_LIMIT = 25


def make_filter_objects_blueprint(cm, csrf, limiter, login_required):
    bp = Blueprint("filter_objects", __name__)

    @bp.route('/api/filter-objects/suggest', methods=['GET'])
    @login_required
    @limiter.limit("240 per hour")
    def api_filter_objects_suggest():
        q = (request.args.get('q') or '').strip()
        raw_types = (request.args.get('types') or ','.join(_ALL_TYPES)).split(',')
        types = [t.strip() for t in raw_types if t.strip() in _ALL_TYPES]
        try:
            limit = max(1, min(_MAX_LIMIT, int(request.args.get('limit', 10))))
        except (ValueError, TypeError):
            limit = 10
        if not q or not types:
            return jsonify({"ok": True, "results": {}})

        from src.api_client import ApiClient
        from src.gui.filter_object_cache import search_cached_objects
        cm.load()
        api = ApiClient(cm)

        results = {}
        cached_types = [t for t in types if t in _CACHED_TYPES]
        if cached_types:
            # 快取類：module cache 若已填則離線也可回；填充失敗回空清單、不整體失敗
            try:
                results.update(search_cached_objects(api, q, cached_types, limit))
            except Exception:
                for t in cached_types:
                    results[t] = {"items": [], "error": "pce_unreachable"}

        if "workload" in types:
            results["workload"] = _search_workloads(api, q, limit)

        return jsonify({"ok": True, "results": results})

    return bp


def _search_workloads(api, q: str, limit: int) -> dict:
    """即時查 workload：name 與 hostname 各查一次、合併去重（by href）。"""
    try:
        seen, items = set(), []
        for param in ("name", "hostname"):
            for w in (api.search_workloads({param: q, "max_results": limit}) or []):
                href = w.get("href")
                if href in seen:
                    continue
                seen.add(href)
                ip = ""
                for iface in (w.get("interfaces") or []):
                    a = iface.get("address", "")
                    if a and "." in a and ":" not in a:  # IPv4 優先顯示
                        ip = a
                        break
                items.append({"name": w.get("name") or w.get("hostname") or href,
                              "hostname": w.get("hostname", ""), "ip": ip, "href": href})
        return {"items": items[:limit], "truncated": len(items) > limit, "error": None}
    except Exception:
        return {"items": [], "truncated": False, "error": "pce_unreachable"}
```

- [ ] **Step 3: 註冊藍圖（src/gui/__init__.py，actions 註冊之後）**

在 `src/gui/__init__.py` 的 actions 藍圖註冊（約 485 行）之後加入：

```python
    from src.gui.routes.filter_objects import make_filter_objects_blueprint
    app.register_blueprint(make_filter_objects_blueprint(cm, csrf, limiter, login_required))
```

（`login_required` 的取得方式與同段其他藍圖一致；以現場變數為準。）

- [ ] **Step 4: 跑端點測試**

Run: `python3 -m pytest tests/test_gui_filter_suggest.py -v`
Expected: 全 PASS。若 `login_required` 裝飾器與端點的 401 行為衝突（既有 before_request security_check 已處理登入），且測試已登入，應正常；若重複保護導致問題，以現場登入中介層為準調整（可能不需 `@login_required`，因 before_request 已全域保護 /api/）。

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/filter_objects.py src/gui/__init__.py tests/test_gui_filter_suggest.py
git commit -m "feat(gui): filter-objects suggest endpoint with cached types and live workload"
```

---

### Task 4: 全量回歸 + i18n 稽核

- [ ] **Step 1: 全量測試**

Run: `python3 -m pytest tests/ -q`
Expected: 執行時 main 基準（約 2318 passed）+ 本計畫新增（約 18）全 PASS、0 failed。

- [ ] **Step 2: i18n 稽核**

Run: `python3 scripts/audit_i18n_usage.py`
Expected: 0 findings（本計畫錯誤碼 `pce_unreachable` 是 API 回應值非 i18n key，前端負責顯示對應文案——確認未引入裸中文或缺 key）。

- [ ] **Step 3: 回報**

回報：全量測試數字、新端點的請求/回應範例、快取 TTL 行為（同 TTL 內第二次查不打 PCE 的證據）、離線降級驗證。

---

## Self-Review 紀錄

- **Spec §4.1 覆蓋**：端點路徑/query params → Task 3；回傳分類分組結構（label 含 key/value、iplist 含 summary）→ Task 2；workload name+hostname 合併去重 → Task 3 `_search_workloads`；PCE 離線 workload 降級、快取類照常 → Task 3；label key 動態分組（跨維度）→ Task 2 `get_all_labels` + `_match_labels`。
- **Phase 2 阻塞前置**：ex_any_ cache/df 修復 → Task 1（opus final review 標記的 must-close）。
- **cache 短命缺口**：module 層 TTLCache（Task 2）解決，設計說明已記錄。
- **Placeholder 掃描**：無 TBD；所有程式碼步驟含完整程式碼。
- **型別一致性**：`search_cached_objects`（Task 2 定義、Task 3 消費）；`get_all_labels`（Task 2 定義、filter_object_cache 呼叫）；`_ex_any_object_cidrs`（Task 1 expander 產生、df_filter 消費一致）；回應結構 `{type: {items, truncated/error}}` Task 2/3 一致。
- **已知不確定點（任務內已標註）**：`_cidrs_mask` helper 命名（Task 1 Step 4）、`login_required` 取得與是否與 before_request 重複（Task 3 Step 4）、`search_workloads` 是否接受 `max_results` in params（以現場簽名為準）——實作者現場對位。
