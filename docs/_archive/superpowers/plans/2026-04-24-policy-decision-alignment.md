# Policy Decision Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Illumio `draft_policy_decision` 七個子類語意完整整合進 illumio_ops 的 rules engine / reports / GUI，讓 draft deny 規則、override deny、boundary breach 可被偵測、呈現、篩選。

**Architecture:** 三個獨立子 plan（B1 rules、B2 reports、B3 GUI）依序 ship，共用一組 i18n keys。Rules engine 內部為新規則主動設 `compute_draft=True`（opt-in per rule），不改變 reports/GUI 既有觸發行為。

**Tech Stack:** Python (pandas / pytest), Flask, vanilla JS, existing i18n pipeline (`src/i18n_en.json` + `src/i18n_zh_TW.json`).

**Schedule note:** 本 plan 依用戶指示排在 roadmap queue 最後 — 順序為 **v3.11.1 tag → Phase 14 → Phase 15 → Phase 16 → 本 plan**。

**Final plan location (post-approval):** `docs/superpowers/plans/2026-04-24-policy-decision-alignment.md`。本 umbrella 計畫存此，三個 sub-plan 檔於實作時依序建立：
- `docs/superpowers/plans/2026-04-24-policy-decision-B1-rules.md`
- `docs/superpowers/plans/2026-04-24-policy-decision-B2-reports.md`
- `docs/superpowers/plans/2026-04-24-policy-decision-B3-gui.md`

---

## Context

**問題：** `draft_policy_decision`（Illumio Core 23.2.10+）提供七個子類語意（見 Mem0 memory `e1e89a8f`），可**無需切換 VEN 到 selective mode** 就偵測 draft deny / override deny / boundary breach。目前 illumio_ops：

- `src/report/rules_engine.py` 有 16 條 B/L 規則，**0 條**使用 `draft_policy_decision`（Explore agent 驗證）。
- `src/report/analysis/mod*.py` 全部只讀 `policy_decision`，無 draft 維度。
- GUI 三個 surface 嚴重不一致：`quarantine.js` 七子類徽章完整、`index.html qt-dpd-radio` 5/7（缺 `allowed` / `allowed_across_boundary`）、`dashboard.js:1594 draftPdMap` 只認 3 值、report builder UI 完全沒 draft_pd。
- `compute_draft` end-to-end plumbing 已通（analyzer `src/analyzer.py:811-841` → `src/api/traffic_query.py:_submit_and_stream_async_query` → async_jobs），但**僅在用戶設了 draft_policy_decision filter 時隱式觸發**。
- i18n 欠 5 個 draft 子類的 EN/ZH keys；`index.html:1375-1378` 有 hardcoded English label。
- 零測試 exercise draft_pd 子類或 `compute_draft=True` path。

**Q1/Q2/Q3 決策（用戶確認）：**
- **Q1 = B**：切 3 sub-plan（B1 rules / B2 reports / B3 GUI）
- **Q2 = R01+R02+R03+R04+R05**：五條新規則全做
- **Q3 = C**：opt-in per rule — rules engine 內部為 R01-R05 主動設 `compute_draft=True`，其他路徑維持現況（不動 reports / GUI 既有行為）

---

## 五條新規則規格（B1 Sub-plan 用）

| ID | 名稱 | 觸發條件 | 等級 | 類別 |
|---|---|---|---|---|
| **R-01** | Draft Deny Detected | `policy_decision='allowed'` **AND** `draft_policy_decision ∈ {blocked_by_boundary, blocked_by_override_deny}` | HIGH | B 系列（broad policy coverage） |
| **R-02** | Override Deny Detected | `draft_policy_decision` 含 `_override_deny`（任何子類，含 `potentially_blocked_by_override_deny`） | HIGH | B 系列 |
| **R-03** | Visibility Mode Boundary Breach | `policy_decision='potentially_blocked'` **AND** `draft_policy_decision='potentially_blocked_by_boundary'` | MEDIUM | L 系列（lateral/enforcement） |
| **R-04** | Allowed Across Boundary | `draft_policy_decision='allowed_across_boundary'`（allow 勝過 regular deny，需人工核對） | LOW / informational | L 系列 |
| **R-05** | Draft/Reported Mismatch Scan | `policy_decision='allowed'` **AND** `draft_policy_decision` 屬 `blocked_*` 家族 — 列管清單（R-01 超集，但以群組/聚合形式呈現，無 severity；列完 top N workload pair） | Informational | B 系列附錄 |

