# 設計：Policy Resolver（標籤式策略 → IP 級防火牆規則展開）

- **日期**：2026-06-08
- **範圍代號**：P3（借鏡 alexgoller/illumio-plugger 系列的優化規劃，第三項）
- **狀態**：設計待實作（spec → writing-plans）

## 1. 背景與方向

Illumio 的策略是**抽象標籤式**的：每條 rule 用 label / label_group / ip_list / workload 描述 consumers（來源）與 providers（目的），用 service 描述 port/protocol。第三方防火牆（傳統 NGFW、雲端 SG）無法直接吃這套抽象 — 它們要的是具體的 `src_ip / dst_ip / port / protocol`。

本 spec 設計一個 **Policy Resolver**：把每條 active ruleset/rule 的 scope + consumers/providers + services **完全展開**成一份扁平、可直接落地的 IP 級規則清單，交給第三方防火牆實作或稽核。

**方向**：與既有報表引擎一致地新增一個 report 模組（CLI `report` 子命令 + scheduler 連接，比照 commit ff93df9 的 security_risk / network_inventory），輸出 JSON + CSV，**作用於 ACTIVE policy**。解析核心是**純函式**，與 I/O 分離，可用合成資料單元測試。

明確排除（YAGNI）：策略「衝突/陰影」分析、規則最佳化、deny/override 模擬、跨 PCE 比對、即時 GUI 互動展開（皆非本 spec）。

## 2. 鎖定決策（不再爭論）

- **解析來源（完全展開）**：
  - label / label_group → 成員 workloads → 介面 IP；
  - ip_list → 其 CIDR 範圍（`ip_ranges` 的 `from_ip`/`to_ip` 與 `fqdn` 視為一筆網段/條目）；
  - workload → 其介面 IP。
- **輸出**：JSON + CSV，走既有 exporter 管線；每個 ruleset 一份扁平 resolved 清單。
- **對象**：ACTIVE policy（`get_active_rulesets()`）。
- **落點**：新 report 模組，可由 CLI `report` 執行，並比照 security_risk/network_inventory 連接 scheduler。
- **設定檔**：JSON（永不 YAML）。

## 3. 現況與既有可重用資產（已逐一以程式碼核實）

- `src/api_client.py`
  - `get_active_rulesets() -> list[dict]`（行 748）：回傳 active rule_sets（含 `rules`）。✅ 直接用。
  - `fetch_managed_workloads(max_results=10000) -> list`（行 637）：回傳 VEN-managed workloads（含 `interfaces`）。✅ 用於 label→workload→IP 展開來源。
  - `search_workloads(params) -> list`（行 652）：依 label href 篩 workloads（備用）。
  - `_resolve_label_group_filter_to_actor()`（行 370）/ labels 模組（`src/api/labels.py:352`）：把 label_group 名稱/href 正規化成 `{"label_group": {"href": ...}}` actor，但**不展開成員**。
  - `resolve_actor_str()` / `resolve_service_str()`（行 376/379；`labels.py:407/422`）：actor/service → 人類可讀字串（給 CSV 顯示欄用）。
- **缺口（必須新增，已在 plan 以完整程式碼補上）**：
  1. **無公開「取得所有 ip_lists（含 `ip_ranges`）」方法**。現況只在 `labels.py:208-236` 透過 `/orgs/{org}/sec_policy/draft/ip_lists` 填 href→name 快取，**沒有回傳 `ip_ranges`**。→ Plan Task 1 新增 `ApiClient.get_ip_lists()`。
  2. **無公開「取得所有 label_groups（含成員 `labels`/`sub_groups`）」方法**。→ Plan Task 1 新增 `ApiClient.get_label_groups()`。
- 資料形狀（已核實）：
  - workload 介面：`wl.get("interfaces", [])`，每筆 `iface.get("address")`（見 `src/gui/routes/actions.py:150-153`、`src/static/js/quarantine.js:576-577`）。
  - rule 欄位：`r.get("providers", [])`、`r.get("consumers", [])`、`r.get("ingress_services", [])`（見 `src/gui/routes/rule_scheduler.py:135-136,189-190`）。
  - actor 形狀：`{"label": {"href"}}`、`{"label_group": {"href"}}`、`{"ip_list": {"href"}}`、`{"workload": {"href"}}`、`{"ip_address": {"value"}}`、`{"actors": "ams"}`（見 `src/api/labels.py:302-327`）。
  - service 形狀：`{"port", "proto", "to_port"}` 或 `{"href"}`（見 `resolve_service_str`，`labels.py:422`）；`proto==17` 為 UDP，否則 TCP。

## 4. 架構

三層，I/O 與純核心嚴格分離：

