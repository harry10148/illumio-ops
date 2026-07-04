# Rule Hit Count Report Implementation Plan（v2 — 原生數據增強器）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `rule_hit_count` 報表型別——PCE 內建 Rule Hit Count 報表的增強器：偵測原生功能啟用狀態、必要時引導啟用（含 provision 警告）、自動從 reports API 拉原生數據或匯入原生 CSV，join 完整規則明細後輸出。

**Architecture:** 依 `docs/superpowers/specs/2026-07-05-rule-hit-count-report-design.md`。新增 `EnablementChecker`（偵測+啟用）與 `ReportsApi`（原生報表拉取，掛 ApiClient facade）；`RuleHitCountGenerator` 只消費原生數據（native 拉取與 CSV 上傳共用同一套解析器），join `build_rule_baseline` 明細；**不做**流量近似計數（那是 Policy Usage 的職責）。不可用時只提示，絕不自動產。

**Tech Stack:** Python 3.12 + pandas、requests（經 ApiClient `_api_get/_api_put/_api_post/_request`）、Flask、click + questionary、既有 report_css/cover_page/CsvExporter、unittest + pytest。

## Global Constraints

- 所有 commit message 用英文 conventional commits，不放 emoji。
- 報表長欄位截斷規則（CLAUDE.md）：consumers/providers/services/description 超過 160 字元的儲存格，HTML 顯示前 159 字 + `…`，完整值放 `title` 屬性；CSV 匯出永遠完整值；不可無聲截斷。
- 交付前用實際樣本資料跑完整輸出，逐頁檢查截斷與溢出（Task 12）。
- 原廠事實（NotebookLM 查證 2026-07-05）：版本門檻 SaaS PCE ≥ 24.2.0／地端 ≥ 23.5.10／VEN ≥ 23.2.30；計數僅計 Active 規則、保留 90 天、規則最佳化可能高估、每 flow 最多歸因 100 條——語意注記必須印在報表頂部。
- 排程情境：未啟用 → skip + warning log，絕不詢問、絕不自動啟用、絕不改產 Policy Usage。
- 啟用操作永遠需人為確認（provision 是生產 policy 寫入）；GUI 啟用對話框 v1 僅支援全部 VEN。
- v1 非目標：xlsx、trend snapshot、dashboard summary、fallback 自動產 Policy Usage、從 ingested flows 計算、清理門檻設定 UI。
- 執行時依 superpowers:using-git-worktrees 在隔離 worktree 進行；subagent dispatch prompt 須明文驗證 pwd/分支。

## 檔案結構

| 檔案 | 動作 | 職責 |
|---|---|---|
| `src/report/policy_usage_generator.py` | 修改 | `_build_baseline` 抽成模組層 `build_rule_baseline()`（行為不變） |
| `src/report/rule_hit_count_enablement.py` | 新建 | `EnablementStatus`、`check_enablement()`、`enable_rule_hit_count()`、例外 |
| `src/api/reports.py` | 新建 | `ReportsApi.pull_rule_hit_count_report()`（submit→poll→download CSV） |
| `src/api_client.py` | 修改 | facade 掛 `self._reports` + `pull_rule_hit_count_report` 委派 |
| `src/report/rule_hit_count_generator.py` | 新建 | `RuleHitCountResult` + `RuleHitCountGenerator`（native/csv、enrichment、export） |
| `src/report/exporters/rule_hit_count_html_exporter.py` | 新建 | HTML exporter（KPI + 三節 + 語意注記 + 截斷） |
| `src/report_scheduler.py` | 修改 | dispatch 分支（:414 `else` 前）+ `_REPORT_PREFIXES`（:591） |
| `src/cli/report.py` | 修改 | helper + `rule-hit-count` 指令 + 啟用精靈 `_run_rhc_enablement_wizard` |
| `src/gui/routes/reports.py` | 修改 | enablement GET / enable POST / generate POST 三個 route |
| `src/templates/index.html` | 修改 | rcard 卡片（policy_usage 卡 :1373-1387 後）+ 排程下拉選項（:1526 後） |
| `src/static/js/dashboard.js` | 修改 | typeLabels ×2、modal meta/分支、`_doGenerateRuleHitCount`（含啟用確認） |
| `src/i18n_en.json`、`src/i18n/data/zh_explicit.json` | 修改 | `rpt_rhc_*` 與 `gui_*rhc*` keys |
| `tests/test_rule_hit_count_enablement.py` | 新建 | 三態偵測、404 unsupported、啟用步驟順序與半途失敗 |
| `tests/test_api_reports_pull.py` | 新建 | submit→poll→download 狀態機、逾時、失敗 |
| `tests/test_rule_hit_count_generator.py` | 新建 | baseline、CSV 解析、enrichment、native 模式、export |
| `tests/test_rule_hit_count_html_exporter.py` | 新建 | 渲染、三節、語意注記、截斷 + title |
| `tests/test_rule_hit_count_scheduler_dispatch.py` | 新建 | dispatch、NotEnabled skip、prefix |
| `tests/test_cli_report_rule_hit_count.py` | 新建 | 指令註冊/轉呼叫/NotEnabled 出口 |
| `tests/test_gui_rule_hit_count_generate.py` | 新建 | 三 route 行為 |

---

### Task 1: 抽出 build_rule_baseline（Policy Usage 重構，行為不變）

**Files:**
- Modify: `src/report/policy_usage_generator.py:378-421`（`_build_baseline`）
- Test: `tests/test_rule_hit_count_generator.py`（新建）

**Interfaces:**
- Produces: `build_rule_baseline(rulesets: list) -> tuple[list, dict]`（模組層函式；回傳 `(flat_rules, ruleset_map)`，每條 rule dict 附 `_ruleset_name/_ruleset_href/_ruleset_scopes/_ruleset_id/_rule_id/_rule_no/_rule_type`）。Task 5 的 enrichment 依賴此函式。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_rule_hit_count_generator.py`：

```python
"""Tests for the Rule Hit Count report generator (and the shared rule baseline)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.report.policy_usage_generator import build_rule_baseline


def _sample_rulesets():
    return [{
        "href": "/orgs/1/sec_policy/draft/rule_sets/10",
        "name": "RS-A",
        "scopes": [[{"label": {"href": "/orgs/1/labels/1"}}]],
        "rules": [
            {"href": "/orgs/1/sec_policy/draft/rule_sets/10/sec_rules/100",
             "enabled": True, "description": "allow web",
             "consumers": [{"actors": "ams"}],
             "providers": [{"label": {"href": "/orgs/1/labels/2"}}],
             "ingress_services": [{"port": 443, "proto": 6}]},
        ],
        "deny_rules": [
            {"href": "/orgs/1/sec_policy/draft/rule_sets/10/deny_rules/200",
             "enabled": True, "override": True},
        ],
    }]


class TestBuildRuleBaseline(unittest.TestCase):
    def test_flattens_and_annotates(self):
        flat_rules, ruleset_map = build_rule_baseline(_sample_rulesets())
        self.assertEqual(len(flat_rules), 2)
        self.assertEqual(ruleset_map["/orgs/1/sec_policy/draft/rule_sets/10"], "RS-A")
        allow, deny = flat_rules
        self.assertEqual(allow["_rule_type"], "Allow")
        self.assertEqual(allow["_ruleset_name"], "RS-A")
        self.assertEqual(allow["_rule_no"], 1)
        self.assertEqual(allow["_rule_id"], "100")
        self.assertEqual(deny["_rule_type"], "Override Deny")
        self.assertEqual(deny["_rule_no"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_generator.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_rule_baseline'`

- [ ] **Step 3: 最小實作**

在 `src/report/policy_usage_generator.py`，把 `_build_baseline`（:378）的方法本體搬到模組層（放在 `PolicyUsageResult` 之後、class 之前）：

```python
def build_rule_baseline(rulesets: list) -> tuple:
    """Flatten all rulesets into a list of rules; build a ruleset_map.

    Each rule dict is augmented with:
    - _ruleset_name, _ruleset_href: for display
    - _ruleset_scopes: first scope array from the parent ruleset (for query building)

    Shared by the Policy Usage and Rule Hit Count reports.
    Returns (flat_rules, ruleset_map).
    """
    flat_rules = []
    ruleset_map = {}

    for rs in rulesets:
        rs_href = rs.get('href', '')
        rs_name = rs.get('name', rs_href)
        ruleset_map[rs_href] = rs_name

        # Extract the first scope (most rulesets have exactly one scope)
        scopes = rs.get('scopes', [])
        first_scope = scopes[0] if scopes else []

        rs_id = rs_href.split('/')[-1] if rs_href else ''

        # Collect rules by type; annotate each with _rule_type
        typed_rules = []
        for r in rs.get('sec_rules', []) + rs.get('rules', []):
            typed_rules.append((r, 'Allow'))
        for r in rs.get('deny_rules', []):
            rule_type = 'Override Deny' if r.get('override') else 'Deny'
            typed_rules.append((r, rule_type))

        for rule_no, (rule, rule_type) in enumerate(typed_rules, 1):
            rule_href = rule.get('href', '')
            rule_copy = dict(rule)
            rule_copy['_ruleset_href'] = rs_href
            rule_copy['_ruleset_name'] = rs_name
            rule_copy['_ruleset_scopes'] = first_scope
            rule_copy['_ruleset_id'] = rs_id
            rule_copy['_rule_id'] = rule_href.split('/')[-1] if rule_href else ''
            rule_copy['_rule_no'] = rule_no
            rule_copy['_rule_type'] = rule_type
            flat_rules.append(rule_copy)

    return flat_rules, ruleset_map
```

原方法縮減為委派：

```python
    def _build_baseline(self, rulesets: list) -> tuple:
        """Delegates to the module-level build_rule_baseline (shared helper)."""
        return build_rule_baseline(rulesets)
```

- [ ] **Step 4: 跑測試確認通過 + 既有測試不破**

Run: `python -m pytest tests/test_rule_hit_count_generator.py tests/test_policy_usage_report.py tests/test_xlsx_content_policy_usage.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/policy_usage_generator.py tests/test_rule_hit_count_generator.py
git commit -m "refactor(report): extract build_rule_baseline as shared module-level helper"
```

---

### Task 2: EnablementChecker（偵測 + 啟用）

**Files:**
- Create: `src/report/rule_hit_count_enablement.py`
- Test: `tests/test_rule_hit_count_enablement.py`

**Interfaces:**
- Consumes: `api._api_get(endpoint) -> (status, json|None)`（`src/api_client.py:735`）、`api._api_put(endpoint, payload) -> status`（:749）、`api._api_post(endpoint, payload) -> (status, json|None)`（:759）、`api.api_cfg['org_id']`
- Produces（後續 Task 5/9/10/11 依賴）:
  - `EnablementStatus`（dataclass：`state: str`（`enabled|partial|disabled|unsupported`）、`pce_report_enabled: bool`、`ven_scopes_enabled: bool`、`detail: str`）
  - `check_enablement(api) -> EnablementStatus`（PCE 連線失敗 raise `ConnectionError`）
  - `enable_rule_hit_count(api, scopes: list | None = None) -> list[str]`（回傳完成步驟；失敗 raise `EnablementError`，帶 `steps_done`）
  - `RuleHitCountNotEnabled(RuntimeError)`（帶 `.status: EnablementStatus`）
  - `EnablementError(RuntimeError)`（帶 `.steps_done: list[str]`）

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_rule_hit_count_enablement.py`：

```python
"""Enablement detection + enable flow for the native Rule Hit Count feature."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.report.rule_hit_count_enablement import (
    EnablementError,
    EnablementStatus,
    RuleHitCountNotEnabled,
    check_enablement,
    enable_rule_hit_count,
)


def _api(tpl=(200, {"enabled": True}), fw=(200, {"rule_hit_count_enabled_scopes": [[]]})):
    api = MagicMock()
    api.api_cfg = {"org_id": 1}

    def _get(endpoint, timeout=15):
        if "report_templates" in endpoint:
            return tpl
        if "firewall_settings" in endpoint:
            return fw
        raise AssertionError(f"unexpected GET {endpoint}")

    api._api_get.side_effect = _get
    return api


