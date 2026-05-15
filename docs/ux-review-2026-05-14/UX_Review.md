# Illumio PCE Ops — UX / UI 全面評估報告

| 項目 | 內容 |
|---|---|
| 評估日期 | 2026-05-14 |
| 評估對象 | Illumio PCE Ops `v3.25.0-tracks-abcd`（branch `feat/e2e-playwright-gui-tests`） |
| 測試環境 | https://172.16.15.106:5001（Web GUI）+ 同機 CLI |
| 評估方法 | Playwright 自動化逐頁截圖 + 真實使用者點擊路徑模擬 |
| Viewport | 1440 × 900 desktop |
| 帳號 | illumio / 1qaz@WSX |
| 報告 / 截圖 | `docs/ux-review-2026-05-14/`、`docs/ux-review-2026-05-14/screenshots/`（66 張） |

> **TL;DR**：核心功能完整、視覺有品牌一致性，**主要問題集中在 i18n 翻譯品質、長表單組織、語意色彩、欄位間距與一些 leak 出來的英文字串**。沒有阻擋使用的硬傷，但專業度被細節拖累。

問題分級：
- 🔴 **P0** — 影響功能或正確性
- 🟠 **P1** — 影響第一印象 / 直接降低專業度
- 🟡 **P2** — 一致性與細節打磨

---

## 0. 整體第一印象

**好的部分**
- 品牌色 (`#FF5500` Illumio Orange) 一致地用在 primary action、tab active、KPI 強調
- 字型搭配 Inter / Space Grotesk / Montserrat 與 Zero Trust Tan 100 (`#F7F4EE`) 背景組合有 brand identity
- HSTS / CSP / nonce 等資安 header 預設打開
- 8 個主導航 tab 命名動詞清楚（總覽 / 流量與 Workloads / 事件檢視 / 規則 / 報表 / 規則排程 / 整合 / 設定）
- 報表生成（4 種 × 100% 成功）回應時間 < 20 秒

**整體 friction 點**
- 設定頁是「單一超長 form」，沒分頁、沒側邊章節導覽，scroll 焦慮
- 多處 i18n 漏掉（按鈕、空狀態訊息、報表內容）
- 中文翻譯品質參差（部分欄位疑似機翻：「日越短長覆蓋率」「寛察缺口」「截切」）
- 浮動底部 action bar 與 toast 重疊、空選取仍出現

---

## 1. 登入體驗

> 截圖：`screenshots/00_login_empty.png`、`screenshots/00_login_invalid.png`

| 項目 | 等級 | 觀察 |
|---|---|---|
| 卡片置中乾淨設計 | ✅ | 良好第一印象 |
| 密碼錯誤時保留帳號、清空密碼、focus 回密碼 | ✅ | 符合最佳實務 |
| 紅色錯誤 banner「帳號或密碼錯誤。」 | ✅ | 位置清楚 |
| 沒有「顯示密碼」眼睛 icon | 🟡 P2 | lab 環境輸入長密碼易打錯 |
| 沒有「記住我」/「忘記密碼」恢復路徑 | 🟡 P2 | 內網工具雖可省，但 first-login flow 仍需手把手 |
| 副標「請輸入帳號與密碼以繼續。」 | 🟡 P2 | 文案空洞，可替換為「使用 PCE service-account 憑證登入」之類具引導性的文字 |
| 登入頁未提供語系切換 | 🟡 P2 | 語系僅在登入後設定才能改，第一次使用 EN 用戶會卡住 |
| 沒有 rate limit / 失敗計次提示 | 🟡 P2 | README 提到後端有 rate-limit，但前端不提示 |

**建議**
- 加眼睛 icon (`type=password` ↔ `type=text` toggle)，僅在 lab 模式生效
- 副標改為提示語：例如「PCE Ops 預設使用 GUI 帳號，初次登入會被要求變更密碼」

---

## 2. 主導航 / Header / Dashboard

> 截圖：`screenshots/vp_01_dashboard_fold.png`、`screenshots/clean_01_overview.png`

### 2.1 Header bar
```
[Logo] [https://pce.lab.local:8443]  規則數: 17  排程數: 3  載入時間: 現在  | 佈景 自動 v  密度 緊湊 v  [模組日誌] [停止]
```

