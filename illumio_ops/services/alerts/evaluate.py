"""Alert evaluation after each collection cycle: read what arrived since the last evaluation, run the rules over
it (domain.alerting), pass each trigger through its cooldown and throttle, and record the alerts with a delivery
row per enabled channel. Sending is the dispatcher's job (services.alerts.dispatch).

Each source keeps its own watermark, tagged with the PCE it is about. A first evaluation — on a new install, or
after a PCE switch — only sets the watermark to now: history (and the initial backfill) is never alerted on
(spec §7). A failure leaves the watermark where it was, so the next run sees the same data again.
"""
from __future__ import annotations

import functools
import json
import threading
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain.alerting import (
    DetectionFact,
    EventFact,
    IncrementFacts,
    IncrementTopFact,
    Trigger,
    evaluate_bandwidth_rule,
    evaluate_event_rule,
    evaluate_lateral_rule,
    evaluate_traffic_rule,
    evaluate_volume_rule,
    gate,
)
from illumio_ops.domain.alerting import (
    evaluate_system as evaluate_system_rule,
)
from illumio_ops.domain.alertrules import (
    AlertRule,
    BandwidthRule,
    EventRule,
    LateralRule,
    SystemRule,
    TrafficRule,
    VolumeRule,
    event_matches,
    exact_types,
    uses_regex,
)
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.tamper import explained_by, interpret
from illumio_ops.domain.values import (
    SEVERITY_ORDER,
    CollectionMode,
    DeliveryStatus,
    DetectorKind,
    IngestSource,
    Severity,
    SystemCheck,
    TamperPattern,
    ThresholdType,
)
from illumio_ops.services.alerts.channels import enabled_channels
from illumio_ops.services.alerts.system import max_gap_id, system_facts
from illumio_ops.services.analysis.tamper import list_annotations
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import (
    NewEvent,
    events_after,
    events_in_window,
    max_event_id,
)
from illumio_ops.services.flowsource import increment_totals, increments_watermark
from illumio_ops.settings.schema import Settings
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis, ingest_state, workloads
from illumio_ops.store.flowdb.db import StaleGeneration

EVENT_BATCH = 5_000
EVENT_BATCHES = 10
DETECTION_BATCH = 2_000
DETECTION_BATCHES = 25

SOURCE_EVENTS = "events"
SOURCE_TRAFFIC = "traffic"
SOURCE_LATERAL = "lateral"
SOURCE_SYSTEM = "system"


# One evaluation per source at a time: two jobs evaluate lateral rules (traffic and backfill) and two the system
# checks (probe and alerts_system); run together, both would read the same watermark and record the same alerts.
_LOCKS = {source: threading.Lock() for source in (SOURCE_EVENTS, SOURCE_TRAFFIC, SOURCE_LATERAL, SOURCE_SYSTEM)}


def _one_at_a_time(source: str) -> Callable[[Callable[..., EvalRun]], Callable[..., EvalRun]]:
    def wrap(fn: Callable[..., EvalRun]) -> Callable[..., EvalRun]:
        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> EvalRun:
            with _LOCKS[source]:
                try:
                    return fn(*args, **kwargs)
                except StaleGeneration:  # the PCE was switched meanwhile: nothing of this run is recorded
                    return EvalRun(source=source, evaluated=0, fired=0, suppressed=0, statuses={})
        return run
    return wrap


class EvalRun(BaseModel):
    source: str
    evaluated: int
    fired: int
    suppressed: int
    statuses: dict[str, str]


def _rules(s: Settings, kind: type[Any]) -> list[Any]:
    return [r for r in s.alerts.rules if r.enabled and isinstance(r, kind)]