class TestCheckEnablement(unittest.TestCase):
    def test_enabled_both_sides(self):
        st = check_enablement(_api())
        self.assertEqual(st.state, "enabled")
        self.assertTrue(st.pce_report_enabled)
        self.assertTrue(st.ven_scopes_enabled)

    def test_disabled_both_sides(self):
        st = check_enablement(_api(tpl=(200, {"enabled": False}),
                                   fw=(200, {"rule_hit_count_enabled_scopes": []})))
        self.assertEqual(st.state, "disabled")

    def test_partial_pce_only(self):
        st = check_enablement(_api(fw=(200, {"rule_hit_count_enabled_scopes": []})))
        self.assertEqual(st.state, "partial")
        self.assertTrue(st.pce_report_enabled)
        self.assertFalse(st.ven_scopes_enabled)

    def test_template_404_means_unsupported(self):
        st = check_enablement(_api(tpl=(404, None)))
        self.assertEqual(st.state, "unsupported")

    def test_connection_failure_raises(self):
        with self.assertRaises(ConnectionError):
            check_enablement(_api(tpl=(0, None)))


class TestEnable(unittest.TestCase):
    def _api_ok(self):
        api = MagicMock()
        api.api_cfg = {"org_id": 1}
        api._api_put.return_value = 204
        api._api_post.return_value = (201, {})
        return api

    def test_enable_all_vens_runs_three_steps_in_order(self):
        api = self._api_ok()
        steps = enable_rule_hit_count(api)
        self.assertEqual(steps, ["pce_report_template", "ven_firewall_settings_draft", "provisioned"])
        # PCE template first
        first = api._api_put.call_args_list[0]
        self.assertIn("report_templates/rule_hit_count_report", first.args[0])
        self.assertEqual(first.args[1], {"enabled": True})
        # VEN draft second — all VENs is [[]]
        second = api._api_put.call_args_list[1]
        self.assertIn("sec_policy/draft/firewall_settings", second.args[0])
        self.assertEqual(second.args[1], {"rule_hit_count_enabled_scopes": [[]]})
        # provision third
        prov = api._api_post.call_args
        self.assertIn("/sec_policy", prov.args[0])
        self.assertEqual(
            prov.args[1]["change_subset"],
            {"firewall_settings": [{"href": "/orgs/1/sec_policy/draft/firewall_settings"}]})
        self.assertEqual(prov.args[1]["update_description"], "Enable rule hit count (illumio-ops)")

    def test_enable_with_label_scopes(self):
        api = self._api_ok()
        scopes = [[{"label": {"href": "/orgs/1/labels/7"}}]]
        enable_rule_hit_count(api, scopes=scopes)
        second = api._api_put.call_args_list[1]
        self.assertEqual(second.args[1], {"rule_hit_count_enabled_scopes": scopes})

    def test_failure_mid_way_stops_and_reports_steps_done(self):
        api = self._api_ok()
        api._api_put.side_effect = [204, 500]   # PCE ok, VEN draft fails
        with self.assertRaises(EnablementError) as ctx:
            enable_rule_hit_count(api)
        self.assertEqual(ctx.exception.steps_done, ["pce_report_template"])
        api._api_post.assert_not_called()   # provision must NOT run after failure


class TestNotEnabledException(unittest.TestCase):
    def test_carries_status(self):
        st = EnablementStatus(state="disabled", pce_report_enabled=False,
                              ven_scopes_enabled=False, detail="x")
        exc = RuleHitCountNotEnabled(st)
        self.assertIs(exc.status, st)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_enablement.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 實作**

建立 `src/report/rule_hit_count_enablement.py`：

```python
"""Native Rule Hit Count feature — enablement detection and enable flow.

Vendor facts (verified 2026-07-05 against the Illumio NotebookLM notebook):
  * PCE side:  PUT /orgs/:org/report_templates/rule_hit_count_report {"enabled": true}
  * VEN side:  PUT /orgs/:org/sec_policy/draft/firewall_settings
               {"rule_hit_count_enabled_scopes": [[]]}   ([[]] = all VENs)
               then POST /orgs/:org/sec_policy to provision — this WRITES to
               production policy, so callers must obtain explicit human
               confirmation before calling enable_rule_hit_count().
  * Version floors: SaaS PCE >= 24.2.0 / on-prem >= 23.5.10 / VEN >= 23.2.30.
    A 404 on the report template endpoint is treated as 'unsupported'.
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


@dataclass
class EnablementStatus:
    state: str                  # 'enabled' | 'partial' | 'disabled' | 'unsupported'
    pce_report_enabled: bool
    ven_scopes_enabled: bool
    detail: str


class RuleHitCountNotEnabled(RuntimeError):
    """Raised by the generator when the native feature is not fully enabled."""

    def __init__(self, status: EnablementStatus):
        self.status = status
        super().__init__(f"rule hit count not enabled: {status.state} ({status.detail})")


class EnablementError(RuntimeError):
    """Enable flow failed part-way. steps_done lists what already succeeded."""

    def __init__(self, message: str, steps_done: list):
        self.steps_done = steps_done
        super().__init__(message)


def check_enablement(api) -> EnablementStatus:
    """Two lightweight GETs. Raises ConnectionError if the PCE is unreachable."""
    org = api.api_cfg['org_id']

    status, tpl = api._api_get(f"/orgs/{org}/report_templates/rule_hit_count_report")
    if status == 404:
        return EnablementStatus(
            state="unsupported", pce_report_enabled=False, ven_scopes_enabled=False,
            detail="report template not found — PCE below version floor "
                   "(SaaS 24.2.0 / on-prem 23.5.10) or feature absent")
    if status != 200 or tpl is None:
        raise ConnectionError(f"report_templates query failed: HTTP {status}")
    pce_on = bool(tpl.get("enabled"))

    status, fw = api._api_get(f"/orgs/{org}/sec_policy/active/firewall_settings")
    if status != 200 or fw is None:
        raise ConnectionError(f"firewall_settings query failed: HTTP {status}")
    scopes = fw.get("rule_hit_count_enabled_scopes") or []
    ven_on = len(scopes) > 0

    if pce_on and ven_on:
        state, detail = "enabled", "PCE report template and VEN scopes both enabled"
    elif not pce_on and not ven_on:
        state, detail = "disabled", "PCE report template and VEN scopes both disabled"
    else:
        missing = "VEN firewall_settings scopes" if pce_on else "PCE report template"
        state, detail = "partial", f"missing: {missing}"
    return EnablementStatus(state=state, pce_report_enabled=pce_on,
                            ven_scopes_enabled=ven_on, detail=detail)


def enable_rule_hit_count(api, scopes: list | None = None) -> list:
    """Enable the native feature. scopes=None enables ALL VENs ([[]]).

    Executes: PCE report template -> VEN draft firewall_settings -> provision.
    Stops at the first failure (never leaves provision running after a failed
    draft write) and raises EnablementError carrying the completed steps.
    """
    org = api.api_cfg['org_id']
    steps_done: list = []

    st = api._api_put(f"/orgs/{org}/report_templates/rule_hit_count_report",
                      {"enabled": True})
    if st not in (200, 204):
        raise EnablementError(f"PCE report template enable failed: HTTP {st}", steps_done)
    steps_done.append("pce_report_template")

    payload = {"rule_hit_count_enabled_scopes": scopes if scopes is not None else [[]]}
    st = api._api_put(f"/orgs/{org}/sec_policy/draft/firewall_settings", payload)
    if st not in (200, 204):
        raise EnablementError(f"VEN firewall_settings draft update failed: HTTP {st}", steps_done)
    steps_done.append("ven_firewall_settings_draft")

    st, _body = api._api_post(f"/orgs/{org}/sec_policy", {
        "update_description": "Enable rule hit count (illumio-ops)",
        "change_subset": {
            "firewall_settings": [{"href": f"/orgs/{org}/sec_policy/draft/firewall_settings"}]
        },
    })
    if st != 201:
        raise EnablementError(f"provision failed: HTTP {st}", steps_done)
    steps_done.append("provisioned")
    logger.info(f"Rule hit count enabled (steps: {steps_done})")
    return steps_done
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_rule_hit_count_enablement.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/rule_hit_count_enablement.py tests/test_rule_hit_count_enablement.py
git commit -m "feat(report): rule hit count enablement detection and enable flow"
```

---

### Task 3: ReportsApi — 原生報表拉取（掛 ApiClient facade）

**Files:**
- Create: `src/api/reports.py`
- Modify: `src/api_client.py`（domain class 組裝處 + 委派方法；import 區塊在 :36-41 附近，組裝在 `__init__` 內 `self._labels/_jobs/_traffic` 附近——實作時 grep `self._traffic =` 定位）
- Test: `tests/test_api_reports_pull.py`

**Interfaces:**
- Consumes: `client._api_post/_api_get/_request`、`client.api_cfg`
- Produces:
  - `ReportsApi(client).pull_rule_hit_count_report(last_num_days=None, start_date=None, end_date=None, rule_sets=None, timeout_seconds=600, poll_interval_seconds=5) -> str`（本機 CSV 暫存檔路徑）
  - `RuleHitCountPullTimeout(TimeoutError)`（帶 `.report_href`）
  - facade：`ApiClient.pull_rule_hit_count_report(**kwargs)` 委派

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_api_reports_pull.py`：

```python
"""ReportsApi.pull_rule_hit_count_report — submit → poll → download state machine."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.api.reports import ReportsApi, RuleHitCountPullTimeout


def _client(poll_statuses=("pending", "done"), download=(200, b"Rule HREF,Rule Hit Count\n/r/1,3\n")):
    c = MagicMock()
    c.api_cfg = {"org_id": 1, "url": "https://pce.example.com:8443"}
    c._api_post.return_value = (201, {"href": "/orgs/1/reports/abc-123"})
    polls = [(200, {"status": s}) for s in poll_statuses]
    c._api_get.side_effect = polls
    c._request.return_value = download
    return c


class TestPull(unittest.TestCase):
    def test_happy_path_writes_csv(self):
        c = _client()
        with patch("src.api.reports.time.sleep"):
            path = ReportsApi(c).pull_rule_hit_count_report(last_num_days=30)
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Rule HREF", fh.read())
        os.unlink(path)
        # payload shape
        payload = c._api_post.call_args.args[1]
        self.assertEqual(payload["report_template"]["href"],
                         "/orgs/1/report_templates/rule_hit_count_report")
        self.assertEqual(payload["report_parameters"]["rule_sets"], [])
        self.assertEqual(payload["report_parameters"]["report_time_range"],
                         {"last_num_days": 30})
        self.assertEqual(payload["report_format"], "csv")
        # download hits the /download endpoint
        self.assertIn("/orgs/1/reports/abc-123/download", c._request.call_args.args[0])

    def test_explicit_date_range(self):
        c = _client()
        with patch("src.api.reports.time.sleep"):
            path = ReportsApi(c).pull_rule_hit_count_report(
                start_date="2026-06-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
        os.unlink(path)
        payload = c._api_post.call_args.args[1]
        self.assertEqual(payload["report_parameters"]["report_time_range"],
                         {"start_date": "2026-06-01T00:00:00Z",
                          "end_date": "2026-07-01T00:00:00Z"})

    def test_report_failed_status_raises(self):
        c = _client(poll_statuses=("pending", "failed"))
        with patch("src.api.reports.time.sleep"):
            with self.assertRaises(RuntimeError):
                ReportsApi(c).pull_rule_hit_count_report(last_num_days=7)

    def test_timeout_raises_with_href(self):
        c = _client(poll_statuses=("pending",) * 50)
        with patch("src.api.reports.time.sleep"), \
             patch("src.api.reports.time.monotonic", side_effect=[0.0] + [1000.0] * 60):
            with self.assertRaises(RuleHitCountPullTimeout) as ctx:
                ReportsApi(c).pull_rule_hit_count_report(last_num_days=7, timeout_seconds=600)
        self.assertEqual(ctx.exception.report_href, "/orgs/1/reports/abc-123")

    def test_submit_failure_raises(self):
        c = _client()
        c._api_post.return_value = (500, None)
        with self.assertRaises(RuntimeError):
            ReportsApi(c).pull_rule_hit_count_report(last_num_days=7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_api_reports_pull.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 實作 `src/api/reports.py`**

```python
"""PCE Reports API — native Rule Hit Count report pull.

Flow: POST /orgs/:org/reports (rule_hit_count template, csv format)
      -> poll GET <report href> until status == done
      -> GET <report href>/download, write bytes to a temp CSV file.
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid

from loguru import logger


class RuleHitCountPullTimeout(TimeoutError):
    """Polling exceeded timeout_seconds. report_href allows a later retry/CSV path."""

    def __init__(self, report_href: str):
        self.report_href = report_href
        super().__init__(f"rule hit count report not ready in time: {report_href}")


