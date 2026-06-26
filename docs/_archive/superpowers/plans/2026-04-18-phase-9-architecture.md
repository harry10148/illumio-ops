# Phase 9 Implementation Plan — 架構重構 (god-class 拆分 + 解耦)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解決 [Status.md](../../../Status.md) 所有 MEDIUM 級架構債：A1/A2/A3/A4/A5 + Q1/Q2/Q3。**不引入新套件**。依賴 Phase 7 完成後的乾淨 loguru 基礎（避免重構與 logger import 替換交雜）。

**Architecture:** **Sub-task-by-risk**。從 XS 到 XL 排序，每個子任務獨立 commit，每個完成後驗證全測試綠。facade pattern 保留 `ApiClient` 公開介面，拆出的三個 domain class (TrafficQueryBuilder / AsyncJobManager / LabelResolver) 以 composition 聚合。新增 `src/exceptions.py` 類型階層取代 silent fallback。

**Tech Stack:** 無新套件

**Branch:** `upgrade/phase-9-architecture`（from main **after Phase 7 merge**）

**Target tag on merge:** `v3.7.0-refactor`

**Parent roadmap:** [2026-04-18-upgrade-roadmap.md](2026-04-18-upgrade-roadmap.md)

---

## Sub-tasks in order (risk-low-to-high)

### Task 1: A5 — 移除 `events/shadow.py` (XS ~0.5 day)

- [ ] Confirm [src/events/shadow.py](../../../src/events/shadow.py) duplicates [src/events/matcher.py](../../../src/events/matcher.py) logic (grep callers; compare functions).
- [ ] If confirmed redundant: delete + remove imports.
- [ ] Add test in `tests/test_events_matcher.py` that covers any shadow-only behavior to prevent regression.
- [ ] Commit.

### Task 2: Q3 — 統一重複 `extract_id()` (XS ~0.5 day)

- [ ] Both [src/analyzer.py](../../../src/analyzer.py) + [src/rule_scheduler.py](../../../src/rule_scheduler.py) define similar helpers.
- [ ] Create `src/utils/href_utils.py` (or `src/href_utils.py` — keep utils.py as a single module per Phase 1 convention; add as top-level) with canonical `extract_id(href: str) -> str`.
- [ ] Update 2 callers to import + delete local copies.
- [ ] Commit.

### Task 3: A4 — Exception hierarchy + silent-fallback audit (M ~1.5 day)

- [ ] Create `src/exceptions.py`:
```python
"""Typed exception hierarchy for illumio_ops."""
class IllumioOpsError(Exception): pass
class APIError(IllumioOpsError): pass
class ConfigError(IllumioOpsError): pass
class ReportError(IllumioOpsError): pass
class AlertError(IllumioOpsError): pass
class SchedulerError(IllumioOpsError): pass
class EventError(IllumioOpsError): pass
```

- [ ] Audit `except: pass` + bare `except Exception:` across src/. Candidates (from 2026-04-13 code review):
  - [src/api_client.py](../../../src/api_client.py) async job poll fallbacks
  - [src/analyzer.py](../../../src/analyzer.py) format fallback chains
  - [src/gui.py](../../../src/gui.py) auth + before_request edge cases

- [ ] For each site: replace with typed exception + log (loguru) + either reraise or explicit default value. Document `# intentional fallback` where keeping silent is correct.

- [ ] Full suite + i18n audit. Commit per logical group.

### Task 4: Q1 — `Analyzer.run_analysis()` 196-line decomposition (M ~1.5 day)

- [ ] Read [src/analyzer.py::run_analysis](../../../src/analyzer.py) in full.

- [ ] Extract into private methods (no public API change):
  - `_fetch_traffic()` — API call + filtering
  - `_run_event_analysis()` — events pipeline
  - `_run_rule_engine()` — rule matching + trigger list
  - `_dispatch_alerts()` — collate + hand off to Reporter

- [ ] Each extracted method gets its own unit test in `tests/test_analyzer_decomposition.py` with fixtures from existing integration tests.

- [ ] Keep `run_analysis()` as orchestrator (~20 lines calling the 4 internals).

- [ ] Commit.

### Task 5: A3 + T1 consolidation — remove residual thread-safety debt (M ~1 day)

**Most of A3 + T1 already resolved in Phase 6** (APScheduler ThreadPoolExecutor + `_cache_lock` on TTLCaches). This task handles residuals.

- [ ] [src/gui.py `_rs_log_history`](../../../src/gui.py) — wrap in `threading.Lock` or swap for `collections.deque(maxlen=N)` which is atomic for append/clear.

- [ ] [src/module_log.py](../../../src/module_log.py) — module-level `_registry` dict: add lock around mutations, or use `threading.local()` per-module.

- [ ] [src/utils.py `_LAST_INPUT_ACTION`](../../../src/utils.py) — wrap in `InputState` singleton class with setter/getter method; backward-compat helpers `get_last_input_action()` / `_set_last_input_action()` preserved.

- [ ] [src/i18n.py `_current_lang`](../../../src/i18n.py) — wrap in `I18nState` singleton + `threading.Lock()` for set_language().

- [ ] Test concurrent read/write on each — commit per state.

### Task 6: A2 — `api_client.py` 2542 LOC god-class split (XL ~3 days)

**Keep ApiClient as facade; introduce 3 domain classes via composition.**

- [ ] Create `src/api/__init__.py` (package marker) + 3 modules:

- [ ] `src/api/traffic_query.py` — `TrafficQueryBuilder`:
  - Absorbs all `_build_async_traffic_query_*`, `_resolve_native_filter_*`, the async traffic query payload construction logic.
  - Takes an `ApiClient` reference for HTTP calls (composition, not inheritance).

