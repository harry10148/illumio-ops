"""Predicted blocks (spec §6.5.3 預計阻擋, §6.6 F1): the PCE recomputes a filter's flows against the draft
policy (async query, then update_rules, about a minute), and each flow is shown with the deny rules that
would block it. Not stored: the answer changes with every draft edit (spec §6.4)."""
from __future__ import annotations

import time
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.filter import FilterSpec, matches, to_pce_payload
from illumio_ops.domain.flows import FlowShapeError, normalize_flow
from illumio_ops.domain.policy import RuleRef, index_rules, parse_draft
from illumio_ops.domain.values import CapabilityState
from illumio_ops.pce.async_query import PceQueryError, run_traffic_query
from illumio_ops.pce.policy import fetch_policy_names, fetch_rule_sets
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import FlowRow, live_row
from illumio_ops.store.flowdb import capabilities

_ALWAYS = (datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC))


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


def predict_blocks(ctx: AppContext, spec: FilterSpec, *, limit: int = 1000, max_results: int = 200_000,
                   deadline_seconds: int = 900) -> PredictedBlock:
    at = datetime.now(UTC)
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
                fdb = ctx.flows()
                with fdb.writing(fdb.generation) as conn:
                    capabilities.record(conn, "draft_recompute", CapabilityState.UNSUPPORTED,
                                        "update_rules answered 404", at)
                return PredictedBlock(rows=[], rules={}, capped=False, limit_hit=False, computed_at=at,
                                      unsupported=True, missing_rules=[])
            raise
        rules = index_rules(fetch_rule_sets(client, "draft", deadline=deadline),
                            **fetch_policy_names(client, "draft", deadline=deadline).__dict__)
    rows: list[PredictedRow] = []
    for raw in result.rows:
        try:
            flow = live_row(normalize_flow(raw))
        except FlowShapeError:
            continue
        if not matches(residual, flow.model_dump()):
            continue
        view = parse_draft(raw)
        rows.append(PredictedRow(flow=flow, draft_decision=view.draft_decision,
                                 blocking_rules=list(view.deny_rule_hrefs + view.override_deny_hrefs),
                                 allow_rules=list(view.allow_rule_hrefs),
                                 essential_service_rules=list(view.essential_service_rules)))
    named = {h for r in rows for h in (*r.blocking_rules, *r.allow_rules)}
    return PredictedBlock(rows=rows[:limit], rules={h: rules[h] for h in sorted(named) if h in rules},
                          capped=result.capped, limit_hit=len(rows) > limit, computed_at=at, unsupported=False,
                          missing_rules=sorted(named - rules.keys()))