| 項目 | 等級 | 觀察 |
|---|---|---|
| 「停止」按鈕直接放在 header | 🔴 P0 | 一鍵停止整個 daemon 風險高，且僅一個 outlined button 樣式，視覺與「模組日誌」幾乎相同 |
| Header KPI（規則數/排程數）與主畫面 KPI 卡（規則數/健康摘要/事件查詢）重複 | 🟡 P2 | Header 顯示 17、主畫面也是 17，DRY 原則違反 |
| 「載入時間: 現在」 | 🟡 P2 | 字面文字「現在」，建議顯示「剛剛」或實際時間戳 + relative tooltip |
| 連線目標用 browser-style 假網址列 | 🟡 P2 | 看起來像可點擊 URL，其實只是 informative；改為 chip 或 label 即可 |
| 「佈景」「密度」兩個下拉間距與 button group 對齊不一致 | 🟡 P2 | 標籤靠左、選擇靠右，視覺軸不齊；建議統一為 `Label: Control` 內 inline flex |

**建議**
- 「停止」改為 settings 內的危險動作，並要 confirmation
- Header 改為三個輕量 chip：`PCE: pce.lab.local`、`規則 17 · 排程 3`、`更新於 21:35`

### 2.2 三大 KPI 卡
| 卡片 | 值 | 顏色 | 問題 |
|---|---|---|---|
| 規則數 | 17 | 橘 | OK |
| 健康摘要 | 0 | 橘 | 🟠 P1 數量 0 應為綠色「健康」狀態，不該全用品牌橘 |
| 事件查詢 | OK | 橘 | 🟠 P1 「OK」是 status word，應用 status green |

**🟠 P1 — 語意色彩**：橘色被當成「強調色」濫用，喪失「警示」語意。建議顏色階層：
- Primary action / brand：`#FF5500`
- Healthy / OK：`#16A34A`（深綠）
- Warning：`#F59E0B`
- Critical：`#BE122F`（已用於 danger token）

### 2.3 小 KPI grid（12 個小卡）

> 截圖：`screenshots/vp_01_dashboard_fold.png`

**🔴 P0 — i18n 翻譯品質低落**
- 「**日越短長覆蓋率**」/「**日誌記送無覆蓋率**」/「**寛察缺口**」/「**整分點高度**」這幾個欄位中文像機翻或誤抓 key
- 應對照 `src/i18n/zh_tw.json`（或對應翻譯字典）核對：anomaly_score、log_send_coverage、visibility_gap 等
- 影響：用戶看不懂自己面前的數據

**🟠 P1 — 單位 / 數值格式**
- 大數字未千分位（部分有部分沒）：`52.5/100 (D)`、`8,074`、`20,782,599`、`6402668504.7 MB`
- 6 GB 顯示為 6402668504.7 MB ❌ — 應自動切換成 GB / TB（human readable）
- 「N/A → N/A」 顯示變化箭頭但沒值，視覺像錯誤 — 缺值請省略整個 trend 指示

**🟡 P2 — 12 個卡片 4×3 grid 排版**
- 卡片高度一致但內部 number / label / unit 對齊不齊
- 「BLOCKED 流量數」label 是大寫，「整分點高度」是中文 — typography 不一致

### 2.4 關鍵發現 / Action Matrix

5 列建議卡片設計：
- 嚴重性 chip（HIGH 紅 / MEDIUM 橘 / INFO 藍）對齊清楚 ✅
- 「對 RDP/SSH/SMB 橫向通信窗用」「將 workload 設 test/visibility 模式」 — 🟡 P2 中文翻譯仍卡卡（「窗用」「模式」之類）

---

## 3. 浮動 Bulk Action Bar（嚴重 P0）

> 截圖：`screenshots/01_dashboard.png`（含 bar）vs `screenshots/clean_01_overview.png`（已隱藏）

**🔴 P0 — 永久占位**
- `#bulk-bar.floating-action-bar` 位置 `position: fixed; bottom; 533px × 72px`，內容是：
  ```
  已選取 0 Workloads    [套用隔離]   [提高 Traffic 更新頻率]
  ```
- 即使「已選取 0」也常駐顯示，佔據畫面正下方 70px 高度，遮住 dashboard 底部資料
- 不分頁面顯示（dashboard / events / rules 全部都會看到）

**建議**：當 `selected_count === 0` 時隱藏；或退化為小 chip 「選擇 Workloads 以批次操作」放在側欄而非 fixed bottom

---

## 4. 流量與 Workloads

### 4.1 流量分析 (`vp_02_traffic_fold.png`)

