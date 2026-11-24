"""Report numbers: the latest finished report of each type for this PCE, its KPIs recomputed from raw PCE data in
that report's own period (spec §4.3, appendix A), and compared.

What is read from the PCE: events (GET /events, as the events area reads them), traffic through async traffic
queries, the draft recompute (PUT update_rules on a query this tool created) and the draft rule sets (GET). Every
query this tool creates is deleted in `finally`; one that cannot be deleted is listed as a leftover in report.md.
Windows never cross a UTC midnight: the PCE keeps traffic by UTC day, and a window over two days sums them.
"""
from __future__ import annotations

import gzip
import json
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from illumio_ops.crosscheck import events, kpis
from illumio_ops.crosscheck.io import open_ro, pce_target
from illumio_ops.crosscheck.model import Finding, Run
from illumio_ops.pce.async_query import FAILED_STATES, traffic_payload
from illumio_ops.pce.client import PceBudgetExhausted, PceClient, PceTransportError
from illumio_ops.pce.timefmt import pce_time

AREA = "reports"
F_MAX_RESULTS = 200_000  # a traffic query of the flow reports' kind (the collector's limit)
D_MAX_RESULTS = 50_000   # a draft recompute (policy usage and readiness ask for this many)
MAX_SPLITS = 3           # a window at the limit is halved this many times at most
# A plain GET of a collection stops at 500 items whatever max_results asks (the product then reads it as an async
# collection: pce/collections.py PAGE_LIMIT, lab 2026: 500 rows back while 124,255 matched). This version does not:
# a full page is not compared.
GET_PAGE_LIMIT = 500
QUERY_DEADLINE_SECONDS = 900.0
POLL_START, POLL_FACTOR, POLL_MAX = 2.0, 1.5, 10.0
QUERY_NAME = "illumio-ops crosscheck"
LEFTOVERS = "reports.leftovers"  # Run.cache key: hrefs of queries that could not be deleted
ONE_SECOND = timedelta(seconds=1)
ORDER = ("weekly_overview", "lateral_posture", "new_connections", "unmanaged_endpoints", "traffic", "security_risk",
         "network_inventory", "app_summary", "ven_status", "audit", "ransomware", "policy_usage", "policy_diff",
         "policy_resolver", "custom", "readiness")

_sleep = time.sleep
_clock = time.monotonic


class QueryFailed(Exception):
    """A traffic query did not give an answer; the message is this tool's own (no response body)."""


class DraftUnsupported(Exception):
    """update_rules answered 404: this PCE does not recompute drafts."""


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict[str, Any]]
    capped: bool


def _parse_download(body: bytes) -> list[dict[str, Any]]:
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip().rstrip(b",")
        if not line or line in (b"[", b"]"):
            continue
        item = json.loads(line)
        rows.extend(i for i in (item if isinstance(item, list) else [item]) if isinstance(i, dict))
    return rows


def _poll(client: PceClient, href: str, deadline: float, *, rules: bool) -> dict[str, Any]:
    wait = POLL_START
    while True:
        if _clock() >= deadline:
            raise QueryFailed("the traffic query did not finish in time")
        resp = client.request("GET", href, org_scoped=False, timeout=30)
        if resp.status == 200:
            try:
                body = resp.json()
            except ValueError:
                raise QueryFailed("the traffic query's status is not JSON") from None
            if not isinstance(body, dict):
                raise QueryFailed("the traffic query's status is not an object")
            status = str(body.get("status", "")).lower()
            if status in FAILED_STATES:
                raise QueryFailed(f"the traffic query ended as {status}")
            draft = str(body.get("rules") or "completed").lower()
            if rules and draft in FAILED_STATES:
                raise QueryFailed(f"the draft recompute ended as {draft}")
            if status == "completed" and (not rules or draft == "completed"):
                return body
        elif resp.status not in (404, 410):  # not visible yet right after submit: keep waiting
            raise QueryFailed(f"polling the traffic query answered HTTP {resp.status}")
        _sleep(wait)
        wait = min(wait * POLL_FACTOR, POLL_MAX)


