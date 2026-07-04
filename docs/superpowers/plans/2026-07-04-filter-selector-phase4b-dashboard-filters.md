# Filter 物件選擇器 Phase 4b：Dashboard 路徑（儲存查詢 + Top10）— Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 dashboard 儲存查詢 modal 的分欄文字 filter 升級為 FilterBar pill 元件，並補齊 dashboard 路徑兩道後端 whitelist 的 forward 缺口——含修正儲存查詢端點把前端已送的 `any_*` 存檔即丟的**既有 bug**。

**Architecture:** dashboard 路徑有兩道各自獨立的 whitelist：(1) 儲存端點 `api_save_dashboard_query` 用 `'=' in src` 啟發式把文字拆成 `src_label`/`src_ip_in`（scalar），whitelist 完全不含 `any_*`（前端有欄位、有送、被丟）與 object/複數 key；(2) Top10 端點 `api_dashboard_top10` 的 params dict 已 forward 舊 scalar key + `any_label`/`any_ip`，但缺全部 object/複數 key。下游 `Analyzer.query_flows` 的 whitelist（Phase 3 已修）**全 key 支援**（analyzer.py:1046-1102，含 label_groups/iplists/workloads/any_*），所以本批只補兩道 dashboard whitelist + 前端換 FilterBar。儲存格式採 **flat 展平**（FilterBar key 直接放 query_def 頂層，與舊 key 共存）——Top10 前端是 `{...q, mins}` spread，flat 儲存讓 payload 自然帶 key，無需中介轉換。

**Tech Stack:** Flask（dashboard.py）、vanilla JS（FilterBar 重用）、pytest + Playwright MCP（controller 實機）。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §10（分批），沿用 Phase 3 FilterBar 契約與 Phase 4a 模式。

## 設計定案（基於 2026-07-04 盤點）

- **現場證據（缺口）**：
  - `dashboard.js:1738-1741` 送 `any_label`/`any_ip`/`ex_any_label`/`ex_any_ip`，但 `api_save_dashboard_query` 的 `query_def`（dashboard.py:369-380）不含這些 key → **存檔即丟**；編輯回填 `dashboard.js:1702-1703` 讀 `q.any_label` 永遠空。Top10 params（dashboard.py:493-507）其實會 forward `any_label`/`any_ip`——鏈斷在儲存端。
  - Top10 params dict 缺：`{ex_}{src|dst}_labels`（複數）、`_label_groups`、`_iplists`、`_workloads`、`any_iplist`/`any_workload`/`ex_any_iplist`/`ex_any_workload`。
- **儲存格式**：新存檔把 FilterBar getFilters() 的 key **flat 展平**進 query_def 頂層（只存 truthy），保留 `name`/`rank_by`/`pd`/`port`/`proto`/`ex_port` 頂層欄位。舊 query_def 的 `src_label`/`src_ip_in`（scalar）等 key 繼續可讀：Top10 端點同時 forward 舊 scalar key 與新複數 key；FilterBar deserialize 對 scalar 原生相容（4a Task 4 已逐 key 驗證 `{dir}_label`/`{dir}_ip_in`/`ex_{dir}_ip` scalar 都認——`asList` 包裝）。
- **key 型別共存**：`src_ip_in` 舊格式是 scalar 字串、新格式是 list——下游 `query_flows` → native `_pop_many`（list/scalar 皆正規化）與 deserialize `asList` 兩種形狀都認，無需遷移。
- **儲存端點相容**：請求帶 `filters` dict（新前端）走新分支；不帶（理論上只剩快取舊頁）走既有啟發式分支不動。
- **label_group**：dashboard 路徑走 `query_flows` native/fallback（非 cache df），`src_label_groups` 等複數 key 下游已支援——**無** 4a 的 cache-df 限制。
- **any 方向 label_group pill 序列化成 any_label 的 Phase 3 既有語意問題**（4a final review Minor）不在本批範圍，follow-up 照舊。

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動各 Task 列出的檔案；不順手重構。
- 新 UI 字串沿用 Phase 3 `gui_fb_*` 既有鍵；若需新鍵，`src/i18n_en.json` 與 `src/i18n_zh_TW.json` 雙語同步。
- **JS 繁中註解格式**：`//` 行首或 `*`-前綴 JSDoc；**禁行尾 `code // 中文`**（i18n audit C 類會抓）。
- CSP：不引入 inline handler；FilterBar 動態元素已用 document 委派。
- 每 Task 結尾跑該 Task 測試 + commit；Task 4 全量（基準以執行時 main 為準，約 2439 passed / 5 skipped）。
- **worktree 紀律**：每個 Bash 命令以絕對 worktree 路徑 `cd` 前綴，commit 前 `git rev-parse --show-toplevel` 驗證、commit 後確認落點；controller 每 task 驗 parent SHA + `git branch --contains` 不在 main。
- **測試驗真實鏈**：攔在離開被測模組的下游邊界（如 monkeypatch `Analyzer.query_flows` 捕 params），不 stub whitelist 邏輯本身。

