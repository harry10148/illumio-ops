# Vulnerability Scan Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nessus／Qualys XML／Tenable CSV 檔案匯入餵既有弱點報表段落，並提供 PCE vmaps 上傳鏈（含 `optional_features` 預檢、fail closed）。

**Architecture:** `src/report/parsers/vuln_scans/` 各格式 parser 產 `ScanResult`；`to_vuln_df()` 餵 `mod_vuln`；`src/vmaps/uploader.py` 做 precheck→POST 1000 批→PUT report；CLI `report security --vuln-file`＋`vuln parse|upload`；GUI 報表產生第二檔案欄＋上傳勾選。

**Tech Stack:** Python stdlib `xml.etree`／`csv`／pandas；Flask multipart；click。

**Spec:** `docs/superpowers/specs/2026-09-09-vuln-scan-import-design.md`

## Global Constraints

- 分支 `feat/vuln-scan-import` 自 main（fleet 合併後）。
- XML 解析前掃描前 64 KB，含 `<!DOCTYPE` 或 `<!ENTITY` 即 `ValueError("dtd_not_allowed")`；不新增 `defusedxml` 依賴。
- 檔案上限 50 MB；vuln id 前綴 `nessus-`／`qualys-`／`tenable-`；severity↔score 五級來回恆等（0/39/69/89/100 ↔ info/low/medium/high/critical，反推門檻 ≥90/≥70/≥40/≥1/0）。
- 上傳前 precheck 不過**不得**呼叫任何寫入端點；`feature_unknown` 亦 fail closed。
- fixture 目錄 `tests/fixtures/vuln_scans/` 放 `NOTICE`（Apache-2.0，alexgoller/illumio-plugger）。
- 提交只 `git add <路徑>`；全套閘門同其他子專案。

---

### Task 1: Parser 層與 `ScanResult`

**Files:**
- Create: `src/report/parsers/vuln_scans/__init__.py`（`ScanResult`、`Detection`、`sniff`、`load_scan`、`SEVERITY_TO_SCORE`、`score_to_severity`、`_guard_xml`）、`nessus.py`、`qualys.py`、`tenable.py`、`generic_csv.py`
- Modify: `src/report/parsers/vuln_csv.py:28`（`load_vulns` 改為 `load_scan(path, "csv").to_vuln_df()[["ip","cve_id","severity","cvss"]]`，既有測試不動）
- Create: `tests/fixtures/vuln_scans/{sample.nessus, qualys_scan.xml, tenable_sc.csv, tenable_io.csv, NOTICE}`
- Test: `tests/test_vuln_scan_parsers.py`（既有 `tests/test_vuln_csv_parser.py` 必須仍綠）

**Interfaces（Produces）:**
```python
@dataclass class Detection: ip: str; port: int|None; proto: int|None; vuln_id: str; state: str
@dataclass class ScanResult:
    scanner: str; vulns: dict[str, dict]; detections: list[Detection]; scanned_ips: set[str]; warnings: list[str]
    def to_vuln_df(self) -> pd.DataFrame   # ip, cve_id, severity, cvss, vuln_id, name, port, proto, state
def sniff(path) -> str                     # "nessus"|"qualys"|"tenable_sc"|"tenable_io"|"csv"；否則 ValueError("unknown_format")
def load_scan(path, scanner: str|None=None) -> ScanResult
SEVERITY_TO_SCORE = {"info":0,"low":39,"medium":69,"high":89,"critical":100}
def score_to_severity(score:int) -> str
```
- 欄位對應照 `tmp/research/plugger-port/01-plugger-behavior-spec.md` §4（Nessus：`ReportHost/HostProperties/tag[@name="host-ip"]`、`ReportItem@severity/pluginID/pluginName/port/protocol`、`cvss3_base_score`→`cvss_base_score`→severity 表（Nessus 專用 0→0,1→39,2→69,3→89,4→100）；Qualys scan XML：`IP@value`、`CAT@port/@protocol`、`VULN@number/@severity`、`TITLE`、`CVE_ID_LIST//CVE_ID/ID`；Tenable.sc：`Plugin, Plugin Name, IP Address, Port, Protocol, Severity, CVSS V2 Base Score, CVSS V3 Base Score, CVE[, Mitigated On]`；Tenable.io：`Plugin ID, Name, IP Address, Port, Protocol, Risk, CVSS Base Score, CVSS3 Base Score, CVE, Vulnerability State`）。
- 去重鍵 `f"{port}-{proto}-{ip}-{vuln_id}"`，active 蓋 fixed；CVE 逗號分割後 strip、去空、去重；IPv4／IPv6 以 `ipaddress` 正規化；proto 未知→計 warnings 但保留偵測（proto None）。

