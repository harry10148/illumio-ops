# UI/UX 重新設計 v3 — 設計規格

日期：2026-09-03
狀態：使用者已逐節核可（§1–§7 全過）
前置：v2 規格 [`2026-08-03-ui-ux-redesign-v2-design.md`](2026-08-03-ui-ux-redesign-v2-design.md)（已完整交付並封版 `v5.0.0`，commit `cc77fbcf`）
比稿畫布：https://claude.ai/code/artifact/bedafd57-0972-43ad-8500-f80f361193ba（第一頁＝定案方向 D 首頁＋調查中樞線框；第二頁＝未選的 E／F）
工作稿：`tmp/design-v3/`（gitignored；`Main.dc.html`、`InvestigateHub.dc.html`、`canvas.json`、四張自檢截圖）

## 0. 背景與決策紀錄

v2（方向 B「Ops 深色監控台」＋六區 IA）於 2026-09 全數上線後，使用者的回饋是「用起來像工程版／debug 版，不像產品化的 IT 管理平台」。本輪重開比稿，決策如下：

| 決策點 | 結論 |
|---|---|
| 範圍 | GUI 資訊架構＋流程＋視覺全部重做；報表與 CLI **只換皮**（結構、章節、精靈流程不動） |
| 稿件形式 | 靜態稿（不做可點擊原型） |
| v2 封版 | 已打 `v5.0.0`（2026-09-03），v3 從乾淨基線開始 |
| 視覺 | 三方向比稿（D 品牌工作台／E 雲藍儀表／F 值班簡報）→ **選定 D「品牌工作台」** |
| IA | 三方案（工作流層疊在六區上／任務中樞重切／物件中心）→ **選定「任務中樞重切」**（六區→五區） |
| 後端上限 | **a＋b＋c 全做**（告警落地、路由帶狀態、flow→rule 解釋），推翻 v2 的「不動後端」 |
| 主場景 | 「接到告警後追查流量與規則」，六步分鏡（§3）使用者已核可 |
| 使用者 | 一般 IT 維運值班＋熟手網路/資安工程師（同 v2） |
| 品牌 | 使用 Illumio 色盤與 Montserrat（依 `illumio-brand` skill），**不使用 logo／wordmark** |

### 0.1 原始碼盤點結論（決定 IA 的事實，非意見）

在已上線的 v2 中，主場景走不通：

- 沒有「已觸發告警清單」：`state["alert_history"]` 只存 cooldown 計時；`Reporter.send_alerts` 派送四個 bucket（health／event／traffic／metric）後不落地任何可瀏覽紀錄。
- 全站只有一處讀 `ctx.query`（`alerting.mjs:862` 的 `?hl=`），所有跨區跳轉都是無狀態 `router.go(route)`。
- 流量列（`POST /api/quarantine/search`）不帶 rule 資訊；`policy_resolver` 只是離線批次報表，沒有查詢端點。

因此「六區切法不直覺」的根因是旅程沒有軌道，不是分組錯誤；本規格以補軌道為核心。

### 0.2 v2 痛點（使用者回饋，作為驗收對照）

視覺：太暗太硬、太密字太小、圖表不夠好、沒有品牌感。
IA：六區切法不直覺、首頁不能幫忙做決定、操作流程太長太分散、drawer／表單不好用。

方法論硬規則沿用 v2：資料模型一律從原始碼與真快照推導；PCE 術語保留英文；mockup 禁止手寫資料（比稿階段例外：可轉錄快照字面值，須標示）。

## 1. 資訊架構：六區 → 五區

```
 v2                            v3
 總覽 ──────────────────────▶ 首頁 Home（狀況＋待辦；每張卡＝一個決定）
 調查 ──┬─ 流量/Workload/事件 ─▶ 調查 Investigate（中樞：收件匣→流量→規則→行動）
 告警 ──┼─ 收件匣（新）────────┘
        └─ 四型規則 CRUD ─────┐
 自動化 ┬─ rule scheduler ────┼▶ 政策 Policy（告警規則、ruleset 排程、最佳實務、run-once/debug）
        ├─ 報表排程 ──┐       │
        └─ 背景 job ──┼──┐    │
 報表 ─────────────────┴──┼───▶ 報表 Reports（11 型＋產出＋報表排程）
 系統 ────────────────────┴───▶ 設定 System（現有＋job 健康＋管道連線＋測試告警/watermark）
```