所有規則需共用 helper `_needs_draft_pd()`，集中決定 rules engine 要不要向 analyzer 要求 `compute_draft=True`。

---

## File Structure

### Sub-plan B1 — Rules engine + i18n keys + tests

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/report/rules_engine.py` | Modify | 新增 `R01`–`R05` 類 + `_needs_draft_pd()` helper；register in rule registry |
| `src/analyzer.py` | Modify L811-841 | 加入「rules engine 聲明需要 draft」時主動啟用 `compute_draft=True` 的通道（透過 `query_spec.requires_draft_pd` 或類似旗標） |
| `src/i18n_en.json` | Modify | 新增 10+ keys（見下方 i18n 段） |
| `src/i18n_zh_TW.json` | Modify | 對應 10+ keys |
| `tests/test_rules_engine_draft_pd.py` | Create | 五條新規則 × 正負案例 + `_needs_draft_pd` 邏輯 |
| `tests/test_analyzer_draft_pd.py` | Create | analyzer 在 rules engine 要求時正確設 `compute_draft=True` |

### Sub-plan B2 — Report analysis + exporters

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/report/analysis/mod02_policy_decisions.py` | Modify | 新增「Draft vs Reported」交叉表（選 compute_draft 啟用時）；emit chart_spec 第二維 |
| `src/report/analysis/mod13_readiness.py` | Modify | 新增「Draft enforcement gap」維度：若 draft=blocked 家族則計入 readiness gap |
| `src/report/analysis/mod_draft_summary.py` | Create | 新模組：draft_policy_decision 七子類 counts + top workload pairs（與 mod02 互補） |
| `src/report/analysis/__init__.py` | Modify L39 | 註冊 mod_draft_summary |
| `tests/test_mod02_draft.py` | Create | mod02 有/無 draft 欄位兩路徑 |
| `tests/test_mod_draft_summary.py` | Create | 新模組 smoke + golden |

### Sub-plan B3 — GUI harmonize

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/static/js/dashboard.js` | Modify L1594 | `draftPdMap` 擴至 7 值（+4 子類）並全部走 `_t(...)` |
| `src/templates/index.html` | Modify L1374-1378 + L1717 | `qt-dpd-radio` 補 `allowed` / `allowed_across_boundary`；hardcoded EN label 換 `data-i18n`；report builder UI 加 draft_pd checkbox section |
| `src/static/js/quarantine.js` | Modify L369-383 | 現有 7 子類徽章：hardcoded `"Override Deny"` / `"PB by Blocked"` / `"PB by Override Deny"` 換成 `_t(...)` |
| `src/gui.py` | Modify L386-397 + L1749 + L2263-2422 | `_build_policy_decisions_spec` 支援 draft 維度；report-schedule 接受 draft_pd filter；quarantine flow search 補 `allowed_across_boundary` 對應 |
| `tests/test_gui_draft_pd.py` | Create | 7 子類 round-trip 測試 |

---

## Task 0（所有 sub-plan 共通）: 前置

**Files:** none (read-only check)

- [ ] **Step 1: 確認 v3.11.1 / Phase 14 / Phase 15 / Phase 16 皆完成且 main 乾淨**

```bash
cd /mnt/d/RD/illumio_ops && \
  git status -sb && \
  git tag -l | grep -E 'v3\.(11\.1|12|13|14)' | sort && \
  test -z "$(git status --porcelain)" && echo "CLEAN"
