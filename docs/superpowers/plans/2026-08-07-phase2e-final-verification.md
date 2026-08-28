# Phase 2E — 全案終驗與收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** UI redesign v2 全案收斂：docs 全面更新、版本號＋CHANGELOG、離線 bundle 打包與內容驗證（Linux+Windows parity）、測試機部署、以 `design/v2/coverage.yaml` 102 項為底稿的真機全遍歷驗證報告（含 11 型報表真資料重產逐頁驗）、殘項總清點與裁決建議。

**Architecture:** 這是驗證與收尾計畫，不是功能計畫——除 docs／CHANGELOG／版本號外**不改產品程式碼**。若驗證中發現 bug：High 當場修（獨立 commit＋回歸測試），Medium 以下進 T6 殘項總表出裁決建議。所有真機證據落在 `tmp/phase2e-verification/`（gitignored），最終以一份驗證報告交付使用者。

**Tech Stack:** pytest＋Playwright（既有 env-gated 真機模式）、`scripts/build_offline_bundle.sh`、`scripts/docs_check.py`、`scripts/bump_version.sh`、`tools/gate_coverage_live.py`（2A T11 產出）。

## 入場條件（未全數成立不得開工）

- [ ] 2A、2B、2C、2D 四個子計畫全部合入 main（各計畫最後一個任務的 commit 都在 `git log main` 上可指認）
- [ ] main CI 綠：`gh run list --branch main --limit 3` 最新 run 為 `completed success`
- [ ] 本機主 checkout 乾淨且在 main：`git -C /home/harry/rd/illumio-ops status --porcelain` 為空、`git branch --show-current` = main
- [ ] 全套測試本機綠：`pytest -q` 0 failed（記下總數作為本計畫基線）
- [ ] 2A T12 的真機驗證報告存在（`tmp/phase2a-verification.md` 或其 CHANGELOG 摘要）——2E 是跨階段總驗，不重複 2A 自身驗收，但要能引用它


## 2026-08-28 執行前必讀（過期稽核結論 ＋ 拆分建議）

本計畫寫於 2026-08-07，前提是「2A–2D 完成」。**實際上 2A 已出貨，2B/2C/2D 從未執行**
（2D 已由 `docs/superpowers/plans/2026-08-28-product-bug-backlog-v2.md` 取代）。
照原樣整份等下去，等的是三個不會以現狀執行的計畫。

### ★ 建議拆成兩半

**2E-now（今天就能跑，不依賴任何未執行的計畫）**

1. **T4 Step 1**（部署測試機到當前 main）——**必須先跑**，因為 T1 的 gui-tour 改寫是對著
   實機寫的。原計畫把 T1 排在 T4 之前，那是假設 2A T12 剛部署過。
2. **T1**，扣掉 `cli.md` 選單那一列（那列要等 2C）。這是價值最高且幾乎無依賴的一塊——
   它會把目前**紅著**的 `docs_check` 轉綠。
3. **T3 改寫成 Linux-only**（見下）＋ **T4 Step 2** bundle smoke。完全獨立。
4. **T5 的自動化層**——v2 e2e 套件 ＋ `tools/gate_coverage_live.py` 跑到 101/101，
   當作記錄下來的基準。

**2E-final（真的要等）**：T5 的人工遍歷當作**驗收閘門**（目前有 13 條已知缺陷，會產生
預期中的 FAIL——當成盤點可以，當成驗收不行）、RP-02 的參數交叉檢查（要等 2B）、以及整個 T6。

### T3 改寫：Windows parity 已死

`scripts/build_offline_bundle.sh` 今天**零 Windows 參照**，只產出一個產物。

**照原樣存活**：Step 1 的 pre-flight grep；Step 2 建置；檢查 (3) design/ 洩漏、
(4) 金鑰材料、(5) 鎖檔存在、(6) `cryptography-50.*`。

**要更正**：
- **(1)** `app/src/static/js/v2/` 的預期數量是 **29**（`git ls-files src/static/js/v2 | wc -l`），
  不是「≥26」。`templates/v2/` **從未存在過**——v2 是走 `src/templates/index.html` ＋ `login.html`。
- **(2) 必須反轉。** `src/templates/index.html` **現在就是 v2 shell**（載入 `css/v2/*` ＋
  `js/v2/app.mjs`，已查證 4 處引用）。斷言它不存在會**誤報洩漏**。改成：斷言
  `app/src/templates/{index,login}.html` **存在**；斷言
  `app/src/static/js/{dashboard,settings,integrations,quarantine,rule-scheduler,filter-bar}.js`
  與 `app/src/static/css/app.css` **不存在**（這些確實已隨 2A 刪除）。
- **Step 2 的日誌預期**：`OK (<sha256>)` 只會出現**一次**不是兩次；
  `"ERROR: missing Windows-only wheel"` 已不存在，刪掉這條預期。

**已死、必須替換**：ZIP 產出、`$ZIP`/`win.lst`、檢查 (7) app/ parity diff、
檢查 (8) wheel 集合差集 `{colorama, win32_setctime}`、以及 T4 Step 3。

**替換成同等強度的兩條 Linux-only 不變量**：
1. **app/ 子樹完整性**——`app/src/**` 等於 `git ls-files src/`（扣掉腳本自身的 exclude），
   加上三個已知的額外 staged 項（`app/scripts/` 整個目錄、
   `app/docs/_meta/illumio-event-reference.json`、`app/requirements-offline.lock`）。
   這守的正是 (7) 原本在守的東西：「staged 的比 repo 裡的少」。
2. **wheels ↔ lock 對帳**——`wheels/` 下的套件名集合等於 `requirements-offline.lock` 的套件集合。
   這是 (8) 在沒有第二個平台可比之後的殘值。
