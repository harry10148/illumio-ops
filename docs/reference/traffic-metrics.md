---
title: 流量指標與 PCE API 的取值邏輯
audience: [developer, operator]
version: 4.1.0
last_verified: 2026-08-24
verified_against:
  - src/analyzer.py
  - src/api/traffic_query.py
  - src/pce_cache/ingestor_traffic.py
  - src/pce_cache/flow_deltas.py
  - src/pce_cache/archive_query.py
  - src/report/parsers/api_parser.py
  - src/report/parsers/csv_parser.py
  - src/report/analysis/mod11_bandwidth.py
  - src/siem/formatters/cef.py
---

# 流量指標與 PCE API 的取值邏輯

本文說明「一條 flow 的頻寬／流量／連線數是怎麼來的」，以及頻寬數字**現在有三種狀態**——
點值、下界、算不出來——為什麼會有這三種狀態、以及畫面上怎麼分辨它們（§5.2）。給未來要
動這塊的人：先讀 §6，那裡有可以自己重跑一次的查證指令——不要相信本文，去驗。

## 1. 流量資料的三個來源

| 來源 | 取得方式 | 程式進入點 |
|---|---|---|
| PCE 即時查詢 | `POST /api/v2/orgs/{org}/traffic_flows/async_queries` 非同步查詢，完成後下載結果 | `src/api/traffic_query.py` 的 `execute_traffic_query_stream` |
| 本機 cache | 排程把上述查詢的結果寫進 `pce_traffic_flows_raw`，查詢時直接讀 | `src/pce_cache/ingestor_traffic.py` |
| 封存日檔 | cache 的列每日匯出成 `<source>-YYYY-MM-DD.jsonl(.gz)`，查詢時串流掃描 | `src/pce_cache/archive_query.py` |

**三者的原始資料是同一份**：封存匯出自 cache，cache 匯入自 async query。所以
async query 回傳什麼欄位，決定了三條路徑各自能算出什麼。

`Analyzer._fetch_query_flows`（`src/analyzer.py`）依操作者選的 `data_source` 決定走哪條，
回應的 `actual_source` 標明實際走了哪條（`cache` / `api` / `mixed` / `archive`）。

## 2. async query 實際回傳哪些欄位

實測本專案快取中的 `raw_json`（PCE 25.2，org 1）：

```
boundary_decision, caps, client_type, dst, dst_bi, dst_bo, flow_direction,
icmp_code, icmp_type, network, num_connections, policy_decision, seq_id,
service, src, state, timestamp_range, transmission
```

**沒有** `ddms`、`tdms`、`interval_sec`、`dst_dbi`、`dst_dbo`、`dst_tbi`、`dst_tbo`。
這一點是後面所有問題的根源。

## 3. 官方的頻寬公式，以及為什麼我們用不了

Illumio PCE Administration Guide 給兩條公式：

- 區間頻寬 = `dbo / ddms`（`ddms` = Delta flow duration in milliseconds）
- 平均頻寬 = `tbo / tdms`（`tdms` = Total flow duration in milliseconds）

官方原文明確指出這些欄位的歸屬：

> "VENs send two attributes to the Syslog and fluentd output. These attributes
> describe the flow duration and are appended to the flow data."

也就是 `ddms`/`tdms` 是 **Syslog／fluentd 專屬**，REST async query 不送。
原廠文件**沒有記載任何從 async 下載結果計算頻寬的替代公式**。

## 4. `dst_bi` / `dst_bo` 的語意

官方 async query 的 schema **未定義**這兩個欄位（範例中出現，但無說明）。經 PCE 自身的
syslog 輸出證實其語意（查證方法見 §6.2）：

- **`dst_bi`/`dst_bo` 是持續累加的計數器**，對應 CEF 的 `in`/`out`（= syslog 的
  `dst_tbi`/`dst_tbo`），不是單一取樣區間內的量
- 官方對 `dst_tbi` 的字面定義「total ... **in the latest sampled interval**」描述的是
  「該筆紀錄發出時的累計值」，**不是**「累計範圍限於該區間」——實測直接否證後者
- syslog 另有 `dbi`/`dbo`（該區間的增量）與 `interval_sec`（取樣區間長度，實測約 600–605 秒）

**未直接證實**的是「累加的起點恰為 `timestamp_range.first_detected`」——syslog 紀錄不帶
`first_detected`。以 `last_detected - first_detected` 作為時距是目前可得的最佳估計，
其誤差方向為「若真實起點晚於 `first_detected`，分母偏大、速率偏低估」，偏保守。

## 5. 目前的計算方式與其缺陷

### 5.1 連線數與流量：可信

