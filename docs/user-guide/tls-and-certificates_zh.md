---
title: TLS and Certificates
audience: [operator, security]
last_verified: 2026-05-15
verified_against:
  - src/gui/routes/config.py
  - src/gui/_helpers.py
  - src/static/js/settings.js
  - src/config/ (models)
  - commit 86d550e
  - commit c089e58
  - commit 7baf6de
  - commit d056a51
related_docs:
  - multi-pce.md
  - troubleshooting.md
  - siem-integration.md
  - ../contributing/release-process.md
---

> [English](tls-and-certificates.md) | **[繁體中文](tls-and-certificates_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › TLS 與憑證
> 🔍 最後驗證 **2026-05-15** 對 commit `d056a51` — 詳見 frontmatter

# TLS 與憑證

本頁說明 **illumio-ops Web GUI**（Flask 伺服器本身）的 HTTPS 設定，以及
illumio-ops 在呼叫 **PCE API** 時如何驗證 PCE 的 TLS 憑證。
這是兩組不同的信任關係。

---

## 預設自簽憑證

當 `web_gui.tls.enabled` 為 `true` 且 `web_gui.tls.self_signed` 為 `true`
（原廠預設），illumio-ops 會在**第一次啟動**時自動產生自簽憑證（若尚未存在）。

| 項目 | 值 |
|---|---|
| 憑證路徑 | `config/tls/self_signed.pem` |
| 私鑰路徑 | `config/tls/self_signed_key.pem`（同目錄） |
| 有效期 | 5 年 |
| 演算法 | RSA（預設） |

UI 透過 `GET /api/tls/status` 反映目前狀態。若尚未找到憑證檔案，狀態面板會顯示：

> _"No certificate found. It will be generated on next server start."_

**config.json 預設值（web_gui.tls 區塊）：**

```json
"tls": {
  "enabled": true,
  "self_signed": true,
  "cert_file": "",
  "key_file": "",
  "auto_renew": true,
  "auto_renew_days": 30
}
```

若要**停用 HTTPS**（例如放在終止 TLS 的反向代理後方），請將 `"enabled"` 設為 `false`。

---

## 產生 CSR

> 驗證依據：commit `86d550e` — `src/gui/_helpers.py (_generate_csr)`、
> `src/gui/routes/config.py (POST /api/tls/generate-csr)`、`src/static/js/settings.js`。

在正式環境部署時，請使用此流程取得 CA 簽署憑證。

### 操作步驟

1. 前往 **設定 → TLS / HTTPS**。
2. 取消勾選 **「使用自簽憑證」**，展開自訂憑證面板。
3. 展開 **「產生 CSR（憑證簽署請求）」**。
4. 填入以下欄位：

   | 欄位 | 必填 | 說明 |
   |---|---|---|
   | Common Name (CN) | 是 | 瀏覽器使用的 FQDN，例如 `ops.example.com` |
   | Organization (O) | 否 | 法人機構名稱 |
   | Organizational Unit (OU) | 否 | 部門 / 團隊 |
   | Country (C) | 否 | 2 字母 ISO 國碼，例如 `TW` |
   | SAN DNS | 否 | 額外 DNS 名稱（逗號分隔） |
   | SAN IP | 否 | IP SAN（逗號分隔） |
   | 金鑰演算法 | — | RSA-2048 或 ECDSA-P256 |

5. 點擊 **「產生 CSR」**。
6. 後端呼叫 `POST /api/tls/generate-csr`，執行：
   - 產生新的私鑰（`RSA-2048` 或 `ECDSA-P256`）。
   - 以 `0o600` 權限寫入私鑰至 `config/tls/csr_key.pem`。
   - 在回應本體中回傳 CSR PEM。
7. 複製 CSR PEM，送交 CA 簽署。
8. 點擊「產生 CSR」後，**「匯入 CA 簽署憑證」** 面板會自動展開（commit `c089e58`），
   引導您進行下一步。

> **安全注意：** `config/tls/csr_key.pem` 不得離開伺服器。
> 只有 CSR（非私鑰）需要送交 CA。

---

## 匯入已簽署憑證

> 驗證依據：commit `86d550e` — `POST /api/tls/import-cert`、
> `src/gui/_helpers.py (_import_signed_cert)`。

CA 回傳簽署憑證後：

1. 在 **設定 → TLS / HTTPS**，展開 **「匯入 CA 簽署憑證」**。
   （若剛完成 CSR 產生，此面板會自動開啟。）
2. 貼上完整憑證 PEM（包含 `-----BEGIN CERTIFICATE-----`）。
3. 點擊 **「匯入憑證」**。
4. 後端呼叫 `POST /api/tls/import-cert`，執行：
   - 解析 PEM 並對照儲存的 `config/tls/csr_key.pem` 驗證。
   - 成功後，將憑證寫入 `cert_file` 設定的路徑，並更新 `config.json` 的
     `cert_file` / `key_file` 指向新檔案。
5. UI 顯示：

   > _"Certificate imported. Restart the server to apply."_

6. 重新啟動 illumio-ops 以載入新憑證。

**若您有中間 / 鏈結憑證，** 請在貼上前將其串接於葉憑證之後，置於同一個 PEM 中。

---

## 憑證輪替

TLS 憑證的任何異動（自簽憑證更新或 CA 憑證匯入）都必須在**重新啟動伺服器**後才會生效。
任何憑證變更後，GUI 均會顯示提示橫幅：

> _"TLS settings saved. Restart the server to apply."_

### 自簽憑證自動更新

當 `web_gui.tls.auto_renew` 為 `true`（預設），illumio-ops 會在**每次啟動**時檢查
自簽憑證。若剩餘天數 ≤ `auto_renew_days`（預設 `30`），憑證會在伺服器開始接受請求前
自動重新產生。

### 手動更新

在 **設定 → TLS / HTTPS**，點擊 **「更新憑證」**。確認對話框會提示需要重新啟動。
此功能僅適用於自簽憑證（更新 CA 簽署憑證須重新執行 CSR 流程）。

### CA 簽署憑證輪替

1. 產生新的 CSR（或若使用相同金鑰，可直接提供新憑證）。
2. 透過匯入面板匯入新的已簽署 PEM。
3. 重新啟動伺服器。

所有憑證變更皆需要完整的程序重啟，不支援在程序內熱重載。

---

## 剩餘天數顯示

> 驗證依據：commit `7baf6de` — `src/static/js/settings.js` 中的 `humanizeDays()`，
> i18n 鍵 `gui_tls_days_*` 於 `src/i18n_en.json` 和 `src/i18n_zh_TW.json`。

**設定 → TLS / HTTPS** 狀態面板以人性化字串顯示憑證到期時間，而非原始天數。

**格式規則（中文）：**

| 範圍 | 格式 |
|---|---|
| ≥ 1 年 | `N 天（約 Y 年 M 個月）` |
| < 1 年 | `N 天（約 M 個月）` |

**範例：**

```
1804 天（約 4 年 11 個月）
 365 天（約 12 個月）
  45 天（約 1 個月）
```

`settings.js` 中的 `humanizeDays(n)` 透過 i18n 鍵產生標籤：

| 鍵 | zh_TW 值 |
|---|---|
| `gui_tls_days_humanized` | `{n} 天（約 {label}）` |
| `gui_tls_days_label_years` | `{y} 年 {m} 個月` |
| `gui_tls_days_label_months` | `{m} 個月` |

原始天數仍可透過 API 取得：
`GET /api/tls/status` → `days_remaining`。

---

## PCE 端 TLS 驗證

本節說明 illumio-ops 在呼叫 Illumio API 時**如何驗證 PCE 憑證**，
與 GUI 本身的 TLS 憑證無關。

### 各 Profile 的 `verify_ssl`

`config.json` 中的每個 PCE profile 均有一個 `verify_ssl` 布林值：

```json
{
  "pce_profiles": [
    {
      "name": "Production PCE",
      "url": "https://pce.example.com:8443",
      "verify_ssl": true
    }
  ]
}
```

| 值 | 行為 |
|---|---|
| `true`（預設） | 對照系統 CA bundle 進行完整憑證鏈驗證 |
| `false` | 跳過驗證（開發 / 實驗室使用自簽憑證的 PCE） |

> **警告：** 在正式環境設定 `verify_ssl: false` 會使 API 流量暴露於 MITM 攻擊風險。
> 請改用適當的 CA bundle。

### 自訂 CA Bundle

> TODO：確認目前的 config model 是否在 PCE profile 層級公開
> `ca_bundle` / `tls_ca_bundle` 路徑設定。資料模型（`src/config/`）在 SIEM 設定上
> 有 `tls_ca_bundle: Optional[str]` 欄位，但其是否適用於 PCE profile 尚未從目前
> 程式碼確認。請在正式記錄前查閱 `src/config/models.py` 及 PCE API 用戶端。

### 實驗室 / 自簽 PCE

對於使用自簽憑證的實驗室 PCE，建議的做法是：

```json
"verify_ssl": false
```

複製範例設定後，在 `config.json` 中設定此值。
若未設定，首次連線嘗試將因 SSL 驗證錯誤而失敗。

---

## 憑證錯誤排查

### 瀏覽器顯示「NET::ERR_CERT_AUTHORITY_INVALID」

Web GUI 正在使用預設自簽憑證，對於新安裝這是預期行為。解決方案：
- 接受瀏覽器安全性例外（僅限開發環境）。
- 透過 CSR 流程匯入 CA 簽署憑證。
- 將服務部署於終止 TLS 的反向代理後方。

### 顯示「Certificate imported. Restart the server to apply.」但仍顯示舊憑證

伺服器尚未重新啟動。新憑證只有在啟動時才會載入。
請重新啟動程序並強制重新整理瀏覽器。

### 匯入失敗，顯示金鑰不符錯誤

您貼上的 PEM 與 CSR 產生時的私鑰（`config/tls/csr_key.pem`）不符。
可能原因：
- CA 簽署與匯入之間重新產生了 CSR。
- 憑證是使用不同的金鑰簽署的。

解決方法：重新產生 CSR，重新提交 CA，再匯入新憑證。

### 狀態顯示「EXPIRED」或「EXPIRING SOON」

- **自簽憑證：** 點擊 **「更新憑證」** 並重新啟動伺服器。若 `auto_renew: true`，
  下次啟動時若剩餘天數 ≤ `auto_renew_days` 將自動更新。
- **CA 簽署憑證：** 執行 CSR 流程向 CA 取得新憑證，再進行匯入。

### illumio-ops 記錄中出現 `ssl.SSLError: certificate verify failed`

illumio-ops 無法驗證 PCE 的 TLS 憑證。
請對受影響的 PCE profile 設定 `verify_ssl: false`，
或將 PCE 的 CA 憑證加入系統信任存放區。

### 第一次啟動後 `gui_tls_no_cert` 訊息仍持續顯示

`config/tls/` 目錄可能沒有寫入權限。請檢查權限：

```bash
ls -la config/tls/
# 預期：目錄由執行 illumio-ops 的使用者擁有，權限 0755 以上
```

---

## 相關文件

- [Multi-PCE](multi-pce.md) — 各 PCE 的 TLS 設定
- [故障排查](troubleshooting.md) — 憑證錯誤診斷
- [SIEM 整合](siem-integration.md) — syslog-TLS 部署
- [發布流程](../contributing/release-process.md) — 升級期間的 TLS 處理
