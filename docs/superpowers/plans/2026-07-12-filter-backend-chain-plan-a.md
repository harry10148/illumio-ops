# Plan A：Filter 新類別後端鏈 + rule_hit_count 列印按鈕 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 process_name / windows_service_name / transmission 三類 filter 的完整後端鏈、修復 reports 與 dashboard 白名單漏掉 `ports`/`services` 的現行 silent-drop bug，並補上 rule_hit_count 報表的列印按鈕。

**Architecture:** 依 2026-07-12 七層落差矩陣（spec §6 的層定義）只補真實缺口：L3 native payload 大多已存在，工作集中在 L2 端點白名單、L4 `_flow_matches_filters`、L5 `_OBJECT_FILTER_KEYS`、L6 flatten+df_filter。沿用既有 key 命名並將值擴充為 scalar-or-list。FilterBar UI（Plan B）不在本案。

**Tech Stack:** Python 3.12 / Flask / pandas / pytest。

**Spec:** `docs/superpowers/specs/2026-07-12-pce-native-filter-layout-design.md`（§4.3 修訂版 key 命名）。

## Global Constraints

- key 命名沿用查詢層既有：`process_name`/`ex_process_name`、`windows_service_name`/`ex_windows_service_name`、`transmission`（新 include）/`ex_transmission`（既有 exclude，`transmission_excludes` 別名續留）。值一律 scalar-or-list 兩收。
- `port_range`/`port_ranges`/`ex_port_range`/`ex_port_ranges` **維持現狀不動**——範圍走 `ports` token（`src/port_token.py` 文法已含 range+proto）。
- 兩套 client-side 比對器鐵律：任何 key 擴充必須同時處理 `_flow_matches_filters`（traffic_query.py）與 `check_flow_match`（analyzer.py，本案不擴充 scalar 分支但投影清單 `_OBJECT_FILTER_KEYS` 必須加新 key）。
- cache df 對缺欄位（舊 report_json 列）必須 null-tolerant：include 條件缺欄 → 不命中（fail-closed）；exclude 條件缺欄 → 不排除。
- 字串比對語意：process/winservice 不分大小寫、完整字串相等；transmission 值域 `unicast|broadcast|multicast`（小寫正規化，沿用 `labels._normalize_transmission_values`）。
- Commit：英文 conventional commits、無 emoji。測試指令 `python3 -m pytest <path> -v`（repo root）。
- 真 PCE 驗證（Task 6）為必要步驟，不可只靠單測（歷史教訓：單測曾鎖住錯的 API 形狀）。

---

### Task 1: rule_hit_count 列印按鈕 + exporter 家族守門測試

**Files:**
- Modify: `src/report/exporters/rule_hit_count_html_exporter.py:129-133`（return 區塊）
- Test: `tests/test_exporter_print_button.py`（新建）

**Interfaces:**
- Consumes: 既有 i18n key `rpt_nav_print_pdf`（已存在，policy_diff 等在用）；`report_css.py` 的 `@media print` 樣式已由 `_CSS` 帶入。
- Produces: 無（獨立任務）。

- [ ] **Step 1: 寫失敗的守門測試**

建立 `tests/test_exporter_print_button.py`：

```python
"""Guard: every HTML report exporter must render the shared print button.

rule_hit_count shipped without one (2026-07-04 print-layout plan missed it);
this scans exporter sources so a future report family can't repeat that.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTER_DIR = ROOT / "src" / "report" / "exporters"


def test_every_html_exporter_has_print_button():
    exporters = sorted(EXPORTER_DIR.glob("*_html_exporter.py"))
    assert len(exporters) >= 8  # traffic/audit/ven/pu/readiness/policy_diff/app_summary/rhc
    missing = [p.name for p in exporters if "print-btn" not in p.read_text()]
    assert not missing, f"exporters without print button: {missing}"
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_exporter_print_button.py -v`
Expected: FAIL — missing 含 `rule_hit_count_html_exporter.py`

- [ ] **Step 3: 補列印按鈕**

`src/report/exporters/rule_hit_count_html_exporter.py` 的 return 區塊（:129-133），把：

