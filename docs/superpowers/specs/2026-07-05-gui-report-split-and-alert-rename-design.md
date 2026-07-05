# GUI 報表拆三入口 + Rules→告警 改名設計

日期：2026-07-05
狀態：已與使用者逐段確認

## 背景與問題

兩個獨立但一起處理的 GUI 缺口：

### 問題 A：報表在 GUI 沒有真的拆分
2026-07-02 的報表拆分計畫（`docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md`）已把 Traffic / Security / Inventory 拆成三份獨立報表，但**只有 CLI 與後端落地**：

- CLI：`report traffic` / `report security` / `report inventory` 三個獨立命令（`src/cli/report.py`）。
- 排程後端：`report_scheduler.py:314-338` 已分別 dispatch `traffic` / `security_risk` / `network_inventory` 三種 report_type。
- ad-hoc 後端：`/api/reports/generate` 的 `_run_adhoc` 接受 `_VALID_PROFILES = ("traffic","security_risk","network_inventory")`（`src/gui/routes/reports.py:302`）。

**GUI 沒跟上**：
- ad-hoc「產生報表」只有一張「流量報表」卡，靠 modal 內一個 profile 下拉切換，而該下拉（`index.html:2845-2846`）只有 `security_risk` / `network_inventory`，**漏了新的 `traffic` profile**，且預設是 `security_risk`。結果：GUI 使用者產不出新的純流量報表，預設還是拿到舊的 Security 報表。
- 排程下拉（`index.html:1522`）只有「Traffic Flow Report」一個選項，無法排 Security / Inventory（後端明明支援）。

本案是「把已是三向的後端，在 GUI 補齊」，非新功能。

### 問題 B：「規則」分頁名稱不清楚
主導覽的「規則 / Rules」分頁（`p-rules`）內容其實是**告警規則**：Event、System Health、Connection Count、Bandwidth 這類條件觸發的監控規則（欄位 Condition / Status / Filters），面板內有 Send Test Alert、alert channel status 等；與 Illumio 防火牆 policy rule 無關。命名用「規則 / Rules」造成混淆，且總覽區已有「告警 / Alerts」磚（`gui_ov_alerts_title`）。使用者要求改名為「告警 / Alert」。

**重要區隔（已查證後與使用者確認）**：「規則排程 / Rule Scheduler」分頁（`p-rule-scheduler`、`gui_rs_tab`）是 **Illumio Ruleset / Rule 的排程**（Ruleset Name/ID、Rule ID、Ruleset Logs、allow/block、active/draft、provision），跟告警無關，此處「規則」用得正確，**完全不動**。

## 已確認的決策

| 決策點 | 結論 |
|---|---|
| 報表拆分呈現 | ad-hoc 拆成三張獨立卡（Traffic / Security / Inventory），移除 profile 下拉，每卡固定 profile |
| 排程範圍 | 一起補：排程下拉加 Security / Inventory 兩選項 |
| modal 型別命名 | 型別即 profile 名（`traffic` / `security_risk` / `network_inventory`），不另設對照表 |
| 改名範圍 | 只改告警規則功能（`p-rules`）；Rule Scheduler 不動 |
| 主分頁 key | 新增 `gui_tab_alerts`（不沿用 `gui_tab_rules`，該 key 仍被子分頁用） |
| 子分頁命名 | 維持「規則 | 操作」（`gui_tab_rules` / `gui_tab_actions` 不動） |
| 個別「規則」用語 | 當單一設定單位的「規則」保留；只有功能整體稱呼改「告警」 |
| 總覽告警磚指向 | 不動（見下方「不做的事」說明） |
| 後端 / CLI | 一律不動（已是三向） |

## A. 報表拆三入口（前端 + i18n，後端零改動）

### A1. ad-hoc「產生報表」卡片（`index.html` 約 1334-1346）
單張「流量報表」卡 → 三張獨立卡，各一個 Generate 按鈕：

| 卡片 | data-args | 固定 profile | 標題 i18n | 描述 i18n |
|---|---|---|---|---|
| 流量報表 | `["traffic"]` | traffic | `gui_btn_traffic_report`（沿用） | `gui_rcard_traffic_desc`（**改寫**，見下） |
| 安全與風險報表 | `["security_risk"]` | security_risk | `gui_rcard_security_title`（新） | `gui_rcard_security_desc`（新） |
| 資產盤點報表 | `["network_inventory"]` | network_inventory | `gui_rcard_inventory_title`（新） | `gui_rcard_inventory_desc`（新） |

- `gui_rcard_traffic_desc` 現值「流量摘要，涵蓋 Security Risk / Network Inventory 兩種視角」已與拆分後語意不符（obs 4610），改寫為純流量描述（如「純流量事實：連線、Ports/Protocols、頻寬與傳輸量」）。

### A2. ad-hoc modal（`dashboard.js` 約 629-685；`index.html` 2842-2848）
- `openReportGenModal` 的 `meta` map（line 631）加 `security_risk`、`network_inventory` 兩型，欄位版面沿用 `traffic`（source / filters / data-source 列）。
- **移除** profile 下拉列：刪 `index.html:2842-2848`（`m-gen-profile-row`）與 `dashboard.js` 中顯示/重置它的邏輯（line 647、661、668 對 `m-gen-profile-row` 的操作）。
- 分支條件 `type === 'traffic'`（line 644）改為「三種 traffic profile 皆適用」的判斷（例如 `TRAFFIC_PROFILE_TYPES.includes(type)`），讓三型都顯示 source/filters/data-source。
- data-source 支援判斷（line 681 `type === 'traffic'`）同步擴為三型。
- 進度標題 `typeLabels`（line 731）加 `security_risk` / `network_inventory` 兩 key。
- 送出（`_doGenerateTraffic`，line 921、954-961）：把讀 `m-gen-profile` 改為 `traffic_report_profile: _genReportType`（型別即 profile）。CSV 路徑（line 921）同法。
- 派工路由（line 742）：`_genReportType` 為三型之一時皆走 `_doGenerateTraffic`。

