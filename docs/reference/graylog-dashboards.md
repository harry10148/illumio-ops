---
title: Graylog 儀表板與告警設計（Illumio + FortiGate）
audience: [operator, security]
version: 5.2.0
last_verified: 2026-09-21
verified_against:
  - src/siem/formatters/cef_pce.py
  - src/pce_cache/ingestor_traffic.py
  - src/pce_cache/traffic_filter.py
---

> 對象：拿到 Illumio / FortiGate 日誌、要在 Graylog 上做維運與風險檢視的人。
> 這份文件回答三件事：**這些 log 裡有什麼**、**能做出什麼儀表板與告警**、**還缺什麼要補**。
> 所有數字皆為 2026-09-21 在 `172.16.15.105`（Graylog 7.1.1 OSS）實測，非推估。
> **計數**（「7 天 X 筆」）是查詢的完整結果；**百分比與欄位覆蓋率**標示為「抽樣」者，
> 來自 300–1,500 筆訊息的客戶端取樣（Graylog 7.x 已移除 `/terms` 聚合端點），僅供比例參考。

---

## 1. 現況：三路資料

```
   PCE (pce.lab.local)
     │
     ├─ syslog UDP 5514 ──► input "illumio"      98.8k 筆/24h   ← 主要來源
     │   （PCE 原生直送，CEF 藏在 syslog 前綴後，目前未拆欄位）
     │
     └─ REST API ──► illumio-ops (172.16.15.106)
                       └─ CEF TCP 5514 ──► input "illumio-ops"  16.8k 筆/24h  ← 備援／對帳
   FortiGate FG60F ──► syslog UDP 514 ──► input "Fortigate"    348k 筆/24h
```

索引狀態：green、47 shards、journal 無積壓、單一 index set（30–40 天、20 indices）。

### 1.1 為什麼以直送為主

直送是 PCE 自己寫出來的觀測紀錄，**每筆 flow_summary 帶的欄位比 ops 轉送多**：

| 欄位 | 直送 | ops 轉送 | 說明 |
|---|---|---|---|
| `src` / `dst` / `dpt` / `proto` / `cnt` | ✅ | ✅ | 五元組與連線次數 |
| `in` / `out` | ✅ | ❌ | CEF 標準的位元組進出（= dst_tbi / dst_tbo） |
| `cn2=dbi` / `cn3=dbo` | ✅ | ✅ | 另一組位元組計數 |
| `cn1=interval_sec` | ✅ | ❌ | 取樣區間長度，**沒有它算不出速率** |
| `suser` / `sproc` | ✅ 6%（抽樣） | ✅ 2%（抽樣） | 來源端使用者與行程（如 `NT AUTHORITY\SYSTEM` / `dns.exe`） |
| `duser` / `dproc` | ✅ 16%（抽樣） | ✅ 0.7%（抽樣） | 目的端使用者與行程 |
| `shost` / `dhost` | ✅ 82% / 41%（抽樣） | ✅ 22% / 2.7%（抽樣） | 主機名 |
| `cs5=src_href` / `cs6=dst_href` | ✅ | ✅ | 工作負載 href（`/workloads/` vs `/kubernetes_workloads/` 可分辨 VEN 與 K8s） |
| `cs3=src_labels` / `cs4=dst_labels` | ✅ | ✅ | 標籤 JSON，`{"role":…,"env":…,"app":…,"loc":…}` |
| `msg.pd_qualifier` | ✅ | ❌ | **阻擋原因分類**，ops 拿不到（API 不回，見 §7）——這是「直送為主」最實在的理由，見 §4.1 |
| `msg.ddms` / `tdms` | ✅ | ❌ | 連線持續時間（毫秒） |

標籤也不需要靠 ops：直送本身就帶 `cs3`/`cs4`（標籤 JSON）與 `cs5`/`cs6`（href），解析後全部可用。

### 1.2 7 天逐類數量對照（同一時間窗）

| 事件 | 直送 | ops 轉送 | 判讀 |
|---|---:|---:|---|
| flow_allowed | 16,274 | 116 | ops 只有 0.7% |
| flow_potentially_blocked | 140,229 | 2,316 | ops 只有 1.7% |
| flow_unknown | 123,543 | 38,500 | ops 有 31% |
| **flow_blocked** | 0 | 0 | 全環境尚無 enforcement 實際阻擋（注意：PCE 的事件名是 `flow_blocked`，**不是** `flow_denied`；severity 5） |
| user.create_session.success | 4,096 | 2,046 | **直送重複送 2 次**，見 §2.3 |
| user.pce_session_terminated | 2,060 | 1,996 | 相符 |
| agent.upload_existing_ip_table_rules.success | 8 | 8 | 相符 |
| workloads.update.success | 4 | 4 | 相符 |
| container_cluster.security_policy_applied.success | 223 | 222 | 相符 |

**結論：audit 事件兩邊一致（ops 可信）；flow 則是量級差異。**
原因不是設定過濾——實機 `.106` 的 `traffic_filter.actions=[]`、`traffic_pd=[]`、
`source_types=["audit","traffic"]`，什麼都沒擋。差異來自來源本質：
直送是**每 VEN 每取樣區間一筆**，ops 走的是 traffic_flows API 的**聚合結果**。
形狀可以對齊，數值永遠不會相等。

---

## 2. 前置工程（沒有這一段，下面的儀表板都做不出來）

### 2.1 解析直送的 CEF

