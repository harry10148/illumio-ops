# 歷次審查 Defer 殘項收斂 — 設計文件

日期：2026-07-11
狀態：彙整歷次審查 ledger 記 Defer 的 4 項殘項（test flake 排查、traffic stream 吞 406、any×label_group 序列化語意錯誤、IP List exclusion 展開），基於 main @570c52b 現場碼定案。

## 1. 目標與範圍

4 項全部是既有機制的收斂修復，無新功能：

- A. `tests/test_reports_async_generate.py` 順序 flake 排查與隔離
- B. traffic 互動查詢路徑吞 PCE 失敗（406 等）→ GUI 顯示 0 筆不可分辨
- C. FilterBar any 方向 label_group pill 被序列化成 `any_label`（語意靜默錯誤）
- D. IP List `exclusion:true` ranges 被 `_iplist_cidrs` 當 inclusion 展開（cache df 路徑 over-include）

排除：其他 ledger Defer 項（readiness backlog、plugger 借鑒等另案）。

## 2. 項目與設計決策

### A. test_reports_async_generate 順序 flake：真實檔依賴查證與隔離

**現況（已逐項查證）**：

該測試檔的依賴面盤點結果——

1. **真實 `logs/state.json`（唯一真實檔依賴，確認）**：`POST /api/reports/generate` 同步呼叫 `_save_adhoc_job`（`src/gui/routes/reports.py:81`）、worker 執行緒結束時再呼叫一次、`GET /api/reports/jobs/<id>` 走 `_load_adhoc_jobs`（:76）——三者都經 `_resolve_state_file()`（`src/gui/_helpers.py:316`）落在 **repo 真實 `logs/state.json`**。測試每跑一次就把假 job 寫進真實檔（污染），也讀它（依賴）。
2. **rate limiter**：非依賴。`tests/conftest.py:12` 已設 `ILLUMIO_OPS_RATELIMIT_URI=memory://`，`config/limiter/` 檔案 backend 在測試中不啟用。
3. **`_PROGRESS` 全域 dict**：非依賴。它在 `src/pce_cache/archive_import.py:345`，屬 archive 回載路徑，此測試不經過。
4. config／app：已用 `temp_config_file` fixture 隔離。

**flake 機制（同族於 79c51e3 修掉的 analyzer stub flake）**：共享 `logs/state.json` 下有兩條可炸路徑——

- **prune 剔除**：`_save_adhoc_job` 只保留 `started_at` 最新 20 筆（`_ADHOC_JOBS_MAX`）。真實檔殘留的 job（歷次測試污染累積、或時間戳異常的髒資料）足量且較新時，本測試剛建立的 job **在建立當下就被 prune 剔除** → poll 一路 404 → `s["status"]` 取值失敗。可注入式重現：塞 20 筆 `started_at` 為遠未來的假 job，測試必炸。
- **整檔改寫／鎖競爭**：全套中其他測試以 `src.analyzer.STATE_FILE`（同一個 `logs/state.json`）整檔 save_state，或搶 `state.json.lock`（`state_store._state_lock` timeout 10s）——job 記錄在 poll 期間消失或 `_save_adhoc_job` 丟 `TimeoutError`。這正是「全套單次失敗、單獨/重跑皆過」的 order/wall-clock 依賴形態。

**設計**：

1. 測試檔加 **autouse 隔離 fixture**：`monkeypatch.setattr("src.gui.routes.reports._resolve_state_file", lambda: str(tmp_path / "state.json"))`。`_resolve_state_file` 是 from-import 綁進 reports 模組 namespace、call-time 查 module global，patch 該綁定即可同時涵蓋端點與 worker 執行緒（同一 module global）。與 79c51e3 的修法同構（patch 模組層路徑常數/解析函式指向 tmp）。
2. 加**機制釘測試**：在隔離後的 tmp state 檔注入 20 筆未來 `started_at` 的 job → POST generate → 斷言 job 建立即被 prune、poll 404。把 flake 機制固化為可執行證明（隔離後只在刻意注入時發生）。
3. 加**隔離驗證測試**：generate 完成後斷言 job 記錄落在 tmp state 檔（而非真實檔）。

