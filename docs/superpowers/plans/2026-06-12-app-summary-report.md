# App-centric 報表（App Summary Report）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增第 7 種報表「App Summary」— 以單一 App Label 為範圍的應用視角報表（連線基準、政策覆蓋、發現事項），補上 PCE 內建 App Group Summary 在 illumio-ops 中沒有對應物的缺口，服務 app owner 與 PCI/HIPAA 稽核情境。

**Architecture:** 不新造分析引擎 — 沿用 ReportGenerator 取流量 df，**pandas 後過濾**到單一 app（src_app==X 或 dst_app==X），重跑既有模組子集（mod01/02/03 + findings），加兩張 app 專屬基準表（inbound services / outbound dependencies）。獨立 facade `AppSummaryReport`（仿 PolicyDiffReport 形狀）+ 獨立 HTML exporter（仿 audit exporter 的 standalone 模式，非 _TrafficReportBase profile）。CLI + GUI 卡 + 排程分支全套接線（report-type 註冊模式已盤點，無中央 registry，5 處接點）。

**Tech Stack:** Python / pandas / Flask / vanilla JS / pytest；i18n 雙檔 + glossary。

**拍板的設計決策（執行前如不同意請先說）：**
1. **範圍鍵 = App Label 值**（必填），可選 `--env` 二次過濾。v1 不支援多 app、不支援 label group。
2. **後過濾而非 PCE 查詢過濾**：抓全量 df 再 pandas 過濾，避免 PCE traffic query 的 src/dst OR 語意陷阱；副作用是 API 抓取量與全量報表相同（lab 規模可接受；之後可優化）。
3. **內容六節**（v1）：封面+KPI、Inbound 服務基準、Outbound 依賴基準、政策覆蓋（mod03 子集）、本 app 相關 Findings、附錄（資料範圍說明）。**不含** drift（estate 簽章檔與 app 範圍不對齊，v2 再做 per-app 簽章）。
4. 排程支援：report_type `app_summary`，排程設定多存一個 `app`（與可選 `env`）參數。
5. 檔名：`Illumio_App_Summary_{app}_{ts}.html`（app 值做檔名安全化）。

**執行環境：** worktree + venv symlink。基線 `./venv/bin/python -m pytest tests/ -q`（以執行當下 main 為準，2026-06-12 時為 1740 passed, 5 skipped）。

---

## 已驗證事實（grounding）

| 事實 | 出處 |
|------|------|
| mod13 `app_env_scorecards` 欄位：app_env_key/app_display/readiness_score/policy_coverage_ratio/ringfence_maturity_ratio/enforcement_mode_ratio/staged_readiness_ratio/potentially_blocked_ratio/remote_app_coverage_ratio/flow_count/connection_count… | mod13_readiness.py:133-150 |
| 流量 df 欄位：src_app/dst_app/src_env/dst_env/port/proto/policy_decision/num_connections/src_ip/dst_ip/src_managed/dst_managed | api_parser.py:73-116 |
| 模組函式契約：`(df, top_n, lang)` 經 adapters；mod01/02/03 可直接以過濾後 df 重跑 | analysis/__init__.py:26-51 |
| 新報表型別 5 接點：CLI（cli/report.py:144-158 模式）、generator facade（ven_status_generator.py:91-159 模式）、standalone exporter（audit_html_exporter.py 模式）、GUI 路由（reports.py:325-369 policy_diff 模式）、排程 tick() elif 分支（report_scheduler.py:186-310）+ dashboard.js typeLabels | Q12 盤點 |
| GUI modal meta 表支援 per-type 設定（dates: true/false）；新增欄位需擴 modal markup | dashboard.js:638-660 |
| findings 由 RulesEngine.evaluate(df) 產生 — 對過濾後 df 重跑即得「本 app 相關」findings | report_generator.py:558-560 |
| `send_report_email` 既有寄送路徑 | reporter.py |

## 檔案結構

