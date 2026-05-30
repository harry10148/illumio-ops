# illumio-ops — UI/UX 與產品結構評估（2026-05-30）

> 方法：登入實機 `https://172.16.15.106:5001`（HEAD `221e7e8`），用 Playwright 逐一截圖 16 個 GUI 畫面 + 5 份產生的 HTML 報表（各截頂部/中段），再依「監控 / 設定與自動化 / 資料管線與整合 / 報表」四個領域分別深度判讀。截圖存於 `tmp/uxaudit/`。
> 範圍對象：資安/網路維運工程師。繁中為主，PCE/VEN/Workload/Blocked 等 glossary 詞保留英文（不列為問題）。

---

## 0. 總體判斷

功能面其實**很完整**（事件/流量/VEN/規則/排程/告警多通道/SIEM/cache/五種報表都有），管線在實機也確實在跑。問題集中在三件事：

1. **它像「儀表板拼貼」而非「維運主控台」** —— 多數畫面打開是空的（風險卡、分析器 KPI、排程 KPI、Workload 搜尋、Top-N 全是 `–`/`—`/空表），dashboard 本身是把兩份報表摘要拼起來的（帶著 N/A 日期、雙時間戳、截斷欄）。給人「沒載入/壞掉」的第一印象。
2. **回答不了維運每天最在意的三個問題**：①我的 agent（VEN）還活著嗎？②現在有什麼被擋（Blocked）？③管線此刻在流還是卡住了？這三個答案目前都是**散的、或只存在於報表裡、或被圖表藏起來**。
3. **作為「資安產品」缺治理層**：單一共用帳號 `illumio` 就能驅動可隔離 Workload 的 Quarantine 排程；沒有變更稽核軌跡、沒有 RBAC/MFA、且預設不安全（SSL 驗證關閉、SMTP port 25 明文、憑證 CN=localhost）。

下面先講**該有但沒有的內容/介面（含架構建議）**，再附各分頁與報表的具體問題清單。

---

## 1. 應該要有但目前沒有的（架構/產品層）— 優先

### A. 一個「真正的」即時維運總覽（重做 dashboard）
現況 dashboard 是流量報表摘要 + 稽核報表摘要的拼貼，繼承了報表的毛病（N/A 範圍、雙產出時間、截斷建議、風險卡空白、流量卡標錯成規則數）。

**建議**：以「當前狀態模型」重建，固定四問一答：
- **VEN 健康**：online/offline/降級數 + 最舊 heartbeat + 「竄改/未配對」清單入口（資料已存在，只活在 VEN 報表裡）。
- **Blocked Now**：blocked / potentially-blocked 當期數字 + 迷你趨勢 + 「vs 昨日」。
- **管線健康**：cache 擷取延遲 + SIEM 成功率(近 1h) + DLQ 深度，收斂成單一 OK/降級/停滯 判定。
- **近期告警**：哪些規則剛觸發/已抑制/失敗（目前只有一個「已抑制 8」和「MAIL SUCCESS」字串）。
- 全頁要有**真實「資料截至時間」+ 自動刷新**，且每張卡可**點擊下鑽**到對應分頁並帶入篩選。

### B. 即時監控要有 VEN/agent 健康的家
這是 Illumio 維運的核心問題，但 16 個畫面裡沒有任何即時 VEN 狀態（只有事後報表）。Workload 搜尋頁也沒有 enforcement 模式（Idle/Build/Test/Enforced）與 agent 在線/版本欄。**建議**：在「流量與 Workloads」加一個預設就列出全部 Workload + enforcement 模式 + VEN 在線/heartbeat 的清單，並可依 Label facet 篩選。

### C.「現在被擋什麼」要變成一等公民
Blocked vs Potentially-Blocked 目前散落在 dashboard 表格(0 vs 16,298)、分析器標籤(「blocked/potential」合併數)、與 legacy 的空 Top-N widget；而 7 天趨勢圖**把 Blocked 紅色帶藏到看不見**。**建議**：一個會自動刷新的「拒絕監視」視圖（Top 被擋 src→dst/port、可下鑽），趨勢圖預設能看到 Blocked。