PCE 送出的不是純 CEF，而是 syslog 前綴 + CEF，且有兩種前綴：

```
sec=004338.870 sev=INFO pid=20636 tid=16260 rid=<uuid> CEF:0|Illumio|PCE|…
sec=002662.652 sev=INFO pid=… rid=<uuid> [cc_mode=clas] [cc_uuid=<uuid>] CEF:0|…   ← container cluster
```

因為 `CEF:0|` 不在行首，換 CEF codec 沒用。要 pipeline rule：

```
stage 0  抓出 CEF 段   regex "CEF:0\\|.*$"  →  parse_cef()  →  set_fields()
stage 1  依 cat 分支   ── cat=flow_summary ──► parse_json(cs3)→src_labels 展平
                       │                      parse_json(cs4)→dst_labels 展平
                       │                      parse_json(msg)→pd_qualifier/trafclass/network
                       └─ cat=audit_events ──► cs2(+cs3 續段)串接後 parse_json→resource_changes
                                              cs4 是 notifications，**不是 dst_labels**
```

**編號不等於執行順序**：Graylog 的 rule 在同一 stage 內不保證先後，有依賴關係的步驟
必須放在不同 stage priority。分支條件要用 `match either` 或各自獨立的 stage，
避免某條 `match all` 因為欄位不存在而擋住後面的 stage。

**`cs3`/`cs4` 在兩種事件裡意義完全不同**（flow 是標籤，audit 是 resource_changes 續段與
notifications）——不分支就會把 audit 的內容當成標籤寫進去，是最容易犯的錯。

pipeline 要掛在哪個 stream 也要確認：**「stream 分流先於 pipeline」不是無條件成立**，
取決於 Message Processor 的順序設定（Stream Rule Processor 必須排在 Pipeline Processor 之前），
否則就要改成掛在 Default Stream 上、由規則自己 `route_to_stream()`。

`parse_cef` 已確認存在於本機 7.1.1 的 144 個 pipeline function 中。

**驗收條件（缺一不可）**

1. **`rt` 兩種格式都要過**：flow 是 `Sep 21 2026 15:35:51`（無時區、無毫秒），
   audit 是 `Sep 21 2026 15:37:09.152 +0000`（有毫秒、有時區）。
   本專案 2026-09 的實測紀錄：**Graylog 的 CEF input 遇到帶 `+0000` 的 `rt` 會整行靜默丟棄**。
   pipeline 的 `parse_cef()` 是否有同樣行為**未經驗證**，這是第一條要測的。
   若真的踩到（audit 事件整批消失、flow 正常），照這個順序處理：
   (a) 解析前先 `regex_replace(cef_segment, " \\+0000", "")` 把時區去掉再 parse；
   (b) 仍失敗就不要讓整行消失——設 `cef_parse_failed=true`、保留原始 `message`，
       並以 Graylog 的收件時間當 `timestamp`（會失去約 10 分鐘的事件時間精度，但不掉資料）。
2. 解析失敗要**可計數**：失敗時設 `cef_parse_failed=true` 並保留原始 `message`。
3. audit 的 `cs2=resource_changes` 可能被 PCE 分段成 `cs2` + `cs3`（超過 3,995 字元時），
   要重組後才能 `parse_json`。
4. 數值欄位型別固定（`cnt`/`dpt`/`in`/`out` 不可時而字串）。**注意既有 index mapping**：
   欄位型別一旦在現有索引建立就不能改，型別改動要等 index rotation 或另開 index set。
   另外 `parse_cef()` 的 `use_full_names` 會決定拿到短名（`src`）還是長名
   （`sourceAddress`），**要先固定下來**，否則儀表板查詢與告警會對不上欄位。
5. 三種時間分清楚：`rt`（事件時間）、`gl2_receive_timestamp`（Graylog 收件時間）、
   ops 的 API 彙總區間。`timestamp` 預設是收件時間，但一旦把 `rt` 寫進去就變成事件時間——
   要明確決定並寫在規則裡。flow 的 `interval_sec` 實測 600–830 秒，代表**觀測區間**
   （不等於傳輸延遲），儀表板用收件時間、告警視窗 ≥15 分鐘。

**注意**：pipeline 不會回溯解析既有歷史；也救不回在 CEF codec 階段就被丟掉的 ops 訊息。
pipeline 必須掛在 stream 上，stream 分流先發生，規則才會跑。

### 2.1b 實作後的補充（2026-09-21 真的建起來才知道的）

pipeline 已經建好並掛在 `Illumio PCE` stream 上，內容即程式碼放在另一個 repo
（`graylog-ops`，private）。實作時踩到四件文件推不出來的事：

1. **`stage N match either` 會讓整條 pipeline 停住。** 它的語意是「這個 stage
   沒有任何規則命中就不再往下」。解析成功時「標記解析失敗」那條本來就不該命中，
   結果後面的分支 stage 全部跑不到、欄位全缺，而且**不報任何錯**。
   全部改成 `match pass`（Graylog 5.0+ 支援）。
2. **`parse_cef()` 會自己依 `csNLabel` 命名欄位**：拿到的是 `src_labels`、
   `dst_labels`、`resource_changes`、`event_href`、`interval_sec`、`dbi`/`dbo`，
   **不是** `cs3`/`cs4`/`cs2`。規則要讀解析後的名字。
3. **但 Signature ID 兩路名字不同**：pipeline 的 `parse_cef` 叫
   `device_event_class_id`，CEF input（ops 那路）叫 `event_class_id`。
   多一條規則對齊，儀表板才能同時吃兩路。
