# 頻寬與流量計算基準：消除推測值

> 狀態：設計待使用者審閱。
> 本檔所有對現況的描述皆已對原始碼與生產快取資料查證；行號會漂移，以符號為準。

## 1. 要解決什麼

使用者 2026-08-23 的要求：「我需要確保所有跟流量和頻寬的計算不是用猜的」，並在得知
現行分母是硬編的 600 秒後裁定「全部一起改，我會重調告警門檻」。

## 2. 全面盤點（查證結果）

### 2.1 全 codebase 只有四處計算「速率」

以 `grep -rn "\* 8\.0\|\* 8 \|/ 600\|3600\|86400"` 掃過 `src/analyzer.py`、`src/report/`、
`src/pce_cache/`、`src/gui/`，位元組轉每秒位元的運算只有四處：

| # | 位置 | 分子 | 分母 | 判定 |
|---|---|---|---|---|
| 1 | `analyzer.py:257` `WindowDelta.mbps` | 兩次 cache 觀測的累計值相減 | `now - base.observed_at` 實測秒數 | **真量測**。唯一完全不含假設的速率 |
| 2 | `analyzer.py:305` `calculate_mbps` Priority-1 | `dst_dbo+dst_dbi` | `ddms` | 正確，但**在 async query 資料上不可達**（見 2.2） |
| 3 | `analyzer.py:317,324` `calculate_mbps` Priority-2 fallback | `dst_bo+dst_bi`（整段累計） | **硬編 600 秒** | **推測值。本案主要標的** |
| 4 | `csv_parser.py:301` `_estimate_bandwidth` | `bytes_total` | `last_detected - first_detected`，`clip(lower=1)` | 分母正確，但 `clip(lower=1)` 在 span==0 時捏造 1 秒 |

其餘涉及 bytes 的地方（`aggregator.py` 的 `bytes_total` 加總與 MAX 合併、
`calculate_volume_mb`、`num_connections`）**不含分母，不是推測值**——它們是 PCE 給的
數字的直接加總。本案不動。

### 2.2 為什麼 Priority-1 永遠走不到

- 官方（PCE Admin Guide）頻寬公式需要 `ddms`（區間）或 `tdms`（平均）。
- 官方原文：`"VENs send two attributes to the Syslog and fluentd output."`
  ——`ddms`/`tdms` 是 **Syslog／fluentd 專屬**，REST async query 的 JSON 不含。
- 原廠文件**沒有記載任何從 async 下載結果計算頻寬的替代公式**。
- 實測 `data/pce_cache.sqlite` 的 `pce_traffic_flows_raw`：`ddms`/`tdms`/`interval_sec`
  命中 0/500，`dst_bo` 命中 500/500。

`analyzer.py:317` 的 `flow.get("interval_sec", 600)` 中的 600 是官方 `interval_sec`
欄位的文件預設值（`"The default is approximately 600 seconds (10 minutes)"`），
不是憑空捏造。但該欄位在這條資料路徑上**永遠不存在**，所以預設值是唯一會走到的路。

### 2.3 真正的缺陷：分子與分母不同尺度

`dst_bi`/`dst_bo` 的語意在官方 async query schema 中**未定義**（microseg-kb 明確表示
「範例中出現；文件摘錄未說明其定義」，且不可與 syslog 的 `dst_tbi`/`dst_tbo` 等同）。
實測支持「自 `first_detected` 起的累計量」：

| span 區間 | n | median bytes | max bytes |
|---|---|---|---|
| <=600s | 2016 | 10,230 | 0.5 GB |
| 600s-1h | 250 | 22,050 | 2.7 GB |
| 1h-1d | 1532 | 67,850 | 2.96 TB |
| >1d | 820 | 142,140 | 13.2 TB |

若僅為單一 600 秒區間內的量，位元組量不應隨 span 成長四個數量級。最大單筆為
Prometheus → kubelet(10250/tcp)、`num_connections=2406`、`timestamp_range` 橫跨 2.5 天、
`dst_bi+dst_bo = 12.05 TB`——以 600s 為分母得 176,640 Mbps（176 Gbps，實驗室物理不可能），
以 span 為分母得 493 Mbps。全庫以 600s 為分母有 11 筆超過 10 Gbps；以 span 為分母 0 筆。

**結論：把「數天的累計量」除以「一個取樣區間」，得到的不是誤差，是沒有物理意義的數。**

