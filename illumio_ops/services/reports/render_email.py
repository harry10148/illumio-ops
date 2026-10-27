"""The report email (spec §6.5.5): the body is the summary — the key metrics with the previous period, the
findings with why they matter and what to do, one data-quality line and a link back to the GUI — readable
without opening an attachment. Colours are the report shell's own tokens (email clients do not read CSS
variables, so the values are taken from report_shell.css, never a second palette)."""
from __future__ import annotations

import html
import re
from datetime import tzinfo
from functools import cache

from illumio_ops.domain.report import Kpi, ReportDocument, period_text
from illumio_ops.domain.values import Language, Severity
from illumio_ops.services.alerts.messages import Rendered
from illumio_ops.services.reports.render_html import asset, fmt_number, kpi_trend, tr

_TOKEN = re.compile(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\s*;")
_USED = ("text-1", "text-2", "text-3", "line", "surface-2", "accent-fg", "tone-crit-border", "tone-warn-border",
         "tone-info-border", "tone-neutral-border")


@cache
def _tokens() -> dict[str, str]:
    root = asset("report_shell.css").split(":root", 1)[1].split("}", 1)[0]
    found = dict(_TOKEN.findall(root))
    return {k: found[k] for k in _USED}


TOKENS = _tokens()
SEVERITY_BORDER = {Severity.CRITICAL: "tone-crit-border", Severity.HIGH: "tone-crit-border",
                   Severity.MEDIUM: "tone-warn-border", Severity.LOW: "tone-info-border"}


def _value(k: Kpi, lang: Language) -> str:
    if k.value is None:
        return tr(lang, "rpt_kpi_no_value")
    return fmt_number(k.value) + ("%" if k.unit == "percent" else "")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_email(doc: ReportDocument, *, tz: tzinfo | None, note: str | None = None) -> Rendered:
    """`note`: one more line under the data-quality line (e.g. an attachment left out for size)."""
    lang = doc.lang
    period = period_text(doc.period_start, doc.period_end, tz)
    n = len(doc.findings)
    subject = tr(lang, "rpt_mail_subject", title=doc.title, period=period,
                 status=tr(lang, "rpt_mail_status_items", n=n) if n else tr(lang, "rpt_mail_status_none"))
    link_text = (tr(lang, "rpt_mail_link", url=doc.gui_link) if doc.gui_link else tr(lang, "rpt_mail_no_link"))
    quality = "；".join(doc.data_quality) if lang is Language.ZH_TW else " ".join(doc.data_quality)

    lines = [f"{doc.title}  {period}", f"PCE: {doc.pce_label}", "", tr(lang, "rpt_mail_kpis")]
    for k in doc.kpis[:4]:
        trend = kpi_trend(k, lang)
        extra = "; ".join(x for x in (trend, k.note or "") if x)
        lines.append(f"- {k.label}: {_value(k, lang)}" + (f" ({extra})" if extra else ""))
    lines += ["", tr(lang, "rpt_findings_title")]
    if not doc.findings:
        lines.append(tr(lang, "rpt_findings_none"))
    for i, f in enumerate(doc.findings, start=1):
        lines += [f"{i}. [{tr(lang, 'severity_' + f.severity.value)}] {f.title}",
                  f"   {tr(lang, 'rpt_finding_why')} {f.why}", f"   {tr(lang, 'rpt_finding_action')} {f.action}"]
    lines += ["", f"{tr(lang, 'rpt_data_quality_title')}: {quality}"]
    if note:
        lines.append(note)
    lines += ["", link_text]

    t = TOKENS
    kpi_cells = "".join(
        f'<td style="border:1px solid {t["line"]};padding:8px;vertical-align:top;width:25%">'
        f'<div style="color:{t["text-2"]};font-size:12px">{_e(k.label)}</div>'
        f'<div style="color:{t["text-1"]};font-size:20px;font-weight:600">{_e(_value(k, lang))}</div>'
        f'<div style="color:{t["text-3"]};font-size:12px">{_e(kpi_trend(k, lang))}</div>'
        + (f'<div style="color:{t["text-3"]};font-size:12px">{_e(k.note)}</div>' if k.note else "") + "</td>"
        for k in doc.kpis[:4])
    if doc.findings:
        findings = "".join(
            f'<div style="border-left:3px solid {t[SEVERITY_BORDER.get(f.severity, "tone-neutral-border")]};'
            f'background:{t["surface-2"]};padding:6px 10px;margin:6px 0">'
            f'<div style="color:{t["text-1"]};font-weight:600">{_e(f.title)}</div>'
            f'<div style="color:{t["text-2"]}">{_e(tr(lang, "rpt_finding_why"))} {_e(f.why)}</div>'
            f'<div style="color:{t["text-2"]}">{_e(tr(lang, "rpt_finding_action"))} {_e(f.action)}</div></div>'
            for f in doc.findings)
    else:
        findings = f'<p style="color:{t["text-2"]}">{_e(tr(lang, "rpt_findings_none"))}</p>'
    link = (f'<a style="color:{t["accent-fg"]}" href="{_e(doc.gui_link)}">{_e(tr(lang, "rpt_open_in_gui"))}</a>'
            if doc.gui_link else _e(tr(lang, "rpt_mail_no_link")))
    body = (
        f'<div style="font-family:sans-serif;color:{t["text-1"]};max-width:720px">'
        f'<h2 style="margin:0 0 4px">{_e(doc.title)}</h2>'
        f'<div style="color:{t["text-3"]};font-size:12px">{_e(period)} · PCE {_e(doc.pce_label)}</div>'
        f'<h3>{_e(tr(lang, "rpt_mail_kpis"))}</h3>'
        f'<table style="border-collapse:collapse;width:100%"><tr>{kpi_cells}</tr></table>'
        f'<h3>{_e(tr(lang, "rpt_findings_title"))}</h3>{findings}'
        f'<p style="color:{t["text-3"]};font-size:12px;border-top:1px dashed {t["line"]};padding-top:6px">'
        f'{_e(tr(lang, "rpt_data_quality_title"))}: {_e(quality)}'
        + (f"<br>{_e(note)}" if note else "") + f"</p><p>{link}</p></div>")
    lang_attr = "zh-TW" if lang is Language.ZH_TW else "en"
    page = f'<!DOCTYPE html><html lang="{lang_attr}"><head><meta charset="utf-8"></head><body>{body}</body></html>'
    return Rendered(subject=subject, text="\n".join(lines), html=page, card=None, payload=None)
