# 產品 bug backlog v2 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修完 2026-08-07 那份 2D backlog 在 2026-08-27 重驗後仍然成立的 13 條產品缺陷。

**Architecture:** 12 個 task，由小到大排列——先做一字之差與純後端的，最後做需要新 UI 的。每個 task 的邊界都是「一個可獨立驗證的行為改變」。

**Tech Stack:** Python 3.12、Flask、pytest、原生 ES modules（`src/static/js/v2/`）

**前置文件：** `docs/superpowers/plans/2026-08-07-phase2d-product-bugs.md`（**已過期，僅供查閱原始證據**。它的 15 個 task 中 4 條已被其他分支修掉、4 條需重寫、1 條豁免過期；所有行號都是 8 個分支以前的。**不要照它執行。**）

---

## 這份計畫為什麼存在

原 2D 計畫寫於 2026-08-07，之後 2A 重寫了整個 GUI 前端（`src/static/js/*.js` 全刪，改為 `src/static/js/v2/`），另有 7 個分支落地。2026-08-27 三組獨立重驗 ＋ 一次 Codex 對抗式複查後的結論：

- **丟棄 4 條**：#5（`7b0d6a34` 已刪 legacy）、#9 與 #16（`b1dcaf78` 已修）、#12（`a0e363ab` 已移除 `__length`，且已有守門測試——原本掛著的「需使用者裁決」自己消失了）
- **已交付 2 條**：#18 venv（2026-08-28 環境操作）、#6 的前置斷鏈（`91c5a877`）
- **本計畫涵蓋 13 條**

**重驗過程本身的教訓**：2B/2C/2D/2E 四份計畫**全都沒有執行過**（0 commit），而 2A 明明出貨了 checkbox 卻只勾 5/25。**checkbox 不能拿來判斷完成度，要看 commit。**

## Global Constraints

以下每一條都約束**每一個** task：

- **直譯器一律用 `venv/bin/pytest`**（2026-08-28 已修好，先前 24 支 console script 因 shebang 指向舊路徑而 exit 127）。不要用系統 `python3`——它的 click 是 8.1.6 而鎖檔釘 8.3.3，`CliRunner` 相關測試會假紅。
- **要退出碼就不要接管線。** `cmd > /tmp/out.txt 2>&1; echo "exit=$?"` 然後讀那個檔。本 session 已有四次把 `tail` 的退出碼當成程式退出碼的實例，其中兩次污染了回報給使用者的結論。
- **每個新守門測試都要突變驗證**：故意注入該被抓到的缺陷，確認變紅，還原，確認回綠，**紅綠輸出都貼進報告**。沒試過的加固不是加固，是希望。
- **驗證「設定是否真的送達」的測試，一律用真實 pydantic 物件，不要用 MagicMock。** `TrafficFilter(**MagicMock().model_dump())` 不會拋錯——MagicMock 的 `keys()` 迭代成空，靜默產生一個空 filter。用 mock 的測試從一開始就不可能抓到這類缺陷。
- **絕不移除 Windows workload 支援**（`windows_service_name` 全鏈、estate inventory 的 `"Windows"` 分支、相關 i18n 文案）。
- **歷史紀錄不動**：既有的 plans/specs、`docs/_meta/migration-audit.json`、CHANGELOG 既有版本條目、`reports/audit/`。
- 提交訊息用英文 conventional commits；`git add` 只用明確路徑，**永不 `git add -A`**。

---

### Task 1: `login_err_pw_short` 在已登入的 App 內顯示為字面字串（#10）

**Files:**
- Modify: `src/static/js/v2/areas/system.mjs:2035`

**Interfaces:** Consumes 無；Produces 無。

密碼變更表單呼叫 `t("login_err_pw_short")`。該鍵存在於字典（`i18n_en.json:2633`），但 `_ui_translation_dict`（`src/gui/_helpers.py:328-334`）只放行 `gui_` / `sched_` / `status_` / `error_` / `pd_` 前綴，所以它**不會**出現在 `/api/ui_translations`；而 `t()`（`core/i18n.mjs:69-74`）在查不到且無 fallback 時回傳鍵名本身。使用者看到的是字面的 `login_err_pw_short`。

`gui_login_err_pw_short` 已存在（`i18n_en.json:1740`）且 `login.mjs:251` 用的就是它。

- [ ] **Step 1: 先重現**

```bash
venv/bin/python -c "
import json
en = json.load(open('src/i18n_en.json'))
print('login_ 前綴會被白名單濾掉:', not 'login_err_pw_short'.startswith(('gui_','sched_','status_','error_','pd_')))
print('正確的鍵存在:', 'gui_login_err_pw_short' in en)
"
```

預期：`True` / `True`。

- [ ] **Step 2: 改鍵名**

`src/static/js/v2/areas/system.mjs:2035`：`t("login_err_pw_short")` → `t("gui_login_err_pw_short")`。**只改這一處**，不要動 `login.mjs`（它已經是對的）。

- [ ] **Step 3: 加守門**

既有的 `tests/test_login_js_pw_length_coherence.py` **只掃 `login.mjs`**，所以抓不到 `system.mjs`。把它的掃描範圍擴及 `src/static/js/v2/areas/*.mjs`，斷言：任何 `.mjs` 都不得呼叫 `t()` 帶上非白名單前綴的鍵。

