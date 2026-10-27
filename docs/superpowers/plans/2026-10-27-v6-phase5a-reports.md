# v6 P5a 報表平台與三型新報表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一條產生報表的路徑（手動、排程同一函式），產出自足 HTML＋XLSX＋可直接閱讀的信件正文，先交付三型新報表：橫向移動態勢（旗艦，含「目錄與認證流量」節）、新出現的連線、非受管端點；GUI 報表頁可產生、下載、刪除、排程。

**Architecture:** 報表＝領域層的 `ReportDocument`（封面、關鍵指標附上期、發現、節；節由表格／長條圖／文字區塊組成），由各型的 builder 讀 v6 store 以 SQL 彙總產生；兩個 renderer（HTML 用 5.x `report_shell` 的 CSS／表格 JS 移植、XLSX 用 openpyxl）與一個信件 renderer 只吃 `ReportDocument`。產生一律經排隊：GUI 與排程都只寫一筆 `queued` 紀錄，排程器的 `reports_run` 工作逐筆執行，單一行程、無背景 thread。

**Tech Stack:** Python 3.12、SQLite、pydantic 2、openpyxl（新依賴）、Flask、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（§6.3 第 4 點、§6.4、§6.5 報表、§6.5.5、§6.5.1、§6.5.8、§4.3）；路線圖 `docs/superpowers/plans/2026-10-24-v6-roadmap.md` P5 列與末節「報表加一節目錄與認證流量」。

## P5 分段（Ruling，寫入帳本）

P5 依路線圖是最大的階段，拆成三段，各自有可驗收的產物，依序在同一分支系列上做、各自驗收：
- **5a（本計畫）**：報表平台＋三型新報表＋信件＋排程＋GUI 報表頁＋保留。
- **5b**：traffic、security_risk、network_inventory、app_summary、readiness、勒索防護、audit、ven_status 改寫到 v6 store。
- **5c**：policy_usage、rule_hit_count（狀態／反灰／開啟＋寫入用 key＋設定升版）、policy_diff、policy_resolver、自訂報表、`migrate/v5.py` 的 `report`／`report_schedules` 段。
5b、5c 的計畫在前一段完成後才寫（路線圖：提前寫會過期）。

## Global Constraints

- **不引入 pandas／numpy／matplotlib**（Ruling）：1,000 台每日 100 萬筆流量（spec §5），把流量載進 DataFrame 會超過 4–8 GB；報表數字以 SQL 讀 `flow_rollup_daily`、`connection_baseline`、`detections`、`analysis_results`、`lateral_snapshot_daily`、`workloads` 等既有表彙總。只移植不依賴 pandas 的 5.x 資產（`report_shell.css`、`report_table.js`）。新依賴只有 `openpyxl`（XLSX 是 spec 指定的附件）；圖表一律內嵌 SVG。
- 專案 CLAUDE.md：「產出報表、PDF、摘要文件前，先確認欄位與內容的長度上限與截斷邏輯（過長內容的處理方式要明確：換行、省略或分頁，不可無聲截斷）。交付前用實際樣本資料跑一次完整輸出，逐頁檢查有沒有被截斷或溢出，把檢查結果附在回報裡。」本計畫的截斷規則見 Task 1，驗收見 Task 11。
- 反目標（spec §4.3）：沒資料不得顯示成 0 或空白；截斷要揭露（顯示 N／共 M）；資料品質與覆蓋率要寫明；集合不完整時不得顯示成完整。
- 信件只走一套 SMTP（`services/alerts/channels.py`），不得新增第二份 SMTP 程式（5.x 有三份）。
- spec §6.5：「附件為自足 HTML 完整報表＋XLSX 原始資料；不做 PDF」；不做任何 CSV 上傳輸入。
- spec §6.5.5：「信件正文就是摘要：4 個關鍵指標（附上期比較）、3–5 條取自關注清單且屬於該報表範圍的發現（各附『為什麼重要＋建議動作』）、資料品質一行」；「需要一個『GUI 對外網址』設定，未設定時信件不放連結並說明」。
- 「在工作台開啟」連結（Ruling）：工作台是 P6，5a 不產生指向不存在頁面的連結；信件與 HTML 只放「在 GUI 開啟此報表」連結（`{gui_external_url}/reports?id=<report id>`，P5a 的報表頁會處理此參數）。P6 加工作台後再替各節補連結（列入 P6 範圍）。
- 收集模式（spec §6.4）：三型都需要流量；「僅事件」模式下報表目錄反灰並說明要哪種模式，排程執行時記失敗並寫明原因，不產出空報表；「告警」模式只保留 3 天流量，報表封面與資料品質行寫明實際涵蓋天數。
- 時間：期間以顯示時區（`settings.display.zone()`）的日界線計算，存與比較用 UTC。
- 硬性守門（路線圖）：新表在 `store/ownership.py` 登錄；新增的 `/api` 路由在同一任務內有前端呼叫者；新增的設定鍵在同一任務內有讀者；`illumio_ops/` 內不得 print、不得依賴工作目錄。
- i18n：所有報表與介面文字在 `illumio_ops/i18n/en.json`、`zh_TW.json` 各一份，鍵與佔位符一致（`tests_v6/i18n/test_dictionaries.py`）；報表鍵前綴 `rpt_`，介面鍵前綴 `gui_reports_`。
- 閘門：`.superpowers/sdd/2026-10-27-v6-phase5a-reports/gates.sh`（pip-audit、contracts、typecheck、build、ruff、`mypy --no-incremental`、pytest `-n auto`），每個任務之間親自跑。
- 測試指令範本：`timeout 900 .venv/bin/python -m pytest <檔> -q -p no:logging`。
- commit 訊息英文 conventional commits，結尾兩行 trailer（`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`、`Claude-Session: https://claude.ai/code/session_013iFADnkFuumZxobTw5jFC3`）；`git add <明確路徑>`。

