import re

from bs4 import BeautifulSoup

from src.report.exporters.grade_colors import grade_tone
from src.report.exporters.report_shell import (
    SHELL_CSS, ShellCover, ShellSection, build_shell_document, wide_table_attrs)


def _doc(**kw):
    cover = ShellCover(title="Illumio 資安與風險報表", doc_title="Illumio 流量報告",
                       type_label="安全風險分析", eyebrow="Illumio Ops",
                       grade="D", score="52", meta={"PCE": "pce.test", "資料範圍": "2026-01-01 – 2026-02-01"})
    sections = [
        ShellSection(id="exec-summary", title="執行摘要", kind="exec",
                     html='<div class="kpi-strip"><div class="kpi">100</div></div>'),
        ShellSection(id="findings", title="發現與行動", kind="finding", tone="crit",
                     marks={"CRITICAL": 2, "LOW": 5},
                     html='<p>lateral-movement finding narrative</p>'),
        ShellSection(id="overview", title="流量總覽", kind="detail",
                     html='<div class="report-table-panel"><table class="report-table"></table></div>'),
    ]
    return build_shell_document(lang="zh_TW", cover=cover, sections=sections,
                                appendix_html="<p>illumio-ops v9 產出</p>", **kw)


def test_document_skeleton_and_order():
    soup = BeautifulSoup(_doc(), "html.parser")
    doc = soup.select_one("div.sheet > div.doc")
    kids = [c.name + "." + " ".join(c.get("class", [])) for c in doc.find_all(recursive=False)]
    assert kids[0].startswith("header.cover")
    assert any(k.startswith("section.exec") for k in kids)
    assert any(k.startswith("nav.toc") for k in kids)
    assert kids[-1].startswith("section.appendix")


def test_toc_entries_match_sections_and_chapter_order_is_preserved():
    soup = BeautifulSoup(_doc(), "html.parser")
    toc_hrefs = [a["href"] for a in soup.select("nav.toc ol a")]
    assert toc_hrefs == ["#exec-summary", "#findings", "#overview"]  # 不重排
    chapters = [s["id"] for s in soup.select("div.chapters > section.chapter")]
    assert chapters == ["findings", "overview"]


def test_cover_uses_full_title_not_type_label():
    soup = BeautifulSoup(_doc(), "html.parser")
    assert soup.title.string == "Illumio 流量報告"          # doc_title 逐字
    assert soup.select_one("header.cover h1").get_text() == "Illumio 資安與風險報表"


def test_marks_are_all_rendered_never_capped():
    soup = BeautifulSoup(_doc(), "html.parser")
    chips = soup.select("#findings .chapter-marks .mark-chip")
    assert len(chips) == 2  # 原型教訓：chips[:3] 靜默截斷是 bug，全部顯示


def test_marks_outside_the_severity_rank_are_still_rendered():
    doc = build_shell_document(
        lang="en",
        cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="s", title="s", html="<p>x</p>",
                               marks={"CRITICAL": 1, "UNRANKED": 3})],
    )
    soup = BeautifulSoup(doc, "html.parser")
    texts = [c.get_text() for c in soup.select("#s .chapter-marks .mark-chip")]
    assert texts == ["CRITICAL 1", "UNRANKED 3"]


def test_print_button_and_table_js_present():
    html = _doc()
    assert 'class="print-btn"' in html and "window.print()" in html
    assert "<script" in html  # TABLE_JS 保留
    assert "<script" not in _doc(include_table_js=False)


def test_escaping_of_untrusted_title():
    s = ShellSection(id="x", title='<script>alert(1)</script>', html="<p>ok</p>")
    cover = ShellCover(title="t", doc_title="d", type_label="x")
    out = build_shell_document(lang="en", cover=cover, sections=[s])
    assert "<script>alert(1)</script>" not in out and "&lt;script&gt;" in out


def test_escaping_of_untrusted_cover_fields():
    cover = ShellCover(title='<img src=x onerror=alert(1)>',
                       doc_title='"><script>bad()</script>',
                       type_label='" onload="bad()',
                       eyebrow="<b>e</b>", kicker="<b>k</b>",
                       grade='<i>D</i>', score='<i>1</i>',
                       badges=(("<u>b</u>", "warn"),),
                       meta={"<k>": "<v>"})
    out = build_shell_document(lang="en", cover=cover,
                               sections=[ShellSection(id="s", title="s", html="")])
    for payload in ("<img src=x", "<script>bad()", '" onload="bad()',
                    "<b>e</b>", "<b>k</b>", "<i>D</i>", "<i>1</i>",
                    "<u>b</u>", "<k>", "<v>"):
        assert payload not in out