實作提示：用正則抓出所有 `t("...")` 的字面鍵，過濾出前綴不在白名單且不在 `_UI_EXTRA_KEYS` 的，斷言集合為空。**白名單要從 `src/gui/_helpers.py` 讀出來，不要在測試裡再抄一份**——抄一份就會漂移。

- [ ] **Step 4: 突變驗證**

把 `system.mjs` 改回 `t("login_err_pw_short")`，確認新守門變紅；還原，確認回綠。兩段輸出都貼進報告。

- [ ] **Step 5: 跑測試**

```bash
venv/bin/pytest tests/test_login_js_pw_length_coherence.py -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -3 /tmp/t.txt
venv/bin/pytest tests/ -q -k "i18n" > /tmp/t2.txt 2>&1; echo "exit=$?"; tail -3 /tmp/t2.txt
venv/bin/python scripts/audit_i18n_usage.py 2>&1 | grep Total
```

預期：全綠、i18n audit `Total: 0 finding(s)`。

- [ ] **Step 6: Commit**

```bash
git add src/static/js/v2/areas/system.mjs tests/test_login_js_pw_length_coherence.py
git commit -m "fix(gui): password form was showing a translation key, not a translation

The authenticated app asked for login_err_pw_short, which the UI
translation endpoint filters out by prefix, so t() fell back to
returning the key name itself. The gui_ prefixed twin already existed
and login.mjs already used it. The coherence test only scanned
login.mjs, which is why nothing caught it."
```

---

### Task 2: report_type 單一事實來源，API 與 CLI 各自強制（#2 ＋ #3）

**Files:**
- Modify: `src/report_scheduler.py`（新增模組層常數）
- Modify: `src/gui/routes/reports.py:130-157`
- Modify: `src/cli/menus/report_schedule.py:163-170`
- Modify: `tests/test_report_schedule_validation.py`（API 測試加在這裡——**已存在**，且已備妥登入 fixture、CSRF helper 與 `_post()`）
- Test: `tests/test_report_type_registry.py`（新建，只放 CLI↔後端同步的那條）

**Interfaces:**
- Produces: `src.report_scheduler.VALID_REPORT_TYPES: frozenset[str]` —— 11 種可排程報表型別的唯一事實來源。
- Consumes: 無。

**這兩條為什麼合成一個 task：** 原 2D 計畫把它們拆開，而 Task 3 的 Interfaces 寫著要消費 `VALID_REPORT_TYPES`，那個符號由 Task 2 產出——但原計畫的 Task 2 根本沒有產出它（`grep -rn VALID_REPORT_TYPES src/ tests/` 今日為零）。拆開就會踩到順序相依。

**現況：**
- API 的 `_validate_report_schedule` 驗 `cron_expr` / `schedule_type` / `hour` / `minute` / `day_of_month`，**完全不驗 `report_type`**；`add_report_schedule`（`src/config.py:658-664`）原封存進去；未知型別只在 `report_scheduler.py:500-502` 記一行 `logger.error` 然後跳過——排程看起來建立成功，永遠不產出東西。
- CLI 的 `type_map = {"1": "traffic", "2": "audit", "3": "ven_status"}`（`:163`），編輯其他 8 型時 `default_type_k` 取不到而落到 `"1"`，Enter 一下就把 readiness 排程**靜默改成 traffic**。
- v2 前端**已經修好了**（`automation.mjs:1591-1600` 把未知型別保留成自己的選項並加 `⚠` 與 `gui_au_rep_type_unknown` 提示），所以本 task **不需要碰前端**。

**已知陷阱（原計畫沒寫）：** `app_summary` 需要非空的 `app` 值——`report_scheduler.py:459-465` 會 `raise ValueError("app_summary schedule requires an 'app' value")`。CLI 精靈若只是把它加進 `type_map` 而不追問 app，就會產生一個每次 tick 都拋例外的排程。

- [ ] **Step 1: 先確認 11 型的權威清單**

```bash
grep -nE 'report_type ==|elif rtype|== "' src/report_scheduler.py | sed -n '1,40p'
```

把 `_generate_report` 的分派鏈逐一讀出來，列出實際支援的型別。**以這條分派鏈為準**，不要照抄任何文件或 select 選項。

- [ ] **Step 2: 寫失敗測試**

加進 `tests/test_report_schedule_validation.py`（沿用該檔既有的 `client` fixture 與 `_post()`，
**不要自己另造登入流程**——它已經處理好 CSRF 與 `REMOTE_ADDR`）：

```python
def test_unknown_report_type_rejected(client):
    r = _post(client, {"name": "x", "report_type": "not_a_real_type",
                       "schedule_type": "daily", "hour": 1, "minute": 0})
    assert r.status_code == 400
    assert "report_type" in r.get_json().get("error", "").lower()


def test_every_valid_report_type_accepted(client):
    from src.report_scheduler import VALID_REPORT_TYPES
    for rtype in sorted(VALID_REPORT_TYPES):
        body = {"name": f"s-{rtype}", "report_type": rtype,
                "schedule_type": "daily", "hour": 1, "minute": 0}
        if rtype == "app_summary":
            body["app"] = "SomeApp"      # 見下方陷阱說明
        r = _post(client, body)
        assert r.status_code in (200, 201), (rtype, r.status_code, r.get_data(as_text=True))
```

新建 `tests/test_report_type_registry.py`，只放 CLI 與後端的同步守門：

