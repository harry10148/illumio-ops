---
title: 安裝與部署
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - scripts/install.sh
  - scripts/install.ps1
  - scripts/preflight.sh
  - scripts/preflight.ps1
  - scripts/uninstall.sh
  - scripts/build_offline_bundle.sh
  - deploy/illumio-ops.service
  - deploy/install_service.ps1
  - requirements.txt
  - src/__init__.py
  - src/cli/gui_cmd.py
  - illumio-ops.py
  - docs/getting-started_zh.md (legacy, audited)
---

# 安裝與部署

illumio-ops 是針對 Illumio PCE 的無代理（agentless）監控與自動化平台，只透過 REST API
連線一台或多台 PCE，不需要在受管端點部署代理程式。本文件涵蓋兩種安裝方式（從原始碼、
離線安裝包）、升級與移除。安裝完成後的設定細節見 configuration.md（設定參照）；
啟動後的故障排除見 troubleshooting.md（故障排除）。

## 系統需求

| 需求項目 | 說明 |
|---|---|
| **Python** | 從原始碼安裝時，需要 Python 3.10 以上（建議 3.12）。離線安裝包不需要系統 Python — 安裝包內建可攜式 **CPython 3.12**（python-build-standalone 發行版）。 |
| **PCE 存取** | 可透過 HTTPS 連線至 PCE（預設埠 `8443`），並持有 PCE API 金鑰（監控最低需 `read_only`；隔離操作需 `owner`）。 |
| **作業系統** | RHEL / Rocky Linux 8+、Ubuntu 22.04+、Debian 12+（glibc >= 2.17）；Windows Server 2019+ / Windows 11（PowerShell 5.1+）。 |
| **磁碟** | 離線安裝包：安裝根目錄所在磁碟至少 2 GB（Linux）／500 MB（Windows）可用空間。 |

> **如何建立 PCE API 金鑰**：PCE Web Console → **使用者選單 → My API Keys → Add**。

## 從原始碼安裝

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

啟動 Web GUI（預設埠 `5001`，見 `src/cli/gui_cmd.py`）：

```bash
python3 illumio-ops.py gui
```

> 每次開啟新的終端機視窗都需要重新啟用虛擬環境（`source venv/bin/activate`）。

## Offline bundle 安裝

適用於生產環境或隔離網路主機。安裝包內含可攜式 CPython 3.12 直譯器及所有預先建置的
wheel — 目標主機不需要網路連線或系統 Python。

### 建置安裝包

在任何可連線網路的 Linux 或 WSL 機器上執行 `build_offline_bundle.sh`：

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# 輸出：
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio-ops-<version>-offline-windows-x86_64.zip
```

本儲存庫的 `dist/` 目錄不隨附預先建置的安裝包，須自行在可連線的機器上產生。
`build_offline_bundle.sh` 會下載並以 SHA256 驗證 python-build-standalone 的
CPython 3.12 執行環境，同時交叉下載 Linux（manylinux）與 Windows（win_amd64）
兩組 wheel，因此單一 Linux/WSL 主機即可產出兩份安裝包。

### Linux（RHEL / Ubuntu）— 首次安裝

安裝前務必先跑 `preflight.sh`；它會檢查架構、glibc、systemd、磁碟空間、rsync、
安裝包完整性（`VERSION`、`python/`、`wheels/`、`app/`、`deploy/` 是否齊全）、
bundle 內建 Python 與 SQLite 版本、埠 `5001` 是否已被佔用，任何一項 FAIL 就回傳
非零 exit code：

```bash
tar xzf illumio-ops-<version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<version>-offline-linux-x86_64

bash ./preflight.sh                   # 任何檢查失敗則退出碼為 1
sudo ./install.sh                     # 安裝至 /opt/illumio-ops，並註冊 systemd 服務單元
sudo nano /opt/illumio-ops/config/config.json   # 填入 PCE 憑證

sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops     # 應顯示：Active: active (running)
```

`install.sh` 完成前會自動驗證：所有正式相依必須可 import
（`scripts/verify_deps.py --offline-bundle`），且 app 能回應
`illumio-ops.py --help`；任一檢查失敗即中止安裝並回傳非零 exit code。

安裝完成後會提供 `illumio-ops` CLI wrapper（位於 `/usr/local/bin/illumio-ops`）。
手動執行 CLI 操作時一律使用 wrapper（或 bundle 內建直譯器
`/opt/illumio-ops/python/bin/python3`）——舊發行版的系統 `python3` 連結的
SQLite 版本過舊（本應用需要 >= 3.35.0，`INSERT ... RETURNING` 語法所需），應用程式
會拒絕啟動。實際操作請以 `sudo` 執行——設定檔僅服務使用者可讀。

### Windows Server / Windows 11 — 首次安裝

以系統管理員身分執行 PowerShell：

```powershell
Expand-Archive illumio-ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<version>-offline-windows-x86_64

.\preflight.ps1                       # 任何檢查失敗則退出碼為 1
.\install.ps1                         # 安裝至 C:\illumio-ops，並註冊 IllumioOps 服務
notepad C:\illumio-ops\config\config.json       # 填入 PCE 憑證

Get-Service IllumioOps                # 應顯示：Running
```

`preflight.ps1` 檢查項目與 Linux 版對應：OS 版本（Windows 10 / Server 2019+）、
架構（AMD64）、PowerShell 版本（5.1+）、是否以系統管理員執行、NSSM 是否可用、
`C:\` 磁碟空間、安裝包完整性。`install.ps1` 會在註冊服務前先驗證安裝——所有正式
相依必須可 import（`scripts\verify_deps.py --offline-bundle`）；pip 或驗證失敗即
中止並回傳非零 exit code。

### systemd / NSSM 服務

服務定義檔位於 `deploy/`：

| 檔案 | 用途 |
|---|---|
| `deploy/illumio-ops.service` | Linux systemd 服務單元（安裝至 `/opt/illumio-ops`），啟動旗標為 `--monitor-gui --interval 10`（監控 daemon ＋ Web GUI 一併啟動）。 |
| `deploy/install_service.ps1` | Windows NSSM 安裝腳本，註冊 `IllumioOps` 服務，預設啟動旗標為 `--monitor --interval 10`（**不含** `--monitor-gui`；如需常駐 Web GUI，需另行以 `nssm set IllumioOps AppParameters` 調整參數，或改用 `python.exe illumio-ops.py gui` 手動啟動）。 |

離線安裝的 `install.sh` / `install.ps1` 會自動複製並設定這些檔案。若需自訂安裝路徑，
可對 `install.sh` 傳入 `--install-root <path>`，systemd 服務單元將自動更新為指向該
路徑；`install.ps1` 對應參數為 `-InstallRoot <path>`。

在 Windows 上，NSSM 已隨附於 `deploy\nssm.exe`（build 時由 `vendor/windows/nssm-2.24.zip`
解出），`install.ps1` 會自動取用，air-gapped 主機不需要另外下載。

## 首次連線與登入

編輯 `config/config.json`（服務安裝則為 `/opt/illumio-ops/config/config.json` 或
`C:\illumio-ops\config\config.json`），填入 `api` 區塊的欄位（完整鍵值說明見
configuration.md（設定參照））：

```json
"api": {
    "url": "https://pce.example.com:8443",
    "org_id": "1",
    "key": "api_xxxxxxxxxxxxxx",
    "secret": "your-api-secret-here",
    "verify_ssl": true
}
```

驗證連線：

```bash
python3 illumio-ops.py status
```

在瀏覽器開啟儀表板（`https://localhost:5001`，GUI 預設使用 HTTPS，首次啟動時自動
生成自簽憑證，首次存取請接受憑證警告），使用內建預設帳密登入（`illumio` /
`illumio`）。系統強制 `must_change_password` 門檻：密碼變更前，GUI 對所有已驗證
請求回傳 HTTP 423，無法跳過此步驟。首次登入後請立即至 **Settings → Security**
變更密碼。

