"""Alert rules beyond evaluation: a preview over recent data, applying the best-practice pack, and the list the
rules page shows."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from illumio_ops.domain.alerting import (
    RuleState,
    Trigger,
    evaluate_bandwidth_rule,
    evaluate_event_rule,
    evaluate_lateral_rule,
    evaluate_traffic_rule,
    evaluate_volume_rule,
    gate,
)
from illumio_ops.domain.alertpack import best_practice_rules
from illumio_ops.domain.alertrules import (
    AlertRule,
    BandwidthRule,
    EventRule,
    LateralRule,
    TrafficRule,
    event_matches,
    exact_types,
    uses_regex,
)
from illumio_ops.domain.values import Language
from illumio_ops.i18n import translate
from illumio_ops.services.alerts.evaluate import (
    detection_fact,
    event_fact,
    increment_facts,
)
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import events_in_window
from illumio_ops.services.flowsource import increment_times, increment_totals
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.flows import INCREMENT_KEEP

PREVIEW_SAMPLES = 10


class RulePreview(BaseModel):
    would_fire: int
    samples: list[dict[str, Any]]
    status: Literal["ok", "not_applicable"]
    coverage_note: str | None  # an i18n key when the period reaches past the data the preview can read


def _gated(rule: AlertRule, triggers: Sequence[tuple[datetime, Trigger]]) -> list[Trigger]:
    """Cooldown and throttle simulated in memory: what live evaluation would have let through."""
    states: dict[str, RuleState] = {}
    out = []
    for at, t in triggers:
        g = gate(rule, states.get(t.subject_key), at)
        states[t.subject_key] = g.state
        if g.allowed:
            out.append(t)
    return out


def _preview_events(ctx: AppContext, rule: EventRule, start: datetime, now: datetime) -> list[tuple[datetime, Trigger]]:
    every = timedelta(seconds=ctx.settings.current().collection.events_interval_seconds)
    window = timedelta(minutes=rule.window_minutes)
    found = events_in_window(ctx, start=start - window, end=now, exact_types=None if uses_regex(rule) else exact_types(rule))
    matched = [e for e in found if event_matches(rule, e.raw)]
    out: list[tuple[datetime, Trigger]] = []
    at = start + every
    while at <= now + every:  # the collection cycles that would have run
        batch = [event_fact(e) for e in matched if at - every < e.timestamp <= at]
        if batch:
            count = sum(1 for e in matched if at - window < e.timestamp <= at)
            out += [(at, t) for t in evaluate_event_rule(rule, batch, count, now=at)]
        at += every
    return out


def _preview_flows(ctx: AppContext, rule: Any, start: datetime, now: datetime) -> list[tuple[datetime, Trigger]]:
    out: list[tuple[datetime, Trigger]] = []
    previous = start
    for at in increment_times(ctx, start=start, end=now):
        window = (at - timedelta(minutes=rule.window_minutes), at)
        totals = increment_totals(ctx, rule.condition, start=window[0], end=window[1], new_after=previous,
                                  rank_by="mbps" if isinstance(rule, BandwidthRule) else "connections", now=at)
        facts = increment_facts(totals, at, at)
        evaluate = (evaluate_traffic_rule if isinstance(rule, TrafficRule) else
                    evaluate_bandwidth_rule if isinstance(rule, BandwidthRule) else evaluate_volume_rule)
        trigger = evaluate(rule, facts, now=at, window=window)
        if trigger is not None:
            out.append((at, trigger))
        previous = at
    return out


def _preview_lateral(ctx: AppContext, rule: LateralRule, start: datetime) -> list[tuple[datetime, Trigger]]:
    with ctx.flows().connect() as conn:
        rows = list(reversed(analysis.detections_since(conn, start, limit=5000)))
        names = {w.href: w.hostname for w in workloads.all_workloads(conn)}
    facts = [detection_fact(r, start=("", 0), names=names, previous=None) for r in rows]
    return [(t.last_seen, t) for t in evaluate_lateral_rule(rule, facts)]


def preview_rule(ctx: AppContext, rule: AlertRule, *, hours: int, now: datetime | None = None) -> RulePreview:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    start = at - timedelta(hours=hours)
    note = None
    if isinstance(rule, EventRule):
        found = _preview_events(ctx, rule, start, at)
    elif isinstance(rule, LateralRule):
        found = _preview_lateral(ctx, rule, start)
    elif rule.type in ("traffic", "bandwidth", "volume"):
        if timedelta(hours=hours) > INCREMENT_KEEP:
            note = "preview_increments_kept"
        found = _preview_flows(ctx, rule, start, at)
    else:
        return RulePreview(would_fire=0, samples=[], status="not_applicable", coverage_note=None)
    fired = _gated(rule, sorted(found, key=lambda x: x[0]))
    samples = [{"subject": t.subject_key, "at": t.last_seen.isoformat(), "message_key": t.message_key,
                "params": dict(t.params), "facts": dict(t.facts)} for t in fired[-PREVIEW_SAMPLES:]]
    return RulePreview(would_fire=len(fired), samples=samples, status="ok", coverage_note=note)


def apply_pack(current: Sequence[AlertRule], *, mode: Literal["append_missing", "replace"],
               notify_new_defaults: bool) -> tuple[AlertRule, ...]:
    """append_missing adds the pack rules that are not there and leaves everything else as it is. replace puts
    every pack rule back to its default and keeps the operator's own rules — unlike 5.x, which dropped them and
    so needed a backup copy no one could read."""
    pack = {r.id: r for r in best_practice_rules(notify_new_defaults=notify_new_defaults)}
    if mode == "append_missing":
        have = {r.id for r in current}
        return (*current, *(r for rid, r in pack.items() if rid not in have))
    kept = [pack.get(r.id, r) for r in current]
    have = {r.id for r in kept}
    return (*kept, *(r for rid, r in pack.items() if rid not in have))


class RuleListItem(BaseModel):
    rule: AlertRule
    display_name: str
    summary: store.RuleSummary | None


def rule_list(ctx: AppContext, *, now: datetime | None = None) -> list[RuleListItem]:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    s = ctx.settings.current()
    lang: Language = s.display.language
    with ctx.db() as conn:
        summaries = store.rule_summaries(conn, pce_url=s.pce.url, org_id=s.pce.org_id, now=at)
    return [RuleListItem(rule=r, display_name=r.name or translate(lang, r.pack_key or ""),
                         summary=summaries.get(r.id)) for r in s.alerts.rules]