```python
def test_cli_type_map_covers_every_schedulable_type():
    from src.report_scheduler import VALID_REPORT_TYPES
    from src.cli.menus import report_schedule as rs
    assert set(rs.type_map.values()) == set(VALID_REPORT_TYPES), (
        "CLI 精靈的型別對照表與後端分派鏈不同步：編輯未涵蓋的型別會被靜默改掉"
    )
```

**第二條測試（每種合法型別都被接受）比第一條重要**：只擋壞值的白名單很容易寫成過嚴而擋掉合法型別，
而那個失敗模式在生產環境是「使用者建不了排程」，比「壞排程被存下」更明顯但一樣是迴歸。

- [ ] **Step 3: 跑，確認兩條都紅**

```bash
venv/bin/pytest tests/test_report_schedule_validation.py tests/test_report_type_registry.py -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -5 /tmp/t.txt
```

預期：新增的三條全紅（既有 7 條仍綠）。

- [ ] **Step 4: 在 `report_scheduler.py` 定義常數**

放在 `_generate_report` 附近，並在註解裡寫明「新增型別時必須同時改分派鏈與此常數，`tests/test_report_type_registry.py` 會強制兩者同步」。

- [ ] **Step 5: API 補驗證**

在 `_validate_report_schedule` 的 `stype` 檢查之後、`monthly` 區塊之前插入 `report_type` 白名單檢查，回 400，錯誤訊息要含 `report_type` 與允許值。

- [ ] **Step 6: CLI 補全型別 ＋ 處理 app_summary**

`type_map` 由 `VALID_REPORT_TYPES` 產生（排序後編號），不要再手寫字面 dict。選到 `app_summary` 時必須追問 `app` 值且不接受空字串——否則建立出來的排程每 tick 都會 `raise`。

- [ ] **Step 7: 跑測試**

```bash
venv/bin/pytest tests/test_report_schedule_validation.py tests/test_report_type_registry.py tests/ -q -k "report_schedule" > /tmp/t.txt 2>&1; echo "exit=$?"; tail -4 /tmp/t.txt
```

- [ ] **Step 8: 突變驗證**

從 `type_map` 拿掉一個型別，確認 `test_cli_type_map_covers_every_schedulable_type` 變紅；還原。從 API 驗證拿掉 report_type 分支，確認另一條變紅；還原。四段輸出都貼進報告。

- [ ] **Step 9: 注意 v2 的 ⚠ 往返路徑**

`automation.mjs:1612-1620` 會把已存入的無效值原樣送回（附 `⚠`）。API 開始驗證之後，**重存一筆既有的壞排程會開始回 400**。這是預期行為（把「靜默永不觸發」換成「看得見的錯誤」），但要 `grep tests/test_v2_automation_e2e.py` 確認沒有測試斷言那條往返會成功。

- [ ] **Step 10: Commit**

```bash
git add src/report_scheduler.py src/gui/routes/reports.py src/cli/menus/report_schedule.py tests/test_report_schedule_validation.py tests/test_report_type_registry.py
git commit -m "fix(scheduler): one list of schedulable report types, enforced at both entry points

The API validated everything about a schedule except the one field
that decides whether it ever produces anything, and the CLI wizard
knew three of the eleven types -- editing any other one silently
rewrote it to traffic. Both now read the same frozenset the dispatch
chain is built from, and a test fails if they drift."
```

---

### Task 3: 週排程 `day_of_week` 驗證（#1）

**Files:**
- Modify: `src/gui/routes/reports.py`（`_validate_report_schedule`）
- Modify: `src/cli/menus/report_schedule.py:183-189`

**Interfaces:** Consumes Task 2 的驗證器結構；Produces 無。

`_validate_report_schedule` 沒有 `day_of_week` 分支；CLI 的 `_ask(t("sched_day_of_week"), default=day_of_week)` 是 `cast=str` 無選項集；`ReportSchedule`（`config_models.py:191-198`）是 `extra="allow"` 且沒有該欄位——所以 `"mon"` 一路存進去，而 `report_scheduler.py:259-260` 比對的是 `strftime("%A").lower()`（即 `monday`），**排程永遠不觸發且無任何訊號**。

GUI 表單送的是全名，本來就相容；缺口只在 API 與 CLI。

- [ ] **Step 1: 寫失敗測試**（API 收 `"mon"` 應回 400；CLI 精靈輸入 `"mon"` 應重問）
- [ ] **Step 2: 跑，確認紅**
- [ ] **Step 3: API 補 `weekly` 分支**——只接受 `monday`..`sunday`（小寫全名），錯誤訊息列出允許值
- [ ] **Step 4: CLI 補重問迴圈**——沿用該檔既有的重問樣式，不要自創
- [ ] **Step 5: 跑測試 ＋ 突變驗證**（各拿掉一邊的驗證，確認對應測試變紅）
- [ ] **Step 6: Commit** — `fix(scheduler): validate weekly day_of_week at the API and in the CLI wizard`

---

### Task 4: `has_draft_changes` 的父 RuleSet 檢查涵蓋 deny rules 與 legacy rules（#7）

**Files:**
- Modify: `src/api_client.py:1298-1309`

`:1304` 的 `if "/sec_rules/" in draft_href:` 是唯一的父檢查，但 `toggle_and_provision`（`:1325`）對任何非 ruleset href 都會用 `"/".join(draft_href.split("/")[:7])` 推出父 ruleset 並整個 provision。deny rules 是本專案可排程的物件（`gui/routes/rule_scheduler.py:169-171`），href 含 `/deny_rules/`——所以父 ruleset 有 pending draft 時會被連帶推出去，而 sec_rules 有防護、deny_rules 沒有。

