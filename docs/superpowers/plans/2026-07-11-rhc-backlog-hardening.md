# Rule Hit Count Backlog Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收斂 Rule Hit Count 真 PCE 驗證（v1/v2 報告）與 final review 累積的 5 項 backlog（spec：`docs/superpowers/specs/2026-07-11-rhc-backlog-hardening-design.md`）。

**Architecture:** 全部是既有機制的補強：opt-in 失敗例外（`raise_on_error`）走 generator 既有 except 路徑、CSV 別名表擴充＋既有 pass-through 慣例、traffic 路由白名單前例複製、submit fail-fast、pin 測試。單分支 `fix/rhc-backlog-hardening` 串行（Task 1/2/5 共檔 `rule_hit_count_generator.py`＋其測試檔）。

**Tech Stack:** 既有（pytest、pandas、loguru、Flask）。

## Global Constraints

- TDD：先寫失敗測試再實作（superpowers:test-driven-development）；Task 5 是 pin 測試，預期直接 GREEN——若 RED 即發現真 bug，停下回報，不得為湊綠改測試。
- i18n 新鍵三檔流程：`src/i18n_en.json` 加 en 值＋`src/i18n/data/zh_explicit.json` 加 zh 值＋跑 `python3 -m scripts.precompute_zh_translations --write` 重生 `src/i18n_zh_TW.json`（三檔一起 commit）。
- zh 譯文遵守 glossary 禁譯規則（`src/i18n/data/glossary.json`：PCE/VEN/Service/Policy/Ruleset 等保留英文，禁用「服務」「政策」等替代字）。
- Commit message 英文 conventional-commits；一切輸出（含註解、i18n 值）不用 emoji。
- 每 task 後：聚焦測試 GREEN → 收尾跑全套 `python3 -m pytest -q` 全綠；`ruff check` 改動檔零新增 violations。
- 本機無 `python`，一律 `python3 -m pytest ...`。
- 預設行為變更僅限 spec 明定項（`raise_on_error=True` 只有 RHC generator opt-in；上傳白名單兩條新路由；submit no-href fail-fast）；其餘零行為變更。
- 行號以檔案現況為準（本 plan 引用行號來自 2026-07-11 main @d039bf1，可能漂移——以符號/內容定位）。

---

### Task 1: enrichment 失敗訊號斷鏈（spec §A）

**Files:**
- Modify: `src/api_client.py`（`get_all_rulesets`，:784-793 一帶）
- Modify: `src/report/rule_hit_count_generator.py`（`_enrich_rows` 的 `get_all_rulesets` 呼叫，:239）
- Test: `tests/test_api_client_get_all_rulesets.py`（新檔，照 `tests/test_api_client_get_all_labels.py` 樣式）
- Test: `tests/test_rule_hit_count_generator.py`（`TestCsvEnrichment` 擴充）

**Interfaces:**
- Produces: `ApiClient.get_all_rulesets(force_refresh: bool = False, raise_on_error: bool = False) -> list[dict]`——`raise_on_error=True` 時非 200（含 status 0 連線層失敗）raise `RuntimeError`；預設 False 行為零變更（其他 5 個呼叫端不動）。
- Consumes: `_enrich_rows` 既有 `except Exception` → `enrich_failed=True` → exporter 既有 `rpt_rhc_note_enrich_failed` 注記鏈（`tests/test_rule_hit_count_html_exporter.py::test_enrich_failed_note_shown` 已覆蓋，不動）。
- 不動：`src/interfaces.py` 的 `IApiClient` Protocol（Analyzer/RuleScheduler 不用新參數）。

- [ ] **Step 1: 寫失敗測試（RED）**——新檔 `tests/test_api_client_get_all_rulesets.py`：

