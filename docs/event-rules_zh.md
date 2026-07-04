---
title: 事件規則說明（Event Rules）
audience: [operator, security]
version: 4.1.0
last_verified: 2026-06-26
verified_against:
  - src/analyzer.py
  - src/report/rules_engine.py
  - src/report/rules/
  - src/events/
  - src/report/analysis/
---

# 事件規則說明（Event Rules）— illumio-ops v4.1.0

> 本文件說明 illumio-ops 內部的**規則判斷**與**分析方法**：系統如何決定要對什麼發出告警（alert），以及如何分析 traffic 流量與安全 posture。內容**逐條對照原始碼**列出實際實作的規則，未實作者不列入。
>
> 詞彙（PCE、VEN、Workload、Service、Port、Policy、Ruleset、flow、policy_decision、draft_policy_decision 等）保留英文原文。

---

## 1. 總覽：兩套判斷系統 ＋ 一條事件管線

illumio-ops 內部有**兩套獨立的規則判斷引擎**，加上一條**事件處理管線**：

| 系統 | 程式位置 | 觸發時機 | 判斷對象 | 輸出 |
|------|----------|----------|----------|------|
| **即時監控規則引擎**（Real-time Monitor Rule Engine）| `src/analyzer.py` | 每個監控週期（預設每 300 秒，由 scheduler 觸發 `Analyzer.run_analysis()`）| PCE audit **events** ＋ 即時 **traffic flows** | 派送告警（event / traffic / metric / health alert）到各通道 |
| **報表安全規則引擎**（Report Security Rule Engine）| `src/report/rules_engine.py` ＋ `src/report/rules/` | 產生報表時（`ReportGenerator._run_pipeline`）| 一份「unified DataFrame」彙整的 flows | 一組 `Finding`（規則命中清單），供 Module 12 摘要與 HTML/Excel 匯出 |
| **事件管線**（Event Pipeline）| `src/events/` | 即時監控引擎的事件階段呼叫 | 原始 PCE events | 正規化、去重、節流、分類（已知/未知）、影子比對、統計、runbook 對應 |

### 兩套引擎的本質差異

- **即時監控規則引擎**是「條件比對 + 門檻 + 冷卻」型：每條規則是一份設定字典（存於 `config/alerts.json`），描述要比對的 event type / flow 條件、門檻值與運算子。命中且超過門檻就派送告警。規則由使用者自訂或套用「最佳實務」預設集。
- **報表安全規則引擎**是「程式化偵測邏輯」型：每條規則（B/L/R 系列）是一段寫死的 Python 偵測函式，跑在彙整後的 flow DataFrame 上，依網路情境（cross-subnet、cross-env、是否 allowed）決定**嚴重度**，並附上 MITRE ATT&CK 對應與建議。共 **24 條**已實作規則。

### 規則總數速覽（依原始碼實際清點）

| 類別 | 實作 ID | 數量 |
|------|---------|------|
| 即時監控規則「型別」 | event / traffic / bandwidth / volume / system | 5 種型別 |
| 預設出廠告警規則 | `config/alerts.json` ID 18–34（`apply_best_practices`）| 16 event ＋ 1 traffic ＝ 17 條 |
| 報表 B 系列（勒索/覆蓋率）| B001–B009 | 9 |
| 報表 L 系列（橫向移動/外洩）| L001–L010 | 10 |
| 報表 R 系列（Draft policy 對齊）| R01–R05 | 5 |
| **報表安全規則合計** | | **24** |

> **「24 條規則」核對結果：正確。** B 系列 9 ＋ L 系列 10 ＋ R 系列 5 ＝ 24，與稽核宣稱一致。報表規則引擎檔頭註解雖寫「B001–B009, L001–L010」，R 系列另存於 `src/report/rules/`；三者加總恰為 24。

---

## 2. 即時監控規則（Real-time Monitor Rules）

程式核心：`src/analyzer.py` 的 `Analyzer` 類別。一個監控週期 `run_analysis()` 依序執行：

1. `_run_health_check()` — system / `pce_health` 規則
2. `_run_event_analysis()` — event 規則
3. `_fetch_traffic()` ＋ `_run_rule_engine()` — traffic / bandwidth / volume 規則
4. `_dispatch_alerts()` — 派送 traffic 類告警
5. `save_state()` — 持久化水位（watermark）、歷史、冷卻狀態

規則統一存於 `config/alerts.json` 的 `rules` 陣列；每條都有 `type` 欄位區分五種型別。

### 2.1 五種規則型別與觸發運算子

| `type` | 觸發指標來源 | 門檻運算子 | 跨 flow 的累加方式 | 派送方法 |
|--------|--------------|------------|--------------------|----------|
| `event` | 命中事件數 | `count_val >= threshold_count`（且 `> 0`）| `immediate`：本批命中數；`count`：滑動視窗 `threshold_window` 分鐘內的歷史命中數（`_event_count_in_window`）| `reporter.add_event_alert` |
| `traffic` | 連線數 `num_connections` | `val >= threshold_count` | **加總**（sum）| `reporter.add_traffic_alert` |
| `volume` | 資料量（MB，`calculate_volume_mb`）| `val >= threshold_count` | **加總**（sum）| `reporter.add_metric_alert` |
| `bandwidth` | 頻寬（Mbps，`calculate_mbps`）| `bw_val > threshold_count`（**嚴格大於**）| **取最大值**（max）；任一 flow 超標即觸發 | `reporter.add_metric_alert` |
| `system` | PCE health 狀態碼 | health status **≠ 200** 即觸發 | —（呼叫 `api.check_health()`）| `reporter.add_health_alert` |