### 2.4 同一份報表現在有兩種互不相容的頻寬定義

`bandwidth_mbps` 欄在報表裡的來源依 parser 而異：API 走 `calculate_mbps`（600s 假分母），
CSV 走 `_estimate_bandwidth`（span 分母）。`mod11_bandwidth` 與 `_fmt_bw` 一視同仁地顯示。
同一條 flow 換個資料來源就換一個數字，差距可達數百倍。

### 2.5 附帶發現（命名，非計算）

`rules_engine._b008_bandwidth_anomaly` 名為 "High Bandwidth Anomaly"，實際運算對象是
`bytes_total` 的百分位數——那是**總量**異常，不是頻寬異常。

### 2.6 附帶事實（資料可得性）

實測 5000 列中 2955 列（59%）bytes 為 0。官方：byte 欄位需 `Enhanced Data Collection`；
`dst_dbo` 另需 `Byte Count Premium Feature`。這不是計算缺陷，但意味 bandwidth／volume
排序有相當比例在排 0，應在文件說明。

## 3. 決策

**單一定義，全路徑一致。** 速率一律為

```
Mbps = (dst_bo + dst_bi) × 8 ÷ (last_detected − first_detected) ÷ 1e6
```

這不是新發明的算法，而是官方 `tbo / tdms`（平均頻寬）公式，以 `timestamp_range` 的
觀測時距作為 `tdms` 的估計。基準註記為 `(Avg)`。

`ddms`/`tdms` 存在時（syslog／fluentd 來源、或帶該欄位的 CSV）維持 Priority-1／
Priority-2 原路徑不變——那些是真實的持續時間，優於估計。

**`span == 0` 時給下界，不給點值。** 實測 4618 筆有 bytes 的列中，1883 筆（40.8%）
`first_detected == last_detected`。這**不是資料缺漏**——PCE 給的資料是完整的，缺的是
小數點以下的時間。查證那群列的長相：`num_connections` 中位數為 1（最大 21）、bytes
中位數 9.8 KB、state 以 `closed`/`timed out` 為主，是**單一短連線在同一秒內開關**。

因此我們確知兩件事：bytes 的值，以及**持續時間必定小於 1 秒**（兩個時間戳截斷到同一
秒 ⟹ 真實時距 ∈ [0, 1)）。所以

```
真實速率 > (dst_bo + dst_bi) × 8 ÷ 1s
```

是一句**可以證明為真的陳述**，不是估算。這類列一律以「≥ X Mbps」呈現，不呈現點值。

實測下界分佈（n=1883）：中位數 0.079 Mbps、P90 1.502、P99 99.383、最大 4077.972；
下界 > 100 Mbps 者 17 筆、> 1000 Mbps 者 7 筆。不給下界等於把這些高速短連線從頻寬
告警中整批移除。

`csv_parser` 現行的 `clip(lower=1)` 移除——它算出的正是這個下界，但**當成點值呈現**，
把「至少 4078 Mbps」說成「就是 4078 Mbps」。同一個數字，錯的是它宣稱的確定性。

**量化誤差對 `span > 0` 的列可忽略。** 時間戳為秒解析度，真實時距 ∈ (span−1, span+1)。
實測分佈是雙峰的：span==0 佔 40.8%、span>=60 佔 59.1%、**中間 1–59 秒只有 5 筆
（0.1%）**。故 span >= 1 時直接用 span 當分母，誤差上界 <= 2%，不另做處理。

**告警路徑的三分支。** 本 codebase 已有 `_basis_decision` / `_window_delta` 的守門設計：
推導不出量測基準時回傳 `reason`，規則**不評估**、計數、並在輸出中說明
（`analyzer.py:1770-1775` 的 `info["reasons"]`）。速率的處理併入同一機制：

| 情況 | 行為 |
|---|---|
| 有點值（span >= 1） | 照常比對門檻 |
| 只有下界，且**下界 > 門檻** | **觸發**——真值必定更高，不可能因此誤報 |
| 只有下界，且下界 <= 門檻 | 無法判定 → 進守門，計數並回報，新增一個 reason |

**不得靜默當 0**——0 永遠小於任何正門檻，等於規則悄悄失效。

## 4. 設計

### 4.1 `calculate_mbps`（`src/analyzer.py`）