```python
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_esc(t('rpt_rhc_report_title', lang=lang))}</title>{_CSS}</head>"
            f"<body>{cover}<div class='report-shell'><main class='report-main'>"
            f"{kpi_row}{self._notes()}{body_sections}</main></div>{TABLE_JS}</body></html>"
        )
```

改為（比照 `policy_diff_html_exporter.py:148-151` 的 nav_html 模式，插在 report-shell 與 report-main 之間）：

```python
        nav_html = (
            '<aside class="report-toc screen-only">'
            f'<button class="print-btn" onclick="window.print()">{t("rpt_nav_print_pdf", lang=lang)}</button>'
            '</aside>'
        )
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_esc(t('rpt_rhc_report_title', lang=lang))}</title>{_CSS}</head>"
            f"<body>{cover}<div class='report-shell'>{nav_html}<main class='report-main'>"
            f"{kpi_row}{self._notes()}{body_sections}</main></div>{TABLE_JS}</body></html>"
        )
```

- [ ] **Step 4: 執行測試 + 既有 rhc 測試，確認通過**

Run: `python3 -m pytest tests/test_exporter_print_button.py tests/ -k "rule_hit" -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/rule_hit_count_html_exporter.py tests/test_exporter_print_button.py
git commit -m "fix(report): add print button to rule hit count report; guard all html exporters"
```

---

### Task 2: L2 白名單修復——reports 與 dashboard 漏 `ports`/`services`（現行 silent-drop bug）

**Files:**
- Modify: `src/gui/routes/reports.py:383-422`（report_filters dict）
- Modify: `src/gui/routes/dashboard.py:374-383`（`_fb_keys`）、`src/gui/routes/dashboard.py:519-555`（top10 params dict）
- Test: `tests/test_filter_key_forward_contract.py`（新建；Task 3/5 會擴充）

**Interfaces:**
- Consumes: `analyzer.query_flows` whitelist 已含 `services/ex_services/ports/ex_ports`（analyzer.py:1402-1405）——只缺端點 forward。
- Produces: `tests/test_filter_key_forward_contract.py` 的 `FORWARD_SURFACES` 常數（Task 3/5 對新 key 重用同一張表）。

- [ ] **Step 1: 寫失敗的契約測試**

建立 `tests/test_filter_key_forward_contract.py`：

```python
"""Contract: FilterBar keys must appear in every endpoint forward whitelist.

Whitelist misses are SILENT drops (the analyzer never sees the key) — the
seventh..ninth incidents of this class. This is a static source contract:
each (file, anchor) surface below must name every key in KEYS.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (label, file, anchor-substring-that-identifies-the-dict)
FORWARD_SURFACES = (
    ("reports.report_filters", "src/gui/routes/reports.py", "report_filters = {"),
    ("dashboard._fb_keys", "src/gui/routes/dashboard.py", "_fb_keys = ("),
    ("dashboard.top10_params", "src/gui/routes/dashboard.py", '"src_ip_in": d.get("src_ip_in")'),
)

PILL_KEYS = ("ports", "ex_ports", "services", "ex_services")


def _surface_text(path: str, anchor: str, span: int = 4000) -> str:
    text = (ROOT / path).read_text()
    idx = text.find(anchor)
    assert idx >= 0, f"anchor not found in {path}: {anchor}"
    return text[idx : idx + span]


def test_pill_port_service_keys_forwarded_everywhere():
    for label, path, anchor in FORWARD_SURFACES:
        seg = _surface_text(path, anchor)
        missing = [k for k in PILL_KEYS if f"'{k}'" not in seg and f'"{k}"' not in seg]
        assert not missing, f"{label} missing keys: {missing}"
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_filter_key_forward_contract.py -v`
Expected: FAIL — 三個 surface 都 missing 全部 4 key

- [ ] **Step 3: 修 reports.py**

`report_filters` dict（reports.py:383-422）在 `'ex_any_workload': ...` 行後加：

