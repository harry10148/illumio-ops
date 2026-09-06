# UI Redesign v3 — 總路線圖（實作 src/）

> 本檔是排序文件，不是可執行計畫。各子計畫另立檔案，**輪到才寫**（同日預寫多份計畫的存活率教訓：`memory/plan-staleness-depends-on-dependencies`）；每份子計畫獨立可合併、CI 全綠、部署測試機驗證後才寫下一份。
> 規格權威：`docs/superpowers/specs/2026-09-03-ui-redesign-v3-design.md`＋修訂 `2026-09-04-ui-redesign-v3-1-workbench-design.md`（§1／§2／§3／§5／§8 以修訂為準）（使用者 2026-09-03 逐節核可，commit `aed72211`）。
> 比稿畫布：https://claude.ai/code/artifact/bedafd57-0972-43ad-8500-f80f361193ba（第一頁＝Direction D 首頁＋調查中樞線框）。
> 基線：v2 已封版 `v5.0.0`（`cc77fbcf`）；4d SIEM `traffic_pd` 已先行交付（`122d2d83`）。

## 子計畫序列

| # | 計畫 | 內容 | 前置 | 狀態 |
|---|---|---|---|---|
| 3A | `2026-09-03-phase3a-backend.md` | spec §4a/§4b/§4c 後端契約：告警落地 SQLite＋`/api/alerts`、`?alert=` 查詢重建端點、`POST /api/policy/explain`（PCE Rule Search＋本地備援）；純後端＋守門，不動任何前端 | 無 | **已交付**（main `261768ad`＋`aa81f477`，2026-09-03；真機驗證 OK） |
| 3B | `2026-09-04-phase3b-gui.md` | spec §5 token（`css/v3/tokens.css`＋components）→ §1 五區路由與 shell → §2 首頁 → §3 調查中樞（收件匣／詳情／流量帶條件／規則面板／行動）→ 政策／報表／設定區搬遷 → 登入頁；`design/v3/coverage.yaml` 重編＋coverage gate 改讀；每區完成即部署測試機 | 3A | **已交付**（2026-09-04；Task 1–7 全部合入 main 並部署測試機；原地演進 v2 路徑；驗證報告 `tmp/phase3b-verification/report.md`） |
| 3E | `2026-09-04-phase3e-workbench.md` | v3.1 修訂 spec：左導覽殼層、清單／詳情／設定三種頁型、告警頁（自動 explain＋行動）、首頁最近告警、系統設定表單、文案去工程味；砍 3B 步進／上下文條 | 3B | 已撰寫（2026-09-04，7 任務） |
| 3C | `2026-09-06-phase3c-reports-cli.md` | **範圍已縮小**（2026-09-06 裁決）：報表 shell 換 v3 色票（設計權威移到 `design/v3/reports/shell.css`）＋圖表色盤鏡射 tone token＋CLI 主選單六區併五區。原列的「11 型真資料重產雙寬度逐頁驗」**已由 Phase 2B 完成**，降為 Task 1 的驗證步驟。內文墨色維持印刷黑 `#12161C`（報表要列印） | 3B（token 定案） | 計畫已寫 |
| 3D | `2026-09-03-phase3d-final.md`（3C 合入後撰寫） | spec §7：主場景六步 Playwright 真機走查＋截圖、五區 coverage 100%、docs（gui-tour 重寫）、CHANGELOG＋版本號（建議 6.0.0，待裁決）、release tag | 3A–3C | 待寫 |

判準與邊界（spec §1）：首頁看「現在」、調查查「這件事」、政策改「規則」、報表產「交付物」、設定改「系統」。

## 全程約束（每份子計畫的 Global Constraints 都要抄這段）

- 技術底座沿用 v2 spec §3：原生 ES modules、零 build、無 SPA 框架、無 npm；離線 bundle 腳本不動（新增檔案在 `src/` 下即自動打包）。
- 後端「不動」清單**解除**（spec §0），但 CSRF/session/auth 機制不動；新端點一律 `login_required`＋既有 CSRF 慣例。
- 資料模型從原始碼與真快照推導；PCE 術語保留英文；mockup／測試資料禁手寫（快照或真機）。
- i18n：新鍵走七層白名單鏈（memory `filter-key-chain-checklist`），`scripts/audit_i18n_usage.py` 必須 0 findings；`gui_` 前綴給 GUI、`sic_` 給 CLI。
- 守門沿用：三翻車點測試、CSS drift、conservation、`test_color_token_lint.py`／`test_css_color_tokens.py`（掃描加 `css/v3`）、coverage gate、全套 pytest＋CI。
- 檔案擁有者：測試機任何新落地檔（`logs/alerts.sqlite`）由 service 帳號 `illumio-ops` 建立，0600；不得以 root 手工建立（`rule_schedules.json`／`audit-2026-08-30.jsonl` 兩次事故）。
- Commit 英文 conventional commits；每任務結束＝乾淨 commit＋CI 綠。
- 「全套」＝ CI 的每道閘門：`scripts/check_no_naive_datetime.py`、`scripts/check_doc_links.py`、`scripts/audit_i18n_usage.py`、`mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`、`pytest`。本機 click 8.1.6 讓 `tests/test_cache_cli.py::test_cache_flush_json_output` 恆紅（CI 用 lock 的 8.3.3 為準）。

## 既知缺陷（順手可修，非本案範圍）

- `GET /api/siem/destinations` 用裸 `ConfigManager()` 讀預設路徑而非 `current_app.config["CM"]`（`src/siem/web.py:15`）；e2e 測試註解早已記錄。3B 搬設定區時順修。
- 測試機 repo 有 5 個舊 untracked 檔（3 個 config 備份、`alerts.json`、`time_events.py`），3D 收尾時處置。
