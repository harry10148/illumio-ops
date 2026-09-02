import re
from pathlib import Path

from bs4 import BeautifulSoup

from src.report.exporters.grade_colors import grade_tone
from src.report.exporters.report_shell import (
    APPENDIX_SECTION_ID, SHELL_CSS, SHELL_CSS_PORT_MARKER, ShellCover,
    ShellSection, build_shell_document, wide_table_attrs)

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN_SHELL_CSS = REPO_ROOT / "design" / "v2" / "reports" / "shell.css"


# ---------------------------------------------------------------------------
# C2: effective value, not "the declaration exists somewhere".
#
# Every guard below used to grep SHELL_CSS for a declaration. That is blind to
# the cascade: appending `@page { @bottom-right { content: none; } }` cancels
# the page number while leaving the original declaration in place, and the
# guard stays green. Today the drift guard happens to reject any SHELL_CSS
# edit, so the attack is caught -- but by the wrong test, and only until the
# override is itself added to the design file or registered as an authorised
# delta. The page-number guard exists because six report types shipped with no
# page numbers at all for two tasks and nobody noticed; defence in depth that
# does not defend is not defence.
#
# So these resolve the LAST declaration that applies, which is what the browser
# uses when specificity ties.
# ---------------------------------------------------------------------------

def _decomment(css: str) -> str:
    """Strip ``/* ... */`` before parsing.

    Not cosmetic: a comment sitting between ``}`` and the next selector is
    glued onto that selector by any regex-based rule splitter, so ``.cover``
    silently stops matching its own rule and the guard reports "no declaration"
    instead of the value.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str, opener: str):
    """Yield the body of every ``opener``-introduced block, brace-matched.

    ``re`` cannot do this: ``@page`` bodies nest ``@bottom-right`` blocks, so a
    non-greedy ``[^}]*`` stops at the inner closing brace.
    """
    i = 0
    while True:
        i = css.find(opener, i)
        if i < 0:
            return
        j = css.index("{", i + len(opener) - 1)
        depth, k = 1, j + 1
        while depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        yield css[j + 1:k - 1]
        i = k


def _effective_margin_box_content(css: str, page: str, box: str) -> str | None:
    """The content the LAST matching ``@page`` block gives ``box``."""
    value = None
    for body in _blocks(_decomment(css), page):
        for inner in _blocks(body, box):
            m = re.search(r"content:\s*([^;]+);", inner)
            if m:
                value = m.group(1).strip()
    return value


def _effective_declaration(css: str, selector: str, prop: str) -> str | None:
    """The last value ``prop`` is given by any rule whose selector list contains
    ``selector`` -- i.e. what wins when specificity ties."""
    value = None
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", _decomment(css)):
        if selector not in {s.strip() for s in m.group(1).split(",")}:
            continue
        d = re.search(rf"(?<![\w-]){re.escape(prop)}:\s*([^;]+);", m.group(2))
        if d:
            value = d.group(1).strip()
    return value


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
    cls9, hint9 = wide_table_attrs(9, "zh_TW")
    # 2026-09-02: nine columns moved above the threshold — the audit report's
    # nine-column table needs 729px against a 674px portrait panel.
    assert "report-table-panel--landscape" in cls9 and "9" in hint9
    assert wide_table_attrs(8, "zh_TW") == ("", "")


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
    # .score-num 吃 tone。錨在 .score-num 自己的規則上，不是整份 SHELL_CSS：
    # `color: var(--ink)` 在殼裡出現不只一次，只查子字串時把這一條從 .score-num
    # 拿掉照樣綠——分數會退回本文墨色、等級訊號整個消失（Task 6 以突變抓到）。
    score_num = SHELL_CSS.split("\n.score-num {")[1].split("}")[0]
    assert "color: var(--ink)" in score_num, score_num


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


def _cover_tone(*sections):
    out = build_shell_document(
        lang="en",
        cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=list(sections),
    )
    return BeautifulSoup(out, "html.parser").select_one("header.cover")["data-tone"]


def _chapter(id_, tone, kind="detail"):
    return ShellSection(id=id_, title=id_, html="", kind=kind, tone=tone)


def test_document_tone_is_critical_when_a_finding_chapter_is_critical():
    assert BeautifulSoup(_doc(), "html.parser").select_one("header.cover")["data-tone"] == "crit"
    # Critical wins outright over an earlier, milder finding chapter.
    assert _cover_tone(_chapter("a", "warn", "finding"),
                       _chapter("b", "crit", "finding")) == "crit"
    # No critical: the first FINDING chapter's tone carries.
    assert _cover_tone(_chapter("a", "warn", "finding"),
                       _chapter("b", "info", "finding")) == "warn"


def test_document_tone_ignores_chapters_that_are_not_findings():
    """G1: a detail chapter's tint must not speak for the whole document.

    A single critical row in an unmanaged-hosts or vulnerability table tints
    that chapter; it is not a finding, and it used to dye the cover of a report
    that found nothing.
    """
    assert _cover_tone(_chapter("a", "crit"), _chapter("b", "warn")) == "neutral"
    assert _cover_tone(_chapter("a", "crit"),
                       _chapter("b", "warn", "finding")) == "warn"
    # Exec sections have never counted, and still do not.
    assert _cover_tone(_chapter("e", "crit", "exec"), _chapter("a", "info")) == "neutral"


def test_document_tone_is_neutral_when_there_is_no_finding_chapter():
    """A report that never looks for findings has made no claim to colour."""
    assert _cover_tone(_chapter("a", "info"), _chapter("b", "ok")) == "neutral"
    assert _cover_tone() == "neutral"


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
     寬度釋放掉。釋放規則只要 table / col / thead th 三條就是全部覆蓋：
     report_css.py 裡 12 個 .style.width / .style.minWidth 寫入點全落在
     table、th、col，沒有一個碰 td，所以 td 上無事可放。
     下面四組欄寬下限跟著升成 !important，是為了整組對稱一致；實測只有
     --landscape 的 .col-long { width: 30% } 真的 load-bearing——拿掉 !important
     之後 9 欄直式的欄寬逐欄與出貨版相同、PDF 缺漏 0，11 欄橫式也只有 col-long
     的份額從 305px 掉到 93px、缺漏 0。
     這裡刻意不碰 table-layout。版面政策（直式 auto、橫式 fixed）是設計檔明文
     的裁決（.report-table-panel--landscape .report-table { table-layout: fixed }），
     一條為了相容 JS 而移植進來的規則不該把它靜默翻掉。 */
  .report-table { width: 100% !important; min-width: 0 !important; }
  .report-table col { width: auto !important; min-width: 0 !important; }
  .report-table thead th { width: auto !important; min-width: 0 !important; }
  .report-table-panel { overflow: visible; }
""")

