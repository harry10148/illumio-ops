"""
src/report/exporters/report_css.py
Shared CSS/JS foundation for HTML report exporters.
"""

FONT_LINK = '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">'

BASE_CSS = """\
  :root {
    --cyan-120:#1A2C32; --cyan-110:#24393F; --cyan-100:#2D454C; --cyan-90:#325158;
    --orange:#FF5500; --gold:#FFA22F; --gold-110:#F97607;
    --green:#166644; --green-80:#299B65; --green-10:#D1FAE5;
    --red:#BE122F; --red-80:#F43F51; --red-10:#FEE2E2;
    --slate:#313638; --slate-10:#EAEBEB; --slate-20:#D6D7D7; --slate-50:#989A9B;
    --tan:#F7F4EE; --tan-120:#E3D8C5; --border:#D6D7D7;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Montserrat', -apple-system, sans-serif; background: var(--tan); color: var(--slate); }
  nav { position: fixed; top: 0; left: 0; width: 210px; height: 100vh; background: var(--cyan-120); overflow-y: auto; padding: 60px 0 20px; z-index: 100; }
  nav a { display: block; color: var(--slate-20); text-decoration: none; padding: 7px 16px; font-size: 12px; border-left: 3px solid transparent; }
  nav a:hover, nav a.active { background: var(--cyan-100); border-left-color: var(--orange); color: #fff; }
  main { margin-left: 210px; padding: 24px; }
  h1 { color: var(--orange); font-size: 22px; font-weight: 700; margin-bottom: 4px; }
  h2 { color: var(--cyan-120); font-size: 16px; font-weight: 600; margin: 24px 0 10px; border-bottom: 2px solid var(--orange); padding-bottom: 6px; }
  h3 { color: var(--slate); font-size: 13px; font-weight: 600; margin: 16px 0 8px; }
  h4 { color: var(--slate-50); font-size: 12px; font-weight: 600; margin: 12px 0 6px; text-transform: uppercase; letter-spacing: .04em; }

  .card { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; color: var(--slate); }
  .note { background: var(--tan); border-left: 4px solid var(--orange); padding: 12px; border-radius: 4px; color: var(--cyan-120); font-size: 13px; margin: 10px 0; }
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
  .summary-pill-value { display: block; font-size: 15px; font-weight: 700; color: var(--cyan-120); }
  .section-intro { margin: 0 0 14px; color: var(--slate-50); font-size: 12px; line-height: 1.6; }

  .kpi-grid { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
  .kpi-card { background: #fff; border-radius: 8px; padding: 14px 18px; box-shadow: 0 1px 4px rgba(0,0,0,.08); min-width: 160px; border-top: 3px solid var(--orange); }
  .kpi-label { font-size: 11px; color: var(--slate-50); text-transform: uppercase; letter-spacing: .04em; }
  .kpi-value { font-size: 22px; font-weight: 700; color: var(--cyan-120); }
  .report-hero .kpi-card { background: #fff; box-shadow: 0 6px 16px rgba(26,44,50,.08); border-top-color: var(--orange); }

  .report-table-panel { margin: 12px 0 18px; border: 1px solid rgba(50,81,88,.14); border-radius: 14px; overflow: hidden; background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(247,244,238,.92)); box-shadow: 0 10px 24px rgba(26,44,50,.08); }
  .report-table-wrap { overflow: auto; max-width: 100%; }
  .report-table { min-width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12px; }
  .report-table thead th { background: var(--cyan-110); color: #fff; position: sticky; top: 0; z-index: 2; min-width: 120px; padding: 12px 28px 12px 12px; vertical-align: middle; border-right: 1px solid rgba(255,255,255,.08); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .report-table thead th:hover { background: var(--cyan-100); }
  .report-table tbody td { padding: 10px 12px; vertical-align: top; border-bottom: 1px solid var(--slate-20); color: var(--slate); }
  .report-table tbody td, .report-table tbody td * { color: var(--slate); }
  .report-table tbody td code { color: var(--cyan-120); background: rgba(26,44,50,.06); padding: 1px 4px; border-radius: 4px; }
  .report-table tbody tr:nth-child(even) td { background: var(--tan); }
  .report-table tbody tr:hover td { background: var(--tan-120); }

  .th-label { display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 18px; }
  .report-table--interactive thead th { cursor: pointer; user-select: none; }
  .sort-indicator { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-size: 11px; opacity: .72; pointer-events: none; }
  .col-resizer { position: absolute; top: 0; right: 0; width: 8px; height: 100%; cursor: col-resize; background: transparent; }
  .col-resizer:hover, .col-resizer.is-active { background: linear-gradient(180deg, rgba(255,162,47,.0), rgba(255,85,0,.75), rgba(255,162,47,.0)); }
  .report-table thead th.is-sorted-asc, .report-table thead th.is-sorted-desc { background: linear-gradient(180deg, var(--cyan-100), var(--cyan-120)); }
  .report-table-wrap::-webkit-scrollbar { height: 12px; width: 12px; }
  .report-table-wrap::-webkit-scrollbar-thumb { background: rgba(50,81,88,.22); border-radius: 999px; border: 3px solid transparent; background-clip: padding-box; }

  .coverage-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
  .cov-stat { background: #fff; border-radius: 6px; padding: 10px 16px; border: 1px solid var(--slate-20); min-width: 140px; }
  .cov-stat .cov-label { font-size: 11px; color: var(--slate-50); text-transform: uppercase; letter-spacing: .04em; }
  .cov-stat .cov-value { font-size: 18px; font-weight: 700; color: var(--cyan-120); }
  .progress-bar { background: var(--slate-20); border-radius: 4px; height: 8px; margin: 6px 0 14px; }
  .progress-fill { height: 100%; border-radius: 4px; background: var(--orange); }

  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; color: #fff; }
  .badge-CRITICAL { background: var(--red); }
  .badge-HIGH { background: var(--red-80); }
  .badge-MEDIUM { background: var(--gold-110); }
  .badge-LOW { background: var(--green); }
  .badge-INFO { background: var(--cyan-100); }

  .dual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; margin: 8px 0 12px; }
  @media (max-width: 1200px) { .dual-grid { grid-template-columns: 1fr; } }
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
  .finding-rule-id { font-size: 11px; color: var(--slate-50); font-family: monospace; background: var(--slate-10); padding: 2px 6px; border-radius: 3px; }
  .finding-desc { font-size: 13px; margin-bottom: 10px; color: var(--slate); line-height: 1.5; }
  .finding-evidence { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .ev-pill { background: var(--tan); border: 1px solid var(--tan-120); border-radius: 4px; padding: 4px 10px; font-size: 12px; }
  .ev-pill span.ev-label { color: var(--slate-50); font-size: 10px; display: block; text-transform: uppercase; letter-spacing: .04em; }
  .ev-pill b { color: var(--cyan-110); }
  .finding-rec { background: var(--tan); border-left: 3px solid var(--orange); padding: 10px 12px; border-radius: 4px; font-size: 12px; color: var(--cyan-120); line-height: 1.6; }
"""