- [ ] `src/api/async_jobs.py` — `AsyncJobManager`:
  - Absorbs `submit_async_job`, `poll_async_job`, `download_async_result`, async job cache management, `_prune_async_job_state`.
  - Owns the `_async_query_jobs` state dict + serialization.

- [ ] `src/api/labels.py` — `LabelResolver`:
  - Absorbs `update_label_cache`, `invalidate_labels`, `_ensure_query_lookup_cache`, label href resolution, label_group resolution, iplist resolution.
  - Owns the 5 TTLCaches previously on ApiClient (moved here; `_cache_lock` stays here too).

- [ ] `ApiClient.__init__` composes them:
```python
self._traffic = TrafficQueryBuilder(self)
self._jobs = AsyncJobManager(self)
self._labels = LabelResolver(self)
```

- [ ] **Every public method on ApiClient stays** — each now delegates to the appropriate domain class:
```python
def update_label_cache(self, *a, **kw): return self._labels.update_label_cache(*a, **kw)
def submit_async_traffic_query(self, *a, **kw): return self._jobs.submit_async_traffic_query(*a, **kw)
# ... etc
```

- [ ] The 50+ callers of `ApiClient` methods see no change.

- [ ] Run full suite after each domain extraction — commit per domain (3 commits).

- [ ] End target: `src/api_client.py` < 800 LOC (facade + constants + `_request()` + shared initializer).

### Task 7: A1 / Q2 — Protocol-based decoupling (L ~2 day)

- [ ] Create `src/interfaces.py` with `typing.Protocol` definitions:
```python
from typing import Protocol

class IApiClient(Protocol):
    def check_health(self) -> tuple[int, str]: ...
    def list_workloads(self) -> list[dict]: ...
    # ... only the methods Analyzer actually uses

class IReporter(Protocol):
    def send_alerts(self) -> None: ...

class IEventStore(Protocol):
    def append(self, event: dict) -> None: ...
```

- [ ] `Analyzer.__init__` type-annotate with Protocol:
```python
def __init__(self, cm, api: IApiClient, rep: IReporter):
    ...
```

- [ ] Write `tests/test_analyzer_with_mock_api.py` using a lightweight Protocol impl (not MagicMock) — proves the decoupling.

### Task 8: Final docs + merge (S ~0.5 day)

- [ ] Update Status.md: A1/A2/A3/A4/A5/Q1/Q2/Q3 all ✅; version `v3.7.0-refactor`.
- [ ] Update Task.md with Phase 9 completion block.
- [ ] Update [docs/Project_Architecture.md](../../../docs/Project_Architecture.md) + zh version: new `src/api/` package + Protocol interfaces.
- [ ] Push + PR + merge + tag `v3.7.0-refactor`.

---

## File Structure Summary

| Action | Files |
|---|---|
| Create | `src/exceptions.py`, `src/interfaces.py`, `src/href_utils.py`, `src/api/__init__.py`, `src/api/traffic_query.py`, `src/api/async_jobs.py`, `src/api/labels.py` |
| Delete | `src/events/shadow.py` |
| Modify | `src/api_client.py` (from 2542 LOC → < 800), `src/analyzer.py`, `src/rule_scheduler.py`, `src/gui.py`, `src/module_log.py`, `src/utils.py`, `src/i18n.py` |
| Test (new) | 4-6 new test files for decomposed components |

---

## 完成驗收清單

- [ ] `src/events/shadow.py` removed (A5)
- [ ] `src/href_utils.py` with canonical `extract_id()` (Q3)
- [ ] `src/exceptions.py` + silent-fallback sites converted (A4)
- [ ] `Analyzer.run_analysis()` < 30 lines orchestrating 4 private methods (Q1)
- [ ] All 4 global-mutable-state sites thread-safe (A3 + T1)
- [ ] `src/api_client.py` < 800 LOC (facade); 3 domain classes in `src/api/` (A2 + Q2)
- [ ] `src/interfaces.py` Protocol typings used by Analyzer (A1)
- [ ] 50+ ApiClient callers UNCHANGED (backward-compat invariant)
- [ ] All tests green; i18n audit 0 findings
- [ ] `v3.7.0-refactor` tag

---

## Rollback Strategy

Because Phase 9 is purely internal refactoring with facade preservation, `git revert v3.7.0-refactor` restores the pre-refactor monolith cleanly. Each sub-task's commit can also be reverted individually.

---

## 與 Phase 7 的關係

Phase 9 必須在 Phase 7 之後開工。原因：
- Phase 9 會修改 100+ 處 `logger` 呼叫（新增 error logging、替換 silent fallback）。若 Phase 7 還在用 stdlib logging，這些新增邏輯全部走舊 API，之後 Phase 7 的 codemod 還要再掃一次 Phase 9 新增的程式碼。
- 先做 Phase 7 後，Phase 9 新增的所有 logging 直接走 loguru `{}` 格式。

---

## 已知風險

1. **facade delegation 樣板代碼**：50+ `ApiClient` 公開方法都要寫 `def X(self, *a, **kw): return self._domain.X(*a, **kw)`。可用 metaclass 或 `__getattr__` 動態委派減少重複 — 但犧牲 IDE 補全 + 型別檢查。**決策保留給執行者**；mindlessly 寫明確 delegation 也可以。

2. **測試 mock 更新**：既有 test_api_client*.py 的 monkey-patching 可能打到舊的內部實作（例如 `api._request`）。facade 仍有 `_request`；但如果 test patches `api._label_cache`（現在在 `_labels._label_cache`）就會失敗。執行時逐個修復。

3. **shadow.py 可能仍被呼叫**：事前 grep callers（包括 test 檔 + scripts/）。若真有業務依賴，不刪除而改為 deprecation warning。