Priority-2 的 `tdms` 取值改為：`tdms` 欄位存在則用之；否則由 flow 的
`timestamp_range.first_detected` / `last_detected` 求時距（毫秒）。兩處時間戳的讀取
比照 `flow_aggregation_start` 既有做法：頂層與巢狀 `timestamp_range` 兩處都認。

時距 == 0 → 回傳**下界**（以 1 秒為分母）並標記為下界，呼叫端據此呈現「≥」。
時間戳缺漏 → 回傳「算不出來」（實測 0 筆，但不可假設永遠如此）。移除
`flow.get("interval_sec", 600)` 這條假設分母，以及 `(Avg est.)` 註記。

回傳型別需區分三種狀態——點值／下界／算不出來。現行回傳為
`(val, note, bytes, denom)` 四元組，`note` 已是基準註記的既有載體
（`(Interval)`/`(Avg)`/`(Window)`），沿用它承載這個區分，不新增第五個元素。

`calculate_volume_mb` **不動**：它沒有分母。

`flow_deltas.cumulative_metrics` **不動**：它取的是分子欄位，優先序與 Priority-2 分子
逐字一致（該函式 docstring 明載此約束），本案只改分母。

### 4.2 呼叫端

| 呼叫端 | 改動 |
|---|---|
| `analyzer.py:1725` 告警引擎 | 依 §3 的三分支：點值照常比對；下界 > 門檻即觸發；下界 <= 門檻進守門並計數 |
| `analyzer.py:2434` `query_flows` | 下界列的 `formatted_bandwidth` 帶「≥」；算不出來顯示不可得，不顯示 0.00 Mbps |
| `analyzer.py:2632` 規則模擬 | 同告警引擎的三分支，模擬與引擎必須同基準（該處註解已載明此約束） |
| `report/parsers/api_parser.py:57` | 承接新回傳值，保留下界／點值的區分至報表欄 |
| `report/parsers/csv_parser.py:301` | 移除 `clip(lower=1)`：同一個數字改標為下界；時間戳缺漏 → NaN（`_fmt_bw` 已將 NaN render 為 `—`） |
| `gui/routes/dashboard.py:737` top10 | 依 bandwidth 排序時，下界列以其下界參與排序並標「≥」；算不出來的列不參與 |

### 4.3 顯示

三種狀態必須在畫面上可區分：

| 狀態 | 呈現 |
|---|---|
| 點值 | `493.30 Mbps (Avg)` |
| 下界 | `≥ 4077.97 Mbps` |
| 算不出來 | `—` |

`format_unit(0, 'bandwidth')` 目前回 `"0.00 Mbps"`，與「真的是 0」無法區分——
「算不出來」一律 render 為 `—`（`_fmt_bw` 已有此行為，`format_unit` 需比照）。
「≥」的前綴不得只靠 note 字串拼接後被下游截斷，需有測試釘住它在各輸出格式
（GUI、CLI 表格、HTML 報表、XLSX）都存活。

### 4.4 告警門檻的遷移（交付物）

改動前後各跑一次同一份 traffic 資料，輸出比對表：每條 bandwidth 規則的
`max_val` 改動前／改動後、是否改變觸發狀態、因下界未超過門檻而進守門的 flow 數、
以及因時間戳缺漏而完全無法評估的 flow 數。
使用者依此表重設門檻。此表是本案的交付物之一，不是附帶產物。

### 4.5 命名修正

`_b008_bandwidth_anomaly` 的 rule_name 與文案改為反映其實際運算對象（總量百分位），
規則 ID `B008` 不變（外部可能已引用）。

## 5. 測試

- `calculate_mbps` 單元測試：有 `ddms` 走 Priority-1；無 `ddms` 有 span 走 span 分母且
  note 為 `(Avg)`；span==0 回下界標記；時間戳缺漏回「算不出來」；巢狀與頂層
  `timestamp_range` 兩種形狀都認
- **守門測試：`interval_sec` 與字面值 600 不得再出現在 `calculate_mbps` 中**（比照本
  專案既有的命名守門寫法，用集合相等而非子字串）
- 告警路徑三分支各一條：下界 > 門檻 → 觸發；下界 <= 門檻 → 進守門並計數；點值照常比對。
  且**不**被當成 0 評估
- 下界不得退化為點值：斷言下界列的輸出帶「≥」標記，且與同值的點值列可區分
- `csv_parser`：span==0 回**標記為下界**的值（數值與現行相同，改變的是它宣稱的確定性）；
  時間戳缺漏才回 NaN
