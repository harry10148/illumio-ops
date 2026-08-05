"""把既有 exporter 產出的報表 HTML 重排進 design/v2 的統一報表殼（spec §4.1）。

這是 Phase 2 重寫 `report_css.py` 前的原型：驗證「同一份 exporter 標記 +
新的殼與 CSS」就能達到 spec §4.1 的順序（封面 → 執行摘要 → 目錄 → 發現章節 →
明細章節 → 附錄），並且不掉任何內容。

原始結構的 selector 轉錄（2026-08-03 從測試機真報表逐一比對，見
design/v2/reports/original/*.source.txt 標註來源檔）：

    body
    ├─ div.report-cover-block.screen-only   螢幕封面（eyebrow / h1 / .meta 標籤值對）
    ├─ section.report-cover.card.print-only#cover
    │      .cover-eyebrow / .cover-title / .cover-type / .cover-grade
    │      .cover-meta / .cover-footer > .cover-generated
    ├─ div.report-shell
    │   ├─ aside.report-toc.screen-only     ol > li > a[href="#id"]（＝章節標籤來源）
    │   └─ main.report-main
    │       ├─ section.exec-summary          執行摘要（.kpi-strip > .kpi）
    │       ├─ div.report-hero-top           報表題名／kicker／副標（→ 併入新封面）
    │       ├─ section.card[id]  × N         每個 id 對應 aside 目錄的一個錨點
    │       └─ footer                        版權/出處行（→ 併入附錄 colophon）
    └─ script                                互動排序/欄寬（新殼不沿用）

兩型報表（traffic / audit）結構一致，差別只在 section 數量與 id，因此
`extract_sections()` 對兩型共用一組 selector。

用法：
    python design/v2/tools/reskin_report.py            # 產出 reskinned/*.html
    python design/v2/tools/reskin_report.py --render   # 另跑 Playwright 截圖＋PDF
"""
import argparse
import html as html_mod
import pathlib
import re
import subprocess
import sys

from bs4 import CData, Comment, Declaration, Doctype, ProcessingInstruction
from bs4 import BeautifulSoup, NavigableString

HERE = pathlib.Path(__file__).resolve().parent
REPORTS = HERE.parent / "reports"
ORIGINAL = REPORTS / "original"
RESKINNED = REPORTS / "reskinned"
SHELL_CSS = REPORTS / "shell.css"

# ---------------------------------------------------------------- tone 對映 --
# 報表詞彙 → spec §2.3 的 5 tone。CRITICAL 與 HIGH 同 tone，靠實心/描邊分級。
SEVERITY_TONE = {
    "CRITICAL": "crit",
    "HIGH": "crit",
    "MEDIUM": "warn",
    "LOW": "info",
    "INFO": "neutral",
    "OK": "ok",
    "GOOD": "ok",
    "PASS": "ok",
}
SEVERITY_RANK = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "PASS", "GOOD", "OK"]
_SEV_CLASS_RE = re.compile(r"\b(?:badge|risk|sev)-([A-Z]{2,})\b")
# audit 的 risk-badge 只把 severity 寫在文字裡（class 沒帶級別），因此 tone
# 判讀在 _annotate_tones() 之後改看 data-sev；兩種來源都要認。
_SEV_ANY_RE = re.compile(r'(?:\b(?:badge|risk|sev)-|data-sev=")([A-Z]{2,})')

# 舊調色盤 → token。exporter 內嵌樣式殘留的硬編色碼一律改吃 tone token，
# 否則新殼會被舊色系穿透（幾何類宣告如 width 不動）。
LEGACY_COLOR = {
    "#BE122F": "var(--tone-crit-fg)",
    "#C0392B": "var(--tone-crit-fg)",
    "#DC2626": "var(--tone-crit-fg)",
    "#E53E3E": "var(--tone-crit-fg)",
    "#EF4444": "var(--tone-crit-border)",
    "#991B1B": "var(--tone-crit-fg)",
    "#7F1D1D": "var(--tone-crit-fg)",
    "#FCA5A5": "var(--tone-crit-border)",
    "#FEF2F2": "var(--tone-crit-bg)",
    "#FFF5F5": "var(--tone-crit-bg)",
    "#FEE2E2": "var(--tone-crit-bg)",
    "#D4A017": "var(--tone-warn-border)",
    "#D69E2E": "var(--tone-warn-border)",
    "#F59E0B": "var(--tone-warn-border)",
    "#FEFCE8": "var(--tone-warn-bg)",
    "#16A34A": "var(--tone-ok-fg)",
    "#38A169": "var(--tone-ok-fg)",
    "#22C55E": "var(--tone-ok-border)",
    "#D4EDDA": "var(--tone-ok-bg)",
    "#60A5FA": "var(--tone-info-border)",
    "#3987E5": "var(--tone-info-border)",
    "#375379": "var(--text-2)",
    "#6B7280": "var(--text-3)",
    "#808080": "var(--text-3)",
    "#989A9B": "var(--text-3)",
    "#F9FAFB": "var(--surface-2)",
    "#F5F5F5": "var(--surface-2)",
    "#000000": "var(--text-1)",
    "#FFFFFF": "var(--paper)",
    "#FFF": "var(--paper)",
}
# 型別由新殼的字級系統決定，內嵌宣告一律丟棄（否則列印時字級被舊值鎖死）
DROP_DECLS = {
    "font-size", "font-weight", "font-family", "letter-spacing",
    "text-transform", "opacity", "line-height", "color-scheme",
}

