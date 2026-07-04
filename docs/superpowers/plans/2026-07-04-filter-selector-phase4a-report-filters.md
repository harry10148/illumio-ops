# Filter 物件選擇器 Phase 4a：報表路徑（即時報表 + 排程報表）— Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把即時報表與排程報表的分欄文字 filter 升級為 FilterBar pill 元件（重用 Phase 3 的 `createFilterBar`），並補齊報表路徑後端的 filter forward 缺口——含修正即時報表 `any_*` key 被 whitelist 靜默丟棄的**既有 bug**。

**Architecture:** 報表路徑（`report_generator`）有 native / cache-df 雙路徑：有物件 filter 時先 `expand_object_filters_for_df`（iplist/workload → CIDR），cover_state full 走 cache df（`apply_df_traffic_filters`），否則走 native（`fetch_traffic_for_report` → `build_traffic_query_spec`，Phase 1 全支援）。本批 (1) 補 `df_filter` 的 `any_label`/`src_ip_in`（cache 路徑常用缺口），(2) 擴充即時報表後端 `reports.py` 的 filter whitelist（不再 drop object/any/複數 key），(3) 兩個報表前端 modal 換 FilterBar。排程報表後端透傳（不改），與即時報表共用下游。

**Tech Stack:** Python/pandas（df_filter）、Flask（reports.py）、vanilla JS（FilterBar 重用）、pytest + Playwright MCP（controller 實機）。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §10（分批），沿用 Phase 3 的 FilterBar 契約。

## 設計定案（基於 2026-07-04 盤點）

- **FilterBar getFilters() 送的 key**（`src/static/js/filter-bar.js:52-75`）：src/dst 複數 list（`{ex_}{dir}_labels`/`_label_groups`/`_iplists`/`_workloads`）、`{dir}_ip_in`（include list）/`ex_{dir}_ip`（exclude）、any 純量（`{ex_}any_label`/`any_iplist`/`any_workload`/`any_ip`）。
- **報表路徑下游支援矩陣**：
  - native（`build_traffic_query_spec`，Phase 1）：**全部 key 支援**。
  - cache df（`df_filter` + `expand_object_filters_for_df`）：已支援 `src/dst_labels`（複數）、`ex_*_labels`、`src_ip`/`dst_ip`（scalar）、`_*_object_cidrs`（iplist/workload 展開）、`port`/`ex_port`/`proto`。**缺** `any_label`、`src_ip_in`（list）、`label_groups`。
- **本批 df 層補**：`src_ip_in`（list，多 IP OR，對映既有 `_ip_mask`）、`any_label`（either-side，src 或 dst 命中）+ `ex_any_label`。iplist/workload 靠既有 `expand`。
- **label_group 決定（native 主路徑，cache df 記 follow-up）**：label_group 語意是「命中群組成員任一」（OR-of-members，成員可跨 key），與 `df_filter._label_mask` 的「同 key OR、跨 key AND」不同，df 層正確實作複雜且 label_group 少用。依使用者一路核可的策略：label_group 在 **native 路徑支援**（`reports.py` whitelist 需 forward 它讓 native 用），**cache df 路徑不展開、明確標註不支援**（follow-up）。這是透明的已知限制，非「假象」（不宣稱支援）。
- **IP key 對映**：FilterBar include 送 `src_ip_in`（list）。native 認 `src_ip_in`（Phase 1 `_pop_many`）。df 層本批補認 `src_ip_in`（list）。**前端不需轉換**（統一送 `src_ip_in`），但既有報表 df 用 `src_ip`（scalar）保留相容（兩者都認）。

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動各 Task 列出的檔案；不順手重構。
- 新 UI 字串進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`（沿用 Phase 3 的 `gui_fb_*`，本批多數重用，若需新鍵雙語同步）。
- **JS 繁中註解格式**（Phase 3 audit 教訓）：block comment 每行加 ` * ` 前綴或用 `//` 行首；**禁行尾 `code // 中文`**（i18n audit C 類會抓）。
- CSP：FilterBar 動態元素已用 document 委派；modal 換掛載點不引入 inline handler。
- 每 Task 結尾跑該 Task 測試 + commit；Task 5 全量（基準以執行時 main 為準，約 2384 passed）。
- **worktree 紀律**：每個 Bash 命令以絕對 worktree 路徑 `cd` 前綴，commit 前 `git rev-parse --show-toplevel` 驗證、commit 後確認落點；controller 每 task 驗 parent SHA + `git branch --contains` 不在 main。

---

### Task 1: df_filter 補 src_ip_in + any_label（cache 路徑共用基礎）

