"""The report email (spec §6.5.5; UI redesign spec §9.1): the body is the report's first page — the conclusion,
what to know before reading the numbers, the three lead numbers, the three things to do — and a link back to the
GUI, readable without opening an attachment. The findings one by one and the data notes are in the report, not
here. What it says about things to do is render_html.to_do's judgement, the one the HTML's first page prints.
The text and the HTML are written from the same parts, so they say the same.

Length rules: MAIL_KPIS numbers (the others are in the report); the first TOP_ACTIONS things to do and how many
more there are; one thing names the titles of its first ACTION_TITLES_MAX findings and counts the rest. Only the
subject is ever cut (SUBJECT_MAX), with an ellipsis.

Colours are the report shell's own tokens (email clients do not read CSS variables, so the values are taken from
report_shell.css, never a second palette)."""
from __future__ import annotations

import html
import re
from datetime import tzinfo
from functools import cache

from illumio_ops.domain.report import Kpi, ReportDocument, period_text
from illumio_ops.domain.values import Language, Severity
from illumio_ops.services.alerts.messages import Rendered
from illumio_ops.services.reports.render_html import (
    BETTER_KEYS,
    LEAD_KPIS,
    asset,
    fmt_number,
    kpi_trend,
    solves_titles,
    to_do,
    tr,
)

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