3. **新增一條反向閘門**（比照 `tests/test_windows_host_removed.py`）：tarball 內任何地方
   都不得出現 `win_amd64`、`.ps1`、`nssm`。

### T2 版本號：只剩時機問題，數字已定

**5.0.0 已經寫進 `CHANGELOG.md`** 的 `### Removed`（Windows 移除那段明寫
「This makes the next release a major version (5.0.0)」）。所以 T2 Step 1 的
「向使用者確認 5.0.0 vs 4.2.0」要改成**時機**問題：現在就 cut，還是等
backlog-v2／2B／2C 落地。Step 3 的「Fixed：2D 的 18 條」要改成 backlog-v2 的 13 條。

**另外注意**：`## [Unreleased]` 已累積到 **704 行、15 個重複小標**
（4 個 `### Added`、3 個 `### Changed`、6 個 `### Fixed`、2 個 `### Removed`）。
T2 要先整併這些小標，否則發版說明會有四個 Added 區塊。

### 其他已查證的事實更正

- **`design/v2/coverage.yaml` 是 101 項不是 102**（OV16/IV15/AL14/AU13/RP9/SY17/LG3/XC14）。
  `SY-01: PCE profiles CRUD/切換` 已隨 profile 移除刪除（`baac0908`）。
- **`tests/test_gui_e2e*.py` 不存在**（2A 的 `df67e358` 刪除），T5 Step 1 的 pytest 選擇器
  收集不到東西。Global Constraints 引用的 `tests/test_gui_e2e_playwright.py:14-41` 也是死參照，
  慣例現在在 `tests/v2_e2e_utils.py`。
- **`tests/test_v2_*.py` 是 in-process 的**，自建 Flask app——**它們不是真機測試**，
  把 `ILLUMIO_OPS_E2E_BASE_URL` 指到測試機不會讓它們變成真機測試。
  只有 `tests/test_e2e_dashboard_story.py` 打真實 appliance。
- **`tools/gate_coverage_live.py` 吃的是 `--base-url` / `--username` / `--password` 旗標**，
  不是 `ILLUMIO_OPS_E2E_*` 環境變數；不給 `--base-url` 它會自建臨時 app，
  所以覆蓋率閘門今天就能跑，不需要測試機。
- **報表型別 11 種，但 HTML 殼只有 10 種**（`policy_resolver` 只有 JSON/CSV）。
  且**產品沒有伺服端 PDF**——PDF 驗收＝print CSS ＋ Playwright print-to-PDF。
- **`docs_check.py` 不是 CI 閘門**（CI 只跑 `check_doc_links.py`）。用計畫指定的
  `--all --exclude 'superpowers/**' --exclude 'ux-review*'` 跑，目前是 **19 findings**
  （11 freshness／1 frontmatter／7 verified_against），exit 1。

### coverage.yaml 的潛在陳舊（閘門抓不到）

- **SY-18**（設定 dirty 追蹤）仍指向 `#/system/pce`——**那個頁面已不存在**。
  它之所以通過，是因為 anchor 是跨路由 set-union 比對。人工檢查表必須改在一個still存在的頁面上驗 dirty 追蹤。
- **IV-02** 仍寫「流量來源切換 即時快取/Archive」——2F-1 已改成**三種**來源
  （cache-first／direct PCE／archive streaming），行號引用也已失效。
- **IV-06** 的「ssh 抽查 sqlite」已死——review DB 已移除，archive 現在直接串流每日檔案。

## Global Constraints（每任務隱含適用）

- **執行時以當下原始碼為準**：本計畫撰於 2A–2D 執行前，引用的行號／檔名（尤其 2A T11 切換後的 v2 檔案路徑、2B/2C 的產出）一律先 `git grep` / `ls` 實測再用，不盲信本文
- 測試機 = `172.16.15.106`（GUI `https://172.16.15.106:5001`，checkout 於 `root@172.16.15.106:/root/illumio-ops`，systemd unit `illumio-ops`）
- 真機 e2e 環境變數慣例：`ILLUMIO_OPS_E2E_BASE_URL` / `ILLUMIO_OPS_E2E_USER` / `ILLUMIO_OPS_E2E_PASSWORD`（見 `tests/test_gui_e2e_playwright.py:14-41`）
- **憑證不落檔、不印出**：密碼一律 `op read op://Lab/<item>/<field>` 於單一指令生命週期注入（item 名以 1Password Lab vault 現況為準）；禁止 export 進 shell rc、禁止出現在任何 commit / 報告 / 截圖
- 報表驗收遵守專案 CLAUDE.md 硬規則：**真資料**重產、**逐頁**檢查截斷/溢出、檢查結果附在回報裡
- Commit 一律英文 conventional commits（docs: / chore(release): / fix: / test:）
- 證據目錄：`mkdir -p tmp/phase2e-verification/`（gitignored；截圖、清單 diff、pytest 輸出全放這裡）
- 發現 bug 的處置線：High（資料錯誤/安全/功能斷裂）當場修＋測試＋獨立 commit；Medium/Low 記入 T6 總表，不擅自修（避免驗證期擴散改動面）

## File Structure

```
docs/guide/*.md、docs/reference/*.md、docs/handover/*.md、docs/INDEX.md   # T1 更新
CHANGELOG.md、src/__init__.py、README.md、README_zh.md                    # T2 版本
（scripts/build_offline_bundle.sh 預期零改動——src/ 全量 rsync 已自動涵蓋
  v2 資產、design/ 從未入列；T3 只加「驗證」不加「打包邏輯」，除非驗證抓到缺口）
tmp/phase2e-verification/
  bundle/            # 清單 diff、parity 輸出
  traversal/         # 102 項勾稽表（filled）、六區×雙主題截圖
  reports/           # 11 型報表逐頁檢查紀錄＋截圖
  phase2e-report.md  # 最終驗證報告（交使用者）
```