**Files:**
- Modify: `src/report/df_filter.py`（`apply_df_traffic_filters`）
- Test: `tests/test_df_filter.py`（追加）

**Interfaces:**
- Produces: `apply_df_traffic_filters` 消費 `src_ip_in`/`dst_ip_in`（list，多 IP OR）、`ex_src_ip_in`/`ex_dst_ip_in`（若 FilterBar 送）、`any_label`/`ex_any_label`（either-side label）。既有 `src_ip`（scalar）保留。

**背景**：FilterBar 送 `src_ip_in`（list）與 `any_label`（純量），但 df 層只認 `src_ip`（scalar）、不認 `any_label`。即時報表走 cache df 時這些 pill 會靜默失效。native 路徑已支援（Phase 1），本 task 補 cache df 路徑。

- [ ] **Step 1: 寫失敗測試（追加 tests/test_df_filter.py）**

```python
def test_src_ip_in_list_matches_any():
    df = _df_two_apps()  # src_ip 10.0.0.1/2/3
    out = apply_df_traffic_filters(df, {"src_ip_in": ["10.0.0.1", "10.0.0.3"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1", "10.0.0.3"]


def test_src_ip_in_cidr():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_ip_in": ["10.0.0.0/31"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1"]


def test_any_label_either_side():
    df = _df_two_apps()  # 假設 src_app=erp/web/hr, dst_app 空
    out = apply_df_traffic_filters(df, {"any_label": "app=erp"})
    # src 或 dst 命中 app=erp 的列留下
    assert "erp" in out["src_app"].tolist()
    assert set(out["src_app"]) == {"erp"}


def test_ex_any_label_excludes_either_side():
    df = _df_two_apps()
    out = apply_df_traffic_filters(df, {"ex_any_label": "app=erp"})
    assert "erp" not in out["src_app"].tolist()
```

註：`_df_two_apps()` 的欄位以 tests/test_df_filter.py 既有 fixture 為準（src_app/src_env/src_ip 等）；`any_label` 測試的欄位值對齊 fixture。

Run: `python3 -m pytest tests/test_df_filter.py -v -k "src_ip_in or any_label"`
Expected: FAIL（key 被忽略）。

- [ ] **Step 2: 實作（src/report/df_filter.py）**

在 `apply_df_traffic_filters` 內，既有 `src_ip`/`dst_ip`（scalar）處理之後加入 `src_ip_in`（list）與 `any_label`：

```python
    # src_ip_in / dst_ip_in（FilterBar 送 list；多 IP/CIDR 取 OR）。既有 src_ip（scalar）保留相容。
    for side in ("src", "dst"):
        inc = [s for s in (filters.get(f"{side}_ip_in") or []) if s]
        if inc and f"{side}_ip" in df.columns:
            m = pd.Series(False, index=df.index)
            for v in inc:
                m |= _ip_mask(df, f"{side}_ip", v)
            mask &= m
        exi = [s for s in (filters.get(f"ex_{side}_ip_in") or []) if s]
        if exi and f"{side}_ip" in df.columns:
            for v in exi:
                mask &= ~_ip_mask(df, f"{side}_ip", v)

    # any_label / ex_any_label（either-side label：src 或 dst 命中）。用既有 _label_mask 單值。
    any_lbl = _scalar(filters, "any_label")
    if any_lbl:
        mask &= (_label_mask(df, "src", [any_lbl]) | _label_mask(df, "dst", [any_lbl]))
    ex_any_lbl = _scalar(filters, "ex_any_label")
    if ex_any_lbl:
        mask &= ~(_label_mask(df, "src", [ex_any_lbl]) | _label_mask(df, "dst", [ex_any_lbl]))
```

（`_ip_mask`、`_label_mask`、`_scalar` 均為 df_filter.py 既有 helper。）

- [ ] **Step 3: 跑測試確認通過**

Run: `python3 -m pytest tests/test_df_filter.py -v`
Expected: 全 PASS（既有 + 新增；既有 src_ip scalar / _object_cidrs / query_operator 不回歸）。

- [ ] **Step 4: Commit**

```bash
git add src/report/df_filter.py tests/test_df_filter.py
git commit -m "feat(df_filter): support src_ip_in list and any_label for cache report path"
```

---

### Task 2: 即時報表後端 forward 全部 filter key（修 any_* 既有 bug）

**Files:**
- Modify: `src/gui/routes/reports.py`（即時報表 filter whitelist，約 348-361）
- Test: `tests/test_gui_app_report_generate.py` 或 `tests/test_gui_reports.py`（依現場報表端點測試檔；追加）