**Codex 補充：也漏了產品支援的 legacy `/rules/` collection**（`gui/routes/rule_scheduler.py:158`）。

- [ ] **Step 1: 寫失敗測試**——deny rule href ＋ 父 ruleset 有 draft，斷言 `has_draft_changes` 回 True
- [ ] **Step 2: 跑，確認紅**（現況會回 False）
- [ ] **Step 3: 把 `:1304` 的單一比對改為三者**：`("/sec_rules/", "/deny_rules/", "/rules/")`
- [ ] **Step 4: 跑測試**——這是對 fail-closed 檢查的純增補，迴歸風險低；`tests/test_rule_note_tag_strip.py` 有可照抄的 stub 樣式
- [ ] **Step 5: 突變驗證** ＋ **Commit** — `fix(api): draft check covers deny and legacy rule collections, not just sec_rules`

---

### Task 5: `is_ruleset` 由伺服端從 href 推導（#13）

**Files:**
- Modify: `src/gui/routes/rule_scheduler.py:349`

`"is_ruleset": data.get('is_ruleset', False)` 原封收下 client 送的旗標，不與 href 形狀對帳。旗標錯 → `toggle_and_provision` 的 provision 範圍推導錯誤。

v2 前端**目前推得是對的**（`automation.mjs:743` 由 href 正則決定），所以今天的 UI 產不出不一致——但端點對任何呼叫端（含直接打 API 或被竄改的請求）都照單全收。

**知會：** 伺服端保證一致之後，`automation.mjs:483-487` 的 `targetMismatch()` 會變成死碼。**先 grep `tests/test_v2_automation*` 確認沒有測試斷言那個不一致橫幅存在**，再決定是否一併刪除；若有測試釘住，本 task 不刪，另記 backlog。

- [ ] **Step 1: 寫失敗測試**——送出與 href 矛盾的 `is_ruleset`，斷言存下來的值是由 href 推導的
- [ ] **Step 2: 跑，確認紅**
- [ ] **Step 3: 加模組層 `_href_is_ruleset()`，在 `:349` 使用，不一致時 `logger.warning`**
- [ ] **Step 4: 跑測試 ＋ 突變驗證 ＋ Commit** — `fix(gui): derive is_ruleset from the href instead of trusting the caller`

---

### Task 6: hero KPI 以 `label_key` 比對（#4）

**Files:**
- Modify: `src/dashboard_hero.py:45-46`

`if "maturity" not in label` 比對的是**已經被在地化**的 label——`_retranslate_kpi_labels`（`gui/routes/dashboard.py:27-52`）會用當前語言覆寫，中文機上是「微分段成熟度」，永遠比不中。實測：zh → `score 0.0 / grade "?"`；en → `72.5 / "B"`。

KPI 帶有 `label_key: "mod12_kpi_maturity_score"`（`mod12_executive_summary.py:265`）可用。

**注意（Codex 補充）：** v2 已經**繞過**這個 bug——`overview.mjs:914-919` 直接讀 snapshot 的 `maturity_score` / `maturity_grade`，並留了註解指名這個缺陷。所以主 UI 目前不會顯示 0/?，但 **API payload 仍然是錯的**，任何其他消費者都會拿到壞值。修好之後，那段繞道註解可以移除（一併做，並在報告中說明）。

- [ ] **Step 1: 寫失敗測試**——中文語系下斷言 hero 取到正確 score/grade
- [ ] **Step 2: 跑，確認紅**
- [ ] **Step 3: 改用 `kpi.get("label_key") == "mod12_kpi_maturity_score"`，保留原本的子字串比對作為 legacy snapshot 的 fallback**（`_retranslate_kpi_labels:47` 明確容忍沒有 `label_key` 的舊快照）
- [ ] **Step 4: 跑測試 ＋ 突變驗證 ＋ 移除 `overview.mjs` 的繞道註解 ＋ Commit**

---

### Task 7: 四型報表補 metadata sidecar（#15）

**Files:**
- Modify: `src/report/ven_status_generator.py:176`
- Modify: `src/report/exporters/policy_diff_html_exporter.py:178`
- Modify: `src/report/exporters/policy_resolver_exporter.py:29-63`
- Modify: `src/report/exporters/app_summary_html_exporter.py:190`

寫 sidecar 的只有 traffic 家族、audit、policy_usage、rule_hit_count、readiness。**ven_status / policy_diff / policy_resolver / app_summary 四型不寫**，所以 `/api/reports`（`gui/routes/reports.py:204-222`）對它們的 `report_type` / `summary` / `execution_stats` 一律回空。

**兩點 Codex 補充，原計畫沒有：**
1. **排程路徑其實會建 sidecar**——`report_scheduler.py:726` 的 `_stamp_schedule_id()` 會從零建一個，但內容只有 `schedule_id`。所以「完全沒有 sidecar」只對 manual/direct exporter 成立；新寫入必須**合併**而非覆蓋，否則會洗掉 `schedule_id`。
2. **v2 有客戶端 band-aid**——`reports.mjs:420-431` 的 `derivedType` 由檔名前綴回推 `policy_diff` / `policy_resolver` / `app_summary`，**但沒有 ven_status**（`Illumio_VEN_Report_` 無前綴規則）。所以最明顯的使用者症狀是 ven_status。修好後可考慮移除 band-aid，但**那要另開 task**，本 task 不動前端。
3. `/api/reports` 不列 `.json`（`reports.py:193`），而 policy_resolver 可能只輸出 JSON——補了 sidecar 它仍不會出現在清單。**這條列為已知殘留，本 task 不處理，寫進報告。**

