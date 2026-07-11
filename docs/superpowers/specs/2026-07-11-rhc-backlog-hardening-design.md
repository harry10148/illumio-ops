# Rule Hit Count 驗證後 Defer Backlog 收斂 — 設計文件

日期：2026-07-11
狀態：彙整自真 PCE 驗證兩份報告（`.superpowers/sdd/rhc-verify-v1-report.md`、`rhc-verify-v2-report.md`）與 final review 裁決累積的 5 項 backlog，收斂成一輪執行。基準：main @d039bf1。

## 1. 目標與範圍

Rule Hit Count 報表已交付並完成真 PCE 驗證（v1 啟用態六項、v2 未啟用態七項）。驗證過程證實 1 個訊號斷鏈缺陷、標記 2 個低風險缺口，加上 final review 裁決的 2 個防禦/測試補強，共 5 項一次修完：

- A. enrichment 失敗訊號斷鏈（真環境證實，重要）
- B. 原生 CSV 3 個附加欄未涵蓋（無聲忽略）
- C. GUI CSV 上傳 mimetype 白名單缺口（RHC 與 policy_usage 路由）
- D. submit 回應缺 href 的防禦（空字串輪詢到 timeout）
- E. native 路徑整合測試補強（enablement 態、pull 失敗傳遞）

排除（非目標，見 §3）：v2 報告的日期 406 bug（已修——`src/api/reports.py` 的 `_to_iso_timestamp` 與 `tests/test_api_reports_pull.py::test_bare_dates_normalized_to_iso_timestamps` 已在 main）。

## 2. 項目與設計決策

### A. enrichment 失敗訊號斷鏈

**現況**（真 PCE 驗證 v1 項 6，FAIL）：

- `src/api_client.py:784-793` `get_all_rulesets()` 在非 200（實測 403；`_api_get` 慣例下 status 0 = 連線層失敗亦同）時回傳 `[]` 而非拋例外。
- `src/report/rule_hit_count_generator.py:232-243` `_enrich_rows()` 只在「例外」時回 True 設 `enrich_failed`；空 list 走正常路徑 → `build_rule_baseline([])` 成功 → 回 False。
- 結果：`enrich_failed=False`、HTML 無 `rpt_rhc_note_enrich_failed` 注記、來源/目的/Service/enabled 欄靜默全空。

**三案評估**：

| 案 | 內容 | 評估 |
|---|---|---|
| 屬性訊號 | 比照 `ApiClient.last_fetch_error` 慣例（`src/api_client.py:128`、`src/api/traffic_query.py:685` 一帶），失敗時設屬性、呼叫端事後檢查 | 該慣例是為「訊號要穿過 generator/streaming 邊界到 ingestor/watchdog」的非同步跨層鏈而生。此處消費者是直接同步呼叫端且已有 except 分支；共用 `last_fetch_error` 會與 events/traffic 鏈語意混流，另立新屬性（如 `last_rulesets_error`）則屬性擴散、有清理時機問題。過重。 |
| **新參數 `raise_on_error`（選定）** | `get_all_rulesets` 加 `raise_on_error: bool = False`，非 200 時 raise `RuntimeError`；預設 False 行為零變更 | 最小侵入：其他 5 個呼叫端全部不動（`src/gui/routes/rule_scheduler.py:104,141`、`src/rule_scheduler_cli.py:356`、`src/api_client.py:860`、`src/report/policy_diff_report.py:78`、`src/report/policy_usage_generator.py:137`）；只有 RHC generator 傳 True，失敗 raise → 落入 `_enrich_rows` **既有** `except Exception` → `enrich_failed=True` → HTML 注記鏈全通（exporter 端 `test_enrich_failed_note_shown` 已覆蓋）。訊號同步、就地、無殘留狀態。 |
| 回傳 None 區分空 | 失敗回 None、成功回 list | 破壞回傳型別 `list[dict]`；所有呼叫端都要防 None（rule_scheduler GUI 直接迭代會 TypeError），侵入面最大。否決。 |

**選定理由**：案二是唯一「訊號只送給要它的呼叫端、且不碰任何既有呼叫端」的做法，並直接復用 `_enrich_rows` 既有例外路徑——generator 側只改一行呼叫。

**細節**：

