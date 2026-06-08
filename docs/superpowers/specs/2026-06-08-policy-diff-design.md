# 設計：Policy Diff（DRAFT vs ACTIVE 欄位級差異 + 操作者歸因）

- **日期**：2026-06-08
- **範圍代號**：P2（借鏡 alexgoller/illumio-plugger 系列的優化規劃，第二項）
- **狀態**：設計待實作（spec → writing-plans）

## 1. 背景與方向

PCE 的安全政策有兩個版本面：**DRAFT**（已編輯但尚未 provision）與 **ACTIVE**（已 provision、實際生效）。營運人員常見痛點是「DRAFT 與 ACTIVE 到底差在哪、誰改的、改了什麼」——目前 illumio-ops 沒有任何一處把這個差異攤平成可閱讀的清單。既有 Audit 報表 `audit_mod03_policy` 能告訴你「發生過哪些政策事件、誰做的」，但它是**事件流**，不是**狀態差異**：它看不出「目前 DRAFT 相對 ACTIVE 的淨差異」。

本 spec 的方向是把這兩個面向接起來：以 **DRAFT vs ACTIVE 的狀態 diff 為核心**（git-like、欄位級），再用**既有 audit 事件管線**補上操作者歸因。完全建立在既有資產之上、零新增 PCE 蒐集型 endpoint（draft 與 active rule_sets 都已可抓），維持氣隙友善。

本 spec 只含一條垂直切片，皆為純衍生 + 既有 API 重用：

- **核心 — 狀態 diff**：抓 draft 與 active 兩份 ruleset，對齊後逐 Ruleset / 逐 Rule / 逐欄位比對，產出 added / removed / modified 三類差異列。
- **歸因 — operator attribution**：把既有 audit 事件（`audit_policy_changes`）以 Ruleset / Rule href 對映到差異列，標註「最近一次改動的操作者與時間」。

明確排除（YAGNI / 已鎖定）：

- **物件範圍只含 Ruleset / Rule**。IP lists、services、label groups、virtual services、firewall settings 一律不在 v1。
- **snapshot 歷史 / 趨勢**不在 v1（只做即時 draft-vs-active 活差異）。
- 不新增合規對映、不新增 LLM 敘述、不做 provision 動作（純唯讀報表）。

## 2. 現況（不得破壞 / 直接重用）

### 2.1 可重用 API（已驗證簽章）

`src/api_client.py`：

- `get_all_rulesets(force_refresh: bool = False) -> list[dict]`（行 737）
  → `GET /orgs/{org}/sec_policy/draft/rule_sets?max_results=10000`，回 **DRAFT** rulesets（含 rules）。**有快取**（`self.ruleset_cache`）。
- `get_active_rulesets() -> list[dict]`（行 748）
  → `GET /orgs/{org}/sec_policy/active/rule_sets?max_results=10000`，回 **ACTIVE** rulesets（含 rules）。無快取。
- `get_ruleset_by_id(rs_id) -> dict | None`（行 764）— v1 不需要（已用整批抓取）。

> **關鍵驗證結論：draft 與 active rule_sets 兩端皆已可整批抓取，無須新增 fetch 方法。** Spec 不引入新的 PCE endpoint。

### 2.2 可重用歸因管線（已驗證）

`src/report/audit_generator.py`：

- `AuditGenerator(config_manager, api_client, config_dir, *, cache_reader)`（行 424）
- `_fetch_events(start, end) -> (events, source)`（行 434）— cache-aware 混合抓取。
- `_build_dataframe(events) -> pd.DataFrame`（行 505）— 經 `src.events.normalize_event` 正規化，欄位含 `event_type`、`actor`（缺則退回 `created_by`）、`resource_name`、`change_detail`、`timestamp`、`severity`。

`src/report/analysis/audit/audit_mod03_policy.py`：

- `audit_policy_changes(df) -> dict`（行 81）— 已過濾 `_DRAFT_RULE_EVENTS`（`rule_set.create/update/delete`、`sec_rule.create/update/delete`），輸出 `draft_events`（含 `timestamp / event_type / resource_name / actor / change_detail`）等 DataFrame。歸因即重用此模組的事件集。

### 2.3 可重用報表骨架（已驗證）