**Interfaces:**
- Produces: `POST /api/reports/generate` 的 `report_filters` dict forward 全部 FilterBar key（labels 複數/label_groups/iplists/workloads/`src_ip_in`/any_*/ex_*），傳給 `report_generator`。

**背景**：`reports.py:348-361` 重建 `report_filters` 只保留 labels/src_ip/dst_ip/ex_*/port/proto，**丟棄前端送的 any_***（既有 bug）與所有 object/複數 key。native 下游支援全部（Phase 1）、cache df 支援本批補的（Task 1）+ 既有 + iplist/workload（expand）；label_group 走 native（見設計定案）。

- [ ] **Step 1: 寫失敗測試（追加報表端點測試檔）**

```python
def test_report_generate_forwards_object_and_any_filters(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    captured = {}
    # 攔 report_generator 收到的 filters（monkeypatch 生成入口，以現場為準）
    import src.gui.routes.reports as rep_mod
    # 依現場：reports.py 呼叫 _run_adhoc → report_generator.generate_from_api(filters=...)
    # 攔 generate_from_api 捕 filters
    from src.report.report_generator import ReportGenerator
    def fake_gen(self, *a, **kw):
        captured.update(kw.get("filters") or {})
        return {"files": []}
    monkeypatch.setattr(ReportGenerator, "generate_from_api", fake_gen, raising=False)

    client.post('/api/reports/generate', json={
        "report_type": "traffic",
        "filters": {
            "src_labels": ["app=erp", "app=web"],
            "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
            "src_workloads": ["/orgs/1/workloads/abc"],
            "src_label_groups": ["PG-Prod"],
            "any_label": "env=prod",
            "any_iplist": "corp-vpn",
            "src_ip_in": ["10.0.0.1"],
        },
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})

    assert captured.get("src_labels") == ["app=erp", "app=web"]
    assert captured.get("dst_iplists") == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert captured.get("src_workloads") == ["/orgs/1/workloads/abc"]
    assert captured.get("src_label_groups") == ["PG-Prod"]
    assert captured.get("any_label") == "env=prod"          # 既有 bug 修復
    assert captured.get("any_iplist") == "corp-vpn"
    assert captured.get("src_ip_in") == ["10.0.0.1"]
```

註：報表生成入口的實際函式（`generate_from_api` / `_run_adhoc` / `rep.run`）與 monkeypatch 目標以 `reports.py:198-364` 現場為準；測試檔沿用現場報表端點測試樣式。

Run: `python3 -m pytest tests/test_gui_app_report_generate.py -v -k forwards_object`（檔名以現場為準）
Expected: FAIL（whitelist 丟棄這些 key）。

- [ ] **Step 2: 實作 whitelist 擴充（src/gui/routes/reports.py:348-361）**

把 `report_filters` dict 從固定 whitelist 改為 forward 全部 FilterBar filter key。保留既有 key，追加：

```python
                # Phase 4a：forward FilterBar 的 object/複數/any key（原 whitelist 漏收
                # any_*、iplists、workloads、label_groups、src_ip_in——含 any_* 既有 bug）。
                "src_labels": f.get("src_labels", []),
                "dst_labels": f.get("dst_labels", []),
                "ex_src_labels": f.get("ex_src_labels", []),
                "ex_dst_labels": f.get("ex_dst_labels", []),
                "src_label_groups": f.get("src_label_groups", []),
                "dst_label_groups": f.get("dst_label_groups", []),
                "ex_src_label_groups": f.get("ex_src_label_groups", []),
                "ex_dst_label_groups": f.get("ex_dst_label_groups", []),
                "src_iplists": f.get("src_iplists", []),
                "dst_iplists": f.get("dst_iplists", []),
                "ex_src_iplists": f.get("ex_src_iplists", []),
                "ex_dst_iplists": f.get("ex_dst_iplists", []),
                "src_workloads": f.get("src_workloads", []),
                "dst_workloads": f.get("dst_workloads", []),
                "ex_src_workloads": f.get("ex_src_workloads", []),
                "ex_dst_workloads": f.get("ex_dst_workloads", []),
                "src_ip_in": f.get("src_ip_in", []),
                "dst_ip_in": f.get("dst_ip_in", []),
                "ex_src_ip": f.get("ex_src_ip", []),
                "ex_dst_ip": f.get("ex_dst_ip", []),
                "any_label": f.get("any_label", ""),
                "any_ip": f.get("any_ip", ""),
                "any_iplist": f.get("any_iplist", ""),
                "any_workload": f.get("any_workload", ""),
                "ex_any_label": f.get("ex_any_label", ""),
                "ex_any_ip": f.get("ex_any_ip", ""),
                "ex_any_iplist": f.get("ex_any_iplist", ""),
                "ex_any_workload": f.get("ex_any_workload", ""),
```

