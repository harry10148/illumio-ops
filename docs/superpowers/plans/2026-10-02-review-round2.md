# 第二輪 review：SIEM、真實 PCE 驗證、可靠性遺留、安裝升級、故障注入、測試品質

2026-10-02 起草。**提案，尚未執行。** 基準版本：main @ 393607b（PR #43 合併後）。

這份計畫整合六個方向的 read-only 分析。其中五個由各自的 subagent 執行，SIEM 的
7 個關鍵發現另由第二個 agent 獨立重現。真實 PCE 驗證由主 session 透過 Illumio
LAB MCP 評估。

分析期間 repo 沒有被修改。重現腳本放在 session 的暫存目錄，不會留存；執行時，
每一項修正都要把對應的重現腳本移植成 `tests/` 裡的回歸測試，先紅後綠。

標記說明：

- **已重現**：實際注入故障或執行程式後觀察到結果。
- **讀碼**：只從程式碼推論，未執行。
- 工作量：S（半天內）、M（1–3 天）、L（一週以上）。

---

## 0. 結論先講

| 方向 | 高 | 中 | 低 | 最嚴重的一件事 |
|---|---|---|---|---|
| SIEM 轉送 | 7 | 9 | ~12 | TCP/TLS 接收端中途重啟或卡住時，**未送達的資料被標成已送出**（已重現：300 筆收到 145 筆；5 萬筆在 0 bytes 被讀取下全標已送） |
| 故障注入 | 7 項重大 | — | — | **DST 結束那天 cron 排程報表觸發約 61 次**，每次都寄信（已重現） |
| 可靠性遺留 | 6 項設計 | — | — | 告警遺失的時間窗比原先以為的多：cache 模式的事件 cursor 在送出前就提交 |
| 安裝升級維運 | 5 | 10 | 8 | 非 purge 解除安裝後**重裝同版本會被拒絕**；**升級中途失敗會讓服務停擺且無法回滾** |
| 測試品質 | 3 項高 | — | — | **改 PCE 的程式碼被改壞也沒有測試會失敗**（9/16 個突變存活） |
| 真實 PCE 驗證 | — | — | — | 容器連不到 LAB PCE，需要在 lab 主機上執行（見 §2） |

**資料遺失或重複類（優先修）：**

1. **SIEM 標錯已送出。** TCP/TLS 中途重連或接收端不讀資料時，資料遺失卻標成已送出。
   - 對應項目：S-H1、S-M5。
2. **SIEM 整條佇列被丟進 DLQ。** HEC token 錯誤（401/403/404/400）會在一個 tick 內把整條佇列丟進 DLQ，而且 job 狀態還是綠的。
   - 對應項目：S-H2。
3. **DST 時 cron 報表重複寄出。**
   - 對應項目：C-1。
4. **cache 模式下 state.json 寫不進去時，事件告警永久遺失。**
   - 對應項目：C-2、D-1 W0。
5. **非同步流量下載壞一行就默默少資料，短少的結果也照收。**
   - 對應項目：C-4。
6. **legacy 事件輪詢在本機時鐘快超過 20 分鐘時遺失事件。**
   - 對應項目：C-5。
7. **SIEM 接收端停機約 1.5 小時，整條佇列進 DLQ。** DLQ 30 天後清除，期間沒有任何告警。
   - 對應項目：S-M2、C-3。
8. **events 積壓時遇到 2% 暫時錯誤就完全無法前進（livelock）。**
   - 對應項目：C-livelock。
9. **CLI 編輯 SIEM 目的地會清掉 host/port 並關閉 `mask_pii`。**
   - 對應項目：S-H3。

**無聲停擺類：**

- **排程 job 一再失敗或卡住時，沒有任何告警。**
  - `monitor_cycle` 出錯就等於全部告警停擺。
  - 對應項目：C-6、O-M3。
- **config.json、state.json 或快取 DB 毀損時，會降級運作或改用舊路徑，但不告警。**
  - 對應項目：C-corrupt。

---

## 1. SIEM 轉送（S-*）

設計上是 at-least-once。佇列是 `siem_dispatch` 表，裡面的每一筆是「一筆來源資料要送到某個目的地」的派送紀錄；後面說的「列」都指這種派送紀錄。

### 高

