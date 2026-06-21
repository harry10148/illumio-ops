# illumio-ops

![Version](https://img.shields.io/badge/Version-v4.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** 是針對 **Illumio Core (PCE)** 的 agentless 監控與自動化工具，僅透過 PCE REST API 互動。它補齊 PCE Web Console 的維運缺口：排程流量/稽核/VEN 狀態報表、多通道警示（Email、LINE、Webhook）、SIEM 轉送、安全規則排程、Workload 隔離，以及多 PCE 管理 — 不需部署 agent，也不直接接觸 workload。

---

## 快速開始

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json   # 編輯 api.url / api.key / api.secret
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 常駐 daemon + Web GUI 於 https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

首次登入：`illumio` / `illumio`（首次使用會強制變更密碼）。

隔離環境安裝、systemd/NSSM 服務設定，以及 Windows 部署，請見 **[docs/getting-started.md](docs/getting-started.md)**。

---

## 文件

所有文件在 [docs/](docs/)。從 [INDEX_zh.md](docs/INDEX_zh.md) 開始。

English: [INDEX.md](docs/INDEX.md).

---

## 重點功能

- **四種執行模式** — 背景 daemon、互動式 CLI、獨立 Web GUI，或常駐監控 + GUI（`--monitor-gui`）
- **24 條自動化資安規則** — B 系列（勒索軟體/覆蓋率）、L 系列（橫向移動/外洩）、R 系列（Draft Policy 對齊）
- **15 模組 Traffic 報表** + Audit、Policy Usage、VEN Status 報表；輸出格式支援 HTML / CSV / PDF / XLSX
- **SIEM 轉送器** — CEF、JSON、RFC5424 syslog、Splunk HEC，支援 UDP/TCP/TLS/HTTPS，每目的地獨立 DLQ
- **完整多語系** — CLI、Web GUI、報表、警示全面支援英文與繁體中文

---

## 專案結構

```text
illumio-ops/
├── illumio-ops.py          # 進入點 — dispatcher 視 argv 路由 click subcommand 或 legacy argparse
├── src/
│   ├── main.py                 # 舊版 argparse 路徑（--monitor / --gui / --report）；新 flag 已移至 src/cli
│   ├── api_client.py           # PCE REST API（async job、native filter、O(1) streaming）
│   ├── api/                    # PCE API helpers（async jobs、labels、traffic queries）
│   ├── analyzer.py             # 規則引擎（flow matching、事件分析、狀態管理）
│   ├── cli/                    # Click subcommand + 共用 output / exit-code helper（root、monitor、gui_cmd、report、rule、workload、cache、siem、status、config、menus/）
│   ├── gui/                    # Flask Web GUI 套件 — shell + Blueprint routes（auth/admin/dashboard/events/reports/rules/rule_scheduler/actions/config）— 約 70 個 route
│   ├── config.py               # ConfigManager（Argon2id GUI 密碼、atomic write）
│   ├── reporter.py             # 多通道警示派送（SMTP、LINE、Webhook）
│   ├── i18n/                   # i18n 引擎（engine.py + JSON 資料）— EN/ZH_TW，約 2,200 個 string key
│   ├── events/                 # 事件 pipeline（catalog、normalize、dedup、throttle）
│   ├── report/                 # 報表引擎（15 個 traffic 模組 + audit + policy usage + R3 intelligence 模組）
│   ├── scheduler/              # 報表排程 cron 工作
│   ├── settings/               # 互動式設定 wizard（從 legacy settings.py 拆分）
│   ├── pce_cache/              # SQLite WAL 快取 + ingestor
│   ├── siem/                   # SIEM forwarder（CEF/JSON/Syslog、UDP/TCP/TLS/HEC）
│   ├── alerts/                 # 警示 plugin（mail、LINE、webhook）
│   ├── templates/              # Flask HTML templates（login、index）
│   └── static/                 # 內嵌字型（Space Grotesk / Inter / JetBrains Mono）、JS、CSS
├── config/                     # config.json、alerts.json、report_config.yaml、rule_schedules.json
├── docs/                       # EN + ZH_TW 文件
├── tests/                      # 約 178 個測試檔（~970 個 test）
├── deploy/                     # systemd（Ubuntu/RHEL）+ NSSM（Windows）服務設定
└── scripts/                    # 工具腳本（離線 bundle 建置、安裝/解除安裝、preflight）
```

---

## 部署注意事項 / Deployment Notes

> 稽核依據：`docs/security-audit-2026-05-22.md` L-11 至 L-14。

### L-11: Reverse Proxy

本服務未自動配置 Flask `ProxyFix`。如部署於 reverse proxy（nginx、Apache、Traefik）後方：

- 必須在啟動前設定 `ProxyFix` middleware，且只信任 1 個 hop。
- 否則 IP allowlist 將失效（所有來源顯示為 proxy 的 IP）。

範例（在 cheroot 伺服器啟動前，於 `src/gui/__init__.py` 加入）：

```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
```

### L-12: Telegram Alert Plugin — Token 洩漏風險

Telegram Bot API 將 token 嵌在 URL path（`https://api.telegram.org/bot<TOKEN>/sendMessage`）。在金融 / 國防 / 高敏感環境部署 Telegram alert plugin 時，**必須**採取下列其中一項措施：

- 禁止 forward proxy 或 WAF 將完整 URL path 寫入 access log。
- 使用 NoProxy direct 連線繞過企業代理。
- 改用 webhook 模式（雖然 webhook 仍會經過代理，但 URL 不含 token）。

Loguru log 已加入 Telegram token 正則屏蔽（commit T2.14），但無法保護中介網路設備。

### L-13: Server Header 指紋識別

cheroot 預設輸出 `Server: Cheroot/<version>` 響應 header，可被指紋識別。若稽核要求嚴格 strip：

- 在 reverse proxy 端以 `proxy_hide_header Server;`（nginx）或相應指令移除。
- 或自訂 cheroot WSGI middleware 移除 header（後續優化計畫）。

### L-14: 正式環境 Git 流程 — autoStash 與可重現性

`scripts/setup-prod-git.sh` 啟用 `git config merge.autoStash=true`，意味著 prod box 在 `git pull` 時可能**靜默 stash 未提交的本地編輯**，且不會發出警告。後果：

- prod box 與 `git tag` **可能不是 bit-for-bit reproducible**。
- 稽核時若要證明 prod 與某 release tag 完全一致，必須額外確認沒有 stashed changes：`git stash list` 必須為空。

**建議：** 每次正式部署完成後執行 `git stash list` 並確認為空。若正式環境需保證可重現性，請改用 `scripts/setup.sh` 而非 `setup-prod-git.sh`。

---

## 授權

本專案授權條款請見倉庫根目錄 `LICENSE` 檔案。
