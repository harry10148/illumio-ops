---
title: 監控規則、告警與事件規則
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/analyzer.py
  - src/report/rules_engine.py
  - src/report/rules/
  - src/report/analysis/mitre_map.py
  - src/events/poller.py
  - src/events/normalizer.py
  - src/events/throttle.py
  - src/events/catalog.py
  - src/events/matcher.py
  - src/events/shadow.py
  - src/events/runbooks.py
  - src/reporter.py
  - src/alerts/plugins.py
  - src/alerts/metadata.py
  - src/config.py
  - src/gui/routes/actions.py
  - config/report_config.yaml
---

# 監控規則、告警與事件規則

illumio-ops 內部有**兩套獨立的規則判斷引擎**，加上一條**事件處理管線**，彼此輸出各異：

| 系統 | 程式位置 | 觸發時機 | 判斷對象 | 輸出 |
|------|----------|----------|----------|------|
| 即時監控規則引擎 | `src/analyzer.py` | 每個監控週期（`rule_scheduler.check_interval_seconds`，預設 300 秒，觸發 `Analyzer.run_analysis()`）| PCE audit events ＋ 即時 traffic flows | 派送告警（event／traffic／metric／health）到各通道 |
| 報表安全規則引擎 | `src/report/rules_engine.py` ＋ `src/report/rules/` | 產生報表時（`ReportGenerator._run_pipeline`）| 彙整後的 unified flow DataFrame | 一組 `Finding`（規則命中清單），供 Module 12 摘要與 HTML/Excel 匯出 |
| 事件管線 | `src/events/` | 即時監控引擎的事件階段呼叫 | 原始 PCE events | 正規化、去重、節流、分類（已知/未知）、影子比對、統計、runbook 對應 |

即時監控規則引擎是「條件比對 + 門檻 + 冷卻」型：每條規則是存於 `config/alerts.json` 的一份設定字典，命中且超過門檻就派送告警。報表安全規則引擎則是「程式化偵測邏輯」型：每條規則（B/L/R 系列，共 **24 條**）是一段寫死的 Python 偵測函式，依網路情境判定嚴重度，並附上 MITRE ATT&CK 對映。

設定檔結構與各鍵語意見 [configuration.md](configuration.md)；GUI 的 Alerts／Settings → Channels 頁面操作步驟見 [gui-tour.md](gui-tour.md)；報表產出與模組總覽見 [reports.md](reports.md)。

---

## 1. 即時監控規則（Real-time Monitor Rules）

程式核心是 `src/analyzer.py` 的 `Analyzer` 類別。一個監控週期 `run_analysis()` 依序執行：

1. `_run_health_check()` — system／`pce_health` 規則：先查 `/api/v2/health`（狀態碼＋body degraded 判讀），通過後再探官方 SLB 端點 `/api/v2/node_available`（免驗證；200/202 = 健康，404/502/無回應 = 節點不可服務，官方註明狀態反映最多延遲 30 秒）。
2. `_run_event_analysis()` — event 規則。
3. `_fetch_traffic()` ＋ `_run_rule_engine()` — traffic／bandwidth／volume 規則。
4. `_dispatch_alerts()` — 派送 traffic 類告警。
5. `_check_watchdog()` ＋ `_maybe_alert_overflow()` — 可靠性自我檢查（見第 4 節）。
6. `save_state()` — 持久化水位（watermark）、歷史、冷卻狀態。

規則統一存於 `config/alerts.json` 的 `rules` 陣列，每條都有 `type` 欄位區分五種型別。

### 1.1 五種規則型別

| `type` | 觸發指標來源 | 門檻運算子 | 跨 flow 累加方式 | 派送方法 |
|--------|--------------|------------|--------------------|----------|
| `event` | 命中事件數 | `count_val >= threshold_count`（且 `> 0`）| `immediate`：本批命中數；`count`：滑動視窗 `threshold_window` 分鐘內的歷史命中數 | `reporter.add_event_alert` |
| `traffic` | 連線數 `num_connections` | `val >= threshold_count` | 加總（sum）| `reporter.add_traffic_alert` |
| `volume` | 資料量 MB（`calculate_volume_mb`）| `val >= threshold_count` | 加總（sum）| `reporter.add_metric_alert` |
| `bandwidth` | 頻寬 Mbps（`calculate_mbps`）| `bw_val > threshold_count`（**嚴格大於**）| 取最大值（max）；任一 flow 超標即觸發 | `reporter.add_metric_alert` |
| `system` | PCE health 狀態碼 | health status **≠ 200**、`/health` body 回報 degraded、或 `/node_available` 非 200/202 即觸發 | — | `reporter.add_health_alert` |