KIND_LABEL = {"exec": "執行摘要", "finding": "發現", "detail": "明細", "appendix": "附錄"}
FINDING_CARD_SELECTOR = ".finding-card, .concern-card, .audit-attn-item"


def tone_of(fragment):
    """由片段內的 severity 標記取最嚴重的一級，回傳 5 tone 之一。"""
    sevs = set(_SEV_ANY_RE.findall(fragment))
    if "note-warn" in fragment:
        sevs.add("MEDIUM")
    for sev in SEVERITY_RANK:
        if sev in sevs:
            return SEVERITY_TONE[sev]
    return "neutral"


def severity_counts(node):
    """章節內各 severity 標記的出現次數（供章頭的 mark chip 用）。

    在 _annotate_tones() 之後對 [data-sev] 數，兩種標記寫法（class 帶級別 /
    只有徽章文字帶級別）都算得到，且不會重複計數。
    """
    counts = {}
    for el in node.select("[data-sev]"):
        sev = el["data-sev"]
        if sev in SEVERITY_TONE:
            counts[sev] = counts.get(sev, 0) + 1
    return counts


# ------------------------------------------------------------ 內嵌樣式清洗 --
def _map_color_value(value):
    def repl(m):
        return LEGACY_COLOR.get(m.group(0).upper(), m.group(0))

    return re.sub(r"#[0-9A-Fa-f]{3,6}\b", repl, value)


def _clean_style(style):
    kept = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        prop, _, value = decl.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if not prop or prop in DROP_DECLS:
            continue
        kept.append(f"{prop}: {_map_color_value(value)}")
    return "; ".join(kept)


def _retokenize_inline_styles(node):
    """清洗 node 底下所有內嵌樣式；圖表 SVG 內部原樣不動（server-side 產物）。"""
    for el in node.select("[style]"):
        if el.name == "svg" or el.find_parent("svg") is not None:
            continue
        cleaned = _clean_style(el["style"])
        if cleaned:
            el["style"] = cleaned
        else:
            del el["style"]


def _annotate_tones(node):
    """把 severity class 翻成 data-tone/data-sev，讓 tone token 直接生效。"""
    for el in node.select("[class]"):
        classes = el.get("class") or []
        sev = next(
            (m.group(1) for c in classes if (m := _SEV_CLASS_RE.search(c))
             and m.group(1) in SEVERITY_TONE),
            None,
        )
        if sev is None and "note-warn" in classes:
            sev = "MEDIUM"
        if sev is None and any(c in ("badge", "risk-badge") for c in classes):
            text = el.get_text(strip=True).upper()
            sev = next((s for s in SEVERITY_RANK if s == text), None)
        if sev:
            el["data-tone"] = SEVERITY_TONE[sev]
            el["data-sev"] = sev
    # 語意明確者才給 tone：up/down 本身不帶好壞（流量變多不等於變差）
    for selector, tone in ((".bp-box", "info"), (".trend-chip--good-up", "ok"),
                           (".note-warn", "warn")):
        for el in node.select(selector):
            if "data-tone" not in el.attrs:
                el["data-tone"] = tone


def _title_cells(node):
    """.cell-long 的摘要一定要帶 title 全文——省略必附全文（CLAUDE.md 硬規則）。"""
    for details in node.select("details.cell-long"):
        full = details.select_one(".cell-long-full")
        summary = details.find("summary")
        if summary is not None and full is not None:
            summary["title"] = full.get_text("\n", strip=True)


LANDSCAPE_MIN_COLUMNS = 10
_NUMERIC_RE = re.compile(r"^[<>~+-]?[\d][\d,.\s]*\s*[%KMGTB]{0,3}$")


def _mark_numeric_columns(node):
    """整欄都是數字的欄位標成 .num：等寬、靠右、且不准斷行。

    列印的寬表用 overflow-wrap: anywhere 保證塞得進紙面，副作用是連
    「1,023,744」都會被折成兩行（2026-08-03 逐頁實檢抓到）。數值欄改成
    nowrap，欄寬下限就是完整數字，其餘文字欄仍可任意折。
    """
    for table in node.select("table.report-table"):
        heads = table.select("thead th")
        rows = [tr.find_all("td", recursive=False) for tr in table.select("tbody tr")]
        rows = [cells for cells in rows if len(cells) == len(heads)]
        if not heads or not rows:
            continue
        for idx in range(len(heads)):
            values = [c.get_text(" ", strip=True) for c in (r[idx] for r in rows)]
            filled = [v for v in values if v]
            if not filled or not all(_NUMERIC_RE.match(v) for v in filled):
                continue
            heads[idx]["class"] = (heads[idx].get("class") or []) + ["num"]
            for row in rows:
                row[idx]["class"] = (row[idx].get("class") or []) + ["num"]