判準：首頁看「現在」、調查查「這件事」、政策改「規則」、報表產「交付物」、設定改「系統」。

- 「自動化」區取消：rule scheduler → 政策；報表排程 → 報表；背景 job 健康 → 設定（首頁只顯示摘要燈）。
- 告警管道不再讀寫分離：狀態與連線設定都在設定區；「測試告警」與 watermark 重置也在設定區。
- 頂欄：品牌字（`illumio-ops`＋環境名）｜五區導覽｜五燈健康摘要（Jobs／PCE／Lag／SIEM／Channels，同 `health_line.py`；點開 popover）｜⌘K｜使用者。
- ★ **待裁決**：頂欄健康燈改為**全頁常駐**。這推翻 2026-08-05「僅總覽區顯示」的裁決，理由是五區導覽變短、頂欄有空間；本項未在 §1–§3 口頭核可時明示，需使用者另行同意，否則沿用「只在首頁」。
- URL：每區／子視圖穩定 hash 路由，**帶狀態**（§4b）。

### 1.1 路由表

| 區 | 路由 | 內容 |
|---|---|---|
| 首頁 | `#/home` | §2 |
| 調查 | `#/investigate/inbox`、`#/investigate/inbox?id=` | 收件匣、告警詳情 |
| | `#/investigate/traffic`、`?alert=`、`?f=` | 流量（可帶條件） |
| | `#/investigate/workloads`、`#/investigate/events` | 沿用 v2 |
| 政策 | `#/policy/alert-rules`、`?hl=` | 四型告警規則 CRUD＋rule_test |
| | `#/policy/rulesets`、`?rs=&rule=` | ruleset 瀏覽＋排程 drawer |
| | `#/policy/schedules` | 排程清單／時間軸／PCE 對帳／執行紀錄 |
| | `#/policy/ops` | run-once、debug、最佳實務 |
| 報表 | `#/reports`、`#/reports/schedules` | 11 型卡＋產出；報表排程 |
| 設定 | `#/system/{pce,cache,siem,tls,security,display,channels,alerting,jobs,logs}` | v2 八個＋`alerting`（測試告警／watermark／輸出主控台）＋`jobs` |
| 登入 | `login.html` | 同一視覺系統 |

`design/v2/coverage.yaml` 的 101 項依此表重編為 `design/v3/coverage.yaml`；每一項在 v3 必須有落點或明列「移除」。

## 2. 首頁：狀況＋待辦

首頁只回答五個問題，每個問題一張卡，卡片可點進對應區；v2 的 16 張卡收斂如下。

| 問題 | 卡 | 資料源（既有端點） | 去處 |
|---|---|---|---|
| 要處理什麼 | 需要你處理：`status=new` 的告警依嚴重度列前 4 則＋計數 | `GET /api/alerts`（新，§4a） | 收件匣 |
| 系統好不好 | 系統健康：一句話結論＋六燈（頂欄五燈＋VEN；VEN 只在首頁卡，不進頂欄） | `/api/status`、`/api/dashboard/overview` | 設定各頁 |
| 今天會動什麼 | 今天會發生：rule scheduler 當日時間點、報表排程、retention | `rs_schedules`、`report_schedules`、cache settings | 政策／報表 |
| 資料可不可信 | 7 天流量決策：allowed／potentially blocked／unknown／blocked 一條堆疊帶＋較前期變化＋一句解讀 | `dashboard_overview.blocked` | 調查／流量 |
| 態勢往哪走 | 安全態勢：posture 分數＋三分量 | `dashboard_overview.posture` | readiness 報表 |

頁首：日期時間／時區眉標＋一句話標題（「今天有 N 則需要處理」）＋主按鈕「前往調查」。

**移出首頁**（v2 卡 → 新家）：Top10 與自訂查詢 → 調查／流量的側欄；audit 摘要、policy usage、snapshot、報表最近產出 → 報表區首頁；TLS、Integrations、pipeline 明細、資料完整性明細 → 設定各頁（首頁只留燈）。