```python
                    # 2026-07-12 七層對帳：port/service pill key 原漏收（silent drop）。
                    'ports': raw_filters.get('ports', []),
                    'ex_ports': raw_filters.get('ex_ports', []),
                    'services': raw_filters.get('services', []),
                    'ex_services': raw_filters.get('ex_services', []),
```

- [ ] **Step 4: 修 dashboard.py 兩處**

`_fb_keys` tuple（dashboard.py:374-383）末尾加一行：

```python
                "ports", "ex_ports", "services", "ex_services",
```

top10 params dict（dashboard.py:519-555）在 `"ex_any_workload": ...` 行後加：

```python
                "ports": d.get("ports", []),
                "ex_ports": d.get("ex_ports", []),
                "services": d.get("services", []),
                "ex_services": d.get("ex_services", []),
```

- [ ] **Step 5: 執行測試與相關套件，確認通過**

Run: `python3 -m pytest tests/test_filter_key_forward_contract.py -v && python3 -m pytest tests/ -k "dashboard or report_filters or top10" -q`
Expected: 契約測試 passed；相關套件無回歸

- [ ] **Step 6: Commit**

```bash
git add src/gui/routes/reports.py src/gui/routes/dashboard.py tests/test_filter_key_forward_contract.py
git commit -m "fix(gui): forward port/service pill keys in reports and dashboard whitelists"
```

---

### Task 3: process_name / ex_process_name 全鏈（L2/L4/L5/L6）

**Files:**
- Modify: `src/analyzer.py:63-70`（`_OBJECT_FILTER_KEYS`）、`src/analyzer.py:1393-1445`（query_flows whitelist）
- Modify: `src/api/traffic_query.py:599-609`（payload 收 list）、`src/api/traffic_query.py:1020-1148` 區域（matcher 加分支）
- Modify: `src/report/df_filter.py`（process mask）
- Modify: `src/gui/routes/reports.py`、`src/gui/routes/dashboard.py`（兩處）、`src/gui/routes/rules.py:32`、`src/gui/routes/actions.py:132-135`（L2 加 key）
- Test: `tests/test_filter_process_winservice.py`（新建）、`tests/test_filter_key_forward_contract.py`（擴充）

**Interfaces:**
- Consumes: Task 2 的 `FORWARD_SURFACES`。
- Produces: matcher helper `_name_values(filters, key) -> list[str]`（traffic_query.py 模組層，Task 4 重用）；df helper `_name_mask(df, column, values) -> pd.Series`（df_filter.py，Task 4 重用）。

- [ ] **Step 1: 寫失敗測試（matcher + df + payload list 形）**

建立 `tests/test_filter_process_winservice.py`：

```python
import pandas as pd

from src.api.traffic_query import TrafficQueryBuilder
from src.report.df_filter import df_filter


def _flow(process="httpd", port=443, proto=6):
    return {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": port, "proto": proto, "process_name": process},
        "policy_decision": "allowed",
    }


def test_process_name_include_matches_case_insensitive():
    f = TrafficQueryBuilder._flow_matches_filters
    assert f(_flow("HTTPD"), {"process_name": "httpd"})
    assert f(_flow("httpd"), {"process_name": ["HTTPD", "nginx"]})
    assert not f(_flow("nginx"), {"process_name": "httpd"})


def test_process_name_exclude():
    f = TrafficQueryBuilder._flow_matches_filters
    assert not f(_flow("httpd"), {"ex_process_name": ["httpd"]})
    assert f(_flow("nginx"), {"ex_process_name": ["httpd"]})


def test_process_missing_on_flow_is_fail_closed_include():
    f = TrafficQueryBuilder._flow_matches_filters
    flow = _flow(); flow["service"].pop("process_name")
    assert not f(flow, {"process_name": "httpd"})   # include 缺值不命中
    assert f(flow, {"ex_process_name": "httpd"})    # exclude 缺值不排除


def _df(rows):
    return pd.DataFrame(rows)


def test_df_filter_process_name():
    df = _df([
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 443, "proto": "TCP", "process_name": "httpd"},
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 80, "proto": "TCP", "process_name": "nginx"},
    ])
    out = df_filter(df, {"process_name": ["HTTPD"]})
    assert len(out) == 1 and out.iloc[0]["port"] == 443
    out = df_filter(df, {"ex_process_name": "nginx"})
    assert len(out) == 1 and out.iloc[0]["process_name"] == "httpd"


def test_df_filter_process_column_missing_null_tolerant():
    df = _df([{"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 443}])
    assert len(df_filter(df, {"process_name": "httpd"})) == 0   # fail-closed
    assert len(df_filter(df, {"ex_process_name": "httpd"})) == 1  # 不排除


def test_native_payload_accepts_list(monkeypatch):
    from src.api.traffic_query import TrafficQueryBuilder as B
    import types
    b = B.__new__(B)
    b._client = types.SimpleNamespace()
    spec = b.build_traffic_query_spec({"process_name": ["httpd", "nginx"]})
    payload = b._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"], spec=spec)
    entries = [e for e in payload["services"]["include"] if "process_name" in e]
    assert {e["process_name"] for e in entries} == {"httpd", "nginx"}
```