**理由**：注入式重現證明「共享 state 檔＝測試可被外部狀態炸掉」，隔離修一次消滅 prune／改寫／鎖競爭三條路徑，且測試不再污染 repo 檔。不改產品碼（prune 對未來時間戳髒資料的敏感性屬產品既有語意，真實環境由單一寫入者＋now() 時間戳保證，不在本案範圍）。

### B. traffic 互動查詢層吞 PCE 失敗（406 等）

**現況**：H-Task 1（2026-07-11）已把 `_submit_and_stream_async_query` 的全部失敗分支（submit 非 2xx 含 406、無 href、poll `state=="failed"`、poll 逾時、download 失敗）接上 `ApiClient.last_fetch_error` 訊號屬性（開頭清 None、失敗設描述字串、重下載復原清 None），**ingest 路徑**（scheduler `_fetch_window`）已消費該訊號。但**互動查詢鏈**仍全程吞掉：

- `execute_traffic_query_stream`（`src/api/traffic_query.py:899-902`）的 `except Exception` 只 log 後裸 `return`，且不設 `last_fetch_error`（`_request` 層丟的 `APIError` 有設，其餘例外沒有）——訊號缺口。
- `Analyzer.query_flows`（`src/analyzer.py:1352`）消費完 stream 後**從不檢查** `last_fetch_error`，失敗回 `[]` 與真 0 筆完全同形。
- GUI `actions.py /api/quarantine/search`、`dashboard.py` top-actions 拿到 `[]` 回 `{"ok": true, "data": []}`——使用者看到 0 列，無從得知查詢其實失敗（filter-selector 4b 記錄的 payload 形狀錯 406 即此形態）。

**設計（raise，於 analyzer 層；API 層維持訊號屬性）**：

1. `execute_traffic_query_stream` 的 `except Exception` 分支補訊號：`if not c.last_fetch_error: c.last_fetch_error = f"traffic query exception: {e}"`。**不 raise**。
2. `src/exceptions.py` 新增 `class TrafficQueryError(APIError)`。
3. `Analyzer.query_flows` 在 stream 耗盡後（含 `not traffic_stream` 早退分支）檢查：`last_query_source in ("api", "mixed")` 且 `self.api.last_fetch_error` 非空 → `raise TrafficQueryError(err)`。
4. GUI 兩個呼叫端（`actions.py` quarantine search、`dashboard.py` top-actions）在既有泛用 except 之前捕捉 `TrafficQueryError` → `{"ok": false, "error": t("gui_err_traffic_query_failed", detail=...)}` HTTP 502。前端 `quarantine.js` 既有 `if (!r.ok || r.error) throw` 錯誤列渲染（:293-306）直接生效，**JS 零改動**。

**raise vs 訊號屬性的取捨（理由寫明）**：

- **API 層（generator）不 raise**：ingest 路徑消費同一個 generator，契約是「空 yield ＋ `last_fetch_error` 訊號」（失敗→watermark 不推進→下輪重試）；改成 raise 會改變 ingest 控制流，違反「不可破壞 ingest 既有語意」。except 分支補設訊號對 ingest 是同向改善（原本靜默空、現在正確判失敗重試），非破壞。
- **analyzer 層 raise 而非再加一個訊號屬性**：本 bug 的成因正是「訊號要靠每個 caller 記得查」——`query_flows` 忘了查 `last_fetch_error`。typed exception 對現有與未來 caller 都 fail-loud；`query_flows` 的呼叫者只有 GUI 互動端點（actions.py、dashboard.py，已查證無其他 caller），raise 不觸及任何背景鏈。
- **`mixed` 也 raise**：hybrid 路徑 API 補洞失敗時回「部分結果」比回錯誤更糟（不可分辨的不完整資料），與本項宗旨一致。
- 時序安全：`_submit_and_stream_async_query` 是「全部下載完才開始 yield」，第一筆 yield 出現時 `last_fetch_error` 已定稿（失敗分支根本不 yield；重下載復原會清 None）——`query_flows` 因 cap 提前跳出也不會誤判。

