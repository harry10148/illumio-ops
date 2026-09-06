# Phase 3D — v3 收尾與發版

> Roadmap `2026-09-03-ui-redesign-v3-roadmap.md` 的 3D，spec §7「驗收」。
> 前置 3A／3B／3E／3C **全部已交付**（main `d439990b`）。這份計畫不新增功能，
> 只做「證明它成立」與「把它發出去」。

**Spec：** `docs/superpowers/specs/2026-09-03-ui-redesign-v3-design.md` §7
＋修訂 `2026-09-04-ui-redesign-v3-1-workbench-design.md` §7
（§1／§2／§3／§5／§8 以修訂為準——**主場景的「步進＋上下文條」版式已被修訂砍掉**，
走查要照修訂後的實際畫面走，不是照 v3 §3.1 的分鏡稿）。

## 起始基線（2026-09-07 實查，不是引用）

| 項目 | 現況 |
|---|---|
| main = origin = 測試機 | `d439990b`，服務 active |
| 全套 pytest | 4689 passed（排除本機恆紅的 `test_cache_flush_json_output`） |
| live coverage gate | **`covered=108/108 extra=[]`** — 3D 的任務是「維持」不是「做到」 |
| 測試機告警 | 3 筆，**全部是 `type='event'`** |
| 測試機規則 | 19 條（16 event／1 traffic／1 system／1 bandwidth），存在 `config/alerts.json`，由 ConfigManager 併入 `cm.config["rules"]` |
| `docs/guide/gui-tour.md` | 508 行，自帶 2026-09-05 過渡註記：除首頁與告警兩節外仍是 v2 六區時期內容 |
| `src/__init__.py` | `__version__ = "5.0.0"`；最新 tag `v5.0.0` |
| 測試機 untracked | `alerts.json`、`config/*.bak` ×3、`time_events.py` |

## 使用者裁決（2026-09-07）

1. **版本號 `5.1.0`**（我建議 6.0.0，使用者選 5.1.0）。
   **因此 CHANGELOG 必須把「CLI 主選單編號改變」寫成顯著的升級注意事項**——
   minor 版本本身不會提示操作者按鍵行為變了，而這是唯一一項升級後會撞到的
   行為變更（六區→五區；自動化的 1／2 變成規則區的 10／11）。
2. **測試機殘檔分三類**：`alerts.json` 刪除（空的 `{"rules": []}`，已被
   `logs/alerts.sqlite` 取代）；三個 `.bak` 移到 `/root/backups/`；
   `time_events.py` 移到 `/root/tools/` 保留（它是量測 PCE events 查詢耗時的
   診斷腳本，讀測試機自身設定、不印憑證）。

## Global Constraints

- 「全套」＝ CI 的每道閘門：`scripts/check_no_naive_datetime.py`、
  `scripts/check_doc_links.py`、`scripts/audit_i18n_usage.py`（0 findings）、
  `mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`、
  `timeout 3600 python3 -m pytest --tb=short -q --deselect tests/test_cache_cli.py::test_cache_flush_json_output`。
- 每任務＝乾淨 commit（英文 conventional commits）＋CI 綠＋部署測試機。
  **禁止 `git add -A`**，只用明確路徑。
- 憑證只從 1Password 按需取得，不寫入檔案／終端／記憶；驗遮罩不印 secret。
- 測試機任何新落地檔由 service 帳號 `illumio-ops` 建立，不得以 root 手工建立。
- 產出物放 `tmp/phase3d-verification/`，不進 `tests/`。
- **跑 pytest 時不要改被測的檔**（3C 因此吃過一次假紅：drift guard 在全套跑到
  一半時比對到我同時改掉的設計檔）。

---

## Task 1 — 主場景六步真機走查

**Outcome：** spec §7.3 的「主場景六步 Playwright 走一遍＋每步截圖」有實際證據，
而且每一步都落在 `design/v3/coverage.yaml` 有登記的錨點上。

### 1.1 六步的實際落點（已對過原始碼，不是照分鏡稿）

