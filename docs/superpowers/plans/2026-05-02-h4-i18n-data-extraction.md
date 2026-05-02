# H4 — `src/i18n.py` Data Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `src/i18n.py` (a 2275-line file dominated by ~2000 lines of literal Chinese-translation data) into the package `src/i18n/` where the data lives in JSON files and only the engine code is in `.py`.

**Architecture:** Replace `src/i18n.py` with `src/i18n/` package. Data dictionaries (`_ZH_EXPLICIT`, `_TOKEN_MAP_EN`, `_TOKEN_MAP_ZH`, `_PHRASE_OVERRIDES`) move to `src/i18n/data/*.json`. Engine code (state, humanize, translate, build_messages, public `t` / `set_language` / `get_language` / `get_messages`) moves to `src/i18n/engine.py`. `src/i18n/__init__.py` re-exports the public API so all 59 importers (`from src.i18n import t` / `set_language` / etc.) keep working unchanged.

**Tech Stack:** Python 3.12, json, threading, functools.lru_cache, pathlib. Tests already cover i18n behaviour via `tests/test_i18n_audit.py`, `tests/test_i18n_quality.py`, `tests/test_humanize_coverage.py`, `tests/test_humanize_ext.py` plus the integration audit `scripts/audit_i18n_usage.py`.

---

## Scope Note

This plan is one of three Batch 4 sub-plans (see
`docs/superpowers/plans/2026-05-01-code-review-fixes.md` Batch 4 sketch). H5
(`gui/__init__.py` Blueprint split) and H6 (`settings.py` rename) are
separate plans. This plan touches `src/i18n.py` only.

External callers import exactly these four symbols:

- `t`
- `get_language`
- `set_language`
- `get_messages`

No external file imports any private constant (`_ZH_EXPLICIT`,
`_TOKEN_MAP_*`, `EN_MESSAGES`, `ZH_MESSAGES`, etc.). This was verified with:

```bash
grep -hE "^from src\.i18n import" src/ tests/ scripts/ -r | \
  sed -E 's/^.*import //' | tr ',' '\n' | sort -u
```

The public API surface stays exactly the same. Internal-only state can move
freely.

---

## File Structure

After this refactor, the i18n subsystem looks like:

```
src/i18n/
├── __init__.py              # Re-exports the public API: t, get_language,
│                            # set_language, get_messages.
├── engine.py                # State, humanize_*, translate_text,
│                            # _build_messages, t, get_messages, set_language,
│                            # get_language. ~270 lines.
└── data/
    ├── zh_explicit.json     # Final merged _ZH_EXPLICIT dict (single object;
    │                        # merge order is baked in at build time).
    ├── token_map_en.json    # _TOKEN_MAP_EN.
    ├── token_map_zh.json    # _TOKEN_MAP_ZH.
    └── phrase_overrides.json # _PHRASE_OVERRIDES.
```

Existing files NOT moved (already JSON, sit at `src/`):

- `src/i18n_en.json`
- `src/i18n_zh_TW.json`

These stay where they are; only their loaders' file paths in `engine.py`
change to `_ROOT.parent / "i18n_en.json"` (since `engine.py` is now one
directory deeper).

The set `_SKIP_TOKENS` (small — 16 tokens) and the tuple `_STRICT_PREFIXES`
(also small — 30 tokens) stay in `engine.py` as Python literals. They are
small, rarely changed, and JSON-ifying them adds no value. The regex
`_PLACEHOLDER_VALUE_RE` likewise stays as a Python expression.

---

## Risk Analysis

The single biggest risk is `_ZH_EXPLICIT` reconstruction. The current source
builds it in **four** stages:

1. Initial dict literal — `src/i18n.py:84` … `src/i18n.py:1385`.
2. Three individual key assignments — `src/i18n.py:1387–1389`
   (`gui_top10_widgets`, `gui_top10_title`, `gui_report_lang_en`).
3. First `_ZH_EXPLICIT.update({...})` block — `src/i18n.py:1391–1459`.
4. Second `_ZH_EXPLICIT.update({...})` block — `src/i18n.py:1945–2040`.

The merge order matters: a later stage's key overrides an earlier stage's
value. The plan extracts the FINAL merged dict (after all four stages) into
one JSON file. Task 1's golden-output snapshot makes any drift detectable.

---

## Pre-flight (run once before starting)