class ReportsApi:
    def __init__(self, client):
        self._c = client   # ApiClient (facade) — uses its _api_post/_api_get/_request

    def pull_rule_hit_count_report(
        self,
        last_num_days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        rule_sets: list | None = None,
        timeout_seconds: int = 600,
        poll_interval_seconds: int = 5,
    ) -> str:
        """Generate + download the native report. Returns a local temp CSV path.

        Caller owns (and should unlink) the returned file.
        """
        org = self._c.api_cfg['org_id']
        if start_date and end_date:
            time_range = {"start_date": start_date, "end_date": end_date}
        else:
            time_range = {"last_num_days": int(last_num_days or 30)}

        payload = {
            "report_template": {"href": f"/orgs/{org}/report_templates/rule_hit_count_report"},
            "description": "illumio-ops rule hit count pull",
            "report_parameters": {
                "report_time_range": time_range,
                "rule_sets": rule_sets or [],   # [] = all rulesets
            },
            "report_format": "csv",
        }
        status, body = self._c._api_post(f"/orgs/{org}/reports", payload)
        if status not in (200, 201) or not body:
            raise RuntimeError(f"rule hit count report submit failed: HTTP {status}")
        href = body.get("href", "")
        logger.info(f"Rule hit count report submitted: {href}")

        deadline = time.monotonic() + timeout_seconds
        while True:
            status, rep = self._c._api_get(href)
            state = str((rep or {}).get("status", "")).lower() if status == 200 else ""
            if state == "done":
                break
            if state in ("failed", "error"):
                raise RuntimeError(f"rule hit count report failed on PCE: {href}")
            if time.monotonic() >= deadline:
                raise RuleHitCountPullTimeout(href)
            time.sleep(poll_interval_seconds)

        url = f"{self._c.api_cfg['url']}/api/v2{href}/download"
        status, content = self._c._request(url, timeout=60)
        if status != 200:
            raise RuntimeError(f"rule hit count report download failed: HTTP {status}")
        out = os.path.join(tempfile.gettempdir(), f"rhc_native_{uuid.uuid4().hex}.csv")
        with open(out, "wb") as fh:
            fh.write(content if isinstance(content, bytes) else bytes(content))
        return out
```

- [ ] **Step 4: facade 掛線（`src/api_client.py`）**

import 區（`from src.api.traffic_query import ...` 之後）加：

```python
from src.api.reports import ReportsApi
```

`__init__` 內、其他 domain class 組裝處（grep `self._traffic =`）之後加：

```python
        self._reports = ReportsApi(self)
```

委派方法（放在 `pull` 相關或 `provision_changes` 附近皆可）：

```python
    def pull_rule_hit_count_report(self, **kwargs) -> str:
        """Delegates to ReportsApi — native Rule Hit Count report pull."""
        return self._reports.pull_rule_hit_count_report(**kwargs)
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/test_api_reports_pull.py -v && python -m pytest tests/ -q -k "api_client or apiclient" 2>/dev/null | tail -3`
Expected: 新測試全 PASS；既有 api client 測試不破

- [ ] **Step 6: Commit**

```bash
git add src/api/reports.py src/api_client.py tests/test_api_reports_pull.py
git commit -m "feat(api): native rule hit count report pull via PCE reports API"
```

---

### Task 4: RuleHitCountGenerator — CSV 解析 + 三節 finalize + enrichment + 報表 i18n keys

**Files:**
- Create: `src/report/rule_hit_count_generator.py`
- Modify: `src/i18n_en.json`（`rpt_pu_*` 區塊附近，約 :3383）、`src/i18n/data/zh_explicit.json`（約 :1169）
- Test: `tests/test_rule_hit_count_generator.py`

**Interfaces:**
- Consumes: `build_rule_baseline`（Task 1）、`api.get_all_rulesets(force_refresh=True)`（`src/api_client.py:771`）、`api.resolve_actor_str`（:390）、`api.resolve_service_str`（:393）
- Produces:
  - `RuleHitCountResult`（dataclass：`generated_at, record_count: int, date_range: tuple, source: str`（`native|csv`）`, module_results: dict, dataframe`）；`module_results = {'kpis': dict, 'hit_df', 'unused_df', 'cleanup_df'}`
  - `RuleHitCountGenerator(config_manager, api_client=None, config_dir='config')`
  - `generate_from_csv(csv_path: str, lang: str = "en") -> RuleHitCountResult`
  - `_norm_header`、`_CSV_ALIASES`、`CLEANUP_DAYS_THRESHOLD = 90`
  - DataFrame 欄位（後續 Task 沿用）：`rule_href, ruleset, rule_no, rule_id, rule_type, description, consumers, providers, services, enabled, hit_count, days_since_last_hit`

- [ ] **Step 1: 加入全部 rpt_rhc_* i18n keys**

`src/i18n_en.json`（插在 `rpt_pu_*` 區塊後）：

```json
  "rpt_rhc_report_title": "Rule Hit Count Report",
  "rpt_rhc_cover_type": "Rule Hit Count (VEN-measured)",
  "rpt_rhc_pulling": "Generating native rule hit count report on PCE...",
  "rpt_rhc_html_saved": "Rule Hit Count HTML report saved: {path}",
  "rpt_rhc_csv_saved": "Rule Hit Count CSV raw data saved: {path}",
  "rpt_rhc_kpi_total": "Total Rules",
  "rpt_rhc_kpi_hit": "Hit Rules",
  "rpt_rhc_kpi_unused": "Unused Rules",
  "rpt_rhc_kpi_hit_rate": "Hit Rate",
  "rpt_rhc_kpi_total_hits": "Total Hits",
  "rpt_rhc_sec_hit": "Hit Rules (sorted by hit count)",
  "rpt_rhc_sec_unused": "Unused Rules",
  "rpt_rhc_sec_cleanup": "Cleanup Candidates (enabled, unused or no hit for {days}+ days)",
  "rpt_rhc_no_rows": "No rules in this section.",
  "rpt_rhc_note_semantics": "Hit counts are VEN-measured native data. Only Active rules are counted; Essential Rules are excluded.",
  "rpt_rhc_note_optimization": "PCE rule optimization may increment merged rules together (counts can overestimate). Each flow attributes at most 100 rules.",
  "rpt_rhc_note_retention": "Counts are retained for 90 days; last-hit timestamps are kept permanently.",
  "rpt_rhc_note_enrich_failed": "Rule detail enrichment failed — consumer/provider/service columns are empty.",
  "rpt_rhc_note_csv_window": "Data window taken from the imported CSV's Start/End Date columns.",
  "rpt_rhc_col_ruleset": "Ruleset",
  "rpt_rhc_col_rule_no": "No.",
  "rpt_rhc_col_rule_id": "Rule ID",
  "rpt_rhc_col_rule_type": "Type",
  "rpt_rhc_col_description": "Description",
  "rpt_rhc_col_consumers": "Consumers (Source)",
  "rpt_rhc_col_providers": "Providers (Destination)",
  "rpt_rhc_col_services": "Services",
  "rpt_rhc_col_enabled": "Enabled",
  "rpt_rhc_col_hit_count": "Hit Count",
  "rpt_rhc_col_days_since": "Days Since Last Hit",
```

`src/i18n/data/zh_explicit.json`（插在 `rpt_pu_*` 區塊後）：

```json
  "rpt_rhc_report_title": "規則命中次數報表",
  "rpt_rhc_cover_type": "規則命中次數（VEN 實測）",
  "rpt_rhc_pulling": "正在 PCE 產生原生規則命中次數報表...",
  "rpt_rhc_html_saved": "規則命中次數 HTML 報表已儲存：{path}",
  "rpt_rhc_csv_saved": "規則命中次數 CSV 原始資料已儲存：{path}",
  "rpt_rhc_kpi_total": "規則總數",
  "rpt_rhc_kpi_hit": "有命中規則",
  "rpt_rhc_kpi_unused": "未命中規則",
  "rpt_rhc_kpi_hit_rate": "命中率",
  "rpt_rhc_kpi_total_hits": "總命中次數",
  "rpt_rhc_sec_hit": "有命中規則（依命中次數排序）",
  "rpt_rhc_sec_unused": "未命中規則",
  "rpt_rhc_sec_cleanup": "清理候選（啟用中，未命中或 {days} 天以上無命中）",
  "rpt_rhc_no_rows": "本節無規則。",
  "rpt_rhc_note_semantics": "命中數為 VEN 實測原生數據；僅計 Active 規則，Essential Rules 不計入。",
  "rpt_rhc_note_optimization": "PCE 規則最佳化可能使合併規則同時累加（計數可能高估）；每筆 flow 最多歸因 100 條規則。",
  "rpt_rhc_note_retention": "計數保留 90 天；「距上次命中」時間戳為永久保留。",
  "rpt_rhc_note_enrich_failed": "規則明細 enrichment 失敗——來源/目的/服務欄位為空。",
  "rpt_rhc_note_csv_window": "資料時窗取自匯入 CSV 的 Start/End Date 欄。",
  "rpt_rhc_col_ruleset": "Ruleset",
  "rpt_rhc_col_rule_no": "編號",
  "rpt_rhc_col_rule_id": "規則 ID",
  "rpt_rhc_col_rule_type": "類型",
  "rpt_rhc_col_description": "說明",
  "rpt_rhc_col_consumers": "Consumers（來源）",
  "rpt_rhc_col_providers": "Providers（目的）",
  "rpt_rhc_col_services": "服務",
  "rpt_rhc_col_enabled": "啟用",
  "rpt_rhc_col_hit_count": "命中次數",
  "rpt_rhc_col_days_since": "距上次命中天數",
```

- [ ] **Step 2: 寫失敗測試（追加到 tests/test_rule_hit_count_generator.py）**

```python
from src.report.rule_hit_count_generator import (
    CLEANUP_DAYS_THRESHOLD,
    RuleHitCountGenerator,
    RuleHitCountResult,
    _norm_header,
)


def _write_native_csv(dirpath: str) -> str:
    """Write a CSV shaped like the PCE-native Rule Hit Count export."""
    path = os.path.join(dirpath, "rule-hit-count.csv")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(
            "Rule HREF,Rule Name,Rule Set HREF,Rule Set Name,Rule Hit Count,"
            "Days Since Last Hit,Start Date,End Date\n"
            "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/100,allow web,"
            "/orgs/1/sec_policy/active/rule_sets/10,RS-A,42,3,2026-06-01,2026-07-01\n"
            "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/101,stale allow,"
            "/orgs/1/sec_policy/active/rule_sets/10,RS-A,5,120,2026-06-01,2026-07-01\n"
            "/orgs/1/sec_policy/active/rule_sets/11/deny_rules/200,deny legacy,"
            "/orgs/1/sec_policy/active/rule_sets/11,RS-Legacy,0,,2026-06-01,2026-07-01\n"
        )
    return path


class TestNormHeader(unittest.TestCase):
    def test_native_headers_normalize(self):
        self.assertEqual(_norm_header("Rule HREF"), "rule_href")
        self.assertEqual(_norm_header("Rule Hit Count"), "rule_hit_count")
        self.assertEqual(_norm_header("  Days Since Last Hit "), "days_since_last_hit")


class TestGenerateFromCsv(unittest.TestCase):
    def test_parses_native_csv_without_api(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td), lang="en")
        self.assertIsInstance(result, RuleHitCountResult)
        self.assertEqual(result.record_count, 3)
        self.assertEqual(result.source, "csv")
        self.assertEqual(result.date_range, ("2026-06-01", "2026-07-01"))
        kpis = result.module_results["kpis"]
        self.assertEqual(kpis["total_rules"], 3)
        self.assertEqual(kpis["hit_rules"], 2)
        self.assertEqual(kpis["unused_rules"], 1)
        self.assertEqual(kpis["total_hits"], 47)
        hit_df = result.module_results["hit_df"]
        self.assertEqual(list(hit_df["hit_count"]), [42, 5])   # desc by hits

    def test_missing_required_columns_raises(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("foo,bar\n1,2\n")
            with self.assertRaises(ValueError):
                gen.generate_from_csv(path)


class TestCleanupCandidates(unittest.TestCase):
    def test_cleanup_includes_unused_and_stale_enabled_rules(self):
        # Without enrichment 'enabled' is '', so cleanup only applies when
        # enrichment sets enabled=True. Enrich rows 100/101 via mocked api.
        api = MagicMock()
        api.get_all_rulesets.return_value = [{
            "href": "/orgs/1/sec_policy/active/rule_sets/10",
            "name": "RS-A",
            "scopes": [],
            "rules": [
                {"href": "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/100", "enabled": True},
                {"href": "/orgs/1/sec_policy/active/rule_sets/10/sec_rules/101", "enabled": True},
            ],
        }]
        api.resolve_actor_str.return_value = "Any"
        api.resolve_service_str.return_value = "All Services"
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td))
        cleanup = result.module_results["cleanup_df"]
        # rule 101: enabled, 120 days since last hit >= 90 → cleanup candidate
        self.assertIn("101", list(cleanup["rule_id"]))
        # rule 100: 3 days since last hit, has hits → NOT a candidate
        self.assertNotIn("100", list(cleanup["rule_id"]))
        self.assertEqual(CLEANUP_DAYS_THRESHOLD, 90)


