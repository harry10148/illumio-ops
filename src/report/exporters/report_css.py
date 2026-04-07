"""
src/report/exporters/report_css.py
Shared CSS foundation for all HTML report exporters.

Each exporter composes: FONT_LINK + BASE_CSS + exporter-specific styles.
"""

FONT_LINK = '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">'

BASE_CSS = """\
<style>
  /* Illumio Brand Palette */
  :root {
    --cyan-120:#1A2C32; --cyan-110:#24393F; --cyan-100:#2D454C; --cyan-90:#325158;
    --orange:#FF5500;   --gold:#FFA22F;     --gold-110:#F97607;
    --green:#166644;    --green-80:#299B65; --green-10:#D1FAE5;
    --red:#BE122F;      --red-80:#F43F51;   --red-10:#FEE2E2;
    --slate:#313638;    --slate-10:#EAEBEB; --slate-20:#D6D7D7; --slate-50:#989A9B;
    --tan:#F7F4EE;      --tan-120:#E3D8C5;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Montserrat', -apple-system, sans-serif;
         background: var(--tan); color: var(--slate); }
  nav { position: fixed; top: 0; left: 0; width: 210px; height: 100vh;
        background: var(--cyan-120); overflow-y: auto; padding: 60px 0 20px; z-index: 100; }
  nav .nav-brand { position:absolute; top:0; left:0; width:100%; padding:14px 16px;
                   background:var(--orange); color:#fff; font-weight:700; font-size:13px; }
  nav a { display: block; color: var(--slate-20); text-decoration: none;
          padding: 7px 16px; font-size: 12px; border-left: 3px solid transparent; }
  nav a:hover, nav a.active { background: var(--cyan-100); border-left-color: var(--orange); color: #fff; }
  main { margin-left: 210px; padding: 24px; }
  h1 { color: var(--orange); font-size: 22px; font-weight: 700; margin-bottom: 4px; }
  h2 { color: var(--cyan-120); font-size: 16px; font-weight: 600; margin: 24px 0 10px;
       border-bottom: 2px solid var(--orange); padding-bottom: 6px; }
  h3 { color: var(--slate); font-size: 13px; font-weight: 600; margin: 16px 0 8px; }
  h4 { color: var(--slate-50); font-size: 12px; font-weight: 600; margin: 12px 0 6px; text-transform: uppercase; letter-spacing: .04em; }
  .kpi-grid { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
  .kpi-card { background: #fff; border-radius: 8px; padding: 14px 18px;
               box-shadow: 0 1px 4px rgba(0,0,0,.08); min-width: 160px;
               border-top: 3px solid var(--orange); }
  .kpi-label { font-size: 11px; color: var(--slate-50); text-transform:uppercase; letter-spacing:.04em; }
  .kpi-value { font-size: 22px; font-weight: 700; color: var(--cyan-120); }
  .card { background: #fff; border-radius: 8px; padding: 20px;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { background: var(--cyan-110); color: #fff; padding: 8px 10px; text-align: left;
       cursor: pointer; user-select: none; font-weight: 600; }
  th:hover { background: var(--cyan-100); }
  td { padding: 6px 10px; border-bottom: 1px solid var(--slate-20); }
  tr:nth-child(even) td { background: var(--tan); }
  tr:hover td { background: var(--tan-120); }
  .note { background: var(--tan); border-left: 4px solid var(--orange);
          padding: 12px; border-radius: 4px; color: var(--cyan-120); font-size: 13px; }
  footer { text-align: center; color: var(--slate-50); font-size: 11px; margin: 40px 0 20px; }
"""

# ── Exporter-specific CSS fragments ──────────────────────────────────────────

