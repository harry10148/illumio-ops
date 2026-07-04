# Policy Diff 物件層擴充（IP List / Service / Label Group）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 本計劃取代 backlog `2026-07-02-backlog-policy-diff-object-layers.md`，行號與介面已於 2026-07-04 依 main 現況 refresh。
> **與 backlog 的關鍵差異：** ApiClient 的 `get_ip_lists()`/`get_services()`/`get_label_groups()` 已存在且硬編 ACTIVE 端點（api_client.py:793/823/809），本計劃 Task 1 改為「參數化 pversion 以取得 DRAFT 版」，而非 backlog 原寫的「補 active 版」。

**Goal:** Policy Diff 報表（DRAFT vs ACTIVE）從 Ruleset/Rule 層擴充到 IP List、Service、Label Group 三種物件，維持「diff → attribution → risk 分級」純函式管線，HTML 報表新增三章。

**Architecture:** 新增純函式模組 `object_diff.py`（泛用 named-object 比對器 + 引用掃描器），三種物件共用；attribution 經由 `audit_mod03_policy.py` 新增的 `object_events` 輸出鍵取得物件層 audit 事件；risk 依「scope_expanded × 被 ACTIVE allow 規則引用」判 HIGH。API 取數與組裝留在 `policy_diff_report.py` facade。

**Tech Stack:** Python 3.12、pandas、pytest（mock：`unittest.mock.MagicMock` 與 `responses`）。

## Global Constraints

- Commit：英文 conventional commits，無 emoji。程式註解繁體中文（僅在說明程式本身無法表達的限制時才寫）。
- **禁 `git add -A` / `git add .`**：一律逐檔列名 add。
- i18n：`src/i18n_en.json` 與 `src/i18n_zh_TW.json` 同步新增，檔尾保持單一 newline。glossary 鐵律：物件型別名（IP List、Service、Label Group、Ruleset、DRAFT、ACTIVE）在 zh_TW 保持英文。
- 純函式優先：`src/report/analysis/policy_diff/` 內不做任何 I/O；API 取數只在 `policy_diff_report.py`。
- 新章節沿用既有 `_table` 版型（`report-table-wrap` 包裹、print-fit、無水平捲動溢出）——spec N 規範。
- 風險語義：造成「防護面擴大」的 modified（ip_ranges/fqdns/service_ports/labels/sub_groups 新增成員）且該物件被任一 ACTIVE enabled allow 規則引用 = HIGH；removed（provision 後會消失）= MEDIUM；其餘空字串。
- 既有 442+ policy-diff 相關測試與全套 pytest（基線 2465 passed）必須保持全綠；`grade_changes`/`attribute_changes` 的既有呼叫端（不帶新參數）行為不變。

## 現況事實（2026-07-04 refresh，main）

- `src/api_client.py`：`get_ip_lists` :793 / `get_label_groups` :809 / `get_services` :823 全部硬編 `/orgs/{org}/sec_policy/active/...?max_results=10000`，回傳 `list[dict]`，失敗回 `[]` 並 `logger.warning`。`_api_get` :735 回 `(status, json|None)`。無快取。
- `src/report/analysis/policy_diff/diff_engine.py`：`diff_rulesets(draft, active, names=None) -> {"ruleset_changes": df, "rule_changes": df, "summary": dict}`；`_id_from_href` :23 = href 尾段；added/removed 列 `field="*"`；`_blank()` 帶空 attribution 欄。
- `src/report/analysis/policy_diff/attribution.py`：`attribute_changes(diff, policy_events)`；`_latest_by_name` :17-39 讀 `policy_events["draft_events"]`（DataFrame，欄 `resource_name/actor/timestamp/event_type`），`_apply` :42-52 以 `row["ruleset_name"]` 配對。
- `src/report/analysis/policy_diff/risk.py`：`grade_changes(diff)`；`_grade_row` :19-31 只看 enabled 翻轉與 removed。
- `src/report/analysis/audit/audit_mod03_policy.py`：`_POLICY_EVENTS` :7-42（已含 ip_list/service/label_group 單數形 create/update/delete，**缺** `ip_lists.delete`/`services.delete` 複數形）；`_DRAFT_RULE_EVENTS` :45-53 只含 rule_set/sec_rule 事件；`draft_events` 於 :106-112 建構（head(50)，欄含 `resource_name`）。事件型別權威：`src/events/catalog.py`（`ip_lists.delete` :81、`services.delete` :205；**無** `ip_lists.update`/`services.update` 複數形）。
- `src/report/policy_diff_report.py`：`build()` :75-82 = draft(`get_all_rulesets(force_refresh=True)`) + active(`get_active_rulesets()`) → `diff_rulesets` → `attribute_changes(diff, self._fetch_policy_events(lang))` → `grade_changes(diff)`；`_build_name_map()` :52-73 呼叫三個 getter 建 href→name 並複製 `/active/`→`/draft/` key。
- `src/report/exporters/policy_diff_html_exporter.py`：`_table(df, id_col)` :69-96 欄序 `["risk","change_type","ruleset_name",id_col,"field","draft_value","active_value","last_actor","last_changed"]`（僅保留存在欄）；`_COL_I18N` :50-61；空 df 出 `rpt_policy_diff_no_changes` note；risk 排序 `_RISK_RANK` :67。
- 入口三處：CLI `report policy-diff`（report.py:773）、GUI `POST /api/policy_diff_report/generate`（reports.py:478）、scheduler `report_type=="policy_diff"`（report_scheduler.py:372，`record_count=summary["total_changes"]`）。三處皆吃 `build()` 回傳 dict，無需改動（total_changes 語義自然擴大）。
- allow/deny：allow 規則在 `rs["rules"]`，deny 在獨立 `rs["deny_rules"]`；rule/ruleset `enabled` 預設 True，disabled 不強制執行（policy_resolver.py:158,174 慣例）。
- PCE 物件形狀：ip_list `{href, name, ip_ranges:[{from_ip, to_ip?, exclusion?}], fqdns:[{fqdn}], description}`；service `{href, name, service_ports:[{port?, to_port?, proto}], windows_services:[{service_name?/process_name?/port?/proto?}], description}`；label_group `{href, name, labels:[{href}], sub_groups:[{href}], description}`。

## File Structure

