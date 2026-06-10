# Session Handoff — alexgoller-inspired features (updated 2026-06-10)

## 狀態：5 項中 3 項已實作並合併進 main（已 push origin）

分析 alexgoller/illumio-plugger 生態後挑出 5 個優化 illumio-ops 的設計，每個都有 spec + TDD 計畫（`docs/superpowers/{specs,plans}/2026-06-08-*`）。目前 **P1、P4、P2 已完整實作、合併進 `main`、push 到 origin**；P3、P5 仍只有 spec+plan。

- **目前分支**：`main`（與 `origin/main` 同步，HEAD `fc0a236`）
- 所有已完成功能皆以 subagent-driven-development 執行（每任務：實作 → 規格審查 → 程式品質審查 → 最終整體審查）。

## 進度表

| | 功能 | 首版範圍（已拍板） | 狀態 |
|---|---|---|---|
| **P1** | 態勢子分數 + 影響式修補清單 | 優化既有 `posture.py`（放棄合規層） | ✅ 合併（HEAD 系列 …fdbd9fe） |
| **P4** | Teams 告警通道 | Adaptive Card via Power Automate Workflows | ✅ 合併（…29d81a6） |
| **P2** | Policy Diff | 僅 Ruleset/Rule，draft-vs-active + audit 歸屬 | ✅ 合併（…fc0a236） |
| **P3** | Policy Resolver | label→IP（Workload+IP List+Label Group），JSON+CSV | 📋 spec+plan，**未實作** |
| **P5** | AI 輔助規則建議 | 啟發式核心 + 可插拔 LLM（預設關、氣隙安全、僅建議） | 📋 spec+plan，**未實作** |

## 下一步：接續 P3 Policy Resolver

P3 計畫：`docs/superpowers/plans/2026-06-08-policy-resolver.md`（7 任務）。spec：`...specs/2026-06-08-policy-resolver-design.md`。

**接續方式**（下個 session 貼這句即可）：
```
接續 illumio-ops 的 P3 Policy Resolver 實作。先讀 docs/superpowers/2026-06-08-planning-handoff.md，
然後從 main 開 feat/policy-resolver 分支，用 subagent-driven-development 執行
docs/superpowers/plans/2026-06-08-policy-resolver.md。
```

**P3 必讀揭露假設**：repo 原本**沒有**公開的 `get_ip_lists / get_label_groups / get_services`，plan **Task 1** 已用完整程式碼補上；ip_lists/label_groups/services 取自 **draft**（定義穩定），rulesets 取 **active**。純解析核心 `resolve_ruleset` 為純函式，與 I/O facade 分離。

## 執行流程（已驗證有效的工作模式）

1. `git checkout main && git pull` →（每個功能）從 main 開 `feat/<name>` 分支。
2. 讀該功能的 plan，擷取每個 Task 全文，逐任務派 implementer subagent（內嵌完整任務文字，勿讓 subagent 自讀整份 plan）。
3. 每任務：implementer（TDD）→ **spec reviewer**（獨立讀碼+跑測試，不信報告）→ **code-quality reviewer**（base→head diff）。controller 對審查意見用技術判斷裁決（採納真問題、有據回絕 YAGNI/cosmetic）。
4. 全部任務後派**最終整體 reviewer**（跨層契約、向後相容、scope、跑全套測試 + i18n audit）。
5. 用 finishing-a-development-branch：驗測試 → ff-merge 進 main → 在合併結果再驗 → 刪分支 → `git push origin main`。
6. 過程中**真實 bug 確實會被審查抓到**（例：P2 的排程+email `record_count` 對 dict 當機、P4 的 webhook userinfo 洩漏）——別跳過審查。

## 共同設計原則（所有功能遵守）

純函式核心可單元測試、零/可選外部依賴維持氣隙友善、重用既有報表/告警/`pce_cache` 管線、i18n EN+ZH_TW（strict prefix + glossary，`scripts/audit_i18n_usage.py` 須 Total 0）、JSON 設定（非 YAML）、向後相容、L-12 secret 不入 log。

## 環境備忘

- pytest 解譯器：這個 shell 的 `python` 不在 PATH，用 `venv/bin/python -m pytest`（subagent 環境的 `python` 可用）。
- i18n strict prefix：缺 key 時 `t()` 回 `[MISSING:key]`（非 literal fallback），故新 key 須同步進 EN+ZH 兩檔；GUI 端點 display_name 走 `t()`，缺 key 會顯示 `[MISSING:...]`。

## 已知 polish 待辦（非阻擋）

- **P2**：HTML 報表表格表頭仍是原始英文欄名；8 個 `rpt_policy_diff_col_*` i18n key 已定義但尚未接進 exporter 本地化（audit 允許 define-but-unused）。
- **手動驗證未做**：P1 dashboard modal 視覺、P4 CLI 選單與實際 Teams 送出、P2 報表實際畫面。
- 未追蹤檔 `docs/superpowers/plans/2026-06-04-cli-config-set.md` 為本次工作前既存、與此無關。
