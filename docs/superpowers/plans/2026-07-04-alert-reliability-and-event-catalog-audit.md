# Alert 可靠性改善 + Event Catalog 原廠對齊 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正告警管線的四個可靠性缺陷（at-most-once 遺失、無 dead-man's switch、健檢假陰性、溢出無補救），並將事件目錄與原廠 Events Administration Guide 完成全量對齊（分層 vendor/observed、補 5 筆缺漏、修正錯誤引用）。

**Architecture:** 告警可靠性以「state 檔內建 DLQ + 有限重試」實現 at-least-once；健檢改為解析 `/api/v2/health` body 的 status 欄位；watchdog 以 `pce_stats.consecutive_failures` 觸發自身異常告警。事件目錄拆成 `VENDOR_DOCUMENTED_EVENT_TYPES`（與原廠 List of Event Types 一字不差）與 `OBSERVED_EXTENSION_EVENT_TYPES`（實測觀察到但官方未記載），`KNOWN_EVENT_TYPES` 維持兩者聯集，對外行為不變。

**Tech Stack:** Python 3.12、pytest、pydantic（config models）、NotebookLM CLI（僅 Task 1 建 fixture 用）。

## Global Constraints

- Commit message 一律英文 conventional commits（repo 慣例，見 memory `commit-message-language`）。
- 所有輸出（程式、註解、alert 文案）不得使用 emoji。
- i18n：任何新的使用者可見字串必須同時加入 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`（兩檔各 4000+ 行，key 按字母序附近插入即可，JSON 需合法）。
- `is_known_event_type()` 的對外行為不得改變（既有 lenient 分類、`unknown_events` 追蹤依賴它）。
- 每個 KNOWN event type 都必須有 `docs/_meta/illumio-event-reference.json` 條目與 `event_label_<type>` i18n key（`tests/test_event_reference_coverage.py` 會強制檢查）。
- 測試指令一律 `python -m pytest tests/<file> -v`（在 repo 根目錄執行）。
- 專案 CLAUDE.md 規則：任何告警輸出通道的內容變更，交付前須用實際樣本資料跑一次完整輸出檢查截斷（Task 10 統一執行）。

---

## 背景：已完成的盤點結論（2026-07-04，NotebookLM「Illumio」筆記本查證）

以下事實已透過原廠 Events Administration Guide / REST API Guide 逐條查證，實作時直接引用，不需重查（Task 1 會再以 fixture 機械化驗證一次）：

1. **事件 severity 合法值共 8 級**：`emerg / alert / crit / err / warning / notice / info / debug`。現行 `reporter.py` 對照表缺 `notice`、`debug`。
2. **事件 status 合法值**：`success / failure / null`（null 代表純資訊事件）。現行 matcher 處理正確，無需修改。
3. **同步 `GET /events` 超過 `max_results` 時只回傳「最新」事件**，無分頁；超量須改 async GET collections。溢出等於永久漏掉最舊事件。
4. **`GET /api/v2/health` 在 PCE degraded 時仍回 HTTP 200**；健康與否要看 body 的 `status`（`normal` / `warning` / ...）等欄位。只看狀態碼會假陰性。
5. **官方 List of Event Types 中存在、但現行 catalog 缺少的 5 筆**（名稱一字不差）：
   - `agent.refresh_policy` — "Success or failure to apply policy on VEN"
   - `logout_from_jwt` — "User logged out"（無 `user.` 前綴）
   - `support_report_request.create` — "Support report requested"
   - `support_report_request.delete` — "Deleted a request for a support report"
   - `support_reports` — "Support report added"（無動詞後綴）
6. **`agent.reguest_policy`（拼字錯誤）與 `agent.request_policy` 皆不在官方列表**。前者已在 `_HIDDEN_EVENT_TYPES`。
7. **現行 catalog 中約 50 筆為官方未記載**（含 `deny_rule.*`、`label_dimension.*`、`service_account.*`、`radius_config.*`、多筆 `system_task.*` 等）。其中 `deny_rule.*`、`agent.upgrade_successful`、`container_cluster.kubernetes_workloads_bulk_*`、`label_dimension.*` 已知是 PCE 25.x 實測發出的真實事件（見 `tests/test_event_catalog_coverage.py` 的 `PCE_25X_BACKFILL` 註解）。**這些不能刪除**，要移入 observed 分層。
8. **`hard_limit.exceeded` / `soft_limit.exceeded` / `system_task.hard_limit_recovery_completed` / `system_task.event_pruning_completed` 不是 event type**，是「Notification Messages in Events」清單中的 `notification_type` 值，附掛在主要事件（如 `system_task.prune_old_log_events`）的 `notifications[]` 內。容量告警要靠 notification_type 匹配，不是新增 event type。
9. **容量相關語意**：事件儲存達磁碟 20%（soft limit）觸發積極 pruning；達 25%（hard limit）停止記錄新事件並強制清理。`database.temp_table_autocleanup_started/completed` 為官方記載的資料庫暫存表清理事件（catalog 已有）。
10. **reporter `_REC_I18N_KEYS` 中的 `agent.refresh_policy` 是正確的官方名稱**——錯的是 catalog 缺這筆（修 catalog 即對齊，REC key 不動）。

---

### Task 1: Event Catalog 分層重構與原廠 fixture 對齊

**Files:**
- Create: `tests/fixtures/vendor_event_types.json`
- Create: `tests/test_event_catalog_vendor_alignment.py`
- Modify: `src/events/catalog.py`（`KNOWN_EVENT_TYPES` 區塊、`LOCAL_EXTENSION_EVENT_TYPES`）
- Modify: `docs/_meta/illumio-event-reference.json`（新增 5 筆）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新增 5 個 `event_label_*` key）

**Interfaces:**
- Produces: `VENDOR_DOCUMENTED_EVENT_TYPES: frozenset[str]`、`OBSERVED_EXTENSION_EVENT_TYPES: frozenset[str]`、`is_vendor_documented(event_type: str) -> bool`（`src/events/catalog.py` 頂層）。`KNOWN_EVENT_TYPES` 簽名與內容語意不變（= 兩層聯集）。
- Consumes: 無（第一個 task）。

- [ ] **Step 1: 用 NotebookLM 產出官方 event type fixture**

在 repo 根目錄執行三段查詢（官方列表約 240 筆，分段避免回答截斷）：

```bash
NB=8c325126-bc83-4c86-8c6e-8759a242928e
S=$(mktemp -d)
notebooklm ask --notebook $NB "請把 Events Administration Guide 的 List of Event Types 總表中，JSON Event Type 字串以 a 到 k 開頭者全部列出。一行一筆，只要字串本身，不要描述、不要編號、不要遺漏。" > $S/a_k.txt
notebooklm ask --notebook $NB "同上表，列出以 l 到 r 開頭者。一行一筆，只要字串本身。" > $S/l_r.txt
notebooklm ask --notebook $NB "同上表，列出以 s 到 z 開頭者。一行一筆，只要字串本身。" > $S/s_z.txt
# 清洗成 JSON（去掉非 event-type 行）
python3 - "$S" <<'EOF'
import json, re, sys, pathlib
lines = []
for f in pathlib.Path(sys.argv[1]).glob("*.txt"):
    for ln in f.read_text().splitlines():
        ln = ln.strip().strip("`*• ")
        if re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)?", ln) and ln not in ("json", "event", "type"):
            lines.append(ln)
