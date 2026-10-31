---
title: v6 SIEM 轉送與東西向分析指引
last_verified: 2026-10-31
verified_against:
  - illumio_ops/siem/formatters/ops.py
  - illumio_ops/services/siem/sources.py
  - illumio_ops/services/siem/dispatch.py
---

# v6 SIEM 轉送與東西向分析指引

給已經有 SIEM 的客戶：illumio-ops v6 送什麼、不送什麼，以及怎麼在 SIEM 裡用這些事件看東西向（主機之間）的連線與橫向移動。

## 1. 送什麼、不送什麼

```
PCE ──API──> illumio-ops v6 ──syslog / TLS / Splunk HEC──> 你的 SIEM
              │
              ├─ audit 事件          PCE 原樣（可選與 PCE 原生 syslog 相同的 CEF）
              ├─ 偵測與告警          本產品的橫向移動偵測、竄改等，每則一筆
              └─ 新連線（選用）      每個「來源 → 目的 × port」在基準期內第一次出現時一筆
```

**不送流量紀錄。** PCE API 給的流量是「整天累計」的值：同一條連線的連線數與位元組在一天內一直變大。把它當成 log 送進 SIEM，SIEM 會一筆一筆加總，數字變成實際的好幾倍。要原始流量的客戶：

- 地端 PCE：在 PCE 設定原生 syslog 轉送（`flow_summary`，每台 VEN 每個取樣區間一筆）。
- SaaS：PCE 的 S3 匯出。

illumio-ops 送的「新連線」事件**不帶連線數或位元組**，只說「這條連線第一次出現了」，SIEM 不會重複加總。

### 三種收集模式下會送出什麼

| 來源 | 輕量（預設） | 告警 | 完整 |
|---|---|---|---|
| audit 事件 | 照常 | 照常 | 照常 |
| 告警 | 只有事件型告警 | 全部 | 全部 |
| 偵測 | 不會產生 | 有 | 有 |
| 新連線 | 不會產生 | 基準期滿後 | 基準期滿後 |

輕量模式下，SIEM 頁對「偵測」「新連線」寫「需要告警模式」，不會顯示成正常但 0 筆。新連線要等本機累積滿基準期（預設 30 天，資料收集頁可改）才開始送：在那之前「第一次出現」不成立。

## 2. 事件欄位

### CEF（`cef`、`syslog_cef`；`cef_pce` 系列的非 audit 事件也是這個）

標頭的裝置一律是 `Illumio|illumio-ops|<版本>`；只有轉送的 audit 事件在 `cef_pce` 格式下標成 PCE（為了讓為 PCE 原生 syslog 寫的規則直接比對）。

| 欄位 | 內容 |
|---|---|
| Signature ID | `detection.<偵測器>`、`alert.<規則型別>`、`new_connection.<判定>` |
| 嚴重度 | low 3、medium 5、high 8、critical 10（新連線為 1） |
| `rt` | 事件發生時間，epoch 毫秒（不帶時區：Graylog 7.1 會整行丟棄帶 `+0000` 的 rt） |
| `externalId` | `<種類>:<編號>`，重送時相同，可用來去重 |
| `cat` | `illumio_ops_detection`、`illumio_ops_alert`、`illumio_ops_new_connection` |
| `msg` | 一句話說明（顯示語言） |
| `src` / `shost` | 來源 IP／主機名稱（偵測與告警：主體主機） |
| `dst` / `dhost` | 目的 IP／主機名稱（新連線） |
| `dpt` / `proto` | port／協定（tcp、udp、icmp） |
| `act` | 判定：allowed、potentially_blocked、blocked、unknown |
| `start` / `end` | 首次／最後觀察時間，epoch 毫秒 |
| `dvchost` | 所屬 PCE |
| `cs1`／`cs2` | 來源／目的 labels（JSON） |
| `cs3`／`cs4` | 來源／目的 Workload href |
| `cs5` | 其他事實（JSON，例如偵測次數、目標清單）；超過 3,995 字截斷並在 `cs6=true`（`facts_truncated`）說明 |

值依 CEF 規格跳脫 `\` 與 `=`：值裡的 ` act=blocked` 不會被當成另一個欄位。

### JSON（`json`、`syslog_json`、Splunk HEC）

一行一個物件、省略空值：`source`（固定 `illumio-ops`）、`kind`、`id`、`external_id`、`time`（ISO 8601 UTC）、`signature`、`name`、`severity`、`summary`、`src_ip`／`src_host`／`src_href`／`src_labels`、`dst_*`、`port`、`proto`、`decision`、`first_seen`、`last_seen`、`facts`、`pce_fqdn`。

### 送達語意

至少送達一次：送出後、記錄進度前若服務中斷，那一批會再送一次。用 `externalId`（JSON 的 `external_id`）去重。目的地連不上時停在原處，下一輪從同一筆繼續；同一筆連續失敗達「重試次數」後移入 DLQ，不會卡住整個目的地。

## 3. 在 SIEM 裡看東西向

### 新出現的管理連線

管理 port（SSH 22、RDP 3389、SMB 445、WinRM 5985/5986、RPC 135）第一次出現的連線，是橫向移動最直接的線索：

- Graylog：`cat:illumio_ops_new_connection AND dpt:(22 OR 3389 OR 445 OR 5985 OR 5986 OR 135)`
- Splunk（HEC，JSON）：`sourcetype=illumio_ops kind=new_connection port IN (22,3389,445,5985,5986,135) | stats count by src_host, dst_host, port, decision`

### 一台主機短時間連到很多主機

本產品的扇出偵測已經算好；在 SIEM 裡可以再按來源聚合新連線看趨勢：

- Splunk：`sourcetype=illumio_ops kind=new_connection | bin _time span=1h | stats dc(dst_host) as targets by _time, src_host | where targets >= 10`

### 跨環境的連線

labels 在 `cs1`／`cs2`（JSON 的 `src_labels`／`dst_labels`）。例如 dev → prod：

- Splunk：`sourcetype=illumio_ops kind=new_connection src_labels.env=dev dst_labels.env=prod`

### 把偵測和 PCE 的 audit 對起來

偵測主機上近期的竄改或 VEN 事件：VEN 產生的 audit 事件（例如 `agent.tampering`）在 CEF 的 `duser` 是主機名稱，可以和偵測的 `shost` 對起來；Workload href 在偵測的 `cs3` 與 audit 事件 `cs4`（notifications JSON）裡。

## 4. 注意

- labels 是流量發生當時的 labels（新連線事件記錄的是那時的 label set）。
- 新連線只看 port 小於 49152 的服務（動態 port 是客戶端或 RPC 端點，不是新服務）。
- 「遮罩個人資料」開啟時：audit 的管理者 email、來源位址、變更內容文字，以及偵測與告警裡的帳號都換成 `[REDACTED]`；主機與 Workload 的位址保留。
- DLQ 的訊息保留送出當時的格式；目的地之後改了遮罩、主機、port 或格式，那些訊息不會重送到新設定。
