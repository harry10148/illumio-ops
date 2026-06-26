# Design Spec — Dashboard 重建（即時總覽 / Live Operational Overview）

> 日期：2026-05-31 · 狀態：設計核可待 review
> 背景：UX 評估（`docs/ux-review-2026-05-30/assessment.md`）發現現有 dashboard 是「兩份報表摘要 + 雙 JS（dashboard.js + dashboard_v2.js）拼貼」，因此出現風險卡空白、流量卡標錯、N/A 日期、雙時間戳、假新鮮度（永遠「現在」），且回答不了三大維運問題（VEN 是否存活 / 現在被擋什麼 / 管線是否在流）。本案重建上方「即時狀態區」。

## 1. 目標與成功標準

- 上方「掃一眼狀態區」用**即時資料**直接回答三大維運問題（+ 告警），帶**真實新鮮度 + 自動刷新 + 下鑽**。
- **甩開報表依賴**：狀態區不再 scrape 報表產物。
- 根治雙 JS：上方狀態區收斂為單一 `dashboard.js` 模組 + 單一聚合端點，退役 `dashboard_v2.js`。
- 成功標準：①四塊皆有即時資料與 `as_of`；②`/api/dashboard/overview` 一次往返；③無 `dashboard_v2.js`；④下方既有明細區功能不受影響；⑤新端點 + VEN job 有單元測試、前端有 harness 驗證、實機目視通過。

## 2. 已核可的決策

| 決策 | 選定 |
|---|---|
| 使用模式 | **平衡**：上方掃描狀態區 + 下方可操作明細區 |
| 狀態區區塊 | **核心四塊**：VEN 健康 · 現在被擋 · 管線健康 · 告警 |
| 實作策略 | **A：乾淨重建** —— 新增聚合端點 + 單一 JS 模組，退役 dashboard_v2 |
| VEN 資料策略 | **V2**：週期性 VEN 摘要 job 寫入 state，overview 直接讀（不每次打 PCE、不綁報表）|

## 3. 架構與資料流

```
[PCE] --fetch_managed_workloads()--> run_ven_summary (排程, 5m) --> state["ven_summary"]
[cache agg / watermarks / siem / state] ----------------------------+
                                                                     v
 GET /api/dashboard/overview  (一次組裝四塊 + 每塊 verdict + as_of)
                                                                     v
 dashboard.js (單一模組) --> 上方四塊狀態卡 (verdict 上色 + 下鑽)
                            + 自動刷新 30s / 手動刷新 / as_of
 (下方明細區沿用現有載入器，不動)
```

### 3.1 後端聚合端點 `GET /api/dashboard/overview`
- `@login_required`，回傳：
```jsonc
{
  "as_of": "2026-05-31T06:32:07Z",
  "ven":      { "total":21,"online":19,"offline":2,"degraded":0,
                "oldest_heartbeat_age_s":147600,
                "attention":[{"host":"...","reason":"offline 41h"}],
                "stale": false, "verdict":"warn" },
  "blocked":  { "window_days":7,"blocked":1290,"potential":16298,"allowed":621,
                "flagged":17588,"vs_prev_pct":12,"verdict":"ok" },
  "pipeline": { "cache_lag":[{"source":"events","lag_s":240,"level":"ok"}],
                "siem_success_1h":100.0,"dlq":0,"verdict":"ok" },
  "alerts":   { "fired_24h":2,"suppressed":8,"failed":0,
                "recent":[{"rule":"...","time":"...","channel":"line","status":"success"}],
                "verdict":"ok" }
}
```
- **每塊獨立降級**：任一來源失敗（如 VEN job 尚未跑過 → `state["ven_summary"]` 缺）→ 該塊回 `verdict:"unknown"` + `note`，**不**讓整個端點失敗。

### 3.2 各塊資料來源
- `ven` → 讀 `state["ven_summary"]`（由 §3.4 的 job 維護）。
- `blocked` → `pce_traffic_flows_agg` 近 `window_days` 天 sum(allowed/potential/blocked) + 與前一等長窗比較算 `vs_prev_pct`。
- `pipeline` → `check_cache_lag()`（watermarks）+ SIEM 近 1h 成功率（siem_dispatch/state）+ DLQ 深度。
- `alerts` → state 的 `dispatch_history`（近 24h 觸發/失敗）、`throttle_state`（已抑制）、`event_timeline`（recent）。

### 3.3 verdict 門檻（明確定義，避免歧義）
- **ven**：`ok` = offline 0 且 degraded 0；`warn` = offline≥1 或 degraded≥1；`error` = offline > max(1, ⌈total×0.10⌉)（離線比例過高）。job 缺資料 → `unknown`。
- **blocked**：預設 `ok`（被擋在微分段是預期）；`warn` = flagged(blocked+potential) 較前窗 `vs_prev_pct` > 50（突增）。此塊不設 error。
- **pipeline**：`ok` = 所有 cache_lag level 皆 ok 且 siem_success_1h ≥ 99 且 dlq == 0；`warn` = 任一 lag level=warning 或 siem 95–99 或 dlq > 0；`error` = 任一 lag level=error 或 siem < 95 或 dlq ≥ 每目的地上限的 80%。
- **alerts**：`ok` = failed 0；`warn` = failed ≥ 1；此塊不設 error（失敗即需注意，warn 已足）。