| 步 | 路由 | 錨點 | 畫面上要看到什麼 |
|---|---|---|---|
| 1 | `#/home` | `HM-01` | 「最近的告警」前 10 列；整列是連結 |
| 2 | `#/investigate/alerts` | `AT-01`＋`AT-02` | 列式清單、未處理／全部切換、頁尾計數 |
| 3 | `#/investigate/alerts?id=<n>` | `AT-03` | 告警頁四段（發生什麼／誰在跟誰講話／該怎麼辦／更多） |
| 4 | 同上 | `AT-04` | 規則判定欄：載入時並行問 PCE、逐列回填 |
| 5 | `#/investigate/traffic?alert=<n>` | `AT-06`＋`IV-01` | provenance 一行說明條件來自哪一則告警＋回告警的連結；篩選器已由 `/api/alerts/<id>/traffic_query` 帶入 |
| 6 | 回 `#/investigate/alerts?id=<n>` | `AT-05` | 行動列（政策／隔離／標記已處理） |

v3 §3.1 的「步進＋上下文條」不在畫面上——v3.1 修訂砍掉了它，`investigate.mjs`
的註解明寫 "The strip, the stepper and the investigation flow they belonged to
are gone."。照舊稿寫走查會對著一個不存在的 UI 斷言。

### 1.2 前置：第 5 步現在走不通，必須先讓一則 traffic 告警存在

測試機三筆告警**全部是 `type='event'`**，而 `src/gui/routes/alerts.py:121` 對非
traffic 告警回 `code: "not_traffic"`——第 5 步會顯示 fallback 文案而不是帶好條件的
查詢。這正是「守門只在機器剛好有資料時才真的在看」那一類：走查本身就是一道守門。

處置順序（先試最不侵入的）：
1. 測試機規則裡**有一條 traffic 規則**。先跑一次 CLI「規則 → 7. 立即執行分析並
   發送告警」，看它是否觸發。
2. 沒觸發就**暫時**調低那條規則的門檻讓它觸發，走查完**還原**（改動前後各存一份
   `config/alerts.json` 到 `tmp/phase3d-verification/`，還原後 diff 確認為空）。
3. 兩者皆不可行才在報告中寫明第 5 步用的是 `not_traffic` 的正確 fallback 畫面，
   並說明為什麼——**不得跳過不提**。

`force_test=True` 不寫入 alerts.sqlite（spec §7.2），所以「發送測試告警」那一項
造不出可走查的告警，不要用它。

**Files:**
- Create: `tests/test_e2e_v3_main_scenario.py`（env-gated，比照
  `tests/test_e2e_dashboard_story.py` 的 `ILLUMIO_OPS_E2E_BASE_URL` 慣例與登入
  片段：`[data-cov="LG-01"] input[data-field="username"]` → `…password` →
  `button.btn.primary`）
- Create: `tmp/phase3d-verification/shots/step[1-6].png`（1280 寬）

**Steps:**
- [ ] **1. 確認資料**：測試機是否已有 traffic 告警；沒有就照 1.2 處置並記錄。
- [ ] **2. 先紅**：把某一步的錨點改成不存在的值，確認測試會紅——證明它真的在看
      畫面而不是只在看 HTTP 200。
- [ ] **3. 實作＋跑**：
      `ILLUMIO_OPS_E2E_BASE_URL=https://172.16.15.106:5001 timeout 900 python3 -m pytest tests/test_e2e_v3_main_scenario.py -q`
      （憑證走既有的 `ILLUMIO_OPS_E2E_USER` / `_PASSWORD` 環境變數，不寫進檔案）
- [ ] **4. 無 env 時必須 skip 不是 fail**：不帶環境變數再跑一次，確認 skip。
- [ ] **5. 六張截圖逐張親看**，把每張看到什麼寫進報告（不是只貼檔名）。
- [ ] **6. 全套＋commit＋部署＋CI**　`test(e2e): the v3 main scenario, walked end to end`

---

## Task 2 — `gui-tour.md` 依五區重寫，並鎖住路由不再漂移

**Outcome：** 操作者手冊描述的是現在的畫面；而且路由字串寫錯會被守門抓到。

`gui-tour.md` 自己的過渡註記已經列出哪些節是舊的：**除「首頁」與「告警」兩節外
全部是 v2 六區時期的內容**。範圍照它走，不是「整份重寫」。

