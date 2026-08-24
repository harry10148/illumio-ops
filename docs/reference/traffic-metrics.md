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
  - src/siem/formatters/cef.py
---

# 流量指標與 PCE API 的取值邏輯

本文說明「一條 flow 的頻寬／流量／連線數是怎麼來的」，以及為什麼**頻寬目前算出來的數字
不能當真**。給未來要動這塊的人：先讀 §6，那裡有可以自己重跑一次的查證指令——不要相信
本文，去驗。

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

### 5.2 頻寬：目前的數字沒有物理意義

`calculate_mbps`（`src/analyzer.py`）有兩條路：

1. `(dst_dbo + dst_dbi) / ddms` → 真實區間速率，標 `(Interval)`
2. `(dst_bo + dst_bi) / tdms` → 平均速率；**`tdms` 缺時分母改用
   `flow.get("interval_sec", 600)`**，標 `(Avg est.)`

因為 §2 的欄位清單裡 `ddms`/`tdms`/`interval_sec` 一個都沒有，**第一條永遠走不到，
第二條的 600 秒是唯一會用到的分母**。

於是分子是「整段 `timestamp_range` 的累計量」，分母是「一個取樣區間」——兩個不同時間尺度
相除。實測後果：

- 最大單筆：Prometheus → kubelet(10250/tcp)、`num_connections=2406`、跨 2.5 天、
  `dst_bi+dst_bo = 12.05 TB` → 算出 **176,640 Mbps（176 Gbps）**，該實驗室物理不可能
- 全庫 4,618 筆有位元組的列中，11 筆超過 10 Gbps；改以 `timestamp_range` 時距為分母則 0 筆，
  最大 493 Mbps
- 因為分母對每一列都是同一個常數，**依 bandwidth 排序與依 volume 排序的順序完全相同**
  （2,000 筆全量比對一致）

**修法設計見** `docs/superpowers/specs/2026-08-23-bandwidth-basis-design.md`，尚未實作。

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

### 5.5 報表 parser 的兩套定義

`bandwidth_mbps` 欄在報表裡的來源依 parser 而異：

- `src/report/parsers/api_parser.py` → 呼叫 `calculate_mbps`（600 秒假分母）
- `src/report/parsers/csv_parser.py` → `_estimate_bandwidth`：`bytes_total × 8 ÷ (last - first)`，
  且 `clip(lower=1)`

**同一條 flow 換個資料來源就換一個數字**，差距可達數百倍。`mod11_bandwidth` 與
`_fmt_bw` 一視同仁地顯示兩者。這是待修的既有不一致。

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

### 6.3 目前的頻寬數字有多離譜

```bash
./venv/bin/python - <<'PY'
import sqlite3, json, datetime, sys
sys.path.insert(0, ".")
from src.analyzer import calculate_mbps
c = sqlite3.connect("file:data/pce_cache.sqlite?mode=ro", uri=True)
p = lambda s: datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
rows = []
for (r,) in c.execute("select raw_json from pce_traffic_flows_raw"):
    d = json.loads(r)
    tr = d.get("timestamp_range") or {}
    b = float(d.get("dst_bo") or 0) + float(d.get("dst_bi") or 0)
    if b <= 0 or not tr.get("first_detected"):
        continue
    span = (p(tr["last_detected"]) - p(tr["first_detected"])).total_seconds()
    rows.append((b, span, calculate_mbps(d)[0]))
over = [x for x in rows if x[2] > 10000]
print("列數 %d；現行算法 >10 Gbps 的有 %d 筆，最大 %.0f Mbps"
      % (len(rows), len(over), max(x[2] for x in rows)))
ok = [b * 8 / s / 1e6 for b, s, _ in rows if s > 0]
print("改用 timestamp_range 時距：>10 Gbps 有 %d 筆，最大 %.0f Mbps"
      % (sum(1 for x in ok if x > 10000), max(ok)))
PY
```

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

**連線數與流量可信；頻寬不可信。** 頻寬的分子是整段累計量、分母是硬編的 600 秒，
兩者尺度不同，算出來的數字沒有物理意義，且排序結果與 volume 完全相同。
在 `2026-08-23-bandwidth-basis-design.md` 實作之前，看到 Mbps 請當作「未知」。
