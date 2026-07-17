# 文件全面重整（Docs Overhaul）設計

> 2026-07-17 定案。方案 B：全部重寫，素材來源＝程式碼（ground truth）＋舊文件（must-preserve 挖料）＋NotebookLM Illumio 筆記本（vendor 事實查證）。

## 目標

1. 讓任何人打開 repo 就知道這個專案在做什麼。
2. 操作文件：維運者能靠文件完成安裝、設定、日常維運、故障排除。
3. 接手開發文件：新開發者能靠文件理解架構、模組職責與開發流程。
4. 開發須知：沉澱 PCE domain 知識與已驗證的 vendor 事實（policy 種類與意義、API 能調到 GUI 看不到的 policy type、X-Total-Count 語意等），這類知識目前散在記憶、specs 與程式註解，從未成冊。

## 背景盤點結論（2026-07-17）

- 現有核心文件約 25 份，全部 en/_zh 成對；frontmatter 有 `last_verified`/`verified_against` 新鮮度契約，基準停在 2026-06-26，落後最新功能約 3 週。
- 完全沒被記錄的：FilterBar v2 物件選擇器、job health 可觀測性、TLS 每日續期、告警 test-send、dashboard 新鮮度、policy_decision 含 unknown、rest-api 新端點。
- 完全不存在的：架構導覽＋模組地圖、PCE domain 須知。
- 文件不是 runtime load-bearing（app 執行期不讀 .md），可安全重構。
- must-preserve 資產（重寫時必須轉載進新文件）：operations-manual §8.9 實測容量基線（2.3KB/flow-row、外推表）、§9 troubleshooting runbook 與歷史校正、event-rules 的 MITRE ATT&CK 對映與 R 系列 on-demand gate 說明、glossary 術語、`docs/_meta/illumio-event-reference.json`（96K vendor 事件型錄，原地保留）。

## 決策（已與使用者確認）

| 議題 | 決定 |
|---|---|
| 語言策略 | 繁中為主；只留一份精簡英文 README，不再逐頁雙語成對 |
| 操作文件形態 | 任務導向多篇（拆掉 861 行 monolith） |
| 接手文件範圍 | 架構導覽＋模組地圖、PCE domain 須知、開發流程（development.md 合併現 contributing 三篇精華） |
| 重寫幅度 | 方案 B 全部重寫；舊 en/_zh 文件直接刪除（git 歷史可查，重寫期間當素材） |
| docs/superpowers、docs/_meta | 原地保留不動 |

## 新文件樹（約 17 份）

```
README.md              精簡英文：定位、功能一覽、quickstart、指向 docs/
README_zh.md           繁中完整總覽：專案在做什麼、架構圖、文件導航入口
docs/
  INDEX.md             繁中總目錄（唯一入口）
  guide/               操作文件（任務導向）
    installation.md         安裝與部署（source／offline bundle Linux+Windows／升級／移除）
    configuration.md        設定參照（config.json 全鍵、多 PCE、TLS、語言切換）
    gui-tour.md             Web GUI 導覽（8 分頁、FilterBar v2 物件選擇器、dashboard 新鮮度）
    reports.md              報表家族（9 種報表、產生/排程/匯出、cache vs live 資料來源）
    monitoring-alerts.md    監控規則 5 型、告警通道 5 種＋test-send、事件規則、DLQ/watchdog
    automation.md           rule scheduler、quarantine、排程自動化
    siem.md                 SIEM 轉送
    cache-maintenance.md    pce_cache 維運（backfill/aggregate/retention/archive、容量規劃）
    troubleshooting.md      故障排除 runbook（含 job health 面板判讀）
  handover/             接手開發
    architecture.md         架構導覽＋模組地圖（資料流、src/ 模組職責、關鍵設計決策的為什麼）
    pce-domain-notes.md     PCE domain 須知（vendor 事實集）
    development.md          開發環境、測試/CI 閘門、i18n workflow、release、常見斷鏈坑
  reference/
    cli.md                  CLI 參考（13 個 subcommand）
    rest-api.md             REST API 參考（含 filter_objects、job_health 等新端點）
    glossary.md             術語表
```