out = sorted(set(lines))
pathlib.Path("tests/fixtures/vendor_event_types.json").write_text(json.dumps(out, indent=1) + "\n")
print(f"fixture entries: {len(out)}")
EOF
```

Expected: `fixture entries:` 介於 200–260 之間。**人工抽查**：fixture 必須含 `agent.refresh_policy`、`logout_from_jwt`、`support_reports`、`lost_agent.found`、`agent.tampering`；必須不含 `agent.reguest_policy`、`deny_rule.create`。若抽查失敗（NotebookLM 列舉有漏），針對缺漏字母段重問一次並手動補齊，補齊依據以背景結論第 5、6、7 點為準。

- [ ] **Step 2: 寫失敗測試**

`tests/test_event_catalog_vendor_alignment.py`：

```python
"""Vendor-alignment tests: the vendor tier must match the official
Events Administration Guide list exactly; observed tier is disjoint."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path("tests/fixtures/vendor_event_types.json")


def _fixture_set() -> frozenset[str]:
    return frozenset(json.loads(FIXTURE.read_text()))


def test_vendor_tier_matches_official_fixture_exactly():
    from src.events.catalog import VENDOR_DOCUMENTED_EVENT_TYPES
    official = _fixture_set()
    missing = official - VENDOR_DOCUMENTED_EVENT_TYPES
    extra = VENDOR_DOCUMENTED_EVENT_TYPES - official
    assert not missing, f"official types absent from vendor tier: {sorted(missing)}"
    assert not extra, f"vendor tier claims undocumented types: {sorted(extra)}"


def test_tiers_are_disjoint_and_union_is_known():
    from src.events.catalog import (
        KNOWN_EVENT_TYPES,
        OBSERVED_EXTENSION_EVENT_TYPES,
        VENDOR_DOCUMENTED_EVENT_TYPES,
    )
    assert not (VENDOR_DOCUMENTED_EVENT_TYPES & OBSERVED_EXTENSION_EVENT_TYPES)
    assert KNOWN_EVENT_TYPES == (VENDOR_DOCUMENTED_EVENT_TYPES | OBSERVED_EXTENSION_EVENT_TYPES)


def test_previously_missing_official_types_now_known():
    from src.events.catalog import VENDOR_DOCUMENTED_EVENT_TYPES, is_known_event_type
    for et in (
        "agent.refresh_policy",
        "logout_from_jwt",
        "support_report_request.create",
        "support_report_request.delete",
        "support_reports",
    ):
        assert et in VENDOR_DOCUMENTED_EVENT_TYPES
        assert is_known_event_type(et)


def test_typo_variant_stays_observed_and_hidden():
    from src.events.catalog import (
        OBSERVED_EXTENSION_EVENT_TYPES,
        VENDOR_DOCUMENTED_EVENT_TYPES,
        _HIDDEN_EVENT_TYPES,
    )
    assert "agent.reguest_policy" in OBSERVED_EXTENSION_EVENT_TYPES
    assert "agent.reguest_policy" not in VENDOR_DOCUMENTED_EVENT_TYPES
    assert "agent.reguest_policy" in _HIDDEN_EVENT_TYPES


def test_pce_25x_backfill_stays_known_via_observed_tier():
    from src.events.catalog import OBSERVED_EXTENSION_EVENT_TYPES, is_known_event_type
    for et in (
        "deny_rule.create",
        "agent.upgrade_successful",
        "container_cluster.kubernetes_workloads_bulk_create",
        "label_dimension.create",
    ):
        assert et in OBSERVED_EXTENSION_EVENT_TYPES
        assert is_known_event_type(et)


def test_is_vendor_documented_helper():
    from src.events.catalog import is_vendor_documented
    assert is_vendor_documented("agent.tampering")
    assert not is_vendor_documented("deny_rule.create")
    assert not is_vendor_documented("totally.unknown_thing")
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `python -m pytest tests/test_event_catalog_vendor_alignment.py -v`
Expected: FAIL — `ImportError: cannot import name 'VENDOR_DOCUMENTED_EVENT_TYPES'`

- [ ] **Step 4: 重構 `src/events/catalog.py`**

用腳本機械化產生分層（避免手抄 288 筆出錯），在 repo 根目錄執行：

```bash
python3 - <<'EOF'
import json, re
official = set(json.load(open("tests/fixtures/vendor_event_types.json")))
src = open("src/events/catalog.py").read()
m = re.search(r"KNOWN_EVENT_TYPES = \{(.*?)\n\}", src, re.S)
current = set(re.findall(r'"([a-z0-9_.]+)"', m.group(1)))
m2 = re.search(r"LOCAL_EXTENSION_EVENT_TYPES = \{(.*?)\n\}", src, re.S)
local = set(re.findall(r'"([a-z0-9_.]+)"', m2.group(1)))
current |= local
missing = {"agent.refresh_policy", "logout_from_jwt",
           "support_report_request.create", "support_report_request.delete",
           "support_reports"}
vendor = (current & official) | (missing & official) | missing
observed = (current - official) | (local - official)
print("VENDOR_DOCUMENTED_EVENT_TYPES = frozenset({")
for et in sorted(vendor): print(f'    "{et}",')
print("})\n")
print("OBSERVED_EXTENSION_EVENT_TYPES = frozenset({")
for et in sorted(observed): print(f'    "{et}",')
print("})")
EOF
```

把輸出貼進 `src/events/catalog.py`，取代現有的 `KNOWN_EVENT_TYPES = {...}` 與 `LOCAL_EXTENSION_EVENT_TYPES = {...}` 兩個區塊，結構如下：

```python
# Tier 1: exactly the official "List of Event Types" (Events Administration
# Guide; cross-checked against tests/fixtures/vendor_event_types.json).
VENDOR_DOCUMENTED_EVENT_TYPES: frozenset[str] = frozenset({
    # ... 腳本輸出 ...
})

# Tier 2: emitted by real PCE builds (25.x field observations, upstream
# pretty-cool-events entries, notification-derived types) but absent from
# the official List of Event Types. Kept known so they never regress into
# unknown_events noise; excluded from any "vendor documented" claim.
OBSERVED_EXTENSION_EVENT_TYPES: frozenset[str] = frozenset({
    # ... 腳本輸出（含 agent.reguest_policy、agent.request_policy、
    #     deny_rule.* 等）...
})

KNOWN_EVENT_TYPES = set(VENDOR_DOCUMENTED_EVENT_TYPES | OBSERVED_EXTENSION_EVENT_TYPES)


def is_vendor_documented(event_type: str) -> bool:
    """True if the event type appears verbatim in the official Event Guide list."""
    return event_type in VENDOR_DOCUMENTED_EVENT_TYPES
```

注意：舊的 `KNOWN_EVENT_TYPES |= LOCAL_EXTENSION_EVENT_TYPES` 行刪除；`LOCAL_EXTENSION_EVENT_TYPES` 名稱移除（原 3 筆併入 OBSERVED）。全 repo grep `LOCAL_EXTENSION_EVENT_TYPES` 確認無其他引用後才可刪。

- [ ] **Step 5: 補 5 筆新事件的 reference 與 i18n**

`docs/_meta/illumio-event-reference.json` 新增（維持字母序位置）：

```json
"agent.refresh_policy": {
 "category": "Agent Lifecycle",
 "description": "Success or failure to apply policy on VEN.",
 "severity": "info",
 "remediation": "If status is failure, check VEN connectivity and re-sync policy from the PCE.",
 "doc_url": ""
},
"logout_from_jwt": {
 "category": "User Activity",
 "description": "User logged out (JWT session).",
 "severity": "info",
 "remediation": "",
 "doc_url": ""
},
"support_report_request.create": {
 "category": "System",
 "description": "Support report requested.",
 "severity": "info",
 "remediation": "",
 "doc_url": ""
},
"support_report_request.delete": {
 "category": "System",
 "description": "Deleted a request for a support report.",
 "severity": "info",
 "remediation": "",
 "doc_url": ""
},
"support_reports": {
 "category": "System",
 "description": "Support report added.",
 "severity": "info",
 "remediation": "",
 "doc_url": ""
}
```

（category 字串請先看檔內既有值的用法，沿用既有 category 名稱，不要發明新的。）

`src/i18n_en.json` 新增：

```json
"event_label_agent_refresh_policy": "Agent Refresh Policy",
"event_label_logout_from_jwt": "Logout From JWT",
"event_label_support_report_request_create": "Support Report Request Create",
"event_label_support_report_request_delete": "Support Report Request Delete",
"event_label_support_reports": "Support Report Added",
```

`src/i18n_zh_TW.json` 新增：

```json
"event_label_agent_refresh_policy": "代理程式套用政策",
"event_label_logout_from_jwt": "使用者登出（JWT）",
"event_label_support_report_request_create": "建立支援報告請求",
"event_label_support_report_request_delete": "刪除支援報告請求",
"event_label_support_reports": "支援報告已產生",
```

- [ ] **Step 6: 跑新測試與既有回歸**

Run: `python -m pytest tests/test_event_catalog_vendor_alignment.py tests/test_event_catalog_coverage.py tests/test_event_reference_coverage.py -v`
Expected: 全 PASS。若 `test_every_known_type_has_label_key` 因 `logout_from_jwt` / `support_reports`（無動詞）的分類落點失敗，檢查 `_event_category()` 的 fallback 分支並依錯誤訊息補 i18n key，不要改分類邏輯。

- [ ] **Step 7: 全套測試**

Run: `python -m pytest tests/ -x -q`
Expected: 全 PASS。

- [ ] **Step 8: Commit**

```bash
git add src/events/catalog.py docs/_meta/illumio-event-reference.json \
  src/i18n_en.json src/i18n_zh_TW.json tests/fixtures/vendor_event_types.json \
  tests/test_event_catalog_vendor_alignment.py
git commit -m "feat(events): split catalog into vendor-documented and observed tiers, add 5 missing official types"
```

---

### Task 2: notification_type 抽取與規則匹配支援

**Files:**
- Modify: `src/events/normalizer.py`（`normalize_event`）
- Modify: `src/events/matcher.py`（`matches_event_rule`）
- Create: `tests/test_notification_matching.py`

**Interfaces:**
- Consumes: 無新依賴。
- Produces: normalized dict 新增 key `notification_types: list[str]`；event rule 的 `match_fields` 支援特殊欄位 `"notification_type"`（對 `notifications[].notification_type` 做 any-of 匹配，pattern 語法同 `_value_matches`）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_notification_matching.py`：

```python
"""notification_type extraction and rule matching (capacity alerts rely on it:
hard_limit.exceeded / soft_limit.exceeded are notification types, not event types)."""
from __future__ import annotations

from src.events.matcher import matches_event_rule
from src.events.normalizer import normalize_event

PRUNE_EVENT = {
    "href": "/orgs/1/events/abc",
    "event_type": "system_task.prune_old_log_events",
    "timestamp": "2026-07-04T03:00:00Z",
    "severity": "err",
    "status": None,
    "notifications": [
        {"notification_type": "hard_limit.exceeded", "info": {}},
    ],
}


def test_normalizer_extracts_notification_types():
    norm = normalize_event(PRUNE_EVENT)
    assert norm["notification_types"] == ["hard_limit.exceeded"]


def test_normalizer_handles_missing_notifications():
    norm = normalize_event({"event_type": "user.login", "timestamp": "2026-07-04T00:00:00Z"})
    assert norm["notification_types"] == []


def test_rule_matches_on_notification_type():
    rule = {
        "filter_value": "system_task.prune_old_log_events",
        "filter_status": "all",
        "filter_severity": "all",
        "match_fields": {"notification_type": "hard_limit.exceeded|soft_limit.exceeded"},
    }
    assert matches_event_rule(rule, PRUNE_EVENT)


def test_rule_rejects_when_notification_type_absent():
    rule = {
        "filter_value": "system_task.prune_old_log_events",
        "filter_status": "all",
        "filter_severity": "all",
        "match_fields": {"notification_type": "hard_limit.exceeded"},
    }
    benign = dict(PRUNE_EVENT, notifications=[{"notification_type": "system_task.event_pruning_completed"}])
    assert not matches_event_rule(rule, benign)
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_notification_matching.py -v`
Expected: FAIL（`notification_types` KeyError、match 失敗）

- [ ] **Step 3: 實作**

`src/events/normalizer.py` — 在 `_extract_notification_user` 旁新增：

```python
def _extract_notification_types(event: dict[str, Any]) -> list[str]:
    notifications = event.get("notifications")
    if not isinstance(notifications, list):
        return []
    out: list[str] = []
    for entry in notifications:
        if isinstance(entry, dict):
            nt = _string(entry.get("notification_type"))
            if nt:
                out.append(nt)
    return out
```

`normalize_event()` 的 normalized dict 中，緊接 `"notifications_count"` 之後加入：

```python
        "notification_types": _extract_notification_types(event),
```

`src/events/matcher.py` — `matches_event_rule` 的 match_fields 迴圈改為：

```python
    match_fields = rule.get("match_fields") or rule.get("filter_match_fields") or {}
    for field_path, pattern in match_fields.items():
        if field_path == "notification_type":
            notifications = event.get("notifications")
            values = [
                str(entry.get("notification_type") or "")
                for entry in notifications
                if isinstance(entry, dict)
            ] if isinstance(notifications, list) else []
            if not any(_value_matches(str(pattern), v) for v in values):
                return False
            continue
        if not _value_matches(str(pattern), _extract_nested(event, field_path)):
            return False
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_notification_matching.py tests/test_event_core.py tests/test_event_monitoring.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/events/normalizer.py src/events/matcher.py tests/test_notification_matching.py
git commit -m "feat(events): extract notification_types and support notification_type rule matching"
```

---

### Task 3: Runbooks 補強（容量類別、缺漏事件、prune 語意）與 REC 對齊測試

**Files:**
- Modify: `src/events/runbooks.py`
- Create: `tests/test_runbook_rec_alignment.py`

**Interfaces:**
- Consumes: Task 1 的 `KNOWN_EVENT_TYPES`（新增 5 筆已存在）。
- Produces: `RUNBOOK_CATEGORIES` 新增 `pce-capacity` 類別；`agent-lifecycle` 補 `lost_agent.found`、`agent.service_not_available`、`agent.refresh_policy`；`security-auth-activity` 補 `logout_from_jwt`。`runbook_for()` 簽名不變。

- [ ] **Step 1: 寫失敗測試**

`tests/test_runbook_rec_alignment.py`：

```python
"""Keep the two parallel advice systems (reporter _REC_I18N_KEYS and
events.runbooks) aligned with each other and with the catalog."""
from __future__ import annotations

from src.events.catalog import KNOWN_EVENT_TYPES
from src.events.runbooks import RUNBOOK_CATEGORIES, runbook_for
from src.reporter import Reporter


def _all_runbook_patterns() -> set[str]:
    return {p for cat in RUNBOOK_CATEGORIES.values() for p in cat["patterns"]}


def test_every_rec_key_is_a_known_event_type():
    unknown = set(Reporter._REC_I18N_KEYS) - set(KNOWN_EVENT_TYPES)
    assert not unknown, f"_REC_I18N_KEYS references unknown event types: {sorted(unknown)}"


def test_every_rec_key_has_a_runbook():
    missing = set(Reporter._REC_I18N_KEYS) - _all_runbook_patterns()
    assert not missing, f"_REC_I18N_KEYS entries without runbook coverage: {sorted(missing)}"


def test_every_runbook_pattern_is_a_known_event_type():
    unknown = _all_runbook_patterns() - set(KNOWN_EVENT_TYPES)
    assert not unknown, f"runbook patterns reference unknown event types: {sorted(unknown)}"


def test_capacity_category_exists_with_valid_severity():
    cat = RUNBOOK_CATEGORIES["pce-capacity"]
    assert cat["severity_hint"] == "critical"
    assert "database.temp_table_autocleanup_started" in cat["patterns"]


def test_prune_response_mentions_limit_semantics():
    rb = runbook_for("system_task.prune_old_log_events")
    assert rb is not None
    assert "hard limit" in rb["response"].lower()
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_runbook_rec_alignment.py -v`
Expected: FAIL — `pce-capacity` KeyError、`agent.refresh_policy` / `lost_agent.found` / `agent.service_not_available` 無 runbook。

- [ ] **Step 3: 修改 `src/events/runbooks.py`**

(1) `agent-lifecycle` 的 `patterns` 追加三筆：

```python
            "agent.refresh_policy",
            "agent.service_not_available",
            "lost_agent.found",
```

(2) `security-auth-activity` 的 `patterns` 追加：

```python
            "logout_from_jwt",
```

(3) 新增類別（放在 `system-tasks` 之後）：

```python
    "pce-capacity": {
        "patterns": [
            "database.temp_table_autocleanup_started",
            "database.temp_table_autocleanup_completed",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/events-administration/events-monitoring.htm",
        "severity_hint": "critical",
        "response": "Check PCE event database disk usage immediately. The PCE prunes events aggressively once event storage reaches 20 percent of disk (soft limit) and stops recording new events at 25 percent (hard limit), which silently breaks event-based alerting. Review Troubleshooting > Events for prune_old_log_events entries whose notifications carry soft_limit.exceeded or hard_limit.exceeded, reduce event retention, or expand disk. Confirm system_task.hard_limit_recovery_completed appears after cleanup.",
    },
```

(4) `system-tasks` 類別的 `response` 末尾追加一句（保留原文，串接在最後）：

```python
        "response": "... 原句保留 ... running correctly. If a prune_old_log_events event carries a soft_limit.exceeded notification it is informational cleanup, but hard_limit.exceeded means the PCE has stopped recording new events until space is reclaimed and must be treated as critical.",
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_runbook_rec_alignment.py tests/test_event_reference_coverage.py tests/test_reporter_runbook_link.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/events/runbooks.py tests/test_runbook_rec_alignment.py
git commit -m "feat(events): add pce-capacity runbook, cover missing rec-key events, document prune limit semantics"
```

---

### Task 4: severity 對照補齊 notice / debug

**Files:**
- Modify: `src/reporter.py`（`_SEVERITY_I18N_KEYS`、`_highest_severity`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Create: `tests/test_severity_mapping.py`

**Interfaces:**
- Consumes: 無。
- Produces: `_SEVERITY_I18N_KEYS` 新增 `notice`、`debug`；`_highest_severity` 認得全部 8 級官方 severity（notice/debug 歸 info 級）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_severity_mapping.py`：

```python
"""All 8 official event severities (emerg/alert/crit/err/warning/notice/info/debug)
must map to a label and a canonical rank."""
from __future__ import annotations

from src.reporter import Reporter

OFFICIAL_SEVERITIES = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]


def test_every_official_severity_has_i18n_key():
    for sev in OFFICIAL_SEVERITIES:
        assert sev in Reporter._SEVERITY_I18N_KEYS, f"missing severity mapping: {sev}"


def test_highest_severity_ranks_all_official_values():
    assert Reporter._highest_severity([{"severity": "notice"}]) == "info"
    assert Reporter._highest_severity([{"severity": "debug"}]) == "info"
    assert Reporter._highest_severity([{"severity": "notice"}, {"severity": "crit"}]) == "critical"
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_severity_mapping.py -v`
Expected: FAIL — `notice`、`debug` 不在對照表。

- [ ] **Step 3: 實作**

`src/reporter.py` `_SEVERITY_I18N_KEYS` 追加兩行：

```python
        "notice":   "alert_sev_notice",
        "debug":    "alert_sev_debug",
```

`_highest_severity` 的 `_rank` 與 `_canonical` 各追加：

```python
        _rank = {..., 'notice': 1, 'debug': 1}
        _canonical = {..., 'notice': 'info', 'debug': 'info'}
```

（`...` 表示既有內容原樣保留，只加這兩個 key。）

`src/i18n_en.json`：

```json
"alert_sev_notice": "Notice",
"alert_sev_debug": "Debug",
```

`src/i18n_zh_TW.json`：

```json
"alert_sev_notice": "注意",
"alert_sev_debug": "除錯",
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_severity_mapping.py tests/test_reporter_severity_badge.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/reporter.py src/i18n_en.json src/i18n_zh_TW.json tests/test_severity_mapping.py
git commit -m "feat(alerts): map notice and debug severities per official event guide"
```

---

### Task 5: 告警 DLQ——派送全數失敗時下輪重送（at-least-once，最多 3 次）

**Files:**
- Modify: `src/reporter.py`（`send_alerts` 前後段）
- Create: `tests/test_alert_dlq.py`

**Interfaces:**
- Consumes: `src.state_store.update_state_file`、`persist_dispatch_results`（既有）。
- Produces: state 檔新 key `alert_dlq: list[{"buckets": {...}, "attempts": int, "first_failed_at": str}]`；`Reporter.ALERT_DLQ_MAX_ATTEMPTS = 3`；行為——`send_alerts` 開頭（非 force_test）吞入 DLQ 併入本輪 buckets，結尾若「有通道嘗試且全部失敗」把 buckets 寫回 DLQ（attempts+1），達 3 次改記 `dispatch_history` 一筆 `{"channel": "dlq", "status": "dropped"}` 並丟棄。

判準（鎖定語意，實作不得偏離）：
- `skipped`（未設定的通道）不算「嘗試」；全 skipped 不入 DLQ（否則無通道設定時無限循環）。
- 只要任一通道 `success`，整批視為已送達，不入 DLQ（單通道失敗已有 `dispatch_history` 供觀察）。
- `force_test` 不吞 DLQ、不寫 DLQ。

- [ ] **Step 1: 寫失敗測試**

`tests/test_alert_dlq.py`：

```python
"""Alert DLQ: alerts survive a full-channel outage and are retried next cycle,
dropped with a dispatch_history record after 3 attempts."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import src.reporter as reporter_mod
from src.reporter import Reporter