```
src/report/analysis/mod_app_baseline.py    # T1: inbound/outbound 基準表（純函式）
src/report/app_summary_report.py           # T2: facade（fetch→filter→modules→export）
src/report/exporters/app_summary_html_exporter.py  # T3: standalone exporter
src/cli/report.py                          # T4: app-summary 子命令
src/gui/routes/reports.py                  # T5: /api/app_report/generate
src/templates/index.html                   # T5: 第 7 張卡 + modal app 輸入欄
src/static/js/dashboard.js                 # T5: meta/dispatch/_doGenerateAppSummary
src/report_scheduler.py                    # T6: app_summary tick 分支
src/i18n_en.json, src/i18n_zh_TW.json      # T3/T5 keys
tests/test_mod_app_baseline.py / test_app_summary_report.py /
tests/test_gui_app_report_generate.py      # 新測試
```

---

### Task 1: App 基準表模組（純函式）

**Files:** Create `src/report/analysis/mod_app_baseline.py`；Test `tests/test_mod_app_baseline.py`

- [ ] **Step 1（失敗測試）:**

```python
# tests/test_mod_app_baseline.py
"""Per-app inbound/outbound connection baseline tables."""
import pandas as pd

from src.report.analysis.mod_app_baseline import app_baseline, filter_app_flows


def _df():
    return pd.DataFrame([
        # inbound to DB
        {"src_app": "Web", "src_env": "Prod", "dst_app": "DB", "dst_env": "Prod",
         "port": 3306, "proto": "TCP", "policy_decision": "allowed", "num_connections": 9,
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.5"},
        # outbound from DB
        {"src_app": "DB", "src_env": "Prod", "dst_app": "Backup", "dst_env": "Prod",
         "port": 443, "proto": "TCP", "policy_decision": "potentially_blocked", "num_connections": 2,
         "src_ip": "10.0.0.5", "dst_ip": "10.0.0.9"},
        # unrelated
        {"src_app": "Web", "src_env": "Prod", "dst_app": "Cache", "dst_env": "Prod",
         "port": 6379, "proto": "TCP", "policy_decision": "allowed", "num_connections": 7,
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.6"},
    ])


def test_filter_app_flows_keeps_both_directions():
    sub = filter_app_flows(_df(), app="DB")
    assert len(sub) == 2
    assert set(sub["dst_app"]) | set(sub["src_app"]) >= {"DB"}


def test_filter_with_env():
    assert len(filter_app_flows(_df(), app="DB", env="Prod")) == 2
    assert len(filter_app_flows(_df(), app="DB", env="Dev")) == 0


def test_baseline_tables():
    res = app_baseline(_df(), app="DB")
    inb = res["inbound"]
    assert list(inb.iloc[0][["Src App", "Port", "Proto"]]) == ["Web", 3306, "TCP"]
    assert inb.iloc[0]["Decision"] == "allowed"
    out = res["outbound"]
    assert list(out.iloc[0][["Dst App", "Port"]]) == ["Backup", 443]
    assert res["inbound_count"] == 1 and res["outbound_count"] == 1
```

- [ ] **Step 2:** run → FAIL（ModuleNotFoundError）。
- [ ] **Step 3（實作）:**

```python
# src/report/analysis/mod_app_baseline.py
"""Per-app connection baseline — the App Group Summary concept for one app.

PURE functions. filter_app_flows() scopes the estate DataFrame to flows where
the app is source OR destination (optional env refinement); app_baseline()
summarizes inbound services and outbound dependencies for the app owner /
auditor reader.
"""
from __future__ import annotations

import pandas as pd


def filter_app_flows(df: pd.DataFrame, app: str, env: str | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    src_hit = df["src_app"].fillna("") == app
    dst_hit = df["dst_app"].fillna("") == app
    if env:
        src_hit &= df["src_env"].fillna("") == env
        dst_hit &= df["dst_env"].fillna("") == env
    return df[src_hit | dst_hit].copy()


def _grouped(sub: pd.DataFrame, peer_col: str, top_n: int) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame()
    g = (sub.groupby([peer_col, "port", "proto", "policy_decision"], dropna=False)
            ["num_connections"].sum().reset_index()
            .sort_values("num_connections", ascending=False).head(top_n))
    g.columns = [ {"src_app": "Src App", "dst_app": "Dst App"}[peer_col],
                  "Port", "Proto", "Decision", "Connections" ]
    return g.reset_index(drop=True)


def app_baseline(df: pd.DataFrame, app: str, env: str | None = None, top_n: int = 30) -> dict:
    scoped = filter_app_flows(df, app, env)
    inbound = scoped[scoped["dst_app"].fillna("") == app]
    outbound = scoped[scoped["src_app"].fillna("") == app]
    return {
        "app": app,
        "env": env or "",
        "flow_count": int(len(scoped)),
        "inbound_count": int(len(_grouped(inbound, "src_app", 10**9))) if not inbound.empty else 0,
        "outbound_count": int(len(_grouped(outbound, "dst_app", 10**9))) if not outbound.empty else 0,
        "inbound": _grouped(inbound, "src_app", top_n),
        "outbound": _grouped(outbound, "dst_app", top_n),
    }
```