_ISO_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)$")


def _mark_column_kinds(node):
    """給欄位語意 class（.col-long／.col-ts），讓 shell.css 能逐欄定寬度政策。

    起因（2026-08-05 使用者截圖實證）：寬表的長文欄（change_detail）在列印時
    以 max-content 搶走整個版面，其餘 meta 欄被壓到逐字直排——「SEVERITY」印成
    「SE VE RI TY」、「success」印成「suc ces s」。根因是那批欄位在列印時被
    統一設成 overflow-wrap: anywhere（為了保證塞得進紙面），min-content 因此
    降到一個字元，auto 佈局就把寬度全讓給 max-content 最大的長文欄。

    這裡只做「標記」，寬度政策留在 CSS：
      - .col-long：整欄含 details.cell-long 的長文欄，由 CSS 給上限份額。
      - .col-ts：整欄都是 ISO 時間戳的欄位。時間戳是一個沒有空白的長 token，
        逐字拆等於讀不到時間；改成在日期與時間之間插一個 <wbr/>（唯一的折行
        機會）並在 CSS 讓它只用 break-word，最差就是折成「日期／時間」兩行。
    """
    for table in node.select("table.report-table"):
        heads = table.select("thead th")
        rows = [tr.find_all("td", recursive=False) for tr in table.select("tbody tr")]
        rows = [cells for cells in rows if len(cells) == len(heads)]
        if not heads or not rows:
            continue
        for idx in range(len(heads)):
            cells = [row[idx] for row in rows]
            kind = None
            if any(c.select_one("details.cell-long") is not None for c in cells):
                kind = "col-long"
            else:
                texts = [c.get_text(" ", strip=True) for c in cells]
                filled = [v for v in texts if v]
                if filled and all(_ISO_TS_RE.match(v) for v in filled):
                    kind = "col-ts"
                    for cell in cells:
                        _split_timestamp(cell)
            if kind is None:
                continue
            heads[idx]["class"] = (heads[idx].get("class") or []) + [kind]
            for cell in cells:
                cell["class"] = (cell.get("class") or []) + [kind]


def _soften_header_labels(node):
    """欄名的 snake_case 底線後補 <wbr/>：長欄名不再獨自撐住整欄的最小寬度。

    「workloads_affected」是一個 18 字元、沒有任何折行機會的 token，break-word
    下它就是該欄的 min-content（實測 121px，佔 A4 直式寬表版面的 18%），把長文
    欄擠到只剩 20px。補上折行機會後最小寬度降到「affected」那一段，版面才還得
    回去。用 <wbr/>（零文字的折行機會）而非改 word-break，才不會退回逐字拆——
    原 exporter 對 event_type 值也是同一套做法（sec_<wbr/>policy.<wbr/>create）。
    """
    for label in node.select("th .th-label"):
        if len(label.contents) != 1 or not isinstance(label.contents[0], NavigableString):
            continue
        parts = [p for p in re.split(r"(_)", label.get_text()) if p != ""]
        if len(parts) < 2:
            continue
        label.clear()
        for part in parts:
            label.append(part)
            if part == "_":
                label.append(BeautifulSoup("<wbr/>", "html.parser").wbr)


def _split_timestamp(cell):
    """在 ISO 時間戳的日期與時間之間插一個 <wbr/>：唯一允許的折行點。

    <wbr/> 不產生任何文字，保全比對（verify_conservation／verify_no_truncation
    都先把空白正規化掉）不受影響。
    """
    text = cell.get_text(" ", strip=True)
    match = _ISO_TS_RE.match(text)
    if match is None or cell.find("wbr") is not None:
        return
    cell.clear()
    cell.append(match.group(1))
    cell.append(BeautifulSoup("<wbr/>", "html.parser").wbr)
    cell.append(match.group(2))


def _wide_table_hint(node):
    """寬表在螢幕上會左右捲動——明講欄數與列印行為，捲動才不會被誤認成截斷。

    欄數 ≥ LANDSCAPE_MIN_COLUMNS 才標成 --landscape（列印切 A4 橫式命名頁）；
    8–9 欄留在直式縮排版，免得每張寬表都多賠一個分頁。
    """
    for panel in node.select(".report-table-panel--wide"):
        if panel.select_one(".table-hint"):
            continue
        table = panel.find("table")
        cols = int((table.get("data-column-count") if table is not None else 0)
                   or len(table.select("thead th") if table is not None else []))
        landscape = cols >= LANDSCAPE_MIN_COLUMNS
        if landscape:
            panel["class"] = (panel.get("class") or []) + ["report-table-panel--landscape"]
        printed = "列印自動轉為 A4 橫式頁" if landscape else "列印為 A4 直式縮排版"
        hint = BeautifulSoup(
            f'<p class="table-hint">{cols} 欄寬表 · 螢幕可左右捲動檢視全部欄位'
            f" · {printed}</p>", "html.parser")
        panel.insert(0, hint)


def _text(el):
    return el.get_text(" ", strip=True) if el is not None else ""


