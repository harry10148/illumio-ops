# 安全規則參考手冊

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
<!-- END:doc-map -->

> **[English](Security_Rules_Reference.md)** | **[繁體中文](Security_Rules_Reference_zh.md)**

本文件說明 Illumio PCE Ops 流量報表引擎內建的所有安全偵測規則。每次產生流量報表時，規則引擎會自動執行評估，結果顯示於 HTML 報表的 **Security Findings（安全發現）** 章節。

---

## 概覽

規則分為三個系列：

| 系列 | 規則 | 焦點 |
|:---|:---|:---|
| **B 系列**（Baseline） | B001–B009 | 勒索軟體暴露、政策覆蓋缺口、行為異常 |
| **L 系列**（Lateral Movement） | L001–L010 | 攻擊者樞轉、憑證竊取、爆炸半徑路徑、資料外洩 |
| **R 系列**（Draft Policy Decision） | R01–R05 | 即時政策狀態與草稿（未 provision）規則之間的衝突 |

所有 B 系列與 L 系列的閾值均可在 **`config/report_config.yaml`** 的 `thresholds:` 區塊中設定。R 系列規則需要 `draft_policy_decision` 資料，當使用中的規則集包含 R 系列規則時，系統會自動啟用 `compute_draft`（詳見 [§ 設定](#設定)）。

---

## 嚴重度等級

| 等級 | 意義 | 建議回應時間 |
|:---|:---|:---|
| **CRITICAL** | 已確認或幾乎確定的活躍攻擊路徑 | 24 小時內修復 |
| **HIGH** | 重大暴露，可能導致橫向移動或資料外洩 | 1 週內修復 |
| **MEDIUM** | 政策缺口或提升的風險，應安排修復 | 排程修復 |
| **LOW** | 資訊性風險，被利用機率低 | 追蹤觀察 |
| **INFO** | 環境觀察，暫不需立即行動 | 定期審查 |

---

## Policy Decision 欄位

正確理解兩個 policy decision 欄位，是解讀安全規則結果的基礎。

### `policy_decision` — 歷史快照

由 VEN 在流量產生時當下記錄。**永遠只有三個值，無 sub-type。**

| 值 | 意義 |
|:---|:---|
| `allowed` | 有對應的 allow rule，流量被允許。 |
| `potentially_blocked` | **沒有任何 allow 或 deny rule** 覆蓋此流量。VEN 處於 visibility/test 模式，流量不受阻擋。當 workload 切換至 enforced（白名單）模式時，default-deny 才會阻擋。 |
| `blocked` | 流量被主動阻擋——可能是 selective/full-enforcement 模式下的 deny rule，或是 enforced 模式下無 allow rule 的 default-deny。 |

> **重要：** `potentially_blocked` **不代表「規則存在但未強制執行」**，而是代表根本**沒有任何對應規則**。將 PB 流量視為已受規則管轄是錯誤的。

### `draft_policy_decision` — 動態重算

在 async traffic query 完成後，透過 `PUT {job_href}/update_rules` 取得（Illumio Core 23.2.10+ 支援）。PCE 會對**所有**歷史流量紀錄重新套用目前 active（已 provision）和 draft 規則計算，因此此欄位永遠反映當前規則狀態，即使流量在規則建立前已存在。

| 值 | VEN 模式 | 條件 | 意義 |
|:---|:---|:---|:---|
| `allowed` | 任何 | Draft allow rule（未 provision） | 若 provision 此 allow rule，流量將被允許。 |
| `potentially_blocked` | 任何 | 無任何 active 或 draft rule | 完全未覆蓋，任何狀態的規則皆不存在。 |
| `potentially_blocked_by_boundary` | Visibility | Draft regular deny（未 provision） | Deny rule 存在於草稿；VEN 未強制執行，阻擋僅為潛在。 |
| `potentially_blocked_by_override_deny` | Visibility | Draft 或 active override deny | Override deny 存在；VEN 未強制執行，阻擋僅為潛在。 |
| `blocked_by_boundary` | Selective / Full | Regular deny（draft 或 active） | VEN 一旦 provision 即立即阻擋；或已在阻擋新流量。 |
| `blocked_by_override_deny` | Selective / Full | Override deny（draft 或 active） | 同上，但為 override deny，**不可被任何 allow rule 覆蓋**。 |
| `allowed_across_boundary` | 任何 | Active regular deny + allow rule 勝出 | Deny rule 存在，但 allow rule 優先；**絕不與 override deny 共存**。 |

### 核心行為規則

- **`policy_decision` 是凍結的歷史快照。** 規則變更後，舊流量的值不會改變。
- **`draft_policy_decision` 永遠動態重算。** 呼叫 `update_rules` 後，所有舊流量都套用當前規則重新評估。
- **`potentially_` 前綴代表 VEN 的強制執行模式。** 有前綴 = visibility/test 模式（阻擋僅為潛在）；無前綴 = selective/full enforcement（阻擋確定生效）。
- **`blocked_by_override_deny` vs `blocked_by_boundary`** — 兩者都表示 deny rule 將阻擋流量，但 override deny 無法被任何 allow rule 覆蓋。
- **Provision 後的過渡狀態：** Selective 模式下剛 provision deny rule 時，資料會混有舊流量（`pd=potentially_blocked`）和新流量（`pd=blocked`），但全部的 `draft_pd` 都是 `blocked_by_boundary`，因為 `update_rules` 用當前規則重算所有紀錄。

### 取得 `draft_policy_decision`

```
1. POST /api/v2/orgs/{org}/traffic_flows/async_queries   → job_href
2. Poll GET job_href until status == "completed"
3. PUT  job_href/update_rules                             → 202
4. Poll GET job_href until rules.status == "completed"
5. GET  job_href/download                                 → JSON with draft_policy_decision column
```

---

## 勒索軟體風險 Port 分級

`report_config.yaml` 定義了四個勒索軟體風險 port 分級，規則 B001、B002 及 B003 均使用這些分級。

| 分級 | Ports | 使用規則 |
|:---|:---|:---|
| **critical** | 135 (RPC)、445 (SMB)、3389 (RDP)、5985/5986 (WinRM) | B001 |
| **high** | 5938 (TeamViewer)、5900 (VNC)、137/138/139 (NetBIOS) | B002 |
| **medium** | 22 (SSH)、2049 (NFS)、20/21 (FTP)、5353 (mDNS)、5355 (LLMNR)、80 (HTTP)、3702 (WSD)、1900 (SSDP)、23 (Telnet) | B003 |
| **low** | 110 (POP3)、1723 (PPTP)、111 (SunRPC)、4444 (Metasploit) | 保留供未來規則使用 |

---

## B 系列 — 基準規則

### B001 · Ransomware Risk Port `CRITICAL / HIGH / MEDIUM / INFO`

**類別：** Ransomware

**偵測內容：**
掃描以下四個最關鍵的勒索軟體橫向傳播連接埠上，任何未被封鎖的流量，並根據網路鄰近性與流量政策進行**情境式嚴重度**判斷：

| 連接埠 | 協定 | 服務 |
|:---|:---|:---|
| 135 | TCP | Microsoft RPC（遠端程序呼叫） |
| 445 | TCP | SMB（Windows 檔案共享 / EternalBlue 攻擊向量） |
| 3389 | TCP/UDP | RDP（遠端桌面協定） |
| 5985 / 5986 | TCP | WinRM（Windows 遠端管理） |

**重要性：**
EternalBlue、NotPetya、WannaCry 及絕大多數現代勒索軟體都使用這些連接埠進行全網橫向傳播。然而，並非所有 RDP/SMB 流量都代表惡意活動——網域控制器、修補管理伺服器、跳板主機在同網段內合法使用這些連接埠是正常行為。需要上下文判斷才能評估真實風險。

**情境式嚴重度分級：**

| 嚴重度 | 觸發條件 |
|:---|:---|
| **CRITICAL** | 任何流量**跨越環境邊界**（例如 Dev→Prod、Test→Prod） |
| **HIGH** | 流量跨越 **/24 子網路邊界**，且為明確放行（非測試模式） |
| **MEDIUM** | 流量**位於同一 /24 子網路**內，或全部為 `potentially_blocked`（無 allow rule；VEN 在測試模式） |
| **INFO** | 所有流量均為同網段**且**全部為 `potentially_blocked`——尚未建立 allow rule；流量僅因 VEN 處於測試模式而通過 |

**觸發條件：**
連接埠 {135, 445, 3389, 5985, 5986} 上存在至少一筆 `policy_decision != 'blocked'` 的流量。

**閾值設定鍵：**（無閾值——有符合即觸發；嚴重度依上下文判斷）

**建議行動：**
- **CRITICAL**：立即建立環境邊界拒絕規則——跨環境 RPC/SMB/RDP 幾乎沒有合理理由
- **HIGH**：調查跨子網路流量，確認來源是否為授權跳板主機或管理系統
- **MEDIUM**：檢視測試模式工作負載，考慮切換至強制執行模式；確認同網段管理存取是否為預期行為
- **INFO**：可能為正常的同網段管理流量——驗證並記錄，考慮關閉以降低雜訊

---

### B002 · Ransomware Risk Port (High) `HIGH`

**類別：** Ransomware

**偵測內容：**
偵測以下次要遠端存取與持續控制連接埠上的放行流量：

| 連接埠 | 協定 | 服務 |
|:---|:---|:---|
| 5938 | TCP/UDP | TeamViewer |
| 5900 | TCP/UDP | VNC（虛擬網路運算） |
| 137 / 138 / 139 | UDP/TCP | NetBIOS 名稱服務 / 資料報 / 工作階段 |

**重要性：**
勒索軟體操作者及 APT 組織大量使用 TeamViewer、VNC 及 NetBIOS 進行持久化遠端控制及 C2 通訊。

**觸發條件：**
上述連接埠上存在至少一筆 `policy_decision = 'allowed'` 的流量。

**閾值設定鍵：**（無閾值——有符合即觸發）

**建議行動：**
- 將遠端存取工具的放行規則範圍縮小至已知來源 IP/範圍
- 在不需要舊版 Windows 相容性的環境中全面封鎖 NetBIOS
- 以 PAM（特權存取管理）解決方案取代 TeamViewer/VNC

---

### B003 · Ransomware Risk Port (Medium) — Test Mode `MEDIUM`

**類別：** Ransomware

**偵測內容：**
偵測中危連接埠上 `policy_decision = 'potentially_blocked'` 的流量，代表**該流量沒有對應的 allow rule**。VEN 處於測試/可見性模式所以流量通過；工作負載切換至強制執行模式後，預設拒絕（default-deny）白名單將自動封鎖此流量。

監控連接埠包括：SSH (22)、NFS (2049)、FTP (20/21)、mDNS (5353)、LLMNR (5355)、HTTP (80)、WSD (3702)、SSDP (1900)、Telnet (23)。

**重要性：**
`potentially_blocked` 代表**沒有任何規則（allow 或 deny）覆蓋此流量**，流量完全無政策保護。VEN 處於測試/可見性模式所以流量自由通過。這是「我們有微分段政策但仍遭入侵」的常見根因——工作負載從未切換到強制執行模式，預設拒絕白名單因此從未生效。

**觸發條件：**
中危連接埠上存在至少一筆 `policy_decision = 'potentially_blocked'` 的流量。

**閾值設定鍵：**（無閾值——有符合即觸發）

**建議行動：**
- 將工作負載從可見性/測試模式升級至選擇性或完整強制執行
- 優先處理有 SSH、FTP、HTTP 流量的工作負載

---

### B004 · Unmanaged Source High Activity `MEDIUM`

**類別：** UnmanagedHost

**偵測內容：**
統計來自 `src_managed = False`（未在 PCE 中登錄）主機的總流量數。

**重要性：**
未受管主機沒有 VEN 代理，因此沒有微分段強制執行能力，存在於零信任邊界之外，是無法被 Illumio 規則保護的盲點——無論其為影子 IT、外包商設備或攻擊者控制的主機。

**觸發條件：**
未受管來源流量總數超過 `unmanaged_connection_threshold`（預設：**50**）。

**閾值設定鍵：** `unmanaged_connection_threshold`

**建議行動：**
- 調查並識別每個未受管來源 IP
- 將合法主機加入 PCE，或套用明確拒絕規則
- 封鎖未受管來源存取任何敏感連接埠

---

### B005 · Low Policy Coverage `MEDIUM`

**類別：** Policy

**偵測內容：**
計算 `allowed_flows / total_flows x 100` 作為政策覆蓋率百分比，若低於閾值則觸發。

**重要性：**
低覆蓋率意味著大部分觀察到的流量未受控制（無明確規則）或被預設封鎖。無論哪種情況，分段政策均不完整，大量網路區段缺乏微分段保護。

**觸發條件：**
`coverage_pct < min_policy_coverage_pct`（預設：**30%**）。

**閾值設定鍵：** `min_policy_coverage_pct`

**建議行動：**
- 使用報表中的「未覆蓋流量（Uncovered Flows）」章節識別最高流量的未覆蓋路徑
- 優先為正式環境的應用層建立規則
- 使用 Illumio Rule Writing Wizard 依觀察到的流量自動生成規則

---

### B006 · High Lateral Movement (Fan-Out) `HIGH`

**類別：** LateralMovement

**偵測內容：**
依來源 IP 分組，計算每個來源在橫向移動連接埠上連接了多少個不同目的地 IP。橫向移動連接埠：RDP (3389)、VNC (5900)、SSH (22)、SMB (445)、WinRM (5985/5986)、TeamViewer (5938)、Telnet (23)。

**重要性：**
單一來源連接大量目的地是蠕蟲傳播、網路掃描或攻擊者系統性樞轉的典型特徵，也是 Mimikatz + PsExec、BloodHound 引導移動及勒索軟體自我傳播的標誌性模式。

**觸發條件：**
至少一個來源 IP 在橫向移動連接埠上連接超過 `lateral_movement_outbound_dst` 個不同目的地（預設：**10**）。

**閾值設定鍵：** `lateral_movement_outbound_dst`

**建議行動：**
- 立即隔離觸發的來源 IP 進行調查
- 透過 PCE 隔離（Quarantine）功能套用緊急隔離標籤
- 審查允許這些來源 IP 在橫向移動連接埠通訊的所有規則

---

### B007 · Single User High Destinations `HIGH`

**類別：** UserActivity

**偵測內容：**
針對含 `user_name` 欄位的流量，計算每個使用者連接的不同目的地 IP 數量，若任何使用者超過閾值則觸發。

**重要性：**
單一使用者帳號連接大量不同目的地是以下情形的警示：遭竊憑證被用於自動掃描、使用者進行未授權的資料整備，或服務帳號被劫持。

**觸發條件：**
任何使用者連接超過 `user_destination_threshold` 個不同目的地 IP（預設：**20**）。

**閾值設定鍵：** `user_destination_threshold`

**建議行動：**
- 在 PCE 事件日誌中審查觸發的使用者帳號
- 確認帳號是否從異常地點或時間使用
- 若懷疑遭入侵，立即重置憑證並啟用 MFA

---

### B008 · High Bandwidth Anomaly `MEDIUM`

**類別：** Bandwidth

**偵測內容：**
計算所有流量的第 `high_bytes_percentile` 百分位元組量，標記任何超過此閾值的流量。

**重要性：**
來自非預期來源的突發大量傳輸是資料整備（外洩前的資料收集）、大型未授權備份或應用程式設定錯誤產生過量流量的關鍵指標。

**觸發條件：**
任何流量的 `bytes_total` 超過資料集第 `high_bytes_percentile` 百分位（預設：**第 95 百分位**）。

**閾值設定鍵：** `high_bytes_percentile`

**建議行動：**
- 調查觸發的來源-目的地配對——是否合法？
- 確認傳輸時間是否與排程備份窗口一致
- 對非預期的大量傳輸來源套用出口頻寬控制或拒絕規則

---

### B009 · Cross-Environment Flow Volume `INFO`

**類別：** Policy

**偵測內容：**
統計 `src_env != dst_env` 的流量數（例如正式環境 → 開發環境、Staging → 正式環境），排除環境標籤為空的流量。

**重要性：**
環境邊界是巨型分段層（macro-segmentation）。過多跨環境流量可能代表攻擊者從低安全環境橫向移動至正式環境，或應用程式配置錯誤繞過環境隔離。

**觸發條件：**
跨環境流量總數超過 `cross_env_connection_threshold`（預設：**100**）。

**閾值設定鍵：** `cross_env_connection_threshold`

**建議行動：**
- 審查哪些應用程式配對產生跨環境流量
- 確認所有跨環境流量均有業務理由且已有文件記錄
- 為任何非預期的跨環境模式套用環境邊界拒絕規則

---

## L 系列 — 橫向移動規則

以下規則專注於**攻擊者入侵後的殺傷鏈**：橫向移動、特權提升、資料外洩及規避偵測。方法論源自真實世界攻擊模式分析及 Illumio MCP Server 安全分析框架。

---

### L001 · Cleartext Protocol in Use `HIGH / MEDIUM`

**類別：** LateralMovement

**偵測內容：**
偵測以下明文/舊式協定上的任何流量：

| 連接埠 | 服務 | 風險 |
|:---|:---|:---|
| 23 | Telnet | 憑證以明文傳送 |
| 20 / 21 | FTP | 憑證與資料以明文傳送 |

**重要性：**
任何具有網路存取的攻擊者都可執行 ARP 毒化或中間人（MITM）攻擊，直接從 Telnet/FTP 連線截取明文憑證，無需破解任何加密。這些憑證可立即用於任何密碼重複使用的系統進行橫向移動。

**觸發條件：**
連接埠 {23, 20, 21} 上存在任何流量。嚴重度為 **HIGH**（若有明確 `allowed` 流量）；若全部為封鎖或 potentially_blocked 則為 **MEDIUM**。

**閾值設定鍵：**（無閾值——有符合即觸發）

**建議行動：**
- 立即停用所有 Telnet 和 FTP 服務
- 以 SSH（連接埠 22）和 SFTP 取代
- 在 Illumio 中為所有環境套用連接埠 20、21 及 23 的拒絕規則

---

### L002 · Network Discovery Protocol Exposure `MEDIUM`

**類別：** LateralMovement

**偵測內容：**
偵測以下廣播/探索協定上未被封鎖的流量：

| 連接埠 | 協定 | 服務 |
|:---|:---|:---|
| 137 / 138 | UDP | NetBIOS 名稱服務 / 資料報 |
| 5353 | UDP | mDNS（多播 DNS） |
| 5355 | UDP | LLMNR（鏈路本地多播名稱解析） |
| 1900 | UDP | SSDP（UPnP） |
| 3702 | UDP | WSD（Web 服務探索） |

**重要性：**
**Responder** 和 **Inveigh** 等工具利用 LLMNR 和 NetBIOS 毒化攔截名稱解析請求，並以攻擊者控制的 IP 回應。受害機器隨即向攻擊者傳送 NTLM 認證，攻擊者捕獲 NTLMv2 雜湊值——整個過程無需任何使用者互動。這些雜湊可離線破解或直接中繼至其他系統。

**觸發條件：**
這些連接埠上的未封鎖流量超過 `discovery_protocol_threshold`（預設：**10**）。

**閾值設定鍵：** `discovery_protocol_threshold`

**建議行動：**
- 在 Illumio 政策層封鎖 NetBIOS (137/138)、LLMNR (5355) 和 SSDP (1900)
- 這些協定在現代微分段環境中沒有合法用途
- 啟用所有 Windows 工作負載的 SMB 簽章以防止雜湊中繼攻擊

---

### L003 · Database Port Wide Exposure `HIGH`

**類別：** LateralMovement

**偵測內容：**
檢查以下資料庫連接埠是否從超過 `db_unique_src_app_threshold` 個不同來源應用程式標籤，以 `policy_decision = 'allowed'` 方式存取：

| 連接埠 | 服務 |
|:---|:---|
| 1433 | Microsoft SQL Server |
| 3306 | MySQL / MariaDB |
| 5432 | PostgreSQL |
| 1521 | Oracle Database |
| 27017 | MongoDB |
| 6379 | Redis |
| 9200 | Elasticsearch |
| 5984 | CouchDB |
| 50000 | IBM DB2 |

**重要性：**
資料庫應只能由其直接應用程式層存取（通常 1-2 個應用程式標籤）。廣泛暴露代表攻擊者只要橫向移動至任一來源應用程式，就能直接查詢正式資料庫、透過 SQL 查詢外洩資料，或透過預存程序和 xp_cmdshell 進行特權提升。

**觸發條件：**
資料庫連接埠可從超過 `db_unique_src_app_threshold` 個唯一來源應用程式標籤存取（預設：**5**）。

**閾值設定鍵：** `db_unique_src_app_threshold`

**建議行動：**
- 建立明確列出可存取每個資料庫的應用程式標籤的 Illumio 規則集
- 所有其他來源對資料庫連接埠應套用預設拒絕
- 審查證據中列出的頂端來源應用程式，移除無業務理由的存取

---

### L004 · Cross-Environment Database Access `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測 `src_env != dst_env` 的放行資料庫流量（連接埠清單同 L003：1433、3306、5432、1521、27017、6379、9200、5984、50000）。

**重要性：**
環境邊界是保護正式環境免受開發與 Staging 環境影響的巨型分段層。開發應用程式直接存取正式資料庫繞過了所有環境層級控制，是攻擊者入侵低安全環境後直接存取正式資料的捷徑。

**觸發條件：**
任何跨越環境邊界的放行資料庫流量。

**閾值設定鍵：**（無閾值——任何跨環境資料庫流量即觸發）

**建議行動：**
- 開發或 Staging 環境中的應用程式絕不應直接存取正式資料庫
- 使用唯讀副本、API 閘道或資料管線作為跨環境介面
- 在環境邊界為所有資料庫連接埠套用 Illumio 拒絕規則

---

### L005 · Identity Infrastructure Wide Exposure `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測超過 `identity_unique_src_threshold` 個不同來源應用程式對身分識別基礎設施連接埠的非封鎖流量：

| 連接埠 | 服務 |
|:---|:---|
| 88 | Kerberos（驗證） |
| 389 | LDAP |
| 636 | LDAPS（TLS 加密 LDAP） |
| 3268 / 3269 | Active Directory 全域目錄 |
| 464 | Kerberos 密碼變更 |

**重要性：**
Active Directory 是整個 Windows 網域的主驗證機構。對這些連接埠的過度存取將啟用：
- **BloodHound** — 網域枚舉以發現通往 Domain Admin 的攻擊路徑
- **Kerberoasting** — 請求服務票證進行離線密碼破解
- **AS-REP Roasting** — 攻擊未啟用 Kerberos 預驗證的帳號
- **Golden Ticket / Silver Ticket** — 偽造 Kerberos 票證獲得持久網域存取權

**觸發條件：**
超過 `identity_unique_src_threshold` 個唯一來源應用程式對身分識別連接埠有非封鎖流量（預設：**3**）。

**閾值設定鍵：** `identity_unique_src_threshold`

**建議行動：**
- 將 Kerberos 和 LDAP 限制為僅網域加入的工作負載
- 應用程式應使用包裝 LDAP 呼叫的服務帳號，而非直接對廣泛應用層暴露原始 LDAP
- 封鎖所有非正式環境的工作負載存取 AD

---

### L006 · High Blast-Radius Lateral Path `HIGH`

**類別：** LateralMovement

**偵測內容：**
建立僅使用橫向移動連接埠上 `allowed` 流量的有向應用程式→應用程式通訊圖，從每個應用程式節點執行 BFS（廣度優先搜尋），計算每個節點可透過橫向連接埠連線鏈抵達多少個其他應用程式。

**重要性：**
這是 Illumio MCP Server **detect-lateral-movement-paths** 方法論的直接實作。BFS 可達性高的應用程式是攻擊者最具價值的目標：入侵它即可取得其整個可達子圖中所有應用程式的潛在存取權。這些節點是單次入侵爆炸半徑最大的位置。

**觸發條件：**
至少一個應用程式節點可透過橫向連接埠抵達 >= `blast_radius_threshold` 個其他應用程式（預設：**5**）。

**閾值設定鍵：** `blast_radius_threshold`

**建議行動：**
- 審查證據中列出的頂端樞轉應用程式，確認這些橫向連接埠連線是否必要
- 套用 Illumio intra-scope 規則限制各應用程式使用橫向連接埠的範圍
- 優先隔離可達性最高的應用程式——這是每條規則最大化風險降低效益的策略

---

### L007 · Unmanaged Host Accessing Critical Services `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測未受管主機（`src_managed = False`）在以下關鍵服務連接埠上的非封鎖流量：
- 資料庫連接埠（L003 清單：1433、3306、5432、1521、27017、6379、9200、5984、50000）
- 身分識別連接埠（L005 清單：88、389、636、3268、3269、464）
- Windows 管理連接埠：RPC (135)、SMB (445)、WinRM (5985/5986/47001)

**重要性：**
未受管主機沒有 VEN 強制執行，完全在零信任邊界之外。能存取資料庫、Active Directory 或 Windows 管理連接埠的未受管主機可能是：未申報的影子 IT、從未加入 PCE 的攻擊者控制主機，或完全繞過分段政策的外包商設備。

**觸發條件：**
未受管來源在關鍵連接埠上的非封鎖流量超過 `unmanaged_critical_threshold`（預設：**5**）。

**閾值設定鍵：** `unmanaged_critical_threshold`

**建議行動：**
- 識別每個未受管來源 IP——是否為已知資產？
- 立即將合法主機加入 PCE
- 為未受管→關鍵服務流量套用明確拒絕規則
- 對未知 IP，視為可能已遭入侵並展開調查

---

### L008 · Lateral Ports in Test Mode (PB) `HIGH`

**類別：** LateralMovement

**偵測內容：**
識別橫向移動連接埠、資料庫連接埠、身分識別連接埠及 Windows 管理連接埠上 `policy_decision = 'potentially_blocked'` 的流量。

**重要性：**
`potentially_blocked` 是 Illumio 部署中最嚴重的政策缺口：**這些流量沒有對應的 allow rule**，VEN 處於測試/可見性模式所以流量自由通過。切換至強制執行模式後，預設拒絕白名單會自動封鎖這些流量。強制執行啟用之前，這些都是存活中、完全未受保護的攻擊路徑。

**觸發條件：**
關鍵連接埠上的 potentially_blocked 流量超過 `pb_lateral_threshold`（預設：**10**）。

**閾值設定鍵：** `pb_lateral_threshold`

**建議行動：**
- 審查每筆 `potentially_blocked` 橫向連接埠流量——這些流量**沒有 allow rule**；強制執行前先確認哪些是合法流量
- 為任何合法的橫向連接埠路徑建立 allow rule（例如跳板機 SSH、管理 VLAN）
- 將工作負載從可見性/測試模式移至**選擇性**或**完整**強制執行——預設拒絕將自動封鎖所有未覆蓋流量
- 審查證據中的目的地應用程式，優先處理正式環境工作負載

---

### L009 · Data Exfiltration Pattern `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測受管工作負載（`src_managed = True`，`policy_decision = 'allowed'`）傳輸大量位元組至未受管（`dst_managed = False`）目的地 IP。

**重要性：**
這是**橫向移動後的外洩階段**：攻擊者已樞轉至高價值工作負載，正在將資料整備或傳輸至外部指揮控制（C2）伺服器或暫存主機。受管→未受管、高位元組量、已放行的模式是強烈信號——合法的對外流量應有明確範圍規則，而非任意流向未受管 IP。

**觸發條件：**
從受管工作負載傳輸至未受管目的地的總位元組量超過 `exfil_bytes_threshold_mb` MB（預設：**100 MB**）。

**閾值設定鍵：** `exfil_bytes_threshold_mb`

**建議行動：**
- 調查證據中列出的頂端目的地 IP——是已知 CDN/API 端點還是未知 IP？
- 實作出口白名單規則，將網際網路流量範圍限定在已知 IP 範圍
- 套用出口控制：正式環境工作負載對未受管 IP 的任何流量都應有明確業務理由

---

### L010 · Cross-Environment Lateral Port Access `CRITICAL`

**類別：** LateralMovement

**偵測內容：**
偵測橫向移動連接埠及 Windows 管理連接埠在**不同環境**（`src_env != dst_env`）之間的放行流量。

監控連接埠：SSH (22)、Telnet (23)、RPC (135)、SMB (445)、RDP (3389)、VNC (5900)、WinRM (5985/5986)、TeamViewer (5938)、WinRM alternate (47001)。

**重要性：**
評級為 **CRITICAL** 是因為這代表完整的巨型分段失效。環境邊界（正式/開發/Staging/DMZ）是最高層級的安全域。若橫向移動連接埠被允許跨越這些邊界，入侵低安全開發工作負載的攻擊者可直接以完全相同的橫向移動技術——PsExec、WMI、RDP——抵達正式環境系統，環境分段的全部目的蕩然無存。

**觸發條件：**
跨環境邊界的橫向/管理連接埠放行流量超過 `cross_env_lateral_threshold`（預設：**5**）。

**閾值設定鍵：** `cross_env_lateral_threshold`

**建議行動：**
- **立即**建立 Illumio 拒絕規則封鎖環境邊界上的橫向連接埠
- 這是 P1 修復措施，不應等候維護窗口
- 審查證據中的每個環境配對，確認是否有任何跨環境管理存取是刻意為之（例如跳板主機基礎設施）
- 若屬刻意行為，將放行規則範圍限定至特定授權來源 IP

---

## R 系列 — Draft Policy Decision 規則

這些規則評估**即時**（已 provision）政策狀態與**草稿**（未 provision）政策狀態之間的關係。它們需要流量資料集中的 `draft_policy_decision` 欄位，該欄位僅在 async traffic query 以 `compute_draft=True` 提交時才會填入（詳見 [§ 設定 — compute_draft 自動啟用](#compute_draft-auto-enable)）。

R 系列規則由與 B 系列和 L 系列相同的規則引擎執行。所有 finding 均出現在 HTML 報表 **Security Findings** 章節的 `DraftPolicy` 類別下。

> **PCE 版本需求：** `draft_policy_decision` 自 **Illumio Core 23.2.10+** 起可用。在舊版 PCE 上此欄位不存在，所有 R 系列規則將返回零個 finding（不會拋出錯誤）。

---

### R01 · Draft Deny Detected `HIGH`

目前由即時政策**放行**，但一旦 provision 草稿規則後將被**封鎖**的流量。

**觸發條件：** 一筆或多筆流量同時滿足 `policy_decision == "allowed"` 且 `draft_policy_decision` 為 `"blocked_by_boundary"` 或 `"blocked_by_override_deny"`。該規則以單一彙總 finding 涵蓋所有匹配流量。

**需要 draft PD：** 是

**嚴重度：** HIGH

**Finding 欄位結構：**
- `rule_id`: `R01`
- `rule_name`: 透過 i18n key `rule_r01_name` 本地化
- `severity`: `HIGH`
- `category`: `DraftPolicy`
- `description`: 透過 i18n key `rule_r01_desc` 本地化
- `recommendation`: "Review and provision the draft deny rules, or add explicit allow rules before provisioning to avoid unexpected traffic disruption."
- `evidence_matching_flows`: 整數——匹配流量數量
- `evidence_draft_decisions`: 字串——`draft_policy_decision` 值的 `value_counts()` 字典

**範例 finding：**

```
rule_id: R01
severity: HIGH
evidence_matching_flows: 47
evidence_draft_decisions: "{'blocked_by_boundary': 40, 'blocked_by_override_deny': 7}"
```

**建議補救：** 在 provision 任何新的拒絕規則之前，使用 `docs/User_Manual.md §9.11`（Draft Policy Decision 行為）執行預 provision 影響評估。為此 finding 中出現的所有合法流量新增明確放行規則，然後重新查詢以確認它們不再被匹配。

---

### R02 · Override Deny Detected `HIGH`

具有**草稿 override deny** 規則的流量。Override deny 規則擁有絕對優先權——無論規則順序或範圍如何，都無法被任何 allow rule 覆蓋。

**觸發條件：** 一筆或多筆流量的 `draft_policy_decision` 以 `"_override_deny"` 結尾（即 `"blocked_by_override_deny"` 或 `"potentially_blocked_by_override_deny"`）。以單一彙總 finding 觸發。

**需要 draft PD：** 是

**嚴重度：** HIGH

**Finding 欄位結構：**
- `rule_id`: `R02`
- `rule_name`: 透過 i18n key `rule_r02_name` 本地化
- `severity`: `HIGH`
- `category`: `DraftPolicy`
- `description`: 透過 i18n key `rule_r02_desc` 本地化
- `recommendation`: "Override deny rules take precedence over all allow rules. Verify each override deny is intentional before provisioning."
- `evidence_matching_flows`: 整數——匹配流量數量
- `evidence_draft_decisions`: 字串——`draft_policy_decision` 值的 `value_counts()` 字典

**範例 finding：**

```
rule_id: R02
severity: HIGH
evidence_matching_flows: 3
evidence_draft_decisions: "{'blocked_by_override_deny': 3}"
```

**建議補救：** 在 PCE 控制台中找出每條草稿 override deny 規則集。確認每條規則均為刻意設置且範圍正確。Override deny 規則應極為少見且精確定向——一旦 provision 後即無法以任何 allow rule 恢復流量（操作上不可逆）。詳見 `docs/User_Manual.md §9.10` 的 override deny 規則管理說明。

---

### R03 · Visibility Boundary Breach `MEDIUM`

VEN 處於**可見性/測試模式**（流量今日不受限制）但**草稿拒絕邊界**規則已存在的流量。一旦工作負載切換至強制執行模式，邊界拒絕將啟動並封鎖此流量。

**觸發條件：** 一筆或多筆流量同時滿足 `policy_decision == "potentially_blocked"` 且 `draft_policy_decision == "potentially_blocked_by_boundary"`。兩個值均有 `potentially_` 前綴確認 VEN 尚未強制執行。

**需要 draft PD：** 是

**嚴重度：** MEDIUM

**Finding 欄位結構：**
- `rule_id`: `R03`
- `rule_name`: 透過 i18n key `rule_r03_name` 本地化
- `severity`: `MEDIUM`
- `category`: `DraftPolicy`
- `description`: 透過 i18n key `rule_r03_desc` 本地化
- `recommendation`: "Move workloads to enforced mode to activate the boundary deny. Flows are currently traversable only because VENs are in test/visibility mode."
- `evidence_matching_flows`: 整數——匹配流量數量

**範例 finding：**

```
rule_id: R03
severity: MEDIUM
evidence_matching_flows: 12
```

**建議補救：** 這是強制執行前的缺口。在將工作負載切換至強制執行模式之前，確認這些路徑上的所有合法流量均已有明確放行規則。詳見 `docs/User_Manual.md §9.11` 的建議強制執行準備度檢查清單。

---

### R04 · Allowed Across Boundary `LOW`

**allow rule 明確覆蓋草稿一般拒絕邊界**的流量。草稿拒絕規則存在，但 allow rule 優先——流量跨邊界被允許。

**觸發條件：** 一筆或多筆流量的 `draft_policy_decision == "allowed_across_boundary"`。請注意，此值在 override deny 存在時絕不會出現——它僅適用於一般（非 override）拒絕邊界。

**需要 draft PD：** 是

**嚴重度：** LOW

**Finding 欄位結構：**
- `rule_id`: `R04`
- `rule_name`: 透過 i18n key `rule_r04_name` 本地化
- `severity`: `LOW`
- `category`: `DraftPolicy`
- `description`: 透過 i18n key `rule_r04_desc` 本地化
- `recommendation`: "Confirm that cross-boundary allow rules are intentional and tightly scoped. Consider whether a more restrictive rule can meet the business requirement."
- `evidence_matching_flows`: 整數——匹配流量數量

**範例 finding：**

```
rule_id: R04
severity: LOW
evidence_matching_flows: 8
```

**建議補救：** 在 PCE 控制台中審查每條跨邊界放行規則。確認來源和目的地的範圍盡可能縮小。若業務需求已不存在，移除該放行規則。LOW 嚴重度表示這是設計上的刻意行為，但需定期審查。

---

### R05 · Draft-Reported Mismatch `INFO`

工作負載配對的彙總清單，其中**已報告決策**（`policy_decision`）為 `"allowed"`，但**草稿決策**（`draft_policy_decision`）顯示為封鎖。這是一個超集視圖——無論適用哪種具體封鎖類型，它都能捕獲所有放行但草稿封鎖的配對，是 R01 精準 finding 的補充。

**觸發條件：** 一筆或多筆流量同時滿足 `policy_decision == "allowed"` 且 `draft_policy_decision` 以 `"blocked_"` 開頭。前 20 個來源-目的地配對被捕獲於證據中（依可用的 `src`/`src_ip` 和 `dst`/`dst_ip` 欄位）。

**需要 draft PD：** 是

**嚴重度：** INFO

**Finding 欄位結構：**
- `rule_id`: `R05`
- `rule_name`: 透過 i18n key `rule_r05_name` 本地化
- `severity`: `INFO`
- `category`: `DraftPolicy`
- `description`: 透過 i18n key `rule_r05_desc` 本地化
- `recommendation`: "Review these workload pairs before provisioning draft rules. Currently-allowed traffic will be blocked once the draft is provisioned."
- `evidence_mismatch_count`: 整數——不符合流量的總數
- `evidence_top_pairs`: 字串——最多 20 個 `{src, dst}` 字典的 JSON 序列化清單

**範例 finding：**

```
rule_id: R05
severity: INFO
evidence_mismatch_count: 23
evidence_top_pairs: "[{'src': '10.0.1.5', 'dst': '10.0.2.8'}, ...]"
```

**建議補救：** 將此清單作為預 provision 檢查清單使用。在 provision 草稿規則之前，對照您核准的變更請求逐一核對每個配對。INFO 嚴重度表示不需要立即行動，但應審查並確認此清單。詳見 `docs/User_Manual.md §9.11`。

---

## Analysis Modules (Non-Rule)

除 B 系列和 L 系列安全規則外，流量報表包含三個提供評分與風險評估的分析模組。這些模組**不**在規則引擎中產生 `Finding` 物件，而是在 HTML 報表中以獨立章節呈現。

### Module 13 · Enforcement Readiness Score

計算涵蓋五個加權因素的 0-100 強制執行準備度評分：

| 因素 | 權重 | 說明 |
|:---|:---|:---|
| Policy Coverage | 35 | 具有 `policy_decision = 'allowed'` 的流量百分比 |
| Ringfence Maturity | 20 | 來源與目的地具有相同應用程式標籤的應用程式對應用程式流量百分比 |
| Enforcement Mode | 20 | 受管工作負載處於 `enforced` 模式的百分比 |
| Staged Readiness | 15 | 懲罰 `potentially_blocked` 流量——無 allow rule 的未覆蓋流量；工作負載切換至強制執行後由 default-deny 封鎖 |
| Remote App Coverage | 10 | 遠端存取連接埠流量（SSH、RDP、VNC、TeamViewer）中為 `allowed` 的百分比 |

輸出字母評等（A-F）及優先補救建議。

### Module 14 · Infrastructure Scoring

使用有向應用程式對應用程式通訊分析進行圖形式應用程式關鍵性評分：

- **In-degree**：依賴此應用程式的唯一應用程式數量（提供者關鍵性）
- **Out-degree**：此應用程式通訊的唯一應用程式數量（消費者爆炸半徑）
- **Infra Score**：加權組合（60% 提供者、40% 消費者）
- **角色分類**：Hub（高入度+高出度）、Provider、Consumer、Peer

識別最高價值的分段優先化目標。

### Module 15 · Lateral Movement Risk Detection

提供專屬橫向移動分析模組：

- **橫向連接埠暴露摘要**：依服務與政策決策分類的已知橫向移動連接埠流量
- **扇出偵測**：在橫向連接埠上連接大量目的地的來源（閾值：5+ 個唯一目的地）
- **應用程式層級鏈結偵測**：在放行的橫向連接埠連接上進行最多 3 跳的 BFS 可達性分析
- **中繼代理偵測**：在橫向連接埠上同時具有高入度和高出度的 IP 節點（關鍵節點）
- **每來源風險評分**：基於連接量、目的地分散度、連接埠多樣性和封鎖流量比率的 0-100 風險評分

此模組監控的橫向連接埠：SMB (445)、RPC (135)、NetBIOS (139)、RDP (3389)、SSH (22)、WinRM (5985/5986)、Telnet (23)、NFS (2049)、RPC Portmapper (111)、LDAP (389)、LDAPS (636)、Kerberos (88)、MSSQL (1433)、MySQL (3306)、PostgreSQL (5432)。

---

## 閾值設定參考

所有閾值均在 `config/report_config.yaml` 的 `thresholds:` 區塊中設定。

```yaml
thresholds:
  # -- B-series ----------------------------------------------------------
  min_policy_coverage_pct: 30         # B005: trigger if coverage % below this
  lateral_movement_outbound_dst: 10   # B006: trigger if src contacts > N unique dst
  user_destination_threshold: 20      # B007: trigger if user reaches > N unique dst
  unmanaged_connection_threshold: 50  # B004: trigger if unmanaged src flows > N
  high_bytes_percentile: 95           # B008: anomaly if bytes > Nth percentile
  high_bandwidth_percentile: 95       # bandwidth spike percentile (Module 11)
  cross_env_connection_threshold: 100 # B009: trigger if cross-env flows > N

  # -- L-series ----------------------------------------------------------
  discovery_protocol_threshold: 10    # L002: min unblocked discovery flows to trigger
  db_unique_src_app_threshold: 5      # L003: alert if db reachable from > N source apps
  identity_unique_src_threshold: 3    # L005: alert if LDAP/Kerberos from > N source apps
  blast_radius_threshold: 5           # L006: alert if app reaches > N apps via lateral ports
  unmanaged_critical_threshold: 5     # L007: min unmanaged-to-critical-port flows
  pb_lateral_threshold: 10            # L008: min PB flows on lateral ports to alert
  exfil_bytes_threshold_mb: 100       # L009: trigger if managed->unmanaged bytes > N MB
  cross_env_lateral_threshold: 5      # L010: min cross-env lateral flows to alert
```

### 調整建議

- **高誤報環境**（例如扁平開發網路、跨應用流量多）：將 L003 `db_unique_src_app_threshold` 提高至 10-15，L005 `identity_unique_src_threshold` 提高至 8-10。
- **成熟分段環境**（大多數工作負載已強制執行）：將 B005 `min_policy_coverage_pct` 降至 80，僅在成熟環境退化時觸發。
- **大量資料傳輸工作負載**（備份伺服器、ETL）：將 `high_bytes_percentile` 提高至 99 或將 `exfil_bytes_threshold_mb` 提高至 500-1000。
- **嚴格零容忍環境**：將 `cross_env_lateral_threshold` 設為 1，任何跨環境橫向連接埠流量立即觸發。

---

## Port Reference

安全規則與分析模組所參照的所有連接埠號碼：

| 連接埠 | 服務 | 參照規則 / 模組 |
|:---|:---|:---|
| 20, 21 | FTP | B003, L001 |
| 22 | SSH | B003, B006, L010, Mod15 |
| 23 | Telnet | B003, B006, L001, L010, Mod15 |
| 80 | HTTP | B003 |
| 88 | Kerberos | L005, L007, L008, Mod15 |
| 110 | POP3 | config: low tier |
| 111 | SunRPC | config: low tier, Mod15 |
| 135 | RPC / DCOM | B001, L007, L008, L010, Mod15 |
| 137, 138 | NetBIOS NS/DGM | B002, L002 |
| 139 | NetBIOS Session | B002, Mod15 |
| 389 | LDAP | L005, L007, L008, Mod15 |
| 445 | SMB | B001, B006, L007, L008, L010, Mod15 |
| 464 | Kerberos Password | L005, L007, L008 |
| 636 | LDAPS | L005, L007, L008, Mod15 |
| 1433 | MSSQL | L003, L004, L007, L008, Mod15 |
| 1521 | Oracle | L003, L004, L007, L008 |
| 1723 | PPTP | config: low tier |
| 1900 | SSDP | B003, L002 |
| 2049 | NFS | B003, Mod15 |
| 3268, 3269 | AD Global Catalog | L005, L007, L008 |
| 3306 | MySQL | L003, L004, L007, L008, Mod15 |
| 3389 | RDP | B001, B006, L010, Mod15 |
| 3702 | WSD | B003, L002 |
| 4444 | Metasploit | config: low tier |
| 5353 | mDNS | B003, L002 |
| 5355 | LLMNR | B003, L002 |
| 5432 | PostgreSQL | L003, L004, L007, L008, Mod15 |
| 5900 | VNC | B002, B006, L010 |
| 5938 | TeamViewer | B002, B006, L010 |
| 5984 | CouchDB | L003, L004, L007, L008 |
| 5985, 5986 | WinRM | B001, B006, L007, L008, L010 |
| 6379 | Redis | L003, L004, L007, L008 |
| 9200 | Elasticsearch | L003, L004, L007, L008 |
| 27017 | MongoDB | L003, L004, L007, L008 |
| 47001 | WinRM alternate | L007, L008, L010 |
| 50000 | IBM DB2 | L003, L004, L007, L008 |

---

## 設定

### compute_draft 自動啟用 {#compute_draft-auto-enable}

> **背景——Policy lifecycle：** `compute_draft` 揭露 Illumio policy lifecycle 的 **Draft** 狀態——已撰寫但尚未 provision 至 Active 的規則。理解 Draft → Pending → Active 序列是解讀 `draft_policy_decision` 值的前提。詳見 [docs/Architecture.md — Background.4 Policy lifecycle](Architecture.md#background4-policy-lifecycle)。

流量資料集中的 `draft_policy_decision` 欄位填充成本較高：它需要 analyzer 在 async query 完成後發出 `PUT {job_href}/update_rules` 呼叫，該呼叫會對所有歷史流量紀錄重新套用 active 和 draft 規則進行評估（詳見 [§ 取得 `draft_policy_decision`](#取得-draft_policy_decision)）。

預設情況下，`compute_draft` 為**關閉**——除非操作者明確選擇啟用，否則 analyzer 不會請求草稿政策資料。但是，當使用中的規則集包含**任何** `needs_draft_pd()` 方法返回 `True` 的規則（所有 R01–R05 規則均符合），analyzer 將自動強制啟用 `compute_draft=True`，即使操作者未傳入此旗標。

**自動升級邏輯（取自 `src/analyzer.py`）：**

```python
needs_draft = (
    bool(draft_pd_filter)                              # operator passed a draft PD filter
    or getattr(query_spec, "requires_draft_pd", False) # ruleset annotation
    or bool(params.get("requires_draft_pd", False))    # explicit query param
)
```

`src/report/rules_engine.py` 中的 `ruleset_needs_draft_pd()` 函式會迭代使用中的規則集，並對每個規則實例呼叫 `needs_draft_pd()`。若任何規則返回 `True`，結果將傳播至 analyzer。

**實際效果：**

| 規則集包含 R 系列規則？ | `compute_draft` 參數 | 實際行為 |
|:---|:---|:---|
| 否 | False（預設） | 不請求草稿資料；R 系列規則返回 0 個 finding |
| 否 | True（操作者選擇啟用） | 請求草稿資料；R 系列規則正常評估 |
| 是 | False（預設） | **自動升級為 True**——自動請求草稿資料 |
| 是 | True | 請求草稿資料（無變化） |

**當 `compute_draft` 被強制啟用時，系統會**在 INFO 等級發出日誌條目，使用 i18n key `rs_engine_needs_draft_pd`（「Rule requires draft_policy_decision; compute_draft forced on.」）。操作者可在應用程式日誌中觀察此訊息以確認升級已發生。

**測試覆蓋：** `tests/test_phase34_attack_summaries.py` — `test_policy_usage_html_renders_draft_pd_section` 測試驗證當 `mod05` 草稿衝突資料存在時，HTML 報表中的 Draft Policy 章節可正確渲染。

**交叉參照：**
- `docs/User_Manual.md §9.11` — Draft Policy Decision 行為（終端使用者操作指南）
- `docs/Architecture.md §1.4` — Policy lifecycle：已 provision vs. draft 狀態（Phase C 新增）

## 延伸閱讀

- [User Manual](./User_Manual.md) §9 Reports — 規則 finding 如何呈現於報表
- [Architecture](./Architecture.md) Background.4 — Policy lifecycle 背景
- [README](../README.md) — 專案入口與快速上手
