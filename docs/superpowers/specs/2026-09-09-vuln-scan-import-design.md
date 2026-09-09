# 弱點掃描匯入與 PCE vmaps 上傳 設計（子專案 3／4，借鑒 illumio-plugger vmaps-handler）

日期：2026-09-09　狀態：草案待使用者審閱　分支：feat/ven-fleet-manager（與其他子專案共用 worktree，執行時各自開分支）

## 0. 背景與範圍

現況：`src/report/parsers/vuln_csv.py` 只吃通用 CSV（欄位別名），只有 CLI `--vuln-csv` 路徑，只餵
Security & Risk 報表的 V-E lite 段落；無 GUI 上傳、無 PCE 上傳、無 `optional_features` 讀取。

plugger vmaps-handler 是 illumio-cli 3.0.537 弱點匯入器的 Python 還原：Nessus XML／Qualys XML／
Tenable.sc、.io CSV parser ＋ `POST /orgs/{org}/vulnerabilities`（1000 一批）＋
`PUT /orgs/{org}/vulnerability_reports/{ref}`。它**完全沒處理 license**；本專案兩環境實測該路徑 403
（`optional_features.vulnerability_analytics=false`，見記憶 pce-vulnerability-api-403-license）。

使用者決定：
- 只做**檔案匯入**（Nessus `.nessus`、Qualys XML、Tenable.sc／.io CSV），不做掃描器 API 拉取。
- parser ＋ 上傳鏈都做；上傳鏈加 `optional_features` 預檢；無 license 時上傳段只能 mock 驗證。

不在範圍：掃描器憑證、排程自動匯入、Qualys asset-data XML 的 QID 對齊旗標（plugger 的 `ILO_QUALYS_QID_PREFIX`）。

## 1. 架構

```
scan file ──> src/report/parsers/vuln_scans/  ──> ScanResult ──┬─> to_vuln_df() ──> mod_vuln（既有報表段落）
  .nessus / qualys .xml / tenable .csv / 通用 .csv             │
                                                               └─> src/vmaps/uploader.py
                                                                     ├─ precheck(api)  GET optional_features
                                                                     ├─ POST vulnerabilities  1000/批
                                                                     └─ PUT vulnerability_reports/{ref}
CLI  report security --vuln-file <path>      （--vuln-csv 保留為別名）
CLI  vuln upload <path> [--report-name] [--authoritative] [--dry-run]
GUI  報表產生（Security & Risk）第二個檔案欄「弱點掃描檔」＋「同時上傳到 PCE vmaps」勾選
```

## 2. Parser 層 `src/report/parsers/vuln_scans/`

```python
@dataclass
class Detection: ip: str; port: int | None; proto: int | None; vuln_id: str; state: str  # "active"|"fixed"
@dataclass
class ScanResult:
    scanner: str                      # "nessus"|"qualys"|"tenable_sc"|"tenable_io"|"csv"
    vulns: dict[str, dict]            # vuln_id -> {"name": str, "score": int(0-100), "cve_ids": list[str]}
    detections: list[Detection]
    scanned_ips: set[str]
    warnings: list[str]               # 丟棄列的原因統計，不靜默
    def to_vuln_df(self) -> pd.DataFrame   # 欄：ip, cve_id, severity, cvss, vuln_id, name, port, proto, state
def sniff(path: str) -> str            # 依 root element / CSV 表頭 / 副檔名判 scanner，判不出 raise ValueError
def load_scan(path: str, scanner: str | None = None) -> ScanResult
```

- 對 mod_vuln 的相容：`to_vuln_df()` 一個 CVE 一列（無 CVE 的偵測用 `vuln_id` 當 `cve_id`，`severity` 由 score 反推
  critical≥89／high≥69／medium≥39／low>0／info=0，`cvss` 為 score/10）。`vuln_csv.load_vulns` 改為
  `load_scan(path, "csv").to_vuln_df()` 的薄包裝，既有測試不動。
- 分數：沿用 plugger／illumio-cli 的 `SEVERITY_TO_SCORE_MAP`（1–5／info–critical → 0/39/69/89/100），
  CVSS 存在時 `int(cvss*10)` 優先（v3 > v2）。
- 對 plugger 缺陷的決定：
  | plugger | 本案 |
  |---|---|
  | Nessus severity 0–4 套 1–5 表（錯位） | Nessus 用自己的表 0→0、1→39、2→69、3→89、4→100 |
  | Tenable 的 `vuln_id` 也叫 `nessus-<plugin>` | `tenable-<plugin>`；Nessus `nessus-<pluginID>`；Qualys `qualys-<QID>` |
  | `cve.split(",")` 不 strip | strip 並丟空字串，去重 |
  | 不支援的 proto 仍加入（無 proto） | 同 plugger（PCE schema proto 可選），但計入 `warnings` |
  | IPv6 直接排除 | IPv4／IPv6 都正規化（`ipaddress`）並保留 |
  | 去重鍵 `port-proto-ip-vuln`、active 蓋 fixed | 沿用 |
- 每個 parser 只讀原始格式、產 `ScanResult`，不碰 PCE、不碰 pandas（`to_vuln_df` 在 ScanResult）。
- 檔案大小上限 50 MB（GUI 與 CLI 同），XML 用 `defusedxml`（已在依賴？否則 stdlib `xml.etree` 加 `forbid_dtd`）。