---

### Task 1: docs 全面更新（逐檔盤點結果＋docs_check 守門）

**Files:**
- Modify: `docs/guide/gui-tour.md`（全檔重寫）
- Modify: `docs/reference/rest-api.md`、`docs/reference/cli.md`、`docs/reference/glossary.md`
- Modify: `docs/guide/automation.md`、`docs/guide/siem.md`、`docs/guide/troubleshooting.md`、`docs/guide/reports.md`、`docs/guide/cache-maintenance.md`、`docs/guide/monitoring-alerts.md`
- Modify: `docs/handover/development.md`、`docs/handover/pce-domain-notes.md`
- Modify: `docs/INDEX.md`；核對 `README.md` / `README_zh.md`、`docs/guide/installation.md`、`docs/guide/configuration.md`、`docs/handover/architecture.md`（預期輕量或零改）

**Interfaces:**
- Produces: 全部 docs 的 `last_verified: 2026-08-XX`（執行當日）＋修正後的 `verified_against`（T2 會再 sed `version:` 欄位）；`docs_check.py --all` exit 0（T2/T6 依賴）

**逐檔盤點（2026-08-07 對 main 實測 grep 的結果；執行時重跑確認）：**

| 檔案 | 現況問題 | 動作 |
|---|---|---|
| `docs/guide/gui-tour.md` | 全檔以「8 個分頁」結構撰寫（L32、L142「分頁逐一導覽」8 節）；frontmatter `verified_against` 引用 2A T11 已刪檔：`src/templates/index.html`、`src/static/js/{dashboard,integrations,settings,quarantine,filter-bar}.js` | **全檔重寫**成六區導覽（overview／investigate／alerting／automation／reports／system＋登入＋Cmd-K／健康列等跨域機制）；`verified_against` 改列 v2 實檔（`src/templates/v2/base.html`、`src/static/js/v2/areas/*.mjs` 等，以 `git ls-files src/templates src/static/js` 實況為準）；高風險動作彙整節保留並對齊新 UI 位置 |
| `docs/reference/rest-api.md` | L119「端點總覽（依 GUI 分頁分區）」按 8 分頁分 8 節；L130 敘述 `index.html` 殼頁 | 端點本身零變（2A 後端零改動）；分區標題改六區、殼頁敘述改 v2；26 處分頁字樣逐一改寫 |
| `docs/reference/cli.md` | `### shell`（L592-611）互動選單敘述為舊選單結構；「僅選單可用功能」清單（TLS／PCE profiles／rule scheduler config） | 對齊 2C 重組後的選單結構（`design/v2/cli-flows.md` 63 項對照、36 畫面為規格，但以 2C 合入後的實際程式為準）；click 子指令段落不動（2C 未改） |
| `docs/guide/automation.md` | `verified_against` 引用將刪的 `src/static/js/rule-scheduler.js`；L27/L43 分頁引用 | 改指 v2 automation 區模組；分頁字樣改「Automation 區」 |
| `docs/guide/siem.md` | 6 處「Integrations 分頁」引用 | 改「System 區 SIEM 子頁」（依 coverage SY-07..SY-10 的實際 IA） |
| `docs/guide/troubleshooting.md` | 5 處分頁引用 | 逐處改為新區位 |
| `docs/handover/development.md` | `verified_against` 引用 `src/static/js/dashboard.js`；L262 報表檔名前綴段引用 dashboard.js L241-250；前端架構節仍述舊 17 支 JS | 前綴邏輯改指 v2 對應模組（實測 `git grep -n "Illumio_Traffic_Report_" src/static/js/v2/`）；前端架構節改述 v2（zero-build ES modules、core/components/areas 三層）；§2.4 docs 檢查說明核對 |
| `docs/reference/glossary.md` | 3 處分頁詞 | 逐處改寫 |
| `docs/guide/reports.md` | 1 處 GUI 位置引用；2B 換新報表殼後外觀敘述可能過期 | 對照 2B 實際產出核對外觀／章節敘述 |
| `docs/guide/cache-maintenance.md`、`docs/guide/monitoring-alerts.md`、`docs/handover/pce-domain-notes.md` | 各 1 處分頁/前端引用 | 逐處改寫 |
| `docs/INDEX.md` | `last_verified: 2026-07-17`、文件說明段 | 更新日期與任何過期敘述 |
| `README.md` / `README_zh.md` | grep 無分頁結構字樣；版本 badge 由 T2 腳本處理 | 核對 GUI 描述段（README_zh L21/L69）仍為真即可 |
| `docs/guide/installation.md`、`docs/guide/configuration.md`、`docs/handover/architecture.md` | grep 0 命中 | 通讀確認後僅更新 `last_verified` |

- [ ] **Step 1: 重跑盤點確認現況**（2A–2D 可能已順手改過部分文件）

```bash
cd /home/harry/rd/illumio-ops
grep -rnE "分頁|index\.html|static/js/(dashboard|settings|integrations|quarantine|rule-scheduler|filter-bar)\.js|switchTab" docs/ README*.md | grep -v superpowers | sort > tmp/phase2e-verification/docs-stale-refs.txt
wc -l tmp/phase2e-verification/docs-stale-refs.txt   # 逐行處理，清單即工作項
python scripts/docs_check.py --all --exclude 'superpowers/**' --exclude 'ux-review*'  # 記下起點狀態（verified_against 懸空路徑此時預期已在報錯——2A 刪檔後即發生）
```

- [ ] **Step 2: 依上表逐檔改寫**。gui-tour.md 重寫時**開真機對照寫**（`https://172.16.15.106:5001`，2A T12 部署後的版本），禁止照 mockup 或記憶寫；每檔更新 frontmatter `last_verified` 為執行當日、`verified_against` 逐條確認 `test -e` 存在
- [ ] **Step 3: 守門全過**