TRAFFIC_CSS = """\
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 11px; font-weight: 700; color: #fff; }
  .badge-CRITICAL { background: var(--red); }
  .badge-HIGH     { background: var(--red-80); }
  .badge-MEDIUM   { background: var(--gold-110); }
  .badge-LOW      { background: var(--green); }
  .badge-INFO     { background: var(--cyan-100); }
  /* Security Findings Cards */
  .finding-card { border: 1px solid var(--slate-20); border-radius: 8px;
    padding: 16px; margin-bottom: 16px; background: #fff; }
  .finding-card.sev-CRITICAL { border-left: 5px solid var(--red); }
  .finding-card.sev-HIGH     { border-left: 5px solid var(--red-80); }
  .finding-card.sev-MEDIUM   { border-left: 5px solid var(--gold-110); }
  .finding-card.sev-LOW      { border-left: 5px solid var(--green); }
  .finding-card.sev-INFO     { border-left: 5px solid var(--cyan-100); }
  .finding-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .finding-title  { font-weight: 600; font-size: 14px; color: var(--cyan-120); }
  .finding-rule-id { font-size: 11px; color: var(--slate-50); font-family: monospace;
    background: var(--slate-10); padding: 2px 6px; border-radius: 3px; }
  .finding-desc   { font-size: 13px; margin-bottom: 10px; color: var(--slate); line-height: 1.5; }
  .finding-evidence { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .ev-pill { background: var(--tan); border: 1px solid var(--tan-120); border-radius: 4px;
    padding: 4px 10px; font-size: 12px; }
  .ev-pill span.ev-label { color: var(--slate-50); font-size: 10px; display: block;
    text-transform: uppercase; letter-spacing: .04em; }
  .ev-pill b { color: var(--cyan-110); }
  .finding-rec { background: var(--tan); border-left: 3px solid var(--orange);
    padding: 10px 12px; border-radius: 4px; font-size: 12px; color: var(--cyan-120); line-height: 1.6; }

  .cat-group { margin-bottom: 6px; }
  .sev-summary { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
  .sev-box { text-align: center; padding: 10px 18px; border-radius: 8px; background: #fff;
    border: 1px solid var(--slate-20); min-width: 80px; }
  .sev-box .sev-count { font-size: 24px; font-weight: 700; color: var(--cyan-120); }
  .progress-bar { background: var(--slate-20); border-radius: 4px; height: 8px; margin: 6px 0 14px; }
  .progress-fill { height: 100%; border-radius: 4px; background: var(--orange); }
  .coverage-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
  .cov-stat { background: #fff; border-radius: 6px; padding: 10px 16px;
    border: 1px solid var(--slate-20); min-width: 140px; }
  .cov-stat .cov-label { font-size: 11px; color: var(--slate-50); text-transform: uppercase;
    letter-spacing: .04em; }
  .cov-stat .cov-value { font-size: 18px; font-weight: 700; color: var(--cyan-120); }
"""

AUDIT_CSS = """\
  td { word-break: break-all; }
  .note { margin: 10px 0; }
  .note-warn { border-left-color: var(--red); }
  .note-info { border-left-color: var(--green-80); }
  .bp-box { background: #f0f7f4; border-left: 4px solid var(--green-80);
            padding: 12px 14px; border-radius: 4px; margin: 12px 0; font-size: 12px; }
  .bp-box b { color: var(--green); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 3px;
           font-size: 11px; font-weight: 600; color: #fff; }
  .badge-red { background: var(--red); }
  .badge-orange { background: var(--gold-110); }
  .badge-green { background: var(--green-80); }
"""

VEN_CSS = """\
  td { word-break: break-all; }
  .card.online  { border-top: 4px solid var(--green-80); }
  .card.offline { border-top: 4px solid var(--red-80); }
  .card.warn    { border-top: 4px solid var(--gold-110); }
  .badge-online   { background: var(--green-10); color: var(--green); padding:2px 8px;
                    border-radius:4px; font-size:11px; font-weight:700; }
  .badge-offline  { background: var(--red-10); color: var(--red); padding:2px 8px;
                    border-radius:4px; font-size:11px; font-weight:700; }
  .badge-synced   { background: var(--green-10); color: var(--green); padding:2px 8px;
                    border-radius:4px; font-size:11px; font-weight:700; }
  .badge-unsynced { background: var(--red-10); color: var(--red); padding:2px 8px;
                    border-radius:4px; font-size:11px; font-weight:700; }
  .badge-staged   { background: #FFF3CD; color: #856404; padding:2px 8px;
                    border-radius:4px; font-size:11px; font-weight:700; }
"""


POLICY_USAGE_CSS = """\
  td { word-break: break-word; }
  .note { margin: 10px 0; }
  .note-warn { border-left-color: var(--red); }
  .note-info { border-left-color: var(--green-80); }
  .badge-hit    { display: inline-block; background: var(--green-10); color: var(--green);
                  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .badge-unused { display: inline-block; background: var(--red-10); color: var(--red);
                  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .pu-kpi-row   { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0 16px; }
  .pu-kpi-box   { background: var(--card-bg); border: 1px solid var(--border);
                  border-radius: 8px; padding: 10px 16px; min-width: 130px; text-align: center; }
  .pu-kpi-val   { font-size: 22px; font-weight: 700; color: var(--cyan-120); }
  .pu-kpi-lbl   { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .caveat-box   { background: #fff8e1; border-left: 4px solid #f59e0b;
                  padding: 10px 14px; border-radius: 4px; margin: 12px 0;
                  font-size: 12px; color: #78350f; }
  .attention-box { background: var(--card-bg); border: 1px solid var(--border);
                   border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
  .attention-box h4 { margin: 0 0 8px; font-size: 13px; }
  .attention-row { display: flex; justify-content: space-between; padding: 3px 0;
                   border-bottom: 1px solid var(--border); font-size: 12px; }
"""