@pytest.fixture
def rep(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(reporter_mod, "STATE_FILE", str(state_file))
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["alerts"]["active"] = ["webhook"]
    cm.config["alerts"]["webhook_url"] = "https://hooks.example.com/x"
    r = Reporter(cm)
    return r, state_file


def _failing_send(self, reporter, subject, *, lang="en"):
    return {"channel": "webhook", "status": "failed", "target": "https://hooks.example.com/...", "error": "boom"}


def _ok_send(self, reporter, subject, *, lang="en"):
    return {"channel": "webhook", "status": "success", "target": "https://hooks.example.com/..."}


def _dlq(state_file):
    if not state_file.exists():
        return []
    return json.loads(state_file.read_text()).get("alert_dlq", [])


def test_full_failure_persists_alerts_to_dlq(rep):
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
    entries = _dlq(state_file)
    assert len(entries) == 1
    assert entries[0]["attempts"] == 1
    assert entries[0]["buckets"]["health"][0]["rule"] == "R"


def test_dlq_replayed_and_cleared_on_success(rep):
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
    r2 = Reporter(r.cm)
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok_send):
        results = r2.send_alerts()  # empty buckets + DLQ replay -> must still send
    assert results and results[0]["status"] == "success"
    assert _dlq(state_file) == []