```bash
python scripts/docs_check.py --all --exclude 'superpowers/**' --exclude 'ux-review*'   # 期望 exit 0（bilingual/freshness/frontmatter/verified_against 路徑/links 全過）
python scripts/check_doc_links.py                                                     # CI 硬閘門，期望 exit 0
pytest tests/test_docs_check.py -q                                                    # 期望全過
grep -rnE "index\.html|static/js/dashboard\.js|switchTab" docs/guide docs/reference docs/handover   # 期望空
```

- [ ] **Step 4: Commit**

```bash
git add docs/ README.md README_zh.md
git commit -m "docs: update all user and handover docs for UI redesign v2"
```

---

### Task 2: 版本號＋CHANGELOG

**Files:**
- Modify: `src/__init__.py`（`__version__`）、`CHANGELOG.md`、`README.md`／`README_zh.md`（badge，腳本自動）、docs frontmatter `version:` 欄

**Interfaces:**
- Consumes: T1 完成的 docs（`version:` 欄一起換）
- Produces: 新版本號（T3 bundle 檔名、T6 tag 依賴）。**建議 `5.0.0`**：全 GUI 置換＋CLI 互動選單重組屬使用者可感知的破壞性 UX 變更，慣例升 major；若使用者裁定走 `4.2.0` 亦可，僅替換下方所有 `5.0.0` 字樣（開工前向使用者確認一次）

- [ ] **Step 1: 版本裁決確認**——向使用者一句話確認 `5.0.0` vs `4.2.0`，取得答覆再動手
- [ ] **Step 2: bump（--no-tag，tag 留到 T6 全綠後）**

```bash
scripts/bump_version.sh 5.0.0 --no-tag   # 改 __init__.py + 插 CHANGELOG 空節 + README badge，不 commit 不 tag
```

- [ ] **Step 3: 填 CHANGELOG**。把現有 `## [Unreleased]` 內容併入新的 `## [5.0.0] — <日期>` 節，並補全案摘要，至少涵蓋：
  - Added/Changed：六區 v2 GUI 全面取代 8 分頁 SPA（2A）；11 型報表統一新殼（2B）；CLI 互動選單依 36 畫面重組（2C）
  - Fixed：2D 的 18 條產品 bug 逐條一行（從 2D 計畫／commit log 抄實際內容，不寫「various fixes」）
  - Removed：舊前端檔（index.html＋17 支 JS＋app.css）、`enable_v2_preview` 旗標
  - 保留頂部空的 `## [Unreleased]` 節
- [ ] **Step 4: docs frontmatter version 欄同步**

```bash
grep -rln "^version: 4\.1\.0" docs/ | xargs sed -i 's/^version: 4\.1\.0/version: 5.0.0/'
python scripts/docs_check.py --all --exclude 'superpowers/**' --exclude 'ux-review*'   # 仍 exit 0
```

- [ ] **Step 5: 驗證＋Commit**

```bash
scripts/resolve_version.sh          # 期望輸出 5.0.0+<hash>（未 tag 的 dev 型式）
pytest -q                           # 全綠（版本字串有測試覆蓋的話會抓到漏改）
git add src/__init__.py CHANGELOG.md README.md README_zh.md docs/
git commit -m "chore(release): prepare v5.0.0 changelog and version bump"
```

---

### Task 3: 離線 bundle 打包＋內容驗證＋Linux/Windows parity

**Files:**
- 預期 **不改** `scripts/build_offline_bundle.sh`：讀碼結論——`stage_app()`（L109-148）對 `src/` 全量 rsync，v2 的 `templates/v2/`、`static/js/v2/`、`static/css/v2/` 自動入列；`design/` 從未被 stage，mockup／snapshots 依構造不可能洩入。**但若下列驗證任何一條失敗，缺口就修在 build 腳本並補守門**
- Create: `tmp/phase2e-verification/bundle/verify_bundle.sh`（下方驗證指令集結成可重複腳本；不進 repo，最終報告附全文）

**Interfaces:**
- Consumes: T2 的版本號
- Produces: `dist/illumio-ops-5.0.0+<hash>-offline-{linux-x86_64.tar.gz,windows-x86_64.zip}`（T4 部署用）；驗證腳本（T6 最終重建後重跑同一支）

- [ ] **Step 1: 打包前置檢查**

```bash
cd /home/harry/rd/illumio-ops
# 防「runtime 讀 repo 相對路徑但沒入 bundle」的 FileNotFoundError 前例
#（build 腳本 L141-146 的 illumio-event-reference.json 就是這樣補的）：
git grep -n "design/v2" -- src/        # 期望空——store-map.mjs 是「轉錄」endpoints.yaml，不是 runtime 讀
git grep -nE '"(docs|design|tests)/' -- src/ | grep -v "_meta/illumio-event-reference"   # 期望空；有命中則逐條判定是否需入 bundle
ls src/static/vendor/ 2>/dev/null      # 2A 規劃維持空；若 2B/2C 期間放了字型/資產，確認 rsync 涵蓋（src/ 全量，涵蓋）
```

- [ ] **Step 2: 打包**

```bash
scripts/build_offline_bundle.sh 2>&1 | tee tmp/phase2e-verification/bundle/build.log
# 內建關卡本身就是驗證點，確認 log 含：
#   "requirements-offline.lock is in sync"（鎖檔新鮮度 gate）
#   兩個 "OK (<sha256>)"（PBS 直譯器 in-tree pin 驗證）
#   無 "ERROR: key material"（assert_no_secrets_staged）
#   無 "ERROR: missing Windows-only wheel"（colorama/win32_setctime 守門）
```

- [ ] **Step 3: 內容驗證（寫成 verify_bundle.sh，每條有明確 pass 條件）**