## Review Focus

1. 報表期間內有收集缺口、或回填尚未涵蓋整個期間：封面與資料品質行要寫出缺口與實際涵蓋，指標不得默默以較短的資料算出看似完整的數字（Task 2 `coverage_note` 測試）。
2. 上期沒有資料（新安裝、快照不足）：上期比較顯示「無上期資料」而不是 0 或 ▲100%（Task 3、4、5 的 `previous=None` 測試）。
3. 產生途中 PCE 被切換（流量庫世代改變）：報表記失敗「資料來源已更換」，不留下混了兩個 PCE 的檔案（Task 2 `test_generation_change_fails_report`）。
4. 同一排程在服務停機後恢復：只補跑一次，不連續補產多份；DST 或 UTC+N 時區下時刻正確（Task 7 `test_due_after_downtime_runs_once`、`test_due_in_offset_zone`）。
5. 主機名稱、帳號、process 含 HTML／試算表公式字元（`<script>`、`=cmd|`）：HTML escape、XLSX 中和公式（Task 1 `test_html_escapes_cells`、`test_xlsx_neutralises_formulas`）。

---

### Task 0: NFR RHC 403 時限內查證（spec「P5 開工時要先釐清」）

**Files:** Create `tmp/v6-p5-verification/rhc-nfr-probe.md`（gitignored，結果另抄進帳本）

- [ ] **Step 1**：以 `~/claude-config/bin/op`（`--vault Lab`）取 NFR owner key，只注入子行程。依序唯讀查：`GET /orgs/{org}/report_templates`（列出全部範本與 `enabled`）、`GET /orgs/{org}/report_templates/rule_hit_count_report`、`GET /orgs/{org}/optional_features`、`GET /users/{id}`（key 的角色與 `type`）；再送一次 `PUT /report_templates/rule_hit_count_report {"enabled": false}`（no-op）比對錯誤 body。以 API 臨時建一個 owner 角色的 **service account**（`api_key.expires_in_seconds=3600`），用它重送同一個 no-op PUT；測完 DELETE。限時 30 分鐘。
- [ ] **Step 2**：寫結論：403 是否隨 key 類型（user key vs service account）改變；若仍無法解釋，記為 5c 決策清單項目「NFR 走『PCE 拒絕』分支，RHC 驗收只在 lab」。不改任何 firewall_settings、不 provision。
- [ ] **Step 3**：帳本記 `Task 0: complete (probe → <結論一句>)`。

### Task 1: 報表文件模型與兩個 renderer

**Files:**
- Create: `illumio_ops/domain/report.py`、`illumio_ops/services/reports/__init__.py`、`illumio_ops/services/reports/render_html.py`、`illumio_ops/services/reports/render_xlsx.py`、`illumio_ops/services/reports/svg.py`、`illumio_ops/services/reports/assets/report_shell.css`、`illumio_ops/services/reports/assets/report_table.js`
- Modify: `requirements-v6.in`、`requirements-v6.lock`（`openpyxl>=3.1,<4`，pip-compile 帶 hash）、`illumio_ops/domain/values.py`（`ReportType`、`ReportFormat`）、`illumio_ops/i18n/*.json`
- Test: `tests_v6/domain/test_report.py`、`tests_v6/services/reports/test_render_html.py`、`tests_v6/services/reports/test_render_xlsx.py`

**Interfaces:**
- Produces（`domain/report.py`，pydantic、frozen、`extra="forbid"`）：
  - `Kpi(key: str, label: str, value: int | float | None, previous: int | float | None, unit: Literal["count","percent"], better: Literal["lower","higher","neutral"])`——`value=None`＝無法計算（顯示「無資料」並附原因 `note: str | None`）。
  - `Finding(severity: Severity, title: str, why: str, action: str)`。
  - `Column(key: str, label: str, kind: Literal["text","number","time","host"])`。
  - `TableBlock(kind: Literal["table"], columns: tuple[Column, ...], rows: tuple[tuple[str | int | float | None, ...], ...], total_rows: int, empty_text: str)`——`rows` 為完整資料（XLSX 全寫），HTML 只顯示前 `HTML_ROW_CAP`。
  - `BarBlock(kind: Literal["bars"], title: str, points: tuple[tuple[str, int | None], ...])`——`None`＝該點無資料（畫成斷點，不畫 0）。
  - `TextBlock(kind: Literal["text"], paragraphs: tuple[str, ...])`。
  - `Section(id: str, title: str, intro: str, blocks: tuple[TableBlock | BarBlock | TextBlock, ...])`。
  - `ReportDocument(report_type: ReportType, lang: Language, title: str, period_start: datetime, period_end: datetime, generated_at: datetime, pce_label: str, kpis: tuple[Kpi, ...], findings: tuple[Finding, ...], data_quality: tuple[str, ...], sections: tuple[Section, ...], gui_link: str | None)`。
  - 常數 `HTML_ROW_CAP = 200`、`XLSX_ROW_CAP = 1_000_000`、`CELL_SOFT_MAX = 2_000`。