SUBJECT_MAX = 200
MAIL_KPIS = LEAD_KPIS  # the numbers the first page leads with


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_email(doc: ReportDocument, *, tz: tzinfo | None, note: str | None = None,
                 attached: bool = False) -> Rendered:
    """`note`: a line before the link saying an attachment was left out for its size. `attached`: the email carries
    the report as a file, so an email without a link says where its findings are (when it has any)."""
    lang = doc.lang
    period = period_text(doc.period_start, doc.period_end, tz)
    n = len(doc.findings)
    verdict = to_do(doc)  # the subject never says "nothing to act on" for rules that were not evaluated, or a custom report
    if n:
        subject = tr(lang, "rpt_mail_subject", title=doc.title, period=period, status=tr(lang, "rpt_mail_status_items", n=n))
    elif verdict is None:
        subject = tr(lang, "rpt_mail_subject_plain", title=doc.title, period=period)
    else:
        subject = tr(lang, "rpt_mail_subject", title=doc.title, period=period,
                     status=tr(lang, "rpt_mail_status_none" if verdict.nothing else "rpt_mail_status_held"))
    if doc.conclusion:  # the one sentence the report opens with; the subject is the one place it may be cut
        subject = f"{subject} — {doc.conclusion}"
        if len(subject) > SUBJECT_MAX:
            subject = subject[:SUBJECT_MAX - 1] + "…"
    t = TOKENS
    lines = [f"{doc.title}  {period}", f"PCE: {doc.pce_label}", ""]
    parts = [(f'<h2 style="margin:0 0 4px">{_e(doc.title)}</h2>'
              f'<div style="color:{t["text-3"]};font-size:12px">{_e(period)} · PCE {_e(doc.pce_label)}</div>')]
    if doc.conclusion:
        lines += [doc.conclusion, ""]
        parts.append(f'<p style="font-size:16px;font-weight:600;margin:12px 0">{_e(doc.conclusion)}</p>')
    if doc.caveats:
        title = tr(lang, "rpt_caveats_title")
        lines += [title, *doc.caveats, ""]
        parts.append(
            f'<div style="border-left:3px solid {t["accent-fg"]};background:{t["surface-2"]};padding:8px 12px;'
            f'margin:12px 0"><div style="font-weight:600">{_e(title)}</div>'
            + "".join(f'<div style="color:{t["text-2"]}">{_e(c)}</div>' for c in doc.caveats) + "</div>")

    kpis = doc.kpis[:MAIL_KPIS]
    if kpis:  # a report with no key number (nothing computed) prints no heading over nothing
        title = tr(lang, "rpt_mail_kpis")
        lines.append(title)
        cells = []
        for k in kpis:
            # under the value: the change from the previous period, which way is better, the number's own note —
            # each only when there is one
            under = [x for x in (kpi_trend(k, lang), tr(lang, BETTER_KEYS[k.better]) if k.better in BETTER_KEYS else "",
                                 k.note or "") if x]
            lines.append(f"- {k.label}: {_value(k, lang)}" + (f" ({'; '.join(under)})" if under else ""))
            cells.append(
                f'<td style="border:1px solid {t["line"]};padding:8px;vertical-align:top;width:{100 // MAIL_KPIS}%">'
                f'<div style="color:{t["text-2"]};font-size:12px">{_e(k.label)}</div>'
                f'<div style="color:{t["text-1"]};font-size:20px;font-weight:600">{_e(_value(k, lang))}</div>'
                + "".join(f'<div style="color:{t["text-3"]};font-size:12px">{_e(x)}</div>' for x in under) + "</td>")
        lines.append("")
        parts.append(f'<h3>{_e(title)}</h3><table style="border-collapse:collapse;width:100%;table-layout:fixed">'
                     f'<tr>{"".join(cells)}</tr></table>')

    todo = to_do(doc)
    if todo is not None:  # a custom report has no rules: nothing is said about things to do
        said = []  # the sentences under the list
        if todo.top:
            title = tr(lang, "rpt_actions_title", n=len(todo.top))
            lines.append(title)
            items = []
            for i, a in enumerate(todo.top, start=1):
                severity = tr(lang, "severity_" + a.severity.value)
                solves = tr(lang, "rpt_actions_solves", n=len(a.findings),
                            titles=tr(lang, "rpt_list_sep").join(solves_titles(a, lang)))
                lines += [f"{i}. [{severity}] {a.short}", f"   {solves}"]
                items.append(
                    f'<div style="border-left:3px solid {t[SEVERITY_BORDER.get(a.severity, "tone-neutral-border")]};'
                    f'background:{t["surface-2"]};padding:6px 10px;margin:6px 0">'
                    f'<div style="color:{t["text-1"]};font-weight:600">{i}. [{_e(severity)}] {_e(a.short)}</div>'
                    f'<div style="color:{t["text-2"]}">{_e(solves)}</div></div>')
            parts.append(f"<h3>{_e(title)}</h3>" + "".join(items))
            if todo.more:
                said.append(tr(lang, "rpt_mail_actions_more", n=todo.more))
        if todo.nothing:
            said.append(tr(lang, "rpt_findings_none"))
        if todo.held:
            said.append(todo.held)
        lines += [*said, ""]
        parts += [f'<p style="color:{t["text-2"]}">{_e(x)}</p>' for x in said]

    # the last lines: an attachment left out for its size, then the link — or, without one, that there is none and
    # (when the report is attached) where the findings are
    last = [note] if note else []
    if doc.gui_link:
        lines += [*last, tr(lang, "rpt_mail_link", url=doc.gui_link)]
        link = f'<a style="color:{t["accent-fg"]}" href="{_e(doc.gui_link)}">{_e(tr(lang, "rpt_open_in_gui"))}</a>'
    else:
        last.append(tr(lang, "rpt_mail_no_link"))
        if attached and doc.findings:  # never after "nothing needs action", nor for a report without rules
            last.append(tr(lang, "rpt_mail_see_attachment"))
        lines += last
        link = ""
    foot = "<br>".join(_e(x) for x in last)
    parts.append(
        (f'<p style="color:{t["text-3"]};font-size:12px;border-top:1px dashed {t["line"]};padding-top:6px">{foot}</p>'
         if foot else "") + (f"<p>{link}</p>" if link else ""))
    body = (f'<div style="font-family:sans-serif;color:{t["text-1"]};max-width:720px;overflow-wrap:anywhere">'
            + "".join(parts) + "</div>")
    lang_attr = "zh-TW" if lang is Language.ZH_TW else "en"
    page = f'<!DOCTYPE html><html lang="{lang_attr}"><head><meta charset="utf-8"></head><body>{body}</body></html>'
    return Rendered(subject=subject, text="\n".join(lines), html=page, card=None, payload=None)
