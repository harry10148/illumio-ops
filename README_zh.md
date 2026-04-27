# Illumio PCE Ops

![Version](https://img.shields.io/badge/Version-v3.20.0--report--intelligence-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English summary](README.md)** | **繁體中文主文件**

Illumio PCE Ops 是針對 **Illumio Core / PCE** 的無 Agent 維運工具，涵蓋事件監控、流量分析、安全發現、報表、排程、PCE Cache、SIEM Preview、Web GUI 與 CLI 自動化。

目前文件已收斂為少數主文件：README 只保留快速入口，深入內容集中到 `docs/` 內的 4 份中文主文件與 1 份既有 SIEM integration 相容文件。

## 功能總覽

| 範圍 | 目前功能 |
|:---|:---|
| CLI / Daemon | 互動式選單、舊式 `--monitor` / `--gui` / `--report` 旗標、Click 子命令 `monitor`、`gui`、`report`、`rule`、`workload`、`config`、`cache`、`siem`、`status`、`version` |
| Web GUI | 登入、CSRF token、rate limit、IP allowlist、Dashboard、Rules、Settings、報表產生/下載/批次刪除、Report Schedule、Quarantine、Rule Scheduler、Logs、Daemon restart |
| PCE API | 工作負載、事件、流量查詢、async traffic job、label cache、rule traffic count、retry/resume |
| 監控與告警 | 事件規則、流量/頻寬/流量量規則、Best Practice 規則、Email / LINE / Webhook |
| 報表 | Traffic、Audit、VEN Status、Policy Usage；HTML / CSV / PDF / XLSX；支援 report profile、完整 detail 輸出、圖表、metadata、dashboard summary |
| PCE Cache | SQLite cache、events/traffic ingestor、backfill、retention、watermark、lag monitor、cache-aware report path |
| SIEM Preview | UDP/TCP/TLS/HEC destinations、CEF/JSON/syslog formats、dispatcher、DLQ、replay/purge/export、test event |
| i18n | CLI、Web GUI、報表與告警文字必須使用 i18n key，英文與繁中 key 需同步 |

## 快速開始

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json
python illumio_ops.py
```

常用模式：

```bash
python illumio_ops.py --gui
python illumio_ops.py --monitor --interval 5
python illumio_ops.py --monitor-gui --interval 5 --port 5001
python illumio_ops.py report traffic --format html --profile security_risk
python illumio_ops.py cache status
python illumio_ops.py siem status
```

## 文件索引

| 文件 | 用途 |
|:---|:---|
| [使用手冊](docs/User_Manual_zh.md) | 安裝、執行、部署、Web GUI、報表、PCE Cache、SIEM Preview、疑難排解 |
| [架構與功能盤點](docs/Project_Architecture_zh.md) | 功能盤點、模組架構、資料流、修改指南 |
| [API / 整合指南](docs/API_Cookbook_zh.md) | PCE API、工具內部 API、SIEM/SOAR、Cache、Report automation 範例 |
| [安全規則參考](docs/Security_Rules_Reference_zh.md) | R/B/L 規則、severity、threshold、連接埠參考 |
| [SIEM Integration](docs/SIEM_Integration.md) | 既有英文 SIEM integration 與測試相容文件 |

## 專案結構

```text
illumio_ops/
├── illumio_ops.py              # entrypoint：Click 子命令或 legacy argparse
├── src/
│   ├── cli/                    # Click command groups
│   ├── gui/                    # Flask Web GUI app factory and API routes
│   ├── api_client.py           # PCE REST API / async traffic query
│   ├── analyzer.py             # monitor loop analysis and alert trigger
│   ├── reporter.py             # alert dispatch
│   ├── config.py               # config load/save and profile CRUD
│   ├── config_models.py        # Pydantic config schema
│   ├── events/                 # event catalog, normalization, matching, throttling
│   ├── pce_cache/              # SQLite cache, ingestors, retention, reader
│   ├── report/                 # traffic/audit/VEN/policy usage report engine
│   └── siem/                   # SIEM Preview runtime and transports
├── config/                     # config template and report thresholds
├── deploy/                     # systemd / Windows service and SIEM collector samples
├── docs/                       # consolidated documentation
├── scripts/                    # install, preflight, i18n audit, offline bundle helpers
└── tests/                      # pytest suite
```
