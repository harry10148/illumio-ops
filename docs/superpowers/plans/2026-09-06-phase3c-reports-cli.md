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
- [ ] **5. 真資料驗證**：測試機重產 11 型 × 2 語系，取回 HTML，1280／800 截圖
      **並輸出一份 PDF**（Playwright `page.pdf()`）逐頁看。主色在灰階列印下是否
      仍可辨識，是這個任務唯一無法用測試回答的問題。
- [ ] **6. 全套＋commit＋部署＋CI**　`feat(report): the report shell moves to the v3 palette`

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
- [ ] **1. 先紅**：守門斷言圖表色盤 ⊆ shell.css 的 tone token 值，現況應為紅。
- [ ] **2. 實作＋綠**：`timeout 900 python3 -m pytest tests/test_report_chart_render.py tests/test_report_shell_renderer.py -q`
- [ ] **3. 真資料驗證**：重產帶圖表的報表型別，逐頁看圖例與色塊。
- [ ] **4. 全套＋commit＋部署＋CI**　`feat(report): chart colours come from the shell's tone tokens`

---

## Task 3 — CLI 主選單五區

**Outcome：** CLI 主選單與 GUI 同樣五區；告警與自動化合併成「規則」。

**Files:**
- Modify: `src/main.py`（`main_menu` 的六個 `main_menu_area_*` 與 `sel` 分派；
  `alerting_menu` 與 `automation_menu` 併成一個 policy 選單）
- Modify: `src/cli/menu_chrome.py`（docstring 的「六區」）
- Modify: i18n 三檔（`main_menu_area_*`、合併後選單的子項）
- Modify: `docs/reference/cli-flows.md`
- Modify: `tests/test_cli_flows_parity.py`（`_NEW_KEY_PREFIXES` 相關），以及任何
  斷言六個選項的 CLI 測試

**Constraint（Phase 2C 的教訓，見 `phase2c-cli-delivered` 記憶）：**
一致性**不得弱化既有閘門**。每一條被改動的斷言要寫明為什麼它的意義變了，不是
為了讓測試通過而放寬。

**Steps:**
- [ ] **1. 盤點**：`grep -rn "main_menu_area_\|alerting_menu\|automation_menu" src/ tests/ docs/`
      ——按概念列出所有表面再動手。
- [ ] **2. 先紅**：守門斷言主選單恰有五個區域項，現況六個。
- [ ] **3. 實作＋綠**：`timeout 900 python3 -m pytest tests/test_cli_flows_parity.py tests/test_cli_root_dispatch.py -q`
- [ ] **4. 真跑一次互動選單**，五個區各進一層確認沒有死路。
- [ ] **5. 全套＋commit＋部署＋CI**　`feat(cli): five areas, matching the GUI`

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