| 項目 | 等級 | 觀察 |
|---|---|---|
| 子分頁「排行總覽」字色幾乎與背景同色 | 🟠 P1 | 對比度極低，看起來像 disabled，實際 enabled |
| 空狀態訊息「Run a query to view real-time traffic anomalies.」 | 🟠 P1 | i18n 漏翻 — 應為「請執行查詢以檢視即時流量異常」 |
| 表頭混用大寫英文 + 中文：「指標」「來源端識別」「SERVICE」「POLICY 判」 | 🟠 P1 | typography 不一致；「POLICY 判」更像截斷字串 |
| 「時間範圍 / 查詢條件 / 排序方式」左對齊 + 三個 button 貼右 | 🟡 P2 | 中間大量空白；建議將 button group 緊鄰下拉，或加上 hint 解釋 |
| `placeholder="快速搜尋字串"` 但沒例子 | 🟡 P2 | 增加 e.g. `dst=10.0.0.0/8 OR app=onlineboutique` |

### 4.2 Workload 搜尋 (`workload_search_panel.png`)

| 項目 | 等級 | 觀察 |
|---|---|---|
| 三個欄位「WORKLOAD 名稱 / IP 位址 / 主機名稱」中英大小寫不一致 | 🟠 P1 | 第一個欄位全大寫，後兩個中文 |
| 表頭「MANAGE 狀態」中英混雜 | 🟠 P1 | 中文「管理狀態」 |
| 空狀態：「目前沒有符合條件的 Workloads。」 | ✅ | 友善 |
| 三個輸入欄之間沒有 OR/AND 關係提示 | 🟡 P2 | 用戶不知三欄是 AND 還是 OR |
| 沒有「重設」按鈕 | 🟡 P2 | 多次查詢後想清空所有欄位需手動逐欄刪 |

---

## 5. 事件檢視

> 截圖：`screenshots/events_full.png`

- ✅ Three-pane layout（filter row / event list / JSON detail）— 類似 IDE，習慣後好用
- 🟠 P1 右側 JSON 直接 dump raw text，沒 syntax highlight、沒 collapse、沒 search-in-payload
- 🟡 P2 主表 column 寬度未調整：「角色」column 只顯示 `Harry-MacBook-...`、`System` — 大量被 truncate
- 🟡 P2 沒有「複製此 event」/「以 JSON 下載」按鈕（debug 必要）

---

## 6. 規則

> 截圖：`screenshots/rules_full.png`

- ✅ 表格高密度，可掃描
- 🟡 P2 篩選下拉 + 4 個 button 全部擠在 toolbar 右側，左側只有「Filter text」搜尋框 + 空白；toolbar 對稱性差
- 🟡 P2 表格直接 truncate 為 `Suppressed...`、`Event...`，沒 tooltip on hover
- 🟡 P2 沒有 column header sort affordance

---

## 7. 報表（深度評估）

### 7.1 報表清單頁 (`tour_05_reports.png`)
- ✅ 4 個生成按鈕（流量 / 稽核 / VEN 狀態 / Policy 使用）整齊
- 🟠 P1 列表的每一列 metadata：
  ```
  Illumio_Traffic_Report_SecurityRisk_2026-05-14_0531.html
  Attack posture boundary 5 | pivot 1 | blast 5 | blind 5 | actions 5
  [B5] [P1] [R5] [S5] [A5]
  ```
  - badges 與下方小字幾乎重複資訊（boundary→B, pivot→P, blast→R, blind→S, actions→A）
  - 建議二擇一：保留 badge chips 就移除小字
- 🟠 P1 紅色 X 按鈕沒文字 label，新使用者不知是「刪除」（hover 才知）— 改用 trash icon 或文字 `刪除`
- 🟡 P2 檔名過長時截斷在右側，沒 tooltip 顯示完整檔名

### 7.2 報表生成 Dialog

四個 dialog (`report_*_modal.png`)：

| 觀察 | 等級 | 說明 |
|---|---|---|
| 「報表語言」預設 English，與當前 GUI 語系（繁中）不同 | 🔴 P0 | 用戶連續變更兩次（介面 + 報表），且不調整就拿到英文報表 |
| 「Traffic Filters (optional)」英文標籤 | 🟠 P1 | i18n 漏翻 |
| 「依快取範圍自動截切（跳過 API 補抓）」 | 🟠 P1 | typo 「截切」→「截取」/「擷取」；「補抓」→「補抓取」或「補撈」 |
| 取消(灰)+ 產生(綠) 兩個 primary CTA | 🟡 P2 | 其他 primary action 用橘色，這裡用綠色違反 brand consistency；建議統一橘色，secondary 用灰 |
| 「快速區間」chip（1d/7d/30d/60d）按下無 active state 視覺 | 🟡 P2 | 用戶按了不知道有沒有套用，需自行檢查 date input 變化 |
| 標題前的 ▶ icon 看起來像 expand toggle | 🟡 P2 | 實際是裝飾，建議改 `📄` 或對話框圖示，避免誤導 |
| VEN dialog 有 helper text「快照報表會直接讀取目前資料，不需要指定日期區間。」 | ✅ | 範本：所有 modal 都應有 helper text |