（`inbound_count`/`outbound_count` = 去重後的基準列數，與測試一致；若效能在大 df 上成疑，改成 groupby ngroups — 行為相同。）
- [ ] **Step 4:** 測試 3 passed。Commit `feat(report): per-app inbound/outbound baseline module`

### Task 2: AppSummaryReport facade

**Files:** Create `src/report/app_summary_report.py`；Test `tests/test_app_summary_report.py`

- [ ] **Step 1（失敗測試）:**

```python
# tests/test_app_summary_report.py
"""App Summary facade: fetch → scope → modules subset → export."""
import pandas as pd
from unittest.mock import MagicMock, patch

from src.report.app_summary_report import AppSummaryReport, _safe_filename_token


def test_safe_filename_token():
    assert _safe_filename_token("My App/v2 (Prod)") == "My_App_v2_Prod"


def test_build_scopes_and_runs_modules():
    df = pd.DataFrame([
        {"src_app": "Web", "src_env": "P", "dst_app": "DB", "dst_env": "P", "port": 3306,
         "proto": "TCP", "policy_decision": "allowed", "num_connections": 1,
         "src_ip": "a", "dst_ip": "b", "src_managed": True, "dst_managed": True},
        {"src_app": "Web", "src_env": "P", "dst_app": "Cache", "dst_env": "P", "port": 6379,
         "proto": "TCP", "policy_decision": "allowed", "num_connections": 1,
         "src_ip": "a", "dst_ip": "c", "src_managed": True, "dst_managed": True},
    ])
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        result = rep.build(app="DB", lang="en")
    assert result["app"] == "DB"
    assert result["baseline"]["flow_count"] == 1            # 只剩 DB 相關
    assert result["mod01"]["total_flows"] == 1              # 模組看到的是已過濾 df
    assert "findings" in result


def test_build_unknown_app_flags_empty():
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=pd.DataFrame()):
        result = rep.build(app="Nope", lang="en")
    assert result["empty"] is True
```

- [ ] **Step 2:** run → FAIL。
- [ ] **Step 3（實作）:** 先讀 `ReportGenerator.generate_from_api` 的抓取段（report_generator.py:200-320）確認可重用的「抓 df」最小路徑（含 cache short-circuit）；facade 形狀：

