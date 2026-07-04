# Rule Hit Count Report 設計文件

日期：2026-07-05
狀態：已與 user 逐節確認定案
取代：`docs/superpowers/plans/2026-07-05-rule-hit-count-report.md` 的「api 近似計數」方向（該計畫將依本設計改寫）

## 定位

本報表是 **PCE 內建 Rule Hit Count 報表的增強器**：PCE 原生報表只有 Rule HREF + 命中統計，本功能把它增強成含完整規則明細（consumers/providers/services/enabled/類型）的報表。

- 命中數**一律**是 VEN 實測的原生數據（reports API 拉取或原生 CSV 匯入）。
- **不做**流量近似計數——那是既有 Policy Usage report 的職責，兩報表各司其職。
- 原生功能不可用時**只提示**改用 Policy Usage report 或啟用原生功能，不自動產任何報表。

## 原廠查證事實（NotebookLM Illumio 筆記本，2026-07-05）

| 項目 | 內容 |
|---|---|
| 版本門檻 | PCE：SaaS ≥ 24.2.0、地端 ≥ 23.5.10；VEN ≥ 23.2.30 |
| PCE 端啟用 | `PUT /api/v2/orgs/:org/report_templates/rule_hit_count_report` `{"enabled": true}` |
| VEN 端啟用 | `PUT /api/v2/orgs/:org/sec_policy/draft/firewall_settings` 設 `rule_hit_count_enabled_scopes`（`[[]]`=全部；或 label scope 陣列），需 `POST /sec_policy` provision 才生效 |
| 產報 API | `POST /orgs/:org/reports` 帶 `report_template.href=/orgs/:org/report_templates/rule_hit_count_report`、`report_parameters.report_time_range`（last_num_days 或 start/end）、`rule_sets: []`（空=全部）；輪詢至 `done` 下載 CSV |
| 計數語意 | 只計 Active 規則；Essential Rules 不計；每筆 flow 最多歸因 100 條規則（超過截斷）；PCE 規則最佳化可能使合併規則同時累加（高估可能）；計數保留 90 天，last-hit 時間戳永久 |

## 第 1 節：整體架構與資料流

```
產生入口（GUI / CLI / 排程）
  └─ RuleHitCountGenerator
       ├─ 1. EnablementChecker（src/report/rule_hit_count_enablement.py）
       │     ├─ GET /report_templates/rule_hit_count_report → PCE 端 enabled?
       │     └─ GET /sec_policy/active/firewall_settings → rule_hit_count_enabled_scopes?
       ├─ 2a. 已啟用 → NativeReportPuller：POST /reports → 輪詢 done → 下載 CSV → 解析
       ├─ 2b. source=csv → 解析上傳的原生 CSV（與 2a 同一套解析器）
       ├─ 3. Enrichment：join build_rule_baseline + resolve_actor_str / resolve_service_str
       └─ 4. RuleHitCountHtmlExporter + CsvExporter
  └─ 未啟用且非排程 → 啟用精靈（第 2 節）；拒絕或排程 → 提示改用 Policy Usage，不產報表
```

與原 11-task 計畫的差異：
- **刪除** api 近似計數模式（`batch_get_rule_traffic_counts` 路線整條移除）。
- **新增** EnablementChecker 與 NativeReportPuller。
- CSV 解析、enrichment（`build_rule_baseline` 抽出重用）、exporter、6 個掛載點（scheduler dispatch、`_REPORT_PREFIXES`、GUI route、GUI 前端、CLI、i18n）沿用。

模組邊界：
- `rule_hit_count_enablement.py`：純偵測 + 啟用執行，回傳結構化狀態，不碰報表邏輯；CLI 精靈與 GUI 對話框共用。
- `rule_hit_count_generator.py`：來源選擇、解析、enrichment、Result 組裝、export。
- NativeReportPuller 放在 `src/api/reports.py`（新檔，與 `src/api/traffic_query.py` 同層），經 `ApiClient` facade 暴露 `pull_rule_hit_count_report(time_range, rule_sets=[]) -> csv_path`；generator 只消費 facade，不直接打 HTTP。

