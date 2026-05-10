# 升級指南

> [English](UPGRADE.md) | [繁體中文](UPGRADE_zh.md)

本頁說明如何就地升級既有的 illumio-ops 安裝。若是全新安裝,請參考 `README_zh.md` Quick Start。

## TL;DR

```bash
sudo ./install.sh                          # Linux
.\install.ps1 -Action install              # Windows
```

`install.sh` 與 `install.ps1` 會自動偵測 `$INSTALL_ROOT`(Linux 預設 `/opt/illumio-ops`,Windows 預設 `C:\illumio-ops`)是否已有安裝,並保留 operator 的狀態檔。若你裝在自訂路徑,Linux 用 `--install-root /opt/custom`、Windows 用 `-InstallRoot D:\custom`。

## 升級時保留哪些檔案

判定方式:`<INSTALL_ROOT>/config/config.json` 存在即視為升級,安裝輸出會印 `IS_UPGRADE=true`。

升級時**保留**:

| 路徑 | 原因 |
|---|---|
| `config/config.json` | Operator 設定的憑證與設定 |
| `config/alerts.json` | Operator 設定的 alert / rules 狀態 |
| `config/rule_schedules.json` | 每個部署獨有的排程狀態 |
| `logs/` | 運行歷史 |
| `data/pce_cache.sqlite` | PCE cache 資料庫(若缺少會增量重建;路徑可由 `pce_cache.db_path` 設定覆寫)|

每次升級**覆蓋**:

| 路徑 | 原因 |
|---|---|
| `python/` | Bundle 內建的 Python runtime |
| `src/` | 應用程式碼 |
| `requirements-offline.txt` + wheels | 固定版本相依套件 |
| `config/*.example` | 範本檔(可 diff 線上 config 看新增了哪些 key)|

安裝完畢後,若 `IS_UPGRADE=true`,會執行 `pip install --no-index --find-links wheels` 重新整理相依套件,然後重啟 systemd service(Linux)或 NSSM service(Windows)。

## 各版本的遷移步驟

遷移腳本放在 `scripts/`,皆 idempotent(可重複執行,不會重複作用)。

### 3.26.0 — i18n architecture

`config/alerts.json` 內的 rule 在舊版會存「已渲染」的 description / recommendation 文字。3.26.0 改存 `desc_key` / `rec_key`,讓語系切換立即生效。安裝程式**不會自動遷移**,升級後請手動執行一次:

```bash
# Linux
sudo -u illumio-ops /opt/illumio-ops/python/bin/python3 \
    /opt/illumio-ops/scripts/migrate_rules_to_keys.py \
    --config /opt/illumio-ops/config/config.json --write
```

```powershell
# Windows
& C:\illumio-ops\python\python.exe `
    C:\illumio-ops\scripts\migrate_rules_to_keys.py `
    --config C:\illumio-ops\config\config.json -Write
```

未含 `desc_key` 的舊 rule 仍會運作 — loader 會 fallback 到 `[MISSING:*]` 標記,直到你遷移完。所有 rule 都轉成新格式後,再執行此腳本不會做任何事(no-op)。

### 更早的版本

沒有強制要做的遷移。

## Rollback(回退)

升級時只替換 `python/` 與 `src/`。回退步驟:

1. 停服務:`sudo systemctl stop illumio-ops`(Linux)或 `nssm stop illumio-ops`(Windows)。
2. 從舊 bundle 還原 `python/` 與 `src/`(把舊版 offline tarball/zip 解壓覆蓋到 `$INSTALL_ROOT`)。
3. **不要**還原 `config/` — 你升級後的 `config.json` 對舊版程式碼是向前相容的(舊版會略過不認識的 key,例如 3.26.0+ 新增的 `web_gui.session_lifetime_seconds`)。
4. 重啟服務。

若你跑過遷移腳本(例如 `migrate_rules_to_keys.py`),它會就地改 `config/alerts.json`。舊版程式碼讀新版 `desc_key`/`rec_key` 欄位有 fallback 處理,所以已遷移的 rule 不需要額外 rollback。

## 升級前檢查

升級前可對 offline bundle 跑 preflight:

```bash
bash scripts/preflight.sh --install-root /opt/illumio-ops
```

它會明確顯示 `UPGRADE` 警告(若偵測到既有安裝),並檢查磁碟空間、glibc 版本、Port 5001 可用性,以及 bundle 完整性。

## 相關文件

- `CHANGELOG.md` — 各版本對使用者可見的變動
- `scripts/install.sh` / `scripts/install.ps1` — 實際安裝邏輯
- `scripts/preflight.sh` — 升級前環境檢查
