# Event Catalog 100% Coverage + Runbooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that every PCE event type the project recognises has a verified human description and category, and attach actionable remediation ("runbook") guidance — enforced by CI so it stays 100%.

**Architecture:** Introduce one authoritative data artifact (`docs/_meta/illumio-event-reference.json`) sourced from the user's NotebookLM Illumio notebook (descriptions/categories) + alexgoller `runbooks.yaml` (severity + remediation + official doc URL). Code reads this artifact at build time to backfill i18n description keys and to expose per-event remediation in the events viewer and alert bodies. A coverage test asserts the catalog, the reference artifact, and the i18n keys stay in lockstep.

**Tech Stack:** Python 3.12, SQLAlchemy (existing), pytest, project i18n JSON (`src/i18n_en.json` / `src/i18n_zh_TW.json`), Jinja-style alert templates (`src/alerts/templates/`).

---

## External dependency (gate for Phase A)

The authoritative **descriptions** require the user's NotebookLM Illumio notebook (official docs are SPA-rendered and not plain-HTTP fetchable — verified 2026-06-02). Phases B–E are deterministic TDD against the fixture and do **not** need NotebookLM once `illumio-event-reference.json` exists.

- Reference type list: `src/events/catalog.py::KNOWN_EVENT_TYPES` (288 types, verified 100% superset of alexgoller upstream 272 + 16 PCE 25.x additions).
- Runbook source (already downloaded during planning): `alexgoller/illumio-pretty-cool-events` → `pretty_cool_events/data/runbooks.yaml` (16 categories, 117 event-type patterns, severity_hint + response + runbook_url).

---

## File Structure

- Create `docs/_meta/illumio-event-reference.json` — authoritative per-type metadata (the fixture/source of truth).
- Create `src/events/reference.py` — loader + accessors over the reference artifact.
- Create `src/events/runbooks.py` (data + loader) — vendored runbook categories from alexgoller, keyed for our event types.
- Modify `src/i18n_en.json`, `src/i18n_zh_TW.json` — add `event_desc_<id>` keys for every type.
- Modify `src/events/catalog.py` — make `EVENT_DESCRIPTION_KEYS` derive from the reference (single source of truth) instead of a hand-maintained 23-entry dict.
- Create `tests/test_event_reference_coverage.py` — the 100% coverage gate.
- Modify `src/gui/routes/events.py` and `src/alerts/template_utils.py` — surface description + remediation.

---

## Task 1: Reference artifact schema + loader (TDD)

**Files:**
- Create: `docs/_meta/illumio-event-reference.json`
- Create: `src/events/reference.py`
- Test: `tests/test_event_reference_coverage.py`

- [ ] **Step 1: Write the failing test for the loader + schema**

```python
# tests/test_event_reference_coverage.py
import json
from pathlib import Path
from src.events.reference import load_reference, EventRef

REF_PATH = Path("docs/_meta/illumio-event-reference.json")

def test_reference_loads_and_is_typed():
    ref = load_reference()
    assert isinstance(ref, dict)
    sample = ref["agent.tampering"]
    assert isinstance(sample, EventRef)
    assert sample.category and sample.description  # non-empty
    assert sample.severity in ("info", "warning", "critical")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_event_reference_coverage.py::test_reference_loads_and_is_typed -v`
Expected: FAIL — `ModuleNotFoundError: src.events.reference`.

- [ ] **Step 3: Seed `illumio-event-reference.json` with a minimal valid entry and write the loader**

```json
{
  "agent.tampering": {
    "category": "Agent Security",
    "description": "A VEN reported tampering with its firewall rules or agent files.",
    "severity": "critical",
    "remediation": "Investigate the host immediately; tampering may indicate compromise.",
    "doc_url": "https://docs.illumio.com/core/24.2/Content/Guides/ven-administration/ven-tampering-protection.htm"
  }
}
```

```python
# src/events/reference.py
from __future__ import annotations
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REF_PATH = Path(__file__).resolve().parents[2] / "docs" / "_meta" / "illumio-event-reference.json"

@dataclass(frozen=True)
class EventRef:
    category: str
    description: str
    severity: str
    remediation: str = ""
    doc_url: str = ""

@lru_cache(maxsize=1)
def load_reference() -> dict[str, EventRef]:
    raw = json.loads(_REF_PATH.read_text(encoding="utf-8"))
    return {k: EventRef(**v) for k, v in raw.items()}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_event_reference_coverage.py::test_reference_loads_and_is_typed -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/_meta/illumio-event-reference.json src/events/reference.py tests/test_event_reference_coverage.py
git commit -m "feat(events): add authoritative event-reference artifact + loader"
```

