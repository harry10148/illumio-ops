# Illumio PCE Ops — API / 整合指南

本文件合併原 API Cookbook 與 SIEM/SOAR 整合內容，保留常用場景與端點速查。實際欄位會隨 PCE 版本與本工具 schema 演進；高風險自動化請先在 lab PCE 驗證。

## 快速設定

PCE 直接 API 使用 HTTP Basic auth：

```python
import requests

base = "https://pce.example.com:8443"
org_id = "1"
auth = ("api_key", "api_secret")

r = requests.get(
    f"{base}/api/v2/orgs/{org_id}/workloads",
    auth=auth,
    verify=True,
    timeout=30,
)
r.raise_for_status()
print(r.json())
```

工具內部 Web API 使用 session auth。先登入 `/api/login`，之後帶 cookie 與 CSRF token 呼叫修改型 endpoint。

## 場景一：健康檢查 — 驗證 PCE 連線

### PCE API

```python
def check_pce(base, org_id, auth):
    r = requests.get(
        f"{base}/api/v2/orgs/{org_id}",
        auth=auth,
        verify=True,
        timeout=15,
    )
    return r.status_code, r.text[:200]
```

### CLI

```bash
python illumio_ops.py status
```

### Web GUI

`POST /api/actions/test-connection`

## 場景二：工作負載搜尋與盤點

### PCE API

```python
def search_workloads(base, org_id, auth, hostname):
    r = requests.get(
        f"{base}/api/v2/orgs/{org_id}/workloads",
        params={"hostname": hostname},
        auth=auth,
        verify=True,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

### 工具 CLI

```bash
python illumio_ops.py workload list --limit 50
python illumio_ops.py workload list --env prod --managed-only
```

### 工具 Web API

`GET /api/workloads`

## 場景三：工作負載隔離（Quarantine）

建議流程：

1. 搜尋 workload。
2. 驗證 href 是否為 `/workloads/`。
3. 確認 Quarantine labels 已存在。
4. 對目標 workload 附加隔離 label。
5. 重新查詢 workload 確認 label 已更新。

### 工具 Web API

| Endpoint | 用途 |
|:---|:---|
| `POST /api/quarantine/search` | 搜尋 workload |
| `POST /api/quarantine/apply` | 單筆套用 quarantine |
| `POST /api/quarantine/bulk_apply` | 批次套用 quarantine |
| `POST /api/init_quarantine` | 初始化 quarantine labels |

## 場景四：流量分析查詢

Traffic report 主要透過工具封裝 PCE async traffic query。直接使用工具比手寫 PCE async job 安全，因為它會處理 native filters、fallback filters、draft policy decision、pagination/streaming、query diagnostics。

### CLI

```bash
python illumio_ops.py report traffic --format html --profile security_risk
python illumio_ops.py report traffic --source csv --file flows.csv --format all
```

### Python

```python
from src.config import ConfigManager
from src.api_client import ApiClient
from src.report.report_generator import ReportGenerator

cm = ConfigManager()
api = ApiClient(cm)
gen = ReportGenerator(cm, api_client=api, config_dir="config")

