---
title: i18n Workflow
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - src/i18n/data/zh_explicit.json
  - src/i18n_en.json
  - src/i18n_zh_TW.json
  - tests/test_i18n_audit.py
  - tests/test_i18n_strings_parity.py
  - scripts/audit_i18n_usage.py
  - commit 2e17d81
related_docs:
  - ../architecture/i18n-contract.md
  - ../reference/glossary.md
  - dev-setup.md
  - release-process.md
---

> **[English](i18n-workflow.md)** | [繁體中文](i18n-workflow_zh.md)
> 📍 [INDEX](../INDEX.md) › Contributing › i18n Workflow
> 🔍 Last verified **2026-05-15** against commit `2e17d81` — see frontmatter for sources

# i18n Workflow

This guide explains how to add and maintain internationalization (i18n) keys for
the illumio-ops UI and reports.  The system supports English (`en`) and
Traditional Chinese (`zh_TW`).  For the underlying contract (key resolution,
storage rules, language switching) see
[`../architecture/i18n-contract.md`](../_archive/architecture/i18n-contract.md).

---

## When to add a new i18n key

Add a key whenever you introduce user-visible text that will appear in:

- Any interactive menu, label, button, or prompt rendered by `src/gui/` or
  `src/main.py`.
- A report section header, column label, or KPI title in `src/report/`.
- A scheduled-job status or email body in `src/report_scheduler.py`.
- An event / alert message surfaced to the operator.

Do **not** add a key for:

