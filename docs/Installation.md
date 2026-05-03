# Installation & Prerequisites

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

## 1.1 System Requirements
- **Python 3.8+** (tested up to 3.12)
- **Network Access** to Illumio PCE (HTTPS, default port `8443`)
- **Production deployment:** use `scripts/build_offline_bundle.sh` to produce a self-contained tarball with a portable CPython 3.12 interpreter and all wheels pre-built; see [§1.2](#12-installation) for the full Linux + Windows bundle workflow.
- **Dependencies (pinned in `requirements.txt`):** Flask + security middleware (`flask-wtf`, `flask-limiter`, `flask-talisman`, `flask-login`, `argon2-cffi`, `cryptography`), reports + charts (`pandas`, `pyyaml`, `openpyxl`, `reportlab`, `matplotlib`, `plotly`, `pygments`), HTTP client (`requests`, `orjson`, `cachetools`), config validation (`pydantic`), scheduler + cache (`APScheduler`, `SQLAlchemy`), structured logging (`loguru`), CLI UX (`rich`, `questionary`, `click`, `humanize`), production WSGI server (`cheroot`). The offline bundle pre-builds wheels for all of these.
- **Development from source:** `pip install -r requirements.txt` (use a venv on Ubuntu 22.04+ / Debian 12+ due to PEP 668).
- **PDF export:** `reportlab` is included by default (pure Python; no WeasyPrint / Pango / Cairo / GTK / GDK-PixBuf required). PDF output is a static English summary; HTML and XLSX are the recommended formats for full localized content.

## 1.2 Installation

### Linux — Offline Bundle (air-gapped install)

Use this method when the target host has no internet access and cannot reach PyPI
or any package mirror. The bundle includes a portable CPython 3.12 interpreter and
all pre-built Python wheels — no `dnf`, no `python3`, no network required on the
target host. All report formats (HTML, XLSX, CSV, PDF) work; PDF uses pure-Python
ReportLab and ships in the bundle.

##### Build the bundle (on any internet-connected Linux or WSL machine)

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# Output: dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
```

Transfer the `.tar.gz` to the air-gapped RHEL host (USB, SCP to a jump host, etc.).

##### First-time installation

```bash
tar xzf illumio-ops-<version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<version>-offline-linux-x86_64

# Validate the host environment before installing (exits 1 on any FAIL)
bash ./preflight.sh

# Install to /opt/illumio-ops, register systemd unit
sudo ./install.sh

# Fill in PCE API credentials (config.json was created from the example template)
sudo nano /opt/illumio-ops/config/config.json

# Enable and start the service
sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops      # should show Active: active (running)
```

##### Upgrading to a new version

`install.sh` detects an existing installation and **never overwrites**:
- `config/config.json` — your PCE API credentials
- `config/rule_schedules.json` — your custom rule schedules

```bash
# 1. Stop the running service
sudo systemctl stop illumio-ops

# 2. Extract the new bundle (alongside the old one is fine)
tar xzf illumio-ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<new-version>-offline-linux-x86_64

# 3. Run install.sh — config.json, alerts.json (rules), and rule_schedules.json are preserved
sudo ./install.sh

# 4. Restart
sudo systemctl start illumio-ops
sudo systemctl status illumio-ops

# 5. Verify the new version
/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py --version
```

> **If `report_config.yaml` was customised:** the upgrade replaces it with the
> bundled version (which may add new analysis parameters). Back it up before
> upgrading and re-apply your changes afterwards:
> ```bash
> sudo cp /opt/illumio-ops/config/report_config.yaml \
>         /opt/illumio-ops/config/report_config.yaml.bak
> # then run sudo ./install.sh, then merge your changes back
> ```

##### Verify offline build integrity

```bash
# Confirm every required production package imports under the bundled Python.
# Exit 0 = all PASS, exit 1 = any FAIL — safe to run before enabling the service.
/opt/illumio-ops/python/bin/python3 \
    /opt/illumio-ops/scripts/verify_deps.py --offline-bundle
```

### Windows — Offline Bundle (air-gapped install)

NSSM (Non-Sucking Service Manager) is bundled at `deploy\nssm.exe`; the
service installer picks it up automatically. All report formats (HTML, XLSX,
CSV, PDF) work; PDF uses pure-Python ReportLab and ships in the bundle.

##### Build the bundle (on any internet-connected Linux or WSL machine)

```bash
git clone <repo-url>
cd illumio-ops
bash scripts/build_offline_bundle.sh
# Output: dist/illumio-ops-<version>-offline-windows-x86_64.zip
```

Transfer the `.zip` to the air-gapped Windows host.

##### First-time installation (run PowerShell as Administrator)

```powershell
# Extract the bundle (built-in Windows 11 / Server 2019+)
Expand-Archive illumio-ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\

# Validate the host environment before installing (exits 1 on any FAIL)
cd C:\illumio-ops-<version>-offline-windows-x86_64
.\preflight.ps1

# Install to C:\illumio-ops, register IllumioOps Windows service
.\install.ps1

# Fill in PCE API credentials
notepad C:\illumio-ops\config\config.json

# Verify the service is running
Get-Service IllumioOps
```

##### Upgrading to a new version (PowerShell as Administrator)

`install.ps1` detects an existing installation and **never overwrites**
`config\config.json` or `config\rule_schedules.json`.

```powershell
# 1. Stop the service
Stop-Service IllumioOps

# 2. Extract new bundle
Expand-Archive illumio-ops-<new-version>-offline-windows-x86_64.zip -DestinationPath C:\

# 3. Run install.ps1 — config preserved automatically
cd C:\illumio-ops-<new-version>-offline-windows-x86_64
.\install.ps1

# 4. Verify
Get-Service IllumioOps   # should show Running
```

> **If `report_config.yaml` was customised:** back it up before upgrading:
> ```powershell
> Copy-Item C:\illumio-ops\config\report_config.yaml `
>           C:\illumio-ops\config\report_config.yaml.bak
> # then run .\install.ps1, then merge changes back
> ```

### Ubuntu / Debian

Modern Ubuntu (22.04+) and Debian (12+) enforce **PEP 668** — direct `pip install` is blocked to protect the system Python. Use a virtual environment:

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

> **Note**: You must re-activate the venv (`source venv/bin/activate`) each time you open a new terminal session before running the application.

### macOS / Other (pip)

```bash
git clone <repo-url>
cd illumio-ops
pip install -r requirements.txt
```

### Custom install root

`install.sh` accepts `--install-root` to deploy to a non-default path:

```bash
sudo ./install.sh --install-root /opt/custom_path
```

The systemd unit file is updated automatically to reference the chosen path.

### Config preservation on upgrade

On upgrade, `install.sh` detects `config/config.json` and skips the entire `config/` tree (comment in source: *"Preserve all of config/ on upgrade — never overwrite operator-owned files"*). Only `*.example` templates are updated so operators can diff for new keys:

```bash
diff /opt/illumio-ops/config/config.json.example \
     /opt/illumio-ops/config/config.json
```

### Uninstall

The installer places `uninstall.sh` inside the install root so removal is self-contained.

```bash
# Preserve config/ (default — safe for re-install)
sudo /opt/illumio-ops/uninstall.sh

# Remove everything, including config/ (--purge)
sudo /opt/illumio-ops/uninstall.sh --purge

# When running from a bundle directory, or with a custom install root
sudo ./uninstall.sh --install-root /opt/custom_path
```

Both variants stop and disable the `illumio-ops` systemd unit, remove the service file, and delete the `illumio_ops` system user. The default (no `--purge`) preserves `config/` in place — run `sudo rm -rf /opt/illumio-ops` afterwards to complete a full removal.

## 1.3 Configuration (`config.json`)

Copy the example config and fill in your PCE API credentials:

```bash
cp config/config.json.example config/config.json
```

| Field | Description | Example |
|:---|:---|:---|
| `api.url` | PCE hostname with port | `https://pce.lab.local:8443` |
| `api.org_id` | Organization ID | `"1"` |
| `api.key` | API Key username | `"api_1a2b3c4d5e6f"` |
| `api.secret` | API Key secret | `"your-secret-here"` |
| `api.verify_ssl` | SSL certificate verification | `true` or `false` |

> **How to obtain an API Key**: In the PCE Web Console, navigate to **User Menu → My API Keys → Add**. Select the appropriate role (minimum: `read_only` for monitoring, `owner` for quarantine operations).


## 1.4 Shell Tab Completion (bash)

The `scripts/illumio-ops-completion.bash` file provides Click-generated completions for `illumio-ops` subcommands and option flags.

| Scenario | Command |
|---|---|
| Try it once for the current shell (development) | `source scripts/illumio-ops-completion.bash` |
| Install globally on Linux | `sudo cp scripts/illumio-ops-completion.bash /etc/bash_completion.d/illumio-ops` |
| RPM / offline-bundle install | Already installed by `scripts/install.sh` — nothing to do |
| Verify it works | Type `illumio-ops <Tab><Tab>` and confirm subcommand suggestions appear |

The completion script targets the kebab-case entry point (`illumio-ops`). It works only when the entry script is on `PATH` (e.g. via offline bundle install at `/opt/illumio-ops/illumio-ops.py`); for direct dev runs (`python illumio-ops.py`), bash completion is not invoked.

For zsh / fish, install the corresponding `_CLICK_COMPLETION_BASH_SOURCE` equivalent — see [Click documentation](https://click.palletsprojects.com/en/stable/shell-completion/).


## See also

- [User Manual](./User_Manual.md) — Execution modes, rules, alert channels, and more
- [Architecture](./Architecture.md) — System overview, module map, PCE Cache, REST API Cookbook
- [README](../README.md) — Project entry and Quickstart