def run_query(client: PceClient, payload: Mapping[str, Any], *, draft: bool, leftovers: list[str]) -> QueryResult:
    """submit, poll, (draft: PUT update_rules, poll), download — and DELETE the query whatever happened."""
    deadline = _clock() + QUERY_DEADLINE_SECONDS
    resp = client.request("POST", "/traffic_flows/async_queries", json=dict(payload), timeout=60)
    if resp.status not in (200, 201, 202):
        raise QueryFailed(f"submitting the traffic query answered HTTP {resp.status}")
    try:
        body = resp.json()
    except ValueError:
        raise QueryFailed("the traffic query's answer is not JSON") from None
    href = body.get("href") if isinstance(body, dict) else None
    if not isinstance(href, str) or not href:
        raise QueryFailed("the traffic query's answer has no href")
    try:
        status = _poll(client, href, deadline, rules=False)
        if draft:
            put = client.request("PUT", f"{href}/update_rules", org_scoped=False, json={}, timeout=60)
            if put.status == 404:
                raise DraftUnsupported()
            if put.status not in (200, 202, 204):
                raise QueryFailed(f"update_rules answered HTTP {put.status}")
            status = _poll(client, href, deadline, rules=True)
        got = client.request("GET", f"{href}/download", org_scoped=False, timeout=300)
        if got.status != 200:
            raise QueryFailed(f"downloading the traffic query answered HTTP {got.status}")
        try:
            rows = _parse_download(got.body)
        except (EOFError, OSError, zlib.error, ValueError, UnicodeDecodeError):
            raise QueryFailed("the traffic query's result cannot be read") from None
        flows, matches = status.get("flows_count"), status.get("matches_count")
        if isinstance(flows, int) and len(rows) < flows:
            raise QueryFailed(f"the PCE reported {flows} records but the result held {len(rows)}")
        cap = int(payload["max_results"])
        return QueryResult(rows, len(rows) >= cap or (isinstance(matches, int) and matches >= cap))
    finally:
        try:
            gone = client.request("DELETE", href, org_scoped=False, timeout=30)
            deleted = gone.status in (200, 202, 204, 404)
        except Exception:  # noqa: BLE001 - the delete is cleanup: its failure is reported, never raised over the answer
            deleted = False
        if not deleted:
            leftovers.append(href)


# ── windows ──────────────────────────────────────────────────────────────────

