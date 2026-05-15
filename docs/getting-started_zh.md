---
title: Getting Started
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - docs/Installation.md (legacy, audited)
  - docs/UPGRADE.md (legacy, audited)
  - requirements.txt
  - requirements-offline.txt
  - illumio-ops.py
  - deploy/illumio-ops.service
  - deploy/install_service.ps1
  - config/config.json.example
  - scripts/setup-prod-git.sh
  - python illumio-ops.py --help (output captured verbatim)
  - commit 31c1c48
related_docs:
  - INDEX.md
  - user-guide/dashboard.md
  - user-guide/multi-pce.md
  - user-guide/troubleshooting.md
---

> 🌐 [English](getting-started.md) | **[繁體中文](getting-started_zh.md)**
> 📍 [INDEX](INDEX.md) › 快速上手
> 🔍 最後驗證 **2026-05-15** 對 commit `31c1c48` — 詳見 frontmatter

# 快速上手

## illumio-ops 是什麼

illumio-ops 是針對 Illumio PCE 的無代理監控與自動化平台。
它透過 REST API 連接一台或多台 PCE — 不需要部署代理程式、不需要調整防火牆規則 —
並提供 Operator 儀表板、排程報表、告警規則、SIEM 轉發，以及政策 / 工作負載檢查，
全部整合於一個自架服務中。

## 先決條件

| 需求項目 | 說明 |
|---|---|
| **Python** | 3.10 以上（建議 3.12）。使用離線安裝包部署時不需要 — 安裝包內建 CPython 3.12。 |
| **PCE 存取** | 可透過 HTTPS 連線至 PCE（預設埠 `8443`），並持有 PCE API 金鑰（監控最低需 `read_only`；隔離操作需 `owner`）。 |
| **作業系統** | RHEL / Rocky Linux 8+、Ubuntu 22.04+、Debian 12+、Windows Server 2019+ / Windows 11。 |

> **如何建立 PCE API 金鑰**：PCE Web Console → **使用者選單 → My API Keys → Add**。

## 安裝

### 從原始碼（開發用）

適用於工作站，或可直接存取 PyPI 的主機。

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json
```

**Ubuntu 22.04+ / Debian 12+** — PEP 668 禁止直接 `pip install`，請使用虛擬環境：

```bash
sudo apt install python3-venv     # 若尚未安裝
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**RHEL / macOS / 其他系統**：

```bash
pip install -r requirements.txt
```

啟動 Web GUI：

```bash
python3 illumio-ops.py gui
```

> 每次開啟新的終端機視窗都需要重新啟用虛擬環境（`source venv/bin/activate`）。

### 離線安裝包（RHEL / Ubuntu / Windows）

適用於生產環境或隔離網路主機。安裝包內含可攜式 CPython 3.12 直譯器
及所有預先建置的 wheel — 目標主機不需要網路連線或系統 Python。

**建置安裝包**（在任何可連線網路的 Linux 或 WSL 機器上執行）：

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# 輸出：
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio-ops-<version>-offline-windows-x86_64.zip
```

> [!NOTE]
> 本儲存庫的 `dist/` 目錄不隨附預先建置的安裝包。
> 請在可連線的機器上執行 `build_offline_bundle.sh` 來產生安裝包。

**Linux（RHEL / Ubuntu）— 首次安裝**：

```bash
tar xzf illumio-ops-<version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<version>-offline-linux-x86_64

bash ./preflight.sh                   # 任何檢查失敗則退出碼為 1
sudo ./install.sh                     # 安裝至 /opt/illumio-ops，並註冊 systemd 服務單元
sudo nano /opt/illumio-ops/config/config.json   # 填入 PCE 憑證

sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops     # 應顯示：Active: active (running)
```

**Windows Server / Windows 11 — 首次安裝**（以系統管理員身分執行 PowerShell）：

```powershell
Expand-Archive illumio-ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<version>-offline-windows-x86_64

.\preflight.ps1                       # 任何檢查失敗則退出碼為 1
.\install.ps1                         # 安裝至 C:\illumio-ops，並註冊 IllumioOps 服務
notepad C:\illumio-ops\config\config.json       # 填入 PCE 憑證

Get-Service IllumioOps                # 應顯示：Running
```

### systemd / NSSM 服務

服務定義檔位於 `deploy/`：

| 檔案 | 用途 |
|---|---|
| `deploy/illumio-ops.service` | Linux systemd 服務單元（安裝至 `/opt/illumio-ops`） |
| `deploy/install_service.ps1` | Windows NSSM 安裝腳本（`IllumioOps` 服務） |

離線安裝的 `install.sh` / `install.ps1` 會自動複製並設定這些檔案。
若需自訂安裝路徑，可對 `install.sh` 傳入 `--install-root <path>` —
systemd 服務單元將自動更新為指向該路徑。

systemd 服務單元的啟動設定：

```text
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py \
          --monitor-gui --interval 10
