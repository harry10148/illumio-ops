# SIEM 轉拋新增 `cef_pce` 格式：對齊 PCE 原生 syslog CEF

日期：2026-09-11　狀態：已核准（使用者 2026-09-11 拍板：事件＋流量都對齊、新增模式不改既有 `cef`）

## 1. 動機

SOC 同時收 PCE 直送 syslog 與 ops 轉拋。用 Graylog（`172.16.15.105`，input `illumio` =
PCE 直送 UDP 5514、input `illumio-ops` = ops CEF TCP 5514）以同一 `event_href` 對帳後，
兩邊是兩套形狀：Signature ID 不同（PCE 為 `event_type.status`）、嚴重度數字不同、
PCE 帶完整 `resource_changes`／`notifications` JSON 而 ops 只留一段摘要、欄位名不同
（`duser` vs `suser`）。SOC 的規則無法通用，心跳／離線事件的 VEN 清單在 ops 側完全沒有。

使用者要求：ops 轉拋盡量與 PCE 原生 log 一致。

## 2. 決策

- **新增格式 `cef_pce`（與 `syslog_cef_pce`），不改既有 `cef`**。理由：既有 `cef` 的
  Signature ID 是純 `event_type`，SOC 可能已有精確比對規則；既有測試刻意不送空值
  `outcome=`，與 PCE 行為相反。
- **不仿 PCE 行首的 `sec=… sev=… pid=… tid=… rid=…` 前綴**。那是 PCE 內部 log 框架，
  正是它讓 Graylog 拆不出 PCE 直送的欄位；ops 的乾淨 CEF 反而被完整解析。
- **流量記錄只能對齊形狀，不能對齊語意**。PCE `flow_summary` 是每個 VEN 每個取樣區間
  一筆（`cn1=interval_sec`、`cnt` 為區間內連線數、`cn2/cn3` 為區間增量），ops 的來源是
  `traffic_flows` API 的聚合結果（一個 flow key 一筆、`num_connections` 與 `dst_bi/bo`
  是查詢視窗內總量）。形狀對齊讓 SOC 的 parser 與欄位名通用；數值語意差異寫進文件。

## 3. 證據

- `tests/fixtures/pce_native_cef_pairs.json`：19 組 audit 事件（ops cache `raw_json` ↔
  PCE 直送 CEF，同 `event_href`；涵蓋 system／user／agent／container_cluster 行為者、
  status null、非空 `resource_changes`、`FILTERED` src_ip、info／warning／err）＋ 6 組
  流量（同 5-tuple，非同一筆實例，只作形狀參考）。
- Graylog 36 天（2026-08-06 起）PCE 直送 3,000 筆掃描：擴充欄位值**不做 CEF 跳脫**
  （`suser=NT AUTHORITY\SYSTEM` 原樣、JSON 內 `"` 原樣；未觀察到含 `=`／`|` 的值）。
- 嚴重度實測：audit `info→1`、`warning→3`、`err→4`；flow `allowed→1`、
  `potentially_blocked→3`、`unknown→1`。未觀察到 `blocked`、`critical` 等。

## 4. 格式契約

### 4.1 Audit 事件（`format_event`）

Header：`CEF:0|Illumio|PCE|<pce_version>|<sig>|<name>|<sev>|`

| 欄 | 規則 |
|---|---|
| `pce_version` | 建構時注入（dispatcher 以 `GET /api/v2/product_version` 的 `version` 取得，失敗時 `"unknown"`；tester 用 `"unknown"`）。已知差異：PCE 送真實版本。 |
| `sig` | `event_type` ＋（`status` 非空時）`"." + status`。例 `sec_policy.create.success`、`user.pce_session_terminated`（status null）。 |
| `name` | `sig` 以 `.`／`_` 切詞，每詞首字大寫其餘小寫，空白連接。例 `User Pce Session Terminated`、`System Task Agent Offline Check Success`。 |
| `sev` | `info→1`、`notice→2`（假設）、`warning`/`warn→3`、`err`/`error→4`、`critical`/`crit→5`（假設）、`alert→6`（假設）、`emerg`/`emergency→7`（假設）、`debug→0`（假設）、其他→1。標「假設」者未在真機觀察到，以單調外推填入，程式碼註解標明。 |

Extension（順序固定、以單一空白連接、鍵值 `k=v`）：

```
rt dvchost [duid] duser dst outcome cat [request requestMethod reason] cs2 cs2Label cs4 cs4Label cn2 cn2Label cs1Label cs1
```

