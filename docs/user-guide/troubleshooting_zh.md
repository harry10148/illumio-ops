---
title: Troubleshooting
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - docs/Troubleshooting.md (legacy, audited)
  - logs/
  - scripts/setup-prod-git.sh
  - commit 8dd14b7
related_docs:
  - ../getting-started.md
  - tls-and-certificates.md
  - siem-integration.md
  - reports.md
---

> **[繁體中文](troubleshooting_zh.md)** | **[English](troubleshooting.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 疑難排解
> 🔍 最後驗證日期 **2026-05-15**，對應 commit `8dd14b7` — 詳見 frontmatter

# 疑難排解

---

## 日誌 — 從哪裡看

所有日誌檔案位於安裝根目錄下的 `logs/`（生產環境套件為 `/opt/illumio-ops/logs/`）。

| 檔案 | 內容 | 輪替規則 |
|---|---|---|
| `logs/illumio_ops.log` | 人類可讀的純文字日誌（≥ 設定最低等級的所有記錄） | 10 MB，保留 10 個備份 |
| `logs/illumio_ops.json.log` | 結構化 JSON sink — 每行一筆記錄；`logging.json_sink: true` 時啟用，適合送往 Splunk / Elastic / Loki | 與文字日誌相同 |
| `logs/state.json` | 報告排程與規則冷卻時間的執行階段狀態 | 不輪替 — 勿手動編輯 |

**變更日誌等級：**

```bash
# 在 config.json 中設定：
"logging": { "level": "DEBUG", "retention": 10, "rotation": "10 MB" }
```

有效等級（詳細程度遞增）：`ERROR`、`WARNING`、`INFO`、`DEBUG`。

**快速追蹤日誌（生產 systemd）：**

```bash
sudo journalctl -u illumio-ops -f -n 100
# 或直接讀取檔案：
tail -f /opt/illumio-ops/logs/illumio_ops.log
```

---

## 常見安裝問題

### Ubuntu/Debian 上的 `externally-managed-environment` pip 錯誤

- **症狀：** `pip install` 失敗，錯誤訊息為 `error: externally-managed-environment`。
- **原因：** Ubuntu 22.04+ / Debian 12+ 強制執行 PEP 668 — 封鎖系統層級的直接 pip 安裝。
- **解決方式：** 建立並啟用虛擬環境：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

每次開啟新終端機後，執行應用程式前都必須重新啟用 venv（`source venv/bin/activate`）。

### 模組缺失錯誤 / `--monitor` 無法啟動

- **症狀：** 啟動時出現 `ModuleNotFoundError`，或 GUI 無法開啟。
- **原因：** 依賴套件未安裝在目前使用的直譯器下 — 常見於 `$PATH` 中使用了錯誤的 Python。
- **解決方式（生產離線套件）：**

```bash
/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/scripts/verify_deps.py
# 若回報缺少套件，重新執行安裝程式：
sudo ./install.sh
```

- **解決方式（開發環境）：** 在已啟用的 venv 中執行 `pip install -r requirements.txt`。

### 啟動時出現 `TypeError: unsupported operand type(s) for |`

- **症狀：** Python 在型別提示的 `|` 運算子處拋出 `TypeError`。
- **原因：** 目前的直譯器版本早於 Python 3.10（聯集型別語法 `X | Y` 需要 3.10+）。
- **解決方式：** 生產環境使用套件內建的 CPython 3.12；開發環境請使用 Python 3.10+ 重建 venv。

```bash
python3 --version   # 確認版本 ≥ 3.10
```

---

## PCE 連線失敗

### 驗證失敗 / API 金鑰被拒

- **症狀：** 儀表板 **PCE Status** 小工具顯示「auth failed」；日誌包含 `401` 或 `403`。
- **原因：** `config.json` 中的 `api.key` 或 `api.secret` 錯誤，或金鑰已在 PCE Web Console 中撤銷。
- **解決方式：** 在 PCE Web Console（右上角使用者選單 → **My API Keys** → **Add**）重新生成 API 金鑰，然後更新 `config.json`：

```json
"api": {
  "url": "https://pce.example.com:8443",
  "key": "<PCE 的 auth_username>",
  "secret": "<PCE 的 secret>",
  "org_id": "1",
  "verify_ssl": true
}
```

更新後重啟服務：`sudo systemctl restart illumio-ops`。

### 連線被拒 / 網路不可達

- **症狀：** 日誌顯示 `ConnectionRefusedError` 或 `TimeoutError`，無法連至 PCE URL。
- **原因：** 網路防火牆、連接埠錯誤，或 PCE 服務停止。
- **解決方式：**

```bash
# 從執行 illumio-ops 的主機測試連通性：
curl -v --max-time 5 https://pce.example.com:8443/api/v2/health
```

確認此主機與 PCE 之間的連接埠 8443（或設定的連接埠）已開放。

### 實驗室 PCE 的 SSL 驗證錯誤

- **症狀：** 日誌中出現 `SSLCertVerificationError`；PCE 使用自簽憑證。
- **原因：** `api.verify_ssl` 預設為 `true`。
- **解決方式：** 實驗室環境請在 `config.json` 中設定 `"verify_ssl": false`。生產環境請改為安裝 CA 套件 — 參閱 [TLS 與憑證](tls-and-certificates_zh.md)。

---

## TLS / 憑證不一致

完整的憑證管理流程（自簽、ACME/Let's Encrypt、自訂 CA）請參閱 **[TLS 與憑證](tls-and-certificates_zh.md)**。

### 瀏覽器顯示憑證警告

- **症狀：** 瀏覽器顯示「您的連線不安全」/ `NET::ERR_CERT_AUTHORITY_INVALID`。
- **原因：** 使用自簽憑證 — 新安裝時的預期行為。
- **解決方式：** 內部使用可接受瀏覽器警告，或透過 **設定 → TLS** 面板（GUI）或 `illumio-ops tls` CLI 佈建由 CA 簽發的憑證。

### 憑證過期

- **症狀：** 日誌行：`TLS: certificate expires in -N days`。
- **原因：** 自動更新已停用，或憑證更新靜默失敗。
- **解決方式：**

```bash
illumio-ops tls renew
sudo systemctl restart illumio-ops
```

在設定 → TLS → **自動更新於啟動前到期時** 啟用自動更新。

### SIEM TLS 目的地：握手失敗

- **症狀：** SIEM 分派日誌中出現 `SSL: CERTIFICATE_VERIFY_FAILED`。
- **原因：** SIEM 伺服器使用系統套件不信任的私有 CA 憑證。
- **解決方式：** 在 SIEM 目的地設定中指定 `ca_bundle` 路徑：

```json
"siem": {
  "destinations": [
    { "type": "syslog_tls", "host": "siem.internal", "port": 6514,
      "tls_verify": true, "ca_bundle": "/etc/ssl/certs/internal-ca.pem" }
  ]
}
```

實驗室環境可設定 `"tls_verify": false`（會寫入警告日誌）。

---

## 報告無法產生

### 空報告 / 無資料

- **症狀：** 報告執行完成但無錯誤，所有表格卻是空的或計數為零。
- **原因：** 快取中所選時間窗口無資料，或窗口太窄。
- **解決方式：**

```bash
illumio-ops cache backfill --source events --since 2026-01-01
illumio-ops cache backfill --source traffic --since 2026-01-01
```

然後用更寬的 `--since` / `--until` 範圍重新產生報告。

### `mod_change_impact` 顯示 `skipped: no_previous_snapshot`

- **症狀：** 首次執行時，變更影響分析區塊為空白。
- **原因：** 沒有先前的快照可供比較。
- **解決方式：** 在首次執行後再產生一次報告；快照保留 `report.snapshot_retention_days`（預設 30）天。

### PDF 顯示方框而非 CJK 字元

- **症狀：** HTML 報告顯示正確，但 PDF 報告中中文字元顯示為空白方框。
- **原因：** 主機上找不到 CJK 字型，`reportlab` 無法渲染。
- **解決方式：**

```bash
# Debian/Ubuntu
sudo apt install fonts-noto-cjk
# RHEL/Rocky
sudo dnf install google-noto-cjk-fonts
```

安裝字型後重新產生報告。若 PDF CJK 輸出仍有問題，建議改用 `--format html`。

### Policy Usage 報告顯示 0 次命中

- **症狀：** Policy Usage 區塊顯示零次規則命中，即使存在流量記錄。
- **原因：** 查詢只包含已佈建（啟用）的規則；草稿規則依設計不納入。
- **解決方式：** 執行報告前先在 PCE Console 中佈建草稿規則。

---

## SIEM 目的地未收到事件

### 測試事件立即失敗

```bash
illumio-ops siem test <目的地名稱>
```

檢查輸出中的具體錯誤。常見原因：

| 錯誤 | 原因 | 解決方式 |
|---|---|---|
| `Connection refused` | SIEM 連接埠錯誤或監聽器未啟動 | 確認 SIEM 接收連接埠，並確認 TCP/UDP 監聽器已啟用 |
| `Timed out` | illumio-ops 主機與 SIEM 之間有防火牆阻擋 | 開放所需連接埠；以 `nc -zv <host> <port>` 測試 |
| `SSL: CERTIFICATE_VERIFY_FAILED` | TLS 傳輸使用不受信任的 CA | 參閱上方 [TLS / 憑證不一致](#tls--憑證不一致) |
| 事件已送出但未出現 | 格式不符或 index/source type 設定錯誤 | 確認 SIEM 預期的格式（`syslog`、`cef`、`normalized_json`）與設定一致 |

### 日誌中出現 TCP 重連循環

- **症狀：** 日誌反覆出現 `TCP syslog connection lost, reconnecting`。
- **原因：** 網路中斷或 SIEM 監聽器重啟；傳輸層會自動重連。
- **解決方式：** 這是預期的暫時性行為。若持續發生，請檢查網路穩定性與 SIEM 監聽器健康狀態。

### UDP 事件被靜默丟棄

- **症狀：** UDP 目的地無錯誤，但 SIEM 未收到任何事件。
- **原因：** UDP 無交付保證；封包在壅塞的節點上會被靜默丟棄。
- **解決方式：** 改用 `syslog_tcp` 或 `syslog_tls` 以確保可靠交付。確認 SIEM UDP 監聽器已啟用並綁定至正確的網路介面。

---

## 儀表板顯示過期資料

### PCE 變更後 KPI 小工具仍顯示舊值

- **症狀：** 儀表板 KPI 反映的是上次執行的資料；重新整理瀏覽器無效。
- **原因：** 儀表板讀取 `logs/latest_snapshot.json`；此檔案只在報告執行完成後才更新。
- **解決方式：**

```bash
illumio-ops report run --format snapshot
```

或在 GUI 中使用 **儀表板 → 重新整理**（觸發輕量快照更新，無需完整報告）。

### 快照檔案遺失

- **症狀：** 儀表板顯示「No snapshot available」橫幅。
- **原因：** 服務從未成功完成報告執行，或快照已被刪除。
- **解決方式：** 執行 `illumio-ops report run` 一次以產生初始快照。

### 切換語言後快照標籤仍為舊語言

- **症狀：** 在設定中切換語言後，部分 KPI 標籤仍維持舊語言。
- **原因：** 3.26.0 版本前產生的快照儲存的是已渲染文字而非 i18n 金鑰；舊資料無法重新翻譯。
- **解決方式：** 重新產生快照：`illumio-ops report run --format snapshot`。新快照包含 `label_key`，可立即反映目前語言設定。

---

## i18n / 語言切換問題

### 設定中的語言切換無效果

- **症狀：** 在設定 → 語言選擇「繁體中文」或「English」並儲存後，UI 無變化。
- **原因：** 瀏覽器可能快取了舊的翻譯套件。
- **解決方式：** 儲存語言設定後強制重新整理瀏覽器（`Ctrl+Shift+R` / `Cmd+Shift+R`）。

### UI 中出現 `[MISSING:some_key]`

- **症狀：** UI 標籤顯示為 `[MISSING:alert_rec_xyz]`。
- **原因：** 在 3.26.0 版本前建立的警報規則仍使用舊版純文字欄位，而非 i18n 金鑰。
- **解決方式：** 執行一次遷移腳本：

```bash
# Linux（生產環境）
sudo -u illumio-ops /opt/illumio-ops/python/bin/python3 \
    /opt/illumio-ops/scripts/migrate_rules_to_keys.py \
    --config /opt/illumio-ops/config/config.json --write
```

此腳本具冪等性，重複執行不會有副作用。

### 人性化時間戳記不翻譯

- **症狀：** 切換至 zh_TW 後，相對時間字串（例如「2 hours ago」）仍顯示為英文。
- **原因：** `humanize` 函式庫內部使用 `zh_HK` 對應繁體中文；若 locale 檔案遺失，會靜默回退至英文。
- **解決方式：** 確認 `humanize` 已從 `requirements.txt` 安裝（離線套件已內建）。若從原始碼執行，確認 `pip show humanize` 顯示版本 ≥ 4.0。

---

## 服務無法啟動（systemd）

### 快速診斷

```bash
sudo systemctl status illumio-ops -l
sudo journalctl -u illumio-ops -n 100 --no-pager
```

### 服務啟動後立即退出

| journal 中的症狀 | 可能原因 | 解決方式 |
|---|---|---|
| `FileNotFoundError: config.json` | 設定檔遺失或 `WorkingDirectory` 設定錯誤 | 確認 `/opt/illumio-ops/config/config.json` 存在且 `illumio-ops` 使用者可讀取 |
| `PermissionError: logs/` 或 `data/` | 服務使用者無法寫入日誌/資料目錄 | `sudo chown -R illumio-ops:illumio-ops /opt/illumio-ops/{data,logs,config}` |
| `ModuleNotFoundError` | Python 直譯器錯誤；依賴套件未安裝 | 確認 `ExecStart` 指向 `/opt/illumio-ops/python/bin/python3`，並執行 `verify_deps.py` |
| config 中出現 `json.JSONDecodeError` | `config.json` 有語法錯誤 | `python3 -m json.tool /opt/illumio-ops/config/config.json` 驗證；修正回報的錯誤 |
| `Address already in use` | 另一個程序佔用連接埠 5001（或設定的連接埠） | `ss -tlnp \| grep 5001`；停止衝突的程序或變更 config 中的 `settings.port` |

### 重啟前驗證設定

```bash
illumio-ops config validate
```

此命令在不啟動完整服務的情況下，檢查 JSON 語法、必填欄位與 PCE 連通性。

### 服務單元檔參考

生產環境單元檔位於 `/opt/illumio-ops/deploy/illumio-ops.service`。關鍵欄位：

```text
User=illumio-ops
WorkingDirectory=/opt/illumio-ops
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py --monitor-gui --interval 10
```

編輯單元檔後執行：`sudo systemctl daemon-reload && sudo systemctl restart illumio-ops`。

---

## 升級因 pull 衝突中止

### 症狀

升級期間（或自動更新腳本執行時）`git pull` 中止，並出現：

```text
error: Your local changes to the following files would be overwritten by merge:
    deploy/install_service.ps1
    scripts/install.sh
```

### 原因

部署機器上有人直接就地編輯了受版本控制的檔案（例如安裝腳本或 ingestor 模組）。Git 在 pull 時拒絕覆蓋本地修改。

### 解決方式 — 每台部署機器一次性設定

在初始 clone 後執行所提供的設定腳本**一次**。它會在本地啟用 `merge.autoStash` 和 `rebase.autoStash`，使 `git pull` 自動執行：暫存本地修改 → 快進更新 → 還原暫存：

```bash
bash scripts/setup-prod-git.sh
```

輸出確認設定已套用：

```text
merge.autoStash=true
rebase.autoStash=true
Done. git pull will now stash local edits, fast-forward, and pop.
```

此設定僅套用於該部署機器；不影響上游倉庫或其他 clone。

### 若 pull 已經失敗

```bash
git stash
git pull
git stash pop
```

在 `git stash pop` 輸出中確認衝突後再繼續升級。

---

## 如何提交有用的 bug 報告

提交 bug 報告或支援請求時，請包含以下資訊：

1. **應用程式版本與 commit：**

```bash
illumio-ops --version
git -C /opt/illumio-ops rev-parse HEAD
```

2. **相關日誌行** — 包含錯誤前後 20–50 行：

```bash
grep -n "ERROR\|Exception\|Traceback" /opt/illumio-ops/logs/illumio_ops.log | tail -30
```

3. **設定檔（已脫敏）：** 複製 `config.json` 並將 `api.key`、`api.secret` 及所有密碼替換為 `***REDACTED***`。

4. **系統資訊：**

```bash
uname -a
python3 --version
systemctl status illumio-ops --no-pager -l | head -20
```

5. **重現步驟** — 錯誤出現前所執行操作的編號清單。

6. **預期行為與實際行為** — 各一句話說明。

> **請勿在 bug 報告中包含**未脫敏的 API 金鑰、密碼或客戶識別資料。

---

## 相關文件

- [開始使用](../getting-started.md) — 初始設定問題
- [TLS 與憑證](tls-and-certificates_zh.md) — 憑證錯誤詳情
- [SIEM 整合](siem-integration_zh.md) — 目的地交付問題
- [報告](reports_zh.md) — 報告產生失敗