**Acceptance / Tests（TDD）:**
- 四格式 fixture 各驗：vulns 數、detections 數、一筆完整欄位、`scanned_ips`。
- Nessus severity 表；Tenable `Mitigated On` 非空→fixed；Tenable.io `resurfaced`→active；CVE strip；DTD 拒絕；`sniff` 四格式＋未知 raise；IPv6 保留。
- 五級 severity 來回恆等。
- `to_vuln_df` 餵 `mod_vuln.vuln_exposure` 與等價 CSV 輸入結果相同（`exposed_count` 與 `exposed` 表相等）。

Run: `timeout 600 python3 -m pytest tests/test_vuln_scan_parsers.py tests/test_vuln_csv_parser.py tests/test_mod_vuln.py -q`

Commit: `feat(vuln): Nessus, Qualys and Tenable scan parsers behind one ScanResult`

---

### Task 2: 上傳鏈 `src/vmaps/uploader.py`

**Files:**
- Create: `src/vmaps/__init__.py`、`src/vmaps/uploader.py`
- Modify: `src/api_client.py`（新增 `get_optional_features() -> tuple[int, list]`（用 `_api_get_with_headers :969`）、`post_vulnerabilities(batch: list) -> tuple[int, str]`、`put_vulnerability_report(ref, body) -> tuple[int, str]`，皆直接 `self._request(..., rate_limit=True)`，POST 帶 `Prefer: respond-async` 不帶）
- Test: `tests/test_vmaps_uploader.py`

**Interfaces:**
```python
@dataclass class Precheck: ok: bool; reason: str          # ok|feature_disabled|feature_unknown|http_<code>|transport
def precheck(api) -> Precheck
@dataclass class UploadResult: ok: bool; reason: str; vulns_posted: int; detections_matched: int; detections_dropped: int
                              batches: list[dict]; report_http: int|None; message: str
def build_ip_map(workloads) -> dict[str, str]              # interfaces[].address 與 public_ip → href，IPv4/IPv6 正規化
def upload(api, scan: ScanResult, *, report_name: str, authoritative: bool, dry_run=False,
           batch_size=1000, detection_batch=10_000) -> UploadResult
```
- 偵測項與 report body 形狀照 spec §3；authoritative 尾批 `detected_vulnerabilities: []` 沖 `scanned_ips` 中無發現者；非 2xx 停止並 `ok=False`。
- `message` 用 `t()`（`vmaps_precheck_disabled` 等鍵），CLI／GUI 直接顯示。

**Acceptance / Tests（TDD，fake api 記錄呼叫序列）:**
- precheck 四種 reason；disabled／unknown 時 `upload` 零寫入呼叫。
- 2500 個 vuln → 3 批；10 001 偵測 → 2 批 report PUT；authoritative 尾批存在且非 authoritative 時 `scanned_ips=[]`。
- 第二批 POST 回 500 → 停止、`batches` 記錄、`ok=False`。
- `dry_run` 回統計、零寫入。
- 無 href 的偵測計入 `detections_dropped`。

Run: `timeout 600 python3 -m pytest tests/test_vmaps_uploader.py -q`

Commit: `feat(vmaps): license-gated upload of scan results to PCE vulnerability maps`

---

### Task 3: CLI