### 3.4 V2：`run_ven_summary` 排程 job
- 隨 daemon 執行（`monitor` / `monitor-gui`），**獨立於 `pce_cache.enabled`**；間隔預設 300s（可設）。
- 邏輯：`api.fetch_managed_workloads()` → 重用 `VenStatusGenerator` 既有狀態判定（含 `_ONLINE_HEARTBEAT_THRESHOLD_HOURS`）算 total/online/offline/degraded + 最舊心跳秒數 + offline 清單（host+原因）。
- 定義：`online` = 心跳在門檻內；`offline` = 心跳逾門檻；`degraded` = online 但 policy_sync 非 `synced`（policy 套用異常，warn 等級，不算離線）。
- 寫入 `state["ven_summary"] = { ...counts, oldest_heartbeat_age_s, attention[], updated_at }`（與 `pce_stats` 同模式，透過 state_store 原子更新）。
- 失敗 → 記 `state["ven_summary"]["last_error"]`，不覆蓋上次成功的計數（保留最後已知良好值）。

### 3.5 前端：單一 `dashboard.js`
- 上方狀態區改打 `/api/dashboard/overview`（一次往返）。
- **退役 `dashboard_v2.js`**：其重疊 overlay 邏輯併入 `dashboard.js`；index.html 移除該 `<script>`。
- 下方明細區（Top Ports / 未覆蓋 / Audit 摘要 / 12-KPI）**沿用現有載入器**，僅移到狀態區下方；不重寫。
- 四塊渲染：每塊 verdict 記號（✓綠 ok / ⚠黃 warn / ●紅 error / –灰 unknown）+ 關鍵數字 + 下鑽連結；整張卡可點。

## 4. 版面

```
即時總覽                            ⟳ 資料截至 14:32:07 · 自動刷新 30s ▾  [手動刷新]

┌─ VEN 健康      ⚠ ┐  ┌─ 現在被擋     ✓ ┐  ┌─ 管線健康     ✓ ┐  ┌─ 告警        ✓ ┐
│  19/21  online    │  │  Blocked   1,290 │  │  cache 延遲  4m  │  │  24h 觸發    2  │
│  ⚠ 2   offline    │  │  Potential 16,298│  │  SIEM 1h    100% │  │  已抑制      8  │
│  最舊心跳  41h     │  │  ↑12% vs 昨日     │  │  DLQ          0  │  │  失敗        0  │
│  → 看 offline ↗    │  │  → 看 blocked ↗   │  │  → 整合 ↗        │  │  → 事件/規則 ↗  │
└───────────────────┘  └──────────────────┘  └─────────────────┘  └────────────────┘
─────────────────────────────────────────────────────────────────────────────────
▾ 可操作明細（保留現有）：Top 10 Ports · 未覆蓋流量 · Audit 摘要 · 詳細 12-KPI …
```

下鑽目標：VEN→Workloads(filter offline)｜被擋→流量分析器(filter blocked)｜管線→整合｜告警→事件檢視/規則。

註：每塊右上角標**一律跟隨該塊 verdict**（✓綠 ok / ⚠黃 warn / ●紅 error / –灰 unknown）。上圖「現在被擋」在 12%（無突增）下依 §3.3 為 `ok`→✓，僅當 flagged 較前窗突增 >50% 才轉 ⚠。

## 5. 自動刷新行為
- 只輪詢 overview 端點，預設 30s，可關；手動刷新鈕。
- `document.hidden` 時暫停輪詢。
- 顯示真實 `as_of`；當 now − as_of > 2×間隔 → 時間戳變灰 + 「資料可能過時」提示。

## 6. 測試策略
- **後端**：① overview 組裝（mock 四來源 → 斷言形狀 + 各塊 verdict 門檻邊界）；② 任一來源失敗 → 該塊 `unknown` 不拖垮端點；③ `run_ven_summary`（mock workloads → 斷言計數/offline 清單寫入 state；失敗保留上次值）。
- **前端**：harness 載入真實新 `dashboard.js`、餵樣本 payload → 斷言四塊 verdict 上色/數字/下鑽連結（同 trend/line-card harness 模式）。
- **回歸**：完整 pytest 套件；i18n parity + 稽核（新增鍵走中文一般 UI 慣例）。
- **實機**：部署後登入目視四塊即時數字 + as_of + 自動刷新 + 下鑽。

## 7. 範圍邊界
- **做**：上方四塊狀態區、`/api/dashboard/overview`、`run_ven_summary` job + `state["ven_summary"]`、退役 dashboard_v2、真實新鮮度/自動刷新、四塊下鑽。
- **不做（保留現狀）**：下方明細區內容、下鑽目標頁本身、完整 VEN 報表。
- **不在本案**（其他 Phase）：報表 exporter 修正、治理層（RBAC/稽核/安全預設）、管線可觀測性深化。

## 8. 實作待解（交由 writing-plans 細化）
- `dashboard.js` 與 `dashboard_v2.js` 的逐行合併（哪些 loader 留、哪些併）。
- SIEM 近 1h 成功率的精確查詢來源（siem_dispatch 表 vs state）。
- 新 i18n 鍵清單（四塊標題/標籤/verdict 文案）。