- Internal log messages (Python `logging` calls) — they always stay English.
- Data stored to disk (e.g., rule names, policy labels) — these are stored in
  English and must be translated at display time via `t(key, lang=lang)`;
  see [Common pitfalls](#common-pitfalls).
- Hard-coded strings inside test fixtures or developer tooling.

---

## Where keys live

| File | Role |
|------|------|
| `src/i18n_en.json` | **Source of truth** — English values for every key. |
| `src/i18n_zh_TW.json` | zh_TW translations.  Must have a 1-to-1 match with `i18n_en.json`. |
| `src/i18n/data/zh_explicit.json` | Authoritative Illumio-term glossary.  When a key covers an Illumio product term (workload, PCE, VEN, pairing profile, …), the approved zh_TW value lives here and is cross-checked by CI. |
| `src/i18n/data/dashboard_approved.json` | Subset of keys whose zh_TW values are locked for the dashboard KPI panel.  CI Category J enforces exact-match. |

Cross-reference: [`../architecture/i18n-contract.md`](../_archive/architecture/i18n-contract.md)
explains how `t()` resolves keys at runtime and how `zh_explicit.json` overrides
the base translation file.

---

## Adding a key — step-by-step

### Step 1 — Decide the key name

Keys follow the pattern `<area>_<purpose>` where `<area>` is the functional
prefix.  Common prefixes:

| Prefix | Area |
|--------|------|
| `gui_` | Interactive GUI widgets (`src/gui/`) |
| `menu_` | Main-menu and sub-menu labels |
| `alert_` | Alert category / message strings |
| `rpt_` | Report headers and email bodies |
| `rs_` | Rule scheduler UI |
| `pd_` | Policy-decision labels |
| `lbl_` | Generic UI labels |
| `pu_` | Policy-usage module |

Examples: `gui_accel_bulk_btn`, `alert_cat_cluster`, `rs_back`, `pd_1`.

Choose the shortest descriptive name that makes the key's purpose unambiguous
when read in isolation.

### Step 2 — Add the English value to `src/i18n_en.json`

```json
// src/i18n_en.json  (alphabetical insertion)
{
  "gui_my_new_label": "My New Label"
}
```

Keep the English value concise.  Interpolation placeholders use
`{variable_name}` syntax, e.g. `"Lag: {lag}s"`.

### Step 3 — Add the zh_TW value to `src/i18n_zh_TW.json`

```json
// src/i18n_zh_TW.json
{
  "gui_my_new_label": "我的新標籤"
}
```

Both files must contain **exactly the same set of keys**; parity is enforced by
CI Category I (`audit_zh_parity_against_en`).

### Step 4 — If the key covers an Illumio-specific term: also update `src/i18n/data/zh_explicit.json`

```json
// src/i18n/data/zh_explicit.json
{
  "alert_cat_my_illumio_term": "我的 Illumio 詞彙"
}
```

Check [`../reference/glossary.md`](../reference/glossary.md) for already-approved
translations before inventing a new one.  The audit (`--only E`) will flag any
`i18n_zh_TW.json` value that diverges from `zh_explicit.json` for a key present
in both files.

### Step 5 — Reference the key in source via `t()`

```python
from src.i18n import t

# Standard usage — renders in the user's current language
label = t("gui_my_new_label")

# For strings going into stored data or email output, pass lang explicitly
subject = t("rpt_email_traffic_subject", lang=lang)
```

Import path: `src/i18n/__init__.py` exposes the `t()` function.

### Step 6 — Run the audit tests

```bash
# Fast unit-level parity checks (run from repo root, venv activated)
pytest tests/test_i18n_audit.py tests/test_i18n_strings_parity.py -v

# Full comprehensive audit script (all categories A–J)
python scripts/audit_i18n_usage.py

# Run a single category
python scripts/audit_i18n_usage.py --only J   # dashboard approved-translation gate
```

All categories must exit 0 before merging.

### Step 7 — Verify in the UI by switching language

```bash
# Run the app, go to Settings → Language, toggle to 繁體中文
python -m src.main
```

Check that your new label renders correctly in both languages without layout
overflow or missing text.

---

## Glossary alignment

Before translating any Illumio product term (workload, PCE, VEN, enforcement
boundary, pairing profile, label, IP list, …) check the project glossary first:

- [`../reference/glossary.md`](../reference/glossary.md) — human-readable
  reference with approved EN and zh_TW terms.
- `src/i18n/data/zh_explicit.json` — machine-readable authoritative source used
  by the audit script (Category E: glossary violations).

If the glossary does not yet contain your term, add it to **both** files in the
same PR.  Do not add a translation to `i18n_zh_TW.json` that contradicts
`zh_explicit.json` — CI will catch the divergence and block the merge.

---

## Approved translations gate (CI)

**Category J** (`audit_dashboard_approved_translations`) was added in commit
`b9d88de` as a regression gate for the 9 dashboard mini-KPI translations.

What it checks:

1. Every key listed in `src/i18n/data/dashboard_approved.json` must be present
   in `src/i18n_zh_TW.json`.
2. The zh_TW value must match the approved value **exactly**.
3. The value must have a Han-character ratio ≥ 0.8, unless the key appears in
   `han_ratio_exceptions` (reserved for legitimate Latin-glossary terms such as
   `PCE`, `VEN`).

**What causes a CI failure:**

- Editing a dashboard KPI translation without updating `dashboard_approved.json`.
- Copying an auto-translated string (e.g. from a machine-translation tool) that
  disagrees with the approved value.
- Accidentally running a bulk key-rename that shifts a dashboard key.

To intentionally update an approved translation, edit **both**
`src/i18n_zh_TW.json` and `src/i18n/data/dashboard_approved.json` in the same
commit and include a reviewer note explaining the change.

The gate is exercised by `tests/test_i18n_audit.py` alongside Categories A–I.

---

## Running i18n audit locally

```bash
# All categories (A–J) — standard run before opening a PR
python scripts/audit_i18n_usage.py

# Single category
python scripts/audit_i18n_usage.py --only A   # placeholder leaks
python scripts/audit_i18n_usage.py --only E   # glossary violations
python scripts/audit_i18n_usage.py --only I   # zh parity vs EN
python scripts/audit_i18n_usage.py --only J   # dashboard approved translations

# Run the pytest suite that wraps the audit
pytest tests/test_i18n_audit.py -v

# Run all i18n-related tests at once
pytest tests/test_i18n_*.py -v
```

The audit script prints a summary table.  A non-zero exit code means at least
one finding requires attention.  Findings are grouped by category (A–J) with
file + line references.

---

## Common pitfalls

### 1. Language leakage into stored data

**Wrong:**
```python
# Stores zh_TW into the schedule config — breaks when language changes
schedule["type_label"] = t("rpt_email_traffic_subject")
```

**Right:**
```python
# Translate at render time using the recipient's language, not the UI language
type_label = t("rpt_email_traffic_subject", lang=lang)
```

Stored data (JSON configs, rule names, database fields) must always be in
English.  Translate on output.  The `lang` parameter accepts `"en"` or `"zh_TW"`.
Test `tests/test_report_i18n_leakage.py` enforces this pattern.

### 2. Missing zh_TW counterpart

Adding a key to `i18n_en.json` without a matching entry in `i18n_zh_TW.json`
will cause Category I to fail.  Always add both in the same commit.  The parity
check runs in `tests/test_i18n_strings_parity.py` as well.

### 3. Inventing Illumio-term translations

Do not translate `Workload`, `PCE`, `VEN`, `Enforcement Boundary`, `Pairing
Profile`, or any Illumio product concept without checking `zh_explicit.json`
first.  Unauthorized translations trigger Category E failures and may introduce
terminology inconsistencies that are costly to fix retroactively.

If `zh_explicit.json` does not yet contain the term, add it there (with a source
reference or team sign-off) before adding it to `i18n_zh_TW.json`.

---

## Related Docs

- [i18n Contract (architecture)](../_archive/architecture/i18n-contract.md) — the underlying contract
- [Glossary](../reference/glossary.md) — Illumio terminology
- [Dev Setup](dev-setup.md) — getting your venv ready first
- [Release Process](release-process.md) — what audit gates run before release
