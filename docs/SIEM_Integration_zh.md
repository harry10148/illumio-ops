# SIEM 整合

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
| Glossary | [Glossary.md](./Glossary.md) | [Glossary_zh.md](./Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
<!-- END:doc-map -->

---

## SIEM 轉送器

> [!WARNING]
> 狀態：**預覽**（2026-04-23）。
> 現有部署可繼續使用 SIEM 轉送以維持相容性，但完整正式環境推出應等到執行管線缺口補齊後再進行。
>
> Task.md 中追蹤的已知缺口：
> - 執行時攝入路徑尚未自動排入 SIEM 派送列。
> - 排程器派送路徑尚未接線至完整的端對端消費迴圈。
> - 酬載建置失敗目前可能導致列留在持久性 `pending` 狀態。

## 架構

```
PCE API
  └─► EventsIngestor / TrafficIngestor
           │  (rate-limited, watermarked)
           ▼
      pce_cache.sqlite
           │
     siem_dispatch table
           │
      SiemDispatcher (tick every 5s)
           │
      ┌────┴───────────────────┐
      │         Formatter      │
      │  CEF 0.1 / JSON Lines  │
      │  + RFC5424 syslog hdr  │
      └────┬───────────────────┘
           │
      ┌────┴───────────────────┐
      │       Transport        │
      │  UDP / TCP / TLS / HEC │
      └────────────────────────┘
           │  (failure → DLQ)
           ▼
      SIEM / Splunk / Elastic
```

## 必要條件

必須先啟用 PCE 快取（`pce_cache.enabled: true`）。

## 啟用

在 `config/config.json` 中新增：

```json
"siem": {
  "enabled": true,
  "destinations": [
    {
      "name": "splunk-hec",
      "transport": "hec",
      "format": "json",
      "endpoint": "https://splunk.example.com:8088",
      "hec_token": "your-hec-token-here",
      "source_types": ["audit", "traffic"],
      "max_retries": 10
    }
  ]
}
```

## 全域 `siem` 設定區塊

`config.json` 中的頂層 `siem` 區段控制轉送器執行時行為：

| 鍵 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `siem.enabled` | bool | `false` | 啟用 SIEM 轉送器 |
| `siem.destinations` | list | `[]` | 目的地物件清單（見下方 schema） |
| `siem.dlq_max_per_dest` | int | `10000` | 每個目的地在最舊列被驅逐前的最大死信佇列深度 |
| `siem.dispatch_tick_seconds` | int | `5` | 派送器檢查待傳送列的頻率（秒） |

**操作命令：** `illumio-ops siem test <name>`（傳送合成事件）、`illumio-ops siem status`（顯示各目的地派送數量）、`illumio-ops siem replay --dest <name>`（重新排入 DLQ 項目）、`illumio-ops siem dlq --dest <name>`（列出死信事件）、`illumio-ops siem purge --dest <name>`（移除超過 N 天的 DLQ 項目）。

## 目的地設定 Schema

| 欄位 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `name` | string | 必填 | 唯一識別碼（1–64 字元） |
| `transport` | udp\|tcp\|tls\|hec | 必填 | 傳輸線路協定 |
| `format` | cef\|json\|syslog_cef\|syslog_json | `cef` | 日誌行格式 |
| `endpoint` | string | 必填 | syslog 的 `host:port`；HEC 的完整 URL |
| `tls_verify` | bool | `true` | 驗證 TLS 憑證（僅開發環境停用） |
| `tls_ca_bundle` | string | null | 自訂 PKI 的 CA bundle 路徑 |
| `hec_token` | string | null | Splunk HEC token（`transport: hec` 時必填） |
| `batch_size` | int | 100 | 每個派送器 tick 的列數 |
| `source_types` | list | `["audit","traffic"]` | 要轉送的資料類型 |
| `max_retries` | int | 10 | 移至隔離前的重試次數 |

## 格式範例

**CEF（稽核事件）：**
```
CEF:0|Illumio|PCE|3.11|policy.update|policy.update|3|rt=1745049600000 dvchost=pce.example.com externalId=uuid-abc outcome=success
```

**JSON Lines（流量記錄）：**
```json
{"src_ip":"10.0.0.1","dst_ip":"10.0.0.2","port":443,"protocol":"tcp","action":"blocked","flow_count":5}
```

**RFC5424 syslog 封裝（包裝任何格式）：**
```
<14>1 2026-04-19T10:00:00.000Z pce.example.com illumio-ops - - - CEF:0|Illumio|PCE|...
```

使用 `format: syslog_cef` 或 `format: syslog_json` 啟用 RFC5424 封裝。

## 測試目的地

```bash
illumio-ops siem test splunk-hec
```

傳送一個合成 `siem.test` 事件，並回報成功或失敗及錯誤訊息。

## DLQ 操作指南

當目的地連續失敗 `max_retries` 次時，派送列會移至 `dead_letter` 表。使用以下命令檢查：

```bash
illumio-ops siem dlq --dest splunk-hec
```

修復根本原因（錯誤 token、網路分區等）後，重新排入：

```bash
illumio-ops siem replay --dest splunk-hec --limit 1000
```

清除不再需要的舊項目：

```bash
illumio-ops siem purge --dest splunk-hec --older-than 30
```

## 傳輸層選擇指南

| 選項 | 傳輸層 | 可靠性 | 順序 | 加密 | 使用場景 |
|---|---|---|---|---|---|
| Option A | UDP | 盡力傳送 | 否 | 否 | 低價值、高流量；即發即忘 |
| Option B | TCP | 至少一次 | 是 | 否 | 內部網路，不需要 TLS |
| Option C | TLS | 至少一次 | 是 | 是 | 正式環境**建議** |
| Option D | HEC | 至少一次 | 是 | 是（HTTPS） | Splunk 環境 |

UDP 可用但**不建議用於正式環境** — 設定 UDP 目的地時，GUI 會顯示警告橫幅。

## 退避排程

失敗的傳送以指數退避策略重試，上限為 1 小時：

| 重試 | 等待 |
|---|---|
| 1 | 10s |
| 2 | 20s |
| 3 | 40s |
| 4 | 80s |
| 5 | 160s |
| 6 | 320s |
| 7 | 640s |
| 8 | 1280s |
| 9 | 2560s |
| 10 | 3600s（上限） |


## CLI 指令參考

`illumio-ops siem` 子指令群組用於管理目的地與派送佇列。下表彙整 `src/cli/siem.py` 中提供的子指令；完整選項語法請參閱 [使用手冊 §1.5](./User_Manual_zh.md#illumio-ops-siem-subcommands)。

| 指令 | 用途 |
|---|---|
| `illumio-ops siem test <name>` | 對指定目的地傳送合成 `siem.test` 事件，並回報延遲 |
| `illumio-ops siem status` | 顯示各目的地的 pending / sent / failed 計數與 DLQ 深度 |
| `illumio-ops siem dlq --dest <name>` | 列出指定目的地的死信佇列項目 |
| `illumio-ops siem replay --dest <name>` | 將 DLQ 項目重新排入為待派送列 |
| `illumio-ops siem purge --dest <name>` | 刪除超過 N 天（預設 30 天）的 DLQ 項目 |

> 註：目前並無 `siem flush` 子指令。派送器會依 `siem.dispatch_tick_seconds` 間隔（預設 5 秒）自動排空佇列。

範例：

```bash
illumio-ops siem test splunk-hec
illumio-ops siem status
illumio-ops siem dlq --dest splunk-hec --limit 20
illumio-ops siem replay --dest splunk-hec --limit 500
illumio-ops siem purge --dest splunk-hec --older-than 7
```

## 接收端設定範例

以下為常見 SIEM／日誌平台的接收端設定範例。每個接收端應搭配 `config/config.json` 中對應的目的地設定區塊（參見[目的地設定 Schema](#目的地設定-schema)）。

### Splunk HEC

在 Splunk Web → Settings → Data inputs → HTTP Event Collector：

1. 新增 Token，來源類型設為 `_json`，索引設為 `illumio_ops`。
2. 記下 token；將 URL 填入目的地設定的 `endpoint`，token 填入 `hec_token`。

使用 curl 驗證：

```bash
curl -k -H "Authorization: Splunk <TOKEN>" \
  https://splunk:8088/services/collector/event \
  -d '{"event":"test"}'
```

### Splunk 透過 Syslog（UDP／TCP）

`inputs.conf`：

```conf
[udp://514]
sourcetype = cef
index = illumio_ops

[tcp://1514]
sourcetype = cef
index = illumio_ops
```

### Logstash（JSON 行）

```conf
input {
  tcp { port => 5044  codec => json_lines }
}
filter {
  if [event_type] {
    mutate { add_tag => ["illumio_event"] }
  }
}
output {
  elasticsearch { hosts => ["es:9200"] index => "illumio-ops-%{+YYYY.MM.dd}" }
}
```

### rsyslog（CEF over UDP）

`/etc/rsyslog.d/illumio.conf`：

```conf
$ModLoad imudp
$UDPServerRun 514
:msg, contains, "CEF:0|Illumio" /var/log/illumio.log
& stop
```

### Filebeat（讀取 JSON sink 檔案）

```yaml
filebeat.inputs:
  - type: log
    paths: ["/opt/illumio_ops/logs/illumio_ops.json.log"]
    json.keys_under_root: true
output.elasticsearch:
  hosts: ["es:9200"]
  index: "illumio-ops-%{+yyyy.MM.dd}"
```

## 延伸閱讀

- [使用手冊 §1.5 — `illumio-ops siem` 子指令](./User_Manual_zh.md#illumio-ops-siem-subcommands) — 完整子指令語法與選項
- [使用手冊](./User_Manual_zh.md) — 執行模式、告警通道與進階部署
- [Architecture](./Architecture_zh.md) — 系統概觀、模組地圖、PCE 快取、REST API 手冊
- [README](../README_zh.md) — 專案入口與快速上手
