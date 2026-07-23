# Alert Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 2026-07-24 alert 審查全部發現（High A1；Medium A2/A3/B1/B2/B3/D1；Low A4/A5/B4/B5/C1/D3）並落實兩處文案精緻化（sec_policy.create 推送範圍、NEN tips 非官方註記）。發現明細見 memory `alert-review-findings-2026-07-24`。

**Architecture:** A1 以「cache 路徑改全視窗查詢」對齊 legacy 語意（`CacheSubscriber.fetch_window_rows` 用 `last_detected` 索引，不動 cursor）；B 系列重塑 DLQ 語意（skipped 不耗額度不遺失、LINE 冷卻改 skipped、attempts 合併取 min、bucket 上限防無界）；A2/A4 收斂 rule engine 邊角；A3 視窗上限驗證＋prune 動態化；D1 poller overlap 預設 300s 可調；B3/C1/D3/A5 以文件與註解明文化設計取捨。

**Tech Stack:** Python（SQLAlchemy、pytest）、i18n 雙 JSON、docs。

## Global Constraints

- Commit 英文 conventional commits、無 emoji；i18n en/zh 同步；測試只用 tmp_path；四 CI 硬閘綠；全套 pytest 親跑；pipe 不判斷成敗；worktree（EnterWorktree `alert-remediation`）。
- 行為變更一律記 CHANGELOG；docs/guide/monitoring-alerts.md 同步（該檔 verified_against 含本批改動檔案時更新 last_verified）。

---

### Task 1: A1 — cache 路徑流量規則改全視窗查詢

**Files:** `src/pce_cache/subscriber.py`（新 `fetch_window_rows`）、`src/analyzer.py` `_fetch_traffic`（cache 分支）；Test `tests/test_pce_cache_subscriber.py`＋`tests/test_analyzer_on_cache.py`。

- [ ] subscriber 加（時間欄位 per-model：traffic→`last_detected`、events→`timestamp`）：
```python
_TIME_COL = {"pce_traffic_flows_raw": "last_detected", "pce_events": "timestamp"}

def fetch_window_rows(self, since: datetime, limit: int = 10000) -> list[dict]:
    """全視窗查詢（不動 cursor）：規則引擎的 threshold_window 加總需要
    「視窗內全部 flow」，cursor 增量會把視窗退化成單次輪詢間隔
    （2026-07-24 審查 A1）。"""
    col = getattr(self._model, _TIME_COL[self._source])
    with self._sf() as s:
        rows = s.execute(
            select(self._model).where(col >= since)
            .order_by(col.asc()).limit(limit)
        ).scalars().all()
    return [_row_to_dict(r) for r in rows]
```
- [ ] analyzer `_fetch_traffic` cache 分支：比照 legacy 算 `max_win = max(threshold_window)`，`since = now_utc - timedelta(minutes=max_win + 2)`，改呼叫 `fetch_window_rows(since, limit=10000)`；log 訊息改 "cache window ({} rows)"。
- [ ] 測試（TDD）：subscriber 兩測（視窗過濾正確、不推 cursor——fetch 後 poll_new_rows 仍回所有列）；analyzer 一測：模擬兩個 cycle 各插入 60 筆（視窗內），第二 cycle 規則 threshold=100 必須觸發（修前只看增量不觸發）。
- [ ] Commit `fix(analyzer): cache-path traffic rules evaluate the full threshold window`

### Task 2: A2＋A4 — rule engine 邊角收斂

**Files:** `src/analyzer.py`（`_run_event_analysis` ~989、`check_flow_match` ~385）；Test `tests/test_event_monitoring.py`（或既有事件規則測試檔）＋`tests/test_analyzer.py`。

- [ ] A2：count 型觸發加 `and matches` 條件——本 cycle 無新事件不再發空殼告警（time=N/A）；註解說明「告警要有新證據；視窗計數僅作門檻」。CHANGELOG 記行為變更。
- [ ] A4：`check_flow_match` 視窗過濾改 fail-closed——`start_time_limit` 存在而 flow 時戳缺失/不可解析 → return False（A1 改視窗 SQL 查詢後，cache 列必在窗內，此分支只影響 legacy/離群資料）；log debug 計數不需要。
- [ ] 測試：A2——視窗計數達標但本 cycle matches 空 → 不告警；有新事件 → 告警且 count=視窗值。A4——無 timestamp 的 flow 在帶視窗規則下不計入。
- [ ] Commit `fix(analyzer): no empty-shell count alerts; window filter fail-closed on missing timestamps`

### Task 3: A3 — threshold_window 上限與 history prune 動態化

**Files:** `src/analyzer.py` `save_state`（~261）、`src/config.py`（rule 驗證處，grep threshold_window）、`src/cli/menus/event.py:124` 一帶、`src/gui/routes/rules.py`（規則存檔驗證）；Test 對應檔。

- [ ] 上限常數 `MAX_THRESHOLD_WINDOW_MINUTES = 1440`（analyzer 模組層）；CLI/GUI/config 驗證超過即拒（i18n 錯誤鍵 `gui_err_window_too_large` en/zh：max 1440）。
- [ ] `save_state` history 裁剪改動態：`cutoff = now - timedelta(minutes=max(120, max_count_window + 10))`，其中 max_count_window = count 型事件規則的最大 threshold_window（無則 120）；上限自然被 1440 驗證約束。
- [ ] 測試：>1440 被拒（CLI/GUI 各一）；window=180 時 history 保留 3h+ 條目、計數正確。
- [ ] Commit `fix(analyzer): cap threshold_window at 24h and retain history to match`

### Task 4: B1＋B2＋B4 — DLQ 語意重塑