def _midnight_after(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def _asked(end: datetime) -> datetime:
    """The PCE's end is inclusive: a window ending at a UTC midnight is asked to the second before it."""
    e = end.astimezone(UTC)
    return e - ONE_SECOND if e == e.replace(hour=0, minute=0, second=0, microsecond=0) else e


def day_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[start, end) as pieces that never cross a UTC midnight, each with the end it is asked with."""
    out, cur = [], start.astimezone(UTC)
    end = end.astimezone(UTC)
    while cur < end:
        nxt = min(_midnight_after(cur), end)
        out.append((cur, _asked(nxt)))
        cur = nxt
    return out


def whole_days(first_day: str, last_day: str) -> list[tuple[datetime, datetime]]:
    """Whole UTC days first_day..last_day (YYYY-MM-DD), as windows."""
    d = datetime.fromisoformat(first_day).replace(tzinfo=UTC)
    last = datetime.fromisoformat(last_day).replace(tzinfo=UTC)
    out = []
    while d <= last:
        out.append((d, d + timedelta(days=1) - ONE_SECOND))
        d += timedelta(days=1)
    return out


@dataclass
class Fetched:
    flows: dict[tuple[Any, ...], kpis.Flow] = field(default_factory=dict)
    records: int = 0
    queries: int = 0
    capped: list[tuple[datetime, datetime]] = field(default_factory=list)
    unsupported: bool = False

    def describe(self, decisions: frozenset[str]) -> str:
        return (f"PCE: {self.queries} queries, {self.records:,} records ({len(self.flows):,} unique), decisions "
                f"{', '.join(sorted(decisions)) or 'all'}, {'truncated' if self.capped else 'none truncated'}")


def fetch(client: PceClient, windows: Sequence[tuple[datetime, datetime]], *, decisions: frozenset[str], draft: bool,
          max_results: int, leftovers: list[str]) -> Fetched:
    """The records of every window, each record once (the same record from two windows is one); a window at the
    limit is halved up to MAX_SPLITS times, and one still at the limit is listed in `capped`."""
    got = Fetched()
    pending = [(a, b, 0) for a, b in windows]
    while pending:
        a, b, depth = pending.pop(0)
        payload = traffic_payload(a, b, max_results=max_results, query_name=QUERY_NAME,
                                  policy_decisions=sorted(decisions))
        got.queries += 1
        try:
            res = run_query(client, payload, draft=draft, leftovers=leftovers)
        except DraftUnsupported:
            got.unsupported = True
            return got
        if res.capped and depth < MAX_SPLITS and b - a > 2 * ONE_SECOND:
            mid = a + (b - a) / 2
            pending[:0] = [(a, mid, depth + 1), (mid, b, depth + 1)]
            continue
        if res.capped:
            got.capped.append((a, b))
        got.records += len(res.rows)
        for raw in res.rows:
            f = kpis.parse_flow(raw, draft=draft)
            if f is None:
                continue
            seen = got.flows.get(f.identity)
            if seen is None or f.connections > seen.connections:
                got.flows[f.identity] = f
    return got


# ── what each report type is recomputed from ─────────────────────────────────

@dataclass(frozen=True)
class Report:
    id: int
    report_type: str
    params: dict[str, Any]
    start: datetime
    end: datetime
    kpis: dict[str, Any]  # key -> value as the report stored it
    ran_at: datetime  # when it started (the draft and the inventory it read were as of then)


@dataclass(frozen=True)
class Recomputed:
    values: dict[str, int | None]
    note: str


class CannotCheck(Exception):
    """Why a report's numbers cannot be recomputed this time (a filter not carried, a window still at the limit, ...):
    its recomputed numbers become unchecked with this message."""


def _empty(v: Any) -> bool:
    if v in (None, "", False):
        return True
    if isinstance(v, (list, tuple)):
        return not v
    if isinstance(v, dict):
        return all(_empty(x) for x in v.values())
    return False


def carried_decisions(params: Mapping[str, Any]) -> frozenset[str]:
    """The report filter's decisions; CannotCheck when it holds anything else (this version carries decisions only)."""
    cond = params.get("filter")
    if cond is None:
        return frozenset()
    if not isinstance(cond, dict):
        raise CannotCheck("the report's filter cannot be read")
    other = sorted(k for k, v in cond.items() if k != "decisions" and not _empty(v))
    if other:
        raise CannotCheck(f"the report's filter uses {', '.join(other)}, which this version does not carry into "
                         "its PCE queries")
    return frozenset(str(d) for d in cond.get("decisions") or ())


def _events_of(run: Run, start: datetime, end: datetime) -> tuple[list[kpis.AuditEvent], str]:
    key = f"reports.events.{start.isoformat()}.{end.isoformat()}"
    h = run.cache.get(key)
    if not isinstance(h, events.Harvest):
        h = events.harvest(run.pce, start, end, timeout=events.request_timeout(run))
        run.cache[key] = h
    if h.unchecked:
        raise CannotCheck(f"{len(h.unchecked)} windows of the PCE's events could not be read whole "
                         f"({'; '.join(sorted({s.reason for s in h.unchecked}))})")
    evs = [e for e in (kpis.parse_audit_event(r) for r in h.items) if e is not None and start <= e.timestamp < end]
    return evs, f"PCE: {len(evs):,} events in the period, {h.requests} requests"


def _audit(run: Run, r: Report, leftovers: list[str]) -> Recomputed:
    evs, note = _events_of(run, r.start, r.end)
    return Recomputed(kpis.audit_values(evs), note)


def _weekly(run: Run, r: Report, leftovers: list[str]) -> Recomputed:
    evs, note = _events_of(run, r.start, r.end)
    return Recomputed({"provisions": kpis.provisions_value(evs)}, note)


def _whole(f: Fetched, what: str) -> None:
    if f.capped:
        raise CannotCheck(f"{len(f.capped)} {what} windows were still at the PCE's limit after halving")


def _traffic(run: Run, r: Report, leftovers: list[str]) -> Recomputed:
    decisions = carried_decisions(r.params)
    f = fetch(run.pce, day_windows(r.start, r.end), decisions=decisions, draft=False, max_results=F_MAX_RESULTS,
              leftovers=leftovers)
    _whole(f, "traffic")
    flows = list(f.flows.values())
    if kpis.long_records(flows):
        raise CannotCheck("the PCE answered with records longer than two days: it keeps traffic this old by the "
                         "week, which the report's store did not hold")
    primaries = [p for p, _ in kpis.pair(flows)]
    return Recomputed(kpis.traffic_values(primaries, r.start, r.end, decisions), f.describe(decisions))


def _unmanaged(run: Run, r: Report, leftovers: list[str]) -> Recomputed:
    carried_decisions(r.params)  # this type takes no filter: one there is not carried
    first_day = r.start.astimezone(UTC).strftime("%Y-%m-%d")
    last_day = (r.end - timedelta(microseconds=1)).astimezone(UTC).strftime("%Y-%m-%d")
    f = fetch(run.pce, whole_days(first_day, last_day), decisions=frozenset(), draft=False,
              max_results=F_MAX_RESULTS, leftovers=leftovers)
    _whole(f, "traffic")
    flows = list(f.flows.values())
    if kpis.long_records(flows):
        raise CannotCheck("the PCE answered with records longer than two days: it keeps traffic this old by the "
                         "week, which the daily rollups did not hold")
    primaries = [p for p, _ in kpis.pair(flows)]
    note = f"{f.describe(frozenset())}; UTC days {first_day} to {last_day}"
    why = _unmanaged_why(run, primaries, first_day, last_day)
    return Recomputed(kpis.unmanaged_values(primaries, first_day, last_day), f"{note}{'; ' + why if why else ''}")


_ROLLUP_ADDRESSES = ("SELECT substr(src_key, 4) FROM flow_rollup_daily WHERE day >= ? AND day <= ? "
                     "AND src_key LIKE 'ip:%' AND dst_key NOT LIKE 'ip:%' UNION "
                     "SELECT substr(dst_key, 4) FROM flow_rollup_daily WHERE day >= ? AND day <= ? "
                     "AND dst_key LIKE 'ip:%' AND src_key NOT LIKE 'ip:%'")
EXAMPLES = 3


def _unmanaged_why(run: Run, primaries: Sequence[kpis.Flow], first_day: str, last_day: str) -> str:
    """Where the store's addresses and the PCE's answer part, and how: the PCE names the workloads of old traffic as
    they are today, so a workload deleted or paired since moves an address in or out. Says nothing when they agree
    or the store cannot be read; it explains a difference, it never turns one into agreement."""
    try:
        conn = open_ro(run.paths.flows_db)
    except Exception:  # noqa: BLE001 - the note is an aid; the comparison stands without it
        return ""
    try:
        days = (first_day, last_day, first_day, last_day)
        store = {str(r[0]) for r in conn.execute(_ROLLUP_ADDRESSES, days)}
        answer = kpis.unmanaged_addresses(primaries, first_day, last_day)
        only_store, only_pce = sorted(store - answer), sorted(answer - store)
        if not only_store and not only_pce:
            return ""
        in_range = [p for p in primaries if first_day <= p.last.strftime("%Y-%m-%d") <= last_day]
        named = {ip for p in in_range for ip, href in ((p.src_ip, p.src_href), (p.dst_ip, p.dst_href)) if href}
        bare = {ip for p in in_range if p.src_href is None and p.dst_href is None for ip in (p.src_ip, p.dst_ip)}
        kinds: dict[str, list[str]] = {}
        for ip in only_store:
            kind = ("a workload in the PCE's answer today" if ip in named else
                    "no workload at either end in the PCE's answer today" if ip in bare else
                    "not in the PCE's answer")
            kinds.setdefault(f"only in the store, {kind}", []).append(ip)
        for ip in only_pce:
            had = conn.execute("SELECT 1 FROM flows WHERE is_primary = 1 AND last_detected >= ? AND last_detected < ? "
                               "AND ((src_ip = ? AND src_key NOT LIKE 'ip:%') OR (dst_ip = ? AND dst_key NOT LIKE "
                               "'ip:%')) LIMIT 1", (f"{first_day}T00:00:00", f"{last_day}T24", ip, ip)).fetchone()
            kind = "the store recorded a workload there" if had else "not in the store's rollups"
            kinds.setdefault(f"only in the PCE's answer, {kind}", []).append(ip)
    except Exception:  # noqa: BLE001 - an older or partial store: no note
        return ""
    finally:
        conn.close()
    parts = [f"{len(ips)} {kind} (e.g. {', '.join(ips[:EXAMPLES])})" for kind, ips in kinds.items()]
    return ("the store's rollups and the PCE's answer part on " + "; ".join(parts) +
            ". The PCE names the workloads of old traffic as they are now: a workload deleted, re-paired or created "
            "since the traffic moves its peers in or out")


def _get_list(client: PceClient, path: str, *, org_scoped: bool) -> list[dict[str, Any]]:
    sep = "&" if "?" in path else "?"
    resp = client.request("GET", f"{path}{sep}max_results={GET_PAGE_LIMIT}", org_scoped=org_scoped, timeout=60)
    if resp.status != 200:
        raise CannotCheck(f"GET {path.split('?')[0]} answered HTTP {resp.status}")
    try:
        body = resp.json()
    except ValueError:
        raise CannotCheck(f"GET {path.split('?')[0]} did not answer with JSON") from None
    if not isinstance(body, list):
        raise CannotCheck(f"GET {path.split('?')[0]} did not answer with a list")
    if len(body) >= GET_PAGE_LIMIT:
        raise CannotCheck(f"GET {path.split('?')[0]} returned a full page ({GET_PAGE_LIMIT} items): the rest would "
                          "need an async collection, which this version does not read")
    return [x for x in body if isinstance(x, dict)]


def draft_rule_sets(client: PceClient) -> list[dict[str, Any]]:
    sets = _get_list(client, "/sec_policy/draft/rule_sets", org_scoped=True)
    for rs in sets:
        if "deny_rules" not in rs and isinstance(rs.get("href"), str):
            rs["deny_rules"] = _get_list(client, f"{rs['href']}/deny_rules", org_scoped=False)
    return sets


def _draft_unchanged(run: Run, r: Report) -> None:
    """A draft recompute answers for the draft as it is now: the report's numbers can be compared only when nothing
    that changes that answer happened since the report ran (from the PCE's own events)."""
    evs, _ = _events_of(run, r.ran_at, run.now)
    changes = kpis.draft_changes(evs)
    if changes:
        first = min(e.timestamp for e in evs if e.event_type in changes)
        raise CannotCheck(f"the draft or the workloads changed after the report ran ({sum(changes.values())} events "
                          f"from {pce_time(first)}: {', '.join(f'{t} x{n}' for t, n in sorted(changes.items()))}); "
                          "a recompute now answers for another draft")


def _daily(f: Fetched) -> None:
    if kpis.long_records(f.flows.values()):
        raise CannotCheck("the PCE answered with records longer than two days: it keeps traffic this old by the "
                          "week, so a recompute now counts whole weeks where the report counted days")


def _policy_usage(run: Run, r: Report, leftovers: list[str]) -> Recomputed:
    carried_decisions(r.params)
    _draft_unchanged(run, r)
    f = fetch(run.pce, day_windows(r.start, r.end), decisions=frozenset(), draft=True, max_results=D_MAX_RESULTS,
              leftovers=leftovers)
    if f.unsupported:
        return Recomputed(dict.fromkeys(("used", "unused", "deny_hit", "no_rule")),
                          "the PCE does not recompute drafts (update_rules answered 404): the report gives none")
    _whole(f, "draft recompute")
    _daily(f)
    hits = kpis.rule_hits(kpis.pair(f.flows.values()))
    sets = draft_rule_sets(run.pce)
    return Recomputed(kpis.policy_usage_values(sets, hits),
                      f"{f.describe(frozenset())}; the draft as it is now ({len(sets)} rule sets): a draft changed "
                      "since the report shows as a difference")


def _readiness(run: Run, r: Report, leftovers: list[str]) -> Recomputed:
    decisions = carried_decisions(r.params)
    _draft_unchanged(run, r)
    f = fetch(run.pce, day_windows(r.start, r.end), decisions=decisions, draft=True, max_results=D_MAX_RESULTS,
              leftovers=leftovers)
    if f.unsupported:
        return Recomputed({"predicted_blocked": None},
                          "the PCE does not recompute drafts (update_rules answered 404): the report gives none")
    _whole(f, "draft recompute")
    _daily(f)
    p = kpis.predicted(kpis.pair(f.flows.values()))
    return Recomputed({"predicted_blocked": p.value()},
                      f"{f.describe(decisions)}; {p.blocked_flows:,} connections into managed hosts the draft blocks, "
                      f"{p.undetermined_flows:,} without a draft decision; read per UTC day (the report asks one "
                      "window for the whole period)")


RECOMPUTE = {"audit": _audit, "weekly_overview": _weekly, "traffic": _traffic, "unmanaged_endpoints": _unmanaged,
             "policy_usage": _policy_usage, "readiness": _readiness}


# ── the reports table and the comparison ─────────────────────────────────────

def latest_reports(run: Run) -> dict[str, Report]:
    """Each type's latest finished report made for this PCE (by id: the newest made)."""
    target = pce_target(run.settings.pce.url, run.settings.pce.org_id)
    conn = open_ro(run.paths.app_db)
    try:
        rows = conn.execute("SELECT id, report_type, params_json, period_start, period_end, kpis_json, pce_target, "
                            "COALESCE(started_at, created_at) FROM reports WHERE status = 'done' "
                            "ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    out: dict[str, Report] = {}
    for rid, rtype, params, start, end, kpis_json, tgt, ran in rows:
        if rtype in out or rtype not in kpis.KPI_KEYS or tgt != target:
            continue
        try:
            stored, given = json.loads(kpis_json), json.loads(params)
            if not isinstance(stored, list) or not isinstance(given, dict):
                continue
            out[rtype] = Report(int(rid), str(rtype), given, datetime.fromisoformat(start),
                                datetime.fromisoformat(end),
                                {str(k["key"]): k.get("value") for k in stored if isinstance(k, dict) and "key" in k},
                                datetime.fromisoformat(ran))
        except (ValueError, TypeError):
            continue  # an unreadable row: the next older one of the type is used
    return out


def _difference(reported: Any, expected: int | None) -> str:
    if isinstance(reported, (int, float)) and not isinstance(reported, bool) and expected is not None:
        diff = expected - reported
        pct = f" ({100 * diff / reported:+.1f}%)" if reported else " (no percentage: the report has 0)"
        return f"report {reported}, recomputed {expected}, difference {diff:+}{pct}"
    return f"report {reported}, recomputed {expected}"


def _compare(r: Report, got: Recomputed) -> list[Finding]:
    out = []
    for key, expected in got.values.items():
        item = f"{r.report_type} #{r.id}: {key}"
        if key not in r.kpis:
            out.append(Finding(AREA, item, "unchecked", f"the report has no such number; recomputed {expected}. "
                                                        f"{got.note}"))
        elif r.kpis[key] == expected:
            out.append(Finding(AREA, item, "consistent", f"report {r.kpis[key]}, recomputed {expected}. {got.note}"))
        else:
            out.append(Finding(AREA, item, "inconsistent", f"{_difference(r.kpis[key], expected)}. {got.note}"))
    return out


def _safe(exc: Exception) -> str:
    if isinstance(exc, PceTransportError):
        return f"the PCE cannot be reached ({exc.kind})"
    if isinstance(exc, PceBudgetExhausted):
        return "no PCE request budget left"
    return str(exc)  # this module's and the events area's own messages


def _report(run: Run, r: Report, leftovers: list[str]) -> list[Finding]:
    period = f"period {pce_time(r.start)} to {pce_time(r.end)}"
    keys = list(kpis.KPI_KEYS[r.report_type]) + sorted(k for k in r.kpis if k not in kpis.KPI_KEYS[r.report_type])
    out = [Finding(AREA, f"{r.report_type} #{r.id}: {k}", "unchecked", f"{why} ({period})")
           for k in keys if (why := kpis.reason(r.report_type, k)) is not None]
    work = RECOMPUTE.get(r.report_type)
    if work is None:
        return out
    try:
        got = work(run, r, leftovers)
    except Exception as exc:  # noqa: BLE001 - one report's failure must not cost the others their findings
        known = (CannotCheck, QueryFailed, events.EventsUnavailable, PceTransportError, PceBudgetExhausted)
        # only this tool's own messages and the transport's kind are written; never str() of anything else
        why = f"{type(exc).__name__}: {_safe(exc)}" if isinstance(exc, known) else type(exc).__name__
        return out + [Finding(AREA, f"{r.report_type} #{r.id}: {k}", "unchecked", f"not recomputed: {why} ({period})")
                      for k in sorted(kpis.RECOMPUTED[r.report_type])]
    return out + _compare(r, Recomputed(got.values, f"{got.note}; {period}"))


def check(run: Run) -> list[Finding]:
    leftovers: list[str] = run.cache.setdefault(LEFTOVERS, [])
    found = latest_reports(run)
    out: list[Finding] = []
    for rtype in ORDER:
        n = len(kpis.KPI_KEYS[rtype])
        if not n:
            continue  # a custom report has no key numbers
        r = found.get(rtype)
        if r is None:
            out.append(Finding(AREA, rtype, "unchecked",
                               f"no finished report of this type for this PCE: its {n} key numbers are not checked"))
            continue
        out += _report(run, r, leftovers)
    if leftovers:
        out.append(Finding(AREA, "traffic queries left on the PCE", "unchecked",
                           f"{len(leftovers)} queries this tool created could not be deleted (listed at the top)"))
    return out