class _Recorder:
    """Gates triggers and records the alerts that pass. What one batch found is recorded together with the
    source's new watermark, in one transaction: a failure leaves neither an alert, a cooldown nor the watermark
    behind, so the retry sees the same data with the same state (a cooldown saved without its alert would
    suppress the retry; an alert kept without the watermark would be written again)."""

    def __init__(self, ctx: AppContext, s: Settings, now: datetime) -> None:
        self.ctx, self.now = ctx, now
        self.pce = (s.pce.url, s.pce.org_id)
        self.generation = ctx.flows().generation  # what was read is this flow database's
        self.channels = enabled_channels(s.alerts.channels)
        self.fired = self.suppressed = 0
        self.pending: list[tuple[AlertRule, list[Trigger]]] = []
        self.seen: list[tuple[str, str, str]] = []  # (rule, detection fingerprint, its severity) evaluated

    def record(self, rule: AlertRule, triggers: Sequence[Trigger]) -> None:
        if triggers:
            self.pending.append((rule, list(triggers)))

    def commit(self, source: str, watermark: str | None) -> None:
        """Record the pending triggers and move the source's watermark (None: leave it) as one change."""
        fired = suppressed = 0
        pce = self.ctx.settings.current().pce
        if (pce.url, pce.org_id) != self.pce or self.ctx.flows().generation != self.generation:
            raise StaleGeneration  # read from one PCE's data, about to be recorded as another's
        with self.ctx.db() as conn:
            for rule, triggers in self.pending:
                for t in triggers:
                    g = gate(rule, store.rule_state(conn, rule.id, t.subject_key), self.now)
                    store.save_rule_state(conn, rule.id, t.subject_key, g.state,
                                          suppressed=None if g.allowed else g.reason)  # type: ignore[arg-type]
                    if not g.allowed:
                        suppressed += 1
                        continue
                    hold = (DeliveryStatus.GROUPED if t.grouped_annotation is not None
                            else None if rule.notify else DeliveryStatus.NOT_NOTIFIED)
                    store.insert_alert(conn, pce_url=self.pce[0], org_id=self.pce[1], rule_name=rule.name,
                                       pack_key=rule.pack_key, trigger=t, at=self.now, channels=self.channels,
                                       hold=hold)
                    fired += 1
            for rule_id, fingerprint, severity in self.seen:
                store.set_seen_severity(conn, rule_id, fingerprint, severity)
            if watermark is not None:
                store.set_eval_watermark(conn, source, watermark, pce_url=self.pce[0], org_id=self.pce[1])
        self.pending.clear()
        self.seen.clear()
        self.fired += fired
        self.suppressed += suppressed

    def status(self, rule_id: str, status: str) -> None:
        with self.ctx.db() as conn:
            store.set_rule_status(conn, rule_id, status, self.now)


def _watermark(ctx: AppContext, s: Settings, source: str) -> str | None:
    with ctx.db() as conn:
        return store.eval_watermark(conn, source, pce_url=s.pce.url, org_id=s.pce.org_id)


def _set_watermark(ctx: AppContext, s: Settings, source: str, value: str) -> None:
    with ctx.db() as conn:
        store.set_eval_watermark(conn, source, value, pce_url=s.pce.url, org_id=s.pce.org_id)


def _collected(ctx: AppContext, source: IngestSource) -> bool:
    """Whether a collection of this source has succeeded. Until one has, a first evaluation waits: starting its
    watermark on an empty store would make the first successful cycle's cold start look new."""
    with ctx.flows().connect() as conn:
        state = ingest_state.get(conn, source)
    return state is not None and state.last_ok_at is not None


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


# ── events ───────────────────────────────────────────────────────────────────

def event_fact(e: NewEvent) -> EventFact:
    return EventFact(href=e.href, event_type=e.event_type, status=e.status, severity=e.severity, timestamp=e.timestamp,
                     host_key=e.host_key, hostname=e.hostname, raw=e.raw, actor=e.actor)


def _window_matches(ctx: AppContext, rule: EventRule, at: datetime) -> int:
    types = None if uses_regex(rule) else exact_types(rule)
    found = events_in_window(ctx, start=at - timedelta(minutes=rule.window_minutes), end=at, exact_types=types)
    return sum(1 for e in found if event_matches(rule, e.raw))


def _tamper_context(ctx: AppContext) -> tuple[dict[str, TamperPattern], list[Any]]:
    with ctx.flows().connect() as conn:
        row = analysis.read_result(conn, "tamper")
    hosts = json.loads(row["result_json"]).get("hosts", []) if row is not None else []
    return {h["href"]: TamperPattern(h["pattern"]) for h in hosts}, list_annotations(ctx)