- [ ] Verify clean working tree: `git status` → "nothing to commit"
- [ ] Verify on `main` and up-to-date: `git pull --ff-only`
- [ ] Verify test suite green baseline:
      `venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3`
      → expect `824 passed, 1 skipped`
- [ ] Verify i18n audit baseline:
      `venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3`
      → expect `Total: 0 finding(s)`
- [ ] Create branch:
      `git checkout -b h4-i18n-data-extraction`

---

## Task 1: Capture golden output baseline

**Why:** Every later task changes how the message dictionaries are built. We
need a byte-identical snapshot of the current `get_messages('en')` and
`get_messages('zh_TW')` outputs to verify nothing drifts.

**Files:**
- Create: `tests/test_i18n_data_extraction_baseline.py` (temporary — deleted
  in Task 8 once the refactor is complete; while it lives, it pins behaviour).

- [ ] **Step 1: Capture the current output to a JSON file (one-time
  generator script run from a Python REPL or a throwaway script):**

```bash
venv/bin/python3 - <<'PY'
import json
import pathlib
from src import i18n

baseline = {
    "en": i18n.get_messages("en"),
    "zh_TW": i18n.get_messages("zh_TW"),
}
out = pathlib.Path("tests/_i18n_baseline.json")
out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote {out}: {out.stat().st_size} bytes, "
      f"en={len(baseline['en'])} keys, zh_TW={len(baseline['zh_TW'])} keys")
PY
```

Expected output (approximate, depends on `_discover_keys()` results at
generation time): a 1+ MB JSON file with thousands of keys per language.

- [ ] **Step 2: Write the differential test**

`tests/test_i18n_data_extraction_baseline.py`:

```python
"""Golden-output snapshot test for the H4 refactor.

Compares get_messages('en') and get_messages('zh_TW') against a baseline
captured from the pre-refactor src/i18n.py. Once H4 is complete and the
data has fully moved into src/i18n/data/*.json, this file is removed
(see Task 8). Until then, every refactor task must leave this test green.
"""
from __future__ import annotations
import json
from pathlib import Path

from src.i18n import get_messages

_BASELINE_PATH = Path(__file__).parent / "_i18n_baseline.json"


def _baseline() -> dict[str, dict[str, str]]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def test_en_output_matches_baseline():
    expected = _baseline()["en"]
    actual = get_messages("en")
    diff = {
        k: (expected.get(k, "<missing>"), actual.get(k, "<missing>"))
        for k in set(expected) | set(actual)
        if expected.get(k) != actual.get(k)
    }
    assert not diff, f"en drift on {len(diff)} keys: {dict(list(diff.items())[:5])}"


def test_zh_tw_output_matches_baseline():
    expected = _baseline()["zh_TW"]
    actual = get_messages("zh_TW")
    diff = {
        k: (expected.get(k, "<missing>"), actual.get(k, "<missing>"))
        for k in set(expected) | set(actual)
        if expected.get(k) != actual.get(k)
    }
    assert not diff, f"zh_TW drift on {len(diff)} keys: {dict(list(diff.items())[:5])}"
```

- [ ] **Step 3: Run the test — confirm both pass against pristine baseline**

```bash
venv/bin/python3 -m pytest tests/test_i18n_data_extraction_baseline.py -v --timeout=60 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_i18n_data_extraction_baseline.py tests/_i18n_baseline.json
git commit -m "test(i18n): add baseline snapshot for H4 refactor

Captures get_messages('en') and get_messages('zh_TW') outputs as a
JSON snapshot, plus a test that confirms future refactor tasks don't
drift the dictionary content. Both file and test will be removed at
the end of Task 8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Create `src/i18n/` package skeleton (parallel with the old file)

**Why:** Adding a directory `src/i18n/` while `src/i18n.py` still exists
will fail at import time — Python disallows that. So the move must happen
atomically. We do it in two phases: rename the old file, then build the
package on top.

**Files:**
- Rename: `src/i18n.py` → `src/i18n/_legacy.py` (temporary intermediate,
  deleted in Task 7).
- Create: `src/i18n/__init__.py`
- Create: `src/i18n/data/` (empty for now).

- [ ] **Step 1: Make the package directory and move the old file in**

```bash
# Rename — file → directory + file inside it.
mkdir -p src/i18n
git mv src/i18n.py src/i18n/_legacy.py
mkdir -p src/i18n/data
```

- [ ] **Step 2: Re-export the public API from `__init__.py`**

`src/i18n/__init__.py`:

```python
"""i18n subsystem (refactored from src/i18n.py per H4).

Public API:
- t(key, **kwargs)
- get_messages(lang=None)
- set_language(lang)
- get_language()
"""
from src.i18n._legacy import (  # noqa: F401
    t,
    get_messages,
    set_language,
    get_language,
)
```

This re-export keeps `from src.i18n import t` working while every later
task moves code from `_legacy.py` into the new `engine.py`.

- [ ] **Step 3: Run the full test suite + audit + baseline**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: `826 passed, 1 skipped` (824 baseline + 2 new H4 baseline tests
from Task 1) AND `Total: 0 finding(s)`. The package move is transparent
to every importer.

- [ ] **Step 4: Commit**

```bash
git add src/i18n/__init__.py src/i18n/_legacy.py src/i18n/data/
# Note: git mv staged the rename automatically.
git commit -m "refactor(i18n): convert src/i18n.py to src/i18n/ package skeleton (H4 step 1)