- Modify `src/api_client.py` — 三個 getter 加 `pversion` 參數（T1）。
- Create `src/report/analysis/policy_diff/object_diff.py` — `diff_objects` / `object_change_counts` / `scan_object_refs` 純函式（T2、T4）。
- Modify `src/report/analysis/audit/audit_mod03_policy.py` — `_DRAFT_OBJECT_EVENTS` + `object_events` 輸出鍵（T3）。
- Modify `src/report/analysis/policy_diff/attribution.py` — `_latest_by_name` 改吃 df、`_apply` 參數化 name 欄、物件表歸屬（T3）。
- Modify `src/report/analysis/policy_diff/risk.py` — `grade_changes(diff, *, object_refs=None)` + 物件列分級（T4）。
- Modify `src/report/policy_diff_report.py` — 取數、diff_objects×3、summary 併入、refs 掃描（T5）。
- Modify `src/report/exporters/policy_diff_html_exporter.py` — `_table` 泛化 + 三新章（T5）。
- Modify `src/i18n_en.json` / `src/i18n_zh_TW.json` — 章節標題與欄位 key（T5）。
- Tests: `tests/test_api_policy_object_pversion.py`（新）、`tests/test_policy_diff_object_diff.py`（新）、既有 attribution/risk/report/exporter 測試檔擴充。

---

### Task 1: ApiClient 物件 getter 參數化 pversion

**Files:**
- Modify: `src/api_client.py:793-835`（`get_ip_lists` / `get_label_groups` / `get_services`）
- Test: `tests/test_api_policy_object_pversion.py`（新檔）

**Interfaces:**
- Produces: `get_ip_lists(pversion="active")`、`get_label_groups(pversion="active")`、`get_services(pversion="active")` —— `pversion` 僅接受 `"active"`/`"draft"`，其他值 `ValueError`。預設 `"active"` 保持所有既有呼叫端行為與端點完全不變。回傳形狀不變（`list[dict]`，失敗 `[]`）。

- [ ] **Step 1: 寫失敗測試**

新檔 `tests/test_api_policy_object_pversion.py`（mock 模式沿用 `tests/test_api_client_request_contract.py` 的 `responses` 慣例；若該檔實際用 `_api_get` monkeypatch 更輕，以現場為準，斷言不變）：

```python
"""pversion 參數化：物件 getter 可切換 draft/active 端點。"""

import pytest
from unittest.mock import MagicMock

from src.api_client import ApiClient


@pytest.fixture
def api():
    client = ApiClient.__new__(ApiClient)
    client.api_cfg = {"url": "https://pce.example.com:8443", "org_id": 1}
    client._api_get = MagicMock(return_value=(200, [{"href": "/orgs/1/sec_policy/draft/ip_lists/5", "name": "L"}]))
    return client


@pytest.mark.parametrize("method,segment", [
    ("get_ip_lists", "ip_lists"),
    ("get_services", "services"),
    ("get_label_groups", "label_groups"),
])
def test_default_pversion_hits_active(api, method, segment):
    getattr(api, method)()
    endpoint = api._api_get.call_args[0][0]
    assert f"/sec_policy/active/{segment}" in endpoint
    assert "max_results=10000" in endpoint


@pytest.mark.parametrize("method,segment", [
    ("get_ip_lists", "ip_lists"),
    ("get_services", "services"),
    ("get_label_groups", "label_groups"),
])
def test_draft_pversion_hits_draft(api, method, segment):
    result = getattr(api, method)(pversion="draft")
    endpoint = api._api_get.call_args[0][0]
    assert f"/sec_policy/draft/{segment}" in endpoint
    assert isinstance(result, list)


@pytest.mark.parametrize("method", ["get_ip_lists", "get_services", "get_label_groups"])
def test_invalid_pversion_raises(api, method):
    with pytest.raises(ValueError):
        getattr(api, method)(pversion="prod")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_api_policy_object_pversion.py -v`
Expected: FAIL（`TypeError: ... unexpected keyword argument 'pversion'`）

- [ ] **Step 3: 最小實作**

三個 getter 同款改法（以 `get_ip_lists` 為例；docstring 保留原 ACTIVE 對齊說明並補一句 pversion）：

```python
    def get_ip_lists(self, pversion: str = "active") -> list[dict[str, Any]]:
        """Get all IP Lists with their ip_ranges/fqdns.

        Default ACTIVE so returned hrefs (/sec_policy/active/ip_lists/...)
        match actor references inside active rulesets; pass pversion="draft"
        for the draft-side inventory (policy diff).
        """
        if pversion not in ("active", "draft"):
            raise ValueError(f"pversion must be 'active' or 'draft', got {pversion!r}")
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/{pversion}/ip_lists?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_ip_lists: status={status}, returned empty list")
        return []
```

`get_label_groups` / `get_services` 比照（各自的 segment 與 warning 訊息）。

- [ ] **Step 4: 跑測試確認通過 + 既有合約測試不破**

Run: `python3 -m pytest tests/test_api_policy_object_pversion.py tests/test_api_client_request_contract.py tests/test_policy_diff_report.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api_client.py tests/test_api_policy_object_pversion.py
git commit -m "feat(api): pversion parameter for policy object fetchers"
```

---

### Task 2: 泛用 named-object diff（object_diff.py）

**Files:**
- Create: `src/report/analysis/policy_diff/object_diff.py`
- Test: `tests/test_policy_diff_object_diff.py`（新檔）

**Interfaces:**
- Produces:
  - `diff_objects(draft: list[dict], active: list[dict], *, kind: str, fields: list[str], names: dict[str, str] | None = None) -> pd.DataFrame`
    欄位 `_OBJECT_COLS = ["change_type", "object_kind", "name", "object_id", "field", "draft_value", "active_value", "scope_expanded", "last_actor", "last_changed", "last_event"]`。
    對齊 key = href 尾段 id（同 diff_engine `_id_from_href` 慣例，PCE 物件 draft/active 同 id）。
    added 列 `field="*"`、`draft_value=name`；removed 列 `field="*"`、`active_value=name`；modified 每個差異欄一列。
    `scope_expanded`（bool）：field 屬 `_EXPANSION_FIELDS = {"ip_ranges", "fqdns", "service_ports", "labels", "sub_groups"}` 且 draft token set 含有 active 沒有的成員（新增覆蓋面即算，不要求嚴格超集）。added/removed/description 列一律 False。
    attribution 三欄以空字串初始化（同 diff_engine `_blank()` 慣例）。
    排序：`["change_type", "name", "field"]`，`ignore_index=True`。空輸入回帶欄位的空 DataFrame。
  - `object_change_counts(df: pd.DataFrame) -> tuple[int, int, int]` —— (added, removed, modified)；modified 以 `object_id` nunique 計（對齊 diff_engine summary「物件數」語義）。
