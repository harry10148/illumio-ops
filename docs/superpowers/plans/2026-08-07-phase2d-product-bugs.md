# Phase 2D — 產品 bug backlog 修復 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 UI redesign v2 Phase 1 審查挖出的產品 bug backlog（18 條中經 2026-08-07 逐條原始碼驗證後判定需修的 15 條），每條一 commit、能寫測試的先 RED 後修。

**Architecture:** 不引入新子系統。修復散落在報表排程驗證鏈（GUI API / CLI 精靈 / scheduler）、GUI 前端（dashboard.js / integrations.js / actions.js / index.html）、SIEM DLQ（dlq.py / web.py）、api_client、dashboard_hero、四型報表 exporter、與測試環境（analysis.lock、venv）。共通手法：把「單一事實來源」上收（report type 全集、is_ruleset 由 href 推導、latency 權重基礎對齊後端），入口處補驗證，死碼整塊移除並同步撤守死碼的測試。

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy / pytest；前端 vanilla JS（無 node 測試 runner，JS 以 pytest source-gate 測試＋`ILLUMIO_OPS_E2E_BASE_URL` 閘控的 Playwright e2e 驗證）。

## Global Constraints

- **行號一律執行時重驗**：本計畫引用的行號為 2026-08-07 驗證當下快照，執行時以符號／內容搜尋重新定位，不可盲信行號（Phase 1 已知約 10 處 citation drift）。
- **TDD**：每條 bug 先寫 RED 測試（跑一次確認失敗）再修。例外：純死碼刪除／純文案與環境債（Task 6、15）可用「守門測試斷言新狀態」＋人工驗證指令代替行為 RED，任務內已寫明驗證方式。
- **2A 重疊標注**：凡動 `src/static/js/dashboard.js`、`src/static/js/actions.js`、`src/static/js/integrations.js`、`src/templates/index.html` 的任務（Task 2、6、7、8、9、10），**執行前先查 2A 是否已上線 v2 前端**（`src/static/js/v2/` 是否存在且已接線）。若已上線：改在 v2 對應位置修，或確認該畫面已被 v2 取代後僅修後端部分並記錄。
- **2C 重疊標注**：Task 3、13 動 CLI 互動選單；執行前先查 2C（cli-flows.md 選單重組）是否已合併，若已合併則在重組後的選單位置實施同等修復。
- **Commit 規範**：英文 conventional commits，**一條 bug 一 commit**（測試＋實作＋i18n 鍵同 commit）。
- **i18n 新鍵**：新增鍵必須同時進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`，並跑 `venv/bin/pytest tests/test_i18n_audit.py -q` 確認 audit 綠；GUI 端新鍵須符合 `_ui_translation_dict` 白名單前綴（`gui_` 開頭即可，見 `src/gui/_helpers.py:326-332`）。刪鍵時反向同步兩檔並重跑 audit。
- **不碰 venv 進 git**：Task 15 只下環境指令，不產生 commit。
- 每任務結束跑 `venv/bin/pytest tests/ -x -q`（全套）確認無回歸再 commit；push 後 `gh run watch` 盯 CI（記憶教訓：subagent 回報綠不算數，須親驗）。

---

## 驗證結果總表（2026-08-07 逐條對當前原始碼驗證）

| # | 判定 | 驗證實況（當前符號位置） |
|---|---|---|
| 1 | **描述有誤，殘餘缺口要修** | GUI 表單選項其實是全名 `monday..sunday`（`index.html:1639-1645`），與 `report_scheduler.py:259-260` 的 `strftime("%A").lower()` 比對相容——「週排程永不觸發」對 GUI 建立的排程不成立。真缺口：CLI 精靈 `report_schedule.py:186` 自由輸入無驗證（可存 `"mon"`→靜默永不觸發）、API `_validate_report_schedule`（`gui/routes/reports.py:130-158`）不驗 `day_of_week`。→ Task 1 |
| 2 | **描述有誤，殘餘缺口要修** | `audit_summary` 不是可排程型別（是 dashboard summary endpoint，`gui/routes/dashboard.py:617`）；select 已含後端支援的全部 11 型（`index.html:1591-1603` 對齊 `report_scheduler.py:372-488` 分支）。殘餘缺口：`dashboard.js:401` 對未知型別 select 值變 `''`、儲存時清空，且後端 `_validate_report_schedule` 不驗 `report_type`。→ Task 2 |
| 3 | **仍在** | `cli/menus/report_schedule.py:163-170` `type_map` 只認 traffic/audit/ven_status，編輯其他 8 型會靜默改成 traffic。→ Task 3 |
| 4 | **仍在** | `dashboard_hero.py:45-46` 以英文 `"maturity" in label` 比對；KPI label 由 `_retranslate_kpi_labels`（`gui/routes/dashboard.py:27-52`）以當前語言覆寫，中文機恆不中。KPI 帶 `label_key: "mod12_kpi_maturity_score"`（`mod12_executive_summary.py:265`）可用。severity 是英文常數，不受影響。→ Task 11 |
| 5 | **仍在** | `index.html` `#snap-fieldset` 整塊（含 `#snap-content`、`#d-top-actions-grid`、`#snap-kpi-grid` 等，約 1011-1094 行）無任何 JS renderer（全 repo grep 零引用）；`dashboard.js:61-67` 只搬動面板不填充。三支測試釘住死碼：`test_dashboard_top_actions.py`、`test_dashboard_legacy_kpi_collapsed.py`、`test_e2e_dashboard_story.py:30-55`。→ Task 6 |
| 6 | **仍在** | `integrations.js:521-526` `validateIp` 無 `/` 分支拒 CIDR；`gui_cache_exclude_src_ips_help` 兩語系皆承諾「CIDR 或精確 IP」；hints 於 `:532` 對 `tf-ips`（exclude_src_ips）產生誤導警告（非阻斷）。→ Task 7 |
| 7 | **判定為 bug（非刻意設計）** | `api_client.py:1298-1309` docstring 意圖是「item **或其父 RuleSet**」，但父檢查只認 `/sec_rules/`。deny rules 是本專案可排程物件（`gui/routes/rule_scheduler.py:164-166` 收 `deny_rules`，href 含 `/deny_rules/`），`toggle_and_provision`（`:1311-1326`）對 deny rule 一樣以前 7 段推 rs_href 並 provision 整個 ruleset——父 ruleset 有 pending draft 時會被一併掃出去，與 sec_rules 的防護語意完全相同，漏掉純屬 deny 支援後加時未同步。建立（`rule_scheduler_cli.py:432`）與每 tick（`rule_scheduler.py:384`）同走此函式，一處修即全覆蓋。→ Task 4 |
| 8 | **仍在** | `integrations.js:1245-1259` `dlqPurgeSelected` 送 `{dest, older_than_days: 0}` 無 ids，後端 `siem/web.py:309-323` 只支援 dest+older_than_days → 實際清掉該 dest 全部，確認文案卻寫「purge N」。`replay_ids`（`dlq.py:52-74`、`web.py:296-298`）已有現成對稱樣板。→ Task 8 |
| 9 | **仍在** | `actions.js:118-127` `stopGui`：`post()`＝`api()` 包裝（`utils.js:58`），非 2xx 回 `{ok:false}` 不 throw，catch 永不觸發；persistent mode 下 `/api/shutdown` 回 403（`gui/routes/admin.py:51-52`）仍顯示「GUI stopped」假頁。→ Task 9 |
| 10 | **已修／描述失效** | 18 個 `login_*` 鍵全部經兩條不依賴白名單的通道送達：login.html 服務端 Jinja `t('login_*')`（`login.html:6-262`）＋ `login_page()` 專用 `login_i18n_json` 注入（`gui/routes/auth.py:62-80`、`login.html:265`）。主 app JS/模板無任何 `login_*` 消費。無事可修。→ 豁免清單 |
| 11 | **仍在** | 同 config 鍵（`rule_scheduler.enabled` / `check_interval_seconds`）的設定選單在 `cli/menus/_root.py:164-188` 與 `rule_scheduler_cli.py:668-697` 重複實作（連框線繪製都複製，且 _root 版改完無回饋訊息）。→ Task 13 |
| 12 | **需使用者裁決** | `gui/_helpers.py:126-140` `_redact_secrets` 附 `<key>__length`＝真實長度。`tests/design_v2/test_masking.py:82-99` 註解明載這是刻意設計（「安全的衍生 metadata 供前端顯示」）；但全前端 grep 只消費 `__set`（`integrations.js:1656-1671`），`__length` 零消費者。→ 豁免清單（裁決選項見該節） |
| 13 | **仍在** | `gui/routes/rule_scheduler.py:349` 建立端原封收 client 的 `is_ruleset`，不與 href 形狀對帳；`rule-scheduler.js:504` 顯示端也只信 flag。flag 錯 → `toggle_and_provision` 的 provision 範圍推導錯誤。→ Task 5 |
| 14 | **仍在，豁免移交 2C** | 三支 standalone CLI（`pce_cache_cli.py:12` 起、`siem_cli.py`、`rule_scheduler_cli.py`）確實無 `draw_panel`（`cli/_render.py:390`）外框，純樣式債。2C 將依 `design/v2/cli-flows.md`（36 畫面）重組全部互動選單，此時先做必被重工。→ 豁免清單 |
| 15 | **仍在** | 寫 sidecar 的只有 traffic 家族（`report_generator.py:844`）、audit（`audit_generator.py:849`）、policy_usage（`policy_usage_generator.py:431`）、rule_hit_count（`:234`）、readiness（`readiness_report.py:288`）。**ven_status / policy_diff / policy_resolver / app_summary 四型完全不寫**（generator/exporter grep 零 `metadata.json`）。→ Task 12 |
| 16 | **仍在** | 後端 `avg_latency_ms` 只對 `status=="sent"` 的列取平均（`siem/web.py:213-216`）；前端合併多目的地時卻以 `w = s1h + f1h` 加權（`integrations.js:620-623`）——加權基礎≠平均基礎，failed 多的目的地會把它「sent-only 平均」灌成過大權重。正確權重＝`sent_1h`。→ Task 10 |
| 17 | **仍在** | `src/main.py:30-42` `analysis_lock_path()` 錨定 repo root 的 `logs/analysis.lock`，無任何 override 機制；`scheduler/jobs.py:45`、`gui/routes/actions.py:524` 同路徑；tests/ 無任何隔離（grep 零處理）→ 平行測試搶真實 flock，test_main_menu.py 偶發失敗。→ Task 14 |
| 18 | **仍在（範圍比描述大）** | 不只 pip-compile/pip-sync：`venv/bin/` 內 pip、pip3、pytest、flask、activate 等大量 script 的 shebang／路徑仍指 `/home/harry/dev/illumio-ops`（repo 已搬到 `/home/harry/rd/`）；`pip-audit` 已是新路徑（曾單獨重裝過）。環境債，一次性指令處置、不 commit。→ Task 15 |

