---
title: CLI 參考手冊
audience: [operator, developer]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/cli/root.py
  - src/cli/_global_flags.py
  - src/cli/_completion.py
  - src/cli/_exit_codes.py
  - src/cli/cache.py
  - src/cli/config.py
  - src/cli/gui_cmd.py
  - src/cli/monitor.py
  - src/cli/monitor_gui_cmd.py
  - src/cli/report.py
  - src/cli/rule.py
  - src/cli/siem.py
  - src/cli/status.py
  - src/cli/workload.py
  - src/cli/_render.py
  - src/main.py
  - src/alerts/plugins.py
  - src/__init__.py
---

# CLI 參考手冊

本篇涵蓋 `illumio-ops` 的完整命令樹：13 個頂層子命令（依 `src/cli/root.py` 註冊順序）、
每個子命令的選項表與至少一個實例、結束碼、環境變數，以及仍受支援的舊版 argparse 旗標。
所有內容以原始碼（`src/cli/` 各檔的 Click option 宣告）為準；報表家族與監控規則的**用途**說明見
[reports.md](../guide/reports.md) 與 [monitoring-alerts.md](../guide/monitoring-alerts.md)，本篇只列命令語法。

---

## 語法概要

```
illumio-ops [全域旗標] <子命令> [參數...]
```

所有 PCE 憑證與連線設定均從 `config/config.json` 讀取（也可用 `illumio-ops config login`
互動式寫入）。CLI **不**接受把 PCE 憑證當成一般旗標傳入。

