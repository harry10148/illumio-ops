---
title: SIEM 轉送
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/siem/dispatcher.py
  - src/siem/dlq.py
  - src/siem/formatters/cef.py
  - src/siem/formatters/normalized_json.py
  - src/siem/formatters/syslog_wrapped.py
  - src/siem/formatters/syslog_header.py
  - src/siem/mask.py
  - src/siem_cli.py
  - src/cli/siem.py
  - src/config_models.py
  - src/pce_cache/health.py
  - src/gui/routes/dashboard.py
---

# SIEM 轉送

illumio-ops 可將 PCE audit events 與 traffic 摘要轉送到任意 syslog 相容 SIEM、Splunk HEC，或本地 JSON sink。轉送具備持久性：事件先進入本地 SQLite 派送佇列（`siem_dispatch` 表，與 pce_cache 共用資料庫，見 [cache-maintenance.md](cache-maintenance.md)），失敗會依退避策略重試，超過重試上限後移入 **DLQ（dead-letter queue，死信佇列）**。

> **狀態提示**：SIEM 轉送為正式功能。舊版（2026-07-17 之前）啟動時會記一條「SIEM forwarder is PREVIEW」的 warning——該提示與其 `src/siem/preview.py` 模組已移除；升級後啟動記錄不會再出現此警告，若仍看到即代表跑的是舊版程式。

SIEM 轉送依賴 pce_cache（見 [cache-maintenance.md](cache-maintenance.md)）：`siem_dispatch`／`dead_letter` 兩張表都存在 cache 資料庫中，`pce_cache.enabled=false` 時 SIEM 轉送無從運作。

---

## 1. Destination 設定

透過 Web GUI（Integrations → SIEM → Add destination，見 [gui-tour.md](gui-tour.md)）或直接編輯 `config.json › siem.destinations` 新增目的地。完整欄位表（型別／預設值／說明）見 [configuration.md](configuration.md) 的「siem（SIEM 轉送）」一節；本節只列出決定行為的兩組列舉。

### 1.1 Transport（傳輸協定）

| `transport` | 協定 | 預設埠 | 備註 |
|---|---|---|---|
| `udp` | Syslog UDP | 514 | 無傳遞保證，簡單快速 |
| `tcp` | Syslog TCP | 514 | 有序、可靠傳遞，自動重連 |
| `tls` | Syslog TCP + TLS | 6514 | `tls_verify`／`tls_ca_bundle` 控制憑證驗證；`profile="production"` 時禁止 `tls_verify=false`（載入時直接拒絕） |
| `hec` | Splunk HTTP Event Collector | 8088 | 僅 HTTPS，需 `hec_token` |

### 1.2 Format（輸出格式）

| `format` | 內容 | 適用對象 |
|---|---|---|
| `cef` | ArcSight CEF 0.1 單行（`CEF:0\|Illumio\|PCE\|3.11\|<event_type>\|<event_type>\|<severity>\|<extension>`） | ArcSight、QRadar |
| `syslog_cef` | 同上，外層包一層 RFC5424 syslog header | 需要 RFC5424 framing 的 syslog 伺服器 |
| `json` | 扁平 JSON，使用 Illumio 官方欄位名稱（`NormalizedJSONFormatter`） | Splunk HEC、Elastic、Logstash、檔案 sink |
| `syslog_json` | 同上 JSON，外層包一層 RFC5424 header | rsyslog／syslog-ng（`mmjsonparse`） |

`syslog_cef`／`syslog_json` 的 RFC5424 header 由 `wrap_rfc5424()` 產生，格式為 `<PRI>1 TIMESTAMP HOSTNAME illumio-ops - - - MSG`；`HOSTNAME` 取事件的 `pce_fqdn`，traffic 記錄沒有 `pce_fqdn` 時退回轉送端主機名稱 `illumio-ops`。CEF 的 severity 對照：`info`→3、`warning`/`warn`→6、`error`/`err`→8、`critical`/`crit`→10；syslog header 的 severity 另有一套對照（`info`→6、`warning`→4、`error`→3、`critical`→2）。

### 1.3 設定範例

