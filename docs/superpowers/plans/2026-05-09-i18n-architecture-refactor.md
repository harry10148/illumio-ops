# i18n Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate three parallel i18n subsystems into one source-of-truth, replace the 46-rule regex auto-translator with a declarative glossary, parameterize language at the call site, and stop persisting translated text in rule storage.

**Architecture:** The codebase currently maintains three translation systems (`t()` over `i18n_*.json`, `STRINGS` dict in `report_i18n.py`, inline `dict[lang]` templates) with 195 duplicate keys, a 46-pattern regex auto-translator that hides glossary violations, and a `ConfigManager.load()` self-heal that exists only because rules persist eager-translated strings. This plan keeps `t()` as the single runtime API, demotes `STRINGS` to a thin compatibility wrapper that delegates to `t()`, externalizes the glossary and strict-prefix list to JSON data, pre-computes auto-translations once and removes the runtime regex chain, threads `lang=` through call sites that need multi-language rendering, and migrates rule storage to persist `desc_key`/`rec_key` instead of localized text.

**Tech Stack:** Python 3.12, pytest, pandas, loguru. Tests run with `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest`. Git operations use `/usr/bin/git` to bypass the rtk wrapper. Direct commits to `main` per project convention.

---

## File Structure

### Created
- `src/i18n/data/glossary.json` — preserve-list of English terms that must NOT be translated to zh_TW (Block, Allow, Manage, Unmanage, PCE, VEN, Workload, Service, Port, Policy, Ringfence, App, Label, SMTP, Online, Offline, etc.) plus violation patterns used by audit Cat E.
- `src/i18n/data/strict_prefixes.json` — array of key prefixes that must short-circuit to `[MISSING:key]` instead of humanize fallback. Replaces the 28-element `_STRICT_PREFIXES` tuple in `engine.py`.
- `scripts/migrate_strings_to_json.py` — one-shot migration that emits 467 only-STRINGS keys into `i18n_en.json` / `i18n_zh_TW.json`, reconciles 195 overlap keys, and writes a manifest to `scripts/migrate_strings_manifest.json` for audit.
- `scripts/precompute_zh_translations.py` — one-shot migration that runs every key with blank/missing zh_TW through the current `_translate_text()` pipeline and persists the result, so the runtime regex path can be retired.
- `scripts/migrate_rules_to_keys.py` — one-shot migration that walks `data/config.json` rules, detects known translations (or `[MISSING:*]` markers), and rewrites them to use `desc_key`/`rec_key` fields.
- `tests/test_i18n_strings_parity.py` — contract test asserting `STRINGS[k].get(lang) == t(k, lang=lang)` for every shared key.
- `tests/test_i18n_glossary.py` — asserts known glossary terms remain English in zh_TW values.
- `tests/test_i18n_lang_param.py` — asserts `t(key, lang="zh_TW")` and `t(key, lang="en")` work without mutating global state, including thread-concurrent calls.
- `tests/test_config_rule_keys.py` — asserts rules round-trip correctly when stored as keys.

### Modified
- `src/report/exporters/report_i18n.py` — `STRINGS` becomes a `_StringsView` wrapper class delegating to `t()`; the 662 inline `_entry(...)` definitions migrate to JSON; the dynamic loops (lines 872/873/896/1046/1090/1100) write through a runtime overlay that the wrapper merges on read.
- `src/i18n/engine.py` — `t()` gains `lang` kwarg; `_STRICT_PREFIXES` loaded from JSON; `_translate_text()` no longer called from `_build_messages()` runtime path (kept callable for migration scripts only); `_humanize_key_*()` calls log a warning so gaps are visible.
- `src/i18n_en.json` — grows from 2300 to ~2767 keys (absorbs 467 from STRINGS).
- `src/i18n_zh_TW.json` — same growth + every key gains an explicit zh_TW value (no more runtime regex synthesis).
- `src/config.py` — `ConfigManager.load()` self-heal removed; rule schema accepts `desc_key`/`rec_key` and resolves them at read time.
- `src/reporter.py` — `_REC_I18N_KEYS` becomes the canonical rec-key map; readers prefer `rec_key` over `rec` text.
- `scripts/audit_i18n_usage.py` — Cat E loads glossary from `glossary.json`; Cat I expanded to cover the merged key set.
- The 9 STRINGS-consumer files (`pdf_exporter.py`, `audit_html_exporter.py`, `ven_html_exporter.py`, `policy_usage_html_exporter.py`, `_exec_summary.py`, `html_exporter.py`, `chart_renderer.py`, `table_renderer.py`, `report_i18n.py`) — no callsite changes; the wrapper keeps the `STRINGS[k].get(lang)` shape working.
- The 6 `set_language()` callers (`config.py:185,268`, `report_generator.py:338,529,573`, `gui/routes/events.py:300`) — converted to pass `lang=` explicitly where the call is request-scoped; only CLI bootstrap retains global mutation.

### Deleted (after migrations validated)
- 662 inline `_entry()` definitions inside `STRINGS = _StringMap({...})` block in `report_i18n.py` (lines 16-861, approximately).
- Static `replacements` regex list inside `_translate_text()` in `engine.py:189-249`.
- `_STRICT_PREFIXES` tuple literal in `engine.py:62-68`.

---

## Phases

- **Phase 1 (R1, Tasks 1-7):** Single source of truth. Merge STRINGS into JSON; STRINGS becomes a delegating wrapper. Outcome: zero key duplication; one place to add a translation.
- **Phase 2 (R2, Tasks 8-12):** Externalize glossary and strict prefixes; pre-compute zh_TW values; demote regex pile to migration-only. Outcome: glossary violations become machine-checkable; runtime path has no auto-translation magic.
- **Phase 3 (R3, Tasks 13-16):** `t(key, lang=...)` parameter; migrate request-scoped callers off `set_language()`. Outcome: concurrent multi-language rendering is safe.
- **Phase 4 (R4, Tasks 17-20):** Rules persist `desc_key`/`rec_key` instead of localized text; remove ConfigManager self-heal. Outcome: rule storage is language-agnostic; no more `[MISSING:*]` self-heal band-aid.
- **Phase 5 (Tasks 21-22):** Final audit + docs. Outcome: `audit_i18n_usage.py` exits 0; CLAUDE.md / README captures the new contract.

Each phase ends in a working, shippable state. Phase boundaries are natural rollback points.

---

## Phase 1 — Single Source of Truth (R1)

### Task 1: Add STRINGS↔t() parity contract test

**Files:**
- Test: `tests/test_i18n_strings_parity.py`

- [ ] **Step 1: Write the failing test**

```python
"""Phase 1 contract: STRINGS and t() must agree for every shared key."""
from __future__ import annotations

import pytest

from src.i18n import t
from src.report.exporters.report_i18n import STRINGS


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_strings_matches_t_for_all_shared_keys(lang: str) -> None:
    from src.i18n.engine import EN_MESSAGES

    json_keys = set(EN_MESSAGES.keys())
    strings_keys = set(STRINGS.keys())
    shared = json_keys & strings_keys

    mismatches: list[tuple[str, str, str]] = []
    for key in shared:
        from_strings = STRINGS[key].get(lang) or STRINGS[key]["en"]
        from_t = t(key, lang=lang) if "lang" in t.__code__.co_varnames else t(key)
        if from_strings != from_t:
            mismatches.append((key, from_strings, from_t))

    assert not mismatches, (
        f"{len(mismatches)} keys disagree between STRINGS and t() at lang={lang}. "
        f"First 5: {mismatches[:5]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strings_parity.py -v`
Expected: FAIL — both lang parametrizations report mismatches (the 195 overlap keys today have divergent values in many cases).

