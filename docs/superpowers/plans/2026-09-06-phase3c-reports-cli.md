# Phase 3C — 報表與 CLI 對齊 v3

> Roadmap `2026-09-03-ui-redesign-v3-roadmap.md` 的 3C。**範圍已縮小**：原本列的
> 「11 型真資料重產雙寬度逐頁驗」不是交付項，它在 Phase 2B（`2026-09-02`，見
> `phase2b-task7-acceptance-delivered` 記憶）就做過了——它是本計畫 Task 1 的
> **驗證步驟**，不是要做的事。剩下的是**配色對齊**與 **CLI 五區**。

## 為什麼還需要做

GUI 在 3B／3E 換到 v3 色票，報表與 CLI 沒跟上，今天的實際狀態：

| | 現況 | GUI v3 |
|---|---|---|
| 報表主色 | `#2A78D6`（藍） | `#FF5500` |
| 報表底色／線框 | 冷調中性灰 | `#F7F4EE` / `#E6E2DA` |
| 報表 CSS 來源 | `design/v2/reports/shell.css`，`port-marker: shell-css-port-v2` | — |
| CLI 主選單 | **六區** | **五區** |

## 使用者裁決（2026-09-06）

1. **一致到主色、底色、線框；內文墨色維持印刷黑 `#12161C`。** 報表會被列印，
   `#12161C` 印出來比 GUI 的暖調 `#313638` 實。主色在白底只有 3.2:1，所以
   **字與細線用深一階的 `#C24300`**（GUI 自己也是這樣分工）。
2. **CLI 六區合併成五區**：總覽→首頁、調查→調查、**告警＋自動化→規則**、
   報表→報表、系統→系統。

## Global Constraints

- 每任務＝乾淨 commit（英文 conventional commits）＋全套 pytest（排除
  `tests/test_cache_cli.py::test_cache_flush_json_output`）＋CI 綠＋部署測試機。
- 新 `gui_`／`cli_` 鍵同時寫進 `src/i18n_en.json`、`src/i18n_zh_TW.json`、
  `src/i18n/data/zh_explicit.json`。
- **色票不得寫死在 HTML `style=` 裡**；圖表那類 Python 端無法用 CSS var 的，
  集中成一份鏡射 token 的常數並加守門，不是散落的 hex。
- 本機截圖／驗證產物放 `tmp/phase3c-verification/`，不進 `tests/`。
- 專案 CLAUDE.md 的報表規則適用：**用真實樣本資料跑一次完整輸出，逐頁檢查**。

---

## Task 1 — 報表色票對齊，設計權威移到 v3

**Outcome：** 報表的視覺與 GUI 同一套（主色／底色／線框），內文維持印刷黑；
報表 shell 的設計權威從 v2 移到 v3；HTML 內嵌的寫死色票改用 token。

**Files:**
- New: `design/v3/reports/shell.css`（v3 token；tone 家族不動——那幾組本來就
  與主題無關，是「紙上也一樣的 LED」）
- Modify: `src/report/exporters/report_shell.py`（token 值換 v3；provenance 標頭
  改指 v3；`SHELL_CSS_PORT_MARKER` → `shell-css-port-v3`）
- Modify: `tests/test_report_shell_renderer.py`（`DESIGN_SHELL_CSS` 指向 v3）
- Modify: `scripts/audit_i18n_usage.py`（Cat C 豁免的字面 marker，第 90 行附近）
- Modify: `src/report/report_generator.py`、`src/report/exporters/audit_html_exporter.py`、
  `html_exporter.py`、`policy_diff_html_exporter.py`、`policy_usage_html_exporter.py`
  （HTML `style="color:#..."` 改 `var(--…)`）

**三處 marker 必須一起改**（照概念盤點，不是 grep 一個字）：定義、guard、audit
豁免。漏一處的症狀各不相同——guard 紅、或 audit Cat C 突然抓到 CJK。

**Steps:**
- [x] **1. 先紅**：建好 v3 shell.css 後把 `DESIGN_SHELL_CSS` 指過去，在還沒動
      `report_shell.py` 前跑 drift guard——拿到的是**內容不符**（token 值與標頭
      兩處都差），不是 FileNotFoundError。指向不存在的路徑那種紅太廉價，證明
      不了 guard 真的在比對內容。