# F1 的另一半：釋放規則之後，這四組欄寬下限一併升成 !important 保持對稱
# （只有 --landscape 的 col-long width 有實測必要性，見上面的註解）。
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

# T3/F1: 舊殼 report_css.py:529 有 `.report-shell .mat-fill.warn`
# (var(--gold-110))；design/v2/reports/shell.css 只移植了 .bad 與 .good。缺這條
# 時 40-70% 的中段長條吃 .mat-fill 的預設 var(--tone-info-border)，語意色從
# 三級塌成兩級。設計檔也漏只代表設計檔有洞——判斷退化的基準是產品舊殼的輸出。
_MAT_FILL_GOOD = ".mat-fill.good, .progress-fill.good { background: var(--tone-ok-border); }\n"
_DELTA_MAT_FILL_WARN = (_MAT_FILL_GOOD, _MAT_FILL_GOOD + """/* 舊殼 report_css.py:529 有 .mat-fill.warn（var(--gold-110)），設計檔漏了這一條。
   缺它會讓 40-70% 的中段長條退回 .mat-fill 的預設 info 藍，語意色從三級塌成兩級
   ——這是移植回歸，不是新設計，所以補回來並登記成授權 delta。 */
.mat-fill.warn, .progress-fill.warn { background: var(--tone-warn-border); }
""")