（`f` 為前端送的 `filters` dict，變數名以現場 348 行為準。既有 `src_ip`/`dst_ip` scalar 保留相容。空預設無害：native `_pop_many` 與 df 層都略過 falsy。）

- [ ] **Step 3: 跑測試確認通過 + 既有報表測試不回歸**

Run: `python3 -m pytest tests/test_gui_app_report_generate.py tests/test_gui_reports.py -q`（檔名以現場為準）
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/reports.py tests/test_gui_app_report_generate.py
git commit -m "fix(reports): forward object, any_ and plural filter keys to report generator"
```

---

### Task 3: 即時報表前端 modal 換 FilterBar

**Files:**
- Modify: `src/templates/index.html`（`#m-gen-filters` 的 rpt-* 分欄，約 2881-2933）
- Modify: `src/static/js/dashboard.js`（`_collectReportFilters` 約 755-815，改讀 FilterBar；FilterBar 實例初始化）
- Test: `tests/test_component_object_filter_bar.py`（追加 index.html 落地斷言）

**Interfaces:**
- Consumes: `window.createFilterBar`（Phase 3）、getFilters/setFilters。
- Produces: 即時報表 modal 用 FilterBar 取代 rpt-src/rpt-dst/rpt-ex-*/rpt-any-* 分欄；送 `/api/reports/generate` 帶物件 filter key。

- [ ] **Step 1: index.html 換掛載點**

`#m-gen-filters`（2881-2933）的 `rpt-src`/`rpt-dst`/`rpt-ex-src`/`rpt-ex-dst`/`rpt-any-label`/`rpt-any-ip`/`rpt-ex-any-label`/`rpt-ex-any-ip` 分欄替換為單一 `<div id="rpt-filter-bar"></div>`（含說明 label）。保留 `rpt-pd-*`（PD checkbox）、`rpt-proto`、`rpt-port`、`rpt-ex-port`（非 FilterBar 範圍）。加靜態斷言：index.html 含 `id="rpt-filter-bar"`。

- [ ] **Step 2: dashboard.js 接線**

`_collectReportFilters`（755-815）的 rpt-* 讀值段改為：先取 FilterBar 實例 `getFilters()`、`Object.assign(filters, fb.getFilters())`，移除舊 `parseSrcDst`/`=` 啟發式讀值（保留 pd/proto/port 讀取）。FilterBar 實例用 lazy singleton（仿 Phase 3 `_ensureQtFilterBar`）：`_ensureRptFilterBar()` 建 `createFilterBar(document.getElementById('rpt-filter-bar'), {})`，存模組作用域。開 modal 時 setFilters 回填（若有既有值）。

- [ ] **Step 3: 跑靜態 + 端點測試**

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py tests/test_gui_app_report_generate.py -q`
Expected: 全 PASS。node --check dashboard.js。

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): wire filter-bar into instant report modal"
```

---

### Task 4: 排程報表前端 modal 換 FilterBar

**Files:**
- Modify: `src/templates/index.html`（`#sched-filter-section` 的 sched-* 分欄，約 1622-1682）
- Modify: `src/static/js/dashboard.js`（`_collectSchedFilters` 約 817-876、`_populateSchedFilters` 約 878-903）
- Test: `tests/test_component_object_filter_bar.py`（追加）

**Interfaces:**
- Consumes: `window.createFilterBar`、getFilters/setFilters。
- Produces: 排程報表 modal 用 FilterBar；存 config 的 filter 為 getFilters() 格式；回填用 setFilters()。排程報表後端透傳（不改），下游共用 report_generator（Task 1 補的 df 支援）。

**背景**：排程報表後端 verbatim 存 `schedule['filters']`。舊格式是 `_collectSchedFilters` 的輸出（`src_labels` 單元素 list、`src_ip` scalar、`any_label` 純量）。新格式是 FilterBar getFilters()。**既有排程的 config 相容**：`_populateSchedFilters` 用 setFilters 反序列化——FilterBar setFilters 已能讀 `{dir}_labels`/`{dir}_ip_in`/`any_*` 等（Phase 3 `_objfbDeserialize`），但舊排程存的是 `src_ip`（scalar）不是 `src_ip_in`——setFilters 的 deserialize 需認舊 `src_ip` scalar（見 Step 2）。

- [ ] **Step 1: index.html 換掛載點**