### C. any 方向 label_group pill 序列化成 any_label — 採 (b)「明確不支援」

**現況**：`src/static/js/filter-bar.js:79` 把 `dir==='any'` 的 label_group pill 序列化成 `${ex}any_label`（group 名被當 label spec）。下游 `any_label` 是 fallback 比對（capability matrix :80）、`_label_match` 拿 group 名對 flow label 全不命中 → fail-closed 0 筆（4b 已實測記錄）。不會壞資料，但使用者選了 label_group 卻靜默查不到東西。

**兩案評估**：

- **(a) 全鏈支援 `any_label_group`**：需要動七層白名單鏈（filter-bar.js 序列化 → actions.py/reports.py forward → analyzer `query_flows` whitelist → `_TRAFFIC_FILTER_CAPABILITIES` ＋殘餘比對 → df 展開閘門 → CLI）＋第八處 `_CACHE_UNEVALUABLE_FILTER_KEYS`。致命點在**執行語意不可靠**：any_* 全族是 fallback（either-side 無法逐 filter 表達成 native payload——`sources_destinations_query_op` 是全查詢層級旗標），而 **client 端比對器沒有 label_group 成員展開**（`analyzer.py:72-74` 註解明載「成員展開只存在於 PCE 端」，含巢狀 sub_groups）。要支援就得新建 client 端成員展開機制（巢狀遞迴、快取一致性、與 PCE 語意對齊），成本與風險遠超「any 方向的便利性」。
- **(b) any 方向明確不支援 label_group**：UI 排除＋序列化防禦。有直接先例——`rules.py` 的 `_RULE_REJECTED_KEYS` 對同性質的「client 端不可評估」限制已採明確拒絕（400 ＋ `gui_rule_label_group_unsupported`）。使用者替代方案完整：分別加 src 與 dst 的 label_group pill（native 執行、語意可靠）。

**裁決：採 (b)**。實作四點：

1. **序列化防禦**（:79）：刪除 label_group→any_label 映射，改為 skip ＋ `console.warn`（防禦性拒絕：即使 guard 被繞過也不產生錯 key、不變形語意）。
2. **pill 建立拒絕**：`_objfbAddPill` 入口 guard——`cat==='label_group' && addDir==='any'` 時不建 pill，顯示提示。
3. **suggest 排除**：`addDir==='any'` 時，suggest types 導出（:492）、下拉分類快選鈕（:342）、suggest 結果迭代（:545）三處都排除 `label_group`；切換到 any 方向時若 `scopeCat==='label_group'` 清除 scope。正常流程使用者根本看不到選項，guard 是 backstop。
4. **i18n 提示**：新鍵 `gui_fb_any_label_group_unsupported`，比照 `gui_fb_any_slow` hint 列（:246-250）樣式顯示。

**後端防禦性拒絕的裁決**：評估後**不加後端拒絕碼**。`any_label_group` key 從未存在於任何白名單（actions.py/reports.py/analyzer 天然丟棄未知 key）；而錯誤形態是「group 名藏在 `any_label` 值裡」，後端無法與真 label spec 區辨。為不可到達的 key 寫拒絕鏈等同做半套 (a)。防禦收斂在序列化邊界（第 1 點的 skip+warn）。

**CLI 查證結論**：`src/cli/object_picker.py` 無 any 槽位（`preserve_any_filters` 僅原樣保留 GUI 專屬 key）、`cli/menus/traffic.py` 的 `_PICK_CATS` 本就不含 label_group——CLI 層天然不受影響，零改動。

**已知限制（記錄）**：修正前已被錯存成 `any_label` 值的 label_group 名稱無法回溯辨識，維持現狀（fail-closed 0 筆，與修正前行為相同）；編輯該查詢時會以 label pill 回填，使用者重存即收斂。

### D. IP List `exclusion:true` ranges 展開語意對齊 PCE

**現況**：`src/api/labels.py:593` `_iplist_cidrs`（`expand_object_filters_for_df` 的內部函式，cache df 路徑物件展開專用）迭代 `ip_ranges` 時**忽略 `exclusion` 旗標**，把 exclusion 條目一併展開成 inclusion CIDR。PCE 語意是「effective = inclusion 聯集 − exclusion 聯集」，現行展開造成 cache df 路徑 over-include（data-dependent：只有帶 exclusion 條目的 IP List 受影響）。