```python
"""get_all_rulesets raise_on_error — enrichment 失敗訊號鏈（真 PCE 驗證 v1 項 6）。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


class TestGetAllRulesetsRaiseOnError(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def test_default_returns_empty_on_http_error(self):
        # 零行為變更釘：預設仍回 []（rule_scheduler/policy_diff 等呼叫端依賴）
        self.client._api_get = lambda ep, timeout=15: (403, None)
        self.assertEqual(self.client.get_all_rulesets(), [])

    def test_raise_on_error_raises_on_http_error(self):
        self.client._api_get = lambda ep, timeout=15: (403, None)
        with self.assertRaises(RuntimeError) as ctx:
            self.client.get_all_rulesets(raise_on_error=True)
        self.assertIn("403", str(ctx.exception))

    def test_raise_on_error_raises_on_connection_layer_failure(self):
        # _request 連線層失敗慣例：status 0（v1 報告附註的未驗證縫，一併涵蓋）
        self.client._api_get = lambda ep, timeout=15: (0, None)
        with self.assertRaises(RuntimeError):
            self.client.get_all_rulesets(raise_on_error=True)

    def test_raise_on_error_returns_data_on_200(self):
        rs = [{"href": "/orgs/1/sec_policy/draft/rule_sets/1", "rules": []}]
        self.client._api_get = lambda ep, timeout=15: (200, rs)
        self.assertEqual(self.client.get_all_rulesets(raise_on_error=True), rs)

    def test_raise_on_error_empty_200_is_legit_empty(self):
        # 200 且空 list = 合法空 org，不 raise
        self.client._api_get = lambda ep, timeout=15: (200, [])
        self.assertEqual(self.client.get_all_rulesets(raise_on_error=True), [])
```

`tests/test_rule_hit_count_generator.py` 的 `TestCsvEnrichment` 加一測（釘 generator opt-in）：

```python
    def test_enrichment_opts_into_raise_on_error(self):
        """真 PCE 驗證 v1 項 6：HTTP 40x 時 get_all_rulesets 預設回 [] 不拋例外，
        enrich_failed 永不為 True、HTML 無注記、欄位靜默全空。generator 必須以
        raise_on_error=True 呼叫，讓 HTTP 失敗走既有 except 路徑設旗標。"""
        api = MagicMock()
        api.get_all_rulesets.side_effect = RuntimeError("get_all_rulesets failed: HTTP 403")
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td))
        self.assertTrue(result.module_results.get("enrich_failed"))
        api.get_all_rulesets.assert_called_once_with(force_refresh=True, raise_on_error=True)
```

Run: `python3 -m pytest tests/test_api_client_get_all_rulesets.py tests/test_rule_hit_count_generator.py -q` → 新測試 FAIL（`raise_on_error` 是未知 kwarg／`assert_called_once_with` 不符）。

- [ ] **Step 2: 實作**——`src/api_client.py`：

```python
    def get_all_rulesets(self, force_refresh: bool = False,
                         raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get all rulesets from PCE (cached unless force_refresh).

        raise_on_error=True: any non-200 (incl. status 0 = connection-layer
        failure per _request) raises RuntimeError instead of silently
        returning [] — opt-in for callers that must distinguish fetch failure
        from a legitimately empty org (rule hit count enrich_failed signal,
        real-PCE verified 2026-07-11). Default False keeps the legacy
        empty-list contract for all existing callers.
        """
        if self.ruleset_cache and not force_refresh:
            return self.ruleset_cache
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/rule_sets?max_results=10000")
        if status == 200 and data:
            self.ruleset_cache = data
            return self.ruleset_cache
        if raise_on_error and status != 200:
            raise RuntimeError(f"get_all_rulesets failed: HTTP {status}")
        return []
```

`src/report/rule_hit_count_generator.py` `_enrich_rows` 呼叫改為：

```python
            rulesets = self.api.get_all_rulesets(force_refresh=True, raise_on_error=True)
```

