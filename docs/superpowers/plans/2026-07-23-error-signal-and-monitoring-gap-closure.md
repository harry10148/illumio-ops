# Error-Signal and Monitoring Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收清 2026-07-23 建議清單的四個未結項：(A) 吞錯類掃描修復（1 C 級＋5 B 級＋ven summary 空集合假真相）、(B) `last_truncated_collections` 持久化＋接 Integrations 面板＋raise_on_error 截斷大聲失敗、(C) `/node_available` 官方健康檢查接入 pce_health 鏈、(D) filter key 七層鏈跨層一致性守門測試。

**Architecture:** A 是逐點手術修復（log＋訊號欄位，不改行為契約除 ven summary）；B 新增 `src/data_integrity.py` 小儲存（鏡射 job_health.py 模式，檔案 `logs/data_integrity.json`）＋`TruncatedCollectionError`；C 在 `ApiClient` 加 `check_node_available()`（免驗證端點，healthy={200,202}，真機 lab PCE 實測回 200）並在 `Analyzer._check_pce_health` 的 /health 通過分支後追加探測；D 是純測試檔（import Python 常數＋regex 切片抽 JS/函式體 key），以「FilterBar 可序列化的 key 必須在每層存活或有明文豁免」為不變量。

**Tech Stack:** Python 3.10+（pytest、AST/regex 靜態抽取）、既有 state_store 原子寫。

## Global Constraints

- Commit 英文 conventional commits、無 emoji；JS 禁行尾 CJK 註解；測試只用 tmp_path。
- 四 CI 硬閘不得紅；i18n 鍵 en/zh_TW 同 commit 同步。
- 全套 pytest 本人親跑；驗證命令不可接在 pipe 後判斷成敗（exit code 會被吃掉）。
- 工作於 worktree 分支（EnterWorktree `gap-closure`）。
- 刪改「區段」前逐 symbol 判定歸屬（前一批 quarantine.js 誤刪教訓）。

---

### Task A1: ransomware posture enrichment 失敗不得偽裝乾淨（C 級）

**Files:** Modify `src/report/ransomware_posture_enrichment.py:83,91`；Test 擴充該模組既有測試檔（先 `grep -rln ransomware_posture_enrichment tests/`）。

- [ ] Step 1: 讀 `refresh_ransomware_posture` 全文與下游消費者（cache dict 形狀、報告端讀哪些欄位），確認加 `enrichment_error` 欄位不破壞既有讀取。
- [ ] Step 2: 失敗測試——monkeypatch `api.get_workload` raise，斷言 (a) 該 workload 條目帶 `enrichment_error`（truthy，含例外摘要），(b) logger.warning 被呼叫（caplog），(c) `open_service_ports`/`details` 維持空清單（行為相容）。
- [ ] Step 3: 兩個 except 各改為：`logger.warning("ransomware enrichment failed for {}: {}", href, exc)`＋條目記 `entry["enrichment_error"] = str(exc)[:200]`；模組 docstring 同步改寫（不再宣稱 swallowed）。
- [ ] Step 4: 檢查報告渲染端：若 mod/exporter 有「乾淨/曝險」判定，enrichment_error 條目須排除在「乾淨」結論外（顯示為資料不可得）；只在有明確判定點時改，改動處加測試。
- [ ] Step 5: 跑該模組相關測試綠 → commit `fix(report): ransomware enrichment failures no longer masquerade as clean`

### Task A2: `_tls_overview` 例外不得回「健康」預設（B-1）

**Files:** Modify `src/gui/routes/dashboard.py:302-323`；Test `tests/test_gui_job_health_panel.py` 或 TLS 相關測試檔擴充。