### 7.3 報表 HTML 內容（4 個全部執行成功）

| 報表 | 大小 | 觀察 |
|---|---|---|
| VEN Status (`raw_ven.png`) | 4.9 MB | ✅ 結構清楚（KPI / 環形圖 / Online / Offline / Lost），TOC sidebar 良好 |
| Traffic SecurityRisk (`rep_traffic_*.png`) | 5.0 MB | ✅ 12+ 區塊 + Print/PDF sticky；🟠 KPI 區段「Executive Summary」與下方「Key Metrics」5 個指標完全重複；🟠 數值 `6062571061.6` 應顯示為「6.06 GB」 |
| Audit Report (`rep_audit_*.png`) | 5.1 MB | ✅ 6 個 KPI cards 簡潔；attention required events list 易讀 |
| Policy Usage (`rep_pu_*.png`) | 4.9 MB | 🟠 P1 重複 KPI 兩次（exec summary banner + 標題下 mini KPI），且「Submitted N new async queries」也重複出現兩次 |

**🟠 P1 — 報表共通問題**
- 4 個報表都用英文輸出（即使 GUI 設繁中），原因見 7.2 預設值問題
- TOC sidebar 標題顏色與背景對比低（`raw_pu.png` 中可見「Illumio PCE Ops」標題幾乎看不到）
- 圖表 label tiny（環形圖中 87.5% 字很小）
- `52.4/100 (D)` 評分為 D 但配色橘色而非紅色（不及格應有 critical 視覺）

---

## 8. 規則排程

> 截圖：`screenshots/tour_06_rule_scheduler.png`

| 項目 | 等級 | 觀察 |
|---|---|---|
| 左右分欄 1:2，左側 table 擠右側空白 panel 大 | 🟠 P1 | 大量未用空間；建議 split 改 50:50 或 hide right pane 直到選取一筆 |
| 右側空狀態「請輸入關鍵字」 | 🟠 P1 | 與左側 search box 關聯不明；用戶不知道在哪輸入 |
| 「⭐ = Ruleset 排程」「● = 規則排程」legend | 🟡 P2 | legend 在左上但 icon 在表格列前；用戶要對照才知道 |
| `[ACTIVE]` 綠 + `[OFF]` 紅同列 | 🟡 P2 | 部署狀態 vs 啟用狀態同時顯示為對比色，易讓人誤以為衝突 |

---

## 9. 整合 (Integrations)

> 截圖：`screenshots/tour_07_integrations.png`

| 項目 | 等級 | 觀察 |
|---|---|---|
| 4 個 KPI cards：快取列數 / SIEM 目的地 / SIEM 佇列 / DLQ 總數 | ✅ | 結構好 |
| 「SIEM 目的地: 1」下方再寫「1個目的地」 | 🟡 P2 | 重複 |
| 「SIEM 佇列」卡片 3 個子值並排 (待發/已發/失敗)，但「已發 36093」字遠大於其他 | 🟡 P2 | 視覺權重不平衡 |
| 三個小指標都用綠色頂線（失敗也是綠色） | 🟠 P1 | 顏色語意錯：失敗應為紅色，已發為綠色 |
| 「近期分派事件」表只有 1 列（garylog 36093 0 0） | 🟡 P2 | 表格與上方 KPI cards 完全重複資訊；可考慮折疊或合併 |

---

## 10. 設定（總和最大痛點）

> 截圖：`ss_settings_top/mid/low/btm.png`、`csr_settings_full_open.png`

### 10.1 結構問題

**🔴 P0 — 沒有 sub-navigation**
- 整個設定頁是「**單一 form**」垂直堆疊以下 7 個區塊：
  1. API 狀態（含 console-style log）
  2. PCE 設定檔
  3. API 連線
  4. 告警管道（LINE / Email / Webhook）
  5. 顯示與一般設定（時區 / 語言 / theme）
  6. 報表輸出
  7. TLS / HTTPS（含 Certificate Info + CSR / 匯入）
  8. Web 安全設定
