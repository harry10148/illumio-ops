# UI/UX Redesign v2 — Phase 1（設計驗證：快照→比稿→互動樣本→守門放行）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 產出由測試機真資料快照驅動、功能覆蓋 100% 守門通過的全套互動樣本（六區 GUI＋登入＋報表新殼＋CLI 流程稿），交使用者放行後才進 Phase 2 實作。

**Architecture:** 所有產物住 `design/v2/`（納入版控）。mockup 用與未來產品相同的技術形態（原生 ES modules＋tokens.css＋單頁殼），資料一律 fetch 遮罩後的真快照；守門三件套（coverage gate、inline-data lint、Playwright 遍歷）用 pytest 收斂。**本階段絕不修改 `src/`。**

**Tech Stack:** Python 3.12（工具鏈：requests、PyYAML、BeautifulSoup4、pytest、playwright——全部已在 requirements-dev）、原生 ES modules、CSS custom properties。

## Global Constraints（每個任務隱含適用）

- 本階段 **禁改 `src/`**；所有新檔在 `design/v2/`、`tests/design_v2/`、`docs/`
- mockup JS **禁止內嵌手寫資料物件**（lint 強制，Task 5）；畫面資料一律 fetch `design/v2/snapshots/`
- 快照落地前必須遮罩（key 名含 password/token/secret/key/hec/credential → `***MASKED***`）；**遮罩前的原始回應絕不寫入任何檔案**
- PCE 術語保留英文原文（ruleset、enforcement、draft、provision、label、workload、VEN…）
- 不引入 npm/build；vendor 檔只能放 `design/v2/mockup/vendor/`
- 測試機連線一律走環境變數 `ILLUMIO_OPS_E2E_BASE_URL` / `ILLUMIO_OPS_E2E_USER` / `ILLUMIO_OPS_E2E_PASSWORD`（沿用 tests/test_gui_e2e_playwright.py 慣例）；憑證值不落檔、不印出
- Commit 訊息：英文 conventional commits
- 每個任務結尾：`pytest tests/design_v2/ -q` 全綠才 commit

## File Structure（本階段全貌）

```
design/v2/
  tools/
    masking.py            # 遞迴遮罩（Task 1）
    capture_snapshots.py  # 快照抓取 CLI（Task 2）
    endpoints.yaml        # 端點→快照 manifest（Task 2）
    lint_no_inline_data.py# 內嵌資料 lint（Task 5）
    gate_coverage.py      # 功能覆蓋 gate（Playwright DOM 收集）（Task 4）
    reskin_report.py      # 舊報表→新殼重排（Task 13）
    tour.py               # 全遍歷截圖導覽產生器（Task 15）
  snapshots/              # 遮罩後真快照 JSON（Task 3）
  coverage.yaml           # 功能項→data-cov 錨（Task 4）
  pitch/                  # 比稿三稿（Task 6）
  mockup/
    index.html            # 單頁殼（Task 7）
    login.html            # 登入樣本（Task 12）
    assets/tokens.css / components.css / app.css
    js/core/*.mjs  js/components/*.mjs  js/areas/*.mjs
  reports/
    original/             # 測試機抓回的真報表 HTML
    reskinned/            # 新殼版 Traffic/Audit + PDF
  cli-flows.md            # CLI 選單流程稿（Task 14）
  tour/tour.html          # 截圖導覽（Task 15）
tests/design_v2/          # 上述工具的 pytest
```

錨點慣例：mockup 每個功能落點掛 `data-cov="<ID>"`，ID 見 coverage.yaml（OV/IV/AL/AU/RP/SY/LG/XC 前綴）。

---

### Task 1: 工作區腳手架＋遮罩函式庫

**Files:**
- Create: `design/v2/tools/masking.py`
- Create: `design/v2/tools/__init__.py`（空檔）
- Test: `tests/design_v2/test_masking.py`

**Interfaces:**
- Produces: `mask_payload(obj: Any) -> Any`（遞迴遮罩，回新物件）；`SENSITIVE_KEY_RE`（後續 Task 3 遮罩稽核 gate 復用）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/design_v2/test_masking.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"))
from masking import mask_payload

def test_masks_sensitive_keys_recursively():
    src = {"api_key": "AAA", "nested": [{"hec_token": "BBB", "name": "keep"}],
           "password_hash": "CCC", "credentials": {"x": 1}}
    out = mask_payload(src)
    assert out["api_key"] == "***MASKED***"
    assert out["nested"][0]["hec_token"] == "***MASKED***"
    assert out["nested"][0]["name"] == "keep"
    assert out["password_hash"] == "***MASKED***"
    assert out["credentials"] == "***MASKED***"   # 整棵子樹遮掉
    assert src["api_key"] == "AAA"                # 不改原物件

def test_masks_secretish_string_values_even_under_safe_keys():
    # 防呆：value 長得像 PCE api secret（40+ hex）也遮
    out = mask_payload({"note": "a" * 10, "blob": "0123456789abcdef" * 3})
    assert out["note"] == "a" * 10
    assert out["blob"] == "***MASKED***"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/design_v2/test_masking.py -q`
Expected: FAIL（ModuleNotFoundError: masking）

- [ ] **Step 3: 實作**

```python
# design/v2/tools/masking.py
"""遞迴遮罩快照裡的機密。key 命中 → 整值（含子樹）遮蔽；長 hex 字串值也遮。"""
import re
from typing import Any

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api_key|apikey|private_key|credential|hec)", re.I)
_HEXY_VALUE_RE = re.compile(r"^[0-9a-fA-F]{40,}$")
MASK = "***MASKED***"