- [ ] **Step 3: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_api_client_get_all_rulesets.py tests/test_rule_hit_count_generator.py tests/ -q -k "rule_hit or api_client or policy_diff or policy_usage or rule_scheduler" && ruff check src/api_client.py src/report/rule_hit_count_generator.py tests/test_api_client_get_all_rulesets.py tests/test_rule_hit_count_generator.py`
Expected: 全 PASS（既有呼叫端測試不受影響——預設路徑逐位元不變）

- [ ] **Step 4: Commit** — `fix(report): surface ruleset fetch failures to rule hit count enrich_failed signal`

---

### Task 2: 原生 CSV 3 欄納入（spec §B）

**Files:**
- Modify: `src/report/rule_hit_count_generator.py`（`_CSV_ALIASES` :43-56、`generate_from_csv` 的 row 組裝 :125-148）
- Modify: `src/report/exporters/rule_hit_count_html_exporter.py`（`_COLS` :27-28、`_COL_I18N` :30-42）
- Modify: `src/i18n_en.json`＋`src/i18n/data/zh_explicit.json`＋重生 `src/i18n_zh_TW.json`（新鍵 `rpt_rhc_col_last_hit_at`）
- Test: `tests/test_rule_hit_count_generator.py`（fixture 擴充＋新測試類）
- Test: `tests/test_rule_hit_count_html_exporter.py`（`_row` 擴充＋新測試）

**Interfaces:**
- Produces: row dict 新增三鍵（皆 str，NaN/缺欄 → `''`）：`last_hit_at`（HTML＋CSV）、`last_updated_by`、`last_updated_at`（CSV pass-through only，比照 `rule_href`/`rule_id` 先例：CSV 有、HTML `_COLS` 白名單濾掉）。
- Consumes: `CsvExporter` 現有全欄 dump 行為（`src/report/exporters/csv_exporter.py`，不動）；`_TRUNC_COLS` 截斷政策不動（時戳固定約 20-24 字 << `_CELL_MAX=160`，跟 `days_since_last_hit` 同慣例整值呈現——CLAUDE.md 截斷規則已核對，無無聲截斷路徑）。

- [ ] **Step 1: 更新 fixture 為完整原生 header（v1 報告項 3 實測欄序）**——`tests/test_rule_hit_count_generator.py` 的 `_write_native_csv` 改為：

```python
def _write_native_csv(dirpath: str) -> str:
    """Write a CSV shaped like the PCE-native Rule Hit Count export
    (full 11-column header, real-PCE verified 2026-07-11)."""
    path = os.path.join(dirpath, "rule-hit-count.csv")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(
            "Rule Name,Rule HREF,Ruleset Name,Ruleset HREF,Rule Hit Count,"
            "Days Since Last Hit,Timestamp of Last Hit,Last Updated By,"
            "Timestamp Last Updated,Start Date,End Date\n"
            "allow web,/orgs/1/sec_policy/active/rule_sets/10/sec_rules/100,"
            "RS-A,/orgs/1/sec_policy/active/rule_sets/10,42,3,"
            "2026-06-28T09:14:23Z,admin@lab.local,2026-05-01T00:00:00Z,"
            "2026-06-01,2026-07-01\n"
            "stale allow,/orgs/1/sec_policy/active/rule_sets/10/sec_rules/101,"
            "RS-A,/orgs/1/sec_policy/active/rule_sets/10,5,120,"
            "2026-03-03T00:00:00Z,admin@lab.local,2026-05-01T00:00:00Z,"
            "2026-06-01,2026-07-01\n"
            "deny legacy,/orgs/1/sec_policy/active/rule_sets/11/deny_rules/200,"
            "RS-Legacy,/orgs/1/sec_policy/active/rule_sets/11,0,,,,,"
            "2026-06-01,2026-07-01\n"
        )
    return path
```

（既有測試斷言 KPI/date_range/rule_id，欄位增加不影響；跑一次確認既有測試仍綠再繼續。）

- [ ] **Step 2: 寫失敗測試（RED）**——`tests/test_rule_hit_count_generator.py` 加：

```python
class TestNativeExtraColumns(unittest.TestCase):
    def test_extra_native_columns_parsed(self):
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td), lang="en")
        row = result.dataframe[result.dataframe["rule_id"] == "100"].iloc[0]
        self.assertEqual(row["last_hit_at"], "2026-06-28T09:14:23Z")
        self.assertEqual(row["last_updated_by"], "admin@lab.local")
        self.assertEqual(row["last_updated_at"], "2026-05-01T00:00:00Z")
        # 未命中列：Timestamp of Last Hit 為空 → ''（不得為 'nan'）
        row0 = result.dataframe[result.dataframe["rule_id"] == "200"].iloc[0]
        self.assertEqual(row0["last_hit_at"], "")

    def test_missing_extra_columns_default_empty(self):
        # 舊版/精簡 CSV（無這 3 欄）不得失敗
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "minimal.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("Rule HREF,Rule Hit Count\n/r/1,3\n")
            result = gen.generate_from_csv(path)
        row = result.dataframe.iloc[0]
        self.assertEqual(row["last_hit_at"], "")
        self.assertEqual(row["last_updated_by"], "")
        self.assertEqual(row["last_updated_at"], "")

    def test_csv_export_carries_extra_columns(self):
        import zipfile
        gen = RuleHitCountGenerator(MagicMock(), api_client=None)
        with tempfile.TemporaryDirectory() as td:
            result = gen.generate_from_csv(_write_native_csv(td))
            paths = gen.export(result, fmt="csv", output_dir=td)
            with zipfile.ZipFile([p for p in paths if p.endswith(".zip")][0]) as zf:
                name = next(n for n in zf.namelist() if n.endswith("all_rules.csv"))
                content = zf.read(name).decode("utf-8")
        self.assertIn("last_hit_at", content)
        self.assertIn("last_updated_by", content)
        self.assertIn("admin@lab.local", content)
