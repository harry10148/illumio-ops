"""
src/report/exporters/policy_usage_html_exporter.py
Self-contained HTML report for the Policy Usage Report.
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

_CSS = build_css('policy_usage')


def _df_to_html(df, no_data_key: str = "rpt_no_data") -> str:
    if df is None or (hasattr(df, 'empty') and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">— No data —</p>'
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
        for col in df.columns:
            val = str(row[col]) if row[col] is not None else ''
            # Render boolean Enabled as badge
            if col == 'Enabled':
                if str(val).lower() in ('true', '1', 'yes'):
                    html += '<td><span class="badge-hit">✓</span></td>'
                else:
                    html += '<td><span class="badge-unused">✗</span></td>'
            else:
                html += f'<td>{val}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


class PolicyUsageHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None,
                 date_range: tuple = ('', ''), lookback_days: int = 30):
        self._r = results
        self._df = df
        self._date_range = date_range
        self._lookback_days = lookback_days

    def export(self, output_dir: str = 'reports') -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        filename = f'illumio_policy_usage_report_{ts}.html'
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self._build())
        logger.info(f"[PolicyUsageHtmlExporter] Saved: {filepath}")
        return filepath

    def _build(self) -> str:
        mod00 = self._r.get('mod00', {})

        nav_html = (
            '<nav>'
            '<div class="nav-brand">Illumio PCE Ops</div>'
            '<a href="#summary"><span data-i18n="rpt_pu_nav_summary">Executive Summary</span></a>'
            '<a href="#overview"><span data-i18n="rpt_pu_nav_overview">1 Usage Overview</span></a>'
            '<a href="#hit-rules"><span data-i18n="rpt_pu_nav_hit">2 Hit Rules</span></a>'
            '<a href="#unused-rules"><span data-i18n="rpt_pu_nav_unused">3 Unused Rules</span></a>'
            '</nav>'
        )

        date_str = ' ~ '.join(self._date_range) if any(self._date_range) else ''
        today_str = str(datetime.date.today())
        period_part = (
            ' &nbsp;|&nbsp; <span data-i18n="rpt_period">Period:</span> ' + date_str
            if date_str else ''
        )

        kpi_html = self._kpi_html(mod00.get('kpis', []))
        attention_html = self._attention_html(mod00.get('attention_items', []))

        body = (
            '<section id="summary" class="card">'
            '<h1 data-i18n="rpt_pu_title">Illumio Policy Usage Report</h1>'
            '<p style="color:#718096;margin-top:4px">'
            '<span data-i18n="rpt_generated">Generated:</span> '
            + mod00.get('generated_at', '') + period_part + '</p>'
            + kpi_html
            + attention_html
            + '</section>\n'
            + self._section('overview',    'rpt_pu_sec_overview', '1 · Policy Usage Overview',  self._mod01_html()) + '\n'
            + self._section('hit-rules',   'rpt_pu_sec_hit',      '2 · Hit Rules Detail',        self._mod02_html()) + '\n'
            + self._section('unused-rules','rpt_pu_sec_unused',   '3 · Unused Rules Detail',     self._mod03_html()) + '\n'
            + '<footer>'
            '<span data-i18n="rpt_pu_footer">Illumio PCE Ops — Policy Usage Report</span>'
            ' &middot; ' + today_str + '</footer>'
        )
        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>Illumio Policy Usage Report</title>' + _CSS + '</head>\n'
            '<body>' + lang_btn_html() + nav_html + '<main>' + body + '</main>'
            + TABLE_JS + make_i18n_js() + '</body></html>'
        )

    def _section(self, id_: str, i18n_key: str, title: str, content: str) -> str:
        return (
            f'<section id="{id_}" class="card">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f'{content}</section>'
        )

    def _kpi_html(self, kpis: list) -> str:
        if not kpis:
            return ''
        cards = ''.join(
            f'<div class="pu-kpi-box">'
            f'<div class="pu-kpi-val">{k["value"]}</div>'
            f'<div class="pu-kpi-lbl">{k["label"]}</div>'
            f'</div>'
            for k in kpis
        )
        return f'<div class="pu-kpi-row">{cards}</div>'

    def _attention_html(self, attention_items: list) -> str:
        if not attention_items:
            return ''
        rows = ''.join(
            f'<div class="attention-row">'
            f'<span>{item.get("ruleset", "")}</span>'
            f'<span class="badge-unused">{item.get("unused_count", 0)}</span>'
            f'</div>'
            for item in attention_items
        )
        return (
            '<div class="attention-box">'
            '<h4 data-i18n="rpt_pu_attention">Top Rulesets by Unused Rules</h4>'
            + rows +
            '</div>'
        )

    def _mod01_html(self) -> str:
        mod01 = self._r.get('mod01', {})
        total  = mod01.get('total_rules', 0)
        hit    = mod01.get('hit_count', 0)
        unused = mod01.get('unused_count', 0)
        rate   = mod01.get('hit_rate_pct', 0.0)
        summary_df = mod01.get('summary_df')

        stats = (
            f'<p>'
            f'<span data-i18n="rpt_pu_total_rules">Total Active Rules</span>: <strong>{total}</strong> &nbsp;|&nbsp; '
            f'<span class="badge-hit" data-i18n="rpt_pu_hit_rules">Hit</span> {hit} &nbsp;|&nbsp; '
            f'<span class="badge-unused" data-i18n="rpt_pu_unused_rules">Unused</span> {unused} &nbsp;|&nbsp; '
            f'<span data-i18n="rpt_pu_hit_rate">Hit Rate</span>: <strong>{rate}%</strong>'
            f'</p>'
        )
        table_html = _df_to_html(summary_df)
        return stats + table_html

    def _mod02_html(self) -> str:
        mod02 = self._r.get('mod02', {})
        hit_df = mod02.get('hit_df')
        count  = mod02.get('record_count', 0)
        note   = f'<p style="color:#718096;font-size:12px;">{count} rules</p>' if count else ''
        if hit_df is None or (hasattr(hit_df, 'empty') and hit_df.empty):
            return f'<p class="note" data-i18n="rpt_pu_no_hit_rules">No rules were hit during this period.</p>'
        return note + _df_to_html(hit_df)

    def _mod03_html(self) -> str:
        mod03 = self._r.get('mod03', {})
        unused_df = mod03.get('unused_df')
        count     = mod03.get('record_count', 0)
        caveat    = mod03.get('caveat', '')

        caveat_html = ''
        if caveat:
            caveat_html = (
                '<div class="caveat-box">'
                '<strong data-i18n="rpt_pu_caveat_title">⚠ Retention Period Caveat</strong><br>'
                f'<span data-i18n="rpt_pu_caveat_body">{caveat}</span>'
                '</div>'
            )

        if unused_df is None or (hasattr(unused_df, 'empty') and unused_df.empty):
            return (
                caveat_html
                + '<p class="note" data-i18n="rpt_pu_no_unused_rules">'
                'All rules had traffic hits — no unused rules found.</p>'
            )

        note = f'<p style="color:#718096;font-size:12px;">{count} rules</p>' if count else ''
        return caveat_html + note + _df_to_html(unused_df)