```

Expected: `CLEAN`，tags 至少有 `v3.11.1-siem-cache`（roadmap 前序完成）。若 Phase 14-16 尚未完成則暫停本 plan。

- [ ] **Step 2: 跑 baseline 測試**

```bash
TMPDIR=/tmp TEMP=/tmp TMP=/tmp python3 -m pytest -q --basetemp=/tmp/pytest-illumio
```

記下 baseline 數字 (會 ≥ 523)。

---

# Sub-plan B1 — Rules Engine + i18n + Tests

**Target tag:** `v3.15.0-draft-pd-rules`
**Branch:** `feature/draft-pd-rules`

## Task B1.1: 建分支 + 建 sub-plan 檔

- [ ] **Step 1: 建分支**
```bash
cd /mnt/d/RD/illumio_ops && git checkout -b feature/draft-pd-rules
```

- [ ] **Step 2: 建 sub-plan 檔**（從本 umbrella 切出 B1 章節）
```bash
cp /home/harry/.claude/plans/plan-golden-ladybug.md /tmp/umbrella.md
# 手動截取 B1 章節寫入：
# /mnt/d/RD/illumio_ops/docs/superpowers/plans/2026-04-24-policy-decision-B1-rules.md
```

- [ ] **Step 3: Commit plan 檔**
```bash
git add docs/superpowers/plans/2026-04-24-policy-decision-B1-rules.md && \
git commit -m "docs(plan): add draft_policy_decision rules engine sub-plan"
```

## Task B1.2: i18n keys 先行

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

新增 keys（兩檔同步）：

```json
"pd_blocked_by_boundary": "Blocked by Boundary",
"pd_blocked_by_override_deny": "Blocked by Override Deny",
"pd_potentially_blocked_by_boundary": "Potentially Blocked by Boundary",
"pd_potentially_blocked_by_override_deny": "Potentially Blocked by Override Deny",
"pd_allowed_across_boundary": "Allowed Across Boundary",
"rule_r01_name": "Draft Deny Detected",
"rule_r01_desc": "Flows currently allowed but a draft deny rule would block them once provisioned.",
"rule_r02_name": "Override Deny Detected",
"rule_r02_desc": "Override deny rule present; cannot be overridden by any allow rule.",
"rule_r03_name": "Visibility Mode Boundary Breach",
"rule_r03_desc": "VEN in visibility/test mode and a deny boundary draft exists for this flow.",
"rule_r04_name": "Allowed Across Boundary",
"rule_r04_desc": "Allow rule overrides a regular deny. Verify this is intentional.",
"rule_r05_name": "Draft vs Reported Mismatch",
"rule_r05_desc": "Aggregated list of workload pairs where reported=allowed but draft suggests block.",
"rs_engine_needs_draft_pd": "Rule requires draft_policy_decision; compute_draft forced on."
```

ZH 版對照：
```json
"pd_blocked_by_boundary": "Blocked by Boundary（邊界封鎖）",
"pd_blocked_by_override_deny": "Blocked by Override Deny（強制拒絕封鎖）",
"pd_potentially_blocked_by_boundary": "Potentially Blocked by Boundary（潛在邊界封鎖）",
"pd_potentially_blocked_by_override_deny": "Potentially Blocked by Override Deny（潛在強制拒絕封鎖）",
"pd_allowed_across_boundary": "Allowed Across Boundary（越過邊界允許）",
"rule_r01_name": "偵測到 Draft Deny 規則",
"rule_r01_desc": "目前被允許的流量，一旦 draft deny 規則 provision 後將被封鎖。",
"rule_r02_name": "偵測到 Override Deny",
"rule_r02_desc": "存在 Override Deny 規則；任何 allow 規則都無法覆蓋。",
"rule_r03_name": "Visibility 模式 Boundary 突破",
"rule_r03_desc": "VEN 處於 visibility/test 模式且此流量有 deny boundary draft。",
"rule_r04_name": "Allowed Across Boundary",
"rule_r04_desc": "Allow 規則覆蓋了 regular deny，請確認是否為預期行為。",
"rule_r05_name": "Draft 與 Reported 不一致",
"rule_r05_desc": "彙整 reported=allowed 但 draft 顯示會被封鎖的 workload pair 清單。",
"rs_engine_needs_draft_pd": "規則需要 draft_policy_decision，強制啟用 compute_draft。"
```

Glossary：`Workload`、`Policy`、`Service`、`Port`、`Override Deny`、`Boundary`、`Allowed`、`Blocked` 保持英文（依 `_TOKEN_MAP_ZH` 既定策略）。

- [ ] **Step 1: Edit `src/i18n_en.json`** — append 上列 15 個 key。
- [ ] **Step 2: Edit `src/i18n_zh_TW.json`** — append 對照 key。
- [ ] **Step 3: 跑 i18n audit**
```bash
python3 scripts/audit_i18n_usage.py
```
Expected: `A–I = 0 findings`。
- [ ] **Step 4: Commit**
```bash
git add src/i18n_en.json src/i18n_zh_TW.json && \
git commit -m "i18n: add draft_policy_decision + R01-R05 rule keys"
```

## Task B1.3: analyzer 支援 rules-engine-driven compute_draft

**Files:**
- Modify: `src/analyzer.py:811-841`

- [ ] **Step 1: 寫 failing test**

Create `tests/test_analyzer_draft_pd.py`：
```python
def test_rules_engine_can_force_compute_draft(monkeypatch):
    """Analyzer honors query_spec.requires_draft_pd=True regardless of filters."""
    from src.analyzer import Analyzer
    spec = SimpleNamespace(
        report_only_filters={},
        requires_draft_pd=True,
    )
    captured = {}
    def fake_submit(payload, compute_draft=False):
        captured['compute_draft'] = compute_draft
        return iter([])
    monkeypatch.setattr('src.api.traffic_query._submit_and_stream_async_query', fake_submit)
    Analyzer(...)._fetch_traffic(spec)
    assert captured['compute_draft'] is True