- [ ] Step 1: 失敗測試——monkeypatch `_cert_days_remaining` raise，斷言回傳含 `check_failed: True` 且 logger.warning 有記。
- [ ] Step 2: except 分支改 `logger.warning("tls overview check failed: {}", exc)` 並回 `{"enabled": True, "days_remaining": None, "expiring_soon": False, "check_failed": True}`；正常分支補 `"check_failed": False`。前端 TLS 卡：`integrations.js` 找 TLS 卡 render 處，`check_failed` 時顯示 `gui_tls_check_failed`（新 i18n 鍵 en「TLS check failed」/zh「TLS 檢查失敗」）而非 days。
- [ ] Step 3: 測試綠＋`node --check` → commit `fix(gui): TLS overview surfaces check failures instead of defaulting healthy`

### Task A3: rule hit count CSV 解析失敗不得記 0 命中（B-2）

**Files:** Modify `src/report/rule_hit_count_generator.py:134-140` 一帶；Test 該檔既有測試擴充。

- [ ] Step 1: 讀 `generate_from_csv` 上下文：hits=0 的下游是否餵「未使用可停用」判定（enablement 報告）。
- [ ] Step 2: 失敗測試——CSV 帶一列 `hit_count` 為垃圾字串，斷言該列不進 0-hit 名單：計入 `result.unparsed_rows`（新欄位）且 logger.warning 記 rule 識別。
- [ ] Step 3: 實作：解析失敗 → `unparsed_rows += 1`＋warning＋該列跳過（不以 hits=0 收錄）；報告 meta 顯示 unparsed_rows>0 警示（有既有 meta/warnings 機制就掛上去，沒有就只記 log＋欄位）。
- [ ] Step 4: 測試綠 → commit `fix(report): unparsable hit_count rows no longer counted as zero hits`

### Task A4: snapshot/capacity/subscriber 靜默點補訊號（B-3/B-4/B-5）

**Files:** `src/report/snapshot_store.py:46,68`、`src/pce_cache/capacity.py:30`、`src/pce_cache/subscriber.py:89`；各自既有測試檔擴充。

- [ ] Step 1: snapshot_store：corrupt 檔 → `logger.warning("skipping corrupt snapshot {}: {}", f, exc)`（`:46` 與 `:68` 同改）；測試：壞 JSON 檔 caplog 斷言＋read_latest 仍回舊檔。
- [ ] Step 2: capacity：`except OSError: pass` 改為 `except FileNotFoundError: pass`（-wal/-shm 不存在是常態）＋`except OSError as exc: logger.warning(...)`；測試：monkeypatch getsize raise PermissionError → warning 記錄且 snapshot 仍回。
- [ ] Step 3: subscriber：JSONDecodeError → `logger.warning("corrupt cached payload row id={}", getattr(row, "id", "?"))`；測試沿該檔既有 harness。
- [ ] Step 4: 三檔測試綠 → commit `fix: surface corrupt-file and stat failures in snapshot store, capacity, cache subscriber`

### Task A5: ven summary 不得把 PCE 失敗當 0 workloads（B-6 核心）

**Files:** `src/api_client.py` `fetch_managed_workloads`（~751）加 `raise_on_error: bool = False`（非 200 raise APIError，鏡射 get_all_labels:648-664 樣式）；`src/scheduler/jobs.py` `run_ven_summary` 改用 `raise_on_error=True`（外層 except 已寫 last_error＋job_health error）。Test：`tests/` 中 run_ven_summary 既有測試擴充：api 回非 200 → summary 帶 `last_error` 而非 total=0。

- [ ] Step 1: 失敗測試 → Step 2: 實作 → Step 3: 綠 → commit `fix(scheduler): ven summary raises on PCE fetch failure instead of reporting 0/0`

### Task B1: data_integrity 儲存＋`_get_collection` 接線

**Files:** Create `src/data_integrity.py`（鏡射 `src/job_health.py`：`_data_integrity_file()`→`logs/data_integrity.json`、`load_data_integrity()`、`record_truncation(path, got, total)`（條目 `{path: {"last_seen": ts, "got": n, "total": m}}`）、`clear_truncation(path)`、全部 `_safe_update` 靜默）；Modify `src/api_client.py:895-902`（append 處呼叫 `record_truncation`、recovery 處呼叫 `clear_truncation`，import 放函式內、try/except 包裹——遙測失敗不得影響 API 路徑）；Test 新檔 `tests/test_data_integrity.py`（roundtrip、clear、record 失敗不炸）＋`tests/test_api_collection_truncation.py` 擴充（截斷→record、恢復→clear，monkeypatch `_data_integrity_file` 到 tmp_path）。