- Produces（renderer）：`render_html(doc: ReportDocument, *, tz: tzinfo | None) -> str`、`render_xlsx(doc: ReportDocument, *, tz: tzinfo | None) -> bytes`、`bar_svg(points, *, width=640, height=160) -> str`。

**截斷與溢出規則（先定再寫，CLAUDE.md）：**
- HTML 表格：每個表最多 `HTML_ROW_CAP` 列，超過時表下方寫「顯示前 200 列，共 N 列；完整資料見 XLSX 的〈<分頁名>〉分頁」。
- 儲存格：HTML 不截字，以 shell CSS 換行（`overflow-wrap:anywhere`）；超過 `CELL_SOFT_MAX` 字元時 HTML 顯示前 2,000 字＋「…（全文 N 字，見 XLSX）」，`title` 不放全文（避免巨型屬性）。
- XLSX：每表一分頁，名稱去非法字元並截到 31 字、重名加序號；寫入全部列至 `XLSX_ROW_CAP`，超過時在分頁第一列寫截斷說明；欄寬 `min(max_len+2, 60)`、`wrap_text=True`；字串開頭為 `= + - @ \t \r` 時前加 `'`。
- 長條圖：最多 90 個點；超過時取最後 90 點並在圖下寫「只顯示最近 90 天」。

- [ ] **Step 1：寫失敗的測試**

```python
# tests_v6/services/reports/test_render_html.py
def test_html_caps_rows_and_says_so(doc_with_rows):          # 450 列
    out = render_html(doc_with_rows(450), tz=UTC)
    assert out.count("<tr data-row") == 200
    assert "450" in out and "XLSX" in out
def test_html_escapes_cells(doc_with_rows):
    out = render_html(doc_with_rows(1, cell="<script>alert(1)</script>"), tz=UTC)
    assert "<script>alert(1)" not in out and "&lt;script&gt;" in out
def test_html_long_cell_points_to_xlsx(doc_with_rows):
    out = render_html(doc_with_rows(1, cell="x" * 2500), tz=UTC)
    assert "x" * 2001 not in out and "2500" in out
def test_kpi_without_value_is_not_zero(doc):
    out = render_html(doc(kpis=(Kpi(key="k", label="L", value=None, previous=None, unit="count",
                                    better="lower", note="n/a"),)), tz=UTC)
    assert ">0<" not in out and "n/a" in out
def test_html_is_self_contained(doc):
    out = render_html(doc(), tz=UTC)
    assert "<link " not in out and "src=\"http" not in out and "<style>" in out
def test_bars_none_is_gap_not_zero():
    svg = bar_svg((("d1", 3), ("d2", None), ("d3", 5)))
    assert svg.count("<rect") == 2

# tests_v6/services/reports/test_render_xlsx.py
def test_xlsx_one_sheet_per_table_all_rows(doc_with_rows):
    wb = load_workbook(BytesIO(render_xlsx(doc_with_rows(450), tz=UTC)))
    assert wb.worksheets[0].max_row == 451          # header + every row
def test_xlsx_neutralises_formulas(doc_with_rows):
    wb = load_workbook(BytesIO(render_xlsx(doc_with_rows(1, cell="=cmd|' /C calc'!A0"), tz=UTC)))
    assert wb.worksheets[0]["A2"].value.startswith("'=")
def test_xlsx_sheet_names_unique_and_short(doc_two_tables_same_long_title):
    names = load_workbook(BytesIO(render_xlsx(doc_two_tables_same_long_title, tz=UTC))).sheetnames
    assert len(set(names)) == len(names) and all(len(n) <= 31 for n in names)
```

- [ ] **Step 2**：Run `timeout 900 .venv/bin/python -m pytest tests_v6/services/reports tests_v6/domain/test_report.py -q -p no:logging` → FAIL（模組不存在）。
- [ ] **Step 3：實作。** `report_shell.css`／`report_table.js` 從 5.x `src/report/exporters/assets/` 原樣複製（commit 訊息註明來源與 5.x commit `640e7182` 時的 blob），以 `importlib.resources` 讀；HTML 結構沿用 5.x `build_shell_document` 的封面／目錄／節／表格標記（只移植用得到的部分，不移植 cover_meta 的死參數）。表格列加 `data-row` 屬性。時間以 `tz` 顯示（`None`＝伺服器本地）。`ReportType` 先有 `lateral_posture`、`new_connections`、`unmanaged_endpoints`；`ReportFormat` 為 `html`、`xlsx`。
- [ ] **Step 4**：Run 同 Step 2 → PASS；跑閘門腳本（pip-audit 會檢查新鎖檔）。
- [ ] **Step 5：Commit** `feat(v6): report document model with HTML and XLSX renderers`

