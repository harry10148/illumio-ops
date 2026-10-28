"""Predicted blocks (spec §6.5.3 預計阻擋, §6.6 F1): the PCE recomputes a filter's flows against the draft
policy (async query, then update_rules, about a minute), and each flow is shown with the deny rules that
would block it. Not stored: the answer changes with every draft edit (spec §6.4)."""
from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.filter import FilterSpec, matches, to_pce_payload
from illumio_ops.domain.flows import (
    FlowShapeError,
    group_pairs,
    normalize_flow,
    record_key,
)
from illumio_ops.domain.policy import DraftView, RuleRef, index_rules, parse_draft
from illumio_ops.domain.values import CapabilityState
from illumio_ops.pce.async_query import PceQueryError, run_traffic_query
from illumio_ops.pce.policy import fetch_policy_names, fetch_rule_sets
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import FlowRow, pair_row
from illumio_ops.store.flowdb import capabilities
from illumio_ops.store.flowdb.db import StaleGeneration

_ALWAYS = (datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC))
DECIDED = frozenset({"allowed", "potentially_blocked"})  # with blocked_*: a draft decision the PCE gave


class PredictedRow(BaseModel):
    flow: FlowRow
    draft_decision: str
    blocking_rules: list[str]
    allow_rules: list[str]
    essential_service_rules: list[str]


