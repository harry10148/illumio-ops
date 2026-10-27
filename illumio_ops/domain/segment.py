"""Analysis segments (spec §6.3 point 4): a filter, a grouping of at most two levels, a metric and a view.

The workbench, a report section with flows or events as its data, and an alert's evidence are all
segments; compile_flow_ranking / compile_event_ranking are the one place their numbers are computed,
so the screen and the report agree. The SQL reads the flow store's primary rows (one per connection,
both sides' attributes merged at ingest) and the events table.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from illumio_ops.domain.filter import FilterSpec, PortProto, like_pattern, to_sql
from illumio_ops.domain.timefmt import store_time
from illumio_ops.domain.values import SegmentDimension, SegmentMetric, SegmentView

FLOW_DIMENSIONS = frozenset({
    SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST, SegmentDimension.SRC_LABEL, SegmentDimension.DST_LABEL,
    SegmentDimension.SERVICE, SegmentDimension.INITIATOR_PROCESS, SegmentDimension.INITIATOR_USER,
    SegmentDimension.SERVICE_PROCESS, SegmentDimension.SERVICE_USER, SegmentDimension.DECISION,
    SegmentDimension.DIRECTION,
})
EVENT_DIMENSIONS = frozenset({
    SegmentDimension.EVENT_TYPE, SegmentDimension.EVENT_HOST, SegmentDimension.EVENT_SEVERITY,
    SegmentDimension.ACTOR,
})
_LABEL_DIMENSIONS = frozenset({SegmentDimension.SRC_LABEL, SegmentDimension.DST_LABEL})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GroupBy(_Model):
    dimension: SegmentDimension
    label_key: str | None = Field(default=None, min_length=1)  # required for src_label / dst_label only

    @model_validator(mode="after")
    def _key(self) -> GroupBy:
        if (self.dimension in _LABEL_DIMENSIONS) != (self.label_key is not None):
            raise ValueError("a label dimension needs a label key, and only a label dimension has one")
        return self


def _check_shape(view: SegmentView, group_by: tuple[GroupBy, ...], allowed: frozenset[SegmentDimension]) -> None:
    if view is SegmentView.RANKING and not group_by:
        raise ValueError("a ranking groups by at least one dimension")
    if view is not SegmentView.RANKING and group_by:
        raise ValueError("only a ranking is grouped")
    if any(g.dimension not in allowed for g in group_by):
        raise ValueError("a dimension of the other data source")


class FlowSegment(_Model):
    filter: FilterSpec
    group_by: tuple[GroupBy, ...] = Field(default=(), max_length=2)
    metric: SegmentMetric = SegmentMetric.FLOWS
    view: SegmentView
    limit: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def _shape(self) -> FlowSegment:
        _check_shape(self.view, self.group_by, FLOW_DIMENSIONS)
        if self.metric is SegmentMetric.EVENTS:
            raise ValueError("events is the metric of event segments")
        return self


class EventFilter(_Model):
    start: AwareDatetime
    end: AwareDatetime
    event_types: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    host_hrefs: tuple[str, ...] = ()
    actor: str | None = Field(default=None, min_length=1)  # partial match, like_pattern semantics

    @model_validator(mode="after")
    def _window(self) -> EventFilter:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class EventSegment(_Model):
    filter: EventFilter
    group_by: tuple[GroupBy, ...] = Field(default=(), max_length=2)
    metric: SegmentMetric = SegmentMetric.EVENTS
    view: SegmentView
    limit: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def _shape(self) -> EventSegment:
        if self.view is SegmentView.PREDICTED_BLOCK:
            raise ValueError("events have no predicted-block view")
        if self.metric is not SegmentMetric.EVENTS:
            raise ValueError("an event segment counts events")
        _check_shape(self.view, self.group_by, EVENT_DIMENSIONS)
        return self


# ── flows ────────────────────────────────────────────────────────────────────

def user_key_sql(column: str) -> str:
    """The SQL that makes one user of an account's spellings (shared with the findings engine)."""
    return _user(column)


def _user(column: str) -> str:
    """Domain accounts (DOMAIN\\acct, acct@domain) are case-insensitive; local Linux accounts are not."""
    return (f"CASE WHEN instr({column}, '\\') > 0 OR instr({column}, '@') > 0 "
            f"THEN lower({column}) ELSE {column} END")


_FLOW_COLUMNS: dict[SegmentDimension, str] = {
    SegmentDimension.SRC_HOST: "f.src_key",
    SegmentDimension.DST_HOST: "f.dst_key",
    SegmentDimension.SERVICE: "COALESCE(f.port, -1) || '/' || f.proto",
    SegmentDimension.INITIATOR_PROCESS: "f.initiator_process",
    SegmentDimension.INITIATOR_USER: _user("f.initiator_user"),
    SegmentDimension.SERVICE_PROCESS: "f.service_process",
    SegmentDimension.SERVICE_USER: _user("f.service_user"),
    SegmentDimension.DECISION: "f.policy_decision",
    SegmentDimension.DIRECTION: "f.direction",
}
# What a host key is shown as: any hostname the store has for it, else the key (an IP for unmanaged ends).
_HOST_DISPLAY = {SegmentDimension.SRC_HOST: "MAX(f.src_hostname)", SegmentDimension.DST_HOST: "MAX(f.dst_hostname)"}

_METRICS: dict[SegmentMetric, str] = {
    SegmentMetric.FLOWS: "COUNT(*)",
    SegmentMetric.CONNECTIONS: "SUM(f.num_connections)",
    SegmentMetric.DISTINCT_DST: "COUNT(DISTINCT f.dst_key)",
    SegmentMetric.DISTINCT_SRC: "COUNT(DISTINCT f.src_key)",
    SegmentMetric.DISTINCT_PORTS: "COUNT(DISTINCT COALESCE(f.port, -1) || '/' || f.proto)",
    SegmentMetric.BYTES: "SUM(COALESCE(f.bytes_in, 0) + COALESCE(f.bytes_out, 0))",
}


