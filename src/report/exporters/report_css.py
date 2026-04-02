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
    padding: 10px 12px; border-radius: 4px; font-size: 12px; color: var(--cyan-120); }
  .finding-rec::before { content: "\\2192  "; font-weight: 700; }
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


def build_css(exporter_type: str) -> str:
    """Build the complete CSS block for a given exporter type."""
    extra = {
        'traffic': TRAFFIC_CSS,
        'audit': AUDIT_CSS,
        'ven': VEN_CSS,
    }.get(exporter_type, '')
    return f"{FONT_LINK}\n{BASE_CSS}{extra}</style>\n"
