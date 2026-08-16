"""The report-language selector must default to the operator's configured UI
language rather than a hard-coded value.

Phase 2A Task 11 retargeted this file. The legacy version asserted two
things about deleted files: that src/templates/index.html's
`<select id="m-gen-lang">` carried no hard-coded `selected` attribute, and
that src/static/js/dashboard.js defined `syncReportLangToUi()` to set it at
open time. The v2 reports area has no server-rendered select at all — it
builds the generate drawer from the live snapshot — so the same invariant is
asserted against src/static/js/v2/areas/reports.mjs, where the default is
read from /api/status's `language` field.
"""
from __future__ import annotations

import re
from pathlib import Path


REPORTS_MJS = Path(__file__).parent.parent / "src" / "static" / "js" / "v2" / "areas" / "reports.mjs"


def _source() -> str:
    return REPORTS_MJS.read_text(encoding="utf-8")


def test_report_lang_default_comes_from_the_configured_ui_language():
    js = _source()
    # state.lang is seeded from the status snapshot's `language`, not a literal.
    m = re.search(r"state\.lang\s*=\s*(.+)", js)
    assert m, "reports.mjs no longer seeds state.lang"
    seed = m.group(1)
    assert "status" in seed and "language" in seed, (
        f"report language must default to the configured UI language, got: {seed!r}"
    )


def test_report_lang_default_is_not_hardcoded_at_the_drawer():
    """The drawer must be handed state.lang, not a literal — the v2 shape of
    "no `selected` attribute baked into the template"."""
    js = _source()
    assert re.search(r"genDrawer\([^)]*state\.lang", js), (
        "the generate drawer must receive state.lang"
    )


def test_both_languages_are_offered():
    js = _source()
    assert '["en", "gui_report_lang_en"]' in js
    assert '["zh_TW", "gui_report_lang_zh_tw"]' in js