result = gen.generate_from_api(
    start_date="2026-04-01T00:00:00Z",
    end_date="2026-04-27T23:59:59Z",
    filters={"policy_decisions": ["blocked", "potentially_blocked", "allowed"]},
    traffic_report_profile="security_risk",
)
paths = gen.export(result, fmt="html", output_dir="reports")
print(paths)
```

### Traffic filter 分類

| 類型 | 範例 | 說明 |
|:---|:---|:---|
| Native filters | label groups、policy decisions、port/proto | 儘量下推到 PCE |
| Fallback filters | 無法由 PCE 原生查詢完整表達的條件 | API 回傳後本地過濾 |
| Report-only filters | profile、language | 只影響報表輸出 |

Raw Explorer CSV export 只支援 API-sourced traffic report，不能用在 CSV source。

## 場景五：安全事件監控

### PCE events

```python
def fetch_events(base, org_id, auth, start, end):
    r = requests.get(
        f"{base}/api/v2/orgs/{org_id}/events",
        params={"start_date": start, "end_date": end},
        auth=auth,
        verify=True,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

### 工具能力

- `src.events.normalizer` 將 vendor event 正規化。
- `src.events.matcher` 支援 nested field pattern。
- `Analyzer` 使用 watermark 避免重複告警。
- Web GUI `/api/events/viewer` 可查事件與 pagination。
- `/api/events/rule_test` 可比較目前 matcher 與 legacy 行為。

## 場景六：標籤管理

PCE labels 可用於 Quarantine、多 PCE profile、流量規則、report filter。新增或修改 label 前請確認 org id 與 label type。

常見 label type：

- `app`
- `env`
- `role`
- `loc`

範例：

```python
def list_env_labels(base, org_id, auth):
    r = requests.get(
        f"{base}/api/v2/orgs/{org_id}/labels",
        params={"key": "env"},
        auth=auth,
        verify=True,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

## 場景七：工具內部 API 認證與 CSRF

登入：

```python
import requests

s = requests.Session()
login = s.post(
    "http://127.0.0.1:5001/api/login",
    json={"username": "illumio", "password": "illumio"},
    timeout=10,
)
login.raise_for_status()
csrf = login.json()["csrf_token"]
```

修改型 request：

```python
r = s.post(
    "http://127.0.0.1:5001/api/actions/test-connection",
    headers={"X-CSRFToken": csrf},
    timeout=30,
)
print(r.json())
```

## 場景八：報表自動化

### Report generation endpoints

| Endpoint | 用途 |
|:---|:---|
| `POST /api/reports/generate` | Traffic Report |
| `POST /api/audit_report/generate` | Audit Report |
| `POST /api/ven_status_report/generate` | VEN Status Report |
| `POST /api/policy_usage_report/generate` | Policy Usage Report |
| `GET /api/reports` | 列出報表與 metadata |
| `DELETE /api/reports/<filename>` | 刪除報表 |
| `POST /api/reports/bulk-delete` | 批次刪除報表 |

Traffic report request 範例：

```json
{
  "source": "api",
  "format": "html",
  "traffic_report_profile": "security_risk",
  "lang": "zh_TW",
  "filters": {
    "policy_decisions": ["blocked", "potentially_blocked", "allowed"],
    "port": "445"
  }
}
```

Report generation 不提供 detail level 分級；輸出一律是完整 detail。舊 payload 若仍帶 `detail_level`，目前視為 legacy no-op。

## 場景九：PCE Cache API

| Endpoint | Method | Body / Query | 用途 |
|:---|:---|:---|:---|
| `/api/cache/status` | GET | 無 | row counts |
| `/api/cache/backfill` | POST | `source`、`since`、`until` | backfill events/traffic |
| `/api/cache/settings` | GET | 無 | 讀取 cache 設定 |
| `/api/cache/settings` | PUT | pce_cache partial settings | 驗證並儲存 |

Backfill 範例：

```json
{
  "source": "traffic",
  "since": "2026-04-01",
  "until": "2026-04-27"
}
```

## 場景十：SIEM Preview API

| Endpoint | Method | 用途 |
|:---|:---|:---|
| `/api/siem/destinations` | GET | 列出 destinations |
| `/api/siem/destinations` | POST | 新增 destination |
| `/api/siem/destinations/<name>` | PUT | 更新 destination |
| `/api/siem/destinations/<name>` | DELETE | 刪除 destination |
| `/api/siem/destinations/<name>/test` | POST | 發 synthetic test event |
| `/api/siem/status` | GET | pending/sent/failed/DLQ |
| `/api/siem/dlq` | GET | 列 DLQ |
| `/api/siem/dlq/replay` | POST | replay DLQ |
| `/api/siem/dlq/purge` | POST | purge DLQ |
| `/api/siem/dlq/export` | GET | export DLQ CSV |

Destination schema 摘要：

```json
{
  "name": "soc",
  "enabled": true,
  "transport": "tls",
  "format": "cef",
  "endpoint": "siem.example.com:6514",
  "tls_verify": true,
  "batch_size": 100,
  "source_types": ["audit", "traffic"],
  "max_retries": 10
}
```

## 場景十一：多 PCE Profile

| Endpoint | 用途 |
|:---|:---|
| `GET /api/pce-profiles` | 列出 profiles |
| `POST /api/pce-profiles` | 新增、更新、啟用或刪除 profile，視 payload action 而定 |

Profile 切換會同步 `api.url`、`api.org_id`、`api.key`、`api.secret`、`api.verify_ssl`。

## SIEM/SOAR 快速查閱表

| 需求 | 建議入口 |
|:---|:---|
| PCE connectivity health | `python illumio_ops.py status` 或 PCE org endpoint |
| Workload inventory | `workload list` 或 PCE workloads API |
| Traffic risk report | `report traffic` 或 `/api/reports/generate` |
| Audit report | `report audit` 或 `/api/audit_report/generate` |
| Cache operational state | `cache status` 或 `/api/cache/status` |
| SIEM test event | `siem test <dest>` 或 `/api/siem/destinations/<name>/test` |
| DLQ operations | `siem dlq/replay/purge` 或 `/api/siem/dlq*` |