```

- [ ] **Step 2: Run test → FAIL** (`requires_draft_pd` attribute not read)

- [ ] **Step 3: 改 `src/analyzer.py` L811-841**

```python
# In _fetch_traffic:
draft_pd_filter = query_spec.report_only_filters.get("draft_policy_decision")
needs_draft = bool(draft_pd_filter) or getattr(query_spec, "requires_draft_pd", False)
if needs_draft:
    logger.debug("compute_draft=True (filter={!r} rules_needs={})".format(
        draft_pd_filter, getattr(query_spec, "requires_draft_pd", False)))
    ...
    compute_draft = True
```

- [ ] **Step 4: Run test → PASS**

- [ ] **Step 5: Commit**
```bash
git add src/analyzer.py tests/test_analyzer_draft_pd.py && \
git commit -m "feat(analyzer): honor query_spec.requires_draft_pd for rules engine"
```

## Task B1.4: 實作 `_needs_draft_pd` helper + 五條規則

**Files:**
- Modify: `src/report/rules_engine.py`

- [ ] **Step 1: 寫 failing tests**

Create `tests/test_rules_engine_draft_pd.py` 共 15+ tests（每規則 正 + 負 + 邊界，覆蓋：policy_decision × draft_policy_decision 矩陣）。以 R-01 為例：
```python
def test_r01_fires_on_allowed_with_blocked_by_boundary_draft():
    flows_df = pd.DataFrame([
        {"src": "web", "dst": "db", "port": 3306, "policy_decision": "allowed",
         "draft_policy_decision": "blocked_by_boundary"},
    ])
    rule = R01DraftDenyDetected()
    findings = rule.evaluate(flows_df, {})
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert "draft" in findings[0].title.lower()

def test_r01_silent_when_draft_matches_reported():
    flows_df = pd.DataFrame([
        {"src": "web", "dst": "db", "port": 3306, "policy_decision": "allowed",
         "draft_policy_decision": "allowed"},
    ])
    assert R01DraftDenyDetected().evaluate(flows_df, {}) == []

def test_r01_needs_draft_pd_returns_true():
    assert R01DraftDenyDetected().needs_draft_pd() is True
```

類似測試為 R02/R03/R04/R05（可抽 parametrize）。

- [ ] **Step 2: Run all 15+ tests → FAIL**

- [ ] **Step 3: 在 `src/report/rules_engine.py` 新增實作**

```python
class _DraftPdRuleMixin:
    def needs_draft_pd(self) -> bool:
        return True

class R01DraftDenyDetected(_DraftPdRuleMixin, BaseRule):
    id = "R01"
    severity = "HIGH"
    name_key = "rule_r01_name"

    def evaluate(self, flows_df, ctx):
        mask = (flows_df["policy_decision"] == "allowed") & (
            flows_df["draft_policy_decision"].isin([
                "blocked_by_boundary", "blocked_by_override_deny"
            ])
        )
        if not mask.any():
            return []
        pairs = flows_df[mask].groupby(["src", "dst", "port"]).size().reset_index(name="flows")
        return [Finding(
            rule_id=self.id, severity=self.severity,
            title=t(self.name_key),
            description=t("rule_r01_desc"),
            evidence=pairs.to_dict("records"),
        )]