| ID | 問題 | 證據 | 驗證 | 修法 | 工作量 |
|---|---|---|---|---|---|
| S-H1 | TCP/TLS 接收端在一個 batch 中途 RST 或當機時，`send()` 默默重連，舊連線上對方還沒讀的資料就遺失了。`finish_batch` 只確認新連線，所以整個 batch 被標成 sent。`sendall` 逾時也會走同一條路。 | `syslog_tcp.py:33-53`、`syslog_tls.py:58-78`、`_stream.py:21-79`、`dispatcher.py:208-240` | 已重現（端到端，經過 DB）：TCP 300 筆收到 145、TLS 300 筆收到 150 | 已經在本 batch 送過資料的連線一旦斷掉，就把 batch 標為「未確認」，`finish_batch` 拋錯，整批走既有的重試路徑 | S |
| S-H2 | HEC 401/403/404/400 一律視為「這一筆永久失敗」。一個 tick 就把整條佇列（上限 `dlq_max_per_dest`，預設 1 萬）丟進 DLQ，回報 `aborted=False`，job_health 保持綠燈。DLQ 30 天後清除。 | `dispatcher.py:21-35,180-189`、`jobs.py:707`、`retention.py:90` | 已重現（真實 transport）：2500 列全進 DLQ | 401/403/404 改為目的地層級錯誤：中止 batch、不消耗重試次數、標示目的地不健康並發告警。只有真正屬於單筆資料的錯誤（例如 413）才進 DLQ | S |
| S-H3 | CLI 的 SIEM 選單：<br>• 列表讀 `d.endpoint` 直接當掉。<br>• 編輯時一路按 Enter，host/port 被清空、`mask_pii`/`framing`/`profile` 被重設。host 變成空字串，就是送到本機 514。<br>• dev profile 的目的地無法從 CLI 編輯。<br>• 允許同名目的地：每筆資料產生兩列派送紀錄，第一個目的地送兩次，第二個什麼都收不到。 | `siem_cli.py:92-178`、`config_models.py:401-433` | 已重現 | 套用 GUI 的合併語意（`web.py:86-104`）；模型層加名稱唯一驗證；啟用中的目的地 host 不得為空 | S |
| S-H4 | 規模不足：<br>• HEC 每筆事件一個 POST，20 ms RTT 下約 48 筆/秒，低於每天 500 萬筆所需的 58 筆/秒，而且多個目的地是依序處理。<br>• 每個 tick 都用 NOT EXISTS 掃最近 14 天的 safety-net（約 1 秒/百萬列）。 | `splunk_hec.py:53-69`、`dispatcher.py:609-613`、`jobs.py:678` | 部分實測，部分推算 | HEC 批次送（多個 JSON 物件串接）；safety-net 改用每個（表、目的地）的 high-water mark，完整 anti-join 只在啟動、設定變更時或每小時跑一次 | M |
| S-H5 | 刪除或改名目的地後，它待送的列永遠不會被清掉，還會擋住來源資料的 retention 並持續觸發積壓告警。改名會把最近 14 天重送一次。之後如果又新增同名目的地，會收到這些過期資料。 | `web.py:113-131`、`siem_cli.py:171-178`、`retention.py:100-147` | 已重現（真實流程） | 刪除或改名時一併清理（或改掛到新名稱）待送列；retention 清除找不到目的地的待送列；status 與 capacity 只計算目前設定中的目的地 | S–M |
| S-H6 | 新增目的地或首次啟用 SIEM 時，所有候選列在**單一 transaction** 裡寫入。70 萬列時寫入鎖持有 48 秒，其他 writer 等 30 秒後收到 `database is locked`。3500 萬列推算會用掉約 20 GB 記憶體。 | `dispatcher.py:640-663` | 已重現（10 萬／30 萬／70 萬列） | 用 Core executemany 每 5–10k 列 commit 一次、串流讀取候選列、每個 tick 設上限 | S |
| S-H7 | `siem_dispatch` 每列 273 B（含 8 個索引）。每天 500 萬筆 × 保留 14 天 ≈ 7000 萬列 ≈ 19 GB／每個目的地。其中有 3 個單欄索引是多餘的。 | `models.py:159-182`、`retention.py:100-103` | 實測 | 移除多餘索引；sent 列提早刪除或壓縮（需要 S-H4 的 high-water mark） | M |

### 中