def test_dropped_after_max_attempts(rep):
    r, state_file = rep
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _failing_send):
        r.send_alerts()
        for _ in range(Reporter.ALERT_DLQ_MAX_ATTEMPTS - 1):
            Reporter(r.cm).send_alerts()
    assert _dlq(state_file) == []
    history = json.loads(state_file.read_text()).get("dispatch_history", [])
    assert any(h["channel"] == "dlq" and h["status"] == "dropped" for h in history)


def test_all_skipped_does_not_enqueue(rep):
    r, state_file = rep
    r.cm.config["alerts"]["webhook_url"] = ""
    r.add_health_alert({"time": "t", "rule": "R", "status": "503", "details": "d"})
    r.send_alerts()
    assert _dlq(state_file) == []
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_alert_dlq.py -v`
Expected: FAIL — `alert_dlq` 不存在、`ALERT_DLQ_MAX_ATTEMPTS` 屬性錯誤。

- [ ] **Step 3: 實作 `src/reporter.py`**

類別常數與兩個 helper（放在 `send_alerts` 上方）：

```python
    ALERT_DLQ_MAX_ATTEMPTS = 3

    def _pop_alert_dlq(self) -> list[dict[str, Any]]:
        """Atomically take all pending DLQ entries from the state file."""
        popped: list[dict[str, Any]] = []

        def _take(existing: dict) -> dict:
            nonlocal popped
            popped = list(existing.get("alert_dlq", []))
            out = dict(existing)
            out["alert_dlq"] = []
            return out

        try:
            update_state_file(STATE_FILE, _take)
        except Exception as exc:
            logger.warning("Failed to read alert DLQ: {}", exc)
            return []
        return popped

    def _push_alert_dlq(self, buckets: dict[str, list], attempts: int, first_failed_at: str) -> None:
        entry = {"buckets": buckets, "attempts": attempts, "first_failed_at": first_failed_at}

        def _append(existing: dict) -> dict:
            out = dict(existing)
            out["alert_dlq"] = list(existing.get("alert_dlq", [])) + [entry]
            return out

        try:
            update_state_file(STATE_FILE, _append)
        except Exception as exc:
            logger.error("Failed to persist alert DLQ (alerts lost): {}", exc)