class TestCsvEnrichment(unittest.TestCase):
    def test_enriches_matching_hrefs(self):
        api = MagicMock()
        api.get_all_rulesets.return_value = _sample_rulesets()
        api.resolve_actor_str.return_value = "All Workloads"
        api.resolve_service_str.return_value = "443/tcp"
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rhc.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    "Rule HREF,Rule Hit Count\n"
                    "/orgs/1/sec_policy/draft/rule_sets/10/sec_rules/100,7\n"
                )
            result = gen.generate_from_csv(path)
        row = result.dataframe[result.dataframe["rule_id"] == "100"].iloc[0]
        self.assertEqual(row["consumers"], "All Workloads")
        self.assertEqual(row["services"], "443/tcp")
        self.assertEqual(row["ruleset"], "RS-A")
        self.assertEqual(row["rule_type"], "Allow")
        self.assertEqual(row["enabled"], True)

    def test_enrichment_failure_is_non_fatal_and_flagged(self):
        api = MagicMock()
        api.get_all_rulesets.side_effect = ConnectionError("PCE down")
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td))
        self.assertEqual(result.record_count, 3)
        self.assertTrue(result.module_results.get("enrich_failed"))
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.report.rule_hit_count_generator'`

- [ ] **Step 4: 實作 generator（CSV 解析 + enrichment + finalize）**

建立 `src/report/rule_hit_count_generator.py`：

```python
"""
src/report/rule_hit_count_generator.py
Rule Hit Count Report generator — enhancer over the PCE-NATIVE report.

Hit counts in this report are always VEN-measured native data:
  native — auto-pull via api.pull_rule_hit_count_report() (Task 5)
  csv    — import the PCE UI's native Rule Hit Count CSV export
Both paths feed the same parser; rows are then enriched with live rule
details (consumers/providers/services) joined by rule href.

This report does NOT compute traffic-derived approximations — that is the
existing Policy Usage report's job.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from src.i18n import t

CLEANUP_DAYS_THRESHOLD = 90   # vendor: counts are retained 90 days


@dataclass
class RuleHitCountResult:
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    record_count: int = 0
    date_range: tuple = ('', '')
    source: str = 'native'
    module_results: dict = field(default_factory=dict)
    dataframe: object = None


# PCE-native CSV header → canonical column. Headers are normalized first
# (lowercase, non-alnum → '_'), so "Rule HREF" → "rule_href".
_CSV_ALIASES = {
    'rule_href': 'rule_href',
    'rule_hit_count': 'hit_count',
    'hit_count': 'hit_count',
    'rule_name': 'description',
    'rule_description': 'description',
    'rule_set_name': 'ruleset_name',
    'ruleset_name': 'ruleset_name',
    'rule_set_href': 'ruleset_href',
    'ruleset_href': 'ruleset_href',
    'days_since_last_hit': 'days_since_last_hit',
    'start_date': 'start_date',
    'end_date': 'end_date',
}


def _norm_header(header) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(header).strip().lower()).strip('_')


class RuleHitCountGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = 'config'):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir
        self._lang = "en"

    # ── Public interface ──────────────────────────────────────────────────

    def generate_from_csv(self, csv_path: str, lang: str = "en") -> RuleHitCountResult:
        """Parse the PCE-native Rule Hit Count CSV (needs Rule HREF + Rule Hit Count)."""
        import pandas as pd
        self._lang = lang
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        df.columns = [_norm_header(c) for c in df.columns]
        df = df.rename(columns={c: _CSV_ALIASES[c] for c in df.columns if c in _CSV_ALIASES})
        logger.info(f"Loaded rule hit count CSV: {len(df)} rows, columns={list(df.columns)}")
        if 'rule_href' not in df.columns or 'hit_count' not in df.columns:
            raise ValueError(
                f"unrecognized rule hit count CSV (columns={list(df.columns)}); "
                "need at least 'Rule HREF' and 'Rule Hit Count'")

        rows = []
        for _, row in df.iterrows():
            href = str(row.get('rule_href', '') or '').strip()
            if not href or href == 'nan':
                continue
            try:
                hits = int(float(row.get('hit_count', 0) or 0))
            except (TypeError, ValueError):
                hits = 0
            days = row.get('days_since_last_hit', '')
            rows.append({
                'rule_href': href,
                'ruleset': str(row.get('ruleset_name', '') or ''),
                'rule_no': '',
                'rule_id': href.rstrip('/').rsplit('/', 1)[-1],
                'rule_type': '',
                'description': str(row.get('description', '') or ''),
                'consumers': '',
                'providers': '',
                'services': '',
                'enabled': '',
                'hit_count': hits,
                'days_since_last_hit': '' if pd.isna(days) else str(days),
            })

        # Native export carries the report window as Start/End Date columns.
        date_range = ('', '')
        if len(df) and 'start_date' in df.columns and 'end_date' in df.columns:
            date_range = (str(df.iloc[0]['start_date'])[:10], str(df.iloc[0]['end_date'])[:10])

        enrich_failed = self._enrich_rows(rows)
        return self._finalize(rows, source='csv', date_range=date_range,
                              enrich_failed=enrich_failed)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _actor_str(self, actors) -> str:
        if not actors:
            return 'Any'
        try:
            return self.api.resolve_actor_str(actors)
        except Exception:
            logger.opt(exception=True).debug("resolve_actor_str failed")
            return ''

    def _service_str(self, services) -> str:
        if not services:
            return 'All Services'
        try:
            return self.api.resolve_service_str(services)
        except Exception:
            logger.opt(exception=True).debug("resolve_service_str failed")
            return ''

    def _enrich_rows(self, rows: list) -> bool:
        """Best-effort join of live rule details by href. Returns True on FAILURE
        (so the exporter can flag it); enrichment failure never kills the report."""
        if not self.api or not rows:
            return False
        try:
            from src.report.policy_usage_generator import build_rule_baseline
            rulesets = self.api.get_all_rulesets(force_refresh=True)
            flat_rules, _ = build_rule_baseline(rulesets or [])
        except Exception as exc:
            logger.warning("Rule detail enrichment skipped: {}", exc)
            return True
        by_href = {r.get('href', ''): r for r in flat_rules}
        for row in rows:
            rule = by_href.get(row['rule_href'])
            if not rule:
                continue
            row['ruleset'] = row['ruleset'] or rule.get('_ruleset_name', '')
            row['rule_no'] = rule.get('_rule_no', '')
            row['rule_type'] = rule.get('_rule_type', '')
            row['description'] = row['description'] or rule.get('description', '')
            row['consumers'] = self._actor_str(rule.get('consumers'))
            row['providers'] = self._actor_str(rule.get('providers'))
            row['services'] = self._service_str(rule.get('ingress_services'))
            row['enabled'] = bool(rule.get('enabled', True))
        return False

    def _finalize(self, rows: list, source: str, date_range: tuple,
                  enrich_failed: bool = False) -> RuleHitCountResult:
        import pandas as pd
        df = pd.DataFrame(rows)
        total = len(rows)
        hit = sum(1 for r in rows if r['hit_count'] > 0)
        kpis = {
            'total_rules': total,
            'hit_rules': hit,
            'unused_rules': total - hit,
            'hit_rate_pct': round(hit * 100.0 / total, 1) if total else 0.0,
            'total_hits': sum(r['hit_count'] for r in rows),
        }
        if total:
            hit_df = df[df['hit_count'] > 0].sort_values('hit_count', ascending=False)
            unused_df = df[df['hit_count'] == 0]
            days = pd.to_numeric(df['days_since_last_hit'], errors='coerce')
            cleanup_df = df[(df['enabled'] == True) &
                            ((df['hit_count'] == 0) | (days >= CLEANUP_DAYS_THRESHOLD))]
            cleanup_df = cleanup_df.assign(_days=days[cleanup_df.index]) \
                                   .sort_values('_days', ascending=False, na_position='last') \
                                   .drop(columns=['_days'])
        else:
            hit_df = unused_df = cleanup_df = df
        return RuleHitCountResult(
            record_count=total,
            date_range=date_range,
            source=source,
            module_results={'kpis': kpis, 'hit_df': hit_df, 'unused_df': unused_df,
                            'cleanup_df': cleanup_df, 'enrich_failed': enrich_failed},
            dataframe=df,
        )
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/test_rule_hit_count_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/report/rule_hit_count_generator.py tests/test_rule_hit_count_generator.py src/i18n_en.json src/i18n/data/zh_explicit.json
git commit -m "feat(report): rule hit count generator with native CSV parsing and enrichment"
```

---

### Task 5: generate_from_native（偵測 → 拉取 → 解析）

**Files:**
- Modify: `src/report/rule_hit_count_generator.py`
- Test: `tests/test_rule_hit_count_generator.py`

**Interfaces:**
- Consumes: `check_enablement` / `RuleHitCountNotEnabled`（Task 2）、`api.pull_rule_hit_count_report(...) -> csv_path`（Task 3）
- Produces: `generate_from_native(start_date=None, end_date=None, lang="en") -> RuleHitCountResult`（未啟用 raise `RuleHitCountNotEnabled`；result.source == 'native'）

- [ ] **Step 1: 寫失敗測試（追加）**

```python
class TestGenerateFromNative(unittest.TestCase):
    def _api(self, tmpdir):
        api = MagicMock()
        api.get_all_rulesets.return_value = []
        api.pull_rule_hit_count_report.return_value = _write_native_csv(tmpdir)
        return api

    def test_pulls_and_parses_when_enabled(self):
        from unittest.mock import patch
        from src.report.rule_hit_count_enablement import EnablementStatus
        with tempfile.TemporaryDirectory() as td:
            api = self._api(td)
            gen = RuleHitCountGenerator(MagicMock(), api_client=api)
            with patch("src.report.rule_hit_count_generator.check_enablement",
                       return_value=EnablementStatus("enabled", True, True, "")):
                result = gen.generate_from_native(start_date="2026-06-01T00:00:00Z",
                                                  end_date="2026-07-01T00:00:00Z")
        self.assertEqual(result.source, "native")
        self.assertEqual(result.record_count, 3)
        kwargs = api.pull_rule_hit_count_report.call_args.kwargs
        self.assertEqual(kwargs["start_date"], "2026-06-01T00:00:00Z")

    def test_raises_when_not_enabled(self):
        from unittest.mock import patch
        from src.report.rule_hit_count_enablement import (
            EnablementStatus, RuleHitCountNotEnabled)
        gen = RuleHitCountGenerator(MagicMock(), api_client=MagicMock())
        with patch("src.report.rule_hit_count_generator.check_enablement",
                   return_value=EnablementStatus("disabled", False, False, "off")):
            with self.assertRaises(RuleHitCountNotEnabled):
                gen.generate_from_native()

    def test_temp_csv_is_cleaned_up(self):
        from unittest.mock import patch
        from src.report.rule_hit_count_enablement import EnablementStatus
        with tempfile.TemporaryDirectory() as td:
            api = self._api(td)
            path = api.pull_rule_hit_count_report.return_value
            gen = RuleHitCountGenerator(MagicMock(), api_client=api)
            with patch("src.report.rule_hit_count_generator.check_enablement",
                       return_value=EnablementStatus("enabled", True, True, "")):
                gen.generate_from_native()
            self.assertFalse(os.path.exists(path))

    def test_requires_api_client(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with self.assertRaises(RuntimeError):
            gen.generate_from_native()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_generator.py::TestGenerateFromNative -v`
Expected: FAIL — no attribute `generate_from_native`

- [ ] **Step 3: 實作（加在 `generate_from_csv` 之前；同時在檔頭 import 區加 `from src.report.rule_hit_count_enablement import RuleHitCountNotEnabled, check_enablement`）**