AUDIT_CSS = """\
  td { word-break: break-all; }
  .bp-box { margin: 12px 0; padding: 12px 14px; border-left: 4px solid var(--orange); border-radius: 6px; background: linear-gradient(180deg, #FFFDF8, #F7F4EE); color: var(--cyan-120); line-height: 1.7; font-size: 12px; }
  .bp-box b { color: var(--cyan-120); }
  .report-hero + .card .report-table-panel,
  .card .report-table-panel { box-shadow: 0 6px 18px rgba(26,44,50,.08); }
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

function initReportTable(table) {
  if (!table || table.dataset.interactive !== 'true') return;
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  if (headers.length < 3) return;
  headers.forEach(th => {
    if (!th.querySelector('.th-label')) {
      const label = document.createElement('span');
      label.className = 'th-label';
      label.innerHTML = th.innerHTML;
      th.innerHTML = '';
      th.appendChild(label);
    }

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
      const width = Math.max(96, startWidth + event.clientX - startX);
      if (targetCol) {
        targetCol.style.width = `${width}px`;
        targetCol.style.minWidth = `${width}px`;
      }
      th.style.width = `${width}px`;
      th.style.minWidth = `${width}px`;
      table.style.minWidth = 'max-content';
    };
    const onMouseUp = () => {
      resizer.classList.remove('is-active');
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    resizer.addEventListener('mousedown', event => {
      event.preventDefault();
      event.stopPropagation();
      startX = event.clientX;
      startWidth = (targetCol || th).getBoundingClientRect().width;
      resizer.classList.add('is-active');
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.report-table').forEach(initReportTable);
});
</script>
"""