# T4: 舊殼 report_css.py 有空資料面板（205-207）與排序指示器（161-163,178）兩組
# 規則，design/v2/reports/shell.css 兩組都沒有。它們樣式化的是
# table_renderer.py / TABLE_JS 產出的元素，10 型報表共用——缺了之後「查無資料」
# 的面板與正常表格長得一樣，TABLE_JS 建立的 .sort-indicator 也失去定位。
# 同 F1 的判準：設計檔也漏只代表設計檔有洞，基準是產品舊殼的輸出。
_PANEL_COMPACT = ".report-table-panel--compact { max-width: 640px; }\n"
_DELTA_TABLE_JS_AFFORDANCES = (_PANEL_COMPACT, _PANEL_COMPACT + """\
/* 自舊殼 report_css.py 移植的兩組「表格 JS 附屬樣式」，設計檔沒有涵蓋（T4）。
   兩者都是 table_renderer.py / TABLE_JS 產出的元素，10 型報表共用：
     · 空資料面板（report_css.py:205-207）——缺這一段，「無資料」與「有資料」
       兩種面板長得一模一樣，讀者分不出是查無資料還是渲染壞掉；
     · 排序指示器（report_css.py:161-163,178）——TABLE_JS 仍會建立
       .sort-indicator 元素，沒有規則時它會變成擠在欄名後面的裸文字，
       游標也不再提示欄頭可點。
   顏色改吃殼的 token；已排序欄的強調色用 --accent 而非舊殼的 --gold：
   那是互動狀態，殼的語意色（tone-*）保留給嚴重度。 */
.report-table-panel--empty {
  padding: var(--space-8) var(--space-7);
  border-style: dashed;
  background: var(--surface-2);
  text-align: center;
  color: var(--text-3);
  font-size: var(--fs-body);
}
.report-table-panel--empty .empty-marker {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--line);
  margin-right: var(--space-4);
  vertical-align: middle;
}
.report-table-panel--empty .empty-text { font-style: italic; letter-spacing: 0.02em; }
/* 舊殼 th 是 padding: 10px 28px 10px 12px，那 28px 右內距在 report_css.py:157-159
   有註解寫明是「為絕對定位的 .sort-indicator 保留的空間」。移植被定位的元素就必須
   一起移植它的保留區：新殼 th 只有 8px 右內距而箭頭在 12px，實測 audit 的 count 欄
   欄名與箭頭重疊 +14.5px（舊殼同欄是 −12.6px 有餘裕）。只加在可排序的表格上，
   不可排序的表格沒有箭頭、不該平白損失 16px 欄寬。 */
.report-table--interactive thead th { cursor: pointer; user-select: none; padding-right: var(--space-7); }
.sort-indicator {
  position: absolute;
  right: var(--space-5);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--fs-mini);
  opacity: 0.55;
  pointer-events: none;
}
.report-table thead th:hover .sort-indicator { opacity: 0.85; }
.report-table thead th.is-sorted-asc .sort-indicator,
.report-table thead th.is-sorted-desc .sort-indicator { opacity: 1; color: var(--accent); }
""")


def test_empty_table_panel_and_sort_indicator_survive_the_port():
    """T4: 與 F1 同型——drift guard 單獨守不住「規則連同 delta 一起被刪」。

    這裡直接斷言渲染用的 SHELL_CSS 真的有這兩組規則，而不是只斷言它與設計檔
    的差異等於清單。
    """
    screen_block = SHELL_CSS.split("@media print")[0]
    assert ".report-table-panel--empty {" in screen_block
    assert ".report-table-panel--empty .empty-marker {" in screen_block
    assert ".report-table-panel--empty .empty-text {" in screen_block
    assert (".report-table--interactive thead th { cursor: pointer; user-select: none; padding-right: var(--space-7); }") in screen_block
    # Anchored on the SCREEN block and on the rule's own body. Asserting
    # ``".sort-indicator {" in SHELL_CSS`` was blind: the print block's
    # ``.sort-indicator { display: none; }`` satisfied it, so renaming the
    # screen rule away left the guard green while the arrow lost its
    # positioning entirely (found by mutation, Task 6).
    indicator = screen_block.split(".sort-indicator {")[1].split("}")[0]
    assert "position: absolute" in indicator
    assert "right: var(--space-5)" in indicator
    assert "translateY(-50%)" in indicator