```python
    def generate_from_native(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        lang: str = "en",
    ) -> RuleHitCountResult:
        """Pull the PCE-native report and parse it. Raises RuleHitCountNotEnabled
        when the feature is not fully enabled — callers decide whether to run
        the enablement wizard (interactive) or skip (scheduler)."""
        if not self.api:
            raise RuntimeError("api_client required for native rule hit count generation")
        self._lang = lang

        status = check_enablement(self.api)
        if status.state != "enabled":
            raise RuleHitCountNotEnabled(status)

        print(t("rpt_rhc_pulling", lang=lang))
        kwargs = {}
        if start_date and end_date:
            kwargs = {"start_date": start_date, "end_date": end_date}
        else:
            kwargs = {"last_num_days": 30}
        csv_path = self.api.pull_rule_hit_count_report(**kwargs)
        try:
            result = self.generate_from_csv(csv_path, lang=lang)
        finally:
            try:
                os.unlink(csv_path)
            except OSError:
                pass
        result.source = 'native'
        return result
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_rule_hit_count_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/rule_hit_count_generator.py tests/test_rule_hit_count_generator.py
git commit -m "feat(report): rule hit count native mode with enablement gate"
```

---

### Task 6: HTML exporter（三節 + 語意注記 + 截斷）

**Files:**
- Create: `src/report/exporters/rule_hit_count_html_exporter.py`
- Test: `tests/test_rule_hit_count_html_exporter.py`

**Interfaces:**
- Consumes: `RuleHitCountResult`（Task 4）、`build_css(exporter_type)`（`src/report/exporters/report_css.py:557`；未知型別 fallback 基礎樣式）、`build_cover_page(...)`（`src/report/exporters/cover_page.py:12`）、`TABLE_JS`、i18n keys（Task 4 Step 1）
- Produces: `RuleHitCountHtmlExporter(result, lang="en", pce_url="", org_name="").export(output_dir) -> path`；檔名 `Illumio_Rule_Hit_Count_Report_YYYY-MM-DD_HHMM.html`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_rule_hit_count_html_exporter.py`：

```python
"""Rendering tests for RuleHitCountHtmlExporter (sections, notes, truncation)."""
from __future__ import annotations

import os
import tempfile
import unittest

import pandas as pd

from src.report.rule_hit_count_generator import RuleHitCountResult
from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter


def _row(**over):
    base = {"rule_href": "/r/1", "ruleset": "RS-A", "rule_no": 1, "rule_id": "1",
            "rule_type": "Allow", "description": "d", "consumers": "c",
            "providers": "p", "services": "s", "enabled": True,
            "hit_count": 5, "days_since_last_hit": "3"}
    base.update(over)
    return base


def _result(rows, enrich_failed=False, source="native"):
    df = pd.DataFrame(rows)
    hit_df = df[df["hit_count"] > 0] if len(df) else df
    unused_df = df[df["hit_count"] == 0] if len(df) else df
    return RuleHitCountResult(
        record_count=len(rows),
        date_range=("2026-06-01", "2026-07-01"),
        source=source,
        module_results={
            "kpis": {"total_rules": len(rows), "hit_rules": len(hit_df),
                     "unused_rules": len(unused_df), "hit_rate_pct": 50.0,
                     "total_hits": int(df["hit_count"].sum()) if len(df) else 0},
            "hit_df": hit_df, "unused_df": unused_df, "cleanup_df": unused_df,
            "enrich_failed": enrich_failed,
        },
        dataframe=df,
    )


