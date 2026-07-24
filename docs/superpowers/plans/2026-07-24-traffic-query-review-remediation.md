# Traffic Query Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 2026-07-24 流量分析調閱審查全部發現（High: draft filter 打光 cache、hybrid gap 吞錯；Medium: 邊界雙算、cache_bypass 漏 native-only key、port/proto include fail-open、mins 未夾限；Low: df 排除反轉、mins 400、archive 空語意、checkbox escape）。發現明細見 memory `traffic-query-review-findings-2026-07-24`。

**Architecture:** 核心在 `analyzer.query_flows`/`_fetch_query_flows`（draft 併入 bypass、gap 失敗查 last_fetch_error、合併去重、bypass 補 key）、`traffic_query._flow_matches_filters`（scalar port/proto fail-closed）、`gui/routes/actions.py`（mins 夾限＋typed 400＋archive not-loaded 訊號）、`df_filter`（排除路徑非法 CIDR fail-closed）、前端 `quarantine.js`（checkbox escape、archive 訊號呈現）。

**Tech Stack:** Python（pytest）、vanilla JS、i18n 雙 JSON。

## Global Constraints

- Commit 英文 conventional commits、無 emoji；i18n en/zh 同步；測試只用 tmp_path；四 CI 硬閘綠；全套 pytest 親跑；驗證命令不接 pipe 判斷成敗；JS 禁行尾 CJK 註解；worktree（EnterWorktree `traffic-query-remediation`）。
- 行為變更記 CHANGELOG。

---

### Task 1: H1 — draft filter 併入 cache bypass

**Files:** `src/analyzer.py`（`query_flows` ~1553 cache_bypass_keys 組裝）；Test `tests/test_analyzer_on_cache.py` 或 `tests/test_api_pce_contract.py`。

- [ ] Step 1 失敗測試：cache reader cover_state=full、read_flows_raw 回一筆無 draft_policy_decision 欄的 flow；params 帶 `draft_policy_decision="deny"`；斷言走 API（execute_traffic_query_stream 被呼叫、last_query_source=="api"），不是回空。
- [ ] Step 2 實作：`needs_draft` 併入 bypass 判定——
```python
cache_bypass_keys = [k for k in _CACHE_UNEVALUABLE_FILTER_KEYS if query_filters.get(k)]
if needs_draft:
    # draft_policy_decision 只在 compute_draft async 查詢的 flow 上存在；
    # cache 從不算 draft，client 端無從評估——強制走 API（2026-07-24 審查 H1）
    cache_bypass_keys = cache_bypass_keys + ["draft_policy_decision"]
```
- [ ] Step 3 綠。Commit `fix(analyzer): draft-policy filter bypasses cache (client cannot evaluate draft PD)`

### Task 2: H2 — hybrid gap 失敗查 last_fetch_error

**Files:** `src/analyzer.py`（`_fetch_query_flows` hybrid 分支 ~1401）；Test 同上。

- [ ] Step 1 失敗測試：cover_state=partial、gap 的 execute_traffic_query_stream 回空 generator 且設 `api.last_fetch_error="submit failed: 406"`；斷言 `_fetch_query_flows` 回的 source 不是 "cache"（應退 full API 或讓上層 raise）。
- [ ] Step 2 實作：gap_list 取得後檢查 last_fetch_error——非空視同 gap 失敗，退整條 full API（fall through）：
```python
gap_list = list(gap_stream) if gap_stream is not None else []
if getattr(self.api, "last_fetch_error", None):
    # gap API 靜默失敗（yield 0 + last_fetch_error）——不可標成 cache 成功
    # 吞掉歷史段遺失（2026-07-24 審查 H2）；退 full API 讓契約檢查生效
    logger.warning("query_flows hybrid: gap fetch reported error; falling back to full API")
    gap_list = None
```
（gap_list=None 已有的 fall-through 會走底部 full API path，其 source="api" → `_raise_if_query_fetch_failed` 生效。）
- [ ] Step 3 綠。Commit `fix(analyzer): hybrid gap fetch failure falls back to full API instead of masking as cache`

### Task 3: M3 — hybrid 合併去重

**Files:** `src/analyzer.py`（`_fetch_query_flows` `gap_list + cached` ~1419）；Test 同上。

- [ ] Step 1 失敗測試：gap 與 cache 各回同一筆 flow（同 flow identity——用相同 src.ip/dst.ip/service/first_detected/last_detected），斷言合併結果只含一筆。
- [ ] Step 2 實作：合併時按 flow 身分去重（helper `_flow_identity(f)`：`(src.ip, dst.ip, service.port, service.proto, first_detected, last_detected)` tuple）。cache 端優先（較完整）：
```python
def _merge_dedup(gap, cached):
    seen = {_flow_identity(f) for f in cached}
    return cached + [f for f in gap if _flow_identity(f) not in seen]
```
- [ ] Step 3 綠。Commit `fix(analyzer): dedup hybrid gap+cache flows by identity to avoid boundary double-count`