**Files:**
- Modify: `docs/guide/gui-tour.md`（〈五區逐一導覽〉各節；刪掉那條 2026-09-05
  過渡註記——它描述的過渡狀態結束了）
- Create: `tests/test_docs_gui_tour_routes.py`

**五區與子項的權威來源是 `src/static/js/v2/shell.mjs` 的 `NAV`**（與左側選單、
麵包屑、`labelForRoute()` 同一份）：

- 首頁 `#/home`
- 調查 `#/investigate/{alerts,traffic,workloads,events}`
- 規則 `#/policy/{alert-rules,rulesets,schedules,ops}`
- 報表 `#/reports`、`#/reports/schedules`
- 系統 `#/system/{pce,cache,siem,tls,security,display,channels,alerting,jobs,logs}`

**守門的設計**（`check_doc_links.py` 只驗連結存不存在，不驗散文裡的路由名對不對）：
斷言 `gui-tour.md` 裡出現的每一個 `#/…` 字串，都能在 `shell.mjs` 的 `NAV`
（含 children）或一份寫明理由的已知轉址清單裡找到。**從 `shell.mjs` 解析，不要
在測試裡再打一份路由表**——那會變成第二份會落後的清單（Task 2 of 3C 的同一個
教訓）。

**Steps:**
- [ ] **1. 先紅**：守門寫好後先跑，現況應該會抓到舊路由（`#/overview`、
      `#/alerting`、`#/automation` 之類）。把它抓到的清單貼進報告——那就是要改的
      範圍，比人工盤點可靠。
- [ ] **2. 重寫**：逐節改，PCE 術語保留英文，五區判準（首頁看「現在」、調查查
      「這件事」、規則改「規則」、報表產「交付物」、系統改「系統」）貫穿。
- [ ] **3. 綠**：`timeout 600 python3 -m pytest tests/test_docs_gui_tour_routes.py -q`
      ＋`python3 scripts/check_doc_links.py`
- [ ] **4. 注入驗證**：在文件裡塞一個 `#/nonexistent`，確認守門紅。
- [ ] **5. 全套＋commit＋部署＋CI**　`docs(guide): the GUI tour describes the five areas`

---

## Task 3 — CHANGELOG、版本號 5.1.0、測試機殘檔

**Outcome：** `5.1.0` 的 CHANGELOG 完整且對操作者有用；版本號一處改、處處對；
測試機 `git status` 乾淨。

**Files:**
- Modify: `CHANGELOG.md`（`## [Unreleased]` → `## [5.1.0] - 2026-09-07`；補 3C 條目）
- Modify: `src/__init__.py`（`__version__ = "5.1.0"`）

**先讀再寫**：`## [Unreleased]` 已經有 3A／3B／3E 的條目，**不要重寫它們**。這個
任務要加的是：

- 3C：報表殼換 v3 色票（設計權威 `design/v3/reports/shell.css`）、圖表色盤與
  shell tone token 同源、CLI 主選單五區。
- `### Fixed` 兩條潛伏缺陷：mod13 執行模式圖例讓整份 security_risk 報表建置失敗
  （`enforcement_mode_distribution` 非空時）；首頁的語言／佈景那一行印出原始樣板。
- **升級注意事項（因為選了 minor，這段是必要的）**：CLI 主選單由六區改為五區，
  告警與自動化併為「規則」；自動化原本的 1／2 變成規則區的 10／11。腳本若靠
  互動選單的按鍵順序自動化，需要調整——click 子指令介面沒有變動。

**版本號的落點要按概念盤點，不是 grep 一個字串**：`src/__init__.py` 是唯一真相
（`gui/__init__.py`、`gui/routes/dashboard.py`、`cli/menus/_root.py` 都是 import
它）。離線 bundle 檔名由 `scripts/build_offline_bundle.sh` 從版本號組出來，
**不要手改檔名**。

