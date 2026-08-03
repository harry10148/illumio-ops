# UI/UX 全面重新設計 v2 — 設計規格

日期：2026-08-03
狀態：使用者已逐節核可（六節全過）
前置文件：[功能盤點](2026-08-03-ui-redesign-feature-inventory.md)（source-first，守門基準）

## 0. 背景與決策紀錄

上一輪重設計（7/31–8/3）因 mockup 使用臆造資料、資料模型與後端反覆對不上而中止。本輪重啟的既定決策：

| 決策點 | 結論 |
|---|---|
| 上輪成果 | 全部重來，不沿用 |
| 目標 | 可視性 + 良好操作體驗 |
| 範圍 | Web GUI + HTML 報表 + 登入頁 + CLI 選單 |
| 技術約束 | 套件不限，但既有離線部署方案必須照常運作 |
| 樣本資料 | 測試機真 API 快照驅動，mockup 禁止手寫資料 |
| 視覺 | 3 方向比稿後定案 |
| 使用者 | 一般 IT 維運值班 + 熟手網路/資安工程師 |
| 驗收 | 自動守門 + 抽查（功能對照表 100% + Playwright 截圖導覽） |
| IA | 方案 B：任務導向六區重組 |

方法論硬規則（延續 2026-08-03 教訓）：
- 一切資料模型從原始碼與真快照推導，不從文件、不憑印象
- PCE 專業術語一律保留英文原文（ruleset、enforcement、draft、provision…）
- 上輪三個翻車點（rule scheduler 資料模型、alert 規則四型條件模型、FilterBar AND/OR 語意）各配專屬守門測試

## 1. 資訊架構

### 1.1 全域層

- 頂欄：Logo｜六區導覽｜全域健康列｜Cmd/Ctrl+K 快捷搜尋｜使用者選單
- 全域健康列（所有頁面常駐）：5 顆語意燈——Daemon/排程、PCE 連線、Cache lag、SIEM 管線、告警管道。點開 popover 摘要 + 前往詳情連結。資料源 `/api/status` + `/api/dashboard/overview`，零新後端
- URL：每區/子視圖穩定 hash 路由（擴充既有 `updateUrlState`），可書籤

### 1.2 六區分配

| # | 區 | 收納（→ 為遷移來源） |
|---|---|---|
| 1 | 總覽 Overview | 現 Dashboard 全部＋pipeline/job 健康、資料完整性卡（→Integrations，唯讀摘要）＋posture score＋自訂查詢＋Top10＋audit/policy usage 摘要 |
| 2 | 調查 Investigate | 流量分析器（KPI＋FilterBar＋來源切換＋archive）、Workload 搜尋、隔離 apply/lift、加速、cache backfill、事件檢視器（三層 catalog）、shadow compare |
| 3 | 告警 Alerting | 四型規則 CRUD、run-once/debug/測試告警/watermark/最佳實務、rule_test（→Events）、輸出主控台、管道狀態卡（唯讀） |
| 4 | 自動化 Automation | Rule scheduler 全部（KPI/時間軸/PCE 對帳）、報表排程（→Reports）、背景 job 執行歷史與健康（→Integrations） |
| 5 | 報表 Reports | 11 型報表卡＋產生流程＋產出清單管理 |
| 6 | 系統 System | PCE profiles、cache 設定/retention、流量過濾器/取樣、SIEM forwarder/目的地/DLQ、TLS、安全、顯示偏好、告警管道連線設定、模組日誌、daemon 重啟/停止 |

邊界判準：看現況→總覽；查一件事→調查；規則何時叫→告警；排程會動的→自動化；產交付物→報表；改系統本身→系統。

刻意的讀寫分離：告警管道「狀態與測試」在告警區、「連線設定」在系統區。

登入頁獨立，同一視覺系統，含首次登入強制改密碼。

## 2. 互動模式與元件系統

### 2.1 四種版式模式（全站僅此四種）

1. 總覽網格：狀態卡＋圖表卡，點擊跳深入
2. 清單→詳情：左清單右詳情（ruleset 瀏覽、事件檢視、DLQ、報表清單）
3. 查詢工作台：FilterBar＋KPI 列＋結果表＋分頁（流量分析器、Workload 搜尋、事件檢視器共用骨架）
4. 設定表單頁：分節卡片＋dirty 追蹤＋底部固定儲存列

### 2.2 彈窗分級（現 15 modal 重編）

| 類型 | 載體 |
|---|---|
| 大型表單（四型告警規則、SIEM 目的地、兩型排程、報表參數） | 右側 drawer |
| 破壞性確認（刪除、隔離、daemon 重啟） | 小 modal＋影響範圍摘要 |
| 物件選擇（FilterBar PCE 物件） | modal（object-browser 升級） |
| 唯讀說明（篩選語法、隔離指南、posture 解釋） | popover/說明側欄 |

### 2.3 操作體驗