- [ ] **Step 1: 讀既有寫入者的樣式**（`report_generator.py:844` 是範本）並抽成共用 helper
- [ ] **Step 2: 寫失敗測試**——四型各產一次，斷言 sidecar 存在且含 `report_type` 與 `summary`
- [ ] **Step 3: 跑，確認四條全紅**
- [ ] **Step 4: 四個 call site 接上 helper，採合併語意（保留既有 `schedule_id`）**
- [ ] **Step 5: 寫一條測試證明合併不會洗掉 `schedule_id`**
- [ ] **Step 6: 跑測試 ＋ 突變驗證 ＋ Commit**

---

### Task 8: 測試隔離——analysis lock 與 ScheduleDB（#17 ＋ E1）

**Files:**
- Modify: `src/main.py:30-42`（`analysis_lock_path()`）
- Modify: `tests/conftest.py`
- Modify: `tests/test_v2_automation_e2e.py`

**兩條合成一個 task 的理由：** 同一個病——測試依賴共享的真實檔案狀態卻不自己準備。

**#17：** `analysis_lock_path()` 由 `__file__` 錨定 `<repo>/logs/analysis.lock`，無 env 或參數 override；`scheduler/jobs.py:45`、`gui/routes/actions.py:524` 同路徑。`tests/test_api_settings.py:344` 與 `tests/test_pce_flush.py:28` 各自 monkeypatch 它（證明這個作法可行），但 `test_main_menu.py` 沒有，它的 option-7 測試會在工作目錄上取一個 5 秒逾時的真 flock。

**可達性比原計畫窄：** `pytest.ini` 沒有 `-n`、CI 跑純 `pytest`、`xdist` 未安裝——所以要撞上需要同一個 checkout 上有第二個行程（跑著的 `--monitor-gui` 服務，或開發者的第二個 pytest）。**仍要修**，因為那兩個條件在開發機上都成立。

**E1：** `tests/test_v2_automation_e2e.py` 的兩個測試斷言 `existing == []`（"this test requires a schedule-free ScheduleDB"），但不自己清空——`config/rule_schedules.json` 有殘留就紅。2026-08-28 在本機重現：主 checkout 有 3 筆殘留 → 紅；乾淨 worktree → 綠。

- [ ] **Step 1: `analysis_lock_path()` 加 env override**（例如 `ILLUMIO_OPS_ANALYSIS_LOCK`），預設行為不變
- [ ] **Step 2: `conftest.py` 加 autouse fixture**，把該 env 指到 `tmp_path`
- [ ] **Step 3: 讓 `test_v2_automation_e2e.py` 的相關測試自備乾淨 ScheduleDB**（fixture 指向 tmp 路徑，或在 setup 清空），**不要靠外部狀態剛好乾淨**
- [ ] **Step 4: 突變驗證**——在 `config/rule_schedules.json` 塞一筆假排程，確認那兩個測試**仍然綠**（證明它們不再依賴外部狀態）；還原
- [ ] **Step 5: 跑全套兩次**，確認 `test_main_menu.py` 不再偶發
- [ ] **Step 6: Commit** — `fix(tests): isolate the analysis lock and the schedule store from the working checkout`

---

### Task 9: rule scheduler 設定選單去重（#11）

**Files:**
- Modify: `src/cli/menus/_root.py:213-236`
- Modify: `src/rule_scheduler_cli.py:668-699`

同樣兩個 config 鍵（`rule_scheduler.enabled` / `check_interval_seconds`）有兩套手繪選單，連框線繪製都複製，且行為不同：`rule_scheduler_cli` 改完會印 `rsc_toggle_result` / `rsc_interval_result`，`_root` 版**改完沒有任何回饋**就 `cm.save()`。

**必須先解決的差異：** `_root` 用 `safe_input`，`rule_scheduler_cli` 用裸 `clean_input(input(...))`。共用 helper 只能挑一種輸入契約——**挑 `safe_input`**（它是本專案較新的、有處理中斷的那個），並在報告中說明。

- [ ] **Step 1: 讀兩處，列出行為差異表**（輸入契約、回饋訊息、驗證範圍）
- [ ] **Step 2: 寫測試**——斷言兩個入口對同一組輸入產生相同的 config 結果**且都有回饋訊息**
- [ ] **Step 3: 跑，確認 `_root` 那條因缺回饋而紅**
- [ ] **Step 4: 抽出共用 helper，兩處都改為呼叫它**
- [ ] **Step 5: 跑測試 ＋ 突變驗證 ＋ Commit**

---

### Task 10: 三支 standalone CLI 補 `draw_panel` 外框（#14）

**Files:**
- Modify: `src/pce_cache_cli.py:10-14`
- Modify: `src/siem_cli.py:9-14`
- Modify: `src/rule_scheduler_cli.py:645-650, 674-681`
- Modify: 三本 i18n 字典

**豁免已過期。** 這條原本豁免的理由是「2C 會依 `design/v2/cli-flows.md` 重組全部互動選單」——但 **2C 從未執行**（0 commit、0 checkbox），所以前提不成立。