- Facade 形狀：`SecurityRiskReport(cm, api_client, config_dir, cache_reader).run(output_dir, lang) -> str`（`src/report/security_risk_report.py`）。新報表 facade 比照。
- CSV：`CsvExporter(results: dict, report_label: str).export(output_dir) -> str`（`src/report/exporters/csv_exporter.py`）— 通用走訪 `module_results` 內所有非空 DataFrame、打包成 ZIP。**無須改它**，只要把 module_results 餵成它能走訪的形狀（dict of DataFrame）。
- HTML：既有 exporter（`src/report/exporters/`）以 `module_results` + `lang` 渲染；新報表用一支精簡專屬 HTML exporter（見 §4.3）。

### 2.4 CLI / scheduler 既有接點（已驗證）

- CLI `report` 是 click group（`src/cli/report.py`）；既有 `report security`、`report inventory` 為 command。新增 `report policy-diff`。
- Scheduler 以 `report_type` 字串分派（`src/report_scheduler.py:_generate_report`，行 248）；`_REPORT_PREFIXES`（行 469）與 email `type_label`（行 322）在 ff93df9 已為 `security_risk` / `network_inventory` 接好——新 `policy_diff` 比照那次 commit 的兩個落點接上。

## 3. 核心 — 狀態 diff

### 3.1 介面

新分析模組 `src/report/analysis/policy_diff/diff_engine.py`，純函式（**不做 I/O**，吃已抓好的兩份 list）：

```python
def diff_rulesets(draft: list[dict], active: list[dict]) -> dict:
    """純衍生：對齊 draft 與 active rulesets，回傳欄位級差異結構。"""
```

回傳結構（供 exporter + CSV 走訪）：

```json
{
  "ruleset_changes": {  # added / removed / modified Rulesets（DataFrame）
    "...": "pandas.DataFrame[change_type, ruleset_name, ruleset_id, field, draft_value, active_value]"
  },
  "rule_changes": {     # added / removed / modified Rules（DataFrame）
    "...": "pandas.DataFrame[change_type, ruleset_name, rule_id, field, draft_value, active_value]"
  },
  "summary": {
    "rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
    "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
    "total_changes": 0
  }
}
```

### 3.2 對齊鍵（identity）

- Ruleset 與 Rule 的穩定 identity 取自 `href` 的尾段數字 id（draft 與 active 同物件共用相同數字 id；href 前綴 `/draft/` vs `/active/` 不同，須剝除後比對）。
- 提供 `_rule_id(href)` / `_ruleset_id(href)`：取 `href.rstrip("/").split("/")[-1]`。
- 對齊後分三類：
  - **added**：id 只在 draft（DRAFT 新增、尚未 provision）。
  - **removed**：id 只在 active（DRAFT 已刪、active 仍生效）。
  - **modified**：id 兩邊都有但欄位值不同。

> 語意定位：diff 是「**DRAFT 相對 ACTIVE**」。added = DRAFT 將新增的；removed = DRAFT 將移除的；modified = DRAFT 將變更的。

### 3.3 比對欄位（Ruleset / Rule ONLY）

逐 Rule 比對的欄位白名單（與既有 `pu_mod*` 對 rule 的取值一致，避免造輪子）：

| 欄位 | 取值 | 正規化方式 |
|---|---|---|
| `enabled` | `rule.get("enabled", True)` | bool → str |
| `providers` | `rule.get("providers", [])` | 摘要成穩定字串（見 §3.4） |
| `consumers` | `rule.get("consumers", [])` | 同上 |
| `ingress_services` | `rule.get("ingress_services", [])` | 同上 |

逐 Ruleset 比對的欄位白名單：

| 欄位 | 取值 |
|---|---|
| `name` | `rs.get("name", "")` |
| `enabled` | `rs.get("enabled", True)` |
| `description` | `rs.get("description", "")` |
| `rule_count` | `len(rs.get("rules", []))`（衍生計數，方便一眼看出增減） |

每個有差異的欄位產出**一列** `(change_type="modified", ..., field, draft_value, active_value)`；added / removed 的物件各以單列代表（`field="*"`、對側值留空），避免一個新 Rule 炸出 N 列噪音。

### 3.4 值正規化（穩定可比、避免假差異）

actor / service 清單在 PCE JSON 內是 list of dict（含 label/ip_list/workload href 等），順序不保證。`_summarize_actors(items)`：