```bash
V=$(scripts/resolve_version.sh)
TAR=dist/illumio-ops-${V}-offline-linux-x86_64.tar.gz
ZIP=dist/illumio-ops-${V}-offline-windows-x86_64.zip
OUT=tmp/phase2e-verification/bundle
tar tzf "$TAR" | sed 's|^[^/]*/||' | sort > "$OUT/linux.lst"
unzip -Z1 "$ZIP" | sed 's|^[^/]*/||' | sort > "$OUT/win.lst"

# (1) v2 前端資產在內（路徑以 2A T11 切換後 git ls-files 實況為準）
grep -c '^app/src/static/js/v2/'  "$OUT/linux.lst"       # 期望 ≥ 26（core 9＋components 10＋areas 7＋app.mjs；以實檔數為準）
grep    '^app/src/static/css/v2/tokens.css' "$OUT/linux.lst"   # 期望命中
grep -c '^app/src/templates/'     "$OUT/linux.lst"       # v2 模板（base.html、login.html）全在

# (2) 舊前端已不存在（2A T11 刪檔後不應回魂）
grep -E '^app/src/(templates/index\.html|static/js/dashboard\.js|static/css/app\.css)' "$OUT/linux.lst" && echo LEAK || echo OK   # 期望 OK

# (3) design/v2 零洩入（mockup、snapshots、pitch、tour 全不得出現）
grep -E 'design/|mockup|snapshot' "$OUT/linux.lst" "$OUT/win.lst" && echo LEAK || echo OK   # 期望 OK

# (4) 無憑證/金鑰（對「產物」複驗，不只信 build 期 gate）
grep -E 'config/config\.json$|config/alerts\.json$|config/tls/|\.pem$|\.key$|\.p12$|\.pfx$' "$OUT/linux.lst" "$OUT/win.lst" && echo LEAK || echo OK   # 期望 OK（*.example 允許）

# (5) lock 在內
grep '^app/requirements-offline.lock' "$OUT/linux.lst" && grep '^app/requirements-offline.lock' "$OUT/win.lst"   # 皆命中

# (6) cryptography wheel（兩平台皆備、版本符合 lock 的 >=50 釘選）
grep -E '^wheels/cryptography-50\.' "$OUT/linux.lst"   # manylinux wheel
grep -E '^wheels/cryptography-50\.' "$OUT/win.lst"     # win_amd64 wheel

# (7) Linux/Windows parity：app/ 子樹逐檔一致（wheels/deploy/安裝腳本平台各異，app/ 必須相同）
grep '^app/' "$OUT/linux.lst" > "$OUT/linux-app.lst"
grep '^app/' "$OUT/win.lst"   > "$OUT/win-app.lst"
diff "$OUT/linux-app.lst" "$OUT/win-app.lst"           # 期望輸出空

# (8) wheels 套件名集合 parity：允許差集僅 {colorama, win32_setctime}（Windows-only）
for side in linux win; do grep '^wheels/' "$OUT/$side.lst" | sed 's|^wheels/||; s/-[0-9].*//' | sort -u > "$OUT/$side-pkgs.lst"; done
diff "$OUT/linux-pkgs.lst" "$OUT/win-pkgs.lst"          # 期望只有 "> colorama" 與 "> win32_setctime"；其餘差異一律追查
```

- [ ] **Step 4: 任一條失敗 → 修 build 腳本＋在 `tests/` 補對應守門測試＋commit `fix(offline): ...` 後回 Step 2 重打包**；全過則把 8 條輸出存檔進 `$OUT/` 並在 ledger 記錄

---

### Task 4: 部署——測試機 git 部署＋Linux bundle 安裝 smoke

**Interfaces:**
- Consumes: T3 產物
- Produces: 測試機跑最新 main（T5 遍歷對象）；bundle 可安裝性證據

- [ ] **Step 1: 測試機 git 部署（T5 遍歷用；測試機常態即 git-based systemd 服務）**

```bash
ssh root@172.16.15.106 'cd /root/illumio-ops && git pull --ff-only && systemctl restart illumio-ops && systemctl is-active illumio-ops'
ssh root@172.16.15.106 'cd /root/illumio-ops && git rev-parse --short HEAD'   # 必須 == 本機 main HEAD
curl -ksSo /dev/null -w '%{http_code}\n' https://172.16.15.106:5001/          # 期望 200（登入頁）
```

- [ ] **Step 2: Linux bundle 安裝 smoke（乾淨環境，不碰測試機——install.sh 會寫 systemd unit，蓋掉測試機的 git-based 服務）**。首選：帶 systemd 的拋棄式 VM/container（比照 offline-bundle-db-hardening 案的驗證環境），完整跑 `preflight.sh`＋`install.sh`＋服務啟動＋`curl` 登入頁。若手邊無 systemd 環境，fallback 為容器內驗證安裝鏈的非 systemd 段：

```bash
S=/tmp/claude-1000/-home-harry-rd-illumio-ops/5e19ec90-7e6d-4cf8-af08-24d70ddcadc4/scratchpad/bundle-smoke
mkdir -p "$S" && tar xzf dist/illumio-ops-*-offline-linux-x86_64.tar.gz -C "$S"
cd "$S"/illumio-ops-*-offline-linux-x86_64
./preflight.sh --install-root "$S/opt" || true       # 記錄輸出（非 root 會有預期內 warn）
# 複刻 install.sh L224-227 的離線安裝（--no-index：證明 wheels 自足、hash 全過）
./python/bin/python3 -m pip install --no-index --find-links wheels --require-hashes -r app/requirements-offline.lock --quiet
./python/bin/python3 app/scripts/verify_deps.py --offline-bundle    # 期望 exit 0
(cd app && ../python/bin/python3 illumio-ops.py --help >/dev/null && echo SMOKE-OK)   # 期望 SMOKE-OK
```

