# Session Handoff — 報表效能線 + GUI 驗證修復 + 快取硬化（2026-06-14）

> 取代 `2026-06-13-session-handoff.md`。本 session 主軸:回應「報表太慢/不可接受」,
> 根因調查 + 全面效能優化 + cache DB 硬化 + 架構決策。

## 狀態快照
- **分支** `main`,HEAD **`cf37e00`**,已 push,`origin/main` 同步。
- **測試機** `illumio-ops-test`（root@172.16.15.106,`/root/illumio-ops`）已部署 `cf37e00`,service active。
- 測試基線:`~1818 passed`。**4 個 `TestOverviewPostureHelper` 失敗是已知 snapshot 污染 quirk**（report-export 測試寫 `reports/snapshots/traffic/*.json`+`logs/state.json`;隔離下 `35/35`。清除:`rm -f reports/snapshots/traffic/*.json logs/state.json`）。

## 根因:報表慢 = 6/12 弱掃灌爆 10× 流量(非程式回歸)
- 報表抓取/解析/分析程式碼自 4–5 月未改（git 證實）。
- PCE 歷史 7 天流量:5 月底 **14,228**、6 月初 **21,931**、現在 **218,924**。
- cache 逐日:6/05–6/11 每天 ~2–3.6k(正常);**6/12 單日 221,840**(99% potentially_blocked,96% 來自單一未受管 IP `172.16.15.142` 掃 DemoApp = 弱掃);6/13 回 1,918。
- 結論:查詢窗含 6/12 就吃 22 萬筆 → 慢。同程式查舊窗(14k)只要 11s → **變數是資料量,不是程式**。使用者確認弱掃是預期的,不處理。

## 效能優化(全部已 push + 部署 + 實機量測)
| commit | 內容 | 量測 |
|--------|------|------|
| `cc820ff`/`7a11674` | SIEM `run_siem_dispatch` 每 5 秒 `NOT IN(全集)`→`too many SQL variables` 崩潰且搶 DB;改 **NOT EXISTS anti-join + `ix_dispatch_source(source_table,source_id)`** | 0 崩潰、0 job 重疊 |
| `4fb4e3c` | async 流量查詢輪詢 **固定 120s → 900s 截止 + 2s→10s 退避**(原本 PCE 算 >120s 會靜默丟資料) | — |
| `47e9aa5` | **資料來源 Cache/純API 選項**(CLI `--cache/--no-cache`、GUI「資料來源」下拉、報表類報表)。預設 cache | — |
| `1b72d93` | **cache 按 app workload-href 過濾**(App Summary 只讀該 app 流量)+ **agg NULL 去重**（COALESCE NULL→''，修 4.5M 膨脹）| App Summary 17 分→**10 秒**(讀 2,026 vs 24 萬) |
| `31258eb` | aggregator 改 **set-based 單一 INSERT…SELECT**(原逐列迴圈逾時) | 重建 6s |
| `1a78161` | **`PRAGMA busy_timeout=30s`**(併發寫者等鎖而非「database is locked」) | — |
| `0c005f7` | **批次 ingest**(chunked `ON CONFLICT DO NOTHING RETURNING`,取代每列一交易)+ **砍 5 個沒用的 raw 索引**(first_detected/src_ip/dst_ip/port/action) | ingest 寫入大減 |
| `266c26d`/`a9f68b3` | **Tier-2a:flatten 快取**(ingest 時算 `report_json` = api_parser flatten 產物;`read_flows_df` 向量化還原,跳過 per-row re-flatten;`build_unified_df` 共用保證一致)| **~4.4×**(8,299 vs 1,905 列/秒) |
| `a0855f2`/`c18ceca`/`0192ed3` | **Tier-2b:policy_decisions 下推 SQL**(修正確性:cache 原本忽略報表 filters)+ 複合索引 **`ix_raw_last_action(last_detected,action)`** | allowed-only **2.7s vs ~127s ≈ 45×** |
| `155c3d6` | **cache df 套用其餘 filters**(`src/report/df_filter.py`:標準 label 走欄、自訂走 extra_labels、ip 精確/CIDR、port、proto、排除;**honor query_operator=or** 保 App Summary 正確) | 修正確性 |
| `cf37e00` | **`PRAGMA cache_size=64MB` + `mmap_size=256MB`** | read 29s→23s(~20%) |

一次性 ops:手動 backfill `report_json`(24 萬列 75s)、agg 重建(4.57M→222k)、VACUUM(3.2G→829M)。

