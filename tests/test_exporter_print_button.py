"""Guard: every HTML report exporter must render the shared print button.

rule_hit_count shipped without one (2026-07-04 print-layout plan missed it).
The print button is this product's only route from an HTML report to a PDF, so
losing it on one family is a shipped-defect-class bug, not cosmetics.

This used to grep the exporter *sources* for the literal ``print-btn``. That
stopped meaning anything the moment an exporter started getting its button from
a shared renderer instead of writing the markup itself: the traffic family moved
onto ``report_shell.build_shell_document()`` in Phase 2B, the button was still
in every rendered report, and the scan went red anyway — while, in the other
direction, a source literal sitting in an unreachable branch would have kept the
scan green with no button on the page at all.

So it renders now. Each report type is built through
``tests/report_shell/fixtures.BUILDERS`` and the button is asserted in the
output the reader actually receives. ``EXPORTER_TYPES`` keeps the old file-level
coverage floor: a new ``*html_exporter.py`` module has to be listed here, with a
fixture that renders it, or this test fails.
"""
from pathlib import Path

import pytest

from tests.report_shell.fixtures import BUILDERS

ROOT = Path(__file__).resolve().parents[1]
EXPORTER_DIR = ROOT / "src" / "report" / "exporters"

# exporter module -> the report types that render through it.
EXPORTER_TYPES: dict[str, tuple[str, ...]] = {
    "html_exporter.py": ("traffic", "security_risk", "network_inventory"),
    "audit_html_exporter.py": ("audit",),
    "ven_html_exporter.py": ("ven_status",),
    "policy_usage_html_exporter.py": ("policy_usage",),
    "policy_diff_html_exporter.py": ("policy_diff",),
    "app_summary_html_exporter.py": ("app_summary",),
    "rule_hit_count_html_exporter.py": ("rule_hit_count",),
    "readiness_html_exporter.py": ("readiness",),
}

ALL_TYPES = sorted({t for types in EXPORTER_TYPES.values() for t in types})


def test_every_exporter_module_is_covered_by_a_fixture():
    """The file-level floor the old source scan provided, kept.

    Without this a newly added exporter family could ship with no button and no
    test would notice, because nothing would be rendering it.
    """
    on_disk = {p.name for p in EXPORTER_DIR.glob("*html_exporter.py")}
    assert on_disk == set(EXPORTER_TYPES), (
        "exporter modules and the covered-type map disagree; add the new "
        f"module here with a fixture that renders it: {on_disk ^ set(EXPORTER_TYPES)}")
    assert len(EXPORTER_TYPES) >= 8
    missing_fixture = [t for t in ALL_TYPES if t not in BUILDERS]
    assert not missing_fixture, f"no fixture builder for: {missing_fixture}"


@pytest.mark.parametrize("report_type", ALL_TYPES)
def test_rendered_report_offers_the_print_button(report_type):
    html = BUILDERS[report_type]()
    assert 'class="print-btn"' in html, (
        f"{report_type}: 渲染輸出裡沒有列印按鈕——使用者拿不到 PDF 入口")
    # The class alone is not the affordance; the handler is what prints.
    assert "window.print()" in html, f"{report_type}: 列印按鈕沒有掛上 window.print()"
