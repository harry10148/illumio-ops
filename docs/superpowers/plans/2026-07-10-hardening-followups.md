# Hardening Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收斂 2026-07-10 四大案審查累積的 6 組 Defer 修復/優化（spec：`docs/superpowers/specs/2026-07-10-hardening-followups-design.md`）。

**Architecture:** 全部是既有機制的補強：訊號屬性（`last_fetch_error`）、co-owned-key merge、cooldown 語意、訊息長度防護。單分支 `fix/hardening-followups` 串行（共檔 analyzer.py/reporter.py/stats.py/traffic_query.py）。

**Tech Stack:** 既有（pytest、loguru、orjson、SQLAlchemy）。

## Global Constraints

- Commit message 英文 conventional-commits；一切輸出不用 emoji。
- datetime 一律 timezone-aware；測試只用 `tmp_path`。
- i18n 新鍵 en/zh 兩檔同步（zh 遵守 glossary：技術詞不中譯）；截斷必須明確可見（CLAUDE.md）。
- 本機無 `python`，一律 `python3 -m pytest ...`；每 task 後 `ruff check` 改動檔（無新增 violations）。
- 預設行為變更僅限 spec 明定項；其餘零行為變更。
- 各 task 的行號以檔案現況為準（本 plan 引用的行號來自 2026-07-10 各 review 報告，可能漂移——以符號/內容定位）。

---

### Task 1: traffic 鏈殘餘吞錯三分支（spec §A）

**Files:**
- Modify: `src/api/traffic_query.py`（`_submit_and_stream_async_query` 的 poll 逾時、`state=="failed"`、download 失敗三個裸 `return` 分支）
- Test: `tests/test_traffic_query_retry.py`（第三層 fix 已建，同檔擴充）

**Interfaces:**
- Consumes: `ApiClient.last_fetch_error` 屬性慣例（第三層 fix 建立：失敗設描述字串、`_submit_and_stream_async_query` 開頭清 None）。
- Produces: 三分支失敗時 `last_fetch_error` 皆非 None → ingestor 既有檢查（`_fetch_window`）自動生效，無需改 ingestor。

- [ ] **Step 1: 讀現場**——`src/api/traffic_query.py` 的 `_submit_and_stream_async_query`，定位三個失敗分支（poll 逾時：`_ASYNC_QUERY_MAX_WAIT_SECONDS` 超時後的 return；`state == "failed"`；download 非 200）。確認每分支目前只 log 後裸 `return`。

- [ ] **Step 2: 寫三個失敗測試（RED）**——同檔既有第三層測試樣式（mock `_api_get`/poll 回應序列），每分支一個：

```python
def test_poll_timeout_sets_last_fetch_error(...):
    # mock: submit 202 成功、poll 永遠回 running、時鐘超過 _ASYNC_QUERY_MAX_WAIT_SECONDS（monkeypatch 時鐘或把常數調小）
    flows = list(client._traffic._submit_and_stream_async_query(payload))
    assert flows == []
    assert client.last_fetch_error is not None and "timeout" in client.last_fetch_error.lower()

def test_query_state_failed_sets_last_fetch_error(...):
    # mock: poll 回 {"status": "failed"}（以現場欄位名為準）
    ...
    assert client.last_fetch_error is not None

def test_download_failure_sets_last_fetch_error(...):
    # mock: poll completed、download 回 (500, None)
    ...
    assert client.last_fetch_error is not None
```

（mock 細節照該檔既有測試 fixture；斷言核心是三分支後 `last_fetch_error` 非 None。）

Run: `python3 -m pytest tests/test_traffic_query_retry.py -q` → 新測試 FAIL。

- [ ] **Step 3: 實作**——三分支 return 前各加一行（描述含失敗類別與關鍵值，例：`c.last_fetch_error = f"async query poll timeout after {waited}s"`／`f"async query state failed: {state}"`／`f"async query download failed: HTTP {status}"`）。

- [ ] **Step 4: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_traffic_query_retry.py tests/test_watchdog_ingest_pipeline.py tests/ -q -k "traffic_query or ingestor" && ruff check src/api/traffic_query.py tests/test_traffic_query_retry.py`
Expected: 全 PASS

- [ ] **Step 5: Commit** — `fix(api): surface poll timeout, failed state and download errors to ingest signal`

---

### Task 2: `alert_dlq` 納入 co-owned key（spec §D）

**Files:**
- Modify: `src/analyzer.py`（`save_state` 的 `_merge`——C1/C2 修復建立的 co-owned-key 區塊）
- Test: `tests/test_watchdog_overflow_cache_cycle_merge.py`（同檔擴充）

**Interfaces:**
- Consumes: `_merge` 現有的「`traffic_overflow` 永遠信磁碟」處理。
- Produces: `alert_dlq` 同語意（analyzer 只讀不寫；reporter 經 `update_state_file` 是唯一寫者）。

- [ ] **Step 1: 寫 race 注入測試（RED on current code）**——照同檔既有樣式：Analyzer 建構（load_state 快照含 `alert_dlq=[entry]`）→ 模擬 reporter 在 cycle 中清空磁碟上的 `alert_dlq`（直接 `update_state_file` 寫 `[]`）→ `save_state()` → 斷言磁碟 `alert_dlq` 仍為 `[]`（不被快照復活）。

Run: `python3 -m pytest tests/test_watchdog_overflow_cache_cycle_merge.py -q` → 新測試 FAIL（現行 merge 會蓋回 `[entry]`）。

- [ ] **Step 2: 實作**——`_merge` 的永遠信磁碟清單加 `"alert_dlq"`（與 `traffic_overflow` 同處理；更新該區塊的 co-owned keys 註解）。

- [ ] **Step 3: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_watchdog_overflow_cache_cycle_merge.py tests/test_alert_dlq.py tests/ -q -k "watchdog or dlq" && ruff check src/analyzer.py`
Expected: 全 PASS（既有 DLQ 測試不受影響——reporter 流程在 save_state 之後，語意不變）