## pce-domain-notes.md 內容綱要

- **Policy 模型**：draft vs active（`/sec_policy/draft` vs `/active`、provision 生命週期）；rule 動作種類與意義（allow／deny／override_deny）；enforcement mode 四態（idle／visibility／selective／full）；API 調得到但 GUI 看不到的 policy type，以及本專案各報表（policy diff／resolver／rule hit count）如何利用這點。
- **Traffic / Explorer**：policy_decision 值域四值（blocked／potentially_blocked／allowed／unknown；unknown 涵蓋 idle/快照模式 VEN 與 Flowlink 未管理流量，漏掉它報表數字會少一大塊）；draft_policy_decision 的 on-demand 特性；async query 全流程（提交→輪詢→下載）。
- **API 行為實測事實**：Jobs API 終態是 `done` 不是 `completed`；集合 GET 硬上限 500 筆；`X-Total-Count` 在帶 query filter 的查詢回**未過濾總數**（PCE 25.2.40 真機實測）；帶日期參數需完整 ISO 時戳否則 406；429/Retry-After 行為與 POST 冪等注意；rule hit count 版本門檻（SaaS 24.2.0+/地端 23.5.10+/VEN 23.2.30+）、計數僅 Active 規則、保留 90 天、每 flow 最多歸因 100 條。
- 每條事實標註來源等級：`[真機驗證]`／`[官方文件]`（NotebookLM 查證）／`[推測待驗]`。

## 守門鏈適配（重寫不能弄斷）

1. `scripts/docs_check.py`：`--bilingual` 改為只要求 README.md/README_zh.md 成對，docs/ 內單語；frontmatter 契約（`title`/`last_verified`/`verified_against`）保留，所有新文件都帶且 `verified_against` 綁對應原始碼路徑。
2. `scripts/check_doc_coverage.sh`：CLI subcommand／install script 的覆蓋率映射改指新路徑（`docs/getting-started.md` → `docs/guide/installation.md`；`docs/reference/cli.md` 路徑不變）。
3. `tests/test_docs_contracts.py`：8 個契約測試改指新路徑，斷言邏輯保留（Python 版本宣告、版本 badge、GUI port/bind 預設、CLI 範例、SIEM 命令存在性、preflight 警語、entrypoint 名稱）。
4. CI `scripts/check_doc_links.py` 路徑無關，改完自然通過。

## 寫作方法

每份文件的產出流程：
1. 以程式碼為 ground truth 盤點該主題的當前行為（GUI routes、CLI、config models、scheduler jobs）。
2. 從舊文件挖 must-preserve 素材（見背景盤點），轉寫而非照抄。
3. domain 事實用 NotebookLM Illumio 筆記本查證後標註來源等級。
4. 過 `docs_check.py --all`＋`check_doc_links.py`。
5. 遵守專案規則：表格欄位與長內容的截斷/換行處理明確，交付前逐份走查。

## 驗證標準（全案完成的定義）

- `python scripts/docs_check.py --all` 綠（新 bilingual 語意下）。
- `python scripts/check_doc_links.py` 綠。
- `bash scripts/check_doc_coverage.sh` 綠（新路徑映射）。
- 全套 pytest 綠（含改路徑後的 test_docs_contracts.py）。
- docs/INDEX.md 每條導航人工走查。
- 舊 en/_zh 檔案已移除，repo 內無指向舊路徑的殘連結。

## 明確排除

- docs/superpowers/（52 份 specs/plans）與 docs/_meta/ JSON 資料：原地保留。
- GUI 內建說明頁、README badge 自動化：不在本案。
- 英文完整文件集：不做（僅精簡英文 README）。