- **連線數**：直接取 `num_connections`，PCE 給什麼就是什麼，無推導
- **流量（volume）**：`calculate_volume_mb`（`src/analyzer.py`）取 `dst_bo + dst_bi`，
  純加總、無分母，因此**不是推測值**

  但有一個已知缺陷：counter 不存在時它回 `0.0`，下游印成 `0.00 MB (Total)`，
  把「沒量到」講成「量到零」（見 §5.3）。

- **cache 端的合併**：`ingestor_traffic` 對同一 `flow_hash` 的重複匯出取 MAX
  （`_VOLATILE = ("last_detected", "bytes_in", "bytes_out", "flow_count")`）；
  封存查詢端由 `archive_query.merge_row` 以同樣規則在查詢時重現。**渲染封存列時，
  指標必須取自 `merge_row` 的合併值，不可從 `raw` 重算**——`raw` 只是最新的單一快照，
  用它會悄悄把合併撤銷、重現低估。

### 5.2 頻寬：三種狀態，不再假設一個分母

舊版 `calculate_mbps` 有個從未被踩過的分支：`(dst_bo + dst_bi) / tdms`，`tdms` 缺時分母
改用 `flow.get("interval_sec", 600)`。因為 §2 的欄位清單裡 `ddms`/`tdms`/`interval_sec`
一個都沒有，這條路徑上分子永遠是「整段 `timestamp_range` 的累計量」、分母永遠是硬編的
600 秒——兩個不同時間尺度相除。實測後果：最大單筆（Prometheus → kubelet(10250/tcp)、
`num_connections=2406`、跨 2.5 天、`dst_bi+dst_bo = 12.05 TB`）算出 176,640 Mbps
（176 Gbps），該實驗室物理不可能；因為分母對每一列都是同一個常數，依 bandwidth 排序與
依 volume 排序的順序完全相同。這條路徑已移除。

`calculate_mbps`（`src/analyzer.py`）現在回傳三種狀態之一，仍以既有的 `note` 欄位承載：

| 狀態 | 何時發生 | 分母 | `note` | 畫面呈現 |
|---|---|---|---|---|
| **點值** | 真的有 `ddms`（Priority-1）或 `tdms`（Priority-2）——本工具實際使用的 async query 路徑目前不會出現，但欄位存在時仍照官方公式走 | `ddms` 或 `tdms` | `(Interval)` / `(Avg)` | `493.30 Mbps (Avg)` |
| **下界** | 無 `ddms`/`tdms`，改用 flow 自己的 `timestamp_range`（Priority-3，本工具實際會走到的路） | `span + 1` 秒——時間戳是秒解析度，真實時距落在 `(span-1, span+1)`，`span+1` 保證**真實速率只會更高，不會更低** | `BOUND_BASIS_NOTE = "(>=)"` | `≥ 493.30 Mbps` |
| **算不出來** | 沒有位元組，或時間戳缺漏／不可解析／倒置，或算出非有限值（例如欄位字面值 `"nan"` 污染了分子） | — | `""` | `—`，絕不是 `0.00 Mbps` |

「下界」不是估計、是可證明的陳述：分子是那段時距內的累計量，分母取這段時距的上界
（`span + 1`），所以算出來的值**不可能大於真實速率，只可能等於或小於它**。

告警引擎、規則模擬與 `query_flows` 三個呼叫端共用同一套三分支：

- 點值：照常與門檻比較
- 下界，且下界 **`>=` 門檻**：觸發——真實速率必定更高，不可能因此誤報
- 下界，且下界 `<` 門檻：**無法判定**，規則不評估，計入守門計數並在輸出說明原因
  （`reason` 之一，比照本工具既有的守門回報機制）
- 算不出來：一律進守門計數，**絕不當成 0** 評估——0 會被任何正門檻判定為「未觸發」，
  等於規則悄悄失效

`report/parsers/api_parser.py` 與 `report/parsers/csv_parser.py`（原本各自定義、互不相容，
見舊版 §5.5）現在共用同一條公式：`bytes_total × 8 ÷ (span + 1)`，`span == 0` 時視為下界，
不再是 `csv_parser` 原本的 `clip(lower=1)` 把下界說成點值。`mod11_bandwidth.bandwidth_analysis`
的統計量（max/mean/P95）在其輸入族群含有任何一筆下界時，統計量本身也標記為下界——
order statistics 保序，含下界的族群其統計量同樣只會被低估，不會被高估。

**真機量測（2026-08-24，appliance 快取，1 條 bandwidth 規則、22,478 筆 flow）**：
舊分母（600 秒）算出的 Max 為 138,792.52 Mbps；新分母（span+1）算出的 Max 為
1,025.56 Mbps——差 135 倍。同一次量測也曝露一個與本案改動無關、但操作者需要知道的
事實：22,478 筆裡只有 1,239 筆（5.5%）算得出速率，其餘 21,239 筆（94.5%）沒有位元組
counter，從第一天就不可得——不是本次改動造成的覆蓋率下降，而是舊分母把「無法量測」
偽裝成一個看似合理的數字，掩蓋了這個缺口。查證方法見 §6.3。