### Task 2: 產生管線、報表紀錄、排隊執行與保留

**Files:**
- Create: `illumio_ops/store/migrations/0007_reports.sql`、`illumio_ops/store/reports.py`、`illumio_ops/services/reports/registry.py`、`illumio_ops/services/reports/generate.py`、`illumio_ops/services/reports/retention.py`
- Modify: `illumio_ops/store/ownership.py`、`illumio_ops/settings/schema.py`（`SCHEMA_VERSION=6`、`ReportSettings`、`Settings.reports`、`default_reports()`）、`illumio_ops/settings/upgrade.py`（`_v5_to_v6`）、`illumio_ops/jobs/scheduler.py`（`reports_run` 每 30 秒、`reports_retention` 每日）、`illumio_ops/migrate/v5.py`（新設定段用 `default_reports()` 補齊；`report`／`report_schedules` 仍標 P5 延後，5c 處理）
- Test: `tests_v6/store/test_reports.py`、`tests_v6/services/reports/test_generate.py`、`tests_v6/services/reports/test_retention.py`、`tests_v6/settings/test_upgrade.py`（加 v5→v6）

**Interfaces:**
- 表（app DB，擁有者 `illumio_ops.store.reports`）：
  - `reports(id INTEGER PRIMARY KEY, report_type TEXT, params_json TEXT, status TEXT CHECK IN ('queued','running','done','failed'), trigger TEXT CHECK IN ('manual','schedule'), schedule_id TEXT, pce_label TEXT, period_start TEXT, period_end TEXT, created_at TEXT, started_at TEXT, finished_at TEXT, error_key TEXT, error_detail TEXT, files_json TEXT, kpis_json TEXT, email_status TEXT, email_detail TEXT)`。
- `settings.schema`：
  - `ReportSettings(gui_external_url: str, retention_days: int = Field(ge=1, le=3650), schedules: tuple[ReportSchedule, ...] = Field(max_length=100))`；本任務先加 `retention_days`（預設 90）；`gui_external_url` 由 Task 6、`schedules` 由 Task 7 加入同一個 v6 模型（未發佈，`_v5_to_v6` 一律用 `default_reports()`）。
- `registry.py`：`ReportParams(report_type: ReportType, lookback_days: int = Field(default=7, ge=1, le=90), lang: Language | None = None, formats: tuple[ReportFormat, ...] = ("html","xlsx"))`；`ReportSpec(type, group: Literal["lateral","inventory","analysis","assessment","operations"], needs_traffic: bool, build: Callable[[AppContext, ReportParams, datetime, datetime, Language], ReportDocument])`；`REGISTRY: dict[ReportType, ReportSpec]`；`availability(ctx) -> dict[ReportType, Unavailable | None]`，`Unavailable(reason_key: str)`（僅事件模式→`rpt_unavailable_events_only`）。
- `generate.py`：
  - `enqueue(ctx, params: ReportParams, *, trigger, schedule_id: str | None, now) -> int`（不可用時直接寫 `failed`＋原因，不排隊）。
  - `period(now: datetime, lookback_days: int, tz) -> tuple[datetime, datetime]`：結束＝顯示時區今天 00:00，開始＝往前 lookback_days 天。
  - `run_queued(ctx, *, now) -> int`：取最舊一筆 `queued`→`running`→呼叫 builder→寫檔到 `paths.reports_dir/<id>/`（`<type>-<YYYYMMDD>-<id>.html|.xlsx`，0600）→`done`；任何例外→`failed`（`error_key`＋`error_detail` 截 500 字）並刪掉已寫的半成品。讀取前後比對流量庫世代，變了→`failed`、`rpt_err_pce_switched`。服務重啟時把殘留的 `running` 改回 `queued`（`recover_running(ctx)`，在 `reports_run` 首次執行時呼叫）。
  - `coverage_note(ctx, start, end, lang) -> tuple[str, ...]`：以 `services.coverage.store_coverage` 求期間內流量覆蓋與缺口，產生資料品質句（含實際涵蓋天數、缺口時段、收集模式）。
- `retention.py`：`run_report_retention(ctx, *, now) -> int`：刪除 `created_at` 早於 `retention_days` 的紀錄與目錄；另依排程 `keep`（Task 7）。目錄名不是紀錄 id 的不碰。

- [ ] **Step 1：寫失敗的測試**（節錄）

