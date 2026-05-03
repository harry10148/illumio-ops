# 安裝與必要條件

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
| Glossary | [Glossary.md](./Glossary.md) | [Glossary_zh.md](./Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
<!-- END:doc-map -->

---

## 1.1 系統需求
- **Python 3.8+**（已測試至 3.12）
- **網路存取：** 可透過 HTTPS 連線至 Illumio PCE（預設埠 `8443`）
- **正式部署：** 使用 `scripts/build_offline_bundle.sh` 建立自包含 tarball，內含可攜式 CPython 3.12 直譯器與所有預建 wheel；完整 Linux + Windows bundle 流程請見 [§1.2](#12-安裝)。
- **相依套件（鎖定於 `requirements.txt`）：** Flask + 安全中介層（`flask-wtf`、`flask-limiter`、`flask-talisman`、`flask-login`、`argon2-cffi`、`cryptography`）、報表 + 圖表（`pandas`、`pyyaml`、`openpyxl`、`reportlab`、`matplotlib`、`plotly`、`pygments`）、HTTP 客戶端（`requests`、`orjson`、`cachetools`）、設定驗證（`pydantic`）、排程 + 快取（`APScheduler`、`SQLAlchemy`）、結構化日誌（`loguru`）、CLI UX（`rich`、`questionary`、`click`、`humanize`）、生產級 WSGI server（`cheroot`）。離線 bundle 已為以上全部預建 wheel。
- **從原始碼開發：** `pip install -r requirements.txt`（Ubuntu 22.04+ / Debian 12+ 因 PEP 668 需改用 venv）。
- **PDF 匯出：** `reportlab` 預設包含（純 Python；不需 WeasyPrint / Pango / Cairo / GTK / GDK-PixBuf）。PDF 內容為靜態英文摘要；HTML 與 XLSX 是完整本地化內容的建議格式。

## 1.2 安裝

### Linux — 離線 Bundle（air-gapped 安裝）

當目標主機無法連線網際網路且無法存取 PyPI 或任何套件鏡像時，請使用此方式。Bundle 包含可攜式 CPython 3.12 直譯器及所有預建的 Python wheel — 目標主機上無需 `dnf`、`python3` 或網路連線。所有報表格式（HTML、XLSX、CSV、PDF）皆可使用；PDF 採用純 Python 的 ReportLab，已內含於 bundle。

##### 建置 bundle（在任何可連線網際網路的 Linux 或 WSL 機器上執行）

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# Output: dist/illumio_ops-<version>-offline-linux-x86_64.tar.gz
```

將 `.tar.gz` 傳輸至 air-gapped RHEL 主機（USB、SCP 至跳板機等）。

##### 首次安裝

```bash
tar xzf illumio_ops-<version>-offline-linux-x86_64.tar.gz
cd illumio_ops-<version>

# Validate the host environment before installing (exits 1 on any FAIL)
bash ./preflight.sh

# Install to /opt/illumio_ops, register systemd unit
sudo ./install.sh

# Fill in PCE API credentials (config.json was created from the example template)
sudo nano /opt/illumio_ops/config/config.json

# Enable and start the service
sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops      # should show Active: active (running)
```

##### 升級至新版本

`install.sh` 偵測到現有安裝時**絕不覆寫**：
- `config/config.json` — 您的 PCE API 憑證
- `config/rule_schedules.json` — 您的自訂規則排程

```bash
# 1. Stop the running service
sudo systemctl stop illumio-ops

# 2. Extract the new bundle (alongside the old one is fine)
tar xzf illumio_ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio_ops-<new-version>

# 3. Run install.sh — config.json, alerts.json (rules), and rule_schedules.json are preserved
sudo ./install.sh

# 4. Restart
sudo systemctl start illumio-ops
sudo systemctl status illumio-ops

# 5. Verify the new version
/opt/illumio_ops/python/bin/python3 /opt/illumio_ops/illumio-ops.py --version
```

> **若 `report_config.yaml` 已自訂：** 升級時會以 bundle 內附版本覆寫（可能新增分析參數）。升級前請先備份並在之後重新套用您的修改：
> ```bash
> sudo cp /opt/illumio_ops/config/report_config.yaml \
>         /opt/illumio_ops/config/report_config.yaml.bak
> # then run sudo ./install.sh, then merge your changes back
> ```

##### 驗證離線 bundle 完整性

```bash
# 確認所有必要的 production 套件都能在 bundle Python 下成功 import。
# Exit 0 = 全部 PASS，exit 1 = 有任何 FAIL — 啟用服務前可放心執行。
/opt/illumio_ops/python/bin/python3 \
    /opt/illumio_ops/scripts/verify_deps.py --offline-bundle
```

### Windows — 離線 Bundle（air-gapped 安裝）

**必要條件：** NSSM（Non-Sucking Service Manager）— 從 https://nssm.cc/download 下載，
並將 `nssm.exe` 放入系統 PATH 或 bundle 的 `deploy\` 目錄。

所有報表格式（HTML、XLSX、CSV、PDF）皆可使用；PDF 採用純 Python 的 ReportLab，已內含於 bundle。

##### 建置 bundle（在任何可連線網際網路的 Linux 或 WSL 機器上執行）

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# Output: dist/illumio_ops-<version>-offline-windows-x86_64.zip
```

將 `.zip` 傳輸至 air-gapped Windows 主機。

##### 首次安裝（以系統管理員身分執行 PowerShell）

```powershell
# Extract the bundle (built-in Windows 11 / Server 2019+)
Expand-Archive illumio_ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\

# Validate the host environment before installing (exits 1 on any FAIL)
cd C:\illumio_ops-<version>
.\preflight.ps1

# Install to C:\illumio_ops, register IllumioOps Windows service
.\install.ps1

# Fill in PCE API credentials
notepad C:\illumio_ops\config\config.json

# Verify the service is running
Get-Service IllumioOps
```

##### 升級至新版本（以系統管理員身分執行 PowerShell）

`install.ps1` 偵測到現有安裝時**絕不覆寫**
`config\config.json` 或 `config\rule_schedules.json`。

```powershell
# 1. Stop the service
Stop-Service IllumioOps

# 2. Extract new bundle
Expand-Archive illumio_ops-<new-version>-offline-windows-x86_64.zip -DestinationPath C:\

# 3. Run install.ps1 — config preserved automatically
cd C:\illumio_ops-<new-version>
.\install.ps1

# 4. Verify
Get-Service IllumioOps   # should show Running
```

> **若 `report_config.yaml` 已自訂：** 升級前先備份：
> ```powershell
> Copy-Item C:\illumio_ops\config\report_config.yaml `
>           C:\illumio_ops\config\report_config.yaml.bak
> # then run .\install.ps1, then merge changes back
> ```

### Ubuntu / Debian

現代 Ubuntu（22.04+）與 Debian（12+）實施 **PEP 668** — 直接 `pip install` 會被系統封鎖以保護系統 Python 環境。請使用虛擬環境：

```bash
# Install venv support if not already present
sudo apt install python3-venv

git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json

# Create and activate a virtual environment inside the project directory
python3 -m venv venv
source venv/bin/activate          # bash/zsh
# source venv/bin/activate.fish   # Fish shell

pip install -r requirements.txt
```

> **注意**：每次開啟新終端機視窗後，執行應用程式前需先重新啟動虛擬環境（`source venv/bin/activate`）。

### macOS / 其他（pip）

```bash
git clone <repo-url>
cd illumio-ops
pip install -r requirements.txt
```

### 自訂安裝根目錄

`install.sh` 支援 `--install-root` 以部署至非預設路徑：

```bash
sudo ./install.sh --install-root /opt/custom_path
```

systemd 單元檔案會自動更新以參照所選路徑。

### 升級時保留設定

升級時，`install.sh` 偵測到 `config/config.json` 後會跳過整個 `config/` 樹（原始碼中的備註：*「升級時保留所有 config/ — 絕不覆寫操作者擁有的檔案」*）。僅更新 `*.example` 範本，讓操作者可以 diff 確認新增的設定鍵：

```bash
diff /opt/illumio_ops/config/config.json.example \
     /opt/illumio_ops/config/config.json
```

### 解除安裝

安裝程式會將 `uninstall.sh` 放置於安裝根目錄中，使移除作業可自給自足。

```bash
# Preserve config/ (default — safe for re-install)
sudo /opt/illumio_ops/uninstall.sh

# Remove everything, including config/ (--purge)
sudo /opt/illumio_ops/uninstall.sh --purge

# When running from a bundle directory, or with a custom install root
sudo ./uninstall.sh --install-root /opt/custom_path
```

兩種方式均會停止並停用 `illumio-ops` systemd 單元、移除服務檔案，並刪除 `illumio_ops` 系統使用者。預設（不含 `--purge`）會保留 `config/` — 之後執行 `sudo rm -rf /opt/illumio_ops` 以完成完全移除。

## 1.3 設定檔（`config.json`）

複製範例設定檔後填入 PCE API 憑證：

```bash
cp config/config.json.example config/config.json
```

| 欄位 | 說明 | 範例 |
|:---|:---|:---|
| `api.url` | PCE 主機名稱含連接埠 | `https://pce.lab.local:8443` |
| `api.org_id` | 組織 ID | `"1"` |
| `api.key` | API Key 使用者名稱 | `"api_1a2b3c4d5e6f"` |
| `api.secret` | API Key 密鑰 | `"your-secret-here"` |
| `api.verify_ssl` | SSL 憑證驗證 | `true` 或 `false` |

> **如何取得 API Key**：在 PCE 網頁主控台點選 **使用者選單 → My API Keys → Add**。選擇適當角色（監控最低需 `read_only`，隔離操作需 `owner`）。


## 1.4 Shell Tab Completion（bash）

`scripts/illumio-ops-completion.bash` 提供 Click 生成的 `illumio-ops` 子命令與選項補全。

| 情境 | 命令 |
|---|---|
| 目前 shell 暫時試用（開發） | `source scripts/illumio-ops-completion.bash` |
| Linux 全域安裝 | `sudo cp scripts/illumio-ops-completion.bash /etc/bash_completion.d/illumio-ops` |
| RPM / 離線 bundle 安裝 | `scripts/install.sh` 已自動安裝，無需操作 |
| 驗證 | 鍵入 `illumio-ops <Tab><Tab>` 確認出現子命令建議 |

補全腳本以 kebab-case 進入點（`illumio-ops`）為目標，需要進入點位於 `PATH`（例如離線 bundle 安裝後位於 `/opt/illumio_ops/illumio-ops.py`）；直接以 `python illumio-ops.py` 啟動時 bash completion 不會被呼叫。

zsh / fish 請安裝對應的 `_CLICK_COMPLETION_BASH_SOURCE` 等價物，詳見 [Click 文件](https://click.palletsprojects.com/en/stable/shell-completion/)。


## 延伸閱讀

- [使用手冊](./User_Manual_zh.md) — 執行模式、規則、告警通道等
- [Architecture](./Architecture_zh.md) — 系統概觀、模組地圖、PCE 快取、REST API 手冊
- [README](../README_zh.md) — 專案入口與快速上手