`#sched-filter-section`（1622-1682）的 sched-src/dst/ex-*/any-* 分欄替換為 `<div id="sched-filter-bar"></div>`。保留 `sched-pd-*`/`sched-proto`/`sched-port`/`sched-ex-port`。加靜態斷言。

- [ ] **Step 2: dashboard.js 接線 + 舊 config 相容**

`_collectSchedFilters`（817-876）改為 `_ensureSchedFilterBar().getFilters()` + pd/proto/port。`_populateSchedFilters`（878-903）改為 `setFilters(schedule.filters)`。

**舊 config 相容**：FilterBar `_objfbDeserialize`（filter-bar.js）需能讀舊排程的 `src_ip`（scalar）與 `dst_ip`（scalar）——確認 Phase 3 的 deserialize 是否已認 `{dir}_ip`（Phase 3 deserialize 認 `{dir}_ip_in` 與 `ex_{dir}_ip`；舊排程存 `src_ip` scalar）。若未認，在 `_objfbDeserialize` 補：`for ip of asList(d['src_ip']): add('ip','src',...)`（單值 scalar 也 asList 包）。這是本 task 對 filter-bar.js 的最小擴充（向後相容既有排程）。

- [ ] **Step 3: 跑測試**

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py -q`
Expected: 全 PASS。node --check。

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js src/static/js/filter-bar.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): wire filter-bar into scheduled report modal with legacy config compat"
```

---

### Task 5: 全量回歸 + CSP/i18n + Playwright 實機煙霧

- [ ] **Step 1: 全量測試**

Run: `python3 -m pytest tests/ -q`
Expected: 執行時 main 基準 + 本計畫新增全 PASS、0 failed。**注意 i18n audit test**：確認新增/改動的 JS 繁中註解用 `//` 行首或 `*`-前綴（Phase 3 教訓）。

- [ ] **Step 2: i18n 稽核**

Run: `python3 scripts/audit_i18n_usage.py`
Expected: 0 findings。

- [ ] **Step 3: controller Playwright MCP 實機煙霧**

scratch config + HTTP + 真實 PCE（同 Phase 3）：
1. 登入 → 報表分頁 → 開即時報表 modal → 驗 `#rpt-filter-bar` 掛載、setFilters/getFilters round-trip、輸入觸發 suggest 候選。
2. 開排程報表 modal → 驗 `#sched-filter-bar`、既有排程 setFilters 回填（舊 config 相容）。
3. 送一次即時報表（含 label + iplist pill），確認後端收到物件 key（看 log 或回應）。
4. console 零錯誤、無 CSP 違規。截圖存證。

- [ ] **Step 4: 回報**

回報：全量數字、i18n 稽核、Playwright 實機（兩 modal round-trip、舊 config 相容、送報表）結果與截圖。**明列 follow-up**：label_group 在 report cache df 路徑不支援（native 支援）——已知限制。

---

## Self-Review 紀錄

- **Spec 覆蓋**：即時報表 + 排程報表換 FilterBar → Task 3/4；報表後端 forward 缺口（含 any_* 既有 bug）→ Task 2；cache df 缺口（any_label/src_ip_in）→ Task 1；排程 config 相容 → Task 4。
- **每個進入點的第二道 whitelist（Phase 3 教訓）**：即時報表 reports.py:348-361 whitelist → Task 2 擴充；排程報表後端透傳（無第二道，盤點確認）；下游 df_filter → Task 1 補。native 路徑（build_traffic_query_spec）全支援。
- **label_group / IP key 決定**：label_group native 主路徑、cache df follow-up（設計定案已記錄，Task 5 明列）；src_ip_in 前端統一送、df+native 都認（Task 1）。
- **Placeholder 掃描**：df_filter/reports.py 後端給完整碼；前端 modal 換掛載點 + 接線給具體結構（重用 Phase 3 lazy singleton 樣式）+ 靜態斷言 + Task 5 Playwright 把關（同 Phase 3 前端策略）。
- **型別一致性**：FilterBar getFilters key（Task 2 reports.py forward ↔ Task 1 df_filter 消費 ↔ Phase 1 native）沿鏈對齊；`_ensureRptFilterBar`/`_ensureSchedFilterBar`（Task 3/4，仿 Phase 3 `_ensureQtFilterBar`）。
- **已知不確定點（任務內標註）**：報表生成入口實際函式與 monkeypatch 目標（Task 2）、報表端點測試檔名（Task 2/3）、FilterBar deserialize 是否已認 `{dir}_ip` scalar（Task 4）、_collectReportFilters/_collectSchedFilters 的實際行號（Task 3/4，Phase 3 後可能位移）——實作者現場對位。