def test_section_html_is_not_double_escaped():
    out = build_shell_document(
        lang="en",
        cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="s", title="s", html='<p class="note">kept</p>')],
    )
    assert '<p class="note">kept</p>' in out


def test_shell_css_print_invariants():
    assert "size: A4 portrait" in SHELL_CSS
    assert "@page wide" in SHELL_CSS and "size: A4 landscape" in SHELL_CSS
    assert "page: wide" in SHELL_CSS                       # --landscape 取用
    assert "display: table-header-group" in SHELL_CSS      # 表頭每頁重複
    assert "content-visibility: visible" in SHELL_CSS      # cell-long 列印展開（PDF 文字層）
    assert re.search(r"\.chapter\s*\{[^}]*break-before:\s*page", SHELL_CSS)
    assert "prefers-color-scheme" not in SHELL_CSS         # 恆亮，無 dark 分支


def test_shell_css_is_offline_self_contained():
    # 單檔離線可開：不得引入任何遠端資源。
    assert "http://" not in SHELL_CSS and "https://" not in SHELL_CSS
    assert "@import" not in SHELL_CSS


def test_shell_css_keeps_screen_print_visibility_pair():
    # `.print-only { display: none; }` 是螢幕側的一半，列印段才翻回 block；
    # 刪掉它會讓 print-only 內容在螢幕上現形。
    assert ".print-only { display: none; }" in SHELL_CSS
    assert ".print-btn { display: none; }" in SHELL_CSS
    # 舊的雙封面防禦性隱藏已移除——產品端不再產第二張封面。
    assert ".report-cover-block.screen-only" not in SHELL_CSS


def test_wide_table_attrs_threshold():
    cls, hint = wide_table_attrs(11, "zh_TW")
    assert "report-table-panel--landscape" in cls and "11" in hint and "table-hint" in hint
    assert wide_table_attrs(9, "zh_TW") == ("", "")


def test_grade_tone_maps_d_and_f_to_critical_red():
    assert grade_tone("D") == grade_tone("F") == "crit"
    assert grade_tone(None) == "neutral"
    assert grade_tone("") == "neutral"
    assert grade_tone("?") == "neutral"
    assert grade_tone("a") == "ok" and grade_tone("C") == "warn"


def test_crit_tone_ink_is_red_not_orange():
    match = re.search(r"--tone-crit-fg:\s*(#[0-9A-Fa-f]{6})", SHELL_CSS)
    assert match, "SHELL_CSS must define --tone-crit-fg"
    hexval = match.group(1).upper()
    assert hexval != "#F97316"                            # UX_Review §7.3
    r, g, b = (int(hexval[i:i + 2], 16) for i in (1, 3, 5))
    assert r > 2 * g and r > 2 * b                        # 紅，不是橘


def test_grade_chip_uses_tone_token_not_inline_colour():
    soup = BeautifulSoup(_doc(), "html.parser")
    chip = soup.select_one("header.cover .grade-chip")
    assert chip is not None
    assert chip["data-tone"] == "crit"                    # grade D
    assert not chip.get("style")
    assert "color: var(--ink)" in SHELL_CSS               # .score-num 吃 tone


def test_document_tone_is_critical_when_any_chapter_is_critical():
    soup = BeautifulSoup(_doc(), "html.parser")
    assert soup.select_one("header.cover")["data-tone"] == "crit"
    out = build_shell_document(
        lang="en",
        cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="a", title="a", html="", tone="warn"),
                  ShellSection(id="b", title="b", html="", tone="info")],
    )
    assert BeautifulSoup(out, "html.parser").select_one("header.cover")["data-tone"] == "warn"


def test_chapter_index_is_ascii_and_appendix_indexes_chapters():
    soup = BeautifulSoup(_doc(), "html.parser")
    assert [s.get_text() for s in soup.select(".chapter-index")] == ["S01", "S02"]
    assert [d.get_text() for d in soup.select(".appendix dl dt")][-2:] == ["01", "02"]


def test_rule_index_renders_with_severity_tone():
    out = _doc(rule_index=[("B001", "SMB exposure", "CRITICAL")])
    soup = BeautifulSoup(out, "html.parser")
    item = soup.select_one("ol.rule-index li")
    assert item["data-tone"] == "crit"
    assert item.select_one("code").get_text() == "B001"
    assert item.select_one(".rule-sev").get_text() == "CRITICAL"


def test_html_lang_attribute_follows_lang():
    assert '<html lang="zh-TW">' in _doc()
    assert '<html lang="en">' in build_shell_document(
        lang="en", cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[])