**這條為什麼自成一個 task：** `pcc_menu` / `sic_menu` 是**單一大塊字串**（`1. …\n  2. …` 純文字），要用 `draw_panel(title, lines)` 就得先拆成逐行的 i18n 鍵或依 `\n` 切開——那會動到三本字典，必須過 glossary 與 parity 閘門。`rule_scheduler_cli` 是手繪 `╭──│╰`，相對機械。

- [ ] **Step 1: 讀 `draw_panel` 契約**（`src/cli/_render.py:398`）與其他選單模組的呼叫樣式
- [ ] **Step 2: 決定 `pcc_menu` / `sic_menu` 的拆法並在報告中說明**（拆成逐行鍵 vs 依 `\n` 切）——**兩者都可，但要說出取捨**
- [ ] **Step 3: 三支各自改為 `draw_panel`**
- [ ] **Step 4: 跑 i18n 全鏈閘門**

```bash
venv/bin/python scripts/audit_i18n_usage.py 2>&1 | grep Total
venv/bin/python scripts/precompute_zh_translations.py --dry-run 2>&1 | tail -1
venv/bin/pytest tests/ -q -k "glossary or i18n" > /tmp/t.txt 2>&1; echo "exit=$?"; tail -3 /tmp/t.txt
```

預期：`Total: 0 finding(s)`、`would update 0 keys`、全綠。

- [ ] **Step 5: 真機視覺確認**——三支選單各截一次輸出貼進報告（本專案 CLI 改動有欄寬 overflow 的前科）
- [ ] **Step 6: Commit**

---

### Task 11: `exclude_src_ips` 端到端支援 CIDR（#6）

**Files:**
- Modify: `src/config_models.py`（`TrafficFilterSettings._validate_ips`）
- Modify: `src/pce_cache/traffic_filter.py`（`TrafficFilter.__init__` / `passes`）
- Modify: `src/static/js/v2/areas/system.mjs:855-866, 1151`
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`、`src/i18n/data/zh_explicit.json`（移除 `gui_sy_tf_cidr_bug`）

**前置已完成：** filter 從未接進 `run_traffic_ingest` 這條更根本的斷鏈已於 `91c5a877` 修好。在那之前，改 CIDR 也不會有任何效果。

**使用者已裁決：做端到端支援，不撤回文案。** 理由：`exclude_src_ips` 是操作者排除掃描器／監控流量的唯一手段，而掃描器通常就是一整個網段；只允許精確 IP 等於要人列舉整個子網。

**現況四層：**
- `system.mjs:861-866` `validateIp` 兩個字元類都沒有 `/`，拒絕 CIDR；IPv6 分支是 `/^[\da-fA-F:]+$/` 加「至少有一個冒號」，所以 `"::::"` 會過
- `config_models.py` 的 `_validate_ips` 用 `ipaddress.ip_address`，拒絕 CIDR
- `TrafficFilter` 是 `flow.get("src_ip") in self._excl_src` 精確集合比對
- `system.mjs:1151` 有一則 `gui_sy_tf_cidr_bug` 提示**在產品裡自承這個 bug**

**設計決定（已釘死，不要自行更動）：**

1. **混合語意**：`exclude_src_ips` 同時容納精確 IP 與 CIDR。分類法：字串含 `/` → `ip_network(..., strict=False)`；否則 → `ip_address`。**驗證器與 `TrafficFilter.__init__` 兩處用同一條規則。**
2. **精確 IP 走原本的 set（O(1)）**，只有含 `/` 的進網段清單。**現有設定的行為必須逐位元不變**——這個功能自 `91c5a877` 起已在真機生效。
3. **只在 `__init__` 解析一次，絕不在 `passes()` 裡解析字串。** `passes()` 每一筆 flow 都會呼叫（真機每輪 fetch 300+ 筆），而本功能的用途正是設定多個網段。
4. **v4／v6 分開存放**，比對時先看版本再比；跨版本一律**不匹配**，不得拋例外（`ipaddress` 在某些形式下對跨版本比對會 `TypeError`）。
5. **空字串要安全**：`_flatten_flow` 產出的是 `flow.get("src_ip","") or src.get("ip","")`，可能是 `""`。`passes({"src_ip": ""})` 不得拋例外。（真機 65k 筆現況 0 空值，但程式路徑允許。）
6. **IPv6 的 `"::::"` 漏洞在範圍內**——那則自承提示點名了它。

**真機事實（已查證）：** `src_ip` 永遠是字串、無 NULL、無含 `/`、**有 492 筆 IPv6**。所以 v6 路徑是會走到的，不是理論。

- [ ] **Step 1: 寫失敗測試**（先全部寫完再實作）

```python
import pytest
from src.pce_cache.traffic_filter import TrafficFilter
from src.config_models import TrafficFilterSettings