- [x] **2. 實作**：建 v3 shell.css、換 token、改 marker、清 HTML 內嵌 hex。
      **marker 實際上是五處同步點，不是三處**：`report_shell.py` 的常數與標頭
      字面、`test_report_shell_renderer.py` 的 `_PORT_HEADER` 散文與
      `DESIGN_SHELL_CSS` 路徑、`audit_i18n_usage.py` 的 needle。drift guard 比對
      的是「常數 == `_PORT_HEADER` + 設計檔」，所以測試裡那段散文也是同步點。
      另有三處純散文：`report_shell.py` docstring、guard 的失敗訊息、
      `policy_usage_html_exporter.py:36` 的註解。
- [x] **3. 綠**：`timeout 900 python3 -m pytest tests/test_report_shell_renderer.py tests/test_report_export_hardening.py tests/test_print_button_all_exporters.py -q`
- [x] **4. 新守門**：`tests/test_report_no_hardcoded_colour.py`，**兩層**。
      原本計畫的 `style="…#RRGGBB…"` 正則看不到實際存在的三種寫法：`<style>`
      區塊裡的規則、餵給 `style=` 的 Python dict、以及 f-string 內插的變數。
      所以改成：(1) 逐檔 ratchet 數**任何**十六進位字面量，除五個寫明理由的
      豁免外一律 0；(2) 渲染層——用**打得開上色分支**的 fixture 產 HTML，斷言
      `<style>/<script>/<svg>` 以外沒有色值，**再加一條反向斷言**那些段落確實
      渲染了且用的是 token（否則第一條在該分支上是空砲）。兩層各自注入驗證過。
- [x] **5. 真資料驗證**：22 份全部 rc=0，`scripts/verify_report_render.py` 22/22
      PASS。灰階問題有答案：四階色塊最小間距**新 21、舊 14**（同法取樣兩份 PDF，
      不是用亮度公式估的），改善而非勉強維持。**語系切換的 config 路徑是
      `config/config.json` 不是 `config.json`**，屬主 `illumio-ops`——計畫與 2B
      報告都寫錯，第一次跑就是這樣失敗的。
- [x] **6. 全套＋commit＋部署＋CI**　`1ede8ea6`，4677 passed，CI `34021718804` success。
      **順手修掉一個既有的高嚴重度缺陷**：mod13 執行模式圖例的 f-string 裡把
      `STRINGS` fallback 寫成 `{{}}`（＝內含空 dict 的集合），分佈非空就 `TypeError`
      而 `_mod13_html` 沒有 caller 端保護 → 整份 security_risk 報表產不出來。潛伏自
      `633379d5`（2026-04-30）。**喚醒條件：任一環境的 workload 有非 idle 的
      enforcement mode。**
      另：`.gitignore` 裸的 `reports/` 會吃掉 `design/v3/reports/`，已比照
      `!design/v2/reports/` 補例外——漏掉的話 CI 會紅在本機重現不了的地方。

---

## Task 2 — 圖表色盤與 token 對齊，並鎖住不再漂移

**Outcome：** 圖表（matplotlib）與資料模型的語意色與 shell token 同源。

**Files:**
- Modify: `src/report/exporters/chart_renderer.py`（`success`/`warning`/`danger`/
  `info`、`allowed`/`blocked` 兩組）、`src/report/analysis/audit/audit_risk.py`
  （risk→色）、`src/report/report_generator.py`（severity→色）
- New: 一份集中常數（名稱沿用 `chart_renderer.py` 既有慣例），值鏡射 shell 的
  tone token

**Steps:**
- [x] **1. 先紅**：`tests/test_chart_palette_tokens.py`。
- [x] **2. 實作＋綠**（測試檔名是 `tests/test_chart_renderer.py`，計畫寫錯）。
      **範圍比計畫小**：`SIGNAL_COLORS`／`VERDICT_COLORS`／`RISK_COLOR`／`RISK_BG`
      四份色表**都沒有讀者**（HTML 早在 2B Task 6 改走 `data-tone`），活的只有
      `_SEMANTIC_COLORS` 與兩處 `#375379`。四份仍改成同源，因為下一個不能用 CSS 的
      消費端應該讀它們，而不是再發明第三份。
      **問題比計畫嚴重**：`_SEMANTIC_COLORS` 把 `low` 畫成綠色，而 HTML 徽章走的
      `SEVERITY_TONE` 是 `LOW → info` 藍——同一份報表對同一個嚴重度給兩種顏色。