- 頁面總高 > 3500px，需 scroll 4-5 個 viewport
- 沒有 anchor / sub-tab 可跳到指定區塊
- 「儲存所有設定」 fixed 在右下角，但用戶不知改了什麼會被「全部」儲存（部分改 PCE URL 風險高）

**建議**：拆成 sub-tabs，例如：
```
[ PCE 連線 ] [ 告警通道 ] [ 顯示 / 報表 ] [ 安全（TLS / 密碼 / IP 白名單） ]
```
或維持單頁但加左側 anchor list（粘性 TOC）。

### 10.2 API 狀態 + 連線

| 項目 | 等級 | 觀察 |
|---|---|---|
| 「狀態成功」大綠字 + 「測試連線」橘色 button | ✅ | 清楚 |
| 黑色 terminal-style log box（Ready / 連線中 / HTTP 200） | 🟠 P1 | 與整體 light theme 視覺嚴重衝突，像 debug console 不像 production UI；可改為時間軸 list / status pill |
| PCE 設定檔列表 + API 連線 form 同時顯示同一條 URL | 🟡 P2 | 重複；form 用於「目前活躍的 PCE」應該與表格行同步而非重複 |
| 「✓ ...」 動作 column | 🟡 P2 | 不明意義；建議 `[編輯] [刪除]` 兩個明確按鈕 |
| 「使用中的 PCE: lab — 儲存 PCE Profile」（斜體） | 🟡 P2 | 看起來像 hint，但「儲存 PCE Profile」 4 字其實是 action — 沒按鈕辨識度 |

### 10.3 告警管道

> 截圖：`ss_settings_mid.png`

| 項目 | 等級 | 觀察 |
|---|---|---|
| 三個卡片（LINE / Email / Webhook）結構一致 | ✅ | 好 |
| 「Enabled」用 checkbox 而非 toggle switch | 🟡 P2 | 啟用/停用語意建議用 switch；checkbox 通常代表 multi-select |
| Email 收件者欄有黑色 outline 殘留（focus state 沒清除？） | 🟠 P1 | 視覺像 active 但已 blur — bug 嫌疑 |
| STARTTLS（左對齊）vs SMTP 認證（右對齊）helper text | 🟡 P2 | 對齊不一致 |
| 「以 HTML Email 寄送廠商對齊格式的告警內容」 | 🟠 P1 | 「廠商對齊格式」翻譯怪 — 應是「以 HTML Email 寄送內容，按警示格式樣板（如預期）」之類 |
| LINE「目標 ID」明文顯示 | 🟡 P2 | 雖屬 channel ID 而非 secret，但仍建議 mask + 「顯示」toggle，避免截圖外洩 |

### 10.4 顯示與一般設定

| 項目 | 等級 | 觀察 |
|---|---|---|
| 時區下拉欄位寬度 ~50%，但「UTC+8」很短 | 🟡 P2 | 浪費空間，建議 `width: 200px` |
| 語言 radio：ENGLISH（全大寫）vs 繁體中文 | 🟡 P2 | typography 不一致 |
| THEME radio：深色 / 淺色 | ✅ | 對稱 |

### 10.5 報表輸出

- ✅ 簡潔：報表輸出目錄 + 保留天數，配 helper text
- 🟡 P2 報表目錄 `reports/` 未說明是相對於什麼路徑（cwd? installation dir?）

### 10.6 TLS / HTTPS + CSR 工作流

> 截圖：`ss_settings_btm.png`

| 項目 | 等級 | 觀察 |
|---|---|---|
| 啟用 HTTPS / 使用自簽憑證 / 啟動時若即將到期自動更新 | ✅ | 3 個邏輯選項清楚 |
| 「啟動時若即將到期自動更新」 + 「剩餘天數低於此值時更新: 30」 | 🟡 P2 | 兩個 control 強相關但視覺分離；建議縮排 + 條件性顯示（前者勾起才出後者） |
| 「Renew Now」按鈕英文 | 🟠 P1 | i18n 漏翻 — 應為「立即更新」 |
| 「Days Remaining: 1804」 | 🟡 P2 | 1804 天無法直覺理解，應顯示「將於 2031-04-23 到期（約 4 年 11 個月）」 |
| CSR 工作流分兩個 `<details>` 折疊：「產生 CSR」+「匯入 CA 簽署憑證」 | ✅ | 對少用功能折疊合理；但折疊狀態時看不到 affordance |
| 「產生 CSR」按下無 CN → 紅色 toast「請填寫 Common Name (CN)」 | ✅ | 表單驗證良好 |