# T4/F2: 列印區塊裡 th 是 position: static，絕對定位的 .sort-indicator 會失去定位祖先
# 而飄到章右緣（實測 audit PDF 20 個游離箭頭）。紙本不能排序，列印時直接不印，並把
# 螢幕上為它保留的右內距還回去。與 _DELTA_TABLE_JS_AFFORDANCES 是同一個移植的兩半。
_PRINT_TH_STATIC = "  .report-table thead th { position: static; }\n"
_DELTA_SORT_INDICATOR_PRINT = (_PRINT_TH_STATIC, _PRINT_TH_STATIC + """\
  /* 列印時 th 變成 position: static，絕對定位的 .sort-indicator 因此失去定位祖先、
     改對 section.chapter 定位，整排箭頭飄到表格之後的章右緣（實測 audit PDF 出現 20 個
     游離「↕」，pdftotext -bbox 只解析出 3 個可分辨的 word、全部疊在 x=543.5）。
     紙本不能排序，這個提示在列印時沒有意義——直接不印，順便把它的保留區還給欄寬。 */
  .sort-indicator { display: none; }
  .report-table--interactive thead th { padding-right: var(--space-4); }
""")


def test_the_sort_indicator_is_not_printed():
    """F2: 沒有這一條，箭頭在 PDF 裡會脫離欄頭，六型（T5 後十型）全中。

    drift guard 守不住它——把規則連同 delta 一起刪掉它照樣綠——所以直接斷言
    列印區塊裡有這條規則，且它排在 th 變成 static 之後。
    """
    print_block = SHELL_CSS.split("@media print")[1]
    assert ".sort-indicator { display: none; }" in print_block
    assert (print_block.index(".report-table thead th { position: static; }")
            < print_block.index(".sort-indicator { display: none; }"))


# T5: 舊殼 report_css.py:288-295 在 @page 的 @bottom-right margin box 印
# 「頁碼 / 總頁數」，design/v2/reports/shell.css 沒有這一段。前六型遷移時一起
# 掉了、沒有人發現（實測 620f7a52：未遷移的 policy_diff/readiness 每頁都有頁碼，
# 已遷移的 traffic/audit/policy_usage 一頁都沒有）。一份 8-10 頁的報表 PDF 沒有
# 頁碼就無法標頁、無法引用、散頁後無法還原順序——與 .mat-fill.warn 同一個判準：
# 設計檔也漏只代表設計檔有洞，基準是產品舊殼的輸出。
# 只宣告在預設 @page：具名頁 @page wide 會繼承它。這是量出來的，不是假設的——
# 把 wide 那一份拿掉之後重新渲染 rule_hit_count（直橫混排 8 頁），8 頁仍然全部
# 有頁碼，所以第二份是多餘的。
# 字級/顏色/字族沿用舊殼的字面值是為了照抄已出貨的樣子，不是技術限制：實測
# margin box 解析得了 :root 的自訂屬性（var() 版與同色字面值版的 PDF footer
# 像素完全相同）。
_DELTA_PAGE_NUMBER = (
    "@page {\n  size: A4 portrait;\n  margin: 15mm 13mm 14mm;\n}\n",
    "@page {\n  size: A4 portrait;\n  margin: 15mm 13mm 14mm;\n"
    "  /* 頁碼頁尾自舊殼 report_css.py:288-295 移植（T5）。設計檔沒有這一段，但舊殼\n"
    "     十型全部都印，Chromium 支援 @page 的 margin box，實測舊 policy_diff PDF 每頁\n"
    "     右下角都有「1 / 7」。少了它，一份 8-10 頁的 PDF 印出來無法標頁、無法引用、\n"
    "     散頁之後無法還原順序——這是移植回歸，不是新設計。\n"
    "     只宣告在預設 @page：實測具名頁 @page wide 會繼承它（把這一段從 wide 拿掉，\n"
    "     rule_hit_count 直橫混排的 8 頁仍然 8 頁都有頁碼），所以不需要第二份。\n"
    "     字級/顏色/字族沿用舊殼的字面值是為了照抄已出貨的樣子，不是技術限制——\n"
    "     實測 margin box 解析得了 :root 的自訂屬性（var() 版與同色字面值版的 PDF\n"
    "     footer 像素完全相同）。 */\n"
    "  @bottom-right {\n"
    '    content: counter(page) " / " counter(pages);\n'
    "    font-family: sans-serif;\n"
    "    font-size: 8pt;\n"
    "    color: #888;\n"
    "  }\n"
    "}\n",
)


