"""
src/report/exporters/report_css.py
Shared CSS/JS foundation for HTML report exporters.
"""

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Montserrat:wght@400;500;600;700&'
    'family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">'
)

BASE_CSS = """\
  :root {
    --cyan-120:#1A2C32; --cyan-110:#24393F; --cyan-100:#2D454C; --cyan-90:#325158;
    --orange:#FF5500; --gold:#FFA22F; --gold-110:#F97607;
    --green:#166644; --green-80:#299B65; --green-10:#D1FAE5;
    --red:#BE122F; --red-80:#F43F51; --red-10:#FEE2E2;
    --slate:#313638; --slate-10:#EAEBEB; --slate-20:#D6D7D7; --slate-50:#989A9B;
    --tan:#F7F4EE; --tan-120:#E3D8C5; --border:#D6D7D7;
    --font-mono: 'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
    --shadow-card: 0 1px 4px rgba(0,0,0,.08);
    --shadow-panel: 0 6px 18px rgba(26,44,50,.07);
    --shadow-panel-strong: 0 10px 24px rgba(26,44,50,.10);
    --radius-panel: 10px;
    --radius-compact: 8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Montserrat', -apple-system, sans-serif; background: var(--tan); color: var(--slate); }
  nav { position: fixed; top: 0; left: 0; width: 210px; height: 100vh; background: var(--cyan-120); overflow-y: auto; padding: 60px 0 20px; z-index: 100; }
  nav a { display: block; color: var(--slate-20); text-decoration: none; padding: 7px 16px; font-size: 12px; border-left: 3px solid transparent; }
  nav a:hover, nav a.active { background: var(--cyan-100); border-left-color: var(--orange); color: #fff; }
  main { margin-left: 210px; padding: 24px; container-type: inline-size; container-name: main; }
  h1 { color: var(--orange); font-size: 22px; font-weight: 700; margin-bottom: 4px; }
  h2 { color: var(--cyan-120); font-size: 16px; font-weight: 600; margin: 24px 0 10px; border-bottom: 2px solid var(--orange); padding-bottom: 6px; }
  h3 { color: var(--slate); font-size: 13px; font-weight: 600; margin: 16px 0 8px; }
  h4 { color: var(--slate-50); font-size: 12px; font-weight: 600; margin: 12px 0 6px; text-transform: uppercase; letter-spacing: .04em; }

  .card { background: #fff; border-radius: 8px; padding: 24px 28px; box-shadow: var(--shadow-card); margin-bottom: 24px; color: var(--slate); container-type: inline-size; }
  .note { background: var(--tan); border-left: 4px solid var(--orange); padding: 12px 14px; border-radius: 4px; color: var(--cyan-120); font-size: 13px; margin: 12px 0; line-height: 1.6; }
  .note-warn { border-left-color: var(--red-80); background: var(--red-10); }
  footer { text-align: center; color: var(--slate-50); font-size: 11px; margin: 40px 0 20px; }

  .report-hero { position: relative; overflow: hidden; background:
    radial-gradient(circle at top right, rgba(255,162,47,.16), transparent 24rem),
    linear-gradient(135deg, #FFFFFF, #F7F4EE 62%, #F2EEE6); color: var(--slate); border: 1px solid rgba(50,81,88,.10); box-shadow: 0 10px 30px rgba(26,44,50,.10); }
  .report-hero h1 { color: var(--cyan-120); font-size: 30px; margin-bottom: 8px; }
  .report-hero h2 { color: var(--cyan-120); border-bottom-color: rgba(255,85,0,.24); }
  .report-subtitle { color: var(--slate-50); font-size: 13px; margin-bottom: 14px; }
  .report-kicker { display: inline-block; padding: 7px 12px; margin-bottom: 12px; border-radius: 999px; background: rgba(45,69,76,.08); color: var(--cyan-120); font-size: 10px; letter-spacing: .12em; text-transform: uppercase; font-weight: 700; }
  .summary-pill-row { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
  .summary-pill { min-width: 140px; padding: 12px 14px; border-radius: 14px; background: rgba(255,255,255,.92); border: 1px solid rgba(50,81,88,.10); box-shadow: 0 6px 14px rgba(26,44,50,.06); }
  .summary-pill-label { display: block; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--slate-50); margin-bottom: 4px; }
  .summary-pill-value { display: block; font-size: 15px; font-weight: 700; color: var(--cyan-120); font-variant-numeric: tabular-nums; }
  .section-intro { margin: 0 0 14px; color: var(--slate-50); font-size: 12px; line-height: 1.6; }

  .kpi-grid { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 24px; }
  .kpi-card { background: #fff; border-radius: 8px; padding: 14px 18px; box-shadow: var(--shadow-card); min-width: 150px; flex: 1 1 150px; max-width: 220px; border-top: 3px solid var(--orange); }
  .kpi-label { font-size: 11px; color: var(--slate-50); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 4px; }
  .kpi-value { font-size: 20px; font-weight: 700; color: var(--cyan-120); font-variant-numeric: tabular-nums; }
  .report-hero .kpi-card { background: #fff; box-shadow: 0 6px 16px rgba(26,44,50,.08); border-top-color: var(--orange); }

  /* Tables ------------------------------------------------------- */
  /* width: max-content makes the panel shrink to the natural width of its
     table. Narrow tables (e.g. 3-col Top Ports) now show as a tight panel
     with empty space OUTSIDE the panel (in the section card), rather than
     a full-width panel with a half-filled table and dead space inside. */
  .report-table-panel { position: relative; margin: 12px 0 18px; border: 1px solid rgba(50,81,88,.14); border-radius: var(--radius-panel); overflow: hidden; background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(247,244,238,.92)); box-shadow: var(--shadow-panel-strong); width: max-content; max-width: 100%; }
  /* Wide panels (sticky first col) need full container width so the sticky
     column is visually anchored. */
  .report-table-panel--wide { width: auto; }
  .report-table-panel--compact { min-width: min(280px, 100%); }
  .dual-grid .report-table-panel--compact { max-width: 100%; }
  .dual-grid .report-table-panel { box-shadow: var(--shadow-panel); border-radius: var(--radius-compact); }

  .report-table-wrap { position: relative; overflow: auto; max-width: 100%; }
  /* min-width starts at 100% for tables that haven't been auto-fitted yet
     (initial paint before JS runs). After fit, JS sets inline width/minWidth
     directly and this CSS default is overridden. */
  .report-table { min-width: 100%; table-layout: auto; border-collapse: collapse; font-size: 12px; }
  .report-table[data-auto-fitted="true"] { table-layout: fixed; min-width: 0; }
  .report-table-panel--compact .report-table { min-width: 100%; }
  .report-table-panel--compact .report-table[data-auto-fitted="true"] { min-width: 0; }

  .report-table thead th { background: var(--cyan-110); color: #fff; position: sticky; top: 0; z-index: 2; padding: 10px 28px 10px 12px; vertical-align: middle; border-right: 1px solid rgba(255,255,255,.18); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; letter-spacing: .01em; }
  .report-table thead th:hover { background: var(--cyan-100); }
  .report-table thead th:last-child { border-right: none; }
  .report-table tbody td { padding: 8px 12px; vertical-align: top; border-bottom: 1px solid var(--slate-20); color: var(--slate); line-height: 1.5; font-variant-numeric: tabular-nums; }
  .report-table tbody td, .report-table tbody td * { color: var(--slate); }
  .report-table tbody td code { color: var(--cyan-120); background: rgba(26,44,50,.06); padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px; }
  .report-table tbody tr:nth-child(even) td { background: var(--tan); }
  .report-table tbody tr:hover td { background: var(--tan-120); transition: background .12s ease; }

  /* .th-label sits inside th's content-box. The 28px right-padding on th
     already reserves room for the absolutely-positioned .sort-indicator — no
     additional padding needed here, or the label double-pads and truncates. */
  .th-label { display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .report-table--interactive thead th { cursor: pointer; user-select: none; }
  .sort-indicator { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-size: 11px; opacity: .55; pointer-events: none; transition: opacity .12s ease; }
  .report-table thead th:hover .sort-indicator { opacity: .85; }
  /* Resizer: wider hit area (11px), with an always-visible 1px center line
     so users can see where to grab. Brightens to orange on hover / drag. */
  .col-resizer { position: absolute; top: 0; right: -5px; width: 11px; height: 100%; cursor: col-resize; background: transparent; z-index: 3; }
  .col-resizer::before {
    content: "";
    position: absolute; top: 22%; bottom: 22%; left: 50%;
    width: 1px; background: rgba(255,255,255,.32);
    transform: translateX(-.5px);
    transition: background .15s ease, top .15s ease, bottom .15s ease;
  }
  .report-table thead th:hover .col-resizer::before { background: rgba(255,255,255,.55); top: 12%; bottom: 12%; }
  .col-resizer:hover::before, .col-resizer.is-active::before { background: var(--gold); top: 0; bottom: 0; width: 2px; transform: translateX(-1px); }
  .col-resizer:hover, .col-resizer.is-active { background: linear-gradient(180deg, rgba(255,162,47,0), rgba(255,85,0,.18), rgba(255,162,47,0)); }
  .report-table thead th.is-sorted-asc, .report-table thead th.is-sorted-desc { background: linear-gradient(180deg, var(--cyan-100), var(--cyan-120)); }
  .report-table thead th.is-sorted-asc .sort-indicator, .report-table thead th.is-sorted-desc .sort-indicator { opacity: 1; color: var(--gold); }
  .report-table-wrap::-webkit-scrollbar { height: 10px; width: 10px; }
  .report-table-wrap::-webkit-scrollbar-thumb { background: rgba(50,81,88,.22); border-radius: 999px; border: 2px solid transparent; background-clip: padding-box; }
  .report-table-wrap::-webkit-scrollbar-thumb:hover { background: rgba(50,81,88,.34); background-clip: padding-box; border: 2px solid transparent; }

  /* Wide table: sticky first col + right scroll affordance */
  .report-table-panel--wide .report-table thead th:first-child,
  .report-table-panel--wide .report-table tbody td:first-child {
    position: sticky; left: 0; z-index: 2;
    box-shadow: 6px 0 8px -6px rgba(26,44,50,.18);
  }
  .report-table-panel--wide .report-table thead th:first-child { z-index: 3; background: var(--cyan-110); }
  .report-table-panel--wide .report-table tbody td:first-child { background: #FFFFFF; color: var(--cyan-120); font-weight: 600; }
  .report-table-panel--wide .report-table tbody tr:nth-child(even) td:first-child { background: var(--tan); }
  .report-table-panel--wide .report-table tbody tr:hover td:first-child { background: var(--tan-120); }
  .report-table-panel--wide::after {
    content: ""; position: absolute; top: 0; right: 0; bottom: 0; width: 28px;
    pointer-events: none;
    background: linear-gradient(90deg, rgba(247,244,238,0), rgba(247,244,238,.96));
    opacity: 0; transition: opacity .18s ease;
    z-index: 4;
  }
  .report-table-panel--wide[data-scroll-state="scrollable"]::after,
  .report-table-panel--wide[data-scroll-state="start"]::after { opacity: 1; }
  .report-table-panel--wide[data-scroll-state="end"]::after { opacity: 0; }

  /* Empty data state */
  .report-table-panel--empty { padding: 28px 22px; border-style: dashed; border-color: var(--slate-20); background: rgba(255,255,255,.6); box-shadow: none; text-align: center; color: var(--slate-50); font-size: 12px; }
  .report-table-panel--empty .empty-marker { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--slate-20); margin-right: 8px; vertical-align: middle; }
  .report-table-panel--empty .empty-text { font-style: italic; letter-spacing: .02em; }

  .coverage-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
  .cov-stat { background: #fff; border-radius: 6px; padding: 10px 16px; border: 1px solid var(--slate-20); min-width: 140px; }
  .cov-stat .cov-label { font-size: 11px; color: var(--slate-50); text-transform: uppercase; letter-spacing: .04em; }
  .cov-stat .cov-value { font-size: 18px; font-weight: 700; color: var(--cyan-120); font-variant-numeric: tabular-nums; }
  .progress-bar { background: var(--slate-20); border-radius: 4px; height: 8px; margin: 6px 0 14px; }
  .progress-fill { height: 100%; border-radius: 4px; background: var(--orange); }

  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; color: #fff; letter-spacing: .02em; }
  .badge-CRITICAL { background: var(--red); }
  .badge-HIGH { background: var(--red-80); }
  .badge-MEDIUM { background: var(--gold-110); }
  .badge-LOW { background: var(--green); }
  .badge-INFO { background: var(--cyan-100); }

  .dual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: start; margin: 12px 0 18px; }
  .dual-grid > div { min-width: 0; }
  .dual-grid > div > h4:first-child { margin-top: 0; }
  .dual-grid .report-table-panel { margin: 8px 0 0; }
  .dual-grid .note { margin: 8px 0 0; padding: 16px 14px; border-radius: 8px; }
  @media (max-width: 1100px) { .dual-grid { grid-template-columns: 1fr; } }
  @container main (max-width: 880px) { .dual-grid { grid-template-columns: 1fr; } }

  .attention-box { position: relative; background: linear-gradient(180deg, #FFFFFF, var(--tan)); border: 1px solid var(--tan-120); border-radius: var(--radius-compact); padding: 16px 18px; margin: 12px 0 18px; box-shadow: var(--shadow-panel); }
  .attention-box h4 { margin: 0 0 10px; color: var(--cyan-120); }
  .attention-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 7px 0; border-bottom: 1px solid rgba(50,81,88,.06); font-size: 12px; }
  .attention-row:last-child { border-bottom: none; }
  .attention-row > span:first-child { color: var(--slate); font-weight: 500; }
  .badge-hit      { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: var(--green-10); color: var(--green); font-variant-numeric: tabular-nums; }
  .badge-unused   { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: var(--red-10);   color: var(--red);   font-variant-numeric: tabular-nums; }
  .badge-synced   { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: var(--green-10); color: var(--green); }
  .badge-staged   { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: rgba(255,162,47,.16); color: var(--gold-110); }
  .badge-unsynced { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: var(--red-10);   color: var(--red); }
  .caveat-box { background: #FFFBF0; border-left: 4px solid var(--gold-110); padding: 12px 14px; border-radius: 4px; margin: 12px 0; font-size: 12px; line-height: 1.6; }

  /* Trend chips (replaces inline-styled trend table) */
  .trend-chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 7px; border-radius: 999px; font-family: var(--font-mono); font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .trend-chip--up   { background: rgba(190,18,47,.10);  color: var(--red); }
  .trend-chip--down { background: rgba(22,102,68,.10);  color: var(--green); }
  .trend-chip--flat { background: rgba(50,81,88,.08);   color: var(--slate-50); }
  .trend-chip--good-up   { background: rgba(22,102,68,.10); color: var(--green); }
  .trend-chip--good-down { background: rgba(190,18,47,.10); color: var(--red); }
  .trend-arrow { font-weight: 700; line-height: 1; }
  .trend-empty-note { display: flex; align-items: center; gap: 8px; margin: 10px 0 16px; padding: 10px 14px; border: 1px dashed var(--slate-20); border-radius: 8px; background: rgba(255,255,255,.5); color: var(--slate-50); font-size: 12px; font-style: italic; }
  .trend-empty-note .trend-empty-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--gold); display: inline-block; }

  .mono, .report-table tbody td.mono { font-family: var(--font-mono); font-size: 11px; }

  @media print {
    nav { display: none; }
    main { margin-left: 0; padding: 12px; }
    .card { box-shadow: none; border: 1px solid var(--slate-20); page-break-inside: avoid; }
    .report-table-panel { box-shadow: none; }
    .report-table-panel--wide::after { display: none; }
    .report-table-panel--wide .report-table thead th:first-child,
    .report-table-panel--wide .report-table tbody td:first-child { position: static; box-shadow: none; }
  }
"""