- 值摘要（穩定、排序後 `", ".join`，順序不同不算 diff）：
  - ip_range：`from_ip`（有 `to_ip` 接 `-to_ip`；`exclusion` 前綴 `!`）
  - fqdn：`fqdn` 值
  - service_port：`{proto}/{port}`（有 `to_port` 接 `-to_port`；無 `port` 顯示 `proto:{proto}`）
  - windows_service：`service_name` 或 `process_name`，皆無則 `str(sorted(it.items()))`
  - label / sub_group 成員：href 先 `/active/`→`/draft/` 正規化再 `names.get(href, href)`（沿用 `_build_name_map` 慣例：names 的 key 已含兩版）
  - description：原字串 strip

- [ ] **Step 1: 寫失敗測試**

`tests/test_policy_diff_object_diff.py` 核心 case（實作者可增不可減）：

```python
"""object_diff：三種 policy 物件的 added/removed/modified 純函式比對。"""

import pandas as pd

from src.report.analysis.policy_diff.object_diff import (
    diff_objects,
    object_change_counts,
)


def _ipl(oid, name, ranges=None, fqdns=None, desc="", side="draft"):
    return {
        "href": f"/orgs/1/sec_policy/{side}/ip_lists/{oid}",
        "name": name,
        "ip_ranges": ranges or [],
        "fqdns": fqdns or [],
        "description": desc,
    }


def test_added_object_single_star_row():
    df = diff_objects([_ipl(1, "New-L")], [], kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert len(df) == 1
    row = df.iloc[0]
    assert row["change_type"] == "added"
    assert row["object_kind"] == "ip_list"
    assert row["field"] == "*"
    assert row["draft_value"] == "New-L"
    assert row["object_id"] == "1"
    assert bool(row["scope_expanded"]) is False


def test_removed_object_single_star_row():
    df = diff_objects([], [_ipl(2, "Old-L", side="active")], kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert df.iloc[0]["change_type"] == "removed"
    assert df.iloc[0]["active_value"] == "Old-L"


def test_modified_ip_ranges_expansion_flagged():
    draft = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}, {"from_ip": "192.168.1.0/24"}])]
    active = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}], side="active")]
    df = diff_objects(draft, active, kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert len(df) == 1
    row = df.iloc[0]
    assert row["change_type"] == "modified"
    assert row["field"] == "ip_ranges"
    assert "192.168.1.0/24" in row["draft_value"]
    assert bool(row["scope_expanded"]) is True


def test_modified_shrink_not_expansion():
    draft = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}])]
    active = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}, {"from_ip": "172.16.0.0/12"}], side="active")]
    df = diff_objects(draft, active, kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert bool(df.iloc[0]["scope_expanded"]) is False


def test_same_content_different_order_no_diff():
    a = [{"from_ip": "10.0.0.0/8"}, {"from_ip": "172.16.0.0/12"}]
    b = [{"from_ip": "172.16.0.0/12"}, {"from_ip": "10.0.0.0/8"}]
    df = diff_objects([_ipl(4, "L", ranges=a)], [_ipl(4, "L", ranges=b, side="active")],
                      kind="ip_list", fields=["ip_ranges", "fqdns", "description"])
    assert df.empty


def test_description_change_not_scope_expanded():
    df = diff_objects([_ipl(5, "L", desc="new")], [_ipl(5, "L", desc="old", side="active")],
                      kind="ip_list", fields=["ip_ranges", "fqdns", "description"])
    assert df.iloc[0]["field"] == "description"
    assert bool(df.iloc[0]["scope_expanded"]) is False


def _svc(oid, name, ports=None, side="draft"):
    return {
        "href": f"/orgs/1/sec_policy/{side}/services/{oid}",
        "name": name,
        "service_ports": ports or [],
        "windows_services": [],
        "description": "",
    }


def test_service_port_summary_and_expansion():
    draft = [_svc(7, "S", ports=[{"port": 443, "proto": 6}, {"port": 1024, "to_port": 2048, "proto": 6}])]
    active = [_svc(7, "S", ports=[{"port": 443, "proto": 6}], side="active")]
    df = diff_objects(draft, active, kind="service",
                      fields=["service_ports", "windows_services", "description"])
    row = df.iloc[0]
    assert row["field"] == "service_ports"
    assert "6/1024-2048" in row["draft_value"]
    assert bool(row["scope_expanded"]) is True


def _lg(oid, name, labels=None, side="draft"):
    return {
        "href": f"/orgs/1/sec_policy/{side}/label_groups/{oid}",
        "name": name,
        "labels": labels or [],
        "sub_groups": [],
        "description": "",
    }


def test_label_group_members_use_names_map():
    names = {"/orgs/1/labels/9": "role-web"}
    draft = [_lg(8, "G", labels=[{"href": "/orgs/1/labels/9"}])]
    active = [_lg(8, "G", side="active")]
    df = diff_objects(draft, active, kind="label_group",
                      fields=["labels", "sub_groups", "description"],
                      names=names)
    assert "role-web" in df.iloc[0]["draft_value"]
    assert bool(df.iloc[0]["scope_expanded"]) is True


def test_empty_inputs_empty_frame_with_columns():
    df = diff_objects([], [], kind="service",
                      fields=["service_ports", "windows_services", "description"])
    assert df.empty
    assert "object_kind" in df.columns and "scope_expanded" in df.columns


def test_object_change_counts():
    draft = [_ipl(1, "A"), _ipl(3, "C", ranges=[{"from_ip": "10.0.0.0/8"}], fqdns=[{"fqdn": "x.example.com"}])]
    active = [_ipl(2, "B", side="active"), _ipl(3, "C", side="active")]
    df = diff_objects(draft, active, kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    added, removed, modified = object_change_counts(df)
    assert (added, removed, modified) == (1, 1, 1)  # C 改兩欄仍算 1 個 modified 物件
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_policy_diff_object_diff.py -v`
Expected: FAIL（`ModuleNotFoundError: ... object_diff`）

- [ ] **Step 3: 實作 `object_diff.py`**