4. **規則語言沒有 `if` 陳述式**，條件只能寫在 `when`；一個欄位一條規則。

另外兩個 API 形狀：`POST /streams` 與 `POST /views` 收的是 `CreateEntityRequest`
包裝（`{entity, share_request}`），直接送本體會得到 `entity cannot be null`；
`GET /system/pipelines/connections/<stream>` 在還沒有連結時回 404，那是空集合不是錯誤。

**`cat` 這個欄位名不是 Illumio 專屬**：FortiGate 的 webfilter 也用 `cat`
（值是分類代碼，例如 52）。任何以 `cat` 做的 widget 都要夾住來源
（用 `cat:(flow_summary OR audit_events)` 或 stream 過濾），否則會混到防火牆資料。

**`rt` 帶 `+0000` 的疑慮解除**：實測 audit 事件（`rt=Sep 21 2026 …+0000`）
在 pipeline 裡解析正常，`rt` 正確轉成 epoch。規則仍保留去時區那一步當保險，
因為 CEF **input** 那條路的丟棄行為並沒有改變。

### 2.1c 目前已經上線的東西（2026-09-21，09-23 補兩頁）

| 類別 | 名稱 | 狀態 |
|---|---|---|
| stream | `Illumio PCE`、`Illumio Ops` | 啟用，不動 Default Stream |
| pipeline | `Illumio PCE direct`（9 規則） | 掛 `Illumio PCE`，解析成功率 100%、失敗 0 |
| pipeline | `FortiGate ops`（3 規則） | 掛 `FortiGate Syslog`，補 `sent_bytes`/`cpu_pct` 等可聚合欄位 |
| dashboard | 頁 0 資料可信度（7 widget） | 已驗，0 errors |
| dashboard | 分段待辦（8 widget） | 已驗，0 errors |
| dashboard | 政策與強制變更（6 widget，7 天） | 已驗，0 errors（09-23） |
| dashboard | 存取與身分（6 widget，7 天） | 已驗，0 errors（09-23） |
| dashboard | Illumio × FortiGate 對外依賴（4 widget） | 已驗，0 errors（09-23）；對外潛在阻擋大宗是各伺服器直接對外 NTP（123） |
| 升級 | 7.1.1 → 7.1.9 | **已完成（09-23）**，停機約 2 分半，驗收 0 異常；見 graylog-ops `docs/upgrade-7.1.9.md` |
| dashboard | FortiGate 防火牆維運（4 分頁 19 widget） | 已驗，0 errors |
| 告警 | 9 條 event definition | 全部 ENABLED 並排程 |

**FortiGate 的數值欄位要另外做**：`sentbyte`/`rcvdbyte`/`cpu`/`mem` 在既有索引裡是
`keyword`，`sum()` 會直接回 `not supported for aggregation`，而既有 mapping 不能改。
解法是 pipeline 另寫一組 `sent_bytes`/`rcvd_bytes`/`cpu_pct`/`mem_pct`/`sessions` 數值欄位。

**告警要先驗過會不會響**：用一條 canary 定義（查一定存在的資料）確認事件真的產生，
收到事件後再刪掉。沒驗過的告警定義等於不知道它會不會響。
刪掉定義**不會**刪掉它產生的事件——OSS 沒有刪單筆事件的 API，canary 留下的 20 筆是 09-23 以輪替 `gl-events` 再刪舊 index（`gl-events_0`/`_1`）清掉的；下次做 canary 前先想好這一步，或接受它們等保留期（30–40 天）自然過期。
另外本機目前**沒有任何 notification channel**，事件只會進 Events 清單，不會外送。

### 2.2 Stream 切分

目前兩個 Illumio input 都落在 Default Stream。建議：

| Stream | 規則 | 用途 |
|---|---|---|
| `Illumio PCE` | `gl2_source_input` = 直送 input id | 主資料、pipeline 掛這裡 |
| `Illumio Ops` | `gl2_source_input` = ops input id | 對帳、audit 備援 |
| `FortiGate Syslog` | 既有（`devid` regex） | 維持 |

Stream ≠ 保留期；要讓 flow 短、audit 長，得另外配 index set。

### 2.3 直送的 audit 會重複，而且**重複倍數因事件類型而異**

同一個 24 小時窗、以 `cs1`（event_href）的集合比對：

```
直送 audit  2,366 行 → 1,583 個不重複 event_href（另有 50 行根本沒有 cs1）
ops  audit  1,590 行 → 1,590 個不重複 event_href
交集 1,580 ｜ 直送獨有 3 ｜ ops 獨有 10（皆為視窗邊界的時間差）
```

**兩邊的事件集合一致（差異 < 1%）**——ops 沒有漏送；直送是同一事件寫了多行。

但倍數不是固定的 2：

| 事件類型 | 行數 | 不重複 | 倍數 |
|---|---:|---:|---:|
| `user.create_session.success` | 1,440 | 720 | 2.0 |
| `user.pce_session_terminated` | 687 | 687 | 1.0 |
| `container_cluster.security_policy_applied.success` | 141 | 141 | 1.0 |
| `user.login.success` / `user.sign_in.success` | 各 6 | 各 3 | 2.0 |
| `request.authentication_failed.failure` | 15 | 11 | 1.36 |
| `workloads.update.success` | 2 | 2 | 1.0 |

**而且失敗類事件常常沒有 `cs1`**（實測 24h：`user.login.failure` 3 行、
`user.logout.failure` 4 行、`request.authentication_failed.failure` 4 行全無 event_href）。