Renames src/i18n.py → src/i18n/_legacy.py and adds an __init__.py that
re-exports t, get_messages, set_language, get_language so every existing
importer continues to work. Empty src/i18n/data/ ready for later JSON
extracts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Extract `_ZH_EXPLICIT` to `data/zh_explicit.json`

**Why:** This is the largest data block (~1400 lines spread across four
merge stages: lines 84–1385, 1387–1389, 1391–1459, 1945–2040 in
`_legacy.py`). Merging it into one JSON kills 1400 lines of code without
behaviour change.

**Files:**
- Create: `src/i18n/data/zh_explicit.json`
- Modify: `src/i18n/_legacy.py` — replace the four merge stages with a
  single JSON load.

- [ ] **Step 1: Generate the merged JSON from the live module**

```bash
venv/bin/python3 - <<'PY'
import json
import pathlib
from src.i18n import _legacy as m
out = pathlib.Path("src/i18n/data/zh_explicit.json")
out.write_text(
    json.dumps(m._ZH_EXPLICIT, ensure_ascii=False, indent=2, sort_keys=True),
    encoding="utf-8",
)
print(f"Wrote {out}: {len(m._ZH_EXPLICIT)} keys, {out.stat().st_size} bytes")
PY
```

Expected: a JSON file with ~1300 keys, sorted by key for stable diffs in
future commits.

- [ ] **Step 2: Replace the four merge stages with a single JSON load**

In `src/i18n/_legacy.py`, find lines 84 (start of `_ZH_EXPLICIT` literal)
through 1459 (end of first `.update({})` block), and lines 1945–2040
(second `.update({})` block). Replace ALL OF THAT with:

```python
def _load_json_data(filename: str) -> dict[str, str]:
    """Load a JSON-encoded dict from src/i18n/data/<filename>."""
    path = Path(__file__).parent / "data" / filename
    return json.loads(path.read_text(encoding="utf-8"))


_ZH_EXPLICIT: dict[str, str] = _load_json_data("zh_explicit.json")
```

Place `_load_json_data` and the `_ZH_EXPLICIT` assignment immediately AFTER
the existing `_missing_marker` function (currently at line 81–82), and
BEFORE the remaining symbols `_SKIP_TOKENS`, `_TOKEN_MAP_EN`, etc. The two
big literal ranges and the two `_ZH_EXPLICIT.update({...})` blocks are
deleted. (`_load_json_data` is intentionally generic — Tasks 4 and 5 reuse
it for the remaining data extracts.)

The three individual assignments (`_ZH_EXPLICIT["gui_top10_widgets"] = "..."`
etc., currently lines 1387–1389) are now redundant — the merged JSON
already includes them. **Delete those three lines.**

- [ ] **Step 3: Run the suite + baseline**

```bash
venv/bin/python3 -m pytest tests/test_i18n_data_extraction_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected:
- baseline test: 2 passed (key verifier — drift here means the merge order
  was wrong).
- full suite: 826 passed, 1 skipped (the two from Task 1 stay green).
- audit: `Total: 0 finding(s)`.

If the baseline test fails, inspect the diff message — it shows up to 5
drifted keys. Most likely cause: the second `.update({...})` block had a
key that re-overrode the same key from the first block, and the JSON dump
lost that order. Re-generate with `sort_keys=False` and inspect.

- [ ] **Step 4: Commit**

```bash
git add src/i18n/_legacy.py src/i18n/data/zh_explicit.json
git commit -m "refactor(i18n): extract _ZH_EXPLICIT to data/zh_explicit.json (H4 step 2)

