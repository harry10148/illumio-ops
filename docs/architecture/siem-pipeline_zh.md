---
title: SIEM Pipeline Architecture
audience: [developer, api, security]
last_verified: 2026-05-15
verified_against:
  - src/siem/
  - src/siem/formatters/
  - src/siem/transports/
  - commit 21b7740
related_docs:
  - overview.md
  - ../user-guide/siem-integration.md
  - ../reference/rest-api.md
  - ../user-guide/alerts-and-quarantine.md
---

> 🌐 **[English](siem-pipeline.md)** | **[繁體中文](siem-pipeline_zh.md)**
> 📍 [INDEX](../INDEX.md) › 架構 › SIEM 管線
> 🔍 最後驗證：**2026-05-15**，對應 commit `21b7740` — 詳見 frontmatter 來源說明

# SIEM 管線架構

本文件說明 SIEM 轉送管線的內部架構：事件如何進入管線、如何被正規化與格式化、
如何傳送至外部 SIEM 系統，以及系統如何處理失敗情況。

---

## 事件來源

管線由兩個來源表（source table）提供資料。dispatcher（`src/siem/dispatcher.py`）
透過相同的 `SiemDispatch` 佇列機制從兩個表讀取資料。

### PCE 稽核事件 — `pce_events`

PCE 稽核事件從 Illumio PCE API 擷取後寫入 `pce_events` SQLite 資料表
（定義於 `src/pce_cache/models.py`）。每一列代表一筆 PCE 稽核日誌：
政策變更、工作負載更新、使用者登入、API 呼叫等。

- **Model 類別：** `PceEvent`
- **來源表名稱（用於 `SiemDispatch.source_table`）：** `pce_events`
- **原始資料欄位：** `raw_json` — 原始 PCE API JSON

Ingestor 在寫入快取列的同一個 transaction 中呼叫 `siem.dispatcher.enqueue()`，
確保每筆稽核事件立即加入所有已設定 SIEM 目的地的佇列。

### PCE 流量記錄 — `pce_traffic_flows_raw`

網路流量記錄從 PCE 流量分析 API 擷取後寫入 `pce_traffic_flows_raw` 資料表。

- **Model 類別：** `PceTrafficFlowRaw`
- **來源表名稱：** `pce_traffic_flows_raw`
- **原始資料欄位：** `raw_json`

### 入佇列機制

```python
# src/siem/dispatcher.py
def enqueue(session_factory, source_table, source_id, destinations):
    """為每個目的地針對每筆新擷取記錄建立一列 siem_dispatch。"""
```

每個目的地、每筆來源記錄建立一列 `SiemDispatch`。
安全網補填函式 `enqueue_new_records()` 負責補充 ingestor 未能即時入佇列的記錄。

---

## 事件正規化

管線不定義嚴格的內部事件 model — formatter 直接接收從 `raw_json` 反序列化的原始
`dict`，並在輸出時進行正規化。PCE API 回傳兩種結構：

| 結構 | 說明 |
|---|---|
| **巢狀 PCE API 格式** | `src`、`dst`、`service` 為巢狀 dict；`created_by` 為巢狀 actor 物件 |
| **扁平官方日誌格式** | `src_ip`、`dst_ip`、`dst_port` 等欄位出現於頂層 |

所有 formatter 均相容兩種結構。正規化用的輔助函式定義於
`src/siem/formatters/cef.py`，並供其他 formatter 引用：

| 輔助函式 | 用途 |
|---|---|
| `_extract_actor(created_by)` | 從巢狀 `created_by` dict 擷取 actor 字串 |
| `_format_labels(labels)` | 將 Illumio label 清單格式化為簡短字串 |
| `_format_resource_changes(rc)` | 將資源變更清單彙整為可讀字串 |
| `_proto_to_str(proto)` | 將協定號碼（6、17、1）對映為字串（tcp、udp、icmp） |
| `_ts_to_epoch_ms(ts_str)` | 將 ISO8601 時間戳轉換為毫秒 epoch |

`NormalizedJSONFormatter` 引用上述函式以避免重複實作。

---

## Formatters

所有 formatter 位於 `src/siem/formatters/`。抽象基底類別為
`src/siem/formatters/base.py`：

```python
class Formatter(ABC):
    @abstractmethod
    def format_event(self, event: dict) -> str: ...

    @abstractmethod
    def format_flow(self, flow: dict) -> str: ...
```

兩個方法均接收原始 dict，回傳可直接傳入 transport `send()` 的 UTF-8 字串。

格式鍵（目的地設定中的 `format:`）在啟動時選擇 formatter：