> 運算子差異由 `_build_criteria_str` 與 `_dispatch_alerts` 明示：**bandwidth 用 `>`，traffic/volume 用 `>=`**。`calculate_mbps` 以 delta bytes/`ddms`（Interval）為優先、total bytes/`tdms`（Avg）為次；`calculate_volume_mb` 同理（Interval → Total）。

> 除了上述輪詢式的 `system` health 狀態檢查外，PCE 本身約每分鐘還會發出 `system_health` 事件 —— 叢集健康時記錄為 **INFO** severity，只有當系統指標（CPU、記憶體、磁碟）超過閾值時才升級為 **Warning / Error / Fatal**。Illumio 的最佳實務是過濾 **severity Warning 以上** 來監控這些事件。（來源：Illumio「Events Described — Recommended Events to Monitor」。）

### 2.2 Flow 比對：`check_flow_match`

每條 traffic/bandwidth/volume 規則對每個 flow 呼叫 `check_flow_match(rule, f, start_time_limit)`，依序檢查：

1. **滑動視窗**：flow 的 `timestamp`（或 `timestamp_range.last_detected/first_detected`）早於 `now - threshold_window` 則排除。
2. **policy_decision（`pd`）**：flow 的 `pd` 數值化為 `0=allowed`、`1=potentially_blocked`、`2=blocked`（無 `pd` 欄時由 `policy_decision` 字串推斷）。規則 `pd` 預設為 `-1`（event 類）或 `3`（traffic 類）；**`-1` 與 `3` 皆代表「任意 PD」**，其餘需精確相等才命中。（註：此 `3` 是工具內部表示「任意 PD」的 sentinel，與 Illumio 原始 traffic 資料**不同** — 在後者中，flow 的 `pd` 為 `3` 代表 **「Unknown」**，例如處於 snapshot 狀態的閒置 VEN 回報的流量，或經 bulk-upload API 上傳的 flow。來源：Illumio「Traffic Flow Summaries」。）
3. **Port / Proto**：`rule.port`、`rule.proto` 需與 flow 的 `dst_port`／`service.port`、`proto`／`service.proto` 相等。
4. **Label / IP 包含過濾**：`src_label`、`dst_label`（支援 `key=value` 與 `key:value` 兩種分隔）、`src_ip_in`、`dst_ip_in`（比對 IP 或 ip_list 名稱）。
5. **任一側（any-side）包含**：`any_label`、`any_ip` — src **或** dst 任一符合即可。
6. **排除過濾**：`ex_port`、`ex_src_label`、`ex_dst_label`、`ex_src_ip`、`ex_dst_ip`，以及任一側排除 `ex_any_label`、`ex_any_ip`。

`_run_rule_engine` 逐 flow 算出 `bw_val`、`vol_val`、`conn_val`，再依型別累加到各規則的 `max_val` 與 `top_matches`；`_dispatch_alerts` 排序取 Top 10、組 criteria 字串後派送。

### 2.3 Event 比對：`matches_event_rule`（`src/events/matcher.py`）

event 規則用 `filter_value` 比對 event type，支援豐富運算子：