## 3. 上傳鏈 `src/vmaps/uploader.py`

```python
@dataclass
class Precheck: ok: bool; reason: str   # reason ∈ "ok" | "feature_disabled" | "http_<code>" | "transport"
def precheck(api) -> Precheck           # GET /orgs/{org}/optional_features，找 name=="vulnerability_analytics" 且 enabled
def upload(api, scan: ScanResult, *, report_name: str, authoritative: bool, dry_run: bool = False,
           batch_size: int = 1000, detection_batch: int = 10_000) -> UploadResult
```

- 流程：precheck 不過→**fail closed**，回 `UploadResult(ok=False, reason="feature_disabled")` 並附人話
  「PCE 未啟用 Vulnerability Maps（需安裝 vulnerability_maps 授權）」，不打任何寫入端點。
- 之後：`api.fetch_managed_workloads()` 建 IP→href（interfaces[].address 與 public_ip，IPv4／IPv6 正規化）；
  無 href 的偵測丟棄並計數；`POST /orgs/{org}/vulnerabilities` body 為純陣列
  `[{"reference_id","score","name","cve_ids"}]` 1000 一批（直接走 `api._request(..., method="POST",
  rate_limit=True)`，因 `_api_post` 只收 dict）；`PUT /orgs/{org}/vulnerability_reports/{report_name}`
  body `{"name","report_type","authoritative","scanned_ips","detected_vulnerabilities"}`，
  detected 每批 `detection_batch`；authoritative 語意照 illumio-cli 正典：只有 authoritative 才帶
  `scanned_ips`，最後補 PUT `detected_vulnerabilities: []` 沖無發現的 IP。
- 偵測項：`{"ip_address","port"?,"proto"?,"vulnerability":{"href":"/orgs/{org}/vulnerabilities/{id}"},
  "state"?,"workload":{"href"}}`。
- `UploadResult{ok, reason, vulns_posted, detections_matched, detections_dropped, batches:[{kind,http,count}], report_http}`；
  任何批次非 2xx→停止後續批次、`ok=False`、附 body 前 500 字。
- `dry_run=True`：做 precheck 與 IP 對應，回統計，不 POST/PUT。
- 事件對帳：上傳後 `events/catalog.py` 已有 `vulnerability.create`／`vulnerability_report.update`，
  GUI 事件頁可看到；不另做。

## 4. CLI

- `report security --vuln-file <path>`：取代 `--vuln-csv`（保留舊名為隱藏別名）；`sniff` 判型別，
  `--vuln-scanner` 可強制。
- 新群組 `vuln`：`vuln parse <path>`（印統計與 warnings）、`vuln upload <path> --report-name NAME
  [--authoritative] [--dry-run]`；precheck 失敗以非零碼結束並印原因；輸出用 `t()`。

## 5. GUI

- 報表產生頁（`#/reports`，Security & Risk）：第二個檔案欄 `vuln_file`（接受 .csv/.xml/.nessus，
  mimetype 白名單另立 `_ALLOWED_SCAN_UPLOAD_MIMETYPES` 含 `text/xml`、`application/xml`）；
  `toFormData` 支援第二個檔案；後端 `payload["vuln_temp_path"]`，worker `generate_from_*` 傳
  `vuln_csv_path=`（參數名不改，值可為任何支援格式）並 finally 刪檔。
- 勾選「同時上傳到 PCE vmaps」：顯示 report_name 與 authoritative；產報表 job 完成後執行 `upload`，
  結果進 job 狀態 `vmaps: UploadResult`；precheck 失敗在 job 結果以 tone=warn 顯示原因並連到說明。
- `#/system/pce` 頁顯示「Vulnerability Maps：已啟用／未啟用」一行（讀 precheck，快取 5 分鐘）。
- coverage.yaml：RP-* 新兩項（檔案欄、上傳勾選）、SY-* 一項。

## 6. 錯誤處理

- 檔案判型失敗→400／CLI 非零，列出可接受格式。
- parser 丟列不靜默：`warnings` 進 CLI 輸出與 GUI job 結果。
- 上傳部分失敗：回 batches 清單；GUI 顯示到第幾批失敗；不自動重試（POST 不重試是 api_client 既定原則）。

## 7. 測試

- fixture：`tests/fixtures/vuln_scans/{sample.nessus, qualys_scan.xml, tenable_sc.csv, tenable_io.csv}`
  （自 plugger sample-data 精簡改寫，去除真實主機名）。
- parser 單元：各格式欄位對應、Nessus severity 表、Tenable 去重、CVE strip、IPv6 保留、sniff。
- `to_vuln_df` 餵 `mod_vuln.vuln_exposure` 結果與舊 CSV 路徑等價（同一組偵測兩種輸入）。
- uploader：fake api 驗 precheck fail-closed 不呼叫寫入；1000 分批；authoritative 尾批；非 2xx 停止；dry_run。
- GUI：第二檔案上傳走 job；mimetype 拒絕 .exe。
- 真機：lab 只能驗 precheck=feature_disabled 與 parser；上傳段標「待授權環境」。

## 8. 已知限制

- 無 license 的環境永遠停在 precheck；這是設計，不是 bug。
- Qualys asset-data XML 定義／偵測鍵不一致問題不處理，只支援 scan-data XML。