| 鍵 | 值 |
|---|---|
| `rt` | `timestamp` 轉 UTC，格式 `%b %d %Y %H:%M:%S.mmm +0000`（毫秒三位，日兩位補零）。例 `Sep 11 2026 09:00:08.882 +0000`。timestamp 缺失時省略整個鍵。 |
| `dvchost` | `pce_fqdn`；缺失時用建構時注入的 `pce_fqdn`（api.url 主機名）。 |
| `duid`／`duser` | 依 `created_by`：`system` → 無 `duid`、`duser=system`；`user` → `duid`=`user.href` 最後一段、`duser`=`username`（缺則 `name`）；`agent`（同時有 `ven`）→ `duid`=`ven.href` 最後一段（無 `ven` 時 `agent.href` 最後一段）、`duser`=`agent.hostname`；`container_cluster` → `duid`=href 最後一段、`duser`=`name`；`service_account` → `duid`=href 最後一段、`duser`=`name`（未實測，比照 container_cluster）；其他／空 → `duser=system`。 |
| `dst` | `action.src_ip` 存在且不是 `FILTERED` 時用它；否則用 `dvchost` 的值。已知差異：PCE 在 `FILTERED` 時送真實 IP 或 PCE 自己的 IP，API 端看不到。 |
| `outcome` | `status`；null／空時輸出 `outcome=`（空值保留，與 PCE 一致）。 |
| `cat` | 固定 `audit_events`。 |
| `request`／`requestMethod`／`reason` | 只在 `action` 為 dict 時輸出：`api_endpoint`、`api_method`、`http_status_code`。三者各自為 null 時省略該鍵。 |
| `cs2` | `resource_changes` 的 compact JSON（`orjson.dumps`，鍵序照原 JSON）；空清單或缺失 → `cs2=`。`cs2Label=resource_changes`。 |
| `cs4` | `notifications` 同上；`cs4Label=notifications`。 |
| `cn2` | 固定 `2`，`cn2Label=schema-version`。 |
| `cs1Label`／`cs1` | `cs1Label=event_href` 在前、`cs1=<href>` 在後（PCE 順序如此）。href 取 `href`，缺則 `pce_event_id`。 |

跳脫：不做 CEF 擴充欄位跳脫（不動 `\`、`"`、`=`）；只把 `\r`／`\n` 換成空白，`|` 只在 header
欄位跳脫為 `\|`。理由：cs2／cs4 必須是 SOC 可直接解析的 JSON，且 PCE 本身不跳脫。

PII 遮罩：走既有 `mask_event`（遮 `created_by.user.username`、`action.src_ip`、
`resource_changes[].changes.*.before/after`）之後才格式化，因此 `duser`／`dst`／`cs2`
內容自動被遮；`cs4`（notifications）內的 `info.user.username` **目前不在遮罩範圍**，
本案在 `mask_event` 加一條 `_mask_notifications`：遮 `notifications[].info.user.{username,name,email}`
與 `notifications[].info.src_ip`。

### 4.2 流量（`format_flow`）

Header：`CEF:0|Illumio|PCE|<pce_version>|flow_<pd>|Flow <Pd Words>|<sev>|`

| 欄 | 規則 |
|---|---|
| `pd` | `policy_decision`（或 flat `pd`）：`allowed`、`potentially_blocked`、`blocked`、`unknown`；其他→`unknown`。flat 數字 pd：0 allowed、1 potentially_blocked、2 blocked。 |
| `name` | `Flow Allowed`、`Flow Potentially Blocked`、`Flow Blocked`、`Flow Unknown`。 |
| `sev` | `allowed→1`、`unknown→1`、`potentially_blocked→3`、`blocked→5`（假設；來自 LEEF 文件 `sev=5`）。 |

Extension 順序：

```
act cat deviceDirection dpt src dst proto cnt [in out] rt [suser|duser] [destinationServiceName] [sproc|dproc]
cn1 cn1Label [cn2 cn2Label cn3 cn3Label] cs2 cs2Label [shost cs5 cs5Label [cs3 cs3Label]] [dhost cs6 cs6Label [cs4 cs4Label]] dvchost msg
```