## 架構決策(本 session 結論)
**留在 SQLite**,不上 DuckDB/Postgres。
- **SQLite 零額外套件**:`sqlite3` 是 Python 標準庫(bundle 的 PBS CPython 3.12.7 自帶,實測 SQLite 3.45.1);只用核心功能(WAL/JSON/busy_timeout),**零 offline bundle 衝擊**。
- **DuckDB**:額外 per-arch binary wheel(~20-40MB×2)+ `sqlite_scanner` 擴充**會連網下載→破氣隙**(要改 Parquet 或預打包);且若仍用 pandas 分析,對「單報表延遲」贏 Route 2 不多。**觸發點:願意把分析層改寫成欄式 SQL。**
- **Postgres+Timescale**:解規模/併發/HA,不是單查詢延遲;氣隙下要**運維一台 server**,打破嵌入式部署模型。**觸發點:多實例/HA 或持續百萬/日。**

## Route 2 結案(2026-06-14 後續 session,HEAD `fa64493`)
**Route 2 不做了 —— 量測推翻前提。** 詳見 `docs/superpowers/specs/2026-06-14-cache-read-raw-cursor.md`。
- 在測試機 242k 列實測:read_sql 反正規化 41 欄(11.70s)只比 raw blob+orjson+build(12.04s)快 3% —— 它用「撈 41 欄」換掉「撈 1 blob」又吐回去。瓶頸是 sqlite3 driver 的 per-row×per-column 物件建構(CPU,非 I/O:`ORDER BY` 有無一樣)。反正規化沒價值。
- 「SQLAlchemy 多吃 40%」也被推翻:那是 fallback double-scan + 服務搶資源的假象。乾淨量測:SQLAlchemy 7.26s vs raw cursor 11.41s(raw 反而慢)→ raw cursor 已 revert(原 `bde3b52` 撤回)。
- **真正瓶頸**:`read_flows_df` 第二段 `report_json IS NULL` fallback,在已 backfill 的庫對到 0 列,但 report_json 不在任何索引 → 全掃 242k 列 last_detected range 每列查一次,~8s 做白工。
- **修法(已上)**:`cf fa64493` 加 partial index `ix_raw_report_json_null ON (last_detected) WHERE report_json IS NULL`。fallback 改吃這個(正常為空的)索引 → 瞬回。**零寫入成本**(ingest 一律設 report_json,新列永不進此索引),`init_schema` 冪等建立,重啟即生效免遷移。
- **結果**:全量 7 天報表乾淨讀 ~16s → ~8-11s(~1.5-2×,視 cache 暖度;測試機有量測變異)。read_flows_df 邏輯/輸出不變(新增 APIParser 對等測試 pin 住)。

## 待執行(parked,可隨時做)
- ~~Route 2~~ → 已結案(見上)。再要壓延遲只剩換欄式引擎(DuckDB),已在架構決策 parked。
- top10/analyzer `query_flows` 仍是 dict-based、未吃 Tier-2a 向量化(要改 df-based,中等工程、價值窄:1 天窗+爆量)。
- report_json 讓每列存 raw_json+report_json≈2.4KB(7 天 retention 下有界;要省可壓縮)。

## 踩坑筆記(本 session 驗證)
- **維護/backfill cache DB 要先停服務**:`systemctl stop illumio-ops` 後等 `pgrep -f illumio-ops.py` 清空（`--monitor-gui` 有子程序）。SQLite 單寫者,兩個大寫並行即使有 busy_timeout 仍會 `database is locked`。
- **`create_all` 不會對既有表加索引/加欄**:用 `CREATE INDEX IF NOT EXISTS` / `ALTER TABLE ADD COLUMN`(都在 `schema.py` 的 init_schema,冪等)。
- **SQLite unique 索引把 NULL 當不同**:agg 去重要 COALESCE NULL→sentinel,否則未受管端點(NULL workload)永不碰撞、每次重插→膨脹。
- **`auto_vacuum` 在 connect listener 設不可靠**(SQLite 要建庫前設或需 VACUUM)— 已放棄,改靠手動/一次性 VACUUM。
- **SQLite CLI 未裝在測試機**:用 `./venv/bin/python -c "import sqlite3…"`。
- **實機 GUI 驗證**:MCP Playwright 擋自簽憑證 → 用 standalone Node script(`/home/harry/.npm/_npx/*/node_modules/playwright`,CommonJS `import pkg;{chromium}=pkg`)+ `ignoreHTTPSErrors`;GUI flask_login(`web_gui.username`預設 illumio + argon2 密碼)→ root 在測試機 `cp -a config.json` 備份後用 `src.config.hash_password` 暫設已知密碼、驗後從備份還原。
- rtk shell proxy 會 garble git/grep → 用絕對路徑 `/usr/bin/git`。

## 下次接續指令
```
接續 illumio-ops。先讀 docs/superpowers/2026-06-14-session-handoff.md。
效能線已完成(Tier-1/2a/2b + cache 過濾 + PRAGMA);架構決定留 SQLite。
若要再壓全量報表 23s:做 parked 的 Route 2(欄位+read_sql)。
維護 cache DB 一律先停服務(SQLite 單寫者)。git/grep 用絕對路徑(rtk proxy)。
```