（注意：`_build_native_traffic_payload` 的實際簽名以檔內為準——實作者先讀 `traffic_query.py:206` 的參數列，必要時調整測試呼叫方式；重點斷言是 list 值展開成多個 services entry。）

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_filter_process_winservice.py -v`
Expected: 全部 FAIL（matcher/df 無分支、payload 只收 scalar）

- [ ] **Step 3: matcher 加分支（traffic_query.py）**

在 `_flow_matches_filters` 內（`ports_exc` 段之後、`services` 迴圈之前，約 :1120）插入；helper 放模組層（`parse_port_token` import 附近）：

```python
def _name_values(filters, key):
    """Scalar-or-list 字串值正規化：去空、casefold。"""
    raw = filters.get(key)
    if not raw:
        return []
    vals = raw if isinstance(raw, list) else [raw]
    return [str(v).strip().casefold() for v in vals if v and str(v).strip()]
```

matcher 內：

```python
        # process / windows service 名稱比對（不分大小寫完整相等；include 缺值
        # fail-closed、exclude 缺值不排除——與 cache df 的 null-tolerant 規則一致）
        for inc_key, ex_key, svc_field in (
            ("process_name", "ex_process_name", "process_name"),
            ("windows_service_name", "ex_windows_service_name", "windows_service_name"),
        ):
            inc = _name_values(filters, inc_key)
            if inc:
                flow_val = str(svc.get(svc_field) or "").casefold()
                if not flow_val or flow_val not in inc:
                    return False
            exc = _name_values(filters, ex_key)
            if exc:
                flow_val = str(svc.get(svc_field) or "").casefold()
                if flow_val and flow_val in exc:
                    return False
```

（此段同時涵蓋 Task 4 的 winservice——Task 4 只補 flatten/df 與測試。）

- [ ] **Step 4: payload 收 list（traffic_query.py:599-609）**

把 process/winservice 迴圈改為：

```python
        for key, field_, target in (
            ("process_name", "process_name", "include"),
            ("windows_service_name", "windows_service_name", "include"),
            ("ex_process_name", "process_name", "exclude"),
            ("ex_windows_service_name", "windows_service_name", "exclude"),
        ):
            value = native_filters.get(key)
            if value:
                values = value if isinstance(value, list) else [value]
                for v in values:
                    v = str(v).strip()
                    if v:
                        payload["services"][target].append({field_: v})
                _record_consumed(key, spec.native_filters.get(key))
                _consume_keys((key,))
```

- [ ] **Step 5: analyzer 兩處（:63-70 與 query_flows whitelist）**

`_OBJECT_FILTER_KEYS` 末尾加：

```python
    "process_name", "ex_process_name",
    "windows_service_name", "ex_windows_service_name",
```

query_flows 的 `query_filters` dict（:1393-1445，`"ports"` 群後）加：

```python
            "process_name": params.get("process_name"),
            "ex_process_name": params.get("ex_process_name"),
            "windows_service_name": params.get("windows_service_name"),
            "ex_windows_service_name": params.get("ex_windows_service_name"),