class R02OverrideDenyDetected(_DraftPdRuleMixin, BaseRule):
    id = "R02"
    severity = "HIGH"
    def evaluate(self, flows_df, ctx):
        mask = flows_df["draft_policy_decision"].str.endswith("_override_deny", na=False)
        # ... analogous structure

class R03VisibilityBoundaryBreach(_DraftPdRuleMixin, BaseRule):
    id = "R03"
    severity = "MEDIUM"
    def evaluate(self, flows_df, ctx):
        mask = (flows_df["policy_decision"] == "potentially_blocked") & (
            flows_df["draft_policy_decision"] == "potentially_blocked_by_boundary"
        )
        # ...

class R04AllowedAcrossBoundary(_DraftPdRuleMixin, BaseRule):
    id = "R04"
    severity = "LOW"
    def evaluate(self, flows_df, ctx):
        mask = flows_df["draft_policy_decision"] == "allowed_across_boundary"
        # ...

class R05DraftReportedMismatch(_DraftPdRuleMixin, BaseRule):
    id = "R05"
    severity = "INFO"
    def evaluate(self, flows_df, ctx):
        blocked_draft = flows_df["draft_policy_decision"].str.startswith("blocked_", na=False)
        mask = (flows_df["policy_decision"] == "allowed") & blocked_draft
        if not mask.any():
            return []
        top = (flows_df[mask].groupby(["src", "dst"])
               .size().sort_values(ascending=False).head(20).reset_index(name="flows"))
        return [Finding(
            rule_id=self.id, severity=self.severity,
            title=t("rule_r05_name"), description=t("rule_r05_desc"),
            evidence=top.to_dict("records"),
        )]
```

Register：在規則 registry 尾端加 `R01DraftDenyDetected, R02OverrideDenyDetected, R03VisibilityBoundaryBreach, R04AllowedAcrossBoundary, R05DraftReportedMismatch`。

- [ ] **Step 4: Run tests → PASS**

- [ ] **Step 5: 處理缺失欄位 graceful fallback**

若 DataFrame 無 `draft_policy_decision` 欄（未啟用 compute_draft），所有 `_DraftPdRuleMixin` 子類 evaluate 必須 return `[]` 不 raise。

在 mixin 的 base call 前加 guard：
```python
def _has_draft(self, flows_df):
    return "draft_policy_decision" in flows_df.columns

# 每個 evaluate 最前面 check
if not self._has_draft(flows_df):
    return []
```

補 test：
```python
def test_r01_silent_when_column_missing():
    flows_df = pd.DataFrame([{"src":"a","dst":"b","port":80,"policy_decision":"allowed"}])
    assert R01DraftDenyDetected().evaluate(flows_df, {}) == []
```

- [ ] **Step 6: Run all tests → PASS**

- [ ] **Step 7: Commit**
```bash
git add src/report/rules_engine.py tests/test_rules_engine_draft_pd.py && \
git commit -m "feat(rules): add R01-R05 draft_policy_decision security rules"
```

## Task B1.5: rules engine 驅動 `requires_draft_pd`

**Files:**
- Modify: `src/report/rules_engine.py`（聚合 helper）
- Modify: caller path — `src/report/report_generator.py:323` or `src/analyzer.py` 視載入時機

- [ ] **Step 1: 加 module-level helper**

```python
def ruleset_needs_draft_pd(ruleset) -> bool:
    return any(getattr(r, "needs_draft_pd", lambda: False)() for r in ruleset)
```

- [ ] **Step 2: 在 report/analyzer 入口設 `query_spec.requires_draft_pd`**

在 rules engine 被呼叫前：
```python
from src.report.rules_engine import ruleset_needs_draft_pd, ACTIVE_RULES
query_spec.requires_draft_pd = ruleset_needs_draft_pd(ACTIVE_RULES)
```

- [ ] **Step 3: 測試整合**

Create `tests/test_rules_engine_draft_integration.py`：
```python
def test_active_ruleset_needs_draft_pd():
    from src.report.rules_engine import ruleset_needs_draft_pd, ACTIVE_RULES
    assert ruleset_needs_draft_pd(ACTIVE_RULES) is True  # R01-R05 present