| 鍵 | 值 |
|---|---|
| `act` | `pd`。`cat=flow_summary`。 |
| `deviceDirection` | `flow_direction`（或 `dir`）：`inbound`/`I`→`0`、`outbound`/`O`→`1`；缺→`0`。 |
| `dpt`／`src`／`dst`／`proto` | 目的埠（ICMP 為 `0`）、來源 IP、目的 IP、協定字串（6→tcp、17→udp、1→icmp）。 |
| `cnt` | `num_connections`（或 `count`／`flow_count`）；缺→省略。 |
| `in`／`out` | `dst_tbi`／`dst_tbo` 存在時輸出；ops 的 API 資料通常沒有 → 省略。已知差異。 |
| `rt` | `timestamp_range.last_detected`（或 `timestamp`／`last_detected`）轉 UTC `%b %d %Y %H:%M:%S`（無毫秒無時區）。 |
| 使用者／程序 | `service.user_name`／`service.process_name`（或 flat `un`／`pn`）：`deviceDirection=1` 時輸出 `suser`／`sproc`，`=0` 時 `duser`／`dproc`（回報方那一側）。 |
| `destinationServiceName` | `service.name`（或 flat `service_name`）存在時輸出，位置在 user 與 proc 之間。 |
| `cn1` | `interval_sec` 存在時輸出 `cn1=<n> cn1Label=interval_sec`；缺則省略。已知差異：PCE 一律有。 |
| `cn2`／`cn3` | `dst_dbi`／`dst_dbo`（或 `dst_bi`／`dst_bo`）存在時 `cn2=<n> cn2Label=dbi cn3=<n> cn3Label=dbo`。 |
| `cs2` | `state`：`active→A`、`snapshot→S`、`closed→C`、`timed_out→T`、`new→N`（假設）；單字母原樣；缺→`cs2=`。`cs2Label=state`。 |
| `shost`／`cs5`／`cs3` | 來源有 `workload` 時：`shost=<hostname>`（可為空字串，PCE 亦如此）、`cs5=<href> cs5Label=src_href`、labels 非空時 `cs3={"key":"value",…} cs3Label=src_labels`（鍵序照 labels 陣列）。 |
| `dhost`／`cs6`／`cs4` | 目的側同上，label 為 `dst_href`／`dst_labels`。 |
| `dvchost` | 建構時注入的 `pce_fqdn`（flow JSON 沒有）。 |
| `msg` | compact JSON，鍵序：`icmp_type`、`icmp_code`（原 JSON 有此鍵時，含 0）、`trafclass_code`（`transmission`：unicast→U、broadcast→B、multicast→M；flat `class` 原樣；缺→`U`）、`ddms`、`tdms`（存在時）、`network`（`network.name`）、`pd_qualifier`（存在時）。 |

PII 遮罩：`mask_flow` 遮 `service.user_name`／`process_name` → `suser/duser/sproc/dproc` 自動為
`[REDACTED]`。

### 4.3 syslog 包裝

`syslog_cef_pce` = `SyslogWrappedFormatter(PceNativeCEFFormatter)`，RFC5424 header 規則不變。

## 5. 觸點（七層清單）

1. `src/siem/formatters/cef_pce.py`（新）
2. `src/config_models.py` `SiemDestinationSettings.format` Literal 加 `cef_pce`、`syslog_cef_pce`
3. `src/siem/dispatcher.py` `_formatter_for`／`build_dispatcher`（注入 `pce_fqdn`、`pce_version`）
4. `src/scheduler/jobs.py` 呼叫 `build_dispatcher` 處提供兩個值
5. `src/siem/tester.py` `_build_formatter`
6. `src/siem/mask.py` 加 notifications 遮罩
7. i18n `gui_siem_format_help`／`sic_dest_config_help`（zh_TW、en、zh_explicit 釘選）＋ `docs/guide/siem.md`／`configuration.md`

## 6. 驗收

- 單元：19 組 audit golden pair 逐字相等（header 版本欄以 fixture 的 `26.2.20` 注入；
  `dst` 在 FILTERED 案例以規則值比對而非 PCE 值）；流量 6 組以規則推導的期望字串比對，
  並斷言鍵順序與 PCE 參考行的鍵順序一致（去掉 ops 沒有的 `in`/`out`/`cn1` 後）。
- 守門：注入缺陷（拿掉 `cn2`）確認 golden 測試變紅。
- 真機：測試機 graylog 目的地切 `cef_pce`，跑一小時，以 `externalId`＝PCE `cs1` 對帳，
  逐鍵 diff；容許差異僅 `dvchost`／`dst` fallback 與版本欄。
