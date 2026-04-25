# Report Module Inventory And Reader Guidance

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

