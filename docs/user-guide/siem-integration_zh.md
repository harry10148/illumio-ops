---
title: SIEM Integration
audience: [operator, security]
last_verified: 2026-05-15
verified_against:
  - src/siem/
  - src/siem/formatters/
  - src/siem/transports/
  - python illumio-ops.py siem --help
  - python illumio-ops.py siem status --help
  - commit c792c93
related_docs:
  - ../architecture/siem-pipeline.md
  - alerts-and-quarantine.md
  - tls-and-certificates.md
  - ../reference/rest-api.md
---

> 🌐 **[English](siem-integration.md)** | **[繁體中文](siem-integration_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › SIEM 整合
> 🔍 最後驗證 **2026-05-15** 對 commit `c792c93` — 詳見 frontmatter

# SIEM 整合

illumio-ops 可將 PCE 稽核事件與流量記錄轉發至任何相容 syslog 的 SIEM、透過
HTTP Event Collector (HEC) 轉發至 Splunk，或寫入本機 JSON sink 檔案。
轉發具備持久性：事件會排入本機 SQLite 派送佇列，並以退避重試方式重發，直到
進入死信佇列 (DLQ) 為止。

---

## 支援的目的地

共有四種傳輸協定可用，已在 `src/siem/transports/` 中驗證：

| Transport 鍵 | 模組 | 協定 | 預設埠 | 說明 |
|---|---|---|---|---|
| `udp` | `syslog_udp.py` | Syslog UDP | 514 | 低額外負擔；無傳遞保證 |
| `tcp` | `syslog_tcp.py` | Syslog TCP | 514 | 持久連線；自動重連 |
| `tls` | `syslog_tls.py` | Syslog TCP + TLS | 6514 | TLS 1.2+；支援自訂 CA bundle |
| `hec` | `splunk_hec.py` | Splunk HTTP Event Collector (HTTPS) | 8088 | JSON 由 Splunk 原生自動索引 |

> **注意：** 不支援純 HTTP HEC 傳輸。`hec` 傳輸一律透過 HTTPS (`https://host:port`)
> 連線。`tls_verify: false` 僅限開發環境使用。

---

## 設定目的地

### 透過 Web UI

1. 前往 **Settings → Integrations → SIEM**。
2. 點擊 **Add destination** 開啟目的地 modal。
3. 填寫欄位：
   - **Name** — 唯一標籤（1–64 字元）。
   - **Transport** — `udp`、`tcp`、`tls` 或 `hec`。
   - **Host** 與 **Port** — 分開輸入（post-redesign UX，commit `7035f50`）。
     syslog 預設埠為 `514`，HEC 為 `8088`。
   - **Format** — 參見 [Formatter 選擇](#formatter-選擇)。
   - **HEC Token** — 傳輸為 `hec` 時必填。
   - **TLS 選項** — 傳輸為 `tls` 時顯示；參見
     [syslog 的 TLS 設定](#syslog-的-tls-設定)。
   - **Source types** — `audit`、`traffic` 或兩者皆選。
4. 點擊 **Save**，再使用 **Test** 按鈕發送合成 `siem.test` 事件驗證連線。

### 透過 CLI / 設定檔

目的地儲存於 `config/config.json` 的 `siem.destinations` 底下。
完整欄位結構（已對照 `src/config_models.py` 驗證）：

```json
{
  "name":          "splunk-prod",
  "transport":     "hec",
  "format":        "json",
  "host":          "splunk.example.com",
  "port":          8088,
  "hec_token":     "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tls_verify":    true,
  "tls_ca_bundle": null,
  "batch_size":    100,
  "source_types":  ["audit", "traffic"],
  "max_retries":   10
}
```

**欄位說明：**

| 欄位 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `name` | string | 必填 | 唯一識別碼 |
| `transport` | `udp`\|`tcp`\|`tls`\|`hec` | `udp` | 傳輸協定 |
| `format` | `cef`\|`json`\|`syslog_cef`\|`syslog_json` | `cef` | 日誌行格式 |
| `host` | string | 必填 | 目的地主機名稱或 IP |
| `port` | int (1–65535) | `514` | 目的地埠 |
| `tls_verify` | bool | `true` | 驗證 TLS 憑證 |
| `tls_ca_bundle` | string\|null | `null` | 自訂 CA bundle 路徑 |
| `hec_token` | string\|null | `null` | Splunk HEC token（`hec` 必填） |
| `batch_size` | int (1–10000) | `100` | 每次派送 tick 的列數 |
| `source_types` | list | `["audit","traffic"]` | 轉發的資料種類 |
| `max_retries` | int | `10` | 進入 DLQ 前的重試次數 |

> **舊版遷移：** 若設定仍使用單一 `endpoint: "host:port"` 欄位，model
> validator 會在載入時自動拆分為 `host` + `port`。

---

## 轉發的事件類型

兩個來源資料表會饋入 SIEM 派送佇列（已在 `src/siem/dispatcher.py` 中驗證）：

| `source_types` 值 | 來源資料表 | 內容 |
|---|---|---|
| `audit` | `pce_events` | PCE 稽核日誌 — 政策變更、登入事件、API 呼叫、工作負載操作 |
| `traffic` | `pce_traffic_flows_raw` | 流量摘要 — 來源/目的地 IP、埠、協定、政策決定 |

每當 ingestor 寫入新的快取列時，事件即會同步排入佇列。啟動時亦有安全補全
掃描，以補抓 ingestor 遺漏的列。

派送器每 5 秒執行一次（`siem.dispatch_tick_seconds`）。持續傳輸失敗時，
列會重試至多 `max_retries` 次，再移入死信佇列 (DLQ)。

> **交叉參考：** 完整的每事件類型欄位結構，請參見
> [SIEM Pipeline — 架構](../architecture/siem-pipeline.md)（B2 交付物）。
> 觸發隔離的事件記載於 [Alerts & Quarantine](alerts-and-quarantine.md)。

---

## Formatter 選擇

支援四種 format 值，已在 `src/siem/formatters/` 中驗證：

| `format` 值 | 類別 | 輸出 | 最適用於 |
|---|---|---|---|
| `cef` | `CEFFormatter` (`cef.py`) | ArcSight CEF 0.1 — 每事件一行 | ArcSight、QRadar、任何支援 CEF 的 SIEM |
| `syslog_cef` | `SyslogWrappedFormatter(CEFFormatter())` | CEF 行加上 RFC5424 syslog 標頭 | 需要 RFC5424 框架包覆 CEF 的 syslog 伺服器 |
| `json` | `NormalizedJSONFormatter` (`normalized_json.py`) | 扁平 JSON 物件 — 官方 Illumio 欄位名稱，無巢狀鍵 | Splunk HEC（自動索引）、Elastic、Logstash、檔案 sink |
| `syslog_json` | `SyslogWrappedFormatter(NormalizedJSONFormatter())` | 扁平 JSON 包覆於 RFC5424 syslog 標頭中 | 期望 RFC5424 + JSON 本體的 rsyslog / syslog-ng 接收端 |

**使用時機：**

- 當 SIEM 有原生 CEF 解析器時（ArcSight、QRadar、Splunk `syslog` sourcetype
  搭配 `TRANSFORMS-cef`），使用 **`cef`**。
- 當 syslog 接收端需要 RFC5424 `<priority>VERSION TIMESTAMP HOSTNAME APPNAME`
  標頭出現在 CEF 行之前時，使用 **`syslog_cef`**。
- Splunk 搭配 `hec` 傳輸時，使用 **`json`** — HEC 傳輸會自動偵測 JSON
  payload 並以結構化物件傳送，所有欄位無需 `spath` 即可原生索引。
- rsyslog 或 syslog-ng 管線接受 RFC5424 框架內 JSON 本體時（如 `mmjsonparse`
  模組），使用 **`syslog_json`**。

**RFC5424 嚴重性對映**（實作於 `syslog_wrapped.py`）：

| 事件嚴重性 | Syslog 數值 |
|---|---|
| `info` | 6 |
| `warning` / `warn` | 4 |
| `error` / `err` | 3 |
| `critical` / `crit` | 2 |

**範例輸出 — CEF 稽核事件：**
```
CEF:0|Illumio|PCE|3.11|policy.update|policy.update|3|rt=1745049600000 dvchost=pce.example.com externalId=uuid-abc outcome=success
```

**範例輸出 — RFC5424 syslog 封裝：**
```
<14>1 2026-04-19T10:00:00.000Z pce.example.com illumio-ops - - - CEF:0|Illumio|PCE|...
```

---

## syslog 的 TLS 設定

使用 transport `tls` 進行加密 syslog 傳遞。TLS 傳輸
（`src/siem/transports/syslog_tls.py`）使用 Python 的
`ssl.create_default_context()` 包覆 TCP socket。

**設定欄位：**

| 欄位 | 用途 |
|---|---|
| `tls_verify: true` | *（預設）* 驗證伺服器憑證鏈與主機名稱 |
| `tls_verify: false` | 停用憑證驗證 — **僅限開發 / 實驗室環境** |
| `tls_ca_bundle: "/path/to/ca.pem"` | 載入自訂 CA bundle（私有 PKI 用） |

**範例目的地（syslog TLS 至 Graylog）：**
```json
{
  "name":          "graylog-tls",
  "transport":     "tls",
  "format":        "syslog_cef",
  "host":          "graylog.corp.example.com",
  "port":          6514,
  "tls_verify":    true,
  "tls_ca_bundle": "/etc/illumio-ops/ca-bundle.pem"
}
```

**重連行為：** TLS 傳輸維持持久連線。發生 `BrokenPipeError`、
`ConnectionResetError` 或 `SSLError` 時，會自動關閉並重新建立 socket，
再重試失敗的傳送。

憑證簽發與輪換，請參見 [TLS & Certificates](tls-and-certificates.md)。

---

## 測試與狀態

### 測試目的地

在真實事件排入佇列之前，先發送合成 `siem.test` 事件驗證連線：

```bash
illumio-ops siem test <destination-name>
# 例如
illumio-ops siem test splunk-prod
```

tester 會建立已設定的 formatter + transport，發送最小化 `siem.test` 事件，
並以毫秒回報延遲。失敗時輸出非零結束碼與錯誤訊息。

### 查看派送狀態

```bash
illumio-ops siem status
```

顯示每個目的地的待處理 / 已傳送 / 失敗計數與 DLQ 深度。目的地集合為
(a) `cm.models.siem.destinations` 中已設定的目的地，與 (b) `SiemDispatch`
DB 資料表中曾出現的目的地的聯集 — 對齊 WebUI Integrations 分頁的合併視圖
（UX Review §11.2，commits `d217646` / `4577c7b`）。

**空狀態提示：** 若未設定任何目的地且派送資料表為空，指令會顯示設定提示，
而非空白表格（於 `4577c7b` 中還原）。

### 管理死信佇列

```bash
illumio-ops siem dlq    --dest <name> [--limit N]       # 列出 DLQ 條目
illumio-ops siem replay --dest <name> [--limit N]       # 重新排入待處理
illumio-ops siem purge  --dest <name> [--older-than N]  # 刪除（預設 30 天）
```

> **注意：** 沒有 `siem flush` 子指令。派送器在 tick 間隔（預設 5 秒）內
> 自動排空佇列。

---

## 合規與稽核轉發

本節為安全 / 合規稽核員的入口（依 `docs/INDEX.md` §Security）。

當 `source_types` 包含 `"audit"` 時，所有 PCE 稽核事件（`event_type:
policy.update`、登入事件、API 呼叫、工作負載狀態變更等）均會轉發。
合規用途的關鍵屬性：

- **防竄改傳遞：** 事件在傳送前先寫入本機派送佇列。若傳輸失敗，
  最多重試 `max_retries` 次再移入 DLQ — 不會無聲丟棄。
- **事件識別：** 每筆轉發的稽核事件均帶有 `pce_event_id`（使用原始 PCE
  JSON 格式時，回退為 `uuid` 再回退為 `href`）。
- **操作者歸因：** `suser` / `created_by` 欄位識別觸發每筆事件的使用者或
  服務帳號。
- **時間戳記：** 每筆事件均有 ISO-8601 UTC 時間戳記。

**合規轉發建議設定：**
```json
{
  "name":         "audit-siem",
  "transport":    "tls",
  "format":       "syslog_cef",
  "host":         "siem.corp.example.com",
  "port":         6514,
  "tls_verify":   true,
  "source_types": ["audit"],
  "max_retries":  10
}
```

> 完整稽核事件欄位結構，請參見
> [SIEM Pipeline（架構）](../architecture/siem-pipeline.md)。

---

## 相關文件
- [SIEM Pipeline（架構）](../architecture/siem-pipeline.md) — 內部事件流程 + 結構（B2）
- [Alerts & Quarantine](alerts-and-quarantine.md) — 轉發事件的來源
- [TLS & Certificates](tls-and-certificates.md) — syslog-TLS 部署參考
- [REST API](../reference/rest-api.md) — 以程式化方式管理目的地（B2）