> 運算子差異：**bandwidth 用 `>`，traffic/volume 用 `>=`**。`calculate_mbps`／`calculate_volume_mb` 以 delta（Interval）為優先、total（Avg）為次。

### 1.2 Flow 比對：`check_flow_match`

每條 traffic/bandwidth/volume 規則對每個 flow 依序檢查：

1. **滑動視窗**：flow 時間早於 `now - threshold_window` 則排除。
2. **policy_decision（`pd`）**：flow 的 `pd` 數值化為內部代碼 `0=allowed`、`1=potentially_blocked`、`2=blocked`（無 `pd` 欄時由 `policy_decision` 字串推斷）。規則 `pd` 未設時預設為 `-1`（event 類）或 `3`（traffic 類）；`-1` 與 `3` 皆為工具內部的「任意 PD」sentinel，其餘需精確相等才命中。
   > 這個 `3` sentinel 是本工具內部代碼，與 PCE 原始 traffic 資料的 `policy_decision` 值域**不同**——PCE 側的實際值域是四值（含 `unknown`），詳見 [pce-domain-notes.md](../handover/pce-domain-notes.md) 的 policy_decision 一節；預設查詢若漏掉 `unknown`，統計數字會大幅偏低。
3. **Port／Proto**：`rule.port`、`rule.proto` 需與 flow 的 `dst_port`／`service.port`、`proto`／`service.proto` 相等。
4. **Label／IP 包含過濾**：`src_label`、`dst_label`（支援 `key=value` 與 `key:value`）、`src_ip_in`、`dst_ip_in`。
5. **任一側（any-side）包含**：`any_label`、`any_ip`。
6. **排除過濾**：`ex_port`、`ex_src_label`、`ex_dst_label`、`ex_src_ip`、`ex_dst_ip`，以及任一側排除 `ex_any_label`、`ex_any_ip`。

### 1.3 Event 比對：`matches_event_rule`

event 規則用 `filter_value` 比對 event type（`src/events/matcher.py`）：

