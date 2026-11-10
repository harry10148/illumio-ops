---
title: illumio-ops v6 文件總目錄
last_verified: 2026-11-10
verified_against:
  - docs/guide/v6-installation.md
  - docs/guide/v6-siem-east-west.md
  - docs/reference/v6-rest-api.md
  - CHANGELOG.md
---

# illumio-ops v6 文件總目錄

這裡列的是 v6 的文件。v6 只有網頁介面；目前版本與各版變更見根目錄的 [CHANGELOG.md](../CHANGELOG.md)，
總覽與快速上手見 [README_zh.md](../README_zh.md)（英文版 [README.md](../README.md)）。

## v6 文件

| 文件 | 內容 | 給誰看 |
|---|---|---|
| [guide/v6-installation.md](guide/v6-installation.md) | 硬體建議、全新安裝、首次登入、從 5.x 升級、v6 升級、回退、救援指令、移除 | 安裝與維運人員 |
| [guide/v6-siem-east-west.md](guide/v6-siem-east-west.md) | SIEM 轉送送什麼、不送什麼，以及在 SIEM 裡看東西向連線的做法 | 已有 SIEM 的客戶 |
| [reference/v6-rest-api.md](reference/v6-rest-api.md) | 網頁介面使用的每一個 API 操作（由 API 契約產生） | 整合與開發人員 |

介面上每一頁的操作說明寫在介面本身，沒有另外的操作手冊。

## 5.x 文件

5.x 的文件整批放在 [legacy-5.x/](legacy-5.x/)，內容描述的是 5.x 的程式（`src/`、`config/config.json`、命令列工具），
**不適用 v6**，只供仍在執行 5.x 或要對照舊行為時查閱：

- `legacy-5.x/guide/`：安裝、設定、介面導覽、監控告警、報表、SIEM、自動化、快取維護、疑難排解。
- `legacy-5.x/reference/`：命令列、REST API、詞彙表、流量計量、Graylog 儀表板。
- `legacy-5.x/handover/`：架構、開發流程、PCE 領域筆記。
- `legacy-5.x/_meta/`：2026-07 文件重整的稽核紀錄與事件參考資料。

其中 `legacy-5.x/handover/pce-domain-notes.md` 與 `legacy-5.x/reference/traffic-metrics.md` 記錄的 PCE 行為
（policy 模型、流量欄位語意、API 實測）與 illumio-ops 的版本無關，但文中對應的程式路徑是 5.x 的。

## 其他

- `docs/superpowers/`：設計文件（specs）與實作計畫（plans），是開發過程的紀錄，不是使用手冊。