---

### Task 1: 儲存查詢端點收 FilterBar filters（修 any_* 存檔即丟既有 bug）

**Files:**
- Modify: `src/gui/routes/dashboard.py`（`api_save_dashboard_query`，約 336-397）
- Test: `tests/test_gui_dashboard.py`（追加）

**Interfaces:**
- Produces: `POST /api/dashboard/queries` 接受 `filters` dict（FilterBar getFilters() 格式），whitelist 展平存入 query_def 頂層；無 `filters` 時走既有啟發式分支（不動）。後續 Task 2/3 依賴此 flat 格式。

**背景**：前端已送 `any_label`/`any_ip`/`ex_any_label`/`ex_any_ip`（dashboard.js:1738-1741）但 query_def whitelist 丟棄——既有 bug。本 task 先開新分支收 FilterBar dict（Task 3 之後前端改送 `filters`），同時讓 any_* 經新分支存活。

- [ ] **Step 1: 寫失敗測試（追加 tests/test_gui_dashboard.py，沿用現場登入/CSRF helper 樣式）**

```python
def test_save_dashboard_query_stores_filterbar_keys(app_persistent):
    client = _login(app_persistent)  # 依現場 helper 為準
    r = client.post('/api/dashboard/queries', json={
        "name": "Q1", "rank_by": "count", "pd": 3,
        "filters": {
            "src_labels": ["app=erp", "app=web"],
            "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
            "src_workloads": ["/orgs/1/workloads/abc"],
            "src_label_groups": ["PG-Prod"],
            "src_ip_in": ["10.0.0.1"],
            "ex_dst_ip": ["10.9.9.9"],
            "any_label": "env=prod",
            "any_iplist": "corp-vpn",
            "ex_any_workload": "/orgs/1/workloads/xyz",
        },
    }, headers=..., environ_overrides=...)
    assert r.get_json()["ok"] is True
    saved = client.get('/api/dashboard/queries').get_json()[-1]
    assert saved["src_labels"] == ["app=erp", "app=web"]
    assert saved["dst_iplists"] == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert saved["src_workloads"] == ["/orgs/1/workloads/abc"]
    assert saved["src_label_groups"] == ["PG-Prod"]
    assert saved["src_ip_in"] == ["10.0.0.1"]
    assert saved["ex_dst_ip"] == ["10.9.9.9"]
    assert saved["any_label"] == "env=prod"          # 既有 bug 修復
    assert saved["any_iplist"] == "corp-vpn"
    assert saved["ex_any_workload"] == "/orgs/1/workloads/xyz"
    assert saved["name"] == "Q1"


def test_save_dashboard_query_legacy_branch_unchanged(app_persistent):
    client = _login(app_persistent)
    r = client.post('/api/dashboard/queries', json={
        "name": "Legacy", "rank_by": "count", "pd": 3,
        "src": "app=erp", "dst": "10.0.0.5", "ex_src": "env=dev",
    }, headers=..., environ_overrides=...)
    assert r.get_json()["ok"] is True
    saved = client.get('/api/dashboard/queries').get_json()[-1]
    assert saved["src_label"] == "app=erp"
    assert saved["dst_ip_in"] == "10.0.0.5"
    assert saved["ex_src_label"] == "env=dev"
```

Run: `python3 -m pytest tests/test_gui_dashboard.py -v -k "filterbar_keys or legacy_branch"`
Expected: 第一個 FAIL（filters dict 被忽略、any_label 被丟）、第二個 PASS（既有行為回歸鎖）。

- [ ] **Step 2: 實作（api_save_dashboard_query 加新分支）**