- **多型態樣**：逗號分隔多個 pattern，命中任一即算。
- **萬用字元**：`*`／`any`／`all`／空字串 → 永遠符合。
- **管線替代**：`a|b|c`（非 regex 樣式）→ 屬於集合即符合。
- **正規式**：含 `^ $ * + ? [ ] ( ) { } \` 或 `.* .+ .?` 者，以 `^pattern$` 錨定比對。
- **否定**：前綴 `!` → 反向。
- 另比對 `filter_status`（如 `failure`）與 `filter_severity`，以及 `match_fields`（巢狀欄位 dot-path）。

### 1.4 冷卻與節流：`_check_cooldown`

命中門檻後需通過兩道閘：

1. **Cooldown**：`cooldown_minutes`（未設時預設＝`threshold_window`，再預設 10 分鐘）。距上次同規則告警未滿冷卻時間 → 抑制（`cooldown` suppression）。
2. **Throttle**（`AlertThrottler.allow`，`src/events/throttle.py`）：規則 `throttle` 欄為 `"count/period[unit]"`（unit：`s`/`m`/`h`/`d`，省略預設 `m`）。滑動視窗 `period` 內已派送達 `count` 次 → 抑制（`throttle` suppression）。

### 1.5 預設出廠規則（Best-Practice Rule Set）

由 `src/config.py` 的 `_best_practice_rules()` 產生（`apply_best_practices` 套用），寫入 `config/alerts.json`。共 **16 條 event ＋ 1 條 traffic**：

| name_key | filter_value（event type）| 門檻型 | count | window(分) | cooldown(分) | throttle | 說明 |
|----------|---------------------------|--------|-------|-----------|--------------|----------|------|
| `rule_agent_tampering` | `agent.tampering` | immediate | 1 | 10 | 30 | — | VEN agent 遭竄改 |
| `rule_agent_suspend` | `agent.suspend` | immediate | 1 | 10 | 30 | — | agent 被暫停（停止強制執行）|
| `rule_agent_clone` | `agent.clone_detected` | immediate | 1 | 10 | 30 | — | 偵測 cloned agent |
| `rule_agent_heartbeat` | `system_task.agent_missed_heartbeats_check` | count | 3 | 30 | 60 | `1/30m` | 心跳遺失 |
| `rule_agent_offline` | `system_task.agent_offline_check` | count | 3 | 30 | 60 | `1/30m` | agent 離線 |
| `rule_lost_agent` | `lost_agent.found` | immediate | 1 | 10 | 60 | — | lost-agent 復原 |
| `rule_login_failed` | `user.sign_in,user.login` | count | 5 | 10 | 30 | `1/15m` | `filter_status=failure`；登入失敗 |
| `rule_api_auth_failed` | `request.authentication_failed` | count | 5 | 10 | 30 | `1/15m` | API 認證失敗 |
| `rule_policy_fail` | `agent.refresh_policy` | immediate | 1 | 10 | 30 | — | `filter_status=failure`；Policy 刷新失敗 |
| `rule_ruleset_change` | `rule_set.create,rule_set.update,rule_set.delete` | immediate | 1 | 10 | 60 | — | Ruleset 變更 |
| `rule_policy_provision` | `sec_policy.create` | immediate | 1 | 10 | 60 | — | Security Policy 佈署 |
| `rule_api_authz_failed` | `request.authorization_failed` | count | 3 | 10 | 30 | `1/15m` | API 授權失敗 |
| `rule_api_key_change` | `api_key.create,api_key.delete` | immediate | 1 | 10 | 60 | — | API key 新增/刪除 |
| `rule_sec_rule_change` | `sec_rule.create,sec_rule.update,sec_rule.delete` | immediate | 1 | 10 | 60 | — | Security Rule 變更 |
| `rule_bulk_unpair` | `workloads.unpair,agents.unpair` | immediate | 1 | 10 | 60 | — | 批次 unpair（大規模解除強制）|
| `rule_auth_settings_change` | `authentication_settings.update` | immediate | 1 | 10 | 60 | — | 認證設定變更 |
| `rule_high_blocked`（traffic，`pd=2`）| — | count | 25 | 10 | 30 | `1/15m` | 高 Blocked 流量 |

> **ID 編號**：`apply_best_practices` 從呼叫當下規則陣列的最大 `id + 1` 開始連續編號，不是固定值——全新安裝（空規則陣列）套用後即為 1–17；已有其他自訂規則時則接續在其後。
>
> **i18n 鍵存放**：每條規則持久化的是 `name_key`／`desc_key`／`rec_key`（i18n 鍵），**不是**已翻譯文字。讀取時由 `_resolve_rule_keys()` 以 `t(key, lang=lang)` 依當前語言重新渲染；`_write_alerts_file` 寫檔前剝除已渲染文字。

---

## 2. 報表安全規則（B / L / R 系列）

程式：`src/report/rules_engine.py`（B/L 系列內建函式）＋ `src/report/rules/r01`–`r05`（R 系列模組）。`RulesEngine.evaluate(df)` 先跑內建 B/L 規則、再跑 R 系列，最後依嚴重度排序並掛上 MITRE ATT&CK 技法。共 **24 條**（B 9 ＋ L 10 ＋ R 5，逐檔清點確認）。

- `Finding`（`src/report/rules/_base.py`）：`rule_id, rule_name, severity, category, description, recommendation, evidence, technique_ids`。
- 嚴重度排序：`CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4`。
- 風險 port／門檻來源：`config/report_config.yaml`（`ransomware_risk_ports`、`lateral_movement_ports`、`thresholds`）。
- `description`／`recommendation` 走 `t(key, lang=...)` 在地化，持久化的是 key 而非文字。

### 2.1 風險 port 設定（供 B001–B003、mod04 使用）

| 等級 | Ports（service）|
|------|------------------|
| critical | 135 RPC、445 SMB、3389 RDP、5985/5986 WinRM |
| high | 5938 TeamViewer、5900 VNC、137/138/139 NetBIOS |
| medium | 22 SSH、2049 NFS、20/21 FTP、5353 mDNS、5355 LLMNR、80 HTTP、3702 WSD、1900 SSDP、23 Telnet |
| low | 110 POP3、1723 PPTP、111 SunRPC、4444 Metasploit |

`lateral_movement_ports`（供 B006、L006）：`3389, 5900, 22, 445, 5985, 5986, 5938, 23`。

### 2.2 B 系列（勒索風險／覆蓋率／行為異常）— 9 條

| ID | 名稱 | 嚴重度 | 偵測邏輯（命中條件）| 關鍵門檻 | MITRE |
|----|------|--------|----------------------|----------|-------|
| B001 | Ransomware Risk Port — Contextual Analysis | 依情境：CRITICAL／HIGH／MEDIUM／INFO | critical 風險 port 且 `policy_decision != blocked` 的 flow，依網路鄰近度分級（見下）| 風險 port 集 | T1486、T1021.002 |
| B002 | Ransomware Risk Port (High) | HIGH | high 風險 port 且 `policy_decision == allowed` | — | T1486、T1219 |
| B003 | Ransomware Risk Port (Medium) — Uncovered | MEDIUM | medium 風險 port 且 `policy_decision == potentially_blocked` | — | T1486 |
| B004 | Unmanaged Source High Activity | MEDIUM | `src_managed == False` 的 flow 數 > 門檻 | `unmanaged_connection_threshold=50` | T1046 |
| B005 | Low Policy Coverage | MEDIUM | allowed 佔比 < 門檻% | `min_policy_coverage_pct=30` | （治理，未對應）|
| B006 | High Lateral Movement | HIGH／MEDIUM | lateral port（非 blocked）下，單一 src 觸及的唯一 dst 數 > 門檻；若有 allowed 撐起扇出則 HIGH，否則（僅 PB）MEDIUM | `lateral_movement_outbound_dst=10` | T1021 |
| B007 | Single User High Destinations | HIGH | 單一 `user_name` 觸及唯一 dst 數 > 門檻 | `user_destination_threshold=20` | T1078 |
| B008 | High Bandwidth Anomaly | MEDIUM | `bytes_total` 超過第 95 百分位的 flow | `high_bytes_percentile=95` | T1048 |
| B009 | Cross-Env Flow Volume | INFO | 跨 env（`src_env != dst_env`）flow 數 > 門檻 | `cross_env_connection_threshold=100` | （資訊性，未對應）|

**B001 的 cross-subnet 範圍計數（嚴重度核心邏輯）**：先把命中 flow 標記 `_same_subnet`（src/dst IP 前三段相同即同 /24）與 `_cross_env`，再依序判斷：

1. **CRITICAL** — 存在 cross-env flow（如 Dev → Prod 走 SMB/RDP）。
2. **HIGH** — 有 cross-subnet flow，且其中屬於 cross-subnet 子集的 allowed 數 > 0。
3. **MEDIUM** — cross-subnet flow 全為 `potentially_blocked`（test-mode）。
4. **INFO** — 全部同 /24 且全為 PB。
5. **MEDIUM**（fallback）— 同 /24 但含 allowed（合法管理流量，仍記錄）。

嚴重度由**cross-subnet 子集內**的 allowed/PB 佔比驅動，而非全域計數——避免把同子網管理流量誤判為高風險。

### 2.3 L 系列（橫向移動／外洩）— 10 條

port 群組常數：`_DB_PORTS = {1433,3306,5432,1521,27017,6379,9200,5984,50000}`；`_IDENTITY_PORTS = {88,389,636,3268,3269,464}`；`_CLEARTEXT_PORTS = {23,20,21}`；`_DISCOVERY_PORTS = {137,138,5353,5355,1900,3702}`；`_WINDOWS_MGMT_PORTS = {135,445,5985,5986,47001}`。

| ID | 名稱 | 嚴重度 | 偵測邏輯 | 門檻 | MITRE |
|----|------|--------|----------|------|-------|
| L001 | Cleartext Protocol in Use | HIGH／MEDIUM | Telnet/FTP（23/20/21）有 flow；含 allowed 則 HIGH，否則 MEDIUM | — | T1040 |
| L002 | Network Discovery Protocol Exposure | MEDIUM | NetBIOS/mDNS/LLMNR/SSDP/WSD 非 blocked flow 數 ≥ 門檻 | `discovery_protocol_threshold=10` | T1557.001 |
| L003 | Database Port Wide Exposure | HIGH | DB port 的 allowed flow，單一 (dst_ip,port) 的唯一 `src_app` 數 > 門檻 | `db_unique_src_app_threshold=5` | T1210 |
| L004 | Cross-Environment Database Access | HIGH | DB port 且跨 env 且 allowed | — | T1210 |
| L005 | Identity Infrastructure Wide Exposure | HIGH／MEDIUM | Kerberos/LDAP/GC 非 blocked，唯一 `src_app` 數 > 門檻；allowed 撐起則 HIGH | `identity_unique_src_threshold=3` | T1558 |
| L006 | High Blast-Radius Lateral Movement Path | HIGH | lateral port（allowed）建 app→app 有向圖，BFS 算每節點可達數 ≥ 門檻 | `blast_radius_threshold=5` | T1021 |
| L007 | Unmanaged Host Accessing Critical Services | HIGH | `src_managed==False` 對 DB/Identity/WinMgmt port（非 blocked）flow 數 ≥ 門檻 | `unmanaged_critical_threshold=5` | T1210 |
| L008 | Lateral Ports in Test Mode (PB) | HIGH | lateral/WinMgmt/DB/Identity port 上 `potentially_blocked` flow 數 ≥ 門檻（強制執行落差）| `pb_lateral_threshold=10` | （治理，未對應）|
| L009 | Data Exfiltration Pattern (Outbound to Unmanaged) | HIGH | managed src → unmanaged dst、allowed、`bytes_total>0`，總量 ≥ 門檻 MB | `exfil_bytes_threshold_mb=100` | T1048 |
| L010 | Cross-Environment Lateral Port Access | CRITICAL | lateral/WinMgmt port 且跨 env 且 allowed，flow 數 ≥ 門檻 | `cross_env_lateral_threshold=5` | T1021、T1570 |

> L006 方法論借鏡圖論可達性（BFS）。治理型規則（B005、B009、L008、R01–R05）刻意**不對應** MITRE，以免誤導 SOC。

### 2.4 R 系列（Draft Policy 對齊）— 5 條

R 系列只在 unified DataFrame 帶有 **`draft_policy_decision`** 欄時才會評估（`_DraftPdRuleMixin._has_draft`）；缺欄即整批 no-op。皆屬 `DraftPolicy` 類別，MITRE 全部刻意不對應（治理/衛生型規則）。

| ID | 名稱 | 嚴重度 | 命中條件（draft_policy_decision）|
|----|------|--------|----------------------------------|
| R01 | Draft Deny Detected | HIGH | `policy_decision==allowed` 但 draft ∈ {`blocked_by_boundary`,`blocked_by_override_deny`}（現允許、草案會擋）|
| R02 | Override Deny Detected | HIGH | draft 以 `_override_deny` 結尾（override deny 規則，任何 allow 都無法蓋過）|
| R03 | Visibility Boundary Breach | MEDIUM | `policy_decision==potentially_blocked` 且 draft==`potentially_blocked_by_boundary`（VEN 在 visibility/test 模式且有 deny boundary 草案）|
| R04 | Allowed Across Boundary | LOW | draft==`allowed_across_boundary`（allow 規則覆蓋了一般 deny boundary，需確認是否刻意）|
| R05 | Draft Reported Mismatch | INFO | `policy_decision==allowed` 但 draft 以 `blocked_` 開頭（彙整 reported=allowed 但草案建議 block 的 workload 對）|

#### R 系列的啟用狀態（on-demand gate，請據實理解）

- **引擎已接好**：`RulesEngine.evaluate` 會在 DataFrame 帶 `draft_policy_decision` 欄時跑 R01–R05；該欄由查詢時的 `compute_draft=True`（PCE `update_rules`）產生。
- **標準報表路徑預設不含該欄**：`ReportGenerator.generate_from_api()` 的 `draft_policy` 參數預設 `False`，此時 `_fetch_traffic_df(..., compute_draft=draft_policy)` 傳入 `compute_draft=False`；cache 路徑（`read_flows_df`）本來就沒有 draft 欄。因此一般報表與 cache 命中報表的 DataFrame **不含** `draft_policy_decision`，R 系列即 no-op。
- **on-demand 觸發方式**：CLI 提供獨立子命令 `illumio-ops report draft-policy`（`src/cli/report.py`），呼叫時把 `draft_policy=True` 傳入 `generate_from_api`——此時強制 `use_cache=False`（cache 無 draft 欄）並帶 `compute_draft=True` 做即時 PCE 查詢。HTML 匯出層另外用 `ruleset_needs_draft_pd(DRAFT_PD_RULES)`（因 R01–R05 全部 `needs_draft_pd()=True`，此判斷恆為 True）決定 exporter 是否渲染 draft 相關欄位，與是否**抓取**該欄是兩回事。
- **成本**：把 `compute_draft` 接進每次報表抓取，會讓每份報表都付出 PCE `update_rules` 的成本（實測約 12 秒）。
- **結論**：R 系列為「引擎就緒 ＋ 資料已證實可得，但採按需（on-demand）啟用」，透過專門的 `report draft-policy` 命令觸發，並非每份報表都會執行。

---

## 3. 事件規則與 vendor catalog

事件處理分八個階段：**poll → normalize → dedup → throttle → classify（已知/未知）→ shadow-compare → stats → runbooks**（`src/events/`）。

### 3.1 Poll ＋ Dedup（`poller.py`）

- `EventPoller(api_client, max_results=5000, overlap_seconds=60, subscriber=None)`。
- `fetch_batch(watermark, seen_events)`：以 `watermark - overlap_seconds`（**60 秒重疊**，補抓遲到事件）為查詢起點。
- **去重**：`event_identity(event)` 為去重鍵——有 `href` 直接用之，否則對 `event_type/timestamp/status/severity/created_by/resource/message` 取 `sha1` 指紋；已在 `seen` 中者跳過。
- **溢位風險**：`overflow_risk = raw_count >= max_results`（≥ 5000 代表視窗可能被截斷）——由第 4 節的溢位 meta-alert 通知。
- `next_watermark` 取 `max(poll_started_at, watermark, latest_event_ts)`，單調不回退。

### 3.2 Normalize（`normalizer.py`）

`normalize_event(event)` 把原始 PCE event 攤平成穩定字典，欄位含 `event_id, href, timestamp, event_type, category, verb, status, severity, known_event_type, actor, actor_type, source_ip, target_*, resource_*, action_*, workloads_affected, parser_notes` 等。`known_event_type = is_known_event_type(event_type)` 即在此戳記。

### 3.3 Throttle（`throttle.py`）

`parse_throttle` 解析 `count/period[unit]`（單位倍率 `s=1, m=60, h=3600, d=86400`，預設 `m`）。`AlertThrottler.allow` 是 `period` 秒內最多 `count` 次的滑動視窗速率限制。

### 3.4 Classify 已知／未知（`catalog.py`）— vendor event catalog

- `KNOWN_EVENT_TYPES = VENDOR_DOCUMENTED_EVENT_TYPES | OBSERVED_EXTENSION_EVENT_TYPES`：**239** 個 vendor 文件記載型別 ＋ **54** 個實測觀察到的擴充型別 ＝ **293 個已知型別**（實際清點；`vendor 239 / observed_extension 54`，總數與坊間流傳的舊數字 285/288 不同，以本文清點為準）。
- `KNOWN_RESOURCE_PREFIXES`（**69** 個 resource 家族前綴）為第二道防線：對既有 resource 的新動作可被寬鬆視為已知。
- `is_known_event_type(event_type, lenient=False, *, resource_type=None)`：normalizer 以非寬鬆模式呼叫，凡不在 293 集合者一律標 `known_event_type=False` 並打 `unknown_event_type` 標籤。
- `classify_unknown_event_type(...)`：將未知型別歸入 resource 家族或標 `unclassified`。
- 即時引擎 `_update_parser_observability` 把未知型別累積到 `state["unknown_events"]`（上限 100 筆）。

### 3.5 Shadow-compare（`shadow.py`）— 診斷工具，非正式比對邏輯

`matches_event_rule_legacy` 是原始/簡化語意（僅逗號分隔精確比對，無 regex/否定/管線/巢狀）；`compare_event_rules` 同時跑「現行」與「legacy」matcher，比對命中集合差異並標 `same/mixed/current_more/legacy_more`，供 GUI 的 Shadow Compare、Rule Test 端點使用。**正式派送一律走 `matches_event_rule`**（第 1.3 節）。

### 3.6 Runbooks（`runbooks.py`）

`RUNBOOK_CATEGORIES` 把 event type 對應到操作指引，共 **17 個分類**，每個含 `patterns`（涵蓋的 event types）、`runbook_url`（docs.illumio.com 連結）、`severity_hint`、多行 `response` 處置劇本。`severity_hint=critical` 的分類共 5 個：`security-auth-failure`、`agent-tampering`、`auth-config`、`pce-capacity`、`server-errors`。`runbook_for(event_type)` 查回對應分類。

---

## 4. 告警通道設定與 test-send

### 4.1 五種通道

| 通道 | plugin 名 | 必要設定鍵 |
|---|---|---|
| Email（SMTP） | `mail` | `email.sender`、`email.recipients`、`smtp.host`、`smtp.port`（選用 `smtp.user`/`password`/`enable_tls`/`enable_auth`） |
| LINE Messaging API | `line` | `alerts.line_channel_access_token`、`alerts.line_target_id` |
| Webhook | `webhook` | `alerts.webhook_url`（POST JSON，期望 2xx） |
| Telegram Bot | `telegram` | `alerts.telegram_bot_token`、`alerts.telegram_chat_id` |
| Microsoft Teams | `teams` | `alerts.teams_webhook_url`（Power Automate Workflow webhook，送 Adaptive Card） |

啟用哪些通道由 `alerts.active` 清單決定（例如 `["mail", "line"]`）。各通道所需欄位、必填/密鑰標記見 `src/alerts/metadata.py` 的 `PLUGIN_METADATA`（GUI 表單即由此動態產生）。Teams webhook URL 內嵌有效機密（`sig=` 查詢字串），`redact_webhook_url()` 確保日誌與持久化只留 `scheme://host[:port]/...`，不外洩完整網址。

