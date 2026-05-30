# Design Spec — 管線可觀測性 (Pipeline Observability)

> 日期：2026-05-31 · 狀態：設計核可待 review
> 背景：UX 評估（`docs/ux-review-2026-05-30/assessment.md` §1F、整合分頁稽核）發現整合/管線面只有**生命週期累計值**——管線死掉跟健康長一樣；平均延遲硬編 `—`；DLQ 看不到單筆完整內容；SIEM 無每目的地健康歷史；缺統一「管線健康」判定。
> 結構事實：單一 SQLite DB、7 張表、無 migration（`Base.metadata.create_all` 加欄/表為冪等加法）。**無任何 metrics/rollup/time-series 表**；但所有時間戳都在（`pce_events.ingested_at`、`siem_dispatch.sent_at/queued_at`、`dead_letter.quarantined_at`），可即時查窗。SIEM `siem_dispatch` 是**就地更新無歷史**。DLQ 只存 `payload_preview[:512]`，但保留 `source_table/source_id`，可由 `dispatcher._build_payload(row)` 重建完整 payload。

## 1. 目標與成功標準
- 管線數字從「累計」升級為能回答「**現在是否在流/哪裡卡**」：近 1h 速率、成功率、延遲、統一健康判定。
- DLQ 能檢視單筆完整內容、能針對特定項重送並看到結果。
- 成功標準：①SIEM 狀態含近 1h sent/failed/成功率 + 真實平均延遲（非 `—`）；②整合 overview 有單一管線健康判定 tile（ok/warn/error）；③`GET /api/siem/dlq/<id>` 回完整重建 payload + 完整 error；④DLQ 重送可帶 id 並回每項結果；⑤既有測試 + 新單元測試全綠。

## 2. 已核可決策
| 項目 | 決策 |
|---|---|
| 時間窗 | **即時查既有時間戳**，不新增 rollup 表（siem_dispatch 補 `queued_at`/`sent_at` 索引） |
| backfill 進度 | **本次不做**（需改非同步 + job 狀態表，列為後續獨立項） |
| DLQ 單筆檢視 | **由 source row 即時重建**完整 payload（不改 schema、不存全 payload） |
| 每目的地 SIEM 歷史 | **只做近 1h 視窗**（不新增 append-only log 表） |
| 健康判定 | **重用 dashboard overview 的 pipeline verdict**（cache lag + SIEM 近1h + DLQ） |

## 3. 工作項目

### (a) SIEM 近 1h 視窗度量 + 真實延遲
- 強化 `/api/siem/status`（`src/siem/web.py:126`）：除既有累計，每目的地再加 `sent_1h`（`status='sent' AND sent_at>=now-1h`）、`failed_1h`（`status='failed' AND queued_at>=now-1h`，因 failed 列 `sent_at` 為 NULL）、`success_1h = sent_1h/(sent_1h+failed_1h)`、`avg_latency_ms`（`avg(sent_at-queued_at)`，近 1h sent 列）。
- 索引：`siem_dispatch` 補 `Index` on `queued_at`、`sent_at`（`models.py:104-120`；`create_all` 冪等加上）。
- 前端 `integrations.js renderSiem`（:540）：**修掉硬編 `—` 的平均延遲 tile（:582）** 改讀 `avg_latency_ms`；**修 `per_destination` 空 bug**（:588 讀不存在的 key）→ 改用 status 列。成功率 tile 改顯示「近1h」。

### (b) Cache ingest 近 1h 速率
- 新增 `/api/cache/throughput`（或併入 status）：events 近 1h = `count(pce_events WHERE ingested_at>=now-1h)`，traffic 同理（`pce_traffic_flows_raw.ingested_at`）。
- 前端 cache 分頁 `buildCacheStatusCards`（:110）：累計值旁加「近1h +N」小字（速率感），不取代累計。

### (c) 統一管線健康判定 tile
- 重用 dashboard overview 的 pipeline verdict 邏輯（cache lag level + SIEM 近1h 成功率 + DLQ 深度 → ok/warn/error）。把該門檻抽成共用函式（`src/pce_cache/health.py` 之類），dashboard overview 與整合 overview 共用，避免兩套門檻漂移。
- 前端整合 overview `_buildOvCards`（:1268）最前面加一張「管線健康」判定 tile。
- 相依：與 dashboard 重建的 `_overview_pipeline` 共用同一函式（哪邊先實作就先建該共用函式，另一邊接）。

### (d) DLQ 單筆完整檢視
- 新增 `GET /api/siem/dlq/<int:id>`（`src/siem/web.py`）：讀該 DeadLetter → 由 `source_table/source_id` 取回原始列 → `dispatcher._build_payload(row)` 重建完整 payload；回 `{id, destination, retries, last_error(full), quarantined_at, payload(full|null), payload_source}`。source 列已不存在時 `payload=null` + note，退回 `payload_preview`。
- 前端 `dlqView(id)`（:1197）：改為 fetch 此端點顯示完整 payload + 完整 error（取代目前只顯示 512 字預覽的純前端 modal）。

### (e) DLQ 依 id 重送 + 結果
- 強化 `POST /api/siem/dlq/replay`（`web.py:186`）：除既有 `{dest, limit}`，接受 `{ids:[...]}`；`DeadLetterQueue.replay` 加 `replay_ids(ids)` 針對特定列 requeue（INSERT `SiemDispatch(status="pending")`），回 `{requeued:[{id, ok}], failed:[...]}`。
- 前端 `dlqReplay`/`dlqReplaySelected`（:1124-1150）：改帶實際 row ids（目前忽略 id 只傳 `limit`）→ 顯示每項 requeue 結果 + 刷新。
- 說明：requeue 成功 ≠ 投遞成功；真正投遞結果之後由 dispatcher 處理、反映在 status（本案不追投遞層級結果，那需 (非範圍的) 歷史表）。

## 4. 測試策略
- **單元**：①seed `siem_dispatch`（含 sent_at/queued_at 不同時間）→ 斷言 status 回近 1h sent/failed/成功率/avg_latency_ms 正確；②seed `pce_events.ingested_at` → throughput 近 1h 計數正確；③健康判定函式門檻邊界（ok/warn/error）；④seed DeadLetter + 對應 source 列 → `GET /api/siem/dlq/<id>` 回完整重建 payload；source 缺 → payload=null + 退預覽；⑤`replay_ids` → 對應列產生 pending SiemDispatch、回每項結果。
- **前端**：harness 餵樣本 → SIEM tile 顯示真實延遲非 `—`、管線健康 tile 上色、DLQ view 顯示完整 payload。
- **回歸**：`test_cache_web` / `test_siem*` / 完整套件；新索引不影響既有查詢。

## 5. 範圍邊界
- **做**：SIEM 近1h 度量+真實延遲+修 per_destination/em-dash bug、cache ingest 近1h 速率、統一健康判定 tile（與 dashboard 共用）、DLQ 單筆完整檢視（重建）、DLQ 依 id 重送+結果。
- **不做（明確排除）**：backfill 非同步/進度（後續獨立項）；SIEM/DLQ append-only 歷史表與真正 per-attempt sparkline；投遞層級重送結果追蹤。
- 不新增 rollup/metrics 表；不改 dispatcher 投遞流程（只新增重建/replay-by-id 讀寫）。

## 6. 實作待解（交由 writing-plans）
- 共用健康判定函式的落點與 dashboard 重建的先後（誰先建 `pce_cache/health.py`）。
- `dispatcher._build_payload` 是否可在 web 請求脈絡安全呼叫（session/相依）。
- `replay_ids` 與既有 `replay(dest,limit)` 的介面整合方式。