## 第 2 節：啟用偵測與啟用精靈

**偵測**（每次產生報表時執行，兩個 GET）：
- 三態：`enabled`（雙邊皆開）／`partial`（單邊，註明缺哪邊）／`disabled`。
- 版本門檻檢查：PCE product_version 不足 → 直接告知不可用原因，不進精靈。VEN 版本不逐台檢查，於精靈文案提醒「VEN < 23.2.30 不會回報」。

**啟用精靈**（CLI questionary / GUI 確認對話框，共用後端函式）：
1. 顯示現狀與影響，**明確警告**：VEN 端啟用需修改 draft firewall_settings 並執行 policy provision（生產 policy 寫入操作）。
2. 詢問範圍：全部 VEN（`[[]]`）或指定 label scope（重用 filter 物件選擇器）。
3. 依序執行：PCE 端 PUT → VEN 端 PUT draft → provision（`update_description: "Enable rule hit count (illumio-ops)"`）。
4. 成功後提示 VEN 需時間回報，**不**立刻自動產報表。
5. 全程 ModuleLog；任一步失敗即停，回報已完成/未完成步驟與補救指令。

**排程**：未啟用 → skip + warning log。絕不詢問、絕不自動啟用、絕不改產 Policy Usage。

## 第 3 節：報表內容與呈現

KPI 列：規則總數／有命中／未命中／命中率／總命中次數。

三節：
1. **有命中規則**（命中次數降序）：Ruleset、編號、類型、說明、Consumers、Providers、Services、啟用、命中次數、距上次命中天數。
2. **未命中規則**：時窗內命中 0。
3. **清理候選**：`enabled=true` 且（未命中 或 `days_since_last_hit ≥ 90`），依 days 降序；90 天為常數可調（不做設定 UI）。

**數據語意注記**（報表頂部固定顯示）：VEN 實測、僅 Active 規則、Essential Rules 不計；規則最佳化可能高估；每 flow 最多 100 條歸因；計數保留 90 天（last-hit 永久）；CSV 模式標注資料時窗來自 CSV 的 Start/End Date。

截斷政策：長欄位（consumers/providers/services/description）160 字元截斷 + `…`，完整值在 `title` 屬性與 CSV 匯出；表格置於水平捲動容器（CLAUDE.md 報表規則）。

輸出：HTML + CSV zip；檔名前綴 `Illumio_Rule_Hit_Count_Report_`；retention 沿用 `_REPORT_PREFIXES` 機制。無 xlsx。

## 第 4 節：錯誤處理與測試

錯誤處理：
- 輪詢逾時（預設 10 分鐘）→ 回報 report UUID，提示可稍後 CSV 上傳補產。
- CSV 欄位不認得 → `ValueError` 附實際欄位清單；`_CSV_ALIASES` 為擴充點。
- Enrichment 失敗 → 非致命，明細欄空 + 頂部注記。
- 啟用半途失敗 → 停止並回報狀態與補救指令。
- 排程拉取失敗 → raise 交 scheduler 既有錯誤路徑。

測試：
- EnablementChecker 三態 + 版本門檻（mock）。
- 啟用流程步驟順序、provision payload、半途失敗停止（mock，驗證不發真請求）。
- NativeReportPuller submit→poll→download 狀態機與逾時（mock）。
- 解析/enrichment/exporter/CLI/GUI/scheduler dispatch 沿用原計畫測試清單（移除 api 近似模式測試）。
- 端到端：樣本 CSV 完整輸出逐頁截斷檢查 + zh_TW（CLAUDE.md 規則）。

## 非目標

- 不自動啟用（永遠人為確認）
- 不做 xlsx、trend snapshot、dashboard summary
- fallback 不自動產 Policy Usage
- 不從已 ingest 的 flows 計算命中數
- 不做清理候選門檻的設定 UI