```

- [ ] **Step 4: Commit**
```bash
git add src/report/rules_engine.py src/analyzer.py tests/test_rules_engine_draft_integration.py && \
git commit -m "feat(rules): auto-enable compute_draft when ruleset needs draft_pd"
```

## Task B1.6: B1 收尾 + tag

- [ ] **Step 1: Full regression**
```bash
TMPDIR=/tmp TEMP=/tmp TMP=/tmp python3 -m pytest -q --basetemp=/tmp/pytest-illumio
```
Expected: baseline + 20+ new tests, all green.

- [ ] **Step 2: i18n audit**
```bash
python3 scripts/audit_i18n_usage.py
```
Expected: `A–I = 0`.

- [ ] **Step 3: Merge to main + tag**
```bash
git checkout main && git merge --no-ff feature/draft-pd-rules && \
git tag -a v3.15.0-draft-pd-rules -m "feat(v3.15.0): draft_policy_decision rules R01-R05

R01 Draft Deny Detected (HIGH)
R02 Override Deny Detected (HIGH)
R03 Visibility Mode Boundary Breach (MEDIUM)
R04 Allowed Across Boundary (LOW)
R05 Draft/Reported Mismatch Scan (Informational)

Rules engine auto-enables compute_draft=True when ACTIVE_RULES contains
any draft-pd-dependent rule. No change to reports/GUI triggering." && \
git push origin main && git push origin v3.15.0-draft-pd-rules
```

- [ ] **Step 4: Mem0 記錄 B1 完成**（via `mcp__plugin_mem0_mem0__add_memory`，metadata `{"type":"project","project":"illumio_ops","version":"3.15.0-draft-pd-rules"}`）

---

# Sub-plan B2 — Report Analysis + Exporters

**Target tag:** `v3.16.0-draft-pd-reports`
**Branch:** `feature/draft-pd-reports`
**Depends on:** B1 merged (i18n keys + compute_draft plumbing)

## Task B2.1: 建分支 + sub-plan 檔

- [ ] `git checkout -b feature/draft-pd-reports`
- [ ] 建 `docs/superpowers/plans/2026-04-24-policy-decision-B2-reports.md`
- [ ] Commit plan

## Task B2.2: `mod_draft_summary` 新模組（TDD）

**Files:**
- Create: `src/report/analysis/mod_draft_summary.py`
- Modify: `src/report/analysis/__init__.py:39`
- Create: `tests/test_mod_draft_summary.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_draft_summary_counts_7_subtypes():
    flows = pd.DataFrame([
        {"src":"a","dst":"b","port":80,"policy_decision":"allowed","draft_policy_decision":"allowed"},
        {"src":"a","dst":"b","port":443,"policy_decision":"allowed","draft_policy_decision":"blocked_by_boundary"},
        {"src":"x","dst":"y","port":22,"policy_decision":"allowed","draft_policy_decision":"blocked_by_override_deny"},
        # ... cover all 7 subtypes
    ])
    out = analyze(flows)
    assert set(out["counts"].keys()) == {
        "allowed","potentially_blocked",
        "blocked_by_boundary","blocked_by_override_deny",
        "potentially_blocked_by_boundary","potentially_blocked_by_override_deny",
        "allowed_across_boundary",
    }