```json
{
  "name": "splunk-prod",
  "enabled": true,
  "transport": "hec",
  "format": "json",
  "host": "splunk.example.com",
  "port": 8088,
  "profile": "production",
  "tls_verify": true,
  "tls_ca_bundle": null,
  "hec_token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "batch_size": 100,
  "source_types": ["audit", "traffic"],
  "max_retries": 10,
  "mask_pii": false
}
```

- `source_types`：`audit`（PCE audit events，來源表 `pce_events`）、`traffic`（traffic 摘要，來源表 `pce_traffic_flows_raw`），可只選一種或兩種都要。
- `mask_pii`：`true` 時在格式化前遮蔽下列欄位（逐目的地獨立設定，可讓內部 SOC 收全量、外部 SaaS SIEM 只收遮蔽後的資料）：
  - PCE audit event：`created_by.user.username`（管理者帳號/email）、`action.src_ip`（管理者來源 IP）、`resource_changes[].changes[*].{before,after}`（可能帶內部專案名稱的文字）、`actor`/`source_ip`（標準化事件的頂層欄位）
  - Traffic flow：`service.user_name`/`service.process_name`（連線相關的 OS 使用者與行程名稱；格式化時同步寫入平坦版 `un`/`pn`）
- 舊版設定的 `endpoint`（`"host:port"` 或 HEC URL 字串）在載入時會自動遷移成 `host`＋`port`，不需手動轉換。

---

## 2. 佇列與重試語意

### 2.1 Enqueue（入列）時機

Ingestor（`src/pce_cache/ingestor_events.py`、`ingestor_traffic.py`）在把一筆事件／流量寫入 cache 的**同一個 SQL 交易**內，為每個符合 `source_types` 的啟用目的地各新增一列 `siem_dispatch`（`status="pending"`）。這保證「cache 有這筆資料」與「SIEM 佇列已排入」不會出現不一致的中間態——寫入成功即代表兩者都成立，或都不成立（交易回滾）。

`enqueue_new_records()`（`src/siem/dispatcher.py`）是安全網式的補登：每個 `siem_dispatch` tick 都會執行一次，正常情況下應該找不到東西可補（因為 ingest 已經 inline enqueue）。它存在的目的是覆蓋三種情境：(a) 目的地是後來才新增／啟用的，該 source_type 的歷史列從未排入過；(b) 程序崩潰造成 inline enqueue 未完成；(c) 操作者手動要求補跑。判斷範圍以 `(source_table, source_id, destination)` 三元組為準，不會漏掉「已排給 A 目的地，但缺 B 目的地」的列，也不會重複排入已存在的 pair。

### 2.2 派送與重試

派送由 `siem_dispatch` 排程 job 驅動（每個啟用的目的地各自一個 `DestinationDispatcher`），間隔為 `siem.dispatch_tick_seconds`（預設 **30 秒**；`config.json.example` 範本示範較密集的 5 秒，兩者是不同用途，實際生效值以自己 `config.json` 內的設定為準）。每個 tick：

1. 取出該目的地至多 `batch_size`（預設 100）筆 `status="pending"` 且到了重試時間（`next_attempt_at` 為空或已過期）的列，依 `queued_at` 排序。
2. 逐筆格式化並透過 transport 送出。
3. 送出失敗：重試次數 `retries += 1`。若未達 `max_retries`（預設 10）：以指數退避排定下次嘗試時間，公式為 `min(2^retries × 5, 3600)` 秒（例如第 1 次失敗後 10 秒重試，第 5 次失敗後約 160 秒，封頂 1 小時）。若已達 `max_retries`：這筆記錄移入 DLQ，`siem_dispatch` 列標記 `status="failed"`。
4. 送出成功的列在同一個 tick 結束時，以單一交易批次標記 `status="sent"`（而非逐筆 commit）。

**at-least-once 語意（刻意取捨）**：若程序在「已成功送出至 transport」與「標記為 sent 的 commit」之間崩潰，下一輪會重送同一筆記錄，SIEM 端可能收到重複事件。這是刻意的設計取捨——SIEM 轉送本質上就是 at-least-once（網路層面同樣可能重複），為了避免逐筆 commit 造成的鎖爭用（會與 ingest 寫入互撞），改為批次 commit 換取較寬的重複交付窗口。

### 2.3 進入 DLQ 的兩種路徑