```

（`update_state_file` 需 import：`from src.state_store import update_state_file`；檔頭已 import `STATE_FILE` 者沿用。）

`send_alerts` 開頭（進入 early-return 判斷「之前」）插入 DLQ replay：

```python
        replayed_attempts = 0
        replayed_first_failed_at = ""
        if not force_test:
            for entry in self._pop_alert_dlq():
                buckets = entry.get("buckets", {})
                self.health_alerts.extend(buckets.get("health", []))
                self.event_alerts.extend(buckets.get("event", []))
                self.traffic_alerts.extend(buckets.get("traffic", []))
                self.metric_alerts.extend(buckets.get("metric", []))
                replayed_attempts = max(replayed_attempts, int(entry.get("attempts", 0)))
                replayed_first_failed_at = replayed_first_failed_at or entry.get("first_failed_at", "")
```

`send_alerts` 結尾、`persist_dispatch_results` 之前插入失敗判定：

```python
        attempted = [r for r in results if r.get("status") != "skipped"]
        delivered = any(r.get("status") == "success" for r in results)
        if attempted and not delivered and not force_test:
            attempts = replayed_attempts + 1
            first_failed_at = replayed_first_failed_at or format_utc(
                datetime.datetime.now(datetime.timezone.utc)
            )
            buckets = {
                "health": list(self.health_alerts),
                "event": list(self.event_alerts),
                "traffic": list(self.traffic_alerts),
                "metric": list(self.metric_alerts),
            }
            if attempts >= self.ALERT_DLQ_MAX_ATTEMPTS:
                logger.error(
                    "Alert DLQ: dropping {} alert bucket(s) after {} failed dispatch attempts",
                    sum(len(v) for v in buckets.values()), attempts,
                )
                results.append({"channel": "dlq", "status": "dropped", "target": "",
                                "error": f"dropped after {attempts} attempts"})
            else:
                logger.warning("Alert DLQ: all channels failed, queuing for retry (attempt {})", attempts)
                self._push_alert_dlq(buckets, attempts, first_failed_at)
```

（`format_utc` import 自 `src.events.poller`，reporter 若已有等價 util 則沿用既有。`raw_data` 內含原始 event dict，state 檔本就存 event 樣本，體積可接受——buckets 中每類告警的 raw_data 已在 analyzer 端限制為 5 筆事件 / 10 筆 flow。）

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_alert_dlq.py tests/test_alerts_teams.py tests/test_alerts_telegram.py tests/test_reporter_email_multipart.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/reporter.py tests/test_alert_dlq.py
git commit -m "feat(alerts): retry undelivered alerts via state-backed DLQ (at-least-once, max 3 attempts)"
```

---

### Task 6: Dead-man's switch——PCE 連續失敗自身告警

**Files:**
- Modify: `src/analyzer.py`（`run_analysis`、新方法 `_check_watchdog`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Create: `tests/test_watchdog_alert.py`