```python
def test_manual_and_schedule_share_one_path(ctx, fake_builder):
    a = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    b = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="schedule", schedule_id="s1", now=NOW)
    assert generate.run_queued(ctx, now=NOW) == a and generate.run_queued(ctx, now=NOW) == b
    assert fake_builder.calls == 2
def test_events_only_mode_fails_with_reason(ctx_events_only):
    rid = generate.enqueue(ctx_events_only, ReportParams(report_type=NEW_CONN), trigger="schedule",
                           schedule_id="s", now=NOW)
    row = get_report(ctx_events_only, rid)
    assert row.status == "failed" and row.error_key == "rpt_unavailable_events_only" and row.files == []
def test_generation_change_fails_report(ctx, builder_that_switches_pce):
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    row = get_report(ctx, rid)
    assert row.status == "failed" and row.error_key == "rpt_err_pce_switched"
    assert not any((ctx.paths.reports_dir / str(rid)).glob("*"))
def test_builder_error_leaves_no_files(ctx, failing_builder): ...
def test_running_rows_requeued_after_restart(ctx): ...
def test_period_uses_display_day_boundaries():
    s, e = generate.period(datetime(2026, 10, 27, 1, 0, tzinfo=UTC), 7, timezone(timedelta(hours=8)))
    assert e == datetime(2026, 10, 26, 16, 0, tzinfo=UTC) and s == e - timedelta(days=7)
def test_coverage_note_names_gap(ctx_with_gap):
    note = generate.coverage_note(ctx_with_gap, START, END, Language.ZH_TW)
    assert any("缺口" in line for line in note)
def test_retention_removes_old_reports_and_only_report_dirs(ctx): ...
def test_v5_settings_upgrade_adds_reports(): ...
```

- [ ] **Step 2**：Run `timeout 900 .venv/bin/python -m pytest tests_v6/store/test_reports.py tests_v6/services/reports tests_v6/settings -q -p no:logging` → FAIL。
- [ ] **Step 3**：實作。檔案寫入先寫 `.part` 再 rename；目錄 0700。`reports_run` 一次最多跑一份（下一份等下一輪），避免長報表連續佔用。
- [ ] **Step 4**：Run 同 Step 2 → PASS；跑閘門。
- [ ] **Step 5：Commit** `feat(v6): one report generation path with queued runs and retention`

### Task 3: 橫向移動態勢報表（旗艦）

**Files:** Create `illumio_ops/services/reports/lateral_posture.py`；Modify `registry.py`、i18n；Test `tests_v6/services/reports/test_lateral_posture.py`

**Interfaces:**
- Consumes：`analysis.read_result(conn, "exposure")`（`ExposureResult`）、`lateral_snapshot_daily`（新增讀函式 `analysis.lateral_snapshots(conn, since_day, until_day) -> list[tuple[str, dict]]`，擁有者模組內）、`analysis.detections_since`、`focus_items`（新增 `analysis.active_focus(conn, kinds) -> list[Row]`）、`flowsource_anomaly.directory_sources`、`workloads` 主機名稱。
- Produces：`build_lateral_posture(ctx, params, start, end, lang) -> ReportDocument`。

**內容**（每節沒有資料時寫明原因，不留空表）：
- 關鍵指標（4）：可觸及重要資產的來源數（現在，加總）、樞紐主機數、本期新偵測數、跨環境管理連線數；上期＝期間開始當天（或之前最近一天）的 `lateral_snapshot_daily` 與前一個同長期間的偵測數；沒有快照→`previous=None`。未設定重要資產時第一項 `value=None`、note「尚未設定重要資產」。
- 發現：`focus_items` 中 active 且 kind ∈ {detection, exposure_asset, pivot_host, cross_env} 的前 5 項（依 score），用項目的 title／why／action 鍵翻譯。
- 節：①暴露面（現在 vs 全部強制後的節點、邊、unknown 邊、可觸及最多的主機；每日趨勢長條圖取期間內快照）②重要資產（來源數現在／強制後、最短路徑、切斷點句子：「只切 A → B 的 <ports>，可觸及 X 的主機從 N 降到 M」）③可觸及最多的主機 前 50 ④樞紐主機 ⑤本期偵測（依偵測器計數表＋明細：嚴重度、偵測器、主體、首見、最後見、次數、晚到、重要資產）⑥跨環境管理連線（`cross_env`，並寫 `cross_env_total`）⑦**目錄與認證流量**：宣告與推論的目錄伺服器（`directory_sources` ≥3 來源者＋設定宣告者，標「推論／宣告／兩者」）、本期 `auth_to_non_dc`／`new_dc_client`／`directory_surge` 偵測、目錄 port 連線數前 20 的來源（`flow_rollup_daily`，目錄類 port，附上期倍數，上期為 0 時寫「上期無」）、可疑工具偵測中目的為目錄 port 者。
- 資料品質：暴露面計算時間與是否過期（> 2 小時）、`unknown_edges`、`limits_hit`、基準天數未滿、`coverage_note`。

- [ ] **Step 1：寫失敗的測試**：`test_kpis_from_exposure_and_previous_snapshot`、`test_previous_none_without_snapshot`、`test_no_critical_assets_says_so`（value None＋note）、`test_cut_sentence`（含主機名稱與數字）、`test_directory_section_marks_inferred_and_declared`、`test_directory_previous_zero_says_none`、`test_findings_only_lateral_kinds_max_five`、`test_stale_exposure_in_data_quality`、`test_no_exposure_result_yet`（每節寫「暴露面尚未計算」而非空表）。用 tests_v6 既有的 flow 寫入 fixture 與 `analysis.write_result` 準備資料。
- [ ] **Step 2**：Run `timeout 900 .venv/bin/python -m pytest tests_v6/services/reports/test_lateral_posture.py -q -p no:logging` → FAIL。
- [ ] **Step 3**：實作並註冊（group `lateral`、`needs_traffic=True`）。
- [ ] **Step 4**：→ PASS；閘門。
- [ ] **Step 5：Commit** `feat(v6): lateral movement posture report`