### D. 治理層（資安產品的硬需求）
- **設定變更稽核軌跡**：誰改了 PCE 密鑰/啟用了 Quarantine 排程/改了密碼或 IP 白名單 —— 目前完全沒有。
- **RBAC / 多使用者 / MFA / Session 控制**：目前單一 `illumio` 共用密碼，且改密碼不需驗證舊密碼。
- **密鑰生命週期**：PCE key/secret 與通道 token 只能寫入+遮罩，無輪替/建立時間/使用範圍顯示。
- **修正不安全預設**：`驗證 SSL` 預設關 → 改預設開；SMTP port 25 + STARTTLS 關（告警內含 IP/port 等敏感資訊走明文）→ 預設開或警告；自簽憑證 `CN=localhost` 對上 `pce.lab.local` 必定觸發瀏覽器警告 → 允許設定 CN/SAN，並支援上傳 CA 憑證/CSR。

### E. 驗證與安全護欄（test / dry-run）
- **每通道 test-send**：通道設定頁目前的「測試連線」測的是 PCE，不是通道；無法驗證 LINE/SMTP/Telegram/webhook 真的送得出去。
- **規則 dry-run**：「這條規則過去 24h 會命中什麼」的預覽，啟用前驗證。
- **排程影響預覽 + 確認護欄**：尤其 `Quarantine` 排程（會對 Workload 動作）目前啟用無任何確認；且排程有 `部署 ACTIVE/DRAFT × 狀態 ON/OFF` 雙狀態模型卻無說明（出現 ACTIVE+OFF、DRAFT+ON 這種看不懂的組合）。

### F. 管線可觀測性（時間窗，而非累計）
- 目前所有健康數字（已發 109,603、成功率 100%、待發 0、DLQ 0）都是**生命週期累計** —— 管線死掉跟健康長一樣。需要**近 1h/24h 速率 + 趨勢 + 「最後派送時間」**。
- **`平均延遲` 是空的（—）**卻宣稱 100% 成功 —— 要嘛量測它、要嘛拿掉。
- **回填(backfill) 是無參數無進度的單一按鈕**：缺起訖日期、進度、ETA、是否有前一個回填還在跑。
- **每目的地 SIEM 健康/歷史**：現在一列一個綠點，多目的地時看不出哪個壞了；測試結果也無處顯示。
- **單筆 DLQ 檢視 + 重送結果**：目前只有批次「重送所選」，無法開單筆看 payload/完整錯誤/目的地回應（CSV 匯出不能取代）。DLQ 達上限(10000)會**靜默丟棄**，應接近時警告。

### G. 報表升級（見 §4）
最大機會：補「**與前次比較 / 趨勢 delta**」、把失效的甜甜圈換成傾斜分布友善的長條、給 NetworkInventory 專屬封面、把 Audit 報表的「需要關注的事件」卡片模式（嚴重度+主體+內嵌建議）推廣成全系列範本。

---

## 2. 跨領域主題（依嚴重度）

| # | 主題 | 嚴重度 | 證據（畫面） |
|---|---|---|---|
| T1 | **預設皆空，像壞掉** —— 風險卡空白、分析器 4 KPI 全 `–`、排程 4 KPI 全 `—`（但上方寫 2 triggers）、Workload/Top-N 空 | P1 | 01,02,03,04,08 |
| T2 | **即時監控無 VEN/agent 健康**（只在報表）；Workload 無 enforcement 模式 | P1 | 01,03 |
| T3 | **「現在被擋什麼」散且被藏**（趨勢圖隱藏 Blocked 帶） | P1 | 01,02,04 |
| T4 | **管線只有累計值，無速率/趨勢/新鮮度**；平均延遲空 | P1 | 09,10,11 |
| T5 | **治理缺口**：無變更稽核、無 RBAC/MFA、不安全預設、無密鑰輪替 | P1 | 13,14,16 |
| T6 | **無 test/dry-run/影響預覽**（通道、規則、Quarantine 排程） | P1 | 06,08,14 |
| T7 | **無跨畫面下鑽** —— 每個畫面是孤島 | P2 | 全部 |
| T8 | **管線操作缺觀測**：回填無進度、無單筆 DLQ 檢視、無每目的地歷史 | P1/P2 | 10,11,12 |
| T9 | **報表：甜甜圈失效(3/5)、KPI 重複、兩份流量報表共用封面、無趨勢** | P1 | 5 份報表 |
| T10 | **洩漏開發殘留/測試髒資料**：報表列 `B1 P1 R0 S5 A4`、「Attack posture boundary…」佔位字、規則 `test/tttt`、排程 `tttt`、`EVENTS_POLL_INTERVAL_SECONDS` 當標籤 | P1/P2 | 07,06,08,10 |
| T11 | **i18n 一致性**（非 glossary 的英文）：`Verified/Not configured`、`Certificate Info`、`Renew Now`、`THEME`、`REQUIRED`、DLQ 英文開發提示 | P2 | 09,12,15,16 |
| T12 | **狀態僅靠顏色編碼**（綠/橘/紅 chip、甜甜圈灰階不可辨） | P3 | 全部、報表 |
| T13 | **新鮮度/信任訊號弱**：`載入時間 現在`、同頁雙產出時間、報表 `N/A→N/A` 日期、跨分頁數字對不上(總覽 891,887 vs cache 866,928) | P2 | 01,09,報表 |