- [ ] **Step 3: Windows 側**——T3 的 parity＋win wheels＋NSSM 內容驗證為本計畫閘門；**真 Windows 安裝驗證列 T6 殘項**（需使用者提供 Windows 主機授權；比照過往「需授權真環境驗證」清單處理，2026-07-12 案已全過一輪，本輪差異僅 app/ 內容）
- [ ] **Step 4: 證據入 `tmp/phase2e-verification/bundle/`**（smoke 輸出全文）；無 commit（本任務不動 repo）

---

### Task 5: 真機全遍歷驗證（102 項勾稽＋截圖）＋11 型報表真資料重產逐頁驗

**Interfaces:**
- Consumes: T4 部署完成的測試機
- Produces: `tmp/phase2e-verification/traversal/checklist.md`（下表 filled，逐項 PASS/FAIL/N-A＋備註）、六區×雙主題截圖、`reports/` 逐頁檢查紀錄——全部進 T6 最終報告

- [ ] **Step 1: 自動層——真機全 e2e＋覆蓋 gate**

```bash
cd /home/harry/rd/illumio-ops
ILLUMIO_OPS_E2E_BASE_URL=https://172.16.15.106:5001 \
ILLUMIO_OPS_E2E_USER=illumio \
ILLUMIO_OPS_E2E_PASSWORD="$(op read 'op://Lab/illumio-ops-testbox/password')" \
pytest tests/test_v2_*.py tests/test_gui_e2e*.py -v 2>&1 | tee tmp/phase2e-verification/traversal/e2e.log
# 期望 0 failed；輸出親驗（記憶 subagent-full-suite-verification：數字要親看，不信轉述）

ILLUMIO_OPS_E2E_BASE_URL=https://172.16.15.106:5001 \
ILLUMIO_OPS_E2E_PASSWORD="$(op read 'op://Lab/illumio-ops-testbox/password')" \
python tools/gate_coverage_live.py 2>&1 | tee tmp/phase2e-verification/traversal/coverage-live.log
# 期望 102/102（gate_coverage_live 為 2A T11 產物；旗標/呼叫方式以實檔 --help 為準）
```

- [ ] **Step 2: 人工層——以下逐區檢查表在真機逐項操作勾稽**（表即底稿，複製到 `traversal/checklist.md` 填 PASS/FAIL；「檢點」欄是最低操作標準，不是全部）。破壞性動作規範：隔離 apply/lift、TLS 續期/匯入、daemon restart、GUI stop、watermark 重置、run-once **只驗到確認 modal 出現後取消**；CRUD 類用 `e2e-` 前綴資料並當場清理。

**Overview（16 項，`#/overview`）**

| ID | 項目 | 檢點 |
|---|---|---|
| OV-01 | 系統狀態總覽卡 | daemon/GUI/排程欄位=真值（與 `systemctl status` 對照） |
| OV-02 | posture score 卡+詳情 | 分數非 `?`（中文機 hero 恆 0 為 2D bug#4，驗已修）；詳情 drawer 開合 |
| OV-03 | Top Actions 區 | 有內容且項目可跳轉（2D bug#5 死碼案的替代實作） |
| OV-04 | 自訂查詢卡 CRUD | 建 `e2e-q1` → 出現 → 刪除 → 消失 |
| OV-05 | Top10 查詢 | 送出查詢，結果非空或有誠實空態 |
| OV-06 | audit 摘要卡 | 數字與 `#/investigate/events` 一致性抽查 |
| OV-07 | policy usage 摘要卡 | 載入無錯誤卡 |
| OV-08 | dashboard snapshot | 渲染完整、無 NaN/undefined |
| OV-09 | 報表最近產出 meta | 與 `#/reports` 產出清單一致 |
| OV-10 | pipeline 健康摘要 | 唯讀、狀態語意色正確 |
| OV-11 | job 健康摘要 | 唯讀、與 `#/automation/jobs` 一致 |
| OV-12 | 資料完整性卡 | 唯讀渲染 |
| OV-13 | 近期事件表 | 有資料、時間為所選時區 |
| OV-14 | TLS 卡 | 憑證到期日=真值（與 `#/system/tls` 一致） |
| OV-15 | 告警管道卡 | 唯讀、5 管道狀態正確 |
| OV-16 | Integrations 狀態卡摘要 | 與 System 區各子頁狀態一致 |

**Investigate（15 項）**

| ID | 項目 | 檢點 |
|---|---|---|
| IV-01 | 流量查詢+KPI | 查最近 1h，KPI 與結果筆數自洽 |
| IV-02 | 即時快取/Archive 切換 | 兩來源各查一次、結果來源標示正確 |
| IV-03 | FilterBar 進階篩選 | 加 label pill＋exclude 一條，查詢生效 |
| IV-04 | 流量查詢指南 | 說明側欄開啟、內容非空 |
| IV-05 | 結果分頁 | 翻頁、每頁筆數正確 |
| IV-06 | archive 狀態/範圍 | 顯示範圍與 DB 實況一致（ssh 抽查 sqlite） |
| IV-07 | cache backfill | 表單送出被驗證擋（不真跑） |
| IV-08 | workload 搜尋+分頁 | 關鍵字搜尋命中、翻頁 |
| IV-09/10/11 | 隔離 apply 單台/bulk/lift | **只驗到雙重確認 modal＋影響摘要出現後取消** |
| IV-12 | 流量更新加速+倒數 | 觸發後倒數出現（此為非破壞性）|
| IV-13 | 事件三層 catalog | 三層連動選擇有效 |
| IV-14 | 事件 load-more+詳情卡 | load more 增量、詳情卡欄位齊 |
| IV-15 | shadow compare | 真資料載入、差異渲染 |

