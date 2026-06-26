# Session Handoff — alexgoller-inspired features (updated 2026-06-11)

## 狀態：5 項中 4 項已實作並合併進 main（已 push origin）

分析 alexgoller/illumio-plugger 生態後挑出 5 個優化 illumio-ops 的設計，每個都有 spec + TDD 計畫（`docs/superpowers/{specs,plans}/2026-06-08-*`）。目前 **P1、P4、P2、P3 已完整實作、合併進 `main`、push 到 origin**；僅 P5 仍只有 spec+plan。

- **目前分支**：`main`（與 `origin/main` 同步，HEAD `3df4ec5`）
- 所有已完成功能皆以 subagent-driven-development 執行（每任務：實作 → 規格審查 → 程式品質審查 → 最終整體審查）。

## 進度表

| | 功能 | 首版範圍（已拍板） | 狀態 |
|---|---|---|---|
| **P1** | 態勢子分數 + 影響式修補清單 | 優化既有 `posture.py`（放棄合規層） | ✅ 合併（HEAD 系列 …fdbd9fe） |
| **P4** | Teams 告警通道 | Adaptive Card via Power Automate Workflows | ✅ 合併（…29d81a6） |
| **P2** | Policy Diff | 僅 Ruleset/Rule，draft-vs-active + audit 歸屬 | ✅ 合併（…fc0a236） |
| **P3** | Policy Resolver | label→IP（Workload+IP List+Label Group），JSON+CSV | ✅ 合併（…3df4ec5） |
| **P5** | AI 輔助規則建議 | 啟發式核心 + 可插拔 LLM（預設關、氣隙安全、僅建議） | 📋 spec+plan，**未實作** |

## 下一步：接續 P5 AI 輔助規則建議

P5 計畫：`docs/superpowers/plans/2026-06-08-ai-rules.md`。spec：`...specs/2026-06-08-*`。

**接續方式**（下個 session 貼這句即可）：
```
接續 illumio-ops 的 P5 AI 輔助規則建議實作。先讀 docs/superpowers/2026-06-08-planning-handoff.md，
然後從 main 開 feat/ai-rules 分支，用 subagent-driven-development 執行該功能的 plan。
```

## P3 Policy Resolver 收尾筆記（2026-06-11 完成，7 任務）

- **新增 API**：`get_ip_lists / get_label_groups / get_services`（`api_client.py`，取自 **draft**，定義穩定）；rulesets 取 **active**。
- **純核心**：`src/report/analysis/policy_resolver.py::resolve_ruleset`（零 I/O，cartesian 展開 + scope 收斂 + ANY sentinel + dedup）。偏離計畫修正：未知 ref → 丟棄規則（空 actor 清單才 → ANY）；label_group **不**受 scope 過濾（已知限制，docstring 已註記）。
- **Facade**：`policy_resolver_report.py`（5 個 O(N) lookup builder，label-group 展開 cycle-correct）。**`run()` 回傳 `list[str]`**（非 str）。
- **Exporter**：`policy_resolver_exporter.py`，`export(output_dir, fmt)` 依 fmt 選擇 json/csv/all（`--format` 真正生效）。
- **CLI**：`report resolve --format json/csv/all --output-dir`（**移除了計畫中的 silent no-op `--email`**，由使用者拍板）。
- **Scheduler**：report_type `policy_resolver` 已接 dispatch（回傳 `(SimpleNamespace(record_count=...), paths)` 對齊 policy_diff）+ prefix + email subject；**兩個 prune 方法（count-based 與 age-based）皆已加入 `.json`**（修正 .json 無限累積的 retention leak）。
- **i18n**：8 個 `rpt_*` key（EN+ZH_TW），其中 7 個為 define-but-unused（exporter 語言中性，audit 允許，同 P2 模式）。
- 驗證：33 focused + 1689 廣泛迯測通過、i18n audit Total 0。**手動 live PCE smoke-run 未做**（plan Final Verification 的 optional 項）。

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
