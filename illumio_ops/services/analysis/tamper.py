"""Tamper investigation (spec §6.5.4): per host on demand (readings, interval pattern, the timeline around the
first event, host-side commands, known causes), and a summary of every host in the hourly step."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.flows import parse_time
from illumio_ops.domain.tamper import (
    HOST_TIMELINE_TYPES,
    ORG_TIMELINE_TYPES,
    Annotation,
    Command,
    PatternResult,
    TamperReading,
    TimelineEvent,
    classify,
    explained_by,
    guidance,
    interpret,
    timeline,
)
from illumio_ops.domain.values import (
    CapabilityState,
    TamperClassification,
    TamperPattern,
)
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import query_events, tamper_events
from illumio_ops.store import annotations as annotation_store
from illumio_ops.store.flowdb import analysis, capabilities, workloads

KIND = "tamper"
SUMMARY_DAYS = 60
RECENT = timedelta(days=7)


class HostTamper(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    readings: list[TamperReading]
    pattern: PatternResult
    timeline: list[TimelineEvent]
    guidance: list[Command]
    annotations: list[Annotation]
    explained: dict[int, int]            # annotation id -> readings it explains
    signal_capability: CapabilityState   # whether this VEN version reports signal-type events


def list_annotations(ctx: AppContext) -> list[Annotation]:
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        rows = annotation_store.for_pce(conn, pce.url, pce.org_id)
    return [Annotation(id=r["id"], host_href=r["host_href"], pattern=TamperPattern(r["pattern"]) if r["pattern"] else None,
                       process=r["process"], reason=r["reason"]) for r in rows]


def add_annotation(ctx: AppContext, *, host_href: str | None, pattern: TamperPattern | None, process: str | None,
                   reason: str, by: str) -> int:
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        return annotation_store.add(conn, pce_url=pce.url, org_id=pce.org_id, host_href=host_href,
                                    pattern=pattern.value if pattern else None, process=process, reason=reason,
                                    created_by=by, at=datetime.now(UTC))


def remove_annotation(ctx: AppContext, annotation_id: int) -> None:
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        annotation_store.remove(conn, annotation_id, pce_url=pce.url, org_id=pce.org_id)


def _signal_capability(ctx: AppContext) -> CapabilityState:
    with ctx.flows().connect() as conn:
        cap = capabilities.all(conn).get("tamper_signal")
    return CapabilityState(cap.state) if cap is not None else CapabilityState.UNKNOWN


def host_tamper(ctx: AppContext, href: str, *, now: datetime | None = None, days: int = SUMMARY_DAYS) -> HostTamper:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    found = query_events(ctx, start=at - timedelta(days=days), end=at, event_types=("agent.tampering",),
                         workload_href=href, limit=10_000, now=at)
    rows = sorted(found.rows, key=lambda r: r.timestamp)
    readings = [reading for r in rows for reading in interpret(r.raw)]
    pattern = classify([r.timestamp for r in rows])
    events: list[TimelineEvent] = []
    if rows:
        first = rows[0].timestamp
        window = {"start": first - timedelta(hours=24), "end": first + timedelta(hours=24), "limit": 500, "now": at}
        nearby = query_events(ctx, event_types=HOST_TIMELINE_TYPES, workload_href=href, **window).rows  # type: ignore[arg-type]
        nearby += query_events(ctx, event_types=ORG_TIMELINE_TYPES, **window).rows  # type: ignore[arg-type]
        events = timeline([TimelineEvent(at=e.timestamp, event_type=e.event_type,
                                         summary=e.created_by_name or e.event_type) for e in nearby], first)
    with ctx.flows().connect() as conn:
        os_id = next((w.os_id for w in workloads.all_workloads(conn) if w.href == href), None)
    notes = list_annotations(ctx)
    explained: dict[int, int] = {}
    for reading in readings:
        aid = explained_by(reading, href, pattern.kind, notes)
        if aid is not None:
            explained[aid] = explained.get(aid, 0) + 1
    return HostTamper(readings=readings, pattern=pattern, timeline=events, guidance=list(guidance(os_id)),
                      annotations=notes, explained=explained, signal_capability=_signal_capability(ctx))


def tamper_summary(ctx: AppContext, now: datetime) -> None:
    """The hourly step: per host with tampering in the last 60 days, its counts, pattern and how many recent
    readings no known cause explains."""
    found = tamper_events(ctx, start=now - timedelta(days=SUMMARY_DAYS), end=now)
    by_host: dict[str, list[dict[str, object]]] = {}
    for host, raw in found.items:
        by_host.setdefault(host, []).append(raw)
    with ctx.flows().connect() as conn:
        names = {w.href: w.hostname for w in workloads.all_workloads(conn)}
    notes = list_annotations(ctx)
    ranked: list[tuple[int, str, dict[str, object]]] = []
    for host, raws in by_host.items():
        readings = [r for raw in raws for r in interpret(raw)]
        stamps = sorted({parse_time(raw["timestamp"]) for raw in raws})
        pattern = classify(stamps)
        unexplained = sum(1 for r in readings if r.at >= now - RECENT and explained_by(r, host, pattern.kind, notes) is None)
        last = stamps[-1].isoformat()
        ranked.append((unexplained, last, {
            "href": host, "hostname": names.get(host), "n_60d": len(raws), "n_7d": sum(1 for t in stamps if t >= now - RECENT),
            "pattern": pattern.kind.value, "median_minutes": pattern.median_minutes, "last_at": last,
            "unexplained_7d": unexplained,
            "has_signal": any(r.classification == TamperClassification.SIGNAL for r in readings)}))
    hosts = [h for _, _, h in sorted(ranked, key=lambda x: (x[0], x[1]), reverse=True)]  # most unexplained first
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:
        analysis.write_result(conn, KIND, params={"days": SUMMARY_DAYS}, result={"hosts": hosts, "unmatched": found.unmatched},
                              at=now)