# ------------------------------------------------------------------- 抽取 --
def extract_cover(html, source=None):
    """從舊的雙封面（螢幕 .report-cover-block + 列印 section.report-cover）
    與 .report-hero-top 抽出封面欄位。全部是原報表既有的真值，不補假資料。"""
    soup = BeautifulSoup(html, "html.parser")
    screen = soup.select_one("div.report-cover-block")
    printed = soup.select_one("section.report-cover")
    hero = soup.select_one(".report-hero-top")

    meta = {}
    for block in (screen.select(".meta > div") if screen else []):
        label = block.find("div")
        value = block.find("strong")
        if label is not None and value is not None:
            meta[_text(label)] = _text(value)
    for block in (printed.select(".cover-meta > div") if printed else []):
        raw = _text(block).lstrip("📅🕒 ").strip()
        if ":" in raw:
            key, _, value = raw.partition(":")
            meta.setdefault(key.strip(), value.strip())
    generated = printed.select_one(".cover-generated") if printed else None
    if generated is not None:
        lines = [t for t in generated.stripped_strings]
        if len(lines) >= 2:
            meta.setdefault(lines[0], lines[-1])
    if source:
        meta["原始報表檔"] = source

    grade = soup.select_one(".cover-grade")
    # 短型別標籤（.cover-title/.cover-type/screen h1 三處都寫同一句，例如
    # 「安全風險分析」「稽核報告」）——這不是報表的完整標題，真正的標題只在
    # .report-hero-top 的 <h1> 裡（例如「Illumio 資安與風險報表」）。extract_sections
    # 會把整個 hero-top decompose 掉搬進封面，若這裡不撈 <h1> 全文，兩份輸出
    # 的報表標題就會整個消失（2026-08-04 C1）。
    type_label = _text(printed.select_one(".cover-title")) if printed else _text(
        screen.find("h1") if screen else None)
    heading = _text(hero.find("h1")) if hero else ""
    return {
        "eyebrow": _text(printed.select_one(".cover-eyebrow")) if printed else "",
        "title": heading or type_label,
        # 原始 <title> 標籤的值逐字保留，不由封面欄位重新推導——舊 exporter
        # 的 <title>（例如「Illumio 流量報告」）跟 hero <h1>、cover-title 三者
        # 文案都不同，任何一個拿來頂替都是竄改原值。
        "doc_title": _text(soup.title) or heading or type_label,
        "type": _text(printed.select_one(".cover-type")) if printed else "",
        "kicker": _text(hero.select_one(".report-kicker")) if hero else "",
        "subtitle": _text(hero.select_one(".report-subtitle")) if hero else "",
        "profile": _text(soup.select_one(".report-profile-badge")),
        "grade": " ".join(grade.stripped_strings) if grade is not None else "",
        "meta": meta,
    }


