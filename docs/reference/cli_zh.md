---
title: CLI Reference
audience: [operator, api, developer]
last_verified: 2026-05-15
verified_against:
  - src/cli/
  - src/cli/menus/
  - docs/cli-command-map.md (legacy, folded in)
  - python illumio-ops.py --help
  - python illumio-ops.py <subcmd> --help (each subcommand)
  - commit 060a32f
related_docs:
  - rest-api.md
  - glossary.md
  - ../user-guide/reports.md
  - ../user-guide/siem-integration.md
---

> **[English](cli.md)** | **[繁體中文](cli_zh.md)**
> 📍 [INDEX](../INDEX.md) › 參考 › CLI
> 🔍 最後驗證 **2026-05-15** 對 commit `060a32f` — 詳見 frontmatter

# CLI 參考手冊

---

## 語法概要

```
illumio-ops [全域旗標] <子命令> [參數...]
```

所有憑證與 PCE 連線設定均從 `config/config.json` 讀取。
CLI **不接受**以旗標形式傳入 PCE 憑證——請在設定檔中配置
（覆寫方式見[環境變數](#環境變數)章節）。

**舊版 argparse 入口** — `--monitor`、`--gui`、`--report` 等舊旗標
仍為向後相容保留，但已非標準介面。請優先使用本文件所示的子命令形式。

---

## 全域旗標

以下旗標可置於子命令之前：

```
illumio-ops [--json] [-q] [-v] <子命令> [參數...]
```

| 旗標 | 縮寫 | 說明 |
|------|------|------|
| `--json` | | 將機器可讀的 JSON 輸出至 stdout（每筆結果一個物件）。錯誤仍以 JSON 輸出至 stderr。 |
| `--quiet` | `-q` | 抑制非必要輸出；錯誤仍會輸出至 stderr。 |
| `--verbose` | `-v` | 詳細輸出，包含 debug 層級資訊。 |
| `--help` | `-h` | 顯示說明訊息並退出。 |

> **注意：** `--lang` **不是** CLI 旗標。語言設定透過 `config/config.json` 中的
> `settings.language` 欄位配置。環境變數 `ILLUMIO_OPS_I18N_STRICT`（詳見
> [環境變數](#環境變數)）僅影響報表輸出的 i18n 嚴格模式。

---

## 子命令

### cache

PCE 快取管理——回填、狀態、保留策略。

```
illumio-ops cache <子命令> [選項]
```

#### cache backfill

從 API 回填指定歷史日期範圍的 PCE 快取。

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops cache backfill
illumio-ops --json cache backfill
```

#### cache status

顯示快取資料列數及最後同步時間戳。

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops cache status
illumio-ops --json cache status
```

#### cache retention

顯示已設定的快取保留策略，或立即執行保留清理。

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops cache retention
```

---

### completion

管理 Shell 補全安裝（bash、zsh、fish）。

```
illumio-ops completion <子命令> [選項]
```

#### completion install

輸出需加入 shell rc 檔的 `source`/`fpath` 行。

```
illumio-ops completion install {bash|zsh|fish}
```

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
# 輸出需加入 ~/.bashrc 的行：
illumio-ops completion install bash

# 輸出需加入 ~/.zshrc 的行：
illumio-ops completion install zsh
```

---

### config

檢查並驗證 `config/config.json`。

```
illumio-ops config <子命令> [選項]
```

#### config show

以格式化 JSON 輸出目前（已驗證的）設定。

| 選項 | 說明 |
|------|------|
| `--section TEXT` | 僅顯示指定區段（如 `api`、`smtp`、`web_gui`）。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops config show
illumio-ops config show --section api
illumio-ops --json config show --section siem
```

#### config validate

依 pydantic schema 驗證 `config.json`。

| 選項 | 說明 |
|------|------|
| `--file PATH` | config.json 路徑（預設：`config/config.json`）。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops config validate
illumio-ops config validate --file /etc/illumio/config.json
```

---

### gui

啟動 Web GUI（等同舊版 `--gui` 旗標）。

```
illumio-ops gui [選項]
```

| 選項 | 說明 |
|------|------|
| `-p, --port INTEGER` | HTTP 監聽連接埠。 |
| `-h, --host TEXT` | 綁定位址（預設取自設定檔）。 |
| `--help` | 顯示說明並退出。 |

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

| 選項 | 說明 |
|------|------|
| `-i, --interval INTEGER` | 每次循環間隔分鐘數。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops monitor
illumio-ops monitor --interval 10
```

---

### monitor-gui

同時執行無介面監控與 Web GUI（等同舊版 `--monitor-gui` 旗標）。

```
illumio-ops monitor-gui [選項]
```

| 選項 | 說明 |
|------|------|
| `-i, --interval INTEGER` | 監控循環間隔分鐘數。 |
| `-p, --port INTEGER` | GUI 連接埠。 |
| `--host TEXT` | GUI 綁定主機。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops monitor-gui
illumio-ops monitor-gui --interval 15 --port 8443
```

---

### report

產生報表（流量 / 稽核 / VEN 狀態 / 政策使用量）。

```
illumio-ops report <子命令> [選項]
```

標準子命令名稱與 WebUI 按鈕標籤一致。`generate-*` 形式為別名
（詳見[子命令別名](#子命令別名)）。

#### report traffic

產生流量分析報表。

| 選項 | 說明 |
|------|------|
| `--source [api\|csv]` | 資料來源。 |
| `--file PATH` | 輸入檔路徑（`--source csv` 時使用）。 |
| `--format [html\|csv\|pdf\|xlsx\|all]` | 輸出格式。 |
| `--output-dir PATH` | 報表輸出目錄。 |
| `--email` | 產生後以 e-mail 寄送報表。 |
| `--profile [security_risk\|network_inventory]` | 流量報表分析設定檔。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops report traffic --format html --output-dir /tmp/reports
illumio-ops report traffic --source csv --file flows.csv --format xlsx
```

#### report audit

產生稽核報表。

| 選項 | 說明 |
|------|------|
| `--start-date TEXT` | 開始日期（`YYYY-MM-DD`）。 |
| `--end-date TEXT` | 結束日期（`YYYY-MM-DD`）。 |
| `--format [html\|csv\|pdf\|xlsx\|all]` | 輸出格式。 |
| `--output-dir PATH` | 報表輸出目錄。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops report audit --start-date 2026-05-01 --end-date 2026-05-15
illumio-ops report audit --format pdf --output-dir /var/reports
```

#### report ven-status

產生 VEN 狀態報表。

| 選項 | 說明 |
|------|------|
| `--format [html\|csv\|pdf\|xlsx\|all]` | 輸出格式。 |
| `--output-dir PATH` | 報表輸出目錄。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops report ven-status --format html
illumio-ops --json report ven-status
```

#### report policy-usage

產生政策使用量報表。

| 選項 | 說明 |
|------|------|
| `--source [api\|csv]` | 資料來源。 |
| `--file PATH` | 輸入檔路徑（`--source csv` 時使用）。 |
| `--start-date TEXT` | 開始日期（`YYYY-MM-DD`）。 |
| `--end-date TEXT` | 結束日期（`YYYY-MM-DD`）。 |
| `--format [html\|csv\|pdf\|xlsx\|all]` | 輸出格式。 |
| `--output-dir PATH` | 報表輸出目錄。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops report policy-usage --start-date 2026-05-01 --format xlsx
illumio-ops report policy-usage --source csv --file rules.csv
```

---

### rule

檢查與編輯監控規則。

```
illumio-ops rule <子命令> [選項]
```

#### rule list

列出已設定的監控規則。

| 選項 | 說明 |
|------|------|
| `--type [event\|traffic\|bandwidth\|volume\|system\|all]` | 依規則類型篩選。 |
| `--enabled-only` | 僅顯示已啟用的規則。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops rule list
illumio-ops rule list --type traffic --enabled-only
illumio-ops --json rule list
```

#### rule edit

以 1-based 索引互動式編輯規則。

```
illumio-ops rule edit [選項] RULE_ID
```

| 選項 | 說明 |
|------|------|
| `--no-preview` | 儲存前略過差異預覽。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops rule edit 3
illumio-ops rule edit 3 --no-preview
```

---

### shell

啟動互動式選單。**TLS 憑證管理**、**PCE 設定檔管理**、**規則排程器配置**
等功能均僅透過互動式 shell 存取，未作為 CLI 子命令對外公開。

```
illumio-ops shell
```

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops shell
```

> **未接線功能說明：** `tls`、`pce`（設定檔管理）、`rule-scheduler`
> **不是**頂層 CLI 子命令，只能透過執行 `illumio-ops shell` 後在選單中操作。
> 請勿嘗試直接呼叫。

---

### siem

SIEM 轉發器管理。

```
illumio-ops siem <子命令> [選項]
```

#### siem status

顯示各目標目的地的派送計數。目的地集合為已設定目的地與
`SiemDispatch` 資料表中觀察到的目的地之聯集，與 WebUI 整合頁籤所顯示一致。

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops siem status
illumio-ops --json siem status
```

#### siem test

向指定目的地發送合成測試事件並回報成功/失敗。

```
illumio-ops siem test [選項] DESTINATION
```

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops siem test splunk-prod
```

#### siem dlq

列出指定目的地的 Dead Letter Queue（DLQ）項目。

| 選項 | 說明 |
|------|------|
| `--dest TEXT` | 目的地名稱。**必填。** |
| `--limit INTEGER` | 顯示的最大項目數（預設：50）。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops siem dlq --dest splunk-prod
illumio-ops siem dlq --dest splunk-prod --limit 100
illumio-ops --json siem dlq --dest splunk-prod
```

#### siem replay

將指定目的地的 DLQ 項目重新排入待派送佇列。

| 選項 | 說明 |
|------|------|
| `--dest TEXT` | 目的地名稱。**必填。** |
| `--limit INTEGER` | 最多重播的 DLQ 項目數（預設：100）。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops siem replay --dest splunk-prod
illumio-ops siem replay --dest splunk-prod --limit 200
```

#### siem purge

刪除指定目的地中超過 N 天的 DLQ 項目。

| 選項 | 說明 |
|------|------|
| `--dest TEXT` | 目的地名稱。**必填。** |
| `--older-than INTEGER` | 清除超過 N 天的項目（預設：30）。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops siem purge --dest splunk-prod
illumio-ops siem purge --dest splunk-prod --older-than 7
```

---

### status

顯示常駐程式 / 排程器 / 設定狀態。

```
illumio-ops status
```

| 選項 | 說明 |
|------|------|
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops status
illumio-ops --json status
```

---

### version

輸出 illumio-ops 版本號。

```
illumio-ops version
```

```bash
illumio-ops version
# illumio-ops 3.25.0-tracks-abcd
```

---

### workload

檢查 PCE 工作負載。

```
illumio-ops workload <子命令> [選項]
```

#### workload list

從 PCE 擷取並顯示工作負載。

| 選項 | 說明 |
|------|------|
| `--env TEXT` | 依環境標籤值篩選（如 `prod`）。 |
| `--limit INTEGER` | 最大顯示列數（須 ≥ 1）。 |
| `--enforcement [full\|selective\|visibility_only\|idle\|all]` | 依執行模式篩選。 |
| `--managed-only` | 僅顯示 VEN 管控的工作負載。 |
| `-h, --help` | 顯示說明並退出。 |

```bash
illumio-ops workload list
illumio-ops workload list --env prod --managed-only
illumio-ops --json workload list --enforcement full --limit 500
```

---

## 子命令別名

以下別名整合自 `docs/cli-command-map.md`。別名與對應的標準命令產生相同輸出；建議優先使用標準形式。

| 別名 | 標準命令 | 備註 |
|------|----------|------|
| `report generate-traffic` | `report traffic` | `--help` 中顯示 `(alias of traffic)` |
| `report generate-audit` | `report audit` | `--help` 中顯示 `(alias of audit)` |
| `report generate-ven-status` | `report ven-status` | `--help` 中顯示 `(alias of ven-status)` |
| `report generate-policy-usage` | `report policy-usage` | `--help` 中顯示 `(alias of policy-usage)` |
| `illumio-ops`（無參數） | `illumio-ops shell` | 已棄用的裸呼叫；會提示使用 `shell` |
| `--monitor`（舊版旗標） | `monitor` 子命令 | argparse 向後相容；透過舊版處理器路由 |
| `--monitor-gui`（舊版旗標） | `monitor-gui` 子命令 | argparse 向後相容 |
| `--gui`（舊版旗標） | `gui` 子命令 | argparse 向後相容 |
| `--report`（舊版旗標） | `report traffic` | argparse 向後相容；`--report-type` 選擇變體 |

**入口點參考**（來自 `cli-command-map.md`）：

| 入口 | 狀態 | 備註 |
|------|------|------|
| `illumio-ops <子命令>` | **標準** | 單一命令樹，基於 Click |
| `illumio-ops shell` | **標準** | 明確啟動互動式選單 |
| `illumio-ops`（無參數） | 已棄用 | 顯示提示指向 `shell`；仍會啟動選單 |
| `illumio-ops --monitor` 等 | 向後相容 | 路由至舊版 argparse 處理器 |
| `python -m src.pce_cache_cli` | 非獨立入口 | 由 `src/main.py` 內部呼叫；請勿直接執行 |
| `python -m src.siem_cli` | 非獨立入口 | 同上 |
| `python -m src.rule_scheduler_cli` | 非獨立入口 | 同上 |

---

## 結束碼

結束碼遵循 BSD `sysexits.h` 慣例。來源：`src/cli/_exit_codes.py`。

| 代碼 | 常數 | 意義 |
|------|------|------|
| `0` | `EXIT_OK` | 成功 |
| `64` | `EXIT_USAGE` | 不正確的呼叫方式（未知旗標、缺少必填參數） |
| `65` | `EXIT_DATAERR` | 輸入資料無效（格式錯誤的 CSV、日期格式不符） |
| `66` | `EXIT_NOINPUT` | 輸入檔案缺失或無法讀取 |
| `69` | `EXIT_UNAVAILABLE` | 服務無法連線（PCE、郵件伺服器） |
| `70` | `EXIT_SOFTWARE` | 內部錯誤（程式缺陷） |
| `71` | `EXIT_OSERR` | 作業系統層級錯誤（檔案權限、建立目錄失敗） |
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

以下環境變數在執行期間由 CLI 讀取：

| 變數 | 元件 | 說明 |
|------|------|------|
| `NO_COLOR` | 輸出渲染 | 設定任意值即可停用 ANSI 色彩輸出（遵循 [no-color.org](https://no-color.org/)）。 |
| `TERM=dumb` | 輸出渲染 | 終端不支援色彩時同樣停用色彩輸出。 |
| `ILLUMIO_SMTP_PASSWORD` | 警報 / SMTP | 覆寫 `config.json` 中的 `smtp.password`。可避免在設定檔中存放明文密碼。 |
| `ILLUMIO_OPS_I18N_STRICT` | 報表 i18n | 設定後，若報表 i18n 層找不到翻譯鍵，將拋出錯誤而非靜默降回英文。用於 CI 翻譯覆蓋率檢查。 |

> **PCE 連線提示：** `EXIT_UNAVAILABLE`（69）的錯誤訊息建議檢查 `PCE_HOST` 與 `PCE_PORT`。
> 這些是**錯誤訊息中的標籤名稱**，而非環境變數——實際值來自 `config.json → api.url`。

---

## 相關文件

- [REST API](rest-api.md) — 程式化等效操作（B2 交付物）
- [詞彙表](glossary.md) — Illumio 術語說明
- [報表使用指南](../user-guide/reports.md) — 操作員層級報表使用
- [SIEM 整合](../user-guide/siem-integration.md) — 操作員層級 SIEM 配置