## 3. 調查中樞

主場景六步（使用者核可）：

1. 首頁看到「今天有 N 則需要處理」，點進去
2. 收件匣：每則告警一列（時間／嚴重度／規則／摘要／狀態）
3. 告警詳情：觸發條件、命中的 flow 摘要，「看流量」帶條件跳流量
4. 流量結果已套好條件，挑一條 flow →「看規則」
5. 看到放行／阻擋它的 ruleset／rule（provision 狀態、來源→目的→服務）
6. 行動：隔離 workload、對該 rule 建排程變更、或回收件匣標記已處理

### 3.1 版式：步進＋上下文條

不用三欄同屏。每一步全寬，上一步的關鍵資訊釘在頂部一條「上下文條」，可隨時退回。

```
 ① 收件匣 › ② 告警詳情 › ③ 流量（已套條件）› ④ 規則 › ⑤ 行動
┌ 上下文條：● crit  SSH 從非管理段進入 DB  10:32  規則 traffic#3  命中 24 flows  ← 回告警詳情 ┐
│ 篩選條件（由告警帶入，可改）[port 22][dst label app=db][最近 5 分鐘][hybrid]   24/24 flows │
│ 來源 | 目的 | 服務 | 決策 | 連線 | 最後出現 | [看規則][隔離]                                 │
│ …                                                          ┃ 步驟④ 規則面板（常駐右側）    │
│                                                            ┃ 步驟⑤ 行動按鈕                │
└────────────────────────────────────────────────────────────┴────────────────────────────────┘
```

- 收件匣＝四型告警同一張表；狀態 new／ack／done 由使用者切換（PATCH）。
- 告警詳情＝該筆紀錄的 `criteria`＋`payload_json`（top flows／event matches）＋派送結果；「看流量」產生 `#/investigate/traffic?alert=<id>`。
- 流量列的「看規則」呼叫 `POST /api/policy/explain`（§4c），結果進右側面板；面板底部就是行動（隔離→既有 quarantine API；排程變更→政策區 ruleset drawer 帶 `?rs=&rule=`；標記已處理→PATCH）。
- 流量／Workload／事件檢視器仍可獨立進入；不從告警來時上下文條不出現、條件為空。
- 線框已核可：畫布第一頁「調查中樞 · 線框」。

### 3.2 彈窗分級（沿用 v2 §2.2，修正兩點）

大型表單仍走右側 drawer，但 drawer 寬度 560px、內文 14px、分節有標題；破壞性確認 modal 附影響摘要；「看規則」面板是**常駐側欄不是 drawer**（使用者裁決）。

## 4. 後端契約

v2「不動後端」在 v3 解除；以下三項是產品程式碼變更，各自獨立可交付。

### 4a. 告警落地

- Hook 點：`Reporter.send_alerts`。**首次派送嘗試時就寫入**（不論成敗），鍵為 `(type, rule_index, fired_at)`；DLQ 重播時以同鍵**更新** `dispatch_json`，不新增列（否則每則先失敗後成功的告警會出現兩次）。`force_test` 不寫。
- 儲存：新 SQLite `logs/alerts.sqlite`（`state.json` 為單一 JSON 不宜無限成長；pce_cache DB 有自己的 `user_version` 升級流程，不混入）。檔案由 service 帳號建立，權限 0600；安裝／升級腳本不預建。
- 欄位：`id, fired_at, type(event|traffic|bandwidth|system), rule_index, rule_name, severity, summary, criteria, payload_json, dispatch_json, status(new|ack|done), status_by, status_at`。
- 端點：`GET /api/alerts?status&type&since&page`、`GET /api/alerts/<id>`、`GET /api/alerts/<id>/traffic_query`（§4b 用；由該告警的規則重建 FilterBar query spec）、`PATCH /api/alerts/<id>` `{status}`（CSRF 同既有規則）。
- 保留：沿用 archive retention 天數，由同一個 retention job 清理。

### 4b. 路由帶狀態