TRAFFIC_CSS = """\
  .finding-card { border: 1px solid var(--slate-20); border-radius: 8px; padding: 16px; margin-bottom: 16px; background: #fff; }
  .finding-card.sev-CRITICAL { border-left: 5px solid var(--red); }
  .finding-card.sev-HIGH { border-left: 5px solid var(--red-80); }
  .finding-card.sev-MEDIUM { border-left: 5px solid var(--gold-110); }
  .finding-card.sev-LOW { border-left: 5px solid var(--green); }
  .finding-card.sev-INFO { border-left: 5px solid var(--cyan-100); }
  .finding-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .finding-title { font-weight: 600; font-size: 14px; color: var(--cyan-120); }
  .finding-rule-id { font-size: 11px; color: var(--slate-50); font-family: var(--font-mono); background: var(--slate-10); padding: 2px 6px; border-radius: 3px; }
  .finding-desc { font-size: 13px; margin-bottom: 10px; color: var(--slate); line-height: 1.5; }
  .finding-evidence { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .ev-pill { background: var(--tan); border: 1px solid var(--tan-120); border-radius: 4px; padding: 4px 10px; font-size: 12px; font-variant-numeric: tabular-nums; }
  .ev-pill span.ev-label { color: var(--slate-50); font-size: 10px; display: block; text-transform: uppercase; letter-spacing: .04em; }
  .ev-pill b { color: var(--cyan-110); }
  .finding-rec { background: var(--tan); border-left: 3px solid var(--orange); padding: 10px 12px; border-radius: 4px; font-size: 12px; color: var(--cyan-120); line-height: 1.6; }
"""