---

## 3. 各分頁重點問題（P1 為主）

**01 總覽 / Dashboard**
- 風險卡完全空白（P1）；「流量」卡實際顯示規則數 18/未知事件 0/已抑制 8 —— 標題與內容不符（P1）；Top 10 Ports 出現兩次 443（10,596 與 1,395）無區分維度；未覆蓋流量「建議」欄每列截在同一處＝等同雜訊；`載入時間 現在` 非時間戳；同頁兩個不同產出時間。

**02 流量分析**
- 4 個 KPI 全 `–`（P1）；趨勢圖只標一個 Y 值、無刻度、Blocked 紅色帶看不見（P1）；標頭「9,176,940 blocked/potential」把兩種判定塞成一個斜線數字；缺一鍵「只看 Blocked / 近 1h 拒絕」快篩；查詢結果無 CSV 匯出。

**03 Workload 搜尋**
- 只有搜尋、無預設盤點清單（P1）；無 enforcement 模式欄/篩選（P1，Illumio 維運核心）；無每 Workload 的 VEN 在線/版本；LABELS 是結果欄卻不能當 facet 篩選；下半 60% 空白。

**04 排行總覽（legacy）**
- 兩個空 widget（`Blocked`/`conn`，開發簡稱）需手動執行（P1）；功能與分析器/dashboard 重疊，建議合併（架構）；時間控制有「分鐘輸入」又有預設 chips，關係不明。

**05 事件檢視**
- 11 列裡 8 列是 `workloads.set_flow_reporting_frequency` 設定雜訊淹沒重要事件（P1）；filter 無「嚴重度」/「只看 CRITICAL/HIGH」（P1，安全事件檢視最核心）；列表無嚴重度欄/色；`狀態` 綠色 success 是 API 成功，非「事件安全與否」（成功的 `agents.unpair` 也是綠）；無從事件下鑽到 Workload/VEN/來源 IP；三個重複 JSON 面板過重。

**06 規則**
- 條件與表達式之間有 2–3 個幾乎空白且無標頭的欄（P1，看起來壞掉）；右側欄混機器 DSL（`PCEBlocked Port:514`）與人類標籤；頂部 5 個同權重橘色按鈕；有批次「套用通知」卻看不到列選取機制；無「最後觸發/命中數」欄、無每規則通道綁定欄、無規則範本、無 dry-run、無匯入匯出；`test/tttt` 髒資料混在正式規則中。

**08 規則排程**
- 4 個 KPI 全 `—`（上方卻寫 2 triggers，矛盾，P1）；`部署 ACTIVE/DRAFT × 狀態 ON/OFF` 雙狀態無說明（P1，Quarantine 的信任危機）；右側 55% 死空間；`全部重新整理` 語意危險（可能有副作用）；無 cron/下次 N 次預覽、無影響預覽、無 kill-switch。

**13 設定/PCE**
- `驗證 SSL` 預設關（P1，不安全預設）；`API 金鑰` vs `API 密鑰` 中文太像易填反；綠色「狀態成功」橫條不知是即時還是上次手測結果（無時間戳）；無密鑰輪替/範圍顯示。

**14 設定/通道**
- 頂部「測試連線」測的是 PCE 不是通道，且**無每通道 test-send**（P1，本頁最大缺口）；SMTP port 25 + STARTTLS 關＝明文寄送告警（P1）；LINE 目標 ID、收件者 email 明文顯示；停用通道的欄位仍標 `REQUIRED`；無訊息範本/預覽、無 rate-limit/quiet-hours、無送達歷史。

**15 設定/顯示**
- 時區欄看似 disabled 卻顯示 `UTC+8`（非具名時區）；`THEME/ENGLISH` 大寫與其他標籤不一致；保留天數用 `0=永久` 魔術值；無報表目錄磁碟用量/「立即清除」、無路徑驗證。