---

## 豁免與裁決清單

**#10 login_* i18n（已修／失效）** — 不寫修復任務。證據：`src/gui/routes/auth.py` `login_page()` 以專用 `login_i18n` dict（9 個 runtime 鍵）注入 `login.html:265` 的 `<script id="login-i18n-data">`；其餘鍵由 Jinja 服務端 `t()` 直渲。`_ui_translation_dict` 白名單只影響主 app 的 `ui_translations_json`，login 頁不經它。主 app 無 `login_*` 消費者。

**#12 api.key__length（需使用者裁決）** — 兩造證據：(a) 刻意設計——`tests/design_v2/test_masking.py:82-99` 明文把 `__set`/`__length` 定義為「不可能還原機密的安全衍生 metadata」，並有守門測試保護它不被遮罩器打掉；(b) 洩漏論——精確長度可縮小暴力搜尋空間、可辨識金鑰型別，且全前端**沒有任何 `__length` 消費者**（只用 `__set`），移除零 UI 成本。裁決選項：**A.** 維持現狀（接受設計）；**B.** 直接刪 `__length` 欄位（改 `_redact_secrets` ＋ 同步改 `test_masking.py`、`test_siem_web.py` 兩處斷言）；**C.** 改回桶化值（如 `0 / short / normal / long`）。建議 B（無消費者、風險面收斂），但因有明文設計紀錄，**未經使用者裁決不得動工**。

**#14 三支 CLI 無 draw_panel 外框（豁免，移交 2C）** — bug 屬實但屬純視覺統一。2C 將依 `design/v2/cli-flows.md` 重組全部互動選單（含這三支的 63 項對照），在 2D 先包 `draw_panel` 必定被 2C 重工。處置：在 2C 計畫的對應選單任務中列為驗收項。若 2C 因故取消，此條回收為獨立任務。

---

## 任務總覽

| Task | Bug# | 子系統 | commit 訊息 |
|---|---|---|---|
| 1 | #1 | 排程驗證 | `fix(scheduler): validate weekly day_of_week across GUI API and CLI wizard` |
| 2 | #2 | 排程驗證 | `fix(gui): whitelist report_type on schedule create/update and guard unknown types in modal` |
| 3 | #3 | 排程驗證/CLI | `fix(cli): report schedule wizard supports all 11 report types` |
| 4 | #7 | API client | `fix(api): has_draft_changes checks parent ruleset for deny rules` |
| 5 | #13 | 排程驗證 | `fix(gui): derive rule schedule is_ruleset from href server-side` |
| 6 | #5 | GUI 前端 | `refactor(gui): remove dead legacy snapshot markup and orphan i18n keys` |
| 7 | #6 | GUI 前端 | `fix(gui): validateIp accepts CIDR as promised by exclude help text` |
| 8 | #8 | SIEM/GUI | `feat(siem): dlq purge supports explicit ids so purge-selected purges only the selection` |
| 9 | #9 | GUI 前端 | `fix(gui): stopGui surfaces shutdown failure instead of fake stopped page` |
| 10 | #16 | GUI 前端 | `fix(gui): weight siem latency kpi by sent-only basis to match backend average` |
| 11 | #4 | 後端 | `fix(dashboard): hero matches maturity kpi by label_key on localized snapshots` |
| 12 | #15 | 後端/報表 | `feat(report): write metadata sidecar for ven_status, policy_diff, policy_resolver, app_summary` |
| 13 | #11 | CLI | `refactor(cli): dedupe rule scheduler settings menu logic` |
| 14 | #17 | 測試環境 | `fix(tests): isolate analysis lock file via env override` |
| 15 | #18 | 環境（不 commit） | —（一次性環境指令） |

---

### Task 1: 週排程 day_of_week 驗證鏈（#1）

**Files:**
- Modify: `src/gui/routes/reports.py`（`_validate_report_schedule`，約 :130-158）
- Modify: `src/cli/menus/report_schedule.py`（精靈 Step 3，約 :183-189）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新鍵 `gui_err_invalid_day_of_week`）
- Test: `tests/test_report_schedule_validation.py`（擴充）、`tests/test_report_schedule_wizard_dow.py`（新建）

**Interfaces:**
- Produces: `src/cli/menus/report_schedule.py` 模組層新增 `_normalize_dow(raw: str) -> str | None`（全名或唯一前綴 → 正規化全名小寫；無效回 None）。Task 內部使用，無跨任務依賴。

**失敗情境：** CLI 精靈輸入 `mon` 被原樣存檔；`report_scheduler.py:260` 與 `strftime("%A").lower()`（=`"monday"`）永不相等 → 週排程靜默永不觸發、無任何 operator 訊號。API 端 PUT/POST 畸形 `day_of_week` 也 verbatim 存下（與 2026-07-24 BUG-2 修掉的 hour/minute 同類）。

- [ ] **Step 1: 寫 RED 測試（API 端）** — 加到 `tests/test_report_schedule_validation.py`：

```python
def test_weekly_invalid_day_of_week_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "weekly", "day_of_week": "mon",
                       "hour": 8, "minute": 0})
    assert r.status_code == 400


def test_weekly_valid_day_of_week_accepted_case_insensitive(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "weekly", "day_of_week": "Friday",
                       "hour": 8, "minute": 0})
    assert r.status_code == 200
```

- [ ] **Step 2: 寫 RED 測試（CLI 正規化 helper）** — 新建 `tests/test_report_schedule_wizard_dow.py`：

```python
"""#1：CLI 精靈 day_of_week 自由輸入無驗證，可存 'mon' → 排程靜默永不觸發。"""
import pytest
from src.cli.menus.report_schedule import _normalize_dow


@pytest.mark.parametrize("raw,expected", [
    ("monday", "monday"), ("Friday", "friday"), ("SUNDAY", "sunday"),
    ("mon", "monday"), ("fri", "friday"), ("我", None), ("", None),
    ("s", None),          # saturday/sunday 前綴不唯一 → 拒絕
    ("sat", "saturday"), ("su", "sunday"),
])
def test_normalize_dow(raw, expected):
    assert _normalize_dow(raw) == expected
```

- [ ] **Step 3: 確認 RED**

Run: `venv/bin/pytest tests/test_report_schedule_validation.py::test_weekly_invalid_day_of_week_rejected tests/test_report_schedule_wizard_dow.py -v`
Expected: FAIL（前者 200 而非 400；後者 ImportError `_normalize_dow`）

- [ ] **Step 4: 實作 API 端驗證** — `_validate_report_schedule` 的 `stype` 檢查後加：

```python
_VALID_DAYS_OF_WEEK = ("monday", "tuesday", "wednesday", "thursday",
                       "friday", "saturday", "sunday")
# ...函式內，monthly 檢查之前：
    if stype == "weekly":
        dow = str(d.get("day_of_week", "monday")).strip().lower()
        if dow not in _VALID_DAYS_OF_WEEK:
            raise ValueError(t("gui_err_invalid_day_of_week", lang=lang))
        d["day_of_week"] = dow   # 正規化為小寫全名再入庫
```

i18n 新鍵（兩檔都加）：
`"gui_err_invalid_day_of_week": "Invalid day of week (expect monday..sunday)."` ／ `"gui_err_invalid_day_of_week": "無效的星期值（須為 monday..sunday）。"`

- [ ] **Step 5: 實作 CLI 端正規化** — `report_schedule.py` 模組層加 `_normalize_dow`：

```python
_DOW_FULL = ("monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday")

def _normalize_dow(raw) -> str | None:
    """全名或唯一前綴 → 小寫全名；無效/歧義回 None。"""
    v = str(raw or "").strip().lower()
    if not v:
        return None
    if v in _DOW_FULL:
        return v
    hits = [d for d in _DOW_FULL if d.startswith(v)]
    return hits[0] if len(hits) == 1 else None
```

精靈 Step 3（`if schedule_type == "weekly":` 區塊）改為重問迴圈：

```python
    if schedule_type == "weekly":
        while True:
            dow = _ask(t("sched_day_of_week"), default=day_of_week)
            if dow is None:
                return
            norm = _normalize_dow(dow)
            if norm:
                day_of_week = norm
                break
            print(f"{Colors.FAIL}{t('cli_invalid_dow', value=dow, default='[-] Invalid day of week: {value}')}{Colors.ENDC}")
```

