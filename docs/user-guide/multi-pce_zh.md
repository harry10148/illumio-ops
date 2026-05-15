---
title: Multi-PCE
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/settings/manager.py
  - src/config.py
  - src/config_models.py
  - config/config.json.example
  - src/gui/routes/config.py
  - src/static/js/settings.js
  - src/cli/
  - python illumio-ops.py --help
  - commit 11a4ffc
related_docs:
  - tls-and-certificates.md
  - dashboard.md
  - settings-and-pce-cache.md
  - ../reference/cli.md
---

> 🌐 **[English](multi-pce.md)** | **[繁體中文](multi-pce_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 多 PCE
> 🔍 最後驗證 **2026-05-15** 對 commit `11a4ffc` — 詳見 frontmatter

# 多 PCE

Illumio-Ops 將 PCE 連線資訊以**設定檔（profile）**列表的形式存放於
`config/config.json`。任何時刻只有一個設定檔處於**啟用（active）**狀態——所有
功能（監控、報告、規則、SIEM 快取）都針對該啟用設定檔運作。您可儲存多個設定檔，
並在不手動編輯檔案的情況下切換。

> [!NOTE]
> **目前支援等級：多 PCE，需手動切換設定檔。**
> 設定檔可正常儲存，Web GUI 設定頁面支援新增、啟用及刪除。目前尚未實作同時輪詢多
> 個 PCE 的功能；在任何時間點，只有啟用中的設定檔會被監控。

---

## 何時使用多 PCE

當您的環境符合以下任一情況時，建議儲存多個設定檔：

| 情境 | 範例 |
|---|---|
| Lab 與 Production PCE 分離 | `lab.pce.example.com` + `pce.example.com` |
| 聯邦租戶 / Illumio Cloud SaaS | 每個租戶一個 org，各有獨立 API 金鑰 |
| 分階段部署 | 舊版 PCE 與升級後 PCE 並存 |
| DR / 容錯切換配對 | 主站點 + 備用站點 |

由於每次只有一個設定檔啟用，多設定檔的操作是**循序進行**的：監控某個 PCE 一段時
間後，啟用另一個再繼續。單一執行程序中同時監控兩個 PCE 目前尚未實作。

---

## 新增 PCE

### 透過 Web GUI（建議）

1. 在側邊欄開啟 **Settings → PCE Profiles**。
2. 點擊 **Add Profile** 並填入：
   - **Name** — 易辨識的標籤（必填）
   - **URL** — 含連接埠的完整基礎 URL，例如 `https://pce.example.com:8443`（必填）
   - **Org ID** — 預設為 `1`
   - **API Key** 與 **API Secret** — 從 PCE 使用者的 API 金鑰頁面取得
   - **Verify SSL** — 僅在 Lab 環境使用自簽憑證時取消勾選
3. 點擊 **Save**，設定檔立即出現於表格中。
4. 若要將其設為啟用設定檔，點擊該列旁的 **Activate**。
   頁首 chip 會更新為新的 PCE URL。

### 直接編輯 `config/config.json`

在 `pce_profiles` 陣列中新增一個物件，並更新 `active_pce_id`：

```json
{
  "pce_profiles": [
    {
      "id": 1000000000001,
      "name": "Production PCE",
      "url": "https://pce.example.com:8443",
      "org_id": "1",
      "key": "api_xxxxxxxxxxxxxx",
      "secret": "your-api-secret-here",
      "verify_ssl": true
    },
    {
      "id": 1000000000002,
      "name": "Lab PCE",
      "url": "https://lab-pce.example.com:8443",
      "org_id": "1",
      "key": "api_yyyyyyyyyyyyyy",
      "secret": "lab-secret-here",
      "verify_ssl": false
    }
  ],
  "active_pce_id": 1000000000001
}
```

`id` 欄位必須是唯一整數。CLI 互動式介面自動指派時使用
`int(time.time() * 1000)`（毫秒時間戳）。

手動編輯檔案後請重新啟動程序（或透過 GUI 重新載入）。

### 無專用 CLI 子命令

`python3 illumio-ops.py --help` 中沒有 `pce` 子命令。從命令列管理設定檔僅能透過
互動式 **shell** 選單（`python3 illumio-ops.py shell`）的 **Settings → API
credentials** 進行，且只能編輯啟用設定檔的欄位。若要新增設定檔，需直接編輯
`config.json` 或使用 Web GUI。

---

## PCE 切換器

### Web GUI 切換器（已實作）

`settings.js` 中的 **Settings → PCE Profiles** 表格，對每個非啟用設定檔渲染
**Activate** 按鈕。點擊後會呼叫：

```
POST /api/pce-profiles  { "action": "activate", "id": <profile-id> }
```

`src/config.py` 中的 `ConfigManager.activate_pce_profile()` 執行以下步驟：
1. 將 `active_pce_id` 設為指定設定檔 ID。
2. 將該設定檔的 `url`、`org_id`、`key`、`secret`、`verify_ssl` 複製到頂層
   `api` 區塊（API 客戶端讀取此處）。
3. 儲存 `config.json`。

頁首 chip（`<span class="pce-host">`）在 `loadSettings()` 觸發頁面重新載入後
立即更新。

> [!NOTE]
> **Dashboard 無 PCE 切換器小工具。** B1.4 審計確認 `index.html` 中不含
> `pce_switcher` 元素或 `switchPce` 呼叫。切換功能僅能從 **Settings** 頁面進行，
> 無法從 dashboard 操作。

### 切換後注意事項

監控常駐程式在下次輪詢週期時讀取 `active_pce_id`，無需重新啟動即可套用變更。若切
換後無效果，請確認是否使用了 **Activate** 按鈕（而非僅儲存編輯表單）——只有
`activate` 動作才會將憑證複製到 `api` 區塊。詳見 `docs/User_Manual.md` §6 的
疑難排解說明。

---

## 每個 PCE 的設定 vs 共用設定

| 設定 | 範圍 | 儲存位置 |
|---|---|---|
| `url` | 每個 PCE 設定檔 | `pce_profiles[*].url` |
| `org_id` | 每個 PCE 設定檔 | `pce_profiles[*].org_id` |
| `key` / `secret` | 每個 PCE 設定檔 | `pce_profiles[*].key/secret` |
| `verify_ssl` | 每個 PCE 設定檔 | `pce_profiles[*].verify_ssl` |
| 告警規則 | **全域** — 所有設定檔共用 | `config/alerts.json` |
| 報告排程 | **全域** — 針對啟用設定檔執行 | `config.json › report_schedules` |
| Email / SMTP | **全域** | `config.json › email / smtp` |
| Web GUI 憑證與 TLS | **全域** | `config.json › web_gui` |
| PCE 快取 | **全域**路徑；資料以啟用設定檔標記 | `config.json › pce_cache` |
| SIEM 轉發器 | **全域**設定；指向啟用設定檔 | `config.json › siem` |
| 時區 / 語言 / 主題 | **全域** | `config.json › settings` |

切換啟用設定檔**不會**重置現有規則或報告排程。所有規則將繼續套用於當前啟用的 PCE。

---

## 各 PCE 的認證與 TLS

每個設定檔各自帶有 `verify_ssl` 旗標。目前的結構（`src/config_models.py` 中的
`PceProfile`）沒有每個設定檔的 TLS CA bundle 欄位，只有 `id`、`url`、`org_id`、
`key`、`secret`、`name`、`verify_ssl`。

若某個 PCE 使用私有 CA：

- 將 `verify_ssl` 設為 `true`（不要停用驗證）。
- 將 CA 憑證安裝至執行 illumio-ops 主機的系統信任存放區，使 Python 的 `requests`
  程式庫能自動驗證。
- 或者使用 `REQUESTS_CA_BUNDLE` 環境變數指向特定的憑證 bundle 檔案。

**Web GUI 自身的 TLS**（供管理員瀏覽器連線用的 HTTPS）與 PCE TLS 無關，設定於
`web_gui.tls` 下——詳見 [TLS & Certificates](tls-and-certificates.md)。

> [!NOTE]
> 目前結構中尚無每個設定檔的 CA bundle / 用戶端憑證欄位。若需要設定檔層級的 CA
> 固定，可在 `extra=allow` 下新增 `ca_bundle` 鍵（模型接受未知欄位），並在程式碼
> 中引用。

---

## 跨 PCE 報告

報告引擎（`src/reporter.py`）在產生報告時呼叫 `_active_pce_url()`，讀取
`active_pce_id` 後查找對應設定檔的 `url`。**報告始終針對單一啟用設定檔產生。**

若需為兩個 PCE 各自產生報告：

1. 啟用設定檔 A → 執行 `python3 illumio-ops.py report …` → 儲存輸出。
2. 啟用設定檔 B → 再次執行 → 儲存輸出。

目前沒有「對所有設定檔執行報告並合併」的內建功能。排程報告（`report_schedules`）
同樣以排程觸發時的啟用設定檔為目標。

> [!TODO]
> 多 PCE 並行報告產生（fan-out）尚未實作。未來可為 `report` 子命令新增
> `--all-profiles` 旗標。

---

## 相關文件

- [TLS & Certificates](tls-and-certificates.md) — 各 PCE 的 TLS 設定
- [Dashboard](dashboard.md) — Dashboard 目前呈現多 PCE 狀態的方式
- [Settings & PCE Cache](settings-and-pce-cache.md) — 各 PCE 快取管理
- [CLI Reference](../reference/cli.md) — PCE 管理命令（如有）