**Interfaces:**
- Consumes: `self.state["pce_stats"]["consecutive_failures"]`（`StatsTracker` 既有維護）、`reporter.add_health_alert`。
- Produces: 模組常數 `WATCHDOG_FAILURE_THRESHOLD = 3`、`WATCHDOG_COOLDOWN_MINUTES = 60`；state 新 key `watchdog_last_alert_at`；i18n key `alert_watchdog_rule`、`alert_watchdog_details`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_watchdog_alert.py`：

```python
"""Watchdog: after N consecutive PCE failures the analyzer must self-alert,
because a dead poller otherwise fails silent (no events -> no alerts)."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

from src.analyzer import Analyzer, WATCHDOG_FAILURE_THRESHOLD
from src.events.poller import format_utc


@pytest.fixture
def ana(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = []
    a = Analyzer(cm, MagicMock(), MagicMock())
    return a


def test_watchdog_fires_at_threshold(ana):
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_called_once()
    alert = ana.reporter.add_health_alert.call_args[0][0]
    assert str(WATCHDOG_FAILURE_THRESHOLD) in alert["details"]
    assert ana.state["watchdog_last_alert_at"]


def test_watchdog_quiet_below_threshold(ana):
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD - 1
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_not_called()


def test_watchdog_respects_own_cooldown(ana):
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD
    ana.state["watchdog_last_alert_at"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    )
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_not_called()


def test_watchdog_run_by_run_analysis(ana, monkeypatch):
    monkeypatch.setattr(ana, "_run_health_check", lambda: True)
    monkeypatch.setattr(ana, "_run_event_analysis", lambda: [])
    monkeypatch.setattr(ana, "_fetch_traffic", lambda: (None, [], datetime.datetime.now(datetime.timezone.utc)))
    monkeypatch.setattr(ana, "save_state", lambda: None)
    ana.state["pce_stats"]["consecutive_failures"] = WATCHDOG_FAILURE_THRESHOLD
    ana.run_analysis()
    ana.reporter.add_health_alert.assert_called_once()
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_watchdog_alert.py -v`
Expected: FAIL — `WATCHDOG_FAILURE_THRESHOLD` ImportError。

- [ ] **Step 3: 實作 `src/analyzer.py`**

模組層常數（與 `TOP_MATCHES_LIMIT` 同區）：

```python
WATCHDOG_FAILURE_THRESHOLD = 3
WATCHDOG_COOLDOWN_MINUTES = 60
```

新方法（放在 `_run_health_check` 之後）：

```python
    def _check_watchdog(self) -> None:
        """Self-alert when the PCE has been unreachable for N consecutive cycles.

        Without this, a dead poller fails silent: no events, no alerts, and the
        operator assumes all is well. Uses its own cooldown so a long outage
        produces one alert per hour instead of one per cycle.
        """
        failures = int(self.state.get("pce_stats", {}).get("consecutive_failures", 0))
        if failures < WATCHDOG_FAILURE_THRESHOLD:
            return
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last = parse_event_timestamp(self.state.get("watchdog_last_alert_at"))
        if last and (now_utc - last).total_seconds() < WATCHDOG_COOLDOWN_MINUTES * 60:
            return
        self.state["watchdog_last_alert_at"] = format_utc(now_utc)
        last_error = self.state.get("pce_stats", {}).get("last_error", "")
        self.reporter.add_health_alert({
            "time": now_utc.strftime('%Y-%m-%d %H:%M:%S'),
            "rule": t('alert_watchdog_rule'),
            "status": "critical",
            "details": t('alert_watchdog_details', count=failures, error=last_error[:120]),
        })
        logger.error(f"Watchdog: {failures} consecutive PCE failures — self-alert dispatched")
```

`run_analysis` 在 `self._dispatch_alerts(triggers, tr_rules)` 之後、`self.save_state()` 之前加一行：

```python
        self._check_watchdog()
```

i18n（en）：

```json
"alert_watchdog_rule": "PCE connectivity watchdog",
"alert_watchdog_details": "PCE polling has failed {count} consecutive cycles; event and traffic alerting is blind. Last error: {error}",
```

i18n（zh_TW）：

```json
"alert_watchdog_rule": "PCE 連線看門狗",
"alert_watchdog_details": "PCE 輪詢已連續失敗 {count} 個週期，事件與流量告警目前處於盲區。最近錯誤：{error}",
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_watchdog_alert.py tests/test_analyzer.py tests/test_analyzer_decomposition.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py src/i18n_en.json src/i18n_zh_TW.json tests/test_watchdog_alert.py
git commit -m "feat(monitor): dead-man's switch alert after consecutive PCE polling failures"
```

---

### Task 7: 健檢解析 `/health` body status（消除 degraded 假陰性）

**Files:**
- Modify: `src/api_client.py`（新增 module-level helper `health_status_from_body`）
- Modify: `src/analyzer.py`（`_run_health_check`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Create: `tests/test_health_body_parsing.py`

**Interfaces:**
- Consumes: `ApiClient.check_health()`（回傳 `(status_code, body_text)`，不變）。
- Produces: `health_status_from_body(text: str) -> str`（回傳小寫 status 字串，無法解析回 `""`）；`_run_health_check` 在 HTTP 200 且 body status ∈ {warning, degraded, error, critical} 時也觸發健檢告警。

原廠依據（背景結論第 4 點）：`/api/v2/health` 只要能回報就回 200；degraded 資訊在 body 的 `status` 欄位。

- [ ] **Step 1: 寫失敗測試**

`tests/test_health_body_parsing.py`：

```python
"""HTTP 200 from /api/v2/health does NOT mean healthy: parse body status."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.api_client import health_status_from_body


def test_parses_top_level_status_dict():
    assert health_status_from_body('{"status": "normal"}') == "normal"
    assert health_status_from_body('{"status": "WARNING"}') == "warning"


def test_parses_node_list_and_picks_worst():
    body = '[{"status": "normal"}, {"status": "critical"}, {"status": "warning"}]'
    assert health_status_from_body(body) == "critical"


def test_unparseable_body_returns_empty():
    assert health_status_from_body("not json") == ""
    assert health_status_from_body("") == ""
    assert health_status_from_body("[1, 2]") == ""


def test_degraded_200_fires_health_alert(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = [{
        "id": 1, "name": "PCE Health", "type": "system",
        "filter_value": "pce_health", "threshold_count": 1, "threshold_type": "count",
    }]
    api = MagicMock()
    api.check_health.return_value = (200, '{"status": "warning"}')
    rep = MagicMock()
    ana = Analyzer(cm, api, rep)
    ana._run_health_check()
    rep.add_health_alert.assert_called_once()
    alert = rep.add_health_alert.call_args[0][0]
    assert "warning" in alert["details"].lower()
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_health_body_parsing.py -v`
Expected: FAIL — `health_status_from_body` ImportError。

- [ ] **Step 3: 實作**

`src/api_client.py`（module level，`check_health` 附近）：

```python
_HEALTH_BAD_ORDER = ("critical", "error", "degraded", "warning")


def health_status_from_body(text: str) -> str:
    """Extract the PCE health status string from a /api/v2/health body.

    The endpoint returns HTTP 200 whenever it can report at all, so the body
    status is the only truthful health signal. Returns '' when unparseable —
    callers must treat '' as unknown, never as healthy.
    """
    import json as _json
    try:
        data = _json.loads(text)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("status") or "").strip().lower()
    if isinstance(data, list):
        statuses = [
            str(node.get("status") or "").strip().lower()
            for node in data if isinstance(node, dict)
        ]
        statuses = [s for s in statuses if s]
        for bad in _HEALTH_BAD_ORDER:
            if bad in statuses:
                return bad
        return statuses[0] if statuses else ""
    return ""