- **多型態樣**：`filter_value` 以逗號分隔多個 pattern，命中任一即算。
- **萬用字元**：`*` / `any` / `all` / 空字串 → 永遠符合。
- **管線替代**：`a|b|c`（非 regex 樣式時）→ 屬於集合即符合。
- **正規式**：含 `^ $ * + ? [ ] ( ) { } \` 或 `.* .+ .?` 者，以 `^pattern$` 錨定比對。
- **否定**：前綴 `!` → 反向。
- 另比對 `filter_status`（如 `failure`）與 `filter_severity`，以及 `match_fields`（巢狀欄位 dot-path）。

### 2.4 冷卻與節流：`_check_cooldown`

命中門檻後並非立即派送，需通過兩道閘：

1. **Cooldown**：`cooldown_minutes`（預設＝`threshold_window`，再預設 10 分鐘）。距上次同規則告警未滿冷卻時間 → 抑制（記為 `cooldown` suppression）。
2. **Throttle**（`AlertThrottler.allow`，`src/events/throttle.py`）：規則 `throttle` 欄為 `"count/period[unit]"`（unit：`s`/`m`/`h`/`d`，省略預設 `m`）。在滑動視窗 `period` 內已派送達 `count` 次 → 抑制（記為 `throttle` suppression）。

### 2.5 預設出廠規則（Best-Practice Rule Set）

由 `src/config.py` 的 `_best_practice_rules()` 產生（`apply_best_practices` 套用），同步落地於 `config/alerts.json`（ID 18–34）。共 **16 條 event ＋ 1 條 traffic**：

| ID | name_key | filter_value（event type）| 門檻型 | count | window(分) | cooldown(分) | throttle | 過濾 |
|----|----------|---------------------------|--------|-------|-----------|--------------|----------|------|
| 18 | `rule_agent_tampering` | `agent.tampering` | immediate | 1 | 10 | 30 | — | VEN agent 遭竄改 |
| 19 | `rule_agent_suspend` | `agent.suspend` | immediate | 1 | 10 | 30 | — | agent 被暫停（停止強制執行）|
| 20 | `rule_agent_clone` | `agent.clone_detected` | immediate | 1 | 10 | 30 | — | 偵測 cloned agent |
| 21 | `rule_agent_heartbeat` | `system_task.agent_missed_heartbeats_check` | count | 3 | 30 | 60 | `1/30m` | 心跳遺失 |
| 22 | `rule_agent_offline` | `system_task.agent_offline_check` | count | 3 | 30 | 60 | `1/30m` | agent 離線 |
| 23 | `rule_lost_agent` | `lost_agent.found` | immediate | 1 | 10 | 60 | — | lost-agent 復原 |
| 24 | `rule_login_failed` | `user.sign_in,user.login` | count | 5 | 10 | 30 | `1/15m` | `filter_status=failure`；登入失敗 |
| 25 | `rule_api_auth_failed` | `request.authentication_failed` | count | 5 | 10 | 30 | `1/15m` | API 認證失敗 |
| 26 | `rule_policy_fail` | `agent.refresh_policy` | immediate | 1 | 10 | 30 | — | `filter_status=failure`；Policy 刷新失敗 |
| 27 | `rule_ruleset_change` | `rule_set.create,rule_set.update,rule_set.delete` | immediate | 1 | 10 | 60 | — | Ruleset 變更 |
| 28 | `rule_policy_provision` | `sec_policy.create` | immediate | 1 | 10 | 60 | — | Security Policy 佈署 |
| 29 | `rule_api_authz_failed` | `request.authorization_failed` | count | 3 | 10 | 30 | `1/15m` | API 授權失敗 |
| 30 | `rule_api_key_change` | `api_key.create,api_key.delete` | immediate | 1 | 10 | 60 | — | API key 新增/刪除 |
| 31 | `rule_sec_rule_change` | `sec_rule.create,sec_rule.update,sec_rule.delete` | immediate | 1 | 10 | 60 | — | Security Rule 變更 |
| 32 | `rule_bulk_unpair` | `workloads.unpair,agents.unpair` | immediate | 1 | 10 | 60 | — | 批次 unpair（大規模解除強制）|
| 33 | `rule_auth_settings_change` | `authentication_settings.update` | immediate | 1 | 10 | 60 | — | 認證設定變更 |
| 34 | `rule_high_blocked` | （traffic，`pd=2`）| count | 25 | 10 | 30 | `1/15m` | 高 Blocked 流量 |

> **關於規則 20（`agent.clone_detected`）**：除了偵測 clone 之外，Illumio 對地端 Windows 網域加入（domain-joined）的 workload 原生支援**自動 cloned-VEN 修復**（automatic cloned VEN remediation）— 透過偵測 workload 網域 SID 的變更，自動修復被 clone 的 VEN。（來源：Illumio「Events Described — Automatic Cloned VEN Remediation」。）

> **i18n 鍵存放**：每條規則持久化的是 `name_key`／`desc_key`／`rec_key`（i18n 鍵），**不是**已翻譯文字。`_write_alerts_file` 在寫檔前剝除已渲染的 `name`/`desc`/`rec`；`load()` 時由 `_resolve_rule_keys()` 以 `t(key, lang=lang)` 依當前語言重新渲染。`_LEGACY_FILTER_TO_NAME_KEY`（16 筆）將舊版以 `filter_value` 標示的規則映射回正規 `name_key`，用於遷移舊 `alerts.json`。

---

## 3. 事件管線（Event Pipeline）— `src/events/`

事件處理分八個階段：**poll → normalize → dedup → throttle → classify（已知/未知）→ shadow-compare → stats → runbooks**。套件 docstring 自述「inspired by illumio-pretty-cool-events」。

### 3.1 Poll ＋ Dedup（`poller.py`）

- `EventPoller(api_client, max_results=5000, overlap_seconds=60, subscriber=None)`。
- `fetch_batch(watermark, seen_events)`：以 `watermark - overlap_seconds`（**60 秒重疊**，補抓遲到事件）為查詢起點，呼叫 `api.fetch_events_strict(...)`。
- **去重就發生在此**：`event_identity(event)` 為去重鍵 — 有 `href` 直接用之，否則對 `event_type/timestamp/status/severity/created_by/resource/message` 取 `sha1` 指紋；已在 `seen` 中者跳過。
- **溢位風險**：`overflow_risk = raw_count >= max_results`（≥ 5000 代表視窗可能被截斷）。
- `next_watermark` 取 `max(poll_started_at, watermark, latest_event_ts)`，**單調不回退**。
- 設 `subscriber` 時改走 SQLite cache 路徑（`poll_new_rows`）。

### 3.2 Normalize ＋ 標記分類（`normalizer.py`）

`normalize_event(event)` 把原始 PCE event 攤平成穩定字典，欄位含 `event_id, href, timestamp, event_type, category（首個 . 前綴）, verb（末段）, status, severity, known_event_type, actor, actor_type, source_ip, target_*, resource_*, action_*, workloads_affected, parser_notes` 等。其中 **`known_event_type = is_known_event_type(event_type)`** 即在此戳記。`_build_parser_notes` 會加上診斷標籤（如 `unknown_event_type`、`action_unresolved`、`principal_unresolved` 等）。`_RESOURCE_TYPE_PRIORITY`（20 種 resource type）決定主要 resource。

### 3.3 Throttle（`throttle.py`）

`parse_throttle` 解析 `count/period[unit]`（單位倍率 `s=1, m=60, h=3600, d=86400`，預設 `m`）。`AlertThrottler.allow` 是 `period` 秒內最多 `count` 次的**滑動視窗速率限制**；`prune` 預設保留 24 小時（86400 秒）。（即時引擎在 §2.4 透過此類別執行 throttle 抑制。）

### 3.4 Classify 已知 / 未知（`catalog.py`）

- 檔頭自述：「**Vendor-derived PCE event catalog … based on alexgoller/illumio-pretty-cool-events**」，作為偵測未知/新進 event type 的基線。
- **`KNOWN_EVENT_TYPES`**：285 個 vendor event type ＋ `LOCAL_EXTENSION_EVENT_TYPES` 3 個 ＝ **288 個已知型別**。
- **`KNOWN_RESOURCE_PREFIXES`**（69 個 resource 家族前綴）為第二道防線：PCE 25.x+ 對既有 resource 的新動作可被寬鬆視為已知。
- `is_known_event_type(event_type, lenient=False, *, resource_type=None)`：normalizer 以**非寬鬆**模式呼叫，凡不在 288 集合者一律標 `known_event_type=False` 並打 `unknown_event_type` 標籤。
- `classify_unknown_event_type(...)`：將未知型別歸入 resource 家族或標 `unclassified`。
- 即時引擎 `_update_parser_observability` 把未知型別累積到 `state["unknown_events"]`（上限 100 筆）；啟動時 `load_state` 會把已被新版 catalog 涵蓋的舊未知項清除。

### 3.5 Shadow-compare（`shadow.py`）

**診斷工具，非正式比對邏輯**。`matches_event_rule_legacy` 是原始/簡化語意（僅逗號分隔精確比對，無 regex/否定/管線/巢狀）；`compare_event_rules` 同時跑「現行」與「legacy」matcher，比對命中集合差異並標 `same / mixed / current_more / legacy_more`，供 GUI 的 `shadow_compare`、`rule_test` 端點使用。**正式派送一律走 `matches_event_rule`。**

### 3.6 Stats（`stats.py`）

`StatsTracker`（`timeline_limit=100`、`dispatch_limit=50`）記錄 `dispatch_history`、`event_timeline`、`pce_stats`（含 `health_status`、`event_poll_status`、`consecutive_failures`、`last_batch_total/unknown/notes/overflow` 等）。提供 `record_pce_success/error`、`record_event_batch`、`record_rule_trigger`、`record_suppression`、`record_dispatch`。

### 3.7 Runbooks（`runbooks.py`）

`RUNBOOK_CATEGORIES` 把 event type 對應到操作指引，共 **16 個分類**，每個含 `patterns`（涵蓋的 event types）、`runbook_url`（docs.illumio.com 連結）、`severity_hint`、多行 `response` 處置劇本。`runbook_for(event_type)` 查回對應分類。`severity_hint=critical` 的分類含：`security-auth-failure`、`agent-tampering`、`auth-config`、`server-errors`。

> 另有 `reference.py`：以 `docs/_meta/illumio-event-reference.json` 為後盾的 `EventRef`（category/description/severity/remediation/doc_url），`lru_cache` 快取。

---

## 4. 報表安全規則（Report Security Rules）— B / L / R

程式：`src/report/rules_engine.py`（B/L 系列內建函式）＋ `src/report/rules/r01..r05`（R 系列模組）。`RulesEngine.evaluate(df)` 先跑內建 B/L 規則、再跑 R 系列（`_eval_draft_pd`），最後依嚴重度排序並由 `annotate_techniques` 掛上 MITRE 技法。

### 4.1 共通模型

- `Finding`（`src/report/rules/_base.py`）：`rule_id, rule_name, severity, category, description, recommendation, evidence, technique_ids`。
- **嚴重度排序**：`CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4`。
- **風險 port／門檻來源**：`config/report_config.yaml`（`ransomware_risk_ports`、`lateral_movement_ports`、`thresholds`）。
- `description`／`recommendation` 走 `t(key, lang=...)` 在地化（持久化的是 key 而非文字）。

#### 風險 port 設定（`report_config.yaml`，供 B001–B003、Module 4 使用）

| 等級 | Ports（service）|
|------|------------------|
| critical | 135 RPC、445 SMB、3389 RDP、5985/5986 WinRM |
| high | 5938 TeamViewer、5900 VNC、137/138/139 NetBIOS |
| medium | 22 SSH、2049 NFS、20/21 FTP、5353 mDNS、5355 LLMNR、80 HTTP、3702 WSD、1900 SSDP、23 Telnet |
| low | 110 POP3、1723 PPTP、111 SunRPC、4444 Metasploit |

`lateral_movement_ports`（供 B006、L006）：`3389, 5900, 22, 445, 5985, 5986, 5938, 23`。

### 4.2 B 系列（勒索風險 / 覆蓋率 / 行為異常）— 9 條

| ID | 名稱 | 嚴重度 | 偵測邏輯（命中條件）| 關鍵門檻 | MITRE |
|----|------|--------|----------------------|----------|-------|
| **B001** | Ransomware Risk Port — Contextual Analysis | **依情境**：CRITICAL / HIGH / MEDIUM / INFO | critical 風險 port 且 `policy_decision != blocked` 的 flow，依**網路鄰近度**分級（見下）| 風險 port 集 | T1486、T1021.002 |
| B002 | Ransomware Risk Port (High) | HIGH | high 風險 port 且 `policy_decision == allowed` | — | T1486、T1219 |
| B003 | Ransomware Risk Port (Medium) — Uncovered | MEDIUM | medium 風險 port 且 `policy_decision == potentially_blocked` | — | T1486 |
| B004 | Unmanaged Source High Activity | MEDIUM | `src_managed == False` 的 flow 數 > 門檻 | `unmanaged_connection_threshold=50` | T1046 |
| B005 | Low Policy Coverage | MEDIUM | allowed 佔比 < 門檻% | `min_policy_coverage_pct=30` | （治理，未對應）|
| B006 | High Lateral Movement | HIGH／MEDIUM | lateral port（非 blocked）下，單一 src 觸及的唯一 dst 數 > 門檻；若有 **allowed** 撐起扇出則 HIGH，否則（僅 PB）MEDIUM | `lateral_movement_outbound_dst=10` | T1021 |
| B007 | Single User High Destinations | HIGH | 單一 `user_name` 觸及唯一 dst 數 > 門檻 | `user_destination_threshold=20` | T1078 |
| B008 | High Bandwidth Anomaly | MEDIUM | `bytes_total` 超過第 95 百分位的 flow | `high_bytes_percentile=95` | T1048 |
| B009 | Cross-Env Flow Volume | INFO | 跨 env（`src_env != dst_env`）flow 數 > 門檻 | `cross_env_connection_threshold=100` | （資訊性，未對應）|

**B001 的 cross-subnet 範圍計數（嚴重度核心邏輯）**：先把命中 flow 標記 `_same_subnet`（src/dst IP 前三段相同即同 /24）與 `_cross_env`，再依序判斷：

1. **CRITICAL** — 存在 cross-env flow（如 Dev → Prod 走 SMB/RDP）。
2. **HIGH** — 有 cross-subnet flow 且其中**屬於 cross-subnet 子集的 allowed 數** > 0。
3. **MEDIUM** — cross-subnet flow 全為 `potentially_blocked`（test-mode）。
4. **INFO** — 全部同 /24 且全為 PB。
5. **MEDIUM**（fallback）— 同 /24 但含 allowed（合法管理流量，仍記錄）。

> 關鍵在於：嚴重度由 **cross-subnet 子集內**的 allowed/PB 佔比驅動（`n_cross_subnet_allowed`、`n_cross_subnet_pb`），而非全域 allowed/PB 計數 — 避免把同子網管理流量誤判為高風險。

#### L 系列使用的 port 群組（`rules_engine.py` 常數）

`_DB_PORTS = {1433,3306,5432,1521,27017,6379,9200,5984,50000}`；`_IDENTITY_PORTS = {88,389,636,3268,3269,464}`；`_CLEARTEXT_PORTS = {23,20,21}`；`_DISCOVERY_PORTS = {137,138,5353,5355,1900,3702}`；`_WINDOWS_MGMT_PORTS = {135,445,5985,5986,47001}`。

### 4.3 L 系列（橫向移動 / 外洩）— 10 條

| ID | 名稱 | 嚴重度 | 偵測邏輯 | 門檻 | MITRE |
|----|------|--------|----------|------|-------|
| L001 | Cleartext Protocol in Use | HIGH／MEDIUM | Telnet/FTP（23/20/21）有 flow；含 allowed 則 HIGH，否則 MEDIUM | — | T1040 |
| L002 | Network Discovery Protocol Exposure | MEDIUM | NetBIOS/mDNS/LLMNR/SSDP/WSD 非 blocked flow 數 ≥ 門檻 | `discovery_protocol_threshold=10` | T1557.001 |
| L003 | Database Port Wide Exposure | HIGH | DB port 的 allowed flow，單一 (dst_ip,port) 的唯一 `src_app` 數 > 門檻 | `db_unique_src_app_threshold=5` | T1210 |
| L004 | Cross-Environment Database Access | HIGH | DB port 且跨 env 且 allowed | — | T1210 |
| L005 | Identity Infrastructure Wide Exposure | HIGH／MEDIUM | Kerberos/LDAP/GC 非 blocked，唯一 `src_app` 數 > 門檻；allowed 撐起則 HIGH | `identity_unique_src_threshold=3` | T1558 |
| L006 | High Blast-Radius Lateral Movement Path | HIGH | 在 lateral port（allowed）上建 app→app 有向圖，**BFS** 算每節點可達數 ≥ 門檻 | `blast_radius_threshold=5` | T1021 |
| L007 | Unmanaged Host Accessing Critical Services | HIGH | `src_managed==False` 對 DB/Identity/WinMgmt port（非 blocked）flow 數 ≥ 門檻 | `unmanaged_critical_threshold=5` | T1210 |
| L008 | Lateral Ports in Test Mode (PB) | HIGH | lateral/WinMgmt/DB/Identity port 上 `potentially_blocked` flow 數 ≥ 門檻（強制執行落差）| `pb_lateral_threshold=10` | （治理，未對應）|
| L009 | Data Exfiltration Pattern (Outbound to Unmanaged) | HIGH | managed src → unmanaged dst、allowed、`bytes_total>0`，總量 ≥ 門檻 MB | `exfil_bytes_threshold_mb=100` | T1048 |
| L010 | Cross-Environment Lateral Port Access | **CRITICAL** | lateral/WinMgmt port 且跨 env 且 allowed，flow 數 ≥ 門檻 | `cross_env_lateral_threshold=5` | T1021、T1570 |

> L006 方法論借鏡 Illumio MCP 的 `detect-lateral-movement-paths`（BFS 可達性）；L001–L010 整體對應 MITRE 在 `src/report/analysis/mitre_map.py`。治理型規則（B005、B009、L008、R01–R05）刻意**不對應** MITRE，以免誤導 SOC。

### 4.4 R 系列（Draft Policy 對齊）— 5 條

R 系列只在 unified DataFrame 帶有 **`draft_policy_decision`** 欄時才會評估（`_DraftPdRuleMixin._has_draft`）；缺欄即整批 no-op。皆屬 `DraftPolicy` 類別。

| ID | 名稱 | 嚴重度 | 命中條件（draft_policy_decision）|
|----|------|--------|----------------------------------|
| R01 | Draft Deny Detected | HIGH | `policy_decision==allowed` 但 draft ∈ {`blocked_by_boundary`,`blocked_by_override_deny`}（現允許、草案會擋）|
| R02 | Override Deny Detected | HIGH | draft 以 `_override_deny` 結尾（override deny 規則，任何 allow 都無法蓋過）|
| R03 | Visibility Boundary Breach | MEDIUM | `policy_decision==potentially_blocked` 且 draft==`potentially_blocked_by_boundary`（VEN 在 visibility/test 模式且有 deny boundary 草案）|
| R04 | Allowed Across Boundary | LOW | draft==`allowed_across_boundary`（allow 規則覆蓋了一般 deny boundary，需確認是否刻意）|
| R05 | Draft Reported Mismatch | INFO | `policy_decision==allowed` 但 draft 以 `blocked_` 開頭（彙整 reported=allowed 但草案建議 block 的 workload 對）|

#### R 系列的啟用狀態（請據實理解）

- **引擎已接好**：`RulesEngine.evaluate` 會在 DataFrame 帶 `draft_policy_decision` 欄時跑 R01–R05；該欄由查詢時的 `compute_draft`（PCE `update_rules`）產生。
- **資料證實可得**：2026-06-26 對 LIVE PCE 實測，當 traffic query 以 `compute_draft` 執行（`update_rules`），PCE **確實對每個 flow 回傳 `draft_policy_decision`**。
- **但正式全量啟用受「按需閘門」限制**：`ruleset_needs_draft_pd(DRAFT_PD_RULES)` 因 R01–R05 全部 `needs_draft_pd()=True`，**實質恆為 True**。`report_generator.py` 雖會據此把 `requires_draft_pd=True` 塞進 filters，但**標準報表抓取路徑** `fetch_traffic_for_report → execute_traffic_query_stream` **並未傳入 `compute_draft`（預設 False）**，且 **cache 路徑（`read_flows_df`）本來就沒有 draft 欄**。因此一般報表與 cache 命中報表的 DataFrame 都**不含** `draft_policy_decision`，R 系列即 no-op。
- 若把 `compute_draft` 接進每次報表抓取，會讓每份報表都付出 PCE `update_rules`（實測約 12 秒）的成本。
- **結論（誠實標註）**：R 系列為「**引擎就緒 ＋ 資料已證實可得，但採按需（on-demand）啟用**」— 屬於專門的 draft-policy 分析 / draft-report 模式，**並非每份報表都會執行**。

---

## 5. 報表分析模組（Report Analysis Modules）

註冊表：`src/report/analysis/__init__.py` 的 `TRAFFIC_MODULES`，由 `_run_modules` 動態載入。Module 12（executive_summary）最後執行，彙整其他模組結果。**mod05（Remote Access）已併入 mod15。**

### 5.1 流量分析模組（mod01–mod15）

| 模組 | 標題 | 分析內容（關鍵輸出）|
|------|------|----------------------|
| mod01 | Traffic Overview | KPI 總覽：`total_flows`、`total_connections`、唯一 src/dst IP、`total_bytes`、`policy_coverage_pct`（allowed%）、allowed/blocked/PB/unknown 計數、`src_managed_pct`/`dst_managed_pct`、Top ports/protocols |
| mod02 | Policy Decision Breakdown | 依 `policy_decision` 拆解；每類的 top app→app flows、top ports、inbound/outbound 拆分、port 覆蓋率 |
| mod03 | Uncovered Flows（覆蓋落差）| **三層覆蓋率**：Enforced（allowed/total）、Staged（PB/total，規則存在但 workload 在 test/visibility）、True Gap（(blocked+unknown)/total）。未覆蓋 flow 分類為 `unmanaged_source`／`intra_app`／`cross_app`，並出 per-port、per-service 缺口排名與 in/outbound 覆蓋率 |
| mod04 | Ransomware Exposure | 以 `report_config` 風險 port（4 等級）標記 flow，輸出 A) 各等級摘要 B) per-port 明細（allowed/blocked/PB）C) 依 PD 分布 D) host 暴露排名（暴露最多風險 port 的 dst）E) 調查目標（critical/high port 上有 allowed 的 host）。`risk_flows_total` 餵入 mod12 成熟度 |
| mod05 | （已併入 mod15）| — |
| mod06 | User & Process Activity | 有 `user_name`/`process_name` 的 flow：top users、user→app 矩陣、top processes |
| mod07 | Cross-Label Flow Matrix | 以 `env/app/role/loc` 四種 label key 建 src×dst 流量矩陣 |
| mod08 | Unmanaged Host Analysis | 涉及 unmanaged host 的流量：per dst_app、per (port,proto)、src-port 明細 |
| mod09 | Traffic Distribution | 各 label（env/app/role/loc）的流量分布與 top talkers |
| mod10 | Allowed Traffic | `policy_decision==allowed` 的 top app→app、ports、services |
| mod11 | Bandwidth & Volume | 量/頻寬分析：top by bytes、top by Mbps、以 per-connection bytes 第 95 百分位為異常門檻 |
| mod12 | Executive Summary | 彙整摘要 ＋ **Microsegmentation Maturity Score**（見 5.2）、三層覆蓋 KPI、Action Matrix、Key Findings |
| mod13 | Enforcement Readiness | 逐 app(env) **就緒分數**（見 5.3），含 attack-posture items 與優先建議 |
| mod14 | Infrastructure Scoring | 以 **betweenness centrality** 對 app(env) 圖評分；用 `_DB_PORTS`、`_IDENTITY_PORTS` 偵測關鍵資產；分層（tier）並產 posture items |
| mod15 | Lateral Movement Risk | 見 5.4 |

### 5.2 mod12 Microsegmentation Maturity Score（成熟度，0–100）

`_compute_maturity_score` 五維加權（總和 100）：

| 維度 | 權重 | 比率算法 |
|------|------|----------|
| enforcement_coverage | 40 | `min(100, enforced% + 0.5×staged%)/100` |
| policy_coverage | 25 | `enforced%/100`（allowed/total）|
| lateral_movement_control | 15 | `1 - min(lateral_pct,30)/30`（lateral_pct 來自 mod15）|
| managed_asset_ratio | 10 | `1 - min(unmanaged%,50)/50` |
| risk_port_control | 10 | `1 - min(risk_ratio×5, 1)`（risk_ratio = mod04 risk_flows/total；20% 即 0 分）|

輸出 `maturity_score`、`maturity_grade` 及各維 `maturity_dimensions`。

### 5.3 mod13 Enforcement Readiness（逐 app(env) 就緒分數，0–100）

`_WEIGHTS`：policy_coverage **35**、ringfence_maturity **20**、enforcement_mode **20**、staged_readiness **15**、remote_app_coverage **10**。

- policy_coverage：allowed 比率；ringfence_maturity：`src_key==dst_key`（同 app 內部）比率；enforcement_mode：managed flag 比率（無則用全域 workload enforcement 比率）；staged_readiness：＝allowed 比率（PB **不**計分）；remote_app_coverage：remote port `{22,3389,5900,5901,5938,3283}` 的 allowed 比率（無 remote flow 視為 1.0）。
- 等級：A≥90、B≥75、C≥60、D≥45、F。
- 依比率產生 attack-posture items：`enforcement_gap`（allowed<0.75）、`boundary_breach`（ringfence<0.5 或 remote_coverage<0.85）、`suspicious_pivot`（blocked>0.2）。嚴重度 `_severity_from_ratio`：≥0.75 CRITICAL、≥0.45 HIGH、否則 MEDIUM。

### 5.4 mod15 Lateral Movement Risk（圖論橫向移動）

- Lateral port 表（16 種）：445 SMB、135 RPC、139 NetBIOS、3389 RDP、22 SSH、5985/5986 WinRM、23 Telnet、2049 NFS、111 RPC Portmapper、389 LDAP、636 LDAPS、88 Kerberos、1433 MSSQL、3306 MySQL、5432 PostgreSQL。
- `lateral_pct = lateral flows / 全部 flows × 100`（餵回 mod12 維度 3）。
- 以可穿越（allowed＋PB）lateral flow 建 app|env 圖，計算：**Tarjan 關節點（articulation/bridge node）**、每節點 **BFS 可達性**（`max_depth=4`）。
- `reach_score = reach_count/max_reach×100`；`bridge_score = (關節點 60 else 0) + reach_score×0.4`；Risk Level：≥85 Critical、≥60 High、≥35 Medium。
- attack-posture items：`suspicious_pivot`（關節點且 reach≥2，reach≥6 為 CRITICAL 否則 HIGH）、`blast_radius`（reach≥4，HIGH）、`blind_spot`（unmanaged 可穿越，≥3 HIGH 否則 MEDIUM）。
- 輸出 service_summary、fan-out sources、attack_paths、bridge_nodes、top_reachable_nodes、source_risk_scores 與網路圖 chart_spec。

### 5.5 Posture 子分數（`src/report/posture.py`）

`compute_posture(kpis)` 由報表快照（mod12 輸出）算 dashboard posture 分數，**純函式**：

```
score = round(coverage×0.3 + readiness×0.3 + risk_health×0.4)   （缺項則重新正規化權重）
```

- **coverage**：`enforced_coverage_pct`（policy enforcement %）。
- **readiness**：`maturity_score`（微分段成熟度）。
- **risk_health** ＝ `100 - penalty`，`penalty = min(100, ransomware_pts + lateral_pts + uncovered_pts)`：
  - `ransomware_pts = min(40, ransomware_apps×5)`（每個暴露 app 5 分、上限 40）
  - `lateral_pts = round((1 - lateral_control_ratio)×30)`（完全失控 30 分）
  - `uncovered_pts = min(30, uncovered_pct×0.5)`（60% gap = 30 分）
- 三個 risk 子分數：`ransomware_containment`＝`100×(1-ransomware_pts/40)`、`lateral_containment`＝`100×(1-lateral_pts/30)`、`flow_coverage`＝`100×(1-uncovered_pts/30)`。

### 5.6 Attack-posture 資料層（`attack_posture.py`）

mod13/mod14/mod15 共用的去確定性 posture 層：`make_posture_item`（scope/framework/app_env_key/finding_kind/attack_stage/confidence/recommended_action_code/severity/evidence）、`rank_posture_items`（依 severity → confidence → attack_stage → finding_kind 排序）、`resolve_recommendation`（12 個 action code 對應 `rpt_action_*` i18n key）、`summarize_attack_posture`（彙整 boundary_breaches/suspicious_pivot/blast_radius/blind_spots ＋ action_matrix）。

### 5.7 Draft 與其他輔助模組

- **`mod_draft_summary`**：在有 `draft_policy_decision` 欄時，統計 **7 個子型別**（allowed、potentially_blocked、blocked_by_boundary、blocked_by_override_deny、potentially_blocked_by_boundary、potentially_blocked_by_override_deny、allowed_across_boundary）計數與各型別 top workload pairs；無欄則 skip。
- **`mod_draft_actions`**：可行動分析 — `override_deny`、`potentially_blocked_by_override_deny`、`allowed_across_boundary` 的 top pairs 與修補/審查工作流，加 `what_if_summary`（reported 與 draft 不同的 `would_change_share`）。
- **`ransomware_posture`**：PCE-native（非 flow-based）勒索 posture — 由 workload 的 `risk_summary.ransomware`（exposure severity、protection %）與 `open_service_ports` 交叉，輸出 KPI（各 exposure 等級數、avg protection %）、per-VEN 與高風險開放 port 清單。
- **`mod_ringfence`**：per-app 相依輪廓 ＋ candidate allow rules ＋ boundary deny 候選。
- **`mod_drift`**：基線漂移 — 與上次執行相比，新增/消失的 app→app 連線對（純簽章比對）。雜訊簽名（ICMP、port 0、ephemeral 高 port ≥49152）與 `(unlabeled)→(unlabeled)` 配對會從兩表與其計數中排除（後者改收合為單一統計行）。當前次基線帶有中繼資料（window/data_source/profile）且本次視窗與其差異過大時，直接拒絕比較（仍會存入新基線），避免整批基線換血被誤報為大量消失；在此中繼資料出現前存下的舊基線則完全照舊比較（不拒絕、不警語）。
- **`mod_change_impact`**：與上次快照比較 KPI；`LOWER_BETTER=(pb_uncovered_exposure, high_risk_lateral_paths, blocked_flows)`、`HIGHER_BETTER=(active_allow_coverage, microsegmentation_maturity)`。
- **趨勢差異（`trend_store`）**：traffic/audit/policy_usage/VEN 四種報表各自保存每次執行的 KPI 快照，並與前次快照算出差異渲染（`load_previous` 讀磁碟上最新一份——因為存檔緊接在讀取之後，差異從下一次執行起就看得到，不必等到再下一次）。快照同樣帶 window/data_source/profile 中繼資料；與前次快照不一致時，Trend 區塊會顯示列出差異欄位的警語，而非靜默比較不同基準的期間。此中繼資料出現前存下的舊快照則完全照舊比較（無警語）。

---

## 6. 資料來源（Cache vs Live、Draft-PD 取得方式）

兩套引擎都跑在「unified DataFrame / flow 串流」上，來源可為 **LIVE PCE** 或 **SQLite `pce_cache`**：

- **報表抓取**（`ReportGenerator._fetch_traffic_df`）採 cache-aware 混合策略：
  - cache **完整覆蓋** → 全讀 cache（`read_flows_df`，向量化）。
  - **部分覆蓋** → API 補前段缺口、cache 補其餘（source 標 `mixed` 或 `cache`）。
  - 未覆蓋或 `use_cache=False` → 純 LIVE API。
- **即時監控抓取**（`Analyzer._fetch_query_flows`）採相同混合邏輯（`cover_state` 判斷 full/partial/miss）。
- **policy_decision 來源**：PCE flow 的 `policy_decision`（allowed / potentially_blocked / blocked）。`potentially_blocked` 代表「規則會擋、但 workload 仍在 visibility/test 模式」。
- **draft_policy_decision 取得**：唯有 traffic query 帶 `compute_draft=True` 時，API 才呼叫 PCE 的 `…/update_rules`（PUT）計算 draft 結果，並於 CSV 下載時 `include_draft_policy=True` 帶回；**cache 不含此欄**。此即 §4.4 R 系列按需啟用的根本原因（實測 `update_rules` 約 12 秒成本）。

---

## 7. 如何新增 / 調整規則

### 7.1 即時監控告警規則

- **GUI / CLI**：透過 `ConfigManager.add_or_update_rule()` 新增或覆寫（同 `type` 且 event 的 `filter_value`／traffic 的 `name` 相同視為同規則）。規則寫入 `config/alerts.json`。
- **套用最佳實務**：`apply_best_practices(mode="append_missing" | "replace")`。`append_missing` 以 `_rule_signature` 去重後補入缺漏；`replace` 全量替換（並自動備份至 `rule_backups`，上限 10）。
- **可調欄位**：`threshold_type`（immediate/count）、`threshold_count`、`threshold_window`（分鐘）、`cooldown_minutes`、`throttle`（`count/period[unit]`）、`pd`、`port`/`proto`、各種 label/ip 包含與排除過濾。

### 7.2 報表規則門檻與風險 port

直接編輯 `config/report_config.yaml`：

- `ransomware_risk_ports`（B001–B003、mod04 的等級與 port）。
- `lateral_movement_ports`（B006、L006）。
- `thresholds`（每條 B/L 規則的數值門檻，§4.2/§4.3 表列）。

> 嚴重度分支（如 B001 的 cross-subnet 範圍計數）寫在規則函式內，非設定值；要改判斷邏輯需改 `rules_engine.py`／`src/report/rules/`。新增報表規則：在 `rules_engine.py` 加 `_bNNN`／`_lNNN` 方法（或在 `src/report/rules/` 新增模組類別並登錄），並於 `mitre_map.py` 對應 MITRE。

### 7.3 排程器（Schedulers）

倉庫有三個獨立排程器，勿混淆：

- **監控迴圈**（`src/scheduler/`）：依 `config.json` 的 `rule_scheduler.check_interval_seconds`（預設 **300 秒**）週期觸發 `Analyzer.run_analysis()`，即時評估 §2 的告警規則。
- **ReportScheduler**（`src/report_scheduler.py`）：依排程產生報表。
- **Illumio Rule Scheduler / `ScheduleEngine`**（`src/rule_scheduler.py`，設定 `config/rule_schedules.json`）：這是**獨立功能** — 依時間窗（recurring/one_time）切換 PCE 上的 Ruleset/sec_rule/deny_rule 啟用狀態，與告警規則無關。

### 7.4 i18n 鍵（desc_key / rec_key）

- 監控規則持久化 `name_key`/`desc_key`/`rec_key`，由 `_resolve_rule_keys()` 在讀取時以 `t(key, lang)` 渲染；新增規則應提供 i18n key 而非寫死文字，文字定義於 `src/i18n_en.json`／`src/i18n_zh_TW.json`。
- 報表 `Finding` 與分析模組同樣以 `t(key, lang=...)` 在讀取（render）時在地化；持久化/快照存的是 key，切換語言即時重譯。

---

### 附註：誠實標示的程式落差

- **「24 條規則」**：與原始碼一致（B 9 ＋ L 10 ＋ R 5）。`rules_engine.py` 檔頭僅列「B001–B009, L001–L010」，R 系列分置 `src/report/rules/`。
- **R 系列（R01–R05）**：引擎已接好、LIVE 實測證實 PCE 可回傳 `draft_policy_decision`，但標準/cache 報表路徑不含該欄（`fetch_traffic_for_report` 未傳 `compute_draft`），故為**按需啟用**，非每份報表都跑（見 §4.4、§6）。
- **mod04 風險 port 數**：模組 docstring 寫「20 high-risk ports」，但 `report_config.yaml` 實際列出 24 個 distinct port（critical 5 ＋ high 5 ＋ medium 10 ＋ low 4）。本文以設定檔實際內容為準。