→ 直送的 audit 計數必須「以 `event_href` 去重、**但不能把沒有 href 的行丟掉**」，
  否則丟掉的剛好是最該看的失敗事件。
→ **Graylog pipeline 做不到跨訊息去重**（沒有共用狀態、重啟即失憶）。
  去重要在**查詢端**做：明細用 `event_href` 分組取一筆，告警則接受重複、
  改用 grace period 控制通知頻率。這兩件事要分開設計，不要期待一條規則同時解決。
→ audit 對帳建議直接用 ops（集合一致且已拆欄位），直送留給 flow。
→ flow 沒有 `cs1`，**無法用同樣方法驗證是否重複**；上線前要另尋鍵
  （例如 `src+dst+dpt+rt+cnt`）抽驗一次。

## 3. 對照：本專案報表 vs Graylog 能做到什麼

| 專案報表 | Graylog 可重現？ | 說明 |
|---|---|---|
| Traffic（流量） | ✅ 可 | 直送 flow_summary 欄位比報表還細（帶行程、位元組、標籤） |
| App Summary | ⚠️ 部分 | 可用 `src_app`/`dst_app` 標籤聚合，但沒有工作負載清單做分母 |
| Policy Diff | ✅ 可 | `sec_policy.*` 的 `resource_changes` 內含 before/after，見 §4.2 |
| Audit | ✅ 可 | 兩路都有，欄位齊全 |
| Security Risk | ⚠️ 部分 | 可做「暴露面」視角（對外埠、公網對談），但風險評分邏輯不在 log 裡 |
| Network Inventory | ⚠️ 部分 | flow 裡沒有 `cs5` 的來源＝未納管主機，可列清單；但沒有 PCE 清冊做完整度 |
| VEN Status / Fleet | ❌ 不可 | 只有事件驅動的 `agent.*`（7 天 171 筆）與 `lost_agent.*`；`system_health` 7 天 0 筆。可以看「發生了什麼」，看不到「現在有幾台離線」 |
| Readiness（就緒度） | ❌ 不可 | 分母是工作負載清冊，log 看不到「安靜的主機」 |
| Rule Hit Count | ❌ 不可 | flow_summary 不帶命中的規則 href |
| Posture / Ransomware | ❌ 不可 | 需要 PCE 設定狀態，不是事件 |

**一句話**：Graylog 適合做「**發生了什麼**」與「**變化與異常**」；
「**現在的組態長怎樣**」（就緒度、規則命中、VEN 健康）仍要回本專案報表。
這條界線本身就是要給讀者看的結論。

---

## 4. Illumio 儀表板

### 4.0 頁 0：資料可信度（先做，否則其他頁的「0」不能解讀）

| Widget | 查詢 | 現值 |
|---|---|---|
| 各 input 最後收件時間 | 三個 input 各一格 | 皆 < 1 分鐘 |
| 每分鐘筆數趨勢 | 依 input 分組 | 直送 ~68/分、ops ~12/分、FG ~240/分 |
| CEF 解析失敗數 | `cef_parse_failed:true` | 目標恆為 0 |
| 重複率抽查 | `cat:audit_events` 去重前後比 | 目前 1.49（見 §2.3） |
| **各類別分別看有沒有斷** | flow / audit 各一條趨勢，不要只看 input 總量 | audit 正常而 traffic 停掉時，總量幾乎看不出來 |
| ops 端的積壓 | illumio-ops 的 SIEM dispatch pending / DLQ（在本專案 GUI，不在 Graylog） | 轉送塞住時 Graylog 這邊只會「變安靜」 |

這頁只能證明「有資料進來」，**不能證明資料完整**：UDP 丟包、codec 丟行、索引失敗、
API 取值達上限、ops 端 backlog，都不會在 Graylog 裡留下痕跡。零筆不等於零風險。

### 4.1 頁 1：分段待辦（這頁是整套的核心）

`flow_potentially_blocked` = **現在允許、開啟強制後會被擋**。24 小時 47,515 筆。
它不是事故，是**上線前要處理的依賴清單**。

KB 查證的 `pd_qualifier` 語意，決定了每一類的處置方式：

| pd_qualifier | 意義 | 該做什麼 |
|---|---|---|
| 0 | 缺少分段規則 | 找 owner 確認是否必要 → 補規則 |
| 1 | 被 boundary 擋 | 確認 boundary 範圍是否過寬 |
| 2 | 被覆蓋的 global deny 擋 | 檢查 deny 規則的例外設計 |
| 3 | 被非 Illumio 撰寫的 deny 規則擋 | 與網路團隊對齊 |

**本環境現況（3,153 筆 flow 抽樣，取自最近訊息，非全時段隨機）**：`pd_qualifier` **100% 都是 0**，
也就是目前所有的潛在阻擋都屬於「缺少分段規則」，沒有 boundary 或 deny 規則造成的。
處置方向單一：逐條確認依賴後補規則。

同一份抽樣還顯示納管缺口：**12.2% 的 flow 來源端沒有 `src_href`**（未納管主機），
**48.2% 的目的端沒有 `dst_href`**（多為外部服務）；來源端有 13% 是 K8s 工作負載
（`/kubernetes_workloads/`），儀表板要把這兩類分開看。

