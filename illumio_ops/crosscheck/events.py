"""Events: every PCE event of the period vs the built-in event catalog vs the events this system received.

Independent of the product's event code: the PCE's raw JSON is read here (href, event_type, timestamp, status,
severity), and the flow database's `events` table is read read-only by href and timestamp.

Samples carry identifiers only (href, event_type, timestamp) and field names, never other values.
"""
from __future__ import annotations

import sqlite3
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from illumio_ops.crosscheck.io import open_ro
from illumio_ops.crosscheck.model import Finding, Run
from illumio_ops.domain.event_catalog import catalog
from illumio_ops.domain.values import DeploymentType
from illumio_ops.pce.client import PceBudgetExhausted, PceClient, PceTransportError
from illumio_ops.pce.timefmt import pce_time

AREA = "events"
CAP = 10_000  # the PCE's max_results for /events; at the cap it returns only the newest events of the window
RETRIES = 3
RETRY_WAIT = 2.0
RETRYABLE = frozenset({429, 500, 502, 503, 504})
SAMPLE_MAX = 50
HREF_CHUNK = 500
# A collection cycle runs every events_interval_seconds and reads up to the moment it starts; this much more is
# allowed for the cycle itself before an event counts as one it should already have.
CYCLE_SLACK = timedelta(minutes=5)
ONE_SECOND = timedelta(seconds=1)

_sleep = time.sleep  # module-level so tests do not wait


class EventsUnavailable(Exception):
    """The PCE refused the request (401/403) or no window at all could be read: the area cannot run."""


@dataclass(frozen=True)
class Slice:
    start: datetime
    end: datetime
    reason: str


@dataclass
class Harvest:
    items: list[dict[str, Any]] = field(default_factory=list)  # unique by href (items without one are all kept)
    unchecked: list[Slice] = field(default_factory=list)
    requests: int = 0
    windows: int = 0


@dataclass(frozen=True)
class PceEvent:
    href: str
    event_type: str
    timestamp: datetime
    raw_timestamp: str
    status: str | None
    severity: str | None
    fields: tuple[str, ...]


def _fetch(client: PceClient, a: datetime, b: datetime, *, timeout: float, cap: int,
           h: Harvest) -> list[dict[str, Any]] | str:
    """The events of [a, b], or why they could not be read. Timeouts, 429, 5xx and an empty request budget are
    retried RETRIES times; another transport failure propagates (the PCE cannot be reached at all)."""
    query = urlencode({"timestamp[gte]": pce_time(a), "timestamp[lte]": pce_time(b), "max_results": str(cap)})
    reason = ""
    for attempt in range(RETRIES + 1):
        if attempt:
            _sleep(RETRY_WAIT * attempt)
        h.requests += 1
        try:
            # bounded: one attempt per call, so these retries are the only ones
            resp = client.request("GET", f"/events?{query}", timeout=timeout, bounded=True)
        except PceTransportError as exc:
            if exc.kind != "timeout":
                raise
            reason = "timed out"
            continue
        except PceBudgetExhausted:
            reason = "no request budget"
            continue
        if resp.status in (401, 403):
            raise EventsUnavailable(f"the PCE refused /events with HTTP {resp.status}")
        if resp.status == 200:
            try:
                items = resp.json()
            except ValueError:
                return "the response is not JSON"
            if not isinstance(items, list):
                return "the response is not a list"
            return [i for i in items if isinstance(i, dict)]
        reason = f"HTTP {resp.status}"
        if resp.status not in RETRYABLE:
            return reason
    return f"{reason} after {RETRIES} retries"