---

## Task 2: Vendor alexgoller runbooks as severity/remediation source (TDD)

**Files:**
- Create: `src/events/runbooks.py`
- Test: `tests/test_event_reference_coverage.py`

- [ ] **Step 1: Write the failing test**

```python
def test_runbook_lookup_returns_severity_and_response():
    from src.events.runbooks import runbook_for
    rb = runbook_for("request.authentication_failed")
    assert rb is not None
    assert rb["severity_hint"] == "critical"
    assert "brute force" in rb["response"].lower()
    assert runbook_for("totally.unknown") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_event_reference_coverage.py::test_runbook_lookup_returns_severity_and_response -v`
Expected: FAIL — `ModuleNotFoundError: src.events.runbooks`.

- [ ] **Step 3: Vendor the runbook data + lookup**

Copy `runbooks.yaml` content (categories → patterns/severity_hint/response/runbook_url) into `src/events/runbooks.py` as a Python dict `RUNBOOK_CATEGORIES` (avoids a YAML runtime dep; keeps it offline-bundle-safe). Build a flat `event_type -> category` index and:

```python
# src/events/runbooks.py  (RUNBOOK_CATEGORIES vendored from
# alexgoller/illumio-pretty-cool-events @ pretty_cool_events/data/runbooks.yaml)
from __future__ import annotations

RUNBOOK_CATEGORIES: dict[str, dict] = {
    "security-auth-failure": {
        "patterns": ["request.authentication_failed", "request.authorization_failed"],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/events-administration/event-types.htm",
        "severity_hint": "critical",
        "response": ("Immediate action required. Review the source IP and username. "
                     "Multiple failures from the same IP may indicate brute force attack. "
                     "Check if the account is locked. Review API key expiration dates."),
    },
    # ... remaining 15 categories vendored verbatim during execution ...
}

_INDEX = {p: c for c, d in RUNBOOK_CATEGORIES.items() for p in d["patterns"]}

def runbook_for(event_type: str) -> dict | None:
    cat = _INDEX.get(event_type)
    return RUNBOOK_CATEGORIES[cat] if cat else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_event_reference_coverage.py::test_runbook_lookup_returns_severity_and_response -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/events/runbooks.py tests/test_event_reference_coverage.py
git commit -m "feat(events): vendor alexgoller runbook categories for severity/remediation"
```

---

## Task 3 (DATA — gated on NotebookLM): Populate reference for all 288 types

**Files:**
- Modify: `docs/_meta/illumio-event-reference.json`

This is a **data-acquisition task**, not code. For each of the 288 `KNOWN_EVENT_TYPES`:
1. `description` + `category`: query the NotebookLM Illumio notebook (official-docs grounded). Cross-check category against `catalog.py::_event_category()`; where they disagree, the NotebookLM/official value wins and `_event_category` is corrected in Task 4.
2. `severity` + `remediation` + `doc_url`: from `runbook_for(event_type)` when available; else `severity="info"`, empty remediation.

- [ ] **Step 1:** Generate the skeleton with all 288 keys (category from `_event_category`, severity/remediation from runbooks) so only `description` needs human/NotebookLM fill:

```bash
python - <<'PY'
import json
from src.events.catalog import KNOWN_EVENT_TYPES, _event_category
from src.events.runbooks import runbook_for
out = {}
for et in sorted(KNOWN_EVENT_TYPES):
    rb = runbook_for(et) or {}
    out[et] = {"category": _event_category(et), "description": "",
               "severity": rb.get("severity_hint", "info"),
               "remediation": rb.get("response", ""), "doc_url": rb.get("runbook_url", "")}
json.dump(out, open("docs/_meta/illumio-event-reference.json", "w"), indent=2, ensure_ascii=False)
print("seeded", len(out))
PY
```

- [ ] **Step 2:** Fill every empty `description` from NotebookLM (English). Verify none remain empty: `python -c "import json;d=json.load(open('docs/_meta/illumio-event-reference.json'));print('empty:', [k for k,v in d.items() if not v['description']])"` → Expected: `empty: []`.
- [ ] **Step 3: Commit** `git add docs/_meta/illumio-event-reference.json && git commit -m "data(events): populate authoritative descriptions for all 288 event types"`

