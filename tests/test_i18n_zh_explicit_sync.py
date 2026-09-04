"""zh_explicit.json must stay in sync with zh_TW for the keys that depend on it.

## Why this file exists

`scripts/precompute_zh_translations.py` recomputes `src/i18n_zh_TW.json`, with
`src/i18n/data/zh_explicit.json` taking priority. So a key whose Chinese text
was hand-written but which is ABSENT from (or stale in) zh_explicit can be
silently reverted to machine translation on the next precompute run — the
failure mode the deleted guards named in so many words ("otherwise precompute
reverts").

Nothing else covers this. `scripts/audit_i18n_usage.py` checks en/zh
*existence* systematically (categories G and I) but never requires zh_explicit
to agree with zh_TW; at audit_i18n_usage.py:317-325 it reads zh_explicit only
as an exemption reason.

## What this restores (Task 11 review, Important 2)

Three deleted files each carried three-way assertions across
`src/i18n_en.json`, `src/i18n_zh_TW.json` AND `src/i18n/data/zh_explicit.json`:

  tests/test_gui_tls_days_format.py           gui_tls_days_humanized
                                              gui_tls_days_label_years
                                              gui_tls_days_label_months
  tests/test_gui_settings_confirm_password.py gui_new_password_confirm
                                              gui_password_mismatch
  tests/test_dashboard_kpi_tooltips.py        gui_card_unknown_types_tooltip
                                              gui_card_suppressed_tooltip

The first five are all still consumed — src/static/js/v2/areas/system.mjs:1554-1559
(the TLS "expires in N days (about ...)" readout) and :1806 / :1839 (the
change-password field and its mismatch hint) — so their guard is restored here.
The two tooltip keys have NO consumer in the v2 frontend (the legacy dashboard
story-stat tooltips they belonged to are gone); guarding the wording of a
string nobody renders would be guarding a corpse, so they are left in the
orphan list in task-11-report.md instead.

## Why five keys and not the general invariant

The reviewer's preferred form — "any gui_* key consumed in src/ that has a
zh_TW value must have a zh_explicit entry" — was implemented and MEASURED
before choosing: 1,536 gui_* keys are referenced from src/, 1,534 have a
zh_TW value, and **1,022 of those have no zh_explicit entry**. As a gate that
is an instant, project-wide red with a four-figure backlog behind it — a
catalogue-policy decision for its own task, not something to land inside a
GUI switchover. Turning it on here would mean either a 1,022-entry exclusion
list (which is not a gate) or 1,022 hand-written translations (which is not
this task).

So: the narrow guard is restored now, for exactly the keys that lost one, and
the general invariant is recorded with its real number in
task-11-report.md's backlog. `test_the_general_invariant_is_still_backlog`
below pins that number so it cannot quietly grow while nobody is looking.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
ZH = json.loads((ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
ZH_EXPLICIT = json.loads(
    (ROOT / "src" / "i18n" / "data" / "zh_explicit.json").read_text(encoding="utf-8")
)

# key -> the source file that renders it, so a dead key is visible as a dead
# key rather than silently guarded forever.
GUARDED = {
    "gui_tls_days_humanized": "src/static/js/v2/areas/system.mjs",
    "gui_tls_days_label_years": "src/static/js/v2/areas/system.mjs",
    "gui_tls_days_label_months": "src/static/js/v2/areas/system.mjs",
    "gui_new_password_confirm": "src/static/js/v2/areas/system.mjs",
    "gui_password_mismatch": "src/static/js/v2/areas/system.mjs",
}


def test_guarded_keys_exist_in_all_three_files():
    for key in GUARDED:
        assert key in EN and EN[key].strip(), f"{key} missing/empty in i18n_en.json"
        assert key in ZH and ZH[key].strip(), f"{key} missing/empty in i18n_zh_TW.json"
        assert key in ZH_EXPLICIT and ZH_EXPLICIT[key].strip(), (
            f"{key} missing from zh_explicit.json — precompute_zh_translations.py "
            f"will overwrite its hand-written Chinese with machine translation"
        )


def test_guarded_keys_are_identical_in_zh_tw_and_zh_explicit():
    """Existence is not enough: a STALE zh_explicit entry reverts the text too."""
    drift = {
        key: (ZH[key], ZH_EXPLICIT[key])
        for key in GUARDED
        if ZH.get(key) != ZH_EXPLICIT.get(key)
    }
    assert not drift, (
        "zh_explicit.json disagrees with i18n_zh_TW.json; the next precompute "
        f"run would replace the zh_TW value with the zh_explicit one: {drift}"
    )


def test_guarded_keys_still_have_a_consumer():
    """A key with no reader does not need this guard — it needs deleting.

    Without this, the two tooltip keys' fate (guarded here for months after
    the panel that rendered them was deleted) would just repeat.
    """
    orphans = []
    for key, source in GUARDED.items():
        text = (ROOT / source).read_text(encoding="utf-8")
        if key not in text:
            orphans.append((key, source))
    assert not orphans, (
        "these keys no longer appear in the file recorded as their consumer — "
        f"update GUARDED or drop them: {orphans}"
    )


def test_the_general_invariant_is_still_backlog():
    """Pin the size of the gap this file deliberately does not close.

    See the module docstring. The number is asserted as a CEILING so the
    backlog cannot silently grow; lower it whenever a batch is filled in, and
    when it reaches zero the narrow guard above can be replaced by the general
    invariant outright.
    """
    src = ROOT / "src"
    blob = []
    for pattern in ("*.py", "*.mjs", "*.js", "*.html"):
        for path in src.rglob(pattern):
            blob.append(path.read_text(encoding="utf-8", errors="ignore"))
    used = set(re.findall(r"[\"'](gui_[a-z0-9_]+)[\"']", "\n".join(blob)))

    translated = {k for k in used if str(ZH.get(k, "")).strip()}
    missing = {k for k in translated if k not in ZH_EXPLICIT}

    # Measured at 1022 when this guard was restored (Task 11 review); lowered to
    # 1021 after pinning gui_card_unknown and gui_errcard_retry, the two keys the
    # system.mjs/api.mjs/shell.mjs switchover started rendering. Lowered to 1004
    # after task 12b removed 17 keys that carried mockup design commentary
    # (DESIGN-ADDED notes and citations of deleted source files) out of
    # operator-facing copy. Lowered to 928 after task 12c pinned 76 keys whose
    # reviewer-facing copy (source citations, internal paths, product-vs-mockup
    # framing) was rewritten for operators and hand-translated into zh_explicit.
    # Lowered to 878 on 2026-09-04 after phase 3B (v3 GUI) pinned its 77 new
    # home / investigate-hub / five-area keys.
    assert len(missing) <= 878, (
        f"{len(missing)} gui_* keys rendered by src/ have a zh_TW value but no "
        "zh_explicit entry, up from the 1021 ceiling — "
        "new hand-written Chinese is being added without a zh_explicit entry, "
        "so precompute_zh_translations.py will revert it"
    )
    # ...and the five guarded above are not among them, which is the whole point.
    assert not (missing & set(GUARDED)), missing & set(GUARDED)
