import re
from pathlib import Path

from bs4 import BeautifulSoup

from src.report.exporters.grade_colors import grade_tone
from src.report.exporters.report_shell import (
    APPENDIX_SECTION_ID, SHELL_CSS, SHELL_CSS_PORT_MARKER, ShellCover,
    ShellSection, build_shell_document, wide_table_attrs)

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN_SHELL_CSS = REPO_ROOT / "design" / "v2" / "reports" / "shell.css"


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


def _sections(n_exec):
    execs = [ShellSection(id=f"e{i}", title=f"E{i}", kind="exec", html="")
             for i in range(n_exec)]
    chapters = [ShellSection(id=f"c{i}", title=f"C{i}", kind="detail", html="")
                for i in range(3)]
    return execs + chapters


def _numbering(n_exec):
    """Return the three numberings the shell shows the reader."""
    soup = BeautifulSoup(build_shell_document(
        lang="en", cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=_sections(n_exec)), "html.parser")
    return {
        "toc": [(a.select_one(".toc-num").get_text(),
                 a.select_one(".toc-label").get_text())
                for a in soup.select("nav.toc ol a")],
        "chapter": [(s.select_one(".chapter-index").get_text(),
                     s.select_one(".chapter-title").get_text())
                    for s in soup.select("div.chapters > section.chapter")],
        "appendix": [(dt.get_text(), dt.find_next_sibling("dd").get_text())
                     for dt in soup.select(".appendix-grid div:nth-of-type(2) dl dt")],
    }


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


def test_zero_count_marks_are_deliberately_not_rendered():
    # 這是明示決定（見 _mark_chips docstring）：0 代表「本章沒有這級標記」，
    # 畫成 "CRITICAL 0" 會被讀成有發現。非零的一律不丟。
    doc = build_shell_document(
        lang="en",
        cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="s", title="s", html="",
                               marks={"CRITICAL": 0, "LOW": 2, "UNRANKED": 0})],
    )
    soup = BeautifulSoup(doc, "html.parser")
    assert [c.get_text() for c in soup.select("#s .mark-chip")] == ["LOW 2"]


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


def test_shell_css_releases_js_autofit_widths_in_print():
    """F1 守門：TABLE_JS 把量到的寬度寫成 table/th/col 的 inline style，只有
    !important 蓋得過 inline。少任何一條，列印時寬表就會被 panel 裁掉
    （2026-07-23 視覺實檢：發現與行動表近半內容消失）。"""
    print_block = SHELL_CSS.split("@media print")[1]
    for rule in (
        ".report-table { width: 100% !important; min-width: 0 !important; }",
        ".report-table col { width: auto !important; min-width: 0 !important; }",
        ".report-table thead th { width: auto !important; min-width: 0 !important; }",
        ".report-table-panel { overflow: visible; }",
    ):
        assert rule in print_block, f"missing wide-table print release rule: {rule}"
    # ...and the width floors that must survive the release have to be
    # !important too, or auto layout squeezes meta columns to one char a line.
    for floor in ("min-width: 14em !important", "width: 30% !important",
                  "min-width: 5.5em !important", "min-width: 7.5em !important"):
        assert floor in print_block, f"width floor lost its !important: {floor}"


def test_shell_css_is_offline_self_contained():
    # 單檔離線可開：不得引入任何遠端資源。
    assert "http://" not in SHELL_CSS and "https://" not in SHELL_CSS
    assert "@import" not in SHELL_CSS
    # url() 也要查——只允許內嵌的 data: URI，任何檔案/網路參照都是外部相依。
    for ref in re.findall(r"url\(\s*['\"]?([^'\")]*)", SHELL_CSS):
        assert ref.startswith("data:"), f"non-inline url() in SHELL_CSS: {ref!r}"


def test_shell_css_keeps_screen_print_visibility_pair():
    # `.print-only { display: none; }` 是螢幕側的一半，列印段才翻回 block；
    # 兩側都要在，只留一側等於功能壞掉而測試照樣綠。
    screen_block, print_block = SHELL_CSS.split("@media print")
    assert ".print-only { display: none; }" in screen_block
    assert ".print-only { display: block; }" in print_block
    assert ".screen-only { display: none; }" in print_block
    assert ".print-btn { display: none; }" in print_block
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


def test_score_survives_when_grade_is_empty():
    """F2：score 曾整個被 `if cover.grade:` 包住，grade 空時分數在輸出裡
    一個字都不存在——無聲丟資料。"""
    out = build_shell_document(
        lang="en",
        cover=ShellCover(title="t", doc_title="d", type_label="x", score="52"),
        sections=[ShellSection(id="s", title="s", html="")])
    assert "52" in out
    soup = BeautifulSoup(out, "html.parser")
    assert soup.select_one("header.cover .score-denom").get_text() == "52"
    assert soup.select_one("header.cover .grade-chip") is None   # 無 grade 不畫 chip


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