def extract_sections(html):
    """切章：main.report-main 的每個直接子元素＝一章。

    回傳 [{"id","title","label","kind","tone","html","marks"}]，順序＝原順序。
    exec-summary → kind "exec"、footer → kind "appendix"、
    含發現卡（.finding-card/.concern-card/.audit-attn-item）→ "finding"、其餘 "detail"。
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main.report-main") or soup.select_one("div.report-shell")
    if main is None:
        raise ValueError("找不到 main.report-main：報表結構與轉錄的 selector 不符")

    toc_labels = {
        a["href"].lstrip("#"): _text(a)
        for a in soup.select("aside.report-toc a[href^='#']")
    }

    # 報表題名區塊屬於封面，不留在第一章裡（不含表格/圖表，切章不變量不受影響）
    for hero_top in main.select(".report-hero-top"):
        hero_top.decompose()

    sections = []
    for el in main.find_all(recursive=False):
        if el.name == "footer":
            kind, sec_id, title = "appendix", "appendix", "附錄"
        else:
            classes = el.get("class") or []
            sec_id = el.get("id") or ("exec-summary" if "exec-summary" in classes else None)
            if sec_id is None:
                # 比照上面「找不到 main.report-main」的失敗方式：不認得的章節
                # 結構要吵，不要默默 continue 把整章丟掉。之前這裡是靜默
                # continue，一旦 exporter 加了新的無 id 直接子元素，該章內容
                # 會無聲消失，且不會被任何守門測試抓到。
                raise ValueError(
                    "extract_sections：main.report-main 底下有不認得的章節結構"
                    f"（<{el.name} class={classes!r}>，既無 id 也不是 exec-summary）"
                    "——selector 轉錄需要更新，不能默默跳過")
            kind = "exec" if "exec-summary" in classes else (
                "finding" if el.select_one(FINDING_CARD_SELECTOR) else "detail")
            heading = el.find(re.compile(r"^h[1-3]$"))
            title = _text(heading) or toc_labels.get(sec_id, sec_id)
            if heading is not None and _text(heading) == title:
                heading.decompose()

        _retokenize_inline_styles(el)
        _annotate_tones(el)
        _title_cells(el)
        _mark_numeric_columns(el)
        _mark_column_kinds(el)
        _soften_header_labels(el)
        _wide_table_hint(el)
        body = el.decode_contents() if el.name != "footer" else str(el)
        sections.append({
            "id": sec_id,
            "title": title,
            "label": toc_labels.get(sec_id, title),
            "kind": kind,
            "tone": tone_of(body),
            "marks": severity_counts(el),
            "html": body,
        })
    return sections


# --------------------------------------------------------------------- 殼 --
def _esc(text):
    return html_mod.escape(text or "", quote=True)


def _mark_chips(marks):
    """章頭的 severity chip 全顯示——章內實際有幾種 severity 就秀幾顆，不砍到
    3 顆。曾經 `chips[:3]` 靜默丟掉排序較後的 severity（traffic findings 章
    少了 INFO/LOW、ransomware 章少了 LOW），而 .chapter-marks 本來就是
    flex-wrap: wrap，放多顆不會破版，沒有理由裁切。"""
    chips = []
    for sev in SEVERITY_RANK:
        if marks.get(sev):
            chips.append(
                f'<span class="mark-chip" data-tone="{SEVERITY_TONE[sev]}"'
                f' title="本章共 {marks[sev]} 處 {sev} 標記">{sev} {marks[sev]}</span>')
    return "".join(chips)


def _render_cover(cover, title, tone):
    if not cover:
        return (f'<header class="cover" data-shell="cover" data-tone="{tone}">'
                f"<h1>{_esc(title)}</h1></header>")
    badges = ""
    if cover.get("profile") and cover["profile"] != cover.get("title"):
        badges += f'<span class="report-profile-badge">{_esc(cover["profile"])}</span>'
    if cover.get("grade"):
        badges += f'<span class="grade-chip" data-tone="{tone}">{_esc(cover["grade"])}</span>'
    meta = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in cover["meta"].items())
    return (
        f'<header class="cover" data-shell="cover" data-tone="{tone}">'
        f'<p class="cover-eyebrow">{_esc(cover.get("eyebrow") or "Illumio Operations")}</p>'
        f"<h1>{_esc(cover.get('title') or title)}</h1>"
        f'<p class="cover-kicker">{_esc(cover.get("kicker"))}'
        f'{" · " + _esc(cover["subtitle"]) if cover.get("subtitle") else ""}</p>'
        f'<div class="cover-badges">{badges}</div>'
        f'<dl class="cover-meta">{meta}</dl>'
        "</header>")


def _render_toc(entries, page_numbers):
    items = []
    for idx, entry in entries:
        page = (page_numbers or {}).get(entry["id"])
        page_html = f'<span class="toc-page">{page}</span>' if page else ""
        items.append(
            f'<li data-tone="{entry["tone"]}"><a href="#{_esc(entry["id"])}">'
            f'<span class="toc-num">{idx}</span>'
            f'<span class="toc-label">{_esc(entry["label"] or entry["title"])}</span>'
            f'<span class="toc-dot"></span>{page_html}</a></li>')
    return ('<nav class="toc" data-shell="toc" aria-label="目錄"><h2>目錄</h2>'
            f"<ol>{''.join(items)}</ol></nav>")


def _render_appendix(sections, cover):
    rules = []
    for section in sections:
        soup = BeautifulSoup(section["html"], "html.parser")
        for card in soup.select(FINDING_CARD_SELECTOR):
            code = card.select_one(".finding-rule-id, .concern-event, .audit-attn-event-code")
            name = card.select_one(".finding-title, .concern-summary, .audit-attn-summary")
            badge = card.select_one(".badge, .risk-badge")
            sev = _text(badge).upper() or "INFO"
            rules.append((
                _text(code) or "—",
                _text(name)[:120],
                sev,
                SEVERITY_TONE.get(sev, "neutral"),
                section["id"],
            ))
    rule_html = "".join(
        f'<li data-tone="{tone}"><code>{_esc(code)}</code>'
        f'<span>{_esc(name)}</span><span class="rule-sev">{_esc(sev)}</span></li>'
        for code, name, sev, tone, _sid in rules)
    meta = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
                   for k, v in (cover or {}).get("meta", {}).items())
    chapters = "".join(
        f'<dt>{i:02d}</dt><dd>{_esc(s["title"])}</dd>'
        for i, s in enumerate((s for s in sections if s["kind"] in ("finding", "detail")), 1))
    colophon = next((s["html"] for s in sections if s["kind"] == "appendix"), "")
    return (
        '<section class="appendix" data-shell="appendix" id="appendix"><h2>附錄</h2>'
        '<div class="appendix-grid">'
        f'<div><h3>產出參數</h3><dl>{meta}</dl></div>'
        f'<div><h3>章節索引</h3><dl>{chapters}</dl></div>'
        "</div>"
        + (f'<h3>發現規則索引（{len(rules)} 條）</h3><ol class="rule-index">{rule_html}</ol>'
           if rules else "")
        + f'<div class="colophon">{colophon}</div></section>')


def chapter_order(sections):
    """spec §4.1 的章節順序：發現章節在前、明細章節在後（各自維持原順序）。

    出圖量頁碼時的章號 marker 必須吃這同一個順序——兩邊各排一次的話，目錄
    頁碼會整組錯位（2026-08-03 實測：traffic「發現與行動」被標成第 32 頁）。
    """
    return ([s for s in sections if s["kind"] == "finding"]
            + [s for s in sections if s["kind"] == "detail"])


def build_shell(title, sections, cover=None, page_numbers=None, css=None):
    """把切出來的章節填進 spec §4.1 的殼；回傳完整、可離線開啟的 HTML。"""
    css = css if css is not None else SHELL_CSS.read_text(encoding="utf-8")
    execs = [s for s in sections if s["kind"] == "exec"]
    ordered = chapter_order(sections)
    doc_tone = next((s["tone"] for s in ordered if s["tone"] == "crit"),
                    ordered[0]["tone"] if ordered else "neutral")

    parts = [_render_cover(cover, title, doc_tone)]
    for section in execs:
        parts.append(
            f'<section class="exec" data-shell="exec" id="{_esc(section["id"])}">'
            f'<h2>{_esc(section["title"])}</h2>{section["html"]}</section>')

    toc_entries = [(f"{i:02d}", s) for i, s in enumerate(execs + ordered)]
    parts.append(_render_toc(toc_entries, page_numbers))

    chapters = []
    for idx, section in enumerate(ordered, 1):
        chapters.append(
            f'<section class="chapter" id="{_esc(section["id"])}"'
            f' data-shell="{section["kind"]}" data-tone="{section["tone"]}">'
            f'<div class="chapter-head">'
            f'<span class="chapter-index">S{idx:02d}</span>'
            f'<span class="chapter-eyebrow">{KIND_LABEL[section["kind"]]}</span>'
            f'<h2 class="chapter-title">{_esc(section["title"])}</h2>'
            f'<span class="chapter-marks">{_mark_chips(section["marks"])}</span>'
            f"</div>{section['html']}</section>")
    parts.append(f'<div class="chapters">{"".join(chapters)}</div>')
    parts.append(_render_appendix(sections, cover))

    out = (
        "<!doctype html>\n"
        '<html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(title)}</title>\n<style>\n{css}\n</style></head>\n"
        f'<body data-report="{_esc(title)}"><div class="sheet"><div class="doc">'
        f'{"".join(parts)}</div></div></body></html>\n')
    # HTML 解析器會把 svg 的 viewBox 小寫化；還原以免舊瀏覽器不縮放
    return out.replace(" viewbox=", " viewBox=")


def reskin(name, page_numbers=None):
    src = ORIGINAL / f"{name}.html"
    source_file = (ORIGINAL / f"{name}.source.txt")
    source = source_file.read_text(encoding="utf-8").strip() if source_file.exists() else None
    html = src.read_text(encoding="utf-8")
    cover = extract_cover(html, source=source)
    sections = extract_sections(html)
    # build_shell() 的 title 參數只餵 <title> 標籤（cover 存在時 <h1> 一律吃
    # cover["title"]）；用 doc_title 保留原始 <title> 的逐字值，不要用封面欄位
    # 重新推導出不同的文案（2026-08-04 C1：曾退化成「安全風險分析」）。
    title = cover.get("doc_title") or cover.get("title") or name
    return build_shell(title, sections, cover=cover, page_numbers=page_numbers), sections


# ------------------------------------------------------------------ 產出 --
def _page_index(pdf_path, markers):
    """兩趟出圖的第一趟：從 PDF 文字層找出每章的頁碼。

    章用 ASCII 章號 S01… 當錨點（中文字在文字層可能被拆行、加空白，ASCII 穩）；
    執行摘要沒有章號，改用標題文字。比對前把空白全部拿掉。
    """
    text = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                          check=True, capture_output=True, text=True).stdout
    pages = [re.sub(r"\s+", "", page) for page in text.split("\f")]
    found = {}
    for marker, sec_id in markers.items():
        needle = re.sub(r"\s+", "", marker)
        for number, page in enumerate(pages, 1):
            if needle in page:
                found[sec_id] = number
                break
    return found


def _shrink_png(path):
    """整頁截圖動輒 3.5 MB；報表版面只有百來種顏色，量化到 256 色省 2–3 倍
    體積而看不出差別（圖表是純色 matplotlib SVG）。"""
    from PIL import Image

    image = Image.open(path).convert("RGB")
    image.quantize(colors=256, method=Image.MEDIANCUT).save(path, optimize=True)


def _render(name, page_numbers=None):
    from playwright.sync_api import sync_playwright

    RESKINNED.mkdir(parents=True, exist_ok=True)
    (RESKINNED / "shots").mkdir(exist_ok=True)
    html, sections = reskin(name, page_numbers=page_numbers)
    target = RESKINNED / f"{name}.html"
    target.write_text(html, encoding="utf-8")

    pdf_path = RESKINNED / f"{name}.pdf"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for width in (1280, 800):
            page.set_viewport_size({"width": width, "height": 1000})
            page.goto(target.resolve().as_uri())
            shot = RESKINNED / "shots" / f"{name}-{width}.png"
            page.screenshot(path=str(shot), full_page=True)
            _shrink_png(shot)
        page.emulate_media(media="print")
        page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
        browser.close()

    markers = {f"S{i:02d}": s["id"] for i, s in enumerate(chapter_order(sections), 1)}
    markers.update({s["title"]: s["id"] for s in sections if s["kind"] == "exec"})
    return pdf_path, _page_index(pdf_path, markers)


TEXT_SELECTORS = (
    ".report-table tbody td, .report-table thead th, .cell-long-full,"
    " .finding-desc, .finding-rec, .concern-summary, .audit-attn-rec,"
    " .kpi-value, .ev-pill b, .mat-val, .cov-value, .sev-count, .cover-meta dd"
)


def _norm(text):
    import unicodedata
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


# A4 直式：210mm - 26mm 邊界 = 184mm ≈ 695px（96dpi）；橫式 297-23mm ≈ 1035px
PRINT_WIDTH_PORTRAIT = 695
PRINT_WIDTH_LANDSCAPE = 1035

_CLIP_JS = """(portrait) => {
  const bad = [];
  for (const panel of document.querySelectorAll('.report-table-panel')) {
    if (getComputedStyle(panel).overflowX === 'visible') continue;
    if (panel.classList.contains('report-table-panel--landscape') !== !portrait) continue;
    const t = panel.querySelector('table');
    if (t && t.scrollWidth > panel.clientWidth + 1)
      bad.push([panel.closest('section').id, t.scrollWidth, panel.clientWidth]);
  }
  return bad;
}"""


def verify_print_clipping(name):
    """列印時被 overflow:hidden 橫向切掉的表格——PDF 文字層驗不出來（被裁切的
    字仍在 content stream 裡），只能量 scrollWidth。直式/橫式各量一次。"""
    from playwright.sync_api import sync_playwright

    uri = (RESKINNED / f"{name}.html").resolve().as_uri()
    clipped = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.emulate_media(media="print")
        for width, portrait in ((PRINT_WIDTH_PORTRAIT, True), (PRINT_WIDTH_LANDSCAPE, False)):
            page.set_viewport_size({"width": width, "height": 1000})
            page.goto(uri)
            clipped += [(name, "portrait" if portrait else "landscape", *row)
                        for row in page.evaluate(_CLIP_JS, portrait)]
        browser.close()
    return clipped


def verify_no_truncation(name):
    """列印無聲截斷檢查：HTML 每段文字都要出現在 PDF 的文字層裡。

    比對前把空白全部拿掉並 casefold（CSS 會把欄名轉大寫、換行位置也不同）。
    含 .cell-long 的儲存格改用摘要/全文分開比對——列印時摘要本來就藏起來，
    整格串起來的字串本來就不會連續出現。

    門檻：略過 <4 字元的短字串（不計入回傳的 checked 分母）。理由：短字串
    跨欄碰撞率高——PDF 文字層裡任何位置都可能巧合出現形似的短片段，逐字比
    對這種長度的字串既會製造假陽性（巧合命中掩蓋真正遺失）也會製造假陰性
    （排版差異被誤判成截斷），對「有沒有無聲截斷」這個問題幾乎沒有訊號量。
    這個門檻不是把短字串「當作已驗證」，而是不把它們算進比對範圍；--verify
    的輸出行會明講「比對 N 段文字」，N 就是排除短字串後的真實分母。
    """
    html = (RESKINNED / f"{name}.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    for svg in soup.find_all("svg"):
        svg.decompose()
    flat = _norm(subprocess.run(
        ["pdftotext", "-raw", str(RESKINNED / f"{name}.pdf"), "-"],
        check=True, capture_output=True, text=True).stdout)
    missing, checked = [], 0
    for el in soup.select(TEXT_SELECTORS):
        if el.select_one("details.cell-long"):
            continue
        text = _norm(el.get_text(" ", strip=True))
        if len(text) < 4:
            # 略過 <4 字元的短字串：短到這個程度（數字碎片、單位、圖示字元
            # 之類）在整份 PDF 文字層裡到處都找得到形似的片段，逐字比對只會
            # 產生大量跨欄/跨儲存格的假陽性巧合命中或假陰性排版差異，稀釋掉
            # 真正的截斷訊號。這是「略過」不是「當作已驗證」——見 --verify
            # 輸出行的比對段數，短字串本來就不計入分母。
            continue
        checked += 1
        if text not in flat:
            missing.append(text[:90])
    return checked, missing


# --------------------------------------------------- original→reskinned 保全 --
# verify_no_truncation 只比對 reskinned↔PDF（抓「印出來但被列印裁切」），從沒
# 比對過 original→reskinned 本身（抓「切章/抽取階段就把內容弄丟了」）——2026-08-03
# 的 C1 就是這樣：.report-hero-top 整塊被 decompose()，裡面的真報表標題
# 「Illumio 資安與風險報表」/「Illumio 稽核與系統事件報表」兩份輸出都不在了，
# 但 verify_no_truncation 完全驗不出來，因為它只看 reskinned 自己的 PDF。
CONSERVATION_ALLOWLIST = {
    # aside.report-toc 側欄的「列印 / PDF」按鈕（onclick="window.print()"）：
    # 純畫面互動控制項，不是報表內容；aside 本身不在 main.report-main 底下，
    # 從未被 extract_sections/extract_cover 處理過，新殼由畫面本身提供列印
    # 入口，不需要落地成 HTML 文字節點。
    "列印/pdf",
}


def _conservation_text(html):
    """去除 script/style/svg（圖表 SVG 原樣保留，內容比對交給既有的表格/圖表
    數量守恆測試，這裡只看『敘述文字』），回傳 (原始 leaf 文字集合, 攤平後的
    比對用長字串)。

    `find_all(string=True)` 連 Doctype/Comment/ProcessingInstruction 這些非
    內容的 NavigableString 子類都會配到（例如 `<!doctype html>` 的節點文字
    就是字面上的 "html"）；但 `get_text()` 攤平字串時不會納入這些子類。兩邊
    用不同的字串集合會製造假陽性——leaf 集合裡有「html」，攤平字串卻找不到，
    看起來像內容遺失，其實只是文件宣告本身，必須先濾掉。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "svg"]):
        tag.decompose()
    non_content = (Comment, Doctype, ProcessingInstruction, CData, Declaration)
    leaves = {
        _norm(str(s)) for s in soup.find_all(string=True)
        if not isinstance(s, non_content) and len(_norm(str(s))) >= 4
    }
    flat = _norm(soup.get_text(" "))
    return leaves, flat


