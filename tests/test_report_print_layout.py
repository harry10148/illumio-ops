import pandas as pd

from src.report.exporters.report_css import BASE_CSS
from src.report.exporters.cover_page import build_cover_page
from src.report.exporters.html_exporter import HtmlExporter


def test_card_no_longer_has_page_break_inside_avoid():
    lines = [l.strip() for l in BASE_CSS.split('\n') if 'page-break-inside: avoid' in l]
    card_lines = [l for l in lines if l.startswith('.card')]
    assert card_lines == [], f"Found: {card_lines}"


def test_thead_display_table_header_group():
    assert 'thead { display: table-header-group' in BASE_CSS


def test_tr_page_break_inside_avoid():
    assert 'tr { page-break-inside: avoid' in BASE_CSS


def test_wide_table_font_size_in_print():
    print_block = BASE_CSS.split('@media print')[1]
    assert '.report-table-panel--wide .report-table {' in print_block
    assert 'font-size: 7.5pt' in print_block


def test_cover_page_css_present():
    assert '.report-cover {' in BASE_CSS


def test_cover_hidden_in_screen():
    # Cover page must be hidden in browser (display: none in base CSS)
    # so it doesn't show as a dark block when viewing the HTML report.
    assert 'display: none' in BASE_CSS.split('@media print')[0].split('.report-cover')[1]


def test_cover_visible_in_print():
    # Cover page must reappear in print mode with flex layout and 100vh height.
    print_block = BASE_CSS.split('@media print')[1]
    assert 'display: flex' in print_block
    assert '100vh' in print_block


def test_print_table_overflow_wrap():
    # Tables must use overflow-wrap:break-word (not anywhere) to preserve min-content-width for
    # proportional column distribution while still breaking long unbreakable strings.
    print_block = BASE_CSS.split('@media print')[1]
    assert 'overflow-wrap: break-word' in print_block


def test_chart_container_overflow_hidden_in_print():
    # Chart containers must clip overflow to prevent legend/axis bleeding into adjacent content.
    print_block = BASE_CSS.split('@media print')[1]
    assert '.chart-container { page-break-inside: avoid; overflow: hidden' in print_block


def test_page_counter_present():
    assert 'counter(page)' in BASE_CSS


def test_cover_page_contains_title():
    html = build_cover_page(
        title="Traffic Security Report",
        report_type="Security Risk",
        date_range=("2026-04-01", "2026-05-11"),
        pce_url="pce.example.com",
        org_name="Acme Corp",
        lang="en",
    )
    assert "Traffic Security Report" in html
    assert "pce.example.com" in html
    assert "Acme Corp" in html
    assert "report-cover" in html


def test_cover_page_zh_tw():
    html = build_cover_page(
        title="流量安全報告",
        report_type="",
        date_range=("", ""),
        pce_url="",
        org_name="",
        lang="zh_TW",
    )
    assert "流量安全報告" in html
    assert "產生時間" in html


def test_cover_page_empty_optional_fields():
    html = build_cover_page(
        title="Test",
        report_type="",
        date_range=("", ""),
        pce_url="",
        org_name="",
        lang="en",
    )
    assert "📅" not in html
    assert "🖥" not in html


def _minimal_results() -> dict:
    return {k: {} for k in [
        "mod01", "mod02", "mod03", "mod04", "mod05", "mod06",
        "mod07", "mod08", "mod09", "mod11", "mod12",
        "mod13", "mod14", "mod15",
    ]}


def test_html_exporter_cover_page():
    exp = HtmlExporter(
        _minimal_results(),
        pce_url="pce.test", org_name="TestOrg",
        date_range=("2026-01-01", "2026-05-01"), lang="en",
    )
    html = exp.build()
    assert 'class="report-cover' in html
    assert "pce.test" in html
    assert "TestOrg" in html


def test_html_exporter_data_report_title():
    exp = HtmlExporter(_minimal_results(), lang="en")
    html = exp.build()
    assert 'data-report-title="' in html
    assert 'data-report-title=""' not in html


def test_screen_td_breaks_long_words():
    # Screen layout must break long words in table cells to prevent
    # horizontal scrolling on narrow viewports (URLs, hostnames, etc.).
    screen_part = BASE_CSS.split('@media print')[0]
    td_rule = [ln for ln in screen_part.splitlines() if '.report-table tbody td' in ln]
    assert td_rule and 'overflow-wrap: break-word' in td_rule[0]