```python
"""泛用 named-object diff：IP List / Service / Label Group 三種物件共用。

DRAFT relative to ACTIVE，語義與 diff_engine 一致：
added = 只在 draft、removed = 只在 active、modified = 白名單欄位值不同。
純函式，無 I/O。
"""

from __future__ import annotations

import pandas as pd

_OBJECT_COLS = [
    "change_type", "object_kind", "name", "object_id", "field",
    "draft_value", "active_value", "scope_expanded",
    "last_actor", "last_changed", "last_event",
]

# 值為成員清單、且新增成員等於擴大防護面的欄位
_EXPANSION_FIELDS = {"ip_ranges", "fqdns", "service_ports", "labels", "sub_groups"}


def _id_from_href(href: str) -> str:
    return str(href or "").rstrip("/").split("/")[-1]


def _fmt_ip_range(it: dict) -> str:
    base = str(it.get("from_ip", ""))
    if it.get("to_ip"):
        base += f"-{it['to_ip']}"
    if it.get("exclusion"):
        base = "!" + base
    return base


def _fmt_service_port(it: dict) -> str:
    proto = str(it.get("proto", ""))
    port = it.get("port")
    if port is None:
        return f"proto:{proto}"
    s = f"{proto}/{port}"
    if it.get("to_port") is not None:
        s += f"-{it['to_port']}"
    return s


def _fmt_windows_service(it: dict) -> str:
    return str(it.get("service_name") or it.get("process_name") or sorted(it.items()))


def _member_tokens(field: str, value, names: dict[str, str]) -> list[str]:
    """把清單欄位轉成穩定 token 清單（順序無關）。"""
    items = value if isinstance(value, list) else []
    tokens = []
    for it in items:
        if not isinstance(it, dict):
            tokens.append(str(it))
        elif field == "ip_ranges":
            tokens.append(_fmt_ip_range(it))
        elif field == "fqdns":
            tokens.append(str(it.get("fqdn", "")))
        elif field == "service_ports":
            tokens.append(_fmt_service_port(it))
        elif field == "windows_services":
            tokens.append(_fmt_windows_service(it))
        elif field in ("labels", "sub_groups"):
            href = str(it.get("href", "")).replace("/active/", "/draft/")
            tokens.append(names.get(href, names.get(str(it.get("href", "")), str(it.get("href", "")))))
        else:
            tokens.append(str(sorted(it.items())))
    return tokens


def _field_view(field: str, obj: dict, names: dict[str, str]) -> tuple[str, frozenset]:
    """回傳 (顯示摘要, 比對用 token set)。純量欄位 token set 為單元素。"""
    value = obj.get(field)
    if field in _EXPANSION_FIELDS or field == "windows_services":
        tokens = _member_tokens(field, value, names)
        return ", ".join(sorted(tokens)), frozenset(tokens)
    text = str(value or "").strip()
    return text, frozenset([text])


def _blank() -> dict:
    return {"last_actor": "", "last_changed": "", "last_event": ""}


def _index(objs: list[dict]) -> dict[str, dict]:
    out = {}
    for o in objs or []:
        if isinstance(o, dict) and o.get("href"):
            out[_id_from_href(o["href"])] = o
    return out


def diff_objects(draft: list[dict], active: list[dict], *, kind: str,
                 fields: list[str], names: dict[str, str] | None = None) -> pd.DataFrame:
    names = names or {}
    d_idx, a_idx = _index(draft), _index(active)
    rows: list[dict] = []

    for oid, obj in d_idx.items():
        if oid not in a_idx:
            rows.append({"change_type": "added", "object_kind": kind,
                         "name": str(obj.get("name", "")), "object_id": oid,
                         "field": "*", "draft_value": str(obj.get("name", "")),
                         "active_value": "", "scope_expanded": False, **_blank()})
    for oid, obj in a_idx.items():
        if oid not in d_idx:
            rows.append({"change_type": "removed", "object_kind": kind,
                         "name": str(obj.get("name", "")), "object_id": oid,
                         "field": "*", "draft_value": "",
                         "active_value": str(obj.get("name", "")),
                         "scope_expanded": False, **_blank()})
    for oid in d_idx.keys() & a_idx.keys():
        d_obj, a_obj = d_idx[oid], a_idx[oid]
        for field in fields:
            d_text, d_set = _field_view(field, d_obj, names)
            a_text, a_set = _field_view(field, a_obj, names)
            if d_text == a_text:
                continue
            expanded = field in _EXPANSION_FIELDS and bool(d_set - a_set)
            rows.append({"change_type": "modified", "object_kind": kind,
                         "name": str(d_obj.get("name", "")), "object_id": oid,
                         "field": field, "draft_value": d_text,
                         "active_value": a_text, "scope_expanded": expanded,
                         **_blank()})

    df = pd.DataFrame(rows, columns=_OBJECT_COLS)
    if not df.empty:
        df = df.sort_values(["change_type", "name", "field"], ignore_index=True)
    return df


def object_change_counts(df: pd.DataFrame) -> tuple[int, int, int]:
    """(added, removed, modified)；modified 以物件數計，非變動列數。"""
    if df is None or df.empty:
        return 0, 0, 0
    added = int((df["change_type"] == "added").sum())
    removed = int((df["change_type"] == "removed").sum())
    modified = int(df.loc[df["change_type"] == "modified", "object_id"].nunique())
    return added, removed, modified
```

（`scan_object_refs` 屬 Task 4，本 task 不寫。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_policy_diff_object_diff.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/policy_diff/object_diff.py tests/test_policy_diff_object_diff.py
git commit -m "feat(policy-diff): generic named-object diff engine"
```

---

### Task 3: audit object_events 輸出 + attribution 物件層歸屬

**Files:**
- Modify: `src/report/analysis/audit/audit_mod03_policy.py`（`_POLICY_EVENTS` 補複數形、新增 `_DRAFT_OBJECT_EVENTS` 與 `object_events` 輸出鍵）
- Modify: `src/report/analysis/policy_diff/attribution.py`（`_latest_by_name` 改吃 DataFrame、`_apply` 參數化 name 欄、物件表歸屬）
- Test: `tests/test_policy_diff_attribution.py` 擴充、`tests/test_audit_mod03_object_events.py`（**新檔**——`audit_policy_changes` 目前無直接單元測試，2026-07-04 已確認）

**Interfaces:**
- Consumes: Task 2 的物件表欄位 `name`。
- Produces:
  - `audit_policy_changes(df)` 輸出 dict 新增 `"object_events": DataFrame`（欄含 `timestamp/event_type/resource_name/...`，同 `draft_events` 選欄邏輯，head(50)；empty 分支也補 `"object_events": pd.DataFrame()`）。
  - `attribute_changes(diff, policy_events)`：簽名不變。ruleset/rule 表用 `draft_events` 配 `ruleset_name`（行為不變）；`ip_list_changes`/`service_changes`/`label_group_changes` 表（若存在於 diff）用 `object_events` 配 `name`。防禦行為不變（garbage/None/empty 不 raise）。
- **不動 `_DRAFT_RULE_EVENTS`**：audit 報表的 `rule_change_count` KPI 與 `draft_events` 表語義維持原樣。

- [ ] **Step 1: 寫失敗測試**

`tests/test_policy_diff_attribution.py` 追加：

```python
def test_object_changes_attributed_from_object_events():
    diff = {
        "ruleset_changes": pd.DataFrame(),
        "rule_changes": pd.DataFrame(),
        "ip_list_changes": pd.DataFrame([
            {"change_type": "modified", "object_kind": "ip_list", "name": "Corp-Nets",
             "object_id": "5", "field": "ip_ranges", "draft_value": "x", "active_value": "y",
             "scope_expanded": True, "last_actor": "", "last_changed": "", "last_event": ""},
        ]),
    }
    events = {
        "draft_events": pd.DataFrame(),
        "object_events": pd.DataFrame([
            {"resource_name": "Corp-Nets", "actor": "alice@corp",
             "timestamp": "2026-07-03T10:00:00Z", "event_type": "ip_list.update"},
        ]),
    }
    out = attribute_changes(diff, events)
    row = out["ip_list_changes"].iloc[0]
    assert row["last_actor"] == "alice@corp"
    assert row["last_event"] == "ip_list.update"