def _conservation_preserved(text, flat):
    """text 是否在 flat 裡『找得到』。

    允許一種結構性重排：原始節點把 icon/標籤/值黏在同一個文字節點裡
    （例如 audit 封面的「📅 資料範圍: 2026-07-16 – 2026-07-23」），新殼把
    圖示、標籤、值拆成獨立節點（dt/dd）——資訊沒有少一個字，只是不再是
    同一段字串。這種情況只在『標籤與值各自都找得到』時才算保全，不是
    放寬到「隨便一部分符合就算數」。
    """
    if text in flat:
        return True
    core = re.sub(r"^[^\w一-鿿]+", "", text)
    if ":" in core:
        label, _, value = core.partition(":")
        if label and value and label in flat and value in flat:
            return True
    return False


def conservation_diff(original_html, reskinned_html):
    """original→reskinned 文字節點保全檢查：original 的每一段敘述文字（去除
    script/style/svg 後的 leaf text node，≥4 字）都必須在 reskinned 裡找得到
    ——找不到就是切章/抽取階段把內容弄丟了。回傳未保全的文字清單（已扣掉
    CONSERVATION_ALLOWLIST 明列的 chrome）。"""
    orig_leaves, _ = _conservation_text(original_html)
    _, resk_flat = _conservation_text(reskinned_html)
    return sorted(
        text for text in orig_leaves
        if text not in CONSERVATION_ALLOWLIST
        and not _conservation_preserved(text, resk_flat)
    )