```

- [ ] **Step 6: df_filter 加 mask（helper 供 Task 4 重用）**

`df_filter.py` 在 `_port_entries_mask` 附近加 helper、在 ports 段之後加分支：

```python
def _name_mask(df, column, values):
    """不分大小寫完整相等；缺欄回全 False（呼叫端決定 include/exclude 語意）。"""
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    vals = {str(v).strip().casefold() for v in values if v and str(v).strip()}
    return df[column].fillna("").astype(str).str.strip().str.casefold().isin(vals)
```

```python
    for inc_key, ex_key, col in (
        ("process_name", "ex_process_name", "process_name"),
        ("windows_service_name", "ex_windows_service_name", "windows_service_name"),
    ):
        raw = filters.get(inc_key)
        if raw:
            vals = raw if isinstance(raw, (list, tuple)) else [raw]
            mask &= _name_mask(df, col, vals)      # 缺欄 → 全 False（fail-closed）
        raw = filters.get(ex_key)
        if raw:
            vals = raw if isinstance(raw, (list, tuple)) else [raw]
            mask &= ~_name_mask(df, col, vals)     # 缺欄 → 不排除
```

- [ ] **Step 7: L2 四處端點加 key + 契約測試擴充**

reports.py report_filters、dashboard `_fb_keys`、top10 params、`rules.py:32` 白名單、`actions.py:132-135` params——各加 `process_name`/`ex_process_name`/`windows_service_name`/`ex_windows_service_name`（形式比照該處既有 key）。`tests/test_filter_key_forward_contract.py` 加：

```python
NAME_KEYS = ("process_name", "ex_process_name",
             "windows_service_name", "ex_windows_service_name")

FORWARD_SURFACES_ALL = FORWARD_SURFACES + (
    ("rules.whitelist", "src/gui/routes/rules.py", "src_labels"),
    ("actions.quarantine", "src/gui/routes/actions.py", "src_labels"),
)


def test_name_keys_forwarded_everywhere():
    for label, path, anchor in FORWARD_SURFACES_ALL:
        seg = _surface_text(path, anchor)
        missing = [k for k in NAME_KEYS if f"'{k}'" not in seg and f'"{k}"' not in seg]
        assert not missing, f"{label} missing keys: {missing}"
```

- [ ] **Step 8: 全部測試通過 + 相關套件**

Run: `python3 -m pytest tests/test_filter_process_winservice.py tests/test_filter_key_forward_contract.py -v && python3 -m pytest tests/ -k "traffic_query or df_filter or analyzer" -q`
Expected: all passed

- [ ] **Step 9: Commit**

```bash
git add src/analyzer.py src/api/traffic_query.py src/report/df_filter.py src/gui/routes/ tests/
git commit -m "feat(filter): process and windows service name keys across the full chain"
```

---

### Task 4: windows_service_name 的 flatten 欄位 + 舊列 null-tolerant

**Files:**
- Modify: `src/report/parsers/api_parser.py:87` 附近（flatten 加欄）
- Test: `tests/test_filter_process_winservice.py`（擴充）

**Interfaces:**
- Consumes: Task 3 的 matcher 分支與 `_name_mask`（winservice 已涵蓋）。
- Produces: 統一 df 新欄 `windows_service_name`（str，缺值空字串）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_filter_process_winservice.py` 加：

```python
def test_flatten_carries_windows_service_name():
    from src.report.parsers.api_parser import flatten_flow_record
    rec = {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 53, "proto": 17, "windows_service_name": "Dnscache"},
        "num_connections": 1, "policy_decision": "allowed",
    }
    row = flatten_flow_record(rec)
    assert row["windows_service_name"] == "Dnscache"


def test_df_filter_winservice_null_tolerant_old_rows():
    # 舊 report_json 列沒有此欄——include fail-closed、exclude 不排除
    df = pd.DataFrame([{"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 53}])
    assert len(df_filter(df, {"windows_service_name": "Dnscache"})) == 0
    assert len(df_filter(df, {"ex_windows_service_name": "Dnscache"})) == 1
```