@pytest.mark.parametrize("entry, ip, excluded", [
    ("10.0.0.5",        "10.0.0.5",      True),   # 精確 v4，行為不得改變
    ("10.0.0.5",        "10.0.0.6",      False),
    ("10.0.0.0/24",     "10.0.0.99",     True),   # v4 CIDR
    ("10.0.0.0/24",     "10.0.1.1",      False),
    ("10.0.0.7/24",     "10.0.0.1",      True),   # 非網路位址 → strict=False
    ("2001:db8::/32",   "2001:db8::1",   True),   # v6 CIDR
    ("2001:db8::/32",   "2001:dba::1",   False),
    ("10.0.0.0/24",     "2001:db8::1",   False),  # 跨版本不匹配且不拋例外
    ("2001:db8::/32",   "10.0.0.1",      False),
])
def test_exclude_matches_exact_and_cidr(entry, ip, excluded):
    f = TrafficFilter(exclude_src_ips=[entry])
    assert f.passes({"src_ip": ip, "port": 1, "protocol": "TCP", "action": "allowed"}) is not excluded


def test_empty_src_ip_does_not_raise():
    f = TrafficFilter(exclude_src_ips=["10.0.0.0/24"])
    assert f.passes({"src_ip": "", "port": 1, "protocol": "TCP", "action": "allowed"}) is True


@pytest.mark.parametrize("good", ["10.0.0.1", "10.0.0.0/24", "2001:db8::1", "2001:db8::/32"])
def test_settings_accepts_ip_and_cidr(good):
    assert TrafficFilterSettings(exclude_src_ips=[good]).exclude_src_ips == [good]


@pytest.mark.parametrize("bad", ["not-an-ip", "10.0.0", "10.0.0.0/33", "::::", "10.0.0.0/", "/24"])
def test_settings_rejects_malformed(bad):
    with pytest.raises(ValueError):
        TrafficFilterSettings(exclude_src_ips=[bad])


def test_networks_are_parsed_once_not_per_flow():
    """passes() 每筆 flow 都會被呼叫；解析必須在 __init__ 完成。"""
    import inspect
    src = inspect.getsource(TrafficFilter.passes)
    for forbidden in ("ip_network", "ip_address"):
        assert forbidden not in src, f"passes() 不得在每筆 flow 解析字串（發現 {forbidden}）"