**16 設定/安全**
- 憑證 `CN=localhost` 對上 `pce.lab.local`（P1，必觸發瀏覽器警告，UI 不讓改 CN/SAN）；`Renew Now` 是橘色按鈕但憑證還有 1788 天，無確認護欄（誤點作廢健康憑證）；改密碼不需舊密碼；IP 白名單空值語意不明（全允許？全拒？）；無上傳 CA 憑證/CSR、無 session/鎖定/密碼強度、無 min-TLS。

---

## 4. 報表（HTML，5 份）專節

**整體**：5 份共用左側目錄 + 橘色 Print/PDF + 執行摘要 KPI 橫條。Audit 報表的「需要關注的事件」卡片（CRITICAL/HIGH tag + 操作者/IP/目標 + 內嵌建議）是**全系列應對齊的範本**。

跨報表問題（依嚴重度）：
- **P1 NetworkInventory 與 SecurityRisk 共用同一封面**（都頂著「安全風險分析 / D (49.4/100)」與同一組 KPI）—— 打開分不清看哪份。NetworkInventory 應有「盤點」導向封面（資產數/Unmanaged/Top services/talkers）。
- **P1 甜甜圈在 3/5 份失效**（VEN 19/21、Policy 100%、Audit info 99.7%）—— 極度傾斜分布畫成「一片橘 + 重疊小標籤」，零洞察還佔大版面。改水平長條/堆疊條或直接刪、保留 KPI。
- **P1 執行摘要 KPI 與內文 header KPI 重複**：同一份前兩屏同組數字出現兩次（VEN 最明顯）；內文「樣本數 14/類型」資訊量低。移除重複內文 header。
- **P2 全線缺「與前次比較/趨勢」delta**（只有 Audit 放佔位文案）—— 這是把報表從「描述現況」升級成「支撐決策」的最大單一機會。
- **P2 表格樣式不一致**：VEN 用淺色斑馬列，Policy/Traffic 用厚黑底表頭 + 右側空排序欄，與淺橘主題衝突、灰階列印偏黑。
- **P2 列印破版風險**：Audit 的 sec_policy 長資源路徑、Traffic 的多 IP finding、VEN 8 欄寬表，A4 橫向換行會截斷或跨頁切斷單筆 —— 對 finding 卡/表列加 `page-break-inside: avoid`、長字串加 word-break。
- **P2 排序未對齊目的**：VEN 把 2 台 OFFLINE 混在 19 台正常裡（應異常置頂）；SecurityRisk MID 密度過載、十多筆 finding 重複同組 IP、缺「依攻擊路徑類型計數 / 受影響 Workload Top-N」rollup。

單報表缺內容：VEN 缺「需處置清單」(哪 2 台 offline/影響哪些 Workload)；Policy 缺 Deny 有效性/草稿風險數字 + 未使用規則明細(可清的死規則)；Audit 缺 Failed Logins(15 筆)展開 + 跨事件行動清單彙總；Traffic 缺資產清單/Top talkers(依 TB)、16,298 筆 Potentially Blocked 的上線衝擊評估、橫向移動的關係圖視覺化。

---

## 5. 建議推進順序

**Phase 0（看起來壞掉的，先止血，多為前端小改）**
修：dashboard 風險卡空白 + 流量卡標錯、分析器/排程 KPI 空、報表列 `B1 P1…`/「Attack posture」佔位字、規則表空白欄、`載入時間 現在` 改真實時間戳、報表重複 KPI header、NetworkInventory 套錯封面。

**Phase 1（安全與信任，資安產品必要）**
不安全預設（SSL 驗證/STARTTLS/憑證 CN）、每通道 test-send、Quarantine 排程確認護欄 + 雙狀態說明、設定變更稽核軌跡（最小可行版）。

**Phase 2（回答三大維運問題）**
重做即時總覽（VEN 健康 + Blocked Now + 管線健康 + 近期告警 + 新鮮度/自動刷新/下鑽）、Workload 預設盤點 + enforcement 欄、事件嚴重度篩選。

**Phase 3（管線可觀測 + 報表升級）**
時間窗速率/趨勢、回填進度、單筆 DLQ 檢視/重送結果、每目的地 SIEM 歷史；報表 delta 趨勢、甜甜圈換長條、推廣 Audit 卡片範本。

**Phase 4（治理深化）**
RBAC/多使用者/MFA/session、密鑰輪替、上傳 CA 憑證/CSR、規則匯入匯出。

---

*評估基於螢幕截圖目視判讀 + 程式碼結構；列印破版為依版面密度推斷，建議實際列印 A4 橫向各匯一份 PDF 驗證分頁。截圖：`tmp/uxaudit/`。*