- [ ] **Step 3: Capture baseline mismatch report for migration**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strings_parity.py -v 2>&1 | tee /tmp/strings_parity_baseline.txt`

This is the artifact the migration script (Task 4) consumes to decide canonical values.

- [ ] **Step 4: Commit the failing test (xfail-marked so CI stays green during migration)**

Edit the test to add `@pytest.mark.xfail(reason="Phase 1 migration in progress; removed in Task 7", strict=False)` at the top of `test_strings_matches_t_for_all_shared_keys`.

```bash
/usr/bin/git add tests/test_i18n_strings_parity.py
/usr/bin/git commit -m "test(i18n): add STRINGS↔t() parity contract (xfail until Phase 1 done)"
```

---

### Task 2: Migration script — emit only-STRINGS keys to JSON

**Files:**
- Create: `scripts/migrate_strings_to_json.py`
- Test: `tests/test_migrate_strings_script.py`

- [ ] **Step 1: Write the failing test**

```python
"""Phase 1 migration script writes a deterministic manifest."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_emits_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "migrate_strings_to_json.py"),
            "--dry-run",
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": f"{ROOT}:{ROOT}/venv/lib/python3.12/site-packages"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["only_in_strings"] >= 400, "expect ~467 only-STRINGS keys"
    assert data["overlap"] >= 100, "expect ~195 overlap keys"
    assert "samples" in data and len(data["samples"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_migrate_strings_script.py -v`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement the migration script**

```python
# scripts/migrate_strings_to_json.py
"""Migrate STRINGS dict → i18n_*.json. Dry-run first, apply with --write."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.report.exporters.report_i18n import STRINGS  # noqa: E402

EN_PATH = ROOT / "src" / "i18n_en.json"
ZH_PATH = ROOT / "src" / "i18n_zh_TW.json"