def test_object_changes_survive_missing_object_events_key():
    diff = {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
            "ip_list_changes": pd.DataFrame([
                {"change_type": "removed", "object_kind": "ip_list", "name": "L",
                 "object_id": "1", "field": "*", "draft_value": "", "active_value": "L",
                 "scope_expanded": False, "last_actor": "", "last_changed": "", "last_event": ""}])}
    out = attribute_changes(diff, {"draft_events": pd.DataFrame()})
    assert out["ip_list_changes"].iloc[0]["last_actor"] == ""
```

新檔 `tests/test_audit_mod03_object_events.py`（完整內容）：

```python
"""audit_policy_changes 的 object_events 輸出鍵。"""

import pandas as pd

from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes


def _events_df(rows):
    return pd.DataFrame(
        [{"timestamp": ts, "event_type": et, "resource_name": name,
          "severity": "info", "actor": "alice@corp"} for ts, et, name in rows]
    )


def test_object_events_key_present_and_filtered():
    df = _events_df([
        ("2026-07-01T00:00:00Z", "ip_list.update", "Corp-Nets"),
        ("2026-07-01T01:00:00Z", "service.create", "HTTPS-8443"),
        ("2026-07-01T02:00:00Z", "label_group.delete", "G1"),
        ("2026-07-01T03:00:00Z", "ip_lists.delete", "Bulk"),
        ("2026-07-01T04:00:00Z", "rule_set.update", "RS-A"),
    ])
    result = audit_policy_changes(df)
    obj = result["object_events"]
    assert set(obj["event_type"]) == {"ip_list.update", "service.create",
                                      "label_group.delete", "ip_lists.delete"}
    # draft_events 語義不變：只含 rule 事件
    assert set(result["draft_events"]["event_type"]) == {"rule_set.update"}


def test_object_events_empty_frame_on_no_policy_events():
    result = audit_policy_changes(pd.DataFrame({"event_type": ["login.success"], "timestamp": ["t"]}))
    assert result["object_events"].empty
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_policy_diff_attribution.py tests/test_audit_mod03_object_events.py -v`
Expected: 新測試 FAIL（KeyError `object_events` / attribution 空欄）

- [ ] **Step 3: 實作**

`audit_mod03_policy.py`：

```python
# _POLICY_EVENTS 清單內補（放在對應單數形旁）：
    "ip_lists.delete",
    "services.delete",

# _DRAFT_RULE_EVENTS 之後新增：
_DRAFT_OBJECT_EVENTS = {
    "ip_list.create", "ip_list.update", "ip_list.delete", "ip_lists.delete",
    "service.create", "service.update", "service.delete", "services.delete",
    "label_group.create", "label_group.update", "label_group.delete",
}
```

`audit_policy_changes` 內、draft_events 區塊之後比照建構：

```python
    obj_mask = target_df["event_type"].isin(_DRAFT_OBJECT_EVENTS)
    object_events = pd.DataFrame()
    if obj_mask.any():
        obj_df = target_df[obj_mask]
        cols = _select_cols(obj_df, ["timestamp", "event_type", "severity"],
                            extra_cols=("resource_name", "action", "src_ip", "change_detail"))
        object_events = obj_df[cols].sort_values("timestamp", ascending=False).head(50)
```

回傳 dict（含 :87-101 的 empty 分支）補 `"object_events": object_events`（empty 分支 `pd.DataFrame()`）。

`attribution.py` 重構（保持既有防禦語義）：

```python
_OBJECT_TABLES = ("ip_list_changes", "service_changes", "label_group_changes")


def _latest_by_name(events) -> dict:
    """events 為 DataFrame（draft_events 或 object_events）；防禦同前。"""
    if not isinstance(events, pd.DataFrame) or events.empty:
        return {}
    if "resource_name" not in events.columns:
        return {}
    df = events.copy()
    if "timestamp" not in df.columns:
        df["timestamp"] = ""
    df = df.sort_values("timestamp", ascending=True)
    latest = {}
    for _, row in df.iterrows():
        name = str(row.get("resource_name", "")).strip()
        if name:
            latest[name] = {
                "actor": str(row.get("actor", "")),
                "timestamp": str(row.get("timestamp", "")),
                "event_type": str(row.get("event_type", "")),
            }
    return latest


def _apply(df, latest: dict, name_col: str) -> None:
    if not isinstance(df, pd.DataFrame) or df.empty or name_col not in df.columns:
        return
    for idx, row in df.iterrows():
        hit = latest.get(str(row.get(name_col, "")).strip())
        if hit:
            df.at[idx, "last_actor"] = hit["actor"]
            df.at[idx, "last_changed"] = hit["timestamp"]
            df.at[idx, "last_event"] = hit["event_type"]


def attribute_changes(diff: dict, policy_events: dict) -> dict:
    events = policy_events if isinstance(policy_events, dict) else {}
    latest_rules = _latest_by_name(events.get("draft_events"))
    if latest_rules:
        for key in ("ruleset_changes", "rule_changes"):
            _apply(diff.get(key), latest_rules, "ruleset_name")
    latest_objects = _latest_by_name(events.get("object_events"))
    if latest_objects:
        for key in _OBJECT_TABLES:
            _apply(diff.get(key), latest_objects, "name")
    return diff
```

（既有 `_latest_by_name` 呼叫慣例改變：原本吃 policy_events dict、現改吃 DataFrame——同檔內部私有函式，外部無人 import；既有防禦測試（None/garbage/`{"error":...}`）由 `attribute_changes` 的 isinstance 守門與 `events.get` 吸收，語義不變。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_policy_diff_attribution.py tests/test_audit_mod03_object_events.py tests/test_policy_diff_report.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/audit/audit_mod03_policy.py src/report/analysis/policy_diff/attribution.py tests/test_policy_diff_attribution.py tests/test_audit_mod03_object_events.py
git commit -m "feat(policy-diff): object-level audit events and attribution"
```

