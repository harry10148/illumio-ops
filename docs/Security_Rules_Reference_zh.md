# Illumio PCE Ops — 安全規則參考

本文件說明 Traffic Report 與 RulesEngine 目前使用的安全發現規則。規則分成：

- **R 系列**：Draft policy decision 專用規則。
- **B 系列**：Baseline coverage / ransomware / anomaly 規則。
- **L 系列**：Lateral movement 與 exfiltration 規則。
- **分析模組**：不一定產生 `Finding`，但會在報表中提供排序、摘要、圖表或 remediation。

## 1. 嚴重性

| Severity | 用途 |
|:---|:---|
| `CRITICAL` | 已存在跨安全邊界的高危可利用路徑，需立即處理 |
| `HIGH` | 明確安全風險，可能導致 lateral movement、資料外洩或重大政策落差 |
| `MEDIUM` | 有風險但需要更多上下文，或風險受 enforcement/test mode 影響 |
| `LOW` | 需要確認意圖或縮小範圍 |
| `INFO` | 提醒、盤點或供後續 review |

## 2. Policy Decision 欄位

### 2.1 `policy_decision`

PCE traffic record 的既有決策狀態，描述目前 flow 在現行政策下的狀態：

- `allowed`
- `blocked`
- `potentially_blocked`
- `unknown`

### 2.2 `draft_policy_decision`

當查詢要求 draft policy decision 時，PCE 回傳以 draft 規則重算後的結果。它能揭露「目前 allowed，但 draft provision 後會 blocked」或「allow rule 跨過 boundary」等情境。

常見 subtype：

- `allowed`
- `allowed_across_boundary`
- `blocked_by_boundary`
- `blocked_by_override_deny`
- `potentially_blocked_by_boundary`
- `potentially_blocked_by_override_deny`
- 其他 PCE 版本特定值

### 2.3 行為規則

- `allowed` + `draft_policy_decision` 為 blocked subtype：代表目前可通，但 draft provision 後會中斷。
- `potentially_blocked`：代表目前因 workload 未完全 enforced 而仍可通；進入 enforcement 後會被擋。
- `allowed_across_boundary`：代表有 allow rule 穿越 boundary，需確認是否刻意。
- override deny 優先權高於 allow，應特別 review。

## 3. R 系列 — Draft Policy Decision

| Rule | Severity | 觸發條件 | 建議 |
|:---|:---|:---|:---|
| R01 Draft Deny Detected | HIGH | `policy_decision=allowed`，但 draft 會 blocked by boundary 或 override deny | Provision 前確認是否會中斷必要流量；必要時先補 explicit allow |
| R02 Override Deny Detected | HIGH | draft decision 以 `_override_deny` 結尾 | 確認 override deny 是否刻意；它不可被 allow 覆蓋 |
| R03 Visibility Boundary Breach | MEDIUM | `policy_decision=potentially_blocked` 且 draft 為 `potentially_blocked_by_boundary` | 將 workload 移入 enforced mode 以啟用 boundary deny |
| R04 Allowed Across Boundary | LOW | `draft_policy_decision=allowed_across_boundary` | 確認跨 boundary allow 是否必要並縮小 scope |
| R05 Draft Reported Mismatch | INFO | 目前 allowed 但 draft 以 `blocked_` 開頭 | Provision 前列出 top workload pairs 做變更影響 review |

## 4. B 系列 — Baseline 規則

### B001 · Ransomware Risk Port — Contextual Analysis

針對 critical ransomware ports（RPC、SMB、RDP、WinRM）進行情境化判斷。Severity 不只看 port，也看跨環境、跨 subnet、allowed 或 potentially_blocked。

- `CRITICAL`：跨環境 lateral/management port。
- `HIGH`：跨 subnet 且 explicit allowed。
- `MEDIUM`：同 subnet 或 test-mode 類風險。
- `INFO`：同 subnet 且只在 potentially_blocked。

