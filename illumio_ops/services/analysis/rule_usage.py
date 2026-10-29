"""Rule usage (spec §6.5 policy_usage, P5c-1; user 2026-10-29, plan A): which draft rules the period's traffic used,
from the PCE's own draft recompute — an ordinary traffic query names no rules (lab, 2026-10-29), only one followed by
update_rules does. Active rules' real hits are the Rule Hit Count report; with nothing pending, the draft is the active
policy, which the report says.

The period is read a day at a time (each answer is held whole while it is read, about 200 MB for 50,000 rows); a day
at the cap is halved up to MAX_SPLITS times, and what still caps is kept and reported as truncated. Each window's
rows are counted and let go. Nothing is stored: the answer changes with every draft edit (spec §6.4)."""
from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.flows import group_pairs, record_key
from illumio_ops.domain.policy import RuleRef, index_rules
from illumio_ops.domain.values import CapabilityState
from illumio_ops.pce.async_query import (
    PceQueryError,
    run_traffic_query,
    traffic_payload,
)
from illumio_ops.pce.client import PceClient
from illumio_ops.pce.policy import (
    PendingItem,
    fetch_pending,
    fetch_policy_names,
    fetch_rule_sets,
)
from illumio_ops.services.analysis.predicted_block import draft_records
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import pair_row
from illumio_ops.store.flowdb import capabilities

WINDOW = timedelta(days=1)
PER_QUERY = 50_000
MAX_SPLITS = 3
QUERY_DEADLINE_SECONDS = 900
TOP_PAIRS = 3
NO_RULE_TOP = 50
APP = "app"


class RuleHits(BaseModel):
    flows: int = 0
    connections: int = 0
    top_pairs: list[tuple[str | None, str | None, int]] = []  # (source app, destination app, connections)


class NoRuleGroup(BaseModel):
    """Connections no rule allows and no Deny Rule blocks: they pass now only because the destination is not
    enforced, or are blocked by default once it is."""
    src_app: str | None
    dst_app: str | None
    port: int | None
    proto: int
    connections: int


class RuleUsage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    rules: dict[str, RuleRef]
    hits: dict[str, RuleHits]
    no_rule: list[NoRuleGroup]
    no_rule_total: int  # groups, before the top NO_RULE_TOP
    windows: int
    truncated: list[tuple[datetime, datetime]]
    unsupported: bool
    pending: list[PendingItem]
    computed_at: datetime


class _Counts:
    def __init__(self) -> None:
        self.flows: Counter[str] = Counter()
        self.connections: Counter[str] = Counter()
        self.pairs: Counter[tuple[str, str | None, str | None]] = Counter()
        self.no_rule: Counter[tuple[str | None, str | None, int | None, int]] = Counter()
        self.windows = 0
        self.truncated: list[tuple[datetime, datetime]] = []


def _count(raws: list[dict[str, Any]], c: _Counts) -> None:
    records, views = draft_records(raws)
    for primary, partner in group_pairs(records):
        flow = pair_row(primary, partner)
        ends = [views[record_key(primary)]] + ([views[record_key(partner)]] if partner is not None else [])
        allows = dict.fromkeys(h for v in ends for h in v.allow_rule_hrefs)
        denies = dict.fromkeys(h for v in ends for h in (*v.deny_rule_hrefs, *v.override_deny_hrefs))
        n = flow.num_connections
        sa, da = flow.src_labels.get(APP) or None, flow.dst_labels.get(APP) or None
        for h in (*allows, *denies):
            c.flows[h] += 1
            c.connections[h] += n
            c.pairs[(h, sa, da)] += n
        decided_allowed = any(v.draft_decision == "allowed" for v in ends)
        if not allows and not denies and not decided_allowed:
            c.no_rule[(sa, da, flow.port, flow.proto)] += n


def _walk(client: PceClient, a: datetime, b: datetime, depth: int, c: _Counts) -> None:
    result = run_traffic_query(client, traffic_payload(a, b, max_results=PER_QUERY, query_name="illumio-ops rule usage"),
                               deadline=time.monotonic() + QUERY_DEADLINE_SECONDS, compute_draft=True)
    c.windows += 1
    if result.capped and depth < MAX_SPLITS:
        del result  # not held while the halves are read
        mid = a + (b - a) / 2
        _walk(client, a, mid, depth + 1, c)
        _walk(client, mid, b, depth + 1, c)
        return
    if result.capped:
        c.truncated.append((a, b))
    _count(result.rows, c)


def rule_usage(ctx: AppContext, *, start: datetime, end: datetime, now: datetime | None = None) -> RuleUsage:
    """Raises a PCE failure (the report says it could not be computed); update_rules answering 404 is
    `unsupported`, recorded as the PCE's capability."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current()
    c = _Counts()
    deadline = time.monotonic() + QUERY_DEADLINE_SECONDS
    with ctx.pce_client(settings.pce) as client:
        pending = fetch_pending(client, deadline=deadline)
        rules = index_rules(fetch_rule_sets(client, "draft", deadline=deadline),
                            **fetch_policy_names(client, "draft", deadline=deadline).__dict__)
        cur = start
        try:
            while cur < end:
                nxt = min(cur + WINDOW, end)
                _walk(client, cur, nxt, 0, c)
                cur = nxt
        except PceQueryError as exc:
            if exc.stage == "update_rules" and exc.status == 404:
                fdb = ctx.flows()
                with fdb.writing(fdb.generation) as conn:
                    capabilities.record(conn, "draft_recompute", CapabilityState.UNSUPPORTED,
                                        "update_rules answered 404", at)
                return RuleUsage(rules=rules, hits={}, no_rule=[], no_rule_total=0, windows=c.windows, truncated=[],
                                 unsupported=True, pending=pending, computed_at=at)
            raise
    hits = {h: RuleHits(flows=c.flows[h], connections=c.connections[h],
                        top_pairs=sorted(((sa, da, n) for (rh, sa, da), n in c.pairs.items() if rh == h),
                                         key=lambda p: (-p[2], p[0] or "", p[1] or ""))[:TOP_PAIRS])
            for h in c.flows}
    groups = sorted(c.no_rule.items(), key=lambda kv: (-kv[1], kv[0][0] or "", kv[0][1] or "", kv[0][2] or 0))
    return RuleUsage(rules=rules, hits=hits,
                     no_rule=[NoRuleGroup(src_app=k[0], dst_app=k[1], port=k[2], proto=k[3], connections=n)
                              for k, n in groups[:NO_RULE_TOP]],
                     no_rule_total=len(groups), windows=c.windows, truncated=c.truncated, unsupported=False,
                     pending=pending, computed_at=at)