```python
# src/report/app_summary_report.py
"""App Summary report — single-app view for app owners and auditors.

Mirrors the PolicyDiffReport facade shape: __init__(cm, api_client, ...),
build() returns module_results, run() exports HTML. Reuses ReportGenerator's
traffic fetch, then scopes the DataFrame to one App Label (post-filter) and
re-runs a module subset (mod01/02/03 + RulesEngine findings) plus the
app-baseline tables.
"""
from __future__ import annotations

import re

from loguru import logger

from src.report.analysis.mod_app_baseline import app_baseline, filter_app_flows


def _safe_filename_token(value: str) -> str:
    token = re.sub(r"[^\w.-]+", "_", value.strip())
    return token.strip("_") or "app"


class AppSummaryReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None):
        self.cm = cm
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader

    def _fetch_estate_df(self, start_date=None, end_date=None):
        """Fetch the estate traffic DataFrame via ReportGenerator's API path."""
        from src.report.report_generator import ReportGenerator
        gen = ReportGenerator(config_manager=self.cm, api_client=self.api,
                              config_dir=self._config_dir, cache_reader=self._cache)
        return gen.fetch_traffic_df(start_date=start_date, end_date=end_date)
        # ↑ 若 ReportGenerator 沒有獨立的 fetch_traffic_df，將 generate_from_api 的
        #   「查詢→DataFrame」段抽成該方法（重構而非複製；既有 generate_from_api 改為呼叫它），
        #   並為此重構跑 pytest -k report_generator 確認無回歸。

    def build(self, app: str, env: str | None = None, lang: str = "en",
              start_date=None, end_date=None) -> dict:
        df = self._fetch_estate_df(start_date=start_date, end_date=end_date)
        scoped = filter_app_flows(df, app, env)
        if scoped.empty:
            return {"app": app, "env": env or "", "empty": True}

        from src.report.analysis.mod01_traffic_overview import traffic_overview
        from src.report.analysis.mod02_policy_decisions import policy_decision_analysis
        from src.report.analysis.mod03_uncovered_flows import uncovered_flows
        from src.report.rules_engine import RulesEngine

        results: dict = {"app": app, "env": env or "", "empty": False}
        results["baseline"] = app_baseline(df, app, env)
        results["mod01"] = traffic_overview(scoped)
        results["mod02"] = policy_decision_analysis(scoped, top_n=10, lang=lang)
        results["mod03"] = uncovered_flows(scoped, top_n=10, lang=lang)
        engine = RulesEngine(getattr(self.cm, "config", {}).get("report", {}) if self.cm else {},
                             config_dir=self._config_dir, lang=lang)
        results["findings"] = engine.evaluate(scoped)
        return results
        # ↑ mod01/02/03 與 RulesEngine 的實際簽名以 analysis/__init__.py adapters 與
        #   report_generator.py:558 為準（上面是依盤點寫的；不符就照實際簽名調整並更新測試 fixture）。

    def run(self, app: str, env: str | None = None, output_dir: str = "reports",
            lang: str = "en", start_date=None, end_date=None) -> str:
        results = self.build(app=app, env=env, lang=lang,
                             start_date=start_date, end_date=end_date)
        from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
        return AppSummaryHtmlExporter(results, lang=lang).export(output_dir)
```

- [ ] **Step 4:** 測試 3 passed（exporter 尚不存在 — `run()` 的測試留到 T3；本任務測 build 與 token）。Commit `feat(report): AppSummaryReport facade (fetch → scope → module subset)`

### Task 3: AppSummaryHtmlExporter（standalone）

**Files:** Create `src/report/exporters/app_summary_html_exporter.py`；Modify i18n 兩檔；Test 加到 `tests/test_app_summary_report.py`

- [ ] **Step 1（失敗測試）:**

```python
def test_export_writes_html(tmp_path):
    results = {  # 最小 build() 形狀（沿用 test_build 的 df 跑 build 取得真實 results 更佳）
        ...
    }
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    path = AppSummaryHtmlExporter(results, lang="zh_TW").export(str(tmp_path))
    html = open(path, encoding="utf-8").read()
    assert "App Summary" in html or "App 摘要" in html
    assert 'id="inbound"' in html and 'id="outbound"' in html
    assert "Illumio_App_Summary_DB_" in path
```

（實作方式：直接在測試裡呼叫 T2 的 `build()`（mock fetch）取得真 results 餵 exporter — 不要手寫假 results dict。）
- [ ] **Step 2（實作）:** 仿 `policy_diff_html_exporter.py` 的 self-contained 結構（`__init__(results, lang)` + `export(output_dir) -> path`），但使用主報表的 `report_css` 與 cover page（`from .report_css import ...`、`from .cover_page import _build_cover_page` — 先 grep 兩者的實際匯出名）。六節：
  1. 封面（title=`t('rpt_app_title', lang)` + app 名、日期範圍）
  2. KPI 列（flow_count / inbound_count / outbound_count / mod03 coverage）
  3. `id="inbound"`：`_df_to_html(baseline['inbound'])`（沿用 table_renderer 的 `render_df_table` — grep 實際函式名）
  4. `id="outbound"`：同上
  5. `id="coverage"`：mod03 子集（enforced/staged/true gap 三數字 + top uncovered for this app）
  6. `id="findings"`：findings 卡（重用 html_exporter 的 `_findings_html` 不可行 — 它是 method；v1 用簡表：severity/rule_id/description，每列一 finding）
  檔名：`Illumio_App_Summary_{_safe_filename_token(app)}_{ts}.html`。