**Alerting（14 項）**

| ID | 項目 | 檢點 |
|---|---|---|
| AL-01 | 規則清單+啟停+刪除 | 建 `e2e-rule` → toggle → 刪除全程 |
| AL-02..05 | 四型規則 drawer | 各開一次，欄位=後端 schema（e2e 已自動驗，人工抽 traffic 型） |
| AL-06 | highlight 定位 | 從別處跳入時目標規則高亮 |
| AL-07 | rule_test 沙盤 | 真端點回應渲染 |
| AL-08 | run-once | 確認 modal 出現即取消 |
| AL-09 | debug 模式 | toggle 往返、狀態持久 |
| AL-10 | 測試告警 | 單管道測試送出一次（低破壞性，對測試管道） |
| AL-11 | watermark 重置 | 確認 modal 出現即取消 |
| AL-12 | 最佳實務套用 | 預覽差異出現即取消 |
| AL-13 | 輸出主控台 | 有近期輸出 |
| AL-14 | 管道狀態卡 | 與 System 區管道設定一致 |

**Automation（13 項）**

| ID | 項目 | 檢點 |
|---|---|---|
| AU-01 | scheduler 狀態列+KPI | 與 CLI `illumio-ops rule ...` 對照 |
| AU-02 | 排程時間軸 | 真排程渲染、時間軸時區正確 |
| AU-03 | ruleset 瀏覽+詳情 | 分頁瀏覽＋開詳情 |
| AU-04 | rule 個別搜尋 | 關鍵字命中 |
| AU-05/06 | ruleset/rule 層排程 drawer | 建 one-time 2027 排程 → 列表對帳 → 刪除 |
| AU-07 | one-time expire_at 語意 | drawer 顯示語意說明正確 |
| AU-08 | 排程清單+PCE 對帳 | 對帳狀態欄非全 unknown |
| AU-09 | 立即檢查 | 觸發後狀態更新（非破壞性） |
| AU-10 | 執行紀錄+清除 | 紀錄有資料；清除到確認即取消 |
| AU-11 | 報表排程 CRUD | 建 `e2e-sched`（audit_summary 型——驗 2D bug#2/#3 已修）→ 編輯 → 刪除 |
| AU-12 | toggle/run-now/history | toggle 往返；run-now 對小型報表真跑一次；history 有紀錄 |
| AU-13 | 背景 job 健康與歷史 | 與 OV-11 一致、job 時間軸合理（記憶 temporal-bug-class-sweep：驗時間軸不只驗當下） |

**Reports（9 項）＋11 型逐頁驗（本區為 CLAUDE.md 硬規則區）**

| ID | 項目 | 檢點 |
|---|---|---|
| RP-01 | 11 型報表卡+最近產出 | 卡片數=11、meta 正確 |
| RP-02 | 產生 drawer 型專屬參數 | 每型開 drawer 核對參數集（對照 2B 計畫參數表） |
| RP-03 | 進度步驟+async 輪詢 | 真產一份觀察全程 |
| RP-04 | 部分結果提示 | 若當次未觸發，以 2B 的 e2e 證據替代並註記 |
| RP-05 | RHC enablement | 檢查狀態顯示=PCE 真值 |
| RP-06 | 產出清單下載/瀏覽 | 下載一份、HTML 瀏覽一份 |
| RP-07 | 單刪/批刪 | 對 e2e 產物執行 |
| RP-08 | 報表語言切換 | zh/en 各產一份抽查 |
| RP-09 | Labels 查詢輔助 | suggest 有真 label |

11 型報表**全型**於 GUI 以真資料重產（型別清單以 Reports 區卡片實況為準；CLI 對照：traffic／security／inventory／audit／ven-status／policy-usage／rule-hit-count／app-summary／resolve／readiness／policy-diff，另有 draft-policy 子命令——GUI 卡片若含之則一併產）。每份：
1. HTML 於 1280px 與 768px 兩寬度 Playwright 截圖，**親看**逐頁/逐區檢查截斷、溢出、空欄、亂碼、語意色
2. 有 PDF 輸出的型別逐頁翻檢
3. 檢查紀錄逐型寫入 `tmp/phase2e-verification/reports/<type>.md`（含截圖檔名）——回報時附上（CLAUDE.md 要求）

**System（18 項）**

| ID | 項目 | 檢點 |
|---|---|---|
| SY-01 | PCE profiles CRUD/切換 | 檢視與編輯表單開合；不真切換 profile |
| SY-02 | cache 設定表單 | 改一非關鍵欄 → 儲存 → 重讀 → 改回 |
| SY-03 | 重啟 banner+daemon restart | banner 邏輯出現；restart 到確認即取消 |
| SY-04 | retention 立即執行 | 確認 modal 即取消 |
| SY-05 | 流量過濾器+IP 驗證 | 輸入 CIDR 驗證通過（2D bug#6 驗已修） |
| SY-06 | 流量取樣設定 | 表單載入=config 真值 |
| SY-07/08/09 | SIEM forwarder/目的地/測試 | 目的地檢視；測試送出對測試目的地一次 |
| SY-10 | DLQ 家族 | 搜尋/分頁/檢視；清除到確認即取消（2D bug#8 文案驗已修） |
| SY-11 | TLS 狀態/續期/CSR/匯入 | 狀態=真憑證；續期/匯入到確認即取消 |
| SY-12 | 安全設定 | 表單載入正確；不改密碼 |
| SY-13 | 顯示偏好 | 主題/密度/時區/語言各切換往返，reload 持久 |
| SY-14 | 告警管道 5 插件 | 各插件表單開合、密鑰欄遮罩（不印值） |
| SY-15 | 模組日誌檢視器 | 選模組載入真 log |
| SY-16 | GUI 停止 | 確認 modal 即取消（2D bug#9 驗已修） |
| SY-17 | cache 狀態卡+lag | lag 值合理（與 daemon interval 對照） |
| SY-18 | dirty 追蹤+儲存列 | 改欄位 → 儲存列亮起 → 還原 → 熄滅 |