### B002 · Ransomware Risk Port High

偵測 high tier ports，例如 TeamViewer、VNC、NetBIOS 等。重點是 remote-control 或 legacy exposure 是否未被封鎖。

### B003 · Ransomware Risk Port Medium — Uncovered

偵測 medium tier ports，例如 SSH、NFS、FTP、mDNS、LLMNR、HTTP、WSD、SSDP、Telnet 等，特別是 uncovered/test-mode flow。

### B004 · Unmanaged Source High Activity

未受管來源產生大量連線，超過 `unmanaged_connection_threshold`。代表 shadow IT、未安裝 VEN 的主機或潛在攻擊來源。

### B005 · Low Policy Coverage

Policy coverage 低於 `min_policy_coverage_pct`。代表 microsegmentation rule 尚不足，allowed/default-deny 行為不可靠。

### B006 · High Lateral Movement

來源在 lateral ports 連到過多目的地，超過 `lateral_movement_outbound_dst`。表示單一 host/app 具備過大 fan-out。

### B007 · Single User High Destinations

單一使用者連線到過多目的地，超過 `user_destination_threshold`。適合偵測帳號濫用或自動化掃描。

### B008 · High Bandwidth Anomaly

bytes / bandwidth 超過 `high_bytes_percentile` 或 `high_bandwidth_percentile`。用於找大量資料移動。

### B009 · Cross-Env Flow Volume

跨環境流量量超過 `cross_env_connection_threshold`。代表 macro-segmentation 邊界可能過寬。

## 5. L 系列 — Lateral Movement 規則

### L001 · Cleartext Protocol in Use

偵測 Telnet、FTP 等明文協定。明文協定會暴露 credential 或 session 資訊。

### L002 · Network Discovery Protocol Exposure

偵測 NetBIOS、mDNS、LLMNR、SSDP、WSD 等 discovery/broadcast 類協定，超過 `discovery_protocol_threshold`。

### L003 · Database Port Wide Exposure

Database ports（MSSQL、MySQL、PostgreSQL、Oracle 等）可從過多 source app 抵達，超過 `db_unique_src_app_threshold`。

### L004 · Cross-Environment Database Access

跨 environment 的 allowed database flow。Dev/Test/Staging 直連 Prod DB 通常應視為高風險。

### L005 · Identity Infrastructure Wide Exposure

Kerberos、LDAP、LDAPS、Global Catalog、Kpasswd 等 identity ports 可從過多 source app 抵達，超過 `identity_unique_src_threshold`。

### L006 · High Blast-Radius Lateral Movement Path

以 app/env graph 計算可達性，若節點可經 allowed lateral paths 抵達過多 app，超過 `blast_radius_threshold`。

### L007 · Unmanaged Host Accessing Critical Services

未受管 host 連往 database、identity、Windows management ports，且流量數超過 `unmanaged_critical_threshold`。

### L008 · Lateral Ports in Test Mode

`potentially_blocked` flow 落在 lateral/critical ports，且數量超過 `pb_lateral_threshold`。這類 path 目前仍可通，只是 enforcement 後才會擋。

### L009 · Data Exfiltration Pattern

Managed source 對 unmanaged destination 傳輸大量資料，超過 `exfil_bytes_threshold_mb`。

### L010 · Cross-Environment Lateral Port Access

跨 environment 且使用 SMB、RDP、WinRM、RPC 等 lateral/management ports，超過 `cross_env_lateral_threshold`。這是最高優先級的環境邊界破口。

## 6. 分析模組

