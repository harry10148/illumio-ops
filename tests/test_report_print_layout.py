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