- [ ] **Step 2: 執行測試，確認第一個 FAIL**

Run: `python3 -m pytest tests/test_filter_process_winservice.py -k "flatten or null_tolerant" -v`
Expected: flatten 測試 FAIL（KeyError）；null_tolerant 通過（Task 3 已實作 `_name_mask` 缺欄語意）

- [ ] **Step 3: flatten 加欄**

`api_parser.py` 在 `'process_name': ...` 行（:87）後加：

```python
        'windows_service_name': svc.get('windows_service_name', '') or '',
```

- [ ] **Step 4: 測試通過 + flatten 既有測試**

Run: `python3 -m pytest tests/test_filter_process_winservice.py tests/ -k "flatten or api_parser or cache_flatten" -q`
Expected: all passed（注意 `test_cache_flatten_vectorized.py` 若斷言欄位集合需同步更新——屬預期內行為變更）

- [ ] **Step 5: Commit**

```bash
git add src/report/parsers/api_parser.py tests/test_filter_process_winservice.py
git commit -m "feat(cache): flatten windows_service_name for df-path filtering"
```

---

### Task 5: transmission include key + exclude 側 L4/L5/L6 補鏈

**Files:**
- Modify: `src/api/traffic_query.py`：能力表（:44-79 加 `"transmission"`）、payload（:611-627 加 include 側）、matcher（Task 3 分支後加 transmission 段）
- Modify: `src/analyzer.py`：`_OBJECT_FILTER_KEYS` 加 3 key、query_flows whitelist 加 `"transmission"`
- Modify: `src/report/parsers/api_parser.py`（flatten 加 `transmission` 欄，值取 record 頂層）
- Modify: `src/report/df_filter.py`（transmission mask，重用 `_name_mask`）
- Modify: L2 五處端點（同 Task 3 Step 7 的表面）加 `transmission`/`ex_transmission`
- Test: `tests/test_filter_transmission.py`（新建）、`tests/test_filter_key_forward_contract.py`（擴充 TRANSMISSION_KEYS）

**Interfaces:**
- Consumes: `labels._normalize_transmission_values`（既有）、Task 3 的 `_name_values`/`_name_mask`。
- Produces: flatten 新欄 `transmission`；payload include 形狀 `destinations["include"].append([{"transmission": v}])`（**真 PCE 驗證點**：include 是 list-of-lists 的 OR 組——實作者先讀 `_build_native_traffic_payload` 內其他 destination include actor 的既有 append 形狀並比照；若既有形狀是 flat append 則跟隨既有，Task 6 實測定案）。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_filter_transmission.py`：

```python
import pandas as pd

from src.api.traffic_query import TrafficQueryBuilder
from src.report.df_filter import df_filter


def _flow(tx="broadcast"):
    f = {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 137, "proto": 17},
        "policy_decision": "potentially_blocked",
    }
    if tx is not None:
        f["transmission"] = tx
    return f


def test_transmission_include_and_exclude():
    f = TrafficQueryBuilder._flow_matches_filters
    assert f(_flow("broadcast"), {"transmission": ["broadcast", "multicast"]})
    assert not f(_flow("unicast"), {"transmission": "broadcast"})
    assert not f(_flow("broadcast"), {"ex_transmission": "broadcast"})
    assert f(_flow("unicast"), {"ex_transmission": ["broadcast"]})


def test_transmission_missing_field_null_tolerant():
    f = TrafficQueryBuilder._flow_matches_filters
    assert not f(_flow(None), {"transmission": "broadcast"})  # include fail-closed
    assert f(_flow(None), {"ex_transmission": "broadcast"})   # exclude 不排除


def test_flatten_carries_transmission():
    from src.report.parsers.api_parser import flatten_flow_record
    rec = {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 137, "proto": 17},
        "num_connections": 1, "policy_decision": "allowed",
        "transmission": "multicast",
    }
    assert flatten_flow_record(rec)["transmission"] == "multicast"