- Cmd/Ctrl+K 指令面板：跳區、跳報表、搜 workload、常用動作
- 非同步進度統一元件：報表產生/backfill/加速倒數，可收合至全域角落
- 防呆分級：一般刪除=確認；批次隔離/重啟=確認＋影響摘要；不做輸入名稱式過度防呆
- 5 tone 語意系統（ok/warn/crit/info/neutral）：燈號、badge、表列、圖表同一組 token
- 保留統一：亮/暗主題、密度、時區、雙語、欄寬拖曳、skeleton、toast、URL 狀態
- 空狀態附成因提示；API 失敗=錯誤卡＋重試＋可展開技術細節

## 3. 技術底座

- 模板：index.html 拆 Jinja 分片（base＋六區 partial＋元件 macro），Flask 直 serve
- 應用形態：維持單頁殼，區內容 lazy 初始化
- JS：原生 ES modules（零 build）——`core/`（api/i18n/theme/router/toast）＋`components/`（table/filter-bar/drawer/progress/command-palette）＋`areas/`（六區）
- CSS：tokens.css（亮暗兩套＋tone）→ components.css → 區級；禁止硬編色碼
- 圖表：vendor 單檔庫進 `src/static/vendor/`（傾向 uPlot，比稿後定案）
- 不引入：npm/build、SPA 框架、htmx
- **不動**：後端 97 端點、CSRF/session/auth、i18n 機制、離線部署腳本/NSSM/wheels
- 風險對策：ES modules 舊瀏覽器→login 頁偵測提示；JS 重寫回歸→守門＋Playwright；i18n 鍵爆量→沿用鍵優先＋audit

## 4. HTML 報表

### 4.1 統一報表殼（11 型共用）

封面（型/時間窗/PCE/參數）→ 執行摘要（一頁）→ 目錄 → 發現章節（發現卡：tone＋敘述＋證據表＋建議）→ 明細章節 → 附錄（參數/詞彙/r01–r05）

- 雙媒體一份 HTML：螢幕 sticky 目錄＋錨點；`@media print` A4 分頁＋頁碼目錄＋寬表列印版式
- 報表吃 GUI token 的列印安全子集，恆亮色；tone 與 GUI 一致
- 圖表沿用 server-side chart_renderer SVG，重繪樣式
- report_css.py 整支重寫（token 化）；各 exporter 改填統一殼

### 4.2 內容層

- 發現卡標配「所以呢」行（對值班的意義＋下一步）
- Traffic 報表執行摘要收斂「風險總覽」矩陣

### 4.3 硬規則

- 每欄位明定長度上限與截斷方式（換行/省略＋title/分頁），禁止無聲截斷
- 交付前測試機真資料重產全 11 型，雙寬度 Playwright 逐頁親驗

## 5. CLI

- click 子指令：結構不動（7/24 全審過），僅術語/輸出對齊
- 互動選單：主選單對齊六區心智模型；頂部常駐 ASCII 健康列；精靈統一（第 n/N 步＋目前值＋預設值、0=返回、錯誤就地重問）；破壞性動作同分級（影響摘要）；雙語/safe_input 沿用

## 6. 樣本製作與驗收

### 6.1 快照

- 測試機真 API 回應存 JSON 快照（secret 遮罩），manifest：端點→檔→視圖
- **mockup 禁止內嵌手寫資料物件**，一律 fetch 快照；lint 腳本掃 mockup 原始碼強制

### 6.2 三階段確認

| 階段 | 產物 | 使用者動作 |
|---|---|---|
| ① 視覺比稿 | 總覽區 3 方向靜態稿 | 挑選/指示混合 |
| ② 全套互動樣本 | 六區全視圖＋drawer/modal＋登入＋指令面板（全吃快照）；報表=新殼實產 Traffic＋Audit 真資料版；CLI=文字流程稿 | 抽查＋放行 |
| ③ 實作 | 逐區動 `src/` | 等驗證報告 |

### 6.3 自動守門

- 功能對照表：盤點文件每項→mockup DOM 錨；守門腳本驗證 100% 覆蓋才交付
- Playwright 自動遍歷全視圖/drawer/彈窗，產截圖導覽 HTML
- 上輪三翻車點專屬迴歸測試

### 6.4 實作驗收

- 每區完成：全套 pytest＋i18n audit＋守門＋Playwright 真後端遍歷
- 最終：部署測試機、真機全遍歷、11 型報表真資料重產逐頁親驗，交「對照表 100%＋真機截圖＋測試輸出」報告

## 7. 測試策略總表

| 層 | 工具 | 守什麼 |
|---|---|---|
| 功能覆蓋 | 守門腳本（對照表） | 盤點清單每項有落點 |
| 資料模型 | 快照驅動＋lint 禁手寫資料 | 形狀錯=當場破圖 |
| 回歸 | 既有全套 pytest＋i18n audit | 後端與 i18n 不退化 |
| UI 行為 | Playwright（mockup 階段＋真機階段） | 視圖/彈窗/流程可達且正確 |
| 報表 | 真資料重產＋雙寬度逐頁截圖 | 無截斷/溢出 |
| 歷史教訓 | 三翻車點專屬測試 | rule scheduler 模型/alert 四型/AND-OR |
