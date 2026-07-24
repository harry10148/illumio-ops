# Scheduler Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 2026-07-24 排程審查全部發現（Critical: cron 首跑永不觸發；High: 過期規則失敗仍刪、報表失敗不重試；Medium: 報表排程 CRUD 零驗證、rule create type 不一致、retention 共池互刪、monthly 月底日；Low: tick sched["id"]、days 非 list）。發現明細見 memory `scheduler-review-findings-2026-07-24`。

**Architecture:** report_scheduler.py（cron first-run 下界、失敗不推進 last_run、monthly 月底夾取、tick id 容錯）；rule_scheduler.py（過期失敗保留排程）；gui/routes/reports.py＋rule_scheduler.py（輸入驗證）；config_models.py（ReportSchedule typed 欄位）。

**Tech Stack:** Python（pytest、APScheduler）、i18n 雙 JSON。

## Global Constraints

- Commit 英文 conventional commits、無 emoji；i18n en/zh 同步；測試只用 tmp_path；四 CI 硬閘綠；全套 pytest 親跑；驗證命令不接 pipe 判斷成敗；worktree（EnterWorktree `scheduler-remediation`）。
- 行為變更記 CHANGELOG。時間邏輯改動附守門測試（本專案 archive 事故教訓：時間性行為要不變量守門）。

---

### Task 1: C1 — cron 排程首跑補跑下界

**Files:** `src/report_scheduler.py`（`should_run` cron 分支 ~184-194）；Test 既有 `tests/test_report_scheduler*.py`（先 grep）。

- [ ] Step 1 失敗測試：cron_expr="0 8 * * *"、last_run=None、now=08:00:23（tick 亞秒後）→ should_run 回 True（修前回 False 永不首跑）；now=07:59:23（cron 點前）→ False（不誤觸）；now=次日 08:05（跨多個未觸發週期後首查）→ True 且只補一次。
- [ ] Step 2 實作：模組常數 `_CRON_CATCHUP_WINDOW_SECONDS = 90`（略大於 daemon 60s tick，容 jitter）。cron 分支 prev 改：
```python
if last_run_dt:
    prev = last_run_dt.replace(tzinfo=tz_obj)
else:
    # last_run=None（從未跑）：get_next_fire_time(None, now) 恆回 ≥ceil(now)，
    # next<=now 只在 tick 落整秒才成立→cron 排程永不首跑（2026-07-24 審查 C1，
    # archive 首跑無限推遲事故重演）。給 prev 一個略大於 tick 的補跑下界，讓
    # 剛過的 cron 點能補跑一次（不 replay 舊週期——只回最近一個觸發點）。
    prev = now_aware - datetime.timedelta(seconds=_CRON_CATCHUP_WINDOW_SECONDS)
next_fire = trigger.get_next_fire_time(prev, now_aware)
```
- [ ] Step 3 綠。Commit `fix(scheduler): cron schedules fire on first run instead of deferring forever`

### Task 2: H — 報表失敗不推進 last_run（該期重試）＋有界 backoff 防 spam

**Files:** `src/report_scheduler.py`（`tick` ~757-766、`_save_state` ~79）；Test 同上。

- [ ] Step 1 失敗測試：run_schedule 拋例外 → last_run 不推進（下 tick should_run 仍 due，會重試）；但同一排程連續失敗有 backoff（不每 60s 重打）——記 `last_attempt`＋`consecutive_failures`，backoff = min(2^n * 60s, 3600s)，未到 backoff 不重試。
- [ ] Step 2 實作：`tick` 失敗分支改為只記 status/error/last_attempt/consecutive_failures，**不寫 last_run**；should_run 前置檢查 backoff（在 tick 內或 should_run 內判 `now - last_attempt < backoff → skip`）。成功時清 consecutive_failures 並寫 last_run。`_save_state` 擴充參數承接 last_attempt/failures。
- [ ] Step 3 綠。Commit `fix(scheduler): report run failure retries within the period with bounded backoff instead of skipping`

### Task 3: rule BUG-1 — 過期 one_time disable 失敗保留排程重試

**Files:** `src/rule_scheduler.py`（`check` expire 分支 ~289-301、cleanup ~353-355）；Test `tests/test_rule_scheduler.py`。

- [ ] Step 1 失敗測試：one_time 到期、`toggle_and_provision` 回 False → 排程**不**被刪除（下 tick 重試）、last_result=error；回 True → 刪除。
- [ ] Step 2 實作：`expired_hrefs.append(href)` 移到 `if expire_ok:` 內；失敗分支不 append（記 error＋continue，排程留存下 tick 重試）。
- [ ] Step 3 綠。Commit `fix(rule-scheduler): keep expired one-time schedule when PCE disable fails so it retries`

### Task 4: BUG-2 — 報表排程 CRUD 輸入驗證

**Files:** `src/gui/routes/reports.py`（`api_create_report_schedule` ~1003、`api_update_report_schedule` ~1019 加驗證 helper）、i18n（錯誤鍵）；Test `tests/` 報表排程路由測試。