| 格式鍵 | Formatter 類別 | 模組 |
|---|---|---|
| `cef` | `CEFFormatter` | `src/siem/formatters/cef.py` |
| `syslog_cef` | `SyslogWrappedFormatter(CEFFormatter())` | `src/siem/formatters/syslog_wrapped.py` |
| `syslog_json` | `SyslogWrappedFormatter(NormalizedJSONFormatter())` | `src/siem/formatters/syslog_wrapped.py` |
| `json` | `NormalizedJSONFormatter` | `src/siem/formatters/normalized_json.py` |

內部的 `JSONLineFormatter`（`src/siem/formatters/json_line.py`）為原始 PCE JSON
的直通格式；**不**對外暴露為使用者可設定的格式鍵，dispatcher 也不使用它。

### CEF

**模組：** `src/siem/formatters/cef.py`
**測試：** `tests/test_cef_formatter.py`

實作 ArcSight Common Event Format (CEF) 第 0 版。

**事件（`format_event`）：**

輸入：PCE 稽核事件 dict。輸出：CEF 字串。

```
CEF:0|Illumio|PCE|3.11|<event_type>|<event_type>|<severity>|rt=<epoch_ms> dvc=<pce_fqdn> ... suser=<actor>
```

PCE severity 字串對映 CEF 整數值：

| PCE severity | CEF 整數 |
|---|---|
| `info` | 3 |
| `warning` / `warn` | 6 |
| `error` / `err` | 8 |
| `critical` / `crit` | 10 |

事件的 extension 欄位：`rt`、`dvc`、`deviceExternalId`、`suser`、`src`
（來自 action 的 src_ip）、`requestMethod`、`request`、`cn1`/`cn1Label`
（HTTP 狀態碼）、`msg`（資源變更摘要）。

**流量（`format_flow`）：**

輸入：PCE 流量記錄 dict（巢狀或扁平）。輸出：CEF 字串。

```
CEF:0|Illumio|PCE|3.11|traffic.flow|traffic.flow|3|rt=<epoch_ms> src=<ip> dst=<ip> dpt=<port> proto=<proto> pd=<decision> ...
```

CEF 標準欄位承載網路 5-tuple（`src`、`dst`、`dpt`、`proto`）。
Illumio 專屬欄位使用原始名稱：`pd`、`src_hostname`、`src_href`、`src_labels`、
`dst_hostname`、`dst_href`、`dst_labels`、`process_name`、`num_connections`、
`flow_count`、`interval_sec`。