### Task 4: 新出現的連線報表

**Files:** Create `illumio_ops/services/reports/new_connections.py`、`illumio_ops/store/flowdb/migrations/0007_baseline_first_seen.sql`（`CREATE INDEX ix_baseline_first ON connection_baseline (first_seen)`）；Modify `illumio_ops/store/flowdb/flows.py`（讀函式 `baseline_first_seen_between(conn, start, end, *, limit) -> tuple[list[Row], int]`）、registry、i18n；Test `tests_v6/services/reports/test_new_connections.py`

**內容：**
- 指標：本期新連線數、其中管理 port（三類合計，附類別）、指向重要資產、來源為非受管；上期＝前一個同長期間 `first_seen` 落在其中的數量。基準期未滿（`LateralContext.baseline_days < baseline_required`）時每個指標 note「基準期累積中（已 N 天）」，數字照算但標示。
- 節：依服務（port／協定，附管理類別）前 20；依目的主機前 20；管理 port 新連線明細；全部明細（來源、目的、port／協定、類別、首見、最後見、期間內判定〔取 `flow_rollup_daily` 期間內出現過的 decision，逗號分隔〕）。
- 明細上限：讀取最多 100,000 列（`limit`），超過時節內寫「只列出最早 100,000 筆，共 N 筆」。
- 回填寫入的基準不算「新」：`first_seen` 早於基準期起點的不會落在報表期間；期間與基準期重疊於冷啟動時由 note 說明。

- [ ] **Step 1**：測試 `test_counts_and_previous_window`、`test_admin_class_attached`、`test_accumulating_baseline_note`、`test_decisions_from_rollup_in_period`、`test_limit_disclosed`（以 `limit=3` 參數化驗揭露）、`test_index_exists_after_migration`。
- [ ] **Step 2**：Run → FAIL。 **Step 3**：實作並註冊（group `analysis`）。 **Step 4**：→ PASS；閘門。
- [ ] **Step 5：Commit** `feat(v6): new connections report`

### Task 5: 非受管端點報表

**Files:** Create `illumio_ops/services/reports/unmanaged.py`；Modify registry、i18n；Test `tests_v6/services/reports/test_unmanaged.py`

**內容：**（非受管＝`ip:` 開頭的端點 key，`domain.identity.endpoint_key`）
- 每列一個非受管位址：位址、私有／公網（`domain.netaddr`）、方向（連入受管／被受管連出／兩者）、受管對端數、連線數、前 3 個 port／協定、期間內判定、首見日、最後見日；讀 `flow_rollup_daily` 期間內資料，以 SQL `GROUP BY` 彙總。
- 指標：非受管位址數、其中私有位址（可裝 VEN 的候選）、對受管主機使用管理 port 的非受管位址、公網位址；上期同法。
- 節：可裝 VEN 的候選（私有、與 ≥3 台受管主機往來，依受管對端數排序）；使用管理 port 的非受管來源；公網端點；全部清單（讀取上限 100,000 列並揭露）。

- [ ] **Step 1**：測試 `test_unmanaged_rollup_grouping`、`test_private_vs_public`、`test_direction_both`、`test_admin_port_sources`、`test_previous_window`、`test_limit_disclosed`。
- [ ] **Step 2–4**：FAIL → 實作並註冊（group `inventory`）→ PASS；閘門。
- [ ] **Step 5：Commit** `feat(v6): unmanaged endpoints report`

### Task 6: 信件正文與寄送

**Files:** Create `illumio_ops/services/reports/render_email.py`、`illumio_ops/services/reports/deliver.py`；Modify `illumio_ops/services/alerts/channels.py`（把 `_smtp` 拆成公開的 `send_mail(cfg: SmtpChannel, *, subject, text, html, attachments: Sequence[tuple[str, str, bytes]] = (), recipients: Sequence[str] | None = None, timeout) -> tuple[bool, str | None]`，`_smtp` 改呼叫它）、`schema.py`（`ReportSettings.gui_external_url`：空字串或 `https://` 開頭、不含查詢字串）、`generate.py`（`done` 後若參數要求寄信則呼叫 `deliver`）、`registry.ReportParams`（加 `email: bool = False`、`recipients: tuple[str, ...] = ()`）；Test `tests_v6/services/reports/test_render_email.py`、`tests_v6/services/reports/test_deliver.py`、`tests_v6/services/alerts/test_channels.py`（迴歸）

**Interfaces：**`render_email(doc, *, tz) -> Rendered`（沿用 `services.alerts.messages.Rendered`：subject、text、html）；`deliver(ctx, report_id) -> None` 寫 `email_status`（`sent`／`failed`／`skipped_no_smtp`）。