User=illumio-ops
Restart=always
```

在 Windows 上，NSSM 已隨附於 `deploy\nssm.exe`，`install.ps1` 會自動取用。

## 首次連線 PCE

編輯 `config/config.json`（服務安裝則為 `/opt/illumio-ops/config/config.json`），
填入 `api` 區塊的欄位：

```json
"api": {
    "url": "https://pce.example.com:8443",
    "org_id": "1",
    "key": "api_xxxxxxxxxxxxxx",
    "secret": "your-api-secret-here",
    "verify_ssl": true
}
```

如需連線多台 PCE，請在 `pce_profiles` 陣列中新增條目，並設定 `active_pce_id`。
完整多 PCE 設定流程請參閱 [Multi-PCE](user-guide/multi-pce.md)。

**驗證連線**，執行 status 指令：

```bash
python3 illumio-ops.py status
```

連線成功時會顯示 PCE 可達性與 daemon 狀態。

## 首次登入（安全）

首次啟動時，應用程式會將一次性自動生成的密碼輸出至 `stderr`：

```text
[illumio-ops] Initial credentials — username: illumio  password: <generated>
Sign in once with these credentials, then change the password at the Settings page.
```

預設使用者名稱為 `illumio`（可透過 `config.json` 的 `web_gui.username` 調整）。
系統強制執行 `must_change_password` 門檻：在密碼變更前，GUI 對所有已驗證請求回傳
HTTP 423，因此無法跳過此步驟。

首次登入後請立即至 **Settings → Security** 變更密碼。

## 升級

**原始碼 / 開發版安裝**：

```bash
# （建議在生產部署機器上執行，一次性設定）
bash scripts/setup-prod-git.sh      # 啟用 merge.autoStash

git pull
source venv/bin/activate            # 若使用虛擬環境
pip install -r requirements.txt
# 重新啟動程序 / 服務
```

`scripts/setup-prod-git.sh` 為本地儲存庫啟用 `merge.autoStash`，
讓 `git pull` 在有本地修改時自動 stash 再 pop，而不是中止並報
「would be overwritten by merge」。每台部署機器在初次 clone 後執行一次即可。

**離線安裝包** — 升級時安裝程式會自動保留設定檔：

```bash
# Linux
sudo systemctl stop illumio-ops
tar xzf illumio-ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<new-version>-offline-linux-x86_64
sudo ./install.sh                   # config.json、alerts.json、rule_schedules.json 均保留
sudo systemctl start illumio-ops
```

```powershell
# Windows
Stop-Service IllumioOps
Expand-Archive illumio-ops-<new-version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<new-version>-offline-windows-x86_64
.\install.ps1
Get-Service IllumioOps
```

升級後保留的檔案：`config/config.json`、`config/alerts.json`、
`config/rule_schedules.json`、`logs/`、`data/pce_cache.sqlite`。

## 驗證安裝成功

在瀏覽器開啟儀表板：

```text
https://localhost:5001
```

GUI 預設使用 HTTPS（首次啟動時自動生成自簽憑證）。
首次存取時請接受憑證警告。

執行以下指令確認 daemon 與 PCE 連線狀態：

```bash
python3 illumio-ops.py status
```

應用程式日誌寫入安裝根目錄下的 `logs/`：
- 原始碼安裝：`<project-dir>/logs/`
- 離線安裝包（Linux）：`/opt/illumio-ops/logs/`
- 離線安裝包（Windows）：`C:\illumio-ops\logs\`

查看 systemd 服務的即時日誌：

```bash
journalctl -u illumio-ops -f
```

> [!NOTE]
> 本應用程式沒有專用的 `/health` HTTP 端點。PCE 連線健康狀態
> 透過 `/api/status` 提供，並顯示於儀表板 KPI 卡片上。

## 下一步

- [Dashboard](user-guide/dashboard.md) — 了解 KPI 卡片、流量查詢與告警
- [Multi-PCE](user-guide/multi-pce.md) — 連接多台 PCE
- [Troubleshooting](user-guide/troubleshooting.md) — 首次執行發生問題時的排查指南

---
## 相關文件
- [INDEX](INDEX.md) — 完整文件地圖
- [Dashboard](user-guide/dashboard.md) — 安裝後第一個查看的地方
- [Multi-PCE](user-guide/multi-pce.md) — 連接多台 PCE
- [Troubleshooting](user-guide/troubleshooting.md) — 首次執行發生問題時的排查指南