```

`tests/test_rule_hit_count_html_exporter.py`：`_row` 的 base dict 加 `"last_hit_at": "2026-06-28T09:14:23Z", "last_updated_by": "admin@lab.local", "last_updated_at": "2026-05-01T00:00:00Z"`，並加：

```python
    def test_last_hit_at_rendered_in_full_and_governance_columns_hidden(self):
        # last_hit_at：固定長度時戳，比照 days_since_last_hit 整值呈現（不進
        # _TRUNC_COLS 截斷路徑；CLAUDE.md：截斷必須明確，此欄無截斷需要）。
        # last_updated_by/last_updated_at：CSV pass-through only，HTML 不顯示。
        with tempfile.TemporaryDirectory() as td:
            path = RuleHitCountHtmlExporter(_result([_row()]), lang="en").export(td)
            html = open(path, encoding="utf-8").read()
        self.assertIn("Timestamp of Last Hit", html)            # 表頭 i18n
        self.assertIn(">2026-06-28T09:14:23Z</td>", html)        # 整值、無截斷
        self.assertNotIn("admin@lab.local", html)                # 治理欄不進 HTML
```

Run: `python3 -m pytest tests/test_rule_hit_count_generator.py tests/test_rule_hit_count_html_exporter.py -q` → 新測試 FAIL。

- [ ] **Step 3: 實作**——

`src/report/rule_hit_count_generator.py` `_CSV_ALIASES` 加三行：

```python
    'timestamp_of_last_hit': 'last_hit_at',
    # last_updated_by / last_updated_at：治理欄位，僅 CSV 匯出 pass-through
    # （CsvExporter dump 全欄；rule_href/rule_id 同先例）。HTML 刻意不顯示——
    # 值班判讀價值低，exporter _COLS 白名單濾掉（spec §B, 2026-07-11）。
    'last_updated_by': 'last_updated_by',
    'timestamp_last_updated': 'last_updated_at',
```

`generate_from_csv` 的 row 迴圈內（`days = row.get(...)` 之後）：

```python
            def _s(col: str) -> str:
                v = row.get(col, '')
                return '' if pd.isna(v) else str(v)
```

row dict 的 `'days_since_last_hit': ...` 之後加：

```python
                'last_hit_at': _s('last_hit_at'),
                'last_updated_by': _s('last_updated_by'),
                'last_updated_at': _s('last_updated_at'),
```

`src/report/exporters/rule_hit_count_html_exporter.py`：

```python
_COLS = ["ruleset", "rule_no", "rule_type", "description", "consumers",
         "providers", "services", "enabled", "hit_count", "days_since_last_hit",
         "last_hit_at"]
```

`_COL_I18N` 加 `"last_hit_at": "rpt_rhc_col_last_hit_at",`（`days_since_last_hit` 行之後）。

- [ ] **Step 4: i18n 三檔**——`src/i18n_en.json` 在 `rpt_rhc_col_days_since` 附近（字母序）加：

```json
  "rpt_rhc_col_last_hit_at": "Timestamp of Last Hit",
```

`src/i18n/data/zh_explicit.json` 對應位置加：

```json
  "rpt_rhc_col_last_hit_at": "最後命中時間",
```

Run: `python3 -m scripts.precompute_zh_translations --write`（重生 `src/i18n_zh_TW.json`；glossary 檢查由腳本執行）。

- [ ] **Step 5: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_rule_hit_count_generator.py tests/test_rule_hit_count_html_exporter.py tests/ -q -k "i18n or rule_hit" && ruff check src/report/rule_hit_count_generator.py src/report/exporters/rule_hit_count_html_exporter.py tests/test_rule_hit_count_generator.py tests/test_rule_hit_count_html_exporter.py`
Expected: 全 PASS（含 i18n parity/glossary 測試）