class TestExporter(unittest.TestCase):
    def test_renders_sections_and_semantic_notes(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()]), lang="en").export(td)
            self.assertIn("Illumio_Rule_Hit_Count_Report_", os.path.basename(path))
            html = open(path, encoding="utf-8").read()
        self.assertIn("RS-A", html)
        self.assertIn("Cleanup Candidates", html)
        self.assertIn("VEN-measured", html)          # rpt_rhc_note_semantics
        self.assertIn("at most 100 rules", html)     # rpt_rhc_note_optimization
        self.assertIn("90 days", html)               # rpt_rhc_note_retention

    def test_csv_source_shows_window_note(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()], source="csv"),
                                            lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("Start/End Date", html)        # rpt_rhc_note_csv_window

    def test_enrich_failed_note_shown(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()], enrich_failed=True),
                                            lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("enrichment failed", html)

    def test_long_cell_truncated_with_full_value_in_title(self):
        long_val = "label-" + "x" * 300
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(
                _result([_row(consumers=long_val)]), lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("…", html)
        self.assertIn(long_val, html)                 # full value survives in title=
        self.assertNotIn(long_val + "</td>", html)    # cell text itself is cut

    def test_empty_section_shows_note(self):
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([]), lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("No rules in this section.", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_html_exporter.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 實作 exporter**

建立 `src/report/exporters/rule_hit_count_html_exporter.py`（shell 結構對齊 `policy_diff_html_exporter.py` 的 `.report-shell / .report-main / .card` 版型）：

```python
"""Rule Hit Count HTML exporter — VEN-measured native data, one row per rule.

Shared report styling (report_css.build_css + cover_page); facade exporter
contract: __init__(result, lang) + export(output_dir) -> path.

Long-cell policy (CLAUDE.md 報表規則): cells in _TRUNC_COLS longer than
_CELL_MAX chars are truncated to _CELL_MAX-1 chars + an ellipsis; the FULL
value is preserved in the cell's title attribute (hover) and in the CSV
export. Truncation is explicit and recoverable, never silent.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.report_css import TABLE_JS, build_css
from src.report.rule_hit_count_generator import CLEANUP_DAYS_THRESHOLD

_CSS = build_css("rule_hit_count")   # unknown type → base styling only

_CELL_MAX = 160
_TRUNC_COLS = {"consumers", "providers", "services", "description"}

_COLS = ["ruleset", "rule_no", "rule_type", "description", "consumers",
         "providers", "services", "enabled", "hit_count", "days_since_last_hit"]

_COL_I18N = {
    "ruleset": "rpt_rhc_col_ruleset",
    "rule_no": "rpt_rhc_col_rule_no",
    "rule_id": "rpt_rhc_col_rule_id",
    "rule_type": "rpt_rhc_col_rule_type",
    "description": "rpt_rhc_col_description",
    "consumers": "rpt_rhc_col_consumers",
    "providers": "rpt_rhc_col_providers",
    "services": "rpt_rhc_col_services",
    "enabled": "rpt_rhc_col_enabled",
    "hit_count": "rpt_rhc_col_hit_count",
    "days_since_last_hit": "rpt_rhc_col_days_since",
}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{_esc(label)}</div>'
        f'<div class="kpi-value">{_esc(value)}</div></div>'
    )


class RuleHitCountHtmlExporter:
    def __init__(self, result, lang: str = "en", pce_url: str = "", org_name: str = ""):
        self._result = result
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    def _cell(self, col: str, value) -> str:
        text = "" if value is None else str(value)
        if col in _TRUNC_COLS and len(text) > _CELL_MAX:
            shown = text[:_CELL_MAX - 1] + "…"
            return f'<td title="{_esc(text)}">{_esc(shown)}</td>'
        return f"<td>{_esc(text)}</td>"

    def _table(self, df) -> str:
        if df is None or df.empty:
            return f'<p class="note">{_esc(t("rpt_rhc_no_rows", lang=self._lang))}</p>'
        cols = [c for c in _COLS if c in df.columns]
        head = "".join(
            f"<th>{_esc(t(_COL_I18N.get(c, c), lang=self._lang))}</th>" for c in cols)
        body = []
        for _, row in df.iterrows():
            cells = "".join(self._cell(c, row.get(c, "")) for c in cols)
            body.append(f"<tr>{cells}</tr>")
        return (
            '<div class="report-table-wrap"><table class="report-table sortable">'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
        )

    def _notes(self) -> str:
        lang = self._lang
        notes = [
            t("rpt_rhc_note_semantics", lang=lang),
            t("rpt_rhc_note_optimization", lang=lang),
            t("rpt_rhc_note_retention", lang=lang),
        ]
        if self._result.source == "csv":
            notes.append(t("rpt_rhc_note_csv_window", lang=lang))
        if (self._result.module_results or {}).get("enrich_failed"):
            notes.append(t("rpt_rhc_note_enrich_failed", lang=lang))
        items = "".join(f"<li>{_esc(n)}</li>" for n in notes)
        return f'<section class="card"><ul class="note">{items}</ul></section>'

    def _render_html(self) -> str:
        mr = self._result.module_results or {}
        kpis = mr.get("kpis", {})
        lang = self._lang
        cover = _build_cover_page(
            t("rpt_rhc_report_title", lang=lang),
            t("rpt_rhc_cover_type", lang=lang),
            date_range=self._result.date_range,
            pce_url=self._pce_url, org_name=self._org_name, lang=lang)
        kpi_row = '<div class="kpi-row">' + "".join([
            _kpi(kpis.get("total_rules", 0), t("rpt_rhc_kpi_total", lang=lang)),
            _kpi(kpis.get("hit_rules", 0), t("rpt_rhc_kpi_hit", lang=lang)),
            _kpi(kpis.get("unused_rules", 0), t("rpt_rhc_kpi_unused", lang=lang)),
            _kpi(f'{kpis.get("hit_rate_pct", 0)}%', t("rpt_rhc_kpi_hit_rate", lang=lang)),
            _kpi(kpis.get("total_hits", 0), t("rpt_rhc_kpi_total_hits", lang=lang)),
        ]) + "</div>"
        sections = [
            ("rhc-hit", t("rpt_rhc_sec_hit", lang=lang), mr.get("hit_df")),
            ("rhc-unused", t("rpt_rhc_sec_unused", lang=lang), mr.get("unused_df")),
            ("rhc-cleanup",
             t("rpt_rhc_sec_cleanup", days=CLEANUP_DAYS_THRESHOLD, lang=lang),
             mr.get("cleanup_df")),
        ]
        body_sections = "".join(
            f'<section id="{sid}" class="card"><h2>{_esc(title)}</h2>{self._table(df)}</section>'
            for sid, title, df in sections)
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_esc(t('rpt_rhc_report_title', lang=lang))}</title>{_CSS}</head>"
            f"<body>{cover}<div class='report-shell'><main class='report-main'>"
            f"{kpi_row}{self._notes()}{body_sections}</main></div>{TABLE_JS}</body></html>"
        )

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Rule_Hit_Count_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._render_html())
        return path
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_rule_hit_count_html_exporter.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/rule_hit_count_html_exporter.py tests/test_rule_hit_count_html_exporter.py
git commit -m "feat(report): rule hit count html exporter with semantic notes and truncation"
```

---

### Task 7: generator.export()（html/csv/metadata sidecar）

**Files:**
- Modify: `src/report/rule_hit_count_generator.py`
- Test: `tests/test_rule_hit_count_generator.py`

**Interfaces:**
- Consumes: `RuleHitCountHtmlExporter`（Task 6）、`CsvExporter(results_dict, report_label='Rule_Hit_Count')`（`src/report/exporters/csv_exporter.py:58`；產出 `Illumio_Rule_Hit_Count_Report_<ts>_raw.zip`）
- Produces: `export(result, fmt='html', output_dir='reports', lang=None) -> list[str]`（fmt ∈ html|csv|all）；每檔附 `<path>.metadata.json`（`report_type: "rule_hit_count"`、`source`）

- [ ] **Step 1: 寫失敗測試（追加）**

```python
class TestExport(unittest.TestCase):
    def test_export_html_csv_and_metadata(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td), lang="en")
            paths = gen.export(result, fmt="all", output_dir=td)
            self.assertEqual(len(paths), 2)
            html = [p for p in paths if p.endswith(".html")]
            zips = [p for p in paths if p.endswith(".zip")]
            self.assertEqual(len(html), 1)
            self.assertEqual(len(zips), 1)
            self.assertTrue(os.path.basename(html[0]).startswith("Illumio_Rule_Hit_Count_Report_"))
            self.assertTrue(os.path.basename(zips[0]).startswith("Illumio_Rule_Hit_Count_Report_"))
            import json as _json
            meta = _json.load(open(html[0] + ".metadata.json", encoding="utf-8"))
            self.assertEqual(meta["report_type"], "rule_hit_count")
            self.assertEqual(meta["record_count"], 3)
            self.assertEqual(meta["source"], "csv")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_generator.py::TestExport -v`
Expected: FAIL — no attribute `export`

- [ ] **Step 3: 實作（加在 `generate_from_csv` 之後）**

```python
    def export(
        self,
        result: RuleHitCountResult,
        fmt: str = 'html',
        output_dir: str = 'reports',
        lang: str | None = None,
    ) -> list[str]:
        from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter

        lang = lang or getattr(self, '_lang', 'en')
        os.makedirs(output_dir, exist_ok=True)
        paths = []

        if fmt in ('html', 'all'):
            path = RuleHitCountHtmlExporter(result, lang=lang).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, result, file_format='html')
            print(t("rpt_rhc_html_saved", path=path, lang=lang))

        if fmt in ('csv', 'all'):
            mr = result.module_results or {}
            export_data = {}
            # CSV carries the FULL untruncated cell values (HTML truncates at
            # _CELL_MAX with title= hover; this is the recovery path).
            for key in ('hit_df', 'unused_df', 'cleanup_df'):
                df = mr.get(key)
                if df is not None and not df.empty:
                    export_data[key.replace('_df', '_rules')] = df
            if result.dataframe is not None and not result.dataframe.empty:
                export_data['all_rules'] = result.dataframe
            if export_data:
                path = CsvExporter(export_data, report_label='Rule_Hit_Count').export(output_dir)
                paths.append(path)
                self._write_report_metadata(path, result, file_format='csv')
                print(t("rpt_rhc_csv_saved", path=path, lang=lang))

        return paths

    def _write_report_metadata(self, report_path: str, result: RuleHitCountResult,
                               file_format: str) -> None:
        payload = {
            "report_type": "rule_hit_count",
            "file_format": file_format,
            "generated_at": result.generated_at.isoformat(),
            "record_count": int(result.record_count or 0),
            "date_range": list(result.date_range or ("", "")),
            "source": result.source,
            "kpis": (result.module_results or {}).get('kpis', {}),
        }
        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_rule_hit_count_generator.py tests/test_rule_hit_count_html_exporter.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/rule_hit_count_generator.py tests/test_rule_hit_count_generator.py
git commit -m "feat(report): rule hit count export with metadata sidecar"
```

---

### Task 8: Scheduler dispatch + 保留清理 prefix

**Files:**
- Modify: `src/report_scheduler.py`（dispatch：`elif report_type == "app_summary":` :400-412 之後、`else:` :414 之前；prefix：`_REPORT_PREFIXES` :591-601）
- Test: `tests/test_rule_hit_count_scheduler_dispatch.py`

**Interfaces:**
- Consumes: `RuleHitCountGenerator.generate_from_native` / `.export`（Task 5/7）、`RuleHitCountNotEnabled`（Task 2）
- Produces: `_generate_report(report_type="rule_hit_count", ...)` 路由；未啟用 → `(None, [])` + warning；`_REPORT_PREFIXES["rule_hit_count"] = "Illumio_Rule_Hit_Count_Report_"`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_rule_hit_count_scheduler_dispatch.py`：

```python
"""Scheduler dispatch for the rule_hit_count report type (native-only, no prompts)."""
from __future__ import annotations

from src.report_scheduler import ReportScheduler
from src.report.rule_hit_count_enablement import EnablementStatus, RuleHitCountNotEnabled


class _DummyConfigManager:
    def __init__(self):
        self.config = {"report": {"output_dir": "reports"}, "settings": {}}

    def load(self):
        pass


def _make_scheduler():
    return ReportScheduler(_DummyConfigManager(), reporter=None)


def test_generate_report_dispatches_rule_hit_count(monkeypatch, tmp_path):
    sched = _make_scheduler()
    calls = {}

    class _FakeResult:
        record_count = 4

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config"):
            calls["init"] = True

        def generate_from_native(self, start_date=None, end_date=None, lang="en"):
            calls["lang"] = lang
            return _FakeResult()

        def export(self, result, fmt="html", output_dir="reports", lang=None):
            calls["fmt"] = fmt
            calls["out"] = output_dir
            return [str(tmp_path / "Illumio_Rule_Hit_Count_Report_x.html")]

    import src.report.rule_hit_count_generator as rhc_mod
    monkeypatch.setattr(rhc_mod, "RuleHitCountGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="rule_hit_count", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date="2026-06-01T00:00:00Z",
        end_date="2026-07-01T23:59:59Z", name="RHC", lang="en")

    assert calls["lang"] == "en"
    assert calls["out"] == str(tmp_path)
    assert result.record_count == 4
    assert paths == [str(tmp_path / "Illumio_Rule_Hit_Count_Report_x.html")]


def test_not_enabled_skips_without_prompting(monkeypatch, tmp_path):
    sched = _make_scheduler()

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config"):
            pass

        def generate_from_native(self, start_date=None, end_date=None, lang="en"):
            raise RuleHitCountNotEnabled(
                EnablementStatus("disabled", False, False, "off"))

    import src.report.rule_hit_count_generator as rhc_mod
    monkeypatch.setattr(rhc_mod, "RuleHitCountGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="rule_hit_count", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date=None, end_date=None,
        name="RHC off", lang="en")
    assert result is None
    assert paths == []


def test_rule_hit_count_prefix_registered():
    assert ReportScheduler._REPORT_PREFIXES["rule_hit_count"] == "Illumio_Rule_Hit_Count_Report_"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_rule_hit_count_scheduler_dispatch.py -v`
Expected: FAIL（dispatch 落入 Unknown 分支；prefix KeyError）

- [ ] **Step 3: 實作**

`src/report_scheduler.py` dispatch 加：

```python
        elif report_type == "rule_hit_count":
            from src.report.rule_hit_count_generator import RuleHitCountGenerator
            from src.report.rule_hit_count_enablement import RuleHitCountNotEnabled
            gen = RuleHitCountGenerator(self.cm, api_client=api, config_dir=self._config_dir)
            try:
                result = gen.generate_from_native(start_date=start_date, end_date=end_date, lang=lang)
            except RuleHitCountNotEnabled as exc:
                # Scheduler NEVER prompts or auto-enables — skip with a warning.
                logger.warning(f"[Scheduler] '{name}': native rule hit count not enabled ({exc}) — skipping")
                return None, []
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': native report returned no rules — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir)
            return result, paths
```

`_REPORT_PREFIXES` 加：

```python
        "rule_hit_count":    "Illumio_Rule_Hit_Count_Report_",
```

- [ ] **Step 4: 跑測試確認通過（含既有測試）**

Run: `python -m pytest tests/test_rule_hit_count_scheduler_dispatch.py tests/test_policy_diff_resolver_scheduler_dispatch.py tests/test_report_scheduler_prune_units.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report_scheduler.py tests/test_rule_hit_count_scheduler_dispatch.py
git commit -m "feat(scheduler): rule_hit_count dispatch with not-enabled skip and retention prefix"
```

---

### Task 9: CLI 指令 + 啟用精靈

**Files:**
- Modify: `src/cli/report.py`（helper 加在 `generate_policy_usage_report` :214-247 之後；指令加在 `report_policy_usage` :534-580 之後）
- Test: `tests/test_cli_report_rule_hit_count.py`

**Interfaces:**
- Consumes: `RuleHitCountGenerator`、`RuleHitCountNotEnabled` / `check_enablement` / `enable_rule_hit_count`（Task 2/4/5/7）、`pick_objects(api, cats, title, lang=None) -> dict`（`src/cli/object_picker.py:177`；labels 值為 `"key=value"` 字串）、`api.get_all_labels()`、既有 `_resolve_paths/_resolve_output_dir/_resolve_lang/_iso_date/_emit_paths/_ctx_lang`、exit codes
- Produces:
  - `generate_rule_hit_count_report(*, source, file_path, start_date, end_date, fmt, output_dir) -> list[str]`（未啟用時 raise `RuleHitCountNotEnabled` 讓指令層處理）
  - `report rule-hit-count` 指令（`--source native|csv --file --start-date --end-date --format html|csv|all --output-dir`）
  - `_run_rhc_enablement_wizard(api, lang) -> bool`（True=已執行啟用）

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_cli_report_rule_hit_count.py`：

```python
"""Tests for the `report rule-hit-count` CLI command."""
from __future__ import annotations

from unittest.mock import patch

import click
from click.testing import CliRunner

from src.cli._exit_codes import EXIT_DATAERR, EXIT_UNAVAILABLE
from src.cli.report import report_group
from src.report.rule_hit_count_enablement import EnablementStatus, RuleHitCountNotEnabled


def test_rule_hit_count_command_registered():
    assert "rule-hit-count" in report_group.commands


def test_rule_hit_count_invokes_report(tmp_path):
    runner = CliRunner()
    with patch("src.cli.report.generate_rule_hit_count_report",
               return_value=[str(tmp_path / "Illumio_Rule_Hit_Count_Report_x.html")]) as gen:
        result = runner.invoke(report_group,
                               ["rule-hit-count", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    gen.assert_called_once_with(source="native", file_path=None, start_date=None,
                                end_date=None, fmt="html", output_dir=str(tmp_path))


def test_rule_hit_count_csv_source(tmp_path):
    csv = tmp_path / "rhc.csv"
    csv.write_text("Rule HREF,Rule Hit Count\n/r/1,3\n", encoding="utf-8")
    runner = CliRunner()
    with patch("src.cli.report.generate_rule_hit_count_report",
               return_value=[str(tmp_path / "x.html")]) as gen:
        result = runner.invoke(report_group,
                               ["rule-hit-count", "--source", "csv",
                                "--file", str(csv), "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert gen.call_args.kwargs["source"] == "csv"


def test_not_enabled_non_tty_exits_unavailable(tmp_path):
    """Without a TTY the wizard must NOT run; command exits EXIT_UNAVAILABLE."""
    runner = CliRunner()
    exc = RuleHitCountNotEnabled(EnablementStatus("disabled", False, False, "off"))
    with patch("src.cli.report.generate_rule_hit_count_report", side_effect=exc):
        result = runner.invoke(report_group, ["rule-hit-count"])
    assert result.exit_code == EXIT_UNAVAILABLE


def test_rule_hit_count_click_exception_maps_to_dataerr():
    runner = CliRunner()
    with patch("src.cli.report.generate_rule_hit_count_report",
               side_effect=click.ClickException("no data")):
        result = runner.invoke(report_group, ["rule-hit-count"])
    assert result.exit_code == EXIT_DATAERR
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_cli_report_rule_hit_count.py -v`
Expected: FAIL — `"rule-hit-count" not in report_group.commands`

- [ ] **Step 3: 實作 helper + 精靈 + 指令**

`src/cli/report.py`（helper 區）：

```python
def generate_rule_hit_count_report(
    *,
    source: str = "native",
    file_path: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
) -> list[str]:
    """Raises RuleHitCountNotEnabled (native source) for the command layer to handle."""
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.rule_hit_count_generator import RuleHitCountGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    gen = RuleHitCountGenerator(cm, api_client=api, config_dir=config_dir)
    if source == "csv":
        if not file_path:
            raise click.ClickException(t("cli_report_file_required_csv", lang=lang))
        result = gen.generate_from_csv(file_path, lang=lang)
    else:
        result = gen.generate_from_native(
            start_date=_iso_date(start_date, end_of_day=False),
            end_date=_iso_date(end_date, end_of_day=True),
            lang=lang,
        )

    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


def _run_rhc_enablement_wizard(api, lang: str) -> bool:
    """Interactive enablement wizard (TTY only). Returns True if enable ran.

    WARNING shown to the operator: the VEN side writes draft firewall_settings
    and provisions — a production policy write.
    """
    import sys

    import questionary

    from src.cli.object_picker import pick_objects
    from src.report.rule_hit_count_enablement import EnablementError, enable_rule_hit_count

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False

    click.echo(t("cli_rhc_not_enabled_intro", lang=lang))
    click.echo(t("cli_rhc_provision_warning", lang=lang))
    if not questionary.confirm(t("cli_rhc_confirm_enable", lang=lang), default=False).unsafe_ask():
        click.echo(t("cli_rhc_enable_declined", lang=lang))
        return False

    scope_choice = questionary.select(
        t("cli_rhc_scope_question", lang=lang),
        choices=[
            questionary.Choice(t("cli_rhc_scope_all", lang=lang), value="all"),
            questionary.Choice(t("cli_rhc_scope_labels", lang=lang), value="labels"),
        ],
    ).unsafe_ask()

    scopes = None   # None → all VENs ([[]])
    if scope_choice == "labels":
        picked = pick_objects(api, ["label"], t("cli_rhc_scope_pick_title", lang=lang), lang=lang)
        kv_to_href = {f"{l['key']}={l['value']}": l.get("href", "")
                      for l in api.get_all_labels()}
        hrefs = [kv_to_href[v] for v in picked.get("labels", []) if kv_to_href.get(v)]
        if hrefs:
            scopes = [[{"label": {"href": h}} for h in hrefs]]

    try:
        steps = enable_rule_hit_count(api, scopes=scopes)
    except EnablementError as exc:
        click.echo(t("cli_rhc_enable_failed", steps=", ".join(exc.steps_done) or "-",
                     error=str(exc), lang=lang), err=True)
        return False
    click.echo(t("cli_rhc_enable_done", steps=", ".join(steps), lang=lang))
    click.echo(t("cli_rhc_ven_delay_note", lang=lang))
    return True
```

指令（加在 `report_policy_usage` 之後）：

```python
@report_group.command("rule-hit-count")
@click.option("--source", type=click.Choice(["native", "csv"]), default="native")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_rule_hit_count(
    ctx: click.Context,
    source: str,
    file_path,
    start_date: str | None,
    end_date: str | None,
    fmt: str,
    output_dir,
) -> None:
    """Generate Rule Hit Count Report (native PCE data, enriched with rule details)."""
    from src.report.rule_hit_count_enablement import RuleHitCountNotEnabled
    try:
        paths = generate_rule_hit_count_report(
            source=source,
            file_path=file_path,
            start_date=start_date,
            end_date=end_date,
            fmt=fmt,
            output_dir=output_dir,
        )
    except RuleHitCountNotEnabled as exc:
        lang = _ctx_lang()
        echo_error(ctx, t("cli_rhc_not_enabled", state=exc.status.state,
                          detail=exc.status.detail, lang=lang))
        from src.api_client import ApiClient
        from src.config import ConfigManager
        _run_rhc_enablement_wizard(ApiClient(ConfigManager()), lang)
        # Wizard never auto-generates (VENs need time to report) — exit either way.
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("rule-hit-count report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)
```

CLI i18n keys——`src/i18n_en.json`：

```json
  "cli_rhc_not_enabled": "Native Rule Hit Count is not available (state: {state}; {detail}). Use the Policy Usage report for traffic-approximated counts, or enable the native feature.",
  "cli_rhc_not_enabled_intro": "The native Rule Hit Count feature is not fully enabled on this PCE.",
  "cli_rhc_provision_warning": "WARNING: enabling writes draft firewall_settings and PROVISIONS the change to production policy. VENs older than 23.2.30 will not report.",
  "cli_rhc_confirm_enable": "Enable the native Rule Hit Count feature now?",
  "cli_rhc_enable_declined": "Enablement declined. You can use the Policy Usage report instead.",
  "cli_rhc_scope_question": "Enable on which VENs?",
  "cli_rhc_scope_all": "All VENs",
  "cli_rhc_scope_labels": "VENs matching specific labels",
  "cli_rhc_scope_pick_title": "Pick labels for the enablement scope",
  "cli_rhc_enable_done": "Rule Hit Count enabled (steps: {steps}).",
  "cli_rhc_enable_failed": "Enable failed after steps [{steps}]: {error}",
  "cli_rhc_ven_delay_note": "VENs need time to start reporting — generate the report again later.",
```

`src/i18n/data/zh_explicit.json`：

```json
  "cli_rhc_not_enabled": "原生 Rule Hit Count 不可用（狀態：{state}；{detail}）。可改用 Policy Usage 報表（流量近似計數），或啟用原生功能。",
  "cli_rhc_not_enabled_intro": "此 PCE 的原生 Rule Hit Count 功能尚未完整啟用。",
  "cli_rhc_provision_warning": "警告：啟用會寫入 draft firewall_settings 並「provision 到生產 policy」。VEN 版本低於 23.2.30 不會回報。",
  "cli_rhc_confirm_enable": "現在啟用原生 Rule Hit Count 功能？",
  "cli_rhc_enable_declined": "已取消啟用。可改用 Policy Usage 報表。",
  "cli_rhc_scope_question": "要對哪些 VEN 啟用？",
  "cli_rhc_scope_all": "全部 VEN",
  "cli_rhc_scope_labels": "符合指定 label 的 VEN",
  "cli_rhc_scope_pick_title": "選擇啟用範圍的 label",
  "cli_rhc_enable_done": "Rule Hit Count 已啟用（步驟：{steps}）。",
  "cli_rhc_enable_failed": "啟用失敗，已完成步驟 [{steps}]：{error}",
  "cli_rhc_ven_delay_note": "VEN 需要時間開始回報——請稍後再產生報表。",
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_cli_report_rule_hit_count.py tests/test_cli_report_policy_diff.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/cli/report.py tests/test_cli_report_rule_hit_count.py src/i18n_en.json src/i18n/data/zh_explicit.json
git commit -m "feat(cli): report rule-hit-count command with enablement wizard"
```

---

### Task 10: GUI 三個 route + GUI i18n keys

**Files:**
- Modify: `src/gui/routes/reports.py`（加在 policy_usage route :678-755 之後）、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`
- Test: `tests/test_gui_rule_hit_count_generate.py`

**Interfaces:**
- Consumes: `RuleHitCountGenerator`、`check_enablement` / `enable_rule_hit_count` / `RuleHitCountNotEnabled` / `EnablementError`、route 內既有 `cm/limiter/_resolve_config_dir/_resolve_reports_dir/_err_with_log/secure_filename/uuid`
- Produces:
  - `GET  /api/rule_hit_count/enablement` → `{ok, state, pce_report_enabled, ven_scopes_enabled, detail}`
  - `POST /api/rule_hit_count/enable`（body 空 = 全部 VEN；GUI v1 僅全部）→ `{ok, steps_done}` 或 `{ok: false, error, steps_done}`
  - `POST /api/rule_hit_count_report/generate`（source native|csv）→ 成功 `{ok, files, record_count, kpis}`；未啟用 `{ok: false, needs_enablement: true, state, detail}`

- [ ] **Step 1: 加 GUI i18n keys**

`src/i18n_en.json`：

```json
  "gui_btn_rhc_report": "Rule Hit Count Report",
  "gui_rcard_rhc_desc": "Native VEN-measured rule hit counts, enriched with full rule details",
  "gui_gen_rhc_title": "Generate Rule Hit Count Report",
  "gui_no_rhc_data": "The native report returned no rules.",
  "gui_sched_rt_rhc": "Rule Hit Count",
  "gui_toast_rhc_done": "Rule Hit Count report generated ({count} rules)",
  "gui_toast_rhc_fail": "Rule Hit Count report failed",
  "gui_toast_rhc_error": "Rule Hit Count report error: {error}",
  "gui_rhc_needs_enable_confirm": "Native Rule Hit Count is not enabled ({state}). Enable it now for ALL VENs? WARNING: this writes draft firewall_settings and PROVISIONS to production policy. (For label-scoped enablement use the CLI wizard.)",
  "gui_rhc_enabled_ok": "Enabled. VENs need time to start reporting — generate the report again later.",
  "gui_rhc_enable_failed": "Enable failed: {error}",
  "gui_rhc_use_pu_hint": "Not enabled — you can use the Policy Usage report (traffic-approximated counts) instead.",
```

`src/i18n/data/zh_explicit.json`：

```json
  "gui_btn_rhc_report": "規則命中次數報表",
  "gui_rcard_rhc_desc": "原生 VEN 實測規則命中次數，補完整規則明細",
  "gui_gen_rhc_title": "產生規則命中次數報表",
  "gui_no_rhc_data": "原生報表未回傳任何規則。",
  "gui_sched_rt_rhc": "規則命中次數報表",
  "gui_toast_rhc_done": "規則命中次數報表已產生（{count} 條規則）",
  "gui_toast_rhc_fail": "規則命中次數報表產生失敗",
  "gui_toast_rhc_error": "規則命中次數報表錯誤：{error}",
  "gui_rhc_needs_enable_confirm": "原生 Rule Hit Count 未啟用（{state}）。要立即對「全部 VEN」啟用嗎？警告：這會寫入 draft firewall_settings 並 provision 到生產 policy。（指定 label 範圍請改用 CLI 精靈。）",
  "gui_rhc_enabled_ok": "已啟用。VEN 需要時間開始回報——請稍後再產生報表。",
  "gui_rhc_enable_failed": "啟用失敗：{error}",
  "gui_rhc_use_pu_hint": "未啟用——可改用 Policy Usage 報表（流量近似計數）。",
```

- [ ] **Step 2: 寫失敗測試**

建立 `tests/test_gui_rule_hit_count_generate.py`：

```python
"""GUI endpoint tests for rule hit count enablement + generation routes."""
from unittest.mock import MagicMock, patch

from tests._helpers import _csrf

from src.report.rule_hit_count_enablement import EnablementStatus, RuleHitCountNotEnabled


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def _fake_result(count=3):
    r = MagicMock()
    r.record_count = count
    r.module_results = {"kpis": {"total_rules": count, "hit_rules": 1}}
    return r


def test_enablement_status_endpoint(client):
    _login(client)
    st = EnablementStatus("partial", True, False, "missing: VEN firewall_settings scopes")
    with patch("src.gui.routes.reports.check_enablement", return_value=st):
        r = client.get("/api/rule_hit_count/enablement",
                       environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["state"] == "partial"
    assert body["pce_report_enabled"] is True


def test_enable_endpoint_runs_enable(client):
    csrf_token = _login(client)
    with patch("src.gui.routes.reports.enable_rule_hit_count",
               return_value=["pce_report_template", "ven_firewall_settings_draft",
                             "provisioned"]) as en:
        r = client.post("/api/rule_hit_count/enable", json={},
                        headers={"X-CSRF-Token": csrf_token},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["steps_done"][-1] == "provisioned"
    # GUI v1 enables ALL VENs — scopes must be None
    assert en.call_args.kwargs.get("scopes") is None


def test_generate_native_returns_files(client):
    csrf_token = _login(client)
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_native.return_value = _fake_result()
        MockGen.return_value.export.return_value = [
            "/tmp/x/Illumio_Rule_Hit_Count_Report_x.html"]
        r = client.post(
            "/api/rule_hit_count_report/generate",
            json={"source": "native", "lang": "zh_TW", "format": "html"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["Illumio_Rule_Hit_Count_Report_x.html"]


def test_generate_not_enabled_returns_needs_enablement(client):
    csrf_token = _login(client)
    exc = RuleHitCountNotEnabled(EnablementStatus("disabled", False, False, "off"))
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_native.side_effect = exc
        r = client.post(
            "/api/rule_hit_count_report/generate",
            json={"source": "native", "lang": "en"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    body = r.get_json()
    assert body["ok"] is False
    assert body["needs_enablement"] is True
    assert body["state"] == "disabled"
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `python -m pytest tests/test_gui_rule_hit_count_generate.py -v`
Expected: FAIL — 404（route 不存在）

- [ ] **Step 4: 實作三個 route（policy_usage route 後、同一 blueprint factory 內；檔頭 import 區加 `from src.report.rule_hit_count_enablement import EnablementError, RuleHitCountNotEnabled, check_enablement, enable_rule_hit_count`）**

```python
    # ── API: Rule Hit Count（原生數據增強器）────────────────────────────────
    @bp.route('/api/rule_hit_count/enablement', methods=['GET'])
    def api_rule_hit_count_enablement():
        try:
            from src.api_client import ApiClient
            cm.load()
            api = ApiClient(cm)
            st = check_enablement(api)
            return jsonify({"ok": True, "state": st.state,
                            "pce_report_enabled": st.pce_report_enabled,
                            "ven_scopes_enabled": st.ven_scopes_enabled,
                            "detail": st.detail})
        except Exception as e:
            return _err_with_log("rule_hit_count_enablement", e, lang='en')

    @bp.route('/api/rule_hit_count/enable', methods=['POST'])
    @limiter.limit("5 per hour")
    def api_rule_hit_count_enable():
        d = request.get_json(silent=True) or {}
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.api_client import ApiClient
            cm.load()
            api = ApiClient(cm)
            # GUI v1: ALL VENs only (scopes=None → [[]]); label scopes via CLI wizard.
            steps = enable_rule_hit_count(api, scopes=None)
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("reports").info(f"Rule hit count enabled via GUI: {steps}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "steps_done": steps})
        except EnablementError as e:
            return jsonify({"ok": False, "error": str(e), "steps_done": e.steps_done})
        except Exception as e:
            return _err_with_log("rule_hit_count_enable", e, lang=lang)

    @bp.route('/api/rule_hit_count_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_rule_hit_count_report():
        d = request.get_json(silent=True) or request.form.to_dict() or {}
        _rhlog = None
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.rule_hit_count_generator import RuleHitCountGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _rhlog = _ML.get("reports")
                _rhlog.separator(f"Rule Hit Count Report {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')} UTC")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional

            cm.load()
            api = ApiClient(cm)
            config_dir = _resolve_config_dir()
            gen = RuleHitCountGenerator(cm, api_client=api, config_dir=config_dir)

            source = d.get('source', 'native')
            if source == 'csv':
                import tempfile
                if 'file' not in request.files or request.files['file'].filename == '':
                    return jsonify({"ok": False, "error": t("gui_err_no_csv", lang=lang)})
                csv_file = request.files['file']
                safe_name = secure_filename(csv_file.filename) or 'upload.csv'
                temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{safe_name}")
                csv_file.save(temp_path)
                try:
                    result = gen.generate_from_csv(temp_path, lang=lang)
                finally:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            else:
                try:
                    result = gen.generate_from_native(start_date=d.get('start_date'),
                                                      end_date=d.get('end_date'), lang=lang)
                except RuleHitCountNotEnabled as exc:
                    return jsonify({"ok": False, "needs_enablement": True,
                                    "state": exc.status.state,
                                    "detail": exc.status.detail,
                                    "error": t("gui_rhc_use_pu_hint", lang=lang)})

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_rhc_data", lang=lang)})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in ('html', 'csv', 'all') else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            filenames = [os.path.basename(p) for p in paths]
            kpis = (result.module_results or {}).get('kpis', {})
            try:
                if _rhlog:
                    _rhlog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames,
                            "record_count": result.record_count, "kpis": kpis})
        except Exception as e:
            try:
                if _rhlog:
                    _rhlog.error(f"Rule hit count report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_rule_hit_count_generate", e, lang=lang)
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/test_gui_rule_hit_count_generate.py tests/test_gui_policy_diff_generate.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/gui/routes/reports.py tests/test_gui_rule_hit_count_generate.py src/i18n_en.json src/i18n/data/zh_explicit.json
git commit -m "feat(gui): rule hit count enablement and generate endpoints"
```

---

### Task 11: GUI 前端（卡片 + modal + 啟用確認 + 排程選項）

**Files:**
- Modify: `src/templates/index.html`（policy_usage rcard :1373-1387 之後；排程下拉 :1526 之後）
- Modify: `src/static/js/dashboard.js`（:312 排程 typeLabels、:635 modal meta、:657 source 分支、:731 confirmReportGen、新函式 `_doGenerateRuleHitCount`）

**Interfaces:**
- Consumes: Task 10 的三個 route、既有 modal 元件（`m-gen-*`）、`_t()` i18n、Task 10 的 gui keys

- [ ] **Step 1: index.html — rcard 卡片（插在 policy_usage 卡之後）**

```html
        <div class="rcard" data-rtype="rule_hit_count">
          <div class="rcard-icon"><svg class="icon" aria-hidden="true"><use href="#icon-shield"></use></svg></div>
          <div class="rcard-body">
            <h3 data-i18n="gui_btn_rhc_report">Rule Hit Count Report</h3>
            <p data-i18n="gui_rcard_rhc_desc">Native VEN-measured rule hit counts, enriched with full rule details</p>
            <div class="rcard-meta"><span class="rcard-meta-last"></span><span class="rcard-meta-sched" style="display:none;"></span></div>
            <div style="display:flex;gap:6px;margin-top:10px;">
              <button class="btn btn-primary btn-sm" id="btn-gen-rhc" data-action="openReportGenModal" data-args='["rule_hit_count"]'>
                <svg class="icon"><use href="#icon-shield"></use></svg> <span data-i18n="gui_gen_generate">Generate</span>
              </button>
            </div>
          </div>
        </div>
```

- [ ] **Step 2: index.html — 排程下拉選項（`policy_usage` option 之後）**

```html
            <option value="rule_hit_count" data-i18n="gui_sched_rt_rhc">Rule Hit Count Report</option>
```

- [ ] **Step 3: dashboard.js — 四處註冊**

(1) 排程列表 typeLabels（:312 附近）加：

```javascript
    rule_hit_count: _t('gui_sched_rt_rhc'),
```

(2) `openReportGenModal` 的 meta（:635 附近）加：

```javascript
    rule_hit_count: { titleKey: 'gui_gen_rhc_title', icon: '#icon-shield', dates: true  },
```

(3) source-row 分支（:657）改為同時涵蓋兩型別（radio 值沿用 api/csv；rule_hit_count 的 `api` 值在送出時對映為 `native`）：

```javascript
  } else if (type === 'policy_usage' || type === 'rule_hit_count') {
    // Both support source selection (no traffic filters/profile).
```

(4) `confirmReportGen`（:731 附近）typeLabels 加 `rule_hit_count: _t('gui_gen_rhc_title'),`，dispatch 鏈加：

```javascript
  else if (_genReportType === 'rule_hit_count') await _doGenerateRuleHitCount();
```

- [ ] **Step 4: dashboard.js — `_doGenerateRuleHitCount`（放在 `_doGeneratePolicyUsageClean` 之後；含未啟用時的確認 + 啟用流程）**

```javascript
async function _doGenerateRuleHitCount() {
  const fmtEl = document.getElementById('m-gen-format');
  const fmt = fmtEl ? fmtEl.value : 'html';
  _updateGenStep(_t('gui_gen_step_fetching'));
  try {
    const start = $('m-gen-start') ? $('m-gen-start').value : null;
    const end   = $('m-gen-end')   ? $('m-gen-end').value   : null;
    const langEl = document.getElementById('m-gen-lang');
    const lang = langEl ? langEl.value : 'en';
    const src = document.querySelector('input[name="traffic-source"]:checked')?.value || 'api';
    let r;
    if (src === 'csv') {
      const fileInput = $('m-gen-csv-file');
      if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        _hideGenProgress(false, _t('gui_csv_required'));
        toast(_t('gui_err_no_csv'), 'err');
        return;
      }
      const fd = new FormData();
      fd.append('source', 'csv');
      fd.append('format', fmt);
      fd.append('lang', lang);
      fd.append('file', fileInput.files[0]);
      r = await fetch('/api/rule_hit_count_report/generate', {
        method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() }, body: fd
      }).then(res => res.json());
    } else {
      r = await post('/api/rule_hit_count_report/generate',
                     { source: 'native', start_date: start, end_date: end, format: fmt, lang: lang });
    }
    if (r.ok) {
      const k = r.kpis || {};
      const kpiText = Object.entries(k).map(([key, val]) => `${key}: ${val}`).join(' | ');
      _hideGenProgress(true, kpiText || _t('gui_gen_done'));
      toast((_t('gui_toast_rhc_done')).replace('{count}', r.record_count));
      loadReports();
      if (typeof loadRcardMeta === 'function') loadRcardMeta();
    } else if (r.needs_enablement) {
      _hideGenProgress(false, r.error || _t('gui_toast_rhc_fail'));
      const msg = (_t('gui_rhc_needs_enable_confirm')).replace('{state}', r.state || '');
      if (window.confirm(msg)) {
        const en = await post('/api/rule_hit_count/enable', { lang: lang });
        if (en.ok) {
          toast(_t('gui_rhc_enabled_ok'));
        } else {
          toast((_t('gui_rhc_enable_failed')).replace('{error}', en.error || ''), 'err');
        }
      } else {
        toast(r.error || _t('gui_toast_rhc_fail'), 'err');
      }
    } else {
      _hideGenProgress(false, r.error || _t('gui_toast_rhc_fail'));
      toast(r.error || _t('gui_toast_rhc_fail'), 'err');
    }
  } catch (e) {
    _hideGenProgress(false, e.message);
    toast((_t('gui_toast_rhc_error')).replace('{error}', e.message), 'err');
  }
}
```

- [ ] **Step 5: 手動驗證前端接線**

Run: `python -m pytest tests/ -k "gui" -q`（確認無回歸），再啟動 GUI 檢查：
1. Reports 頁出現「Rule Hit Count Report」卡片；
2. 點 Generate 開 modal，來源 radio 顯示、切 csv 顯示上傳欄；
3. 排程 modal 的 Report Type 下拉出現「Rule Hit Count」；
4. 對未啟用的 PCE（或 mock）點產生 → 出現含 provision 警告的確認框，取消不發啟用請求。
Expected: 四項皆成立

- [ ] **Step 6: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js
git commit -m "feat(gui): rule hit count report card, enable confirm flow, and schedule option"
```

---

### Task 12: 端到端驗證（CLAUDE.md 報表截斷檢查）

**Files:**
- 無新程式碼；驗證紀錄附在完成回報中

- [ ] **Step 1: 全測試套件**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 2: 用實際樣本 CSV 跑完整輸出**

```bash
mkdir -p /tmp/rhc-verify && cat > /tmp/rhc-verify/sample.csv <<'EOF'
Rule HREF,Rule Name,Rule Set HREF,Rule Set Name,Rule Hit Count,Days Since Last Hit,Start Date,End Date
/orgs/1/sec_policy/active/rule_sets/10/sec_rules/100,allow web frontends to talk to the shared postgres cluster in production east datacenter zone A,/orgs/1/sec_policy/active/rule_sets/10,RS-Production-Core-Services-East,42,3,2026-06-01,2026-07-01
/orgs/1/sec_policy/active/rule_sets/10/sec_rules/101,stale allow,/orgs/1/sec_policy/active/rule_sets/10,RS-Production-Core-Services-East,5,120,2026-06-01,2026-07-01
/orgs/1/sec_policy/active/rule_sets/11/deny_rules/200,deny legacy telnet,/orgs/1/sec_policy/active/rule_sets/11,RS-Legacy,0,,2026-06-01,2026-07-01
EOF
python -m src.cli.main report rule-hit-count --source csv --file /tmp/rhc-verify/sample.csv --format all --output-dir /tmp/rhc-verify
```

（CLI 進入點若非 `python -m src.cli.main`，用 repo 既有 CLI 啟動方式。）
Expected: 一個 `Illumio_Rule_Hit_Count_Report_*.html`、一個 `*_raw.zip`、各附 `.metadata.json`

- [ ] **Step 3: 逐頁檢查截斷與溢出（CLAUDE.md 規則）**

瀏覽器開 HTML，逐節檢查並記錄：
1. 封面：標題、日期區間（2026-06-01 – 2026-07-01）正確；
2. 語意注記：VEN 實測、規則最佳化高估、90 天保留三條皆顯示；
3. KPI：total 3 / hit 2 / unused 1 / rate 66.7% / hits 47；
4. 有命中規則表：長 Rule Name（>160 字時）顯示 `…` 且 hover title 完整；窄視窗下表格於容器內水平捲動不撐破版面；
5. 清理候選表：rule 101（120 天）在列、rule 100 不在列（未 enrich 時 enabled 為空、本節可為空——附註記錄實際行為）；
6. 解開 `_raw.zip` 抽查 `all_rules.csv`：長欄位完整未截斷；
7. zh_TW 再跑一次，中文欄名無亂碼、無 key 名裸露。
Expected: 全過；結果列在完成回報

- [ ] **Step 4: （有測試環境 PCE 時）native 模式煙霧測試**

```bash
python -m src.cli.main report rule-hit-count --source native --output-dir /tmp/rhc-verify
```

Expected: 未啟用 → 顯示不可用訊息 + 精靈詢問（TTY）；已啟用 → 正常拉取產出。無測試 PCE 時標記 skipped 並在回報註明

- [ ] **Step 5: 最終 commit（若驗證期間有修正）**

```bash
git add -A && git commit -m "test(report): rule hit count end-to-end verification fixes"
```

---

## Self-Review 紀錄

- Spec 覆蓋：偵測三態+版本門檻（Task 2）、啟用精靈含 provision 警告與半途失敗處理（Task 2/9/10/11）、原生 API 拉取含輪詢逾時（Task 3）、CSV 備援（Task 4）、enrichment 非致命（Task 4）、三節結構+清理候選 90 天（Task 4/6）、語意注記（Task 6）、fallback 只提示（Task 8 scheduler skip、Task 9 CLI、Task 10/11 GUI hint）、排程絕不詢問（Task 8）、截斷政策（Task 6 + Task 12 驗證）、6 掛載點全落任務。
- 型別一致：`EnablementStatus/RuleHitCountNotEnabled/EnablementError`（Task 2）↔ Task 5/8/9/10 使用一致；`pull_rule_hit_count_report` 簽名 Task 3 ↔ Task 5；DataFrame 欄位 Task 4 ↔ Task 6/7；prefix 與檔名 `Illumio_Rule_Hit_Count_Report_` 三處（exporter/CsvExporter label/`_REPORT_PREFIXES`）一致。
- 已知執行時留意點：原生 CSV 實際欄名以客戶匯出檔為準（`_CSV_ALIASES` 擴充點）；report 輪詢的 status 字串以實際 PCE 回應為準（`done/failed` 之外若有 `queued/pending` 均視為進行中，程式已如此處理）；`GET /sec_policy/active/firewall_settings` 若客戶從未 provision 過任何 firewall_settings 可能回非 200——實作時若遇到，fallback 讀 draft 並記錄。