Widgets：
```
┌ 決策趨勢（三線分開，不合併）──────────────┐ ┌ pd_qualifier 分佈 ──────┐
│ unknown / potentially_blocked / allowed   │ │ 0/1/2/3 各多少          │
└───────────────────────────────────────────┘ └─────────────────────────┘
┌ 待辦關係表（限定 rollout 範圍）────────────────────────────────────────┐
│ src_app → dst_app | dpt | proto | cnt 加總 | 首次/最後觀測 | src_href  │
└───────────────────────────────────────────────────────────────────────┘
┌ 來源無 href（抽樣 12.2%）─────────────────┐ ┌ 對外部位址的流量 ───────┐
│ PCE 認不出是哪個工作負載＝待確認清單      │ │ dst 非私有位址的對談     │
│ （多半是未納管，但不能直接等同沒有 VEN）  │ │ （含特殊用途位址與 IPv6）│
└───────────────────────────────────────────┘ └─────────────────────────┘
```
注意：Top-N 不等於完整清單，要標註並保留明細入口；
`cnt` 是取樣區間內的連線次數，`count()` 是紀錄數，兩者標題要寫清楚。

### 4.2 頁 2：政策與強制狀態變更（風險檢視的重點）

實測在直送裡抓到的真實例子：

```
workloads.update.success  duser=admin@lab.local
  changes: {"enforcement_mode": {"before": "selective", "after": "idle"}}
```

**強制模式被降級**——這是這份 log 能提供的最高價值風險訊號，而它藏在 `cs2` 的 JSON 裡。
做法：對 `workloads.update` / `sec_policy.*` 這幾類事件
`select_jsonpath(resource_changes)` 取出 `changes.enforcement_mode`。
`resource_changes` 是**陣列**，要對每個元素取 before/after 配對，不能只讀根層。

**重要限制**：PCE 對過大的 `resource_changes` 會分段（cs2 前 3,995 字元 + cs3 續段），
兩段仍放不下時會**把每個 entry 的 `changes` 整個丟掉**（見 `cef_pce.py:118` 附近的註解）。
也就是說「收到事件」不等於「拿得到 before/after」——大型政策提交很可能只剩物件清單。
儀表板要標示「內容不完整」並提供回查 PCE 的 `event_href`，否則 A1 會漏報而畫面看起來正常。

| Widget | 查詢 | 現值（7d） |
|---|---|---|
| 強制模式變更明細 | `event_class_id:workloads.update.success` 且有 enforcement_mode | 4 筆 |
| 政策提交（誰、幾點、改了幾個物件） | `event_class_id:sec_policy.*` | 1 筆 |
| 容器叢集政策套用 | `container_cluster.security_policy_applied.*` | 223 筆 |
| 標籤／規則異動 | `cat:audit_events` 且 `requestMethod:(PUT OR POST OR DELETE)` | — |

**實作後的補充（2026-09-23，graylog-ops `171e432`）**

- 上表的「4 筆」是 pipeline 上線（09-21）**之前**的全文搜尋結果，那些行沒有被解析，所以上線後的 7 天窗是 0——不是規則壞了。用 pipeline simulator 拿 09-20 的原始行重跑，規則 20 取得出 `enf_before=[selective]`、`enf_after=[idle]`。
- 規則 20 另取 `enf_workload`（`$..resource.workload.hostname`），否則明細只知道有人改了、不知道改了哪台。容器叢集的強制模式變更（`container_cluster.update.success`）沒有 hostname、`before` 也是空的，明細裡那一欄會是空白。
- `select_jsonpath` 取出的是陣列（`["idle"]`），查詢 `enf_after:idle` 照樣命中。
- 直送**有** `requestMethod`。但不排除工具噪音時 7 天 920 筆幾乎全是 system 的 `user.create_session.success`，套用 §4.3 的排除式後剩 169 筆。
- 分段的偵測用 `_exists_:resource_changes_2`；「整個丟掉 changes」那種情況仍然偵測不到，所以明細空白不代表沒有變更。
- audit 很稀疏，這兩頁預設 7 天；直送 audit 會重複，事件數並列 `card(event_href)`。

### 4.3 頁 3：存取與身分

| Widget | 查詢 | 現值（7d） |
|---|---|---|
| 登入失敗 | `event_class_id:user.login.failure` | 1 |
| API 驗證失敗 | `event_class_id:request.authentication_failed.failure` | 4 |
| 非 system 帳號活動 | `cat:audit_events AND NOT duser:system` | 164（24h） |
| 來源 IP 分佈 | `dst`（PCE 視角的對端） | — |

**VEN 相關的風險事件**（24h 實測就抓到，值得單獨一格）：

| 事件 | 意義 | 24h 實測 |
|---|---|---|
| `agent.tampering.success` | **VEN 防竄改觸發** | 2 行（1 個事件） |
| `lost_agent.found.success` | 失聯的 VEN 又回來了 | 10 行（5 個事件） |
| `system_task.inactive_ven_cleanup.success` | 系統清掉不活躍的 VEN | 1 |
| `agent.upload_existing_ip_table_rules.success` | VEN 回報既有 iptables 規則 | 4 |

這是 log 能提供的 VEN 訊號全部——**不足以取代 VEN 健康報表**（§3），但 `agent.tampering` 應該要告警。

排除工具自身噪音時只擋**成功的 session 建立／終止**：
`NOT (duser:system AND outcome:success AND event_class_id:user.create_session.success)`。
登入失敗、system 帳號的其他異動一律保留。