The _ZH_EXPLICIT dict was previously built across four merge stages (a
1300-line literal at lines 84–1385, three patches at 1387–1389, and two
.update() blocks at 1391–1459 and 1945–2040). Merged at module import
time into a single dict and written to JSON sorted by key for stable
diffs.

Removes ~1400 lines of inline data from _legacy.py. Behaviour is
verified identical via tests/test_i18n_data_extraction_baseline.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Extract `_TOKEN_MAP_EN` and `_TOKEN_MAP_ZH` to JSON

**Why:** ~440 lines of two-column English/Chinese token-mapping dicts.

**Files:**
- Create: `src/i18n/data/token_map_en.json`
- Create: `src/i18n/data/token_map_zh.json`
- Modify: `src/i18n/_legacy.py`

- [ ] **Step 1: Generate the JSON for both maps**

```bash
venv/bin/python3 - <<'PY'
import json
import pathlib
from src.i18n import _legacy as m
for name in ("_TOKEN_MAP_EN", "_TOKEN_MAP_ZH"):
    data = getattr(m, name)
    fname = name.lower().lstrip("_") + ".json"
    out = pathlib.Path("src/i18n/data") / fname
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"{name} -> {out}: {len(data)} entries, {out.stat().st_size} bytes")
PY
```

- [ ] **Step 2: Replace the literals with JSON loads**

In `src/i18n/_legacy.py`, find the `_TOKEN_MAP_EN = {...}` block (search
for `_TOKEN_MAP_EN = {`; positionally it follows `_SKIP_TOKENS` and
precedes `_TOKEN_MAP_ZH`) and the `_TOKEN_MAP_ZH = {...}` block. Replace
BOTH dict literals with:

```python
_TOKEN_MAP_EN: dict[str, str] = _load_json_data("token_map_en.json")
_TOKEN_MAP_ZH: dict[str, str] = _load_json_data("token_map_zh.json")
```

`_load_json_data` was added in Task 3 — reuse it.

- [ ] **Step 3: Run the suite + baseline**

```bash
venv/bin/python3 -m pytest tests/test_i18n_data_extraction_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: 2 baseline passed; 826 passed, 1 skipped.

- [ ] **Step 4: Commit**

```bash
git add src/i18n/_legacy.py src/i18n/data/token_map_en.json src/i18n/data/token_map_zh.json
git commit -m "refactor(i18n): extract _TOKEN_MAP_EN and _TOKEN_MAP_ZH to data/*.json (H4 step 3)

Removes ~440 lines of inline literals from _legacy.py. Both maps are
loaded by the shared _load_json_data helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Extract `_PHRASE_OVERRIDES` to `data/phrase_overrides.json`

**Why:** ~35 lines of English-phrase → Chinese mappings.

**Files:**
- Create: `src/i18n/data/phrase_overrides.json`
- Modify: `src/i18n/_legacy.py`

- [ ] **Step 1: Generate the JSON**

```bash
venv/bin/python3 - <<'PY'
import json
import pathlib
from src.i18n import _legacy as m
data = m._PHRASE_OVERRIDES
out = pathlib.Path("src/i18n/data/phrase_overrides.json")
# Preserve insertion order (Python 3.7+ dicts) — phrase_overrides is
# applied longest-first inside _translate_text, so JSON ordering doesn't
# affect runtime behaviour, but sort_keys=True for stable diffs.
out.write_text(
    json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
    encoding="utf-8",
)
print(f"_PHRASE_OVERRIDES -> {out}: {len(data)} entries, {out.stat().st_size} bytes")
PY
```

- [ ] **Step 2: Replace the literal with JSON load**

In `src/i18n/_legacy.py`, find the `_PHRASE_OVERRIDES = {...}` block
(currently ~lines 1910–1943). Replace with:

```python
_PHRASE_OVERRIDES: dict[str, str] = _load_json_data("phrase_overrides.json")
```

(Reuses the loader from Task 4.)

- [ ] **Step 3: Run the suite + baseline**