（`cli_invalid_dow` 新鍵同步進兩語系 JSON。）

- [ ] **Step 6: 確認 GREEN ＋ i18n audit**

Run: `venv/bin/pytest tests/test_report_schedule_validation.py tests/test_report_schedule_wizard_dow.py tests/test_i18n_audit.py -q`
Expected: PASS

- [ ] **Step 7: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/gui/routes/reports.py src/cli/menus/report_schedule.py src/i18n_en.json src/i18n_zh_TW.json tests/test_report_schedule_validation.py tests/test_report_schedule_wizard_dow.py
git commit -m "fix(scheduler): validate weekly day_of_week across GUI API and CLI wizard"
```

---

### Task 2: report_type 白名單＋編輯視窗未知型別防呆（#2）

**Files:**
- Modify: `src/report_scheduler.py`（模組層新增 `VALID_REPORT_TYPES` 常數）
- Modify: `src/gui/routes/reports.py`（`_validate_report_schedule`）
- Modify: `src/static/js/dashboard.js`（`openSchedModal`，約 :394-434）【2A 重疊——執行前先查】
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新鍵 `gui_err_invalid_report_type`）
- Test: `tests/test_report_schedule_validation.py`（擴充）、`tests/test_report_type_registry.py`（新建）

**Interfaces:**
- Produces: `src/report_scheduler.py` 模組層 `VALID_REPORT_TYPES: tuple[str, ...]`，內容為執行分支（`report_type ==` 鏈，約 :372-488）支援的 11 型：`("traffic", "security_risk", "network_inventory", "audit", "ven_status", "policy_usage", "policy_diff", "policy_resolver", "app_summary", "rule_hit_count", "readiness")`。**Task 3 依賴此常數。**

**失敗情境：** 排程的 `report_type` 若被存成 11 型以外的值（hand-edit config、未來型別先進後端後進前端），(a) 後端 verbatim 存下、tick 走不到任何分支靜默不產報表；(b) GUI 編輯視窗 `$('sched-report-type').value = <unknown>` 後 select 值變 `''`，按儲存把 `report_type` 清成空字串。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_report_type_registry.py`（新建）：

```python
"""#2：report_type 單一事實來源＝report_scheduler.VALID_REPORT_TYPES。
GUI select 選項、排程執行分支、API 驗證必須對齊，防止「新型別進了後端
但排程存出去被清空/靜默不跑」斷鏈重演。"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_valid_report_types_constant_exists_with_11_types():
    from src.report_scheduler import VALID_REPORT_TYPES
    assert set(VALID_REPORT_TYPES) == {
        "traffic", "security_risk", "network_inventory", "audit",
        "ven_status", "policy_usage", "policy_diff", "policy_resolver",
        "app_summary", "rule_hit_count", "readiness",
    }


def test_sched_report_type_select_options_match_backend():
    from src.report_scheduler import VALID_REPORT_TYPES
    html = (ROOT / "src" / "templates" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<select id="sched-report-type".*?</select>', html, re.S)
    assert m, "sched-report-type select not found"
    opts = re.findall(r'value="([a-z_]+)"', m.group(0))
    assert set(opts) == set(VALID_REPORT_TYPES)
```

加到 `tests/test_report_schedule_validation.py`：

```python
def test_unknown_report_type_rejected(client):
    r = _post(client, {"name": "x", "report_type": "audit_summary",
                       "schedule_type": "daily", "hour": 8, "minute": 0})
    assert r.status_code == 400
```

- [ ] **Step 2: 確認 RED**

Run: `venv/bin/pytest tests/test_report_type_registry.py tests/test_report_schedule_validation.py::test_unknown_report_type_rejected -v`
Expected: FAIL（ImportError `VALID_REPORT_TYPES`；後者 200）

- [ ] **Step 3: 實作** — `src/report_scheduler.py` 模組層（class 之外、import 之後）：

```python
# 可排程報表型別全集——GUI select（index.html sched-report-type）、CLI 精靈
# type_map、API 驗證（gui/routes/reports.py）皆以此為單一事實來源；新增型別
# 時 tests/test_report_type_registry.py 會逼三處同步。
VALID_REPORT_TYPES: tuple[str, ...] = (
    "traffic", "security_risk", "network_inventory", "audit",
    "ven_status", "policy_usage", "policy_diff", "policy_resolver",
    "app_summary", "rule_hit_count", "readiness",
)
```

`_validate_report_schedule` 開頭（cron 檢查之前）加：

```python
    from src.report_scheduler import VALID_REPORT_TYPES
    rt = d.get("report_type", "traffic")
    if rt not in VALID_REPORT_TYPES:
        raise ValueError(t("gui_err_invalid_report_type", lang=lang))
```

i18n 新鍵：`"gui_err_invalid_report_type": "Unknown report type."` ／ `"gui_err_invalid_report_type": "無效的報表型別。"`

`dashboard.js` `openSchedModal` 中原 `$('sched-report-type').value = ...` 一行改為：

```js
  const rtSel = $('sched-report-type');
  // #2 防呆：先清掉上次動態補的未知型別 option，再回填
  rtSel.querySelectorAll('option[data-unknown-type]').forEach(o => o.remove());
  const rtWanted = sched ? (sched.report_type || 'traffic') : 'traffic';
  rtSel.value = rtWanted;
  if (rtSel.value !== rtWanted) {
    // 存檔裡是 select 沒有的型別：補一個暫時 option 保留原值，
    // 避免儲存時 report_type 被清成 ''（清空後 tick 靜默不跑）
    const opt = document.createElement('opt' + 'ion');
    opt.value = rtWanted; opt.textContent = rtWanted;
    opt.setAttribute('data-unknown-type', '1');
    rtSel.appendChild(opt);
    rtSel.value = rtWanted;
  }
```

- [ ] **Step 4: 確認 GREEN**

Run: `venv/bin/pytest tests/test_report_type_registry.py tests/test_report_schedule_validation.py tests/test_i18n_audit.py -q`
Expected: PASS

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/report_scheduler.py src/gui/routes/reports.py src/static/js/dashboard.js src/i18n_en.json src/i18n_zh_TW.json tests/test_report_type_registry.py tests/test_report_schedule_validation.py
git commit -m "fix(gui): whitelist report_type on schedule create/update and guard unknown types in modal"
```

---

### Task 3: CLI 排程精靈 type_map 補全 11 型（#3）【2C 重疊——執行前先查】

**Files:**
- Modify: `src/cli/menus/report_schedule.py`（Step 2 區塊，約 :161-170）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（如需補型別顯示鍵）
- Test: `tests/test_report_schedule_wizard_types.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `src.report_scheduler.VALID_REPORT_TYPES`。
- Produces: `report_schedule.py` 模組層 `_report_type_options() -> list[tuple[str, str]]`（`[(編號字串, 型別), ...]`，順序＝`VALID_REPORT_TYPES`）。

**失敗情境：** 編輯一筆 `report_type="readiness"` 的排程，精靈 `default_type_k` 查 `{"traffic":"1","audit":"2","ven_status":"3"}` 落到 fallback `"1"`，使用者按 Enter 保留預設 → 排程被靜默改成 traffic。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_report_schedule_wizard_types.py`：

```python
"""#3：CLI 精靈 type_map 只認 3 型，編輯其他 8 型會被靜默改成 traffic。"""
from src.cli.menus.report_schedule import _report_type_options
from src.report_scheduler import VALID_REPORT_TYPES


def test_wizard_offers_all_backend_types():
    opts = _report_type_options()
    assert [rt for _, rt in opts] == list(VALID_REPORT_TYPES)


def test_wizard_default_roundtrips_every_type():
    # 編輯任何型別時，預設選項必須指回該型別本身（不可 fallback 成 traffic）
    opts = _report_type_options()
    reverse = {rt: num for num, rt in opts}
    for rt in VALID_REPORT_TYPES:
        assert reverse[rt] is not None
```

- [ ] **Step 2: 確認 RED**

Run: `venv/bin/pytest tests/test_report_schedule_wizard_types.py -v`
Expected: FAIL（ImportError `_report_type_options`）

- [ ] **Step 3: 實作** — `report_schedule.py`：

```python
from src.report_scheduler import VALID_REPORT_TYPES

def _report_type_options() -> list[tuple[str, str]]:
    return [(str(i + 1), rt) for i, rt in enumerate(VALID_REPORT_TYPES)]
```

精靈 Step 2 改為（顯示名稱優先取 `rpt_<type>_report_title` 既有鍵——與 `report_scheduler.py:522` email 標題 map 同鍵系，缺鍵 fallback 型別代碼本身；執行時逐鍵確認存在，缺的補進兩語系 JSON）：

```python
    _wizard_step(2, 7, t("sched_report_type"))
    options = _report_type_options()
    type_map = dict(options)
    current = edit_sched.get("report_type", "traffic") if is_edit else "traffic"
    default_type_k = next((num for num, rt in options if rt == current), "1")
    for num, rt in options:
        label = t(f"rpt_{rt}_report_title", default=rt)
        print(f"  {num}. {label}")
    type_sel = _ask(t("sched_report_type"), default=default_type_k)
    if type_sel is None:
        return
    report_type = type_map.get(str(type_sel), current)   # 亂輸入時保留原型別，不再吞成 traffic
```

（原 `opt_traffic_report`/`opt_audit_report`/`opt_ven_report` 三鍵若因此無其他消費者，屬本改動產生的孤兒——刪除並跑 i18n audit。）

- [ ] **Step 4: 確認 GREEN**

Run: `venv/bin/pytest tests/test_report_schedule_wizard_types.py tests/test_i18n_audit.py tests/test_main_menu.py -q`
Expected: PASS

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/cli/menus/report_schedule.py src/i18n_en.json src/i18n_zh_TW.json tests/test_report_schedule_wizard_types.py
git commit -m "fix(cli): report schedule wizard supports all 11 report types"
```