- `core/router.mjs` 已解析 `?query`；每區 mount 讀 `ctx.query`。
- 契約：`#/investigate/inbox?id=`、`#/investigate/traffic?alert=<id>`（後端以該告警的規則 filters＋pd＋window 重建查詢：`GET /api/alerts/<id>/traffic_query` 回 FilterBar 可載入的 query spec）、`#/investigate/traffic?f=<urlsafe-base64 JSON>`（一般跳轉）、`#/policy/rulesets?rs=&rule=`、`#/policy/alert-rules?hl=`。
- 規則：狀態在 URL＝可書籤、上一頁可退；`f=` 超過 2KB 改存 sessionStorage 並以 token 代替。

### 4c. flow → rule 解釋

- 端點：`POST /api/policy/explain` `{src: {workload_href|ip}, dst: {workload_href|ip}, port, proto, basis: "active"|"draft"}` → `{allow: [...], deny: [...], override_deny: [...], basis, evaluated_at, source: "pce_rule_search"|"local_resolver"}`；每個 rule 項含 ruleset href／name／provision_state／enabled、rule href／index、src actors、dst actors、service、scope。
- 主路徑：IP → cache 內 workload／iplist href，再呼叫 PCE **Rule Search**（`POST /api/v2/orgs/:org/sec_policy/:pversion/rule_search`，Public Experimental；`rule_types` 白名單 `sec_rules, deny_rules, override_deny_rules`，版本差異靠白名單擋）。
- 備援：對不到 href 的純 IP（未管理端點）走本地 `policy_resolver` 的 iplist CIDR 比對（沿用 `_cap_sides` 上限，標記 truncated）。
- 快取：同一 (src,dst,port,proto,basis) 60 秒內不重打 PCE；rule_search 併發上限依 PCE 文件 12。
- 語意：`allow` 空＝「沒有 allow rule 涵蓋」（解釋 potentially blocked／blocked）；面板另列「最接近的 ruleset」（同 dst actor 的 allow rule，差異欄標出服務／來源不符）。

### 4d. SIEM traffic log 依 policy decision 過濾（獨立先做，不在 v3 計畫內）

- `SiemDestinationSettings.traffic_pd: list[Literal["allowed","potentially_blocked","blocked","unknown"]]`，空＝全送。
- 過濾放 `enqueue_new_records` 的 ingest 閘（與 `source_types` 同層），backfill 一致。
- GUI SIEM 目的地 drawer 加 checkbox 群；CLI siem 選單同步；CEF 已帶 `pd=` 不改格式。
- 以獨立 PR＋TDD 交付並部署測試機，先於 v3 計畫。

## 5. 視覺系統：Direction D「品牌工作台」

| 項目 | 值 |
|---|---|
| 字型 | 標題 Montserrat Light 300（`--font-display`）；數字 Montserrat tabular；內文 Noto Sans TC → PingFang TC → Microsoft JhengHei。離線部署**只內嵌 Montserrat**（Latin 子集，woff2 約 4 個字重 <100KB），CJK 沿 v2 走系統字型，不把 Noto Sans TC（每字重數 MB）塞進 bundle；不依賴 Google Fonts |
| 面 | 白 `#FFFFFF` 主面；Tan `#F7F4EE` 次要面（目前分頁、chip、次要區塊）；Cerulean `#E5F2F9` 僅表格 hover／選取 |
| 墨 | Slate `#313638` 主文字；`#5B6164` 次；`#8A9296` 眉標／meta；線 `#E6E2DA`／`#F0EDE6` |
| 強調 | Orange `#FF5500` **只給動作**：主按鈕、連結、目前分頁底線、頁首關鍵數字。禁止大面積、禁止放在 Tan 上當文字 |
| 深色元素 | Cyan `#2D454C` 用於頭像、次要按鈕、圖表主色 |
| 語意 | ok `#166644`／warn `#FFA22F`／crit `#BE122F`／neutral `#9AA3A6`；燈號與 chip 一律帶文字 |
| 尺度 | 內文 14px、表格 13.5px、meta 12.5px、眉標 11px；列高 40px、控制項 36px、頂欄 60px；圓角 6–8px；1px 細線；**無陰影** |
| 密度 | 預設 cozy；compact 切換保留（同 v2 只動 token） |
| 主題 | 亮色為原生；暗色**保留但降為次要**（token 反轉、不另設計、真機只驗不破版） |
| 圖表 | 依 `dataviz` skill：單一色階（magnitude）或語意色（decision）；不做雙軸、不做甜甜圈；≥2 序列附圖例＋表格檢視；伺服端 SVG 沿用 chart_renderer 重繪樣式 |

