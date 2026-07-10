# Hardening Follow-ups（審查累積 Defer 項收斂）— 設計文件

日期：2026-07-10
狀態：彙整自 2026-07-10 四大案各層審查的 Defer/追蹤發現（出處：`.superpowers/sdd/progress.md` ledger 與各 review 報告），使用者指示「還沒寫成 plan 的都開始規劃修復或優化」。

## 1. 目標與範圍

把本日交付過程中被審查標記為 Defer、但值得收斂的 6 組項目一次修完。全部是既有發現的修復/優化，無新功能。

排除：Rule Hit Count（已有 plan）、readiness backlog（客戶回饋 blocked）、plugger 借鑒構想（新功能，另案 brainstorm）。

## 2. 項目與設計決策

### A. traffic 鏈殘餘吞錯三分支（watchdog 訊號第四層）

出處：ingest-error-signal fix review 確認 `src/api/traffic_query.py` 的 async query **poll 逾時**（:734-746 一帶）、**`state=="failed"`**、**download 失敗**三分支仍是裸 `return`，不設 `last_fetch_error`——這三種失敗下 ingest 仍會誤判「成功 0 筆」。

設計：與第三層修法同構——三分支在 return 前設 `c.last_fetch_error = <描述字串>`。ingestor 端無需再改（`_fetch_window` 已檢查該屬性）。注意 poll 逾時的語意：PCE 可達但查詢算不完——仍屬「本輪拉取失敗」，記 error 正確（watermark 不前進、下輪重拉，與 Task 1 既有例外路徑一致）。

### B. watchdog cooldown 恢復重置（與 lag monitor 語意統一）

出處：AL-6 review Minor＋AL-11 確立「恢復重置」為較佳語意後的不一致（AL-11 review 亦標記）。現況：`watchdog_last_alert_at` 永不清除，前次事故的 cooldown 會壓住新事故的首發（最長 60 分鐘）。

設計：恢復點＝計數歸零處。`record_pce_success`（`src/events/stats.py`）在把 `consecutive_failures` 從非零歸零時，同步清 `state["watchdog_last_alert_at"]`（stats 拿得到 state dict——以現場簽章為準，若 stats 層拿不到則在 analyzer `_check_watchdog` 開頭做：計數為 0 且 timestamp 存在即清除）。零行為變更面：cooldown 內同一事故持續中（計數未歸零）不受影響。

### C. LINE 訊息總長防護（比照 Telegram）

出處：AL-9/AL-10 review——LINE 實際 API 上限 ~5000 字，`_build_line_message` 無在地防護；現況各來源欄位已裁切（120-200 字）實務不可達，屬防禦深度。

設計：比照 `_build_telegram_message` 的 3500 cap 樣式（`src/reporter.py:1243` 一帶），`_build_line_message` 組完後若總長 > **4500**（留 API buffer）截斷至 4500 並附既有風格的明確截斷 footer（i18n 新鍵雙語、無 emoji、不可無聲截斷——CLAUDE.md 規範）。截斷點預留 footer 長度。

### D. `alert_dlq` 納入 co-owned key 防護（M1 latent 一行修）

出處：Alert 案 final review M1——若未來 Analyzer 改常駐，`save_state._merge` 會把 stale `alert_dlq` 快照蓋回磁碟造成重複派送。C1/C2 修復已建立 co-owned-key merge 機制（`traffic_overflow` 永遠信磁碟）。

設計：`alert_dlq` 加入「永遠信磁碟」清單（analyzer 只讀不寫該鍵；reporter 經 `update_state_file` 原子讀改寫）。加一個 race 注入回歸測試（比照 `test_watchdog_overflow_cache_cycle_merge.py` 樣式：cycle 中 reporter 清空 DLQ → save_state 不得復活）。

### E. iplist/workload 同 key 多值 native 分組語意覆核（查證後修或釘）

出處：IP range 案 Step 0 修 ip 系列 inner-AND 時，iplist/workload 的同構分組（`[[a, b]]` 內層 AND）依 brief 保留未動。語意疑點：一個 flow 的 src 可同時屬於多個 IP List（AND 可滿足），但 PCE 原生 UI 對同類多值的慣例是 OR。

設計（兩步）：
1. **查證**：NotebookLM「Illumio」筆記本查官方語意（Explorer 對 consumer 多個 IP List 的組合語意）；必要時測試機真 PCE 實測（`[[A,B]]` vs `[[A],[B]]` 各回幾筆，比照前案 §2.2 方法）。
2. **裁決分支**：若官方/實測為 OR → 比照 ip 系列修法（每值一組），df/fallback 殘餘比對同步核對（`_iplist_hit` 的 any() 語意已是 OR——native 改後三路一致）；若確為 AND（或官方明定 AND）→ 加釘測試＋程式註解記錄語意依據，不改行為。

### F. 品質雜項 sweep（一個 task 收攏）

1. lag monitor 壓制起點 debug log 一條（AL-11 Minor：值班可觀測性）。
2. `_check_ip_filter` 每 flow 重複 parse 的預解析（containment fix Minor：值清單在進 flow 迴圈前 parse 一次）。
3. A-Task 7 的 `_PROGRESS` 終態在下次 load 開始時重置＋前端輪詢加上限（如 720 次＝1 小時）。
4. i18n `alert_siem_backlog` 字母序歸位（兩檔同步搬移）。
5. `--accent-purple/--accent-teal` css var 改為既有 dot 慣例的硬編 hex（B-8 Minor）。

## 3. 非目標

- watchdog 文案細分斷線/degraded 情境（可觸發時皆屬實，AL-7 review 已裁決可接受）。
- `record_local_read` 寫 last_success（刻意不寫，語意隔離）。
- E741 全面清理（repo 無 ruff gate，維持現狀）。
- pce_cache_cli 的 ingest 過濾 picker（概念不同，B-12 已裁決）。

## 4. 測試原則

各項 TDD；A 需三分支各一個 RED 測試（mock 對應失敗形態）；B 需「恢復後新事故首發不被壓」測試；C 需超長樣本截斷＋footer 斷言（截斷後總長 ≤ 4500）；D 需 race 注入測試；E 依裁決分支產出修復測試或釘測試。全套迴歸綠、`ruff check` 改動檔無新增violations。

## 5. 執行順序

A（訊號完整性，最高價值）→ D（一行＋測試）→ B → C → E（含查證，時間不定）→ F。單分支串行（多項共檔 `analyzer.py`/`reporter.py`/`stats.py`）。