def test_every_printed_page_is_numbered():
    """T5: drift guard 守不住它——規則連同 delta 一起被刪掉它照樣綠。

    C2 之後改為解析**最終生效值**：把所有預設 ``@page`` 區塊依序走過，取最後一次
    對 ``@bottom-right`` 的 ``content`` 宣告。這樣「保留原宣告、在後面追加一條
    ``content: none`` 取消掉」也會紅——那正是 drift guard 一旦放行（覆寫被寫進
    設計檔或登記成授權 delta）就再也沒人擋得住的攻擊面。

    只查預設頁是因為量過了：具名頁 ``@page wide`` 會繼承它（拿掉 wide 自己那一份，
    rule_hit_count 直橫混排的 8 頁仍然 8 頁都有頁碼），所以第二份是多餘的、不該
    被這條守門要求。
    """
    expected = 'counter(page) " / " counter(pages)'
    effective = _effective_margin_box_content(SHELL_CSS, "@page {", "@bottom-right")
    assert effective == expected, (
        f"@page 的 @bottom-right 最終生效內容是 {effective!r}，不是頁碼。"
        f"（宣告可能還在，但被後面的規則覆寫掉了）")
    # 具名頁不得把它取消掉——繼承來的頁碼被 wide 頁覆寫成 none 一樣是全書缺頁碼。
    named = _effective_margin_box_content(SHELL_CSS, "@page wide {", "@bottom-right")
    assert named in (None, expected), (
        f"@page wide 覆寫了頁碼 margin box：{named!r}")


def test_the_cover_exec_and_toc_still_each_own_a_page():
    """C2, same shape: ``break-after: page`` must be the value that WINS.

    A later ``.cover { break-after: auto; }`` in the print block collapses the
    cover onto the first chapter's page while the original declaration sits
    there satisfying a substring check.
    """
    print_block = SHELL_CSS.split("@media print")[1]
    for selector in (".cover", ".exec", ".toc"):
        value = _effective_declaration(print_block, selector, "break-after")
        assert value == "page", (
            f"{selector} 的 break-after 最終生效值是 {value!r}，不是 page")

_COVER_META_DT = ".cover-meta dt {\n"
# 設計檔的 .cover-meta 是 grid，而 dt 與 dd 是兩個獨立的 grid item——三欄時會把
# 「資料範圍 / 值 / 產生時間」排成第一列，把產生時間的值單獨丟到第二列、正好落在
# 資料範圍的標籤底下，讀者無從判斷哪個值屬於哪個標籤。守恆檢查看不到它（字都還在，
# 只有位置變了），是讀真實 17 頁 PDF 才發現的。_render_cover 改成每組包一層
# .cover-meta-pair，這條規則讓那層成為唯一的 grid item，任何欄數都拆不開一組配對。
# 下面的字串必須與 SHELL_CSS 逐字相同，drift guard 才對得上。
_DELTA_COVER_META_PAIR = (_COVER_META_DT, """/* One grid cell per label+value pair. Without this the dt and dd are separate
   grid items and a pair can be split across a row boundary, leaving a value
   sitting under someone else's label. */
.cover-meta-pair {
  min-width: 0;
}

""" + _COVER_META_DT)