### 5.3 「沒有 counter」是正常狀態，而且分辨不出來

不是每條連線都有位元組 counter，這是 PCE 的正常行為（需 `Enhanced Data Collection`；
`dst_dbo` 另需 `Byte Count Premium Feature`）。

**async query 從不省略這兩個欄位，一律送 0**（實測 20,000 列，缺欄位 0 筆），所以
**單看數值無法區分「未量測」與「量測結果為零」**。

`state` 與 counter 有無**相關，但不是可靠的判準**。兩個環境的實測（皆只看兩端為
managed workload 的流量）差異很大：

| `state` | PCE A（.130 真實流量） | PCE B（開發機快取樣本） |
|---|---|---|
| `active` | 58.2% | 65.0% |
| `timed out` | 62.0% | 64.6% |
| `closed` | 89.5% | 66.7% |
| `snapshot` | **7.5%** | **62.6%** |

`snapshot` 在兩邊差了八倍。**不要拿 `state` 當「有沒有量到」的判斷式**——它只能當粗略的
期望值參考。目前**沒有**任何欄位能在 async query 的資料上乾淨地區分「未量測」與
「量測到零」；syslog 路徑則可以（無 counter 時 `in=`/`out=` 整個欄位不出現）。

實務結論：計算端遇到 `bytes == 0` 只能一律當作「不可得」處理，不要試圖分辨。
這對 volume 是保守的（少報一筆零流量，不會誤報數字），對 bandwidth 是必要的。

因此「沒有頻寬」必須是第一級的正常顯示狀態。封存查詢已如此處理：`Analyzer._shape_traffic_row`
對封存列傳 `bw_val=None`，**不寫入** `max_bandwidth_mbps`/`formatted_bandwidth`，
讓畫面顯示「—」而不是看似量測到的 0。

### 5.4 唯一真正量測的速率：`WindowDelta`

`WindowDelta.mbps`（`src/analyzer.py`）取兩次 cache 觀測的累計值相減、以實際經過秒數為分母，
標記 `(Window)`。這是本 codebase 裡唯一不含假設的速率。

但它只用在**告警引擎與規則模擬**，查詢與報表路徑沒有用它。而且它依賴
`pce_traffic_flow_obs` 有帶位元組的連續觀測——若該表的列位元組皆為 0（環境未開 EDC，
或當下流量都是 `snapshot`），它算不出東西，規則會退回原始值或守門。

### 5.5 報表 parser：現在共用一個定義

`bandwidth_mbps` 欄過去依 parser 而異——`api_parser.py` 呼叫 `calculate_mbps`（600 秒假
分母），`csv_parser.py` 自己的 `_estimate_bandwidth` 用 `bytes_total × 8 ÷ (last - first)`
且 `clip(lower=1)`。同一條 flow 換個資料來源就換一個數字，差距可達數百倍——這是舊有的
不一致，不是本案造成的。

現在兩者用同一條公式（§5.2 的下界公式：`bytes_total × 8 ÷ (span + 1)`）。
`csv_parser._estimate_bandwidth` 的 docstring 明載這個約束——PCE CSV 匯出從不帶
`ddms`/`tdms`，因此永遠是 §5.2 表格裡的「下界」狀態；`span == 0` 或時間戳不可解析時回
NaN，render 為 `—`，不再是捏造的 1 秒分母。

## 6. 自己驗一次

### 6.1 async query 到底回什麼

```bash
./venv/bin/python - <<'PY'
import sqlite3, json, collections
c = sqlite3.connect("file:data/pce_cache.sqlite?mode=ro", uri=True)
keys, hit = collections.Counter(), collections.Counter()
for (r,) in c.execute("select raw_json from pce_traffic_flows_raw limit 500"):
    d = json.loads(r)
    keys.update(d.keys())
    for k in ("ddms", "tdms", "interval_sec", "dst_bo", "dst_tbo"):
        if d.get(k) not in (None, ""):
            hit[k] += 1
print("欄位:", sorted(keys))
print("命中:", dict(hit))
PY
```

### 6.2 證明 `dst_bi`/`dst_bo` 是累計值

需要 PCE 直送 syslog 的收集端（本實驗室為 Graylog，input `illumio`，SyslogUDPInput:5514）。
CEF flow_summary **同一筆紀錄同時帶累計與增量**：

```
in=72533 out=92590            <- 累計
cn2=82  cn2Label=dbi          <- 該區間增量
cn3=104 cn3Label=dbo
cn1=601 cn1Label=interval_sec
```

取回報多次的長命 flow，比對「累計值的相鄰差」與「該次的 `dbi+dbo`」。累計語意 →
兩者相等；區間語意 → 不相等。2026-08-24 實測四條 flow、三十餘次回報，**每一次都相等**：