def harvest(client: PceClient, start: datetime, end: datetime, *, timeout: float, cap: int = CAP) -> Harvest:
    """Every event of [start, end]: a window that comes back full is halved (whole seconds, sharing the boundary
    second) until it is not; a full window of one second or less is kept but listed as unchecked."""
    h = Harvest()
    by_href: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    read = 0
    pending = [(start, end)]
    while pending:
        a, b = pending.pop()
        got = _fetch(client, a, b, timeout=timeout, cap=cap, h=h)
        if isinstance(got, str):
            h.unchecked.append(Slice(a, b, got))
            continue
        read += 1
        if len(got) >= cap:
            half = timedelta(seconds=int((b - a).total_seconds()) // 2)
            if half >= ONE_SECOND:
                pending += [(a, a + half), (a + half, b)]
                continue
            h.unchecked.append(Slice(a, b, f"{len(got)} events within one second, the PCE's limit per request: "
                                           "the others of that second cannot be read"))
        h.windows += 1
        for item in got:
            href = item.get("href")
            if isinstance(href, str) and href:
                by_href.setdefault(href, item)
            else:
                anonymous.append(item)
    if read == 0:
        raise EventsUnavailable("no window of the period could be read: "
                                + "; ".join(sorted({s.reason for s in h.unchecked})))
    h.items = list(by_href.values()) + anonymous
    return h


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t.astimezone(UTC) if t.tzinfo is not None else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse(raw: dict[str, Any]) -> PceEvent | None:
    """The fields compared here, or None when href, event_type or timestamp is missing or unreadable."""
    href, event_type, ts = _text(raw.get("href")), _text(raw.get("event_type")), _parse_time(raw.get("timestamp"))
    if href is None or event_type is None or ts is None:
        return None
    return PceEvent(href, event_type, ts, str(raw["timestamp"]), _text(raw.get("status")),
                    _text(raw.get("severity")), tuple(sorted(raw)))


def _ident(e: PceEvent) -> dict[str, str]:
    return {"href": e.href, "event_type": e.event_type, "timestamp": e.raw_timestamp}


def _n(count: int, what: str) -> str:
    return f"{count} {what}{'' if count == 1 else 's'}"


def _span(a: datetime, b: datetime) -> str:
    return f"{pce_time(a)} to {pce_time(b)}"


def _samples(count: int) -> str:
    return f" (the first {SAMPLE_MAX} of {count} below)" if count > SAMPLE_MAX else ""


def _incomplete(raws: Iterable[dict[str, Any]]) -> Finding | None:
    bad = []
    for raw in raws:
        missing = [k for k, ok in (("href", _text(raw.get("href"))), ("event_type", _text(raw.get("event_type"))),
                                   ("timestamp", _parse_time(raw.get("timestamp")))) if ok is None]
        if missing:
            bad.append({"missing_or_unreadable": missing, "fields": sorted(str(k) for k in raw)})
    if not bad:
        return None
    return Finding(AREA, "incomplete PCE events", "unchecked",
                   f"{_n(len(bad), 'PCE event')} without a readable href, event_type or timestamp could not be "
                   f"compared{_samples(len(bad))}", sample=bad[:SAMPLE_MAX])


def _catalog(evs: Sequence[PceEvent], *, partial: bool, read: str) -> list[Finding]:
    known = {c.event_type for c in catalog()}
    counts = Counter(e.event_type for e in evs)
    first: dict[str, PceEvent] = {}
    for e in sorted(evs, key=lambda e: (e.timestamp, e.href)):
        first.setdefault(e.event_type, e)
    out = []
    for t in sorted(set(counts) - known):
        e = first[t]
        out.append(Finding(AREA, f"catalog: {t}", "inconsistent",
                           f"{_n(counts[t], 'PCE event')} of a type the built-in event catalog does not list",
                           sample={**_ident(e), "fields": list(e.fields)}))
    seen = set(counts) & known
    note = " Some windows could not be read (listed as unchecked), so more types may have occurred." if partial else ""
    out.append(Finding(AREA, "catalog", "consistent",
                       f"{len(seen)} of the catalog's {len(known)} types occurred in the period; "
                       f"{len(known - seen)} did not appear in the period (not an error). {read}{note}"))
    return out


def _db_time_bounds(a: datetime, b: datetime) -> tuple[str, str]:
    """Day strings around [a, b): stored timestamps start with the ISO date, whatever follows, so text order by
    day prefix is safe; rows are then filtered on their parsed time."""
    return (a - timedelta(days=1)).strftime("%Y-%m-%d"), (b + timedelta(days=2)).strftime("%Y-%m-%d")


def _known_hrefs(conn: sqlite3.Connection, hrefs: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for i in range(0, len(hrefs), HREF_CHUNK):
        chunk = list(hrefs[i:i + HREF_CHUNK])
        out |= {r[0] for r in conn.execute(
            f"SELECT href FROM events WHERE href IN ({','.join('?' * len(chunk))})", chunk)}
    return out


def _store(run: Run, evs: Sequence[PceEvent], h: Harvest) -> list[Finding]:
    item = "received"
    c = run.settings.collection
    if not c.enabled:
        return [Finding(AREA, item, "unchecked", "event collection is switched off in the settings (as they are "
                                                 "now; the settings keep no history)")]
    floor = max(run.start, run.now - timedelta(days=c.retention.event_days))
    ceiling = min(run.end, run.now - timedelta(seconds=c.events_interval_seconds) - CYCLE_SLACK)
    out: list[Finding] = []
    if floor > run.start:
        n = sum(1 for e in evs if run.start <= e.timestamp < floor)
        out.append(Finding(AREA, f"{item}: outside retention", "unchecked",
                           f"{_span(run.start, floor)}: older than the {c.retention.event_days}-day event retention, "
                           f"so not kept here; {_n(n, 'PCE event')} there not compared"))
    if ceiling < run.end:
        n = sum(1 for e in evs if max(ceiling, run.start) <= e.timestamp < run.end)
        out.append(Finding(AREA, f"{item}: not collected yet", "unchecked",
                           f"{_span(max(ceiling, run.start), run.end)}: events are collected every "
                           f"{c.events_interval_seconds} s, so this end of the period may not be collected yet; "
                           f"{_n(n, 'PCE event')} there not compared"))
    if ceiling <= floor:
        return out + [Finding(AREA, item, "unchecked", "no part of the period is both kept and already collected")]
    try:
        conn = open_ro(run.paths.flows_db)
    except sqlite3.Error as exc:
        return out + [Finding(AREA, item, "unchecked", f"the flow database cannot be opened: {exc}")]
    try:
        bound = conn.execute("SELECT pce_url, org_id FROM pce_binding WHERE id = 1").fetchone()
        if bound is None:
            return out + [Finding(AREA, item, "unchecked", "the flow database is not bound to a PCE yet "
                                                           "(nothing has been collected)")]
        if (str(bound[0]).rstrip("/"), str(bound[1])) != (run.settings.pce.url.rstrip("/"), run.settings.pce.org_id):
            return out + [Finding(AREA, item, "unchecked", "the flow database holds another PCE's data "
                                                           f"({bound[0]}, org {bound[1]})")]
        lo, hi = _db_time_bounds(floor, ceiling)
        rows = conn.execute("SELECT href, event_type, timestamp FROM events WHERE timestamp >= ? AND timestamp < ?",
                            (lo, hi)).fetchall()
        mine = [e for e in evs if floor <= e.timestamp < ceiling]
        found = _known_hrefs(conn, [e.href for e in mine])
    except sqlite3.Error as exc:
        return out + [Finding(AREA, item, "unchecked", f"the flow database cannot be read: {exc}")]
    finally:
        conn.close()

    def unread(t: datetime) -> bool:  # inside a window the PCE could not (fully) give
        return any(s.start <= t < s.end + ONE_SECOND for s in h.unchecked)

    pce_hrefs = {e.href for e in evs}
    extra, bad_time = [], 0
    for href, event_type, ts in rows:
        t = _parse_time(ts)
        if t is None:
            bad_time += 1
            continue
        if floor <= t < ceiling and not unread(t) and href not in pce_hrefs:
            extra.append({"href": href, "event_type": event_type, "timestamp": ts})
    missing = sorted((e for e in mine if e.href not in found), key=lambda e: (e.timestamp, e.href))
    window = _span(floor, ceiling)
    if missing:
        out.append(Finding(AREA, f"{item}: not received by this system", "inconsistent",
                           f"{_n(len(missing), 'PCE event')} in {window} not in this system's events"
                           f"{_samples(len(missing))}", sample=[_ident(e) for e in missing[:SAMPLE_MAX]]))
    if extra:
        extra.sort(key=lambda r: (r["timestamp"], r["href"]))
        out.append(Finding(AREA, f"{item}: not on the PCE", "inconsistent",
                           f"{_n(len(extra), 'stored event')} in {window} the PCE did not return; the PCE may have "
                           f"deleted them, a person has to judge{_samples(len(extra))}", sample=extra[:SAMPLE_MAX]))
    if bad_time:
        out.append(Finding(AREA, f"{item}: unreadable stored time", "unchecked",
                           f"{_n(bad_time, 'stored event')} with a timestamp this check cannot read"))
    both = len(mine) - len(missing)
    out.append(Finding(AREA, item, "consistent",
                       f"{_n(both, 'event')} in {window} are both on the PCE and in this system (by href)"))
    return out


def _timeout(run: Run) -> float:
    p = run.settings.pce
    if p.events_timeout_seconds is not None:
        return float(p.events_timeout_seconds)
    return 180.0 if p.deployment_type is DeploymentType.SAAS else 30.0  # SaaS /events answers slowly


def check(run: Run, *, cap: int = CAP) -> list[Finding]:
    h = harvest(run.pce, run.start, run.end, timeout=_timeout(run), cap=cap)
    findings = [Finding(AREA, f"PCE window {_span(s.start, s.end)}", "unchecked", s.reason) for s in h.unchecked]
    in_period = [r for r in h.items if (t := _parse_time(r.get("timestamp"))) is None or run.start <= t < run.end]
    inc = _incomplete(in_period)
    if inc is not None:
        findings.append(inc)
    evs = [e for e in (parse(r) for r in in_period) if e is not None]
    read = (f"Read from the PCE: {_n(len(evs), 'event')} in the period, {_n(h.windows, 'window')}, "
            f"{_n(h.requests, 'request')}.")
    findings += _catalog(evs, partial=bool(h.unchecked), read=read)
    findings += _store(run, evs, h)
    return findings
