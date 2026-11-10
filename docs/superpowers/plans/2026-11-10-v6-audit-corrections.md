# v6 重構複查改正計畫

**來源：** 2026-11-10 七路稽核（main d10df598，6.4.4）。報告在 session scratchpad `audit1110/r1`–`r7`，本計畫已把要做的項目抄進來，不需再讀報告。

**規格：** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（下稱主規格）、`docs/superpowers/specs/2026-11-03-v6-ui-redesign-design.md`（下稱 UI 規格）。

**目標：** 把稽核的 3 High（文件）與 Medium 全部收掉：缺陷直接修、規格要求而值得做的補做、介面重做後已換設計的改規格。

## 全域約束

- 分支從 main 開，整合在 `.worktrees/v6-ui`；閘門用 `.worktrees/v6-ui/.superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`，全綠才合 main、才 push。
- 行為變更一律先寫會紅的測試；純文件與設定檔用比例測試。
- 新增或改動的介面與報表文字：en／zh_TW 兩語系同步，用語照主規格 §6.2.1，每句話對得到資料或固定規則（UI 規格 §6），頁面名稱用「VEN 總覽」。
- 報表有改動的型別：兩台實機重產、兩種寬度逐頁看有無截斷或溢出，結果寫進回報。
- commit 用英文 conventional commits，只 stage 明列路徑。tag 等使用者點頭。
- 不對 NFR 寫入；lab 可寫入測試。

## 順序

```
批次 A（6.4.5 缺陷與文件）──► 批次 C（規格修訂，純文件）──► 批次 B（6.5.0 補做功能）
   A1 A2 A3 A4 A5 互不相依          C1                          B1 … B6 互不相依
```

C 排在 B 前面：B 的驗收條文以修訂後的規格為準。

---

## 批次 A：缺陷與文件（發 6.4.5）

### A1 安裝、升級、回退腳本

- **結果**
  - `scripts/rollback.sh:35`：v6 服務不存在或停不下來時不中止，繼續還原 5.x（現在 `systemctl stop … || die` 會在還原前停下）。
  - `scripts/install.sh`：`--port` 搭配 `--upgrade-from` 時生效（把埠傳給遷移，寫進 v6 設定）；結尾訊息印的埠等於設定檔實際的埠。
  - `.gitignore` 加 `config/settings.json`。
  - `README.md:32`：開發安裝指令拆成兩行，無雜湊的 `requirements-dev.txt` 不放在 `--require-hashes` 下；改完實跑一次。
- **檔案** `scripts/rollback.sh`、`scripts/install.sh`、`illumio_ops/migrate/__main__.py`（如需加 `--port`）、`.gitignore`、`README.md`、`tests/scripts/`、`tests/migrate/`
- **驗收** 新測試先紅後綠：(1) unit 不存在時回退仍還原；(2) 升級帶 `--port 8443` 後設定檔埠為 8443、訊息一致。`git check-ignore config/settings.json` rc=0。
- **實機** .135 上以離線包實跑一次 `--upgrade-from` 不適用（無 5.x）；改在 dev 用 5.x 夾具目錄跑安裝腳本的升級路徑。

### A2 用語與推論句

- **結果**
  - `illumio_ops/i18n/zh_TW.json` 的「允許／被擋」「選擇性強制／僅可視」「Agent 遭竄改」等改成 §6.2.1 的寫法（已知位置 :527、:644、:646、:1273、:1274；改前全檔掃一次同類）。
  - `tests/i18n/test_terminology.py` 的禁用清單補上這些舊寫法，之後出現即紅。
  - 三句推論改成只陳述觀察到的事實：`tamper_pattern_regular_cycle`（:779）、`rpt_rule_b007_how`（:1145）、`rpt_rule_l009_how`（:1167）；en 同步。
- **檔案** `illumio_ops/i18n/zh_TW.json`、`illumio_ops/i18n/en.json`、`web/src` 內對應字串（若有）、`tests/i18n/test_terminology.py`
- **驗收** 先把禁用詞加進測試看到紅，再改字到綠。全檔 grep 推論用語（「多半」「可能代表」「攻擊者已」）無殘留，或逐條說明為何算固定規則。
- **決定** 推論句的掃查範圍是兩個語系檔全檔，不只那三句。

### A3 分層

- **結果**
  - `services/shell.py:12`、`services/analysis/focus.py:21`、`services/alerts/system.py:15` 不再 import `illumio_ops.jobs.health`：把 job 健康狀態的讀取搬到 services 或 store 層，jobs 改用它。
  - `jobs/scheduler.py:47`、`runtime.py:26` 不再 import `illumio_ops.web.tls`：TLS 檔案處理搬出 web 層。
  - `tests/gates/test_layering.py` 加 jobs 的規則（services、domain、store 不得 import jobs；jobs 不得 import web）。
