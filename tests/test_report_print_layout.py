from src.report.exporters.report_css import BASE_CSS


def test_card_no_longer_has_page_break_inside_avoid():
    lines = [l.strip() for l in BASE_CSS.split('\n') if 'page-break-inside: avoid' in l]
    card_lines = [l for l in lines if l.startswith('.card')]
    assert card_lines == [], f"Found: {card_lines}"


def test_thead_display_table_header_group():
    assert 'thead { display: table-header-group' in BASE_CSS


def test_tr_page_break_inside_avoid():
    assert 'tr { page-break-inside: avoid' in BASE_CSS


def test_wide_table_font_size_in_print():
    assert '.report-table-panel--wide .report-table { font-size: 8pt' in BASE_CSS


def test_cover_page_css_present():
    assert '.report-cover {' in BASE_CSS


def test_page_counter_present():
    assert 'counter(page)' in BASE_CSS


from src.report.exporters.cover_page import build_cover_page


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