def test_df_filter_transmission():
    df = pd.DataFrame([
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 137, "transmission": "broadcast"},
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 53, "transmission": "unicast"},
    ])
    assert len(df_filter(df, {"transmission": "broadcast"})) == 1
    assert len(df_filter(df, {"ex_transmission": ["broadcast"]})) == 1


def test_native_payload_include_side():
    import types
    from src.api.traffic_query import TrafficQueryBuilder as B
    b = B.__new__(B)
    b._client = types.SimpleNamespace()
    spec = b.build_traffic_query_spec({"transmission": ["broadcast"]})
    payload = b._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"], spec=spec)
    flat = str(payload["destinations"]["include"])
    assert "broadcast" in flat  # 形狀細節由 Task 6 真 PCE 定案，此處鎖「有進 include」
```

（payload 測試呼叫簽名同 Task 3 註記——以檔內實際簽名為準調整。）

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_filter_transmission.py -v`
Expected: 全部 FAIL

- [ ] **Step 3: 能力表 + payload include 側**

`_TRAFFIC_FILTER_CAPABILITIES`（:76-77 附近）加：

```python
    "transmission": {"execution": "native", "min_pce_version": "21.2", "notes": "Destination-side transmission include (unicast/broadcast/multicast)."},
```

payload（:611 前、既有 exclude 段之前）加 include 側：

```python
        transmission_include = labels._normalize_transmission_values(
            native_filters.get("transmission")
        )
        if transmission_include:
            for value in transmission_include:
                payload["destinations"]["include"].append([{"transmission": value}])
            _record_consumed("transmission", spec.native_filters.get("transmission"))
            _consume_keys(("transmission",))
        elif "transmission" in native_filters:
            _record_unresolved("transmission", spec.native_filters.get("transmission"))
            _consume_keys(("transmission",))
```

（append 形狀——flat dict vs 單元素 list——先比照檔內其他 include actor 的既有寫法；Task 6 真 PCE 定案後若需改，連同本測試一起修。）

- [ ] **Step 4: matcher + analyzer + flatten + df_filter**

matcher（Task 3 分支之後）：

```python
        tx_inc = _name_values(filters, "transmission")
        if tx_inc:
            flow_tx = str(flow.get("transmission") or "").casefold()
            if not flow_tx or flow_tx not in tx_inc:
                return False
        tx_exc = _name_values(filters, "ex_transmission") or _name_values(filters, "transmission_excludes")
        if tx_exc:
            flow_tx = str(flow.get("transmission") or "").casefold()
            if flow_tx and flow_tx in tx_exc:
                return False
```

`_OBJECT_FILTER_KEYS` 加：`"transmission", "ex_transmission", "transmission_excludes",`
query_flows whitelist 加：`"transmission": params.get("transmission"),`（`transmission_excludes` 行已存在）。

flatten（api_parser.py，`'state'` 行附近）加：

```python
        'transmission': r.get('transmission', '') or '',
```

df_filter（Task 3 迴圈之後）：

```python
    raw = filters.get("transmission")
    if raw:
        vals = raw if isinstance(raw, (list, tuple)) else [raw]
        mask &= _name_mask(df, "transmission", vals)
    raw = filters.get("ex_transmission") or filters.get("transmission_excludes")
    if raw:
        vals = raw if isinstance(raw, (list, tuple)) else [raw]
        mask &= ~_name_mask(df, "transmission", vals)
```

- [ ] **Step 5: L2 五處 + 契約測試擴充**

五個 surface 各加 `transmission`/`ex_transmission`；契約測試加：

```python
TRANSMISSION_KEYS = ("transmission", "ex_transmission")


def test_transmission_keys_forwarded_everywhere():
    for label, path, anchor in FORWARD_SURFACES_ALL:
        seg = _surface_text(path, anchor)
        missing = [k for k in TRANSMISSION_KEYS if f"'{k}'" not in seg and f'"{k}"' not in seg]
        assert not missing, f"{label} missing keys: {missing}"
```

- [ ] **Step 6: 全部測試通過**