| 模組 | 是否產生 Finding | 說明 |
|:---|:---|:---|
| Module 13 Enforcement Readiness | 不一定 | 以 policy coverage、ringfence、enforcement mode、staged coverage、remote access coverage 計算準備度 |
| Module 14 Infrastructure Scoring | 不一定 | 以圖分析找 critical asset、hub、bridge、tier |
| Module 15 Lateral Movement | 不一定 | 產生 graph attack views、pivot nodes、service summary |
| Draft Summary | 不一定 | 統計 draft policy decision subtype |
| Draft Actions | 不一定 | 提供 override deny / boundary remediation workflow |
| Enforcement Rollout | 不一定 | 排序適合優先進入 enforcement 的 app |
| Ringfence | 不一定 | 產生 app dependency profile 與 candidate allow rules |
| Change Impact | 不一定 | 比對前次 snapshot，指出 KPI 改善或惡化 |
| Exfiltration Intel | 不一定 | managed-to-unmanaged exfil 與 threat intel CSV join |

## 7. Threshold 設定

Threshold 位於 `config/report_config.yaml`。

| Key | 對應 | 預設用途 |
|:---|:---|:---|
| `min_policy_coverage_pct` | B005 | policy coverage 低於此值觸發 |
| `lateral_movement_outbound_dst` | B006 | lateral ports unique destination threshold |
| `user_destination_threshold` | B007 | 單一使用者 unique destination threshold |
| `unmanaged_connection_threshold` | B004 | unmanaged source connection threshold |
| `high_bytes_percentile` | B008 | bytes anomaly percentile |
| `high_bandwidth_percentile` | B008 | bandwidth anomaly percentile |
| `cross_env_connection_threshold` | B009 | cross-env flow volume threshold |
| `discovery_protocol_threshold` | L002 | discovery protocol flow threshold |
| `db_unique_src_app_threshold` | L003 | database source app count threshold |
| `identity_unique_src_threshold` | L005 | identity port source app count threshold |
| `blast_radius_threshold` | L006 | graph reachable app threshold |
| `unmanaged_critical_threshold` | L007 | unmanaged-to-critical flow threshold |
| `pb_lateral_threshold` | L008 | potentially_blocked lateral flow threshold |
| `exfil_bytes_threshold_mb` | L009 | exfil volume threshold |
| `cross_env_lateral_threshold` | L010 | cross-env lateral flow threshold |

## 8. 連接埠參考

### Critical ransomware / Windows management

| Port | Service |
|:---|:---|
| 135/tcp | RPC |
| 445/tcp | SMB |
| 3389/tcp/udp | RDP |
| 5985/tcp | WinRM |
| 5986/tcp | WinRM over HTTPS |

### High risk remote access / legacy

| Port | Service |
|:---|:---|
| 5938/tcp/udp | TeamViewer |
| 5900/tcp/udp | VNC |
| 137-139/tcp/udp | NetBIOS |

### Medium risk / discovery

| Port | Service |
|:---|:---|
| 22/tcp | SSH |
| 20-21/tcp/udp | FTP |
| 2049/tcp/udp | NFS |
| 5353/udp | mDNS |
| 5355/udp | LLMNR |
| 3702/udp | WSD |
| 1900/udp | SSDP |
| 23/tcp | Telnet |

### Database

| Port | Service |
|:---|:---|
| 1433/tcp | MSSQL |
| 3306/tcp | MySQL |
| 5432/tcp | PostgreSQL |
| 1521/tcp | Oracle |

### Identity

| Port | Service |
|:---|:---|
| 88/tcp/udp | Kerberos |
| 389/tcp/udp | LDAP |
| 636/tcp | LDAPS |
| 3268/tcp | Global Catalog |
| 3269/tcp | Global Catalog SSL |
| 464/tcp/udp | Kerberos password change |

## 9. 調整建議

- 先用預設 threshold 產生 baseline，再針對大型環境調高 fan-out 與 volume 閾值。
- 不要只依 severity 自動封鎖；先看 evidence 中的 top pairs、ports、apps。
- `potentially_blocked` 代表 enforcement gap，不代表現在已 blocked。
- Draft policy decision 相關 R 規則應在 provision 前 review，避免必要服務中斷。
- Unmanaged source 與 cross-env lateral ports 應優先處理。