- 對每個 item 取其穩定識別（依序嘗試 `label.href` → `ip_list.href` → `workload.href` → `actors`("ams") → `str(item)`），收成 set，**排序後 join**。
- service item 取 `proto`/`port`/`href`，同樣排序 join。
- 空 list → `"(any)"`（對齊 PCE「unscoped = any」語意）。

目的：避免「同一組 providers 只是 JSON 順序不同」被誤判為 modified。

### 3.5 邊界

- draft 或 active 任一為空 list（API 失敗或無政策）→ `diff_rulesets` 仍回合法空結構（summary 全 0、各 DataFrame 為空），不丟例外。
- 某 Rule 缺 `href`（理論上不應發生）→ 該 Rule 略過比對，不污染結果。

## 4. 歸因 — operator attribution

### 4.1 介面

`src/report/analysis/policy_diff/attribution.py`，純函式：

```python
def attribute_changes(diff: dict, policy_events: dict) -> dict:
    """以 audit 事件對 diff 各列補上 last_actor / last_changed / last_event。
    policy_events 為 audit_policy_changes(df) 的輸出。回傳 diff（就地擴充欄位）。"""
```

### 4.2 對映方式

- 從 `policy_events["draft_events"]`（DataFrame）取 `resource_name`、`actor`、`timestamp`、`event_type`。
- 對 diff 內每個 Ruleset / Rule 列，以 **ruleset_name / 物件名稱**對 `resource_name` 做比對（PCE audit 事件以 `resource_name` 帶物件名稱），取**時間最新**的一筆事件，寫入該列的 `last_actor`、`last_changed`、`last_event` 欄。
- 找不到對應事件（事件窗未涵蓋）→ 三欄留 `""`（不假填、不丟例外）。

> 設計取捨（揭露）：attribution 以**物件名稱**而非 href 對映，因為 audit 事件的 `resource_name` 是名稱、未必含可剝 id 的 href。名稱碰撞風險低（同一 Ruleset 下物件名稱通常唯一），且取「最新一筆」已足夠回答「最近誰改的」。href 級精準對映留待後續（需 audit normalizer 暴露 resource href）。

### 4.3 落點與資料窗

歸因事件窗：預設取最近 N 天（與既有 audit 報表預設窗一致，由 `PolicyDiffReport` 決定 start/end 後交給 `AuditGenerator._fetch_events`）。窗外的改動歸因留空——這是即時 diff 的已知限制，於報表頁面以 footnote 說明。

## 5. 報表落點（新報表模組，比照既有 report engine）

### 5.1 Facade

新檔 `src/report/policy_diff_report.py`，比照 `SecurityRiskReport`：

```python
class PolicyDiffReport:
    def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None): ...
    def run(self, output_dir="reports", lang="en") -> str:
        # 1. draft = api.get_all_rulesets();  active = api.get_active_rulesets()
        # 2. diff = diff_rulesets(draft, active)
        # 3. events_df = AuditGenerator(...)._fetch_events()+_build_dataframe()（重用）
        #    policy_events = audit_policy_changes(events_df)
        # 4. attribute_changes(diff, policy_events)
        # 5. HTML：PolicyDiffHtmlExporter(diff, lang).export(output_dir)
        # 6. （fmt=csv 時）CsvExporter(module_results, "Policy_Diff").export(output_dir)
        # 回傳產出檔路徑（無差異時仍產出「無差異」報表，回傳路徑；不回空字串以利 scheduler）
```

### 5.2 HTML exporter

新檔 `src/report/exporters/policy_diff_html_exporter.py`，比照既有 exporter 慣例（吃 dict + lang、回 path）。版面三段：summary 卡片、Ruleset 差異表、Rule 差異表；每列以 change_type 著色（added=綠 / removed=紅 / modified=黃），尾欄顯示 `last_actor @ last_changed`。

### 5.3 module_results 形狀（給 CsvExporter 直接走訪）

`PolicyDiffReport` 內把 diff 攤成 `module_results = {"ruleset_changes": <DataFrame>, "rule_changes": <DataFrame>, "summary": <dict>}`，`CsvExporter` 既有的 `_iter_dataframes` 會自動把兩個 DataFrame 各寫一個 CSV、打包 ZIP，**無須改 CsvExporter**。