def test_chapter_index_is_ascii():
    soup = BeautifulSoup(_doc(), "html.parser")
    assert [s.get_text() for s in soup.select(".chapter-index")] == ["S01", "S02"]


def test_all_three_numberings_agree_for_any_exec_count():
    """F3：TOC / 章頭 / 附錄索引原本各編各的，只有 n_exec == 1 時巧合對齊，
    而所有 fixture 都是那一格。三者現在都讀同一個序列。"""
    for n_exec in (0, 1, 2, 3):
        nums = _numbering(n_exec)
        titles = [f"E{i}" for i in range(n_exec)] + [f"C{i}" for i in range(3)]
        expected = [f"{i:02d}" for i in range(len(titles))]

        assert [n for n, _ in nums["toc"]] == expected
        assert [t for _, t in nums["toc"]] == titles
        # 附錄索引涵蓋每一章（含 exec），號碼與 TOC 相同
        assert nums["appendix"] == list(zip(expected, titles))
        # 章頭只出現在非 exec 章，但用的是同一組號碼
        assert nums["chapter"] == [
            (f"S{num}", title)
            for num, title in zip(expected, titles) if title.startswith("C")
        ]


def test_unknown_kind_degrades_to_detail_instead_of_vanishing():
    out = build_shell_document(
        lang="en", cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="s", title="s", html="", kind="Detail")])
    soup = BeautifulSoup(out, "html.parser")
    section = soup.select_one("div.chapters > section.chapter")
    assert section["data-shell"] == "detail"
    assert section.select_one(".chapter-eyebrow").get_text() == "Details"


def test_empty_appendix_html_emits_no_empty_colophon():
    out = build_shell_document(
        lang="en", cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="s", title="s", html="")])
    assert 'class="colophon"' not in out
    assert 'class="colophon"' in _doc()


def test_appendix_uses_the_exported_section_id():
    # APPENDIX_SECTION_ID is the reserved id callers are told to avoid; it has
    # to be the one the renderer actually emits, not a second copy that can
    # drift away from the hardcoded string.
    soup = BeautifulSoup(_doc(), "html.parser")
    assert soup.select_one("section.appendix")["id"] == APPENDIX_SECTION_ID


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


# ---------------------------------------------------------------------------
# F4 — drift guard for the SHELL_CSS copy of design/v2/reports/shell.css.
#
# SHELL_CSS is a 1200-line copy of a file that lives outside src/. A prose
# "keep these in sync" note in the docstring is not a gate: either side can be
# edited and nothing notices. This rebuilds SHELL_CSS from the design file by
# applying exactly the authorised deltas and asserts equality, so an edit to
# either side — or a fifth undeclared delta — turns this red.

_PORT_HEADER = f"""/* ===========================================================================
   PORTED FROM design/v2/reports/shell.css — that file stays the design
   authority for the report shell. Any product-side edit must be annotated
   back into it; see report_shell.py's module docstring for the deltas.
   port-marker: {SHELL_CSS_PORT_MARKER}
   (Do not remove or reword the marker: scripts/audit_i18n_usage.py scopes its
   Cat C exemption to the literal containing this exact token, and the design
   commentary below is CJK.)
   =========================================================================== */

"""

# (b) 產品端不再產雙封面，舊的防禦性隱藏刪掉。只刪這條規則本身——
#     `.print-only { display: none; }` 是 screen/print 配對規則的螢幕側，保留。
_DELTA_DROP_OLD_COVER = (
    "/* 螢幕限定的原始列印封面：新殼自己有封面，藏掉舊的 */\n"
    ".report-cover.print-only,\n"
    ".report-cover-block.screen-only { display: none; }\n"
    "\n",
    "",
)

_TOC_FOCUS = ".toc a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }\n"

# (c) 列印按鈕：screen-only，字級/accent 色比照 .toc a。
_DELTA_PRINT_BTN = (_TOC_FOCUS, _TOC_FOCUS + """
/* 列印按鈕：螢幕限定，字級與 accent 色比照 .toc a；列印時自己不上紙。 */
.print-btn {
  display: block;
  width: 100%;
  margin-bottom: var(--space-5);
  padding: var(--space-3) var(--space-4);
  font-family: var(--font-mono);
  font-size: var(--fs-body);
  letter-spacing: 0.06em;
  color: var(--accent-fg);
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: var(--radius-s);
  text-align: left;
  cursor: pointer;
}

.print-btn:hover { border-color: var(--accent); }
.print-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
""")

# A1: .score-num 沒有顏色宣告；成熟度分數的等級訊號從 T3 起靠 .score-hero 的
# data-tone 傳進來，缺這行分數會退回本文墨色，等級訊號整個消失。
_SCORE_NUM = """.score-num {
  font-family: var(--font-mono);
  font-size: 44px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.03em;
"""
_DELTA_SCORE_INK = (_SCORE_NUM + "}\n", _SCORE_NUM + "  color: var(--ink);\n}\n")