## 升級

**原始碼 / 開發版安裝**：

```bash
git pull
source venv/bin/activate            # 若使用虛擬環境
pip install -r requirements.txt
# 重新啟動程序 / 服務
```

**離線安裝包**：

```bash
# Linux
sudo systemctl stop illumio-ops
tar xzf illumio-ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<new-version>-offline-linux-x86_64
sudo ./install.sh
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

`install.sh` / `install.ps1` 偵測到目標路徑已存在 `config/config.json`（或
`config\config.json`）即視為升級，並套用以下防呆：

1. **Downgrade 守衛**：拒絕安裝比已裝版本更舊的 bundle（比對 bundle `VERSION`
   與已裝 `src/__init__.py` 的 `__version__`；DB schema 遷移只能前進）。找不到
   版本字串時（例如先前以非 purge 方式移除過），退回比對 cache DB 的
   `PRAGMA user_version` 與本 bundle schema 認得的最高遷移版本，防止用舊 bundle
   蓋過已被較新版本遷移過的 DB。確有需要時分別以
   `sudo ./install.sh --allow-downgrade`（Linux）或
   `.\install.ps1 -AllowDowngrade`（Windows）覆寫。
2. **服務停機行為**：若服務正在執行中，安裝腳本會自動停止服務再覆寫檔案，避免
   新舊程序與新舊 site-packages 混用造成 torn state；安裝完成後需由操作者自行
   重新啟動（`sudo systemctl restart illumio-ops` 或 `Restart-Service IllumioOps`）。
3. Linux 端會還原 pristine 的 bundle 內建 Python runtime 並全量重裝 bundle 內的
   wheel（`rsync --delete`）——升級後機器上的相依版本必定與 bundle 一致，新版已
   移除的檔案也會被清掉。Windows 端以 Robocopy 排除 `config.json`、
   `alerts.json`、`rule_schedules.json` 三個操作者檔案後同步應用程式檔案。
4. 完成前自動驗證：所有正式相依必須可 import
   （`scripts/verify_deps.py --offline-bundle`），且 app 能回應
   `illumio-ops.py --help`（Linux）／pip 安裝與相依驗證成功（Windows）。任一
   檢查失敗即中止並回傳非零 exit code。

### 升級後保留的檔案

升級一律保留操作者擁有的狀態檔，不會被覆寫：

- `config/config.json`
- `config/alerts.json`
- `config/rule_schedules.json`
- `logs/`
- `data/pce_cache.sqlite`（cache DB；schema 於服務下次啟動時自動遷移）

Linux 版另外只更新 `*.example` 範本檔（`config.json.example` 等），方便操作者用
`diff` 比對新版有無新增設定鍵；不會動到操作者自己的 `config.json`。

## 移除

**Linux**：

```bash
sudo /opt/illumio-ops/uninstall.sh            # 保留 config/ 與 data/
sudo /opt/illumio-ops/uninstall.sh --purge    # 全部移除
```

`uninstall.sh` 會先停止並停用 systemd 服務、移除服務單元檔與 CLI wrapper，接著
預設只刪除 `config/` 與 `data/` 以外的內容（保留設定檔與 cache DB，供之後重新安裝
沿用）；加上 `--purge` 才會整個安裝目錄一併刪除。

**Windows**：

```powershell
.\install.ps1 -Action uninstall               # 保留 config\ 與 data\
.\install.ps1 -Action uninstall -Purge        # 全部移除
```

行為與 Linux 對應：先移除 NSSM 服務，預設保留 `config\` 與 `data\`，加上 `-Purge`
才整個安裝目錄一併刪除。

## 下一步

- configuration.md（設定參照）— config.json 各區塊鍵值說明
- troubleshooting.md（故障排除）— 服務起不來、PCE 連不上、GUI 埠衝突等症狀導向排錯
- [architecture.md](../handover/architecture.md) — 架構導覽與模組地圖