- [ ] **Step 6: Commit** — `feat(report): parse native last-hit timestamp and governance columns in rule hit count`

---

### Task 3: GUI CSV 上傳 mimetype 白名單（spec §C）

**Files:**
- Modify: `src/gui/routes/reports.py`（traffic :351-355 抽常數；policy_usage :727-734 與 RHC :844-851 的 csv 分支加檢查）
- Test: `tests/test_gui_report_csv_upload_whitelist.py`（新檔，login/CSRF 樣式照 `tests/test_gui_rule_hit_count_generate.py`）

**Interfaces:**
- Consumes: traffic 路由既有前例（mimetype 集合＋`gui_err_invalid_file_type`＋415）；`gui_err_invalid_file_type` i18n 鍵已存在雙語，**無新鍵**。
- Produces: 模組層常數 `_ALLOWED_CSV_UPLOAD_MIMETYPES = {'text/csv', 'application/vnd.ms-excel', 'text/plain', 'application/octet-stream'}`；三路由共用；traffic 行為逐位元不變。副檔名檢查不做（spec §C 評估：與 traffic 前例一致優先）。

- [ ] **Step 1: 寫失敗測試（RED）**——新檔 `tests/test_gui_report_csv_upload_whitelist.py`：

```python
"""CSV upload mimetype whitelist on rule_hit_count / policy_usage routes（spec §C）。
traffic 路由已有前例；此檔釘兩條新路由的拒絕（415）與放行路徑。"""
from io import BytesIO
from unittest.mock import MagicMock, patch

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def _post_csv(client, csrf_token, endpoint, filename, mimetype):
    return client.post(
        endpoint,
        data={"source": "csv", "lang": "en",
              "file": (BytesIO(b"Rule HREF,Rule Hit Count\n/r/1,3\n"),
                       filename, mimetype)},
        headers={"X-CSRF-Token": csrf_token},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        content_type="multipart/form-data",
    )


def test_rhc_upload_rejects_bad_mimetype(client):
    csrf_token = _login(client)
    r = _post_csv(client, csrf_token, "/api/rule_hit_count_report/generate",
                  "evil.pdf", "application/pdf")
    assert r.status_code == 415
    assert r.get_json()["ok"] is False
    assert r.get_json()["error"]


def test_policy_usage_upload_rejects_bad_mimetype(client):
    csrf_token = _login(client)
    r = _post_csv(client, csrf_token, "/api/policy_usage_report/generate",
                  "evil.pdf", "application/pdf")
    assert r.status_code == 415
    assert r.get_json()["ok"] is False


def test_rhc_upload_accepts_text_csv(client):
    # 放行釘：text/csv 通過白名單、進到 generator（mock 掉實際產出）
    csrf_token = _login(client)
    fake = MagicMock()
    fake.record_count = 1
    fake.module_results = {"kpis": {"total_rules": 1}}
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_csv.return_value = fake
        MockGen.return_value.export.return_value = ["/tmp/x/r.html"]
        r = _post_csv(client, csrf_token, "/api/rule_hit_count_report/generate",
                      "rhc.csv", "text/csv")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
```

Run: `python3 -m pytest tests/test_gui_report_csv_upload_whitelist.py -q` → 兩個 reject 測試 FAIL（現況 200 一路進 generator）。

- [ ] **Step 2: 實作**——`src/gui/routes/reports.py`：

模組層（`_ALLOWED_REPORT_FORMATS` 附近）：

```python
# CSV upload mimetype whitelist — single source for the traffic, policy_usage
# and rule_hit_count upload routes (traffic route established the set).
_ALLOWED_CSV_UPLOAD_MIMETYPES = {
    'text/csv', 'application/vnd.ms-excel',
    'text/plain', 'application/octet-stream',
}
```

traffic 路由 :351-355 的 inline 集合改引用 `_ALLOWED_CSV_UPLOAD_MIMETYPES`（其餘不動）。policy_usage 與 RHC 兩處 csv 分支，於 `csv_file = request.files['file']`（或取得 csv_file）之後、`secure_filename` 之前插入：

```python
                if csv_file.mimetype not in _ALLOWED_CSV_UPLOAD_MIMETYPES:
                    return jsonify({"ok": False,
                                    "error": t("gui_err_invalid_file_type", lang=lang)}), 415
```