def mask_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: (MASK if SENSITIVE_KEY_RE.search(str(k)) else mask_payload(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_payload(v) for v in obj]
    if isinstance(obj, str) and _HEXY_VALUE_RE.match(obj):
        return MASK
    return obj
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/design_v2/test_masking.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add design/v2/tools tests/design_v2
git commit -m "feat(design-v2): add snapshot masking library"
```

---

### Task 2: endpoints manifest＋快照抓取 CLI

**Files:**
- Create: `design/v2/tools/endpoints.yaml`
- Create: `design/v2/tools/capture_snapshots.py`
- Test: `tests/design_v2/test_capture_snapshots.py`

**Interfaces:**
- Consumes: `masking.mask_payload`
- Produces: `design/v2/snapshots/<id>.json`（Task 3 產出實檔）；manifest schema `{id, method, path, payload?, note}`

- [ ] **Step 1: 從 JS 呼叫端轉錄 POST payload（source-first，不臆造）**

逐一打開下列呼叫端，把 request body 欄位轉錄進 endpoints.yaml 的 `payload:`（值用測試機上合理的查詢參數，如最近 24h 時間窗）：

```bash
sed -n '255,320p' src/static/js/quarantine.js      # quarantine/search（流量查詢）body
sed -n '518,550p' src/static/js/quarantine.js      # runWorkloadSearch body
grep -n -B2 -A20 "api/dashboard/top10" src/static/js/dashboard.js
grep -n -B2 -A15 "filter-objects/suggest\|filter-objects/browse" src/static/js/filter-bar.js
```

- [ ] **Step 2: 撰寫 endpoints.yaml（GET 全列，POST 附轉錄 payload）**

```yaml
# design/v2/tools/endpoints.yaml — id 對應 snapshots/<id>.json
# GET（無 payload）
- {id: status,              method: GET,  path: /api/status}
- {id: dashboard_overview,  method: GET,  path: /api/dashboard/overview}
- {id: dashboard_queries,   method: GET,  path: /api/dashboard/queries}
- {id: dashboard_snapshot,  method: GET,  path: /api/dashboard/snapshot}
- {id: dashboard_audit,     method: GET,  path: /api/dashboard/audit_summary}
- {id: dashboard_pu,        method: GET,  path: /api/dashboard/policy_usage_summary}
- {id: reports_list,        method: GET,  path: /api/reports}
- {id: report_schedules,    method: GET,  path: /api/report-schedules}
- {id: rhc_enablement,      method: GET,  path: /api/rule_hit_count/enablement}
- {id: rules,               method: GET,  path: /api/rules}
- {id: event_catalog,       method: GET,  path: /api/event-catalog}
- {id: events_viewer,       method: GET,  path: /api/events/viewer?limit=100}
- {id: rs_status,           method: GET,  path: /api/rule_scheduler/status}
- {id: rs_rulesets,         method: GET,  path: /api/rule_scheduler/rulesets}
- {id: rs_schedules,        method: GET,  path: /api/rule_scheduler/schedules}
- {id: rs_logs,             method: GET,  path: /api/rule_scheduler/logs}
- {id: settings,            method: GET,  path: /api/settings}
- {id: alert_plugins,       method: GET,  path: /api/alert-plugins}
- {id: security,            method: GET,  path: /api/security}
- {id: tls_status,          method: GET,  path: /api/tls/status}
- {id: pce_profiles,        method: GET,  path: /api/pce-profiles}
- {id: labels,              method: GET,  path: /api/labels}
- {id: logs_index,          method: GET,  path: /api/logs}
- {id: ui_translations,     method: GET,  path: /api/ui_translations}
# 下列 GET 需先看一筆真資料決定 query 參數，轉錄時補上：
- {id: rs_ruleset_detail,   method: GET,  path: /api/rule_scheduler/rulesets/<第一筆 rs_rulesets 的 id>}
- {id: report_sched_history, method: GET, path: /api/report-schedules/<第一筆 id>/history}
- {id: module_log_sample,   method: GET,  path: /api/logs/<logs_index 第一個模組名>}
# POST（payload 由 Step 1 轉錄；此處鍵名以轉錄結果為準）
- {id: traffic_search,      method: POST, path: /api/quarantine/search,  payload: FROM_STEP1}
- {id: workload_search,     method: POST, path: /api/workloads,          payload: FROM_STEP1}
- {id: top10,               method: POST, path: /api/dashboard/top10,    payload: FROM_STEP1}
- {id: fb_suggest,          method: GET,  path: "/api/filter-objects/suggest?<FROM_STEP1>"}
- {id: fb_browse,           method: GET,  path: "/api/filter-objects/browse?<FROM_STEP1>"}
```

（`FROM_STEP1` 佔位必須在本任務內被真轉錄取代——yaml 交付時不得殘留該字串，Step 5 測試會掃。）

- [ ] **Step 3: 寫失敗測試**

```python
# tests/design_v2/test_capture_snapshots.py
import sys, pathlib, yaml
TOOLS = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"
sys.path.insert(0, str(TOOLS))
import capture_snapshots as cs

def test_manifest_loads_and_has_no_placeholders():
    entries = cs.load_manifest(TOOLS / "endpoints.yaml")
    assert len(entries) >= 30
    assert "FROM_STEP1" not in (TOOLS / "endpoints.yaml").read_text()
    for e in entries:
        assert e["method"] in ("GET", "POST") and e["path"].startswith("/")

def test_capture_writes_masked_json(tmp_path, monkeypatch):
    class FakeResp:
        status_code = 200
        def json(self): return {"api_key": "SECRET", "rows": [1, 2]}
    monkeypatch.setattr(cs, "_request", lambda sess, base, e, csrf: FakeResp())
    out = cs.capture_one(None, "https://x", {"id": "demo", "method": "GET", "path": "/api/x"},
                         tmp_path, csrf="t")
    data = (tmp_path / "demo.json").read_text()
    assert "SECRET" not in data and "***MASKED***" in data
```

- [ ] **Step 4: 跑測試確認失敗** → `pytest tests/design_v2/test_capture_snapshots.py -q` FAIL

- [ ] **Step 5: 實作 capture CLI**

```python
# design/v2/tools/capture_snapshots.py
"""從測試機 GUI 抓真 API 快照（遮罩後落地）。
用法：ILLUMIO_OPS_E2E_BASE_URL=https://host:5001 ILLUMIO_OPS_E2E_USER=... \
      ILLUMIO_OPS_E2E_PASSWORD=... python design/v2/tools/capture_snapshots.py [--only id,id]
"""
import json, os, pathlib, sys
import requests, yaml
from masking import mask_payload

HERE = pathlib.Path(__file__).resolve().parent
SNAP = HERE.parent / "snapshots"

def load_manifest(p):
    return yaml.safe_load(pathlib.Path(p).read_text())

def login(base):
    s = requests.Session()
    # TLS 驗證預設開啟；自簽測試機用 CA bundle 注入，--insecure 需明確指定
    ca = os.environ.get("ILLUMIO_OPS_E2E_CA_BUNDLE")
    if ca:
        s.verify = ca
    elif "--insecure" in sys.argv:
        import urllib3; urllib3.disable_warnings(); s.verify = False
    r = s.post(f"{base}/api/login", json={
        "username": os.environ["ILLUMIO_OPS_E2E_USER"],
        "password": os.environ["ILLUMIO_OPS_E2E_PASSWORD"]}, timeout=30)
    r.raise_for_status()
    body = r.json(); assert body.get("ok"), "login failed"
    return s, body["csrf_token"]

def _request(sess, base, e, csrf):
    if e["method"] == "GET":
        return sess.get(f"{base}{e['path']}", timeout=120)
    return sess.post(f"{base}{e['path']}", json=e.get("payload") or {},
                     headers={"X-CSRFToken": csrf}, timeout=300)

def capture_one(sess, base, e, outdir, csrf):
    r = _request(sess, base, e, csrf)
    if r.status_code != 200:
        print(f"  !! {e['id']}: HTTP {r.status_code}"); return False
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{e['id']}.json").write_text(
        json.dumps(mask_payload(r.json()), ensure_ascii=False, indent=1))
    print(f"  ok {e['id']}"); return True