### Task 4: M4 — cache_bypass 補 native-only key

**Files:** `src/analyzer.py`（`_CACHE_UNEVALUABLE_FILTER_KEYS` ~84）；Test 同上。

- [ ] Step 1 失敗測試：params 帶 `src_ams=["x"]`、cover_state=full → 斷言走 API（bypass）。
- [ ] Step 2 實作：`_CACHE_UNEVALUABLE_FILTER_KEYS` 補 `src_include_groups`/`dst_include_groups`/`src_ams`/`dst_ams`/`ex_src_ams`/`ex_dst_ams`；docstring 補「actor groups/ams 為 native-only，client 兩套比對器不評估」。
- [ ] Step 3 綠。Commit `fix(analyzer): cache-bypass covers native-only actor-group/ams filter keys`

### Task 5: M5 — scalar port/proto include fail-closed

**Files:** `src/api/traffic_query.py`（`_flow_matches_filters` ~1037-1042、~1055-1060）；Test `tests/test_traffic_query_fallback_semantics.py` 或既有比對器測試。

- [ ] Step 1 失敗測試：filter `port="abc"`（不可解析），flow 任意 → 斷言 `_flow_matches_filters` 回 False（fail-closed，include 過濾不可靜默失效）。
- [ ] Step 2 實作：scalar `port`/`proto` 的 `except (ValueError, TypeError): pass` 改 `return False`（與 `ports` list 及 check_flow_match 一致）。
- [ ] Step 3 綠。Commit `fix(traffic-query): scalar port/proto include filter fails closed on unparseable value`

### Task 6: F1＋F2＋F3 — GUI 路由輸入處理

**Files:** `src/gui/routes/actions.py`（`api_quarantine_search` ~86-89）、i18n（archive not-loaded 訊號鍵）；Test `tests/test_actions_archive_source.py`＋新 quarantine_search 輸入測試。

- [ ] Step 1 失敗測試：`{"mins": 999999}` → start 距 end ≤ 10080 分鐘；`{"mins": "abc"}` → 400（非 500）；archive earliest None → 回應帶可辨識旗標（如 `not_loaded: True`）。
- [ ] Step 2 實作：
```python
try:
    mins = int(d.get("mins", 30))
except (TypeError, ValueError):
    return _err(t("gui_err_invalid_number", lang=lang), 400)
mins = max(5, min(mins, 10080))  # 同 debug/events 端點基線
```
archive 分支 earliest None：`return jsonify({"ok": True, "data": [], "not_loaded": True})`（保留 data=[] 相容）。
- [ ] Step 3 前端 `quarantine.js` renderQtPage：`not_loaded` 時顯示新 i18n 提示（`gui_archive_not_loaded`：「尚未載入封存資料，請先於資料來源匯入 review DB」），與「查無流量」區分。
- [ ] Step 4 綠＋node --check＋i18n audit。Commit `fix(gui): clamp traffic-query window, typed 400 on bad mins, distinguish archive-not-loaded`

### Task 7: F4＋L6 — checkbox escape、df 排除 fail-closed

**Files:** `src/static/js/quarantine.js`（:595 checkbox value）、`src/report/df_filter.py`（`_ip_mask` 排除套用點）；Test df_filter 既有測試擴充。

- [ ] F4：`value="${href}"` → `value="${escapeHtml(href)}"`（與姊妹渲染點一致）。node --check。
- [ ] L6：排除路徑非法 CIDR/range 不得清空整表——`_ip_mask` 加 `for_exclude` 參數（或套用點對非法值 fail-closed：非法排除條件視為「不排除任何列」，回全 False mask 而非全 True 反轉）。先讀 `_ip_mask` 與五個套用點（:182/199/208/277/294）判定最小改法：排除套用點改 `mask &= ~_ip_mask(..., default_empty=True)`，非法時 `_ip_mask` 回全 False（排除不到任何列）。測試：`ex_src_ip` 帶非法 CIDR → 結果非空（不清表）。
- [ ] Commit `fix(gui,report): escape workload checkbox href; malformed exclude CIDR no longer empties the table`

### Task 8: 收尾

- [ ] CHANGELOG（Fixed：H1/H2/M3/M4/M5/F1 等，標行為變更）；`docs/guide/troubleshooting.md` 或 reports/monitoring 若有相關段落補「draft 過濾走 API、hybrid 失敗語意」（先 grep 再決定）。
- [ ] 全套 pytest＋四硬閘＋全 JS node --check。
- [ ] merge main → CI → 部署測試機。
- [ ] 真機驗證（Playwright，流量與 Workloads 分頁）：(1) 選 draft PD 過濾查最近時段 → 有結果（非空），journal 出現走 API 的 log；(2) 一般查詢 escape 正常、console 零錯誤；(3) mins 超大送 curl → 窗被夾限；(4) archive 未載入 → 顯示「尚未載入封存資料」而非「查無流量」。
- [ ] 記憶更新（traffic-query-review-findings 標記全修）＋worktree 清理。