---

## Task 4: 100% coverage gate (TDD) + catalog single-source-of-truth

**Files:**
- Test: `tests/test_event_reference_coverage.py`
- Modify: `src/events/catalog.py`, `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Write the failing coverage test**

```python
def test_every_known_type_has_reference_and_i18n():
    import json
    from src.events.catalog import KNOWN_EVENT_TYPES, _HIDDEN_EVENT_TYPES
    from src.events.reference import load_reference
    ref = load_reference()
    visible = set(KNOWN_EVENT_TYPES) - set(_HIDDEN_EVENT_TYPES)
    missing = sorted(visible - set(ref))
    assert not missing, f"types missing from reference: {missing}"
    en = json.load(open("src/i18n_en.json")); zh = json.load(open("src/i18n_zh_TW.json"))
    for et in visible:
        key = "event_desc_" + et.replace(".", "_")
        assert en.get(key), f"{key} missing/empty in i18n_en.json"
        assert zh.get(key), f"{key} missing/empty in i18n_zh_TW.json"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_event_reference_coverage.py::test_every_known_type_has_reference_and_i18n -v`
Expected: FAIL — many `event_desc_*` keys missing.

- [ ] **Step 3: Generate i18n keys from the reference**

```bash
python - <<'PY'
import json
from src.events.reference import load_reference
ref = load_reference()
for path, lang in (("src/i18n_en.json","en"), ("src/i18n_zh_TW.json","zh")):
    d = json.load(open(path))
    for et, r in ref.items():
        d["event_desc_" + et.replace(".", "_")] = r.description  # zh filled via NotebookLM zh pass
    json.dump(d, open(path, "w"), indent=2, ensure_ascii=False, sort_keys=True)
PY
```
Then translate the zh_TW values via NotebookLM/existing glossary. Point `EVENT_DESCRIPTION_KEYS` in `catalog.py` at the generated keys (derive, don't hand-maintain).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_event_reference_coverage.py -v` and `python -m pytest tests/test_i18n_strings_parity.py tests/test_i18n_audit.py -q`
Expected: PASS (parity preserved — keys added to both locales).

- [ ] **Step 5: Commit**

```bash
git add tests/test_event_reference_coverage.py src/events/catalog.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(events): enforce 100% event description coverage via reference artifact"
```

---

## Task 5: Surface description + remediation in events viewer and alerts

**Files:**
- Modify: `src/gui/routes/events.py`, `src/alerts/template_utils.py`
- Test: `tests/test_event_reference_coverage.py`

- [ ] **Step 1: Write the failing test**

```python
def test_alert_body_includes_remediation_for_known_event():
    from src.alerts.template_utils import enrich_event_context
    ctx = enrich_event_context({"event_type": "request.authentication_failed"})
    assert ctx["severity"] == "critical"
    assert ctx["remediation"]  # non-empty actionable text
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_event_reference_coverage.py::test_alert_body_includes_remediation_for_known_event -v`
Expected: FAIL — `enrich_event_context` undefined or no remediation.

- [ ] **Step 3: Implement enrichment using the reference**

```python
# src/alerts/template_utils.py
from src.events.reference import load_reference

def enrich_event_context(event: dict) -> dict:
    ref = load_reference().get(event.get("event_type", ""))
    out = dict(event)
    if ref:
        out.update(description=ref.description, severity=ref.severity,
                   remediation=ref.remediation, doc_url=ref.doc_url)
    return out
```
Wire `enrich_event_context` into the alert template render path and expose `description`/`remediation` in `events.py` JSON responses.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_event_reference_coverage.py -v && python -m pytest tests/test_event_core.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alerts/template_utils.py src/gui/routes/events.py tests/test_event_reference_coverage.py
git commit -m "feat(events,alerts): surface description + remediation from reference"
```

---

## Self-Review notes
- **Spec coverage:** #1 (descriptions, Tasks 3–4), #3 (runbooks, Tasks 2 & 5), CI lock (Task 4). #2 (alert UX) and #4 (reporter-library) are separate findings-first tracks — not in this plan.
- **Type consistency:** `EventRef`, `load_reference`, `runbook_for`, `enrich_event_context` used consistently across tasks.
- **Open data dependency:** Task 3 descriptions require NotebookLM access; Tasks 1, 2, 4-skeleton, 5 are runnable now.
