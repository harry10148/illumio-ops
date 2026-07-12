# PCE 原生式 Filter 版面與 Service 類別擴充 — 設計文件

日期：2026-07-12
狀態：使用者已於 brainstorming（含視覺 mockup 比較）逐項核可

## 1. 背景與目標

使用者回報三個問題：

1. 五個 modal 仍保留舊版獨立 PORT / 通訊協定 / 排除 PORT 裸欄位，與 FilterBar pill 並存（雙軌輸入、易混淆）。
2. Filter 的呈現與可篩類別希望對齊原生 PCE Explore（三欄式 Source/Destination/Service、is-not 排除列、類別面板），且手動輸入 port 時無法表達「TCP+UDP 兩者」、格式引導不足。
3. 報表 print PDF 覆蓋缺口。

盤點事實（2026-07-12 掃描）：

- FilterBar（`src/static/js/filter-bar.js`）已支援 `label/label_group/iplist/workload/ip/service/port` 七類 pill，且能讀回舊 scalar `port`/`proto`/`ex_port`（:104-113）。
- 裸欄位存在於 5 個 modal：`m-query`（dashboard 儲存查詢）、`m-traffic`（連線次數規則）、`m-bw`（頻寬規則）、`m-sched`（排程報表）、`m-gen-report`（即時報表），各自序列化 scalar `port`/`proto`/`ex_port`。
- print PDF 唯一缺口：`rule_hit_count_html_exporter.py` 有 @media print CSS 但無 aside + print-btn（其他 8 個報表家族皆已具備）。
- cache flatten（`src/report/parsers/api_parser.py`）已含 `process_name`、`dst_fqdn`；缺 `windows_service_name`、`transmission`（raw_json 內有原始值）。

## 2. 決策紀錄

| 決策點 | 結論 |
|---|---|
| 舊裸欄位 | 五個 modal 全數移除，port/protocol/排除 port 一律走 FilterBar Service 側 pill |
| 版面 | 方案 A：完整仿 PCE 三欄式（Source ⇄ Destination + Service）+ is-not 排除列，全部入口統一；窄 modal 垂直堆疊 |
| 查詢模式 | AND/OR 模式切換鈕（Source 與 Destination 之間）：AND＝分欄（`src_*`/`dst_*` key）、OR＝合併為「Source OR Destination」單欄（`any_*` key）；⇄ 鈕整組對調兩欄 pill；切換模式時既有 pill 自動搬移（src+dst 併入 any；any 拆回時放 Source 欄並提示） |
| 新類別 | Port Range、Process Name / Windows Services、Transmission；**FQDN 與 App Groups 明確排除（後排）** |
| Service 輸入引導 | 打數字即出三選一候選（預設「兩者 TCP+UDP」）、`-` 轉範圍、文字搜 Process/WinService/Policy Services、面板底部常駐格式提示列 |
| print PDF | rule_hit_count 補 aside + print-btn（比照 policy_diff/app_summary 家族模式）+ 守門測試 |
| API 事實查證 | 已透過 NotebookLM（Illumio 官方 API guide 筆記本）確認（§5）；實作期須再以真 PCE 驗證（歷史教訓：單測可能鎖住錯形狀） |

## 3. UI 設計

### 3.1 版面（元件：FilterBar v2，全入口共用）

```
AND 模式：
[ Source        ]  [AND]  [ Destination    ]  [ Service      ]
                   [ ⇄ ]
[ Source is not ]         [ Destination is not ] [ Service is not ]

OR 模式：
[ Source OR Destination            ]  [OR]  [ Service      ]
[ Source OR Destination is not     ]        [ Service is not ]
```

- 六個（OR 模式四個）輸入區各自是 pill 容器；點擊展開下拉面板：左側候選清單、右側類別清單（Search All Categories / Labels and Label Groups / Workloads / IP Lists / IP Address/CIDR / Port·Port Range / Process·Win Service / Transmission〔僅 Destination〕/ Policy Services〔僅 Service〕），底部鍵盤提示（↑↓ 選擇、Enter 加入、Esc 關閉）。
- Transmission 類別只出現在 Destination（含 is-not）面板——與原生 PCE 一致，也對應 API 形狀（§5）。
- 窄 modal：同一元件以垂直堆疊 render（欄位順序：Source → Destination → Service → 排除列摺疊區）。is-not 列在 modal 內預設收合，點「排除條件」展開。
- 各 modal 既有的時間範圍、Policy 判定等控制**不搬動**（非本案範圍）；只替換 filter 輸入區。

### 3.2 Service 欄輸入引導

- 輸入純數字 `443` → 候選：`443 — 兩者（TCP+UDP）`〔預設〕、`443/tcp`、`443/udp`、範圍起點提示、名稱含 443 的 Policy Services。
- 輸入 `1000-2000` → 範圍三候選（兩者/tcp/udp），提示「起訖皆含」。
- 輸入文字 → Process Name / Windows Services 自由值 + Policy Services suggest。
- 面板底部常駐格式提示列：`443＝兩者 ・ 443/tcp ・ 443/udp ・ 1000-2000 ・ 1000-2000/udp ・ 文字＝Process/WinService/Service 名稱`。
- pill 顯示：`443 (TCP+UDP)`、`8080/tcp`、`1000-2000/udp`、`proc: httpd`、`winsvc: Dnscache`、`TX: broadcast`。

## 4. 資料模型與 key

### 4.1 既有 key（不變）

`src_*/dst_*/any_*`（label、label_group、iplist、workload、ip）、`services`/`ex_services`、`ports`/`ex_ports`；後端 scalar `port`/`proto`/`ex_port` 讀取相容續留（舊設定），儲存時不再產生。