def main():
    base = os.environ["ILLUMIO_OPS_E2E_BASE_URL"].rstrip("/")
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    sess, csrf = login(base)
    fails = [e["id"] for e in load_manifest(HERE / "endpoints.yaml")
             if (only is None or e["id"] in only)
             and not capture_one(sess, base, e, SNAP, csrf)]
    if fails: sys.exit(f"FAILED: {fails}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 跑測試確認通過** → `pytest tests/design_v2/test_capture_snapshots.py -q` PASS

- [ ] **Step 7: Commit**

```bash
git add design/v2/tools tests/design_v2
git commit -m "feat(design-v2): add endpoint manifest and snapshot capture CLI"
```

---

### Task 3: 對測試機執行抓取，快照落庫＋遮罩稽核 gate

**Files:**
- Create: `design/v2/snapshots/*.json`（~33 檔）
- Test: `tests/design_v2/test_snapshots_sane.py`

**Interfaces:**
- Produces: 全部快照實檔；後續所有 mockup 任務只准讀這裡

- [ ] **Step 1: 寫快照稽核測試（先寫，此刻 snapshots/ 為空會 FAIL）**

```python
# tests/design_v2/test_snapshots_sane.py
import json, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
sys.path.insert(0, str(ROOT / "tools"))
from masking import SENSITIVE_KEY_RE
import yaml

def _snaps():
    files = sorted((ROOT / "snapshots").glob("*.json"))
    assert files, "no snapshots captured"
    return files

def test_every_manifest_entry_has_snapshot():
    ids = {e["id"] for e in yaml.safe_load((ROOT / "tools" / "endpoints.yaml").read_text())}
    have = {p.stem for p in _snaps()}
    assert ids <= have, f"missing snapshots: {ids - have}"

def test_no_unmasked_sensitive_values():
    for p in _snaps():
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if SENSITIVE_KEY_RE.search(str(k)):
                        assert v == "***MASKED***", f"{p.name}:{path}/{k} unmasked"
                    walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o): walk(v, f"{path}[{i}]")
        walk(json.loads(p.read_text()))
```

- [ ] **Step 2: 跑測試確認失敗**（no snapshots captured）

- [ ] **Step 3: 對測試機執行抓取**

Run:
```bash
ILLUMIO_OPS_E2E_BASE_URL=<測試機URL> ILLUMIO_OPS_E2E_USER=<user> \
ILLUMIO_OPS_E2E_PASSWORD=<pw> python design/v2/tools/capture_snapshots.py
```
（憑證由使用者環境／op CLI 提供，不落檔。）Expected: 每行 `ok <id>`，無 `!!`。若個別端點非 200：查對應 route 的必要參數修 manifest 重抓，不准跳過。

- [ ] **Step 4: 跑稽核測試** → `pytest tests/design_v2/test_snapshots_sane.py -q` PASS

- [ ] **Step 5: 抽查三檔形狀對得上 JS 消費端**（人工快檢，指令留檔）

```bash
python - <<'EOF'
import json
for f in ("status", "rules", "rs_schedules"):
    d = json.load(open(f"design/v2/snapshots/{f}.json"))
    print(f, type(d).__name__, list(d)[:8] if isinstance(d, dict) else len(d))
EOF
```
比對消費端：`loadDashboard`（dashboard.js:1324）、`loadRules`（rules.js:74）、`rsLoadSchedules`（rule-scheduler.js:490）讀取的鍵存在。

- [ ] **Step 6: Commit**

```bash
git add design/v2/snapshots tests/design_v2/test_snapshots_sane.py
git commit -m "feat(design-v2): capture masked real-API snapshots from staging"
```

---

### Task 4: coverage.yaml（功能對照表）＋覆蓋 gate 工具

**Files:**
- Create: `design/v2/coverage.yaml`
- Create: `design/v2/tools/gate_coverage.py`
- Test: `tests/design_v2/test_gate_coverage.py`

**Interfaces:**
- Produces: `gate_coverage.collect_dom_cov(base_url, routes) -> set[str]`、`gate_coverage.report(found: set) -> (missing: list, extra: list)`；CLI `python design/v2/tools/gate_coverage.py [--serve]`。Task 8–12 每區完成後跑它；Task 15 終局要求 missing==[]

- [ ] **Step 1: 轉錄 coverage.yaml**

來源=盤點文件 §1（docs/superpowers/specs/2026-08-03-ui-redesign-feature-inventory.md）逐 bullet 轉錄，一項一 ID。前綴：OV 總覽/IV 調查/AL 告警/AU 自動化/RP 報表/SY 系統/LG 登入/XC 跨域。完整清單（86 項）：

```yaml
# design/v2/coverage.yaml — item: 功能, anchor: data-cov 值, route: mockup hash 路由
OV-01: {item: 系統狀態總覽卡, route: "#/overview"}
OV-02: {item: posture score 卡+詳情, route: "#/overview"}
OV-03: {item: Top Actions 區, route: "#/overview"}
OV-04: {item: 自訂查詢卡 CRUD, route: "#/overview"}
OV-05: {item: Top10 查詢, route: "#/overview"}
OV-06: {item: audit 摘要卡, route: "#/overview"}
OV-07: {item: policy usage 摘要卡, route: "#/overview"}
OV-08: {item: dashboard snapshot, route: "#/overview"}
OV-09: {item: 報表最近產出 meta, route: "#/overview"}
OV-10: {item: pipeline 健康摘要(唯讀), route: "#/overview"}
OV-11: {item: job 健康摘要(唯讀), route: "#/overview"}
OV-12: {item: 資料完整性卡(唯讀), route: "#/overview"}
IV-01: {item: 流量分析器查詢+KPI, route: "#/investigate/traffic"}
IV-02: {item: 流量來源切換 cache/PCE, route: "#/investigate/traffic"}
IV-03: {item: 進階篩選(FilterBar), route: "#/investigate/traffic"}
IV-04: {item: 流量查詢指南, route: "#/investigate/traffic"}
IV-05: {item: 流量結果分頁, route: "#/investigate/traffic"}
IV-06: {item: archive 狀態/範圍, route: "#/investigate/traffic"}
IV-07: {item: cache backfill, route: "#/investigate/traffic"}
IV-08: {item: workload 搜尋+分頁, route: "#/investigate/workloads"}
IV-09: {item: 隔離 apply 單台, route: "#/investigate/workloads"}
IV-10: {item: 隔離 bulk apply, route: "#/investigate/workloads"}
IV-11: {item: 隔離 lift, route: "#/investigate/workloads"}
IV-12: {item: 流量更新加速+倒數, route: "#/investigate/workloads"}
IV-13: {item: 事件檢視器三層 catalog, route: "#/investigate/events"}
IV-14: {item: 事件 load-more+詳情卡, route: "#/investigate/events"}
IV-15: {item: shadow compare, route: "#/investigate/events"}
AL-01: {item: 規則清單+啟停+刪除, route: "#/alerting/rules"}
AL-02: {item: Event 規則 drawer, route: "#/alerting/rules"}
AL-03: {item: System health 規則 drawer, route: "#/alerting/rules"}
AL-04: {item: Traffic 規則 drawer, route: "#/alerting/rules"}
AL-05: {item: Bandwidth 規則 drawer, route: "#/alerting/rules"}
AL-06: {item: 規則 highlight 定位, route: "#/alerting/rules"}
AL-07: {item: rule_test 沙盤測試, route: "#/alerting/rules"}
AL-08: {item: run-once, route: "#/alerting/ops"}
AL-09: {item: debug 模式, route: "#/alerting/ops"}
AL-10: {item: 測試告警(全+單管道), route: "#/alerting/ops"}
AL-11: {item: watermark 重置, route: "#/alerting/ops"}
AL-12: {item: 最佳實務套用, route: "#/alerting/ops"}
AL-13: {item: 輸出主控台, route: "#/alerting/ops"}
AL-14: {item: 管道狀態卡(唯讀), route: "#/alerting/ops"}
AU-01: {item: rule scheduler 狀態列+KPI, route: "#/automation/rules"}
AU-02: {item: 排程時間軸, route: "#/automation/rules"}
AU-03: {item: ruleset 瀏覽+詳情, route: "#/automation/rules"}
AU-04: {item: rule 個別搜尋, route: "#/automation/rules"}
AU-05: {item: ruleset 層排程 drawer, route: "#/automation/rules"}
AU-06: {item: rule 層排程 drawer, route: "#/automation/rules"}
AU-07: {item: one-time expire_at 語意, route: "#/automation/rules"}
AU-08: {item: 排程清單+PCE 對帳狀態, route: "#/automation/rules"}
AU-09: {item: 立即檢查, route: "#/automation/rules"}
AU-10: {item: 執行紀錄+清除, route: "#/automation/rules"}
AU-11: {item: 報表排程清單 CRUD, route: "#/automation/reports"}
AU-12: {item: 報表排程 toggle/run-now/history, route: "#/automation/reports"}
AU-13: {item: 背景 job 健康與歷史, route: "#/automation/jobs"}
RP-01: {item: 11 型報表卡+最近產出, route: "#/reports"}
RP-02: {item: 產生 drawer(型專屬參數), route: "#/reports"}
RP-03: {item: 產生進度步驟+async 輪詢, route: "#/reports"}
RP-04: {item: 部分結果處理提示, route: "#/reports"}
RP-05: {item: RHC enablement 檢查/啟用, route: "#/reports"}
RP-06: {item: 產出清單 下載/瀏覽, route: "#/reports"}
RP-07: {item: 產出清單 單刪/批刪, route: "#/reports"}
RP-08: {item: 報表語言切換, route: "#/reports"}
SY-01: {item: PCE profiles CRUD/切換, route: "#/system/pce"}
SY-02: {item: cache 設定表單, route: "#/system/cache"}
SY-03: {item: cache 重啟 banner+daemon restart, route: "#/system/cache"}
SY-04: {item: retention 立即執行, route: "#/system/cache"}
SY-05: {item: 流量過濾器+IP 驗證, route: "#/system/cache"}
SY-06: {item: 流量取樣設定, route: "#/system/cache"}
SY-07: {item: SIEM forwarder 設定, route: "#/system/siem"}
SY-08: {item: SIEM 目的地 CRUD+條件, route: "#/system/siem"}
SY-09: {item: SIEM 測試送出, route: "#/system/siem"}
SY-10: {item: DLQ 搜尋/分頁/回放/清除/匯出/檢視, route: "#/system/siem"}
SY-11: {item: TLS 狀態/續期/CSR/匯入, route: "#/system/tls"}
SY-12: {item: 安全設定(認證/session), route: "#/system/security"}
SY-13: {item: 顯示偏好(主題/密度/時區/語言), route: "#/system/display"}
SY-14: {item: 告警管道連線設定(5 插件), route: "#/system/channels"}
SY-15: {item: 模組日誌檢視器, route: "#/system/logs"}
SY-16: {item: GUI 停止, route: "#/system/security"}
LG-01: {item: 登入表單, route: "login.html"}
LG-02: {item: 首次登入改密碼, route: "login.html"}
XC-01: {item: 全域健康列 5 燈+popover, route: "#/overview"}
XC-02: {item: Cmd+K 指令面板, route: "#/overview"}
XC-03: {item: FilterBar pill/AND-OR/include-exclude/zone, route: "#/investigate/traffic"}
XC-04: {item: 物件選擇 modal(suggest+browse), route: "#/investigate/traffic"}
XC-05: {item: 亮暗主題+密度, route: "#/system/display"}
XC-06: {item: 時區+雙語, route: "#/system/display"}
XC-07: {item: 統一進度元件(可收合), route: "#/reports"}
XC-08: {item: 破壞性確認 modal+影響摘要, route: "#/investigate/workloads"}
XC-09: {item: 空狀態成因提示, route: "#/investigate/traffic"}
XC-10: {item: 錯誤卡+重試+技術細節, route: "#/overview"}
XC-11: {item: 說明側欄(篩選語法/隔離指南), route: "#/investigate/traffic"}
XC-12: {item: toast/popover/欄寬拖曳/skeleton, route: "#/investigate/traffic"}
```

（anchor 一律=ID 本身：`data-cov="OV-01"`。轉錄後與盤點文件逐節對讀一次，漏項就補 ID——對照表寧多勿漏。）

- [ ] **Step 2: 寫 gate 工具失敗測試**

```python
# tests/design_v2/test_gate_coverage.py
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
sys.path.insert(0, str(ROOT / "tools"))
import gate_coverage as gc

def test_report_flags_missing_and_extra():
    missing, extra = gc.report(found={"OV-01", "ZZ-99"})
    assert "OV-02" in missing and "ZZ-99" in extra and "OV-01" not in missing
```

- [ ] **Step 3: 跑測試確認失敗** → FAIL

- [ ] **Step 4: 實作 gate（Playwright 收集動態 DOM 的 data-cov）**

```python
# design/v2/tools/gate_coverage.py
"""功能覆蓋 gate：起本機 http.server 服務 mockup，Playwright 走每條路由，
收集 DOM 中 data-cov，與 coverage.yaml 對帳。"""
import pathlib, subprocess, sys, time
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

def expected():
    return yaml.safe_load((ROOT / "coverage.yaml").read_text())

def report(found: set):
    exp = expected()
    return sorted(set(exp) - found), sorted(found - set(exp))

def collect_dom_cov(base_url: str, routes: list[str]) -> set:
    from playwright.sync_api import sync_playwright
    found = set()
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        for r in routes:
            url = f"{base_url}/{r}" if r.endswith(".html") else f"{base_url}/index.html{r}"
            pg.goto(url); pg.wait_for_timeout(600)
            # drawer/modal 內的錨也要：mockup 約定 window.__openAllForAudit() 依序開啟所有 drawer/modal
            pg.evaluate("window.__openAllForAudit ? window.__openAllForAudit() : null")
            pg.wait_for_timeout(400)
            found |= set(pg.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))
        pg.context.browser.close()
    return found

def main():
    routes = sorted({v["route"] for v in expected().values()})
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8377", "-d", str(ROOT / "mockup")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    try:
        missing, extra = report(collect_dom_cov("http://127.0.0.1:8377", routes))
    finally:
        srv.terminate()
    print(f"covered={len(expected()) - len(missing)}/{len(expected())} extra={extra}")
    if missing:
        print("MISSING:", *missing, sep="\n  "); sys.exit(1)

if __name__ == "__main__":
    main()
```

（mockup 殼在 Task 7 需實作 `window.__openAllForAudit()`：依目前路由開啟該視圖全部 drawer/modal/popover 供稽核。）

- [ ] **Step 5: 跑測試確認通過** → `pytest tests/design_v2/test_gate_coverage.py -q` PASS

- [ ] **Step 6: Commit**

```bash
git add design/v2/coverage.yaml design/v2/tools/gate_coverage.py tests/design_v2/test_gate_coverage.py
git commit -m "feat(design-v2): add feature coverage map and Playwright coverage gate"
```

---

### Task 5: 內嵌資料 lint（上輪死因的機器防線）

**Files:**
- Create: `design/v2/tools/lint_no_inline_data.py`
- Test: `tests/design_v2/test_lint_no_inline_data.py`

**Interfaces:**
- Produces: `lint_file(path) -> list[str]`（違規訊息）；CLI `python design/v2/tools/lint_no_inline_data.py`（掃 `design/v2/mockup/js`＋`design/v2/pitch`，違規 exit 1）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/design_v2/test_lint_no_inline_data.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"))
from lint_no_inline_data import lint_source

def test_flags_array_of_objects():
    assert lint_source('const rows = [{name: "wl1", ip: "10.0.0.1"}];')

def test_flags_big_object_literal():
    assert lint_source('let d = {a:1, b:2, c:3, d:4, e:5};')

def test_allows_small_config_and_fetch():
    assert not lint_source('const opt = {method: "GET"}; const r = await fetch("../snapshots/status.json");')

def test_allow_marker_suppresses():
    assert not lint_source('// lint-allow-inline-data: i18n fallback\nconst x = [{a:1},{a:2}];')
```

- [ ] **Step 2: 跑測試確認失敗** → FAIL

- [ ] **Step 3: 實作**

```python
# design/v2/tools/lint_no_inline_data.py
"""mockup 禁手寫資料：陣列裡的物件字面值、>4 屬性的物件字面值都算違規。
豁免：檔案該行前一行有 `// lint-allow-inline-data: <理由>`。"""
import pathlib, re, sys

ARRAY_OF_OBJ = re.compile(r"\[\s*\{")
BIG_OBJ = re.compile(r"\{(?:[^{}]*?[:][^{}]*?,){4,}")   # ≥5 個 key 的物件
ALLOW = "lint-allow-inline-data"

def lint_source(src: str) -> list[str]:
    out, lines = [], src.splitlines()
    for i, line in enumerate(lines):
        if i > 0 and ALLOW in lines[i - 1]:
            continue
        if ARRAY_OF_OBJ.search(line):
            out.append(f"L{i+1}: array-of-objects literal")
        elif BIG_OBJ.search(line):
            out.append(f"L{i+1}: object literal with >4 keys")
    return out

def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = False
    for p in sorted(list((root / "mockup").rglob("*.mjs")) + list((root / "mockup").rglob("*.js"))
                    + list((root / "pitch").rglob("*.html"))):
        for msg in lint_source(p.read_text()):
            print(f"{p.relative_to(root)}: {msg}"); bad = True
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑測試確認通過** → PASS
- [ ] **Step 5: Commit** → `git add ... && git commit -m "feat(design-v2): add inline-data lint for mockup sources"`

---

### Task 6: 視覺比稿三稿（🚪使用者閘門 1）

**Files:**
- Create: `design/v2/pitch/direction-a.html`、`direction-b.html`、`direction-c.html`（各自內嵌該方向的 token CSS；資料 fetch `../snapshots/`）
- Create: `design/v2/pitch/shots/*.png`

**Interfaces:**
- Consumes: snapshots（status/dashboard_overview/top10/dashboard_audit/dashboard_pu）
- Produces: 使用者選定的方向（記錄於 spec 附註），Task 7 的 token 依據

**執行者必先載入 skills：`frontend-design:frontend-design`、`illumio-brand`、`dataviz`**（本任務是視覺工作，skill 規範優先）。

- [ ] **Step 1: 三個方向各做同一張「總覽區」靜態頁**

同一資訊架構（頂欄+健康列+狀態卡網格+posture+top10 圖表+audit/pu 摘要卡），三種視覺：
- **A｜Illumio brand**：套 illumio-brand skill 的官方色/字型規範，亮色為主
- **B｜Ops console**：深色優先、高資料密度、等寬數字、Grafana 質感（dataviz skill 管圖表色）
- **C｜Editorial light**：極簡亮色、大留白、強字階層（frontend-design skill 主導）

共同硬要求：資料一律 `fetch("../snapshots/…json")`（lint 會掃 pitch/）；三稿都要能切亮暗（`data-theme`）；PCE 術語英文。

- [ ] **Step 2: lint＋截圖**

```bash
python design/v2/tools/lint_no_inline_data.py
python - <<'EOF'
import pathlib, subprocess, sys, time
from playwright.sync_api import sync_playwright
root = pathlib.Path("design/v2")
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8378", "-d", str(root)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.8)
with sync_playwright() as p:
    pg = p.chromium.launch().new_page(viewport={"width": 1440, "height": 900})
    for d in ("a", "b", "c"):
        for theme in ("light", "dark"):
            pg.goto(f"http://127.0.0.1:8378/pitch/direction-{d}.html")
            pg.evaluate(f"document.documentElement.dataset.theme='{theme}'")
            pg.wait_for_timeout(700)
            pg.screenshot(path=f"design/v2/pitch/shots/{d}-{theme}.png", full_page=True)
srv.terminate()
EOF
```
Expected: lint exit 0；6 張截圖產出。

- [ ] **Step 3: Commit＋交使用者選向**

```bash
git add design/v2/pitch && git commit -m "feat(design-v2): add three visual direction pitches for overview"
```
把 6 張截圖交給使用者選（SendUserFile）。**未選定前不得開始 Task 7。** 選定結果以一行附註寫進 spec §0 表格（視覺=方向X）並 commit。

---

### Task 7: tokens＋單頁殼＋核心元件

**Files:**
- Create: `design/v2/mockup/index.html`、`assets/tokens.css`、`assets/components.css`、`assets/app.css`
- Create: `design/v2/mockup/js/core/{router,store,i18n,theme,toast}.mjs`
- Create: `design/v2/mockup/js/components/{healthbar,drawer,modal,table,progress,palette}.mjs`
- Test: gate 冒煙（本任務先覆蓋 XC-01、XC-02、XC-05、XC-10）

**Interfaces:**
- Consumes: 選定方向的 pitch token
- Produces（後續六區任務吃這些 API，簽名固定）：
  - `router.register(route: string, mount: (el, ctx) => Promise<void>)`、`router.go(route)`
  - `store.load(id: string) -> Promise<any>`（fetch `../snapshots/${id}.json`，快取；**mockup 取數唯一入口**）
  - `drawer.open({title, body: HTMLElement, onSave}) `、`modal.confirm({title, impact: string[], onOk})`
  - `healthbar.render(statusSnap, overviewSnap)`（5 燈+popover）
  - `table.render(el, {columns, rows, page, onPage})`（欄寬拖曳/skeleton/空狀態內建）
  - `progress.start(label, steps) -> handle.step(n)/done()`（可收合至右下角）
  - `palette.register(cmd: {id, label, run})`（Cmd/Ctrl+K）
  - `window.__openAllForAudit()`：開啟目前路由全部 drawer/modal（gate 用）
- tokens 命名契約（六區與報表殼都只准用這些）：`--tone-{ok,warn,crit,info,neutral}-{bg,fg,border}`、`--surface-{0,1,2}`、`--text-{1,2,3}`、`--space-{1..8}`、`--font-{ui,mono}`、`--radius-{s,m,l}`

- [ ] **Step 1: 建殼**：頂欄（六區導覽+健康列+palette 鈕+使用者選單）、`<main id="area-root">`、hash router 掛載、`data-theme` 亮暗、密度 `data-density`
- [ ] **Step 2: healthbar 從 `store.load("status")`+`store.load("dashboard_overview")` 算 5 燈**（判定規則轉錄自 `_buildOvPipelineHealth`／`_buildOvCards`（integrations.js:1391-1467）的欄位語意，逐欄位對快照）
- [ ] **Step 3: palette 最小命令集**：六區跳轉+主題切換（後續任務逐區 register）
- [ ] **Step 4: 錯誤卡元件**：`store.load` 失敗渲染 XC-10 錨的錯誤卡（重試+詳情摺疊）
- [ ] **Step 5: 驗證**

```bash
python design/v2/tools/lint_no_inline_data.py          # exit 0
python design/v2/tools/gate_coverage.py                # 預期 FAIL，但 covered ≥ 4（XC-01/02/05/10）
pytest tests/design_v2 -q                              # 全綠
```

- [ ] **Step 6: Commit** → `git commit -m "feat(design-v2): mockup shell, tokens, core components"`

---

### Task 8: 總覽區（OV-01…OV-12）

**Files:**
- Create: `design/v2/mockup/js/areas/overview.mjs`（+必要 CSS）

**Interfaces:**
- Consumes: `store.load`（status/dashboard_overview/dashboard_queries/dashboard_snapshot/dashboard_audit/dashboard_pu/top10/reports_list）、table/drawer/modal/palette
- Produces: route `#/overview` 完整視圖，OV-01…OV-12 全掛 `data-cov`

- [ ] **Step 1:** 依選定方向排版總覽網格：狀態卡列（OV-01）、posture 卡+詳情側欄（OV-02）、Top Actions（OV-03）、自訂查詢卡（OV-04，含新增/編輯 drawer——欄位轉錄自 dashboard_queries 快照第一筆的全部 key）、Top10 圖表卡（OV-05，uPlot 或純 SVG）、audit/pu 摘要（OV-06/07）、snapshot 卡（OV-08）、報表 meta（OV-09，取 reports_list 每型最新一筆）、pipeline/job/完整性唯讀摘要卡（OV-10/11/12，各附「前往」連結到對應區）
- [ ] **Step 2:** `__openAllForAudit` 補開本區 drawer；palette 註冊「新增查詢」
- [ ] **Step 3: 驗證** → lint exit 0；`gate_coverage.py` MISSING 不含 OV-*；pytest 全綠
- [ ] **Step 4: Commit** → `git commit -m "feat(design-v2): overview area mockup"`

---

### Task 9: 調查區（IV-01…IV-15＋XC-03/04/09/11/12＋翻車點守門 #3）

**Files:**
- Create: `design/v2/mockup/js/areas/investigate.mjs`
- Create: `design/v2/mockup/js/components/filter-bar.mjs`（**自 src/static/js/filter-bar.js 移植，序列化邏輯逐行保留**）
- Test: `tests/design_v2/test_filterbar_semantics.py`

**Interfaces:**
- Consumes: snapshots（traffic_search/workload_search/event_catalog/events_viewer/fb_suggest/fb_browse/labels）、Task 7 元件
- Produces: routes `#/investigate/{traffic,workloads,events}`；`filterBar.serialize()` 與生產版 `_objfbSerialize` 位元級同構

- [ ] **Step 1:** 三個子視圖用同一「查詢工作台」骨架：FilterBar+KPI 列+結果表+分頁。流量表 KPI 轉錄 `updateTrafficKpis`（quarantine.js:321）欄位語意；來源切換、archive 列、backfill drawer、指南側欄照 coverage 錨落位
- [ ] **Step 2:** workloads 子視圖：搜尋+bulk bar+隔離 apply/lift 確認 modal（`modal.confirm` impact 列出目標台數與方向——語意轉錄 `_computeQuarantineTargets` quarantine.js:86）+加速 drawer（倒數示意）
- [ ] **Step 3:** events 子視圖：三層 catalog 下拉（category→group→type，選項從 event_catalog 快照生成）、load-more、詳情卡
- [ ] **Step 4: FilterBar AND/OR 守門測試（翻車點 #3）**

```python
# tests/design_v2/test_filterbar_semantics.py
"""mockup FilterBar 序列化必須與生產 filter-bar.js 同構：
用 Playwright 在兩份原始碼上跑同一組往返案例比對輸出。"""
import json, pathlib, subprocess, sys, time
import pytest
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "design/v2/snapshots/dashboard_queries.json").read_text())

@pytest.mark.parametrize("mode", ["and", "or"])
def test_serialize_roundtrip_matches_production(mode):
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        results = {}
        for name, src in {"prod": "src/static/js/filter-bar.js",
                          "mock": "design/v2/mockup/js/components/filter-bar.mjs"}.items():
            pg.goto("about:blank")
            pg.add_script_tag(content=(ROOT / src).read_text().replace("export ", ""))
            results[name] = pg.evaluate(
                """([cases, mode]) => cases.filter(c => c.filters).map(c =>
                     _objfbSerialize(_objfbDeserialize({...c.filters, mode})))""",
                [CASES if isinstance(CASES, list) else CASES.get("queries", []), mode])
        assert results["mock"] == results["prod"]
```
（若快照裡沒有帶 filters 的查詢：先在測試機建一筆含 AND、一筆含 OR 的查詢再重抓 dashboard_queries 快照——不准用手寫 case。）

- [ ] **Step 5: 驗證** → lint 0；gate MISSING 不含 IV-*/XC-03/04/09/11/12；`pytest tests/design_v2 -q` 全綠
- [ ] **Step 6: Commit** → `git commit -m "feat(design-v2): investigate area mockup with production-parity filter bar"`

---

### Task 10: 告警區（AL-01…AL-14＋翻車點守門 #2）

**Files:**
- Create: `design/v2/mockup/js/areas/alerting.mjs`
- Test: `tests/design_v2/test_alert_rule_fields.py`

**Interfaces:**
- Consumes: snapshots（rules/event_catalog/alert_plugins/status）、Task 7 元件、Task 9 filter-bar.mjs
- Produces: routes `#/alerting/{rules,ops}`；四型規則 drawer 的欄位 `data-field="<後端欄名>"` 契約

- [ ] **Step 1:** rules 子視圖：規則清單（型別 badge、啟停 toggle、批刪、highlight 跳位）＋四型 drawer。**每型表單欄位=該型在 rules 快照中實際出現的 key**，控件上掛 `data-field="<key>"`；條件區塊語意轉錄各 save 函式（rules.js:515-583 `saveEvent/saveSystemRule/saveTraffic/saveBW`）
- [ ] **Step 2:** ops 子視圖：run-once/debug/測試告警（全+單管道，管道卡從 alert_plugins 快照）/watermark/最佳實務/輸出主控台（monospace 滾動區）
- [ ] **Step 3:** rule_test 沙盤：貼事件 JSON→顯示會命中哪些規則（mockup 以快照內事件示意）
- [ ] **Step 4: 四型欄位覆蓋守門（翻車點 #2）**

```python
# tests/design_v2/test_alert_rule_fields.py
"""四型告警規則 drawer 必須覆蓋快照中該型物件的全部欄位（減internal鍵）。"""
import json, pathlib, subprocess, sys, time
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
INTERNAL = {"id", "idx", "enabled", "created_at", "updated_at", "last_run", "last_status"}

def test_drawer_fields_cover_snapshot_keys():
    rules = json.loads((ROOT / "snapshots" / "rules.json").read_text())
    rules = rules["rules"] if isinstance(rules, dict) and "rules" in rules else rules
    by_type = {}
    for r in rules: by_type.setdefault(r["type"], r)
    assert set(by_type) >= {"event", "system", "traffic", "bandwidth"}, \
        "測試機需先各型建至少一條規則再重抓快照"
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8379", "-d", str(ROOT / "mockup")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    try:
        with sync_playwright() as p:
            pg = p.chromium.launch().new_page()
            pg.goto("http://127.0.0.1:8379/index.html#/alerting/rules")
            pg.wait_for_timeout(800)
            for rtype, rule in by_type.items():
                pg.evaluate(f"window.__openRuleDrawer('{rtype}')")
                pg.wait_for_timeout(300)
                have = set(pg.eval_on_selector_all(
                    "[data-field]", "els => els.map(e => e.dataset.field)"))
                missing = set(rule) - INTERNAL - have
                assert not missing, f"{rtype} drawer missing fields: {missing}"
    finally:
        srv.terminate()
```
（alerting.mjs 需暴露 `window.__openRuleDrawer(type)` 供本測試與 `__openAllForAudit` 用。）

- [ ] **Step 5: 驗證** → lint 0；gate MISSING 不含 AL-*；pytest 全綠
- [ ] **Step 6: Commit** → `git commit -m "feat(design-v2): alerting area mockup with rule-field coverage guard"`

---

### Task 11: 自動化區（AU-01…AU-13＋翻車點守門 #1）

**Files:**
- Create: `design/v2/mockup/js/areas/automation.mjs`
- Test: `tests/design_v2/test_rule_scheduler_model.py`

**Interfaces:**
- Consumes: snapshots（rs_status/rs_rulesets/rs_ruleset_detail/rs_schedules/rs_logs/report_schedules/report_sched_history/dashboard_overview）
- Produces: routes `#/automation/{rules,reports,jobs}`

- [ ] **Step 1:** rules 子視圖：狀態列+KPI+時間軸（rs_status/rs_schedules 驅動）、ruleset 清單→詳情（清單→詳情版式）、rule 搜尋、排程清單（**目標欄顯示 ruleset 或 rule 兩種型態，PCE 對帳狀態欄**——欄位語意逐鍵對 rs_schedules 快照）、雙 drawer（ruleset 層/rule 層各一，one-time 必填 `expire_at`、action allow/disable 語意轉錄 routes/rule_scheduler.py:302-393 的驗證規則）、立即檢查、執行紀錄+清除
- [ ] **Step 2:** reports 子視圖：報表排程清單 CRUD drawer+toggle/run-now/history（report_schedules/report_sched_history 驅動）
- [ ] **Step 3:** jobs 子視圖：背景 job 健康表（dashboard_overview 的 job 區塊欄位）＋語意 tone
- [ ] **Step 4: rule scheduler 資料模型守門（翻車點 #1）**

```python
# tests/design_v2/test_rule_scheduler_model.py
"""mockup 排程表必須逐筆如實呈現 rs_schedules 快照：筆數一致、
每筆的目標型態（ruleset vs rule）與 one-time/recurring 型態如實對應。"""
import json, pathlib, subprocess, sys, time
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"

def test_schedule_rows_mirror_snapshot():
    snap = json.loads((ROOT / "snapshots" / "rs_schedules.json").read_text())
    schedules = snap["schedules"] if isinstance(snap, dict) and "schedules" in snap else snap
    assert schedules, "測試機需至少有 1 筆 ruleset 排程＋1 筆 rule 排程，缺就先建再重抓"
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8380", "-d", str(ROOT / "mockup")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    try:
        with sync_playwright() as p:
            pg = p.chromium.launch().new_page()
            pg.goto("http://127.0.0.1:8380/index.html#/automation/rules")
            pg.wait_for_timeout(800)
            rows = pg.eval_on_selector_all(
                "[data-cov='AU-08'] [data-sched-target-kind]",
                "els => els.map(e => e.dataset.schedTargetKind)")
            assert len(rows) == len(schedules)
            kinds = {"rule" if "/sec_rules/" in str(s) else "ruleset" for s in map(json.dumps, schedules)}
            assert set(rows) == kinds
    finally:
        srv.terminate()
```

- [ ] **Step 5: 驗證** → lint 0；gate MISSING 不含 AU-*；pytest 全綠
- [ ] **Step 6: Commit** → `git commit -m "feat(design-v2): automation area mockup with scheduler-model guard"`

---

### Task 12: 報表區＋系統區＋登入頁（RP/SY/LG/剩餘 XC）

**Files:**
- Create: `design/v2/mockup/js/areas/reports.mjs`、`system.mjs`
- Create: `design/v2/mockup/login.html`（+`js/areas/login.mjs`）

**Interfaces:**
- Consumes: snapshots（reports_list/report_schedules/rhc_enablement/labels/settings/alert_plugins/security/tls_status/pce_profiles/logs_index/module_log_sample/status）
- Produces: routes `#/reports`、`#/system/{pce,cache,siem,tls,security,display,channels,logs}`、`login.html`

- [ ] **Step 1:** 報表區：11 型卡（meta 從 reports_list）、產生 drawer（每型參數區塊轉錄 `openReportGenModal`＋各 `_doGenerate*`（dashboard.js:660-1323）送出的 body 欄位，掛 `data-field`）、統一進度元件示意（XC-07）、RHC enablement 流程、產出清單（下載/瀏覽/單刪/批刪）、報表語言切換
- [ ] **Step 2:** 系統區八子頁全部用「設定表單頁」版式：PCE profiles、cache（設定+重啟 banner+retention+過濾器+取樣）、SIEM（forwarder+目的地 CRUD drawer+測試+DLQ 清單→詳情）、TLS（狀態卡+續期+CSR+匯入）、安全（+GUI 停止）、顯示（主題/密度/時區/語言，XC-05/06 錨在此）、管道設定（5 插件動態表單，欄位從 alert_plugins 快照 schema）、模組日誌（logs_index+module_log_sample）
- [ ] **Step 3:** 登入頁：一般登入＋`must_change_password` 分支的改密碼表單（轉錄 auth 流程，LG-01/02）
- [ ] **Step 4: 驗證** → lint 0；**`gate_coverage.py` 首次要求全綠（MISSING==[]）**；pytest 全綠
- [ ] **Step 5: Commit** → `git commit -m "feat(design-v2): reports/system areas and login mockup — coverage gate green"`

---

### Task 13: 報表新殼＋Traffic/Audit 真資料重排＋print/PDF 驗證

**Files:**
- Create: `design/v2/reports/shell.css`（報表版 token 子集，恆亮）
- Create: `design/v2/tools/reskin_report.py`
- Create: `design/v2/reports/original/{traffic,audit}.html`（測試機抓回）、`reskinned/{traffic,audit}.html`、`reskinned/*.pdf`、`reskinned/shots/*.png`
- Test: `tests/design_v2/test_reskin_report.py`

**Interfaces:**
- Consumes: 測試機 `/api/reports`＋`/reports/<filename>`（沿 capture 登入流程）；tokens 契約（Task 7）
- Produces: 新報表殼視覺規格（Phase 2 重寫 report_css.py 的依據）

- [ ] **Step 1:** 從測試機抓最新 traffic 與 audit 報表 HTML 存 original/（用 capture_snapshots 的 login，GET `/reports/<f>` 存文字；報表若不存在先以 GUI 產一份）
- [ ] **Step 2: 寫失敗測試**

```python
# tests/design_v2/test_reskin_report.py
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"))
from reskin_report import extract_sections, build_shell

def test_extract_keeps_all_tables_and_headings():
    html = (pathlib.Path("design/v2/reports/original/audit.html")).read_text()
    secs = extract_sections(html)
    import re
    assert sum(s["html"].count("<table") for s in secs) == len(re.findall(r"<table\b", html))
    assert all(s["title"] for s in secs)

def test_shell_has_toc_print_css_and_no_silent_truncation():
    out = build_shell("Audit Report", extract_sections(
        pathlib.Path("design/v2/reports/original/audit.html").read_text()))
    assert 'class="toc"' in out and "@media print" in out
    assert "text-overflow" not in out or "title=" in out  # 省略必附 title 全文
```

- [ ] **Step 3:** 實作 `reskin_report.py`：BeautifulSoup 依原報表的章節容器（h2/section 邊界，逐報表型對原始 exporter 的實際輸出結構轉錄 selector）切 sections → 填進新殼模板（封面/執行摘要/目錄/發現卡/明細/附錄，spec §4.1 順序），套 shell.css。截斷規則落實：長欄 `white-space:normal` 換行為主，僅代碼類欄用省略＋`title` 全文
- [ ] **Step 4:** 產出＋雙寬度＋PDF：

```bash
python design/v2/tools/reskin_report.py
python - <<'EOF'
from playwright.sync_api import sync_playwright
import pathlib
with sync_playwright() as p:
    for name in ("traffic", "audit"):
        f = pathlib.Path(f"design/v2/reports/reskinned/{name}.html").resolve().as_uri()
        pg = p.chromium.launch().new_page()
        for w in (1280, 800):
            pg.set_viewport_size({"width": w, "height": 1000}); pg.goto(f)
            pg.screenshot(path=f"design/v2/reports/reskinned/shots/{name}-{w}.png", full_page=True)
        pg.pdf(path=f"design/v2/reports/reskinned/{name}.pdf", format="A4",
               print_background=True)
        pg.context.browser.close()
EOF
```
逐頁親看兩份 PDF＋4 張截圖：無截斷/溢出才算過（CLAUDE.md 硬規則），檢查結果寫進 commit 訊息。

- [ ] **Step 5:** pytest 全綠 → Commit `feat(design-v2): report shell prototype with real-data traffic/audit reskin (page-checked)`

---

### Task 14: CLI 選單流程稿

**Files:**
- Create: `design/v2/cli-flows.md`

**Interfaces:**
- Consumes: src/cli/menus/*.py（現況轉錄）＋spec §5
- Produces: Phase 2 CLI 重組的逐畫面規格

- [ ] **Step 1:** 轉錄現況選單樹（逐檔讀 menus/，畫成樹狀）＋新六區主選單樹的對照表（舊項→新落點，一項不漏——以功能盤點 §3.2 為 checklist）
- [ ] **Step 2:** 新選單逐畫面 ASCII 稿：主選單（含頂部健康列 `●●●○○` 樣式）、每個精靈的逐步畫面（第 n/N 步+目前值+預設值+0=返回）、破壞性動作影響摘要畫面
- [ ] **Step 3:** 自查：對照表左欄=盤點 §3.2 全項且右欄無空格 → Commit `docs(design-v2): CLI menu flow spec aligned to six-area IA`

---

### Task 15: 截圖導覽＋終局守門＋交付（🚪使用者閘門 2）

**Files:**
- Create: `design/v2/tools/tour.py`、`design/v2/tour/tour.html`＋`tour/shots/*.png`
- Test: `tests/design_v2/test_final_gate.py`

**Interfaces:**
- Consumes: 全部前置產物
- Produces: 交付包（tour.html＋coverage 報告＋mockup 入口）

- [ ] **Step 1:** `tour.py`：起 http.server，Playwright 走 coverage.yaml 全路由 × 亮/暗 × `__openAllForAudit`，逐畫面截圖；產 `tour.html`——每張截圖附路由名、該畫面覆蓋的 cov ID 清單與功能名（從 coverage.yaml 反查）
- [ ] **Step 2: 終局守門測試**

```python
# tests/design_v2/test_final_gate.py
"""放行前終局檢查：覆蓋 100%、lint 乾淨、tour 齊全。"""
import pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]

def test_coverage_gate_green():
    r = subprocess.run([sys.executable, "design/v2/tools/gate_coverage.py"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_lint_clean():
    r = subprocess.run([sys.executable, "design/v2/tools/lint_no_inline_data.py"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout

def test_tour_has_all_routes():
    import yaml
    cov = yaml.safe_load((ROOT / "design/v2/coverage.yaml").read_text())
    tour = (ROOT / "design/v2/tour/tour.html").read_text()
    for route in {v["route"] for v in cov.values()}:
        assert route in tour, f"tour missing {route}"
```

- [ ] **Step 3:** `pytest tests/design_v2 -q` 全綠（含三個翻車點守門）＋既有全套 `pytest -q` 不退化（本階段沒動 src/，快檢即可）
- [ ] **Step 4:** Commit `feat(design-v2): screenshot tour and final gates — mockup ready for review`
- [ ] **Step 5:** 交付使用者：tour.html＋coverage 統計＋mockup 開啟方式（`python -m http.server -d design/v2/mockup`）＋兩份重排報表 PDF。**等待放行。放行後才寫 Phase 2 計畫（逐區改 src/）。**

---

## Self-Review 紀錄

- Spec 覆蓋：§1 IA→Task 7-12；§2 元件→Task 7＋各區；§3 技術→Task 7（形態同產品）；§4 報表→Task 13；§5 CLI→Task 14；§6 快照/守門/三階段→Task 1-6、15；三翻車點→Task 9/10/11 ✓
- 型別一致：`store.load`/`drawer.open`/`modal.confirm`/`data-cov`/`data-field`/`data-sched-target-kind` 貫穿各任務同名 ✓
- 佔位掃描：manifest 的 `FROM_STEP1` 有 Step 5 測試強制清除；無其他 TBD ✓
- Phase 2（實作 src/）依本計畫終點的放行樣本另立計畫，不在此檔 ✓