- [ ] **Step 3（i18n 兩檔）:** `rpt_app_title`: "Illumio App Summary Report" / "Illumio App 摘要報表"、`rpt_app_inbound`: "Inbound Services Baseline" / "Inbound 服務基準"、`rpt_app_outbound`: "Outbound Dependencies" / "Outbound 依賴"、`rpt_app_coverage`: "Policy Coverage (this app)" / "Policy 覆蓋（本 App）"、`rpt_app_findings`: "Findings involving this app" / "涉及本 App 的發現"、`rpt_app_empty`: "No flows observed for this App Label in the selected window." / "選定期間內未觀察到此 App Label 的流量。"（empty=True 時輸出含此 note 的單頁報表，而非報錯）。
- [ ] **Step 4:** 測試 passed；i18n audit 0；glossary 測試 passed。Commit `feat(report): App Summary HTML exporter`

### Task 4: CLI 子命令

**Files:** Modify `src/cli/report.py`；Test `tests/test_app_summary_report.py` 加 CLI 測試（仿 tests/test_cli_report_policy_diff.py 的 invoke+mock 模式）

- [ ] **Step 1（失敗測試）:** 仿 test_cli_report_policy_diff.py：invoke `report app-summary --app DB --env Prod --output-dir /tmp/x`，patch facade，斷言以 `app="DB", env="Prod"` 呼叫 `run`；缺 `--app` 時 exit code != 0。
- [ ] **Step 2（實作）:** 仿 policy-diff 子命令 decorator 結構：

```python
@click.option("--app", required=True, help="App Label value to scope the report to.")
@click.option("--env", default=None, help="Optional Env Label refinement.")
@click.option("--days", type=int, default=7, show_default=True, help="Lookback window.")
@click.option("--output-dir", ...)
@click.option("--lang", ...)
```

組 start/end（now - days）後呼叫 `AppSummaryReport(...).run(...)`，輸出路徑 print。命令名 `app-summary`（加 alias `generate-app-summary` 比照其他命令的 alias 慣例）。
- [ ] **Step 3:** 測試 passed；`./venv/bin/python illumio-ops.py report app-summary --help` 渲染正常。Commit `feat(cli): report app-summary command`

### Task 5: GUI 卡片 + 端點 + modal app 輸入欄

**Files:** Modify `src/gui/routes/reports.py`、`src/templates/index.html`、`src/static/js/dashboard.js`、i18n 兩檔；Test `tests/test_gui_app_report_generate.py`

- [ ] **Step 1（失敗測試）:** 仿 tests/test_gui_policy_diff_generate.py：POST `/api/app_report/generate` json `{app: "DB", lang: "zh_TW"}` → ok + files；缺 app → 400 與錯誤訊息；bad lang fallback en。
- [ ] **Step 2（路由）:** 鏡像 policy_diff 路由（limiter 10/hr、handler 內 import、`_err_with_log("report_app_summary_generate", ...)`）；必填驗證：

```python
        app = (d.get('app') or '').strip()
        if not app:
            return jsonify({"ok": False, "error": t("gui_app_required", lang=lang)}), 400
```