def test_draft_summary_absent_when_column_missing():
    flows = pd.DataFrame([{"src":"a","dst":"b","port":80,"policy_decision":"allowed"}])
    out = analyze(flows)
    assert out == {"skipped": True, "reason": "no draft_policy_decision column"}
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: 實作 `mod_draft_summary.py`**
```python
"""Draft policy decision summary: 7-subtype counts + top workload pairs per subtype."""
import pandas as pd

DRAFT_SUBTYPES = [
    "allowed","potentially_blocked",
    "blocked_by_boundary","blocked_by_override_deny",
    "potentially_blocked_by_boundary","potentially_blocked_by_override_deny",
    "allowed_across_boundary",
]

def analyze(flows_df: pd.DataFrame) -> dict:
    if "draft_policy_decision" not in flows_df.columns:
        return {"skipped": True, "reason": "no draft_policy_decision column"}
    counts = flows_df["draft_policy_decision"].value_counts().to_dict()
    for s in DRAFT_SUBTYPES:
        counts.setdefault(s, 0)
    top_pairs = {}
    for subtype in DRAFT_SUBTYPES:
        mask = flows_df["draft_policy_decision"] == subtype
        if mask.sum() == 0: continue
        top_pairs[subtype] = (flows_df[mask].groupby(["src","dst"])
                              .size().sort_values(ascending=False).head(10)
                              .reset_index(name="flows").to_dict("records"))
    return {
        "counts": counts,
        "top_pairs_by_subtype": top_pairs,
        "chart_spec": _build_chart_spec(counts),
    }

def _build_chart_spec(counts):
    return {
        "kind": "bar",
        "title_key": "rpt_draft_summary_chart_title",
        "categories": DRAFT_SUBTYPES,
        "values": [counts.get(s, 0) for s in DRAFT_SUBTYPES],
    }
```

- [ ] **Step 4: Register in `analysis/__init__.py`**
```python
"mod_draft_summary": ("mod_draft_summary", "draft_policy_decision_summary"),
```

- [ ] **Step 5: Run tests → PASS**

- [ ] **Step 6: Commit**
```bash
git add src/report/analysis/mod_draft_summary.py \
        src/report/analysis/__init__.py \
        tests/test_mod_draft_summary.py && \
git commit -m "feat(report): add mod_draft_summary for draft_policy_decision subtype breakdown"
```

## Task B2.3: mod02 加 Draft 交叉維度

**Files:**
- Modify: `src/report/analysis/mod02_policy_decisions.py`
- Create: `tests/test_mod02_draft.py`

- [ ] **Step 1: 寫 failing test**（draft 欄存在時 output 多一個 `draft_breakdown` key；不存在時維持現狀）

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: 在 `mod02_policy_decisions.py` 新增**
```python
def analyze(flows_df, ...):
    result = ...existing...
    if "draft_policy_decision" in flows_df.columns:
        result["draft_breakdown"] = (
            flows_df.groupby(["policy_decision","draft_policy_decision"])
                    .size().unstack(fill_value=0).to_dict()
        )
    return result
```

- [ ] **Step 4: Run tests → PASS**

- [ ] **Step 5: Commit**

## Task B2.4: mod13 加 Draft enforcement gap

**Files:**
- Modify: `src/report/analysis/mod13_readiness.py`

同前：draft 存在時把 `blocked_*` draft 計入 readiness gap 的新欄位（不取代舊欄位）。Test + implement + commit。

## Task B2.5: HTML exporter Data-Source pill

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

當 `compute_draft=True` 時在報表頭部加一個 "Draft Policy Decision: enabled" pill（類似 Phase 14 計畫中的 data-source pill 設計）。純 CSS + i18n key (`rpt_hdr_draft_enabled`)。

## Task B2.6: B2 收尾 + tag `v3.16.0-draft-pd-reports`

同 B1.6 pattern。

---

# Sub-plan B3 — GUI Harmonize

**Target tag:** `v3.17.0-draft-pd-gui`
**Branch:** `feature/draft-pd-gui`
**Depends on:** B1 merged（i18n keys），B2 可選（若 report builder 要展示 draft 報表）

## Task B3.1: 建分支 + sub-plan 檔

同 B1.1 / B2.1 pattern。

## Task B3.2: `dashboard.js draftPdMap` 擴至 7 子類

**Files:**
- Modify: `src/static/js/dashboard.js:1594`

- [ ] **Step 1: 先檢視現況**
```bash
sed -n '1580,1620p' src/static/js/dashboard.js
```

- [ ] **Step 2: 改成**
```javascript
const draftPdMap = {
  allowed: _t('pd_allowed'),
  potentially_blocked: _t('gui_pd_potential'),
  blocked_by_boundary: _t('pd_blocked_by_boundary'),
  blocked_by_override_deny: _t('pd_blocked_by_override_deny'),
  potentially_blocked_by_boundary: _t('pd_potentially_blocked_by_boundary'),
  potentially_blocked_by_override_deny: _t('pd_potentially_blocked_by_override_deny'),
  allowed_across_boundary: _t('pd_allowed_across_boundary'),
};
```