---

### Task 4: risk 物件分級 + scan_object_refs

**Files:**
- Modify: `src/report/analysis/policy_diff/risk.py`
- Modify: `src/report/analysis/policy_diff/object_diff.py`（追加 `scan_object_refs`）
- Test: `tests/test_policy_diff_risk.py` 與 `tests/test_policy_diff_object_diff.py` 擴充

**Interfaces:**
- Consumes: Task 2 物件表欄 `object_kind`/`object_id`/`scope_expanded`。
- Produces:
  - `scan_object_refs(active_rulesets: list[dict]) -> dict[str, int]`（object_diff.py）：掃 enabled ruleset 的 enabled allow 規則（只讀 `rs["rules"]`，不讀 `deny_rules`——deny 引用不構成暴露），providers/consumers 內 `ip_list`/`label_group` href 與 `ingress_services` 內 named `href` → key `f"{kind}:{尾段id}"` → 引用次數。
  - `grade_changes(diff, *, object_refs=None)`：keyword-only 新參數，預設 None（既有呼叫端不變）。物件表分級：removed → MEDIUM；modified 且 `scope_expanded` 且 `object_refs` 命中 → HIGH；其餘 ""。ruleset/rule 表分級規則完全不變。

- [ ] **Step 1: 寫失敗測試**

`tests/test_policy_diff_object_diff.py` 追加：

```python
from src.report.analysis.policy_diff.object_diff import scan_object_refs


def _active_rs(rules=None, enabled=True):
    return {"href": "/orgs/1/sec_policy/active/rule_sets/1", "name": "RS",
            "enabled": enabled, "rules": rules or [], "scopes": [[]]}


def test_scan_object_refs_counts_allow_rule_references():
    rule = {"enabled": True,
            "providers": [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/5"}}],
            "consumers": [{"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/8"}}],
            "ingress_services": [{"href": "/orgs/1/sec_policy/active/services/7"},
                                 {"port": 22, "proto": 6}]}
    refs = scan_object_refs([_active_rs(rules=[rule, rule])])
    assert refs == {"ip_list:5": 2, "label_group:8": 2, "service:7": 2}


def test_scan_object_refs_skips_disabled():
    rule = {"enabled": False,
            "providers": [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/5"}}],
            "consumers": [], "ingress_services": []}
    assert scan_object_refs([_active_rs(rules=[rule])]) == {}
    on_rule = dict(rule, enabled=True)
    assert scan_object_refs([_active_rs(rules=[on_rule], enabled=False)]) == {}
```

`tests/test_policy_diff_risk.py` 追加：

```python
def _obj_row(**over):
    row = {"change_type": "modified", "object_kind": "ip_list", "name": "L",
           "object_id": "5", "field": "ip_ranges", "draft_value": "x",
           "active_value": "y", "scope_expanded": True,
           "last_actor": "", "last_changed": "", "last_event": ""}
    row.update(over)
    return row


def _diff_with(rows):
    return {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
            "ip_list_changes": pd.DataFrame(rows)}


def test_expanded_and_referenced_is_high():
    diff = grade_changes(_diff_with([_obj_row()]), object_refs={"ip_list:5": 3})
    assert diff["ip_list_changes"].iloc[0]["risk"] == "HIGH"


def test_expanded_but_unreferenced_is_blank():
    diff = grade_changes(_diff_with([_obj_row()]), object_refs={})
    assert diff["ip_list_changes"].iloc[0]["risk"] == ""


def test_not_expanded_referenced_is_blank():
    diff = grade_changes(_diff_with([_obj_row(scope_expanded=False)]),
                         object_refs={"ip_list:5": 1})
    assert diff["ip_list_changes"].iloc[0]["risk"] == ""


def test_removed_object_is_medium():
    diff = grade_changes(_diff_with([_obj_row(change_type="removed", field="*",
                                              scope_expanded=False)]))
    assert diff["ip_list_changes"].iloc[0]["risk"] == "MEDIUM"


def test_added_object_is_blank():
    diff = grade_changes(_diff_with([_obj_row(change_type="added", field="*",
                                              scope_expanded=False)]))
    assert diff["ip_list_changes"].iloc[0]["risk"] == ""
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_policy_diff_risk.py tests/test_policy_diff_object_diff.py -v`
Expected: 新測試 FAIL（ImportError / TypeError object_refs / 物件表無 risk 欄）

- [ ] **Step 3: 實作**

`object_diff.py` 追加：

```python
def scan_object_refs(active_rulesets: list[dict]) -> dict[str, int]:
    """掃 ACTIVE enabled allow 規則，統計 ip_list/service/label_group 引用次數。

    只讀 rs["rules"]（allow）；deny 規則引用不構成暴露面，不計。
    key 形如 "ip_list:5"（kind:href 尾段 id）。
    """
    refs: dict[str, int] = {}

    def _bump(kind: str, href) -> None:
        oid = _id_from_href(str(href or ""))
        if oid:
            key = f"{kind}:{oid}"
            refs[key] = refs.get(key, 0) + 1

    for rs in active_rulesets or []:
        if not isinstance(rs, dict) or not rs.get("enabled", True):
            continue
        for rule in rs.get("rules") or []:
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            for side in ("providers", "consumers"):
                for it in rule.get(side) or []:
                    if not isinstance(it, dict):
                        continue
                    if isinstance(it.get("ip_list"), dict):
                        _bump("ip_list", it["ip_list"].get("href"))
                    elif isinstance(it.get("label_group"), dict):
                        _bump("label_group", it["label_group"].get("href"))
            for svc in rule.get("ingress_services") or []:
                if isinstance(svc, dict) and svc.get("href"):
                    _bump("service", svc["href"])
    return refs
```

`risk.py`：

```python
_OBJECT_TABLES = ("ip_list_changes", "service_changes", "label_group_changes")


def _grade_object_row(row, refs: dict) -> str:
    change = str(row.get("change_type", ""))
    if change == "removed":
        return "MEDIUM"
    if change == "modified" and bool(row.get("scope_expanded")):
        key = f"{row.get('object_kind', '')}:{row.get('object_id', '')}"
        if refs.get(key, 0) > 0:
            return "HIGH"
    return ""


def grade_changes(diff: dict, *, object_refs: dict | None = None) -> dict:
    # 既有 ruleset/rule 分級不變
    _apply(diff.get("ruleset_changes"))
    _apply(diff.get("rule_changes"))
    refs = object_refs or {}
    for key in _OBJECT_TABLES:
        df = diff.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df["risk"] = df.apply(lambda r: _grade_object_row(r, refs), axis=1)
    return diff
```