_TOC_HOVER_PRINT = "  .toc a:hover { color: var(--text-2); }\n"
_DELTA_PRINT_BTN_HIDDEN = (_TOC_HOVER_PRINT,
                           _TOC_HOVER_PRINT + "  .print-btn { display: none; }\n")

# F1: 自舊殼 report_css.py 的列印保命段移植過來。
_TABLE_HINT_HIDDEN = "  .table-hint { display: none; }\n"
_DELTA_RELEASE_JS_WIDTHS = (_TABLE_HINT_HIDDEN, _TABLE_HINT_HIDDEN + """
  /* 寬表列印保命（自舊殼 report_css.py 移植，勿刪）。
     TABLE_JS 的 measureColumnWidths() 在**螢幕**載入時量測後，把結果寫成
     inline style：table.style.width / table.style.minWidth、每個 th 的
     style.width、以及 col 的 style.width。inline style 不分 media，會原封
     不動帶進列印，把表格撐成螢幕自動寬度，再被 .report-table-panel 整段裁掉。
       · 2026-07-23 視覺實檢：發現與行動表近半內容消失（舊殼因此有這一段）；
       · 2026-08-30 於新殼重現：11 欄寬表在 A4 橫式量到 table 2479px / panel
         1014px，直式 2479px / 674px。
     只有 !important 蓋得過 inline style，所以這裡用 !important 把 JS 寫進去的
     寬度全部釋放掉。代價是下面那些欄寬下限也必須是 !important，否則它們會輸
     給這裡的釋放，表格就從「整張被切掉」變成「擠回去再逐字切」——換一種無聲
     截斷而已。版面政策（直式 auto、橫式 fixed）仍由 --wide / --landscape 決定，
     這裡不碰 table-layout。 */
  .report-table { width: 100% !important; min-width: 0 !important; }
  .report-table col { width: auto !important; min-width: 0 !important; }
  .report-table thead th { width: auto !important; min-width: 0 !important; }
  .report-table-panel { overflow: visible; }
""")

# F1 的另一半：釋放規則之後，這四組欄寬下限必須贏回來（見上面的註解）。
_DELTA_FLOOR_LONG = (
    "  .report-table-panel--wide .report-table td.col-long,\n"
    "  .report-table-panel--wide .report-table th.col-long { min-width: 14em; }\n",
    "  .report-table-panel--wide .report-table td.col-long,\n"
    "  .report-table-panel--wide .report-table th.col-long { min-width: 14em !important; }\n",
)
_DELTA_FLOOR_LANDSCAPE_LONG = (
    "  .report-table-panel--landscape .report-table td.col-long,\n"
    "  .report-table-panel--landscape .report-table th.col-long { width: 30%; }\n",
    "  .report-table-panel--landscape .report-table td.col-long,\n"
    "  .report-table-panel--landscape .report-table th.col-long { width: 30% !important; }\n",
)
_DELTA_FLOOR_META = (
    "    min-width: 5.5em;\n    max-width: 12em;\n",
    "    min-width: 5.5em !important;\n    max-width: 12em !important;\n",
)
_DELTA_FLOOR_TS = (
    "  .report-table-panel--wide .report-table td.col-ts,\n"
    "  .report-table-panel--wide .report-table th.col-ts { min-width: 7.5em; }\n",
    "  .report-table-panel--wide .report-table td.col-ts,\n"
    "  .report-table-panel--wide .report-table th.col-ts { min-width: 7.5em !important; }\n",
)

AUTHORISED_DELTAS = (
    _DELTA_DROP_OLD_COVER,
    _DELTA_PRINT_BTN,
    _DELTA_SCORE_INK,
    _DELTA_PRINT_BTN_HIDDEN,
    _DELTA_RELEASE_JS_WIDTHS,
    _DELTA_FLOOR_LONG,
    _DELTA_FLOOR_LANDSCAPE_LONG,
    _DELTA_FLOOR_META,
    _DELTA_FLOOR_TS,
)


def build_expected_shell_css() -> str:
    """Rebuild SHELL_CSS from the design file + the authorised deltas."""
    css = DESIGN_SHELL_CSS.read_text(encoding="utf-8")
    for old, new in AUTHORISED_DELTAS:
        assert css.count(old) == 1, f"delta anchor not found exactly once: {old[:70]!r}"
        css = css.replace(old, new, 1)
    return _PORT_HEADER + css


def test_shell_css_matches_the_design_file_modulo_authorised_deltas():
    assert SHELL_CSS == build_expected_shell_css(), (
        "SHELL_CSS and design/v2/reports/shell.css have drifted apart, or a "
        "delta was added without declaring it in AUTHORISED_DELTAS."
    )


def test_shell_css_port_marker_is_present():
    # The Cat C exemption in scripts/audit_i18n_usage.py keys off this token.
    assert SHELL_CSS_PORT_MARKER in SHELL_CSS
