# v6 P6d 隔離 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 從主機側寫、工作台主機列、橫向移動頁的樞紐主機，把 workload 套上／解除 `Quarantine` label（Mild／Moderate／Severe）；套用前檢查 PCE 上有沒有已生效的政策引用該等級，並用流量試算會斷掉的連線；每次套用與解除寫入操作紀錄。

**Architecture:** 讀取（Quarantine labels、active／draft rule sets、workload 現況）走主 key；寫入（建立缺少的 label、PUT workload labels）只走 `ctx.pce_write_client`。政策引用檢查在 `domain/quarantine.py`（純函式，吃 rule set JSON），服務層 `services/quarantine.py` 負責 PCE 呼叫、試算（沿用 `simulate_deny`，進與出兩個提案）與 app.sqlite 的稽核表。套用時伺服器端重跑政策檢查，不靠前端確認框。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5.1「防堵 › 隔離」、§6.5 key 決定（寫入用 key）。

## Global Constraints

- 寫入只用寫入用 key；沒設時所有隔離動作反灰並說明，API 回 409 `no_write_key`。
- 寫入前緊鄰著重新 GET workload；PUT 的 labels 只動 key＝Quarantine 的那一個（移掉其他等級、加目標等級），其他 label 全部保留。
- PCE 拒絕（403／406 等）照 PCE 回應原文（截 300 字）呈現，永不顯示成功；每台結果與稽核各自一列，失敗也記。
- 等級沒有已生效的政策引用時，套用要帶 `acknowledge_no_policy=true`，否則 409 `no_policy`。
- `ip:` key 與清冊沒有的 href 不能隔離（拒絕並寫原因）；Visibility Only／Idle 的主機可套用但標明「不會執行任何規則」。
- 一批最多 50 台；試算與確認以整批為單位。
- 憑證不得出現在稽核、log、API 回應。
- 不替使用者建立 label dimension；PCE 因此拒絕建立 label 時照實說明。
- 每個 operation 要有前端呼叫者，同一 commit；zh 用字照 PCE 主控台（Label、Full／Selective／Visibility Only／Idle）。

## Review Focus

1. 寫入用 key 沒設／權限不足（403）——畫面與 API 都說明，稽核有失敗列，不顯示成功。
2. 等級無政策、只有 draft、ruleset 或規則停用——各自說清楚，未 acknowledge 不可套用。
3. workload 在預覽與套用之間被別人改了 label——以套用當下重新 GET 的結果為準，只換 Quarantine。
4. 批次部分失敗——逐台列出成功／失敗／略過與原因。
5. 解除未隔離的主機——寫「未隔離」，不 PUT。

---

### Task 1: 政策引用檢查、套用／解除、稽核、試算（服務層）

**Files:** Create `illumio_ops/domain/quarantine.py`、`illumio_ops/services/quarantine.py`、`illumio_ops/store/migrations/0010_quarantine_actions.sql`、`illumio_ops/store/quarantine_actions.py`；Test `tests_v6/domain/test_quarantine.py`、`tests_v6/services/test_quarantine.py`（`responses` 模擬 PCE）。

**Interfaces:**
- `domain.quarantine`: `KEY="Quarantine"`, `LEVELS=("Mild","Moderate","Severe")`; `relabel(labels: list[dict], target: str | None, quarantine_hrefs: set[str]) -> list[dict]`（只留 href）; `policy_refs(rule_sets, level_hrefs: dict[str,str]) -> dict[str, list[RuleRef]]`。
- `RuleRef{ruleset: str, ruleset_enabled: bool, rule_type: "allow"|"deny"|"override_deny"|"scope", enabled: bool, side: "consumer"|"provider"|"scope", consumers: list[str], providers: list[str], services: list[str]}`（actor／service 以 href 表示，名稱由服務層補）。
- `services.quarantine`: `check(ctx) -> QuarantineCheck{write_key, labels: dict[level, href|None], levels: dict[level, LevelPolicy{state: "active"|"disabled"|"draft_only"|"none", rules: list[RuleRef]}], names: dict[href,str]}`；`preview(ctx, keys, level) -> QuarantinePreview{check, targets: list[Target], inbound: DenySimulationView|None, outbound: …|None}`；`apply(ctx, keys, level, *, by, acknowledge_no_policy) -> QuarantineOutcome`；`remove(ctx, keys, *, by) -> QuarantineOutcome`；`history(ctx, key|None, limit) -> list[ActionRow]`。
- 例外：`NoWriteKey`、`NoPolicy`、`ValueError`（key 格式、超過 50 台、等級不在 LEVELS）。

- [ ] 測試先寫：relabel 保留他 key／換等級／移除；policy_refs 三態（active 有、規則或 ruleset 停用、無）＋scope；check 的 draft_only；apply 的 PUT body、寫入前重新 GET、缺 label 先 POST、403 → failed＋稽核列、無 write key、無政策未 acknowledge；remove 未隔離不 PUT；ip:／不在清冊略過；稽核不含憑證。
- [ ] 實作；閘門。

### Task 2: 路由與三個入口

**Files:** Create `illumio_ops/web/routes/quarantine.py`、`web/src/pages/quarantine/QuarantineDialog.tsx`；Modify `HostProfile.tsx`（按鈕、目前等級、紀錄、解除）、`Workbench.tsx`（主機維度列）、`LateralMovement.tsx`（樞紐勾選＋批次）、i18n、CSS；Test `tests_v6/web/test_quarantine_routes.py`、`tests_v6/e2e/test_quarantine_e2e.py`。

Operations：`quarantine.check` GET、`quarantine.preview` POST、`quarantine.apply` POST、`quarantine.remove` POST、`quarantine.history` GET。

- [ ] 測試先寫：登入／CSRF；409 no_write_key／no_policy；e2e 對話框列出各等級政策、試算數字、未 acknowledge 時按鈕停用、結果逐台列出。
- [ ] 實作；閘門；與 Task 1 一起 commit。

### Task 3: lab 腳本、最終審查、合併

- [ ] lab 寫入腳本（使用者以 `!` 執行）：對一台測試 workload 套用 Mild（lab 無政策引用 → 走 acknowledge 路徑、零網路影響）、確認 PCE 上 label、解除、確認還原；唯讀部分（check／preview）由我經通道驗。
- [ ] Codex 最終審查（「TASK: code review only…」）；Important 以上一次修完。
- [ ] 合併 main、push、盯 CI。

**不在本計畫**：把 deny rule 的 ip_list 範圍與 service 物件翻成精確的斷線試算（v6.1）；替使用者建立 label dimension 或 Quarantine 政策。