def compile_flow_ranking(seg: FlowSegment, *, wide: bool = False) -> tuple[str, list[Any]]:
    """SELECT k0, d0[, k1, d1], value, bytes_known ... LIMIT limit + 1 (one more row says the limit was hit).
    k = the group key, d = what to show for it (NULL when the key itself is shown)."""
    joins: list[str] = []
    params: list[Any] = []
    keys: list[str] = []
    select: list[str] = []
    for i, g in enumerate(seg.group_by):
        if g.dimension in _LABEL_DIMENSIONS:
            side = "src" if g.dimension is SegmentDimension.SRC_LABEL else "dst"
            joins.append(f"LEFT JOIN label_set_members l{i} ON l{i}.set_id = f.{side}_label_set AND l{i}.key = ?")
            params.append(g.label_key)
            column = f"l{i}.value"
        else:
            column = _FLOW_COLUMNS[g.dimension]
        keys.append(column)
        select += [f"{column} AS k{i}", f"{_HOST_DISPLAY.get(g.dimension, 'NULL')} AS d{i}"]
    where, where_params = to_sql(seg.filter, wide=wide)
    bytes_known = "COUNT(f.bytes_in)" if seg.metric is SegmentMetric.BYTES else "NULL"
    sql = (f"SELECT {', '.join(select)}, {_METRICS[seg.metric]} AS value, {bytes_known} AS bytes_known "
           f"FROM flows f {' '.join(joins)} WHERE {where} GROUP BY {', '.join(keys)} "
           f"ORDER BY value DESC, {', '.join(keys)} LIMIT ?")
    return sql, [*params, *where_params, seg.limit + 1]


FIELD_COVERAGE_SQL = ("SELECT COUNT(*) AS total, COUNT(f.initiator_process) AS initiator_process, "
                      "COUNT(f.initiator_user) AS initiator_user, COUNT(f.service_process) AS service_process, "
                      "COUNT(f.service_user) AS service_user, COUNT(f.bytes_in) AS bytes FROM flows f WHERE {where}")


# ── events ───────────────────────────────────────────────────────────────────

_EVENT_COLUMNS: dict[SegmentDimension, str] = {
    SegmentDimension.EVENT_TYPE: "e.event_type",
    SegmentDimension.EVENT_HOST: "COALESCE(w.hostname, e.created_by_name)",
    SegmentDimension.EVENT_SEVERITY: "e.severity",
    SegmentDimension.ACTOR: "e.created_by_name",
}
# Events name the VEN that sent them, not the workload (P2 ruling): hosts are joined through it.
EVENT_FROM = "FROM events e LEFT JOIN workloads w ON w.ven_href = e.created_by_href"


def compile_event_where(f: EventFilter) -> tuple[str, list[Any]]:
    clauses = ["e.timestamp >= ?", "e.timestamp <= ?"]
    params: list[Any] = [store_time(f.start), store_time(f.end)]
    for column, values in (("e.event_type", f.event_types), ("e.severity", f.severities)):
        if values:
            clauses.append(f"{column} IN ({','.join('?' * len(values))})")
            params.extend(values)
    if f.host_hrefs:
        marks = ",".join("?" * len(f.host_hrefs))
        clauses.append(f"(e.workload_href IN ({marks}) OR w.href IN ({marks}))")
        params.extend([*f.host_hrefs, *f.host_hrefs])
    if f.actor:
        clauses.append("e.created_by_name LIKE ? ESCAPE '\\'")
        params.append(like_pattern(f.actor))
    return " AND ".join(clauses), params


def compile_event_ranking(seg: EventSegment) -> tuple[str, list[Any]]:
    keys = [_EVENT_COLUMNS[g.dimension] for g in seg.group_by]
    select = [f"{k} AS k{i}, NULL AS d{i}" for i, k in enumerate(keys)]
    where, params = compile_event_where(seg.filter)
    sql = (f"SELECT {', '.join(select)}, COUNT(*) AS value, NULL AS bytes_known {EVENT_FROM} WHERE {where} "
           f"GROUP BY {', '.join(keys)} ORDER BY value DESC, {', '.join(keys)} LIMIT ?")
    return sql, [*params, seg.limit + 1]


# ── the lateral-movement defaults (spec §6.5.7) ──────────────────────────────

def lateral_default_segments(admin_ports: Sequence[PortProto], *, start: datetime,
                             end: datetime) -> dict[str, FlowSegment]:
    """The workbench's default rankings and the report's "users and processes" section use these, never
    their own copies. system_accounts_on_admin ranks every initiating account: its caller keeps only the
    rows is_system_account says yes to (the filter has no "only system accounts" condition)."""
    ports = tuple(admin_ports)

    def ranking(dim: SegmentDimension, *, exclude_system: bool) -> FlowSegment:
        return FlowSegment(
            filter=FilterSpec(start=start, end=end, ports=ports, exclude_system_accounts=exclude_system),
            group_by=(GroupBy(dimension=dim),), metric=SegmentMetric.DISTINCT_DST, view=SegmentView.RANKING,
            limit=50)

    return {
        "admin_initiator_users": ranking(SegmentDimension.INITIATOR_USER, exclude_system=True),
        "admin_initiator_processes": ranking(SegmentDimension.INITIATOR_PROCESS, exclude_system=False),
        "system_accounts_on_admin": ranking(SegmentDimension.INITIATOR_USER, exclude_system=False),
    }