### 10.7 Web 安全設定

| 項目 | 等級 | 觀察 |
|---|---|---|
| 帳號 + 新密碼 + ALLOWED 的 IP 同區 | 🟠 P1 | 三個不同 concerns 混在一起；建議分組 |
| 「ALLOWED 的 IP」中英混雜 | 🟠 P1 | 改「IP 白名單」 |
| 新密碼只有 1 欄，無 confirm password | 🔴 P0 | 用戶錯打密碼 → 被鎖出系統；建議加 confirm 欄位 + 顯示密碼 toggle |
| 「留空表示不更改密碼」 helper 放在 ALLOWED 的 IP 下方 | 🟡 P2 | 與「新密碼」距離遠，邏輯關聯弱 |
| 「儲存所有設定」用綠色而非品牌橘色 | 🟡 P2 | brand consistency；綠色表「成功狀態」非「儲存」action |

---

## 11. CLI 體驗

> 來源：`illumio-ops.py --help` 與 ~12 個 subcommand --help 實測

### 11.1 整體結構（✅ 好的）
- Click + Rich 結合，子命令分組清楚（cache / config / monitor / monitor-gui / gui / report / rule / siem / status / workload / completion / shell / version）
- 「did-you-mean」可用：`illumio-ops monitr` → 建議 `monitor` ✅
- Bare-call 跳出彩色互動式 menu（中文）
- Rich Tables 視覺漂亮

### 11.2 問題

**🔴 P0 — 全域 `--json` flag 在 dispatch 時被吃掉**
```
$ illumio-ops --json status
illumio-ops.py: error: unrecognized arguments: --json status
```
原因：root 是 Click，但 `_CLICK_SUBCOMMANDS` allowlist 把 `--json` 視為 argparse 模式而非 click root option，導致 click 的 `--json` 全域旗標完全無法用。

**🟠 P1 — `report` subcommand alias 翻倍且未標示**
```
audit                  Generate Audit Report.
generate-audit         Generate Audit Report.
generate-policy-usage  Generate Policy Usage Report.
generate-traffic       Generate Traffic Flow Report.
generate-ven-status    Generate VEN Status Report.
policy-usage           Generate Policy Usage Report.
traffic                Generate Traffic Flow Report.
ven-status             Generate VEN Status Report.
```
8 個項目實際是 4 對 alias，列表雜亂；建議：
- 只列 canonical（`traffic` / `audit` / `ven-status` / `policy-usage`）
- 別名在 description 加 `(alias of <canonical>)`

**🟠 P1 — `report generate-traffic --help` 缺乏 helper text**
```
--source [api|csv]              <- 無描述
--file PATH                     <- 何時必填？格式？
--format [html|csv|pdf|xlsx|all]<- 無描述
--output-dir PATH               <- 無描述
--email                          <- 是 flag 還是 takes value？
--profile [security_risk|...]   <- 唯一一個有 description
```
全部 option 都應該寫 1 句 help。

**🟠 P1 — CLI 中英混雜**
- top-level help / subcommand help 全英文
- bare-call 互動式 menu 用中文 + 「Manage」混雜：
  ```
  7. Manage PCE 快取
  8. Manage SIEM 轉發器
  ```
- status table column headings 用英文「Item / Value」但 row value 中文「31 秒 之前」
- 建議：用 `--lang` 或讀 config language 切換，且把「Manage」改「管理」

**🟠 P1 — `siem status` 空資料顯示**
- WebUI 顯示有 1 個 SIEM destination「garylog」（已發 36093）
- CLI `siem status` 卻顯示空 table（只有 header / footer）— **資料不一致 / config 不同步**？
- 需查兩者使用的 config 是否同一份

**🟡 P2 — CLI 警告太吵**
- 每次呼叫都印：
  ```
  WARNING ... TLS certificate verification is disabled for PCE API — security risk
  ```
- lab 環境每命令多 1 行；可改 once-per-day / 加 `--quiet` 抑制

**🟡 P2 — 中文時間單位空格**
- `Last log activity │ 31 秒 之前` — 「秒 之前」中間多餘空格

**🟡 P2 — `workload list` 表格截斷**
- 1440px terminal 寬度下：`Enforceme…` `Hostname` `ubuntu-x86_64-…` 都被 ellipsis
- Rich 預設 column squeeze 沒處理好；可考慮預設 `--full` 或自動橫向滾動