class PredictedBlock(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    rows: list[PredictedRow]
    rules: dict[str, RuleRef]
    capped: bool          # the PCE stopped at max_results
    limit_hit: bool       # more rows than `limit` were returned
    computed_at: datetime
    unsupported: bool     # this PCE does not recompute drafts (update_rules answers 404)
    missing_rules: list[str]  # rule hrefs a flow named that the draft no longer has


@dataclass
class _Recompute:
    at: datetime
    rows: Iterator[PredictedRow]  # each connection once, the residual filter applied
    rules: dict[str, RuleRef]
    capped: bool
    unsupported: bool
    gen: int


def _recompute(ctx: AppContext, spec: FilterSpec, *, max_results: int, deadline_seconds: int) -> _Recompute:
    at = datetime.now(UTC)
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with: an answer from a switched-away PCE is dropped
    settings = ctx.settings.current()
    payload, residual = to_pce_payload(spec, max_results=max_results, query_name="illumio-ops predicted blocks",
                                       label_hrefs={})
    # The PCE answered the time window (a daily flow bucket may reach past it); only the conditions it could
    # not take are checked here.
    residual = residual.model_copy(update={"start": _ALWAYS[0], "end": _ALWAYS[1]})
    deadline = time.monotonic() + deadline_seconds
    with ctx.pce_client(settings.pce) as client:
        try:
            result = run_traffic_query(client, payload, deadline=deadline, compute_draft=True)
        except PceQueryError as exc:
            if exc.stage == "update_rules" and exc.status == 404:
                with fdb.writing(gen) as conn:
                    capabilities.record(conn, "draft_recompute", CapabilityState.UNSUPPORTED,
                                        "update_rules answered 404", at)
                return _Recompute(at=at, rows=iter(()), rules={}, capped=False, unsupported=True, gen=gen)
            raise
        rules = index_rules(fetch_rule_sets(client, "draft", deadline=deadline),
                            **fetch_policy_names(client, "draft", deadline=deadline).__dict__)
    views: dict[str, DraftView] = {}
    records = []
    raws = result.rows
    raws.reverse()
    while raws:  # each PCE row is let go once read: 200,000 of them are most of the memory a recompute holds
        raw = raws.pop()
        try:
            rec = normalize_flow(raw)
        except FlowShapeError:
            continue
        records.append(rec)
        views[record_key(rec)] = parse_draft(raw)

    def rows() -> Iterator[PredictedRow]:
        # A connection both VENs reported is one row with both ends' attributes, filtered as such (P3 final
        # review #13); its draft evidence is both ends' rules.
        for primary, partner in group_pairs(records):
            flow = pair_row(primary, partner)
            if not matches(residual, flow.model_dump()):
                continue
            ends = [views[record_key(primary)]] + ([views[record_key(partner)]] if partner is not None else [])
            decision = next((v.draft_decision for v in ends if v.draft_decision.startswith("blocked")),
                            ends[0].draft_decision)
            yield PredictedRow(
                flow=flow, draft_decision=decision,
                blocking_rules=_union(h for v in ends for h in v.deny_rule_hrefs + v.override_deny_hrefs),
                allow_rules=_union(h for v in ends for h in v.allow_rule_hrefs),
                essential_service_rules=_union(h for v in ends for h in v.essential_service_rules))
    return _Recompute(at=at, rows=rows(), rules=rules, capped=result.capped, unsupported=False, gen=gen)


def predict_blocks(ctx: AppContext, spec: FilterSpec, *, limit: int = 1000, max_results: int = 200_000,
                   deadline_seconds: int = 900) -> PredictedBlock:
    rc = _recompute(ctx, spec, max_results=max_results, deadline_seconds=deadline_seconds)
    if rc.unsupported:
        return PredictedBlock(rows=[], rules={}, capped=False, limit_hit=False, computed_at=rc.at, unsupported=True,
                              missing_rules=[])
    rows = list(rc.rows)
    if ctx.flows().generation != rc.gen:
        raise StaleGeneration
    named = {h for r in rows for h in (*r.blocking_rules, *r.allow_rules)}
    return PredictedBlock(rows=rows[:limit], rules={h: rc.rules[h] for h in sorted(named) if h in rc.rules},
                          capped=rc.capped, limit_hit=len(rows) > limit, computed_at=rc.at, unsupported=False,
                          missing_rules=sorted(named - rc.rules.keys()))


class PredictedGroup(BaseModel):
    dst_app: str | None
    rule_href: str
    flows: int
    connections: int


class PredictedSummary(BaseModel):
    """A draft recompute counted by destination app and blocking rule (the readiness report): the rows are
    counted as they come and not kept."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    groups: list[PredictedGroup]  # most connections first
    rules: dict[str, RuleRef]
    blocked_flows: int
    blocked_connections: int
    undetermined_flows: int  # the PCE gave no draft decision: zero blocked is then not a confirmed answer
    capped: bool
    computed_at: datetime
    unsupported: bool
    missing_rules: list[str]


def predicted_summary(ctx: AppContext, spec: FilterSpec, *, app_key: str = "app", max_results: int = 200_000,
                      deadline_seconds: int = 900) -> PredictedSummary:
    rc = _recompute(ctx, spec, max_results=max_results, deadline_seconds=deadline_seconds)
    counts: dict[tuple[str | None, str], list[int]] = {}
    flows = connections = 0
    undetermined = 0
    for row in rc.rows:
        if not row.flow.dst_managed:  # what enforcement would block is traffic into managed hosts
            continue
        if row.draft_decision not in DECIDED and not row.draft_decision.startswith("blocked"):
            undetermined += 1
            continue
        if not row.draft_decision.startswith("blocked"):
            continue
        flows += 1
        connections += row.flow.num_connections
        for href in row.blocking_rules or ["?"]:
            c = counts.setdefault((row.flow.dst_labels.get(app_key), href), [0, 0])
            c[0] += 1
            c[1] += row.flow.num_connections
    if ctx.flows().generation != rc.gen:
        raise StaleGeneration
    named = {h for _, h in counts if h != "?"}
    groups = sorted((PredictedGroup(dst_app=app, rule_href=h, flows=f, connections=n) for (app, h), (f, n) in counts.items()),
                    key=lambda g: (-g.connections, g.dst_app or "", g.rule_href))
    return PredictedSummary(groups=groups, rules={h: rc.rules[h] for h in sorted(named) if h in rc.rules},
                            blocked_flows=flows, blocked_connections=connections, undetermined_flows=undetermined,
                            capped=rc.capped,
                            computed_at=rc.at, unsupported=rc.unsupported, missing_rules=sorted(named - rc.rules.keys()))


def _union(hrefs: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(hrefs))