- [x] **3. 真資料驗證**：六型重產，舊色盤八個值出現 0 次。**看圖才發現的一件事**：
      照抄殼的「實心 vs 外框」把 HIGH 畫淡是錯的——圓餅切片的顏色重量會被讀成量級，
      淡粉紅的 HIGH 比琥珀色的 MEDIUM 還輕，嚴重度排序在圖上被顛倒。改成同紅＋白色
      斜線網底（灰階也分得出來）。
- [x] **4. 全套＋commit＋部署＋CI**　`3b68e04c`，4686 passed，CI `34024386527` success。
      追加 `75352810`：網路圖連線用的是 matplotlib 具名色 `"gray"`，色盤守門只找
      十六進位所以看不到它——守門已擴充成掃所有顏色參數。

---

## Task 3 — CLI 主選單五區

**Outcome：** CLI 主選單與 GUI 同樣五區；告警與自動化合併成「規則」。

**Files:**
- Modify: `src/main.py`（`main_menu` 的六個 `main_menu_area_*` 與 `sel` 分派；
  `alerting_menu` 與 `automation_menu` 併成一個 policy 選單）
- Modify: `src/cli/menu_chrome.py`（docstring 的「六區」）
- Modify: i18n 三檔（`main_menu_area_*`、合併後選單的子項）
- ~~Modify: `docs/reference/cli-flows.md`~~ —— **這個檔不存在**。真正的流程規格是
  `design/v2/cli-flows.md`（95KB），它 2026-09-04 就註記「CLI 對齊五區在 3C，屆時
  另立 v3 版流程規格」。新增 `design/v3/cli-flows.md`**只寫差異**，v2 加註指過去
- Modify: `tests/test_cli_flows_parity.py`（`_NEW_KEY_PREFIXES` 相關），以及任何
  斷言六個選項的 CLI 測試

**Constraint（Phase 2C 的教訓，見 `phase2c-cli-delivered` 記憶）：**
一致性**不得弱化既有閘門**。每一條被改動的斷言要寫明為什麼它的意義變了，不是
為了讓測試通過而放寬。

**Steps:**
- [x] **1. 盤點**：80 處。最重要的一項 grep 這條抓不到：`cli_area_alerting`／
      `cli_area_automation` 是**所有精靈的麵包屑前綴**，散在六個檔共 25 處。
- [x] **2. 先紅**：斷言**畫出來的**區域列恰五條（只驗分派表的話，多印一行按下去
      沒反應的死選項照樣綠）＋`safe_input` 接受的集合是 `{1..5,g,G,0}`。
- [x] **3. 實作＋綠**。既有斷言的意義變更逐條記在 `tmp/phase3c-verification/report.md`
      §3.5，全部是改名或換編號，**沒有一條被放寬**。63 項對照表不減項——它本來就會驗
      「它指的測試還存在」，這次確實是它抓出改名漏網的。
- [x] **4. 真跑一次互動選單**：五區逐一進一層，無死路；規則區 1-9＋10/11 全在。
      **這一步抓到一個潛伏數月的既有缺陷**：首頁印著原始樣板
      `語言: {lang} | 佈景: {theme}`——`t(key, *, lang=…)` 把 `lang=` 當語言選擇器
      吃掉，`{lang}` 永遠填不進去，而 `t()` 的 except 吞掉 KeyError 回傳原始樣板。
      i18n audit 檢查「鍵能不能解析」，不檢查「呼叫端能不能填」。已修＋守門從
      `inspect.signature(t)` 推導保留字。
- [x] **5. 全套＋commit＋部署＋CI**　4689 passed。

---

## 自審

- **範圍**：roadmap 的 3C 有三項，其中「11 型重產逐頁驗」已由 2B 完成，本計畫
  將它降為 Task 1 的驗證步驟並在標頭寫明，避免與 roadmap 各說各話。
- **順序**：T1 是 T2 的相依（tone token 要先定案於 v3 才有東西可鏡射）；T3 獨立，
  排最後是因為它是唯一會改變操作流程的一項。
- **未展開實作碼**：三個任務的斷言對象都是既有測試檔的既有形狀，實作者以
  `tests/test_report_shell_renderer.py` 的 guard 為樣板。
- **風險**：Task 1 的真資料重產需要測試機能連到 PCE；若當下不可用，改用
  `design/v2/snapshots/` 的既有快照產出，並在報告中寫明用的是快照而非真機。