- [ ] Step 1-4: TDD 循環 → commit `feat(api): persist collection truncation events to logs/data_integrity.json`

### Task B2: raise_on_error 截斷大聲失敗

**Files:** `src/exceptions.py` 加 `class TruncatedCollectionError(APIError)`（docstring：集合 GET 截斷且 async fallback 失敗）；`src/api_client.py` 五個帶 `raise_on_error` 的集合 getter（648/1043/1064/1081/1103 一帶）在 `status==200` 後補：`if raise_on_error and path in self.last_truncated_collections: raise TruncatedCollectionError(path)`；CHANGELOG 記行為變更（原「靜默回截斷資料」已 CHANGELOG 記載為 gap）。Test：`test_api_collection_truncation.py` 擴充——截斷＋fallback 失敗＋raise_on_error=True → raise；raise_on_error=False → 仍回截斷資料。

- [ ] Step 1-4: TDD 循環 → commit `feat(api): raise TruncatedCollectionError for raise_on_error getters on unrecovered truncation`

### Task B3: 截斷面板（overview→integrations.js）

**Files:** `src/gui/routes/dashboard.py` `_overview_job_health` 同層新增 `_overview_data_integrity()`（load，過濾 last_seen 7 天內，回 `[{path, got, total, last_seen}]`）並掛進 overview payload `data_integrity`；`src/static/js/integrations.js` Job Health 表下方渲染「資料完整性」警示區（有條目才顯示：每列 path＋got/total＋last_seen，warn 色）；i18n 鍵 `gui_ov_data_integrity`（en「Data Integrity」/zh「資料完整性」）、`gui_ov_truncated_fmt`（en「{path}: fetched {got}/{total} (truncated)」/zh「{path}：僅取得 {got}/{total}（已截斷）」）。Test：route 測試（seed data_integrity.json → overview 回條目；過期條目不回）。

- [ ] Step 1-4: TDD＋node --check＋i18n audit → commit `feat(gui): surface truncated-collection telemetry on integrations overview`

### Task C1: `check_node_available`＋pce_health 鏈接入

**Files:** `src/api_client.py` 加：

```python
    def check_node_available(self) -> tuple[int, str]:
        """GET /api/v2/node_available（免驗證；官方 SLB 健康檢查端點）。

        healthy 判準：HTTP 200（on-prem SLB 文件）或 202（Supercluster 文件）；
        404/502/連線失敗為不健康。官方註明狀態反映最多延遲 30 秒。
        """
        url = f"{self.api_cfg['url']}/api/v2/node_available"
        try:
            status, body = self._request(url, timeout=10)
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            return status, text
        except Exception as e:
            logger.error(f"node_available check failed: {e}")
            return 0, str(e)
```

`src/analyzer.py` `_check_pce_health` 763 行 else（/health OK）分支內、`record_pce_success` 前追加：`na_status, na_msg = self.api.check_node_available()`；`na_status not in (200, 202)` → 走 degraded 同款告警路徑（rule loop＋`record_pce_error("health", f"node_available: HTTP {na_status}")`＋alert details 用新 i18n 鍵 `health_node_unavailable_details` en「node_available returned HTTP {status} - node may be out of service」/zh「node_available 回應 HTTP {status}，節點可能已不可服務」）；健康則照原路 `record_pce_success`。Test：`tests/` 找 `_check_pce_health` 既有測試（grep check_health），擴充三例：node_available 200/202 → success；404 → health alert＋record_pce_error；check_health 已失敗時不多打 node_available（維持原第一分支 early 行為）。

- [ ] Step 1-4: TDD 循環 → commit `feat(monitoring): probe official /node_available endpoint in PCE health check`