def _tamper(trigger: Trigger, matched: Sequence[EventFact], ctx_cache: dict[str, Any], ctx: AppContext) -> Trigger:
    """Tampering alerts carry the reading (spec §6.5.2), and one a known cause explains is grouped, not sent."""
    tampering = [e for e in matched if e.event_type == "agent.tampering"]
    # An immediate rule's trigger is one host's (or one event type's): read only its own events.
    own = [e for e in tampering if (e.host_key or e.event_type) == trigger.subject_key]
    tampering = own or tampering
    if not tampering:
        return trigger
    if "tamper" not in ctx_cache:
        ctx_cache["tamper"] = _tamper_context(ctx)
    patterns, notes = ctx_cache["tamper"]
    read = [(e.host_key, r) for e in tampering for r in interpret(e.raw)]
    readings = [r for _, r in read]
    host = tampering[0].host_key
    pattern = patterns.get(host or "", TamperPattern.TOO_FEW)
    signal = next((r for r in readings if r.has_process_info), None)
    params = {**dict(trigger.params), "classification": readings[0].classification if readings else None,
              "process": signal.process if signal else None, "pid": signal.pid if signal else None,
              "actions": [str(a) for a in signal.actions] if signal else [], "pattern": pattern.value,
              "has_process_info": signal is not None}
    # Grouped only when one known cause explains every reading, each against its own host.
    explained = {explained_by(r, h, patterns.get(h, TamperPattern.TOO_FEW), notes) if h else None for h, r in read}
    grouped = next(iter(explained)) if len(explained) == 1 and None not in explained else None
    return Trigger(**{**trigger.__dict__, "params": params, "grouped_annotation": grouped})


@_one_at_a_time(SOURCE_EVENTS)
def evaluate_events(ctx: AppContext, *, now: datetime | None = None) -> EvalRun:
    at = _now(now)
    s = ctx.settings.current()
    run = EvalRun(source=SOURCE_EVENTS, evaluated=0, fired=0, suppressed=0, statuses={})
    mark = _watermark(ctx, s, SOURCE_EVENTS)
    if mark is None:
        if not _collected(ctx, IngestSource.EVENTS):
            return run
        _set_watermark(ctx, s, SOURCE_EVENTS, str(max_event_id(ctx)))
        return run
    rules: list[EventRule] = _rules(s, EventRule)
    rec = _Recorder(ctx, s, at)
    after = int(mark)
    cache: dict[str, Any] = {}
    for _ in range(EVENT_BATCHES):
        rows, more = events_after(ctx, after, limit=EVENT_BATCH)
        if not rows:
            break
        facts = [event_fact(e) for e in rows]
        for rule in rules:
            matched = [f for f in facts if event_matches(rule, f.raw)]
            if not matched:
                continue
            count = _window_matches(ctx, rule, at) if rule.threshold is ThresholdType.COUNT else 0
            triggers = evaluate_event_rule(rule, matched, count, now=at)
            rec.record(rule, [_tamper(t, matched, cache, ctx) for t in triggers])
        run.evaluated += len(rows)
        after = rows[-1].id
        rec.commit(SOURCE_EVENTS, str(after))
        if not more:
            break
    else:
        logger.info("alert evaluation: more than {} new events; the rest are evaluated next run",
                    EVENT_BATCH * EVENT_BATCHES)
    return run.model_copy(update={"fired": rec.fired, "suppressed": rec.suppressed})


# ── traffic, bandwidth, volume ───────────────────────────────────────────────

def increment_facts(totals: Any, at: datetime, watermark: datetime | None) -> IncrementFacts:
    return IncrementFacts(
        connections=totals.connections, bytes=totals.bytes, bytes_rows=totals.bytes_rows, rows=totals.rows,
        new_rows=totals.new_rows, max_mbps=totals.max_mbps,
        top=tuple(IncrementTopFact(t.src, t.dst, t.port, t.proto, t.connections, t.mbps) for t in totals.top),
        gaps=tuple(totals.coverage.gaps), latency_seconds=int((at - watermark).total_seconds()) if watermark else None)


