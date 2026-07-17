---
title: illumio-ops 文件總目錄
audience: [operator, developer, api, security]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - docs/guide/installation.md
  - docs/guide/configuration.md
  - docs/guide/gui-tour.md
  - docs/guide/monitoring-alerts.md
  - docs/guide/reports.md
  - docs/guide/siem.md
  - docs/guide/automation.md
  - docs/guide/cache-maintenance.md
  - docs/guide/troubleshooting.md
  - docs/handover/architecture.md
  - docs/handover/development.md
  - docs/handover/pce-domain-notes.md
  - docs/reference/cli.md
  - docs/reference/rest-api.md
  - docs/reference/glossary.md
---

> 這裡是文件總目錄。
> 最後校驗 **2026-07-17**

# illumio-ops 文件總目錄

從專案根目錄的 **`README.md`**（**`README_zh.md`**）開始看總覽、架構圖與快速上手。
2026-07 文件重整後，`docs/` 底下全面改為**繁體中文單語**（僅 repo 根的 `README.md`／`README_zh.md`
仍維持中英成對）。以下三區涵蓋全部文件。

## 操作（`guide/`，9 篇）

面向操作員：安裝、設定、日常操作與排錯。

| 文件 | 一句話說明 |
|---|---|
| [安裝與部署](guide/installation.md) | 從原始碼或離線安裝包安裝、systemd／NSSM 服務化部署、升級與解除安裝。 |
| [設定參照](guide/configuration.md) | `config/config.json` 每個鍵的權威參照，以 pydantic schema 為 ground truth。 |
| [Web GUI 導覽](guide/gui-tour.md) | 8 個分頁的 SPA 導覽：登入、Dashboard、Reports、Rules、Events 等。 |
| [監控規則、告警與事件規則](guide/monitoring-alerts.md) | 即時監控規則引擎、B/L/R 報表安全規則引擎與事件處理管線的差異與設定方式。 |
| [報表家族](guide/reports.md) | 9 種報表的業務用途、關鍵欄位、CLI／GUI／排程三種產生方式。 |
| [SIEM 轉送](guide/siem.md) | 把 audit events 與 traffic 摘要轉送到 syslog／Splunk HEC／JSON sink，含 DLQ 重送與清除。 |
| [自動化：規則排程、隔離操作與背景 Job](guide/automation.md) | 會主動改變 PCE 狀態的自動化能力：Rule Scheduler 與隔離操作。 |
| [pce_cache 維運與容量規劃](guide/cache-maintenance.md) | 選用的本機 SQLite 鏡像維運、保留策略與容量估算。 |
| [故障排除](guide/troubleshooting.md) | 症狀導向排錯 runbook：現象、判讀依據、可執行的處置指令。 |

## 接手開發（`handover/`，3 篇）

面向新加入的開發者：零背景接手 codebase 所需的架構、開發流程與踩坑知識。

| 文件 | 一句話說明 |
|---|---|
| [架構導覽與模組地圖](handover/architecture.md) | 資料從哪裡進、在哪裡算、從哪裡出；`src/` 各頂層模組職責與關鍵設計決策。 |
| [開發流程與慣習](handover/development.md) | 開發環境建置、測試與 CI 守門、i18n 鍵值合約、常見斷鏈坑、發版流程。 |
| [PCE domain 須知（vendor 事實集）](handover/pce-domain-notes.md) | 無法從程式碼反推、踩過坑才知道的 Illumio PCE vendor 知識。 |

## 參考（`reference/`，3 篇）

| 文件 | 一句話說明 |
|---|---|
| [CLI 參考手冊](reference/cli.md) | `illumio-ops` 完整命令樹：13 個頂層子命令的旗標、範例與行為。 |
| [REST API 參考](reference/rest-api.md) | Web GUI 背後 Flask 應用的完整 JSON API 端點清單。 |
| [詞彙表](reference/glossary.md) | Illumio 產品術語中英對照；決策/狀態類術語刻意不強譯，與產品 UI 一致。 |

## 文件如何保鮮

每篇文件的 frontmatter 都帶 `last_verified` / `verified_against`。2026-07 文件重整後，`docs/`
語意改為**繁中單語**：不再要求每篇 `.md` 都有 `_zh.md` 對應檔，`--bilingual` 檢查改為只驗證 repo
根的 `README.md`／`README_zh.md` 是否成對存在（詳見 `docs/handover/development.md` §2.4）。

建議提交文件變更前執行：

```bash
python scripts/docs_check.py --all --exclude 'superpowers/**' --exclude 'ux-review*'
```

`docs/superpowers/` 底下是計畫／規格文件，本來就沒有 frontmatter，用 `--exclude` 排除；本機工作目錄
若殘留舊的 `docs/ux-review-2026-05-14/`（已 gitignore、非追蹤檔案，`docs_check` 仍會掃到磁碟上的檔案）
也一併排除。已實測此指令在 2026-07 文件重整（刪除舊雙語檔、改寫 INDEX）後對 `docs/` 其餘部分回傳
exit 0（links／frontmatter／bilingual 檢查全過）。連結正確性另有 CI 硬閘門
`python scripts/check_doc_links.py` 把關，範圍涵蓋整個 repo，不受 `--exclude` 限制。