在 `idx = d.get('idx')` 之後、`query_def = {...}` 之前插入新分支，舊 `query_def` 組裝移入 else：

```python
        idx = d.get('idx')
        f = d.get('filters')
        if isinstance(f, dict):
            # Phase 4b：前端 FilterBar 直送序列化 dict——照 whitelist 展平存入
            # query_def 頂層（flat，與舊 scalar 格式 key 共存；src_ip_in 舊為
            # scalar 新為 list，下游 query_flows 與前端 deserialize 兩種形狀都認）。
            # 原啟發式分支的 whitelist 丟棄 any_*（前端有送）——新分支修正此缺口。
            _fb_keys = (
                "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels",
                "src_label_groups", "dst_label_groups",
                "ex_src_label_groups", "ex_dst_label_groups",
                "src_iplists", "dst_iplists", "ex_src_iplists", "ex_dst_iplists",
                "src_workloads", "dst_workloads", "ex_src_workloads", "ex_dst_workloads",
                "src_ip_in", "dst_ip_in", "ex_src_ip", "ex_dst_ip",
                "any_label", "any_ip", "any_iplist", "any_workload",
                "ex_any_label", "ex_any_ip", "ex_any_iplist", "ex_any_workload",
            )
            query_def = {
                "name": name, "rank_by": rank_by, "pd": pd_sel,
                "port": port, "proto": proto, "ex_port": ex_port,
            }
            for k in _fb_keys:
                v = f.get(k)
                if v:
                    query_def[k] = v
        else:
            query_def = {
                "name": name,
                "rank_by": rank_by,
                "pd": pd_sel,
                "port": port, "proto": proto,
                "src_label": src_label, "dst_label": dst_label,
                "src_ip_in": src_ip, "dst_ip_in": dst_ip,
                "ex_port": ex_port,
                "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
                "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip
            }
```

（既有啟發式解析（`src`/`dst`/`ex_src`/`ex_dst` 文字拆解）與後段 config lock 寫入完全不動。）

- [ ] **Step 3: 跑測試確認通過 + 既有不回歸**

Run: `python3 -m pytest tests/test_gui_dashboard.py -q`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/dashboard.py tests/test_gui_dashboard.py
git commit -m "fix(dashboard): accept filter-bar dict on query save and stop dropping any_ keys"
```

---

### Task 2: Top10 端點 forward object/複數 key

**Files:**
- Modify: `src/gui/routes/dashboard.py`（`api_dashboard_top10` 的 params dict，約 493-507）
- Test: `tests/test_gui_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 flat query_def（Top10 前端 `{...q, mins}` spread 直接帶 key）。
- Produces: params dict forward 全部 FilterBar key 給 `Analyzer.query_flows`（analyzer.py:1046-1102 whitelist 已全支援）。

- [ ] **Step 1: 寫失敗測試（monkeypatch query_flows 捕 params——攔下游邊界，whitelist 邏輯真實行使）**

```python
def test_top10_forwards_object_and_plural_filters(app_persistent, monkeypatch):
    client = _login(app_persistent)
    captured = {}
    from src.analyzer import Analyzer
    def fake_query_flows(self, params):
        captured.update(params)
        return []
    monkeypatch.setattr(Analyzer, "query_flows", fake_query_flows)
    client.post('/api/dashboard/top10', json={
        "mins": 30, "pd": 3, "rank_by": "count",
        "src_labels": ["app=erp", "app=web"],
        "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
        "src_workloads": ["/orgs/1/workloads/abc"],
        "src_label_groups": ["PG-Prod"],
        "ex_dst_labels": ["env=dev"],
        "any_iplist": "corp-vpn",
        "ex_any_workload": "/orgs/1/workloads/xyz",
        "src_label": "role=db",
    }, headers=..., environ_overrides=...)
    assert captured.get("src_labels") == ["app=erp", "app=web"]
    assert captured.get("dst_iplists") == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert captured.get("src_workloads") == ["/orgs/1/workloads/abc"]
    assert captured.get("src_label_groups") == ["PG-Prod"]
    assert captured.get("ex_dst_labels") == ["env=dev"]
    assert captured.get("any_iplist") == "corp-vpn"
    assert captured.get("ex_any_workload") == "/orgs/1/workloads/xyz"
    assert captured.get("src_label") == "role=db"    # 舊 scalar key 不回歸
```

