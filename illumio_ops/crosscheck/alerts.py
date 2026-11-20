"""Event-rule alerts against the PCE's events (spec §4.2), at rule level (the alert's host is not compared).

The rules are read from the settings as plain values and matched by a matcher of our own, simpler than the product's:
event types as exact names, `a|b` or `*`; status and severity as anything (`""`, `*`, `any`, `all`, any case), one
value or `a|b`, with `error` = `err` for severity. A rule using a regular expression, `!` or match_fields is not
checked (it is listed as unchecked with the reason).

Every matching PCE event must be explained: inside one of the rule's alerts ([first_seen, last_seen]); inside the
cooldown or throttle of an earlier alert of the same rule; before evaluation started; or one the product never
evaluates (not evaluated yet, backfilled history, below a count rule's threshold at its time). Otherwise it is a
possible missed alert. Every alert needs a matching PCE event within its [first_seen, last_seen], and a count
rule's alert needs threshold_count matches in [fired_at − window, fired_at].
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from illumio_ops.crosscheck import events
from illumio_ops.crosscheck.io import open_ro
from illumio_ops.crosscheck.model import Finding, Run
from illumio_ops.pce.timefmt import pce_time

AREA = "alerts"
SOURCE = "events"  # the evaluation watermark's key in alert_eval_state
SAMPLE_MAX = 50
HREF_CHUNK = 500
# How far before the period alerts are read: cooldown and a throttle period are at most 7 days (the rule schema).
LOOKBACK = timedelta(days=8)
ANY = frozenset({"", "*", "any", "all"})
ANY_TYPE = frozenset({"*", ".*", ""})
SEVERITY_ALIASES = {"error": "err"}

# What explains a matching event, in the order they are tried (counted per rule in the report).
IN_ALERT = "in an alert"
COOLDOWN = "cooldown"
THROTTLE = "throttle"
BEFORE_START = "before evaluation start"
NOT_YET = "not evaluated yet"
BACKFILLED = "backfilled"
BELOW = "below threshold"
NOT_JUDGED = "not judged"  # a count rule's window at the event reaches past the period or into an unread PCE window
EXPLANATIONS = (IN_ALERT, COOLDOWN, THROTTLE, BEFORE_START, NOT_YET, BACKFILLED, BELOW)


# ── rules and the matcher ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    id: str
    name: str  # the rule's name, or its pack_key for a built-in rule (name "")
    event_types: tuple[str, ...]
    status: str
    severity: str
    match_fields: Mapping[str, Any]
    count: bool  # threshold "count"; otherwise "immediate"
    threshold_count: int
    window: timedelta
    cooldown: timedelta
    throttle_count: int | None
    throttle_period: timedelta | None

    @classmethod
    def from_settings(cls, r: Mapping[str, Any]) -> Rule:
        throttle = r.get("throttle") or None
        return cls(id=str(r["id"]), name=str(r.get("name") or r.get("pack_key") or r["id"]),
                   event_types=tuple(str(t).strip() for t in r["event_types"]), status=str(r["status"]).strip(),
                   severity=str(r["event_severity"]).strip(), match_fields=dict(r.get("match_fields") or {}),
                   count=r["threshold"] == "count", threshold_count=int(r["threshold_count"]),
                   window=timedelta(minutes=int(r["window_minutes"])),
                   cooldown=timedelta(minutes=int(r["cooldown_minutes"])),
                   throttle_count=int(throttle["count"]) if throttle else None,
                   throttle_period=timedelta(minutes=int(throttle["period_minutes"])) if throttle else None)


def _regexy(p: str) -> bool:
    """What the product treats as a regular expression (written again here, not imported)."""
    if p.startswith("^") or p.endswith("$") or any(c in p for c in "*+?[](){}$\\"):
        return True
    return any(token in p for token in (".*", ".+", ".?"))


def _value_reason(p: str) -> str | None:
    if p.lower() in ANY:
        return None
    if p.startswith("!"):
        return "negation (!)"
    if _regexy(p):
        return "a regular expression"
    return None


def unsupported(rule: Rule) -> str | None:
    """None when this matcher covers the rule; otherwise why it does not."""
    for p in rule.event_types:
        if p in ANY_TYPE:
            continue
        if p.startswith("!"):
            return f"event type {p!r} uses negation (!)"
        if _regexy(p):
            return f"event type {p!r} is a regular expression"
    for what, p in (("status", rule.status), ("event severity", rule.severity)):
        why = _value_reason(p)
        if why is not None:
            return f"{what} {p!r} uses {why}"
    if rule.match_fields:
        return f"match_fields ({', '.join(sorted(rule.match_fields))})"
    return None


def _canon_severity(v: str | None) -> str:
    t = (v or "").strip().lower()
    return SEVERITY_ALIASES.get(t, t)


def _value_ok(pattern: str, value: str | None, *, severity: bool) -> bool:
    if pattern.lower() in ANY:
        return True
    if severity:
        return _canon_severity(value) in {_canon_severity(x) for x in pattern.split("|")}
    return (value or "") in pattern.split("|")


def matches(rule: Rule, e: events.PceEvent) -> bool:
    if not any(p in ANY_TYPE or e.event_type in p.split("|") for p in rule.event_types):
        return False
    return _value_ok(rule.status, e.status, severity=False) and _value_ok(rule.severity, e.severity, severity=True)


# ── what the databases hold ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Alert:
    rule_id: str
    subject_key: str
    fired_at: datetime
    first_seen: datetime
    last_seen: datetime


@dataclass(frozen=True)
class Watermark:
    """Where the product's event evaluation got to (alert_eval_state). It is progress, not a start: the product keeps
    no record of where evaluation began. `after_id`: stored events with a higher id are not evaluated yet. `after_time`
    (a 5.x upgrade's "t:<time>"): 5.x evaluated up to it, the stored events after it are not evaluated yet."""
    raw: str | None
    after_id: int | None
    after_time: datetime | None
    note: str


@dataclass(frozen=True)
class Stored:
    id: int
    origin: str


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t.astimezone(UTC) if t.tzinfo is not None else None


def _alerts(run: Run) -> tuple[list[Alert], int, Watermark]:
    """This PCE's event-rule alerts fired since LOOKBACK before the period, how many rows could not be read, and the
    evaluation watermark (with the time of the event an id watermark points at, for the reader)."""
    p = run.settings.pce
    lo = (run.start - LOOKBACK).strftime("%Y-%m-%d")  # stored times start with the ISO date
    conn = open_ro(run.paths.app_db)
    try:
        rows = conn.execute("SELECT rule_id, subject_key, fired_at, first_seen, last_seen FROM alerts "
                            "WHERE pce_url = ? AND org_id = ? AND rule_type = 'event' AND fired_at >= ?",
                            (p.url, p.org_id, lo)).fetchall()
        mark = conn.execute("SELECT pce_url, org_id, watermark FROM alert_eval_state WHERE source = ?",
                            (SOURCE,)).fetchone()
    finally:
        conn.close()
    out, bad = [], 0
    for rule_id, subject, fired, first, last in rows:
        f, a, b = _time(fired), _time(first), _time(last)
        if f is None or a is None or b is None:
            bad += 1
            continue
        out.append(Alert(str(rule_id), str(subject), f, a, b))
    if mark is None or (mark[0], mark[1]) != (p.url, p.org_id):
        return out, bad, Watermark(None, None, None, "no evaluation watermark for this PCE: nothing evaluated yet")
    raw = str(mark[2])
    if raw.startswith("t:"):
        t = _time(raw[2:])
        note = f"watermark {raw!r}: an upgrade from 5.x, which evaluated the events up to that time"
        return out, bad, Watermark(raw, None, t, note if t is not None else f"watermark {raw!r} cannot be read")
    try:
        after = int(raw)
    except ValueError:
        return out, bad, Watermark(raw, None, None, f"watermark {raw!r} cannot be read")
    return out, bad, Watermark(raw, after, None, f"watermark: stored event id {after}")


def _watermark_time(run: Run, wm: Watermark) -> str:
    if wm.after_id is None:
        return ""
    try:
        conn = open_ro(run.paths.flows_db)
    except sqlite3.Error:
        return ""
    try:
        row = conn.execute("SELECT timestamp FROM events WHERE id = ?", (wm.after_id,)).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    t = _time(row[0]) if row else None
    return f" (the event stored at {pce_time(t)})" if t is not None else " (that event is no longer stored)"


def _stored(run: Run, hrefs: Sequence[str]) -> dict[str, Stored] | str:
    """href -> (id, origin) of the events this system stored, or why that cannot be read."""
    try:
        conn = open_ro(run.paths.flows_db)
    except sqlite3.Error as exc:
        return f"the flow database cannot be opened: {exc}"
    try:
        bound = conn.execute("SELECT pce_url, org_id FROM pce_binding WHERE id = 1").fetchone()
        p = run.settings.pce
        if bound is None or (str(bound[0]).rstrip("/"), str(bound[1])) != (p.url.rstrip("/"), p.org_id):
            return "the flow database is not bound to this PCE"
        out: dict[str, Stored] = {}
        for i in range(0, len(hrefs), HREF_CHUNK):
            chunk = list(hrefs[i:i + HREF_CHUNK])
            for href, eid, origin in conn.execute(
                    f"SELECT href, id, origin FROM events WHERE href IN ({','.join('?' * len(chunk))})", chunk):
                out[str(href)] = Stored(int(eid), str(origin))
        return out
    except sqlite3.Error as exc:
        return f"the flow database cannot be read: {exc}"
    finally:
        conn.close()


# ── per rule ─────────────────────────────────────────────────────────────────

def _ident(e: events.PceEvent) -> dict[str, str]:
    return {"href": e.href, "event_type": e.event_type, "timestamp": e.raw_timestamp}


def _within(alert_list: Sequence[Alert], a: datetime, b: datetime) -> list[Alert]:
    return [x for x in alert_list if a <= x.fired_at <= b]


@dataclass
class _Context:
    run: Run
    watermark: Watermark
    stored: dict[str, Stored] | None  # None: the store cannot be read (misses are then not judged)
    store_reason: str
    unread: list[events.Slice]
    alert_floor: datetime | None  # alerts fired before it are deleted by the alert retention
    watermark_text: str = ""  # the evaluation watermark, for the reader of a set-aside count

    def unread_overlaps(self, a: datetime, b: datetime) -> bool:
        return any(s.start <= b and a < s.end + events.ONE_SECOND for s in self.unread)


def _explain(rule: Rule, e: events.PceEvent, mine: Sequence[Alert], matched: Sequence[events.PceEvent],
             cx: _Context) -> str | None:
    t = e.timestamp
    if any(a.first_seen <= t <= a.last_seen for a in mine):
        return IN_ALERT
    # Narrow on purpose: only an alert of this same rule fired before the event, the event inside its cooldown.
    if rule.cooldown and any(a.fired_at < t < a.fired_at + rule.cooldown for a in mine):
        return COOLDOWN
    if rule.throttle_count is not None and rule.throttle_period is not None:
        recent = [a for a in mine if t - rule.throttle_period < a.fired_at < t]
        if len(recent) >= rule.throttle_count:  # the throttle was full at the event's time
            return THROTTLE
    wm = cx.watermark
    if wm.after_time is not None:
        return BEFORE_START if t <= wm.after_time else NOT_YET
    if wm.raw is None:
        return NOT_YET
    s = cx.stored.get(e.href) if cx.stored is not None else None
    if s is not None:
        if s.origin == "backfill":
            return BACKFILLED  # a backfill's history is never evaluated (spec §7)
        if wm.after_id is not None and s.id > wm.after_id:
            return NOT_YET
    if rule.count:
        lo = t - rule.window
        n = sum(1 for m in matched if lo <= m.timestamp <= t)
        if n < rule.threshold_count:
            # an under-count is only trusted when the whole window was read
            return NOT_JUDGED if lo < cx.run.start or cx.unread_overlaps(lo, t) else BELOW
    return None


def _rule(rule: Rule, evs: Sequence[events.PceEvent], all_alerts: Sequence[Alert], cx: _Context) -> list[Finding]:
    run = cx.run
    item = f"rule {rule.name}"
    matched = sorted((e for e in evs if matches(rule, e)), key=lambda e: (e.timestamp, e.href))
    mine = [a for a in all_alerts if a.rule_id == rule.id]
    in_period = [a for a in mine if run.start <= a.first_seen < run.end]
    counts: Counter[str] = Counter()
    misses: list[events.PceEvent] = []
    miss_reason = ""
    if not run.settings.collection.enabled:
        miss_reason = "event collection is switched off in the settings"
    elif cx.stored is None:
        miss_reason = cx.store_reason
    elif not rule.count and rule.threshold_count > 1:
        miss_reason = (f"the rule fires on {rule.threshold_count} events of one host in one evaluation; which events "
                       "were evaluated together cannot be known from here")
    for e in matched:
        if cx.alert_floor is not None and e.timestamp < cx.alert_floor:
            counts["past alert retention"] += 1
            continue
        why = _explain(rule, e, mine, matched, cx)
        if why is not None:
            counts[why] += 1
        elif miss_reason:
            counts[NOT_JUDGED] += 1
        else:
            misses.append(e)

    unsupported_alerts, short, not_judged = [], [], 0
    for a in in_period:
        if any(a.first_seen <= e.timestamp <= a.last_seen for e in matched):
            pass
        elif a.last_seen >= run.end or cx.unread_overlaps(a.first_seen, a.last_seen):
            not_judged += 1
        else:
            unsupported_alerts.append({"fired_at": a.fired_at.isoformat(), "first_seen": a.first_seen.isoformat(),
                                       "last_seen": a.last_seen.isoformat(), "subject_key": a.subject_key})
        if rule.count:
            lo, hi = a.fired_at - rule.window, a.fired_at
            if lo < run.start or hi >= run.end or cx.unread_overlaps(lo, hi):
                not_judged += 1
                continue
            n = sum(1 for e in matched if lo <= e.timestamp <= hi)
            if n < rule.threshold_count:
                short.append({"fired_at": a.fired_at.isoformat(), "matches": n, "threshold": rule.threshold_count})

    totals = (f"{len(matched)} matching PCE events, {len(in_period)} alerts in the period; explained: "
              + ", ".join(f"{k} {counts[k]}" for k in EXPLANATIONS)
              + f"; not judged {counts[NOT_JUDGED]}; past alert retention {counts['past alert retention']}"
              + f"; alerts not judged {not_judged}.")
    out: list[Finding] = []
    # Events set aside without being compared are said as unchecked, never folded into a consistent total.
    aside = [f"{n} {what}" for what, n in ((NOT_YET, counts[NOT_YET]), (BEFORE_START, counts[BEFORE_START]),
                                           ("past alert retention", counts["past alert retention"]),
                                           (NOT_JUDGED, counts[NOT_JUDGED])) if n]
    if miss_reason or aside:
        reasons = [f"misses not judged: {miss_reason}"] if miss_reason else []
        if aside:
            reasons.append(f"matching events set aside without a comparison: {', '.join(aside)}{cx.watermark_text}")
        out.append(Finding(AREA, f"{item}: possible missed alert", "unchecked", f"{'; '.join(reasons)}. {totals}"))
    if misses:
        unreceived = sum(1 for e in misses if cx.stored is not None and e.href not in cx.stored)
        out.append(Finding(AREA, f"{item}: possible missed alert", "inconsistent",
                           f"{len(misses)} matching PCE events with no alert and no explanation ({unreceived} of them "
                           f"not in this system's events){_first(len(misses))}. {totals}",
                           sample=[{**_ident(e), "received": cx.stored is not None and e.href in cx.stored}
                                   for e in misses[:SAMPLE_MAX]]))
    if unsupported_alerts:
        out.append(Finding(AREA, f"{item}: alert without a supporting event", "inconsistent",
                           f"{len(unsupported_alerts)} alerts with no matching PCE event within their first and last "
                           f"seen{_first(len(unsupported_alerts))}. {totals}", sample=unsupported_alerts[:SAMPLE_MAX]))
    if short:
        out.append(Finding(AREA, f"{item}: below threshold", "inconsistent",
                           f"{len(short)} alerts with fewer than {rule.threshold_count} matching PCE events in the "
                           f"{int(rule.window.total_seconds() // 60)} minutes before they fired{_first(len(short))}. "
                           f"{totals}", sample=short[:SAMPLE_MAX]))
    if not any(f.status == "inconsistent" for f in out):
        out.append(Finding(AREA, item, "consistent", totals))
    return out


def _first(n: int) -> str:
    return f" (the first {SAMPLE_MAX} of {n} below)" if n > SAMPLE_MAX else ""


def check(run: Run) -> list[Finding]:
    rules = [Rule.from_settings(r.model_dump(mode="json")) for r in run.settings.alerts.rules
             if r.type == "event" and r.enabled]
    if not rules:
        return [Finding(AREA, "event rules", "unchecked", "no event rule is enabled: nothing to compare")]
    h = events.gather(run)
    _raws, evs = events.in_period(run, h)
    all_alerts, bad_rows, wm = _alerts(run)
    wm_time = _watermark_time(run, wm)
    findings: list[Finding] = []
    findings.append(Finding(
        AREA, "evaluation start", "unchecked",
        "the product keeps no record of where event evaluation began, so the period start "
        f"({pce_time(run.start)}) is used and no event is explained as earlier than it (except under a 5.x "
        f"upgrade's time watermark); {wm.note}{wm_time}. Rules are compared as they are now: "
        "the settings keep no history, so a rule added or changed during the period may show misses before that."))
    if bad_rows:
        findings.append(Finding(AREA, "unreadable alerts", "unchecked",
                                f"{bad_rows} alert rows with a time this check cannot read"))
    checked: list[Rule] = []
    for r in rules:
        why = unsupported(r)
        if why is None:
            checked.append(r)
        else:
            findings.append(Finding(AREA, f"rule {r.name}", "unchecked", f"not checked: {why}"))
    candidates = [e.href for e in evs if any(matches(r, e) for r in checked)]
    stored = _stored(run, candidates)
    days = run.settings.alerts.retention_days
    cx = _Context(run=run, watermark=wm, stored=stored if isinstance(stored, dict) else None,
                  store_reason=stored if isinstance(stored, str) else "", unread=list(h.unchecked),
                  alert_floor=run.now - timedelta(days=days) if days else None,
                  watermark_text=f" ({wm.note}{wm_time})")
    if h.unchecked:
        findings.append(Finding(AREA, "unread PCE windows", "unchecked",
                                f"{len(h.unchecked)} windows of the period could not be read from the PCE (listed under "
                                "events); a missed alert for an event inside them cannot be found here"))
    for r in checked:
        findings += _rule(r, evs, all_alerts, cx)
    ids = {r.id for r in rules}
    other = [a for a in all_alerts if a.rule_id not in ids and run.start <= a.first_seen < run.end]
    if other:
        findings.append(Finding(AREA, "alerts of rules not enabled now", "unchecked",
                                f"{len(other)} event-rule alerts in the period belong to rules that are not enabled "
                                "now (or no longer exist); they are not compared"))
    return findings