Run: `python3 -m pytest tests/test_filter_transmission.py tests/test_filter_key_forward_contract.py tests/test_filter_process_winservice.py -v && python3 -m pytest tests/ -k "traffic_query or df_filter or api_client" -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add src/api/traffic_query.py src/analyzer.py src/report/parsers/api_parser.py src/report/df_filter.py src/gui/routes/ tests/
git commit -m "feat(filter): transmission include key; complete exclude-side client chain"
```

---

### Task 6: 真 PCE 驗證（測試機 .106，必做）

**Files:**
- Create: `.superpowers/sdd/plan-a-live-verification.md`（驗證證據記錄，不入 git 的 scratch）

**Interfaces:**
- Consumes: Tasks 2-5 全部落地並部署到測試機（git pull + restart）。

- [ ] **Step 1: 部署到測試機**

```bash
ssh illumio-ops-test 'cd /root/illumio-ops && git pull --ff-only origin main && systemctl restart illumio-ops && sleep 5 && systemctl is-active illumio-ops'
```

- [ ] **Step 2: 逐項真 PCE 查詢驗證（在測試機以 CLI/Python 直呼）**

對真 PCE 各跑一次 async 查詢並記錄回傳筆數與 payload：

1. `ports: ["1000-2000/tcp"]`（範圍 token → `{"port":1000,"to_port":2000,"proto":6}`）——確認非 4xx 且筆數合理。
2. `ports: ["443"]`（無 proto ＝兩者）——與 `443/tcp`+`443/udp` 兩查詢的聯集筆數比對，驗證「兩者」語意。
3. `process_name: ["<環境中真實存在的 process，先用不帶 filter 的查詢挑一個>"]` ——筆數 > 0 且回傳列的 service.process_name 全部相符。
4. `windows_service_name`（若環境有 Windows workload；無則記錄 N/A 並以 payload 送出不報錯為準）。
5. `transmission: ["broadcast"]`（include）——**形狀定案點**：若 PCE 回 406/400，改用 flat append 形狀重試並回改 Task 5 的 payload 程式與測試。
6. `ex_transmission: ["broadcast"]`——確認回傳零 broadcast 列。

- [ ] **Step 3: 證據寫入記錄檔並回報**

每項記：payload 片段、HTTP 狀態、筆數、結論。任何負結果 = 回改對應 Task 的程式與測試後重驗。

- [ ] **Step 4: Commit（若 Step 2 觸發程式修改）**

```bash
git add -A src/ tests/ && git commit -m "fix(filter): adjust payload shapes per live pce verification"
```

---

### Task 7: 全套驗證 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（Unreleased 區新增條目）

- [ ] **Step 1: 全套測試**

Run: `python3 -m pytest tests/ -q`
Expected: 全綠（基準 3005 passed + 本案新增；任何既有測試因欄位集合變動失敗屬預期內，修測試）

- [ ] **Step 2: CHANGELOG**

Unreleased 區加條目（格式比照現有），涵蓋：process/windows service/transmission filter keys 全鏈、reports 與 dashboard 白名單 silent-drop 修復、flatten 新欄（windows_service_name、transmission）、rule_hit_count 列印按鈕。

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): filter backend chain plan a entries"
```

---

## Self-Review 紀錄

- Spec 覆蓋：§4.3 三類 key（Task 3/4/5）、§6 七層鏈（各 Task 分層落實 + 契約測試）、§8 print（Task 1）、§5 真 PCE 驗證點（Task 6）；`port_range*` 不動與 `ports` token 既通為盤點後的 spec 修訂，已記錄於 spec。
- 佔位掃描：payload 呼叫簽名與 include append 形狀兩處標註「以檔內實際為準／Task 6 定案」——這是刻意的現場驗證點（歷史教訓），非佔位。
- 名稱一致性：`_name_values`（Task 3 定義、Task 5 重用）、`_name_mask`（Task 3 定義、Task 5 重用）、`FORWARD_SURFACES`/`FORWARD_SURFACES_ALL`（Task 2 定義、3/5 擴充）已對齊。
- Plan B（FilterBar v2 前端 + 5 modal 收斂）為後續獨立計畫，依賴本案 key 落地。