- raise 條件：`raise_on_error and status != 200`（含 status 0 連線層失敗——順帶補上 v1 報告附註「網路層連線失敗行為未驗證」的縫：DNS/refused 走 `_api_get` 的 except → `(0, None)` → 同樣 raise）。
- 200 且空 body/空 list：合法空 org，回 `[]`、不 raise、不設旗標（與現行「200 且 data 才進 cache」一致）。
- 例外訊息帶 HTTP status：`f"get_all_rulesets failed: HTTP {status}"`，由 `_enrich_rows` 的 `logger.warning("Rule detail enrichment skipped: {}", exc)` 原樣記錄。
- `src/interfaces.py:15` 的 `IApiClient` Protocol 不動：該 Protocol 記錄 Analyzer/RuleScheduler 使用子集，兩者不用新參數；optional kwarg 不破結構相容（`tests/test_analyzer_with_mock_api.py` 的結構替身不受影響）。

### B. 原生 CSV 3 個附加欄

**現況**（真 PCE 驗證 v1 項 3）：原生匯出 header 為

```
Rule Name,Rule HREF,Ruleset Name,Ruleset HREF,Rule Hit Count,Days Since Last Hit,Timestamp of Last Hit,Last Updated By,Timestamp Last Updated,Start Date,End Date
```

其中 `Timestamp of Last Hit`、`Last Updated By`、`Timestamp Last Updated` 未在 `_CSV_ALIASES`（`src/report/rule_hit_count_generator.py:43-56`），被無聲忽略——不進 row dict，HTML 與 CSV 匯出皆無。

**設計**：

1. **`Timestamp of Last Hit`（最後命中時間）**——原生數據、值班判讀價值高，納入解析與 HTML 欄位：
   - 別名：`'timestamp_of_last_hit': 'last_hit_at'`（canonical 短名，比照 `rule_hit_count → hit_count` 慣例）。
   - row dict 新增 `last_hit_at`；NaN/缺欄 → `''`（比照 `days_since_last_hit` 的 `'' if pd.isna(...) else str(...)` 處理）。
   - HTML：`_COLS` 尾端加 `last_hit_at`（緊接 `days_since_last_hit` 之後，對應原生欄序）；`_COL_I18N` 加 `"last_hit_at": "rpt_rhc_col_last_hit_at"`。
   - **截斷規則核對（CLAUDE.md 報表規則）**：先查現況——`days_since_last_hit` 不在 `_TRUNC_COLS`（`{"consumers","providers","services","description"}`），以 plain `<td>` 整值呈現；`_CELL_MAX=160` 截斷只作用於 `_TRUNC_COLS`。`last_hit_at` 是固定格式 ISO 時戳（約 20-24 字，遠低於 160），跟隨 `days_since_last_hit` 同慣例：整值呈現、不進截斷路徑、無無聲截斷風險。測試釘「HTML cell 含完整時戳值」。
   - i18n 新鍵 `rpt_rhc_col_last_hit_at`：en `"Timestamp of Last Hit"`（與原生欄名一致，比照 `rpt_rhc_col_days_since` 的 en 值 `"Days Since Last Hit"` 對齊原生命名）；zh 「最後命中時間」（glossary 無衝突詞）。
2. **`Last Updated By` / `Timestamp Last Updated`（治理欄位）**——查現有 CSV 匯出行為後，選 **CSV pass-through**：
   - 現況：`CsvExporter` 把 `hit_df/unused_df/cleanup_df/all_rules` 的**全部欄位**原樣 dump（`src/report/exporters/csv_exporter.py`），而 `rule_href`/`rule_id` 已有「進 row dict、CSV 有、HTML 無（`_COLS` 白名單過濾）」的先例——pass-through 是與現況一致的做法，優於「別名表列出但明示忽略」（後者仍把資料丟掉）。
   - 別名：`'last_updated_by': 'last_updated_by'`、`'timestamp_last_updated': 'last_updated_at'`；row dict 納入兩欄（NaN/缺欄 → `''`）；**不加進 HTML `_COLS`**（值班判讀價值低，完整值走 CSV recovery path），在 `_CSV_ALIASES` 該兩行加註解記錄此決策。
3. 相容性：舊版/精簡 CSV（無這 3 欄，如 PCE UI 手動匯出的舊格式或最小欄位測試檔）不得失敗，三欄值為 `''`；`_finalize` 的 KPI/排序/cleanup 邏輯不讀新欄，零影響。

### C. GUI CSV 上傳 mimetype 白名單

**現況**：traffic 路由已有前例——`src/gui/routes/reports.py:351-355`：

```python
if csv_file.mimetype not in {
    'text/csv', 'application/vnd.ms-excel',
    'text/plain', 'application/octet-stream',
}:
    return jsonify({"ok": False, "error": t("gui_err_invalid_file_type", lang=lang)}), 415
```

policy_usage（:727-734）與 RHC（:844-851）的 csv 分支只做 `secure_filename` 即存檔，無型別檢查。

**設計**：完全比照 traffic 前例——

