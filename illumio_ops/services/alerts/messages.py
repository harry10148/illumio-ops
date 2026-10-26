"""What an alert says on each channel. One set of facts, five shapes; every shape has a length limit and, when
it is reached, says what it left out (anti-goal 5). Text comes from the dictionaries in the display language,
times in the display time zone."""
from __future__ import annotations

import html
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from illumio_ops.domain.tamper import TAMPER_ACTION_KEYS, TAMPER_PATTERN_KEYS
from illumio_ops.domain.values import (
    ChannelKind,
    DeploymentType,
    Language,
    Severity,
    TamperAction,
    TamperPattern,
)
from illumio_ops.i18n import translate
from illumio_ops.settings.schema import DisplaySettings, PceSettings

SAAS_CONSOLE = "https://console.illum.io"
LIMITS: Mapping[ChannelKind, int] = {ChannelKind.LINE: 4500, ChannelKind.TELEGRAM: 3800}  # characters (API: 5000 / 4096)
MAX_ITEMS: Mapping[ChannelKind, int] = {ChannelKind.TEAMS: 10, ChannelKind.SMTP: 50, ChannelKind.WEBHOOK: 100}
SEVERITY_KEYS: Mapping[Severity, str] = {
    Severity.LOW: "severity_low", Severity.MEDIUM: "severity_medium", Severity.HIGH: "severity_high",
    Severity.CRITICAL: "severity_critical",
}


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str | None
    card: dict[str, Any] | None
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class AlertView:
    """An alert as the dispatcher and the GUI show it."""
    id: int
    rule_name: str
    pack_key: str | None
    severity: Severity
    subject_key: str
    fired_at: datetime
    late: bool
    message_key: str
    params: Mapping[str, Any]
    facts: Mapping[str, Any]
    confidence: Mapping[str, Any]


def alert_view(row: sqlite3.Row) -> AlertView:
    return AlertView(id=row["id"], rule_name=row["rule_name"], pack_key=row["pack_key"],
                     severity=Severity(row["severity"]), subject_key=row["subject_key"],
                     fired_at=datetime.fromisoformat(row["fired_at"]), late=bool(row["late"]),
                     message_key=row["message_key"], params=json.loads(row["params_json"]),
                     facts=json.loads(row["facts_json"]), confidence=json.loads(row["confidence_json"]))


def console_url(pce: PceSettings) -> str:
    """Where people sign in to the PCE: the configured address, else Illumio Console for SaaS and the API
    address on premises (spec §6.5, PCE health and addresses)."""
    if pce.console_url:
        return pce.console_url
    return SAAS_CONSOLE if pce.deployment_type is DeploymentType.SAAS else pce.url


def rule_title(v: AlertView, lang: Language) -> str:
    return v.rule_name or (translate(lang, v.pack_key) if v.pack_key else v.message_key)


def display_zone(display: DisplaySettings) -> tuple[tzinfo | None, str | None]:
    """The display time zone and how to name it next to a time ("local": the server's own zone's name)."""
    return display.zone(), None if display.timezone == "local" else display.timezone


def _when(t: datetime, tz: tzinfo | None, label: str | None = None) -> str:
    local = t.astimezone(tz)
    return f"{local.strftime('%Y-%m-%d %H:%M')} {label or local.strftime('%Z')}".rstrip()