@_one_at_a_time(SOURCE_TRAFFIC)
def evaluate_traffic(ctx: AppContext, *, now: datetime | None = None) -> EvalRun:
    at = _now(now)
    s = ctx.settings.current()
    run = EvalRun(source=SOURCE_TRAFFIC, evaluated=0, fired=0, suppressed=0, statuses={})
    rules = [r for r in s.alerts.rules if r.enabled and isinstance(r, TrafficRule | BandwidthRule | VolumeRule)]
    rec = _Recorder(ctx, s, at)
    if s.collection.mode is CollectionMode.EVENTS_ONLY or not s.collection.enabled:
        for r in rules:
            rec.status(r.id, "collection_off")
            run.statuses[r.id] = "collection_off"
        return run
    newest = increments_watermark(ctx)
    mark = _watermark(ctx, s, SOURCE_TRAFFIC)
    if mark is None:
        if not _collected(ctx, IngestSource.TRAFFIC):
            return run
        _set_watermark(ctx, s, SOURCE_TRAFFIC, (newest or at).isoformat())
        return run
    since = datetime.fromisoformat(mark)
    for rule in rules:
        window = (at - timedelta(minutes=rule.window_minutes), at)
        totals = increment_totals(ctx, rule.condition, start=window[0], end=window[1], new_after=since,
                                  rank_by="mbps" if isinstance(rule, BandwidthRule) else "connections", now=at)
        facts = increment_facts(totals, at, newest)
        if isinstance(rule, TrafficRule):
            trigger = evaluate_traffic_rule(rule, facts, now=at, window=window)
        elif isinstance(rule, BandwidthRule):
            trigger = evaluate_bandwidth_rule(rule, facts, now=at, window=window)
        else:
            trigger = evaluate_volume_rule(rule, facts, now=at, window=window)
        status = ("no_data" if not isinstance(rule, TrafficRule) and totals.rows and not totals.bytes_rows
                  else "incomplete" if totals.coverage.gaps else "ok")
        rec.status(rule.id, status)
        run.statuses[rule.id] = status
        rec.record(rule, [trigger] if trigger else [])
        run.evaluated += 1
    rec.commit(SOURCE_TRAFFIC, max(since, newest or since).isoformat())
    return run.model_copy(update={"fired": rec.fired, "suppressed": rec.suppressed})


# ── lateral movement ─────────────────────────────────────────────────────────

def _is_new(row: Any, start: tuple[str, int]) -> bool:
    """Created after the run's starting watermark (a new row's created_at equals its updated_at)."""
    return bool(row["created_at"] > start[0] or (row["created_at"] == start[0] and row["id"] > start[1]))


def _previous_severity(conn: Any, rule_id: str, fingerprint: str) -> Severity | None:
    """The detection's severity when this rule last evaluated it — not the last alert's severity, which may be the
    rule's own, and kept when no alert fired (a detection below the rule's floor). Before that was kept: the
    detection's severity on the rule's last alert. None: the rule has not seen it (it predates alerting)."""
    seen = store.seen_severity(conn, rule_id, fingerprint)
    if seen is not None:
        return Severity(seen)
    last = store.last_alert(conn, rule_id, fingerprint)
    if last is None:
        return None
    return Severity(json.loads(last["facts_json"]).get("detection_severity") or last["severity"])


def detection_fact(row: Any, *, start: tuple[str, int], names: dict[str, str | None],
                    previous: Severity | None) -> DetectionFact:
    """previous: the detection's severity when the rule last evaluated it; None for one the rule has not seen,
    which only sets the baseline (a detection older than alerting is history, spec §7)."""
    severity = Severity(row["severity"])
    is_new = _is_new(row, start)
    rose = previous is not None and SEVERITY_ORDER.index(severity) > SEVERITY_ORDER.index(previous)
    return DetectionFact(
        id=row["id"], detector=DetectorKind(row["detector"]), fingerprint=row["fingerprint"],
        subject_key=row["subject_key"], subject_name=names.get(row["subject_key"]) or row["subject_key"],
        severity=severity, critical_asset=bool(row["critical_asset"]), late=bool(row["late"]),
        first_seen=datetime.fromisoformat(row["first_seen"]), last_seen=datetime.fromisoformat(row["last_seen"]),
        summary=json.loads(row["summary_json"]), segment=FlowSegment.model_validate_json(row["segment_json"]),
        confidence=json.loads(row["confidence_json"]), is_new=is_new, severity_rose=rose)