### Task D1: filter key 七層鏈守門測試

**Files:** Create `tests/test_filter_key_chain_invariants.py`。抽取器：Python 常數直接 import（`analyzer._OBJECT_FILTER_KEYS`/`_CACHE_UNEVALUABLE_FILTER_KEYS`、`rules._RULE_FB_KEYS`/`_RULE_REJECTED_KEYS`、`traffic_query._TRAFFIC_FILTER_CAPABILITIES`、`object_picker._ANY_FILTER_KEYS`）；函式體 key 用原始碼切片＋regex（`d.get("...")` on actions.py `api_quarantine_search` 區段、`params.get("...")` on analyzer `query_flows` 區段、`filters.get("...")` on traffic_query `_flow_matches_filters` 區段）；filter-bar.js serialize keys 用該檔 `_objfbSerialize` 區段 regex（`push`/直接 key 樣板——先讀 119-152 行定案 regex，動態組字串 key 用 cat/dir 枚舉展開表列）。

不變量（豁免集合逐一附註解引用出處）：
1. `FILTERBAR_SERIALIZE ⊆ ACTIONS_PARAMS`
2. `ACTIONS_PARAMS(filter 部分) ⊆ QUERY_FLOWS_WHITELIST ∪ KNOWN_ACTIONS_ONLY`（`search/sort_by/draft_policy_decision` 在兩邊；先跑一次抓實際差集——`port/proto/ex_port` 若真不在 whitelist，判定：capability matrix 標 native → 屬斷鏈 bug，**修 analyzer whitelist 補 3 key** 並在測試記載；若查明有前置正規化則列豁免）
3. `FILTERBAR_SERIALIZE ⊆ CAPABILITIES ∪ {"src_ip_in","dst_ip_in",...}`（capability 用單數 ip key 的差異先實查再定豁免）
4. `CAPABILITIES 中 execution=="fallback" 的 key ⊆ FLOW_MATCHES_KEYS`
5. `FILTERBAR_SERIALIZE ⊆ _RULE_FB_KEYS ∪ _RULE_REJECTED_KEYS`（label_groups 4 key 走 rejected，rules.py:22-24）
6. `_obj_filter_keys ⊆ _OBJECT_FILTER_KEYS`
7. `picker 產出 keys ⊆ _RULE_FB_KEYS`
8. `_CACHE_UNEVALUABLE_FILTER_KEYS == label_group 8 key`（rules._RULE_REJECTED_KEYS 同集合——兩處聯動）

- [ ] Step 1: 寫抽取器＋先以 print 跑出各集合，逐一人工核對差集，把真 bug（如 port/proto/ex_port）修掉或列豁免（豁免必須引用程式碼註解出處）。
- [ ] Step 2: 斷言落檔跑綠；故意在本地暫時移除一個 key 驗證測試會紅（不 commit 該驗證）。
- [ ] Step 3: commit `test(filter): cross-layer filter-key chain invariants`（含可能的 whitelist 補 key fix）

### Task E: 收尾

- [ ] CHANGELOG（Added: data_integrity 面板、node_available、TruncatedCollectionError；Fixed: A1-A5）；docs：`docs/guide/monitoring-alerts.md` 補 node_available 一段、`docs/handover/architecture.md` 若列 telemetry 則補 data_integrity（先 grep 再決定）。
- [ ] 全套 pytest＋四硬閘＋node --check 全 JS。
- [ ] merge main（non-ff）→ push → `gh run watch` 綠。
- [ ] 部署測試機：pull、restart、journal 乾淨。
- [ ] 真機驗證：(1) journal 出現 node_available 探測正常（或 log 無異常＋單測覆蓋不健康分支）；(2) 測試機 seed `logs/data_integrity.json` 假條目 → Integrations 面板顯示資料完整性警示 → 清掉恢復；(3) ven summary 照常 ok；(4) Playwright console 零錯誤。
- [ ] 記憶更新（observability-residuals-delivered 的未結清單收斂）＋worktree 清理。
