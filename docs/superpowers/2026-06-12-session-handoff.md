# Session Handoff — 報表/UI 檢視與改善（2026-06-11 ~ 06-12）

## 狀態快照

- **分支**：`main`，HEAD `204fac6`，**領先 `origin/main` 32 commits（未 push）** — 部署前需 `git push`。
- 工作樹乾淨；worktree 全部清除；測試基線 **1740 passed, 5 skipped**（`./venv/bin/python -m pytest tests/ -q`）。
- 上一份 handoff：`docs/superpowers/2026-06-08-planning-handoff.md`（P1-P5 規劃；P5 仍待實作）。

## 這兩天完成（皆已合併進 main）

1. **WebUI/報表實測檢視**（Playwright 實機 + lab PCE 真報表）→ 缺失清單 + 分析師視角報表內容評估（基準：NotebookLM「Illumio」筆記方法論 + PCE 內建五種報表的互補性分析）。
2. **Plan: `plans/2026-06-11-ui-report-review-fixes.md`（12 任務，merge `b648013`）** — trend canonical key、exec-summary 數字格式、evidence i18n 洩漏、Policy Diff 風險分級/友善名稱/歸因窗口、GUI 小修×5、Policy Diff GUI 入口。
3. **Plan: `plans/2026-06-11-report-content-improvements.md`（7 任務，merge `204fac6`）** — 導讀卡修復（從未渲染過）、報表靜態 SVG（5MB→63KB）、基準漂移區段（含修復 trend/drift「匯出後才注入」的 dead-on-arrival Critical）、Label 治理區段、mod10 併入 mod02。

## 待執行（4 份 plan，全部已寫好）

| 順序 | Plan | 內容 | 備註 |
|------|------|------|------|
| 1 | `plans/2026-06-12-gui-fixes-batch2.md`（9 任務） | async 產生、稽核報表無資料調查、Posture CTA、管線 ERROR 原因、Resolver GUI 入口、排程頁兩 bug、VEN 版本分布、表頭截字、dead code 清理 | 使用者可見度最高，先做 |
| 2 | `plans/2026-06-12-report-content-v2.md`（6 任務） | MITRE ATT&CK 對應（含 19 規則對應表）、V-E 弱掃 CSV 整合（`--vuln-csv`） | 開頭有 3 個拍板決策，執行前過目 |
| 3 | `plans/2026-06-12-app-summary-report.md`（6 任務） | 第 7 種報表型別 App Summary（CLI+GUI+排程全套） | 開頭有 5 個拍板決策；與 plan 2 共改 cli/report.py + i18n，**勿平行** |
| 4 | `plans/2026-06-08-ai-assisted-rules.md` | P5 AI 輔助規則（spec 也在 specs/ 同日期） | 使用者條件：「現有修復部署後才開始」→ 先 push/部署 |

## 重要的踩坑筆記（本 session 驗證過）

- **i18n glossary 含複數形**：en 值用 "Ports"/"Labels"/"Workloads" 時，zh_TW 值必須含同形（單數 "Port" 不過 `test_i18n_glossary`）。新增 key 後必跑 `pytest tests/test_i18n_glossary.py` + `scripts/audit_i18n_usage.py`。
- **報表測試污染**：live 報表會寫 `reports/snapshots/traffic/*.json` 與 `logs/state.json`，會弄壞 `TestOverviewPostureHelper`（測試讀到真實 posture 38 而非 fixture 72）。處置：把真實 snapshot 移入 `reports/snapshots/traffic/_stash_traffic_snaps/`（保存非刪除）。
- **flaky 測試**：`tests/test_actions_rate_limit.py::test_dashboard_top10_rate_limit` 偶發失敗（timing 敏感，4 分鐘級），單獨重跑即過。
- **git stash 跨 worktree 共用**：樹乾淨時 `git stash` 是 no-op，後續 `stash pop` 會誤彈倉庫既有舊 stash（現存 `ux-r1 pre-branch backup` 等 2 個舊 stash，**勿動**）。
- **worktree 基準**：EnterWorktree 預設從 `origin/main` 分支 — main 未 push 時，建 worktree 後要先 `git merge main` 才有最新基線。
- 稽核報表「7 天無資料」主要嫌疑：cache 啟用時 audit 走過期 cache（lab cache 延遲 1000h+），事件頁走 live PCE — 已寫入 plan 1 Task 8 的調查假設。

## 下次 session 接續指令（貼這段即可）

```
接續 illumio-ops 的報表/UI 改善。先讀 docs/superpowers/2026-06-12-session-handoff.md。
從 main 用 worktree 執行 docs/superpowers/plans/2026-06-12-gui-fixes-batch2.md，
用 subagent-driven-development 模式（每任務：實作 → spec 審查 → 品質審查，最後整體審查）。
注意 handoff 裡的踩坑筆記（glossary 複數形、worktree 要先 merge 本地 main）。
```

（若想先推進其他 plan，把路徑換成 `2026-06-12-report-content-v2.md` / `2026-06-12-app-summary-report.md` / `2026-06-08-ai-assisted-rules.md` 即可；plan 2/3 執行前先看開頭「拍板的設計決策」。）