### 11.3 互動式 menu (`bare call`)

```
╭─ Illumio PCE Ops ────────────────────────────────────╮
│ API: https://pce.lab.local:8443 | Rules: 17          │
│ Language: ZH_TW | Theme: Light | 最後活動時間: 現在  │
│ 快捷鍵：Enter=接受輸入 | 0=返回 | -1=取消 | h/?=說明  │
│ ─────────────────────                                │
│  1. 規則 Manage 與告警                               │
│  2. 報表產生                                         │
│  3. 規則排程                                         │
│  4. 系統設定                                         │
│  5. 啟動 Web GUI                                     │
│  6. 查看系統日誌                                     │
│  7. Manage PCE 快取                                  │
│  8. Manage SIEM 轉發器                               │
│ 0. 離開                                              │
╰──────────────────────────────────────────────────────╯
```

- ✅ 第一印象好（cyan border + 整齊）
- 🟡 P2 「0. 離開」與 1-8 對齊不一致（少縮排）
- 🟡 P2 同上的中英混雜
- 🟡 P2 「最後活動時間: 現在」用字面「現在」而非時間戳

---

## 12. 細節盤點（user 要求重點檢查）

### 12.1 欄位間距 / spacing

| 區域 | 問題 |
|---|---|
| 設定頁 form rows | 2-column grid 行高 inconsistent；某些區塊垂直 padding 32px，某些 16px |
| Dashboard mini KPI grid | 4×3 grid，但 row gap 比 column gap 大 1.5 倍，視覺像「拉長」 |
| Reports 列表 row | 檔名與 metadata 兩行間距 4px，太擠 → 視覺與下一筆相距像 |
| Modal 內 `label → input` 間距 | LINE / Email 區塊：4px；TLS 區塊：8px — 不一致 |
| 子分頁 `tab` button group | 「報表 / 報表排程」兩個 sub-tab gap 8px；「總覽 / 流量與 Workloads」main tab gap 16px — 階層間距倒置 |

**建議**：定義 spacing token：
```
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
```
form row gap 一律 `var(--space-6)`，label→input 一律 `var(--space-2)`。

### 12.2 對齊

- 「篩選條件」「參數說明」「查詢 Flow」三個 button 與上方欄位垂直軸沒對齊（欄位 label 起始 x 與 button 起始 x 差 16px）
- KPI cards 內「數字」垂直置中但 unit (`(D)`、`%`、`MB`) 字體大小不一造成 baseline 偏移
- Reports table action column 「檢視」灰按鈕 + 「下載」橘按鈕 + 「X」紅按鈕高度不一致（橘色稍高 1-2px）

### 12.3 對比度（WCAG）

| 元素 | 問題 |
|---|---|
| 「排行總覽」 sub-tab 灰字 | 與 white bg 對比度 ~2.5 (應 ≥4.5) |
| 報表 TOC sidebar 標題「Illumio PCE Ops」 | 深灰 on 深底，幾乎不可見 |
| Mini KPI cards label 灰字 | 對比約 3.2，邊緣 |
| 表格 row hover 沒有明顯背景變化 | 連續 row 難以追蹤 |

---

## 13. 結論與優先級

### 🎉 全部完成（2026-05-15）

**所有 9 份 plans + 1 ADR 透過 subagent-driven-development（含並行 git worktree）已全部 merged 到 main**。累計 68 commits、1306 pytest passed、0 failures、CI all green。

| Plan | Status | Branch | Highlight |
|---|---|---|---|
| Phase 0 — P0 Quick Wins | ✅ | `feat/phase-0-*` | 8 tasks + 4 follow-up（語言預設、密碼 confirm、CLI dispatcher、SIEM 一致性、alias 標示）|
| Phase 3.2 — Settings layout ADR | ✅ | inline doc | 採 Option A sub-tab，6 個月後評估升級 master-detail |
| Phase 1.3 — Color tokens | ✅ | `feat/phase-1.3-*` | `--color-*` 語意層 + lint gate |
| Phase 2.1 — Spacing/Typography | ✅ | `feat/phase-2.1-*` | 4px grid token、移除 Montserrat（-50KB）|
| Phase 1.4 — Header redesign | ✅ | `feat/phase-1.4-*` | 修 config_loaded_at bug、status chip、Operations menu |
| Phase 1.2 — Dashboard i18n audit | ✅ | `feat/phase-1.2-*` | 5-rule 稽核腳本、CI Category J gate、9 mini-KPI 重譯 |
| Phase 2.2 — Component abstraction | ✅ | `feat/phase-2.2-*` | 6 元件（.kpi-card / .status-pill / .filter-bar / .empty-state / .settings-card / .data-table）|
| Phase 3.3 — Report HTML redesign | ✅ | `feat/phase-3.3-*` | KPI 去重、humanize bytes、評分 D=紅、TOC 對比、cover page |
| Phase 1.1 — Settings sub-tab | ✅ | `feat/phase-1.1-*` | 4 sub-tabs（PCE/Channels/Display/Security）、dirty-track、stab deep-link |
| Phase 3.1 — Dashboard story-driven | ✅ | `feat/phase-3.1-*` | Hero block、3 story group、Maturity chart、collapse legacy KPI |