**信件內容（spec §6.5.5）：**主旨「［illumio-ops］<報表名> <期間>：<N> 項需要處理」（N＝發現數）；正文依序：4 個關鍵指標（值、上期、▲▼持平或「無上期資料」）、3–5 條發現（為什麼重要＋建議動作；不足 3 條時照實列出，0 條寫「本期沒有需要處理的項目」）、資料品質一行、「在 GUI 開啟此報表」連結（`gui_external_url` 為空時改寫「未設定 GUI 對外網址，信件不含連結」）。HTML 與純文字兩份；色彩只用 Direction D token 的值（不得新增色表）。附件：HTML＋XLSX；合計超過 20 MB 時只附 HTML 並在正文說明 XLSX 太大、請到 GUI 下載。

- [ ] **Step 1**：測試 `test_subject_counts_findings`、`test_four_kpis_with_previous_or_none`、`test_zero_findings_sentence`、`test_no_link_without_external_url`、`test_link_with_external_url`、`test_attachments_and_size_fallback`、`test_smtp_disabled_records_skipped`、`test_send_failure_recorded_report_stays_done`、`test_alert_smtp_unchanged`（既有告警信件測試仍綠）。SMTP 以 `smtplib.SMTP` 的 monkeypatch 假伺服器驗證附件 MIME。
- [ ] **Step 2–4**：FAIL → 實作 → PASS；閘門。
- [ ] **Step 5：Commit** `feat(v6): report email body and delivery through the one SMTP path`

### Task 7: 排程

**Files:** Create `illumio_ops/services/reports/schedules.py`、`illumio_ops/store/migrations/0008_report_schedule_state.sql`；Modify `schema.py`（`ReportSchedule`、`ReportSettings.schedules`）、`store/reports.py`（擁有 `report_schedule_state(schedule_id TEXT PRIMARY KEY, last_due TEXT, last_report_id INTEGER, last_status TEXT, consecutive_failures INTEGER)`）、`ownership.py`、`generate.py`（`reports_run` 先呼叫 `tick_schedules` 再 `run_queued`）、`retention.py`（每排程保留 `keep` 份）；Test `tests_v6/services/reports/test_schedules.py`

**Interfaces：**
- `ReportSchedule(id: str（uuid4 hex）, name: str(1..80), enabled: bool, report_type: ReportType, lookback_days: int(1..90), frequency: Literal["daily","weekly","monthly"], day_of_week: int | None(0=週一..6), day_of_month: int | None(1..31，短月取月底), hour: int(0..23), minute: int(0..59), formats: tuple[ReportFormat, ...]（至少一個）, email: bool, recipients: tuple[str, ...]（空＝SMTP 通道的收件人）, lang: Language | None（None＝顯示語言）, keep: int(1..365, 預設 30))`；weekly 必須有 day_of_week、monthly 必須有 day_of_month，其他情況必須為 None。
- `due_time(s: ReportSchedule, *, after: datetime, tz) -> datetime`：`after` 之後下一個觸發時刻（顯示時區牆鐘，回傳 UTC）。
- `tick_schedules(ctx, *, now) -> list[int]`：對每個啟用排程，若 `due_time(after=last_due or 建立時刻)` ≤ now，則 enqueue 一次、`last_due` 設為**最後一個已過的觸發時刻**（停機期間錯過多次只補一次）。
- `run_now(ctx, schedule_id, *, now) -> int`：立即 enqueue，不改 `last_due`。

- [ ] **Step 1**：測試 `test_daily_due`、`test_weekly_and_monthly_short_month`、`test_due_in_offset_zone`（`UTC+8`、IANA `America/New_York` 跨 DST 那天）、`test_due_after_downtime_runs_once`、`test_disabled_not_run`、`test_run_now_keeps_last_due`、`test_failure_counter`、`test_keep_prunes_per_schedule`、`test_schedule_validation`（weekly 缺 day_of_week 拒絕）。
- [ ] **Step 2–4**：FAIL → 實作 → PASS；閘門。
- [ ] **Step 5：Commit** `feat(v6): report schedules with single catch-up`

### Task 8: 報表 API 與 GUI 報表頁（目錄、產生、紀錄、下載、刪除）

**Files:** Create `illumio_ops/web/routes/reports.py`、`illumio_ops/services/reports/views.py`、`web/src/pages/reports/Reports.tsx`、`web/src/pages/reports/GenerateDrawer.tsx`；Modify `illumio_ops/web/app.py`（註冊；下載路由 `GET /reports/files/<int:report_id>/<name>`，`login_required`，只送該紀錄 `files_json` 內的檔名，`as_attachment=True`、`X-Content-Type-Options: nosniff`）、`web/src/shell/nav.ts` 登錄（main 區，順序在告警之後）、i18n、契約產生物；Test `tests_v6/web/test_reports_routes.py`、`tests_v6/e2e/test_reports_e2e.py`（Playwright）

**API（契約）：**`reports.catalog` GET `/api/reports/catalog` → 每型：group、名稱、說明、可用與否＋原因；`reports.list` GET `/api/reports`（分頁 50）；`reports.get` GET `/api/reports/<id>`；`reports.generate` POST `/api/reports`（`ReportParams`）→ 新紀錄；`reports.delete` DELETE `/api/reports/<id>`（`running` 時拒絕 409）。
**頁面：**依 group 分組的目錄（只列已實作的型別；不可用的反灰並顯示原因與要去的設定頁連結）；每型「產生」打開抽屜（期間天數、語言、格式、可選寄信與收件人）；下方紀錄表（型別、期間、觸發、PCE、狀態〔排隊／產生中／完成／失敗＋原因〕、檔案下載、寄信狀態、刪除）；有 `queued`／`running` 時每 5 秒刷新。網址帶 `?id=` 時捲到並標出該筆（信件連結落點）。