# 2026-09-02 Task 7 驗收：audit 的 users 表 9 欄各自伸到逐欄 max-width 12em，
# 總寬 729px 超過 674px 的直式面板，右緣兩欄被紙張裁掉。逐欄上限管不到總和，
# 所以直式（非橫式）的 meta 欄再加一道 8em 上限——面板 674px ÷ 最多 9 欄
# （10 欄起走橫式）≈ 8.6em。設計檔沒有這一條，登記成授權 delta。
_DELTA_PORTRAIT_TOTAL_WIDTH = (
    _DELTA_FLOOR_TS[1],
    _DELTA_FLOOR_TS[1] + """  /* 直式的總寬上限。上面的 max-width: 12em 是逐欄的，欄與欄之間沒有人管總和：
     2026-09-02 實測 audit 的 users 表 9 欄各自伸到上限，總寬 729px > 面板 674px，
     右緣兩欄被紙張裁掉。面板 674px ÷ 最多 9 欄（10 欄起走橫式）≈ 8.6em，取 8em
     讓「每欄都頂上限」的最壞情況仍放得下。橫式頁是 table-layout: fixed ＋
     width: 100%，總寬本來就受面板約束，不套這條。 */
  .report-table-panel--wide:not(.report-table-panel--landscape) .report-table tbody td:not(.num):not(.col-long),
  .report-table-panel--wide:not(.report-table-panel--landscape) .report-table thead th:not(.num):not(.col-long) {
    max-width: 8em !important;
  }
""",
)

AUTHORISED_DELTAS = (
    _DELTA_COVER_META_PAIR,
    _DELTA_DROP_OLD_COVER,
    _DELTA_PAGE_NUMBER,
    _DELTA_SORT_INDICATOR_PRINT,
    _DELTA_PRINT_BTN,
    _DELTA_SCORE_INK,
    _DELTA_PRINT_BTN_HIDDEN,
    _DELTA_RELEASE_JS_WIDTHS,
    _DELTA_FLOOR_LONG,
    _DELTA_FLOOR_LANDSCAPE_LONG,
    _DELTA_FLOOR_META,
    _DELTA_FLOOR_TS,
    _DELTA_PORTRAIT_TOTAL_WIDTH,
    _DELTA_MAT_FILL_WARN,
    _DELTA_TABLE_JS_AFFORDANCES,
)


def test_mat_fill_warn_survives_the_port_from_the_old_shell():
    """T3/F1: 三級語意色不得塌成兩級。

    這條不是靠 drift guard 守的——drift guard 只保證「SHELL_CSS == 設計檔 +
    授權清單」，如果有人把 delta 連同規則一起刪掉，它照樣是綠的。這裡直接斷言
    渲染出來的 CSS 有這條規則，且三個等級各自吃不同的 token。
    """
    assert ".mat-fill.warn, .progress-fill.warn { background: var(--tone-warn-border); }" in SHELL_CSS
    assert ".mat-fill.bad, .progress-fill.bad { background: var(--tone-crit-border); }" in SHELL_CSS
    assert ".mat-fill.good, .progress-fill.good { background: var(--tone-ok-border); }" in SHELL_CSS


def test_portrait_wide_tables_cap_the_total_column_width():
    """Task 7 驗收回歸：逐欄 max-width 管不住總寬。

    drift guard 只保證「SHELL_CSS == 設計檔 + 授權清單」，把規則連同 delta
    一起刪掉它照樣是綠的。這裡直接斷言規則還在，且只套在直式——橫式是
    table-layout: fixed，總寬本來就受面板約束，套上去只會白白壓窄欄位。
    """
    assert (
        ".report-table-panel--wide:not(.report-table-panel--landscape) "
        ".report-table thead th:not(.num):not(.col-long)"
    ) in SHELL_CSS
    assert "max-width: 8em !important;" in SHELL_CSS


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