GUI 操作路徑（Settings → Channels 各通道卡片；Rules → Actions 全域測試）見 [gui-tour.md](gui-tour.md)。

### 4.2 Test-send

- **端點**：`POST /api/actions/test-alert`，body 可帶 `channel`（省略則對 `alerts.active` 全部通道各發一次）。呼叫 `Reporter.send_alerts(force_test=True, channels=channels)`，會**真的發送**測試訊息，正式環境使用前請先確認收件者。
- **每通道版本**：Settings → Channels 頁面每張通道卡片有各自的 Send test 按鈕，走同一端點但只帶該通道名稱。
- **限流**：端點掛 `10 per hour` rate limit（`@limiter.limit("10 per hour")`），避免誤觸洗版。
- `force_test=True` 時**略過** DLQ 補送與空告警短路判斷，一定會嘗試對指定通道送出一則測試訊息。

---

## 5. 可靠性機制

### 5.1 Dead-letter queue（DLQ）— 3 次重試

`Reporter.send_alerts()` 派送後若**所有**啟用通道皆失敗（非 `force_test`）：

1. 累計失敗次數 `attempts`；未達上限則把本輪四個 bucket（health/event/traffic/metric）連同 `attempts`、`first_failed_at` 存入 `state.json` 的 `alert_dlq`，等下次 `send_alerts` 呼叫時（`_pop_alert_dlq`）自動與新告警合併重送。
2. `ALERT_DLQ_MAX_ATTEMPTS = 3`：達到第 3 次仍失敗，直接**丟棄**該批告警並記一筆 `{"channel": "dlq", "status": "dropped", ...}` 結果，寫 error log。