**Login（3 項）＋跨域（14 項）**

| ID | 項目 | 檢點 |
|---|---|---|
| LG-01 | 登入表單 | 錯密碼有錯誤訊息、對密碼進 app |
| LG-02 | 首次登入改密碼 | 以 2A T10 e2e 證據為準＋真機驗 UI 存在（不對真帳號觸發） |
| LG-03 | 登出 | 登出後打 `/api/status` 得 401/導登入 |
| XC-01 | 健康列 5 燈+popover | 僅 `#/overview` 出現；popover 內容真值 |
| XC-02 | Cmd+K 面板 | 開啟、搜尋、跳轉各一次 |
| XC-03 | FilterBar 全語意 | pill/AND-OR/include-exclude/zone 各操作一次 |
| XC-04 | 物件選擇 modal | suggest＋browse 分頁各一次 |
| XC-05 | 亮暗主題+密度 | 雙主題×雙密度切換、六區抽查無破版 |
| XC-06 | 時區+雙語 | 切 zh/en 各遍歷一區；時間欄位隨時區變 |
| XC-07 | 統一進度元件 | 報表產生時收合/展開 |
| XC-08 | 破壞性確認 modal | 影響摘要內容正確（隔離流程順帶驗） |
| XC-09 | 空狀態成因提示 | 查一個必空的條件、提示有成因 |
| XC-10 | 錯誤卡+重試 | 暫停 daemon 或查壞參數觸發一次、重試鈕有效 |
| XC-11 | 說明側欄 | 篩選語法＋隔離指南內容開啟 |
| XC-12 | toast/popover/欄寬/skeleton | 各見一次 |
| XC-13 | 使用者選單 | 開合、登出入口 |
| XC-14 | hash 路由同步 | 深連結貼網址直達；上一頁/下一頁正確 |

- [ ] **Step 3: 截圖存證**——六區 × light/dark 共 12 張全頁截圖進 `traversal/`，逐張親看（記憶：真機 e2e 是 DOM/CSS bug 唯一閘門）
- [ ] **Step 4: FAIL 處置**——任何 FAIL 依 Global Constraints 分流（High 當場修＋部署重驗該項；其餘進 T6 總表）；checklist.md 不允許留空格（每項必為 PASS/FAIL/N-A＋一句備註）

---

### Task 6: 殘項總清點＋release tag＋最終 bundle＋驗證報告交付

**Interfaces:**
- Consumes: T1–T5 全部證據
- Produces: `tmp/phase2e-verification/phase2e-report.md`（交使用者）、tag `v5.0.0`、最終 release bundle

- [ ] **Step 1: 殘項總表**。逐源盤點，輸出欄位＝項目｜出處｜影響｜建議裁決（fix-now／backlog／wontfix，裁決權在使用者）：
  - 路線圖追加 backlog #17（`logs/analysis.lock` 跨測試檔 flock 偶發）與 #18（venv pip-tools shebang 殘留）——2D 的 18 條之外
  - 2A–2D 各計畫執行 ledger 的 parked/minor findings（各計畫檔尾與 `tmp/` 下對應 records 目錄實際翻）
  - `tmp/design-v2-phase1-records/` 終審 triage 中標記非 must-fix 的項
  - T3–T5 本計畫新產生的 Medium/Low
  - 條件驗證項：Windows 真機安裝（T4 Step 3）、真 >500 集合 fallback（api-layer-hardening 案未結項，若本輪仍無環境則續掛）
- [ ] **Step 2: 最終報告** `phase2e-report.md`：入場條件證據、T1 docs 清單、T3 八條 bundle 驗證輸出、T4 smoke、T5 102 項勾稽統計（PASS/FAIL/N-A 計數）＋報表 11 型逐頁結果摘要＋截圖索引、殘項總表。**報告內數字全部來自留檔證據，不寫「已確認」而無輸出**
- [ ] **Step 3: 全綠後 tag＋最終 bundle**

```bash
pytest -q                                    # 最終全綠證據
git log --oneline -8                         # 確認 T1/T2/（若有）fix commits 全在
git tag -a v5.0.0 -m "v5.0.0"
scripts/resolve_version.sh                   # 期望輸出 5.0.0（乾淨 release 型式）
scripts/build_offline_bundle.sh              # 以 tag 版本重建正式產物
bash tmp/phase2e-verification/bundle/verify_bundle.sh   # T3 的 8 條驗證對正式產物重跑，全過
git push --follow-tags                       # 推 main＋tag；gh run watch 盯 CI 綠
```

- [ ] **Step 4: 交付**——向使用者回報：報告路徑、dist/ 正式產物、殘項總表請裁決、Windows 真機驗證授權請示

---

## Self-Review 紀錄

- 路線圖 2E 四項全覆蓋：離線 bundle 打包驗證+parity=T3/T4、真機全遍歷報告=T5/T6、docs 更新=T1、CHANGELOG=T2 ✓
- 佔位掃描：無「適當驗證」類；T5 每項有檢點、T3 每條有 pass 條件；「以實況為準」處皆附實測指令（grep/ls/--help）屬防行號漂移指引非 TBD ✓
- 型別/路徑一致：`tmp/phase2e-verification/` 貫穿；版本字樣統一 5.0.0（T2 Step 1 留使用者否決點）✓
- 已知風險：`tools/gate_coverage_live.py` 與 `tests/test_v2_*.py` 是 2A 產物，本計畫寫作時尚不存在——T5 Step 1 已註明以實檔為準；bundle 驗證第 (1)(2) 條的 v2 路徑同理 ✓