**三路現況查證**：

- **native 路徑**：`_resolve_iplist_filter_to_actor` 送 ip_list href 進 payload，exclusion 語意由 PCE 端套用——**本來就正確，不動**。
- **fallback 殘餘比對**：`_iplist_hit`（traffic_query.py:966）比對 flow 裡 PCE 標注的 `side.ip_lists` membership——PCE 產生標注時已套用 exclusion——**本來就正確，不動**。
- **cache df 路徑**：`_iplist_cidrs` 展開 → `df_filter` CIDR mask——**唯一錯的一路，本案修這裡**。修好即三路一致。

**設計（精確扣除，於展開端）**：`_iplist_cidrs` 把 `ip_ranges` 依 `exclusion` 旗標分成 include/exclude 兩組（range 形先 `summarize_address_range` 成 CIDR），**per-IP List** 做 CIDR 集合差後回傳——輸出仍是扁平 CIDR list，`df_filter`／`report_generator`／內部 `_*_object_cidrs` key **零改動**。

- 差集演算法：CIDR 兩兩「非相離即巢狀」（range 已先化成 CIDR），對每個 exclusion：不重疊→保留、exclusion ⊇ inclusion→整塊剔除、inclusion ⊃ exclusion→`address_exclude` 切分。跨 IPv4/IPv6 版本互不作用。無法解析的 inclusion 字串條目原樣保留（fail-open 保守：寧可 over-include 也不無聲丟 inclusion，沿現行 bad-range warn+skip 慣例）。
- **per-list 扣除的必要性**：同一 filter key 多個 IP List 是 OR 聯集語意；若把所有 list 的 exclusion 合併後統一扣，list A 排除、list B 包含的區段會被錯誤剔除。逐 list 算 effective 再聯集才精確。
- **成本評估（「排除 exclusion 條目不展開」保守案否決）**：保守案只解決「exclusion 範圍被當成員」的那一半，inclusion 範圍內被 exclusion 覆蓋的 IP 仍 over-include——沒有達成語意對齊。而精確扣除用 stdlib `ipaddress` 即可：每個 exclusion 對一個 inclusion 的 `address_exclude` 至多產生 prefix 深度（≤32/128）個網段，IP List 條目數量級小，df 展開一次一算，成本可忽略。不存在需要 under-include 取捨的情境。

## 3. 非目標

- A：`_save_adhoc_job` prune 對異常時間戳的防護（產品碼不動；真實環境單一寫入者＋now() 時間戳）。
- B：ingest 路徑行為變更（僅 except 分支補訊號一項同向改善）；`execute_traffic_query_stream` 改成 raise；CLI 互動查詢的錯誤呈現（CLI 已有 print 提示）。
- C：`any_label_group` 全鏈支援（裁決為不支援）；歷史誤存 `any_label` 值的回溯清洗。
- D：ingest 儲存層或 fallback 比對器改動（該兩路語意已正確）；FQDN 條目展開（現行即不展開，維持）。

## 4. 測試原則

各項 TDD（先 RED）：A 需機制釘測試（注入 20 筆未來 job → 404）＋隔離驗證；B 需三層測試（API 層 except 分支訊號、analyzer 層 raise/不 raise 對照、GUI 層 502＋i18n 訊息）；C 用該檔既有靜態斷言樣式（舊映射消失、guard 存在、i18n 鍵雙檔在）＋ `node --check`；D 需 exclusion 扣除／exclusion-only／range 形／相離 no-op／多 list 聯集不交叉扣除五個案例。全套迴歸綠、`ruff check` 改動檔零新增 violations、i18n 新鍵走三檔 precompute 流程＋glossary。

## 5. 執行順序

A（先讓全套測試可信）→ B（訊號完整性，價值最高）→ C → D。單分支 `fix/deferred-minors-hardening` 串行（B/C 均觸 GUI 路由層，A/B 共 tests 慣例）。