（`_apply`/`_grade_row` 既有實作原樣保留；risk.py 現行 `_apply` 簽名若為 `_apply(df, grader)` 依現場保留呼叫式。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_policy_diff_risk.py tests/test_policy_diff_object_diff.py tests/test_policy_diff_report.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/policy_diff/risk.py src/report/analysis/policy_diff/object_diff.py tests/test_policy_diff_risk.py tests/test_policy_diff_object_diff.py
git commit -m "feat(policy-diff): risk grading for policy objects with allow-rule reference scan"
```

---

### Task 5: 報表組裝、exporter 三新章、i18n

**Files:**
- Modify: `src/report/policy_diff_report.py`（`build` 取數與組裝、`_build_name_map` 改吃預取清單）
- Modify: `src/report/exporters/policy_diff_html_exporter.py`（`_table` 泛化 name 欄 + 三新章 + `_COL_I18N` 補欄）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_policy_diff_report.py`、`tests/test_policy_diff_html_exporter.py` 擴充

**Interfaces:**
- Consumes: T1 `pversion="draft"`、T2 `diff_objects`/`object_change_counts`、T3 attribution、T4 `scan_object_refs`/`grade_changes(object_refs=...)`。
- Produces: `build()` 回傳 dict 新增三鍵 `ip_list_changes`/`service_changes`/`label_group_changes`；summary 新增 `ip_lists_added/removed/modified`、`services_*`、`label_groups_*` 九鍵，`total_changes` 含物件層。HTML 新增三章（id：`ip-list-changes`/`service-changes`/`label-group-changes`），沿用既有變更表版型與 risk 排序/上色；空表出 no_changes note。CSV（`CsvExporter(diff, ...)`）自動涵蓋新 DataFrame 鍵。CLI/GUI/scheduler 無需改動。

- [ ] **Step 1: 寫失敗測試**

`tests/test_policy_diff_report.py` 追加（沿用該檔 MagicMock api 慣例、`_fetch_policy_events` patch 慣例）：

```python
def test_build_includes_object_layers():
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.side_effect = lambda pversion="active": {
        "active": [{"href": "/orgs/1/sec_policy/active/ip_lists/5", "name": "L",
                    "ip_ranges": [{"from_ip": "10.0.0.0/8"}], "fqdns": [], "description": ""}],
        "draft": [{"href": "/orgs/1/sec_policy/draft/ip_lists/5", "name": "L",
                   "ip_ranges": [{"from_ip": "10.0.0.0/8"}, {"from_ip": "0.0.0.0/0"}],
                   "fqdns": [], "description": ""}],
    }[pversion]
    api.get_services.side_effect = lambda pversion="active": []
    api.get_label_groups.side_effect = lambda pversion="active": []
    rep = PolicyDiffReport(MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_policy_events", return_value={"draft_events": None}):
        diff = rep.build()
    assert len(diff["ip_list_changes"]) == 1
    assert diff["summary"]["ip_lists_modified"] == 1
    assert diff["summary"]["services_added"] == 0
    assert diff["summary"]["total_changes"] == 1
    assert "risk" in diff["ip_list_changes"].columns


def test_build_object_layers_draft_and_active_fetched():
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.return_value = []
    api.get_services.return_value = []
    api.get_label_groups.return_value = []
    rep = PolicyDiffReport(MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_policy_events", return_value={"draft_events": None}):
        rep.build()
    for m in (api.get_ip_lists, api.get_services, api.get_label_groups):
        kwargs_seen = {c.kwargs.get("pversion", "active") for c in m.call_args_list}
        assert kwargs_seen == {"active", "draft"}
```

（既有 `test_build_without_api_returns_empty_diff` 需同步斷言新 summary 鍵為 0——total_changes 仍 0。）

`tests/test_policy_diff_html_exporter.py` 追加：

```python
def _object_results():
    ipl = pd.DataFrame([
        {"risk": "HIGH", "change_type": "modified", "object_kind": "ip_list",
         "name": "Corp-Nets", "object_id": "5", "field": "ip_ranges",
         "draft_value": "0.0.0.0/0, 10.0.0.0/8", "active_value": "10.0.0.0/8",
         "scope_expanded": True, "last_actor": "alice", "last_changed": "t", "last_event": "ip_list.update"},
    ])
    return {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
            "ip_list_changes": ipl, "service_changes": pd.DataFrame(),
            "label_group_changes": pd.DataFrame(),
            "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
                        "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                        "ip_lists_added": 0, "ip_lists_removed": 0, "ip_lists_modified": 1,
                        "services_added": 0, "services_removed": 0, "services_modified": 0,
                        "label_groups_added": 0, "label_groups_removed": 0,
                        "label_groups_modified": 0, "total_changes": 1}}


def test_object_sections_rendered(tmp_path):
    path = PolicyDiffHtmlExporter(_object_results(), lang="en").export(str(tmp_path))
    html = Path(path).read_text(encoding="utf-8")
    assert 'id="ip-list-changes"' in html
    assert 'id="service-changes"' in html
    assert 'id="label-group-changes"' in html
    assert "Corp-Nets" in html
    assert 'class="pd-risk-high"' in html
    # 空的 service 章顯示 no-changes note 而非空表
    assert html.count("report-table-wrap") == 1


def test_object_section_headers_localized(tmp_path):
    path = PolicyDiffHtmlExporter(_object_results(), lang="zh_TW").export(str(tmp_path))
    html = Path(path).read_text(encoding="utf-8")
    assert "[MISSING" not in html
    assert "IP List" in html  # glossary：物件型別名保持英文
    # 內部欄位 scope_expanded / object_kind 不出現在表頭
    assert "scope_expanded" not in html
    assert "object_kind" not in html
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_policy_diff_report.py tests/test_policy_diff_html_exporter.py -v`
Expected: 新測試 FAIL

- [ ] **Step 3: 實作 facade**

`policy_diff_report.py`：`_build_name_map` 改吃預取清單（呼叫端只有 build）：