```
23:40:57  累計=595,031,628  區間增量=159,452
23:45:57  累計=595,189,660  區間增量=158,032   差值 158,032 == 增量
23:50:57  累計=595,340,500  區間增量=150,840   差值 150,840 == 增量
```

### 6.3 舊分母 vs 新分母：差多少

`scripts/bandwidth_basis_diff.py` 把已退役的舊公式（bytes × 8 ÷ 600 秒，逐字內嵌在
腳本裡，因為 `analyzer.py` 已不再含有它）與現行公式（bytes × 8 ÷ (span+1)）對同一批
快取資料各跑一次：

```bash
./venv/bin/python scripts/bandwidth_basis_diff.py --db data/pce_cache.sqlite
```

規則的挑選與 flow 的比對重用即時規則引擎本身的邏輯（`Analyzer.rule_enabled()` /
`_match_flow_filters`）——停用的規則不比對，每條規則只吃它自己的 port／來源目的／
policy decision 會命中的 flow，不是整個快取庫。逐條 bandwidth 規則印出：兩種分母各
自的 Max、是否改變觸發狀態、以及 §4.4 要求的兩個獨立計數——多少筆 flow 因新分母算出
的下界未達門檻而進守門（`Bound<Thr`）、多少筆因時間戳缺漏或位元組不可得而完全無法評
估（`NoMeasure`）。觸發判定比照引擎：舊分母只曾產生點值，用嚴格 `>`；新分母對點值同
樣用 `>`，只有可證明的下界才用 `>=`——不會對兩種分母都用 `>=` 而聲稱一個引擎不會真的
觸發的結果。舊分母能算但新分母算不出來的 flow（例如時間戳倒置）不會被悄悄丟出兩邊的
Max，會被計進 `flows_regressed_to_unevaluable`。

**這個工具不模擬的東西**：即時引擎的 window-basis 抑制（bucket-basis guard）需要連續
的 cache 觀測才能推導出視窗增量，這份離線、單一快照的比對沒有那個歷史可用。腳本改為
針對每條規則回報「命中的 flow 裡有多少筆自己的時間跨距已經超過該規則的
`threshold_window`」，當作一則警示（`flows_span_exceeds_window`）——命中數非零時，即
時引擎當下可能推導出視窗增量而正常評估，也可能整條規則整個 cycle 被抑制，這份比對表
無法區分是哪一種，「觸發改變：否」不能當作保證，須另外核對即時行為或監控系統自己的
日誌／meta-alert。

輸出的數字取決於你當下快取裡有什麼資料——`data/pce_cache.sqlite` 是本機開發快取，
內容會隨排程同步而變。§5.2 引用的「135 倍、94.5% 不可得」是 2026-08-24 對一份有
22,478 筆 flow 的 appliance 快取跑出來的結果；拿自己的快取重跑，方向（新 Max 遠小於
舊 Max、且相當比例的 flow 沒有可算的速率）應該一致，絕對數字不會相同。門檻怎麼重設，
見腳本輸出的比對表——這是本案交給操作者的交付物，不是附帶產物。

### 6.4 counter 覆蓋率（依 `state`）

```bash
./venv/bin/python - <<'PY'
import sqlite3, json, collections
c = sqlite3.connect("file:data/pce_cache.sqlite?mode=ro", uri=True)
agg = collections.defaultdict(lambda: [0, 0])
for (r,) in c.execute("select raw_json from pce_traffic_flows_raw"):
    d = json.loads(r)
    if not ((d.get("src") or {}).get("workload") and (d.get("dst") or {}).get("workload")):
        continue                      # 只看兩端皆 managed 的流量
    a = agg[d.get("state")]
    a[0] += 1
    if (d.get("dst_bi") or 0) + (d.get("dst_bo") or 0) > 0:
        a[1] += 1
for st, (tot, nz) in sorted(agg.items(), key=lambda x: -x[1][0]):
    print("%-12s 列數=%-6d bytes>0=%-5d (%.1f%%)" % (st, tot, nz, 100 * nz / tot if tot else 0))
PY
```

## 7. 一句話總結

**連線數與流量可信；頻寬看 note。** `(Interval)`/`(Avg)` 是點值，`(>=)`（畫面上顯示為
`≥`）是可證明的下界、真值只會更高，`—` 是算不出來、不是零。三者不可混為一談——尤其
不要把下界或算不出來當成點值拿去比大小或算平均，`mod11_bandwidth` 的統計量已示範怎麼
把這個區分帶到聚合層。門檻怎麼重設見 `scripts/bandwidth_basis_diff.py`
（§6.3）；設計全文見 `docs/superpowers/specs/2026-08-23-bandwidth-basis-design.md`。