註：`Analyzer` 的實際 import 路徑與 top10 內取得 analyzer 實例的方式（`base_ana`）以現場 dashboard.py 為準；若 monkeypatch class method 攔不到（實例綁定），改攔實例工廠，沿用 test_gui_dashboard.py 既有替身樣式。

Run: `python3 -m pytest tests/test_gui_dashboard.py -v -k top10_forwards`
Expected: FAIL（複數/object key 不在 params dict）。

- [ ] **Step 2: 實作（params dict 擴充）**

在既有 params dict（`"ex_any_label": ..., "ex_any_ip": ...` 之後）追加：

```python
                # Phase 4b：forward FilterBar 的 object/複數 key（原 params dict 漏收，
                # 會在此被靜默丟棄；下游 query_flows whitelist 已全支援）。
                "src_labels": d.get("src_labels", []),
                "dst_labels": d.get("dst_labels", []),
                "ex_src_labels": d.get("ex_src_labels", []),
                "ex_dst_labels": d.get("ex_dst_labels", []),
                "src_label_groups": d.get("src_label_groups", []),
                "dst_label_groups": d.get("dst_label_groups", []),
                "ex_src_label_groups": d.get("ex_src_label_groups", []),
                "ex_dst_label_groups": d.get("ex_dst_label_groups", []),
                "src_iplists": d.get("src_iplists", []),
                "dst_iplists": d.get("dst_iplists", []),
                "ex_src_iplists": d.get("ex_src_iplists", []),
                "ex_dst_iplists": d.get("ex_dst_iplists", []),
                "src_workloads": d.get("src_workloads", []),
                "dst_workloads": d.get("dst_workloads", []),
                "ex_src_workloads": d.get("ex_src_workloads", []),
                "ex_dst_workloads": d.get("ex_dst_workloads", []),
                "any_iplist": d.get("any_iplist", ""),
                "any_workload": d.get("any_workload", ""),
                "ex_any_iplist": d.get("ex_any_iplist", ""),
                "ex_any_workload": d.get("ex_any_workload", ""),
```

（既有 scalar key（`src_label`/`src_ip_in`/`any_label` 等）保留不動——舊 query_def 相容。）

- [ ] **Step 3: 跑測試確認通過**

Run: `python3 -m pytest tests/test_gui_dashboard.py -q`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/dashboard.py tests/test_gui_dashboard.py
git commit -m "fix(dashboard): forward object and plural filter keys to query_flows in top10"
```

---

### Task 3: 儲存查詢 modal 換 FilterBar

**Files:**
- Modify: `src/templates/index.html`（`#m-query` 的 dq-* 分欄，約 2337-2390）
- Modify: `src/static/js/dashboard.js`（`saveDashboardQuery` 約 1725-1753、開 modal/回填約 1670-1710）
- Test: `tests/test_component_object_filter_bar.py`（追加）

**Interfaces:**
- Consumes: `window.createFilterBar`、getFilters/setFilters；Task 1 的 `filters` dict 契約。
- Produces: 儲存查詢 modal 用 FilterBar；save 送 `filters: fb.getFilters()`；編輯回填 `fb.setFilters(q)`（flat query_def 直接餵——deserialize 只讀已知 key，`name`/`rank_by` 等頂層欄位自然被忽略；舊格式 `src_label`/`src_ip_in` scalar 原生相容）。

- [ ] **Step 1: index.html 換掛載點**

`#m-query` 內 `dq-src`/`dq-dst`/`dq-exsrc`/`dq-exdst`/`dq-any-label`/`dq-any-ip`/`dq-ex-any-label`/`dq-ex-any-ip` 8 個分欄替換為單一 `<div id="dq-filter-bar"></div>`（含說明 label，沿用 4a 的 `rpt_filter_objects` i18n 鍵）。**保留** `dq-name`/`dq-rank`/`dq-pd` radio 群/`dq-port`/`dq-proto`/`dq-expt`/`dq-idx`。

- [ ] **Step 2: dashboard.js 接線**