def _load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict[str, str]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Apply changes")
    parser.add_argument("--dry-run", action="store_true", help="Report only")
    parser.add_argument("--manifest", type=Path, default=ROOT / "scripts" / "migrate_strings_manifest.json")
    parser.add_argument("--prefer", choices=["strings", "json"], default="strings",
                        help="Canonical source for overlap keys (default: strings — newer)")
    args = parser.parse_args()

    en = _load(EN_PATH)
    zh = _load(ZH_PATH)

    string_keys = set(STRINGS.keys())
    en_keys = set(en.keys())
    only_strings = string_keys - en_keys
    overlap = string_keys & en_keys

    additions_en: dict[str, str] = {}
    additions_zh: dict[str, str] = {}
    overlap_changes: list[tuple[str, str, str]] = []

    for key in only_strings:
        entry = STRINGS[key]
        additions_en[key] = entry["en"]
        additions_zh[key] = entry.get("zh_TW") or entry["en"]

    for key in overlap:
        s_en = STRINGS[key]["en"]
        s_zh = STRINGS[key].get("zh_TW") or s_en
        if s_en != en.get(key) or s_zh != zh.get(key):
            overlap_changes.append((key, en.get(key, ""), s_en))
            if args.prefer == "strings":
                additions_en[key] = s_en
                additions_zh[key] = s_zh

    manifest = {
        "only_in_strings": len(only_strings),
        "overlap": len(overlap),
        "overlap_changes": len(overlap_changes),
        "samples": list(only_strings)[:10] + [c[0] for c in overlap_changes[:10]],
        "prefer": args.prefer,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.write:
        en.update(additions_en)
        zh.update(additions_zh)
        _save(EN_PATH, en)
        _save(ZH_PATH, zh)
        print(f"WROTE: +{len(additions_en)} en keys, +{len(additions_zh)} zh keys")
    else:
        print(f"DRY-RUN: would add {len(additions_en)} en, {len(additions_zh)} zh; "
              f"would change {len(overlap_changes)} overlap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_migrate_strings_script.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add scripts/migrate_strings_to_json.py tests/test_migrate_strings_script.py
/usr/bin/git commit -m "feat(i18n): migration script for STRINGS → JSON consolidation"
```

---

### Task 3: Apply migration — only-STRINGS keys

**Files:**
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json` (data only)
- Test: existing `tests/test_i18n_audit.py` must still pass

- [ ] **Step 1: Run dry-run to confirm scope**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/migrate_strings_to_json.py --dry-run`
Expected output: `DRY-RUN: would add ~467 en, ~467 zh; would change ~195 overlap`

Read `scripts/migrate_strings_manifest.json` and inspect a sample of `only_in_strings` entries to spot-check (e.g., glossary respect on `rpt_col_app_env`).

- [ ] **Step 2: Apply the migration**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/migrate_strings_to_json.py --write --prefer strings`
Expected: `WROTE: +467 en keys, +467 zh keys` (numbers ±10 OK; manifest is the source of truth).

- [ ] **Step 3: Verify audit still clean**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py`
Expected: exit code 0; no Cat E (glossary) or Cat F (placeholder) regressions.

If glossary regressions appear (e.g., a STRINGS-only key had "Service" translated), revert with `/usr/bin/git checkout src/i18n_en.json src/i18n_zh_TW.json`, fix the offending entries in `report_i18n.py`, re-run.

- [ ] **Step 4: Run full test suite**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ -x --ignore=tests/test_i18n_strings_parity.py 2>&1 | tail -20`
Expected: all tests pass (parity test is xfail; rest unaffected because callers still read from STRINGS).

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add src/i18n_en.json src/i18n_zh_TW.json scripts/migrate_strings_manifest.json
/usr/bin/git commit -m "i18n(data): absorb 467 only-STRINGS keys into i18n_*.json (Phase 1)"
```

---

### Task 4: Reconcile overlap keys

**Files:**
- Modify: `src/report/exporters/report_i18n.py` (delete static `_entry()` calls for keys now in JSON)

- [ ] **Step 1: Identify the static block to delete**

The 662 inline `_entry()` calls live inside `STRINGS = _StringMap({...})` at `src/report/exporters/report_i18n.py` lines 16-861 (approximately). Dynamic writes at 872, 873, 896, 1046, 1090, 1100 stay — those are loops over runtime data.

- [ ] **Step 2: Replace static block with empty dict (delete the entries, keep the variable)**

Read `src/report/exporters/report_i18n.py` to confirm the exact closing line of the static block, then edit:

```python
# Before (line 16):
STRINGS: _StringMap = _StringMap({
    "rpt_generated": _entry("Generated:", "產出時間："),
    ... 662 entries ...
})

# After:
STRINGS: _StringMap = _StringMap()  # Static entries migrated to i18n_*.json (Phase 1)
```

The dynamic loops below (line 872+) continue to write into `STRINGS[...]` — those become a runtime overlay until Task 5 wraps it.

- [ ] **Step 3: Run parity test to confirm STRINGS now reads from JSON via __missing__**

The current `_StringMap.__missing__` returns `{"en": key, "zh_TW": key}` — this is wrong for our case. Update `__missing__` to delegate to `t()`:

```python
# src/report/exporters/report_i18n.py
class _StringMap(dict):
    def __missing__(self, key: str) -> dict[str, str]:
        if os.getenv("ILLUMIO_OPS_I18N_STRICT"):
            raise KeyError(f"Missing i18n key: {key}")
        from src.i18n import t
        return {"en": t(key, lang="en"), "zh_TW": t(key, lang="zh_TW")}
```

Note: this introduces a forward dependency on Task 13's `lang=` kwarg. To stay TDD-compliant in Phase 1, use the temporary shim pattern below until Task 13 lands:

```python
def __missing__(self, key: str) -> dict[str, str]:
    if os.getenv("ILLUMIO_OPS_I18N_STRICT"):
        raise KeyError(f"Missing i18n key: {key}")
    from src.i18n.engine import _build_messages
    return {"en": _build_messages("en").get(key, key),
            "zh_TW": _build_messages("zh_TW").get(key, key)}
```

The shim reads from `_build_messages` cache directly (zero global-language mutation) and is replaced in Task 5.

- [ ] **Step 4: Run parity test**

Edit `tests/test_i18n_strings_parity.py` to remove the `xfail` marker (we expect it to pass now for the static-key path):

```python
# Remove this line:
# @pytest.mark.xfail(reason="Phase 1 migration in progress; removed in Task 7", strict=False)
```

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strings_parity.py -v`
Expected: PASS for both `lang=en` and `lang=zh_TW`.

If a small number of mismatches remain, they are in the dynamic-write keys (rpt_cat_*, rpt_rule_*_how, etc.) — those are addressed in Task 5.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add src/report/exporters/report_i18n.py tests/test_i18n_strings_parity.py
/usr/bin/git commit -m "refactor(i18n): delete 662 static STRINGS entries; delegate to t() (Phase 1)"
```

---

### Task 5: Replace `_StringMap` with `_StringsView` wrapper

**Files:**
- Modify: `src/report/exporters/report_i18n.py`
- Test: extend `tests/test_i18n_strings_parity.py`

- [ ] **Step 1: Write the failing test (dynamic-write keys must still work)**

```python
def test_strings_supports_dynamic_writes() -> None:
    """report_i18n.py writes runtime keys at module load (rpt_cat_*, rpt_rule_*).

    The wrapper must accept STRINGS[k] = entry without breaking subsequent reads.
    """
    from src.report.exporters.report_i18n import STRINGS

    test_key = "_test_dynamic_write_unique"
    STRINGS[test_key] = {"en": "Hello", "zh_TW": "你好"}
    try:
        assert STRINGS[test_key]["en"] == "Hello"
        assert STRINGS[test_key].get("zh_TW") == "你好"
    finally:
        del STRINGS[test_key]


def test_strings_unknown_key_falls_through_to_t() -> None:
    """Keys not statically written must resolve via t() (post-migration)."""
    from src.report.exporters.report_i18n import STRINGS

    # rpt_kicker_traffic exists in JSON now (migrated in Task 3)
    entry = STRINGS["rpt_kicker_traffic"]
    assert entry["en"] == "Traffic Analytics Report"
    assert "流量" in entry["zh_TW"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strings_parity.py::test_strings_unknown_key_falls_through_to_t tests/test_i18n_strings_parity.py::test_strings_supports_dynamic_writes -v`
Expected: PASS (Task 4's `__missing__` already routes through `_build_messages`; this is a regression-prevention test).

- [ ] **Step 3: Replace `_StringMap` with explicit `_StringsView`**

Edit `src/report/exporters/report_i18n.py`:

```python
"""Shared i18n helpers for HTML report exporters.

After Phase 1 migration, STRINGS is a _StringsView that:
  - Stores runtime overlay entries (dynamic writes from this module's bottom loops)
  - Falls back to t() for any key not in the overlay
  - Preserves the dict-like API (subscript, .get, __setitem__, __delitem__,
    __contains__, keys()) that 9 exporter files depend on.
"""
from __future__ import annotations

import os
from typing import Iterator


class _StringsView:
    """Compatibility layer over a runtime overlay + t()-backed JSON."""

    def __init__(self) -> None:
        self._overlay: dict[str, dict[str, str]] = {}

    def __getitem__(self, key: str) -> dict[str, str]:
        if key in self._overlay:
            return self._overlay[key]
        if os.getenv("ILLUMIO_OPS_I18N_STRICT"):
            from src.i18n.engine import EN_MESSAGES
            if key not in EN_MESSAGES:
                raise KeyError(f"Missing i18n key: {key}")
        from src.i18n import t
        return {"en": t(key, lang="en"), "zh_TW": t(key, lang="zh_TW")}

    def __setitem__(self, key: str, value: dict[str, str]) -> None:
        self._overlay[key] = value

    def __delitem__(self, key: str) -> None:
        del self._overlay[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self._overlay:
            return True
        from src.i18n.engine import EN_MESSAGES
        return key in EN_MESSAGES

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> Iterator[str]:
        from src.i18n.engine import EN_MESSAGES
        seen: set[str] = set()
        for k in self._overlay:
            seen.add(k)
            yield k
        for k in EN_MESSAGES:
            if k not in seen:
                yield k


def _entry(en: str, zh_tw: str | None = None) -> dict[str, str]:
    return {"en": en, "zh_TW": zh_tw or en}


STRINGS: _StringsView = _StringsView()
```

The dynamic-write loops further down (rpt_cat_*, rpt_rule_*_how, etc.) work unchanged — `STRINGS[k] = _entry(...)` still routes through `__setitem__`.

- [ ] **Step 4: Run full parity + dynamic-write tests**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strings_parity.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Run full suite to catch unrelated breakage**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ -x 2>&1 | tail -20`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/report/exporters/report_i18n.py tests/test_i18n_strings_parity.py
/usr/bin/git commit -m "refactor(i18n): STRINGS becomes _StringsView wrapper over t() (Phase 1)"
```

---

### Task 6: Verify all 9 STRINGS-consumer files still work

**Files:**
- No code changes. Test extension only.
- Test: `tests/test_i18n_consumers_smoke.py`

- [ ] **Step 1: Write smoke test that exercises each consumer**

```python
"""Phase 1 smoke: every STRINGS consumer renders without error in en + zh_TW."""
from __future__ import annotations

import pandas as pd
import pytest

from src.report.exporters.report_i18n import STRINGS

CONSUMER_KEYS_TO_PROBE = [
    "rpt_generated",
    "rpt_kicker_traffic",
    "rpt_pill_flows",
    "rpt_col_action",
    "rpt_no_records",
    "rpt_table_hint",
]


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
@pytest.mark.parametrize("key", CONSUMER_KEYS_TO_PROBE)
def test_strings_subscript_get_pattern(key: str, lang: str) -> None:
    """The 9 consumer files use STRINGS[k].get(lang) or STRINGS[k]['en']."""
    entry = STRINGS[key]
    val = entry.get(lang) or entry["en"]
    assert isinstance(val, str) and val
    assert not val.startswith("[MISSING:"), f"{key} at {lang} returned MISSING marker"


def test_table_renderer_consumes_no_data_key() -> None:
    """table_renderer.py uses _STRINGS[no_data_key].get(lang) at line 25."""
    from src.report.exporters.table_renderer import render_df_table

    empty_df = pd.DataFrame()
    html_en = render_df_table(empty_df, no_data_key="rpt_no_records", lang="en")
    html_zh = render_df_table(empty_df, no_data_key="rpt_no_records", lang="zh_TW")
    assert "No records" in html_en
    assert "沒有記錄" in html_zh
```

- [ ] **Step 2: Run smoke**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_consumers_smoke.py -v`
Expected: PASS.

- [ ] **Step 3: Visual smoke — generate one HTML report and inspect**

Run:
```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -c "
from src.i18n import set_language
set_language('zh_TW')
from src.report.report_generator import generate_report
generate_report('traffic_flow', output_dir='/tmp/i18n_smoke', lang='zh_TW')
"
```

Then `grep -c '\[MISSING:' /tmp/i18n_smoke/*.html` — expect 0 hits.

If any `[MISSING:*]` appear, capture the key and check whether it's a Phase 2 issue (regex fallback was masking a gap that's now visible). Add to `i18n_zh_TW.json` and re-run.

- [ ] **Step 4: Commit**

```bash
/usr/bin/git add tests/test_i18n_consumers_smoke.py
/usr/bin/git commit -m "test(i18n): smoke test for 9 STRINGS-consumer exporters (Phase 1)"
```

---

### Task 7: Remove `_StringMap` legacy and close Phase 1

**Files:**
- Modify: `src/report/exporters/report_i18n.py` (remove dead `_StringMap` if any references remain)

- [ ] **Step 1: Confirm no references to `_StringMap` remain**

Run: `grep -rn '_StringMap' --include='*.py' src/ tests/ scripts/`
Expected: no matches (Task 5 already replaced the class). If any straggler references exist, replace them with `_StringsView`.

- [ ] **Step 2: Remove `xfail` markers added in Task 1**

Already done in Task 4 Step 4. Verify:

Run: `grep -n 'xfail' tests/test_i18n_strings_parity.py`
Expected: no matches (or only test-of-test markers).

- [ ] **Step 3: Final Phase 1 audit**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py`
Expected: exit 0.

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ 2>&1 | tail -5`
Expected: all pass.

- [ ] **Step 4: Commit Phase 1 close**

```bash
/usr/bin/git add -u
/usr/bin/git commit --allow-empty -m "refactor(i18n): close Phase 1 — single source of truth (R1 done)"
```

---

## Phase 2 — Externalize Glossary, Demote Regex (R2)

### Task 8: Create `src/i18n/data/glossary.json`

**Files:**
- Create: `src/i18n/data/glossary.json`
- Test: `tests/test_i18n_glossary.py`

- [ ] **Step 1: Write the failing test**

```python
"""Glossary data file is the single source of truth for English-preserved terms."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_PATH = ROOT / "src" / "i18n" / "data" / "glossary.json"


def test_glossary_loads_and_has_required_terms() -> None:
    data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    preserve = set(data["preserve_in_zh_tw"])
    required = {
        "Block", "Blocked", "Allow", "Allowed", "Manage", "Managed",
        "Unmanage", "Unmanaged", "PCE", "VEN", "Workload", "Service",
        "Port", "Policy", "Ringfence", "App", "Label", "SMTP",
        "Online", "Offline", "Potentially Blocked",
    }
    missing = required - preserve
    assert not missing, f"glossary missing required terms: {missing}"


def test_zh_tw_values_preserve_glossary_terms() -> None:
    """For every key whose en value contains a glossary term as a whole word,
    the zh_TW value must also contain it as-is (not a Chinese substitute)."""
    en = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    zh = json.loads((ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    preserve = glossary["preserve_in_zh_tw"]
    forbidden_translations = glossary["forbidden_zh_substitutes"]  # e.g., {"Service": ["服務"]}

    violations: list[tuple[str, str, str]] = []
    for key, en_val in en.items():
        zh_val = zh.get(key, "")
        if not isinstance(en_val, str) or not isinstance(zh_val, str):
            continue
        for term in preserve:
            if re.search(rf"\b{re.escape(term)}\b", en_val):
                # Must appear in zh too, AND the forbidden Chinese substitute must NOT.
                if term not in zh_val:
                    violations.append((key, term, zh_val))
                for bad in forbidden_translations.get(term, []):
                    if bad in zh_val:
                        violations.append((key, f"{term}->{bad}", zh_val))

    assert not violations, f"{len(violations)} glossary violations. First 5: {violations[:5]}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_glossary.py -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Create `src/i18n/data/glossary.json`**

```json
{
  "_doc": "Glossary preserve-list. Terms here MUST remain English in zh_TW translations. forbidden_zh_substitutes lists Chinese strings that, if present, indicate a glossary violation.",
  "preserve_in_zh_tw": [
    "Block", "Blocked", "Blocking", "Allow", "Allowed", "Allowing",
    "Potentially Blocked",
    "Manage", "Managed", "Managing", "Unmanage", "Unmanaged",
    "PCE", "VEN", "Workload", "Workloads",
    "Service", "Services",
    "Port", "Ports",
    "Policy", "Policies",
    "Ringfence",
    "App", "Apps",
    "Label", "Labels",
    "SMTP",
    "Online", "Offline",
    "Enforcement",
    "Ruleset", "Rulesets"
  ],
  "forbidden_zh_substitutes": {
    "Block": ["封鎖", "阻擋"],
    "Blocked": ["已封鎖", "已阻擋"],
    "Allow": ["允許"],
    "Allowed": ["已允許"],
    "Manage": ["管理"],
    "Managed": ["已管理", "受管"],
    "Unmanaged": ["未管理"],
    "Service": ["服務"],
    "Workload": ["工作負載"],
    "Port": ["連接埠", "埠口"],
    "Policy": ["政策", "策略"]
  }
}
```

- [ ] **Step 4: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_glossary.py -v`
Expected: PASS for `test_glossary_loads_and_has_required_terms`. The second test may FAIL if existing JSON has glossary violations — capture them, fix one-by-one in `i18n_zh_TW.json`, re-run until clean.

If the second test reports >50 violations, mark it `xfail` and resolve in Task 11's pre-compute pass instead. Document the deferral in the commit message.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add src/i18n/data/glossary.json tests/test_i18n_glossary.py src/i18n_zh_TW.json
/usr/bin/git commit -m "feat(i18n): externalize glossary preserve-list to JSON (Phase 2)"
```

---

### Task 9: Migrate `_STRICT_PREFIXES` tuple → JSON

**Files:**
- Create: `src/i18n/data/strict_prefixes.json`
- Modify: `src/i18n/engine.py:62-77`
- Test: `tests/test_i18n_strict_prefixes.py`

- [ ] **Step 1: Write the failing test**

```python
"""Strict prefixes drive [MISSING:key] short-circuit; must load from JSON."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX_PATH = ROOT / "src" / "i18n" / "data" / "strict_prefixes.json"


def test_strict_prefixes_loads() -> None:
    data = json.loads(PREFIX_PATH.read_text(encoding="utf-8"))
    prefixes = set(data["prefixes"])
    assert "gui_" in prefixes
    assert "rpt_" in prefixes
    assert "rule_" in prefixes
    assert len(prefixes) >= 25


def test_strict_prefixes_used_by_engine() -> None:
    from src.i18n.engine import _is_strict_surface_key
    assert _is_strict_surface_key("gui_settings_save")
    assert _is_strict_surface_key("rpt_col_action")
    assert not _is_strict_surface_key("event_label_xyz")  # exception
    assert not _is_strict_surface_key("cat_unmanaged")    # exception
    assert not _is_strict_surface_key("random_key")       # not a strict prefix
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strict_prefixes.py -v`
Expected: FAIL — `strict_prefixes.json` does not exist.

- [ ] **Step 3: Create the JSON file**

```json
{
  "_doc": "Key prefixes that short-circuit to [MISSING:key] instead of humanize fallback. Adding a domain? Append the prefix here. exceptions are keys that match a prefix but should still humanize.",
  "prefixes": [
    "gui_", "sched_", "rs_", "wgs_", "login_", "cli_", "main_",
    "settings_", "rpt_", "menu_", "ven_", "pu_", "report_",
    "error_", "alert_", "daemon_", "line_", "mail_", "webhook_",
    "event_", "confirm_", "select_", "step_", "metric_", "pd_",
    "filter_", "ex_", "rule_", "trigger_", "pill_"
  ],
  "exceptions": ["event_label_", "cat_"]
}
```

- [ ] **Step 4: Update engine to load from JSON**

Edit `src/i18n/engine.py` lines 62-77 (replace the hardcoded tuple + `_is_strict_surface_key`):

```python
# src/i18n/engine.py — replace lines 62-77
def _load_strict_prefixes() -> tuple[tuple[str, ...], tuple[str, ...]]:
    path = Path(__file__).parent / "data" / "strict_prefixes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(data["prefixes"]), tuple(data["exceptions"])


_STRICT_PREFIXES, _STRICT_EXCEPTIONS = _load_strict_prefixes()


def _is_strict_surface_key(key: str) -> bool:
    if any(key.startswith(exc) for exc in _STRICT_EXCEPTIONS):
        return False
    return key.startswith(_STRICT_PREFIXES)
```

- [ ] **Step 5: Run test + full suite**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_strict_prefixes.py tests/test_i18n_audit.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/i18n/data/strict_prefixes.json src/i18n/engine.py tests/test_i18n_strict_prefixes.py
/usr/bin/git commit -m "refactor(i18n): externalize _STRICT_PREFIXES tuple to JSON (Phase 2)"
```

---

### Task 10: Audit `_translate_text()` runtime invocations

**Files:**
- Test: `tests/test_i18n_translate_text_audit.py`

- [ ] **Step 1: Write a test that asserts `_translate_text()` is only called from migration code**

```python
"""Phase 2 invariant: _translate_text() must not run in the t() hot path."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "src" / "i18n" / "engine.py"


def test_translate_text_not_called_from_build_messages() -> None:
    """Walk engine.py AST: _build_messages must NOT invoke _translate_text."""
    import ast
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_messages":
            calls = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_translate_text"
            ]
            assert not calls, (
                f"_build_messages still invokes _translate_text at lines "
                f"{[c.lineno for c in calls]}; Phase 2 requires removing this."
            )
            return
    raise AssertionError("_build_messages function not found in engine.py")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_translate_text_audit.py -v`
Expected: FAIL — `_build_messages` currently calls `_translate_text` at line ~304.

- [ ] **Step 3: This test stays failing until Task 12.** Mark `xfail`:

```python
import pytest

@pytest.mark.xfail(reason="Removed in Task 12 (precompute then drop runtime path)", strict=True)
def test_translate_text_not_called_from_build_messages() -> None:
    ...
```

- [ ] **Step 4: Commit**

```bash
/usr/bin/git add tests/test_i18n_translate_text_audit.py
/usr/bin/git commit -m "test(i18n): assert _translate_text exits hot path after Task 12 (xfail)"
```

---

### Task 11: Pre-compute zh_TW for every key, persist to JSON

**Files:**
- Create: `scripts/precompute_zh_translations.py`
- Test: `tests/test_precompute_zh_script.py`

- [ ] **Step 1: Write the failing test**

```python
"""Pre-compute script must produce a zh_TW value for every en key, glossary-clean."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_precompute_dry_run() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "precompute_zh_translations.py"), "--dry-run"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": f"{ROOT}:{ROOT}/venv/lib/python3.12/site-packages"},
    )
    assert result.returncode == 0, result.stderr
    assert "would update" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_precompute_zh_script.py -v`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement the pre-compute script**

```python
# scripts/precompute_zh_translations.py
"""Phase 2: persist every key's zh_TW value into i18n_zh_TW.json.

Drains _translate_text(), zh_explicit, and humanize fallbacks into static JSON
so the runtime can stop calling them. Idempotent: running twice is a no-op.

After this lands, _build_messages can be simplified to a pure dictionary lookup
(plus strict-prefix MISSING marker), and _translate_text becomes migration-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.i18n.engine import (  # noqa: E402
    EN_MESSAGES,
    ZH_MESSAGES,
    _ZH_EXPLICIT,
    _humanize_key_zh,
    _is_strict_surface_key,
    _translate_text,
)

ZH_PATH = ROOT / "src" / "i18n_zh_TW.json"
GLOSSARY_PATH = ROOT / "src" / "i18n" / "data" / "glossary.json"


def _resolve_zh(key: str, en_val: str) -> str:
    """Replicate the legacy _build_messages('zh_TW') resolution order, but as data."""
    if _is_strict_surface_key(key):
        return f"[MISSING:{key}]"
    if key in _ZH_EXPLICIT:
        return _ZH_EXPLICIT[key]
    if isinstance(en_val, str) and en_val:
        translated = _translate_text(en_val)
        if translated and translated != en_val:
            return translated
    return _humanize_key_zh(key)


def _check_glossary(zh_val: str) -> list[str]:
    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    bad = []
    for term, substitutes in glossary["forbidden_zh_substitutes"].items():
        for sub in substitutes:
            if sub in zh_val:
                bad.append(f"{term}->{sub}")
    return bad


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    zh_now = dict(ZH_MESSAGES)
    updates: dict[str, str] = {}
    glossary_violations: list[tuple[str, list[str]]] = []

    for key, en_val in EN_MESSAGES.items():
        existing = zh_now.get(key, "").strip()
        if existing and not existing.startswith("[MISSING:"):
            continue
        resolved = _resolve_zh(key, en_val)
        bad = _check_glossary(resolved)
        if bad:
            glossary_violations.append((key, bad))
        updates[key] = resolved

    if glossary_violations:
        print(f"GLOSSARY VIOLATIONS ({len(glossary_violations)}):")
        for key, bad in glossary_violations[:20]:
            print(f"  {key}: {bad}")
        print("Fix the offending en strings or add to phrase_overrides.json before --write.")
        return 1

    if args.write:
        zh_now.update(updates)
        ZH_PATH.write_text(
            json.dumps(zh_now, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE: {len(updates)} new zh_TW entries")
    else:
        print(f"DRY-RUN: would update {len(updates)} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run dry-run, fix any glossary violations**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/precompute_zh_translations.py --dry-run`

If violations are reported (e.g., "Service->服務" because the EN string is "Service unavailable"), update `src/i18n/data/phrase_overrides.json` to add a glossary-respecting Chinese version, then re-run.

- [ ] **Step 5: Apply migration**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/precompute_zh_translations.py --write`
Expected: `WROTE: <N> new zh_TW entries`.

- [ ] **Step 6: Run pytest, audit, glossary test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_glossary.py tests/test_i18n_audit.py tests/test_precompute_zh_script.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
/usr/bin/git add scripts/precompute_zh_translations.py tests/test_precompute_zh_script.py src/i18n_zh_TW.json src/i18n/data/phrase_overrides.json
/usr/bin/git commit -m "feat(i18n): pre-compute zh_TW for all keys; remove runtime translation chain (Phase 2)"
```

---

### Task 12: Drop `_translate_text()` from runtime path

**Files:**
- Modify: `src/i18n/engine.py:275-309` (`_build_messages`)
- Test: un-xfail `tests/test_i18n_translate_text_audit.py`

- [ ] **Step 1: Edit `_build_messages` to skip `_translate_text` and `_humanize_key_zh`**

The post-Phase 2 contract: every key has an explicit zh_TW value. Missing → `[MISSING:key]` for strict-prefix keys, raw key for non-strict (with a logged warning so we can find gaps).

Replace `_build_messages` (engine.py:275-309):

```python
@lru_cache(maxsize=2)
def _build_messages(lang: str) -> dict[str, str]:
    """Phase 2 simplified: pure dictionary lookup. No regex, no humanize.

    Pre-compute migration (Task 11) populated every key's zh_TW value.
    Runtime gaps surface as [MISSING:key] (strict prefixes) or logged warnings.
    """
    en_messages = _normalized_en_messages()
    if lang == "en":
        base = dict(en_messages)
        for key in en_messages:
            if not isinstance(base.get(key), str) or not base[key].strip():
                base[key] = _missing_marker(key) if _is_strict_surface_key(key) else key
        return base

    zh_messages = _normalized_zh_messages()
    base: dict[str, str] = {}
    for key in en_messages:
        zh_text = zh_messages.get(key)
        if isinstance(zh_text, str) and zh_text.strip():
            base[key] = zh_text
            continue
        if _is_strict_surface_key(key):
            base[key] = _missing_marker(key)
            continue
        # Non-strict gap — log once and return the raw key as visible signal.
        from loguru import logger
        logger.warning(f"i18n: zh_TW gap for non-strict key '{key}'; returning raw key")
        base[key] = key
    return base
```

`_translate_text`, `_humanize_key_zh`, `_humanize_key_en` stay in the file (migration scripts use them) but are no longer called from `_build_messages`.

- [ ] **Step 2: Un-xfail the audit test from Task 10**

Edit `tests/test_i18n_translate_text_audit.py` — remove the `@pytest.mark.xfail` decorator.

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_translate_text_audit.py tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: all PASS.

- [ ] **Step 4: Visual smoke**

Run the same HTML generation as Task 6 Step 3. Then:
```bash
grep -c '\[MISSING:' /tmp/i18n_smoke/*.html
```
Expected: 0. If non-zero, the missing keys leaked through Phase 2's pre-compute (likely added between Task 11 and now); add them to `i18n_zh_TW.json` manually or re-run Task 11's script.

- [ ] **Step 5: Commit Phase 2 close**

```bash
/usr/bin/git add src/i18n/engine.py tests/test_i18n_translate_text_audit.py
/usr/bin/git commit -m "refactor(i18n): remove _translate_text from t() hot path (Phase 2 done — R2)"
```

---

## Phase 3 — `lang=` Parameter (R3)

### Task 13: Add `lang` kwarg to `t()`

**Files:**
- Modify: `src/i18n/engine.py:317-335`
- Test: `tests/test_i18n_lang_param.py`

- [ ] **Step 1: Write the failing test**

```python
"""Phase 3: t(key, lang=...) must work without mutating global state."""
from __future__ import annotations

import threading

from src.i18n import t, get_language, set_language


def test_t_accepts_lang_kwarg() -> None:
    set_language("en")
    val_en = t("rpt_kicker_traffic", lang="en")
    val_zh = t("rpt_kicker_traffic", lang="zh_TW")
    assert val_en == "Traffic Analytics Report"
    assert "流量" in val_zh
    assert get_language() == "en", "lang= kwarg must NOT mutate global state"


def test_t_default_uses_global_when_lang_omitted() -> None:
    set_language("zh_TW")
    try:
        val = t("rpt_kicker_traffic")
        assert "流量" in val
    finally:
        set_language("en")


def test_t_concurrent_lang_calls_independent() -> None:
    """Two threads asking for different langs must not interleave."""
    set_language("en")
    results: dict[str, list[str]] = {"en": [], "zh_TW": []}

    def worker(lang: str) -> None:
        for _ in range(50):
            results[lang].append(t("rpt_kicker_traffic", lang=lang))

    threads = [threading.Thread(target=worker, args=(lang,)) for lang in ("en", "zh_TW")]
    for t_ in threads:
        t_.start()
    for t_ in threads:
        t_.join()

    assert all(v == "Traffic Analytics Report" for v in results["en"])
    assert all("流量" in v for v in results["zh_TW"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_lang_param.py -v`
Expected: FAIL — `t()` does not accept `lang` kwarg.

- [ ] **Step 3: Implement**

Edit `src/i18n/engine.py:317-335`:

```python
def t(key: str, *, lang: str | None = None, default: str | None = None, **kwargs) -> str:
    """Translate a key. lang=None → use process global; explicit lang= overrides."""
    _lang = lang if lang in {"en", "zh_TW"} else get_language()
    text = get_messages(_lang).get(key)
    if text is None:
        text = _normalized_en_messages().get(key)
    if text is None and _is_strict_surface_key(key):
        text = _missing_marker(key)
    if text is None:
        text = default if default is not None else key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
```

Note: `default` was previously read via `kwargs.pop("default", None)`; now it's an explicit kwarg so static analysis catches misuses.

- [ ] **Step 4: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_lang_param.py -v`
Expected: PASS for all three tests.

- [ ] **Step 5: Run full suite — existing callers should not break**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ -x 2>&1 | tail -10`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/i18n/engine.py tests/test_i18n_lang_param.py
/usr/bin/git commit -m "feat(i18n): t(key, lang=...) parameter; preserves global as default (Phase 3)"
```

---

### Task 14: Migrate `report_generator.py` set_language() callers to lang=

**Files:**
- Modify: `src/report/report_generator.py:338, 529, 573`
- Test: `tests/test_report_generator_lang_param.py`

- [ ] **Step 1: Read the call sites**

Read `src/report/report_generator.py` around lines 338, 529, 573. The pattern is `_prev_lang = get_language(); set_language(lang); ...; set_language(_prev_lang)`.

- [ ] **Step 2: Write the failing test**

```python
"""Phase 3: report_generator must not mutate global lang during render."""
from __future__ import annotations

from src.i18n import get_language, set_language


def test_report_generation_preserves_global_lang() -> None:
    set_language("en")
    try:
        from src.report.report_generator import generate_report
        generate_report("traffic_flow", output_dir="/tmp/i18n_phase3", lang="zh_TW")
        assert get_language() == "en", "report_generator leaked global lang mutation"
    except Exception:
        # Generation may fail in test env; we only assert the lang invariant
        # holds whether or not generation completes.
        assert get_language() == "en"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_report_generator_lang_param.py -v`
Expected: FAIL — generator currently calls `set_language(lang)` at line 338/529.

- [ ] **Step 4: Refactor report_generator.py**

For each `set_language(lang) ... set_language(_prev_lang)` block in `report_generator.py` (lines 338, 529-573):

- Remove the `set_language(lang)` and matching restore `set_language(_prev_lang)`.
- Pass `lang=lang` through to all downstream `t()` calls and exporter constructors. Exporters already accept `lang` parameter — wire it.
- For any indirect `t(key)` call in transitive callees, switch to `t(key, lang=lang)`.

Concrete edits depend on the function bodies; the implementer subagent reads the file and applies the pattern. The constraint: after the refactor, `generate_report(report_type, lang="zh_TW")` must not call `set_language()` anywhere in its call tree.

- [ ] **Step 5: Run test + smoke**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_report_generator_lang_param.py tests/ -x 2>&1 | tail -10`
Expected: PASS.

Visual: `grep -n 'set_language' /home/harry/rd/illumio-ops/src/report/report_generator.py` — expect 0 matches.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/report/report_generator.py tests/test_report_generator_lang_param.py
/usr/bin/git commit -m "refactor(report): thread lang= through report_generator; drop set_language() (Phase 3)"
```

---

### Task 15: Migrate `gui/routes/events.py` and `config.py` callers

**Files:**
- Modify: `src/gui/routes/events.py:300`, `src/config.py:185, 268`
- Test: `tests/test_gui_routes_lang_param.py`

- [ ] **Step 1: Read call sites**

`src/gui/routes/events.py:300` reads language from config and calls `set_language()`. This runs at request handling — leaks across requests if multiple users hit different languages.

`src/config.py:185, 268` similarly calls `set_language()` from ConfigManager methods.

- [ ] **Step 2: Write the failing test**

```python
"""Phase 3: GUI request handlers must not mutate global lang."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.i18n import get_language, set_language


def test_events_route_does_not_leak_lang() -> None:
    set_language("en")
    # Simulate a request that imports events module and triggers route logic.
    from src.gui.routes import events  # noqa: F401
    # The previous behavior reset global to config value at handler entry.
    # After Phase 3, lang lookup is request-scoped via flask g or kwarg.
    assert get_language() == "en"
```

- [ ] **Step 3: Run test to verify it fails (or refactor immediately if test is too coarse)**

If the test passes today by coincidence (because `set_language` is only called inside a function that the test doesn't invoke), the test is not meaningful. In that case skip directly to refactor and validate by reading the diff.

- [ ] **Step 4: Refactor**

In `src/gui/routes/events.py:300`, replace `set_language(...)` with reading the language into a local `lang` and passing it to downstream `t()` calls.

In `src/config.py:185, 268`, the two `set_language()` calls happen at config-load time — that's process-level, not request-level. Justification for keeping these:
- CLI entrypoints expect global language reflects config setting.
- Tests that check `get_language()` after config load depend on it.

Decision: **keep `src/config.py` set_language calls (process bootstrap)**, **remove the request-handler one in `events.py`**.

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ -x 2>&1 | tail -10`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/gui/routes/events.py tests/test_gui_routes_lang_param.py
/usr/bin/git commit -m "refactor(gui): events route reads lang per-request, no set_language() (Phase 3)"
```

---

### Task 16: Document the `set_language()` policy

**Files:**
- Modify: `src/i18n/engine.py:37-39` (docstring on `set_language`)

- [ ] **Step 1: Update the docstring**

```python
def set_language(lang: str) -> None:
    """Set the active UI language (process-global). PROCESS BOOTSTRAP ONLY.

    For request-scoped or report-scoped translation, use `t(key, lang=...)`
    instead. Calling set_language() from request handlers, scheduler tasks,
    or anywhere with concurrency leaks language across calls.

    Allowed callers (Phase 3 baseline):
      - src/config.py:185, 268 — bootstrap from config.json
      - CLI entrypoints — initial language at startup
      - tests — explicit fixture setup

    Adding a new caller? Pass lang= to t() instead.
    """
    _I18N_STATE.set_language(lang)
```

- [ ] **Step 2: Add a lint-style test that scans for new violators**

```python
# tests/test_i18n_set_language_callers.py
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

ALLOWED_CALLERS = {
    SRC / "config.py",
    SRC / "i18n" / "engine.py",
    SRC / "i18n" / "__init__.py",
    SRC / "cli" / "menus" / "__init__.py",
}


def test_no_new_set_language_callers() -> None:
    pattern = re.compile(r"\bset_language\s*\(")
    new_violators: list[str] = []
    for py in SRC.rglob("*.py"):
        if py in ALLOWED_CALLERS:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            new_violators.append(str(py.relative_to(ROOT)))
    assert not new_violators, (
        f"set_language() called from non-allowed file(s): {new_violators}. "
        f"Use t(key, lang=...) instead, or add the file to ALLOWED_CALLERS "
        f"with justification."
    )
```

- [ ] **Step 3: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_i18n_set_language_callers.py -v`
Expected: PASS (after Tasks 14 + 15 removed the violators).

If FAIL: list the remaining call sites and either migrate or add to `ALLOWED_CALLERS` with a comment explaining why.

- [ ] **Step 4: Commit Phase 3 close**

```bash
/usr/bin/git add src/i18n/engine.py tests/test_i18n_set_language_callers.py
/usr/bin/git commit -m "docs(i18n): set_language() bootstrap-only policy + lint test (Phase 3 done — R3)"
```

---

## Phase 4 — Rules Store Keys Not Text (R4)

### Task 17: Add `desc_key` / `rec_key` fields to rule schema

**Files:**
- Modify: `src/config.py` (rule loader/saver — find the schema area)
- Test: `tests/test_config_rule_keys.py`

- [ ] **Step 1: Read existing rule schema**

Read `src/config.py` to find where rules are loaded/saved. The current shape (per the prior session's `_REC_I18N_KEYS` in `reporter.py`) is:

```json
{
  "rules": [
    {"id": "...", "desc": "...", "rec": "...", "event_type": "..."}
  ]
}
```

After Phase 4:

```json
{
  "rules": [
    {"id": "...", "desc_key": "rule_xxx_desc", "rec_key": "alert_rec_xxx", "event_type": "..."}
  ]
}
```

Backward-compat: if `desc_key`/`rec_key` absent, read `desc`/`rec` as legacy.

- [ ] **Step 2: Write the failing test**

```python
"""Phase 4: rules persist desc_key/rec_key, render via t() at read time."""
from __future__ import annotations

import json
from pathlib import Path

from src.config import ConfigManager


def test_rule_with_desc_key_renders_translated(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "rules": [
            {
                "id": "test_001",
                "event_type": "policy_provision",
                "desc_key": "rule_policy_provision_desc",
                "rec_key": "alert_rec_policy_provision",
            }
        ],
        "settings": {"language": "zh_TW"},
    }), encoding="utf-8")

    cm = ConfigManager(config_path=str(cfg_file))
    cm.load()
    rules = cm.config.get("rules", [])
    assert rules[0]["desc"], "loader must populate desc from desc_key at read time"
    assert "[MISSING:" not in rules[0]["desc"]


def test_rule_legacy_format_still_works(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "rules": [
            {"id": "old_001", "desc": "Legacy description", "rec": "Legacy rec"}
        ]
    }), encoding="utf-8")

    cm = ConfigManager(config_path=str(cfg_file))
    cm.load()
    rules = cm.config.get("rules", [])
    assert rules[0]["desc"] == "Legacy description"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_config_rule_keys.py -v`
Expected: FAIL — `desc_key` resolution not implemented.

- [ ] **Step 4: Implement key-resolution at load time**

In `src/config.py` `ConfigManager.load()` (around the existing self-heal block), add a resolver:

```python
def _resolve_rule_keys(self) -> None:
    """If a rule has desc_key/rec_key, populate desc/rec from t() at read time."""
    from src.i18n import t
    lang = self.config.get("settings", {}).get("language", "en")
    for rule in self.config.get("rules", []):
        if rule.get("desc_key"):
            rule["desc"] = t(rule["desc_key"], lang=lang, default=rule.get("desc", ""))
        if rule.get("rec_key"):
            rule["rec"] = t(rule["rec_key"], lang=lang, default=rule.get("rec", ""))
```

Call `_resolve_rule_keys()` at the end of `load()`, replacing the existing `_heal_stale_rule_i18n()` call (the self-heal becomes redundant once keys are stored).

- [ ] **Step 5: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_config_rule_keys.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/config.py tests/test_config_rule_keys.py
/usr/bin/git commit -m "feat(config): rules support desc_key/rec_key; resolve via t() at load (Phase 4)"
```

---

### Task 18: Migration script for existing rule storage

**Files:**
- Create: `scripts/migrate_rules_to_keys.py`
- Test: `tests/test_migrate_rules_script.py`

- [ ] **Step 1: Write the failing test**

```python
"""Migration converts text-based rules to key-based rules."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_migration_dry_run(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [
            {"id": "001", "event_type": "policy_provision",
             "desc": "Policy provisioning event detected",
             "rec": "Review provisioning logs."}
        ]
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_rules_to_keys.py"),
         "--config", str(cfg), "--dry-run"],
        capture_output=True, text=True,
        env={"PYTHONPATH": f"{ROOT}:{ROOT}/venv/lib/python3.12/site-packages"},
    )
    assert result.returncode == 0
    assert "would migrate 1 rule" in result.stdout


def test_migration_write(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [
            {"id": "001", "event_type": "policy_provision",
             "desc": "Policy provisioning event detected",
             "rec": "Review provisioning logs."}
        ]
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_rules_to_keys.py"),
         "--config", str(cfg), "--write"],
        capture_output=True, text=True,
        env={"PYTHONPATH": f"{ROOT}:{ROOT}/venv/lib/python3.12/site-packages"},
    )
    assert result.returncode == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["rules"][0].get("desc_key"), "desc_key must be populated"
    assert data["rules"][0].get("rec_key"), "rec_key must be populated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_migrate_rules_script.py -v`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement**

```python
# scripts/migrate_rules_to_keys.py
"""Phase 4: convert config.json rules from text to key-based fields.

Looks up event_type in src/reporter.py:_REC_I18N_KEYS to find the canonical
rec_key. For desc_key, derives from event_type as `rule_{event_type}_desc`
(matches the existing strict-prefix convention in i18n_*.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reporter import Reporter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.config.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    rec_map = Reporter._REC_I18N_KEYS

    migrated = 0
    for rule in rules:
        event_type = rule.get("event_type")
        if not event_type:
            continue
        if rule.get("desc_key") and rule.get("rec_key"):
            continue
        rule["desc_key"] = rule.get("desc_key") or f"rule_{event_type}_desc"
        rule["rec_key"] = rule.get("rec_key") or rec_map.get(event_type, "alert_rec_default")
        migrated += 1

    if args.write:
        args.config.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE: migrated {migrated} rules in {args.config}")
    else:
        print(f"DRY-RUN: would migrate {migrated} rules in {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_migrate_rules_script.py -v`
Expected: PASS.

- [ ] **Step 5: Apply to repository's config (if checked in)**

Check whether `data/config.json` (or wherever live rules sit) is in version control:
```bash
/usr/bin/git ls-files | grep config.json
```

If yes, dry-run and apply:
```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/migrate_rules_to_keys.py --config data/config.json --dry-run
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/migrate_rules_to_keys.py --config data/config.json --write
```

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add scripts/migrate_rules_to_keys.py tests/test_migrate_rules_script.py data/config.json
/usr/bin/git commit -m "feat(config): migrate rules from text to desc_key/rec_key (Phase 4)"
```

(If `data/config.json` is gitignored, omit it from the commit.)

---

### Task 19: Rule writer persists keys (not text)

**Files:**
- Modify: `src/config.py` (find the rule-save / rule-update code path)
- Test: extend `tests/test_config_rule_keys.py`

- [ ] **Step 1: Find the rule-save code**

Run: `grep -n 'def.*save\|def.*update_rule\|"rules":' /home/harry/rd/illumio-ops/src/config.py`

The implementer locates the function that writes rules back to config.json (likely `save()` or `update_rules()`), and ensures it preserves `desc_key`/`rec_key` rather than re-writing the rendered `desc`/`rec` strings.

- [ ] **Step 2: Add test**

```python
def test_rule_save_preserves_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [{"id": "001", "desc_key": "rule_policy_provision_desc",
                   "rec_key": "alert_rec_policy_provision"}]
    }), encoding="utf-8")

    cm = ConfigManager(config_path=str(cfg))
    cm.load()
    cm.save()

    saved = json.loads(cfg.read_text(encoding="utf-8"))
    rule = saved["rules"][0]
    assert rule["desc_key"] == "rule_policy_provision_desc"
    assert rule["rec_key"] == "alert_rec_policy_provision"
    # The resolved desc/rec MAY be present (rendered cache) but keys are canonical.
