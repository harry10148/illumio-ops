# UI Redesign v2 — Phase 2 總路線圖（實作 src/）

> 本檔是排序文件，不是可執行計畫。各子計畫另立檔案，依序撰寫與執行；每份子計畫獨立可合併、CI 全綠。
> 規格權威：`design/v2/` mockup（閘門 2 已放行，spec `docs/superpowers/specs/2026-08-03-ui-ux-redesign-v2-design.md` §1.1 健康列已修訂為僅總覽）。
> 歷程記錄：`tmp/design-v2-phase1-records/`（gitignored——ledger、15 任務報告、終審 triage）。

## 子計畫序列

| # | 計畫 | 內容 | 前置 | 預估額度視窗 |
|---|---|---|---|---|
| 2A | `2026-08-06-phase2a-gui.md`（本輪撰寫） | 六區前端＋登入＋切換上線：port mockup core/components/areas 到 `src/static/js/v2/`、模板拆分、真 API 接線、i18n 鍵入庫、legacy e2e 遷移、102 項覆蓋 gate 改打真 app、測試機部署驗證 | — | 4–6 |
| 2B | `2026-08-07-phase2b-reports.md`（已撰寫） | 新殼 CSS＋`report_shell.py` renderer；HTML 報表逐一套統一殼（reskin_report.py 的章節模型為原型）；測試機真資料重產、雙寬度＋PDF 逐頁親驗（CLAUDE.md 硬規則） | 無硬前置（實查 shell.css 自帶列印 token 子集，不依賴 2A 檔案；仍建議照序） | 2–3 |
| 2C | `2026-08-07-phase2c-cli.md`（已撰寫） | 互動選單依 `design/v2/cli-flows.md`（63 項對照、41 畫面）重組；click 子指令不動 | 無硬前置，排 2B 後 | 1–2 |
| 2D | `2026-08-07-phase2d-product-bugs.md`（已撰寫） | backlog 18 條已逐條對源碼重驗（14 仍在、2 描述有誤但有殘缺口、#10 已修、#12 需裁決）；與 2A-2C 解耦、可穿插 | — | 1–2 |
| 2E | `2026-08-07-phase2e-final-verification.md`（已撰寫） | 全案收斂：離線 bundle 打包驗證（Linux+Windows parity）、真機 102 項遍歷驗證報告、docs 更新（gui-tour 全檔重寫等）、CHANGELOG＋版本號（建議 5.0.0，待使用者裁決） | 2A–2D | 1 |

> **2026-08-08 撰寫時勘誤**（各計畫內有完整依據，執行時以計畫為準）：HTML 殼實為 **10 型**（policy_resolver 僅 JSON/CSV）；cli-flows 畫面稿實為 **41 張**（非 36）；產品無伺服端 PDF，PDF 驗收＝print CSS＋Playwright print-to-PDF；雙寬度慣例 1280/800；backlog #11 由 2C T7（移除 `_root.py` 重複入口）解決，2D Task 13 為條件式（grep 無命中即跳過）；#14 豁免移交 2C。

## 產品 bug backlog（2D 素材，出處=Phase 1 各任務報告）

1. `report_scheduler.py:259` 週排程存值 `"mon"` 與 `strftime("%A").lower()` 永不相等 → 週排程永不觸發；表單選項 monday..sunday 與存值不一致
2. GUI 報表排程編輯：`audit_summary` 等新型不在 select 選項 → 儲存時 `report_type` 被清空（dashboard.js:401/449）
3. CLI report_schedule 精靈 `type_map` 只認 traffic/audit/ven_status → 編輯把新型清空
4. `dashboard_hero.py:44-46` 用英文字比對已在地化 KPI label → 中文機 hero 恆 0/?
5. `index.html:1023-1028` Top Actions 面板＋`#snap-content` 無 renderer（死碼）
6. `validateIp`（integrations.js:521）拒絕 CIDR，但 `gui_cache_exclude_src_ips_help` 承諾支援
7. `has_draft_changes`（api_client.py:1298-1309）只對 `/sec_rules/` 檢查父 ruleset draft → deny/allow rules 閘門較弱（建立與每 tick 檢查皆然）
8. DLQ 清除（integrations.js dlqPurgeSelected）送 `{dest, older_than_days:0}` 無 ids，確認文案卻寫「purge N」
9. `stopGui`（actions.js:118）吞 403、無條件改寫 body
10. `login_*` i18n 前綴不在 `_ui_translation_dict` 白名單 → 18 鍵永遠讀不到
11. rule_scheduler 啟用/間隔開關在 `_root.py:164-188` 與 `rule_scheduler_cli.py:668-697` 重複實作（同 config 鍵）
12. `api.key__length` 洩漏真實金鑰長度（`_redact_secrets` 行為）
13. 排程清單（rule-scheduler.js:504）只顯示 `is_ruleset` 不驗 href → 兩承重欄位不一致時 UI 靜默
14. pce_cache/siem/rule_scheduler 三支 CLI 無 `draw_panel` 統一外框（WZ-3）
15. 報表產出 69 份中 36 份無 metadata sidecar（gui-report-split 記憶中的檔名 prefix 問題的延伸）
16. SIEM 卡片延遲 KPI 權重：GUI 用 sent；integrations.js:618-623 用 sent+failed（擇一為準）

## Phase 2 入場守則（終審 triage 的 must-fix-in-Phase-2 叢集）

- **元件 teardown 契約**：mockup 的 `FilterBar.destroy()`/chart ResizeObserver/`__openRuleDrawer` 定義了 teardown 但無人呼叫——production 版必須在路由切換時確實呼叫（2A 每區任務的驗收項）
- **a11y**：drawer/modal 需 focus trap＋正確 `aria-modal`；2A 元件層一次解決
- **JS 測試層**：決策=維持 Python+Playwright DOM 測試為主（與現有 suite 一致），但 2A 元件層核心邏輯（tone 判定、序列化）以 Playwright evaluate 直測函式
- **snapshots symlink**：mockup 專用，production 不引入；`design/v2/` 維持設計參考不動
- **引用行號漂移**：Phase 1 報告中約 10 處 citation drift——實作時以當下原始碼為準，不盲信報告行號；`v2_sy_pce_payload_src` 的產品行為誤述已修正（分區段 payload 是 v2 設計，不是產品現狀）
- 驗證面板（verifypane）**不移植**——樣本專用裝置
- i18n 617 補充鍵入庫時遵守七層白名單鏈（記憶：filter-key-chain-checklist）

## 額度策略

- 實作者以 Sonnet 為主（mockup 即規格，屬轉寫），Opus 留給：切換上線任務、各計畫終審、真機驗證判讀
- 每任務結束＝乾淨 commit＋CI 綠，撞額度即停、reset 後續跑（Phase 1 已驗證 ledger 復原零重工）

## 追加 backlog（2026-08-06 CI hotfix 過程發現，皆既有問題）

17. 跨測試檔搶真實 `logs/analysis.lock` flock（src/main.py、scheduler/jobs.py、gui/routes/actions.py 共用未 mock）→ test_main_menu.py 偶發失敗（transient，已隔離重跑確認非 cryptography 相關）
18. venv 的 pip-compile/pip-sync shebang 殘留改名前路徑（/home/harry/dev/...）→ `pip install --force-reinstall pip-tools` 可解；暫用 `python3 -m piptools` 繞過
