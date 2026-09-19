"""The report and the console name a fleet bucket the same way.

One ``analyze_fleet()`` feeds three surfaces. The console
(``src/static/js/v2/areas/fleet.mjs``) has always had operator copy for the
eight pipeline buckets and the five score components; the VEN report printed
the raw dict keys instead — ``idle_compat_unknown``, ``visibility_not_ready``
— so the same workload was in "idle · not checked" on screen and in
``idle_compat_unknown`` on paper. Worse, the report's own design decided the
operator-facing spelling is ``Visibility only`` precisely because
``visibility_only`` is not a glossary term, and then printed the snake_case
form anyway.

These tests bind the two copies together in both languages. They are a static
comparison of the two key sets, which is the point: a renderer test would
only prove the report renders *something*, and a screenshot would only prove
it renders something today. What has to hold is that the two surfaces cannot
be given different words for the same bucket without a gate going red.

A missing key here is not a cosmetic failure. ``t()`` short-circuits on the
``rpt_``/``gui_`` prefixes (``src/i18n/data/strict_prefixes.json``), so the
cell would ship reading ``[MISSING:rpt_ven_fleet_stage_full]``.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from src.report.exporters.ven_html_exporter import VenHtmlExporter

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLEET_MJS = ROOT / "src" / "static" / "js" / "v2" / "areas" / "fleet.mjs"
LANGS = {
    "en": ROOT / "src" / "i18n_en.json",
    "zh_TW": ROOT / "src" / "i18n_zh_TW.json",
}


def _strings(lang: str) -> dict:
    return json.loads(LANGS[lang].read_text(encoding="utf-8"))


def _js_map(name: str) -> dict[str, str]:
    """Read one ``const <name> = { key: "i18n_key", ... }`` out of fleet.mjs.

    Parsed from the source rather than duplicated here, so that renaming a
    bucket on the console side surfaces as a missing pair instead of as two
    lists that quietly describe different things.
    """
    src = FLEET_MJS.read_text(encoding="utf-8")
    m = re.search(rf"const {name} = \{{(.*?)\n\}};", src, re.S)
    assert m, f"{name} not found in {FLEET_MJS.name}"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', m.group(1)))


PAIRS = [
    ("bucket", VenHtmlExporter._FLEET_STAGE_KEYS, "BUCKET_KEYS"),
    ("score component", VenHtmlExporter._FLEET_PART_KEYS, "PART_KEYS"),
]


@pytest.mark.parametrize("what,report_keys,js_name", PAIRS)
def test_the_report_covers_every_bucket_the_console_knows(what, report_keys, js_name):
    console = _js_map(js_name)
    assert set(report_keys) == set(console), (
        f"the report and the console disagree about which {what}s exist: "
        f"report-only={sorted(set(report_keys) - set(console))}, "
        f"console-only={sorted(set(console) - set(report_keys))}")


@pytest.mark.parametrize("lang", sorted(LANGS))
@pytest.mark.parametrize("what,report_keys,js_name", PAIRS)
def test_both_surfaces_use_the_same_words(what, report_keys, js_name, lang):
    strings = _strings(lang)
    console = _js_map(js_name)
    for name, rpt_key in sorted(report_keys.items()):
        gui_key = console[name]
        assert rpt_key in strings, f"{rpt_key} missing from {lang}"
        assert gui_key in strings, f"{gui_key} missing from {lang}"
        assert strings[rpt_key] == strings[gui_key], (
            f"{lang}: the {what} {name!r} is {strings[rpt_key]!r} in the report "
            f"and {strings[gui_key]!r} in the console")


@pytest.mark.parametrize("lang", sorted(LANGS))
@pytest.mark.parametrize("what,report_keys,js_name", PAIRS)
def test_no_surface_falls_back_to_the_raw_field_name(what, report_keys, js_name, lang):
    """The copy must be words, not the dict key spelled out again.

    Without this, satisfying the parity test above is trivial: set both
    strings to the field name and they match perfectly while saying nothing.
    """
    strings = _strings(lang)
    for name, rpt_key in sorted(report_keys.items()):
        value = strings[rpt_key]
        if "_" not in name:
            # Single-word PCE vocabulary (selective, full, online, version…)
            # is already the operator's word; there is nothing to translate.
            continue
        assert value != name, (
            f"{lang}: {rpt_key} is still the field name {name!r}")