### 4.2 port token 格式（`ports`/`ex_ports` 內）

字串 token 統一文法：`<port>[-<to_port>][/<tcp|udp>]`。無 `/proto` 尾碼＝兩者（TCP+UDP）。範例：`443`、`443/tcp`、`1000-2000`、`1000-2000/udp`。轉原生 payload 時「兩者」**預設展開為 tcp+udp 兩個 services entry**（同 key OR 語意天然成立）；實作期以真 PCE 驗證「省略 proto」是否等價，等價則可簡化為單 entry。client-side 比對器與 cache df 的「兩者」語意＝不比對 proto。

### 4.3 新 key

| key | 形式 | 語意 |
|---|---|---|
| `process_name` / `ex_process_name` | str \| list[str] | service.process_name 比對（不分大小寫、完整字串）——沿用查詢層既有 key，擴充為可收 list |
| `windows_service_name` / `ex_windows_service_name` | str \| list[str] | service.windows_service_name 比對——沿用既有 key，擴充為可收 list |
| `transmission`（新）/ `ex_transmission`（既有） | str \| list[str]（值域 unicast/broadcast/multicast） | 流向型態；僅 destination 側。include 為本案新增；exclude 沿用既有 key（`transmission_excludes` 別名續留） |

（修訂 2026-07-12：七層落差矩陣盤點後改沿用查詢層既有 key 命名，取代原草案的 `processes`/`win_services`/`dst_transmission`。另盤點發現 `ports` token 文法已含範圍與 proto 且四層皆通——**`port_range*` 四 key 維持現狀不擴充**，範圍一律走 `ports` token。）

## 5. Vendor-verified API 形狀（NotebookLM／官方 REST API guide，2026-07-12）

- 範圍：services entry `{"port": 1000, "to_port": 2000, "proto": 6}`；`to_port`＝範圍高端（含），非範圍時不得送。
- Process/WinService：services entry `{"process_name": "httpd"}`、`{"windows_service_name": "Dnscache"}`。
- Transmission：放在 `destinations.include`/`destinations.exclude` 的 actor 陣列內：`{"transmission": "broadcast"}`；值域 broadcast/multicast/unicast。
- proto：TCP=6、UDP=17。
- 回傳 flow record：`transmission` 為 record 頂層欄位；`windows_service_name` 在 `service` 物件內。

**實作期真 PCE 驗證點（必做，不可只靠單測）：** (a) `to_port` 範圍查詢實際回傳；(b) 「兩者」的正確表達（省略 proto vs 展開兩 entry）；(c) transmission include/exclude 實測；(d) process_name/windows_service_name 大小寫與部分符合行為。

## 6. 七層鏈逐 key 對帳（每個新 key 都要走完）

1. FilterBar pill 序列化/反序列化（filter-bar.js）
2. 各入口端點 forward 白名單（reports.py、rules 三端點、dashboard 儲存查詢/top10、quarantine search）
3. 查詢層 payload 白名單（`TrafficQueryBuilder`，含 destinations/services 的 payload 構造）
4. `_flow_matches_filters`（client-side fallback 比對器）
5. `check_flow_match`（legacy scalar 比對器——本案不擴充，但需確認新 key 不被誤吞）
6. cache df 路徑（`df_filter` + flatten 欄位）：flatten 補 `windows_service_name`、`transmission` 欄位；**舊 report_json 列缺新欄位** → 比對須 null-tolerant（缺欄位視為不符合而非報錯），並記錄「重新 ingest 後才有完整資料」的行為於文件
7. 守門測試：七層對帳測試 + 兩套比對器一致性測試（歷史教訓：兩套比對器只修一套是 4b 案的 Critical）

## 7. 舊欄位收斂與相容

- 移除 5 個 modal 的裸欄位 DOM 與序列化程式碼（index.html、dashboard.js、rules.js）。
- 既存設定（排程/規則/儲存查詢）內的 scalar `port`/`proto`/`ex_port`：讀取時由 FilterBar 反序列化為 port pill（既有能力）；後端 `check_flow_match` scalar 分支續留。重新儲存後自動轉為 `ports`/`ex_ports`。
- 守門測試：確認 5 個 modal 對應 JS 不再產生 scalar key；舊設定回填 round-trip 測試。

## 8. rule_hit_count print PDF

- `rule_hit_count_html_exporter.py` 比照 policy_diff（:149）/app_summary（:148）加 aside + `<button class="print-btn" onclick="window.print()">`（i18n `rpt_nav_print_pdf`）。
- 新增守門測試：掃所有 HTML exporter 輸出必含 print-btn（防未來新報表再漏）。

## 9. 測試與驗證策略

- 單元/契約：七層對帳、兩套比對器一致、port token 解析（含錯誤格式）、模式切換 pill 搬移、舊 scalar 回填。
- Playwright 實機：AND/OR 切換、⇄ 對調、Service 候選三選一、Transmission 僅 Destination、五 modal 收斂後儲存 round-trip、rule_hit_count 列印按鈕。
- 真 PCE：§5 四個驗證點 + 端到端查詢（range/process/winservice/transmission 各至少一次真實查詢比數）。

## 10. 範圍外（明列）

- FQDN、App Groups 類別（後排；flatten 已有 dst_fqdn，未來成本低）。
- CLI object picker 版面（key 相容、不受影響）。
- 各 modal 的 Time/Policy Decision 控制列重排。
- 原生 PCE 的 Save Query/Load Filter 工具列（dashboard 已有儲存查詢功能，不重造）。