### 假警報（重新驗證後並非 bug）

- **`#bulk-bar` 永久佔位** — CSS 已用 `.show` class 控制 `bottom: -100px → 32px`；原 UX review 是 full_page screenshot 假象
- **「停止」按鈕在 header** — 已有 `confirm(_t('gui_action_stop_gui_confirm'))` 二次確認；後續 Phase 1.4 進一步移進 Operations menu 並加 `.danger` 樣式

### 後續可選 follow-ups

1. **Deploy 到測試機驗證** — 5 個 env-gated Playwright e2e tests（`test_e2e_header_menu` / `test_e2e_report_html_redesign` / `test_gui_settings_subtab_e2e` / `test_e2e_dashboard_story` / `test_gui_e2e_playwright`）需在實機跑
2. **Phase 2.2 Task 7（JS-side empty states sweep）** — skipped 但 baseline scanner 已 lock
3. **Phase 3.1 dashboard-i18n-audit 用 baseline 鎖剩餘 finding** — 仍有 80+ findings，已透過 Category J 鎖死 9 個關鍵 mini-KPI；剩餘 findings 屬於後續 i18n 大稽核範圍
4. **`docs/superpowers/plans/2026-05-15-docs-refactor.md`** — 在 Phase 1.1 merge 時意外帶入 main，這個 docs refactor 計畫尚未執行

### 🟡 P2（細節打磨，未來累積）

- 個別未進 P0/P1 的 polish：表格 hover、互動 menu 對齊、CSR/TLS 區塊內部組織等

---

## 14. 截圖索引

| 區域 | 截圖檔 |
|---|---|
| 登入 | `00_login_empty.png`、`00_login_invalid.png` |
| Dashboard | `01_dashboard.png`、`clean_01_overview.png`、`vp_01_dashboard_fold.png` |
| 流量 / Workloads | `clean_02_traffic.png`、`vp_02_traffic_fold.png`、`workload_search_panel.png` |
| 事件 | `clean_03_events.png`、`events_full.png`、`vp_03_events_fold.png` |
| 規則 | `clean_04_rules.png`、`rules_full.png`、`vp_04_rules_fold.png` |
| 報表清單 | `clean_05_reports.png`、`vp_05_reports_fold.png` |
| 報表 dialog | `report_traffic_modal.png`、`report_audit_modal.png`、`report_ven_modal.png`、`report_pu_modal.png` |
| 報表 HTML | `raw_*.png`、`rep_*_00_y0.png` ~ `rep_*_03_yXXXX.png` |
| 規則排程 | `clean_06_rule_scheduler.png` |
| 整合 | `clean_07_integrations.png` |
| 設定（分段）| `ss_settings_top/mid/low/btm.png`、`csr_settings_full_open.png` |
| CSR flow | `csr_dialog.png` |

---

## 15. 後續建議路線圖

**Sprint 1（1 週內）**：先處理 P0
- 修報表 dialog 「報表語言」預設 = 介面語言
- 加 confirm password 欄位
- 修 `#bulk-bar` 隱藏邏輯
- 全 dashboard mini KPI 翻譯校對（建議找專業在地化）
- 修 CLI `--json` dispatch

**Sprint 2（2 週）**：P1
- 設定頁拆 sub-tab
- 完整 i18n audit（grep 所有 hard-coded 英文）
- 顏色 token 建立 + KPI 重新上色
- CLI help text 補完

**Sprint 3（長期）**：P2
- spacing token / design system 抽出
- 報表內容重構（消除重複 KPI）
- WCAG AA 對比度合規
- Modal / button colour consistency 全站審核