（policy_usage 分支現況先檢查 `'file' not in request.files or ...filename == ''` 再取 `csv_file`，插在取得 `csv_file` 之後即可；RHC 分支同。）

- [ ] **Step 3: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_gui_report_csv_upload_whitelist.py tests/test_gui_rule_hit_count_generate.py tests/test_gui_app_report_generate.py tests/test_gui_routes_robustness.py -q && ruff check src/gui/routes/reports.py tests/test_gui_report_csv_upload_whitelist.py`
Expected: 全 PASS（traffic 路由行為不變）

- [ ] **Step 4: Commit** — `fix(gui): whitelist csv upload mimetypes on rule hit count and policy usage routes`

---

### Task 4: submit 回應缺 href 防禦（spec §D）

**Files:**
- Modify: `src/api/reports.py`（`pull_rule_hit_count_report`，:78 一帶）
- Test: `tests/test_api_reports_pull.py`（同檔擴充）

**Interfaces:**
- Produces: 2xx 但 body 無 `href` → 立即 `RuntimeError`（訊息含 `no href` 與 body 摘要，截 200 字），不進輪詢。CLI/GUI 既有泛型 `except Exception` 路徑承接，呼叫端零改動。

- [ ] **Step 1: 寫失敗測試（RED）**——`tests/test_api_reports_pull.py` 加：

```python
    def test_submit_2xx_without_href_raises_immediately(self):
        """2xx 但 body 無 href：現況拿空字串輪詢直到 timeout（誤導性
        RuleHitCountPullTimeout('')）。必須立即 raise，訊息帶 body 摘要。"""
        c = _client()
        c._api_post.return_value = (201, {"status": "queued"})
        with self.assertRaises(RuntimeError) as ctx:
            ReportsApi(c).pull_rule_hit_count_report(last_num_days=7)
        self.assertIn("no href", str(ctx.exception))
        self.assertIn("queued", str(ctx.exception))
        c._api_get.assert_not_called()   # 不得進入輪詢
```

Run: `python3 -m pytest tests/test_api_reports_pull.py -q` → 新測試 FAIL（現況繞進輪詢）。

- [ ] **Step 2: 實作**——`href = body.get("href", "")` 之後、`logger.info` 之前加：

```python
        if not href:
            raise RuntimeError(
                f"rule hit count report submit returned no href: {str(body)[:200]}")
```

- [ ] **Step 3: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_api_reports_pull.py tests/ -q -k "reports_pull or rule_hit" && ruff check src/api/reports.py tests/test_api_reports_pull.py`
Expected: 全 PASS

- [ ] **Step 4: Commit** — `fix(api): fail fast when rule hit count submit response lacks href`

---

### Task 5: native 路徑整合 pin 測試（spec §E）

**Files:**
- Test: `tests/test_rule_hit_count_generator.py`（`TestGenerateFromNative` 擴充；純測試、零產品碼）

**Interfaces:**
- Consumes: `RuleHitCountNotEnabled.status`（`EnablementStatus`，state ∈ enabled/partial/disabled/unsupported）；`RuleHitCountPullTimeout.report_href`。
- 性質：pin 測試——依現場碼推定直接 GREEN（`generate_from_native` 對 `state != "enabled"` 一律 raise；pull 例外發生在 try/finally 之前，原樣上拋）。**若任一 RED：發現真 bug，停下回報，不得改測試湊綠。**

- [ ] **Step 1: 加測試**——`TestGenerateFromNative` 內：