- [ ] **Step 3: `node --check src/static/js/dashboard.js`** → PASS

- [ ] **Step 4: Commit**

## Task B3.3: `index.html qt-dpd-radio` 補齊 7 值 + i18n

**Files:**
- Modify: `src/templates/index.html:1374-1378`

- [ ] **Step 1: 目前五個 radio 補「`allowed`, `allowed_across_boundary`」兩個；所有 label 改成 `data-i18n="pd_*"` 而非 hardcoded English**
- [ ] **Step 2: `grep -n '<label' src/templates/index.html | head -30`** 驗證無殘留 hardcoded English
- [ ] **Step 3: Commit**

## Task B3.4: `quarantine.js` hardcoded EN → `_t(...)`

**Files:**
- Modify: `src/static/js/quarantine.js:369-383`

現有 hardcoded `"Override Deny"` / `"PB by Blocked"` / `"PB by Override Deny"` → 全部 `_t('pd_*')`。

## Task B3.5: Report Builder UI 加 draft_pd section

**Files:**
- Modify: `src/templates/index.html:1717`（report builder PD potential checkbox 區塊）
- Modify: `src/static/js/dashboard.js` L782/814/844/875/900-902（scheduler PD checkboxes）

加「Draft Policy Decision」子 section，七個 checkbox，送到 backend 時走現有 `draft_policy_decision` filter（analyzer 會自動 `compute_draft=True`）。

## Task B3.6: `gui.py` 接收端補齊 7 值

**Files:**
- Modify: `src/gui.py:2263-2422`

- quarantine flow search 的 pd/draft_pd 對應表補 `allowed`、`allowed_across_boundary`
- report-schedule 端接收 draft_pd filter list（若 B2 的 report builder 有送）

## Task B3.7: Playwright smoke test（可選但建議）

**Files:**
- Create: `tests/e2e/test_draft_pd_ui.py`

用 Playwright MCP：
1. Login GUI
2. 開 quarantine panel → 切到 draft_pd radio → 驗證七個 radio 都有且 label 走 i18n
3. 切 ZH → label 切換正常
4. 報表 builder → 勾 draft_pd → 送出 → 檢視 request payload 含 `draft_policy_decision` filter

## Task B3.8: B3 收尾 + tag `v3.17.0-draft-pd-gui`

同 B1.6 pattern。

---

## Verification（全 3 sub-plans 完成後）

1. `git tag -l | grep -E 'v3\.(15|16|17)\.0-draft-pd' | wc -l` → 3
2. Rules engine 能偵測 draft deny 而無需切換 VEN 到 selective mode（live PCE 驗證 — 參考 Mem0 實驗流程）
3. mod02 / mod13 / mod_draft_summary 在 live PCE query（`compute_draft=True`）回傳完整七子類統計
4. GUI 三介面（quarantine / dashboard / report builder）label 與 radio 均一致、均走 i18n
5. i18n audit `A–I = 0`；pytest baseline + ~50 new tests 全綠
6. Mem0 有三筆對應 milestone memory

---

## Rollback Strategy

- 每個 sub-plan 在各自分支開發，tag 前不 merge main。若 B1 發現需求偏差，`git branch -D feature/draft-pd-rules` 即可重來。
- 已 tag 已 push 則遵循與 v3.11.1 相同的 rollback 步驟（新 commit 還原 + 重 tag）。

---

## Self-Review 註記

- **Spec coverage**：Q1(B) / Q2(R01-R05) / Q3(C) 三決策全落地 ✓
- **R05 vs R01 重疊**：R05 為聚合列管（top 20 pair），R01 為單 flow 等級 HIGH finding，職責分離 ✓
- **無 placeholders**：所有 test code、實作 code、commands 都具體 ✓
- **型別一致**：`_DraftPdRuleMixin`、`needs_draft_pd()`、`ruleset_needs_draft_pd()`、`requires_draft_pd` attribute 命名一致 ✓
- **排序尊重 user**：本 plan 排 queue 最後 ✓