# ---------------------------------------------------------------------------
# Task 6: the old shell is deleted. These two keep it deleted.
# ---------------------------------------------------------------------------

#: Identifiers, not prose. Several src comments still name ``report_css.py`` on
#: purpose — they record where a ported rule came from, and that history is the
#: only place the old baseline still exists. What must never come back is a
#: *call* or a *class name*, so every needle here is one of those.
#: Quote-agnostic: the exporters mix ``'...'`` and ``"..."`` f-strings freely,
#: so anchoring on one quote character lets ``class='report-shell'`` through
#: (C1). ``[\"']`` covers both; the class name itself is what is banned.
LEGACY_SHELL_NEEDLES = (
    r'class=[\"\']report-shell',   # old shell container
    r'class=[\"\']report-toc',     # old sidebar nav
    r'class=[\"\']report-cover',   # old dual cover (both halves)
    r"report-cover-block",
    r"build_css\(",                # old stylesheet builder
    r"build_cover_page\(",         # old cover builder
    r"grade_color\(",              # inline grade hex; the shell uses data-tone
    r"import report_css",
    r"report_css import",
    r"import cover_page",
    r"cover_page import",
)


def _git_grep(pattern: str, *paths: str) -> str:
    import subprocess
    return subprocess.run(
        ["git", "grep", "-l", "-E", pattern, "--", *paths],
        cwd=REPO_ROOT, capture_output=True, text=True).stdout


def test_the_legacy_shell_leaves_no_residue_in_src():
    """No file under ``src/`` may call into, or emit the markup of, the shell
    ``report_css.py`` / ``cover_page.py`` used to provide.

    The control assertion below is not ceremony: this repo has shipped a gate
    that reported zero findings because it was scanning nothing at all, and an
    absence check run through a subprocess is exactly that shape of risk.
    """
    control = _git_grep(r"SHELL_CSS", "src/")
    assert control.strip(), (
        "git grep found no SHELL_CSS under src/ — the search itself is broken, "
        "so the absence result below would mean nothing")

    hits = _git_grep("|".join(LEGACY_SHELL_NEEDLES), "src/")
    assert hits.strip() == "", f"legacy shell residue in src/: {hits}"


def test_the_deleted_modules_are_really_gone():
    """A residue grep is satisfied by an unreferenced file sitting on disk."""
    exporters = REPO_ROOT / "src" / "report" / "exporters"
    assert not (exporters / "report_css.py").exists()
    assert not (exporters / "cover_page.py").exists()
    # ...and TABLE_JS came with them rather than being dropped: all ten types
    # render tables that sort, auto-fit and scroll through it.
    from src.report.exporters.report_shell import TABLE_JS
    assert "function sortTable(" in TABLE_JS
    assert "function autoFitColumns(" in TABLE_JS
    # C1: the function bodies being present is not the same as them running.
    # Without the boot chain every table ships inert -- no sorting, no
    # auto-fit, no wide-scroll state -- and a guard that only greps for the
    # definitions stays green through it.
    boot = TABLE_JS.split("DOMContentLoaded")
    assert len(boot) == 2, "TABLE_JS has no DOMContentLoaded boot hook"
    assert "initReportTable" in boot[1], (
        "the DOMContentLoaded handler never calls initReportTable — every "
        "table would render inert")
    assert ".report-table" in boot[1], (
        "the boot handler selects nothing to initialise")
    assert "function initReportTable(" in TABLE_JS
    assert TABLE_JS in build_shell_document(
        lang="en", cover=ShellCover(title="t", doc_title="d", type_label="x"),
        sections=[ShellSection(id="s", title="s", html="")])