```python
    def test_raises_for_partial_and_unsupported_states(self):
        """GUI route 靠 exc.status.state 轉述前端（needs_enablement 分支）——
        partial/unsupported 必須與 disabled 同路 raise，且 state 原樣攜帶、
        不觸發 pull。"""
        from unittest.mock import patch
        from src.report.rule_hit_count_enablement import (
            EnablementStatus, RuleHitCountNotEnabled)
        for state, detail in (("partial", "missing: PCE report template"),
                              ("unsupported", "report template not found")):
            with self.subTest(state=state):
                api = MagicMock()
                gen = RuleHitCountGenerator(MagicMock(), api_client=api)
                with patch("src.report.rule_hit_count_generator.check_enablement",
                           return_value=EnablementStatus(state, False, False, detail)):
                    with self.assertRaises(RuleHitCountNotEnabled) as ctx:
                        gen.generate_from_native()
                self.assertEqual(ctx.exception.status.state, state)
                api.pull_rule_hit_count_report.assert_not_called()

    def test_pull_runtime_error_propagates_unwrapped(self):
        """pull 的 RuntimeError（如 submit 406/no-href）必須原型別、原訊息上拋
        （GUI _err_with_log / CLI 泛型處理依賴），不得被吞或包裝。"""
        from unittest.mock import patch
        from src.report.rule_hit_count_enablement import EnablementStatus
        api = MagicMock()
        api.pull_rule_hit_count_report.side_effect = RuntimeError(
            "rule hit count report submit failed: HTTP 406")
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with patch("src.report.rule_hit_count_generator.check_enablement",
                   return_value=EnablementStatus("enabled", True, True, "")):
            with self.assertRaises(RuntimeError) as ctx:
                gen.generate_from_native()
        self.assertIn("406", str(ctx.exception))

    def test_pull_timeout_propagates_with_report_href(self):
        """RuleHitCountPullTimeout 必須原型別上拋且 report_href 保留——route 層
        的型別分流（TimeoutError 是 OSError 子類，須先於泛型 except 捕捉）與
        後續重試/CSV 路徑都依賴它。"""
        from unittest.mock import patch
        from src.api.reports import RuleHitCountPullTimeout
        from src.report.rule_hit_count_enablement import EnablementStatus
        api = MagicMock()
        api.pull_rule_hit_count_report.side_effect = RuleHitCountPullTimeout(
            "/orgs/1/reports/xyz")
        gen = RuleHitCountGenerator(MagicMock(), api_client=api)
        with patch("src.report.rule_hit_count_generator.check_enablement",
                   return_value=EnablementStatus("enabled", True, True, "")):
            with self.assertRaises(RuleHitCountPullTimeout) as ctx:
                gen.generate_from_native()
        self.assertEqual(ctx.exception.report_href, "/orgs/1/reports/xyz")
```

- [ ] **Step 2: GREEN（pin）＋全套迴歸**

Run: `python3 -m pytest tests/test_rule_hit_count_generator.py -q && python3 -m pytest -q && ruff check tests/test_rule_hit_count_generator.py`
Expected: 新測試直接 PASS（pin）；全套 pytest 全綠。任一新測試 FAIL → 停下回報（真 bug，另議修法）。

- [ ] **Step 3: Commit** — `test(report): pin native enablement states and pull failure propagation`

---

## 收尾

全部 task 完成後：whole-branch review → 合入 main → push → 部署測試機。真環境抽驗（可選）：以 v1 驗證同手法（deepcopy `api.api_cfg` 改 `org_id=99999`）重跑一次 `generate_from_csv`，確認 HTML 出現 `rpt_rhc_note_enrich_failed` 注記（Task 1 的端到端閉環）；GUI 上傳一個 .pdf 確認 415 toast。

## Self-Review 紀錄

- Spec 覆蓋：§A=Task 1、§B=Task 2、§C=Task 3、§D=Task 4、§E=Task 5；§3 非目標未混入（406 日期 bug 已在 main、policy_usage 空回傳語意、副檔名檢查、Protocol 擴充皆未動）。
- 佔位掃描：所有測試/實作碼皆完整可貼（fixture 內容、常數集合、i18n 鍵值、commit message 具體），無 TBD/placeholder。
- 型別一致：`raise_on_error: bool = False`（api_client 定義＝generator 呼叫＝測試斷言）；row 三新鍵皆 str、NaN → `''`（generator＝exporter `_row` fixture＝CSV 斷言）；canonical 名 `last_hit_at`/`last_updated_by`/`last_updated_at` 貫穿 aliases、row、`_COLS`、`_COL_I18N`、i18n 鍵 `rpt_rhc_col_last_hit_at`、測試；415＋`gui_err_invalid_file_type` 與 traffic 前例一致。
- 順序：Task 1→2 共檔 `rule_hit_count_generator.py`＋同測試檔，Task 5 依賴 Task 2 後的 fixture（`_write_native_csv` 11 欄版），串行正確；Task 3/4 獨立但同分支串行。
- i18n：僅 Task 2 有新鍵，三檔流程＋glossary（「最後命中時間」無保留詞）已載明；Task 3 復用既有鍵。