- [ ] **Step 4: Commit** — `fix(monitoring): protect alert_dlq from analyzer save_state overlay`

---

### Task 3: watchdog cooldown 恢復重置（spec §B）

**Files:**
- Modify: `src/events/stats.py`（`record_pce_success`）或 `src/analyzer.py`（`_check_watchdog`）——依 Step 1 現場判定
- Test: `tests/test_watchdog_alert.py`（同檔擴充）

**Interfaces:**
- Produces: `consecutive_failures` 由非零歸零（真 PCE 探針成功）時，`watchdog_last_alert_at` 一併清除；同一事故持續中（計數未歸零）cooldown 行為不變。

- [ ] **Step 1: 讀現場**——`record_pce_success`（stats.py）的簽章與其對 state dict 的存取範圍：若 stats 層能觸及頂層 state（`watchdog_last_alert_at` 是頂層鍵）→ 修在 stats（歸零時 `state.pop("watchdog_last_alert_at", None)`）；若只拿到 `pce_stats` 子 dict → 修在 `_check_watchdog` 開頭（`if failures == 0 and self.state.get("watchdog_last_alert_at"): self.state.pop(...)`，並確認 `_pce_stats_dirty` 語意不受影響——`watchdog_last_alert_at` 是 analyzer-owned 頂層鍵，merge 走 `self.state` 正常路徑）。把選擇寫進報告。

- [ ] **Step 2: 寫失敗測試（RED）**：

```python
def test_recovery_resets_watchdog_cooldown(...):
    # 事故一：3 連敗 → 告警、watchdog_last_alert_at 寫入
    # 恢復：record_pce_success（真探針）→ 計數歸零
    # 事故二（cooldown 60min 內）：再 3 連敗 → _check_watchdog 必須立即再告警（現行碼會被舊 timestamp 壓住 → RED）
```

Run: `python3 -m pytest tests/test_watchdog_alert.py -q` → FAIL。

- [ ] **Step 3: 實作 → GREEN＋迴歸**

Run: `python3 -m pytest tests/test_watchdog_alert.py tests/ -q -k "watchdog" && ruff check <改動檔>`
Expected: 全 PASS（既有「cooldown 壓制持續事故」測試不變綠）

- [ ] **Step 4: Commit** — `fix(monitoring): reset watchdog cooldown when pce recovers`

---

### Task 4: LINE 訊息總長防護（spec §C）

**Files:**
- Modify: `src/reporter.py`（`_build_line_message` 末端）、`src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_line_truncation_footer.py`（同檔擴充）

**Interfaces:**
- Consumes: `_build_telegram_message` 的 3500 cap 樣式（reporter.py:1243 一帶——先讀它，footer 附加與預留空間的寫法照抄結構）。
- Produces: LINE 訊息總長 ≤ 4500；超長時尾端為新 i18n 鍵 `line_message_truncated` 的 footer（en：`"[Message truncated - see mail or dashboard for full details]"`；zh：`「[訊息已截斷 - 完整內容見 mail 或 dashboard]」`——glossary 無衝突詞）。

- [ ] **Step 1: 寫失敗測試（RED）**：構造超長告警集（多筆長 detail）使組出訊息 > 4500 → 斷言回傳總長 ≤ 4500 且以 footer 結尾；另一測試：正常長度訊息逐位元不變（零行為變更釘）。

- [ ] **Step 2: 實作**——`_build_line_message` return 前：

```python
        _LINE_MESSAGE_CAP = 4500  # LINE push API 實際上限 ~5000，留 buffer（spec §C）
        if len(message) > _LINE_MESSAGE_CAP:
            footer = t("line_message_truncated", lang=self.lang)
            message = message[: _LINE_MESSAGE_CAP - len(footer) - 1].rstrip() + "\n" + footer
```

（常數抽 module 層；具體變數名照現場。）

- [ ] **Step 3: GREEN＋迴歸＋i18n**