- **驗收** 先加規則看到紅（列出現有 5 處），搬完到綠。行為不變，全套 pytest 綠。
- **限制** 只搬位置，不改行為、不改函式簽名以外的東西。

### A4 報表兩處

- **結果**
  - `services/reports/audit.py:242` `who[:5]`：超過 5 位時寫出「另有 N 位」，不再無聲截斷。
  - `services/reports/ven_status.py:265` `findings=()`：依報表已有的資料給發現（失聯、Idle 相容性非 green、版本落後等，每一條對得到報表內的表格列數）；沒有任何一條時寫明「沒有需要處理的項目」。
- **檔案** 上述兩檔、兩語系檔、`tests/services/reports/`
- **驗收** 測試：7 位使用者時輸出含「另有 2 位」；有 1 台失聯時 findings 非空且數字等於表格。.106 重產 audit、ven_status 兩語系，760px 與桌面寬度逐頁看。

### A5 文件

- **結果**
  - `docs/INDEX.md` 重寫成 v6 索引（版本取自現行版本、列出現有 v6 文件、5.x 文件只給 `docs/legacy-5.x/` 一個入口）。
  - `docs/reference/cli.md`、`rest-api.md` 與 `docs/reference/`、`docs/handover/`、`docs/_meta/` 其餘 5.x 文件搬進 `docs/legacy-5.x/`，讓 CHANGELOG 6.0.0 那句話成立；仍適用 v6 的（先逐檔判斷，例如 `glossary.md`、`traffic-metrics.md`）留下並更新。
  - 新增 `docs/reference/v6-rest-api.md`，由 API 契約產生（121 個操作），不手寫。
  - `docs/guide/v6-installation.md:47`：寫明首次登入的帳號來源與第一次登入必須改密碼的流程（照程式實際行為寫）。
  - `tools/`、`design/` 殘檔：列清單交使用者決定，不在本任務刪。
- **驗收** `docs/` 內所有相對連結可解析（寫一支檢查或用現有 docs 檢查）；INDEX 沒有指向不存在的檔。搬檔用 `git mv`。
- **決定** 5.x 文件是搬不是刪。

### A6 報表缺陷（2026-11-10 報表內容評估，來源 `2026-11-10-v6-report-content-6.6.0.md` §6）

- **結果**
  - ven_status 竄改統計：`services/analysis/tamper.py` 的 `n_7d` 與 `unexplained_7d` 用同一個單位（未解釋數不得大於事件數）。
  - unmanaged_endpoints S01 排序依嚴重度由高到低。
  - rule_hit_count 規則名稱不帶排程標記字串。
  - lateral_posture S01 不出現 workload href（顯示主機名稱）。
  - 報表內的原始 PCE 值與內部用語改成可讀文字（資源類型、動作、同步狀態、竄改模式、強制模式、結果、事件類型、OS 代碼；「沿用自 5.x」、`num_connections`、`tedt: 309`）；沒有對應譯名的值照原樣顯示，不猜。
  - policy_resolver 產出 0 列時寫明原因；先查 .106 run 146 的成因（`rules_no_address: 2`）。
  - 100.64.0.0/10（CGNAT）不標成「私有」。
  - audit 使用者欄、policy_diff「最後修改者」全是「—」：先查是資料沒有還是沒讀，沒讀就修，資料沒有就寫明。
- **驗收** 每項一個先紅後綠的測試；.106 重產受影響的報表兩語系、兩種寬度逐頁看。

---

## 批次 C：規格修訂（純文件，一個 commit）

### C1 兩份規格對齊現況

- **改成「不做」並寫明取代它的設計**（使用者 2026-11-10 同意照建議）
  - 主規格 l.602：告警註記附工作台條件 → 註記只有文字；調查條件由告警本身的「在工作台開啟」帶。
  - 主規格 l.637／l.672：報表信件第一段放關注清單 → 信件只放該報表自己的結論。
  - UI 規格 §4.3 l.92：調查頁事件＋流量時間軸 → 不做，寫明目前調查頁提供的是什麼。
  - D1：主規格 §7 遷移器對 5.x `traffic_filter`／`traffic_sampling` → 丟棄並在遷移報告列出（現行行為）。
- **過期條文更新**：報表分組、色票、守門路徑（`tests_v6/` → `tests/`）、「VEN 總覽未交付」、§7／§11／§12 稽核列出的各處。
- **§9 實機驗證**：六類找不到紀錄的逐條標成「已做（附紀錄位置）」或「未做」；未做的留在 §11 待使用者決定，不在本計畫補跑。
- **驗收** 修訂後逐條對照批次 B 的任務，B 的每一項在規格裡都找得到條文。