除了重試耗盡（見上），還有一種立即進 DLQ 的情況：**payload 組裝失敗**（例如來源列在 cache 中已被 retention 清除、或 `raw_json` 解析失敗）。這種情況不會計入重試次數，而是直接以 `last_error` 設為固定字串 `payload_build_failed` 進 DLQ，確保被丟棄的事件仍可被檢視與重送，而不是無聲消失。

---

## 3. DLQ 三命令

DLQ 相關操作走 `illumio-ops siem` 子命令，資料庫連線失敗、schema 不符等例外一律回報並以非零碼結束（不會用 0 筆數假裝正常）。三個命令都需要 `--dest <目的地名稱>`。

### 3.1 `illumio-ops siem dlq` — 列出 DLQ 項目

```bash
illumio-ops siem dlq --dest splunk-prod --limit 20
```

輸出（依 `quarantined_at` 由新到舊排序，逾 60 字的錯誤訊息會截斷）：

```
                              DLQ — splunk-prod
┌─────┬────────────────────────┬─────────┬──────────────────────────────┬─────────────────────┐
│  ID │ Source                 │ Retries │ Error                        │ Quarantined At       │
├─────┼────────────────────────┼─────────┼──────────────────────────────┼─────────────────────┤
│  42 │ pce_events             │      10 │ ConnectionRefusedError: [Er… │ 2026-07-16 09:12:03  │
│  41 │ pce_traffic_flows_raw  │      10 │ TimeoutError: HEC endpoint … │ 2026-07-16 08:47:19  │
└─────┴────────────────────────┴─────────┴──────────────────────────────┴─────────────────────┘
```

目的地當下沒有 DLQ 項目時，改印出「'{dest}' 無 DLQ 項目」（黃色），不印表格。`--json` 模式回傳陣列，每筆含 `id`／`source_table`／`retries`／`last_error`／`quarantined_at`（不截斷）。

### 3.2 `illumio-ops siem replay` — 重新排入派送佇列

```bash
illumio-ops siem replay --dest splunk-prod --limit 100
```

輸出：

```
Requeued 12 entries for 'splunk-prod'
```

行為：依 `--limit`（預設 100）取出該目的地最新的 DLQ 項目，各自新建一列 `siem_dispatch`（`status="pending"`、`retries=0`），並在**同一個交易**內刪除對應的 DLQ 列。刪除與重新入列在同一交易完成，是為了避免同一筆記錄被重送兩次（例如指令執行到一半中斷再重跑）。

> **命令層級 vs GUI 選單層級的差異**：CLI 的 `siem replay` 是以「目的地 + 筆數上限」為單位的批次操作，沒有逐筆挑選功能。互動式選單（`illumio-ops.py` 的 SIEM 選單 → DLQ management，`src/siem_cli.py`）額外支援輸入特定 DLQ id 清單做逐筆 replay／purge，適合只想重送/清除少數幾筆的場景；GUI 的 Integrations → DLQ 頁面同樣支援勾選特定項目重送。

若快取資料庫尚未初始化（例如尚未有任何派送記錄），會回報「無 SIEM 資料可重送」並以非零碼結束。

### 3.3 `illumio-ops siem purge` — 刪除過期 DLQ 項目

```bash
illumio-ops siem purge --dest splunk-prod --older-than 30
```

輸出：

```
Purged 87 DLQ entries for 'splunk-prod'
```

行為：刪除該目的地 `quarantined_at` 早於「現在 − `--older-than` 天」（預設 30 天）的 DLQ 列，**永久刪除、不可還原**。另外 `dlq_max_per_dest`（預設 10000）自 2026-07-17 起實際生效：每次寫入 DLQ（`_quarantine()`）後若該目的地筆數超過上限，**最舊的項目會被自動刪除**（ring-buffer 語意，同交易內完成並記 warning 日誌）——持續失敗的目的地不會再讓 `dead_letter` 表無上限成長。`purge` 仍是手動批次刪除的手段；要清空整個目的地的 DLQ，可用 `--older-than 0`（等同「早於現在」，涵蓋全部既有項目）。

> `illumio-ops siem` 底下沒有手動清空佇列（flush）用的子命令——派送本身由 `siem_dispatch` job 依 tick 間隔自動排空佇列，不需要、也不存在這種手動動作；DLQ 的手動出口只有 `replay`（送回去）與 `purge`（丟掉）兩種。