def _text_value(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(_text_value(x) for x in value)
    if isinstance(value, float):
        return f"{value:g}"
    return "" if value is None else str(value)


def tamper_reading(v: AlertView, lang: Language) -> str | None:
    """A tampering alert's reading (spec §6.5.2, §6.5.4): a signal event's process, PID and actions, or that a
    confirmed event carries no process information; and the host's pattern."""
    p = v.params
    if "classification" not in p:
        return None
    try:
        pattern = translate(lang, TAMPER_PATTERN_KEYS[TamperPattern(p.get("pattern") or TamperPattern.TOO_FEW)])
    except ValueError:
        pattern = translate(lang, TAMPER_PATTERN_KEYS[TamperPattern.TOO_FEW])
    if p.get("has_process_info"):
        names = []
        for a in p.get("actions") or []:
            try:
                names.append(translate(lang, TAMPER_ACTION_KEYS[TamperAction(a)]))
            except ValueError:
                names.append(str(a))
        return translate(lang, "alert_tamper_signal", {"process": str(p.get("process") or "?"),
                                                       "pid": str(p.get("pid") or "?"), "actions": ", ".join(names),
                                                       "pattern": pattern})
    return translate(lang, "alert_tamper_confirmed", {"pattern": pattern})


def summary(v: AlertView, lang: Language) -> str:
    """The alert's one sentence: its message with the facts and parameters filled in (and a tampering alert's
    reading after it)."""
    values = {**{k: _text_value(x) for k, x in v.facts.items()}, **{k: _text_value(x) for k, x in v.params.items()}}
    hosts = v.params.get("hosts")
    total = v.params.get("hosts_total")
    if isinstance(hosts, list) and isinstance(total, int) and total > len(hosts):
        values["hosts"] = f"{_text_value(hosts)} (+{total - len(hosts)})"
    reading = tamper_reading(v, lang)
    text = translate(lang, v.message_key, values)
    return f"{text} {reading}" if reading else text


def caveats(v: AlertView, lang: Language) -> list[str]:
    """What the reader must weigh (anti-goal 8): late data, a gap in the window, partial field coverage."""
    out = []
    if v.late:
        out.append(translate(lang, "alert_msg_late"))
    c = v.confidence
    if c.get("incomplete_gaps"):
        out.append(translate(lang, "alert_msg_incomplete"))
    if c.get("field") and c.get("total"):
        out.append(translate(lang, "alert_msg_coverage", {"covered": str(c.get("covered") or 0),
                                                           "total": str(c["total"])}))
    return out


def _line(v: AlertView, lang: Language, tz: tzinfo | None, label: str | None) -> str:
    sev = translate(lang, SEVERITY_KEYS[v.severity])
    parts = [f"[{sev}] {rule_title(v, lang)} — {summary(v, lang)}", _when(v.fired_at, tz, label)]
    parts += caveats(v, lang)
    return " · ".join(parts)


def subject(alerts: Sequence[AlertView], lang: Language) -> str:
    top = max(alerts, key=lambda a: list(SEVERITY_KEYS).index(a.severity))
    sev = translate(lang, SEVERITY_KEYS[top.severity]).upper()
    more = f" (+{len(alerts) - 1})" if len(alerts) > 1 else ""
    return f"[illumio-ops] {sev} {rule_title(top, lang)}{more}"


def _fit(lines: list[str], limit: int, lang: Language, *, escape: bool) -> str:
    """Whole alerts while they fit, then one line saying how many are left; a single alert longer than the limit
    is cut and marked."""
    out: list[str] = []
    used = 0
    for i, raw in enumerate(lines):
        line = html.escape(raw) if escape else raw
        rest = len(lines) - i
        tail = translate(lang, "alert_msg_more", {"n": str(rest)})
        reserve = len(tail) + 1 if rest > 1 else 0
        if used + len(line) + 1 + reserve <= limit:
            out.append(line)
            used += len(line) + 1
            continue
        if not out:  # the first alert alone is too long: keep what fits of it
            mark = translate(lang, "alert_msg_truncated")
            room = limit - len(mark) - reserve - 2
            cut = raw
            while len(html.escape(cut) if escape else cut) > room:
                cut = cut[:max(0, len(cut) - max(1, len(cut) // 10))]
            out.append((html.escape(cut) if escape else cut) + " " + mark)
            if rest > 1:
                out.append(translate(lang, "alert_msg_more", {"n": str(rest - 1)}))
            return "\n".join(out)
        out.append(tail)
        return "\n".join(out)
    return "\n".join(out)


def render(alerts: Sequence[AlertView], channel: ChannelKind, *, lang: Language, tz: tzinfo | None,
           console_url: str | None, tz_label: str | None = None) -> Rendered:
    subj = subject(alerts, lang)
    lines = [_line(a, lang, tz, tz_label) for a in alerts]
    if channel in LIMITS:
        escape = channel is ChannelKind.TELEGRAM
        head = html.escape(subj) if escape else subj
        body = _fit(lines, LIMITS[channel] - len(head) - 1, lang, escape=escape)
        return Rendered(subject=subj, text=f"{head}\n{body}", html=None, card=None, payload=None)
    cap = MAX_ITEMS[channel]
    shown, rest = list(alerts[:cap]), max(0, len(alerts) - cap)
    more = translate(lang, "alert_msg_more", {"n": str(rest)}) if rest else None
    if channel is ChannelKind.TEAMS:
        items: list[dict[str, Any]] = [{"type": "TextBlock", "text": translate(lang, "alert_card_title",
                                                                              {"n": str(len(alerts))}),
                                        "weight": "Bolder", "size": "Medium", "wrap": True}]
        # Alert lines carry PCE data (hostnames, users, processes): a TextBlock would render Markdown in them, so
        # they go in TextRuns, which Teams shows as plain text.
        items += [{"type": "RichTextBlock", "inlines": [{"type": "TextRun", "text": _line(a, lang, tz, tz_label)}]}
                  for a in shown]
        if more:
            items.append({"type": "RichTextBlock", "inlines": [{"type": "TextRun", "text": more, "isSubtle": True}]})
        card = {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                        "version": "1.4", "body": items}}]}
        return Rendered(subject=subj, text="\n".join(lines[:cap]), html=None, card=card, payload=None)
    if channel is ChannelKind.SMTP:
        plain = "\n".join([subj, "", *lines[:cap], *([more] if more else []),
                           *([translate(lang, "alert_msg_console", {"url": console_url})] if console_url else [])])
        rows = "".join(f"<li>{html.escape(line)}</li>" for line in lines[:cap])
        foot = f"<p>{html.escape(more)}</p>" if more else ""
        link = (f'<p><a href="{html.escape(console_url)}">{html.escape(translate(lang, "alert_msg_console_link"))}</a></p>'
                if console_url else "")
        page = (f'<html><body><h2>{html.escape(subj)}</h2><ul>{rows}</ul>{foot}{link}</body></html>')
        return Rendered(subject=subj, text=plain, html=page, card=None, payload=None)
    payload = {"subject": subj, "truncated": rest, "alerts": [
        {"id": a.id, "rule": rule_title(a, lang), "severity": a.severity.value, "subject": a.subject_key,
         "fired_at": a.fired_at.isoformat(), "late": a.late, "summary": summary(a, lang),
         "facts": dict(a.facts), "caveats": caveats(a, lang)} for a in shown]}
    return Rendered(subject=subj, text="\n".join(lines[:cap]), html=None, card=None, payload=payload)