DLQ 讀寫皆透過 `update_state_file` 做原子檔案更新，避免併發寫壞 state。

### 5.2 Watchdog — PCE 連續失敗自我告警

`Analyzer._check_watchdog()`：PCE 連續失敗次數（`pce_stats.consecutive_failures`）達 `WATCHDOG_FAILURE_THRESHOLD = 3` 次即觸發，以 `WATCHDOG_COOLDOWN_MINUTES = 60` 分鐘為冷卻（長時間中斷每小時只告警一次，不洗版）。目的是避免「poller 掛掉、沒有事件、沒有告警、卻誤以為一切正常」的靜默失效。

### 5.3 溢位 meta-alert

`Analyzer._maybe_alert_overflow()` 對兩種資料遺失訊號各自獨立告警（各自 state key／冷卻 key，互不抑制）：

- `event_overflow`：事件輪詢單批 ≥ `max_results`（5000），代表視窗可能被截斷、較舊事件遺失。
- `traffic_overflow`：cache-ingest 分段抓取（bisection）下限，代表某一分鐘的流量可能不完整。

兩者皆以 60 分鐘（`OVERFLOW_ALERT_COOLDOWN_MINUTES = 60`）為冷卻，每次呼叫 `run_analysis()`（不論是否走 legacy 無 cache-subscriber 分支）都會檢查，確保 `pce_cache.enabled=true` 部署下 `traffic_overflow` 訊號也不會被漏檢。