```bash
venv/bin/python3 -m pytest tests/test_i18n_data_extraction_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: 2 baseline passed; 826 passed, 1 skipped.

- [ ] **Step 4: Commit**

```bash
git add src/i18n/_legacy.py src/i18n/data/phrase_overrides.json
git commit -m "refactor(i18n): extract _PHRASE_OVERRIDES to data/phrase_overrides.json (H4 step 4)

Removes the last large data literal from _legacy.py. The translate-text
phrase-override pipeline reads from JSON via the shared loader.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Move pure code into `src/i18n/engine.py`

**Why:** After Tasks 3–5 the `_legacy.py` file is purely engine code (~270
lines: state class, JSON loaders, humanize functions, `_translate_text`,
`_normalized_*_messages`, `_build_messages`, the public `t` /
`get_messages` / `set_language` / `get_language`). Move it to a
properly-named module.

**Files:**
- Create: `src/i18n/engine.py`
- Modify: `src/i18n/__init__.py` — switch import source.

- [ ] **Step 1: Copy the entire content of `_legacy.py` to `engine.py`**

```bash
cp src/i18n/_legacy.py src/i18n/engine.py
```

- [ ] **Step 2: Adjust `_ROOT` path inside `engine.py`**

`src/i18n.py` (the original) used `_ROOT = Path(__file__).resolve().parent`
which pointed at `src/`. Now `engine.py` is one level deeper at
`src/i18n/`, so the i18n_*.json paths must compensate.

In `src/i18n/engine.py`, find:

```python
_ROOT = Path(__file__).resolve().parent
_EN_MESSAGES_PATH = _ROOT / "i18n_en.json"
_ZH_MESSAGES_PATH = _ROOT / "i18n_zh_TW.json"
```

Replace with:

```python
# engine.py lives at src/i18n/, but i18n_en.json / i18n_zh_TW.json sit at
# src/. Walk up one directory.
_PKG_ROOT = Path(__file__).resolve().parent       # src/i18n/
_SRC_ROOT = _PKG_ROOT.parent                       # src/
_DATA_ROOT = _PKG_ROOT / "data"                    # src/i18n/data/
_EN_MESSAGES_PATH = _SRC_ROOT / "i18n_en.json"
_ZH_MESSAGES_PATH = _SRC_ROOT / "i18n_zh_TW.json"
```

Also update the data-JSON loader to use `_DATA_ROOT`:

```python
def _load_json_data(filename: str) -> dict[str, str]:
    return json.loads((_DATA_ROOT / filename).read_text(encoding="utf-8"))
```

(If the loader was placed elsewhere, just rewire it to read from
`_DATA_ROOT`.)

- [ ] **Step 3: Update `__init__.py` to import from engine**

```python
"""i18n subsystem (refactored from src/i18n.py per H4).

Public API:
- t(key, **kwargs)
- get_messages(lang=None)
- set_language(lang)
- get_language()
"""
from src.i18n.engine import (  # noqa: F401
    t,
    get_messages,
    set_language,
    get_language,
)
```

- [ ] **Step 4: Verify both paths still work (legacy still importable)**

```bash
venv/bin/python3 -m pytest tests/test_i18n_data_extraction_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: 2 baseline passed; 826 passed, 1 skipped; 0 findings. At this
point the entire codebase routes through `engine.py` because of the
`__init__.py` switch in Step 3.

- [ ] **Step 5: Commit**

```bash
git add src/i18n/engine.py src/i18n/__init__.py
git commit -m "refactor(i18n): introduce src/i18n/engine.py (H4 step 5)

Copies _legacy.py to engine.py with the _ROOT path adjusted to
account for the extra directory level. __init__.py now re-exports
the public API from engine. _legacy.py is still on disk and unchanged
— removed in the next task once we've confirmed engine.py is the live
source.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Delete `_legacy.py`

**Why:** `__init__.py` no longer imports from `_legacy.py`; the file is
dead code. Remove it.

**Files:**
- Delete: `src/i18n/_legacy.py`

- [ ] **Step 1: Confirm nothing imports from `_legacy.py`**

```bash
grep -rln 'from src.i18n._legacy\|from src.i18n import _legacy\|src.i18n._legacy' src/ tests/ scripts/ 2>/dev/null
```

Expected: zero output.

- [ ] **Step 2: Delete the file**

```bash
git rm src/i18n/_legacy.py
```

- [ ] **Step 3: Run the suite + baseline**