| ID | 問題 | 修法 | 工作量 |
|---|---|---|---|
| S-M1 | dispatcher 寫入時沒拿 `_CACHE_WRITE_LOCK`。aggregator 跑長 transaction 時，標記已送出（mark-sent）會失敗，整批重送（已重現：50 筆送了 100 次）。 | mark-sent 失敗時以退避重試；只在短暫的寫入段落持鎖 | S |
| S-M2 | 接收端停機時，每個 tick 都消耗最舊那列的重試次數，約 1.5 小時後就進 DLQ（停機 6 小時：300 筆有 58 筆進 DLQ）。重試也會打亂順序。 | 目的地層級退避，中止的嘗試不計入重試；改用時間到期（例如 7 天）；重試時先處理佇列最前面的列以保持 FIFO | M |
| S-M3 | 積壓 200 萬列時，取一個 batch 要 0.43 秒，積壓越多越慢。 | 加 `(destination, status, queued_at)` 複合索引（實測 0.0003 秒） | S |
| S-M4 | 設定重啟後可能有兩個 dispatch 同時跑（`_runtime.py:247` 用 `wait=False`），沒有任何唯一約束能防止重複送。 | 每個目的地一把模組層級鎖，或對列加 lease；`(source_table, source_id, destination)` 加唯一索引並用 ON CONFLICT DO NOTHING | S–M |
| S-M5 | 接收端接受連線但從不讀資料（例如 Splunk tcpin 佇列塞住）時，資料被當成已送達。批次夠大時會走 S-H1 的重連路徑，5 萬筆在 0 bytes 被讀取下全標已送。 | 跟 S-H1 一起修。TCP syslog 本身沒有應用層 ACK，要真正可靠需評估 RELP（列為選項） | S（併入 S-H1） |
| S-M6 | `cef_pce`/`syslog_cef_pce` 不跳脫 `=` 和 `\`。VEN 回報的 process name、hostname、label 說明或 api_endpoint 可以注入或覆蓋 CEF 鍵（已重現：`act=allowed` 覆蓋了 blocked）。這是為了與 PCE 原生格式一致而刻意這樣做；`arcsight` 方言已經存在，但無法從設定選用。 | **需決策**（§7-D2） | S |
| S-M7 | 可觀測性不足：<br>• 目的地掛掉、DLQ 成長都不會主動告警，只有全域待送超過 5 萬筆時每 30 分鐘檢查一次。<br>• `last_error` 從來沒被寫入。<br>• 看不到最後一次成功時間與最舊待送的延遲。<br>• `/api/siem/status` 在大量資料時要跑數十秒。 | 記錄每個目的地的 `last_error`/`last_success` 與最舊待送時間；中止、DLQ 成長或延遲超過門檻時發 ops 告警；加索引 | M |
| S-M8 | HEC 遵守 `Retry-After`，上限 6 小時 × 3 次，會卡住所有目的地。 | `retry_after_max` 設約 30 秒 | S |
| S-M9 | `mask_pii` 漏掉的欄位：<br>• service account 名稱<br>• agent hostname<br>• `resource_changes[].resource.*`（email、名稱）<br>• `duid`<br>• flow 的 hostname/IP/fqdn<br>另外，遮罩後 `dst=[REDACTED]` 會寫進 IP 型欄位。 | 遮罩所有 `created_by` 子物件與 `resource.*`，並在文件中列清楚遮了哪些欄位 | S |

### 低（執行時順手處理）

- **長壽 flow 重送。** 長時間存在的 flow 在 14 天後 sent 列被清掉，可能被再送一次。
- **時間戳不一致。** JSON flow 的時間戳用 `first_detected`，header 用的是 `last_detected`。
- **RFC5424 header：**
  - hostname 沒有清理。
  - flow 的 host 固定寫 `illumio-ops`。
  - severity 固定。
- **ArcSight 欄位型別。** IP 欄位會放 FQDN，`cs2` 可能超過 4000 字元。
- **只支援 IPv4。**
- **UDP 沒有大小策略。** `cef_pce` 一筆約 7–8 KB。
- **HEC 欄位。** 缺少 `index`/`host`/`source`。
- **設定驗證不足。** `source_types` 接受任意字串；transport 是 hec 時沒有強制要求 token。
- **死碼。** `cef.py:39-65` 只有測試在用。
- **i18n 寫死字串（違反 AGENTS.md）：**
  - `web.py:279`
  - `dlq.py:79,108`
  - `jobs.py:714`
  - CLI 提示文字

**需要一起修正的測試。** 既有測試中，有幾支把 S-H2（「永久錯誤進 DLQ」）和 S-H6（「單一 transaction」）的錯誤行為當成預期結果寫死了，修正時要一起改。

---

## 2. 用真實 PCE 驗證數字（V-*）

### 現況

- LAB PCE（`pce.lab.local`，on-prem）可以透過 Illumio LAB MCP 唯讀查詢。workload、事件、流量摘要都查得到，而且目前有實際事件在產生。
- 這個雲端容器無法直接連到 `pce.lab.local`（DNS 解析不到）。所以 illumio-ops 本身沒辦法在這裡對 LAB 執行。
- MCP 回傳的格式經過轉換（compact 表格、`created_by` 被轉成字串），**不等於** PCE REST API 的原始回應。

### 做法

**V-A：在 lab 主機上執行工具（需要你協助）**

1. 在能連到 LAB PCE 的主機上，用**唯讀 API key** 安裝目前的 main。目的地設為測試用的 Graylog/syslog 接收端。
2. 讓它跑一個完整週期，包含 cache ingest、aggregate 與報表。建議至少 24 小時。
3. 選定同一個時段，由工具匯出以下數字：
   - 快取中的事件數（依 event_type）、flow 數（依 policy decision）、workload 數（managed/online/enforcement mode）；
   - 報表 KPI；
   - 告警紀錄；
   - SIEM 已送出筆數與接收端收到的筆數。
4. 同一時段由 MCP 獨立查詢：`get-events`、`get-traffic-flows-summary`、`get-workloads`、`get-workload-enforcement-status`。
5. 寫一支比對腳本逐項列出差異，並為每項差異找出原因：時區、時間窗端點、分頁截斷、取樣、label 正規化等。
6. **告警實測：**
   - 在 LAB 製造已知事件，例如登入失敗 N 次、在測試 workload 上產生指定 port 的流量；
   - 確認該觸發的規則確實觸發、不該觸發的沒有觸發；
   - 確認 PCE health 的 on-prem 探測路徑正確。

驗收標準：

- 計數類數字完全一致，或者每項差異都有書面原因。
- SIEM 接收端收到的筆數等於已送出的筆數。

**V-B：在這裡就能做的部分**

用 MCP 從 LAB 抓取事件、workload、流量的樣本，去識別化後做成 fixtures，餵給工具的解析和分析流程，先驗證格式相容。限制是 MCP 的格式經過轉換，需要先反推回 API 形狀，所以 V-B 只能當作煙霧測試，取代不了 V-A。

### 前置

1. S-H1/H2/H3 修完後再做 V-A。否則 SIEM 計數比對會被已知的 bug 汙染。
2. 你要提供：
   - lab 主機的存取方式（或由你在 lab 執行，我提供腳本）；
   - 一組唯讀 API key。

---

## 3. 可靠性遺留項目（D-*）：完整設計

完整設計放在原型目錄。以下列出要點、實測數字與相依關係。

| ID | 項目 | 設計要點 | 實測／驗證 | 工作量 |
|---|---|---|---|---|
| D-1 | **告警 outbox** | 見下方說明 | kill -9 子程序測試框架（fault hook 在各階段送 SIGKILL） | L |
| D-2 | **每個通道各自重試** | 建在 D-1 上，見下方說明 | 測試情境：mail 成功、webhook 失敗 → 只重送 webhook | M（D-1 之上） |
| D-3 | **流量 ingest 加速與縮小持鎖範圍** | 預先編譯 executemany upsert + RETURNING；資料整理移到鎖外；每個時間窗共用一條連線；每 5000 列 commit 並釋放一次鎖 | 10 萬筆：64.4 秒 → 14.3 秒，持鎖 64.4 秒 → 10.8 秒；raw/obs/siem 三張表與舊版**逐欄相同** | M |
| D-4 | **aggregator、retention 與空間回收** | 見下方說明 | 最大 transaction 9.57 秒 → 1.52 秒，輸出相同；VACUUM 後檔案 2.3 GB → 1.25 GB | M |
| D-5 | **流量告警截斷（每輪上限 1 萬列）** | 分兩步，見下方說明 | Python 引擎每秒約 1.07 萬筆 flow（5 條規則）；每天 500 萬筆時 60 分鐘窗約 21 萬列 ≈ 25 秒 | A：S，B：L |
| D-6 | **session 撤銷** | 見下方說明 | Flask test client 測試 | M |

**D-1 告警 outbox**

- **新的遺失時間窗：**
  - W0：cache 模式的事件 cursor 在送出前就提交。
  - W2：`_pop_alert_dlq` 在派送前就把 DLQ 清空。
- **做法：**
  1. 在 `logs/alerts.sqlite` 新增 `alert_outbox` 與 `alert_delivery` 兩張表（schema v2）。
  2. 去重鍵由證據產生（事件 href、冷卻時間戳）。
  3. 新的週期順序：分析 → 寫入 outbox → 提交事件 cursor（延後到這一步）→ `save_state` → 派送（以 lease 控制，不在分析鎖內）。
  4. 載入時以 outbox 回填 cooldown/throttle。
  5. 舊的 `alert_dlq` 遷移進 outbox。
  6. 帶冪等鍵：LINE 用 Retry-Key、mail 用 Message-ID、webhook 用 Idempotency-Key。

**D-2 每個通道各自重試**

- 每個通道只送它還沒成功的那些。
- 退避：`min(30 秒 × 2ⁿ, 15 分)`。
- 判定為 dead 的條件：失敗 3 次且超過 1 小時，或者 skipped 超過 24 小時。
- 通道被移除的列標 `cancelled`；新增的通道不補送舊告警。
- throttle 計數維持在決策時計一次，不受重試影響。
- 過渡方案（S）：先在 `alert_dlq` 項目上記錄 `pending_channels`。

**D-4 aggregator、retention 與空間回收**

- **aggregator：**
  - 每天一個 transaction（按日切分才能與 GROUP BY 的鍵對齊）。
  - `DO UPDATE` 加上 WHERE 條件，資料沒變時影響 0 列、不產生 WAL。
- **retention：**
  - 改為每個 batch 各自持鎖。現在整個 job 持鎖約 36 秒。
  - `NOT IN` 改為 `NOT EXISTS`。
- **空間回收：**
  - 設定 `journal_size_limit`，並執行 `wal_checkpoint(TRUNCATE)`。
  - `auto_vacuum=INCREMENTAL` 只在 daemon 啟動時轉換，並設門檻：可用空間不足就不轉。
  - `incremental_vacuum` 必須用 `executescript` 執行。用 `execute` 每次呼叫只回收 1 頁。

**D-5 流量告警截斷**

- **A：** 移除 LIMIT，改用 keyset 分頁加 SQL 超集合預先過濾，仍由 Python 決定是否觸發。
- **B：**
  - ingest 時用同一套 Python helper 預先算好約 25 個 `m_*` 欄位，總和改在 SQL 中計算。
  - 無法下推到 SQL 的過濾條件改走 Python 混合路徑。
  - 提供 `python|shadow|sql` 三種模式，先以 shadow 跑一個版本，比對兩邊結果。

**D-6 session 撤銷**

- **新發現的問題：**
  - 被偷走的 cookie 只要每 8 小時內用一次，就永遠不會過期（Flask 每個 request 都會重新簽發）。
  - 從 CLI 改密碼，不會撤銷執行中 GUI 的 session。
- **做法：**
  - 新增 `logs/gui_sessions.sqlite`，記錄每個 session 的 sid hash、絕對到期時間與撤銷時間，再加一個 epoch。
  - 每個 request 都檢查。
  - 登出只撤銷該 sid；改密碼時 epoch +1，撤銷所有其他 session，且不再輪替 `secret_key`。
- **代價：** 升級時需要重新登入一次。

**相依關係：**

- D-3 → D-5B
- D-1 → D-2
- D-4 沿用 D-3 的「每個工作單位各自持鎖」模式
- D-6 與其他項目無關

---

## 4. 安裝、升級與維運（O-*）

分析方式：用假的離線安裝包，實際跑過以下流程：

- 全新安裝、升級；
- 非 purge 解除安裝後重裝；
- pip 失敗的升級；
- 首次開機加 SIGTERM；
- 在 64 KB tmpfs 上模擬磁碟滿。

### 高

| ID | 問題 | 證據 | 修法 | 工作量 |
|---|---|---|---|---|
| O-H1 | 非 purge 解除安裝後**重裝同版本被拒絕**：降版守門讀的是 `_MIGRATION_AGG_BUCKET_DAY=1`，但實際的 `_SCHEMA_VERSION=2`。有一支測試把這個錯的常數名寫死了。 | `install.sh:427-443`、`schema.py:152-157`、`test_install_lifecycle_contract.py:52-61` | 打包時寫入 `SCHEMA_VERSION`，或改從安裝包內的程式 import；補一支行為測試（uv = 版本 → 通過；uv = 版本+1 → 拒絕） | S |
| O-H2 | **升級中途失敗就停擺，而且無法回滾**：先停服務，再用 `rsync --delete` 覆蓋 python 和 app，最後才跑 pip。pip 一失敗，舊的套件已經被刪掉。 | `install.sh:448-496` | 先建到 `$ROOT.new`（pip + 相依驗證 + 煙霧測試），再原子交換並保留 `$ROOT.prev`。最低限度也要先備份，並用 ERR trap 還原 | M |
| O-H3 | 安裝程式的 config「遷移」用 `open(p,'w')` 直接覆寫 config.json，失敗也 `\|\| true`。磁碟滿時 config 被截斷，卻仍顯示「Upgrade complete」，之後服務以 exit 78 無限重啟。 | `install.sh:501-523` | 刪除這段（`_DEPRECATED_KEY_PATHS` 載入時已經處理過了） | S |
| O-H4 | **降版或回滾後，舊版程式無法啟動或靜默重設設定**：新版存檔會寫入完整 `model_dump`，舊版的各區段是 `extra="forbid"`。`api` 區段多一個未知鍵就 exit 78 無限重啟；`report`/`settings`/`smtp`/`web_gui` 區段則靜默退回預設值。 | `config.py:347-349,598-616`、`config_models.py:20-23` | 未知鍵改為警告並忽略（向前相容）；升級時快照 config/，`--allow-downgrade` 時還原 | M |
| O-H5 | 首次開機監聽 `0.0.0.0:5001`，帳密是公開的 `illumio/illumio`，強制改密碼也被關閉。 | `config.py:540-551` | **需決策**（§7-D1） | S |

### 中

| ID | 問題 | 修法 | 工作量 |
|---|---|---|---|
| O-M1 | 文件教用 `sudo` 執行 CLI，但 wrapper 以 root 身分執行。一存檔，config.json 就變成 root:root 0600，服務讀不到，exit 78 無限重啟（已重現）。 | wrapper 偵測到 root 時以 `illumio-ops` 身分重新執行；文件改為 `sudo -u illumio-ops` | S |
| O-M2 | `Restart=always` 沒有設 `RestartPreventExitStatus=78`、啟動次數上限或 `OnFailure`，設定錯誤會每 10 秒重啟一次，永遠不停。 | 補上這三項 | S |
| O-M3 | 沒有不需登入的健康檢查端點，也沒有 systemd watchdog；`status` 指令永遠 exit 0。 | 新增 `/healthz`（scheduler 狀態、最後一次 monitor 週期距今多久、job_health 摘要），加上 `sd_notify` 與 `WatchdogSec` | M |
| O-M4 | 非 purge 解除安裝會刪除 `logs/`（state.json 的 watermark、alert DLQ、alerts.sqlite）和 `reports/`。重裝後，中間那段期間的事件永遠不會被評估。 | 保留狀態檔，或把它們移到 data/ | S |
| O-M5 | 沒有備份與還原工具。狀態放在 logs/ 下；文件只講到快取 DB，而且用的 `sqlite3` CLI 安裝包裡沒有附。 | 新增 `illumio-ops backup create\|restore` 指令（用 SQLite backup API） | M |
| O-M6 | 升級時 `report_config.yaml` 永遠不會更新。例如 e25dfaf 改過的 lateral ports，已安裝的主機收不到。 | 附 `.example`；檔案未被修改過就直接替換，否則寫成 `.new` 並警告 | S–M |
| O-M7 | 打包腳本用黑名單複製 config/，可能把建置主機上殘留的 `tmpXXXX.tmp` 或 `config.json.save`（含密鑰）一起打包（已重現）。 | 改用白名單 | S |
| O-M8 | systemd unit 沒有設定記憶體、task 數或檔案描述元上限。 | 加上 `MemoryHigh`/`MemoryMax` 等 | S |
| O-M9 | 升級時只有服務 `is-active` 才會停止；正在 crash-loop 的服務不算 active，會在半裝好的目錄上被重啟。 | 無條件停止 | S |
| O-M10 | 升級不會修正 UMask 之前就建立的檔案權限。 | 升級時一併修正 | S |

### 低

- **L1：state lock 遇到磁碟滿會殘留**，導致每次寫入都等 10 秒逾時（已重現）。
- **L2：** `logging.rotation`/`retention` 有寫在文件裡，但程式根本沒讀。
- **L3：** 手動產生的報表永遠不會被清理；`alerts.sqlite` 的 retention 預設為永久保留。
- **L4：** 文件與實際不符，共 6 處，例如 `--port` 明明有、`status` 其實不會連 PCE。
- **L5：** `setup.sh` 產生的 unit 檔和權限跟正式版不一致，而且會把 `.git` chown 給服務帳號。
- **L6：** 每次升級都誤顯示「PCE profiles 已移除」。
- **L7：** TLS 換證不是原子操作，key 和 cert 可能不一致，導致啟動無限迴圈。
- **L8：**
  - 缺少 `After=time-sync.target`。
  - journald 裡會出現 ANSI 色碼。
  - 沒有預先 compileall。

---

## 5. 故障注入（C-*）

分析時建了一個可注入故障的假 PCE，分 12 組實驗。

| ID | 故障 | 現在的行為 | 判定 | 修法 | 工作量 |
|---|---|---|---|---|---|
| C-1 | DST 結束 | cron 排程報表觸發約 61 次，每次都寄信。春季跳時那天則整天不跑。改時區會讓存成 naive 的 `last_run` 被重新解讀 | **重複** | 一律用 UTC 比較；`last_run` 存成帶時區的 UTC（`src/report_scheduler.py:383-396`） | S |
| C-2 | state.json 寫入時磁碟滿（cache 模式） | 事件 cursor 已經提交，`save_state` 拋錯，`send_alerts` 被跳過，告警永久遺失 | **資料遺失** | 由 D-1 解決；過渡做法是 cursor 延後到 save 之後才提交 | M（或併入 D-1） |
| C-3 | SIEM 接收端停機 | 同 S-M2 | **無聲遺失** | 同 S-M2/S-M7 | — |
| C-4 | 非同步下載內容格式錯誤或筆數短少 | 壞掉的行只記 debug log 就跳過；短少的結果照收；非 gzip 的 JSON 陣列 fallback 解析錯誤（5 筆只剩 1 筆） | **無聲遺失** | 兩條路徑共用同一個 parser；有任何解析失敗就設定 `last_fetch_error`；與 PCE 回報的 `flows_count` 比對筆數（`traffic_query.py:809-853`、`async_jobs.py:464-491`） | S |
| C-5 | 本機時鐘比 PCE 快 25 分鐘（legacy 事件路徑） | 6 筆事件收到 0 筆 | **資料遺失** | 用 PCE 回應的 `Date` header 量測時鐘偏差並告警；watermark 改以事件時間戳為準 | M |
| C-6 | job 一再失敗或卡住 | 只有 GUI 首頁看得到。`monitor_cycle` 失敗等於全部告警停擺；lag monitor 的門檻是 3 小時警告、6 小時錯誤 | **無聲停擺** | meta-watchdog（獨立 executor），連續 N 次錯誤或逾時就發 ops 告警並 dump stack；每個來源各自的 lag 門檻；systemd watchdog | M |
| C-7 | 對方以極慢速度回傳資料（slow-drip）、`Retry-After` 很大 | 逾時只限制單次 recv：事件 29 秒（期限 10 秒）、webhook 37 秒（期限 10 秒）；`Retry-After` 最多可卡 6 小時 × 3 次 | **卡住** | 每個邏輯呼叫設總期限；`retry_after_max=60` | S–M |
| C-8 | 憑證輪替後回 401/403 | watchdog 說的是「PCE unreachable」；traffic 輪詢遇到 401 會耗滿 900 秒才回報 poll timeout | 降級、訊息錯誤 | 401/403 立即失敗，並使用專屬的告警文字（i18n） | S |
| C-9 | SQLite 鎖定超過 busy_timeout | 被算成 PCE 失敗，watchdog 說「PCE unreachable」；`record_error` 本身也失敗，把原始錯誤蓋掉 | 降級、誤報 | 本機 DB 錯誤與 PCE 錯誤分開分類 | S |
| C-10 | XLSX 寫入時磁碟滿 | `wb.save` 直接寫入目的檔，留下 GUI 會列出的損壞檔案 | 損壞產物 | 先寫暫存檔再 `os.replace` | S |
| C-11 | state.json、config.json 或快取 DB 毀損 | state.json：冷卻、報表排程狀態、DLQ 遺失（造成重複告警或重寄報表）。config.json：執行中的 `monitor_cycle` 與報表 tick 每輪都失敗。快取 DB：靜默改用 deprecated 的 live pull，而且不告警 | **無聲降級** | 保留最後一份正常的 `.bak` 並在毀損時退回使用；繼續用最後一份正常的 config 執行；一律發 ops 告警；不靜默 fallback | S–M |
| C-12 | events 積壓 24 小時，期間有 2% 暫時錯誤 | ingest 是全有或全無，10 輪後 20,000 筆只存進 0 筆 | **livelock** | 依子時間窗逐段提交並推進 watermark（與 traffic ingestor 一致） | M |
| C-13 | collection 回應缺 `X-Total-Count` | 在 500 筆處被靜默截斷 | 可能遺失 | 沒有這個 header 又剛好回 500 筆時，視為可能被截斷 | S |

**沒問題的項目：**

- 無 `Retry-After` 的 429、POST 的 429、events 的 429
- 5xx 重試
- 非同步 job 失敗或逾時
- 下載中途 reset（close-delimited 除外）
- config.json 磁碟滿時仍是原子寫入
- DST 對日／週／月排程沒有影響

**測試框架 `tests/chaos/`：**

- **假 PCE：** threaded HTTP server，可對任一路徑注入狀態碼、延遲、slow-drip、reset、截斷、格式錯誤、時鐘偏移。
- **共用 fixtures：**
  - `fast_time`
  - `cache_db`
  - `db_locked`
  - `enospc`（攔截 os.write）
  - `corrupt`
  - `skewed_clock`
  - `channel_sinks`（假的 SMTP/webhook）
  - `sched_harness`
  - `ops_alerts`
- 新增 `chaos` marker。

前 15 支測試照價值排序，第一支是 C-1。

---

## 6. 測試套件品質（T-*）

| ID | 問題 | 證據 | 修法 | 工作量 |
|---|---|---|---|---|
| T-1 | **改 PCE 的程式碼被改壞也沒有測試會失敗**：16 個手工突變中 9 個存活 | 存活的突變（見下方）。另外 `provision_changes` 只覆蓋 1/21 行，所有寫入 primitive 都被 mock 掉 | 用 `responses` 為 ApiClient 寫入 primitive 寫契約測試（URL、方法、body、狀態碼 → bool）；`ScheduleEngine.check` 寫表格驅動的凍結時間測試；補流量門檻邊界測試；隔離測試斷言 PUT 出去的 label 清單完全正確 | M |
| T-2 | **e2e 大量一次性讀取 DOM**：195 個 `.count()`、114 個 `inner_text()`，只有 27 個 `expect()`；約 33 處固定 `wait_for_timeout`。如果畫面還沒渲染，負向檢查會空泛地通過 | 前面看到的 fleet flake 原因已找到：`[data-route]` 比 `/api/fleet` 資料先出現（`fleet.mjs:623-681`），負載下 29 次失敗 1 次 | 改用 `expect().to_have_count()`/`expect_request`；負向掃描前先斷言畫面已渲染的標記 | M |
| T-3 | `test_actions_rate_limit.py` 一個檔案占全套約 40% 時間（254 秒）：連 DNS 解析不到的 `pce.test`，每次又重試 3 次 | 拿掉這個檔案，全套從 13:45 降到約 6:40 | 重試設 0，並改用 closed-port 技巧，預估降到約 1 秒 | S |
| T-4 | 跟時間有關的測試在特定時刻必定失敗 | 見下方 | 凍結時間，並把斷言改為精確比對 | S |
| T-5 | 測試會寫進工作目錄：`logs/job_health.json`、`data/*`、`reports/snapshots/*`。報表又會讀這些快照，所以可能被前一次執行汙染 | 跑完一次後的 mtime | 新增 autouse 隔離 fixture，並加一支守門測試，確認 repo 內的這些目錄沒被動到 | S |
| T-6 | 錯誤路徑覆蓋不足（src 分支覆蓋率 79%） | `send_scheduled_report_email` 108/109 行未執行；告警外掛的失敗與冷卻路徑；SIEM 重連路徑 | 補測試，並用 `create_autospec` 取代手寫 stub | M |
| T-7 | 自己 mock 自己、套套邏輯、只檢查狀態碼的測試 | 見下方 | 每支逐一加強 | S |
| T-8 | CI 削弱了訊號 | 見下方 | 見下方 | S |
| T-9 | 每支需要登入的測試都要付出 argon2 雜湊約 0.4 秒加登入約 0.45 秒，共約 600 支、8–9 分鐘 CPU；有 16 份重複的 `_login` | | session 範圍共用一次預先算好的雜湊，或測試用低成本參數；統一使用 conftest 的 fixture | S |

T-1 存活的突變：

- 排程 deny 時間窗反轉
- 跨午夜時間窗
- 略過有 draft 的規則
- `provision_changes` 漏掉相依項目
- `toggle_and_provision` 忽略別人的 draft
- `update_workload_labels` 任何狀態碼都當成功
- 隔離時保留了舊等級的 label
- bulk 套用時 label 缺失卻送出 `None`
- 流量告警門檻的 `>=` 改成 `>`

T-4 會在特定時刻失敗的測試：

- `test_rule_scheduler.py:104,149,179`：在 UTC 23:59:xx 必定失敗（已用 freezegun 重現）。
- `test_flow_window_delta.py:543` 等：UTC 午夜後約 10 分鐘內失敗（可能，但沒有完全確認）。

T-7 要加強的測試：

- `test_report_generators_format_parity.py`：mock 掉所有 exporter 之後只斷言 `isinstance(list)`。
- `test_scheduler_integration.py:110`：斷言永遠為真。
- `test_web_security_contracts.py:178,192`、`test_api_settings.py:460`、`test_security_hardening.py:72,80`：寫入之後沒有讀回來驗證。

T-8 CI 的問題與修法：

| 問題 | 修法 |
|---|---|
| 沒有覆蓋率門檻 | 加 `--cov-fail-under` 約 78，之後逐步調高 |
| 沒有 `timeout-minutes` 與 pytest-timeout | 補上 |
| ruff 有安裝但沒有執行 | 在 CI 執行 ruff |
| mypy 只檢查 3 個檔案 | — |
| CI 測 py3.10/3.11，實際出貨的是 **py3.12 + `requirements-offline.lock`**，從來沒測過 | 新增 py3.12 + offline lock 的 job |
| `slow`/`requires_pce` 等 marker 有宣告但沒有任何測試使用 | 啟用 `--strict-markers` |
| 失敗時沒有上傳 Playwright trace | 失敗時上傳 trace |

**沒問題的項目：**

- 隨機順序跑兩次全套：全部通過。
- 28 個含 sleep 的單元測試檔在 CPU 滿載下跑 15 次：2580/2580 通過。
- conftest 對 state、i18n、alert store 的隔離有效。

---

## 7. 需要你決定的事

| # | 問題 | 選項 | 建議 |
|---|---|---|---|
| D1 | 預設帳密 `illumio/illumio` + `0.0.0.0` + 白名單空白 + 強制改密碼關閉（O-H5） | (a) 重新開啟強制改密碼<br>(b) 安裝時產生隨機初始密碼，寫入只有 root 能讀的檔案<br>(c) 改密碼前只綁 127.0.0.1<br>(d) 維持現狀 | (b)，再加 (a) |
| D2 | `cef_pce` 不跳脫 `=`/`\`（S-M6） | (a) 預設改用 arcsight 方言，graylog 方言改為可選<br>(b) 保留 graylog 方言但至少跳脫 `=`，並在文件中說明取捨<br>(c) 維持與 PCE 一致，只補文件 | (b) |
| D3 | SIEM DLQ 策略（S-M2） | (a) 改為時間到期（例如 7 天），目的地停機不消耗重試<br>(b) 維持次數上限，但停機期間不計數 | (a) |
| D4 | TCP syslog 的可靠性上限（S-M5） | (a) 修 S-H1 後接受「TCP 無應用層 ACK」的限制，並在文件中說明<br>(b) 另外支援 RELP | (a)，RELP 列為日後選項 |
| D5 | 告警 outbox 讓派送與分析週期分離（D-1） | (a) 接受：送出時間可能比分析晚幾秒，inbox 會顯示「待送」<br>(b) 先只做過渡方案 | (a) |
| D6 | session 撤銷需要升級後重新登入一次（D-6） | (a) 接受<br>(b) 延後 | (a) |
| D7 | 設定向前相容（O-H4）：未知鍵改為警告並忽略 | (a) 全部區段都這樣處理<br>(b) 只處理會造成 exit 78 的區段 | (a) |
| D8 | 真實 PCE 驗證 V-A | 需要你提供 lab 主機的存取方式與唯讀 API key，或由你在 lab 執行我提供的腳本 | — |

---

## 8. 執行計畫

原則：

- **先修會遺失或重複資料、而且改動小的**，再處理規模，最後處理維運與流程。
- 每個 PR：
  1. 先把重現腳本移植成會失敗的測試，再修到通過；
  2. 跑全套測試、coverage_live、i18n 稽核、mypy、naive datetime 與文件連結檢查；
  3. CI 綠燈後合併。
- T 系列（測試品質）不獨立成批，而是分散到各批：哪一批動到哪個區域，就順便補該區域的測試。

### 批次 R4-1：資料正確性急修（約 3–4 天）

不需要決策、改動小、風險低。

- **C-1：** DST 時 cron 報表重複觸發。
- **SIEM：**
  - S-H1 + S-M5：中途重連與未讀資料標為「未確認」。
  - S-H2：HEC 認證錯誤改為目的地層級。
  - S-H3：CLI SIEM 選單與目的地名稱唯一性。
  - S-H5：刪除或改名後的孤兒待送列。
  - S-H6：backfill 分批 commit。
  - S-M8：HEC 的 `Retry-After` 上限。
- **故障處理：**
  - C-4：下載解析錯誤或筆數短少要報錯。
  - C-8：401/403 立即失敗並使用正確訊息。
  - C-9：本機 DB 錯誤不算 PCE 失敗。
  - C-10：XLSX 原子寫入。
  - C-13：缺 `X-Total-Count` 時的截斷判斷。
- **安裝與維運：**
  - O-H1：降版守門。
  - O-H3：刪除就地覆寫 config。
  - O-M2：限制 systemd 重啟。
  - O-M7：打包白名單。
  - O-M9：無條件停止服務。
  - O-L1：state lock 殘留。
- **測試：**
  - T-3：rate limit 測試提速。
  - T-4：時間相關測試。
  - T-2：先修 fleet flake。
- **驗收：**
  - 每項都有一支先紅後綠的測試。
  - SIEM 的 7 個重現腳本全部轉成測試。

### 批次 R4-2：告警可靠性與無聲停擺（約 1.5–2 週）

- **D-1 告警 outbox，加上 D-2 每個通道各自重試：**
  - 分兩個 PR。
  - 一併涵蓋 C-2 與 W0、W2 遺失時間窗。
- **C-6 meta-watchdog：**
  - job 連續錯誤或卡住時發 ops 告警。
  - 每個來源各自的 lag 門檻。
- **C-11：** 毀損的 state/config/DB 退回最後一份正常的版本，並發 ops 告警。
- **C-7：** 為 PCE 呼叫與告警通道設總期限，並限制 `Retry-After`。
- **C-12：** events 依子時間窗逐段提交。
- **C-5：** 量測時鐘偏差並告警，legacy watermark 改用事件時間戳。
- **測試：** 建立 `tests/chaos/` 測試框架，並完成前 15 支測試。
- **驗收：**
  - kill -9 子程序測試中，每則告警都至少送達每個通道一次。
  - 下一輪不會重複告警。

### 批次 R4-3：SIEM 規模與可觀測性（約 1–1.5 週）

- S-H4：HEC 批次送與 high-water mark。
- S-H7：精簡索引並提早刪除 sent 列。
- S-M1：mark-sent 重試。
- S-M2：目的地層級退避與時間到期，依 D3 決定。
- S-M3：複合索引。
- S-M4：lease 加唯一索引。
- S-M6：依 D2 決定的跳脫方式。
- S-M7：`last_error`/`last_success`、延遲與目的地停機告警。
- S-M9：補齊 `mask_pii`。
- S-低：其餘 SIEM 低優先項目。
- **驗收：**
  - 每天 500 萬筆的模擬下 HEC 能跟上。
  - safety-net 每個 tick < 1 秒。
  - 停機 6 小時後 DLQ 為 0，且維持 FIFO。

### 批次 R4-4：快取規模（約 1.5–2 週）

- D-3：ingest 用 executemany 並縮小持鎖範圍。
- D-5A：移除每輪 1 萬列上限，改用 keyset 分頁。
- D-4：aggregator 按日切分、retention 按 batch 持鎖、空間回收。
- D-5B：在 SQL 中評估流量規則，先以 shadow 模式跑一個版本。
- **驗收：**
  - ingest 時 raw/obs/siem 三張表與舊版逐欄相同。
  - 隨機產生資料的差分測試中，SQL 與 Python 的觸發結果一致。
  - 每天 500 萬筆時，每輪 < 5 秒。

### 批次 R4-5：安裝、升級與維運（約 1–1.5 週）

- O-H2：原子升級與回滾。
- O-H4：設定向前相容，依 D7 決定。
- O-M1：CLI 以服務帳號執行。
- O-M3：`/healthz` 與 systemd watchdog。
- O-M4：解除安裝時保留狀態。
- O-M5：備份與還原指令。
- O-M6：`report_config.yaml` 隨升級更新。
- O-M8：資源上限。
- O-M10：修正舊檔案權限。
- O-L2～L8：其餘低優先項目。
- **測試：** 把用假安裝包跑的 install/upgrade/failed-upgrade/uninstall 流程，做成真正會執行的測試，取代現在只比對字串的契約測試。

### 批次 R4-6：登入與 session（約 3–4 天）

- O-H5：依 D1 決定。
- D-6：server-side session registry 加上 epoch。

### 批次 R4-7：測試與 CI 補強（約 1 週，與 R4-2 之後各批並行）

- T-1：PCE 寫入的契約測試與 ScheduleEngine 表格測試；目標是 16 個突變全部被測試抓到。
- T-2：其餘 e2e 改用 `expect()`。
- T-5：工作目錄隔離。
- T-6：補錯誤路徑測試。
- T-7：加強弱測試。
- T-8：覆蓋率門檻、timeout、ruff、py3.12 + offline lock 的 job。
- T-9：登入 fixture 提速。

### 驗證 V-A：真實 PCE（R4-1 之後、你方便時）

依 §2 的步驟進行，結果寫成一份比對報告。發現的差異列為新的修正項目。

### 預估總工作量

- 約 7–9 週。其中 R4-1 最急，也最便宜。
- 每批結束時，在 CHANGELOG 的 `[Unreleased]` 記錄行為變更與已知限制。

---

## 附錄：分析資料來源

- SIEM：一份完整 review，加上對 7 項高優先發現的獨立對抗式重現。
- 可靠性遺留：設計與原型。ingest/aggregate/vacuum 有實測數字與輸出比對。
- 安裝升級：用假的離線安裝包，實際跑過安裝、升級、失敗升級、解除安裝、磁碟滿等流程。
- 故障注入：假 PCE 加 12 組實驗。
- 測試品質：
  - 全套加分支覆蓋率；
  - 兩個隨機 seed 的隨機順序執行；
  - e2e 在負載下重複執行；
  - 16 個手工突變；
  - 跨時段的時鐘偏移測試。
- 真實 PCE：透過 Illumio LAB MCP 唯讀查詢，確認可連線並取得資料樣本。
