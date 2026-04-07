"""
src/report/exporters/ven_html_exporter.py
Self-contained HTML report for the VEN Status Inventory Report.
Includes embedded EN ↔ 繁體中文 language toggle (via report_i18n).
"""
from __future__ import annotations
import datetime
import os
import logging
import pandas as pd

from .report_i18n import make_i18n_js, lang_btn_html, COL_I18N as _COL_I18N
from .report_css import build_css, TABLE_JS

logger = logging.getLogger(__name__)

_CSS = build_css('ven')


def _policy_sync_badge(val: str) -> str:
    """Return a styled badge for the Policy Sync column value."""
    v = str(val).lower().strip()
    if v == 'synced':
        return f'<span class="badge-synced">{val}</span>'
    if v in ('staged',):
        return f'<span class="badge-staged">{val}</span>'
    if v and v != 'none' and v != 'nan':
        return f'<span class="badge-unsynced">{val}</span>'
    return '—'


def _df_to_html(df, no_data_key: str = "rpt_no_records") -> str:
    if df is None or (hasattr(df, 'empty') and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">— No records —</p>'
    html = '<table><thead><tr>'
    for col in df.columns:
        i18n_key = _COL_I18N.get(col)
        if i18n_key:
            html += f'<th data-i18n="{i18n_key}">{col}</th>'
        else:
            html += f'<th>{col}</th>'
    html += '</tr></thead><tbody>'
    for _, row in df.iterrows():
        html += '<tr>'
        for col, val in zip(df.columns, row.values):
            val_str = '' if val is None or str(val) in ('None', 'nan') else str(val)
            if col == 'Policy Sync':
                html += f'<td>{_policy_sync_badge(val_str)}</td>'
            else:
                html += f'<td>{val_str}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


class VenHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None):
        self._r = results
        self._df = df

    def export(self, output_dir: str = 'reports') -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        filename = f'illumio_ven_status_{ts}.html'
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self._build())
        logger.info(f"[VenHtmlExporter] Saved: {filepath}")
        return filepath

    def _build(self) -> str:
        kpis = self._r.get('kpis', [])
        gen_at = self._r.get('generated_at', '')
        today_str = str(datetime.date.today())

        nav_html = (
            '<nav>'
            '<a href="#summary"><span data-i18n="rpt_ven_nav_summary">📊 Executive Summary</span></a>'
            '<a href="#online"><span data-i18n="rpt_ven_nav_online">✅ Online VENs</span></a>'
            '<a href="#offline"><span data-i18n="rpt_ven_nav_offline">❌ Offline VENs</span></a>'
            '<a href="#lost-today"><span data-i18n="rpt_ven_nav_lost_today">🔴 Lost Today (&lt;24h)</span></a>'
            '<a href="#lost-yest"><span data-i18n="rpt_ven_nav_lost_yest">🟠 Lost Yesterday</span></a>'
            '</nav>'
        )
        kpi_cards = ''.join(
            '<div class="kpi-card"><div class="kpi-label">' + k['label'] + '</div>'
            '<div class="kpi-value">' + k['value'] + '</div></div>'
            for k in kpis
        )
        df_online  = self._r.get('online')
        df_offline = self._r.get('offline')
        df_today   = self._r.get('lost_today')
        df_yest    = self._r.get('lost_yesterday')

        online_count  = len(df_online)  if df_online  is not None and not df_online.empty  else 0
        offline_count = len(df_offline) if df_offline is not None and not df_offline.empty else 0
        today_count   = len(df_today)   if df_today   is not None and not df_today.empty   else 0
        yest_count    = len(df_yest)    if df_yest    is not None and not df_yest.empty    else 0

        body = (
            '<section id="summary" class="card">'
            '<h1 data-i18n="rpt_ven_title">Illumio VEN Status Inventory Report</h1>'
            '<p style="color:#718096;margin-top:4px">'
            '<span data-i18n="rpt_generated">Generated:</span> ' + gen_at + '</p>'
            '<h2 data-i18n="rpt_key_metrics">Key Metrics</h2>'
            '<div class="kpi-grid">' + kpi_cards + '</div>'
            '</section>\n'

            '<section id="online" class="card online">'
            '<h2><span data-i18n="rpt_ven_sec_online">✅ Online VENs</span> (' + str(online_count) + ')</h2>'
            + _df_to_html(df_online) +
            '</section>\n'

            '<section id="offline" class="card offline">'
            '<h2><span data-i18n="rpt_ven_sec_offline">❌ Offline VENs</span> (' + str(offline_count) + ')</h2>'
            + _df_to_html(df_offline) +
            '</section>\n'

            '<section id="lost-today" class="card offline">'
            '<h2><span data-i18n="rpt_ven_sec_lost_today">🔴 Lost Connection in Last 24h</span>'
            ' (' + str(today_count) + ')</h2>'
            '<p style="color:#718096;font-size:12px;margin-bottom:12px" data-i18n="rpt_ven_desc_today">'
            'VENs currently offline whose last heartbeat was within the past 24 hours.</p>'
            + _df_to_html(df_today) +
            '</section>\n'

            '<section id="lost-yest" class="card warn">'
            '<h2><span data-i18n="rpt_ven_sec_lost_yest">🟠 Lost Connection 24\u201348h Ago</span>'
            ' (' + str(yest_count) + ')</h2>'
            '<p style="color:#718096;font-size:12px;margin-bottom:12px" data-i18n="rpt_ven_desc_yest">'
            'VENs currently offline whose last heartbeat was 24\u201348 hours ago.</p>'
            + _df_to_html(df_yest) +
            '</section>\n'

            '<footer><span data-i18n="rpt_ven_footer">Illumio PCE Ops — VEN Status Report</span>'
            ' &middot; ' + today_str + '</footer>'
        )
        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>Illumio VEN Status Report</title>' + _CSS + '</head>\n'
            '<body>' + lang_btn_html() + nav_html + '<main>' + body + '</main>'
            + TABLE_JS + make_i18n_js() + '</body></html>'
        )