def _mark(value: str) -> tuple[str, int]:
    stamp, _, row_id = value.rpartition("|")
    return stamp, int(row_id or 0)


@_one_at_a_time(SOURCE_LATERAL)
def evaluate_lateral(ctx: AppContext, *, now: datetime | None = None) -> EvalRun:
    at = _now(now)
    s = ctx.settings.current()
    run = EvalRun(source=SOURCE_LATERAL, evaluated=0, fired=0, suppressed=0, statuses={})
    saved = _watermark(ctx, s, SOURCE_LATERAL)
    if saved is None:
        if not _collected(ctx, IngestSource.TRAFFIC):
            return run
        with ctx.flows().connect() as conn:
            newest = analysis.max_detection_update(conn)
        _set_watermark(ctx, s, SOURCE_LATERAL, f"{newest[0]}|{newest[1]}")
        return run
    mark = start = _mark(saved)
    rules: list[LateralRule] = _rules(s, LateralRule)
    wanted = {d for r in rules for d in r.detectors}
    rec = _Recorder(ctx, s, at)
    with ctx.flows().connect() as conn:
        names = {w.href: w.hostname for w in workloads.all_workloads(conn)}
    for _ in range(DETECTION_BATCHES):
        with ctx.flows().connect() as conn:
            changed = analysis.detections_changed_since(conn, mark, limit=DETECTION_BATCH)
        if not changed:
            break
        for rule in rules:
            facts = []
            for row in changed:
                if DetectorKind(row["detector"]) not in wanted:
                    continue
                previous = None
                if not _is_new(row, start):  # changed, not new: alert again only if its severity rose
                    with ctx.db() as conn:
                        previous = _previous_severity(conn, rule.id, row["fingerprint"])
                facts.append(detection_fact(row, start=start, names=names, previous=previous))
                if DetectorKind(row["detector"]) in rule.detectors:
                    rec.seen.append((rule.id, row["fingerprint"], row["severity"]))
            rec.record(rule, evaluate_lateral_rule(rule, facts))
        run.evaluated += len(changed)
        mark = (str(changed[-1]["updated_at"]), int(changed[-1]["id"]))
        rec.commit(SOURCE_LATERAL, f"{mark[0]}|{mark[1]}")
        if len(changed) < DETECTION_BATCH:
            break
    else:
        logger.info("alert evaluation: more than {} changed detections; the rest are evaluated next run",
                    DETECTION_BATCH * DETECTION_BATCHES)
    return run.model_copy(update={"fired": rec.fired, "suppressed": rec.suppressed})


# ── system checks ────────────────────────────────────────────────────────────

@_one_at_a_time(SOURCE_SYSTEM)
def evaluate_system(ctx: AppContext, *, now: datetime | None = None,
                    checks: Collection[SystemCheck] | None = None) -> EvalRun:
    at = _now(now)
    s = ctx.settings.current()
    run = EvalRun(source=SOURCE_SYSTEM, evaluated=0, fired=0, suppressed=0, statuses={})
    mark = _watermark(ctx, s, SOURCE_SYSTEM)
    if mark is None:
        _set_watermark(ctx, s, SOURCE_SYSTEM, str(max_gap_id(ctx)))
        mark = str(max_gap_id(ctx))
    rules = [r for r in _rules(s, SystemRule) if checks is None or r.check in checks]
    if not rules:
        return run
    # Only the run that evaluates data loss moves the gap watermark (a probe-only run must not skip gaps).
    watches_gaps = checks is None or SystemCheck.DATA_LOSS in checks
    facts, newest = system_facts(ctx, since_gap_id=int(mark), now=at)
    rec = _Recorder(ctx, s, at)
    for rule in rules:
        rec.record(rule, evaluate_system_rule(rule, facts, now=at))
        run.evaluated += 1
    rec.commit(SOURCE_SYSTEM, str(newest) if watches_gaps else None)
    return run.model_copy(update={"fired": rec.fired, "suppressed": rec.suppressed})