**Files:**
- Modify: `src/cli/report.py:505-528`（`--vuln-file`；`--vuln-csv` 留為 hidden alias 指同一參數；`--vuln-scanner` 選項）
- Create: `src/cli/vuln.py`（`vuln` group：`parse`、`upload`）；Modify: `src/cli/root.py:86-91`（`cli.add_command(vuln_group)`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`cli_vuln_*`）
- Test: `tests/test_cli_vuln.py`

**Interfaces:** `vuln parse <path> [--scanner]` 印 vulns／detections／scanned_ips／warnings 各數；`vuln upload <path> --report-name NAME [--authoritative] [--dry-run] [--scanner]`：precheck 失敗 exit 2 並印 `message`；上傳失敗 exit 1；成功印統計。`report security --vuln-file` 任何支援格式皆可（`generate_*` 的 `vuln_csv_path` 參數名不改）。

**Acceptance / Tests（`cli_runner` fixture，fake api）:** parse 對四 fixture；upload precheck disabled → exit 2 且無寫入；`--vuln-csv` 舊名仍可用；`report security --vuln-file sample.nessus` 產出含 `id="vuln"`。

Run: `timeout 600 python3 -m pytest tests/test_cli_vuln.py tests/test_mod_vuln.py -q`

Commit: `feat(cli): vuln parse/upload, and report security accepts scan files`

---

### Task 4: GUI

**Files:**
- Modify: `src/gui/routes/reports.py:43-58`（新 `_ALLOWED_SCAN_UPLOAD_MIMETYPES` 含 `text/xml`、`application/xml`、`application/octet-stream`、`text/csv`、`text/plain`；`_scan_upload_rejected` 檢查副檔名 `.csv/.xml/.nessus`）、`:472-485`（`request.files.get('vuln_file')`→`payload["vuln_temp_path"]`、`payload["vmaps"] = {enabled, report_name, authoritative}`）、`:366-373`（worker 傳 `vuln_csv_path=payload.get("vuln_temp_path")`，finally 刪；報表成功且 `vmaps.enabled` 時 `load_scan`＋`upload`，結果寫 job `result["vmaps"]`）
- Modify: `src/static/js/v2/areas/reports.mjs:633-658`（Security & Risk 表單加 `vuln_file` 檔案欄與「同時上傳到 PCE vmaps」勾選＋report_name／authoritative）、`:931-941`（`toFormData` 支援第二檔案鍵 `vuln_file`）、job 結果卡顯示 `vmaps` 結果（warn tone 顯示 precheck message）
- Modify: `src/static/js/v2/areas/system.mjs`（`#/system/pce` 卡片一行「Vulnerability Maps：enabled/disabled/unknown」，讀新 `GET /api/pce/optional_features`（快取 5 分鐘，加 store-map／endpoints.yaml，計數 +1））
- Modify: `design/v3/coverage.yaml`（RP-* 兩項、SY-* 一項）、i18n 三檔、`docs/guide/gui-tour.md`
- Test: `tests/test_gui_reports_vuln_upload.py`、`tests/test_v2_reports_vuln_e2e.py`

**Acceptance / Tests:** 第二檔上傳走 job 且 worker 收到 `vuln_temp_path`、結束後檔案刪除；`.exe` 415；`vmaps.enabled` 且 precheck disabled → job `result.vmaps.reason=="feature_disabled"` 且零寫入；e2e 表單送出 FormData 含兩檔；SY 卡文案。

Run: `timeout 900 python3 -m pytest tests/test_gui_reports_vuln_upload.py tests/test_v2_reports_vuln_e2e.py tests/test_v2_coverage_live.py -q`

Commit: `feat(gui): scan file upload with optional vmaps push`

---

### Task 5: 文件與全套閘門

`docs/reference/cli.md`（vuln 群組、`--vuln-file`）、`docs/reference/rest-api.md`、`docs/guide/reports.md`、`CHANGELOG.md`、spec 狀態；`tests/test_docs_check.py`；全套閘門；真機：lab 驗 precheck=feature_disabled、四 fixture 經 GUI 上傳產報表雙語看 vuln 段落。

Commit: `docs(vuln): scan import and vmaps upload`