---

### Task 4: has_draft_changes 涵蓋 deny_rules 父檢查（#7）

**Files:**
- Modify: `src/api_client.py`（`has_draft_changes`，約 :1298-1309）
- Test: `tests/test_has_draft_changes_deny_rules.py`（新建；樁模式抄 `tests/test_rule_note_tag_strip.py` 的 `_make_client`）

**失敗情境：** 排程一條 deny rule（href 含 `/deny_rules/`），其父 ruleset 有 pending draft。`has_draft_changes` 只在 `"/sec_rules/" in href` 時查父，deny rule 跳過父檢查回 False → `toggle_and_provision` 照做 PUT＋provision 整個 ruleset，把父層無關的 pending 變更一併掃上 PCE（sec_rules 有防、deny_rules 沒防）。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_has_draft_changes_deny_rules.py`：

```python
"""#7：has_draft_changes 父 ruleset 檢查只認 /sec_rules/，deny_rules 子 rule
漏檢 → 父層 pending draft 會被 toggle_and_provision 一併 provision。"""
from unittest.mock import MagicMock

from src.api_client import ApiClient


def _make_client():
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "key", "secret": "secret", "verify_ssl": False}}
    return ApiClient(cm)


def _gate(client, rule_href, parent_has_draft):
    def fake_get(href):
        if href.endswith(("/sec_rules/9", "/deny_rules/9")):
            return 200, {"update_type": None}          # rule 本身乾淨
        return 200, {"update_type": "update" if parent_has_draft else None}
    client._api_get = MagicMock(side_effect=fake_get)
    return client.has_draft_changes(rule_href)


def test_sec_rule_parent_draft_blocks():
    assert _gate(_make_client(),
                 "/orgs/1/sec_policy/active/rule_sets/5/sec_rules/9", True) is True


def test_deny_rule_parent_draft_blocks():
    assert _gate(_make_client(),
                 "/orgs/1/sec_policy/active/rule_sets/5/deny_rules/9", True) is True


def test_deny_rule_clean_parent_passes():
    assert _gate(_make_client(),
                 "/orgs/1/sec_policy/active/rule_sets/5/deny_rules/9", False) is False
```

- [ ] **Step 2: 確認 RED**

Run: `venv/bin/pytest tests/test_has_draft_changes_deny_rules.py -v`
Expected: `test_deny_rule_parent_draft_blocks` FAIL（回 False），另兩個 PASS

- [ ] **Step 3: 實作** — `has_draft_changes` 的父檢查一般化：

```python
    def has_draft_changes(self, href: str) -> bool:
        """Check if an item OR its parent RuleSet has pending draft changes."""
        draft_href = href.replace("/active/", "/draft/")
        status, data = self._api_get(draft_href)
        if status == 200 and data and bool(data.get('update_type')):
            return True
        # 子 rule 三型（sec_rules/rules/deny_rules）都要查父 ruleset：
        # toggle_and_provision 對任何子 rule 都是 provision 整個 ruleset，
        # 父層 pending draft 會被一併掃出去（原本只認 /sec_rules/，
        # deny_rules 是後加的可排程型別，2026-08-07 #7）。
        for seg in ("/sec_rules/", "/deny_rules/", "/rules/"):
            if seg in draft_href:
                parent_href = draft_href.split(seg)[0]
                status_p, data_p = self._api_get(parent_href)
                if status_p == 200 and data_p and bool(data_p.get('update_type')):
                    return True
                break
        return False
```

- [ ] **Step 4: 確認 GREEN**

Run: `venv/bin/pytest tests/test_has_draft_changes_deny_rules.py tests/test_rule_note_tag_strip.py -q`
Expected: PASS

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/api_client.py tests/test_has_draft_changes_deny_rules.py
git commit -m "fix(api): has_draft_changes checks parent ruleset for deny rules"
```

---

### Task 5: rule 排程 is_ruleset 伺服端由 href 推導（#13）

**Files:**
- Modify: `src/gui/routes/rule_scheduler.py`（建立端 db_entry 組裝，約 :346-356；模組層新增 helper）
- Test: `tests/test_rule_schedule_is_ruleset_derivation.py`（新建）

**Interfaces:**
- Produces: `src/gui/routes/rule_scheduler.py` 模組層 `_href_is_ruleset(href: str) -> bool`。

**失敗情境：** client（或未來的 v2 前端）送 `href=".../rule_sets/5/sec_rules/9"` 但 `is_ruleset: true`：DB 存下矛盾資料 → `toggle_and_provision(href, ..., is_ruleset=True)` 把 rule href 當 ruleset href 用（provision 範圍推導錯誤），而 `rule-scheduler.js:504` 的清單顯示只信 flag，UI 全程靜默。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_rule_schedule_is_ruleset_derivation.py`：

```python
"""#13：建立 rule 排程時 is_ruleset 原封收 client 值、不與 href 對帳，
矛盾資料會讓 toggle_and_provision 的 provision 範圍推導錯誤。"""
import pytest


@pytest.mark.parametrize("href,expected", [
    ("/orgs/1/sec_policy/active/rule_sets/5", True),
    ("/orgs/1/sec_policy/active/rule_sets/5/sec_rules/9", False),
    ("/orgs/1/sec_policy/active/rule_sets/5/deny_rules/9", False),
    ("/orgs/1/sec_policy/active/rule_sets/5/rules/9", False),
])
def test_href_is_ruleset(href, expected):
    from src.gui.routes.rule_scheduler import _href_is_ruleset
    assert _href_is_ruleset(href) is expected
```

- [ ] **Step 2: 確認 RED**

Run: `venv/bin/pytest tests/test_rule_schedule_is_ruleset_derivation.py -v`
Expected: FAIL（ImportError `_href_is_ruleset`）

- [ ] **Step 3: 實作** — 模組層（blueprint factory 之外）：

```python
_RULE_CHILD_SEGMENTS = ("/sec_rules/", "/deny_rules/", "/rules/")

def _href_is_ruleset(href: str) -> bool:
    """is_ruleset 的單一事實來源＝href 形狀。client 送來的 flag 只做參考，
    矛盾時以 href 為準（#13：flag 錯會讓 provision 範圍推導錯誤）。"""
    return not any(seg in str(href) for seg in _RULE_CHILD_SEGMENTS)