```
src/report/policy_resolver_report.py   # facade：fetch → 呼叫純核心 → exporter（比照 security_risk_report.py）
src/report/analysis/policy_resolver.py # 純核心：resolve_ruleset(...) 吃 lookups、吐扁平 rows（零 I/O、可單測）
src/report/exporters/policy_resolver_exporter.py  # JSON + CSV 輸出（重用既有 CsvExporter）
```

- facade 的 `run(output_dir, lang)` 形狀與 `SecurityRiskReport.run` 一致，回傳輸出路徑（多檔時回傳 list 或 zip 路徑）。
- 純核心**不碰 ApiClient**，只吃預先 fetch 好的查找表（lookups），故可用合成 dict 完整單測。

### 4.1 純核心介面

`src/report/analysis/policy_resolver.py`：

```python
def resolve_ruleset(
    ruleset: dict,
    *,
    label_to_ips: dict[str, list[str]],       # label href → [workload IPs]
    iplist_to_cidrs: dict[str, list[str]],    # ip_list href → [CIDR/range strings]
    label_group_to_labels: dict[str, list[str]],  # label_group href → [member label hrefs]（已遞迴展平）
    workload_to_ips: dict[str, list[str]],    # workload href → [IPs]
) -> list[dict]:
    """純衍生：把單一 ruleset 的每條 rule 展開成扁平的 src/dst/port/proto rows。"""
```

每筆 resolved row：

```json
{
  "ruleset_name": "App-Tier",
  "rule_href": "/orgs/1/sec_policy/active/rule_sets/12/sec_rules/3",
  "src_ip": "10.0.1.5",
  "dst_ip": "10.0.2.7",
  "port": 443,
  "protocol": "TCP",
  "src_kind": "workload",     // workload | ip_list | label | label_group | any
  "dst_kind": "label",
  "service_name": "HTTPS"
}
```

### 4.2 展開語意（純核心內部）

對每條 rule：

1. **scope**：active ruleset 的 `scopes` 是「AND 縮限」標籤集合。本 spec 採**保守、可解釋**作法：scope 標籤併入 providers 側的解析輸入（providers 必須同時落在 scope 內），與 Illumio「scope 限定 ruleset 範圍」一致；scope 為空（全域 ruleset）則不縮限。實作以「scope label 交集」函式表達，並以表格驅動測試固定行為。
2. **consumers → src IP 集合**、**providers → dst IP 集合**：對每個 actor 依 kind 展開
   - `label` → `label_to_ips[href]`
   - `label_group` → 先 `label_group_to_labels[href]` 取成員 label hrefs，再各自 `label_to_ips`
   - `ip_list` → `iplist_to_cidrs[href]`
   - `workload` → `workload_to_ips[href]`
   - `ip_address` → 直接用 `value`
   - `actors == "ams"`（All Managed）→ 特例：以 sentinel `"ANY"` 表示（不展開全 estate，避免笛卡兒爆炸；於 row 標 `src_kind/dst_kind = "any"`）。
3. **services → (port, protocol) 集合**：
   - `{"port","proto"}` → `(port, "UDP" if proto==17 else "TCP")`；`to_port` 存在則展成 port range 的兩端（記錄 `port` 為 from、附 `port_to`，或逐一展開 — 見 §6 邊界）。
   - `{"href"}`（具名 service）→ 由 service lookup 取其 `service_ports`（plan 以 service href→ports 查找表注入；若 service fetch 缺，plan Task 標明新增）。
4. **笛卡兒積**：`src_ip × dst_ip × (port,proto)` 產生扁平 rows；去重。

### 4.3 I/O facade 職責

`policy_resolver_report.py` 在 `run()` 內：

1. `get_active_rulesets()`、`fetch_managed_workloads()`、`get_ip_lists()`、`get_label_groups()`（後二為新增）。
2. 建 lookups：
   - `workload_to_ips`：`{wl["href"]: [i["address"] for i in wl.get("interfaces",[]) if i.get("address")]}`。
   - `label_to_ips`：掃 workloads 的 `labels`（每 workload 帶其 label hrefs），把 IP 歸到對應 label href（O(1) streaming，單趟掃描）。
   - `iplist_to_cidrs`：由 `get_ip_lists()` 的 `ip_ranges`（`from_ip`/`to_ip`）與 `fqdns` 組字串。
   - `label_group_to_labels`：由 `get_label_groups()` 的 `labels` + `sub_groups` 遞迴展平。
3. 逐 ruleset 呼叫 `resolve_ruleset(...)`，彙整成 `module_results`，交 exporter。

> **快取考量**：workload 集合可能很大；facade 一次性建 lookups（單趟 O(N) 掃描），純核心對 lookups 做 O(1) 查找。`src/pce_cache` 的 reader 目前存的是 traffic flow agg（非 workload inventory），故本 spec 不依賴它做 workload 展開；維持「fetch 一次、查找表 O(1)」即可。