```

`src/analyzer.py` `_run_health_check` 的 `else:`（`h_status == 200`）分支改為：

```python
        else:
            from src.api_client import health_status_from_body
            body_status = health_status_from_body(h_msg)
            if body_status in {"warning", "degraded", "error", "critical"}:
                logger.warning(f"PCE health degraded: status={body_status}")
                self.stats.record_pce_error("health", f"degraded: status={body_status}", status=h_status)
                for rule in pce_health_rules:
                    if self._check_cooldown(rule):
                        self.reporter.add_health_alert({
                            "time": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                            "rule": rule["name"],
                            "status": body_status,
                            "details": t('health_degraded_details', status=body_status),
                        })
            else:
                logger.info(t('status_ok'))
                logger.info("PCE health check OK.")
                self.stats.record_pce_success("health", status=h_status, message=h_msg[:120])
```

i18n（en）：

```json
"health_degraded_details": "PCE /health returned HTTP 200 but reports status={status}. Check node health, database replication lag, and service status in the PCE web console.",
```

i18n（zh_TW）：

```json
"health_degraded_details": "PCE /health 回傳 HTTP 200，但 body status={status}。請檢查 PCE 主控台的節點健康、資料庫複寫延遲與服務狀態。",
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_health_body_parsing.py tests/test_analyzer.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/api_client.py src/analyzer.py src/i18n_en.json src/i18n_zh_TW.json tests/test_health_body_parsing.py
git commit -m "feat(monitor): parse /health body status so degraded-but-200 PCE states alert"
```

---

### Task 8: 事件溢出 meta-alert

**Files:**
- Modify: `src/analyzer.py`（`_run_event_analysis`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Create: `tests/test_overflow_meta_alert.py`

**Interfaces:**
- Consumes: `_fetch_event_batch` 既有的 `event_batch.overflow_risk` 與 `self.state["event_overflow"]`。
- Produces: state 新 key `overflow_last_alert_at`（60 分鐘自身冷卻）；i18n key `alert_overflow_rule`、`alert_overflow_details`。

原廠依據（背景結論第 3 點）：同步 events API 溢出時只回最新事件，最舊事件永久漏失——這必須讓操作者知道，而不是只留 log。

- [ ] **Step 1: 寫失敗測試**

`tests/test_overflow_meta_alert.py`：

```python
"""Overflow means the oldest events in the window were silently lost (the
sync events API returns only the newest max_results rows) — must self-alert."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

from src.events.poller import EventBatch, format_utc


@pytest.fixture
def ana(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = []
    a = Analyzer(cm, MagicMock(), MagicMock())
    return a


def _overflow_batch():
    return EventBatch(
        events=[], next_watermark="2026-07-04T00:10:00Z",
        query_since="2026-07-04T00:00:00Z", query_until="2026-07-04T00:10:00Z",
        raw_count=5000, overflow_risk=True, seen_events={},
    )


def test_overflow_fires_meta_alert(ana, monkeypatch):
    monkeypatch.setattr(ana, "_fetch_event_batch", lambda: _overflow_batch())
    ana.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000,
                                   "query_since": "2026-07-04T00:00:00Z",
                                   "query_until": "2026-07-04T00:10:00Z",
                                   "detected_at": "2026-07-04T00:10:00Z"}
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_called_once()


def test_overflow_alert_respects_cooldown(ana):
    ana.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000}
    ana.state["overflow_last_alert_at"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    )
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_not_called()


def test_no_overflow_no_alert(ana):
    ana.state["event_overflow"] = {}
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_not_called()
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_overflow_meta_alert.py -v`
Expected: FAIL — `_maybe_alert_overflow` AttributeError。

- [ ] **Step 3: 實作 `src/analyzer.py`**

常數（與 watchdog 常數同區）：

```python
OVERFLOW_ALERT_COOLDOWN_MINUTES = 60
```

新方法（放在 `_check_watchdog` 之後）：

```python
    def _maybe_alert_overflow(self) -> None:
        """Meta-alert when event polling hit max_results: oldest events were lost."""
        overflow = self.state.get("event_overflow") or {}
        if not overflow:
            return
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last = parse_event_timestamp(self.state.get("overflow_last_alert_at"))
        if last and (now_utc - last).total_seconds() < OVERFLOW_ALERT_COOLDOWN_MINUTES * 60:
            return
        self.state["overflow_last_alert_at"] = format_utc(now_utc)
        self.reporter.add_health_alert({
            "time": now_utc.strftime('%Y-%m-%d %H:%M:%S'),
            "rule": t('alert_overflow_rule'),
            "status": "warning",
            "details": t('alert_overflow_details',
                         raw=overflow.get("raw_count", "?"),
                         cap=overflow.get("max_results", "?"),
                         since=overflow.get("query_since", "?"),
                         until=overflow.get("query_until", "?")),
        })
        logger.warning("Event overflow meta-alert dispatched")
```

`_run_event_analysis` 中 legacy 路徑成功取得 events 後（`events, event_batch = self._legacy_event_pull()` 之後）加：

```python
                self._maybe_alert_overflow()
```

i18n（en）：

```json
"alert_overflow_rule": "Event polling overflow",
"alert_overflow_details": "Event query returned {raw} rows (cap {cap}) between {since} and {until}. The PCE sync events API returns only the newest rows, so older events in this window were permanently missed. Consider narrowing the poll interval or reviewing burst sources.",
```

i18n（zh_TW）：

```json
"alert_overflow_rule": "事件輪詢溢出",
"alert_overflow_details": "事件查詢於 {since} 至 {until} 間回傳 {raw} 筆（上限 {cap}）。PCE 同步事件 API 只回傳最新的事件，此視窗中較舊的事件已永久漏失。請縮短輪詢間隔或調查事件暴增來源。",
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_overflow_meta_alert.py tests/test_event_monitoring.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py src/i18n_en.json src/i18n_zh_TW.json tests/test_overflow_meta_alert.py
git commit -m "feat(monitor): meta-alert when event polling overflows max_results"
```

---

### Task 9: LINE digest 明確截斷 footer

**Files:**
- Modify: `src/reporter.py`（`_build_line_message` 四個 section 迴圈）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Create: `tests/test_line_truncation_footer.py`

**Interfaces:**
- Consumes: 無。
- Produces: LINE digest 每節超過顯示上限（現行 `[:2]`）時，節末追加一行 `t('line_section_more', more=N)`。專案 CLAUDE.md 規則：截斷必須明確，不可無聲。

- [ ] **Step 1: 寫失敗測試**

`tests/test_line_truncation_footer.py`：

```python
"""LINE digest sections cap at 2 entries; the cut must be announced, not silent."""
from __future__ import annotations

import pytest

from src.reporter import Reporter


@pytest.fixture
def rep():
    from src.config import ConfigManager
    return Reporter(ConfigManager())


def _mk_event(i):
    return {"time": "2026-07-04 12:00", "rule": f"rule-{i}", "severity": "warning",
            "count": 1, "source": "s", "target": "t", "resource_type": "",
            "resource_name": "", "action": "", "raw_data": [], "parsed_data": []}


def test_footer_present_when_section_truncated(rep):
    for i in range(5):
        rep.add_event_alert(_mk_event(i))
    msg = rep._build_line_message("subj", lang="en")
    assert "3 more" in msg  # 5 alerts, 2 shown, 3 truncated


def test_no_footer_when_section_fits(rep):
    rep.add_event_alert(_mk_event(0))
    msg = rep._build_line_message("subj", lang="en")
    assert "more" not in msg.split("rule-0")[-1][:40]
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_line_truncation_footer.py -v`
Expected: FAIL — footer 不存在。

- [ ] **Step 3: 實作**

`src/reporter.py` `_build_line_message`：四個 section（health / event / traffic / metric）在各自 `for idx, alert in enumerate(bucket[:2], ...)` 迴圈結束後加（以 event 節為例，其餘三節同型）：

```python
            if len(self.event_alerts) > 2:
                event_section_lines.append(t('line_section_more', more=len(self.event_alerts) - 2))
```

i18n（en）：

```json
"line_section_more": "... and {more} more entries (see mail or dashboard for full list)",
```

i18n（zh_TW）：

```json
"line_section_more": "……還有 {more} 筆（完整列表請見郵件或儀表板）",
```

- [ ] **Step 4: 跑測試**

Run: `python -m pytest tests/test_line_truncation_footer.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/reporter.py src/i18n_en.json src/i18n_zh_TW.json tests/test_line_truncation_footer.py
git commit -m "feat(alerts): announce truncation in LINE digest sections"
```

---

### Task 10: 端到端樣本驗證與收尾

**Files:**
- Test only（不改產品碼；若發現截斷/溢出問題，回到對應 task 修）

**Interfaces:**
- Consumes: Tasks 1–9 全部產出。

- [ ] **Step 1: 全套測試**

Run: `python -m pytest tests/ -q`
Expected: 全 PASS，無 skip 異常增加。

- [ ] **Step 2: 樣本資料實跑各通道輸出（專案 CLAUDE.md 截斷檢查規則）**

```bash
python3 - <<'EOF'
from src.config import ConfigManager
from src.reporter import Reporter

cm = ConfigManager()
rep = Reporter(cm)
# 樣本：塞爆每一類（含超長欄位）驗證截斷行為
long_name = "x" * 300
for i in range(6):
    rep.add_event_alert({"time": "2026-07-04T03:00:00Z", "rule": f"Capacity watch {i}",
        "severity": "err", "count": 3, "source": f"admin @ host-{i} | 10.0.0.{i}",
        "target": long_name, "resource_type": "sec_policy", "resource_name": long_name,
        "action": "PUT /sec_policy", "raw_data": [{"event_type": "system_task.prune_old_log_events"}],
        "parsed_data": []})
rep.add_health_alert({"time": "2026-07-04 03:00:00", "rule": "PCE connectivity watchdog",
    "status": "critical", "details": "PCE polling has failed 3 consecutive cycles; " + long_name})
rep.add_traffic_alert({"rule": "Blocked burst", "count": "999", "criteria": "threshold >= 100",
    "details": "a -> b [443]: 999", "raw_data": []})
rep.add_metric_alert({"rule": "BW spike", "count": "123.45", "criteria": "threshold > 100",
    "details": "", "raw_data": []})

for lang in ("en", "zh_TW"):
    line = rep._build_line_message("subject", lang=lang)
    tg = rep._build_telegram_message("subject", lang=lang)
    mail = rep._build_mail_html("subject")
    print(f"--- {lang} LINE ({len(line)} chars) ---"); print(line[:800])
    assert len(tg) <= 4096, f"telegram over limit: {len(tg)}"
    assert "line_section_more" not in line, "raw i18n key leaked"
    assert "還有" in line or "more entries" in line, "truncation footer missing"
    print(f"telegram len={len(tg)} mail len={len(mail)} OK")
EOF
```

Expected: 兩種語言輸出皆列印成功、無 assert 失敗、footer 出現、無 i18n key 裸露。逐段目視檢查輸出無溢出／破版，把輸出貼進交付回報。

- [ ] **Step 3: 型別與 lint**

Run: `python -m mypy src/events/ src/alerts/ 2>&1 | tail -5 && python -m ruff check src/ tests/ 2>&1 | tail -5`
Expected: 無新增錯誤（與 main 基線相同）。

- [ ] **Step 4: Commit（若 Step 2/3 有小修）**

```bash
git add -A
git commit -m "test(alerts): end-to-end sample verification for channel outputs"
```

---

## 明確不做（Out of Scope，含理由）

- **cooldown 記錄時點不動**：`_check_cooldown` 仍在派送前寫 `alert_history`。Task 5 的 DLQ 已把「全通道失敗」轉為 at-least-once，把 cooldown 延後到派送成功需要重構 analyzer/reporter 邊界，風險大於效益。
- **溢出視窗切分重查 / async GET collections**：legacy 輪詢路徑已標 deprecated（`_legacy_event_pull`），主要路徑是 pce_cache subscriber。僅加 meta-alert（Task 8）；若未來 legacy 路徑要長期保留再議。
- **通道並行發送**：現行序列發送的延遲上限（約 30s + 3×10s）可接受，不引入 thread pool。
- **syslog forwarding**：原廠建議的事件外送主機制，屬 SIEM 模組既有方向，不在本計畫。
- **官方列表 fixture 的自動更新**：fixture 是一次性人工查證產物（PCE 24.2 版 Event Guide）；PCE 升版時人工重跑 Task 1 Step 1 即可。

## Self-Review 檢核結果

- 健檢報告六項可靠性發現 → Task 5（DLQ）、Task 6（watchdog）、Task 7（health body）、Task 8（overflow）、Task 9（LINE footer）；「LINE cooldown 丟棄」由 Task 5 DLQ 吸收（全通道失敗才重送；單通道 cooldown 失敗有 dispatch_history 可觀察，符合原設計意圖）。
- 盤點四項內容發現 → Task 1（catalog 分層 + 5 筆缺漏 + typo 處置）、Task 2（notification_type，容量告警的正確機制）、Task 3（runbook 容量類別 + REC 對齊 + prune 語意）、Task 4（severity 8 級補齊）。
- 型別一致性：`VENDOR_DOCUMENTED_EVENT_TYPES` / `OBSERVED_EXTENSION_EVENT_TYPES` / `is_vendor_documented` / `notification_types` / `_maybe_alert_overflow` / `_check_watchdog` / `ALERT_DLQ_MAX_ATTEMPTS` 名稱在各 task 引用一致。
- 無 placeholder：每個 code step 均附完整程式碼與預期輸出。