## 6. CLI + scheduler 接線（mirror ff93df9）

### 6.1 CLI

`src/cli/report.py` 新增 `report policy-diff` command（比照 `report security`）：`--source`（僅 api，policy diff 不吃 csv）、`--format`（html / csv / all）、`--output-dir`、`--email`。handler 走 `PolicyDiffReport(...).run(...)`（或 fmt 分派到 HTML / CsvExporter）。

### 6.2 Scheduler（兩個落點，比照 ff93df9）

1. `_generate_report`（`report_scheduler.py:248`）新增分支：
   ```python
   elif report_type == "policy_diff":
       from src.report.policy_diff_report import PolicyDiffReport
       rpt = PolicyDiffReport(self.cm, api_client=api, config_dir=self._config_dir,
                              cache_reader=_make_cache_reader(self.cm))
       path = rpt.run(output_dir=output_dir, lang=lang)
       return (rpt_result_or_none, [path] if path else [])
   ```
2. `_REPORT_PREFIXES`（行 469）新增 `"policy_diff": "Illumio_Policy_Diff_Report_"`。
3. email `type_label`（行 322）新增 `"policy_diff": t("rpt_policy_diff_report_title", lang=lang)`。

## 7. i18n

- 報表標題 / 區段：`rpt_policy_diff_report_title`、`rpt_policy_diff_summary`、`rpt_policy_diff_ruleset_changes`、`rpt_policy_diff_rule_changes`、`rpt_policy_diff_no_changes`、`rpt_policy_diff_attribution_note`。
- 欄位 / 變更類型標籤：`rpt_policy_diff_col_change_type`、`rpt_policy_diff_col_field`、`rpt_policy_diff_col_draft`、`rpt_policy_diff_col_active`、`rpt_policy_diff_col_actor`、`rpt_policy_diff_added`、`rpt_policy_diff_removed`、`rpt_policy_diff_modified`。
- EN 與 ZH_TW 雙檔同步補齊；遵守 glossary preserve-list——**Ruleset / Rule / Policy / PCE / DRAFT / ACTIVE 等術語在 zh_TW 保持英文**；新增後跑 `python scripts/audit_i18n_usage.py` 驗證 parity 與 glossary。

## 8. 測試

- **diff 對齊與分類**：合成 draft / active 兩 list → 驗證 added / removed / modified 正確分類、summary 計數正確。
- **欄位級比對**：同一 Ruleset 下改 rule 的 `enabled` / `providers` → 驗證只產出該欄位列、draft/active 值正確。
- **值正規化抗假差異**：同組 providers 只調順序 → 不應判為 modified。
- **邊界**：draft / active 任一空 → 回合法空結構、不丟例外。
- **歸因對映**：合成 diff + 合成 `draft_events` → 驗證最新一筆事件的 actor / timestamp 寫入正確列；窗外無事件 → 欄位留空。
- **CSV 形狀**：`module_results` 經 `CsvExporter` 能寫出 ruleset_changes.csv / rule_changes.csv（重用既有 exporter，無改動）。
- **scheduler 接線**：`_REPORT_PREFIXES` 含 `policy_diff`；prune-by-count 對新型別不報錯（比照 ff93df9 的回歸測試）。
- **i18n parity**：新 key EN/ZH_TW 齊備且通過 audit。

## 9. 風險與緩解

- *風險*：attribution 以名稱對映可能碰撞或錯掛 → *緩解*：取「最新一筆」且僅作參考欄；footnote 揭露限制；href 級精準對映列為後續。
- *風險*：actor / service 清單 JSON 順序差異造成假 modified → *緩解*：`_summarize_actors` 排序後比對，並以「抗假差異」測試把關。
- *風險*：draft 快取（`get_all_rulesets` 有 `ruleset_cache`）導致抓到舊 draft → *緩解*：`PolicyDiffReport.run` 以 `force_refresh=True` 取 draft，確保即時。

## 10. 後續（不在本 spec）

- snapshot 歷史 / diff 趨勢化（重用 `trend_store`）。
- 物件範圍擴大到 IP lists / services / label groups / firewall settings。
- href 級精準歸因（需 audit normalizer 暴露 resource href）。
- P3–P5：Policy Resolver、Teams 告警連接器、AI 輔助規則建議（各自獨立 spec）。