---

## 4. 健康判讀

Integrations Overview（`src/gui/routes/dashboard.py` 的 `_overview_pipeline()`）與 `illumio-ops siem status` 共用同一套判定邏輯（`src/pce_cache/health.py` 的 `pipeline_verdict()`），三個等級：

| 等級 | 觸發條件（任一成立） |
|---|---|
| `error` | 任一來源 cache lag 達 error 等級；近 1 小時 SIEM 成功率 < 95%（有分母時）；DLQ 筆數 ≥ `dlq_cap × 0.8`（`dlq_cap` 預設 10000，即 ≥ 8000） |
| `warn` | 任一來源 cache lag 達 warning 等級；近 1 小時 SIEM 成功率 95%–99%（有分母時）；DLQ 筆數 > 0；**或 `siem_idle=true`** |
| `ok` | 以上皆不成立 |

> 此判定只在 `pce_cache.enabled=true` 時計算；`pce_cache` 未啟用時整體管線判讀回傳 `no_cache`，不會計算 `siem_idle`（因為 SIEM 本身也依賴 cache 資料庫，見本文件開頭）。

### 4.1 `siem_idle`：SIEM 已啟用但空轉

`siem_idle` 代表「`siem.enabled=true`，但轉送實際上沒有在動」，有兩種成因，判定邏輯完全不同：

**成因一：沒有任何啟用中的目的地。** `siem.enabled=true` 但 `destinations` 清單為空，或全部目的地的 `enabled` 都是 `false`。這種情況不需要看任何資料就能判定為 `siem_idle=true`——設定本身就不完整。

- **處置**：到 Integrations → SIEM（見 [gui-tour.md](gui-tour.md)）或 `config.json › siem.destinations` 檢查是否漏了新增目的地，或目的地是否被誤停用。

**成因二：有啟用中的目的地，但近 24 小時完全沒有新記錄排入佇列，而來源端明顯有資料在流動。** 判定條件是「近 24 小時 `siem_dispatch.queued_at` 計數為 0」**且**「至少一個 cache 來源（events／traffic）的 lag 資訊非 `None`，代表 ingest 確實在收資料」。兩個條件同時成立才算 `siem_idle`——如果 PCE 本來就沒有新事件/流量，佇列自然是空的，這不算異常（`denom=0` 的「沒有流量」與「壞掉了、沒在送」必須能區分，這正是 2026-07-16 修掉的一個假綠燈問題，見 CHANGELOG）。

- **處置**：先確認 ingest 是否真的有在寫入 cache（`illumio-ops cache status`，見 cache-maintenance.md）。若 ingest 正常但 enqueue 沒有發生，檢查對應目的地的 `source_types` 是否涵蓋目前有資料的來源（例如目的地只設了 `["audit"]`，但近期只有 traffic 流量，這不算異常，是設定選擇）；若 `source_types` 設定正確仍無記錄，檢查 `siem_dispatch` 排程 job 是否真的在跑（Integrations Overview 的 Job Health 表格，或 `logs/job_health.json`，見 [automation.md](automation.md)）。`enqueue_new_records()` 安全網補登理論上會在下個 tick 自行補上缺漏，若持續空轉，代表 job 本身沒有被觸發，而不是資料層面的問題。

`siem_idle=true` 只會把整體判讀壓到 `warn`（不會單獨觸發 `error`），與 DLQ 筆數 > 0、cache lag 到達 warning 等級同一層級。

---

## 延伸閱讀

- 設定鍵完整表格（型別／預設值／說明）：[configuration.md](configuration.md)
- GUI Integrations 頁面的 SIEM／DLQ 子頁操作：[gui-tour.md](gui-tour.md)
- `siem_dispatch` 排程 job 的完整 job 清單與 Job Health 判讀：[automation.md](automation.md)
- pce_cache 架構、ingest／retention／容量規劃：見 [cache-maintenance.md](cache-maintenance.md)
- 常見故障排除（連線失敗、憑證問題、佇列積壓）：見 [troubleshooting.md](troubleshooting.md)
- 模組地圖與「為什麼 SIEM enqueue 與 cache 寫入同交易」的設計決策：[architecture.md](../handover/architecture.md)
