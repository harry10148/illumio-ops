"""報表新殼（design/v2）守門測試。

不變量（對應 CLAUDE.md「報表 / PDF 產出」硬規則與 spec §4）：
  1. 切章不吃內容——原始報表的每一個 <table> 都要落在某一章裡
  2. 新殼的順序與骨架符合 spec §4.1（封面→執行摘要→目錄→發現→明細→附錄）
  3. 沒有無聲截斷——凡是省略號欄位都必須附 title 全文，且列印時展開全文
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "design" / "v2" / "tools"))

import pytest  # noqa: E402

from reskin_report import (  # noqa: E402
    SEVERITY_TONE,
    _mark_chips,
    build_shell,
    chapter_order,
    conservation_diff,
    extract_cover,
    extract_sections,
    tone_of,
)

ORIGINAL = ROOT / "design" / "v2" / "reports" / "original"
AUDIT = (ORIGINAL / "audit.html").read_text(encoding="utf-8")
TRAFFIC = (ORIGINAL / "traffic.html").read_text(encoding="utf-8")
SHELL_CSS_TEXT = (ROOT / "design" / "v2" / "reports" / "shell.css").read_text(encoding="utf-8")


def _tables(html):
    return len(re.findall(r"<table\b", html))


# ---------------------------------------------------------------- 切章不吃內容 --
def test_extract_keeps_all_tables_and_headings():
    secs = extract_sections(AUDIT)
    assert sum(s["html"].count("<table") for s in secs) == _tables(AUDIT)
    assert all(s["title"] for s in secs)


def test_extract_keeps_all_tables_traffic():
    secs = extract_sections(TRAFFIC)
    assert sum(s["html"].count("<table") for s in secs) == _tables(TRAFFIC)
    assert all(s["title"] for s in secs)
    assert all(s["id"] for s in secs)


def test_extract_keeps_all_charts():
    for html in (AUDIT, TRAFFIC):
        secs = extract_sections(html)
        assert sum(s["html"].count("<svg") for s in secs) == html.count("<svg")


def test_section_ids_are_unique_and_cover_the_original_anchors():
    for html in (AUDIT, TRAFFIC):
        secs = extract_sections(html)
        ids = [s["id"] for s in secs]
        assert len(ids) == len(set(ids))
        # 原始螢幕目錄的每個錨點都必須還在
        for anchor in re.findall(r'<a href="#([\w-]+)">', html):
            assert anchor in ids, anchor


def test_sections_are_classified_into_shell_kinds():
    kinds = {s["kind"] for s in extract_sections(TRAFFIC)}
    assert {"exec", "finding", "detail"} <= kinds
    # 發現章節必須真的含發現卡
    for s in extract_sections(TRAFFIC):
        if s["kind"] == "finding":
            assert "finding-card" in s["html"] or "concern-card" in s["html"]


def test_extract_sections_refuses_to_silently_drop_unrecognized_children():
    """main.report-main 底下如果出現一個既沒有 id、也不是 exec-summary 的直接
    子元素，代表 selector 轉錄跟 exporter 的實際結構對不上了。這種情況以前是
    靜默 continue（I4）——整章內容無聲消失，且不會被任何守門測試抓到；比照
    main.report-main 本身找不到時的失敗方式，改成大聲 raise。"""
    mutated = TRAFFIC.replace(
        '<section id="drift" class="card">',
        '<section class="card mystery-section-without-id">', 1)
    assert "mystery-section-without-id" in mutated  # 確認真的替換到了
    with pytest.raises(ValueError, match="不認得的章節結構"):
        extract_sections(mutated)


def test_mark_chips_show_every_severity_present_not_just_the_first_three():
    """I3：_mark_chips 曾經 `chips[:3]` 靜默砍到 3 顆，traffic「發現與行動」
    章（5 種 severity）少了 INFO/LOW、ransomware 章（4 種）少了 LOW。
    .chapter-marks 本來就是 flex-wrap: wrap，全顯示不會破版，沒有理由裁切。"""
    marks = {"CRITICAL": 2, "HIGH": 16, "MEDIUM": 14, "LOW": 1, "INFO": 4}
    chips = _mark_chips(marks)
    for sev in marks:
        assert f">{sev} {marks[sev]}<" in chips, sev

    findings = next(s for s in extract_sections(TRAFFIC) if s["id"] == "findings")
    assert set(findings["marks"]) == {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
    chips = _mark_chips(findings["marks"])
    for sev in findings["marks"]:
        assert f"{sev} {findings['marks'][sev]}" in chips, sev


def test_tone_mapping_is_the_five_tone_system():
    assert set(SEVERITY_TONE.values()) <= {"ok", "warn", "crit", "info", "neutral"}
    assert tone_of('<span class="badge badge-CRITICAL">x</span>') == "crit"
    assert tone_of('<span class="risk-badge">x</span><i class="risk-MEDIUM">') == "warn"
    assert tone_of("<p>nothing</p>") == "neutral"


# -------------------------------------------------------------------- 新殼骨架 --
def test_shell_has_toc_print_css_and_no_silent_truncation():
    """原本最後一行是 `"text-overflow" not in out or "title=" in out`——這份
    殼從不使用 `text-overflow`（用 <details>/<summary> 收合取代 ellipsis），
    所以左半邊恆真，整條 assert 不管右半邊對不對都會通過（2026-08-04 review
    抓到的套套邏輯）。改成真不變量：這份殼唯一用「收合摘要」代表省略的
    selector 是 `.cell-long > summary`（見 shell.css §12c），凡是它產出的
    節點都必須帶全文 title，且列印時真的把摘要藏起來、換全文顯示。"""
    css = SHELL_CSS_TEXT
    out = build_shell("Audit Report", extract_sections(AUDIT))
    assert 'class="toc"' in out and "@media print" in out

    summaries = re.findall(r"<summary[^>]*>", out)
    assert summaries and all("title=" in s for s in summaries)

    print_block = css[css.index("@media print"):]
    collapse = re.search(r"\.cell-long\s*>\s*summary\s*\{([^}]*)\}", print_block)
    assert collapse and "display: none" in collapse.group(1)


def test_shell_section_order_follows_spec_4_1():
    out = build_shell("Audit Report", extract_sections(AUDIT), cover=extract_cover(AUDIT))
    order = [m.group(1) for m in re.finditer(r'data-shell="(\w+)"', out)]
    assert order[:3] == ["cover", "exec", "toc"]
    assert order.index("appendix") == len(order) - 1
    finding = [i for i, k in enumerate(order) if k == "finding"]
    detail = [i for i, k in enumerate(order) if k == "detail"]
    assert finding and detail and max(finding) < min(detail)


def test_shell_carries_every_table_and_chart_of_the_original():
    for html in (AUDIT, TRAFFIC):
        out = build_shell("t", extract_sections(html), cover=extract_cover(html))
        assert _tables(out) == _tables(html)
        assert out.count("<svg") == html.count("<svg")


def test_shell_toc_lists_every_chapter_with_anchor():
    secs = extract_sections(TRAFFIC)
    out = build_shell("t", secs, cover=extract_cover(TRAFFIC))
    toc = re.search(r'<nav class="toc".*?</nav>', out, re.S).group(0)
    for s in secs:
        if s["kind"] != "appendix":
            assert f'href="#{s["id"]}"' in toc, s["id"]


def test_chapter_index_matches_chapter_order():
    """章號 SNN 是列印目錄頁碼的量測錨點：build_shell 排出來的順序若與
    chapter_order() 不一致，頁碼會整組錯位（而且看起來像是有頁碼的）。"""
    for html in (AUDIT, TRAFFIC):
        secs = extract_sections(html)
        out = build_shell("t", secs)
        pairs = re.findall(
            r'<section class="chapter" id="([\w-]+)"[^>]*>.*?chapter-index">S(\d+)<', out)
        assert [i for i, _ in pairs] == [s["id"] for s in chapter_order(secs)]
        assert [int(n) for _, n in pairs] == list(range(1, len(pairs) + 1))


def test_shell_print_toc_can_carry_page_numbers():
    secs = extract_sections(AUDIT)
    out = build_shell("t", secs, page_numbers={secs[1]["id"]: 3})
    assert re.search(r'class="toc-page"[^>]*>3<', out)


def test_cover_extracts_real_metadata_not_placeholders():
    cover = extract_cover(AUDIT)
    assert cover["title"] and cover["kicker"]
    assert any("2026-07" in v for v in cover["meta"].values())


def test_cover_title_is_the_full_hero_heading_not_the_short_cover_type():
    """C1（2026-08-04）：extract_sections 把整個 .report-hero-top decompose()
    掉搬進封面，但 extract_cover 舊版只撈 .report-kicker/.report-subtitle，
    沒撈裡面的 <h1>——兩份報表真正的標題（「Illumio 資安與風險報表」「Illumio
    稽核與系統事件報表」）因此兩份輸出都不在了，新殼的 <h1> 退化成短版型別
    標籤（.cover-title/.cover-type 都只寫「安全風險分析」/「稽核報告」）。"""
    traffic_cover = extract_cover(TRAFFIC)
    assert traffic_cover["title"] == "Illumio 資安與風險報表"
    audit_cover = extract_cover(AUDIT)
    assert audit_cover["title"] == "Illumio 稽核與系統事件報表"


def test_cover_doc_title_preserves_the_original_title_tag_verbatim():
    """C1：輸出的 <title> 標籤退化過（Illumio 流量報告→安全風險分析；
    Illumio 稽核報告→稽核報告），因為它是拿封面欄位重新推導出來的。
    doc_title 必須逐字等於原始 <title>，不是任何封面欄位的替代品。"""
    assert extract_cover(TRAFFIC)["doc_title"] == "Illumio 流量報告"
    assert extract_cover(AUDIT)["doc_title"] == "Illumio 稽核報告"

    for name, html in (("traffic", TRAFFIC), ("audit", AUDIT)):
        out = build_shell(extract_cover(html)["doc_title"], extract_sections(html),
                           cover=extract_cover(html))
        m = re.search(r"<title>([^<]*)</title>", out)
        assert m and m.group(1) == extract_cover(html)["doc_title"], name


# ------------------------------------------------------------ 截斷政策的守門 --
def test_long_cells_get_title_with_full_text():
    out = build_shell("t", extract_sections(AUDIT))
    for summary in re.findall(r"<summary[^>]*>", out):
        assert "title=" in summary, summary


def _print_rule(print_block, selector_pattern):
    """抓出 print_block 裡某個 selector 自己的宣告區塊，回傳裡面的內容。
    比對『selector 有沒有帶某個宣告』一定要綁在同一條規則上，不能只驗
    「selector 字串」跟「宣告字串」各自存在於 print_block 的某處——那樣就算
    兩者屬於完全不相干的規則，assert 照樣會過（2026-08-04 review 抓到）。"""
    m = re.search(re.escape(selector_pattern).replace(r"\ ", r"\s*") + r"\s*\{([^}]*)\}",
                  print_block)
    assert m, f"print block 找不到規則：{selector_pattern}"
    return m.group(1)


def test_print_css_expands_truncated_cells_and_wraps_cells():
    css = SHELL_CSS_TEXT
    print_block = css[css.index("@media print"):]
    # 列印時摘要收起、全文展開（不可只留省略號）——分別驗證同一條規則裡
    # 「selector 對應到正確的宣告」，不是子字串各自存在於 print_block 裡就算數
    assert "display: none" in _print_rule(print_block, ".cell-long > summary")
    assert "pre-wrap" in _print_rule(print_block, ".cell-long > .cell-long-full")
    # 收合的 <details> 只設子元素 display:block 沒有用，全文不會進 PDF
    assert "content-visibility: visible" in _print_rule(print_block, ".cell-long::details-content")
    # 表格儲存格一律換行，不做無聲裁切
    assert "overflow-wrap: anywhere" in print_block
    assert "overflow-wrap: break-word" in css
    assert "text-overflow: clip" not in css


def test_wide_tables_declare_scroll_and_landscape_behaviour():
    css = (ROOT / "design" / "v2" / "reports" / "shell.css").read_text(encoding="utf-8")
    assert "@page wide" in css and "page: wide" in css
    out = build_shell("t", extract_sections(AUDIT))
    hints = re.findall(r'<p class="table-hint">([^<]+)</p>', out)
    assert hints and all("欄寬表" in h for h in hints)
    assert len(hints) == out[out.index("<body"):].count("report-table-panel--wide")


def test_meta_columns_are_not_crushed_by_the_long_text_column():
    """2026-08-05 使用者截圖實證：寬表列印時每一格都吃 overflow-wrap: anywhere，
    每欄的 min-content 因此降到一個字元，auto 佈局把版面全讓給 max-content 最大
    的長文欄（change_detail），meta 欄被壓成逐字直排（「SEVERITY」→「SE VE RI
    TY」）。不變量：anywhere 只留給長文欄，其餘欄有可讀下限，長文欄有份額。"""
    css = SHELL_CSS_TEXT
    print_block = css[css.index("@media print"):]
    wide_cells = _print_rule(
        print_block,
        ".report-table-panel--wide .report-table tbody td,"
        " .report-table-panel--wide .report-table thead th,"
        " .report-table-panel--wide .th-label")
    assert "break-word" in wide_cells and "anywhere" not in wide_cells
    long_wrap = _print_rule(
        print_block,
        ".report-table-panel--wide .report-table td.col-long,"
        " .report-table-panel--wide .report-table td.col-long .cell-long-full,"
        " .report-table-panel--wide .report-table th.col-long .th-label")
    assert "anywhere" in long_wrap
    meta_floor = _print_rule(
        print_block,
        ".report-table-panel--wide .report-table tbody td:not(.num):not(.col-long),"
        " .report-table-panel--wide .report-table thead th:not(.num):not(.col-long)")
    assert "min-width" in meta_floor and "max-width" in meta_floor
    long_share = _print_rule(
        print_block,
        ".report-table-panel--wide .report-table td.col-long,"
        " .report-table-panel--wide .report-table th.col-long")
    assert "min-width" in long_share


# 稽核報表有 ISO 時間戳欄，流量報表沒有——後者只驗「有長文欄就要標 .col-long」
# 與「凡是標了 .col-ts 的儲存格都插了 <wbr/>」，不要求它一定要有時間戳欄。
@pytest.mark.parametrize("html,name,needs_ts", [(AUDIT, "audit", True),
                                                (TRAFFIC, "traffic", False)])
def test_column_kind_hooks_are_emitted_for_wide_tables(html, name, needs_ts):
    """CSS 的逐欄政策要有掛得上的 class。長文欄一定標 .col-long；時間戳欄標
    .col-ts 並在日期與時間之間插一個 <wbr/>（唯一折行機會，不逐字拆）。"""
    out = build_shell("t", extract_sections(html))
    body = out[out.index("<body"):]
    if "cell-long" in body:
        assert "col-long" in body, name
    for cell in re.findall(r'<t[dh][^>]*class="[^"]*col-ts[^"]*"[^>]*>(.*?)</t[dh]>', body):
        if "th-label" in cell:
            continue
        assert re.match(r"^\d{4}-\d{2}-\d{2}<wbr/>T", cell), (name, cell)
    if needs_ts:
        assert "col-ts" in body, name


def test_snake_case_headers_get_break_opportunities():
    """「workloads_affected」是 18 字元無折行機會的 token，break-word 下它就是
    整欄的 min-content（實測 121px），把長文欄擠到剩 20px。底線後補 <wbr/>。"""
    out = build_shell("t", extract_sections(AUDIT))
    labels = re.findall(r'<span class="th-label">([^<]*(?:<wbr/>[^<]*)*)</span>', out)
    snake = [l for l in labels if "_" in l]
    assert snake, "稽核報表的欄名本來就有 snake_case，抓不到代表 selector 走鐘"
    for label in snake:
        assert "_<wbr/>" in label, label


def test_shell_css_comments_never_terminate_early():
    """註解裡出現 `*/`（例如寫 `--tone-*/`）會提早關掉註解，讓後面的中文說明
    變成 CSS 垃圾，並吞掉緊接著的整條規則——2026-08-03 就是這樣把整個 :root
    token 區塊吃掉，全頁退回瀏覽器預設樣式。不變量：去掉註解後不得有中日韓字。"""
    css = (ROOT / "design" / "v2" / "reports" / "shell.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"[　-鿿＀-￯]", stripped)
    assert re.search(r":root\s*\{[^}]*--font-ui", stripped)


def test_every_color_in_shell_css_comes_from_the_token_block():
    css = (ROOT / "design" / "v2" / "reports" / "shell.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    tokens = stripped[: stripped.index("== 2.") if "== 2." in stripped else len(stripped)]
    used = {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{3,8}\b", stripped)}
    declared = {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{3,8}\b", tokens)}
    assert used <= declared, used - declared


def test_inline_legacy_colors_outside_charts_are_mapped_to_tokens():
    from bs4 import BeautifulSoup

    for html in (AUDIT, TRAFFIC):
        out = build_shell("t", extract_sections(html), cover=extract_cover(html))
        soup = BeautifulSoup(out, "html.parser")
        for svg in soup.find_all("svg"):
            svg.decompose()  # 圖表 SVG 原樣保留，不在改色範圍
        stale = {
            h.upper()
            for el in soup.select("body [style]")
            for h in re.findall(r"#[0-9A-Fa-f]{3,6}\b", el["style"])
        }
        assert not stale, stale


# ------------------------------------------------- C2：original→reskinned 保全 --
# verify_no_truncation（見上）只比對 reskinned↔PDF，從不比對 original→reskinned
# 本身——C1 就是這樣漏網的：.report-hero-top 整塊被 decompose，兩份報表真正
# 的標題完全消失，但沒有任何既有測試會失敗。conservation_diff() 補上這一段。
def test_conservation_diff_catches_a_dropped_heading():
    """先證明檢查機制本身有效：構造一段只在 original 出現、reskinned 完全
    沒有的敘述文字，conservation_diff 必須抓到它——這是 2026-08-03 實測會
    當場抓到 C1（RED）的同一條檢查路徑。"""
    original = "<html><body><h1>Illumio 資安與風險報表獨有標題文字</h1></body></html>"
    reskinned = "<html><body><h1>安全風險分析</h1></body></html>"
    diff = conservation_diff(original, reskinned)
    assert "illumio資安與風險報表獨有標題文字" in diff


def test_conservation_diff_tolerates_icon_label_value_node_splitting():
    """原始封面把「📅 icon + 標籤 + 冒號 + 值」黏在同一個文字節點裡，新殼拆成
    dt/dd 兩個獨立節點——資訊沒有少一個字，只是換了節點結構，不該被判定為
    遺失（若標籤或值真的有一邊不見了，才要抓）。"""
    original = "<div>📅 資料範圍: 2026-07-16 – 2026-07-23</div>"
    reskinned_split = "<dl><dt>資料範圍</dt><dd>2026-07-16 – 2026-07-23</dd></dl>"
    assert conservation_diff(original, reskinned_split) == []

    reskinned_lost_value = "<dl><dt>資料範圍</dt><dd>（無資料）</dd></dl>"
    assert conservation_diff(original, reskinned_lost_value) != []


def test_conservation_diff_ignores_the_allowlisted_print_button_chrome():
    original = '<button class="print-btn" onclick="window.print()">列印 / PDF</button>'
    assert conservation_diff(original, "<body></body>") == []


@pytest.mark.parametrize("name,html", [("traffic", TRAFFIC), ("audit", AUDIT)],
                          ids=["traffic", "audit"])
def test_original_to_reskinned_preserves_all_narrative_text(name, html):
    """C1 的真正回歸守門：直接用 extract_cover/extract_sections/build_shell
    在記憶體裡重建新殼（不依賴 disk 上先前 --render 產出的檔案），確保
    original→reskinned 的內容保全在 pytest 這一層就會失敗，不必等到手動
    跑 --verify。"""
    out = build_shell(extract_cover(html)["doc_title"], extract_sections(html),
                       cover=extract_cover(html))
    lost = conservation_diff(html, out)
    assert lost == [], (name, lost)
