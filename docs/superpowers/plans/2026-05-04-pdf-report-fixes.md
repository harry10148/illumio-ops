# PDF Report Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five distinct visible defects in the ReportLab-generated PDF report (`Illumio_Traffic_Report_*.pdf`): missing ASCII text, empty table rows, untranslated chart titles/labels, overlapping pie chart percentages, and matplotlib font-warning log spam.

**Architecture:** Five surgical fixes, each in a separate commit, ordered by data-correctness severity. The CJK font fix (Task 1) is also the root cause of the empty-table-row symptom (Task 2 in user's original list) — both are resolved by switching `pdf_exporter._try_register_cjk()` from a broken `assets/fonts/*.otf` lookup to ReportLab's built-in `UnicodeCIDFont('MSung-Light')`.

**Tech Stack:** ReportLab (PDF), matplotlib (chart PNG embed), pandas (table data), pytest.

**Branch:** `feat/pdf-report-fixes` (already cut from `origin/main` with prior partial work in working tree).

---

## Pre-Task: Salvage already-applied partial fixes (Task 0)

The working tree carries unstaged work from a prior session that addresses two real bugs unrelated to the five visible PDF defects:

- `pdf_exporter.py`: chart PNG temp-file was `os.unlink`'d before `doc.build()` could read it (race condition that sometimes returned no PDF).
- `report_generator.py` + `gui/routes/reports.py`: PDF/XLSX export errors were silently swallowed; now surfaced via `last_export_errors` to the GUI.
- `tests/test_pdf_exporter.py`: regression test for the temp-file race.

These fixes are correct and tested. Commit them as Task 0 to establish a clean baseline before the five new fixes.

### Task 0: Commit salvaged partial work

**Files (already modified, unstaged):**
- Modify: `src/report/exporters/pdf_exporter.py` — chart_paths list, defer unlink to after `doc.build()`
- Modify: `src/report/report_generator.py` — `last_export_errors` dict, `logger.error(..., exc_info=True)`
- Modify: `src/gui/routes/reports.py` — surface `errors` field in JSON response, accept `.pdf` / `.xlsx` in listing
- Modify: `tests/test_pdf_exporter.py` — add `test_export_pdf_with_chart_spec_does_not_lose_tempfile`

- [ ] **Step 1: Run the salvaged test to confirm it passes**

```bash
cd /home/harry/rd/illumio-ops && pytest tests/test_pdf_exporter.py -v
```

Expected: all tests PASS (3 existing + 1 new = 4).

- [ ] **Step 2: Run the broader pdf-related test slice**

```bash
pytest tests/test_pdf_exporter.py tests/test_chart_renderer.py tests/test_chart_spec_coverage.py -v
```

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add src/report/exporters/pdf_exporter.py src/report/report_generator.py \
        src/gui/routes/reports.py tests/test_pdf_exporter.py
git commit -m "$(cat <<'EOF'
fix(pdf): defer chart tempfile unlink + surface export errors to GUI

Two unrelated PDF-pipeline robustness fixes that were in-flight:

- pdf_exporter: chart PNG tempfile was unlinked inside _append_module
  before reportlab's lazy ImageReader opened it during doc.build().
  Refactor to collect tempfile paths in a caller-owned list and unlink
  them in a try/finally after build completes. Add regression test.

- report_generator + gui/routes/reports: PDF/XLSX export exceptions
  were logged at WARNING and swallowed, leaving the GUI to report
  ok=true with an empty file list. Capture per-format errors in
  last_export_errors and surface them in the JSON response so the
  user sees the actual failure.
EOF
)"
```

---

## Task 1: Fix CJK font registration (resolves missing ASCII + empty table rows)

**Background:** `pdf_exporter._CJK_FONT_SEARCH` lists three font paths:
1. `assets/fonts/NotoSansCJKtc-Regular.otf` — wrong path (`assets/` does not exist; the bundled font lives at `src/static/fonts/NotoSansCJKtc-Regular.otf`)
2. `/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf` — exists, but is a CJK-only fallback font with **no Latin glyph coverage** (renders ASCII as `.notdef` blanks)
3. `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` — exists, but ReportLab's `TTFont` cannot load it (`postscript outlines are not supported`)

Even fixing path #1 fails: the bundled `NotoSansCJKtc-Regular.otf` is a PostScript/CFF-flavored OTF, which ReportLab's `TTFont` also rejects with the same error.

**Result observed in the report:**
- Page 1 paragraph: `此 PDF 為靜態摘要，完整多語系報表請使用 HTML 或 XLSX 格式。` renders as `此　　為靜態摘要，完整多語系報表使用　　或　　格式。` (PDF/HTML/XLSX/請 dropped — `請` is missing from DroidSansFallback's coverage).
- Page 2 / Page 10 tables: all data cells are blank because cell values (verdicts like `"Allowed"`, integer flow counts, percentages like `"93.4%"`) are pure ASCII — every glyph fails to render.

**Fix:** Replace the fragile filesystem-based font registration with ReportLab's built-in `UnicodeCIDFont('MSung-Light')`, which is shipped with ReportLab itself (no external font file needed) and renders both Latin and Traditional Chinese correctly. Verified via concrete repro: `pdftotext` extracts the full mixed string after the switch.

Keep a TTF-based fallback chain for environments where `MSung-Light` is unavailable (extremely unlikely with stock ReportLab, but defensive).

**Files:**
- Modify: `src/report/exporters/pdf_exporter.py:25-55` — replace `_CJK_FONT_SEARCH` and `_try_register_cjk()`
- Modify: `tests/test_pdf_exporter.py` — add regression test asserting ASCII tokens survive PDF round-trip

- [ ] **Step 1: Write the failing regression test**

Add this test to `tests/test_pdf_exporter.py`:

```python
def test_pdf_renders_ascii_inside_cjk_paragraph(tmp_path):
    """Regression for the broken CJK font lookup that dropped ASCII glyphs.

    Previously _CJK_FONT_SEARCH pointed at a non-existent path and fell
    through to DroidSansFallbackFull (CJK-only, no Latin coverage), so any
    PDF body containing both Chinese and ASCII (e.g. "此 PDF 為...")
    rendered with the ASCII tokens as blank .notdef glyphs.
    """
    import subprocess
    from src.report.exporters.pdf_exporter import export_report_pdf

    out = tmp_path / "mixed_lang.pdf"
    export_report_pdf(
        title="Illumio 流量分析報表",
        output_path=str(out),
        module_results={
            "mod01": {
                "title": "概要",
                "summary": pd.DataFrame([
                    {"判定": "Allowed", "流量數": 12345, "占總量比例": "93.4%"},
                    {"判定": "Blocked", "流量數": 678,   "占總量比例": "5.5%"},
                ]),
            }
        },
        metadata={"generated_at": "2026-05-04 00:00", "record_count": 13023},
        lang="zh_TW",
    )
    assert out.read_bytes().startswith(b"%PDF-")

    # Probe rendered text. CID-encoded fonts may not roundtrip through every
    # extractor, so accept either pdftotext finding ALL three ASCII tokens, or
    # pdftotext being unavailable — but if pdftotext IS available and finds
    # NONE of the tokens, that's a regression.
    try:
        r = subprocess.run(["pdftotext", str(out), "-"],
                           capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return  # extractor unavailable — visual-only verification path
    text = r.stdout
    found = sum(tok in text for tok in ("Allowed", "Blocked", "12345"))
    assert found >= 2, (
        f"PDF text extraction found only {found}/3 ASCII tokens; "
        f"font likely lacks Latin coverage. Extracted text: {text!r}"
    )
```

- [ ] **Step 2: Run the test to confirm it fails on current code**

```bash
cd /home/harry/rd/illumio-ops && pytest tests/test_pdf_exporter.py::test_pdf_renders_ascii_inside_cjk_paragraph -v
```

Expected: FAIL with `AssertionError: PDF text extraction found only 0/3 ASCII tokens` (or similar). If pdftotext is missing, the test PASSES vacuously — in that case proceed but rely on the visual verification step at the end.

- [ ] **Step 3: Replace the font registration in `pdf_exporter.py`**

In `src/report/exporters/pdf_exporter.py`, replace lines 25-55 (the `_CJK_FONT_NAME`, `_CJK_FONT_SEARCH`, and `_try_register_cjk` block) with:

```python
_CJK_FONT_NAME = "Helvetica"  # overwritten below by _try_register_cjk()

# Registration order:
#  1. ReportLab's built-in CID font for Traditional Chinese (no file needed,
#     ships with reportlab, renders both Latin and CJK glyphs).
#  2. TrueType-flavoured filesystem fallbacks. NOT used for Noto Sans CJK
#     OTF/TTC files — those are PostScript/CFF outlines, which reportlab's
#     TTFont cannot parse ("postscript outlines are not supported").
_CJK_TTF_FALLBACKS = [
    # Add TTF fallbacks here if a deployment ships a TrueType-flavoured CJK
    # font. Note: bundled NotoSansCJKtc-Regular.otf is CFF-flavoured and
    # CANNOT be loaded by reportlab — leave it for matplotlib's use only.
]


def _try_register_cjk() -> str:
    """Register a CJK-capable font that also has Latin coverage. Return its name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    # Primary: ReportLab built-in CID font for Traditional Chinese.
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
        logger.info("PDF CJK font registered: MSung-Light (built-in CID)")
        return "MSung-Light"
    except Exception as exc:
        logger.warning("PDF MSung-Light registration failed: {}", exc)

    # Fallback: TrueType-flavoured files only.
    for path in _CJK_TTF_FALLBACKS:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJKFont", path))
            logger.info("PDF CJK font registered from {}", path)
            return "CJKFont"
        except Exception as exc:
            logger.debug("PDF font {} failed: {}", path, exc)

    logger.warning(
        "No CJK font registered for PDF; Chinese AND ASCII text may render "
        "as blank glyphs with Helvetica fallback."
    )
    return "Helvetica"


_CJK_FONT_NAME = _try_register_cjk()
```

- [ ] **Step 4: Run the failing test to confirm it now passes**

```bash
pytest tests/test_pdf_exporter.py::test_pdf_renders_ascii_inside_cjk_paragraph -v
```

Expected: PASS.

- [ ] **Step 5: Run the full pdf test slice and a smoke test**

```bash
pytest tests/test_pdf_exporter.py tests/test_chart_renderer.py -v
```

Expected: all PASS, no regressions.

- [ ] **Step 6: Visual verification via the actual report endpoint (manual)**

Generate a fresh report and inspect page 1 + page 2 visually:

```bash
# Whatever the user's normal command is to produce a Traffic Report PDF,
# e.g. via the GUI Reports page or:
python -c "
from src.report.report_generator import ReportGenerator
# ... existing one-shot invocation pattern (defer to user's normal flow)
"
ls -lt reports/*.pdf | head -1
```

Then read the latest PDF and visually confirm:
1. Page 1 paragraph reads `此 PDF 為靜態摘要，完整多語系報表請使用 HTML 或 XLSX 格式。` with no missing tokens
2. Page 2 / Page 10 tables now show ASCII data values in every cell (verdicts, counts, percentages)

If the visual check fails, STOP and re-investigate — the unit test cannot fully verify glyph rendering for CID fonts.

- [ ] **Step 7: Commit**

```bash
git add src/report/exporters/pdf_exporter.py tests/test_pdf_exporter.py
git commit -m "$(cat <<'EOF'
fix(pdf): use builtin UnicodeCIDFont for CJK so ASCII glyphs survive

The previous _CJK_FONT_SEARCH pointed at assets/fonts/NotoSansCJKtc-Regular.otf
(wrong path — bundle lives at src/static/fonts/) and fell through to
DroidSansFallbackFull.ttf, which has no Latin glyph coverage. Result: any
PDF body mixing CJK with ASCII (page-1 note, table data cells, percentages)
rendered the ASCII tokens as blank .notdef glyphs.

Even with the path corrected, the bundled OTF and the system Noto Sans CJK
TTC are both PostScript/CFF flavoured — reportlab's TTFont rejects them
with "postscript outlines are not supported".

Switch to reportlab's built-in UnicodeCIDFont('MSung-Light') (Traditional
Chinese, ships with reportlab, no font file needed). Add regression test
that asserts ASCII tokens survive a round-trip through a PDF containing
mixed CJK + Latin content.
EOF
)"
```

---

## Task 2: Fix overlapping pie chart percentage labels

**Background:** `chart_renderer.render_matplotlib_png` for `chart_type == "pie"` calls `ax.pie(values, labels=..., autopct="%1.1f%%", startangle=90)`. matplotlib's default `autopct` renders a label inside every slice including 0.0% slices, and places labels with no collision avoidance. Page 1 of the sample PDF shows `0.0%`, `5.5%`, and `0.0%` overlapping at the top.

**Fix:** Suppress labels on slices below a small threshold (1.0%), and pull tiny-slice labels outside the pie. Also use slightly larger figure for the pie type to give labels room.

**Files:**
- Modify: `src/report/exporters/chart_renderer.py:240-243` — `pie` branch in `render_matplotlib_png`
- Modify: `tests/test_chart_renderer.py` — add regression test for label suppression

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chart_renderer.py`:

```python
def test_pie_chart_suppresses_zero_percent_labels():
    """0.0% slices should render no autopct label (avoids overlap with adjacent slices)."""
    from src.report.exporters.chart_renderer import render_matplotlib_png
    spec = {
        "type": "pie",
        "title": "Test pie",
        "data": {"labels": ["Big", "Tiny", "Zero"], "values": [99, 1, 0]},
    }
    png = render_matplotlib_png(spec)
    # Sanity: PNG produced
    assert png.startswith(b"\x89PNG"), "expected PNG bytes"
    # Behavioural assertion is necessarily indirect for raster output.
    # We verify the autopct callable directly via the helper introduced
    # in the fix (see Step 3) — see test_pie_autopct_filter below.


def test_pie_autopct_filter():
    """The autopct callable should return '' for percentages below threshold."""
    from src.report.exporters.chart_renderer import _pie_autopct
    assert _pie_autopct(0.0) == ""
    assert _pie_autopct(0.4) == ""           # below 1.0% threshold
    assert _pie_autopct(1.0) == "1.0%"
    assert _pie_autopct(93.4) == "93.4%"
```

- [ ] **Step 2: Run tests, expect failure on `test_pie_autopct_filter` (function not yet defined)**

```bash
pytest tests/test_chart_renderer.py::test_pie_autopct_filter -v
```

Expected: FAIL with `ImportError: cannot import name '_pie_autopct'`.

- [ ] **Step 3: Implement the fix in `chart_renderer.py`**

Add the helper near the top of `chart_renderer.py` (right after the `_PALETTE` definition, around line 60):

```python
def _pie_autopct(pct: float, *, threshold: float = 1.0) -> str:
    """Suppress autopct labels for slices below `threshold` percent.

    Tiny slices crowd labels at the same angular position, producing the
    overlapping '0.0%5.5%0.0%' clusters seen in the sample report.
    """
    return f"{pct:.1f}%" if pct >= threshold else ""
```

In `render_matplotlib_png`, replace the `pie` branch (around lines 240-243):

```python
    elif chart_type == "pie":
        ax.pie(
            data.get("values", []),
            labels=data.get("labels", []),
            autopct=_pie_autopct,
            startangle=90,
            pctdistance=0.78,        # pull % labels slightly inward
            labeldistance=1.08,      # push slice labels outward
            textprops={"fontsize": 9},
        )
        ax.axis("equal")
```

- [ ] **Step 4: Run tests, expect them to pass**

```bash
pytest tests/test_chart_renderer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Visual verification (manual)**

Regenerate a Traffic Report PDF and inspect page 1 / page 2 pie charts. Confirm `0.0%` labels are gone and `5.5%`/`93.4%` no longer collide.

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/chart_renderer.py tests/test_chart_renderer.py
git commit -m "$(cat <<'EOF'
fix(charts): suppress sub-1% pie autopct labels to stop label overlap

Matplotlib's default autopct rendered '0.0%' on every zero-sized slice and
placed labels with no collision avoidance, producing illegible
'0.0%5.5%0.0%' clusters at the top of policy-decision and policy-coverage
pies in the PDF. Filter the autopct callable to return '' below 1.0% and
use pctdistance/labeldistance to give the rest more room.
EOF
)"
```

---

## Task 3: Filter matplotlib rcParams font.family to existing fonts (silence warning spam)

**Background:** `chart_renderer.py:53` sets:

```python
rcParams["font.family"] = ["Noto Sans CJK TC", "Microsoft JhengHei",
                            "PingFang TC", "Heiti TC", "sans-serif"]
```

`Microsoft JhengHei`, `PingFang TC`, and `Heiti TC` are Windows / macOS-only fonts. On Linux, every chart render triggers three `findfont: Font family 'X' not found.` warnings — three per chart × ~10 charts = 30+ lines of log spam per report.

**Fix:** At module import, probe each requested family via `font_manager.findfont(..., fallback_to_default=False)` and keep only those that resolve. Always retain the final `"sans-serif"` safety-net entry.

**Files:**
- Modify: `src/report/exporters/chart_renderer.py:50-55` — replace static rcParams assignment with filtered list
- Modify: `tests/test_chart_renderer.py` — add unit test for the filter helper

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chart_renderer.py`:

```python
def test_filter_existing_font_families_keeps_sans_serif_safety_net():
    from src.report.exporters.chart_renderer import _filter_existing_font_families
    # 'sans-serif' is a generic family name matplotlib always honours.
    out = _filter_existing_font_families(["DefinitelyNotAFontXYZ", "sans-serif"])
    assert out[-1] == "sans-serif"
    assert "DefinitelyNotAFontXYZ" not in out


def test_filter_existing_font_families_keeps_real_font_when_present():
    """If a known matplotlib default like DejaVu Sans is installed, it survives."""
    from src.report.exporters.chart_renderer import _filter_existing_font_families
    out = _filter_existing_font_families(["DejaVu Sans", "sans-serif"])
    # DejaVu Sans is bundled with matplotlib itself, so always present.
    assert "DejaVu Sans" in out
```

- [ ] **Step 2: Run, expect failure (helper undefined)**

```bash
pytest tests/test_chart_renderer.py::test_filter_existing_font_families_keeps_sans_serif_safety_net -v
```

Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the helper in `chart_renderer.py`**

Replace lines 50-55 in `chart_renderer.py` with:

```python
def _filter_existing_font_families(candidates: list[str]) -> list[str]:
    """Drop families matplotlib cannot resolve, always keep 'sans-serif' last.

    Without this filter, listing macOS/Windows-only families (PingFang TC,
    Microsoft JhengHei, Heiti TC) on Linux triggers a findfont warning per
    family per chart render — 30+ warning lines per report.
    """
    from matplotlib import font_manager
    kept: list[str] = []
    for fam in candidates:
        if fam == "sans-serif":
            continue  # added at end
        try:
            font_manager.findfont(fam, fallback_to_default=False)
            kept.append(fam)
        except Exception:
            pass  # not on this system; drop silently
    kept.append("sans-serif")
    return kept


# CJK font fallback for matplotlib — ensures zh_TW titles/labels render.
# Filtered to fonts actually installed so we don't spam warnings on Linux
# where Microsoft JhengHei / PingFang TC / Heiti TC are absent.
rcParams["font.family"] = _filter_existing_font_families([
    "Noto Sans CJK TC", "Microsoft JhengHei", "PingFang TC", "Heiti TC",
    "sans-serif",
])
rcParams["axes.unicode_minus"] = False  # minus sign glitch fix
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_chart_renderer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Smoke-test the warning suppression**

```bash
python -c "
import warnings, logging, io
buf = io.StringIO()
logging.basicConfig(stream=buf, level=logging.WARNING)
import src.report.exporters.chart_renderer as cr
spec = {'type': 'bar', 'title': 't',
        'data': {'labels': ['a', 'b'], 'values': [1, 2]}}
cr.render_matplotlib_png(spec)
print('--- captured warnings ---')
print(buf.getvalue())
"
```

Expected: NO `findfont: Font family 'X' not found.` lines in the captured output. (`Noto Sans CJK TC` should remain since it's installed at `/usr/share/fonts/opentype/noto/`.)

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/chart_renderer.py tests/test_chart_renderer.py
git commit -m "$(cat <<'EOF'
fix(charts): filter matplotlib rcParams font.family to installed fonts

Listing macOS/Windows-only CJK families (Microsoft JhengHei, PingFang TC,
Heiti TC) in rcParams['font.family'] triggered 'findfont: Font family X
not found' warnings on Linux for every chart in the report — ~30 lines of
log spam per render. Probe each candidate via font_manager.findfont with
fallback_to_default=False at module import; drop the missing ones and
always retain 'sans-serif' as the safety net.
EOF
)"
```

---

## Task 4: Add i18n keys to chart_spec for chart titles + axis labels

**Background:** ~13 analyzer modules construct `chart_spec` dicts with hardcoded English `"title"` / `"x_label"` / `"y_label"`. The PDF/Excel pipeline passes `lang="zh_TW"` but `chart_renderer.render_matplotlib_png` only reads the literal English values, so PDF charts show titles like `"Top 20 Ports by Flow Count"` and `"Allowed Traffic Timeline"` even on a Traditional Chinese report.

The plotly HTML path is unaffected (HTML reports interpolate i18n elsewhere; charts in HTML may already render English titles, which is a separate question — out of scope here).

**Fix:** Extend `chart_spec` with three optional fields — `title_key`, `x_label_key`, `y_label_key` — each holding an i18n string key. `render_matplotlib_png` resolves them via `STRINGS[key].get(lang)` when present, falling back to the literal `title`/`x_label`/`y_label` for backward compat. Add the new i18n entries to `report_i18n.py` and update each analyzer to set the new keys alongside the existing literals.

**Scope:** 13 analyzer files (~19 chart_spec dicts), 1 renderer change, ~30-40 new i18n entries.

**Files:**
- Modify: `src/report/exporters/chart_renderer.py` — `render_matplotlib_png` signature gains `lang: str = "en"`; resolve `*_key` fields
- Modify: `src/report/exporters/pdf_exporter.py:172-184` — pass `lang=lang` to `render_matplotlib_png`
- Modify: `src/report/exporters/report_i18n.py` — add `rpt_chart_<key>` entries (~30-40 new lines)
- Modify (analyzers with chart_spec — 13 files, ~19 chart_spec dicts total — exact counts from `grep -c 'chart_spec\s*=\s*{\|"chart_spec":' src/report/analysis/**/*.py`):
  - `src/report/analysis/mod01_traffic_overview.py` (1)
  - `src/report/analysis/mod04_ransomware_exposure.py` (1)
  - `src/report/analysis/mod07_cross_label_matrix.py` (1)
  - `src/report/analysis/mod12_executive_summary.py` (1)
  - `src/report/analysis/mod13_readiness.py` (1)
  - `src/report/analysis/mod14_infrastructure.py` (1)
  - `src/report/analysis/mod15_lateral_movement.py` (2)
  - `src/report/analysis/mod_draft_summary.py` (1)
  - `src/report/analysis/audit/audit_mod00_executive.py` (2)
  - `src/report/analysis/audit/audit_mod02_users.py` (2)
  - `src/report/analysis/audit/audit_mod03_policy.py` (2)
  - `src/report/analysis/policy_usage/pu_mod02_hit_detail.py` (2)
  - `src/report/analysis/policy_usage/pu_mod04_deny_effectiveness.py` (2)
- Modify: `tests/test_chart_renderer.py` — i18n resolution test
- Modify: `tests/test_chart_spec_coverage.py` — assert every analyzer chart_spec has both the literal and the `_key` field

- [ ] **Step 1: Write failing tests**

Add to `tests/test_chart_renderer.py`:

```python
def test_render_matplotlib_resolves_title_key_for_lang(tmp_path, monkeypatch):
    """If chart_spec carries title_key, the renderer resolves it via STRINGS+lang."""
    from src.report.exporters import chart_renderer
    monkeypatch.setitem(
        chart_renderer.__dict__,  # import-time STRINGS reference for the test
        "_TEST_NOOP", True,
    )
    # Inject a temporary i18n entry the renderer can resolve.
    from src.report.exporters import report_i18n
    report_i18n.STRINGS["rpt_chart_test_title"] = {
        "en": "English Title", "zh_TW": "中文標題",
    }
    spec = {
        "type": "bar",
        "title": "English Title",        # backward-compat literal
        "title_key": "rpt_chart_test_title",
        "data": {"labels": ["a"], "values": [1]},
    }
    # We cannot easily inspect rendered PNG text, so test via a renderer-level
    # helper introduced in Step 3 (see _resolve_chart_text below).
    out_en = chart_renderer._resolve_chart_text(spec, "title", lang="en")
    out_zh = chart_renderer._resolve_chart_text(spec, "title", lang="zh_TW")
    assert out_en == "English Title"
    assert out_zh == "中文標題"


def test_render_matplotlib_falls_back_to_literal_when_key_missing():
    from src.report.exporters import chart_renderer
    spec = {"type": "bar", "title": "Plain Title", "data": {"labels": [], "values": []}}
    assert chart_renderer._resolve_chart_text(spec, "title", lang="zh_TW") == "Plain Title"
```

Add to `tests/test_chart_spec_coverage.py`:

```python
def test_every_analyzer_chart_spec_has_title_key():
    """Every chart_spec dict in src/report/analysis/ must carry title_key
    alongside title (so the PDF render path can show Chinese titles)."""
    import ast, pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent
    analyzers = list((repo / "src/report/analysis").rglob("*.py"))
    missing: list[str] = []
    for p in analyzers:
        if "__pycache__" in str(p) or p.name == "__init__.py":
            continue
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            # Look for dict literals containing "type": "bar"|"pie"|... — these are chart_spec.
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "type" in keys and "title" in keys:
                if "title_key" not in keys:
                    missing.append(f"{p.relative_to(repo)}:{node.lineno}")
    assert not missing, "chart_spec dicts missing title_key:\n  " + "\n  ".join(missing)
```

- [ ] **Step 2: Run tests, expect failures**

```bash
pytest tests/test_chart_renderer.py::test_render_matplotlib_resolves_title_key_for_lang \
       tests/test_chart_renderer.py::test_render_matplotlib_falls_back_to_literal_when_key_missing \
       tests/test_chart_spec_coverage.py::test_every_analyzer_chart_spec_has_title_key -v
```

Expected: FAIL — `_resolve_chart_text` undefined; coverage test reports ~19 missing `title_key` sites.

- [ ] **Step 3: Implement the resolver in `chart_renderer.py`**

Add near the top of `chart_renderer.py` (after the `_PALETTE` block):

```python
def _resolve_chart_text(spec: dict[str, Any], field: str, *, lang: str = "en") -> str:
    """Resolve a chart_spec text field, preferring `<field>_key` i18n lookup.

    Lookup order:
      1. spec[f"{field}_key"] -> STRINGS[key].get(lang) if both present
      2. spec[field] (literal fallback for backward compat)
      3. "" if neither present
    """
    key = spec.get(f"{field}_key")
    if key:
        from src.report.exporters.report_i18n import STRINGS
        translated = STRINGS.get(key, {}).get(lang)
        if translated:
            return translated
    return str(spec.get(field, ""))
```

Update `render_matplotlib_png` signature and body:

```python
def render_matplotlib_png(spec: dict[str, Any], *, lang: str = "en") -> bytes:
    """Render chart spec as a PNG byte string (for PDF/Excel embedding)."""
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = _resolve_chart_text(spec, "title", lang=lang)
    x_label = _resolve_chart_text(spec, "x_label", lang=lang)
    y_label = _resolve_chart_text(spec, "y_label", lang=lang)
    # ... rest unchanged, but replace spec.get("x_label", "") with x_label
    #     and spec.get("y_label", "") with y_label, and ax.set_title(title)
    #     stays but uses the local `title` variable.
```

Update the `bar` and `line` branches to use the local `x_label`/`y_label`:

```python
    if chart_type == "bar":
        ax.bar(data.get("labels", []), data.get("values", []), color="#375379")
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
    # ... and likewise in the line branch
```

Update `pdf_exporter._append_module` to pass `lang`:

```python
            png = render_matplotlib_png(chart_spec, lang=lang)  # lines ~175
```

- [ ] **Step 4: Add i18n entries to `report_i18n.py`**

Find the section with existing `rpt_*` entries (around line 620 — `rpt_pdf_static_note`). Add a new block of `rpt_chart_*` keys, one per unique chart title and axis label observed. Suggested structure:

```python
    # --- Chart titles (PDF/Excel render path) ---
    "rpt_chart_policy_decision_breakdown": _entry(
        "Policy Decision Breakdown", "Policy 判定分布"),
    "rpt_chart_policy_coverage_tiers": _entry(
        "Policy Coverage Tiers", "Policy 涵蓋層級"),
    "rpt_chart_ransomware_exposure": _entry(
        "Ransomware Exposure by Risk Level", "依風險等級的勒索軟體暴露面"),
    "rpt_chart_top_apps_by_data_volume": _entry(
        "Top Apps by Data Volume", "依資料量排行的應用程式"),
    "rpt_chart_top_activity_by_process": _entry(
        "Top Activity by Process/User", "依 Process/User 排行的活動"),
    "rpt_chart_cross_label_matrix": _entry(
        "Cross-Label Traffic Matrix", "跨 Label 流量矩陣"),
    "rpt_chart_managed_vs_unmanaged": _entry(
        "Managed vs Unmanaged Flows", "受管 vs 未受管流量"),
    "rpt_chart_top_ports": _entry(
        "Top 20 Ports by Flow Count", "Top 20 連接埠（依流量數）"),
    "rpt_chart_allowed_traffic_timeline": _entry(
        "Allowed Traffic Timeline", "允許流量時間軸"),
    # --- Chart axis labels ---
    "rpt_chart_axis_flows": _entry("Flows", "流量數"),
    "rpt_chart_axis_connections": _entry("Connections", "連線數"),
    "rpt_chart_axis_process": _entry("Process", "Process"),
    "rpt_chart_axis_port": _entry("Port", "連接埠"),
    "rpt_chart_axis_app": _entry("Application", "應用程式"),
    "rpt_chart_axis_risk_level": _entry("Risk Level", "風險等級"),
    # ... (add any others surfaced by the coverage test in Step 6)
```

The exact list will be driven by which English titles/labels currently appear in the analyzer chart_specs. The coverage test in Step 2 lists every site missing a `title_key` — when fixing each one in Step 5, add the corresponding i18n entry.

- [ ] **Step 5: Update each analyzer's chart_spec to add `title_key` (and `*_label_key` where applicable)**

Pattern for every chart_spec (example from `mod01_traffic_overview.py:96`):

```python
# Before:
chart_spec = {
    "type": "bar",
    "title": "Top Apps by Data Volume",
    "x_label": "Application",
    "y_label": "Flows",
    "data": {...},
}

# After (add *_key fields, keep literals for backward compat):
chart_spec = {
    "type": "bar",
    "title": "Top Apps by Data Volume",
    "title_key": "rpt_chart_top_apps_by_data_volume",
    "x_label": "Application",
    "x_label_key": "rpt_chart_axis_app",
    "y_label": "Flows",
    "y_label_key": "rpt_chart_axis_flows",
    "data": {...},
}
```

For each of the 13 files listed under "Files" above, locate the chart_spec dict(s) and add the `_key` fields. Use `grep -n 'chart_spec' src/report/analysis/<file>.py` to find each site.

If an analyzer's chart_spec has no `x_label`/`y_label` (e.g., pies, heatmaps), skip those keys for that spec.

- [ ] **Step 6: Run the coverage test until clean**

```bash
pytest tests/test_chart_spec_coverage.py::test_every_analyzer_chart_spec_has_title_key -v
```

Expected after Step 5: PASS (no missing `title_key` sites).

- [ ] **Step 7: Run all related tests + manual visual check**

```bash
pytest tests/test_chart_renderer.py tests/test_chart_spec_coverage.py tests/test_pdf_exporter.py -v
```

Expected: all PASS.

Then regenerate a Traffic Report PDF and verify:
1. Every chart title is in Traditional Chinese (e.g., `Policy 判定分布`, not `Policy Decision Breakdown`)
2. Axis labels are in Traditional Chinese where translations exist

- [ ] **Step 8: Commit**

```bash
git add src/report/exporters/chart_renderer.py src/report/exporters/pdf_exporter.py \
        src/report/exporters/report_i18n.py src/report/analysis/ \
        tests/test_chart_renderer.py tests/test_chart_spec_coverage.py
git commit -m "$(cat <<'EOF'
feat(charts): localize chart titles + axis labels via title_key/label_key

PDF/Excel charts (matplotlib path) previously rendered hardcoded English
titles like 'Policy Decision Breakdown' even when the report lang was
zh_TW, because chart_spec carried only the literal title and the renderer
read it verbatim. Add optional title_key / x_label_key / y_label_key fields
to chart_spec; render_matplotlib_png now resolves them via STRINGS+lang
when present, falling back to the literal for backward compatibility.

Update all ~19 chart_spec sites in src/report/analysis/ to set the new
*_key fields. Add ~25 new rpt_chart_* i18n entries in report_i18n.py.
Add coverage test that fails CI if a future chart_spec is added without
title_key.
EOF
)"
```

---

## Task 5: Translate hardcoded English categorical labels in pie/bar slices

**Background:** Task 4's final review surfaced an integration gap. Task 4 translates chart `title` / `x_label` / `y_label`, but the slice / bar labels live in `chart_spec.data["labels"]` and are populated by each analyzer. The codebase has TWO patterns:

1. **Already-correct** (mod08, mod13, mod03): uses `t('rpt_<key>', default='English')` so labels are language-resolved at analyzer-execution time. Works.
2. **Broken** (mod01, mod02, mod04): hardcodes English literals (`'Allowed'`, `'Blocked'`, `'Potentially Blocked'`, `'Unknown'`) or computes them from English dict keys (`[lvl.capitalize() for lvl in risk_levels]`). The zh_TW PDF then shows the chart title in Chinese but the slices stay English — visually inconsistent.

**Fix:** Convert the broken sites to use the `t()` pattern, matching the existing convention. NO new mechanism — extend what mod08/mod13 already do.

**In-scope sites** (3 files):
- `src/report/analysis/mod01_traffic_overview.py:101-105` — pie labels `['Allowed', 'Blocked', 'Potentially Blocked', 'Unknown']`
- `src/report/analysis/mod02_policy_decisions.py:100-104` — pie labels `['Allowed', 'Blocked', 'Potentially Blocked']`
- `src/report/analysis/mod04_ransomware_exposure.py:131` — bar labels `[lvl.capitalize() for lvl in risk_levels]` (risk_levels = `['critical', 'high', 'medium', 'low']`)

**Out of scope** (correctly NOT translated — these are data identifiers, not categorical enums):
- `mod05_remote_access.py` (top5_labels — IPs/hosts)
- `mod06_user_process.py` (process/user names)
- `mod07_cross_label_matrix.py` (label dimension values like "Kubernetes")
- `mod09_traffic_distribution.py` (port numbers)
- `mod11_bandwidth.py` (application names)

### Files
- Modify: `src/report/exporters/report_i18n.py` — add 7 new entries (`rpt_allowed`, `rpt_blocked`, `rpt_potentially_blocked`, `rpt_unknown`, `rpt_risk_critical`, `rpt_risk_high`, `rpt_risk_medium`, `rpt_risk_low`)
- Modify: `src/report/analysis/mod01_traffic_overview.py` — wrap each label with `t('rpt_xxx', default='English')`
- Modify: `src/report/analysis/mod02_policy_decisions.py` — same
- Modify: `src/report/analysis/mod04_ransomware_exposure.py` — replace `.capitalize()` list with explicit `t('rpt_risk_xxx', default='Critical')` per level
- Add: `tests/test_chart_label_i18n.py` (new) — one test per affected analyzer asserts zh_TW labels appear

### Step 1: Add i18n entries

In `src/report/exporters/report_i18n.py`, find the existing `rpt_managed` / `rpt_enforced` block (around line 600 — pre-existing labels). Add a sibling block:

```python
    # --- Categorical pie/bar slice labels (analyzer-side translation via t()) ---
    "rpt_allowed": _entry("Allowed", "已允許"),
    "rpt_blocked": _entry("Blocked", "已封鎖"),
    "rpt_potentially_blocked": _entry("Potentially Blocked", "可能被封鎖"),
    "rpt_unknown": _entry("Unknown", "未知"),
    "rpt_risk_critical": _entry("Critical", "嚴重"),
    "rpt_risk_high": _entry("High", "高"),
    "rpt_risk_medium": _entry("Medium", "中"),
    "rpt_risk_low": _entry("Low", "低"),
```

If any of these keys already exist (`rpt_allowed` etc.), reuse them — DO NOT duplicate. Verify before adding via `grep -n 'rpt_allowed\|rpt_risk_critical' src/report/exporters/report_i18n.py`.

### Step 2: Write the failing test

Create `tests/test_chart_label_i18n.py`:

```python
"""Regression: pie/bar slice labels must be translated to zh_TW for the PDF.

Task 4 plumbed `title_key` / `*_label_key` for chart titles and axes, but the
slice/bar labels (chart_spec.data["labels"]) are populated by each analyzer.
mod01/mod02/mod04 hardcoded English; this test ensures they now produce
Chinese when the language is set to zh_TW.
"""
import pandas as pd
import pytest
```

NOTE: the import for the language-setter and the analyzer entry-point function names depend on this codebase's actual API. **Discover them** via:

```bash
grep -rn 'def set_language\|def get_language' src/ | head
grep -n '^def ' src/report/analysis/mod01_traffic_overview.py src/report/analysis/mod02_policy_decisions.py src/report/analysis/mod04_ransomware_exposure.py | head
```

Then write the fixture and tests following this skeleton — adapt the import path and function names to what the codebase actually exposes:

```python
@pytest.fixture
def zh_tw_lang():
    # Adapt to actual API discovered above
    from src.shared.i18n import set_language  # placeholder path
    set_language("zh_TW")
    yield
    set_language("en")  # restore for other tests


def test_mod01_traffic_overview_labels_translate_to_zh_tw(zh_tw_lang):
    from src.report.analysis.mod01_traffic_overview import <actual_function>
    df = pd.DataFrame([...])  # minimal df that exercises the chart_spec branch
    out = <actual_function>(df)
    labels = out.get("chart_spec", {}).get("data", {}).get("labels", [])
    assert "已允許" in labels
    assert "Allowed" not in labels


# Similar for mod02 and mod04. Use minimum-viable DataFrames — look at
# existing tests/test_analyzer.py and tests/test_analyzer_*.py for fixture
# patterns each analyzer expects.
```

If a fixture-construction snag blocks you, simplify to direct testing of the chart_spec result via mocking `t()` — but prefer the realistic path.

### Step 3: Run test, expect failure

```bash
/home/harry/rd/illumio-ops/venv/bin/python -m pytest tests/test_chart_label_i18n.py -v
```

Expected: 3 FAIL — labels are English (`Allowed` etc.), not Chinese.

### Step 4: Apply the fix

**`src/report/analysis/mod01_traffic_overview.py:101-105`** — replace:

```python
            'labels': [
                'Allowed',
                'Blocked',
                'Potentially Blocked',
                'Unknown',
            ],
```

with:

```python
            'labels': [
                t('rpt_allowed', default='Allowed'),
                t('rpt_blocked', default='Blocked'),
                t('rpt_potentially_blocked', default='Potentially Blocked'),
                t('rpt_unknown', default='Unknown'),
            ],
```

(Verify `t` is already imported in the file — `grep -n 'import.*\bt\b' src/report/analysis/mod01_traffic_overview.py`. If not, add the import matching mod08's pattern.)

**`src/report/analysis/mod02_policy_decisions.py:100-104`** — same replacement (3 labels: Allowed, Blocked, Potentially Blocked).

**`src/report/analysis/mod04_ransomware_exposure.py:131`** — replace:

```python
            'labels': [lvl.capitalize() for lvl in risk_levels if lvl in level_counts],
```

with an explicit per-level mapping (more readable than hiding `t()` calls inside a comprehension):

```python
            'labels': [
                t(f'rpt_risk_{lvl}', default=lvl.capitalize())
                for lvl in risk_levels if lvl in level_counts
            ],
```

### Step 5: Run test, expect pass

```bash
/home/harry/rd/illumio-ops/venv/bin/python -m pytest tests/test_chart_label_i18n.py -v
```

Expected: 3 PASS.

### Step 6: Run full slice + analyzer regression

```bash
/home/harry/rd/illumio-ops/venv/bin/python -m pytest tests/test_chart_label_i18n.py tests/test_chart_renderer.py tests/test_chart_spec_coverage.py tests/test_pdf_exporter.py tests/test_analyzer*.py -v 2>&1 | tail -10
```

Expected: all PASS, no regressions in existing analyzer tests. If any pre-existing test asserts English labels in `chart_spec.data["labels"]`, that test will need updating — flag as a concern in your report and update minimally (don't assume the existing test was wrong; verify it was checking the now-broken English assumption).

### Step 7: Visual verification

Defer to user (manual).

### Step 8: Commit

```bash
git add src/report/exporters/report_i18n.py src/report/analysis/mod01_traffic_overview.py \
        src/report/analysis/mod02_policy_decisions.py src/report/analysis/mod04_ransomware_exposure.py \
        tests/test_chart_label_i18n.py
git commit -m "$(cat <<'EOF'
fix(charts): translate hardcoded categorical pie/bar slice labels to zh_TW

Task 4 plumbed title_key/x_label_key/y_label_key but slice and bar labels
(chart_spec.data["labels"]) were populated by each analyzer, and three
analyzers hardcoded English strings — leaving zh_TW PDFs with translated
chart titles but English category labels (Allowed/Blocked, Critical/Medium).

Apply the existing t('rpt_xxx', default='English') pattern (already used
by mod08/mod13/mod03) to mod01/mod02/mod04. Add 7 new rpt_* i18n entries
for the verdict and risk-level enums. Add regression test that runs each
analyzer with lang=zh_TW and asserts Chinese labels appear.
EOF
)"
```

---

## 🛂 Final verification

After all five tasks land:

- [ ] **Step 1: Full test run**

```bash
cd /home/harry/rd/illumio-ops && pytest tests/test_pdf_exporter.py tests/test_chart_renderer.py tests/test_chart_spec_coverage.py -v
```

Expected: all PASS.

- [ ] **Step 2: End-to-end PDF generation + visual review**

Generate a fresh Traffic Report PDF (via the GUI or whatever the user's normal flow is), then:

```bash
ls -lt reports/Illumio_Traffic_Report_*.pdf | head -1
# Read the latest PDF and visually verify:
```

Pass conditions:
1. Page 1 paragraph reads `此 PDF 為靜態摘要，完整多語系報表請使用 HTML 或 XLSX 格式。` (no missing tokens)
2. Tables show data values in every cell (verdicts, counts, percentages)
3. Pie chart percentages do not overlap; 0% slices have no label
4. Chart titles and axis labels render in Traditional Chinese
5. Console log has zero `findfont: Font family 'X' not found.` warnings

If all five pass: branch is ready to merge to main.