1. `_ensureDqFilterBar()` lazy singleton（照 4a `_ensureRptFilterBar` 樣式，dashboard.js 內已有可對照）。
2. 開 modal（約 1670-1710 的 reset/回填段）：新增查詢 reset → `_ensureDqFilterBar().setFilters({})`；編輯 → `_ensureDqFilterBar().setFilters(q)`（flat query_def 直接餵，含舊格式 scalar）。移除 8 個被換欄位的 reset/回填行（含 1697-1698 的 label+ip 字串拼接與 1702-1703 的 any 回填）。
3. `saveDashboardQuery`：移除 `src`/`dst`/`ex_src`/`ex_dst`/`any_*` 讀值，改 `filters: _ensureDqFilterBar().getFilters()`；保留 idx/name/rank_by/pd/port/proto/ex_port。
4. **檢查 dashboard.js 其他讀寫 dq-* 被移除欄位的地方**（grep `dq-`），一併對齊不留死引用。

- [ ] **Step 3: 靜態斷言測試（先寫可先 RED）**

追加 tests/test_component_object_filter_bar.py：index.html 含 `id="dq-filter-bar"`、不含 `id="dq-src"`/`id="dq-any-label"`；dashboard.js 含 `_ensureDqFilterBar`、`saveDashboardQuery` 段含 `filters:`。

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py tests/test_gui_dashboard.py -q`
Expected: 全 PASS。`node --check src/static/js/dashboard.js`。

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): wire filter-bar into dashboard saved-query modal"
```

---

### Task 4: 全量回歸 + i18n + Playwright 實機煙霧（controller）

- [ ] **Step 1: 全量測試**

Run: `python3 -m pytest tests/ -q`
Expected: 執行時 main 基準（約 2439）+ 本批新增全 PASS、0 failed。

- [ ] **Step 2: i18n 稽核**

Run: `python3 scripts/audit_i18n_usage.py`
Expected: 0 findings。

- [ ] **Step 3: controller Playwright MCP 實機煙霧**

scratch config + HTTP + 真實 PCE（同 4a 做法）：
1. 登入 → dashboard → 開儲存查詢 modal → 驗 `#dq-filter-bar` 掛載、setFilters/getFilters round-trip、pill 寬度正常（4a CSS 修復迴歸檢查：含 any pill 時 hint 自成一列）。
2. 舊格式 query_def 回填：`setFilters({src_label:'app=x', src_ip_in:'10.0.0.1', ex_src_ip:'1.2.3.4'})` scalar → pill 正確。
3. 存一個帶 label + iplist + any pill 的查詢 → 重開編輯回填一致 → 跑該 top10 查詢，攔 POST payload 確認帶物件 key、回應正常。
4. console 零錯誤、無 CSP 違規。截圖存證。

- [ ] **Step 4: 回報 + 收尾**

回報全量數字、i18n、實機結果與截圖。final whole-branch review → --no-ff merge（merge-tree 預檢）→ push。

---

## Self-Review 紀錄

- **Spec 覆蓋**：4b 範圍=儲存查詢 + Top10 兩道 whitelist（記憶盤點確認）→ Task 1/2；modal 換 FilterBar → Task 3；下游 query_flows 已支援（Phase 3 修過，analyzer.py:1046-1102 現場確認）不動。
- **每個進入點的第二道 whitelist**：儲存端點（Task 1 新分支）、top10 params（Task 2）；top10 → query_flows 之後無第三道（Phase 3 已修）。排除「上游已支援」假設：analyzer whitelist 逐 key 現場看過（含 label_groups 複數）。
- **既有 bug**：any_* 存檔即丟（前端有送、回填永遠空）——Task 1 修；證據 dashboard.js:1738-1741 vs dashboard.py:369-380。
- **型別一致性**：Task 1 `_fb_keys` = Task 2 params 追加 key = FilterBar getFilters 輸出 key（與 4a reports.py whitelist 同一組 28 key）；`filters` dict 契約 Task 1 定義、Task 3 消費；`_ensureDqFilterBar` Task 3 內一致。
- **舊格式相容三處**：讀（top10 params 保留 scalar key）、回填（deserialize scalar 原生認，4a 已驗）、寫（無 filters dict 走舊分支）。
- **已知不確定點（任務內標註）**：test_gui_dashboard.py 的登入/CSRF helper 名稱與 monkeypatch query_flows 的攔法（Task 1/2 以現場為準）；dq modal 行號（Task 3 現場對位）；`base_ana` 實例的 patch 點（Task 2 註記備援方案）。