**測試機殘檔**（照裁決）：
```
alerts.json                                        → 刪除
config/config.json.pre-profile-removal.bak         → /root/backups/
config/config.json.pre-tf-wiring.bak               → /root/backups/
config/rule_schedules.json.pre-prod-pce-remap-…    → /root/backups/
time_events.py                                     → /root/tools/
```
刪 `alerts.json` **之前**先確認沒有讀者：它是 root 所有、內容 `{"rules": []}`，
而 ConfigManager 讀的外部規則檔是 `config/alerts.json`（不同路徑）——**兩者同名
不同目錄，動手前把這件事再確認一次**。刪完重啟服務並確認 19 條規則仍在。

**Steps:**
- [ ] **1. 讀現有 Unreleased 全文**，列出已涵蓋與待補。
- [ ] **2. 寫 CHANGELOG＋改版本號**。
- [ ] **3. 驗證版本號**：`python3 -c "import src; print(src.__version__)"`；
      GUI `/api/dashboard/...` 的 `version` 欄位；CLI 主選單頁尾。三處都要是 5.1.0。
- [ ] **4. 測試機殘檔**：先確認 `alerts.json` 無讀者 → 搬移／刪除 → 重啟 →
      `git status --porcelain` 空 → 規則數仍 19 → 告警仍 3 筆。
- [ ] **5. 全套＋commit＋部署＋CI**　`chore(release): 5.1.0`

---

## Task 4 — 發版與最終驗收

**Outcome：** `v5.1.0` tag 存在且指向 CI 綠的 commit；離線 bundle 用新版本號建得
起來；spec §7 的每一條都有證據。

**Files:**
- Create: `tmp/phase3d-verification/report.md`
- Modify: `docs/superpowers/plans/2026-09-03-ui-redesign-v3-roadmap.md`（3D 標記交付）

**Steps:**
- [ ] **1. 最終閘門全跑一次**（不是引用先前結果）：五道 CI 閘門＋
      `python3 tools/gate_coverage_live.py -v` 必須仍是 `covered=108/108 extra=[]`。
- [ ] **2. 離線 bundle**：`bash scripts/build_offline_bundle.sh`，確認產出檔名帶
      `5.1.0`，並依 `offline-bundle-db-hardening-delivered` 記憶的教訓抽驗
      bundle 內容（marker 檔、wheels、wrapper 的 cd）。
- [ ] **3. 打 tag 並推**：`git tag -a v5.1.0 -m "..."`＋`git push origin v5.1.0`。
      **tag 只打在 CI 已經綠的 commit 上**，不要打在剛推還沒跑完的 HEAD。
- [ ] **4. 測試機對齊 tag**：部署到 `v5.1.0`，確認 `git describe --tags` 相符。
- [ ] **5. 驗收報告**：spec §7.1／§7.2／§7.3 逐條對照，每條寫證據來源（命令＋
      輸出摘要＋產物路徑）。§7.2 的四條新增守門要指名是哪一個測試在守。
- [ ] **6. commit**　`docs(plan): phase 3D delivered`

---

## 自審

- **範圍**：spec §7 有三節。§7.1（沿用守門）與 §7.2（新增守門）在 3A–3C 已逐一
  落地，Task 4 只做「證明它們仍然綠」的對照；§7.3（真機）是 Task 1 的走查＋
  3C 已完成的 11 型報表重產＋3C 已完成的 CLI 五區遍歷。三者都不重做。
- **順序**：T1 與 T2 互不相依，但 T1 先做——走查會逼出 gui-tour 該怎麼寫。
  T3 依賴 T1／T2 的 commit 都在（CHANGELOG 要涵蓋它們）。T4 最後。
- **最大風險**：T1 的第 5 步需要一則 traffic 告警，而測試機現在沒有。1.2 寫了
  三層處置與「不得跳過不提」的底線。次一風險是暫時改門檻後忘記還原——用改動前後
  的檔案 diff 確認，不靠記性。
- **未展開實作碼**：走查測試的登入片段抄 `tests/test_e2e_dashboard_story.py`
  既有寫法；路由守門的解析對象是 `shell.mjs` 的 `NAV` 字面量。兩者都是既有形狀。
- **刻意不做**：報表 `info` tone 與 GUI 深青的差異、信件與 xlsx 的獨立色表——
  都是 3C 記錄在案的待裁決項，不在 3D 範圍。