`run(app=app, env=d.get('env') or None, output_dir=..., lang=lang, start_date=..., end_date=...)`（日期沿用 traffic 端點的 start/end 解析 idiom）。
- [ ] **Step 3（前端）:** index.html：第 7 張 rcard（`data-args='["app_summary"]'`）；modal 內加 app/env 兩個 text input（`id="m-gen-app"`、`id="m-gen-env"`，預設 `display:none`）。dashboard.js：meta 加 `app_summary: { titleKey: 'gui_gen_app_title', icon: '#icon-shield', dates: true, appField: true }`；openReportGenModal 依 `meta.appField` 顯示/隱藏該兩欄；`_doGenerateAppSummary()`（驗證 app 非空 → POST → 成功路徑同其他 + `loadRcardMeta` 前綴 `Illumio_App_Summary_`）；dispatch 分支。
- [ ] **Step 4（i18n）:** en/zh：`gui_gen_app_title`: "Generate App Summary Report" / "產生 App 摘要報表"、`gui_rcard_app_title`: "App Summary Report" / "App 摘要報表"、`gui_rcard_app_desc`: "Single-App connection baseline + Policy coverage for app owners and audits" / "單一 App 的連線基準與 Policy 覆蓋，供 app owner 與稽核使用"、`gui_app_label_field`: "App Label" / "App Label"、`gui_env_label_field`: "Env Label (optional)" / "Env Label（選填）"、`gui_app_required`: "App Label is required." / "必須指定 App Label。"、toast done/fail 兩鍵。
- [ ] **Step 5:** 測試 passed；node --check；i18n audit 0；`pytest -k "gui or reports" | tail -1` 無新失敗。Commit `feat(gui): App Summary report card + /api/app_report/generate`

### Task 6: 排程支援

**Files:** Modify `src/report_scheduler.py`（tick() elif 分支）、`src/gui/routes/reports.py`（schedule create/update 接受 app/env 參數）、`src/static/js/dashboard.js`（排程表單 type 下拉加 app_summary + app 欄）；Test：仿既有 scheduler 測試（grep -rln "report_scheduler" tests/ 找範本）加一個 tick 分支測試

- [ ] **Step 1（失敗測試）:** 仿既有 scheduler 測試 fixture：schedule dict `{report_type: "app_summary", app: "DB", ...}` → tick() 呼叫 AppSummaryReport.run（patch 斷言參數）；缺 app 的 app_summary 排程 → 寫入 error 狀態而非 crash。
- [ ] **Step 2（實作）:** report_scheduler.py tick() 的 elif 鏈（:276-310）加：

```python
            elif report_type == "app_summary":
                from src.report.app_summary_report import AppSummaryReport
                app = (schedule.get("app") or "").strip()
                if not app:
                    raise ValueError("app_summary schedule requires an 'app' value")
                rep = AppSummaryReport(cm, api_client=api, config_dir=config_dir,
                                       cache_reader=cache_reader)
                paths = [rep.run(app=app, env=schedule.get("env") or None,
                                 output_dir=output_dir, lang=lang)]
```

（變數名以該函式實際區域變數為準；email 寄送沿用該函式既有的 paths→email 流程。）schedule create/update 路由的允許欄位加 app/env；dashboard.js 排程表單 typeLabels 加 app_summary 並在選中時顯示 app/env 欄。
- [ ] **Step 3:** 測試 passed；`pytest -k "scheduler" | tail -1` 無新失敗。Commit `feat(report): app_summary schedule type (per-app recurring reports)`

---

## 完成後整體驗證

```bash
./venv/bin/python -m pytest tests/ -q && ./venv/bin/python scripts/audit_i18n_usage.py
# lab e2e：
./venv/bin/python illumio-ops.py report app-summary --app CoreServices --days 7 --output-dir /tmp/x --lang zh_TW
# → HTML 有六節、檔名含 App token；GUI 第 7 張卡可填 App 產生；排程建立 app_summary 型別成功執行一次。
```

## Self-Review 紀錄
- 五個拍板決策列於開頭（範圍鍵、後過濾、六節內容、排程參數、檔名）供執行前否決。
- 兩處刻意的「依實際碼調整」點都給了重構準則與回歸測試指令（T2 `_fetch_estate_df` 抽取、build 內模組簽名），不是開放式 TBD。
- drift 明確排除並說明理由（estate 簽章 vs app 範圍不對齊）；多 app / label group / GUI 上傳皆 v2。
- 與 plan 2026-06-12-report-content-v2 無檔案衝突（html_exporter 本 plan 不碰 — exporter 是新檔）。
