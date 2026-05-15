# illumio-ops

![Version](https://img.shields.io/badge/Version-v3.25.0--tracks--abcd-blue?style=flat-square)
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

## 授權

本專案授權條款請見倉庫根目錄 `LICENSE` 檔案。