**實作後的補充（2026-09-23）**：VEN、容器叢集、驗證失敗這些已用 `event_class_id` 精準指定的格子只夾直送、不夾 `cat:audit_events`，和告警寫法一致，免得 `cat` 猜錯整格變 0。驗證失敗類有不少行沒有 `event_href`，只能看 count。上線當下 7 天：驗證失敗 2、非 system 活動 172、VEN 風險事件 5、防竄改 0。

### 4.4 先不要做的

- 以 `state` 算 enforcement 覆蓋率——分母不在 log 裡。
  代碼本身可用：本專案 `cef_pce.py:38` 的對照是
  `active→A`、`snapshot→S`、`closed→C`、`timed_out→T`、`new→N`（最後一項在原始碼標為假設）。
  實測抽樣 800 筆：S 83%、A 9%、T 5%、C 4%——絕大多數是 snapshot（取樣當下仍在的連線），
  所以「連線數」不能用紀錄數代替。原廠文件未列完整代碼表（已查 KB）。
- 以流量紀錄算「覆蓋率」——分母是工作負載清冊，不在 log 裡。
- 全域標籤圓餅、全域 Top IP 排行——不驅動任何動作。

---

## 5. 告警（Graylog OSS 只有 Filter & Aggregation，correlation 屬 Enterprise）

| # | 告警 | 條件 | 為什麼 |
|---|---|---|---|
| A1 | 強制模式降級 | pipeline 取出 `enf_after` 後，條件寫 `enf_after:(idle OR visibility_only)`。OSS 的告警只能過濾、不能比較兩個欄位，所以**不要寫成「after 比 before 弱」**；嚴格程度由強到弱是 full > selective > visibility_only > idle | 直接削弱分段 |
| A2 | 政策提交成功 | `event_class_id:sec_policy.create.success`（**要限定提交類型與 success**；只寫 `sec_policy*` 會把所有政策操作與失敗都當成提交） | 變更通知，附 `duser` 與 `commit_message` |
| A3 | **flow_blocked 首次出現** | `event_class_id:flow_blocked` count > 0（事件名是 `flow_blocked`，寫成 `flow_denied` 會永遠不觸發） | 目前恆為 0；一旦出現代表有人真的被擋了 |
| A4b | **VEN 防竄改** | `event_class_id:agent.tampering*` count > 0 | 有人動了主機上的 VEN 或防火牆規則 |
| A4 | 登入／API 驗證失敗突增 | `user.login.failure` OR `request.authentication_failed.failure`，**先用固定門檻**（建議 15 分鐘 ≥ 5 次起步，觀察兩週後再調） | 7d 只有 5 筆，沒有足夠樣本算基線；「> 基線」在 OSS 也做不出來 |
| A5 | 來源斷流 | 每個 input 各一條定義（查詢固定寫死該 input id），15 分鐘內筆數 = 0 | **不可用 group-by 主機桶**：資料消失時桶也跟著消失，永遠不會觸發 |
| A6 | CEF 解析失敗 | `cef_parse_failed:true` count > 0 | 只抓得到**進到 pipeline 才失敗**的行；codec 階段被丟掉的、索引失敗的，這條看不到——要另外用 §4.0 的量趨勢守 |
| A7 | FortiGate 出現 deny | 開啟 deny logging **之前**：`action:deny` count > 0（把「設定變了」當訊號）。開啟**之後**必須改寫：正常拒絕會持續存在，要限定來源、政策或方向並設異常門檻 | 見 §6.1 |

搜尋視窗要涵蓋取樣延遲 → 一律 ≥15 分鐘，用重疊視窗；
**grace period 只能抑制通知頻率，不能當去重，也做不出「首次出現」**——
「首次」要靠人看趨勢或另外記錄狀態。
告警用的時間欄位要講清楚：Graylog 的收件時間是 `gl2_receive_timestamp`，
`timestamp` 則可能已被解析成事件時間。**斷流告警一律用收件時間**，
否則來源時鐘偏移或事件延遲會被誤判成斷流。

---

## 6. FortiGate 防火牆維運儀表板（全新，取代 2023 content pack）

舊的 content pack 有 10 頁，其中 VPN / Multicast 7 天 0 筆、
DNS Filter 用 `eventtype:dns-query` 查（本機無此欄位，是查詢寫錯不是沒資料）、
IPS 7 天 5 筆。建議整頁重做，只留「防火牆維運該看的東西」。

### 6.1 先講三個實測發現（這些是建議，不是 widget）

這三項是**「Graylog 裡看不到」**，不是已證實的設備設定；要到 FortiGate 上確認後才能下結論。
但無論原因為何，現況就是這三個視角做不出來：

1. **`action:deny` 7 天 0 筆**——沒有「被擋了什麼」的資料。
   可能是隱含拒絕未開 logging、也可能是規則層面真的沒有拒絕。先去設備確認 logging 設定。
2. **`utmaction:block` 7 天 0 筆、webfilter 全是 `passthrough`**——看起來是監控模式，
   但 `passthrough` 也可能只代表該 profile 的動作設定；需在設備上核對 profile。
3. **`type:event` 只有系統類**（1,137 筆：perf-stats、DHCP、韌體更新、
   介面狀態變更 26 筆、更新失敗 12 筆），`subtype:user` 僅 3 筆——
   **管理者登入與組態變更沒有出現在這裡**。維運稽核要靠它，優先確認事件日誌的送出設定。

### 6.2 頁面