```

- [ ] **Step 2: 跑，確認全紅**

```bash
venv/bin/pytest tests/test_traffic_filter_cidr.py -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -5 /tmp/t.txt
```

- [ ] **Step 3: 改 `TrafficFilterSettings._validate_ips`**——含 `/` 走 `ip_network(strict=False)`，否則 `ip_address`；錯誤訊息要能分辨兩種失敗
- [ ] **Step 4: 改 `TrafficFilter.__init__`**——精確 IP 留在 set，含 `/` 的解析成 `ip_network` 並依版本分成兩個 list
- [ ] **Step 5: 改 `TrafficFilter.passes`**——先查 set（O(1)），未命中再依版本線性掃描網段；`src_ip` 為空或無法解析時視為不匹配，**不得拋例外**
- [ ] **Step 6: 改前端 `validateIp`**——接受 `/`，並修掉 `"::::"`。前端只做早期提示，權威驗證在 pydantic
- [ ] **Step 7: 移除自承提示的完整鏈**
  - `system.mjs:1151` 的 `note(t("gui_sy_tf_cidr_bug"))` 呼叫
  - `src/i18n_en.json`、`src/i18n_zh_TW.json`、**`src/i18n/data/zh_explicit.json`** 三處的 `gui_sy_tf_cidr_bug`（**這個鍵在正本裡，與 `gui_sy_restart_i_409` 不同**）
- [ ] **Step 8: 跑測試與 i18n 全鏈**

```bash
venv/bin/pytest tests/test_traffic_filter_cidr.py tests/ -q -k "traffic_filter or config_valid or ingest" > /tmp/t.txt 2>&1; echo "exit=$?"; tail -4 /tmp/t.txt
venv/bin/python scripts/audit_i18n_usage.py 2>&1 | grep Total
venv/bin/python scripts/precompute_zh_translations.py --dry-run 2>&1 | tail -1
```

預期：全綠、`Total: 0 finding(s)`、`would update 0 keys`。

- [ ] **Step 9: 真機回歸驗證（必做）**

現有設定的行為必須不變。在真機上以真實 config 建 filter，跑 500 筆真實快取資料：

```bash
ssh illumio-ops-test 'cd /root/illumio-ops && ./venv/bin/python -c "
import sqlite3
from src.config import ConfigManager
from src.pce_cache.traffic_filter import TrafficFilter
f = TrafficFilter(**ConfigManager().models.pce_cache.traffic_filter.model_dump())
db = sqlite3.connect(\"data/pce_cache.sqlite\")
cols=[r[1] for r in db.execute(\"PRAGMA table_info(pce_traffic_flows_raw)\")]
kept=sum(1 for row in db.execute(\"SELECT * FROM pce_traffic_flows_raw ORDER BY RANDOM() LIMIT 500\")
         if f.passes({k:dict(zip(cols,row)).get(k) for k in (\"action\",\"src_ip\",\"port\",\"protocol\")}))
print(\"保留:\", kept, \"/ 500\")
"'
```

預期：**500 / 500**（該機 `actions` 為 `[]`、`exclude_src_ips` 為空）。**若不是 500，停下來回報**——代表改動影響了現有行為。

- [ ] **Step 10: 突變驗證 ＋ Commit**

---

### Task 12: DLQ 清除（#8）

**Files:**
- Modify: `src/siem/web.py:309-323`（`purge_dlq`）
- Modify: `src/siem/dlq.py`（新增 `purge_ids`）
- Modify: `src/static/js/v2/areas/system.mjs:1617-1723`
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`、`src/i18n/data/zh_explicit.json`

**這是本計畫唯一需要新增 UI 的 task，也是與原描述差距最大的一條。**

**現況（已逐項查證）：**
1. 後端 `purge_dlq` 只讀 `dest` ＋ `older_than_days`，**沒有 `ids` 分支**。而 `replay_dlq`（`:289-306`）有——`replay_ids`（`dlq.py:52-74`）是現成的對稱樣板。
2. 前端送 `{dest: destSel.value, older_than_days: 0}`（`:1706`），**清掉該 destination 全部**。
3. **v2 的 DLQ 表格根本沒有選取欄**（`dlqCols`, `:1617-1658`），但按鈕仍叫 `gui_dlq_purge_selected` /「清除所選」——**沒有東西可選**。
4. **「全部」destination 的值是空字串**（`destPairs`, `:1613`），而 `DeadLetterQueue.purge`（`dlq.py:78`）用 `destination == ""` 精確比對 → **靜默無效**，還 toast「已移除 0 筆」。
5. **Codex 補充：同一個空字串也讓列表失效**——`GET /dlq?dest=` 把空字串交給 `list_entries()`（`web.py:227`、`dlq.py:15`），所以預設「全部」畫面**看不到任何正常 destination 的 DLQ**。
6. `gui_sy_dlq_i_typed`（`i18n_en.json:5073`）已經過期——它告訴操作者確認框「仍寫著 purge N entries」，而 v2 的確認框並沒有。

**必須遵守的回應形狀（A3 twist）：** `purge_dlq` 成功時回 `{status:"ok", removed:N}`——**沒有 `ok` 欄位**；失敗時才回 `{ok:false, error, description}`。所以判斷成功要看 `res.error` 是否存在，**不能用 `res.ok !== true`**（那會把每次成功都當成失敗）。`system.mjs:1632` 附近的 replay handler 有完整註解說明這個坑，照它的形狀寫。

- [ ] **Step 1: 決定「全部」的語意並在報告中說明**

兩個合理選項：(a)「全部」在清除時停用（只能選具體 destination）；(b)「全部」真的清除所有 destination。**選 (a)**——清除是不可逆操作，把「全部」做成一鍵清光整個 DLQ 風險過高，而現況那個靜默無效反而意外地保護了使用者。**列表的「全部」則要修成真的顯示全部**（那是唯讀操作，語意自然）。

- [ ] **Step 2: 寫失敗測試**（後端）——`purge_dlq` 帶 `ids` 只刪那幾筆；`list_entries` 對空 dest 回傳所有 destination
- [ ] **Step 3: 跑，確認紅**
- [ ] **Step 4: 後端**——`dlq.py` 加 `purge_ids`（比照 `replay_ids`）；`web.py` 的 `purge_dlq` 加 `ids` 分支；`list_entries` 對空/缺 dest 不加 destination 條件
- [ ] **Step 5: 前端**——`dlqCols` 加選取欄與選取狀態（`:1632` 的 per-row Replay 按鈕是可照抄的樣式）；purge 送選取的 ids；清除時停用「全部」
- [ ] **Step 6: 文案**——`gui_sy_dlq_i_typed` 移除或改寫；`gui_sy_dlq_i_all` / `gui_sy_dlq_i_body` 依 Step 1 的裁決重寫；三本字典同步
- [ ] **Step 7: 跑測試**——`tests/test_v2_system_e2e.py:155,621,1109` 有引用 purge 按鈕標籤，必須同步
- [ ] **Step 8: 突變驗證 ＋ Commit**

---

## 收尾（orchestrator 執行，不是 task）

- [ ] 全套：`venv/bin/pytest tests/ -q > /tmp/final.txt 2>&1; echo "exit=$?"`
- [ ] 七道 CI 硬閘門，逐條跑並記錄輸出：
  1. `venv/bin/python -m pip_audit -r requirements.lock --strict`
  2. `venv/bin/python scripts/check_no_naive_datetime.py`
  3. `venv/bin/python scripts/check_doc_links.py`
  4. `venv/bin/python scripts/audit_i18n_usage.py`
  5. `venv/bin/mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`
  6. `venv/bin/pytest`
  7. `venv/bin/python -m pip_audit -r requirements-offline.lock --strict`
- [ ] 非 CI：`bash scripts/check_doc_coverage.sh`、`venv/bin/python scripts/docs_check.py --frontmatter`（**永遠 exit 0，看輸出；基準 7 條 dangling**）
- [ ] `venv/bin/python scripts/precompute_zh_translations.py --dry-run` → `would update 0 keys`
- [ ] 確認 `git status` 乾淨、主 checkout 未被污染
- [ ] 合 main → push → **`gh run view <id> --json conclusion -q .conclusion`（不要用 `gh run watch | tail`）** → 部署測試機 → 真機驗證

## 本計畫不處理（已記錄，不要順手做）

- **測試機 `unknown` 佔 83%（54,649 / 65,075）** —— 這是調查不是修復，值得單獨查為何多數 decision 是 unknown
- **`/api/reports` 不列 `.json`** —— policy_resolver 可能只輸出 JSON，補了 sidecar 仍不會出現在清單（Task 7 的已知殘留）
- **`reports.mjs` 的 `derivedType` band-aid** —— Task 7 修好後可移除，但要另開 task
- **2F-2（automation/rules 資訊架構）與 2F-3（UI 風格重做）** —— 連需求都還沒落地，需從 brainstorming 開始