**舊版 argparse 入口** — `--monitor`、`--gui`、`--report` 等旗標仍為向後相容保留（見
[舊版 argparse 旗標](#舊版-argparse-旗標)一節），但已非標準介面。本文件其餘章節一律使用子命令形式。

---

## 全域旗標

以下旗標可置於子命令之前（由 `src/cli/_global_flags.py` 的 `inject_global_flags` 裝飾器注入頂層群組）：

```
illumio-ops [--json] [-q] [-v] <子命令> [參數...]
```

| 旗標 | 縮寫 | 說明 |
|------|------|------|
| `--json` | | 將機器可讀的 JSON 輸出至 stdout（每筆結果一個物件）。錯誤仍以 JSON 輸出至 stderr。 |
| `--quiet` | `-q` | 抑制非必要輸出；錯誤仍會輸出至 stderr。與 `--verbose` 互斥（同時給會回傳 `EXIT_USAGE`）。 |
| `--verbose` | `-v` | 詳細輸出，包含 debug 層級資訊。 |
| `--help` | `-h` | 顯示說明訊息並退出。 |

> **注意：** `--lang` **不是** CLI 旗標。語言設定透過 `config/config.json` 中的
> `settings.language` 欄位配置。環境變數 `ILLUMIO_OPS_I18N_STRICT`（詳見
> [環境變數](#環境變數)）僅影響報表輸出的 i18n 嚴格模式。色彩輸出可用 `NO_COLOR` 環境變數關閉
> （見 `src/cli/_render.py`）。

---

## 子命令

### cache

PCE 快取管理——回填、狀態、保留策略。

```
illumio-ops cache <子命令> [選項]
```

#### cache backfill

從 API 回填指定歷史日期範圍的 PCE 快取（`events` 或 `traffic` 其中一種資料源，每次只能選一種）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--source` | `[events\|traffic]` | 無（必填） | 回填的資料源。 |
| `--since` | TEXT (`YYYY-MM-DD`) | 無（必填） | 回填起始日期。 |
| `--until` | TEXT (`YYYY-MM-DD`) | 今天 | 回填結束日期。 |
| `--json` | flag | `false` | 以 JSON 輸出結果。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops cache backfill --source traffic --since 2026-06-01
illumio-ops cache backfill --source events --since 2026-06-01 --until 2026-06-15 --json
```

#### cache status

顯示快取資料列數（`events`／`traffic_raw`／`traffic_agg` 三張表）及最後同步時間戳。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops cache status
illumio-ops --json cache status
```

#### cache retention

顯示已設定的快取保留策略，或加 `--run` 立即執行保留清理。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--run` | flag | `false` | 立即執行保留清理，而非只顯示設定。 |
| `--json` | flag | `false` | 以 JSON 輸出設定（或執行結果）。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops cache retention
illumio-ops cache retention --run
```

---

### completion

管理 Shell 補全安裝（bash、zsh、fish）。

```
illumio-ops completion <子命令> [選項]
```

#### completion install

輸出需加入 shell rc 檔的 `source`／`fpath` 行，指向 `scripts/completions/` 下對應的補全檔。

```
illumio-ops completion install {bash|zsh|fish}
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `SHELL`（位置參數） | `{bash\|zsh\|fish}` | 無（必填） | 目標 shell。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
# 輸出需加入 ~/.bashrc 的行：
illumio-ops completion install bash

# 輸出需加入 ~/.zshrc 的行：
illumio-ops completion install zsh
```

---

### config

檢查、驗證、修改 `config/config.json`。

```
illumio-ops config <子命令> [選項]
```

#### config show

以格式化 JSON 輸出目前（已載入的）設定。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--section` | TEXT | 無（顯示全部） | 只顯示指定區段（如 `api`、`smtp`、`web_gui`）。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops config show
illumio-ops config show --section api
illumio-ops --json config show --section siem
```

#### config validate

依 pydantic schema（`src/config_models.py`）驗證 `config.json`；驗證前會先套用與 `ConfigManager.load()`
相同的「已棄用欄位剔除」邏輯，避免正式環境能載入、卻被本命令誤判為不合法的落差。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--file` | PATH | `config/config.json` | 要驗證的設定檔路徑。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops config validate
illumio-ops config validate --file /etc/illumio/config.json
```

#### config set

以 `區段.欄位` 的點記法設定單一設定值，寫入前會依 pydantic schema 驗證該區段。密鑰類欄位
（`key`／`secret`／`password`／`token`）在輸出中會被遮蔽為 `[REDACTED]`。

```
illumio-ops config set KEY VALUE
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `KEY`（位置參數） | TEXT（`區段.欄位`） | 無（必填） | 可寫入區段限 `api`／`smtp`／`settings`／`web_gui`。 |
| `VALUE`（位置參數） | TEXT | 無（必填） | 依目前值型別自動轉型（bool／int／float／str）。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops config set api.url https://pce.example.com:8443
illumio-ops config set smtp.password s3cr3t   # 輸出會顯示 [REDACTED]
```

#### config login

互動式（或非互動式）設定 PCE API 憑證（`url`／`key`／`secret`／`org-id`）。不加
`--no-interactive` 時，未提供的欄位會逐一提示輸入；secret 輸入時終端不回顯。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--url` | TEXT | 互動提示 | PCE URL（如 `https://pce.example.com:8443`）。 |
| `--key` | TEXT | 互動提示 | API key。 |
| `--secret` | TEXT | 互動提示（隱藏輸入） | API secret。 |
| `--org-id` | TEXT | `1` | 組織 ID。 |
| `--no-interactive` | flag | `false` | 跳過互動提示；此時 `--url`／`--key`／`--secret` 皆為必填。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops config login
illumio-ops config login --no-interactive --url https://pce.example.com:8443 --key K --secret S --org-id 1
```

---

### gui

啟動 Web GUI（等同舊版 `--gui` 旗標）。

```
illumio-ops gui [選項]
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--port` | INTEGER | `5001` | HTTP 監聽連接埠。 |
| `-h, --host` | TEXT | `0.0.0.0` | 綁定位址。 |
| `--help` | | | 顯示說明並退出（本子命令的 `-h` 已被 `--host` 佔用，說明旗標只有長格式）。 |

```bash
illumio-ops gui
illumio-ops gui --port 8443 --host 0.0.0.0
```

---

### monitor

執行無介面監控常駐程式（等同舊版 `--monitor` 旗標）。

```
illumio-ops monitor [選項]
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `-i, --interval` | INTEGER | `10` | 每次監控循環的間隔分鐘數。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops monitor
illumio-ops monitor --interval 5
```

---

### monitor-gui

同時執行無介面監控與 Web GUI（等同舊版 `--monitor-gui` 旗標）。

```
illumio-ops monitor-gui [選項]
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `-i, --interval` | INTEGER | `10` | 監控循環間隔分鐘數。 |
| `-p, --port` | INTEGER | `5001` | GUI 連接埠。 |
| `--host` | TEXT | `0.0.0.0` | GUI 綁定主機。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops monitor-gui
illumio-ops monitor-gui --interval 15 --port 8443 --host 0.0.0.0
```

---

### report

產生報表。標準子命令（`report --help` 實際輸出，不含 `generate-*` 別名）共 12 個：
`traffic`、`draft-policy`、`security`、`inventory`、`audit`、`ven-status`、`policy-usage`、
`rule-hit-count`、`app-summary`、`resolve`、`readiness`、`policy-diff`。

```
illumio-ops report <子命令> [選項]
```

`traffic`／`security`／`inventory`／`audit`／`ven-status`／`policy-usage`／`app-summary` 七個子命令
另有 `generate-<名稱>` 形式的別名（輸出與標準命令完全相同，`--help` 中會標示
`(alias of <canonical>)`），見[子命令別名](#子命令別名)。各報表回答什麼問題、關鍵欄位等業務層說明見
[reports.md](../guide/reports.md)；以下只列 CLI 語法。

> **`--format pdf` 已知落差**：`traffic`／`draft-policy`／`security`／`inventory`／`audit`／
> `ven-status`／`policy-usage` 七個子命令的 `--format` 選項雖然接受 `pdf`，但對應的 exporter
> 目前**沒有實作 pdf 分支**——選這個格式會靜默不輸出任何檔案，結束碼仍是 `0`。詳見
> [troubleshooting.md](../guide/troubleshooting.md) §4.3；請改用 `--format html`（內建瀏覽器列印為 PDF）
> 或 `--format xlsx`。

#### report traffic

產生流量報表——僅純流量事實，不含安全評分。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--source` | `[api\|csv]` | `api` | 資料來源。 |
| `--file` | PATH（須存在） | 無 | 輸入檔路徑（`--source csv` 時使用）。 |
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/`（設定檔可覆寫） | 報表輸出目錄。 |
| `--email` | flag | `false` | 產生後以 e-mail 寄送報表。 |
| `--data-source` | `[hybrid\|live\|cache-only]` | `hybrid` | `hybrid`＝快取＋即時補缺口；`live`＝只查 PCE；`cache-only`＝只用快取範圍內資料，速度最快。 |
| `--cache/--no-cache` | flag | 無 | **已棄用**，請改用 `--data-source`。 |
| `--profile` | `[security_risk\|network_inventory]` | 無 | **已棄用**，重現分拆前的 `report security`／`report inventory` 輸出。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report traffic --format html --output-dir /tmp/reports
illumio-ops report traffic --source csv --file flows.csv --format xlsx
```

#### report draft-policy

產生 Draft-Policy 報表（R01–R05）。一律即時查詢 PCE（帶 `compute_draft`，耗時約 12 秒），快取無法
提供此報表所需的 draft 欄位；`compute_draft` 在寬時間窗下開銷大，建議用 `--start-date`／`--end-date` 限縮
（預設回溯 7 天）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--start-date` | TEXT (`YYYY-MM-DD`) | 回溯 7 天 | 起始日期。 |
| `--end-date` | TEXT (`YYYY-MM-DD`) | 今天 | 結束日期。 |
| `--max-records` | INTEGER | 無 | 上限分析流量筆數（優先保留 draft 與 active 決策不同的流量），避免高流量 PCE 上算圖太久。 |
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `--email` | flag | `false` | 產生後以 e-mail 寄送報表。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report draft-policy --start-date 2026-07-10 --end-date 2026-07-17
```

#### report security

產生安全風險報表（Security Risk Report）——B/L/R 規則發現，可選擇加入 V-E 弱點暴露區段。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--source` | `[api\|csv]` | `api` | 資料來源。 |
| `--file` | PATH（須存在） | 無 | 輸入檔路徑（`--source csv` 時使用）。 |
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `--email` | flag | `false` | 產生後以 e-mail 寄送報表。 |
| `--vuln-csv` | PATH（須存在） | 無 | 弱點掃描 CSV（`ip`＋`cve` 欄，接受 Qualys／Tenable 匯出），用於 V-E 區段。 |
| `--data-source` | `[hybrid\|live\|cache-only]` | `hybrid` | 同 `report traffic`。 |
| `--cache/--no-cache` | flag | 無 | **已棄用**，請改用 `--data-source`。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report security --format html --output-dir /tmp/reports
illumio-ops report security --vuln-csv qualys-export.csv --format xlsx
```

#### report inventory

產生網路與流量盤點報表（Workload、label 與觀測到的 service）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--source` | `[api\|csv]` | `api` | 資料來源。 |
| `--file` | PATH（須存在） | 無 | 輸入檔路徑（`--source csv` 時使用）。 |
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `--email` | flag | `false` | 產生後以 e-mail 寄送報表。 |
| `--data-source` | `[hybrid\|live\|cache-only]` | `hybrid` | 同 `report traffic`。 |
| `--cache/--no-cache` | flag | 無 | **已棄用**，請改用 `--data-source`。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report inventory --format xlsx
```

#### report audit

產生稽核報表。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--start-date` | TEXT (`YYYY-MM-DD`) | 無 | 開始日期。 |
| `--end-date` | TEXT (`YYYY-MM-DD`) | 無 | 結束日期。 |
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report audit --start-date 2026-05-01 --end-date 2026-05-15
illumio-ops report audit --format xlsx --output-dir /var/reports
```

#### report ven-status

產生 VEN 狀態報表。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report ven-status --format html
illumio-ops --json report ven-status
```

#### report policy-usage

產生政策使用量報表。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--source` | `[api\|csv]` | `api` | 資料來源。 |
| `--file` | PATH（須存在） | 無 | 輸入檔路徑（`--source csv` 時使用）。 |
| `--start-date` | TEXT (`YYYY-MM-DD`) | 無 | 開始日期。 |
| `--end-date` | TEXT (`YYYY-MM-DD`) | 無 | 結束日期。 |
| `--format` | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 輸出格式（`pdf` 見上方已知落差）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report policy-usage --start-date 2026-05-01 --format xlsx
illumio-ops report policy-usage --source csv --file rules.csv
```

#### report rule-hit-count

產生 Rule Hit Count 報表（原生 PCE 計數資料，並補上規則細節）。若 PCE 尚未啟用 Rule Hit Count，
CLI 在有 TTY 時會跳出互動式啟用精靈（會對 PCE 執行 draft 寫入＋provision，屬正式政策異動，精靈會先警告
並要求確認），並在任一路徑後以 `EXIT_UNAVAILABLE` 結束（精靈不會自動接著產生報表——VEN 端回報計數需要時間）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--source` | `[native\|csv]` | `native` | 資料來源。 |
| `--file` | PATH（須存在） | 無 | 輸入檔路徑（`--source csv` 時使用）。 |
| `--start-date` | TEXT (`YYYY-MM-DD`) | 無 | 開始日期。 |
| `--end-date` | TEXT (`YYYY-MM-DD`) | 無 | 結束日期。 |
| `--format` | `[html\|csv\|all]` | `html` | 輸出格式（此子命令不接受 `pdf`／`xlsx`）。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report rule-hit-count --start-date 2026-06-01 --end-date 2026-07-01
```

#### report app-summary

針對單一 App Label 產生 App 摘要報表（含 inbound／outbound 視角）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--app` | TEXT | 無（必填） | 要聚焦的 App Label 值。 |
| `--env` | TEXT | 無 | 選填的 Env Label 精煉條件。 |
| `--days` | INTEGER | `7` | traffic 回溯天數。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `--data-source` | `[hybrid\|live\|cache-only]` | `hybrid` | 同 `report traffic`（不支援 clip-to-cache，`cache-only` 等同一般快取讀取）。 |
| `--cache/--no-cache` | flag | 無 | **已棄用**，請改用 `--data-source`。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report app-summary --app payments --env prod --days 7
```

#### report resolve

將 ACTIVE 的 label-based Policy 解析為 IP 層級防火牆規則。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--format` | `[json\|csv\|all]` | `json` | 輸出格式。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `-h, --help` | | | 顯示說明並退出。 |

ACTIVE 政策解析為 0 筆時不會寫出任何檔案，CLI 會在 stderr 明確提示（與 GUI 空狀態 toast 一致），
而非靜默無輸出。

```bash
illumio-ops report resolve --format json
```

#### report readiness

產生 Enforcement Readiness 報表（下一個該切 enforcement 的 App 建議）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--start-date` | TEXT (`YYYY-MM-DD`) | 無 | 開始日期。 |
| `--end-date` | TEXT (`YYYY-MM-DD`) | 無 | 結束日期。 |
| `--format` | `[html\|csv\|all]` | `html` | 輸出格式。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `--data-source` | `[hybrid\|live\|cache-only]` | `hybrid` | 同 `report traffic`。 |
| `--cache/--no-cache` | flag | 無 | **已棄用**，請改用 `--data-source`。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report readiness --start-date 2026-06-01 --end-date 2026-07-01
```

#### report policy-diff

產生政策差異報表（Policy Diff Report，DRAFT vs ACTIVE，Ruleset／Rule 範圍）。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--format` | `[html\|csv\|all]` | `html` | 輸出格式。 |
| `--output-dir` | PATH | `reports/` | 報表輸出目錄。 |
| `--email` | flag | `false` | 產生後以 e-mail 寄送報表（僅 HTML 附件）。 |
| `--attribution-days` | INTEGER | `30` | 操作者歸因的 audit-event 回溯視窗。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops report policy-diff --format html --attribution-days 30
```

---

### rule

檢查與編輯監控規則（`config.json` 的 `rules` 陣列；規則型別與語意見
[monitoring-alerts.md](../guide/monitoring-alerts.md)）。

```
illumio-ops rule <子命令> [選項]
```

#### rule list

列出已設定的監控規則。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--type` | `[event\|traffic\|bandwidth\|volume\|system\|all]` | `all` | 依規則類型篩選。 |
| `--enabled-only` | flag | `false` | 僅顯示已啟用的規則。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops rule list
illumio-ops rule list --type traffic --enabled-only
illumio-ops --json rule list
```

#### rule edit

以 1-based 索引互動式編輯規則（名稱／啟用狀態／threshold），儲存前預設顯示差異預覽並要求確認。

```
illumio-ops rule edit RULE_ID [選項]
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `RULE_ID`（位置參數） | INTEGER | 無（必填） | 規則的 1-based 索引（見 `rule list` 的 `#` 欄）。 |
| `--no-preview` | flag | `false` | 儲存前跳過差異預覽（略過確認步驟）。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops rule edit 3
illumio-ops rule edit 3 --no-preview
```

---

### shell

啟動互動式選單。**TLS 憑證管理**、**PCE 設定檔管理**、**規則排程器配置**等功能僅透過互動式 shell
存取，未作為頂層 CLI 子命令對外公開。裸呼叫 `illumio-ops`（不帶任何子命令）會顯示已棄用警告後仍啟動同一選單；
請優先使用明確的 `illumio-ops shell`。

```
illumio-ops shell
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops shell
```

> **未接線功能說明：** `tls`、`pce`（設定檔管理）、`rule-scheduler` 不是頂層 CLI 子命令，只能透過
> 執行 `illumio-ops shell` 後在選單中操作。請勿嘗試直接呼叫。

---

### siem

SIEM 轉發器管理（destinations 設定與轉送流程見 [siem.md](../guide/siem.md)）。

```
illumio-ops siem <子命令> [選項]
```

#### siem status

顯示各目標目的地的派送計數（pending／sent／failed／dlq）。目的地集合為已設定目的地與
`SiemDispatch` 資料表中觀察到的目的地之聯集，與 WebUI 整合頁籤所顯示一致。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops siem status
illumio-ops --json siem status
```

#### siem test

向指定目的地發送合成測試事件並回報成功／失敗。

```
illumio-ops siem test DESTINATION [選項]
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `DESTINATION`（位置參數） | TEXT | 無（必填） | 目的地名稱，須為已啟用的 destination。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops siem test splunk-prod
```

#### siem dlq

列出指定目的地的 Dead Letter Queue（DLQ）項目。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--dest` | TEXT | 無（必填） | 目的地名稱。 |
| `--limit` | INTEGER | `50` | 顯示的最大項目數。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops siem dlq --dest splunk-prod
illumio-ops siem dlq --dest splunk-prod --limit 100
illumio-ops --json siem dlq --dest splunk-prod
```

#### siem replay

將指定目的地的 DLQ 項目重新排入待派送佇列。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--dest` | TEXT | 無（必填） | 目的地名稱。 |
| `--limit` | INTEGER | `100` | 最多重播的 DLQ 項目數。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops siem replay --dest splunk-prod
illumio-ops siem replay --dest splunk-prod --limit 200
```

#### siem purge

刪除指定目的地中超過 N 天的 DLQ 項目。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--dest` | TEXT | 無（必填） | 目的地名稱。 |
| `--older-than` | INTEGER | `30` | 清除超過 N 天的項目。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops siem purge --dest splunk-prod
illumio-ops siem purge --dest splunk-prod --older-than 7
```

---

### status

顯示常駐程式／排程器／設定狀態（PCE URL、語言、規則數、最後一筆 log 活動時間）。

```
illumio-ops status
```

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops status
illumio-ops --json status
```

---

### version

輸出 illumio-ops 版本號（讀取 `src/__init__.py` 的 `__version__`）。

```
illumio-ops version
```

```bash
illumio-ops version
# illumio-ops 4.1.0
```

---

### workload

檢查 PCE 工作負載。

```
illumio-ops workload <子命令> [選項]
```

#### workload list

從 PCE 擷取並顯示工作負載。

| 選項 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `--env` | TEXT | 無 | 依環境標籤值篩選（如 `prod`）。 |
| `--limit` | INTEGER（≥ 1） | `50` | 最大顯示列數。 |
| `--enforcement` | `[full\|selective\|visibility_only\|idle\|all]` | `all` | 依執行模式篩選。 |
| `--managed-only` | flag | `false` | 僅顯示 VEN 管控的工作負載。 |
| `--pick` | flag | `false` | 互動式挑選 label 作為過濾條件（須有 TTY；非互動環境會顯示提示並回退為未過濾結果）。 |
| `-h, --help` | | | 顯示說明並退出。 |

```bash
illumio-ops workload list
illumio-ops workload list --env prod --managed-only
illumio-ops --json workload list --enforcement full --limit 500
```

---

## 子命令別名

以下別名整合自舊版 `docs/cli-command-map.md`。別名與對應的標準命令產生相同輸出；建議優先使用標準形式。

| 別名 | 標準命令 | 備註 |
|------|----------|------|
| `report generate-traffic` | `report traffic` | `--help` 中顯示 `(alias of traffic)` |
| `report generate-security` | `report security` | `--help` 中顯示 `(alias of security)` |
| `report generate-inventory` | `report inventory` | `--help` 中顯示 `(alias of inventory)` |
| `report generate-audit` | `report audit` | `--help` 中顯示 `(alias of audit)` |
| `report generate-ven-status` | `report ven-status` | `--help` 中顯示 `(alias of ven-status)` |
| `report generate-policy-usage` | `report policy-usage` | `--help` 中顯示 `(alias of policy-usage)` |
| `report generate-app-summary` | `report app-summary` | `--help` 中顯示 `(alias of app-summary)` |
| `illumio-ops`（無參數） | `illumio-ops shell` | 已棄用的裸呼叫；顯示警告後仍啟動選單 |
| `--monitor`（舊版旗標） | `monitor` 子命令 | argparse 向後相容；透過舊版處理器路由 |
| `--monitor-gui`（舊版旗標） | `monitor-gui` 子命令 | argparse 向後相容 |
| `--gui`（舊版旗標） | `gui` 子命令 | argparse 向後相容 |
| `--report`（舊版旗標） | `report traffic` | argparse 向後相容；`--report-type` 選擇變體 |

**入口點參考**：

| 入口 | 狀態 | 備註 |
|------|------|------|
| `illumio-ops <子命令>` | **標準** | 單一命令樹，基於 Click（`src/cli/root.py`） |
| `illumio-ops shell` | **標準** | 明確啟動互動式選單 |
| `illumio-ops`（無參數） | 已棄用 | 顯示警告並提示改用 `shell`；仍會啟動選單 |
| `illumio-ops --monitor` 等 | 向後相容 | 路由至舊版 argparse 處理器（`src/main.py`） |

---

## 舊版 argparse 旗標

`python illumio-ops.py [舊版旗標...]` 這條入口仍受支援，選項來自 `src/main.py` 的
`argparse.ArgumentParser`：

| 旗標 | 縮寫 | 型別 | 預設 | 說明 |
|------|------|------|------|------|
| `--monitor` | | flag | `false` | 以無介面常駐模式執行（不進互動選單）。 |
| `--monitor-gui` | | flag | `false` | 常駐＋Web GUI 一起執行（持續模式，需登入）。 |
| `--interval` | `-i` | INTEGER | `10` | 監控間隔分鐘數。 |
| `--gui` | | flag | `false` | 啟動 Web GUI。 |
| `--port` | `-p` | INTEGER | `5001` | Web GUI 連接埠。 |
| `--report` | | flag | `false` | 從命令列產生報表。 |
| `--report-type` | | `[traffic\|audit\|ven_status\|policy_usage\|draft_policy]` | `traffic` | 報表型別。 |
| `--source` | | `[api\|csv]` | `api` | 報表資料來源。 |
| `--file` | | TEXT | 無 | CSV 檔路徑（`--source csv` 時使用）。 |
| `--format` | | `[html\|csv\|pdf\|xlsx\|all]` | `html` | 報表輸出格式。 |
| `--profile` | | `[security_risk\|network_inventory]` | `security_risk` | 流量報表 profile。 |
| `--email` | | flag | `false` | 產生後以 e-mail 寄送報表。 |
| `--output-dir` | | TEXT | `reports/` | 報表輸出目錄。 |

```bash
python illumio-ops.py                       # 互動式 CLI 選單
python illumio-ops.py --monitor              # 無介面常駐模式
python illumio-ops.py --monitor -i 5         # 常駐模式，5 分鐘間隔
python illumio-ops.py --gui                  # 啟動 Web GUI（連接埠 5001）
python illumio-ops.py --gui --port 8080      # 自訂連接埠的 Web GUI
```

---

## 結束碼

結束碼遵循 BSD `sysexits.h` 慣例。來源：`src/cli/_exit_codes.py`。

| 代碼 | 常數 | 意義 |
|------|------|------|
| `0` | `EXIT_OK` | 成功 |
| `64` | `EXIT_USAGE` | 不正確的呼叫方式（未知旗標、缺少必填參數、`--quiet`／`--verbose` 同時給） |
| `65` | `EXIT_DATAERR` | 輸入資料無效（格式錯誤的 CSV、日期格式不符） |
| `66` | `EXIT_NOINPUT` | 輸入檔案缺失或無法讀取 |
| `69` | `EXIT_UNAVAILABLE` | 服務無法連線（PCE、郵件伺服器）；或 Rule Hit Count 尚未啟用 |
| `70` | `EXIT_SOFTWARE` | 內部錯誤（程式缺陷） |
| `71` | `EXIT_OSERR` | 作業系統層級錯誤（檔案權限、建立目錄失敗、連接埠已被占用） |
| `78` | `EXIT_CONFIG` | `config.json` 錯誤或缺失 |
| `130` | `EXIT_INTERRUPT` | 程序被 Ctrl-C 中斷（SIGINT） |
| `143` | `EXIT_TERMINATED` | 程序被終止（SIGTERM） |

Shell pipeline 範例：

```bash
illumio-ops siem status
case $? in
  0)   echo "OK" ;;
  69)  echo "PCE 無法連線 — 請檢查網路" ;;
  78)  echo "config.json 錯誤" ;;
  130) echo "已中斷" ;;
  *)   echo "錯誤：$?" ;;