```

- [ ] **Step 3: Run test to verify it fails (or skip if save already preserves keys)**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_config_rule_keys.py::test_rule_save_preserves_keys -v`

- [ ] **Step 4: If failing — fix the writer**

In `ConfigManager.save()`, before serializing, strip the rendered `desc`/`rec` for any rule that has a `desc_key`/`rec_key` (the rendering is a derived property, not stored):

```python
def save(self) -> None:
    serializable = copy.deepcopy(self.config)
    for rule in serializable.get("rules", []):
        if rule.get("desc_key"):
            rule.pop("desc", None)
        if rule.get("rec_key"):
            rule.pop("rec", None)
    Path(self.config_path).write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 5: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_config_rule_keys.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add src/config.py tests/test_config_rule_keys.py
/usr/bin/git commit -m "feat(config): rule save() strips rendered text, preserves keys (Phase 4)"
```

---

### Task 20: Remove `_heal_stale_rule_i18n()` self-heal

**Files:**
- Modify: `src/config.py` (delete the self-heal function and its call site)
- Test: existing `tests/test_config_heal_stale_i18n.py` — convert to new behavior

- [ ] **Step 1: Read the self-heal function**

Run: `grep -n '_heal_stale_rule_i18n\|heal_stale' /home/harry/rd/illumio-ops/src/config.py`

