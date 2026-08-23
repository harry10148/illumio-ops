# 2F-1：流量調閱的資料來源選擇與封存串流查詢

> 狀態：設計已與使用者對齊，待寫實作計畫。
> 本檔所有對現況的描述皆已對原始碼查證；行號會漂移，以符號為準。

## 1. 要解決什麼

使用者在 2026-08-21 提出兩件事：

1. `#/investigate/traffic` **無法選擇用純 API 方式取得資料**。
2. **封存無法選時間區間**。

查證後，第二點底下藏著更根本的問題。使用者自己點出來：「目前機制感覺沒有任何限制方式直接全載入，但我的問題是未來如果真的在正式環境遇到大量連線時還能這樣隨意載入一堆資料」。

而封存的用途是明確的：**PCE 最多只保留三個月**，封存是三個月後還想查某些紀錄時唯一的途徑。

## 2. 現況（查證結果）

- **純 API 的能力已經存在**，只是沒有入口。`Analyzer._fetch_flows` 已有 `self.api.execute_traffic_query_stream(...)` 這條路，但只在 cache 涵蓋不足（`cover_state != "full"`）或讀取過大（`CacheReadTooLarge`）時**自動**觸發。`/api/quarantine/search` 沒有把任何來源偏好傳進去。
- **調查頁拿到的是原始列，不是聚合列**。`query_flows` 走 `CacheReader.read_flows_raw`（讀 `pce_traffic_flows_raw`）；`read_flows_agg`（`pce_traffic_flows_agg`）只給報表用。需要注意「原始」的兩層意思：PCE 給的 traffic flow 本來就是彙總過的（同一組 src/dst/port/proto 在偵測窗內合併，帶 `flow_count` 與 `bytes_in/out`），我們這邊的 `flow_hash` 去重是「更新 last_detected」而非把多筆併成一筆。所以每一列對應 PCE 的一筆 flow 紀錄，含 `raw` 原文欄位。
- **調查頁的來源控制項目前只有兩個值**：`live`（實為本機 cache）與 `archive`（實為已載入的 review DB）。名稱本身就有誤導。
- **封存載入是有成本的匯入動作**。`load_archive_review` / `start_archive_load` 把 JSONL 匯進獨立的 review DB 並跑 `TrafficAggregator`。現有唯一的閘門是 `pce_cache.archive_review_max_days`（預設 31），**只限制天數，不限制資料量**。測試機 31 天約 0.1 GB，高流量正式環境可能是數十 GB。
- **封存檔的形狀對串流查詢有利**：一天一個檔（`<source>-<YYYY-MM-DD>.jsonl`），每列已攤平且欄位齊全——traffic 有 `action / bytes_in / bytes_out / dst_ip / dst_workload / event_time / first_detected / flow_count / flow_hash / ingested_at / port / protocol / raw / src_ip / src_workload`。日期區間等於「開哪幾個檔」。
- **但封存檔集合本身有四個性質，初稿全部漏掉**（2026-08-23 Codex 對抗式審查指出，逐項對原始碼查證屬實）：
  1. **舊檔是壓縮的**。`pce_cache.archive_gzip_after_days` 預設 7，`ArchiveExporter._gzip_old_files()` 每次匯出時把超過天數的檔轉為 `.jsonl.gz`。**本案的核心情境（三個月前）的資料必然只以 `.gz` 存在**。
  2. **同一 `flow_hash` 會重複出現**。`src/pce_cache/archive.py` 的註解明寫「下次會重寫同批，JSONL 可能含重複列」——長壽 flow 更新時會再次匯出，fsync 後、游標推進前崩潰也會重寫整批。`ArchiveImporter` 因此使用 `on_conflict_do_update`（`archive_import.py:176-196`）：`last_detected / bytes_in / bytes_out / flow_count / ingested_at` 取 MAX、`first_detected` 取 MIN、`raw_json` 取較新 `last_detected` 那一側。
  3. **現行查詢是全域排序後截斷**。`QUERY_RESULT_CAP = 500`，`query_flows` 依 `sort_by`（bandwidth／volume／connections）排序**全部命中**再取前 500，且註解明訂「截斷需回報，不可無聲」。
  4. **有一類 filter 無法離線評估**。`_CACHE_UNEVALUABLE_FILTER_KEYS`（`analyzer.py:139-147`）列出 label group 與 AMS 系列，註解記載「帶這些 key 時 cache 命中會靜默回未過濾資料（2026-07-24 審查 M4）」；`draft_policy_decision` 也由即時查詢計算，不存在於封存列中。

## 3. 決策

使用者在四個方案中選擇 **A：串流查詢取代載入**，並確認「原始列與聚合都要」。

因為封存的每一列本來就是原始列，「兩者都要」收斂為：**串流回傳原始列為主，聚合摘要在同一趟掃描裡累加**，作為結果上方的摘要而非第二種列表。不掃兩次，也不必向操作者解釋兩種模式。

結果上限採 **「回傳上限＋明說已截斷」**：列表給前 N 筆，聚合摘要涵蓋掃到的全部。

「只用快取」選項經確認**不需要**。

## 4. 設計

