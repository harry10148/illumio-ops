# App Summary Server-Side App Scoping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make App Summary push its app scope to the PCE (Explorer query `src_labels`/`dst_labels` + `query_operator="or"`) so it fetches only the app's flows instead of the whole estate.

**Architecture:** Single change in the `AppSummaryReport` facade: `build()` constructs a native label-filter dict and passes it through `_fetch_estate_df` → `fetch_traffic_df(filters=...)`. The existing `traffic_query` already maps these to `sources.include`/`destinations.include` + `sources_destinations_query_op`. `filter_app_flows` stays as a defensive post-filter safety net.

**Tech Stack:** Python / pandas / pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-app-summary-serverside-scope-design.md`

**執行環境：** worktree + `ln -sfn /home/harry/rd/illumio-ops/venv venv`. 基線 `./venv/bin/python -m pytest tests/test_app_summary_report.py -q`（注意全套有已知 posture snapshot 污染 quirk）。

---

## 已驗證事實（grounding）

| 事實 | 出處 |
|------|------|
| `ReportGenerator.fetch_traffic_df(start_date, end_date, filters=None)` 接受 filters 並轉給 `_fetch_traffic` → 查詢 | report_generator.py |
| native filters：`src_labels`/`dst_labels`（list of `key=value` 字串 → label hrefs → sources/destinations.include）、`query_operator`（→ `sources_destinations_query_op` "or"/"and"） | api/traffic_query.py:32,34,56 |
| GUI traffic report 的 filters 格式：`{'src_labels': [..], 'dst_labels': [..], 'policy_decisions': .., 'ex_*': ..}`，值為 `key=value` 字串如 `role=Web` | gui/routes/reports.py:327-340 |
| 目前 `_fetch_estate_df(start_date, end_date)` 不帶 filters（抓全量）；`build()` 第一行 `df = self._fetch_estate_df(...)` 然後 `scoped = filter_app_flows(df, app, env)` | app_summary_report.py |
| 單一查詢用 `sources_destinations_query_op="or"` + app label 同時放 sources.include 與 destinations.include = 「app 為 src 或 dst」 | NotebookLM Illumio API guide |

## 檔案結構

```
src/report/app_summary_report.py     # _fetch_estate_df 加 filters 參數；build() 組 scope filters
tests/test_app_summary_report.py     # 新測試：build() 傳正確 filters；既有測試仍綠
```

---

### Task 1: build() pushes app scope to the PCE via native label filters

**Files:**
- Modify: `src/report/app_summary_report.py`
- Test: `tests/test_app_summary_report.py`

- [ ] **Step 1: 寫失敗測試** — 加到 `tests/test_app_summary_report.py`（驗證 `_fetch_estate_df` 收到的 filters；用 spy）：

```python
def test_build_pushes_app_scope_filters_to_fetch():
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from src.report.app_summary_report import AppSummaryReport
    captured = {}
    df = pd.DataFrame([_row_decision("Web", "DB", "10.0.0.5", 3306, "allowed", 5)])
    api = MagicMock(); api.fetch_managed_workloads.return_value = []
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)

    def _spy(start_date=None, end_date=None, filters=None):
        captured["filters"] = filters
        return df
    with patch.object(rep, "_fetch_estate_df", side_effect=_spy):
        rep.build(app="DB", env="Prod", lang="en")
    f = captured["filters"]
    assert f is not None
    assert f["src_labels"] == ["app=DB", "env=Prod"]
    assert f["dst_labels"] == ["app=DB", "env=Prod"]
    assert f["query_operator"] == "or"


def test_build_scope_filters_app_only_when_no_env():
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from src.report.app_summary_report import AppSummaryReport
    captured = {}
    df = pd.DataFrame([_row_decision("Web", "DB", "10.0.0.5", 3306, "allowed", 5)])
    api = MagicMock(); api.fetch_managed_workloads.return_value = []
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)
    def _spy(start_date=None, end_date=None, filters=None):
        captured["filters"] = filters; return df
    with patch.object(rep, "_fetch_estate_df", side_effect=_spy):
        rep.build(app="DB", lang="en")
    assert captured["filters"]["src_labels"] == ["app=DB"]
    assert captured["filters"]["query_operator"] == "or"