### 5.4 LINE 訊息截斷 footer

LINE push API 實際上限約 5000 字元；`Reporter._LINE_MESSAGE_CAP = 4500`（留 buffer）。`_build_line_message()` 組出完整摘要後，若超過上限：

```python
if len(message) > self._LINE_MESSAGE_CAP:
    footer = t("line_message_truncated")
    message = message[: self._LINE_MESSAGE_CAP - len(footer) - 1].rstrip() + "\n" + footer
```

即**明確截斷並附上「內容已截斷」的 i18n footer**，而非無聲截斷；Telegram 通道另有獨立的截斷 footer（`telegram_truncated_footer`，於最後一個換行處截斷以維持 HTML 標記平衡）。

---

## 6. 如何新增／調整規則

- **即時監控規則**：GUI／CLI 透過 `ConfigManager.add_or_update_rule()` 新增或覆寫（同 `type` 且 event 的 `filter_value`／traffic 的 `name` 相同視為同規則），寫入 `config/alerts.json`。套用最佳實務用 `apply_best_practices(mode="append_missing"|"replace")`；`replace` 會自動備份至 `rule_backups`（上限 10）。可調欄位：`threshold_type`、`threshold_count`、`threshold_window`、`cooldown_minutes`、`throttle`、`pd`、`port`/`proto`、各種 label/ip 包含與排除過濾。
- **報表規則門檻**：直接編輯 `config/report_config.yaml` 的 `ransomware_risk_ports`、`lateral_movement_ports`、`thresholds`。嚴重度分支邏輯（如 B001 的 cross-subnet 計數）寫在規則函式內，非設定值；改判斷邏輯需改 `rules_engine.py`／`src/report/rules/`，新增規則後記得在 `mitre_map.py` 對應 MITRE。
- **i18n 鍵**：監控規則持久化 `name_key`/`desc_key`/`rec_key`；報表 `Finding` 與分析模組同樣以 `t(key, lang=...)` 在讀取時在地化。新增規則應提供 i18n key 而非寫死文字。