The function exists at a specific line range. Read those lines.

- [ ] **Step 2: Delete it**

Remove the function definition and the line in `load()` that calls it. Replace the call in `load()` (already done in Task 17) with `self._resolve_rule_keys()`.

- [ ] **Step 3: Convert the existing self-heal test to a contract test**

Edit `tests/test_config_heal_stale_i18n.py`. Replace its body with a test asserting the new contract: rules with stale rendered text are still readable because `_resolve_rule_keys()` populates from `desc_key`.

```python
"""Phase 4: rules with stale rendered text or [MISSING:*] markers are repaired
by reading desc_key/rec_key, NOT by mutating stored text.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.config import ConfigManager


def test_stale_desc_does_not_leak_when_desc_key_present(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [{
            "id": "001",
            "desc_key": "rule_policy_provision_desc",
            "rec_key": "alert_rec_policy_provision",
            "desc": "[MISSING:rule_policy_provision_desc]",  # stale
            "rec": "[MISSING:alert_rec_policy_provision]",   # stale
        }],
        "settings": {"language": "en"},
    }), encoding="utf-8")

    cm = ConfigManager(config_path=str(cfg))
    cm.load()
    rule = cm.config["rules"][0]
    assert "[MISSING:" not in rule["desc"], "key resolution must override stale text"
    assert "[MISSING:" not in rule["rec"]
```