Run: `python3 -m pytest tests/test_line_truncation_footer.py tests/ -q -k "i18n or line or reporter" && ruff check src/reporter.py`
Expected: 全 PASS

- [ ] **Step 4: Commit** — `feat(alerts): cap LINE digest length with explicit truncation footer`

---

### Task 5: iplist/workload 同 key native 分組語意覆核（spec §E）

**Files:**
- 查證輸出：報告（不入版控）＋裁決後二擇一：
  - 修：`src/api/traffic_query.py`（include_specs 迴圈對 iplist/workload 改每值一組，比照 ip 系列修法）＋`tests/test_traffic_query_ports_services.py` 或 `tests/test_analyzer_object_filters.py` 擴充
  - 釘：釘測試＋程式註解（語意依據引註）

**Interfaces:**
- Consumes: NotebookLM「Illumio」筆記本（`notebooklm ask ... --notebook 8c325126-bc83-4c86-8c6e-8759a242928e`）；必要時測試機真 PCE（比照 2026-07-03 spec §2.2 的實測法）。

- [ ] **Step 1: 查證**——問 API guide：async traffic query 的 sources.include 中同一 inner group 放兩個 `ip_list` actor 的語意；PCE Explorer UI 對 consumer 選多個 IP List 的組合語意（OR？）。記錄引文。若文件不明確 → 測試機實測 `[[A,B]]` vs `[[A],[B]]` 筆數。

- [ ] **Step 2: 裁決**（規則已定）——官方/實測為 OR → 走「修」分支：iplist/workload include 改每值一組（`ex_*` exclude 已扁平不動），TDD（先 RED 斷言 payload 分組形狀）＋df/fallback 殘餘比對三路一致性核對（`_iplist_hit`/`_workload_hit` 的 any() 已是 OR）。AND 有官方依據 → 走「釘」分支：釘測試（`[[a,b]]` 形狀）＋註解引依據。

- [ ] **Step 3: 迴歸**

Run: `python3 -m pytest tests/ -q -k "traffic or analyzer or object_filter" && ruff check <改動檔>`
Expected: 全 PASS

- [ ] **Step 4: Commit** — 修：`fix(api): OR-group same-side iplist/workload filters to match PCE semantics`；釘：`test: pin iplist/workload inner-AND grouping with vendor citation`

---

### Task 6: 品質雜項 sweep（spec §F，五小項一 commit 或分小 commit）

**Files:**
- Modify: `src/pce_cache/lag_monitor.py`（壓制起點 debug log 一條——第一次進入壓制時 `logger.debug` 記身份與起訖）
- Modify: `src/analyzer.py`（`_check_ip_filter`：值清單於 flow 迴圈外預解析一次——`query_flows` 層 hoist 或 lru_cache 擇一）
- Modify: `src/gui/routes/`＋`src/static/js/quarantine.js`（archive 回載：`_PROGRESS` 於下次 `start_archive_load` 開始時重置為新輪；前端輪詢加上限 720 次，超限顯示既有錯誤樣式訊息——i18n 鍵若需新增則雙語）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`alert_siem_backlog` 搬到字母序正確位置，兩檔同步）
- Modify: `src/static/css/app.css`（`.objfb-dot-service`/`.objfb-dot-port` 改硬編 hex，比照 `.objfb-dot-label` 慣例）
- Test: 對應各檔既有測試擴充（lag monitor debug log 斷言、ip filter 預解析行為不變釘、輪詢上限的靜態斷言、i18n parity）

**步驟**：每小項獨立 TDD-或-釘（行為不變項用行為釘測試），逐項跑對應聚焦測試；最後 `python3 -m pytest -q` 全套＋`node --check` 改動 JS。

- [ ] Step 1: lag monitor debug log＋測試
- [ ] Step 2: `_check_ip_filter` 預解析＋行為不變釘
- [ ] Step 3: `_PROGRESS` 重置＋輪詢上限＋測試
- [ ] Step 4: i18n 字母序搬移（parity 測試綠）
- [ ] Step 5: css var 改 hex（靜態斷言更新）
- [ ] Step 6: 全套迴歸 → Commit — `chore: quality sweep from 2026-07-10 review minors`

---

## 收尾

全部 task 完成後：whole-branch review（該分支 diff 不大，sonnet 即可）→ 合入 main → push → 部署測試機 → Task 1 的訊號補強可在測試機以「poll 逾時模擬」抽驗一項（非必要，unit 已覆蓋）。

## Self-Review 紀錄

- Spec 覆蓋：§A=Task 1、§B=Task 3、§C=Task 4、§D=Task 2、§E=Task 5、§F=Task 6；§3 非目標未混入。
- 順序：spec §5 的 A→D→B→C→E→F 對應 Task 1→2→3→4→5→6。
- 佔位掃描：Task 1/5 的 mock 細節與查證結果依現場（有明確判定規則與樣式引據），非 TBD。
- 型別一致：`last_fetch_error`（str|None）、cap 4500、720 次上限貫穿一致。