---

## 批次 B：補做功能（發 6.5.0）

### B1 封存讀回接進工作台

- **結果** 工作台查詢的時段早於保留期、而封存涵蓋該時段時，讀封存，不向 PCE 重拉；頁面寫明資料來自封存與涵蓋範圍。封存不涵蓋或未啟用時維持現行行為（向 PCE 拉）。
- **介面** `services/workbench_store.py` 的 `lease()`／`needs_pull()` 是唯一決定點；封存讀取沿用 `services/reports/generate.py:32` 已在用的 `archive_read`，不另寫一份（主規格 §6.3：單一實作）。`PullInfo` 加一個來源欄位。
- **檔案** `services/workbench_store.py`、`services/workbench.py`、`web/routes/` 工作台路由、`web/src/pages/workbench/`、兩語系檔、`tests/services/test_workbench_store.py`
- **驗收** 測試：保留期外＋封存涵蓋 → 不呼叫 `open_period`、列數等於封存內容；封存只涵蓋一半 → 寫明缺哪段，不當成完整。.106 實機：查一段已出保留期的時段，頁面顯示封存來源。
- **限制** 輕量模式的行為不變。告警偵測不讀封存（偵測只看近期視窗），在規格寫明。

### B2 內建報表「在工作台開啟」

- **結果** 15 型內建報表中，凡是某節的數字出自一個流量或事件條件的，都填 `workbench_link`（`render_html.py:180` 已會畫）；出自清冊或 PCE 政策的節不填。連結的網址基底用 `gui_external_url`，未設定時不畫連結。
- **介面** 照 `services/reports/custom.py:136` 的做法；連結內容是該節用的同一個 segment，不另組條件。
- **驗收** 每型報表一個測試：有流量節的報表至少一節有連結，且連結解回來的條件等於該節查詢條件。PDF／信件版連結可點。.106 重產全型別檢查。

### B3 橫向移動預設分析

- **結果** `domain/segment.py:221 lateral_default_segments` 接到產品：橫向移動頁（或工作台預設）顯示三組排行（管理埠的發起使用者、發起行程、系統帳號），報表「使用者與行程」一節用同一組 segment。
- **驗收** 測試：頁面與報表的排行來自同一個函式（守門：兩處都呼叫它，沒有各自的副本）。lab 上欄位覆蓋率低（約 5%），頁面寫明有多少流量帶使用者／行程資訊。
- **限制** 輕量模式照 §6.4 寫「需要告警或完整模式」。

### B4 資料可見度進報表

- **結果** 結論依賴主機流量的報表（readiness、勒索防護、橫向移動相關、policy_usage、自訂報表）加一段：有幾台主機的流量回報為 drops／off、是哪些，這些主機的數字不完整。沒有這類主機時不顯示該段。
- **介面** 一個共用 helper，讀清冊的 `visibility_level`，與首頁關注清單 `services/analysis/focus.py` 用同一個判斷（`BLIND`）。
- **驗收** 測試：2 台 flow_off 時報表列出 2 台；0 台時該段不存在。

### B5 「標為已知」

- **結果** 按下後，被標的那一則同時算已處理（不再留在未處理）；非橫向移動類的告警不顯示這個按鈕，或按 UI 規格擴到規格列的類型（執行時先讀 UI 規格對應條文，以條文為準）。
- **檔案** `services/alerts/known.py`、告警路由、`web/src/pages/alerts/`
- **驗收** 測試：標記後該則狀態改變、未處理數減一；之後同指紋的觸發照現行為不通知。

### B6 告警規則清單

- **結果** `web/src/pages/alerts/Rules.tsx` 清單加「條件」「排除」兩欄（一行摘要，過長換行不截斷）與類型篩選（UI 規格對應條文）。
- **驗收** 前端測試讀渲染後文字；e2e 在 1280 與 760 寬度下無水平溢出。

---

## 不在本計畫

- Low：KPI 上期比較、事件模式全文搜尋、SBOM、Ctrl/Cmd+K、保留期外回補——列入後續清單。
- §9 未做的實機驗證（見 C1）。

## 執行方式（建議）

- 批次 A、C：單一 agent 依序做，每個任務一個 commit，批次結束跑全閘門、部署兩台、發 6.4.5。
- 批次 B：六項互不相依，比照 6.4.0 的做法各開一條分支平行做，逐條合回、每合一條跑全閘門，最後部署與實機驗收、發 6.5.0。

## 代為決定的事

1. 5.x 文件搬到 `docs/legacy-5.x/`，不刪。
2. v6 REST API 參考由契約產生。
3. 封存讀回不接告警偵測，只接工作台。
4. 可見度段落只放在結論依賴流量的報表。
5. Low 項目與 §9 補跑不排進這次。