AUDIT_CSS = """\
  td { word-break: break-all; }
  .bp-box { margin: 12px 0; padding: 12px 14px; border-left: 4px solid var(--orange); border-radius: 6px; background: linear-gradient(180deg, #FFFDF8, #F7F4EE); color: var(--cyan-120); line-height: 1.7; font-size: 12px; }
  .bp-box b { color: var(--cyan-120); }
  .report-hero + .card .report-table-panel,
  .card .report-table-panel { box-shadow: var(--shadow-panel); }
"""

VEN_CSS = """\
  td { word-break: break-all; }
"""

POLICY_USAGE_CSS = """\
  td { word-break: break-word; }
"""

def build_css(exporter_type: str) -> str:
    extra = {
        "traffic": TRAFFIC_CSS,
        "audit": AUDIT_CSS,
        "ven": VEN_CSS,
        "policy_usage": POLICY_USAGE_CSS,
    }.get(exporter_type, "")
    return f"{FONT_LINK}\n<style>\n{BASE_CSS}\n{extra}\n</style>\n"

TABLE_JS = r"""
<script>
function normalizeCellValue(text) {
  return (text || '').replace(/[\s\u00A0]+/g, ' ').trim();
}

function parseSortableValue(text) {
  const normalized = normalizeCellValue(text);
  const numeric = normalized.replace(/,/g, '').match(/^-?\d+(\.\d+)?$/);
  if (numeric) return { type: 'number', value: parseFloat(numeric[0]) };
  return { type: 'text', value: normalized.toLowerCase() };
}

function sortTable(table, col) {
  const body = table.tBodies[0];
  if (!body) return;
  const rows = Array.from(body.rows);
  const asc = !(table.dataset.sortCol === String(col) && table.dataset.sortDir === 'asc');
  rows.sort((a, b) => {
    const av = parseSortableValue(a.cells[col] ? a.cells[col].innerText : '');
    const bv = parseSortableValue(b.cells[col] ? b.cells[col].innerText : '');
    if (av.type === 'number' && bv.type === 'number') {
      return asc ? av.value - bv.value : bv.value - av.value;
    }
    return asc ? av.value.localeCompare(bv.value) : bv.value.localeCompare(av.value);
  });
  rows.forEach(row => body.appendChild(row));
  table.dataset.sortCol = String(col);
  table.dataset.sortDir = asc ? 'asc' : 'desc';
  table.querySelectorAll('th').forEach((th, index) => {
    th.classList.toggle('is-sorted-asc', index === col && asc);
    th.classList.toggle('is-sorted-desc', index === col && !asc);
    const indicator = th.querySelector('.sort-indicator');
    if (indicator) indicator.textContent = index === col ? (asc ? '\u25B2' : '\u25BC') : '\u2195';
  });
}

/* Auto-fit: measure natural content widths and distribute slack space.
 * Columns are categorised so narrow-value columns (Proto, Yes/No, short enums)
 * don't absorb slack that belongs to long-text columns. */
function measureColumnWidths(table) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  const body = table.tBodies[0];
  const rows = body ? Array.from(body.rows) : [];
  const nCols = headers.length;
  const MIN_COL = 56;
  /* The th's asymmetric padding (12px left / 28px right) already includes the
     space the absolutely-positioned .sort-indicator occupies, so there's no
     additional reserve to add here — adding one causes the label to
     double-count and ellipsis-truncate short CJK headers like 連接埠. */
  const NARROW_MAX_CHARS = 10;       /* content wider than this = "text" not "narrow" */
  const NARROW_DISTINCT_CAP = 6;     /* column with ≤ this many distinct values = enum-like */

  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font:inherit;padding:0;left:-9999px;top:0';
  document.body.appendChild(probe);

  const naturalWidths = new Array(nCols).fill(MIN_COL);
  const headerWidths = new Array(nCols).fill(MIN_COL);
  const isNumeric = new Array(nCols).fill(true);
  const maxCellChars = new Array(nCols).fill(0);
  const distinctVals = Array.from({ length: nCols }, () => new Set());

  headers.forEach((th, i) => {
    const label = th.querySelector('.th-label');
    const thStyle = getComputedStyle(th);
    /* Read padding live so we don't drift if CSS changes. Add a small
       safety buffer so sub-pixel font rendering doesn't ellipsis-truncate
       on exact-fit widths (observed 2-3px short on some CJK labels). */
    const padHead = (parseFloat(thStyle.paddingLeft) || 0)
                  + (parseFloat(thStyle.paddingRight) || 0)
                  + 6;
    probe.style.font = thStyle.font;
    probe.textContent = (label || th).textContent;
    const hw = probe.offsetWidth + padHead;
    headerWidths[i] = hw;
    naturalWidths[i] = Math.max(naturalWidths[i], hw);
  });

  const sampleRows = rows.slice(0, 30);
  sampleRows.forEach(row => {
    Array.from(row.cells).forEach((td, i) => {
      if (i >= nCols) return;
      const tdStyle = getComputedStyle(td);
      const padCell = (parseFloat(tdStyle.paddingLeft) || 0)
                    + (parseFloat(tdStyle.paddingRight) || 0);
      probe.style.font = tdStyle.font;
      probe.textContent = td.textContent;
      naturalWidths[i] = Math.max(naturalWidths[i], probe.offsetWidth + padCell);
      const v = normalizeCellValue(td.textContent);
      if (v.length > maxCellChars[i]) maxCellChars[i] = v.length;
      if (v) distinctVals[i].add(v);
      if (isNumeric[i]) {
        if (v && !(/^-?[\d,]+(\.\d+)?%?$/.test(v))) isNumeric[i] = false;
      }
    });
  });
  probe.remove();

  /* Column categories:
   *   numeric       — pure numbers/percentages, stay tight, no slack
   *   narrow-value  — short text, few distinct values (Proto, Yes/No, enums), no slack
   *   text          — long or varied text content, absorbs slack proportionally
   */
  const category = naturalWidths.map((_, i) => {
    if (isNumeric[i]) return 'numeric';
    const short = maxCellChars[i] <= NARROW_MAX_CHARS;
    const fewDistinct = distinctVals[i].size > 0 && distinctVals[i].size <= NARROW_DISTINCT_CAP;
    if (short && fewDistinct) return 'narrow';
    return 'text';
  });

  return { widths: naturalWidths, headerWidths, category };
}

function autoFitColumns(table) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  const nCols = headers.length;
  if (nCols < 1) return;

  const wrap = table.closest('.report-table-wrap');
  const panel = table.closest('.report-table-panel');
  const isWide = panel && panel.classList.contains('report-table-panel--wide');

  if (table.dataset.autoFitted === 'true') {
    table.style.minWidth = '';
    headers.forEach((th, i) => { th.style.width = ''; if (cols[i]) cols[i].style.width = ''; });
  }

  const { widths, category } = measureColumnWidths(table);
  const containerWidth = wrap ? wrap.clientWidth : table.parentElement.clientWidth;
  const naturalTotal = widths.reduce((a, b) => a + b, 0);

  let finalWidths;
  let tableMinWidth;
  if (!isWide && naturalTotal <= containerWidth) {
    const slack = containerWidth - naturalTotal;
    /* Distribute slack:
       - If there are 'text' columns (long/varied content): split slack among
         them proportionally. Narrow and numeric cols stay at natural width.
       - If there are no text columns: keep all columns at natural width. The
         panel itself is `width: max-content`, so the narrow table gets a
         tight panel and the empty space lives OUTSIDE the panel (in the card
         background), not inside as bloated column padding. */
    const textIdx = widths.map((_, i) => i).filter(i => category[i] === 'text');
    if (textIdx.length > 0) {
      const textTotal = textIdx.reduce((s, i) => s + widths[i], 0) || 1;
      finalWidths = widths.map((w, i) =>
        category[i] === 'text' ? w + slack * (w / textTotal) : w
      );
      const allocated = finalWidths.reduce((a, b) => a + b, 0);
      if (allocated < containerWidth) {
        finalWidths[textIdx[textIdx.length - 1]] += containerWidth - allocated;
      }
      tableMinWidth = containerWidth;
    } else {
      /* No text columns — keep natural widths; the panel itself is
         width: max-content, so the surrounding card shows the empty space
         rather than the table's narrow columns being bloated. */
      finalWidths = widths.slice();
      tableMinWidth = Math.round(naturalTotal);
    }
  } else {
    /* Wide panel OR content overflows — keep natural widths, allow horizontal scroll */
    finalWidths = widths;
    tableMinWidth = Math.max(containerWidth, Math.round(naturalTotal));
  }

  headers.forEach((th, i) => {
    const w = Math.round(finalWidths[i]);
    if (cols[i]) cols[i].style.width = w + 'px';
    th.style.width = w + 'px';
  });
  table.style.minWidth = tableMinWidth + 'px';
  table.style.width = tableMinWidth + 'px';
  table.dataset.autoFitted = 'true';

  if (isWide) updateWideScrollState(panel);
}

function autoFitSingleColumn(table, colIndex) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  const th = headers[colIndex];
  const col = cols[colIndex];
  if (!th) return;

  const { widths } = measureColumnWidths(table);
  const w = widths[colIndex];
  if (col) { col.style.width = w + 'px'; col.style.minWidth = ''; }
  th.style.width = w + 'px'; th.style.minWidth = '';

  const total = headers.reduce((sum, h) => sum + h.getBoundingClientRect().width, 0);
  table.style.minWidth = total + 'px';

  const panel = table.closest('.report-table-panel--wide');
  if (panel) updateWideScrollState(panel);
}

function updateWideScrollState(panel) {
  const wrap = panel.querySelector('.report-table-wrap');
  if (!wrap) return;
  const max = wrap.scrollWidth - wrap.clientWidth;
  let state = 'fit';
  if (max > 1) {
    const left = wrap.scrollLeft;
    if (left <= 1) state = 'start';
    else if (left >= max - 1) state = 'end';
    else state = 'scrollable';
  }
  panel.setAttribute('data-scroll-state', state);
}

/* Wrap header content in <span class="th-label"> using DOM cloning (no innerHTML). */
function wrapHeaderLabel(th) {
  if (th.querySelector('.th-label')) return;
  const label = document.createElement('span');
  label.className = 'th-label';
  while (th.firstChild) label.appendChild(th.firstChild);
  th.appendChild(label);
}

function initReportTable(table) {
  if (!table) return;
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  if (headers.length < 1) return;

  if (table.dataset.interactive !== 'true') {
    requestAnimationFrame(() => autoFitColumns(table));
    return;
  }

  headers.forEach(th => {
    wrapHeaderLabel(th);

    const indicator = document.createElement('span');
    indicator.className = 'sort-indicator';
    indicator.textContent = '\u2195';
    th.appendChild(indicator);

    const resizer = document.createElement('div');
    resizer.className = 'col-resizer';
    th.appendChild(resizer);

    th.addEventListener('click', event => {
      if (event.target === resizer) return;
      sortTable(table, Array.from(th.parentNode.children).indexOf(th));
    });

    let startX = 0;
    let startWidth = 0;
    const colIndex = Array.from(th.parentNode.children).indexOf(th);
    const targetCol = cols[colIndex] || null;

    const onMouseMove = event => {
      const width = Math.max(48, startWidth + event.clientX - startX);
      if (targetCol) { targetCol.style.width = width + 'px'; targetCol.style.minWidth = width + 'px'; }
      th.style.width = width + 'px'; th.style.minWidth = width + 'px';
      const total = headers.reduce((s, h) => s + h.getBoundingClientRect().width, 0);
      const wrapWidth = table.closest('.report-table-wrap')?.clientWidth || 0;
      table.style.minWidth = Math.max(total, wrapWidth) + 'px';
      const panel = table.closest('.report-table-panel--wide');
      if (panel) updateWideScrollState(panel);
    };
    const onMouseUp = () => {
      resizer.classList.remove('is-active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    resizer.addEventListener('mousedown', event => {
      event.preventDefault();
      event.stopPropagation();
      startX = event.clientX;
      startWidth = (targetCol || th).getBoundingClientRect().width;
      resizer.classList.add('is-active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });

    resizer.addEventListener('dblclick', event => {
      event.preventDefault();
      event.stopPropagation();
      autoFitSingleColumn(table, colIndex);
    });
  });

  requestAnimationFrame(() => autoFitColumns(table));

  const widePanel = table.closest('.report-table-panel--wide');
  if (widePanel) {
    const wrap = widePanel.querySelector('.report-table-wrap');
    if (wrap) {
      wrap.addEventListener('scroll', () => updateWideScrollState(widePanel), { passive: true });
    }
  }
}

function debounce(fn, ms) {
  let t;
  return function () { clearTimeout(t); t = setTimeout(() => fn.apply(this, arguments), ms); };
}

const refitAllTables = debounce(() => {
  document.querySelectorAll('.report-table').forEach(t => autoFitColumns(t));
}, 120);

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.report-table').forEach(initReportTable);
  window.addEventListener('resize', refitAllTables);
});
</script>
"""