### 4.1 資料來源選擇器

調查頁的來源控制項改為三選：

| 選項 | 行為 |
|---|---|
| 快取優先（預設） | 維持現況：cache 涵蓋則讀 cache，不足自動補 PCE |
| 直接查 PCE | 強制 `execute_traffic_query_stream`，完全不碰 cache |
| 封存 | 走 §4.2 的串流查詢 |

`/api/quarantine/search` 接受 `data_source`，沿用報表既有的 `resolve_data_source`（`src/report/cache_support.py`）**同一個判準函式**，避免兩處對「hybrid / live」的定義漂移。`query_flows` 現在自行判斷 `cover_state`；改為**操作者明確指定時尊重指定，未指定才自動判斷**。

**一併修正的既有行為**：目前 cache 涵蓋不足時會靜默補 PCE，操作者不知道拿到的是混合結果。改動後回應要標明實際走了哪條路（cache／api／兩者），前端顯示出來。這與本專案「失敗與正常不能長得一樣」的既有紀律一致。

### 4.2 封存串流查詢

新增 `src/pce_cache/archive_query.py`，單一公開函式：

```python
def stream_query(archive_dir: str, source: str, start: date, end: date,
                 filters: dict, cap: int) -> ArchiveQueryResult
```

回傳 `rows`（最多 `cap` 筆）、`summary`（聚合）、`truncated`、`scanned`、`skipped`、`incomplete_after`。

- 日期區間決定開哪些檔，**`.jsonl` 與 `.jsonl.gz` 都要開**（同一天兩者都存在時以 `.jsonl` 為準，壓縮是原地取代）
- 逐列解析、逐列比對；**至少要有一個篩選條件**，否則拒絕並說明原因
- **在截斷與聚合之前，先依 `flow_hash` 合併重複列**，沿用 `ArchiveImporter` 既有的取值規則（volatile 欄位取 MAX、`first_detected` 取 MIN、`raw` 取較新 `last_detected` 那一側）。不合併就會重複計數並灌水 `flow_count` 與 bytes
- **保留現行的全域排序語意**：依 `sort_by` 維護一個 `cap` 大小的 top-N heap，而不是取檔案順序的前 N 筆——否則後面日期檔裡的高流量結果會被漏掉
- 聚合摘要**必須有界**：維護固定基數的 top-K（K 與 `cap` 同量級）加上「其餘 N 組已省略」的計數。無界 group-by 的狀態是 O(命中列數)，正好重現本案要消除的大量載入問題
- `truncated=True` 時前端明說「列表已截斷」，並標明摘要是 top-K 而非全量

**篩選條件的白名單**：封存來源只接受能逐列離線評估的 key。帶到 `_CACHE_UNEVALUABLE_FILTER_KEYS` 裡的 label group／AMS 條件，或 `draft_policy_decision` 時，**明確拒絕並說明「這個條件需要即時查詢 PCE 才能判定，封存查不到」**——不得靜默回未過濾資料，那正是 2026-07-24 審查抓過的坑。

**移除**（使用者已確認接受既有 review DB 失效）：`load_archive_review`、`start_archive_load`、`ArchiveLoadBusy`、review DB 與 `review_db_path`、`POST /api/cache/archive/load`、System→Cache 的載入 UI、`pce_cache.archive_review_max_days` 設定鍵（走既有的 deprecated-key 退場路徑）。

移除後，「隨意載入一堆資料」這件事不存在，而不是被加上煞車。

### 4.3 錯誤處理

- 封存目錄不存在，或該區間沒有任何檔案 → 明說「這段沒有封存資料」，不是回空結果
- 單列 JSON 壞掉 → 跳過並計數，結果附「略過 N 列無法解析」，不讓整趟失敗
- 掃描逾時 → 回傳已掃到的部分，並標明 `incomplete_after`（掃到哪一天為止）

### 4.4 測試

- `archive_query` 單元測試：篩選正確性、`cap` 截斷、壞列跳過、無篩選被拒、無檔案與逾時路徑
- **針對上述四個性質各一條**：`.jsonl.gz` 查得到；同 `flow_hash` 的成長快照與 at-least-once 重複列合併後不灌水；高基數壓力測試確認摘要記憶體有界且省略計數正確；後面日期檔裡的高流量列會進 top-N（用檔案順序取前 N 的實作必須失敗）
- 白名單測試：帶 label group／AMS／`draft_policy_decision` 時回明確錯誤而非未過濾結果
- e2e：三個來源選項各查一次，斷言請求帶的 `data_source` 與結果標示的實際路徑相符
- 移除路徑的守門測試：`load_archive_review` / `start_archive_load` / `review_db_path` / `archive_review_max_days` 在 `src/` 與 `tests/` 歸零（比照本專案既有的 `test_config_models.py` 命名守門寫法，用集合相等而非子字串）

## 5. 本設計不處理

- **封存的產生端**（retention 與 archiver）完全不動
- **報表的資料來源**已有三模式選擇器，不在本案範圍
- 聚合摘要的呈現形式（圖表或表格）留給 2F-3 的風格重做決定；本案只保證資料算得出來