**頁 1 設備健康**
| Widget | 查詢 | 現值 |
|---|---|---|
| CPU / 記憶體趨勢 | `logdesc:"System performance statistics"` 取 `msg` 數值 | CPU 0–1%、記憶體 57% |
| 介面狀態變更 | `logdesc:"Interface status changed"` | 7d 26 筆 |
| 韌體／更新失敗 | `logdesc:"FortiGate update failed"` | 7d 12 筆 |
| 日誌量健康 | 每分鐘筆數 | ~240/分 |
| 記憶體日誌滿 | `logdesc:"Memory log full*"` | 7d 1 筆 ← 值得追 |

**頁 2 流量與政策（`subtype:forward`）**
| Widget | 內容 | 現值 |
|---|---|---|
| 介面矩陣 | `srcintf → dstintf` | internal→wan1 54%、SERVER→wan1 34%、internal→SERVER 7%（抽樣 1,000 筆） |
| 每條政策的 session 數與位元組 | `policyname`；bytes 要先確認本機的紀錄口徑——`accept`/`timeout` 也可能帶位元組，只取 `close`/`*-rst` 會少算，但把 start 與結束紀錄一起加又會重複。先用 `sessionid` 檢查同一 session 出現幾次再定 | lan_to_wan 33%、server_to_wan 19%（抽樣） |
| Top talkers | `srcname` + `srcip` 並列（只用 `srcname` 會把沒有主機名的合成一桶） | 抽樣 1,000 筆中 38 個不重複來源；**這是樣本裡的數字，不是設備總數** |
| 服務分佈 | `service` | HTTPS 40%、DNS 27%、SSL 16%（抽樣） |
| 連線重置／逾時 | `action:(client-rst OR server-rst OR timeout)` | 抽樣約 15%；RST/timeout 是正常行為的一部分，**看趨勢變化而不是絕對值** |

**頁 3 應用與風險（`subtype:app-ctrl`）**
| Widget | 內容 | 現值 |
|---|---|---|
| 高風險應用 | `apprisk:(critical OR elevated)` 依 `app` + `srcname` | critical 7d 270 筆（完整計數）；elevated 抽樣約 25% |
| GenAI 使用明細 | `appcat:GenAI` 列 `srcname` / `app` | 24h 20,486 筆（Claude、OpenAI.ChatGPT…） |
| 應用類別趨勢 | `appcat` | Network.Service 27%、unscanned 25%（抽樣） |
| 未掃描流量 | `appcat:unscanned` | 抽樣 25%。`unscanned` 可能是未套用 application control profile，**不必然等於 SSL 檢查未涵蓋**；要對照該政策的 profile 設定 |

**頁 4 管理平面（`subtype:local`）**
| Widget | 內容 | 現值 |
|---|---|---|
| 對防火牆本身的連線 | `dstip` = 防火牆介面 | 24h 25,049 筆 |
| 管理埠存取 | `dstport:(22 OR 443 OR 8443)` 依 `srcip` | HTTPS 佔 64% |
| 外部來源敲門 | `srcip` 非內網且排除自家 WAN IP | `114.35.37.162` 佔多數，但**已確認那是防火牆自己的 WAN IP**（`trandisp:snat` 的 `transip` 300/300 都是它），要排除後才看得到真正的外部敲門 |

---

## 7. ops 轉送要補的（已逐項查回原始碼，分清是「格式化沒寫」還是「上游沒有」）

先講結論：**`cef_pce` 格式化器該寫的都寫了**，缺的欄位是 traffic_flows API 根本沒回。
證據——實機 `.106` 的 `pce_traffic_flows_raw.raw_json` 最新一筆，全部的 key 只有：

```
caps, client_type, dst, dst_bi, dst_bo, flow_direction, network,
num_connections, policy_decision, seq_id, service, src, state, timestamp_range
```

| # | 欄位 | 格式化器 | 上游 API | 判定與建議 |
|---|---|---|---|---|
| 1 | `cn1=interval_sec` | 有（`cef_pce.py:295`，取 `flow["interval_sec"]`） | **無** | ~~可由 `timestamp_range` 相減算出~~ **不建議**（2026-09-23 實測）：直送的 `interval_sec` 是 PCE 的回報區間（500 筆裡 900／601／600／0 佔絕大多數），而 ops 的 `first_detected` 常等於 `last_detected`，相減多半是 0——兩者語意不同，填進同一個欄位名會誤導。維持不送 |
| 2 | `in` / `out` | 有（`cef_pce.py:279`，取 `dst_tbi`/`dst_tbo`） | **無**（只有 `dst_bi`/`dst_bo`） | PCE 的「Show Amount of Data Transfer」未啟用時本來就沒有 total bytes（已查 KB）。~~折衷：用 `dst_bi`/`dst_bo` 同時填 `in`/`out`~~ **不建議**（2026-09-23 實測）：直送的 `in`/`out` 是**累計總量**、`dbi`/`dbo` 是**區間增量**，152 筆有 `in` 的裡只有 102 筆兩者相等（例：`in`=198,864,860、`dbi`=263,044），snapshot 狀態幾乎不帶 `in`。ops 已經送 `cn2`/`cn3`（dbi/dbo），那才是兩路可比的欄位；`in`/`out` 維持不送 |
| 3 | `msg.pd_qualifier` | 有（`cef_pce.py:338`） | **無** | **API 不提供阻擋原因**。§4.1 那張分類表只能從直送做——這也是「直送為主」最實在的理由 |
| 4 | `msg.ddms` / `tdms` | 有（`cef_pce.py:331`） | **無** | 同上，API 無連線持續時間。次要 |
| 5 | `shost`/`dhost` 覆蓋率低（抽樣 22% / 2.7%，直送 82% / 41%） | 有（`cef_pce.py:308/316`，但需 `src.workload` 存在） | 部分 | API 只在該端是納管工作負載時回 `workload` 物件；未納管端就沒有主機名。**不是 bug，是資料本質** |
| 6 | flow 筆數只有直送的 0.7–31% | — | — | 聚合粒度差異，**不是漏送**。文件要寫明，避免被當成故障 |
| 7 | 帶 `+0000` 的 `rt` 會被 Graylog CEF input 整行丟棄 | 現行 `cef_pce` 用無時區毫秒格式，正確 | — | 改 `rt` 格式前必須實送一行驗收，不可只看 dispatch 狀態 |