---

## 附錄：誠實標示的程式落差（2026-07-17 現況核對）

- **「24 條規則」**：**仍成立**。逐檔清點 `src/report/rules_engine.py` 的 `_b001`–`_b009`（9 個）、`_l001`–`_l010`（10 個），加上 `src/report/rules/` 的 `r01`–`r05`（5 個檔案）＝ 24，與原始碼一致。
- **R 系列按需啟用**：**仍成立**。`ReportGenerator.generate_from_api()` 的 `draft_policy` 參數預設 `False`，標準/cache 報表路徑不帶 `compute_draft`；需透過獨立命令 `illumio-ops report draft-policy` 才會觸發（見 §2.4）。
- **mod04 風險 port 數（文件字串 vs 設定檔）**：**仍成立**。`src/report/analysis/mod04_ransomware_exposure.py` 的模組 docstring 仍寫「20 high-risk ports」，但 `config/report_config.yaml` 實際列出 **24** 個 distinct port（critical 5 ＋ high 5 ＋ medium 10 ＋ low 4，見 §2.1）。本文以設定檔實際內容為準。
- **vendor catalog 已知型別總數（舊文件誤差已修正）**：舊版文件曾記為 285/288，實際清點 `src/events/catalog.py` 為 `VENDOR_DOCUMENTED_EVENT_TYPES`（239）＋ `OBSERVED_EXTENSION_EVENT_TYPES`（54）＝ **293**；本文採實際清點數字。
- **runbook 分類數（舊文件誤差已修正）**：舊版文件記為 16 個分類、4 個 critical severity_hint；實際清點 `RUNBOOK_CATEGORIES` 為 **17** 個分類、**5** 個 critical（新增 `pce-capacity`）。本文採實際清點數字。