```python
    _OBJECT_SPECS = (
        # (diff 鍵前綴, api 方法名, diff_objects kind, 比對欄位)
        ("ip_lists", "get_ip_lists", "ip_list", ["ip_ranges", "fqdns", "description"]),
        ("services", "get_services", "service", ["service_ports", "windows_services", "description"]),
        ("label_groups", "get_label_groups", "label_group", ["labels", "sub_groups", "description"]),
    )
    _KIND_TO_KEY = {"ip_list": "ip_list_changes", "service": "service_changes",
                    "label_group": "label_group_changes"}

    def _build_name_map(self, *inventories) -> dict[str, str]:
        names: dict[str, str] = {}
        for objs in inventories:
            for obj in objs or []:
                href, name = obj.get("href"), obj.get("name")
                if href and name:
                    names[str(href)] = str(name)
        names.update({h.replace("/active/", "/draft/"): n
                      for h, n in names.items() if "/active/" in h})
        return names

    def build(self, lang: str = "en") -> dict:
        draft = self.api.get_all_rulesets(force_refresh=True) if self.api else []
        active = self.api.get_active_rulesets() if self.api else []
        active_inv, draft_inv = {}, {}
        for key, method, kind, fields in self._OBJECT_SPECS:
            fetch = getattr(self.api, method) if self.api else None
            active_inv[kind] = fetch() if fetch else []
            draft_inv[kind] = fetch(pversion="draft") if fetch else []
        names = self._build_name_map(*active_inv.values())
        diff = diff_rulesets(draft, active, names=names)
        for key, method, kind, fields in self._OBJECT_SPECS:
            df = diff_objects(draft_inv[kind], active_inv[kind],
                              kind=kind, fields=fields, names=names)
            diff[self._KIND_TO_KEY[kind]] = df
            added, removed, modified = object_change_counts(df)
            diff["summary"][f"{key}_added"] = added
            diff["summary"][f"{key}_removed"] = removed
            diff["summary"][f"{key}_modified"] = modified
            diff["summary"]["total_changes"] += added + removed + modified
        attribute_changes(diff, self._fetch_policy_events(lang))
        grade_changes(diff, object_refs=scan_object_refs(active))
        return diff
```

import 補 `from src.report.analysis.policy_diff.object_diff import diff_objects, object_change_counts, scan_object_refs`（依該檔既有 import 風格）。

- [ ] **Step 4: 實作 exporter 與 i18n**

`policy_diff_html_exporter.py`：
1. `_table(df, id_col)` → `_table(df, id_col, name_col="ruleset_name")`，欄序列表中 `"ruleset_name"` 換成 `name_col`。既有兩處呼叫不變。
2. `_COL_I18N` 追加 `"name": "rpt_policy_diff_col_name"`、`"object_id": "rpt_policy_diff_col_object_id"`。
3. `_render_html` 在 rule-changes 章之後、attribution note 之前追加：

```python
        for section_id, title_key, df_key in (
            ("ip-list-changes", "rpt_policy_diff_ip_list_changes", "ip_list_changes"),
            ("service-changes", "rpt_policy_diff_service_changes", "service_changes"),
            ("label-group-changes", "rpt_policy_diff_label_group_changes", "label_group_changes"),
        ):
            parts.append(self._section(
                section_id, t(title_key, lang=lang),
                self._table(self.results.get(df_key), "object_id", name_col="name")))
```

（`parts` 為該檔既有章節累加變數名，依現場為準；置點 = `_section("rule-changes", ...)` 之後。）

i18n（en / zh_TW 同步，zh 物件型別名依 glossary 保持英文）：

```json
"rpt_policy_diff_ip_list_changes": "IP List Changes (DRAFT vs ACTIVE)",
"rpt_policy_diff_service_changes": "Service Changes (DRAFT vs ACTIVE)",
"rpt_policy_diff_label_group_changes": "Label Group Changes (DRAFT vs ACTIVE)",
"rpt_policy_diff_col_name": "Name",
"rpt_policy_diff_col_object_id": "ID",
```

```json
"rpt_policy_diff_ip_list_changes": "IP List 變更（DRAFT vs ACTIVE）",
"rpt_policy_diff_service_changes": "Service 變更（DRAFT vs ACTIVE）",
"rpt_policy_diff_label_group_changes": "Label Group 變更（DRAFT vs ACTIVE）",
"rpt_policy_diff_col_name": "名稱",
"rpt_policy_diff_col_object_id": "ID",
```

放置位置：兩檔各自既有 `rpt_policy_diff_*` 區塊內；檔尾單一 newline。

- [ ] **Step 5: 跑測試確認通過（含入口回歸）**

Run: `python3 -m pytest tests/test_policy_diff_report.py tests/test_policy_diff_html_exporter.py tests/test_cli_report_policy_diff.py tests/test_gui_policy_diff_generate.py tests/test_policy_diff_resolver_scheduler_dispatch.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add src/report/policy_diff_report.py src/report/exporters/policy_diff_html_exporter.py src/i18n_en.json src/i18n_zh_TW.json tests/test_policy_diff_report.py tests/test_policy_diff_html_exporter.py
git commit -m "feat(policy-diff): ip-list/service/label-group diff sections"
```

---

### Task 6: E2E 實樣本輸出與截斷檢查

**Files:**
- Create: 暫存腳本（scratchpad，不入 repo）
- 不改 production code（若檢查發現截斷/溢出問題，回報後由 controller 決定修補 task）

**內容（依專案 CLAUDE.md 報表交付鐵律）：**

- [ ] **Step 1:** 寫暫存腳本：MagicMock ApiClient 餵代表性 fixture——3 個 ruleset（含 added/removed/modified）、3 種物件各含 added/removed/modified 三態，其中至少一筆 ip_list 有 20+ ip_ranges（長值換行測試）、一筆 service 名稱 60+ 字元、一筆 label_group 有 15 個成員；`_fetch_policy_events` patch 成含配對事件。呼叫 `PolicyDiffReport.run(output_dir=<scratchpad>, lang=...)` 產出 en 與 zh_TW 兩份 HTML。
- [ ] **Step 2:** 逐章檢查兩份 HTML：五章齊全（Ruleset / Rule / IP List / Service / Label Group）、長值在 `report-table-wrap` 內正常換行無無聲截斷、risk 上色與排序正確、`[MISSING` 不出現、print CSS（`.print-btn` screen-only）不變。
- [ ] **Step 3:** `python3 -m pytest tests/ -q` 全套（期望 ≥2465+新增 全綠）。
- [ ] **Step 4:** 檢查結果寫入報告檔（含逐章檢核表），不 commit 程式變更；若有 fixture 檔誤入 repo 立即移除。

---

## 完成定義

- `report policy-diff` 產出的 HTML 含五章（Ruleset / Rule / IP List / Service / Label Group），en/zh_TW 皆無 `[MISSING`。
- 三種物件 added/removed/modified 皆有 attribution 欄與 risk 分級；HIGH 僅出現在「擴大且被 ACTIVE enabled allow 規則引用」。
- 既有呼叫端（CLI/GUI/scheduler、`grade_changes(diff)` 舊簽名）零改動、零行為破壞；全套 pytest 綠。
- E2E 實樣本逐章檢查通過（長值無截斷、print-fit）。