CEF 逸出規則套用於所有 extension 值：`\`、`|`、`=`、`\n`、`\r` 均以反斜線逸出。

### syslog_cef

**模組：** `src/siem/formatters/syslog_wrapped.py`（包裝 `CEFFormatter`）
**測試：** `tests/test_json_formatter.py`（路由測試）

`SyslogWrappedFormatter` 為裝飾器模式：呼叫內部 formatter 後，透過
`wrap_rfc5424()`（`src/siem/formatters/syslog_header.py`）在前方加入 RFC5424 syslog 標頭。

```
<PRI>1 <TIMESTAMP> <pce_fqdn> illumio-ops - - - CEF:0|...
```

RFC5424 severity 對映：

| PCE severity | Syslog severity |
|---|---|
| `info` | 6（informational） |
| `warning` / `warn` | 4（warning） |
| `error` / `err` | 3（error） |
| `critical` / `crit` | 2（critical） |

Facility 固定為 1（user-level messages）。PRI = facility × 8 + severity。
事件或流量 dict 中的 `pce_fqdn` 作為 RFC5424 HOSTNAME 欄位。

### syslog_json

**模組：** `src/siem/formatters/syslog_wrapped.py`（包裝 `NormalizedJSONFormatter`）
**測試：** `tests/test_json_formatter.py`

與 `syslog_cef` 使用相同的 RFC5424 框架，但 MSG 部分為
`NormalizedJSONFormatter` 輸出的扁平 JSON，而非 CEF 字串。

```
<PRI>1 <TIMESTAMP> <pce_fqdn> illumio-ops - - - {"timestamp":"...","event_type":"..."}
```

### NormalizedJSON

**模組：** `src/siem/formatters/normalized_json.py`
**測試：** `tests/test_json_formatter.py`

輸出使用官方 Illumio 欄位名稱的扁平單層 JSON 物件。
相容巢狀 PCE API 格式與扁平官方日誌格式。
`None` 及空字串值從輸出中省略（`_omit_none()`）。
序列化使用 `orjson` 以提升效能。

此 formatter 於 commit `edda47b` 引入，用以修正 Splunk HEC 將巢狀 PCE JSON
索引為逸出字串的問題（導致欄位必須透過 `spath` 才能存取）。

**事件（`format_event`）：** 輸出欄位 — 詳見[事件結構](#事件結構)。

**流量（`format_flow`）：** 扁平欄位包含 `timestamp`、`pce_fqdn`、
`src_ip`、`dst_ip`、`dst_port`、`proto`、`pd`（政策決定）、
`src_hostname`、`src_href`、`src_labels`、`dst_hostname`、`dst_href`、
`dst_labels`、`process_name`、`num_connections`、`flow_count`、`interval_sec`。

---

## Transports

所有 transport 位於 `src/siem/transports/`。抽象基底類別為
`src/siem/transports/base.py`：

```python
class Transport(ABC):
    @abstractmethod
    def send(self, payload: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
```

Transport 鍵（目的地設定中的 `transport:`）在啟動時透過
`src/siem/tester.py` 與 `src/siem/dispatcher.py` 中的 `_transport_for()`
選擇實作。

### TCP syslog

**模組：** `src/siem/transports/syslog_tcp.py`
**測試：** `tests/test_transport_udp_tcp.py`

- 協定：TCP 串流，以換行符號（`\n`）分幀
- 預設埠：514
- 連線：持久連線；首次 `send()` 時建立（lazy connect）
- 執行緒安全：`threading.Lock()` 保護 socket
- 重連：發生 `BrokenPipeError`、`ConnectionResetError` 或 `OSError` 時，
  關閉 socket 並嘗試一次重連後重送。重連失敗時，例外傳遞至 dispatcher
  （視為 send 失敗，納入 retry/DLQ 流程）。
- 背壓：transport 層不處理，由 dispatcher 負責

### UDP syslog

**模組：** `src/siem/transports/syslog_udp.py`
**測試：** `tests/test_transport_udp_tcp.py`

- 協定：UDP 資料報，無分幀
- 預設埠：514
- 連線：無狀態，初始化時建立一個 `socket.SOCK_DGRAM`
- 背壓：無 — 發送後不保證送達
- 重試：無 — UDP 不保證傳送
- MTU 警告：payload 超過 1 400 位元組時觸發 `logger.warning`（碎片化風險），
  但仍嘗試傳送

UDP 為最低負擔的選項，但不保證傳送。
僅在可接受偶發性事件遺失的情況下使用。

### TLS syslog

**模組：** `src/siem/transports/syslog_tls.py`
**測試：** `tests/test_transport_tls.py`

- 協定：TCP + TLS 串流，以換行符號分幀
- 預設埠：6514
- TLS 版本：TLS 1.2+（Python `ssl.create_default_context()` 預設）
- 自訂 CA：`ca_bundle` 路徑傳入 `ctx.load_verify_locations()`
- 停用驗證：`tls_verify=False` 設定 `CERT_NONE` 並停用主機名稱檢查；
  觸發 `logger.warning`。僅供開發環境使用。
- 連線 / 重連：與 TCP syslog 相同模式 — lazy connect、鎖保護、
  發生 `BrokenPipeError` / `ConnectionResetError` / `OSError` / `ssl.SSLError`
  時嘗試一次重連
- 執行緒安全：`threading.Lock()`

### HEC

**模組：** `src/siem/transports/splunk_hec.py`
**測試：** `tests/test_transport_hec.py`

- 協定：HTTPS POST 至 Splunk HTTP Event Collector
- 預設埠：8088
- Endpoint：`https://<host>:<port>/services/collector/event`
- 認證：`Authorization: Splunk <token>` 標頭
- Sourcetype：`illumio_ops`（固定）
- Timeout：每次請求 10 秒

**JSON 自動偵測：** 若 `payload` 為有效 JSON，`send()` 將 `event_data`
以 dict 傳入，使 Splunk 能原生索引所有欄位（無需 `spath`）。
非 JSON payload（如 CEF 字串）則以純字串放入 `event` 欄位。

**重試（urllib3 `Retry`）：**

| 參數 | 值 |
|---|---|
| `total` | 3 次嘗試 |
| `backoff_factor` | 0.5 秒 |
| `status_forcelist` | 429、500、502、503、504 |
| `allowed_methods` | POST |

Session 層級的重試在單次 `send()` 呼叫中執行。
3 次均失敗時，例外傳遞至 dispatcher。

---

## 重試與背壓模型

dispatcher（`src/siem/dispatcher.py`）在 SQLite 上實作持久佇列重試模型。

### 佇列狀態

每列 `SiemDispatch` 具有 `status` 欄位：

| 狀態 | 說明 |
|---|---|
| `pending` | 下一個 tick 即可派送 |
| `failed` | 超過 `max_retries`；不再自動重試 |

> **注意：** 超過 `max_retries` 的列會移至 `dead_letters` 資料表（DLQ），
> 不會以 `failed` 狀態永久留存。

### 重試迴圈

`DestinationDispatcher.tick()` 以計時器呼叫
（預設間隔：`dispatch_tick_seconds`，可透過 `SiemForwarderSettings` 設定）。
每個 tick：

1. 選取最多 `batch_size` 列 `next_attempt_at` 已到期（或為 null）的 pending 列。
2. 從 `pce_events` 或 `pce_traffic_flows_raw` 載入來源記錄。
3. 呼叫 `formatter.format_event()` 或 `formatter.format_flow()`。
4. 呼叫 `transport.send(payload)`。
5. 成功：刪除該 `SiemDispatch` 列。
6. 失敗：
   - `retries` 遞增。
   - 設定 `next_attempt_at = now + _backoff_seconds(retries)`。
   - 指數退避：`min(2^retries × 5, 3600)` 秒（上限 1 小時）。
   - 若 `retries >= max_retries`（預設 10）：呼叫 `_quarantine()`。

### 死信佇列（DLQ）

列被隔離時，dispatcher：
1. 寫入一列 `DeadLetter`（資料表 `dead_letters`），包含 `source_table`、
   `source_id`、`destination`、`retries`、`last_error`、`payload_preview`、
   `quarantined_at`。
2. 刪除對應的 `SiemDispatch` 列。

DLQ 管理透過 `src/siem/dlq.py`（`DLQManager`）暴露：

- `list_entries(destination, limit)` — 查詢指定目的地的 DLQ
- `replay(destination, limit)` — 將 DLQ 列重新入佇為 pending
- `purge(destination, older_than_days)` — 刪除舊的 DLQ 列

REST API（`src/siem/web.py`）提供 DLQ CSV 匯出與 replay endpoint。

### 背壓

transport 至 dispatcher 之間沒有明確的背壓訊號。速率限制為隱式：

- `batch_size` 限制每個 tick 處理的列數（預設 100）。
- `dispatch_tick_seconds` 控制 tick 間的最小間隔。
- 指數退避防止對失敗的目的地持續重試。

若佇列累積速度快於清空速度，列會堆積於 `siem_dispatch`。
請透過 `/api/siem/queue` endpoint 監控佇列深度。

---

## 事件結構

本節為正規化內部事件欄位的規範性參考。
`user-guide/siem-integration.md` 連結至此。

管線接收原始 PCE API dict。以下欄位為 formatter 擷取並輸出的內容。
除標記為**必填**者外，所有欄位均為選填。

### 稽核事件欄位

| 欄位 | 型別 | 原始 dict 來源 | 說明 |
|---|---|---|---|
| `timestamp` | `str`（ISO8601） | `event.timestamp` | **必填。** 事件發生時間 |
| `pce_fqdn` | `str` | `event.pce_fqdn` | **必填。** 產生事件的 PCE FQDN |
| `event_type` | `str` | `event.event_type` | **必填。** 點號分隔的事件類型（如 `policy.rule.create`） |
| `severity` | `str` | `event.severity` | `info` / `warning` / `error` / `critical` |
| `status` | `str` | `event.status` | `success` / `failure` |
| `pce_event_id` | `str` | `event.pce_event_id` 或 `event.uuid` 或 `event.href` | 唯一事件識別碼 |
| `suser` | `str` | `event.created_by`（巢狀 actor） | 觸發事件的角色（使用者 email 或 service account） |
| `src_ip` | `str` | `event.action.src_ip` | API 呼叫的來源 IP |
| `request_method` | `str` | `event.action.api_method` | API 呼叫的 HTTP 方法（GET、POST 等） |
| `request` | `str` | `event.action.api_endpoint` | API endpoint 路徑 |
| `http_status_code` | `int` | `event.action.http_status_code` | HTTP 回應碼 |
| `resource_changes` | `str` | `event.resource_changes[]` | 資源變更的可讀摘要（格式化清單） |

### 流量記錄欄位

| 欄位 | 型別 | 原始 dict 來源 | 說明 |
|---|---|---|---|
| `timestamp` | `str`（ISO8601） | `flow.timestamp` 或 `flow.first_detected` 或 `flow.timestamp_range.first_detected` | **必填。** 流量偵測時間 |
| `pce_fqdn` | `str` | `flow.pce_fqdn` | 回報此流量的 PCE |
| `src_ip` | `str` | `flow.src_ip` 或 `flow.src.ip` | 來源 IP 位址 |
| `dst_ip` | `str` | `flow.dst_ip` 或 `flow.dst.ip` | 目的地 IP 位址 |
| `dst_port` | `int` | `flow.dst_port` 或 `flow.port` 或 `flow.service.port` | 目的地埠 |
| `proto` | `str` | `flow.proto` 或 `flow.protocol` 或 `flow.service.proto` | 協定：`tcp`、`udp`、`icmp` 或數字字串 |
| `pd` | `str` | `flow.pd` 或 `flow.policy_decision` | 政策決定：`allowed`、`blocked`、`potentially_blocked`、`unknown` |
| `src_hostname` | `str` | `flow.src_hostname` 或 `flow.src.workload.hostname` | 來源工作負載主機名稱 |
| `src_href` | `str` | `flow.src_href` 或 `flow.src.workload.href` | 來源工作負載 href |
| `src_labels` | `str` | `flow.src_labels` 或 `flow.src.workload.labels` | 來源工作負載的 Illumio labels（格式化） |
| `dst_hostname` | `str` | `flow.dst_hostname` 或 `flow.dst.workload.hostname` | 目的地工作負載主機名稱 |
| `dst_href` | `str` | `flow.dst_href` 或 `flow.dst.workload.href` | 目的地工作負載 href |
| `dst_labels` | `str` | `flow.dst_labels` 或 `flow.dst.workload.labels` | 目的地工作負載的 Illumio labels（格式化） |
| `process_name` | `str` | `flow.process_name` | 行程名稱（若有） |
| `num_connections` | `int` | `flow.num_connections` | 區間內的連線數 |
| `flow_count` | `int` | `flow.flow_count` | 流量計數 |
| `interval_sec` | `int` | `flow.interval_sec` | 聚合區間（秒） |

### `proto` 正規化說明

協定由 `_proto_to_str()` 將數字（IANA）轉換為字串：

| 數字 | 字串 |
|---|---|
| 1 | `icmp` |
| 6 | `tcp` |
| 17 | `udp` |
| 其他 | 數字字串（直接傳遞） |

### actor 擷取說明（`suser`）

`_extract_actor(created_by)` 依序檢查：
`created_by.user.username` → `created_by.service_account.name` →
`created_by.system_account` → 回退為空字串。

---

## 新增 formatter 的步驟

1. **建立** `src/siem/formatters/<name>.py`。繼承 `Formatter`
   （`src/siem/formatters/base.py`）並實作 `format_event(event: dict) -> str`
   與 `format_flow(flow: dict) -> str`。

2. **註冊**格式鍵至 `src/siem/tester.py` 的 `_build_formatter(fmt: str)`
   — 加入 `if fmt == "<key>": return YourFormatter()` 分支。

3. **同樣**在 `src/siem/dispatcher.py` 的 `_formatter_for(dest_cfg)` 中
   加入相同格式鍵，供 production dispatcher 使用。

4. **驗證**格式鍵於 `src/config_models.py` —
   確認 `SiemDestinationSettings.format` 接受新鍵
   （如有 `Literal[...]` 型別或 validator，請將其加入）。

5. **新增測試**至 `tests/test_<name>_formatter.py`。最低限度：
   一個事件測試、一個流量測試；如適用，驗證 syslog 包裝後的輸出。

---

## 新增 transport 的步驟

1. **建立** `src/siem/transports/<name>.py`。繼承 `Transport`
   （`src/siem/transports/base.py`）並實作 `send(payload: str) -> None`
   與 `close() -> None`。若 transport 持有持久狀態（socket、session），
   請使用 `threading.Lock()`。

2. **註冊** transport 鍵至 `src/siem/tester.py` 的 `_build_transport(dest_cfg)`
   — 加入對應的分支。

3. **同樣**在 `src/siem/dispatcher.py` 的 `_transport_for(dest_cfg)` 中
   加入相同 transport 鍵，供 production dispatcher 使用。

4. **新增任何所需的設定欄位**（host、port、token 等）至
   `src/config_models.py` 的 `SiemDestinationSettings`。

5. **新增測試**至 `tests/test_transport_<name>.py`。涵蓋：
   成功傳送、連線失敗（驗證例外正確傳遞）、以及任何 transport 特定行為
   （重試、TLS、MTU 警告等）。

---

## 相關文件
- [架構概覽](overview.md) — 系統整體架構
- [SIEM 整合（operator）](../user-guide/siem-integration.md) — operator 設定說明
- [REST API](../reference/rest-api.md) — 目的地管理 endpoint
- [告警與隔離](../user-guide/alerts-and-quarantine.md) — 主要事件來源