```

建立端 `db_entry` 組裝改為（含矛盾警告 log）：

```python
            derived_is_ruleset = _href_is_ruleset(href)
            if 'is_ruleset' in data and bool(data.get('is_ruleset')) != derived_is_ruleset:
                logger.warning("rule schedule create: client is_ruleset={} contradicts href {}; using derived {}",
                               data.get('is_ruleset'), href, derived_is_ruleset)
            db_entry = {
                "type": data.get('type', 'recurring'),
                "name": data.get('name', ''),
                "is_ruleset": derived_is_ruleset,
                ...
```

（其餘欄位不動。前端 `rule-scheduler.js:504` 顯示端維持讀 flag——伺服端保證一致後 flag 即可信。）

- [ ] **Step 4: 確認 GREEN**

Run: `venv/bin/pytest tests/test_rule_schedule_is_ruleset_derivation.py -q`，另跑既有排程審查守門 `venv/bin/pytest tests/ -q -k "rule_scheduler"`
Expected: PASS

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/gui/routes/rule_scheduler.py tests/test_rule_schedule_is_ruleset_derivation.py
git commit -m "fix(gui): derive rule schedule is_ruleset from href server-side"
```

---

### Task 6: 移除 legacy snapshot 死碼區塊（#5）【2A 重疊——執行前先查；若 2A 已整面替換 legacy 面板則本任務改為確認刪除已含在 2A 並記錄】

**Files:**
- Modify: `src/templates/index.html`（刪 `#snap-fieldset` 整個 fieldset，驗證時約 :1011-1094；保留同面板的 Ranking Summary fieldset）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（刪孤兒鍵）
- Delete: `tests/test_dashboard_top_actions.py`、`tests/test_dashboard_legacy_kpi_collapsed.py`（整檔斷言死碼存在，隨死碼一起撤）
- Modify: `tests/test_e2e_dashboard_story.py`（移除 `d-top-actions-grid`/`d-detailed-kpis` anchor 斷言與 `test_findings_table_collapsed_by_details`、`test_detailed_kpi_grid_collapsed_by_details` 兩個死碼測試）
- Test: `tests/test_legacy_snapshot_removed.py`（新建守門）

**驗證方式說明（TDD 例外）：** 純死碼刪除無「行為 RED」可寫；以守門測試斷言刪除後狀態（markup 與孤兒鍵不得復活），刪除前先跑一次確認它是 RED（死碼還在）。

**失敗情境（現狀危害）：** 使用者點 dashboard 的 legacy 分頁永遠看到「No traffic report snapshot found」佔位＋一塊永不渲染的 Top Actions 骨架；維護者持續為死 DOM 付 i18n／測試成本（已有三支測試在保護死碼）。

- [ ] **Step 1: 寫守門測試（先 RED）** — `tests/test_legacy_snapshot_removed.py`：

```python
"""#5：#snap-fieldset 整塊（snap-content/d-top-actions/snap-kpi-grid...）
無任何 JS renderer，Phase 2D 移除；本檔防死碼與孤兒 i18n 鍵復活。"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
_DEAD_IDS = ('id="snap-fieldset"', 'id="snap-content"', 'id="d-top-actions"',
             'id="snap-kpi-grid"', 'id="snap-findings-body"', 'id="snap-policy-body"',
             'id="snap-ports-body"', 'id="snap-uncovered-body"', 'id="snap-bw-body"')


def test_dead_snapshot_markup_absent():
    html = (ROOT / "src" / "templates" / "index.html").read_text(encoding="utf-8")
    for frag in _DEAD_IDS:
        assert frag not in html, f"dead markup resurrected: {frag}"


def test_orphan_i18n_keys_removed():
    # 刪 markup 後這些鍵全 repo 無消費者（Step 3 會逐鍵複核）
    dead_prefixes = ("gui_snap_", "gui_top_actions_")
    for jf in ("i18n_en.json", "i18n_zh_TW.json"):
        keys = json.loads((ROOT / "src" / jf).read_text(encoding="utf-8"))
        orphans = [k for k in keys if k.startswith(dead_prefixes)]
        assert orphans == [], f"{jf} orphan keys: {orphans}"
```

Run: `venv/bin/pytest tests/test_legacy_snapshot_removed.py -v` → Expected: FAIL（死碼還在）

- [ ] **Step 2: 刪 index.html 死碼** — 刪除 `<fieldset id="snap-fieldset" ...>` 至其 `</fieldset>`（含 snap-placeholder、snap-content、d-top-actions、d-detailed-kpis、findings/policy/ports/uncovered/bw 各表）。**保留**後面的 Ranking Summary fieldset（`d-global-min`、`d-queries-container` 有活躍 renderer）。`db-actions-panel` 等 CSS class 若他處仍用則不動 CSS（無關死碼僅提及，不順手刪）。

- [ ] **Step 3: 清孤兒 i18n 鍵** — 逐鍵確認再刪（執行時以此指令複核每鍵在 src/ 的消費者只剩 i18n JSON 本身）：

```bash
for k in $(grep -o '"gui_snap_[a-z_]*"' src/i18n_en.json | tr -d '"') gui_top_actions_heading gui_top_actions_meta gui_detailed_kpis_label gui_findings_details_label; do
  echo "== $k"; grep -rn "$k" src/ --include=*.js --include=*.html --include=*.py | grep -v 'i18n_'; done
```

輸出為空的鍵才從兩語系 JSON 刪除；有消費者的鍵保留並把它從守門測試的 `dead_prefixes` 邏輯排除（記錄於 commit message）。

- [ ] **Step 4: 撤死碼測試** — 刪 `tests/test_dashboard_top_actions.py`、`tests/test_dashboard_legacy_kpi_collapsed.py`；改 `tests/test_e2e_dashboard_story.py`：移除 `d-top-actions-grid`/`d-detailed-kpis` anchors 與兩個 collapsed 測試（story-card 斷言保留）。

- [ ] **Step 5: 確認 GREEN**

Run: `venv/bin/pytest tests/test_legacy_snapshot_removed.py tests/test_e2e_dashboard_story.py tests/test_i18n_audit.py -q`
Expected: PASS

- [ ] **Step 6: 真機視覺驗證＋全套＋commit** — 測試機部署後開 dashboard → legacy 分頁，確認 Ranking Summary 仍在、無空殼區塊（CLAUDE.md 報表/視覺規則：親看）。

```bash
venv/bin/pytest tests/ -x -q
git add src/templates/index.html src/i18n_en.json src/i18n_zh_TW.json tests/test_legacy_snapshot_removed.py tests/test_e2e_dashboard_story.py
git rm tests/test_dashboard_top_actions.py tests/test_dashboard_legacy_kpi_collapsed.py
git commit -m "refactor(gui): remove dead legacy snapshot markup and orphan i18n keys"
```

---

### Task 7: validateIp 支援 CIDR（#6）【2A 重疊——執行前先查】

**Files:**
- Modify: `src/static/js/integrations.js`（`validateIp`，約 :521-526）
- Test: `tests/test_validate_ip_cidr.py`（新建 source-gate）；行為驗證走 e2e（見 Step 4）

**驗證方式說明：** repo 無 node runner；純 JS 函式以 pytest source-gate 鎖定 CIDR 分支存在＋prefix 上限值，行為面在 `ILLUMIO_OPS_E2E_BASE_URL` 環境以 Playwright `page.evaluate` 直測（既有決策：2A 元件層核心邏輯同此法）。

**失敗情境：** 使用者照 `gui_cache_exclude_src_ips_help`（「CIDR 或精確 IP」）在 pce_cache 排除清單輸入 `10.0.0.0/24`，`validateTrafficFilterHints` 顯示「Invalid IP: 10.0.0.0/24」誤導警告。

- [ ] **Step 1: 寫 RED source-gate** — `tests/test_validate_ip_cidr.py`：

```python
"""#6：validateIp 拒 CIDR，但 gui_cache_exclude_src_ips_help 承諾支援 CIDR。
無 node runner：以 source-gate 鎖定 CIDR 分支；行為由 e2e evaluate 驗證。"""
import re
from pathlib import Path

JS = Path(__file__).parent.parent / "src" / "static" / "js" / "integrations.js"


def _fn_body():
    js = JS.read_text(encoding="utf-8")
    m = re.search(r"function validateIp\(s\)\s*\{(.*?)\n\}", js, re.S)
    assert m, "validateIp not found"
    return m.group(1)


def test_validate_ip_splits_cidr_prefix():
    body = _fn_body()
    assert "split('/')" in body, "validateIp must handle CIDR prefix"


def test_validate_ip_bounds_v4_32_v6_128():
    body = _fn_body()
    assert "32" in body and "128" in body, "prefix bounds /32 (v4) and /128 (v6) required"
```

Run: `venv/bin/pytest tests/test_validate_ip_cidr.py -v` → Expected: FAIL

- [ ] **Step 2: 實作** — 取代 `validateIp`：

```js
function validateIp(s) {
  var parts = String(s).split('/');
  if (parts.length > 2) return false;
  var addr = parts[0];
  var isV4 = /^(\d{1,3}\.){3}\d{1,3}$/.test(addr)
    && addr.split('.').every(function(o) { return Number(o) <= 255; });
  var isV6 = !isV4 && /^[\da-fA-F:]+$/.test(addr) && addr.indexOf(':') >= 0;
  if (!isV4 && !isV6) return false;
  if (parts.length === 2) {
    if (!/^\d{1,3}$/.test(parts[1])) return false;
    var prefix = Number(parts[1]);
    return isV4 ? prefix <= 32 : prefix <= 128;
  }
  return true;
}
```

- [ ] **Step 3: 確認 GREEN**

Run: `venv/bin/pytest tests/test_validate_ip_cidr.py -q` → Expected: PASS

- [ ] **Step 4: e2e 行為驗證（測試機）** —

```bash
ILLUMIO_OPS_E2E_BASE_URL=<測試機URL> venv/bin/pytest tests/test_gui_e2e_playwright.py -q  # 既有 e2e 綠
```

並以 Playwright evaluate 抽測：`validateIp('10.0.0.0/24')===true`、`validateIp('10.0.0.0/33')===false`、`validateIp('::1/128')===true`、`validateIp('1.2.3.4')===true`、`validateIp('1.2.3.999')===false`。把輸出貼進回報。

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/static/js/integrations.js tests/test_validate_ip_cidr.py
git commit -m "fix(gui): validateIp accepts CIDR as promised by exclude help text"
```

---

### Task 8: DLQ purge 支援 ids（#8）【2A 重疊——前端部分執行前先查】

**Files:**
- Modify: `src/siem/dlq.py`（新增 `purge_ids`，樣板＝既有 `replay_ids` :52-74）
- Modify: `src/siem/web.py`（`purge_dlq` :309-323 加 ids 分支，樣板＝`replay_dlq` :296-298）
- Modify: `src/static/js/integrations.js`（`dlqPurgeSelected` :1245-1259 改送 ids）
- Test: `tests/test_siem_dlq.py`（擴充，沿用其 `sf`/`_seed_dlq` fixture）、`tests/test_siem_web.py`（擴充端點測試）

**Interfaces:**
- Produces: `DeadLetterQueue.purge_ids(ids: list[int]) -> int`（回實刪筆數）；`POST /api/siem/dlq/purge` body 支援 `{"ids": [int,...]}`（有 ids 時忽略 dest/older_than_days）。

**失敗情境：** 使用者勾 2 筆按 Purge，確認框寫「purge 2 from dest1」，實際 `{dest, older_than_days:0}` 把 dest1 的**全部** DLQ 清光——資料破壞性行為與確認文案不符。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_siem_dlq.py` 加：

```python
def test_dlq_purge_ids_removes_only_selection(sf):
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=3)
    dlq = DeadLetterQueue(sf)
    with sf() as s:
        ids = [r.id for r in s.execute(select(DeadLetter)).scalars().all()]
    removed = dlq.purge_ids(ids[:2])
    assert removed == 2
    with sf() as s:
        left = s.execute(select(DeadLetter)).scalars().all()
    assert [r.id for r in left] == [ids[2]]
```

`tests/test_siem_web.py` 加端點測試（沿用該檔既有 client/fixture 慣例，執行時對齊其 CM/session 樁）：

```python
def test_dlq_purge_with_ids_deletes_only_those_rows(client, monkeypatch):
    # 樁 _get_sf 指向含 3 筆 DeadLetter 的 in-memory sf（同檔既有樁法），
    # POST {"ids":[id1,id2]} 後斷言 removed==2 且第三筆仍在。
    ...
```

（`...` 處為 fixture 接線，執行時抄同檔 `test_siem_destinations_get_masks_hec_token` 的樁法補齊——斷言部分如上不可省。）

- [ ] **Step 2: 確認 RED**

Run: `venv/bin/pytest tests/test_siem_dlq.py -q` → Expected: FAIL（`purge_ids` 不存在）

- [ ] **Step 3: 實作後端** — `dlq.py`：

```python
    def purge_ids(self, ids: list[int]) -> int:
        """Delete specific DLQ entries by id（#8：purge-selected 只清勾選）。"""
        if not ids:
            return 0
        with self._sf.begin() as s:
            r = s.execute(delete(DeadLetter).where(DeadLetter.id.in_(ids)))
        return r.rowcount
```

`web.py` `purge_dlq` 在讀出 data 後、dest 分支前加：

```python
        if data.get("ids"):
            ids = [int(i) for i in data["ids"]][:1000]
            removed = DeadLetterQueue(_get_sf()).purge_ids(ids)
            return jsonify({"status": "ok", "removed": removed})
```

- [ ] **Step 4: 實作前端** — `dlqPurgeSelected` 的 fetch body 改為 `JSON.stringify({ids: ids})`（dest 空檢查與確認文案保留——現在文案終於是真的）。

- [ ] **Step 5: 確認 GREEN**

Run: `venv/bin/pytest tests/test_siem_dlq.py tests/test_siem_web.py -q` → Expected: PASS

- [ ] **Step 6: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/siem/dlq.py src/siem/web.py src/static/js/integrations.js tests/test_siem_dlq.py tests/test_siem_web.py
git commit -m "feat(siem): dlq purge supports explicit ids so purge-selected purges only the selection"
```

---

### Task 9: stopGui 檢查回應（#9）【2A 重疊——執行前先查】

**Files:**
- Modify: `src/static/js/actions.js`（`stopGui`，約 :118-127）
- Test: `tests/test_stop_gui_guard.py`（新建 source-gate）

**驗證方式說明：** 同 Task 7——JS 行為以 source-gate 鎖「先檢查回應才改寫 body」的順序不變量，後端 403 行為已有 `gui/routes/admin.py` 覆蓋，真機驗證在 persistent mode 按 Stop 應看到錯誤 toast 而非假停機頁。

**失敗情境：** NSSM/persistent mode 下 `/api/shutdown` 回 403 `{ok:false}`；`post()`（=`api()`，非 2xx 不 throw）讓 catch 永不觸發，body 被無條件改寫成「GUI stopped」——服務其實還活著，operator 被騙。

- [ ] **Step 1: 寫 RED source-gate** — `tests/test_stop_gui_guard.py`：

```python
"""#9：stopGui 吞 403、無條件改寫 body。api() 慣例：非 2xx 回 {ok:false}
不 throw（utils.js api()），所以必須檢查回傳值而非依賴 catch。"""
import re
from pathlib import Path

JS = Path(__file__).parent.parent / "src" / "static" / "js" / "actions.js"


def test_stop_gui_checks_response_before_rewriting_body():
    js = JS.read_text(encoding="utf-8")
    m = re.search(r"async function stopGui\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m, "stopGui not found"
    body = m.group(1)
    ok_check = body.find("ok === false")
    rewrite = body.find("document.body.innerHTML")
    assert ok_check != -1, "stopGui must check r.ok before declaring GUI stopped"
    assert rewrite == -1 or ok_check < rewrite, "response check must precede body rewrite"
```

Run: `venv/bin/pytest tests/test_stop_gui_guard.py -v` → Expected: FAIL

- [ ] **Step 2: 實作** —

```js
async function stopGui() {
  hdrMenuClose();
  if (!confirm(_t('gui_action_stop_gui_confirm'))) return;
  let r;
  try { r = await post('/api/shutdown', {}); }
  catch (e) { r = { ok: false, error: String(e) }; }
  // api() 對非 2xx 回 {ok:false} 不 throw（utils.js）；persistent mode 的
  // 403 必須擋在這裡，否則畫面謊報「GUI stopped」（#9）
  if (!r || r.ok === false) {
    toast((r && r.error) || _t('gui_network_error').replace('{error}', ''), true);
    return;
  }
  document.body.innerHTML =
    '<div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">' +
    `<h1 style="color:var(--accent2)">${_t('gui_action_gui_stopped_title')}</h1>` +
    `<p style="color:var(--dim)">${_t('gui_action_gui_stopped_body')}</p>` +
    '</div>';
}
```

- [ ] **Step 3: 確認 GREEN＋真機驗證** — `venv/bin/pytest tests/test_stop_gui_guard.py -q` PASS；測試機（persistent mode 部署）按 Stop GUI，附「出現錯誤 toast、頁面未變假停機頁」的截圖／敘述於回報。

- [ ] **Step 4: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/static/js/actions.js tests/test_stop_gui_guard.py
git commit -m "fix(gui): stopGui surfaces shutdown failure instead of fake stopped page"
```

---

### Task 10: SIEM 延遲 KPI 權重對齊後端（#16）【2A 重疊——執行前先查】

**Files:**
- Modify: `src/static/js/integrations.js`（KPI strip forEach，約 :612-625）
- Test: `tests/test_integrations_siem_queue_color.py`（同檔追加 source-gate，該檔本就是 integrations.js 的守門檔）

**失敗情境：** 後端 `avg_latency_ms` 只平均 `status=="sent"` 的列（`siem/web.py:213-216`）；前端跨目的地加權卻用 `w = s1h + f1h`。某目的地 1h 內 sent=1、failed=99、該筆 sent 延遲 5s → 它以權重 100 灌爆全域延遲 KPI，實際上它只貢獻了 1 筆有延遲資料的事件。

- [ ] **Step 1: 寫 RED source-gate** — `tests/test_integrations_siem_queue_color.py` 加：

```python
def test_latency_kpi_weighted_by_sent_only():
    """#16：avg_latency_ms 是 sent-only 平均（siem/web.py），合併權重必須
    用 sent_1h；用 sent+failed 會讓高失敗目的地灌爆全域延遲 KPI。"""
    js = JS.read_text(encoding="utf-8")
    m = re.search(r"kpiLatencyWsum\s*\+=[^;]+;", js)
    assert m, "latency weighted-sum accumulation not found"
    block = js[max(0, m.start() - 400):m.end()]
    wdef = re.search(r"var w = ([^;]+);", block)
    assert wdef, "weight variable not found near latency accumulation"
    assert wdef.group(1).strip() == "s1h", (
        f"latency weight must be sent-only (s1h), got: {wdef.group(1)!r}")
```

Run: `venv/bin/pytest tests/test_integrations_siem_queue_color.py -v` → Expected: 新測試 FAIL（現值 `s1h + f1h`）

- [ ] **Step 2: 實作** — forEach 內：

```js
    // avg_latency_ms 是後端 sent-only 平均（siem/web.py），權重只能用 s1h；
    // 成功率 KPI 照舊用 s1h+f1h（那是 attempts 語意，正確）（#16）
    var w = s1h;
```

（`kpiAttempts1h`/`kpiRate1h` 的 `s1h + f1h` 不動——成功率的分母本來就該含 failed。）

- [ ] **Step 3: 確認 GREEN** — `venv/bin/pytest tests/test_integrations_siem_queue_color.py -q` PASS

- [ ] **Step 4: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/static/js/integrations.js tests/test_integrations_siem_queue_color.py
git commit -m "fix(gui): weight siem latency kpi by sent-only basis to match backend average"
```

---

### Task 11: dashboard hero 以 label_key 判定 maturity KPI（#4）

**Files:**
- Modify: `src/dashboard_hero.py`（KPI 迴圈，約 :42-56）
- Test: `tests/test_dashboard_hero.py`（新建——舊檔已不存在，僅殘 pycache）

**失敗情境：** 中文機 snapshot 的 KPI label 經 `_retranslate_kpi_labels` 變「成熟度分數」，`"maturity" not in label` 永真 → hero 恆 0 分/「?」等級，中文使用者的健康一句話永遠是無資料語氣。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_dashboard_hero.py`：

```python
"""#4：build_hero 以英文字面比對已在地化的 KPI label → 中文機 hero 恆 0/?。
判定改吃 label_key（mod12_executive_summary.py 產出 mod12_kpi_maturity_score），
英文 label 比對保留為 legacy snapshot fallback。"""
from src.dashboard_hero import build_hero


def _snap(kpi):
    return {"kpis": [kpi], "key_findings": [{"severity": "HIGH", "finding": "f", "action": "a"}]}


def test_matches_localized_label_via_label_key():
    hero = build_hero(_snap({"label": "成熟度分數", "label_key": "mod12_kpi_maturity_score",
                             "value": "72.5/100 (B)"}))
    assert hero["score"] == 72.5
    assert hero["score_grade"] == "B"
    assert hero["high_risk_count"] == 1
    assert hero["sentence_key"] == "gui_hero_sentence"


def test_legacy_english_label_still_matches():
    hero = build_hero(_snap({"label": "Maturity Score", "value": "50/100 (C)"}))
    assert hero["score"] == 50.0
    assert hero["score_grade"] == "C"


def test_unrelated_kpi_ignored():
    hero = build_hero(_snap({"label": "總流量", "label_key": "mod12_kpi_total_flows",
                             "value": "999"}))
    assert hero["score"] == 0.0
```

- [ ] **Step 2: 確認 RED**

Run: `venv/bin/pytest tests/test_dashboard_hero.py -v`
Expected: `test_matches_localized_label_via_label_key` FAIL（score 0.0）

- [ ] **Step 3: 實作** — `build_hero` 迴圈判定改為：

```python
_MATURITY_LABEL_KEY = "mod12_kpi_maturity_score"
# ...迴圈內：
        label_key = str(kpi.get("label_key", ""))
        label = str(kpi.get("label", "")).lower()
        # label 會被 _retranslate_kpi_labels 換成當前語言（中文機無 "maturity"
        # 字面）；以 label_key 為主，英文字面留給無 label_key 的 legacy snapshot
        if label_key != _MATURITY_LABEL_KEY and "maturity" not in label:
            continue
```

- [ ] **Step 4: 確認 GREEN** — `venv/bin/pytest tests/test_dashboard_hero.py -q` PASS

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/dashboard_hero.py tests/test_dashboard_hero.py
git commit -m "fix(dashboard): hero matches maturity kpi by label_key on localized snapshots"
```

---

### Task 12: 四型報表補 metadata sidecar（#15）

**Files:**
- Create: `src/report/metadata_sidecar.py`（共用 helper）
- Modify: `src/report/exporters/policy_diff_html_exporter.py`（`export`，約 :178-190）
- Modify: `src/report/exporters/policy_resolver_exporter.py`（`export_json`/`export_csv`，約 :29-60）
- Modify: `src/report/exporters/app_summary_html_exporter.py`（`export`，約 :190-）
- Modify: `src/report/ven_status_generator.py`（HTML/xlsx 輸出路徑定案處，`generate` 內 `reserve_unique_path` 流程約 :198-211 與 `generate_ven_xlsx` :495——執行時重驗兩處的實際寫檔點）
- Test: `tests/test_report_metadata_sidecar.py`（新建）

**Interfaces:**
- Produces: `src/report/metadata_sidecar.py`：

```python
def write_sidecar(report_path: str, report_type: str, file_format: str,
                  *, record_count: int = 0, date_range=None, **extra) -> None
```

寫出 `<report_path>.metadata.json`，欄位齊 `readiness_report.py:278-289` 的形狀（`report_type`/`file_format`/`generated_at`/`record_count`/`date_range`＋extra），best-effort：寫失敗只 log 不拋（sidecar 缺席的既有語意就是 legacy fallback）。

**失敗情境：** GUI 手動產 ven_status/policy_diff/policy_resolver/app_summary 後，`/api/reports` 清單只能靠檔名 prefix 猜型別（gui-report-split 記憶中已知的坑）、report 列表 metadata 欄位空白；scheduler 的 `_stamp_schedule_id` 只好從零建 sidecar，手動產出的報表永遠是 legacy（unattributed）。實測資料：測試機 69 份報表 36 份無 sidecar。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_report_metadata_sidecar.py`：

```python
"""#15：ven_status/policy_diff/policy_resolver/app_summary 四型不寫
metadata sidecar → 報表清單靠檔名猜型別、retention 歸因永遠 legacy。"""
import json
from pathlib import Path


def _read_sidecar(path: str) -> dict:
    side = Path(path + ".metadata.json")
    assert side.is_file(), f"missing sidecar for {path}"
    return json.loads(side.read_text(encoding="utf-8"))


def test_write_sidecar_helper(tmp_path):
    from src.report.metadata_sidecar import write_sidecar
    p = tmp_path / "X_Report_2026-08-07_0000.html"
    p.write_text("<html></html>")
    write_sidecar(str(p), "policy_diff", "html", record_count=3)
    meta = _read_sidecar(str(p))
    assert meta["report_type"] == "policy_diff"
    assert meta["file_format"] == "html"
    assert meta["record_count"] == 3
    assert "generated_at" in meta


def test_policy_diff_export_writes_sidecar(tmp_path):
    from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
    path = PolicyDiffHtmlExporter({}, lang="en").export(str(tmp_path))
    assert _read_sidecar(path)["report_type"] == "policy_diff"


def test_policy_resolver_export_writes_sidecar(tmp_path):
    from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter
    paths = PolicyResolverExporter({"rulesets": {}}, lang="en").export(str(tmp_path), fmt="json")
    for p in paths:
        assert _read_sidecar(p)["report_type"] == "policy_resolver"


def test_app_summary_export_writes_sidecar(tmp_path):
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    path = AppSummaryHtmlExporter({}, lang="en").export(str(tmp_path))
    assert _read_sidecar(path)["report_type"] == "app_summary"
```

（exporter 以空 dict 建構若 render 需要必要鍵而拋錯，執行時以最小合法 results dict 取代——以各 `_render_html` 實際取用的鍵為準補齊，測試意圖不變。ven_status 的 generate 需要 ApiClient 樁，成本高：ven_status 部分改以「wiring 斷言」覆蓋——source-gate 斷言 `ven_status_generator.py` 含 `write_sidecar(` 呼叫，真機驗證補行為證據。）

```python
def test_ven_status_generator_wires_sidecar():
    src = (Path(__file__).parent.parent / "src" / "report" / "ven_status_generator.py").read_text(encoding="utf-8")
    assert "write_sidecar(" in src, "ven_status generator must write metadata sidecar"
```

- [ ] **Step 2: 確認 RED** — `venv/bin/pytest tests/test_report_metadata_sidecar.py -v` → 全 FAIL

- [ ] **Step 3: 實作 helper** — `src/report/metadata_sidecar.py`：

```python
"""Metadata sidecar（<report>.metadata.json）共用寫入器。

report_scheduler 的 retention/歸因與 GUI 報表清單都以 sidecar 為準；
缺席時 fallback 到檔名 prefix 猜測（歷史坑：gui-report-split）。
Best-effort：寫失敗只 log，不得讓報表產出本體失敗。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from loguru import logger


def write_sidecar(report_path: str, report_type: str, file_format: str,
                  *, record_count: int = 0, date_range=None, **extra) -> None:
    payload = {
        "report_type": report_type,
        "file_format": file_format,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": int(record_count or 0),
        "date_range": list(date_range) if date_range else ["", ""],
    }
    payload.update(extra)
    try:
        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.warning("sidecar write failed for {}: {}", report_path, e)
```

- [ ] **Step 4: 逐型接線（每型都在「輸出檔路徑定案、寫檔成功後」呼叫）** —
  - `policy_diff_html_exporter.py` `export()`：`write_text_atomic(path, html)` 後加 `write_sidecar(path, "policy_diff", "html")`。
  - `policy_resolver_exporter.py`：`export_json` 寫檔後 `write_sidecar(path, "policy_resolver", "json")`；`export_csv` 回傳前 `write_sidecar(path, "policy_resolver", "csv")`。
  - `app_summary_html_exporter.py` `export()`：寫檔後 `write_sidecar(path, "app_summary", "html")`。
  - `ven_status_generator.py`：HTML 寫檔成功處與 `generate_ven_xlsx` 寫檔成功處各加 `write_sidecar(<path>, "ven_status", "html"/"xlsx", record_count=<該報表的 VEN 數>)`（執行時重驗實際寫檔點；`record_count` 取 generate 流程既有的 result/analysis 計數）。

- [ ] **Step 5: 確認 GREEN** — `venv/bin/pytest tests/test_report_metadata_sidecar.py -q` PASS

- [ ] **Step 6: 真機重產驗證＋全套＋commit** — 測試機各手動產一份四型報表，`ls reports/*.metadata.json` 確認新檔皆有 sidecar，證據入回報（CLAUDE.md：報表批次交付前用實際樣本跑一次）。

```bash
venv/bin/pytest tests/ -x -q
git add src/report/metadata_sidecar.py src/report/exporters/policy_diff_html_exporter.py src/report/exporters/policy_resolver_exporter.py src/report/exporters/app_summary_html_exporter.py src/report/ven_status_generator.py tests/test_report_metadata_sidecar.py
git commit -m "feat(report): write metadata sidecar for ven_status, policy_diff, policy_resolver, app_summary"
```

---

### Task 13: rule_scheduler 設定選單去重（#11）【2C 重疊——條件式執行】

> **執行前判定（結果二擇一）：** 跑 `grep -n "settings_6\|rs_cfg_toggle" src/cli/menus/_root.py`。
> - **無命中** → 2C T7 已合入、`_root.py` 重複入口已移除、#11 已消滅：**整個 Task 13 跳過**，只在 ledger 記一行「#11 已由 2C T7 解決（grep 佐證）」。不要為單一呼叫端抽共用函式。
> - **有命中** → 2C 尚未執行，照下述步驟做去重；並在 commit 訊息尾註明「2C T7 移除 _root 入口後，共用函式僅剩 rule_scheduler_cli 一個呼叫端，屬預期」。

**Files:**
- Modify: `src/rule_scheduler.py`（模組層加共用 mutation 函式）
- Modify: `src/cli/menus/_root.py`（:164-188 改呼叫共用函式）
- Modify: `src/rule_scheduler_cli.py`（`_settings_submenu` :668-697 改呼叫共用函式）
- Test: `tests/test_rule_scheduler_settings_shared.py`（新建）

**Interfaces:**
- Produces（`src/rule_scheduler.py` 模組層）：

```python
def get_rs_settings(cm) -> tuple[bool, int]            # (enabled, check_interval_seconds)
def toggle_rs_enabled(cm) -> bool                      # 翻轉並 cm.save()，回新值
def set_rs_interval(cm, seconds: int) -> bool          # <=0 拒絕回 False；有效則存檔回 True
```

**失敗情境：** 同 config 鍵的邏輯兩份手抄（`_root.py` 版連儲存後回饋訊息都沒有）；下次改語意（如 interval 下限）必然只改到一邊——與「時間性 bug 修類不修點」記憶同構的分岔債。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_rule_scheduler_settings_shared.py`：

```python
"""#11：rule_scheduler enable/interval 設定在 _root.py 與 rule_scheduler_cli.py
重複實作。mutation 邏輯上收 src/rule_scheduler.py，兩選單只留 UI。"""
from unittest.mock import MagicMock

from src.rule_scheduler import get_rs_settings, set_rs_interval, toggle_rs_enabled


def _cm(cfg=None):
    cm = MagicMock()
    cm.config = cfg if cfg is not None else {}
    return cm


def test_defaults():
    assert get_rs_settings(_cm()) == (False, 300)


def test_toggle_persists():
    cm = _cm({"rule_scheduler": {"enabled": False}})
    assert toggle_rs_enabled(cm) is True
    assert cm.config["rule_scheduler"]["enabled"] is True
    cm.save.assert_called_once()


def test_set_interval_rejects_nonpositive():
    cm = _cm()
    assert set_rs_interval(cm, 0) is False
    assert set_rs_interval(cm, -5) is False
    cm.save.assert_not_called()


def test_set_interval_persists():
    cm = _cm()
    assert set_rs_interval(cm, 120) is True
    assert cm.config["rule_scheduler"]["check_interval_seconds"] == 120
    cm.save.assert_called_once()


def test_both_menus_delegate():
    # 守門：兩個選單檔不得再各自直改 config（防重複實作復活）
    from pathlib import Path
    root = Path(__file__).parent.parent / "src"
    for rel in ("cli/menus/_root.py", "rule_scheduler_cli.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert 'rs_c["enabled"] = not' not in src and 'rs_cfg["enabled"] = not' not in src, \
            f"{rel} must delegate to toggle_rs_enabled"
```

- [ ] **Step 2: 確認 RED** — `venv/bin/pytest tests/test_rule_scheduler_settings_shared.py -v` → FAIL（ImportError）

- [ ] **Step 3: 實作** — `src/rule_scheduler.py` 模組層：

```python
def get_rs_settings(cm) -> tuple[bool, int]:
    rs = cm.config.get("rule_scheduler", {})
    return bool(rs.get("enabled", False)), int(rs.get("check_interval_seconds", 300))


def toggle_rs_enabled(cm) -> bool:
    rs = cm.config.setdefault("rule_scheduler", {})
    rs["enabled"] = not rs.get("enabled", False)
    cm.save()
    return rs["enabled"]


def set_rs_interval(cm, seconds: int) -> bool:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return False
    if seconds <= 0:
        return False
    cm.config.setdefault("rule_scheduler", {})["check_interval_seconds"] = seconds
    cm.save()
    return True
```

兩選單改為讀 `get_rs_settings`、選 1 呼叫 `toggle_rs_enabled`、選 2 呼叫 `set_rs_interval`（各自保留自己的輸入/列印 UI；`_root.py` 版順帶補上與 `_settings_submenu` 相同的 `rsc_toggle_result`/`rsc_interval_result` 回饋訊息，鍵已存在）。

- [ ] **Step 4: 確認 GREEN** — `venv/bin/pytest tests/test_rule_scheduler_settings_shared.py tests/test_main_menu.py -q` PASS

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/rule_scheduler.py src/cli/menus/_root.py src/rule_scheduler_cli.py tests/test_rule_scheduler_settings_shared.py
git commit -m "refactor(cli): dedupe rule scheduler settings menu logic"
```

---

### Task 14: analysis.lock 測試隔離（#17）

**Files:**
- Modify: `src/main.py`（`analysis_lock_path` :30-42 加 env override）
- Modify: `tests/conftest.py`（autouse fixture）
- Test: `tests/test_analysis_lock_isolation.py`（新建）

**失敗情境：** `analysis_lock_path()` 硬錨 repo root 的 `logs/analysis.lock`；平行測試（或測試與本機常駐 GUI 同時跑）搶同一把真實 flock → `test_main_menu.py` 偶發 timeout 失敗（2026-08-06 CI hotfix 已實錄一次 transient）。

- [ ] **Step 1: 寫 RED 測試** — `tests/test_analysis_lock_isolation.py`：

```python
"""#17：analysis.lock 硬錨 repo root，測試搶真實 flock → 偶發失敗。
修法：ILLUMIO_OPS_ANALYSIS_LOCK 環境變數 override＋conftest autouse 隔離。"""
import os

from src.main import analysis_lock_path


def test_env_override_wins(monkeypatch, tmp_path):
    target = str(tmp_path / "analysis.lock")
    monkeypatch.setenv("ILLUMIO_OPS_ANALYSIS_LOCK", target)
    assert analysis_lock_path() == target


def test_default_unchanged_without_env(monkeypatch):
    monkeypatch.delenv("ILLUMIO_OPS_ANALYSIS_LOCK", raising=False)
    p = analysis_lock_path()
    assert p.endswith(os.path.join("logs", "analysis.lock"))


def test_conftest_isolates_lock_for_tests():
    # conftest 的 autouse fixture 必須讓測試行程看到的鎖檔不在 repo logs/
    p = analysis_lock_path()
    repo_logs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    assert not p.startswith(repo_logs), f"tests must not contend on real lock: {p}"
```

- [ ] **Step 2: 確認 RED** — `venv/bin/pytest tests/test_analysis_lock_isolation.py -v` → 第 1、3 個 FAIL

- [ ] **Step 3: 實作** — `analysis_lock_path` 開頭加：

```python
    override = os.environ.get("ILLUMIO_OPS_ANALYSIS_LOCK")
    if override:
        return override
```

`tests/conftest.py` 加（session 級即可，鎖檔本身允許共用一個 tmp）：

```python
@pytest.fixture(autouse=True, scope="session")
def _isolate_analysis_lock(tmp_path_factory):
    """#17：測試不得搶 repo logs/analysis.lock 真鎖（transient 失敗來源）。"""
    lock = tmp_path_factory.mktemp("locks") / "analysis.lock"
    os.environ["ILLUMIO_OPS_ANALYSIS_LOCK"] = str(lock)
    yield
    os.environ.pop("ILLUMIO_OPS_ANALYSIS_LOCK", None)
```

（`scheduler/jobs.py` 與 `gui/routes/actions.py` 皆在呼叫時才取 `analysis_lock_path()`，env override 對三個入口一體生效，無需另改。）

- [ ] **Step 4: 確認 GREEN＋穩定性抽測**

```bash
venv/bin/pytest tests/test_analysis_lock_isolation.py -q
venv/bin/pytest tests/test_main_menu.py -q --count=5 2>/dev/null || for i in 1 2 3 4 5; do venv/bin/pytest tests/test_main_menu.py -q || break; done
```

Expected: PASS ×5（無 flake；若 pytest-repeat 未安裝走 for 迴圈）

- [ ] **Step 5: 全套＋commit**

```bash
venv/bin/pytest tests/ -x -q
git add src/main.py tests/conftest.py tests/test_analysis_lock_isolation.py
git commit -m "fix(tests): isolate analysis lock file via env override"
```

---

### Task 15: venv 舊路徑 shebang 一次性修復（#18，**不產生 commit**）

**Files:** 無版本控管變更（venv/ 已 gitignore）。

**現況：** repo 由 `/home/harry/dev/illumio-ops` 搬到 `/home/harry/rd/illumio-ops` 後，`venv/bin/` 大量 script（pip、pip3、pip-compile、pip-sync、pytest、flask、activate 系列等）shebang／內嵌路徑仍指舊位置（`pip-audit` 例外，曾單獨重裝）。CI 不受影響（CI 自建環境），只咬本機。

- [ ] **Step 1: 盤點受影響檔案**

```bash
grep -rl 'dev/illumio-ops' /home/harry/rd/illumio-ops/venv/bin/ | tee /tmp/stale-shebang-list
```

- [ ] **Step 2: 批次改寫（僅文字檔會被 sed 動到；二進位不含該字串不受影響）**

```bash
grep -rlZ 'dev/illumio-ops' /home/harry/rd/illumio-ops/venv/bin/ | xargs -0 sed -i 's|/home/harry/dev/illumio-ops|/home/harry/rd/illumio-ops|g'
```

- [ ] **Step 3: 驗證（指令＋輸出附回報）**

```bash
grep -rl 'dev/illumio-ops' /home/harry/rd/illumio-ops/venv/bin/ ; echo "residual=$?"   # 期望 residual=1（無殘留）
/home/harry/rd/illumio-ops/venv/bin/pip --version
/home/harry/rd/illumio-ops/venv/bin/pytest --version
/home/harry/rd/illumio-ops/venv/bin/pip-compile --version
```

- [ ] **Step 4:（可保險）若任何 script 執行仍異常，改用重建法**：`venv/bin/python3 -m pip install --force-reinstall pip pip-tools pytest`；再不行走 `python3 -m venv venv --upgrade-deps` 後 `pip install -r requirements.txt` 全重建。全程不 commit。

---

## Self-Review 紀錄

- **Spec 覆蓋**：18 條全數處置——15 條有任務（#1-#9、#11、#13、#15-#18 → Task 1-15）、3 條入豁免與裁決清單（#10 已修、#12 需裁決、#14 移交 2C）。
- **佔位符掃描**：Task 8 的端點測試與 Task 12 的最小 results dict 各有一處「執行時對齊既有 fixture／render 必要鍵」的接線點，皆已明文指出樣板來源（同檔既有樁法／`_render_html` 取用鍵）且斷言本體完整，非 TBD。
- **型別/命名一致性**：`VALID_REPORT_TYPES`（Task 2 定義、Task 3 消費）、`write_sidecar`（Task 12 內部）、`_normalize_dow`／`_report_type_options`／`_href_is_ruleset`／`get_rs_settings` 系列命名前後一致。
- **依賴順序**：Task 3 依賴 Task 2 的常數，其餘任務互相獨立、可穿插 2A-2C 執行。