## 5. 落點：報表引擎 / CLI / Scheduler

- **CLI**：在 `src/cli/report.py` 新增 `report resolve`（或 `report policy-resolver`）子命令，比照 `report_security`/`report_inventory` 的 click 樣板（`--format`、`--output-dir`、`--email`、`--source`）。格式至少支援 `json`/`csv`（`_REPORT_FORMATS` 已含 `csv`；JSON 由新 exporter 提供）。
- **Scheduler**：在 `src/report_scheduler.py` 的 `_generate_report` 新增 `report_type == "policy_resolver"` 分支；`_REPORT_PREFIXES` 加 `"policy_resolver": "Illumio_Policy_Resolver_"`；email subject map 加對應 `rpt_*` 標題 key（比照 ff93df9）。
- **Report facade**：`PolicyResolverReport(cm, api_client, config_dir, cache_reader).run(output_dir, lang)`，形狀比照 `SecurityRiskReport`。

## 6. 邊界與決策

- **port range（`to_port`）**：預設輸出單筆並帶 `port`（from）+ `port_to`（to）兩欄，**不**逐一展開成上萬筆（避免爆量）；CSV 顯示為 `from-to`。
- **All Managed（ams）/ 空 actor**：以 `"ANY"` sentinel 表示，row kind 標 `any`，不展開全 estate。
- **無介面 IP 的 workload**：跳過（不產生 row），但於 `findings`/`note` 記其 href（供稽核）。
- **IPv6**：保留（`iface.address` 可能是 v6）；不過濾。
- **去重**：同一 `(rule_href, src_ip, dst_ip, port, protocol)` 只留一筆。
- **缺漏 lookup**（label href 查無成員）→ 該 actor 展開為空集合（不報錯），並記 `note`。
- **deny/override rule**：本 spec 只展開 allow 語意的 src/dst/port；不模擬優先序（YAGNI）。

## 7. i18n

- 新增 `rpt_` 前綴 key（報表標題、欄位）與必要的 `gui_`（若 GUI 出現）：
  - `rpt_policy_resolver_title`、`rpt_pr_col_src_ip`、`rpt_pr_col_dst_ip`、`rpt_pr_col_port`、`rpt_pr_col_protocol`、`rpt_pr_col_ruleset`、`rpt_pr_col_service`、`rpt_email_pr_subject`。
- EN 與 ZH_TW 雙檔同步；遵守 glossary preserve-list（**Workload / Label / Ruleset / Service / Port / Policy / IP List** 於 zh_TW 保留）；新增後跑 `python scripts/audit_i18n_usage.py` 驗 parity 與 glossary。

## 8. 測試策略

- **純核心（表格驅動，合成 lookups）**：
  - label → workload IPs 展開（單/多介面、多 workload）。
  - label_group → 遞迴成員 → IPs。
  - ip_list → CIDR/range。
  - workload actor → IPs。
  - service：port/proto（含 UDP=17）、to_port range、具名 service。
  - 笛卡兒積筆數與去重正確。
  - 邊界：ams→ANY、無介面 workload 跳過、查無成員→空集合 + note。
  - scope 縮限：scope 非空時 providers 須落在 scope。
- **facade lookups 建構**：以 mock ApiClient 回傳合成 workloads/ip_lists/label_groups，驗 lookups 正確（label_to_ips 單趟掃描歸戶）。
- **新增 API 方法**：`get_ip_lists` / `get_label_groups` 以 mock `_api_get` 驗 endpoint 與回傳解析。
- **exporter**：JSON 結構 + CSV 欄位（重用 CsvExporter 的 DataFrame 走訪）。
- **CLI / scheduler 連接**：比照 `tests/test_traffic_report_split.py`，驗 `_REPORT_PREFIXES`、email subject、`_generate_report` 分派。
- **i18n parity / glossary**：`tests/test_i18n_audit.py`、`tests/test_i18n_glossary.py`。

## 9. 風險與緩解

- *風險*：完全展開導致 row 爆量（大 estate × 寬 service range）→ *緩解*：port range 不逐一展開（保 from/to 兩欄）；ams 不展開全 estate（ANY sentinel）；row 去重。
- *風險*：新增 `get_ip_lists`/`get_label_groups` 取 draft 還是 active 不一致 → *緩解*：與既有 `labels.py:208-209` 一致取 **draft**（href→定義穩定），但 rulesets 取 **active**；於 spec/plan 明示此差異並以測試固定。
- *風險*：label→IP 歸戶錯（workload 多 label）→ *緩解*：facade 單趟掃描、表格驅動測試覆蓋多 label workload。

## 10. 後續（不在本 spec）

- 策略衝突/陰影分析、規則最佳化建議。
- 與 traffic 實測流量比對（哪些 resolved rule 實際有流量）。
- 互動式 GUI 展開檢視。