def verify_conservation(name):
    """CLI --verify 用：讀 disk 上的 original/{name}.html 與 reskinned/{name}.html。"""
    original = (ORIGINAL / f"{name}.html").read_text(encoding="utf-8")
    reskinned = (RESKINNED / f"{name}.html").read_text(encoding="utf-8")
    return conservation_diff(original, reskinned)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true",
                        help="另跑 Playwright：雙寬度截圖 + A4 PDF（兩趟，回填目錄頁碼）")
    parser.add_argument("--names", default="traffic,audit")
    parser.add_argument("--verify", action="store_true",
                        help="比對既有 PDF 的文字層，證明沒有無聲截斷")
    args = parser.parse_args()

    RESKINNED.mkdir(parents=True, exist_ok=True)
    failed = False
    for name in args.names.split(","):
        if args.verify:
            checked, missing = verify_no_truncation(name)
            clipped = verify_print_clipping(name)
            lost = verify_conservation(name)
            ok = not (missing or clipped or lost)
            print(f"  {'ok' if ok else '!!'} {name}: "
                  f"比對 {checked} 段文字（略過 <4 字元短字串，理由：短字串"
                  f"跨欄碰撞率高），PDF 缺 {len(missing)} 段；"
                  f"列印橫向裁切 {len(clipped)} 張表；"
                  f"original→reskinned 保全比對缺 {len(lost)} 段")
            for text in missing[:10]:
                print("     MISSING (print)", text)
            for row in clipped[:10]:
                print("     CLIPPED", row)
            for text in lost[:10]:
                print("     LOST (original→reskinned)", text)
            failed = failed or bool(missing) or bool(clipped) or bool(lost)
            continue
        if not args.render:
            html, _ = reskin(name)
            (RESKINNED / f"{name}.html").write_text(html, encoding="utf-8")
            print(f"  ok {name}.html")
            continue
        _pdf, pages = _render(name)            # 第一趟：量頁碼
        pdf, pages2 = _render(name, pages)     # 第二趟：回填頁碼後定稿
        if pages != pages2:
            print(f"  !! {name}: 頁碼在第二趟位移 {pages} → {pages2}（目錄以第二趟為準）")
            _render(name, pages2)
        info = subprocess.run(["pdfinfo", str(pdf)], check=True,
                              capture_output=True, text=True).stdout
        npages = re.search(r"Pages:\s+(\d+)", info).group(1)
        print(f"  ok {name}: {npages} 頁 PDF、2 張截圖、目錄頁碼 {len(pages2)} 章")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