### A3. 排程（`index.html:1521-1522`；`dashboard.js`）
- `sched-report-type` 加兩 option：`value="security_risk"`（`gui_sched_rt_security`）、`value="network_inventory"`（`gui_sched_rt_inventory`）。值需與後端 report_type 完全一致。
- 排程列表 `typeLabels`（`dashboard.js:308`）加 `security_risk` / `network_inventory` 兩 key。
- `onSchedReportTypeChange` / `_collectSchedFilters` 中以 `rt === 'traffic'` gate filter 區與 window 的判斷（`dashboard.js:372`、`409-410`、`438`）擴為「三種 traffic profile 皆為 traffic-based」，讓 Security / Inventory 排程也能設 filter/window（與 ad-hoc 一致）。

### A4. i18n（en + zh_TW，兩檔同步）
新增：`gui_rcard_security_title`、`gui_rcard_security_desc`、`gui_rcard_inventory_title`、`gui_rcard_inventory_desc`、`gui_gen_security_title`、`gui_gen_inventory_title`、`gui_sched_rt_security`、`gui_sched_rt_inventory`。
改寫：`gui_rcard_traffic_desc`。
（報表本身標題 `rpt_security_report_title` / `rpt_inventory_report_title` 已存在，供對照命名。）

## B. Rules → 告警 改名（只動告警規則功能）

功能整體稱呼 →「告警 / Alerts」，個別「規則」設定單位保留。實際清單：

| 位置 | 現況 | 改動 |
|---|---|---|
| 主分頁（`index.html:187`） | `data-i18n="gui_tab_rules"`（規則 / Rules） | 改為 `data-i18n="gui_tab_alerts"`（**新 key**：告警 / Alerts） |
| header 計數 chip（`index.html:119`） | `gui_rules_count`（規則數 / Rules） | 值改為 告警數 / Alerts |
| header aria 模板（`i18n:gui_hdr_chip_aria`） | 「{rules} 條規則」 | 措辭改為「{rules} 條告警」（en 對應 alerts） |
| 子分頁 Rules（`index.html:1235`） | `gui_tab_rules`（規則） | **不動** |
| 子分頁 Actions（`index.html:1236`） | `gui_tab_actions`（操作） | 不動 |
| `gui_ruletype_*`、`gui_add_*`、表格欄、best-practices 文案等 | 個別規則單位 | 不動 |
| Rule Scheduler（`p-rule-scheduler`、`gui_rs_*`） | Illumio 規則排程 | **完全不動** |

- 新 key `gui_tab_alerts` 於 en + zh_TW 兩檔新增。`gui_tab_rules` 保持不變（仍供子分頁）。

## 不做的事

- 不動 CLI、不動後端 dispatch / generator（已是三向）。
- 不動 Rule Scheduler（`p-rule-scheduler`）。
- 不重構報表管線、不改報表內容。
- **總覽「告警」磚不改指向**：`gui_ov_alerts_title`（告警）磚目前連到 Event Viewer（`data-tab="events"`），顯示的是告警**事件流**；新「告警」分頁（`p-rules`）是告警**規則設定**。兩者語意不同，本案維持現狀，僅在此註明；若日後要統一導覽再另議。

## 測試 / 驗證策略

### 前端行為
- 三張卡各自開對的 modal（標題正確、無 profile 下拉）；送出後 `/api/reports/generate` payload 帶對的 `traffic_report_profile`（traffic / security_risk / network_inventory 各驗一次）。
- 排程可新增 Security / Inventory 兩型並正確存入（report_type 值正確）、列表顯示正確標籤、可觸發產出。
- filter/window 區在三種 traffic profile 下皆顯示。

### 改名
- 主分頁顯示「告警 / Alerts」、chip 顯示「告警數 / Alerts」、子分頁仍「規則 | 操作」；en / zh_TW 皆正確。
- Rule Scheduler 分頁文字未受影響。
- grep 確認 `gui_tab_rules` 僅剩子分頁一處使用（主分頁已改 `gui_tab_alerts`）。

### 報表產出（依專案 CLAUDE.md 報表規則）
- 用實際樣本資料實跑 Traffic / Security / Inventory 三份報表各一次，逐頁檢查無截斷 / 溢出，檢查結果附在回報。

### 測試套件
- 既有測試（含 i18n 鍵完整性、CLI compat matrix）保持綠燈；新 i18n key 補齊 en / zh 對應以通過鍵一致性檢查。

## 實作分期建議（供 writing-plans 參考）

1. Phase 1：i18n 鍵（A4 + B 新 key / 改值，en + zh 同步）。
2. Phase 2：報表拆三入口——卡片（A1）+ modal 拆 profile 下拉、送出改帶固定 profile（A2）+ 排程下拉與 typeLabels（A3）。
3. Phase 3：Rules→告警 改名（B：主分頁 key、chip、aria）。
4. Phase 4：實跑三報表逐頁檢查 + 全套 pytest。

各期可獨立交付；Phase 1 為其餘前置。