- [ ] **Step 4: Run test**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_config_heal_stale_i18n.py -v`
Expected: PASS.

Run: `grep -n '_heal_stale_rule_i18n' /home/harry/rd/illumio-ops/src/`  — expect no matches.

- [ ] **Step 5: Commit Phase 4 close**

```bash
/usr/bin/git add src/config.py tests/test_config_heal_stale_i18n.py
/usr/bin/git commit -m "refactor(config): delete _heal_stale_rule_i18n; key-based rules don't need it (Phase 4 done — R4)"
```

---

## Phase 5 — Cleanup & Documentation

### Task 21: Final audit + remove dead code

**Files:**
- Modify: `src/i18n/engine.py` (remove `_translate_text` if no callers; or keep in a `migrations/` namespace)
- Modify: `scripts/audit_i18n_usage.py` (refresh categories)

- [ ] **Step 1: Check `_translate_text` and humanize callers**

Run: `grep -rn '_translate_text\|_humanize_key_zh\|_humanize_key_en' --include='*.py' src/ scripts/ tests/`

Expected callers:
- `scripts/precompute_zh_translations.py` — migration only, kept
- `scripts/audit_i18n_usage.py` — Cat A/B use humanize for placeholder detection
- Tests — keep

If any `src/` non-script callers remain, that's a Phase 2 leak. Migrate or document.

- [ ] **Step 2: Run full audit, expect exit 0**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py`
Expected: exit 0 across A-I.

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ 2>&1 | tail -5`
Expected: all PASS.

- [ ] **Step 4: Run mypy on the i18n surface**

Run: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m mypy src/i18n/ src/report/exporters/report_i18n.py 2>&1 | tail -10`
Expected: 0 errors (or pre-existing baseline only).

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add -u
/usr/bin/git commit --allow-empty -m "chore(i18n): final audit clean — Phase 5 cleanup"
```

---

### Task 22: Document the new i18n contract

**Files:**
- Modify: `README.md` (add or refresh i18n section if one exists)
- Modify: `CLAUDE.md` (if i18n guidance section exists, update)

- [ ] **Step 1: Check what docs exist**

Run: `grep -lE 'i18n|translation' /home/harry/rd/illumio-ops/README.md /home/harry/rd/illumio-ops/CLAUDE.md 2>/dev/null`

- [ ] **Step 2: Update or add a single section**

Add the following section to whichever file is the canonical contributor guide (default: `README.md` under a "Translations" heading):

```markdown
## Translations (i18n)