token 檔：`src/static/css/v3/tokens.css`（亮暗兩套＋tone），components／areas 只能引用 token；禁止硬編色碼（守門沿用 `tests/test_color_token_lint.py` 與 `tests/test_css_color_tokens.py`，掃描範圍加入 `css/v3`）。

## 6. 報表與 CLI 換皮

### 6.1 報表殼

- `design/v3/reports/shell.css` 由 v2 `shell.css` 複製後**只改 token**：`--font-ui` 改 Montserrat＋Noto Sans TC；`--text-*`／`--line*` 改 Slate 系；tone 改品牌語意色；`--fs-body` 11.5→12.5px、`--fs-ui` 13→14px；`--accent` 改 Orange。
- 章節結構、封面、目錄、發現卡、列印分頁、寬表 landscape 規則（`WIDE_TABLE_LANDSCAPE_COLS=9`）**全部不動**；CSS drift guard（`SHELL_CSS` 對 `shell.css`＋`AUTHORISED_DELTAS`）與 conservation 測試照舊。
- 交付前 11 型真資料重產、雙寬度 Playwright 逐頁親驗（CLAUDE.md 硬規則）。

### 6.2 CLI

- `src/cli/_render.py` 的 `Colors` 對照改品牌近似色（標題 Slate／強調 Orange／語意三色），健康列燈色同步；`_console_safe_text` 與 `NO_COLOR` 行為不動。
- 互動選單六區→五區（自動化併入政策／報表／設定，對應 §1），63 項對照表（`design/v2/cli-flows.md`）重編為 v3 版；精靈流程、safe_input、雙語不動。
- click 子指令不動。

## 7. 驗收

### 7.1 沿用的自動守門

三翻車點專屬測試、i18n audit（10 類 0 findings）、CSS drift guard、conservation、no-hardcoded-color、coverage gate（改讀 `design/v3/coverage.yaml`）、全套 pytest、CI 全綠。

### 7.2 新增守門

- 告警落地：分析器觸發一則測試告警 → `GET /api/alerts` 必出現該筆且 `dispatch_json` 與 `dispatch_history` 一致；`force_test` 不寫入。
- URL 契約：§4b 每一條帶狀態路由各一個 Playwright 測試（進入→狀態正確→上一頁可退）。
- `POST /api/policy/explain`：lab 三種 flow 固定答案（有 allow rule／無 rule／未管理 IP 走備援）；PCE 回 4xx 時錯誤卡不吞錯。
- 五區 coverage：v2 101 項每項在 v3 有落點或明列移除，守門腳本 100%。

### 7.3 真機

- 主場景六步 Playwright 走一遍＋每步截圖（`test_e2e_*` env-gated 真機模式）。
- 11 型報表真資料重產、雙寬度逐頁檢查無截斷。
- CLI 五區遍歷＋健康列。
- 交付物：`tmp/phase3-verification/report.md`（對照表 100%＋截圖＋測試輸出）。

## 8. 分階段與順序

1. **4d SIEM pd 過濾**（獨立 PR，先做）
2. **後端 4a／4b／4c**（各自獨立 PR，附守門；可與 3 平行）
3. **視覺 token＋元件層**（`css/v3`、topbar、card、table、drawer 新規格）
4. **五區逐區遷移**（首頁 → 調查中樞 → 政策 → 報表 → 設定 → 登入），每區完成即部署測試機驗證
5. **報表殼換 token＋真機重產**
6. **CLI 換色＋五區選單**
7. **最終驗證＋CHANGELOG＋版本號（建議 6.0.0，待裁決）**

各階段獨立可合併、CI 全綠；計畫檔另立（writing-plans）。

## 9. 不做／延後

- 可點擊原型（使用者選靜態稿）。
- 物件中心 IA（方案 3）。
- 暗色模式重新設計（只保留 token 反轉）。
- draft policy 的 explain（v1 只做 active，draft 為 `basis` 參數預留）。
- 報表章節重排、CLI 精靈流程重排。