- [ ] Step 1 失敗測試：cron_expr 畸形（"not a cron"）→ 400；hour=25 → 400；minute=99 → 400；day_of_month=32 → 400；schedule_type="hourly" → 400；合法值 → 200。
- [ ] Step 2 實作 `_validate_report_schedule(d, lang)` helper（create/update 共用）：
  - schedule_type ∈ {daily, weekly, monthly}（有 cron_expr 時 type 可省）
  - cron_expr 存在 → 用 `CronTrigger.from_crontab` 試解析，失敗 400（i18n `gui_err_invalid_cron`）
  - hour ∈ 0..23、minute ∈ 0..59、day_of_month ∈ 1..31（i18n `gui_err_invalid_schedule_time`）
  - 任一違反 raise ValueError → 端點轉 400。
- [ ] Step 3 綠＋i18n audit。Commit `fix(gui): validate report schedule cron/hour/minute/day-of-month/type`

### Task 5: BUG-3 — rule 排程 create type 前置驗證

**Files:** `src/gui/routes/rule_scheduler.py`（`rs_schedule_create` ~297）；Test `tests/test_rule_scheduler.py` 路由測試。

- [ ] Step 1 失敗測試：type 省略 → 400；type="weird" → 400；type="recurring" 缺 start → 既有 400（不回歸）。
- [ ] Step 2 實作：assembly 前加 `rtype = data.get('type'); if rtype not in ('recurring','one_time'): return _err(t("gui_err_invalid_schedule_type", lang=lang), 400)`；後續 `data.get('type', 'recurring')` 改用已驗證的 rtype。
- [ ] Step 3 綠。Commit `fix(gui): reject rule schedule with missing/unknown type instead of storing a broken entry`

### Task 6: M4 — retention 共池以排程 id 區隔

**Files:** `src/report_scheduler.py`（`_prune_by_count` ~652、呼叫點 ~296）；Test 同 report scheduler。

- [ ] Step 1 讀 `_prune_by_count` 與檔名/metadata sidecar 結構，判定最小改法：prune 只清「本排程產出的檔案」。若檔名不含排程識別，改為在 metadata sidecar 記 `schedule_id`，prune 依 report unit 的 sidecar schedule_id 過濾（只數/刪同 schedule_id 的）；若 sidecar 無此欄位（歷史檔），退回原 report_type 池行為並記一次 log（不破壞既有）。
- [ ] Step 2 失敗測試：兩個同 report_type、同 output_dir、不同 schedule_id 的排程各產 N 檔，一個 prune 到 max_reports 不影響另一個。
- [ ] Step 3 綠。Commit `fix(scheduler): report retention prunes per-schedule, not the shared report-type pool`

### Task 7: M5 — monthly 月底日夾取

**Files:** `src/report_scheduler.py`（`should_run` monthly 分支 ~210-212）；Test 同上。

- [ ] Step 1 失敗測試：day_of_month=31、now=2 月 28 日（該月最後一天）→ day_matches True（夾到月底）；day=31、now=2 月 27 → False；day=15、now=2 月 28 → False（不誤觸）。
- [ ] Step 2 實作：用 `calendar.monthrange(now.year, now.month)[1]` 取當月天數，`effective_dom = min(dom, last_day)`，`day_matches = now_naive.day == effective_dom`。dom 也於 BUG-2/BUG-3 validation 夾在 1..31。
- [ ] Step 3 綠。Commit `fix(scheduler): monthly schedule clamps day-of-month to last day of short months`

### Task 8: L6 — tick 缺 id 容錯

**Files:** `src/report_scheduler.py`（`tick` ~764-766）。

- [ ] `self._save_state(sched["id"], ...)` 兩處改用 `sid`（已在 :757 算好 `sid = str(sched.get("id",""))`）；缺 id 的排程不中止本輪其餘。既有測試不回歸即可（此為防禦性小修，加一個「缺 id 排程不中止 tick」測試）。
- [ ] Commit `fix(scheduler): tolerate schedule missing id in tick save-state path`

### Task 9: 收尾

- [ ] CHANGELOG（Fixed：C1/H×2/BUG2/3/M4/M5 標行為變更，特別註記 cron 首跑修復）；`docs/guide/automation.md`（排程說明）補「cron 首跑、失敗重試 backoff、monthly 月底夾取」語意（先 grep 確認該檔涵蓋排程）。
- [ ] 全套 pytest＋四硬閘。
- [ ] merge main → CI → 部署測試機。
- [ ] 真機驗證：(1) 建一個 cron 排程（如 `*/2 * * * *` 每 2 分）不點 Run Now，等一輪 tick → journal 出現 Triggering（C1 修復——修前永不觸發）；(2) 建 monthly day=31 排程，journal/state 反映月底夾取邏輯（或單測覆蓋足夠即可）；(3) GUI 送畸形 cron → 400；(4) 清掉測試排程。
- [ ] 記憶更新（scheduler-review-findings 標記全修）＋worktree 清理。