- [ ] **Step 1**：路由測試：未登入 401、CSRF、產生後列表出現、下載只接受紀錄內檔名（`../` 與他筆檔名 404）、刪除 running 409、catalog 在僅事件模式回 `available=false`。Playwright：登入→報表頁→產生橫向移動態勢→等到完成→下載 HTML 檔可開啟且含封面標題；`?id=` 落點標示；1280 與 390 寬度各截圖存 `tmp/v6-p5-verification/`。
- [ ] **Step 2–4**：FAIL → 實作 → PASS；閘門（contracts、typecheck、build 也要過）。
- [ ] **Step 5：Commit** `feat(v6): reports page with generate, history and download`

### Task 9: 排程與報表設定的 API 與 GUI

**Files:** Create `illumio_ops/web/routes/report_schedules.py`、`web/src/pages/reports/Schedules.tsx`、`web/src/pages/system/Reports.tsx`（系統設定：GUI 對外網址、報表保留天數）；Modify app 註冊、nav、i18n；Test `tests_v6/web/test_report_schedules_routes.py`、`tests_v6/e2e/test_report_schedules_e2e.py`

**API：**`report_schedules.list/create/update/delete/run_now`（`/api/report-schedules…`），寫入經 `SettingsStore.update(revision, fn)`（revision 衝突回 409）；`system.reports_get/reports_put`（`/api/system/reports`）。
**頁面：**報表頁第二分頁「排程」：列表（名稱、型別、頻率與下次執行時間〔顯示時區〕、上次結果、啟用開關、立即執行、編輯、刪除）；編輯抽屜依頻率顯示星期／日期欄位；寄信勾選時若 SMTP 通道未啟用，寫明並連到通知通道頁。系統設定「報表」頁：GUI 對外網址（說明用途：信件連結）、保留天數。

- [ ] **Step 1**：路由測試：建立／更新驗證錯誤指名欄位、revision 衝突 409、立即執行產生一筆 `trigger=schedule` 紀錄、刪除排程不刪既有報表。Playwright：建一個每日排程→立即執行→紀錄出現。
- [ ] **Step 2–4**：FAIL → 實作 → PASS；閘門。
- [ ] **Step 5：Commit** `feat(v6): report schedules and report settings pages`

### Task 10: i18n 與文案收尾、兩語系產出檢查

**Files:** Modify i18n JSON；Test `tests_v6/services/reports/test_report_i18n.py`

- [ ] **Step 1**：測試 `test_no_raw_keys_in_output`：三型 × 兩語系以 fixture 資料產 HTML、XLSX、信件，輸出中不得出現 `rpt_`／`gui_reports_` 原始鍵；zh_TW 輸出不得出現 en 字典獨有的整句（抽樣 20 個值）。
- [ ] **Step 2–4**：FAIL（若有漏鍵）→ 補齊 → PASS；閘門。
- [ ] **Step 5：Commit** `fix(v6): complete report copy in both languages`

### Task 11: 驗收（.106 lab 與規模）、審查、交付紀錄

- [ ] **Step 1：部署 .106**：照 P4.5 的手動更新流程（換套件目錄＋pip 裝新鎖檔；以 `runuser -u illumio-ops` 寫設定或寫完 `chown illumio-ops:illumio-ops`）；備份到 `/root/v6-backup/<ts>`；5.x 必須保持 active。
- [ ] **Step 2：實際產出**：三型 × zh_TW／en 以 lab 資料各產一份（期間 7 天），下載回本機；用 Playwright 在 1280 與 390 寬度逐節截圖，另以列印模式（`page.pdf`）檢查每頁有無截斷或溢出；XLSX 以 openpyxl 讀回核對列數＝報表列數。檢查結果逐項寫入 `tmp/v6-p5-verification/report.md`（CLAUDE.md 規則）。
- [ ] **Step 3：信件**：在 .106 v6 建一個橫向移動態勢排程（寄信），立即執行，確認信件送達、正文不開附件可讀、連結落點正確（先設定 GUI 對外網址）；截圖存證。
- [ ] **Step 4：規模**：在 .106 的 1,000 台合成庫（`tmp/v6-p45-verification/` 的產生方式，7 天、每天 100 萬筆）量三型產生時間與峰值記憶體；目標：每份 ≤ 5 分鐘、峰值記憶體增量 ≤ 0.5 GB；不達標時先 profile 再修。記入報告與 spec §5。
- [ ] **Step 5：審查**：Codex reviewer（gpt-6.1-sol，high）審全分支；逐條查證後修正（每項先寫會紅的測試）；帳本記 `Final:` 行。
- [ ] **Step 6**：更新 spec（§5 報表規模、§6.5.5 實作語意）與路線圖 P5 列（5a 完成、5b／5c 待做）；跑閘門；commit `docs(v6): record P5a acceptance`。
