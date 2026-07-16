# API Layer Hardening (Phase B-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 Phase B-1 三視角深審在 api/ 層實錘的 7 組缺陷：集合 GET 500 筆截斷、async 下載失敗誤判 unused、inventory getter 錯誤傳播缺失、GUI ApiClient 連線洩漏、POST 非冪等重試、PCE 契約小缺口、label cache 並發空窗。

**Architecture:** 全部修在既有模組內（src/api_client.py、src/api/async_jobs.py、src/api/traffic_query.py、src/api/labels.py、src/gui/routes/*.py、src/report/*_report.py），不新增模組。每任務獨立可測、獨立 commit。

**Tech Stack:** Python 3.10+、requests/urllib3、pytest（unit 測試全部 mock `_request`/`_api_get`，不打真 PCE）。

## Global Constraints

- 一律繁體中文註解；Python 行內註解允許，JS/HTML 僅允許整行註解（本計畫不碰 JS）。
- 不用 emoji（程式碼、commit、測試名稱皆同）。
- Commit 為英文 conventional commits，結尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 時間戳一律 UTC ISO-Z：`%Y-%m-%dT%H:%M:%SZ`。
- 修類不修點：任務內指名的同機制站點必須全部處理，不可只修被點名的第一個。
- 每任務結束跑該任務指定測試檔 + `venv/bin/python -m pytest tests/ -q --tb=short -x -k "api or label or traffic or async or policy_diff or policy_resolver"` 級別的相關子集；最終由 controller 跑全套。
- vendor 事實（NotebookLM 已驗證，不要重查）：PCE 同步集合 GET 硬上限 500 筆並回 `X-Total-Count` header；`/labels`、`/workloads`、`/sec_policy/draft/{ip_lists,label_groups,services,rule_sets}` 皆在官方「Async GET Supported APIs」表內；traffic query 的 policy_decision 值域為 `{allowed, potentially_blocked, blocked, unknown}`；async traffic query 終態除 completed/failed 外還有 cancel 類狀態。

---

### Task 1: 集合 GET header 感知 + 截斷偵測

**Files:**
- Modify: `src/api_client.py`（`_request` 附近新增 `_api_get_with_headers`；改 `get_all_labels`、`get_all_rulesets`、`get_active_rulesets`、`get_ip_lists`、`get_label_groups`、`get_services`、`fetch_managed_workloads`）
- Modify: `src/api/labels.py`（`update_label_cache` 內 4 個 `_api_get(...max_results=10000)`）
- Test: `tests/test_api_collection_truncation.py`（新建）

**Interfaces:**
- Produces: `ApiClient._get_collection(path: str, *, timeout: int = 15) -> tuple[int, Any, int | None]`，回傳 `(status, data, total_count)`；`total_count` 取自 `X-Total-Count` header（無此 header 時 None）。
- Produces: `ApiClient.last_truncated_collections: list[str]`（每次 `_get_collection` 偵測到截斷時 append path；Task 2 會消費此語意改為 async fallback）。

**規格：**
1. 新增 `_api_get_with_headers(path)`：與既有 `_api_get` 相同流程，但回 `(status, data, headers_dict)`。實作方式：`_request` 已回 `(status_code, content)`，不要改 `_request` 簽名（呼叫點太多）；改為新增私有方法直接用 `self._session`（比照 `_request` 的錯誤處理：連線例外回 `(0, err_bytes, {})`）。
2. 新增 `_get_collection(path)`：內部呼叫 `_api_get_with_headers`，`max_results` 一律用 500（PCE 硬上限，帶 10000 沒有意義且掩蓋截斷）；path 由呼叫者帶好 query string 以外的部分，`_get_collection` 負責附加 `max_results=500`（path 已含 `?` 時用 `&`）。
3. 截斷偵測：`total_count is not None and total_count > len(data)` 時 `logger.error("collection GET truncated: {} returned {}/{} objects", path, len(data), total_count)` 並記到 `self.last_truncated_collections`。
4. 上列 7 個 getter 與 `update_label_cache` 的 4 個站點全部改走 `_get_collection`。getter 既有回傳型別、快取行為（如 `get_all_rulesets` 的 force_refresh/raise_on_error）不變。
5. 測試（mock `_session.request` 或 `_api_get_with_headers`）：
   - `test_get_collection_reads_total_count`：headers 帶 `X-Total-Count: 3`、body 3 筆 → total=3、無截斷記錄。
   - `test_get_collection_detects_truncation`：headers 帶 `X-Total-Count: 700`、body 500 筆 → `last_truncated_collections` 含該 path。
   - `test_get_collection_no_header`：無 header → total None、不誤報截斷。
   - `test_getters_route_through_get_collection`：以 monkeypatch 驗證 `get_ip_lists`/`get_services`/`get_label_groups`/`get_active_rulesets`/`get_all_labels`/`fetch_managed_workloads` 皆呼叫 `_get_collection`（修類不修點的守門）。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `fix(api): header-aware collection GET with 500-cap truncation detection`

### Task 2: 截斷時 async GET fallback

**Files:**
- Modify: `src/api_client.py`（`_get_collection` 增加 fallback 分支；新增 `_async_collection_get(path, total_count)`）
- Test: `tests/test_api_collection_truncation.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_get_collection` 與 `_api_get_with_headers`。
- Produces: `_get_collection` 在截斷時自動改走 async GET 取回完整集合；失敗則保留截斷資料 + 既有 error log（永不比 Task 1 行為差）。

**規格（官方 async GET 流程）：**
1. `_async_collection_get(path)`：對同一 URL 發 GET，headers 帶 `Prefer: respond-async`。預期 202 且回應 headers 含 `Location`（job href，如 `/orgs/1/jobs/xxx`）與 `Retry-After`。
2. 輪詢 `GET /api/v2{location}`（複用 `_api_get_with_headers`），直到 body `status == "done"`（Jobs API 用 done，不是 completed——本專案既有 vendor 事實）；`failed` 或超時（上限 300s，輪詢間隔從 `Retry-After` 或 2s 起、上限 10s）回 None。
3. done 後從 body `result.href` 取 datafile href，`GET /api/v2{result_href}` 下載完整 JSON 陣列，回傳 list。
4. `_get_collection` 截斷分支：呼叫 `_async_collection_get`；成功（list 且 `len >= total_count` 的 9 成，容忍輪詢期間物件增減）→ 回完整資料並 `logger.info`；失敗 → 維持 Task 1 的截斷資料與 error log。
5. 測試（mock `_api_get_with_headers` 依序回 202+Location → polling running → done+result.href → datafile body）：
   - `test_async_fallback_returns_full_collection`：截斷觸發 fallback，最終回 700 筆。
   - `test_async_fallback_failure_keeps_truncated_data`：輪詢回 failed → 回 500 筆截斷資料、error log 仍在。
   - `test_no_fallback_when_not_truncated`：未截斷不發 Prefer 請求。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `feat(api): async GET fallback for truncated collections`

### Task 3: async 下載失敗誠實化（rule hit count 誤判 unused）

**Files:**
- Modify: `src/api/async_jobs.py`（`iter_async_query_results`、`summarize_async_query`）
- Modify: `src/api/traffic_query.py`（`batch_get_rule_traffic_counts` 的下載迴圈，約 :1626-1652）
- Modify: `src/exceptions.py`（新增 `AsyncDownloadError(APIError)`）
- Test: `tests/test_async_download_failure.py`（新建）

**規格：**
1. `iter_async_query_results`：下載非 200 時，保留現有 `_save_async_job_state(job_href, download_status=f"failed:{dl_status}")`，但改 `raise AsyncDownloadError(f"download {job_href} failed: HTTP {dl_status}")`，不再靜默回空 generator。`logger.debug` 升為 `logger.error`。
2. `summarize_async_query`：不捕捉 `AsyncDownloadError`（往上拋）；只有真正迭代完成才寫 `download_status="completed"`（現況 bug：失敗時也覆寫 completed + flow_count=0，把失敗痕跡清掉）。
3. `batch_get_rule_traffic_counts` 的 `_download`：包 `try/except AsyncDownloadError`，失敗的 rule 走既有 `failed_rule_details.append(self._rule_usage_detail(rule, status="failed", ...))` 路徑（與 poll-failed 同型），**不得**進入 count=0 → unused 分支。
4. 掃 `iter_async_query_results` 與 `summarize_async_query` 的其他呼叫者（`grep -rn "iter_async_query_results\|summarize_async_query" src/`），逐一確認新例外有被處理或合理往上傳（修類不修點）。
5. 測試：
   - `test_iter_raises_on_download_failure`：mock `_request` 回 (500, b"") → raises AsyncDownloadError，job state 寫入 `failed:500` 且**不**被覆寫成 completed。
   - `test_summarize_success_marks_completed`：正常 2 flows → count=2、download_status="completed"。
   - `test_batch_counts_routes_download_failure_to_failed_details`：mock summarize 對某 rule 拋 AsyncDownloadError → 該 rule 出現在 failed_rule_details、不在 unused/hit 名單。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `fix(api): raise on async result download failure instead of reporting zero flows`

### Task 4: inventory getter 錯誤傳播 + 消費端修復

**Files:**
- Modify: `src/api_client.py`（`get_active_rulesets`、`get_ip_lists`、`get_label_groups`、`get_services`、`get_all_labels` 加 `raise_on_error: bool = False`，語意完全比照 `get_all_rulesets` :784-804：非 200（含 status 0 連線層失敗）raise `APIError`）
- Modify: `src/report/policy_diff_report.py`（:78-84 一帶的 inventory 抓取改 `raise_on_error=True`）
- Modify: `src/report/policy_resolver_report.py`（:130-134 同上）
- Modify: `src/api/labels.py`（`expand_object_filters_for_df` 的 `_iplist_cidrs`：改 `c.get_ip_lists(raise_on_error=True)`；名稱找不到（fetch 成功但無匹配）維持回 `[]` 但加 `logger.warning`）
- Test: `tests/test_api_raise_on_error.py`（新建）

**規格：**
1. 五個 getter 的預設行為不變（回空 list），只有 `raise_on_error=True` 時 raise——避免波及其他既有呼叫者。
2. policy_diff / policy_resolver 兩個報表生成器：PCE 故障時必須 raise 讓報表失敗（呈現錯誤），不得產出「規則全被移除」的誤導 diff。確認兩檔案內**全部** inventory 抓取站點（rulesets、ip_lists、label_groups、services、labels）都帶 `raise_on_error=True`。
3. 測試：
   - `test_get_ip_lists_raises_on_error`：mock 回 (503, ...) → `raise_on_error=True` 時 APIError、預設時回 []（五個 getter 參數化跑一輪）。
   - `test_policy_diff_fails_loud_on_pce_error`：mock get_ip_lists 拋 APIError → 生成器往上拋（不產出報表）。
   - `test_iplist_cidrs_fetch_failure_raises`：`expand_object_filters_for_df` 帶 iplist 過濾 + mock fetch 失敗 → raise；名稱不匹配 → 回空 + warning log。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `fix(api): raise_on_error for inventory getters; loud failure in policy diff/resolver and df iplist expansion`

### Task 5: GUI 路由 ApiClient 生命週期清掃（23 站點）

**Files:**
- Modify: `src/gui/routes/reports.py`（9 處）、`src/gui/routes/actions.py`（10 處）、`src/gui/routes/dashboard.py`（1 處）、`src/gui/routes/filter_objects.py`（2 處）、`src/gui/routes/rule_scheduler.py`（1 處）
- Modify（如缺）: `src/api_client.py`（確認 `__enter__`/`__exit__` 存在；`close()` 已存在——若無 context manager 協定則補上：enter 回 self、exit 呼叫 close 回 False）
- Test: `tests/test_gui_apiclient_lifecycle.py`（新建）

**規格：**
1. 盤點指令：`grep -rn "ApiClient(" src/gui/routes/*.py`。同步請求路徑一律改 `with ApiClient(cm) as api:`。
2. **背景執行緒例外**：adhoc 報表類 handler 把 api 交給 thread 長跑的站點，不可用 with 包住 dispatch（會提前關閉）；改為 thread 函式內 `try/finally: api.close()`，並讓 ApiClient 的建構移進 thread 函式內（連建構都進 thread，避免主執行緒與 thread 交接期洩漏）。逐站點判斷並在 commit message 列出哪些站點屬此類。
3. `close()` 後再用的防護已存在（`_request` raise RuntimeError），不需要新增。
4. 測試：
   - `test_apiclient_context_manager`：`with ApiClient(...)` 離開後 `_session is None`。
   - `test_routes_no_bare_apiclient`：靜態掃描 `src/gui/routes/*.py` 原始碼——每個 `ApiClient(` 出現行必須是 `with ` 開頭、或該函式內存在對應 `finally:`+`.close()`（通用不變量守門，未來新增站點忘記關直接紅）。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `fix(gui): close ApiClient in all route handlers (connection pool leak)`

### Task 6: PCE 契約小修包

**Files:**
- Modify: `src/api_client.py`（Retry 設定 :152-158；`_request` 增加 POST 429 單次安全重試）
- Modify: `src/api/traffic_query.py`（poll cancel 狀態 :756 一帶；CSV export timeout :1756；policy_decisions 預設 :1206 與 :1727）
- Modify: `src/api/async_jobs.py`（`_wait_for_async_query` 的同型 poll 分支同步處理 cancel 狀態——修類不修點）
- Modify: `src/api/labels.py`（`update_label_cache` 寫入迴圈 `i['href']` → `i.get('href')` 加跳過防護，4 個集合寫入區全部）
- Test: `tests/test_api_pce_contract.py`（新建）

**規格：**
1. Retry：`allowed_methods=frozenset(["GET", "HEAD", "PUT", "DELETE"])`（移除 POST——read-timeout 自動重試會重複執行 provision/create）。補償：`_request` 內 POST 收到 429 時，讀 `Retry-After`（無則 2s）sleep 後單次重試一次（收到回應代表 PCE 未處理，安全）。行內註解說明取捨。
2. Poll cancel 狀態：`state in ("failed", "cancel_requested", "cancelled", "canceled")` 皆視為失敗終態（訊息帶實際 state），兩個 poll 迴圈（traffic_query.py 與 async_jobs.py）都要。
3. `export_traffic_query_csv`：`timeout=300` → `timeout=_ASYNC_QUERY_MAX_WAIT_SECONDS`。
4. policy_decisions 預設：兩站點改 `["blocked", "potentially_blocked", "allowed", "unknown"]`，行內註解註明 vendor 值域四值、unknown 涵蓋 idle/快照模式與 Flowlink 未管理流量；CHANGELOG 記「traffic 報表可能因納入 unknown 流量而數字上升」。
5. `update_label_cache`：`for i in d_labels:` 等 4 個迴圈，`href = i.get('href')`，falsy 就 `continue`（現況裸 `i['href']` KeyError 會觸發整包 rollback 且 silent=True 下無聲）。
6. 測試：
   - `test_retry_excludes_post`：讀 session adapter 的 max_retries.allowed_methods 斷言不含 POST。
   - `test_post_429_single_retry`：mock session 第一次回 429（帶 Retry-After: 0）第二次 200 → 最終 200 且只重試一次；GET 不走此路徑。
   - `test_poll_treats_cancelled_as_failure`：poll body status="cancelled" → 視為失敗、不等到 timeout。
   - `test_default_policy_decisions_include_unknown`：不帶 policy_decisions 呼叫 → payload 含 unknown。
   - `test_label_cache_skips_entry_without_href`：d_labels 混入無 href 條目 → 其餘正常寫入、不 rollback。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `fix(api): PCE contract gaps (POST retry idempotency, cancel states, unknown decision, csv timeout, href guard)`

### Task 7: label cache 並發：build-then-swap

**Files:**
- Modify: `src/api/labels.py`（`update_label_cache` :216-；`invalidate_labels` docstring 對齊實際範圍）
- Test: `tests/test_label_cache_swap.py`（新建）

**規格：**
1. `update_label_cache` 改 build-then-swap：fetch 階段把四個集合先組進**區域** dict（不動共享快取）；全部成功後在 `c._cache_lock` 內一次 swap（`cache.clear(); cache.update(new)` 或直接替換引用——採 clear+update 保留既有別名引用）。
2. 移除 fetch 前的 `invalidate_query_lookup_cache()` 呼叫（clear-before-fetch 空窗：期間讀者看到空快取；swap 模式天然不需要）。`force_refresh` 語意保留：force_refresh=False 且快取未過期時的既有 early-return 邏輯不變。
3. 失敗路徑：任一集合非 200 → 共享快取完全不動（不需要 rollback snapshot——連帶消除視角二的 rollback lost-update 競態），維持既有的 return False/log 行為。
4. `invalidate_labels` docstring 與實際清除範圍對齊（視角二 F5：docstring 宣稱的範圍與實作不符——以實作為準改文字）。
5. 測試：
   - `test_swap_only_after_all_fetches_succeed`：第三個集合回 503 → 原快取內容原封不動。
   - `test_no_invalidate_before_fetch`：monkeypatch `invalidate_query_lookup_cache` 斷言 fetch 期間未被呼叫。
   - `test_swap_preserves_dict_identity`：swap 後 `c.label_cache` 物件 id 不變（別名引用不失效）。

- [ ] 寫失敗測試 → 驗證紅 → 實作 → 驗證綠 → commit `fix(api): build-then-swap label cache refresh (no clear-before-fetch window, no rollback race)`

---

## 收尾

- controller 親跑全套 `venv/bin/python -m pytest tests/ -q --tb=short` + i18n/lint 守門。
- CHANGELOG.md 補條目（policy_decisions unknown 的數字影響必須寫明）。
- 最終全分支 review（最強模型）→ 修 → 合 main → push → `gh run watch` → 部署測試機 → 真機驗證（至少：dashboard 正常、跑一份 policy_diff 報表、觀察 logs 無 truncation error、`ss -tnp | grep python` 連線數不隨請求無限成長）。

## 記債不修（本輪明確排除，B-5/B-2 對應部位再收）

- TTLCache 無鎖讀（F3）、diagnostics 欄位無鎖（F6）、close TOCTOU（F9）：latent，單執行緒 GIL 下實害極低。
- RHC pull 輪詢把持續性 401 呈現為 pull_timeout（M5）：訊息品質問題，記入 B-4 report 部位。
- invalidate 窗口的 stampede（F2）：swap 化後影響大減，觀察後再議。