esac
```

---

## 環境變數

所有 PCE 憑證與連線設定均儲存於 `config/config.json` 的 `api` 區段
（`url`、`org_id`、`key`、`secret`、`verify_ssl`）。目前不支援純透過環境變數傳入 PCE 憑證。

以下環境變數在執行期間由 CLI／報表層讀取：

| 變數 | 元件 | 說明 |
|------|------|------|
| `NO_COLOR` | 輸出渲染（`src/cli/_render.py`） | 設定任意值即可停用 ANSI 色彩輸出（遵循 [no-color.org](https://no-color.org/)）。 |
| `TERM=dumb` | 輸出渲染 | 終端不支援色彩時同樣停用色彩輸出。 |
| `ILLUMIO_SMTP_PASSWORD` | 告警／SMTP（`src/alerts/plugins.py`） | 覆寫 `config.json` 中的 `smtp.password`。可避免在設定檔中存放明文密碼。 |
| `ILLUMIO_OPS_I18N_STRICT` | 報表 i18n | 設定後，若報表 i18n 層找不到翻譯鍵，將拋出錯誤而非靜默降回英文。用於 CI 翻譯覆蓋率檢查。 |

> **PCE 連線提示：** `EXIT_UNAVAILABLE`（69）的錯誤訊息建議檢查 `PCE_HOST` 與 `PCE_PORT`。
> 這些是**錯誤訊息中的標籤名稱**，而非環境變數——實際值來自 `config.json → api.url`。

---

## 相關文件

- [報表家族](../guide/reports.md) — 各報表的業務用途、關鍵欄位、排程與寄送
- [監控規則、告警與 SIEM](../guide/monitoring-alerts.md) — `rule` 子命令對應的規則型別與語意
- [SIEM 轉送](../guide/siem.md) — `siem` 子命令對應的 destinations 設定與轉送流程
- [故障排除](../guide/troubleshooting.md) — `--format pdf` 無聲落差等症狀導向排錯
- [REST API](rest-api.md) — 程式化等效操作
- [詞彙表](glossary.md) — Illumio 術語說明
- [操作手冊](../operations-manual_zh.md) — 操作員層級操作總覽