```bash
venv/bin/python3 -m pytest tests/test_i18n_data_extraction_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: 2 baseline passed; 826 passed, 1 skipped; 0 findings.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(i18n): drop transitional _legacy.py (H4 step 6)

engine.py is the canonical engine module. _legacy.py was kept only
across the data-extraction commits; nothing imports it now.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Verification gate + retire baseline scaffolding

**Why:** With the refactor complete, the baseline-snapshot test that has
been guarding every step has served its purpose. It now becomes a
liability — any legitimate future change to dictionary content (a new
translation, a typo fix in `i18n_zh_TW.json`) would require regenerating
the baseline, which is overhead future contributors won't expect.

**Files:**
- Delete: `tests/test_i18n_data_extraction_baseline.py`
- Delete: `tests/_i18n_baseline.json`

- [ ] **Step 1: Final full-suite + audit + mypy run**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -5
venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -5
venv/bin/python3 -m mypy --config-file mypy.ini src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -3
```

Expected:
- Tests: 826 passed, 1 skipped (824 baseline + 2 H4 baselines from
  Task 1; the H4 baselines come out in Step 2 below).
- i18n audit: `Total: 0 finding(s)`.
- mypy: 0 errors on the three target files (Batch 5 / M11 contract).

- [ ] **Step 2: Delete the baseline scaffolding**

```bash
git rm tests/test_i18n_data_extraction_baseline.py tests/_i18n_baseline.json
```

- [ ] **Step 3: Run the suite once more to confirm test count drops by 2**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: 824 passed, 1 skipped. (The 2 H4-baseline tests are gone;
nothing else regressed — the count returns to the pre-flight baseline.)

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(i18n): retire H4 baseline scaffolding

H4 is complete. The baseline snapshot test, useful as a step-by-step
guard during the refactor, is now overhead — every future translation
edit would otherwise require regenerating the baseline. Deleted both
the test and the JSON snapshot.

Final shape:
- src/i18n/__init__.py — public API re-exports
- src/i18n/engine.py — ~270 lines of engine code
- src/i18n/data/zh_explicit.json — ~1300 keys
- src/i18n/data/token_map_en.json
- src/i18n/data/token_map_zh.json
- src/i18n/data/phrase_overrides.json

Original src/i18n.py: 2275 lines → src/i18n/engine.py: ~270 lines
(net 2000+ lines moved to JSON).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final Acceptance

- [ ] `venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -5` → green,
      824 passed, 1 skipped (back to the pre-flight baseline once
      Task 8 step 2 deletes the two H4 baselines).
- [ ] `venv/bin/python3 scripts/audit_i18n_usage.py` → 0 findings.
- [ ] `venv/bin/python3 -c "from src.i18n import t, get_messages, set_language, get_language; print(t('gui_tab_dashboard'))"`
      → prints `Dashboard` (en default) — confirms public API still works.
- [ ] `wc -l src/i18n/engine.py` → ~270 lines.
- [ ] `ls src/i18n/data/` → exactly four JSON files.
- [ ] `find src -name 'i18n.py'` → no output (the original module is gone).
- [ ] Squash-merge or rebase-merge `h4-i18n-data-extraction` → `main` and
      tag if you wish.

---

## Self-Review Notes

- **Spec coverage:** Every item in the original Batch 4 H4 sketch is now a
  task — package shell (Task 2), each of the four data extracts (Tasks
  3–5), engine.py rename (Task 6), legacy delete (Task 7), audit + tests
  + zero-drift verification (running through every task plus Task 8).
- **Placeholders:** Each task lists exact paths, exact code blocks, exact
  commands with expected output. Generator scripts use HEREDOCs so the
  engineer pastes them verbatim.
- **Type consistency:** The same loader signature
  `_load_json_data(filename: str) -> dict[str, str]` is used in Tasks 4,
  5, 6. The `_DATA_ROOT` / `_PKG_ROOT` / `_SRC_ROOT` triple is introduced
  in Task 6 and stays consistent.
- **Risk gating:** Task 1 captures the golden output BEFORE any code
  moves. Every subsequent task re-runs the baseline test, so any drift
  is caught at the offending task's commit boundary.
- **Reversibility:** Each task is a single commit; failed work can be
  reset with `git reset --hard HEAD~1`. The branch
  `h4-i18n-data-extraction` is throwaway until the final acceptance.