- 白名單集合抽成模組層常數 `_ALLOWED_CSV_UPLOAD_MIMETYPES`（放 `_ALLOWED_REPORT_FORMATS` 附近），traffic 路由改引用常數（行為逐位元不變），policy_usage 與 RHC 兩路由加同一檢查：拒絕回 `("gui_err_invalid_file_type", lang)` ＋ HTTP 415。
- i18n：`gui_err_invalid_file_type` 已存在雙語（en `"Invalid file type"` / zh `"檔案類型無效"`），**無新鍵**。
- 「副檔名白名單」評估後不做：traffic 前例是 mimetype-only；且白名單已含 `application/octet-stream`（瀏覽器對 .csv 常送此型別），副檔名檢查增益有限，而單獨給兩條新路由加副檔名檢查會與 traffic 行為不一致。維持三路由一致優先；若日後要收緊，三路由一起收（另案）。

### D. submit 回應缺 href 防禦

**現況**：`src/api/reports.py:78` `href = body.get("href", "")`——2xx 但 body 無 href 時拿空字串進輪詢迴圈，`_api_get("")` 打出無意義請求直到 `timeout_seconds` 後拋 `RuleHitCountPullTimeout("")`（誤導性：呼叫端拿到空 `report_href`，且 GUI 會顯示「PCE 尚未完成準備」而實為協定異常）。

**設計**：submit 成功判定後立即防禦——

```python
href = body.get("href", "")
if not href:
    raise RuntimeError(f"rule hit count report submit returned no href: {str(body)[:200]}")
```

訊息帶 body 摘要（截 200 字，防超長 body 灌爆 log/toast）。傳遞面免費到位：CLI 與 GUI 的 `except Exception` 泛型處理已存在（GUI 走 `_err_with_log`），無需再改呼叫端。與 traffic 鏈同型缺陷的既有修法對齊（`src/api/traffic_query.py:696-699` 的「submit 回應無 href」處理）。一行修＋測試。

### E. native 路徑整合測試補強

**現況**：final review 裁決補入。既有覆蓋盤點——

- `tests/test_rule_hit_count_generator.py::TestGenerateFromNative`：enabled 成功、`disabled` 態 raise、temp CSV 清理、無 api_client raise。**缺**：`partial`/`unsupported` 態、pull 失敗在 generator 層的傳遞。
- `tests/test_api_reports_pull.py`：pull 自身的 submit 失敗/failed 態/timeout 已覆蓋（API 層）。
- `tests/test_gui_rule_hit_count_generate.py`：route 層 timeout/needs_enablement 已覆蓋（mock 掉 generator）。

**設計**（純測試，預期為 pin 測試——依現場碼推定會直接 GREEN；若有 RED 即代表發現真 bug，須回報再議，不得為湊綠改測試）：

1. `generate_from_native` 對 `state='partial'` 與 `'unsupported'` 各 raise `RuleHitCountNotEnabled`，且 `exc.status.state` 原樣攜帶（GUI route 靠它轉述給前端）、**不**呼叫 `pull_rule_hit_count_report`。
2. pull 失敗傳遞：`pull_rule_hit_count_report` 拋 `RuntimeError`（如 submit 406）→ `generate_from_native` 原樣上拋不包裝、不吞；拋 `RuleHitCountPullTimeout` → 原型別上拋且 `report_href` 屬性保留（GUI/CLI 的型別分流依賴它——`TimeoutError` 是 `OSError` 子類，包裝或改型別會破壞 route 層既有 except 順序）。

## 3. 非目標

- v2 報告發現的日期 406 bug 與泛型 500 訊息：已修入 main（`_to_iso_timestamp` ＋既有測試），不重做。
- `policy_usage_generator.py:137-139` 對 `get_all_rulesets` 空回傳只 warning 的同型潛在問題：Policy Usage 是流量近似報表、rulesets 是其主資料來源（空即報表無資料，有既有 warning 與 record_count=0 防護），語意與 RHC enrichment（配菜失敗須注記）不同，不在本輪擴散。
- 副檔名白名單、上傳檔案內容嗅探：見 §C 評估，另案。
- HTML 呈現 `last_updated_by`/`last_updated_at`、`last_hit_at` 的本地時區轉換或人性化格式：原生數據增強器定位，原樣呈現原生值。
- scheduler `record_count == 0` skip 分支的真環境驗證（v1 項 7 遺留）：需無命中資料環境，非程式改動。
- `IApiClient` Protocol 簽章擴充。

## 4. 執行順序與相依

A → B（同檔 `rule_hit_count_generator.py`＋同測試檔，串行）→ C → D → E（測試檔與 A/B 共檔，最後）。C、D 彼此獨立，但單分支串行即可（改動量小，開多分支不值得）。