**Single source of truth:** `src/i18n_en.json` and `src/i18n_zh_TW.json`. Every key has an explicit value in both files; no runtime auto-translation.

**Adding a key:**
1. Add to both JSON files. Use a strict-prefix (`gui_`, `rpt_`, `rule_`, etc. — see `src/i18n/data/strict_prefixes.json`) so a missed translation surfaces as `[MISSING:key]` instead of leaking English.
2. Reference via `t("your_key", lang=lang)`. For request-scoped contexts, always pass `lang=`; never call `set_language()` from a handler.
3. Run `python scripts/audit_i18n_usage.py` to verify glossary respect (Cat E) and parity (Cat I).

**Glossary:** `src/i18n/data/glossary.json` lists English terms that must NOT be translated to Chinese (Block, Allow, Manage, Unmanage, PCE, VEN, Workload, Service, Port, Policy, etc.). Adding a new glossary term: append to `preserve_in_zh_tw` and add forbidden Chinese substitutes to `forbidden_zh_substitutes`.

**Reports:** Use `t(key, lang=lang)` directly. The legacy `STRINGS` dict in `src/report/exporters/report_i18n.py` is a thin compatibility wrapper — for new code prefer `t()`.

**Rules (config.json):** Persist `desc_key` and `rec_key`, never localized `desc`/`rec` text. The loader resolves keys via `t()` at read time.
```

- [ ] **Step 3: Commit**

```bash
/usr/bin/git add README.md CLAUDE.md
/usr/bin/git commit -m "docs(i18n): contributor guide for the post-refactor i18n contract (Phase 5 done)"
```

---

## Final Validation

After Task 22 completes, run the consolidated check:

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/ 2>&1 | tail -5
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m mypy src/i18n/ src/report/exporters/report_i18n.py
grep -rn '_StringMap\|_translate_text' --include='*.py' src/
```

Expected:
- pytest: all pass
- audit: exit 0
- mypy: 0 errors on i18n surface (pre-existing baseline elsewhere OK)
- grep: only matches in `src/i18n/engine.py` (kept for migration use), zero matches in any other `src/` file

---

## Implementation Status

| Phase | Tasks | Status |
|-------|------:|--------|
| 1. Single SoT (R1)         | 1-7   | Pending |
| 2. Glossary + de-regex (R2)| 8-12  | Pending |
| 3. lang= parameter (R3)    | 13-16 | Pending |
| 4. Rules store key (R4)    | 17-20 | Pending |
| 5. Cleanup + docs          | 21-22 | Pending |