```

（`_row_decision` 是既有 helper — 沿用。spy 取代 `_fetch_estate_df` 以攔截 filters，回固定 df 讓 build 後續正常跑。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_app_summary_report.py -k "scope_filters" -q`
Expected: FAIL（`_fetch_estate_df` 目前不接受/不收 filters，或 build 沒傳）

- [ ] **Step 3: 實作** —

(a) `_fetch_estate_df` 加 `filters` 參數並轉傳：
```python
    def _fetch_estate_df(self, start_date=None, end_date=None, filters=None):
        """Fetch the (optionally PCE-scoped) traffic DataFrame via ReportGenerator."""
        from src.report.report_generator import ReportGenerator
        gen = ReportGenerator(config_manager=self.cm, api_client=self.api,
                              config_dir=self._config_dir, cache_reader=self._cache)
        return gen.fetch_traffic_df(start_date=start_date, end_date=end_date, filters=filters)
```

(b) `build()` 第一行改為組 scope filters 並傳入（保留其後的 `filter_app_flows` 安全網不動）：
```python
        labels = [f"app={app}"] + ([f"env={env}"] if env else [])
        scope_filters = {"src_labels": labels, "dst_labels": labels, "query_operator": "or"}
        df = self._fetch_estate_df(start_date=start_date, end_date=end_date, filters=scope_filters)
        scoped = filter_app_flows(df, app, env)
```

不要動 `filter_app_flows(df, app, env)`（安全網）、mod01/02/03、policy_impact、enforcement、空狀態判斷。不要加會丟棄 decision 的 `policy_decisions` filter（policy impact 需要 allowed+pb+blocked）。

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_app_summary_report.py -q`
Expected: PASS（新 2 測試 + 既有全部）。既有測試用 `patch.object(rep,"_fetch_estate_df", return_value=df)`，新增 `filters` 參數有預設值故不破壞既有 patch（它們的 side effect/return 不在意參數）。若有既有測試以 positional 呼叫 `_fetch_estate_df` 而受影響，更新為 keyword（預期不需要）。

- [ ] **Step 5: 全域驗證**

Run: `./venv/bin/python -m pytest -k "app_summary or app_baseline" -q | tail -3`
Expected: 無新失敗。

- [ ] **Step 6: Commit**

```bash
git add src/report/app_summary_report.py tests/test_app_summary_report.py
git commit -m "perf(report): App Summary scopes traffic to the app server-side (src/dst label + OR), not full-estate fetch"
```

---

## 完成後整體驗證（部署後在測試機，健康 PCE）

```bash
./venv/bin/python -m pytest tests/ -q          # 無新失敗（posture snapshot quirk 隔離下通過）
# lab e2e（與優化前對照）：
#   time ./venv/bin/python illumio-ops.py report app-summary --app K8sNode --days 14 --output-dir /tmp/x
#   → 比優化前（全量 ~240k）顯著更快；報表內容一致（Policy Impact 覆蓋率/would-block、Enforcement enforced/total、inbound/outbound 節皆在）；
#   → DEBUG/log 確認抓取列數 ≈ 該 app 的流量（非全 estate）。
# 對照組：先前 K8sNode 全量版 coverage 24.0% / would-block 1403 / 3-of-3 enforced；優化後數字應一致（或同數量級，因 server-side OR 與 pandas OR 等價）。
```

## Self-Review 紀錄
- Spec 覆蓋：server-side scope filters（Task 1 Step 3b）、_fetch_estate_df filters 轉傳（Step 3a）、post-filter 安全網保留（不動）、policy_decisions 不丟棄（註明）。
- 無 placeholder：filters 格式具體（`["app=X","env=Y"]` + `query_operator:"or"`），出處在 grounding 表。
- env 處理：`["app=X","env=Y"]` 放同一 list；實作者依 traffic_query resolver 確認此為 AND（同 include set）；即使 resolver 對 list 採別的語意，`filter_app_flows` 安全網仍保證 env 正確。
- 降級：PCE 不支援 native label filter 時 traffic_query 自動走 fallback（抓取 + Python 過濾），安全網再 scope，故不會壞，只是退回舊負載。
- 風險最小：單檔變更 + 安全網保留，行為對既有測試相容（filters 預設 None）。
```