補充：`state` 欄位上游回的是字串 `"snapshot"`，格式化器經 `_STATE` 轉成單碼後送出，
與直送的 `cs2=S` 對得上；此處無缺口。

| 8 | **長壽 flow 的後續增量不會再送** | `ingestor_traffic.py:307` 只對「新的 flow_hash」建立 SIEM dispatch 列；同一條 flow 之後 counters 被 upsert 更新（`:292`）時不會重新入列。**ops 看到的是每條 flow 第一次出現時的數值**，不是最終值 | 這是量差之外、**數值完整度**的缺口。**決定（2026-09-23）：標明「首見值」，不改 ingestor**。精確說是「送出當下的快照」：upsert 會把 `raw_json` 換成較新的一份，dispatcher 在送出時才讀，所以入列到送出之間的成長會帶上，送出之後的不會。已寫進 `docs/guide/siem.md` 與 Graylog 頁 0 的說明 |

補充兩點求嚴謹：
- 量差「不是 bug」只表示**目前設定沒有過濾**（`.106` 實測 `traffic_filter.actions=[]`、`traffic_pd=[]`）。
  `traffic_filter.py` 另有 allowed 抽樣器、`ingestor_traffic.py:145` 有達 max_results 上限時的二分補抓，
  兩者都可能造成缺漏；要完全排除漏送，得比對同窗的 flow 鍵集合，本次尚未做。
- 上表第 1–4 項的「上游無」原本只依最新一筆判定；2026-09-23 已在 `.106` 的
  `pce_cache.sqlite` 抽最新 80 筆＋最舊 40 筆（全表 58,371 筆）確認：沒有任何一筆帶
  `dst_tbi`/`dst_tbo`、`interval_sec`、`pd_qualifier`，`timestamp_range` 的
  `first_detected`/`last_detected` 則 120 筆都有。另外舊資料 40 筆裡有 24 筆帶
  `boundary_decision`——它可能對應 `pd_qualifier=1`（被 boundary 擋），是 #3 唯一可能的
  替代來源，尚未驗證語意。

audit 側以同一個 24 小時窗的 `event_href` 集合比對：交集 1,580、直送獨有 3、ops 獨有 10（視窗邊界時間差），
**無缺口**；`resource_changes` 也有正確帶出（已驗 `workloads.update.success`）。

**優先序（2026-09-23 修正）**：1、2 經實測**不做**（見表內）；3、4 要等 PCE 開功能或改用直送；8 已決定標明「首見值」（見表內）。

## 附錄：拿到 log 之後，先跑這五個查詢

解析尚未建好之前（§2.1），直送只有全文可查；這五條在**現況**就能跑：

```
1. 這批 log 裡有哪些事件類型？
   gl2_source_input:<直送 input id>            → 看 message 欄的 CEF 標頭
2. 有沒有人被真的擋下來？（分段是否已生效）
   message:flow_blocked                         → 目前 0；不是 0 就要看是誰
3. 開啟強制後會被擋的流量有多少？（上線前待辦）
   message:flow_potentially_blocked             → 24h 47,515 筆
4. 誰改了政策或強制模式？
   cat:audit_events AND requestMethod:(PUT OR POST OR DELETE)
   （ops stream 已有欄位；直送要等解析）
5. 防火牆有沒有擋掉什麼？
   gl2_source_input:<FortiGate input id> AND action:deny   → 目前 0，見 §6.1
```

解析建好之後，把第 1、3、4 條換成欄位查詢（`event_class_id:`、`act:`、`duser:`），
才能做聚合與告警。

## 8. 不在範圍／待確認

- `trafclass_code`（U/B/M = unicast/broadcast/multicast，見 `cef_pce.py:39`）與 `state` 的 `new→N` 一項，原廠文件無完整代碼表，已向 KB 查證，仍需向原廠確認。
- ~~`deviceDirection` 0/1 何者為 inbound~~ **已實測（2026-09-23）**：**1＝outbound（由來源端 VEN 回報），0＝inbound（由目的端 VEN 回報）**。直送裡只有來源端納管的 flow 1,091 筆全為 1、只有目的端納管的 351 筆全為 0；兩路共同的 845 組 flow 有 825 組值相同，不同的 20 組都是兩端皆納管、兩台 VEN 各報一次。與 `cef_pce.py` 的 `outbound → 1` 一致。
- ops 是否能補 `pd_qualifier`：取決於 traffic_flows API 是否回傳，尚未查證。
- ~~Graylog 升級~~ 已於 09-23 升到 7.1.9（目前最新穩定版；7.2 仍是 beta）。
- 保留期：目前單一 index set，30–40 天。若拆 flow/audit 兩個 index set，需重新估算。