**Files:** `src/reporter.py`（send_alerts ~996-1018、`_push_alert_dlq`）、`src/alerts/plugins.py`（LINE 冷卻 ~127）；Test `tests/test_alert_dlq.py`。

- [ ] B2：LINE 冷卻中回 `{"status": "skipped", "error": "channel cooldown active"}`（暫時不可用≠失敗）。
- [ ] B1：重寫 push 判準——`not delivered and not force_test and 有任何 bucket 內容` 即回寫 DLQ；`attempted` 只決定 attempts 是否 +1（全 skipped 不消耗重試額度）：
```python
if not delivered and not force_test and any(buckets.values()):
    attempts = replayed_attempts + (1 if attempted else 0)
    if attempted and attempts >= self.ALERT_DLQ_MAX_ATTEMPTS: ... dropped ...
    else: self._push_alert_dlq(buckets, attempts, first_failed_at)
```
- [ ] 防無界：`_push_alert_dlq` 對每 bucket 裁到最新 `ALERT_DLQ_BUCKET_CAP = 100` 筆（超出記 warning＋result 附 dropped_overflow 計數）。
- [ ] B4：多筆重播 attempts 合併 `max`→`min`（單一條目常態不變；多筆殘留時以最年輕者計，避免提早丟棄），註解說明。
- [ ] 測試：全 skipped → DLQ 保留且 attempts 不增；LINE 冷卻回 skipped；skipped+failed 混合 → attempts +1；bucket 超 100 裁切；兩筆 DLQ attempts 1/2 重播失敗 → 合併條目 attempts=2（min 1 +1）。
- [ ] Commit `fix(reporter): DLQ survives skipped-only cycles; LINE cooldown no longer burns retry budget`

### Task 5: B5＋D1 — mail 純文字解除 LINE 上限、poller overlap 可調

**Files:** `src/reporter.py`（`_build_line_message` 加 `cap` 參數、`_build_mail_plain` 傳 `cap=None`）、`src/events/poller.py`（`overlap_seconds` 預設 60→300）、`src/config.py`/config 消費點（`events.overlap_seconds` 可調，grep EventPoller 實例化處接線）；Test `tests/test_alerts_*`＋poller 測試檔。

- [ ] `_build_line_message(subj, *, lang=None, cap: int | None = _LINE_MESSAGE_CAP)`；cap None 不截斷；LINE 呼叫端不變、mail plain 傳 `cap=None`。
- [ ] poller：建構子預設 `overlap_seconds=300`；實例化處讀 `events.overlap_seconds`（預設 300、夾 [60, 900]）；docstring 註明「PCE 事件索引延遲保護；event_seen dedup 使加大 overlap 零重複告警成本」。
- [ ] 測試：mail plain 超 4500 不截；poller overlap 預設 300、config 覆寫生效。
- [ ] Commit `fix(alerts): mail plain part untruncated; event poll overlap 300s configurable`

### Task 6: A5＋C1＋D3＋B3 — 明文化與可視化

**Files:** `src/analyzer.py` `_check_cooldown`（warning log）、`src/events/throttle.py`（docstring）、`src/alerts/plugins.py`（LINE 冷卻註解）、`src/reporter.py`（DLQ all-or-nothing docstring）、`docs/guide/monitoring-alerts.md`（三段補充）、i18n（cooldown=0 語意 hint）。

- [ ] A5：`except ValueError:` 補 `logger.warning("corrupt alert_history timestamp for rule {} — cooldown bypassed once", rid)`；`cooldown_minutes=0` 行為在 GUI hint（找既有 cooldown hint 鍵補「0 = 停用冷卻」en/zh）與 docs 明文。
- [ ] B3/C1/D3：docstring＋monitoring-alerts.md 補三點：DLQ 為 all-or-nothing（部分通道失敗僅記 dispatch_history）、LINE 冷卻為程序內狀態（重啟歸零）、throttle 於決策時記帳（失敗遞送经 DLQ 重送不再過 throttle、額度已耗屬預期）。
- [ ] Commit `docs(alerts): document DLQ, cooldown-zero, LINE cooldown scope, throttle accounting semantics`

### Task 7: 文案精緻化

**Files:** `src/i18n_en.json`/`src/i18n_zh_TW.json`。

- [ ] `event_tips_sec_policy_create`：「推送至所有 VEN」→「為受影響的 workloads 重新計算 OS 層防火牆規則並通知其 VEN 取用」（en 同步）。
- [ ] `event_tips_nen_degraded`／`event_tips_nen_missed_heartbeats`：句尾加「（此事件型別未見於官方事件清單，語意為實測觀察推定。）」en：'(This event type is not in the official event list; the semantics are inferred from field observation.)'
- [ ] `python scripts/audit_i18n_usage.py` 0 findings。
- [ ] Commit `docs(i18n): precise sec_policy.create push scope; mark NEN tips as non-official`

### Task 8: 收尾

- [ ] CHANGELOG（Fixed＋行為變更註記：A2 不再無新事件重發、D1 overlap 300s、A3 視窗上限 1440）；monitoring-alerts.md 相關段同步（cache 路徑視窗語意、DLQ 語意）。
- [ ] 全套 pytest＋四硬閘；merge main → CI → 部署測試機。
- [ ] 真機驗證：journal 觀察 analyzer log 出現 "cache window (N rows)"（N 隨視窗成長，非 30s 增量）；發一次單通道 test-alert 確認派送鏈不受影響；`logs/state.json` 的 alert_dlq 結構正常。
- [ ] 記憶更新（alert-review-findings 標記全修）＋ops-reliability 記憶 LINE defer 行更正＋worktree 清理。
