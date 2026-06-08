# Session Handoff — alexgoller-inspired feature planning (2026-06-08)

## 狀態：規劃完成，尚未開始實作

分析了 alexgoller/illumio-plugger 生態，挑出 5 個能優化 illumio-ops 的設計，**每個都已產出 spec + TDD 實作計畫**。實作尚未開始。

- **分支**：`feat/posture-subscores-remediation`（所有 spec/plan 都在此分支）
- **關鍵 commit**：`9b42d80`（P1 spec）、`a728519`（P1 plan）、`6b9e1a7`（P2–P5 spec+plan）
- 尚未從 `main` 分出獨立的實作分支；尚無任何 source code 變更。

## 5 個功能與文件

| | 功能 | 首版範圍（已拍板） | spec / plan 檔名（`docs/superpowers/{specs,plans}/2026-06-08-*`） | 風險 |
|---|---|---|---|---|
| **P1** | 態勢子分數 + 影響式修補清單 | 優化既有 `posture.py`（**放棄合規對映層**） | `posture-subscores-remediation*` | 低（純衍生） |
| **P2** | Policy Diff | **僅 Ruleset/Rule** draft-vs-active 欄位差異 + audit 歸屬 | `policy-diff*` | 中 |
| **P3** | Policy Resolver | label→IP（Workload+IP List+Label Group），輸出 JSON+CSV | `policy-resolver*` | 中 |
| **P4** | Teams 告警通道 | **Adaptive Card via Power Automate Workflows**（非 O365 MessageCard） | `teams-alert-channel*` | 低 |
| **P5** | AI 輔助規則建議 | 啟發式核心 + 可插拔 LLM（**預設關、氣隙安全、僅建議不套用**） | `ai-assisted-rules*` | 中 |

## 建議實作順序

1. **P1**（最低風險、純衍生、複用最強資產）→ 2. **P4**（最小、獨立）→ 3. **P2** → 4. **P3** → 5. **P5**。
順序可調；五者彼此獨立，可任意先後。

## 如何接續（每個 plan 都是自足的）

每份 plan 開頭都有 `REQUIRED SUB-SKILL` 標頭。接續時：

1. `git checkout feat/posture-subscores-remediation`（或為各功能另開實作分支）。
2. 選一份 plan，用 **superpowers:subagent-driven-development**（推薦，逐任務派 subagent + 審查）或 **superpowers:executing-plans**（本 session 內逐任務執行）。
3. 每個 plan 都是 TDD：失敗測試 → 跑 → 實作 → 跑 → commit，含完整真實程式碼與精確 pytest 指令。

## 必讀的揭露假設（實作時要留意）

- **P2**：audit events 只提供 `resource_name`，故操作者歸屬**先按物件名稱**匹配（非 href）；plan 已加報表註腳，href 精準對映留待後續。
- **P3**：repo 原本**沒有**公開的 `get_ip_lists / get_label_groups / get_services`，plan **Task 1** 已用完整程式碼補上；ip_lists/label_groups/services 取自 **draft**（定義穩定），rulesets 取 **active**。
- **P4**：Teams webhook URL 是 secret，plan 有 `redact_webhook_url` 純函式 + 遮罩測試（沿 README L-12 token 外洩教訓）。
- **P5**：預設 `provider="none"` 100% 離線；plan 有「provider=none 時不得有任何網路呼叫」的測試（monkeypatch socket）。

## 共同設計原則

純函式核心可單元測試、零/可選外部依賴維持氣隙友善、重用既有報表/告警/`pce_cache` 管線、i18n EN+ZH_TW（strict prefix + glossary）、JSON 設定（非 YAML）、向後相容。

## 其他

- 未追蹤檔 `docs/superpowers/plans/2026-06-04-cli-config-set.md` 為本次工作前既存、與此無關，未處理。
