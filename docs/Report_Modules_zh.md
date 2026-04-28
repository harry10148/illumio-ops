# 報表模組

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
<!-- END:doc-map -->

---

> **背景 — 報表使用的 Illumio 概念：** 本章節的報表使用 Illumio 的四維標籤系統（Role、Application、Environment、Location）對流量記錄進行分組與過濾，並參照各 workload 的執行模式（Idle、Visibility Only、Selective、Full）來說明為何流量顯示為「potentially blocked」而非 blocked。標籤維度與執行模式的定義請參閱 [docs/Architecture.md — 背景 — Illumio Platform](Architecture.md#background--illumio-platform)。

## 1. 產生報表

報表可從以下三處觸發：

| 位置 | 操作方式 |
|:---|:---|
| Web GUI → Reports 分頁 | 點選 **Traffic Report**、**Audit Summary**、**VEN Status** 或 **Policy Usage** |
| CLI → **2. Report Generation** 子選單項目 1–4 | 選擇報表類型與日期範圍 |
| Daemon 模式 | 透過 CLI **2. Report Generation → 5. Report Schedule Management** 設定 — 報表自動產生並可透過 Email 寄送 |
| 命令列 | `python illumio_ops.py --report --report-type traffic\|audit\|ven_status\|policy_usage` |

報表儲存至 `reports/` 目錄，依格式設定產生 `.html`（格式化報表）及/或 `_raw.zip`（CSV 原始資料）。

**所需相依套件：**
```bash
pip install pandas pyyaml
```

### 從快取讀取報表資料

當 `config.json` 中 `pce_cache.enabled = true` 時，稽核與流量報表會自動從本地 SQLite 快取讀取資料（若請求的日期範圍在保留期限內）。這可降低 PCE API 負載並加速報表產生。

若請求範圍超出保留期限，報表會自動回退至即時 PCE API。

如需匯入超出保留期限的歷史資料，請使用 backfill 命令：

```bash
illumio-ops cache backfill --source events --since YYYY-MM-DD --until YYYY-MM-DD
```

詳見 `docs/PCE_Cache.md`。

## 2. 報表類型總覽

| 報表類型 | 資料來源 | 模組數 | 說明 |
|:---|:---|:---|:---|
| **Traffic** | PCE 非同步流量查詢或 CSV | 15 模組 + 19 安全發現 | 全面的流量安全分析 |
| **Audit** | PCE events API | 4 模組 | 系統健康、使用者活動、政策變更 |
| **VEN Status** | PCE workloads API | 單一產生器 | VEN 清冊含線上/離線分類 |
| **Policy Usage** | PCE rulesets + 流量查詢，或 Workloader CSV | 4 模組 | 逐規則流量命中分析 |

## 3. 報表章節（Traffic Report）

流量報表包含 **15 個分析模組**加上安全發現章節：

| 章節 | 說明 |
|:---|:---|
| Executive Summary | KPI 卡片：總流量數、政策覆蓋率 %、重要發現 |
| 1 - Traffic Overview | 總流量數、允許/阻擋/PB 分佈、熱門埠 |
| 2 - Policy Decisions | 逐決策分佈含入站/出站拆分及逐埠覆蓋率 % |
| 3 - Uncovered Flows | 無允許規則的流量；埠缺口排名；未覆蓋服務（應用程式+埠） |
| 4 - Ransomware Exposure | **調查目標**（在關鍵/高風險埠上有 ALLOWED 流量的目的主機）醒目標示；逐埠明細；主機暴露排名 |
| 5 - Remote Access | SSH/RDP/VNC/TeamViewer 流量分析 |
| 6 - User & Process | 流量記錄中出現的使用者帳號與程序 |
| 7 - Cross-Label Matrix | 環境/應用/角色標籤組合間的流量矩陣 |
| 8 - Unmanaged Hosts | 來自/前往非 PCE 管理主機的流量；逐應用與逐埠明細 |
| 9 - Traffic Distribution | 埠與協定分佈 |
| 10 - Allowed Traffic | 熱門允許流量；稽核旗標 |
| 11 - Bandwidth & Volume | 依位元組排名的熱門流量 + 頻寬（自動調整單位）；Max/Avg/P95 統計卡片；異常偵測（多連線流量的 P95） |
| 13 - Enforcement Readiness | 0–100 分含因子分解與修復建議 |
| 14 - Infrastructure Scoring | 節點中心性評分以識別關鍵服務（入度、出度、介數中心性） |
| 15 - Lateral Movement Risk | 橫向移動模式分析與高風險路徑 |
| **Security Findings** | **自動化規則評估 — 詳見第 9.5 節** |

## 4. 安全發現規則

安全發現章節對每個流量資料集執行 **19 條自動偵測規則**，並依嚴重性（CRITICAL → INFO）與分類群組顯示結果。

**規則系列概觀：**

| 系列 | 規則 | 重點 |
|:---|:---|:---|
| **B 系列** | B001–B009 | 勒索軟體暴露、政策覆蓋缺口、行為異常 |
| **L 系列** | L001–L010 | 橫向移動、憑證竊取、爆炸半徑路徑、資料外洩 |

**快速參考：**

| 規則 | 嚴重性 | 偵測內容 |
|:---|:---|:---|
| B001 | CRITICAL | 勒索軟體常用埠（SMB/RDP/WinRM/RPC）未阻擋 |
| B002 | HIGH | 遠端存取工具（TeamViewer/VNC/NetBIOS）被允許 |
| B003 | MEDIUM | 勒索軟體常用埠處於測試模式 — 未執行阻擋 |
| B004 | MEDIUM | 來自未管理（非 PCE）主機的大量流量 |
| B005 | MEDIUM | 政策覆蓋率低於閾值 |
| B006 | HIGH | 單一來源在橫向移動埠上的扇出行為 |
| B007 | HIGH | 單一使用者觸及異常大量的目的端 |
| B008 | MEDIUM | 高頻寬異常（潛在外洩/備份） |
| B009 | INFO | 跨環境流量量超過閾值 |
| L001 | HIGH | 使用明文協定（Telnet/FTP） |
| L002 | MEDIUM | 網路探索協定未阻擋（LLMNR/NetBIOS/mDNS） |
| L003 | HIGH | 資料庫埠可從過多應用層級存取 |
| L004 | HIGH | 資料庫流量跨越環境邊界 |
| L005 | HIGH | Kerberos/LDAP 可從過多來源應用存取 |
| L006 | HIGH | 高爆炸半徑橫向路徑（BFS 圖分析） |
| L007 | HIGH | 未管理主機存取資料庫/身份/管理埠 |
| L008 | HIGH | 橫向移動埠處於測試模式 — 政策存在但未執行 |
| L009 | HIGH | 資料外洩模式（管理 → 未管理，高位元組數） |
| L010 | CRITICAL | 橫向移動埠跨環境邊界被允許 |

完整規則文件 — 包含觸發條件、攻擊技術背景及調整指南 — 請參閱 **[Security Rules Reference](Security_Rules_Reference.md)**。

## 5. 稽核報表章節

稽核報表包含 **4 個模組**：

| 模組 | 說明 |
|:---|:---|
| Executive Summary | 依嚴重性與分類的事件數量；熱門事件類型 |
| 1 - System Health Events | `agent.tampering`、離線 agents、心跳失敗 |
| 2 - User Activity | 身份驗證事件、登入失敗、帳號變更 |
| 3 - Policy Changes | Ruleset 與規則的建立/更新/刪除、政策佈建 |

## 6. VEN 狀態報表

VEN 狀態報表盤點所有 PCE 管理的 workloads，並分類 VEN 連線狀態：

| 章節 | 說明 |
|:---|:---|
| KPI Summary | VEN 總數、線上數、離線數 |
| Online VENs | agent 狀態為 active **且**最後心跳 ≤ 1 小時前的 VEN |
| Offline VENs | 已暫停/停止的 VEN，或 active 但心跳 > 1 小時前 |
| Lost (last 24 h) | 最後心跳在過去 24 小時內的離線 VEN |
| Lost (24–48 h ago) | 最後心跳在 24–48 小時前的離線 VEN |

每一列包含：主機名稱、IP、標籤、VEN 狀態、距上次心跳的小時數、最後心跳時間戳、政策接收時間戳、VEN 版本。

> **線上偵測**：PCE 的 `agent.status.status = "active"` 僅反映**管理**狀態。VEN 可能在無法連線（無心跳）時仍維持 `"active"`。報表使用 `hours_since_last_heartbeat` — VEN 僅在最後心跳 ≤ 1 小時前時才被視為線上。此行為與 PCE Web Console 一致。

## 7. Policy Usage 報表

Policy Usage 報表分析每條 PCE 安全規則的實際使用情況，透過比對實際流量記錄來評估。

| 模組 | 說明 |
|:---|:---|
| Executive Summary | 規則總數、有流量命中的規則數、覆蓋率百分比 |
| Overview | 啟用/停用分佈、active/draft 狀態 |
| Executive Summary（`pu_mod00_executive`） | 規則總數、有流量命中的規則數、覆蓋率百分比 |
| Overview（`pu_mod01_overview`） | 啟用/停用分佈、active/draft 狀態 |
| Hit Detail（`pu_mod02_hit_detail`） | 有匹配流量的規則；每條規則的熱門流量 |
| Unused Detail（`pu_mod03_unused_detail`） | 流量命中為零的規則；清理候選項 |
| Deny Effectiveness（`pu_mod04_deny_effectiveness`） | 確認 deny/override-deny 規則正在積極阻擋不需要的流量 |
| Draft Policy Decision（`pu_mod05_draft_pd`） | 逐規則 draft policy decision 風險 — 可見性風險、draft 衝突及三種角度的 draft 覆蓋缺口 |

**資料來源：**
- **API 模式**：從 PCE 取得活躍 rulesets，然後對每條規則執行平行非同步流量查詢以計算匹配流量數
- **CSV 模式**：匯入含預先計算流量數的 Workloader CSV 匯出檔（供離線分析使用）

## 8. 調整安全規則

所有偵測閾值位於 `config/report_config.yaml`：

```yaml
thresholds:
  min_policy_coverage_pct: 30         # B005
  lateral_movement_outbound_dst: 10   # B006
  db_unique_src_app_threshold: 5      # L003
  blast_radius_threshold: 5           # L006
  exfil_bytes_threshold_mb: 100       # L009
  cross_env_lateral_threshold: 5      # L010
  # ... (see Security_Rules_Reference.md for complete list)
```

編輯此檔案後重新產生報表即可套用新閾值 — 無需重新啟動。

## 9. 報表排程

透過 CLI **2. Report Generation → 5. Report Schedule Management** 或 Web GUI **Report Schedules** 分頁設定自動週期報表：

| 欄位 | 說明 |
|:---|:---|
| Report Type | Traffic Flow / Audit / VEN Status / **Policy Usage** |
| Frequency | Daily / Weekly（星期幾） / Monthly（每月幾號） |
| Time | 小時與分鐘 — 以您**設定的時區**輸入（自動以 UTC 儲存） |
| Lookback Days | 包含多少天的流量資料 |
| Output Format | HTML / CSV Raw ZIP / Both |
| Send by Email | 使用 SMTP 設定將報表附加至 Email 寄送 |
| Custom Recipients | 覆寫此排程的預設收件者 |

> **時區注意**：CLI 與 Web GUI 中的時間欄位始終以 Settings → Timezone 設定的時區顯示。底層以 UTC 儲存，因此即使變更時區設定，排程仍會正確執行。

Daemon 迴圈每 60 秒檢查排程，並執行任何已到達設定時間的排程。

每次成功執行後，舊報表檔案會根據**保留政策**自動清理 — 詳見第 11.3 節。

## 10. R3 智能模組

這些模組作為 Traffic Report 管線的一部分自動執行，並在 HTML 輸出中以專屬章節呈現。

| 模組 | 用途 | 輸入 | 輸出 | 相關設定 |
|---|---|---|---|---|
| `mod_change_impact` | 比較目前報表 KPI 與前次快照；針對每個 KPI 輸出 `improved` / `regressed` / `neutral` 判斷 | 目前 KPI 字典 + 前次 JSON 快照 | Delta 表格 + 整體判斷 + 前次快照時間戳 | `report.snapshot_retention_days` |
| `mod_draft_actions` | 針對需要人工審查的 draft policy decision 子類別提供可行的修復建議：Override Deny、Allowed Across Boundary、what-if | 含 `draft_policy_decision` 欄位的 Flows DataFrame | `override_deny` 區塊、`allowed_across_boundary` 區塊、`what_if_summary` | `report.draft_actions_enabled` |
| `mod_draft_summary` | 計算所有 7 種 draft policy decision 子類型並列出每種子類型的熱門 workload 配對 | 含 `draft_policy_decision` 欄位的 Flows DataFrame | `counts` 字典（7 個子類型）+ 每種子類型的 `top_pairs` | — |
| `mod_enforcement_rollout` | 依就緒分數排列應用程式，評估移至完整 enforcement 的優先順序 | 含 app 標籤（`src_app` / `dst_app`）的 Flows DataFrame + 選用 draft / readiness 摘要 | 含分數、`why_now` 理由、必要允許規則、風險降低的優先化應用清單 | — |
| `mod_exfiltration_intel` | 標記具有高位元組流量的受管至未管理流量；選用性地與已知惡意 IP 的 CSV 進行威脅情報比對 | 含 `src_managed` / `dst_managed` + 選用 `bytes` 欄位的 Flows DataFrame | `high_volume_exfil` 清單、`managed_to_unmanaged_count`、`threat_intel_matches` | `report.threat_intel_csv_path` |
| `mod_ringfence` | 每個應用程式的依賴 Profile + 微分段的候選允許規則；無特定目標應用時顯示熱門應用摘要 | 含 `src_app` / `dst_app` 標籤的 Flows DataFrame | 每個應用：應用內流量、跨應用流量、跨環境流量、候選允許規則；或熱門 20 個應用清單 | — |

**威脅情報 CSV 格式（`mod_exfiltration_intel`）：**

選用的 `report.threat_intel_csv_path` 檔案必須包含至少一個名為 `ip` 的欄位（已知惡意 IP 位址）。任何額外欄位（例如 `threat_category`、`confidence`、`source`）均會保留並顯示於威脅比對輸出中：

```csv
ip,threat_category,confidence,source
185.220.101.1,tor_exit_node,high,abuse.ch
203.0.113.45,c2_server,critical,custom_intel
```

在 `config.json` 中設定路徑：

```json
{
    "report": {
        "threat_intel_csv_path": "/opt/illumio_ops/data/threat_intel.csv"
    }
}
```

若未設定路徑或檔案不存在，`mod_exfiltration_intel` 仍會執行 — 它會回報高流量的受管→未管理流量，但回傳空的 `threat_intel_matches` 清單。

**應用程式 Ringfence 使用方式（`mod_ringfence`）：**

在撰寫微分段規則前，使用此模組隔離單一應用程式的依賴 Profile：

1. 執行 Traffic Report（模組預設產生熱門 20 個應用摘要）。
2. 從熱門應用清單中識別目標應用程式。
3. 重新執行聚焦於單一應用的報表 — 模組會回傳應用內流量、跨應用流量、跨環境流量及候選允許規則清單。
4. 使用候選允許規則清單作為在 PCE 中建立標籤式規則的基礎。

若流量資料集中不存在 `src_app` 或 `dst_app` 標籤，模組會靜默跳過。

## 11. Draft Policy Decision 行為

**`compute_draft` 自動啟用：** 當 ruleset 包含使用 `requires_draft_pd` 邏輯的規則時（即 ruleset 有待定的 draft 變更），報表管線會自動為該 ruleset 的流量啟用 draft policy decision 計算。

**HTML 報表標頭標籤：** 當 draft 計算啟用時，Traffic Report HTML 標頭會顯示「Draft Policy Active」指示標籤，讓 draft 範圍一目了然。

**`draft_breakdown` 交叉表（來自 `mod_draft_summary`）：** 顯示每種 draft policy decision 子類型流量數量的 7 欄交叉表：

| 子類型 | 意義 |
|---|---|
| `allowed` | 流量在 draft ruleset 下會被允許 |
| `potentially_blocked` | 流量無匹配的 draft 規則；預設 deny 會阻擋它 |
| `blocked_by_boundary` | 在 draft 中被 boundary 規則阻擋 |
| `blocked_by_override_deny` | 在 draft 中被 Override Deny 規則阻擋 |
| `potentially_blocked_by_boundary` | 在 visibility workload 上；draft boundary 在 enforcement 時會阻擋 |
| `potentially_blocked_by_override_deny` | 在 visibility workload 上；draft override deny 在 enforcement 時會阻擋 |
| `allowed_across_boundary` | 儘管跨越應用邊界仍被允許 — 需要審查 |

**`draft_enforcement_gap`（來自 `mod_draft_summary` / `mod_draft_actions`）：** `policy_decision = potentially_blocked` 但 draft 解析為 `allowed` 或 `blocked_by_boundary` 的流量集合 — 即目前無規則但在 draft 佈建後將被覆蓋（或明確阻擋）的流量。此缺口量化了下次 Provision 時將生效的執行落差。

## 12. 變更影響工作流程

`mod_change_impact` 模組比較目前報表的 KPI 與最近保存的快照。這讓跨報表執行的趨勢追蹤無需手動比對。

**快照運作方式：**

1. 每次產生 Traffic Report 時，引擎會保存一個包含報表 KPI 值與 `generated_at` 時間戳的快照 JSON。
2. 下次報表執行時，`mod_change_impact` 載入前次快照並計算各 KPI 的差值。
3. 超過 `report.snapshot_retention_days`（預設 90）的快照會自動刪除。

**KPI 方向語意：**

| KPI | 方向 | 較佳時 |
|---|---|---|
| `pb_uncovered_exposure` | 越低越好 | 降低 = 未覆蓋流量減少 |
| `high_risk_lateral_paths` | 越低越好 | 降低 = 橫向移動風險降低 |
| `blocked_flows` | 越低越好 | 降低 = 阻擋/丟棄流量減少 |
| `active_allow_coverage` | 越高越好 | 提升 = 更多流量有明確的允許規則 |
| `microsegmentation_maturity` | 越高越好 | 提升 = 更接近完整 enforcement |

**判斷邏輯：**

| 判斷 | 條件 |
|---|---|
| `improved` | 改善的 KPI 數量多於退步的 |
| `regressed` | 退步的 KPI 數量多於改善的 |
| `neutral` | 改善與退步的 KPI 數量相等 |

若無前次快照（首次報表執行），模組回傳 `skipped: true` 並附 `reason: no_previous_snapshot`。

**操作使用：** 以固定排程執行報表（例如每週），並監控 `overall_verdict` 趨勢。政策變更後持續出現 `regressed` 判斷表示該變更引入了新的覆蓋缺口或啟用了不需要的流量模式，應進行調查。

## 13. 執行推進規劃

`mod_enforcement_rollout` 模組依就緒分數排列流量資料集中所有應用程式，評估在 PCE 中移至完整 enforcement 模式的準備程度。

**評分公式：**

```
score = (allowed_flows / total_flows) - (potentially_blocked_flows / total_flows)
```

高分表示大多數流量已有允許規則覆蓋（高分子）且較少流量會因啟用預設 deny 而中斷（低分母）。分數接近 1.0 表示應用程式已準備好以最小的操作風險進行 enforcement。

**每個應用程式的輸出：**

| 欄位 | 說明 |
|---|---|
| `app` | 應用程式標籤值 |
| `priority` | 排名順序（1 = 最就緒） |
| `why_now` | 此排名的人類可讀理由 |
| `expected_default_deny_impact` | 將被丟棄的 `potentially_blocked` 流量數量 |
| `required_allow_rules` | enforcement 前需要允許規則的推斷埠/來源配對清單 |
| `risk_reduction` | enforcement 後預估的橫向移動暴露降低量 |

使用優先順序清單建立 enforcement 路線圖：從優先順序 1 的應用程式開始（已完整覆蓋），逐步處理需要額外允許規則的低優先順序應用程式。


---

## 附錄 A — 報表模組清單

> 從 `docs/report_module_inventory_zh.md`（ed20df0~1）翻譯 — Phase B 更新。

# 報表模組清單與導讀指南

本文盤點 illumio_ops 既有報表模組的實務價值，並定義每個章節應補充的導讀內容。目標是讓報表讀者不只看到圖表和表格，而是能理解「這章在回答什麼問題」、「哪些現象需要注意」、「下一步該做什麼」。

## NotebookLM 佐證摘要

根據 Illumio 筆記本中的手冊、API guide 與微分段技術說明，Traffic / Flow Visibility 在微分段專案中通常同時服務多個角色：

- 資安/SOC：威脅獵捕、異常偵測、事件回應、橫向移動與資料外洩調查。
- 網管/平台團隊：掌握連線相依性、建立 label-based allow rules、排查未納管或未知依賴。
- DevOps / DevSecOps：理解服務間連線，避免 CI/CD 或微服務變更破壞安全策略。
- App Owner：確認應用上下游依賴，審核合理白名單需求。

因此 Traffic Report 不應只是一份大而全報表。建議拆成兩種 profile：

- Security Risk Traffic Report：聚焦異常、危險流量、橫向移動、勒索軟體高風險埠、PB exposure、blocked/denied patterns、外部威脅或外洩跡象。
- Network Inventory Traffic Report：聚焦應用相依性、label matrix、candidate allow rules、shared infrastructure usage、unmanaged/unknown dependencies、enforcement readiness。

NotebookLM 也建議每個章節採固定導讀格式：

- 本章目的：這章回答什麼業務或資安問題。
- 要注意的訊號：哪些值、趨勢、組合代表異常或需要處理。
- 判讀方式：如何理解圖表、Policy Decision、label matrix 或風險分數。
- 建議行動：讀者看完後應調查、建規則、修 label、隔離、清理規則或修 VEN。

## 評分標準

| 分數 | 意義 |
| ---: | --- |
| 5 | 直接支援風險降低、事件調查、規則制定、enforcement 推進或治理決策。 |
| 4 | 對特定 persona 很有價值，但應 profile-specific 或摘要化。 |
| 3 | 有背景價值，但主報表中需要簡化或只在有異常時顯示。 |
| 2 | 適合 appendix / XLSX / CSV，不適合作為主要章節。 |
| 1 | 實務價值低、重複或容易誤導，除非重新設計否則應移除。 |

建議處置：

- `keep-main`：保留為主章節。
- `keep-profile-specific`：依 Security Risk / Network Inventory profile 決定是否主顯示。
- `redesign`：保留目的，但重寫摘要、圖表或導讀。
- `simplify`：保留但縮短。
- `conditional`：只有資料存在或偵測到異常時顯示。
- `appendix`：移到附錄、XLSX 或 CSV。
- `merge/remove`：合併到其他章節或移除。

## Traffic Report 模組盤點

| Module | 實務價值 | 建議 | 主要受眾 | 章節應表達什麼 |
| --- | ---: | --- | --- | --- |
| `mod01_traffic_overview` | 3 | `simplify` | mixed | 說明資料範圍、流量規模、時間範圍與政策決策概況；不應變成主要決策章節。 |
| `mod02_policy_decisions` | 5 | `keep-profile-specific` | security/network | 說明 allowed / blocked / potentially_blocked 的真實比例。資安看未授權或危險流量；網管看規則覆蓋與 enforcement 影響。 |
| `mod03_uncovered_flows` | 5 | `keep-main` | security/network | 說明哪些流量缺乏 allow policy，進入 enforcement 後可能被 default-deny 影響。PB 必須被視為 gap，不是 staged coverage。 |
| `mod04_ransomware_exposure` | 5 | `keep-profile-specific` | security | 找出 SMB、RDP、SSH 等高風險橫向移動通道，協助資安優先調查或限制。 |
| `mod05_remote_access` | 2 | `merge/remove` | security | 已被 `mod15_lateral_movement` 整併，不建議恢復成獨立主章節，避免重複。 |
| `mod06_user_process` | 3 | `conditional` | security | 當 user/process 欄位存在時，找出異常執行程序、非預期使用者或可疑高活動行為。無資料時不應空顯示。 |
| `mod07_cross_label_matrix` | 4 | `keep-profile-specific` | network/app_owner | 把 observed flows 轉成 label-to-label 依賴矩陣，支援規則制定。資安版只應顯示 risky crossing。 |
| `mod08_unmanaged_hosts` | 5 | `keep-main` | security/network | 找出受管 workload 與 unknown/unmanaged destination 的連線。這同時是風險盲點與規則制定阻礙。 |
| `mod09_traffic_distribution` | 2 | `appendix` | network | Port/protocol 分布本身不是決策；只有出現異常集中、陌生服務或趨勢變化時才適合主顯示。 |
| `mod10_allowed_traffic` | 4 | `keep-profile-specific` | network/security | 網管用於建立 allow rules；資安只看 high-risk allowed paths 或跨區域高風險 allowed traffic。 |
| `mod11_bandwidth` | 3 | `conditional` | security/network | 高流量可用於外洩或容量判讀，但一般 Top Talkers 應進 appendix。 |
| `mod12_executive_summary` | 5 | `redesign` | executive/mixed | 應依 profile 產出不同摘要。風險版講 top risks/actions；盤點版講 rule readiness/dependency gaps。 |
| `mod13_readiness` | 5 | `keep-main` | network/executive | 評估哪些 app/env 可推 enforcement、哪些 label/rule/unknown dependency 還沒準備好。 |
| `mod14_infrastructure` | 5 | `keep-profile-specific` | security/network | 找出 DNS、AD、NTP、DB、proxy、backup、logging 等 shared/crown-jewel service 的暴露與依賴。 |
| `mod15_lateral_movement` | 5 | `keep-profile-specific` | security/network | 資安版用來看橫向移動與 blast radius；盤點版用來理解跨 app/env 依賴與 enforcement 邊界。 |
| `attack_posture.py` | 5 | `keep-supporting` | security/executive | 應作為風險評分與 Top Actions 來源，而不是再產生一個讀者不懂的獨立章節。 |

## Audit Report 模組盤點

| Module | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| `audit_mod00_executive` | 4 | `keep-main` | 說明 audit 期間是否有高風險操作、異常控制面活動、需立即關注的事件。 |
| `audit_mod01_health` | 4 | `keep-main` | 說明 PCE/API/audit 資料是否可信，是否有同步、健康或資料完整性問題。 |
| `audit_mod02_users` | 3 | `conditional` | 只在出現高權限、非預期、離峰或異常大量操作時主顯示；一般 top users 應 appendix。 |
| `audit_mod03_policy` | 5 | `keep-main` | 說明 policy/rule set 變更是否合理、是否過寬、是否可能造成風險或斷線。 |
| `audit_mod04_correlation` | 5 | `keep-main` | 把 auth failure、policy change、VEN change、provision 等事件串成可調查故事。 |
| `audit_risk.py` | 5 | `keep-supporting` | 支撐 audit risk scoring 與 attention required，不應讓讀者只看到分數但不知道原因。 |

## Policy Usage Report 模組盤點

| Module | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| `pu_mod00_executive` | 4 | `redesign` | 應說明可清理規則、有效 deny、過寬 allow 與查詢信心，而不是只列總數。 |
| `pu_mod01_overview` | 3 | `simplify` | 保留查詢範圍與資料品質，不應成為主要章節。 |
| `pu_mod02_hit_detail` | 4 | `appendix/main-summary` | Top hit rules 可主顯示；完整 hit detail 應進 XLSX/CSV。 |
| `pu_mod03_unused_detail` | 5 | `keep-main` | 直接支援規則清理與 policy hygiene，是高價值章節。 |
| `pu_mod04_deny_effectiveness` | 5 | `keep-main` | 證明 deny/override deny 是否有效阻擋不想要的流量，支援控制有效性。 |

## VEN Status Report 盤點

| Section | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| VEN summary | 5 | `keep-main` | 說明整體 agent 健康、enforcement 進度與 segmentation blind spots。 |
| Offline / lost heartbeat | 5 | `keep-main` | 失聯 workload 會造成控制盲點，應優先依 app/env/role 影響排序。 |
| Policy sync status | 5 | `keep-main` | Policy 未同步代表控制狀態可能與 PCE 不一致，應列出需修復對象。 |
| Enforcement mode | 5 | `keep-main` | 追蹤 visibility_only/selective/full 推進狀態，支援微分段專案進度管理。 |
| Online inventory | 2 | `appendix` | 完整線上清單適合 XLSX，不適合主報表。 |

## 建議章節導讀格式

每個主要章節都應在圖表或表格前加入導讀區塊。

```text
本章目的：
說明這章回答的問題，以及它和微分段/風險/規則制定的關係。

要注意的訊號：
列出應優先關注的數值、趨勢、異常組合或資料缺口。

判讀方式：
解釋圖表、Policy Decision、label matrix、風險分數或狀態欄位應如何解讀。

建議行動：
提供讀者下一步，例如調查、確認 App Owner、建立 allow rule、修 label、隔離主機、清理規則或修復 VEN。
```

## 高優先章節導讀範例

### Potentially Blocked / Uncovered Flows

本章目的：找出目前因 workload 尚未進入完整 enforcement 而仍可通過，但缺乏 matching allow rule 的流量。

要注意的訊號：PB 流量集中在核心服務、高風險 port、跨 env、跨 app、unmanaged destination，或在近期變更後突然上升。

判讀方式：`potentially_blocked` 不是「規則已準備好」，而是「目前沒有對應 allow/deny rule；若進入 default-deny enforcement，這類流量可能被阻擋」。

建議行動：與 App Owner 確認是否為合法依賴。合法流量應轉成 label-based allow rule；不合法或未知流量應保留為未來 enforcement 的阻擋候選。

### Application Dependency / Cross-Label Matrix

本章目的：把 observed east-west flows 轉成可制定微分段規則的 app/env/role/service 依賴。

要注意的訊號：Dev 到 Prod、跨 app 直連 DB、unknown destination、unmanaged dependency、過多 any-to-any 類型連線。

判讀方式：矩陣不是要展示所有流量，而是要幫網管和 App Owner 確認「哪些 label group 之間需要 allow rule」。

建議行動：將合法依賴整理成候選 allow rules；補齊缺失 label；將 unknown IP 建成 IP List 或 unmanaged workload；移除不符合架構的依賴。

### Lateral Movement

本章目的：找出可能擴大攻擊面或支援橫向移動的 east-west path。

要注意的訊號：SMB/RDP/SSH/WinRM 等高風險 port、單一來源連大量目的地、跨 zone/cross-env 通訊、連向 crown-jewel infrastructure。

判讀方式：節點和邊的數量代表 blast radius；高風險服務和跨邊界連線應比一般流量優先處理。

建議行動：對可疑來源啟動事件調查；對合法但高風險依賴建立最小權限規則；必要時 quarantine 或先以 deny/boundary 限縮。

### Draft Policy

本章目的：在 provision 前模擬規則變更對現有流量的影響。

要注意的訊號：Draft View 中關鍵業務流量仍為 not allowed / potentially blocked，或新規則 scope 過寬。

判讀方式：Reported View 是目前實際狀態；Draft View 是草稿規則生效後的預期狀態。兩者差異應被視為變更影響分析。

建議行動：Provision 前先確認必要流量已被 allow；縮小過寬規則；把仍會被阻擋的合法流量補成候選規則。

### VEN Status

本章目的：確認 segmentation control plane 是否能實際作用到 workload。

要注意的訊號：offline、lost heartbeat、degraded、policy not synced、host firewall tampering、長期停留 visibility_only。

判讀方式：沒有健康 VEN，就算 PCE 有正確 policy，也可能無法有效執行。VEN 問題應視為 segmentation blind spot。

建議行動：優先修復 crown-jewel 或高風險 app 的 VEN；檢查 PCE 連線、憑證、service 狀態與 policy sync；將健康且規則完整的 workload 推進 enforcement。


## 延伸閱讀

- [使用手冊](./User_Manual_zh.md) — 執行模式、規則類型、告警通道與部署
- [Security Rules Reference](./Security_Rules_Reference_zh.md) — R-Series 規則與 `compute_draft` 行為
- [Architecture](./Architecture_zh.md) — 系統概觀、模組地圖、PCE 快取、REST API 手冊