def build_css(exporter_type: str) -> str:
    """Build the complete CSS block for a given exporter type."""
    extra = {
        'traffic':      TRAFFIC_CSS,
        'audit':        AUDIT_CSS,
        'ven':          VEN_CSS,
        'policy_usage': POLICY_USAGE_CSS,
    }.get(exporter_type, '')
    
    # Add table structural CSS required for resizing and filtering
    TABLE_STRUCT_CSS = """
  table { table-layout: fixed; border: 1px solid var(--slate-20); }
  th { position: relative; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; 
       padding-bottom: 32px !important; }
  th .resizer { position: absolute; top: 0; right: 0; width: 4px; cursor: col-resize; user-select: none; height: 100%; z-index: 2; opacity: 0; transition: opacity 0.2s; }
  th:hover .resizer { opacity: 1; background: var(--orange); }
  th .resizer:active { opacity: 1; background: var(--orange); width: 6px; }
  
  .filter-input { 
    position: absolute; bottom: 6px; left: 6px; right: 6px;
    width: calc(100% - 12px); box-sizing: border-box; 
    padding: 4px 8px 4px 20px; font-size: 10px; font-weight: normal; 
    border: 1px solid var(--slate-20); border-radius: 4px; 
    color: var(--slate); background: rgba(255,255,255,0.9) url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>') no-repeat 5px center;
    display: block; cursor: text; outline: none;
    transition: all 0.2s;
  }
  .filter-input:focus { border-color: var(--orange); background: #fff; box-shadow: 0 0 0 2px rgba(255,85,0,0.1); }
  .filter-input::placeholder { color: var(--slate-50); font-style: italic; }
"""
    return f"{FONT_LINK}\n{BASE_CSS}{TABLE_STRUCT_CSS}{extra}</style>\n"

TABLE_JS = """
<script>
// 1. Column Resizing
document.querySelectorAll('th').forEach(th => {
  const resizer = document.createElement('div');
  resizer.classList.add('resizer');
  th.appendChild(resizer);
  let x, w;
  const mouseDownHandler = (e) => {
    e.stopPropagation(); // prevent sort
    x = e.clientX;
    const styles = window.getComputedStyle(th);
    w = parseInt(styles.width, 10);
    document.addEventListener('mousemove', mouseMoveHandler);
    document.addEventListener('mouseup', mouseUpHandler);
  };
  const mouseMoveHandler = (e) => { th.style.width = `${w + e.clientX - x}px`; };
  const mouseUpHandler = () => {
    document.removeEventListener('mousemove', mouseMoveHandler);
    document.removeEventListener('mouseup', mouseUpHandler);
  };
  resizer.addEventListener('mousedown', mouseDownHandler);
});

// 2. Table Sorting
function sortTable(table, col) {
  var rows = Array.from(table.querySelectorAll('tbody tr, tr:not(:first-child)'));
  var asc = table.dataset.sortCol === String(col) && table.dataset.sortDir === 'asc';
  rows.sort((a, b) => {
    var av = a.cells[col] ? a.cells[col].innerText : '';
    var bv = b.cells[col] ? b.cells[col].innerText : '';
    var an = parseFloat(av.replace(/,/g, '')), bn = parseFloat(bv.replace(/,/g, ''));
    if (!isNaN(an) && !isNaN(bn)) return asc ? bn - an : an - bn;
    return asc ? bv.localeCompare(av) : av.localeCompare(bv);
  });
  rows.forEach(r => table.appendChild(r));
  table.dataset.sortCol = col; table.dataset.sortDir = asc ? 'desc' : 'asc';
}
document.querySelectorAll('th').forEach((th, i) => {
  th.addEventListener('click', (e) => {
    if (e.target.tagName.toLowerCase() === 'input' || e.target.classList.contains('resizer')) return;
    sortTable(th.closest('table'), Array.from(th.parentNode.children).indexOf(th));
  });
});

// 3. Table Filtering
document.querySelectorAll('th').forEach((th, i) => {
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'Filter...';
  input.className = 'filter-input';
  input.addEventListener('keyup', (e) => {
    const table = th.closest('table');
    const rows = Array.from(table.querySelectorAll('tbody tr, tr:not(:first-child)'));
    const filters = Array.from(table.querySelectorAll('.filter-input')).map(inp => inp.value.toLowerCase());
    rows.forEach(r => {
      let show = true;
      for(let c=0; c<filters.length; c++) {
        if(!filters[c]) continue;
        const cellText = (r.cells[c] ? r.cells[c].innerText.toLowerCase() : '');
        if(!cellText.includes(filters[c])) { show = false; break; }
      }
      r.style.display = show ? '' : 'none';
    });
  });
  input.addEventListener('click', e => e.stopPropagation()); // prevent sort
  th.appendChild(input);
});
</script>
"""
