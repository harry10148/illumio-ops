# 安全規則參考手冊

> **[English](Security_Rules_Reference.md)** | **[繁體中文](Security_Rules_Reference_zh.md)**

本文件說明 Illumio PCE Ops 流量報表引擎內建的所有安全偵測規則。每次產生流量報表時，規則引擎會自動執行評估，結果顯示於 HTML 報表的 **Security Findings（安全發現）** 章節。

---

## 概覽

規則分為兩個系列：

| 系列 | 規則 | 焦點 |
|:---|:---|:---|
| **B 系列**（基礎） | B001–B009 | 勒索軟體暴露、政策覆蓋缺口、行為異常 |
| **L 系列**（橫向移動） | L001–L010 | 攻擊者樞轉、憑證竊取、爆炸半徑路徑、資料外洩 |

此外，三個進階分析模組（Module 13–15）提供強制執行準備度評分、基礎設施關鍵性評分和橫向移動風險偵測，作為安全發現的補充分析。詳見[進階分析模組](#進階分析模組module-1315)章節。

所有閾值均可在 **`config/report_config.yaml`** 的 `thresholds:` 區塊中設定，無需修改程式碼。

---

## 嚴重性等級

| 等級 | 意義 | 建議回應時間 |
|:---|:---|:---|
| **CRITICAL** | 已確認或幾乎確定的活躍攻擊路徑 | 24 小時內修復 |
| **HIGH** | 重大暴露，可能導致橫向移動或資料外洩 | 1 週內修復 |
| **MEDIUM** | 政策缺口或提升的風險，應安排修復 | 排程修復 |
| **LOW** | 資訊性風險，被利用機率低 | 追蹤觀察 |
| **INFO** | 環境觀察，暫不需立即行動 | 定期審查 |

---

## B 系列 — 基礎規則

### B001 · 勒索軟體高危連接埠 `CRITICAL / HIGH / MEDIUM / INFO`

**類別：** Ransomware（勒索軟體）

**偵測內容：**
掃描以下四個最關鍵的勒索軟體橫向傳播連接埠上，任何未被封鎖的流量，並根據**網路鄰近性與政策上下文**進行情境式嚴重等級判斷：

| 連接埠 | 協定 | 服務 |
|:---|:---|:---|
| 135 | TCP | Microsoft RPC（遠端程序呼叫） |
| 445 | TCP | SMB（Windows 檔案共享 / EternalBlue 攻擊向量） |
| 3389 | TCP/UDP | RDP（遠端桌面協定） |
| 5985 / 5986 | TCP | WinRM（Windows 遠端管理） |

**重要性：**
EternalBlue、NotPetya、WannaCry 及絕大多數現代勒索軟體都使用這些連接埠進行全網橫向傳播。然而，並非所有 RDP/SMB 流量都代表惡意活動——網域控制器、修補管理伺服器、跳板主機在同網段內合法使用這些連接埠是正常行為。需要上下文判斷才能評估真實風險。

**情境式嚴重等級：**

| 嚴重等級 | 觸發條件 |
|:---|:---|
| **CRITICAL** | 任何流量**跨越環境邊界**（例如開發→生產、測試→生產） |
| **HIGH** | 流量跨越 **/24 子網路邊界**，且為明確放行（非測試模式） |
| **MEDIUM** | 流量**位於同一 /24 子網路**內，或僅存在於測試/可見性模式（未強制執行） |
| **INFO** | 所有流量均為同網段**且**全部為測試模式——可能是正常的管理員流量 |

**觸發條件：**
連接埠 {135, 445, 3389, 5985, 5986} 上存在 `policy_decision != 'blocked'` 的流量。

**閾值設定鍵：**（無閾值，有符合即觸發；嚴重等級依上下文判斷）

**建議行動：**
- **CRITICAL**：立即建立環境邊界拒絕規則——跨環境 RPC/SMB/RDP 幾乎沒有合理理由
- **HIGH**：調查跨子網路流量，確認來源是否為授權跳板主機或管理系統
- **MEDIUM**：檢視測試模式工作負載，考慮切換至強制執行模式；確認同網段管理存取是否為預期行為
- **INFO**：可能為正常的同網段管理流量——驗證並記錄，考慮關閉以降低雜訊

---

### B002 · 勒索軟體高危連接埠（高危級） `HIGH`

**類別：** Ransomware

**偵測內容：**
偵測以下次要遠端存取與持續控制連接埠上的放行流量：

| 連接埠 | 協定 | 服務 |
|:---|:---|:---|
| 5938 | TCP/UDP | TeamViewer |
| 5900 | TCP/UDP | VNC（虛擬網路運算） |
| 137 / 138 / 139 | UDP/TCP | NetBIOS 名稱服務 / 資料報 |

**重要性：**
勒索軟體操作者及 APT 組織大量使用 TeamViewer、VNC 及 NetBIOS 進行持久化遠端控制及 C2 通訊。

**觸發條件：**
上述連接埠上存在至少一個 `policy_decision = 'allowed'` 的流量。

**閾值設定鍵：**（無閾值，有符合即觸發）

**建議行動：**
- 將遠端存取工具的放行規則範圍縮小至已知來源 IP/範圍
- 在不需要舊版 Windows 相容性的環境中全面封鎖 NetBIOS
- 以 PAM（特權存取管理）解決方案取代 TeamViewer/VNC

---

### B003 · 勒索軟體中危連接埠（測試模式，未強制執行） `MEDIUM`

**類別：** Ransomware

**偵測內容：**
偵測中危連接埠上 `policy_decision = 'potentially_blocked'` 的流量，代表**該流量沒有對應的 Allow 規則**。VEN 處於測試/可見性模式所以流量通過；工作負載切換至強制執行模式後，預設拒絕（default-deny）白名單將自動封鎖此流量。

監控連接埠包括：SSH (22)、NFS (2049)、FTP (20/21)、mDNS (5353)、LLMNR (5355)、HTTP (80)、WSD (3702)、SSDP (1900)、Telnet (23)。

**重要性：**
`potentially_blocked` 代表**沒有任何規則（allow 或 deny）覆蓋此流量**，流量完全無政策保護。VEN 處於測試/可見性模式所以流量自由通過。這是「我們有微分段政策但仍遭入侵」的常見根因——工作負載從未切換到強制執行模式，預設拒絕白名單因此從未生效。

**觸發條件：**
中危連接埠上存在至少一個 `potentially_blocked` 流量。

**閾值設定鍵：**（無閾值，有符合即觸發）

**建議行動：**
- 將工作負載從可見性/測試模式升級至選擇性或完整強制執行
- 優先處理有 SSH、FTP、HTTP 流量的工作負載

---

### B004 · 未受管來源高活動量 `MEDIUM`

**類別：** UnmanagedHost（未受管主機）

**偵測內容：**
統計來自 `src_managed = False`（未在 PCE 中登錄）主機的總流量數。

**重要性：**
未受管主機沒有 VEN 代理，因此沒有微分段強制執行能力，存在於零信任邊界之外，是無法被 Illumio 規則保護的盲點。

**觸發條件：**
未受管來源流量總數超過 `unmanaged_connection_threshold`（預設：**50**）。

**閾值設定鍵：** `unmanaged_connection_threshold`

**建議行動：**
- 調查並識別每個未受管來源 IP
- 將合法主機加入 PCE，或套用明確拒絕規則
- 封鎖未受管來源存取任何敏感連接埠

---

### B005 · 政策覆蓋率偏低 `MEDIUM`

**類別：** Policy（政策）

**偵測內容：**
計算 `allowed_flows / total_flows × 100` 作為政策覆蓋率百分比，若低於閾值則觸發。

**重要性：**
低覆蓋率意味著大部分流量沒有明確規則管理，分段政策不完整，大量網路節點缺乏微分段保護。

**觸發條件：**
`coverage_pct < min_policy_coverage_pct`（預設：**30%**）。

**閾值設定鍵：** `min_policy_coverage_pct`

**建議行動：**
- 使用報表中的「未覆蓋流量」章節識別最高流量的未覆蓋路徑
- 優先為正式環境的應用層建立規則
- 使用 Illumio Rule Writing Wizard 依觀察到的流量自動生成規則

---

### B006 · 高橫向移動活動（扇出偵測） `HIGH`

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

### B007 · 單一使用者連接大量目的地 `HIGH`

**類別：** UserActivity

**偵測內容：**
針對含 `user_name` 欄位的流量，計算每個使用者連接的不同目的地 IP 數量。

**重要性：**
單一帳號連接大量目的地可能代表：憑證遭竊並用於自動掃描、使用者進行未授權的資料整備，或服務帳號被劫持。

**觸發條件：**
任何使用者連接超過 `user_destination_threshold` 個不同目的地 IP（預設：**20**）。

**閾值設定鍵：** `user_destination_threshold`

**建議行動：**
- 在 PCE 事件日誌中審查觸發的使用者帳號
- 確認帳號是否從異常地點或時間使用
- 若懷疑遭入侵，立即重置憑證並啟用 MFA

---

### B008 · 高頻寬異常 `MEDIUM`

**類別：** Bandwidth

**偵測內容：**
計算所有流量的第 `high_bytes_percentile` 百分位元組量，標記超過此閾值的流量。

**重要性：**
來自非預期來源的突發大量傳輸是資料整備（外洩前的資料收集）、大型未授權備份或應用程式設定錯誤的關鍵指標。

**觸發條件：**
任何流量的 `bytes_total` 超過資料集第 `high_bytes_percentile` 百分位（預設：**第 95 百分位**）。

**閾值設定鍵：** `high_bytes_percentile`

**建議行動：**
- 調查觸發的來源-目的地配對，確認是否合法
- 確認傳輸時間是否與排程備份窗口一致
- 對非預期的大量傳輸來源套用出口頻寬控制或拒絕規則

---

### B009 · 跨環境流量過多 `INFO`

**類別：** Policy

**偵測內容：**
統計 `src_env != dst_env` 的流量數（例如正式環境 → 開發環境），排除環境標籤為空的流量。

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

### L001 · 明文協定使用中 `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測以下明文/舊式協定上的任何流量：

| 連接埠 | 服務 | 風險 |
|:---|:---|:---|
| 23 | Telnet | 憑證以明文傳送 |
| 20 / 21 | FTP | 憑證與資料以明文傳送 |

**重要性：**
任何具有網路存取的攻擊者都可執行 ARP 毒化或中間人攻擊，直接從 Telnet/FTP 連線截取明文憑證，無需破解任何加密。這些憑證可立即用於任何密碼重複使用的系統進行橫向移動。

**觸發條件：**
連接埠 {23, 20, 21} 上存在任何流量；若有明確放行流量則升為 HIGH。

**閾值設定鍵：**（無閾值，有符合即觸發）

**建議行動：**
- 立即停用所有 Telnet 和 FTP 服務
- 以 SSH（22）和 SFTP 取代
- 在 Illumio 中為所有環境套用連接埠 20、21、23 的拒絕規則

---

### L002 · 網路探索協定暴露 `MEDIUM`

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

### L003 · 資料庫連接埠廣泛暴露 `HIGH`

**類別：** LateralMovement

**偵測內容：**
檢查以下資料庫連接埠是否從超過 `db_unique_src_app_threshold` 個不同來源應用程式標籤可存取（`policy_decision = 'allowed'`）：

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

### L004 · 跨環境資料庫存取 `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測 `src_env != dst_env` 的放行資料庫流量（連接埠清單同 L003）。

**重要性：**
環境邊界是保護正式環境免受開發/測試環境影響的巨型分段層。開發應用程式直接存取正式資料庫繞過了所有環境層級控制，是攻擊者入侵低安全環境後直接存取正式資料的捷徑。

**觸發條件：**
任何放行的資料庫流量跨越環境邊界。

**閾值設定鍵：**（無閾值，任何跨環境資料庫流量即觸發）

**建議行動：**
- 開發或測試環境中的應用程式絕不應直接存取正式資料庫
- 使用唯讀副本、API 閘道或資料管線作為跨環境介面
- 在環境邊界為所有資料庫連接埠套用 Illumio 拒絕規則

---

### L005 · 身分識別基礎設施廣泛暴露 `HIGH`

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
Active Directory 是整個 Windows 網域的主驗證機構。過度存取這些連接埠將啟用：
- **BloodHound** — 網域枚舉以發現通往 Domain Admin 的攻擊路徑
- **Kerberoasting** — 請求服務票證進行離線密碼破解
- **AS-REP Roasting** — 攻擊未啟用 Kerberos 預驗證的帳號
- **黃金票證 / 銀色票證** — 偽造 Kerberos 票證獲得持久網域存取權

**觸發條件：**
超過 `identity_unique_src_threshold` 個唯一來源應用程式對身分識別連接埠有非封鎖流量（預設：**3**）。

**閾值設定鍵：** `identity_unique_src_threshold`

**建議行動：**
- 將 Kerberos 和 LDAP 限制為僅網域加入的工作負載
- 應用程式應使用包裝 LDAP 呼叫的服務帳號，而非直接對廣泛應用層暴露原始 LDAP
- 封鎖所有非正式環境的工作負載存取 AD

---

### L006 · 高爆炸半徑橫向移動路徑 `HIGH`

**類別：** LateralMovement

**偵測內容：**
建立僅使用橫向移動連接埠上 `allowed` 流量的有向應用程式→應用程式通訊圖，從每個應用程式節點執行 BFS（廣度優先搜尋），計算每個節點可透過橫向連接埠連線鏈抵達多少個其他應用程式。

**重要性：**
這是 Illumio MCP Server **detect-lateral-movement-paths** 方法論的直接實作。BFS 可達性高的應用程式是攻擊者最具價值的目標：入侵它即可取得其所有下游應用程式的潛在存取權。這些節點是單次入侵爆炸半徑最大的位置。

**觸發條件：**
至少一個應用程式節點可透過橫向連接埠抵達 ≥ `blast_radius_threshold` 個其他應用程式（預設：**5**）。

**閾值設定鍵：** `blast_radius_threshold`

**建議行動：**
- 審查證據中列出的頂端樞轉應用程式，確認這些橫向連接埠連線是否必要
- 套用 Illumio 規則集限制各應用程式使用橫向連接埠的範圍
- 優先隔離可達性最高的應用程式，這是每條規則最大化風險降低效益的策略

---

### L007 · 未受管主機存取關鍵服務 `HIGH`

**類別：** LateralMovement

**偵測內容：**
偵測未受管主機（`src_managed = False`）在以下關鍵服務連接埠上的非封鎖流量：
- 資料庫連接埠（L003 清單）
- 身分識別連接埠（L005 清單）
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

### L008 · 橫向連接埠處於測試模式（PB，未強制執行） `HIGH`

**類別：** LateralMovement

**偵測內容：**
識別橫向移動連接埠、資料庫連接埠、身分識別連接埠及 Windows 管理連接埠上 `policy_decision = 'potentially_blocked'` 的流量。

**重要性：**
`potentially_blocked` 是 Illumio 部署中最嚴重的政策缺口：**這些流量沒有對應的 Allow 規則**，VEN 處於測試/可見性模式所以流量自由通過。切換至強制執行模式後，預設拒絕白名單會自動封鎖這些流量。強制執行啟用之前，這些都是存活中、完全未受保護的攻擊路徑。

**觸發條件：**
關鍵連接埠上的 potentially_blocked 流量超過 `pb_lateral_threshold`（預設：**10**）。

**閾值設定鍵：** `pb_lateral_threshold`

**建議行動：**
- 將受影響工作負載從可見性/測試模式移至**選擇性**或**完整**強制執行
- 審查每筆 potentially_blocked 橫向連接埠流量——這些流量**沒有 Allow 規則**，強制執行前先確認哪些是合法流量
- 對合法的橫向連接埠路徑（例如跳板機 SSH、管理 VLAN）先建立 Allow 規則
- 將工作負載移至**選擇性**或**完整**強制執行後，預設拒絕將自動封鎖所有未覆蓋流量
- 審查證據中的目的地應用程式，優先處理正式環境工作負載

---

### L009 · 資料外洩模式（對外傳輸至未受管目的地） `HIGH`

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

### L010 · 跨環境橫向連接埠存取（邊界突破） `CRITICAL`

**類別：** LateralMovement

**偵測內容：**
偵測橫向移動連接埠及 Windows 管理連接埠在**不同環境**（`src_env != dst_env`）之間的放行流量。

監控連接埠：SMB (445)、RDP (3389)、WinRM (5985/5986/47001)、RPC (135)、SSH (22)、TeamViewer (5938)、VNC (5900/5901)、Telnet (23)。

**重要性：**
評級為 **CRITICAL** 是因為這代表完整的巨型分段失效。環境邊界（正式/開發/測試/DMZ）是您的最高安全域。若橫向移動連接埠被允許跨越這些邊界，入侵低安全開發工作負載的攻擊者可直接以完全相同的橫向移動技術——PsExec、WMI、RDP——抵達正式環境系統，環境分段的全部目的蕩然無存。

**觸發條件：**
跨環境邊界的橫向/管理連接埠放行流量超過 `cross_env_lateral_threshold`（預設：**5**）。

**閾值設定鍵：** `cross_env_lateral_threshold`

**建議行動：**
- **立即**建立 Illumio 拒絕規則封鎖環境邊界上的橫向連接埠
- 這是 P1 修復措施，不應等候維護窗口
- 審查證據中的每個環境配對，確認是否有任何跨環境管理存取是刻意為之（例如跳板主機基礎設施）
- 若屬刻意行為，將放行規則範圍限定至特定授權來源 IP

---

## 閾值設定參考

所有閾值均在 `config/report_config.yaml` 的 `thresholds:` 區塊中設定：

```yaml
thresholds:
  # ── B 系列 ────────────────────────────────────────────────────────────────
  min_policy_coverage_pct: 30         # B005：覆蓋率低於此值時觸發
  lateral_movement_outbound_dst: 10   # B006：來源連接超過 N 個不同目的地時觸發
  user_destination_threshold: 20      # B007：使用者抵達超過 N 個不同目的地時觸發
  unmanaged_connection_threshold: 50  # B004：未受管來源流量超過 N 時觸發
  high_bytes_percentile: 95           # B008：位元組量超過第 N 百分位時觸發
  high_bandwidth_percentile: 95       # 頻寬尖峰百分位（Module 11 使用）
  cross_env_connection_threshold: 100 # B009：跨環境流量超過 N 時觸發

  # ── L 系列 ────────────────────────────────────────────────────────────────
  discovery_protocol_threshold: 10    # L002：未封鎖的探索協定流量下限
  db_unique_src_app_threshold: 5      # L003：資料庫可被超過 N 個來源應用程式存取時觸發
  identity_unique_src_threshold: 3    # L005：LDAP/Kerberos 可被超過 N 個來源應用程式存取時觸發
  blast_radius_threshold: 5           # L006：應用程式可透過橫向連接埠抵達超過 N 個應用程式時觸發
  unmanaged_critical_threshold: 5     # L007：未受管→關鍵連接埠的最低流量下限
  pb_lateral_threshold: 10            # L008：橫向連接埠上 PB 流量的最低下限
  exfil_bytes_threshold_mb: 100       # L009：受管→未受管傳輸超過 N MB 時觸發
  cross_env_lateral_threshold: 5      # L010：跨環境橫向流量最低下限
```

### 調整建議

| 環境狀況 | 建議調整 |
|:---|:---|
| 高誤報環境（開發網路扁平、跨應用流量多） | 提高 `db_unique_src_app_threshold` 至 10–15；`identity_unique_src_threshold` 至 8–10 |
| 成熟分段環境（大多數工作負載已強制執行） | 將 `min_policy_coverage_pct` 提高至 80，僅在成熟環境退化時觸發 |
| 大量資料傳輸工作負載（備份伺服器、ETL） | 提高 `high_bytes_percentile` 至 99 或將 `exfil_bytes_threshold_mb` 提高至 500–1000 |
| 嚴格零容忍環境 | 將 `cross_env_lateral_threshold` 設為 1，任何跨環境橫向連接埠流量立即觸發 |

---

## 勒索軟體風險連接埠清單

`config/report_config.yaml` 中 `ransomware_risk_ports:` 定義了四個風險等級，規則引擎用以分類流量風險：

| 等級 | 連接埠 | 服務 | 控制難度 |
|:---|:---|:---|:---|
| **critical** | 135 | RPC | hard |
| **critical** | 445 | SMB | hard |
| **critical** | 3389 | RDP | easy |
| **critical** | 5985, 5986 | WinRM | medium |
| **high** | 5938 | TeamViewer | easy |
| **high** | 5900 | VNC | easy |
| **high** | 137, 138, 139 | NetBIOS | easy |
| **medium** | 22 | SSH | medium |
| **medium** | 2049 | NFS | medium |
| **medium** | 20, 21 | FTP | easy |
| **medium** | 5353 | mDNS | easy |
| **medium** | 5355 | LLMNR | easy |
| **medium** | 80 | HTTP | easy |
| **medium** | 3702 | WSD | easy |
| **medium** | 1900 | SSDP | easy |
| **medium** | 23 | Telnet | easy |
| **low** | 110 | POP3 | easy |
| **low** | 1723 | PPTP | easy |
| **low** | 111 | SunRPC | easy |
| **low** | 4444 | Metasploit | easy |

> **注意：** `low` 等級連接埠目前已定義於設定檔中，但尚未被任何規則直接引用。未來版本可能新增 L 系列規則覆蓋這些連接埠。

---

## 進階分析模組（Module 13–15）

除安全規則引擎外，報表系統包含三個進階分析模組，提供安全發現的補充視角。這些模組不產生 Finding 物件，而是在報表中獨立輸出分析結果。

### Module 13 · 強制執行準備度評分

**檔案：** `src/report/analysis/mod13_readiness.py`

計算 0–100 的強制執行準備度評分，涵蓋五個面向：

| 面向 | 權重 | 說明 |
|:---|:---|:---|
| Policy Coverage | 35 分 | 具有 `allowed` 政策的流量百分比 |
| Ringfence Maturity | 20 分 | 來源與目的地具有相同應用標籤的流量百分比 |
| Enforcement Mode | 20 分 | 受管工作負載處於強制執行模式的百分比 |
| Staged Readiness | 15 分 | 反向衡量 `potentially_blocked` 流量的比例（沒有 Allow 規則的未覆蓋流量；切換強制執行後由 default-deny 封鎖） |
| Remote App Coverage | 10 分 | 遠端存取連接埠流量中具有允許政策的百分比 |

### Module 14 · 基礎設施關鍵性評分

**檔案：** `src/report/analysis/mod14_infrastructure.py`

使用有向圖分析對應用程式節點進行關鍵性評分：
- **In-degree**（入度）：依賴此應用程式的其他應用程式數量（作為服務提供者的關鍵性）
- **Out-degree**（出度）：此應用程式連線的其他應用程式數量（作為消費者的爆炸半徑）
- **Dual-pattern score**：入度與出度的加權組合
- **Betweenness proxy**：同時具有高入度和高出度的應用程式（中介角色）

### Module 15 · 橫向移動風險偵測

**檔案：** `src/report/analysis/mod15_lateral_movement.py`

偵測橫向移動風險模式，涵蓋連接埠包括：SMB (445)、RPC (135)、NetBIOS (139)、RDP (3389)、SSH (22)、WinRM (5985/5986)、Telnet (23)、NFS (2049)、RPC Portmapper (111)、LDAP (389)、LDAPS (636)、Kerberos (88)、MSSQL (1433)、MySQL (3306)、PostgreSQL (5432)。

---

## 連接埠參考速查表

| 連接埠 | 服務 | 參照規則 |
|:---|:---|:---|
| 20, 21 | FTP | B003, L001 |
| 22 | SSH | B003, B006, L010 |
| 23 | Telnet | L001, B003, B006, L010 |
| 80 | HTTP | B003 |
| 88 | Kerberos | L005 |
| 110 | POP3 | （ransomware_risk_ports: low） |
| 111 | SunRPC | （ransomware_risk_ports: low） |
| 135 | RPC / DCOM | B001, L007, L008, L010 |
| 137, 138 | NetBIOS NS/DGM | B002, L002 |
| 139 | NetBIOS Session | B002 |
| 389 | LDAP | L005 |
| 445 | SMB | B001, L007, L008, L010 |
| 464 | Kerberos 密碼 | L005 |
| 636 | LDAPS | L005 |
| 1433 | MSSQL | L003, L004, L007 |
| 1521 | Oracle | L003, L004 |
| 1723 | PPTP | （ransomware_risk_ports: low） |
| 1900 | SSDP | L002 |
| 2049 | NFS | B003 |
| 3268, 3269 | AD 全域目錄 | L005 |
| 3306 | MySQL | L003, L004, L007 |
| 3389 | RDP | B001, B006, L010 |
| 3702 | WSD | L002 |
| 4444 | Metasploit | （ransomware_risk_ports: low） |
| 5353 | mDNS | L002 |
| 5355 | LLMNR | L002 |
| 5432 | PostgreSQL | L003, L004, L007 |
| 5900, 5901 | VNC | B002, B006, L010 |
| 5938 | TeamViewer | B002, B006, L010 |
| 5984 | CouchDB | L003 |
| 5985, 5986 | WinRM | B001, L007, L008, L010 |
| 6379 | Redis | L003, L007 |
| 9200 | Elasticsearch | L003 |
| 27017 | MongoDB | L003, L004 |
| 47001 | WinRM 備用 | L007, L008, L010 |
| 50000 | IBM DB2 | L003 |

---

## 規則引擎內部連接埠群組

以下是 `rules_engine.py` 中定義的連接埠群組常數，供開發者參考：

```python
_DB_PORTS         = {1433, 3306, 5432, 1521, 27017, 6379, 9200, 5984, 50000}
_IDENTITY_PORTS   = {88, 389, 636, 3268, 3269, 464}
_CLEARTEXT_PORTS  = {23, 20, 21}
_DISCOVERY_PORTS  = {137, 138, 5353, 5355, 1900, 3702}
_WINDOWS_MGMT_PORTS = {135, 445, 5985, 5986, 47001}
_REMOTE_ACCESS_PORTS = {22, 3389, 5900, 5901, 5938, 23}
```

`lateral_movement_ports`（定義於 `report_config.yaml`）：`[3389, 5900, 22, 445, 5985, 5986, 5938, 23]`