- 顯示：算不出來 render 為 `—`，與真值 0 可區分
- 迴歸：以真實快取樣本跑 §4.4 的比對表，確認改動前後的差異全部可用「分母改變」解釋

## 6. 本設計不處理

- **volume 與 connections 的計算**：它們沒有分母，不是推測值
- **PCE 端的資料可得性**（Enhanced Data Collection／Byte Count Premium Feature 是否開啟）
- **告警門檻的實際數值**：由使用者依 §4.4 的比對表重設
- **改用 syslog／fluentd 取得 `ddms`/`tdms`**：那是資料管線的變更，範圍遠大於本案

---

## 附錄 A：Codex 對抗式審查與真機檢驗（2026-08-24）

### A.1 已接受並待修的三條

1. **門檻相等時應觸發。** §3 寫「下界 > 門檻」才觸發是錯的：真實速率**嚴格大於**下界，
   故下界 == 門檻時真值必定超過門檻，應觸發。改為 `>=`，否則製造一個可確定判斷卻
   故意漏掉的告警。
2. **量化誤差的敘述錯誤。** §3 寫「span >= 1 誤差上界 <= 2%」不成立：兩個時間戳截斷後
   相差 1 秒，原始事件可能落在 `.999` 與次秒的 `.001`，真實時距僅 0.002 秒，用 1 秒當
   分母會低估約 500 倍。**改採統一規則**：一律回報 `>= bytes×8 ÷ (span+1)`。span==0 時
   即原本的 `>= bytes×8/1`；span 很大時下界與點值在顯示精度內重合。一條規則，0 不再是特例。
3. **報表統計未納入設計。** `mod11_bandwidth.bandwidth_analysis` 直接以數值欄計算
   max/mean/P95，HTML 與 XLSX 當點值輸出；逐列的「>=」在分析階段就消失。當相當比例的列
   是下界時，**那些統計量本身也不是點值**。§4.2 的呼叫端表需加入 `mod11_bandwidth` 與
   exporters，並定義這些統計要標為下界或不可得。

### A.2 未解決：`dst_bi`/`dst_bo` 的語意仍是推論，不是證明

Codex 的 P1 指出：本設計仍以官方未定義的 `dst_bo`/`dst_bi` 搭配「`timestamp_range` 等同
`tdms`」的假設在重建公式；§2.3 的 span 分桶表與物理合理性是**強證據**，但不構成證明。
若 `dst_bo` 實為區間值，則所有 API 頻寬系統性算錯，且 span==0 的「下界」也不成立。

**設計的決定性檢驗：** `pce_traffic_flow_obs` 存了同一 `flow_hash` 跨輪詢的累計計數器。
累計語意 → 單調遞增；區間語意 → 上下跳動。

**2026-08-24 真機執行結果：無法判定，因為該表沒有可用的位元組資料。**

| 指標 | 測試機（172.16.15.106）實測 |
|---|---|
| `pce_traffic_flow_obs` 列數 | 4,838 |
| 其中 `bytes_in+bytes_out > 0` | **0** |
| 相異 `flow_hash` | **27** |
| 觀測時間範圍 | 2026-08-23 10:37 → 16:35 |
| `pce_traffic_flows_raw` 列數 | 34,357 |
| 其中 bytes > 0 | 1,671（**4.9%**） |

三個推論：

1. **P1 仍未解決。** 要判定需要帶位元組的連續觀測。可行途徑：對部分 workload 開啟
   `Enhanced Data Collection`（PCE 端設定，需使用者決定），或取得同一 PCE 的
   syslog/fluentd 輸出與 async 結果對照（syslog 帶 `tbi/tbo/tdms`，可直接驗證等價性）。
2. **告警路徑的 `WindowDelta` 在這台機器上實質從未生效。** 它需要帶累計計數器的基準觀測，
   而 obs 表沒有任何一列帶位元組。也就是說本 codebase 裡「唯一真量測的速率」在真機上
   算不出來，bandwidth/volume 規則實際上一路退回原始值（假分母）或守門。
   **這是獨立於本 spec 的既有問題，需另案查證**（為何 obs 只追蹤 27 條 flow？）。
3. **4.9% 這個比例讓 bandwidth/volume 排序的意義存疑。** 我在開發機快取上量到的是 41%；
   真機是 4.9%。無論分母怎麼修，排序的絕大多數列都在排 0。

**在 P1 解決之前，本 spec 不進入實作。**
