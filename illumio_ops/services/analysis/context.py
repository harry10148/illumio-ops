"""The lateral-movement context every analysis starts from: the settings snapshot, the management port
set, the host index (critical assets, admin groups) and how much baseline has accumulated."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.lateral import (
    AdminPortSet,
    HostInfo,
    Selector,
    effective_admin_ports,
    selector_matches,
    stale_selectors,
)
from illumio_ops.domain.values import LATERAL_PORTS_DEFAULT, IngestSource
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import LabelSelector, LateralSettings
from illumio_ops.store.flowdb import ingest_state, labels, ransomware, workloads

StaleSelector = tuple[Literal["critical_assets", "admin_groups"], str, str]


@dataclass(frozen=True)
class LateralContext:
    settings: LateralSettings
    admin_ports: AdminPortSet
    hosts: Mapping[str, HostInfo]               # endpoint_key(href) -> host, current inventory only
    label_sets: Mapping[int, Mapping[str, str]]  # the inventory's label sets
    known_labels: frozenset[Selector]
    collected: bool                              # collection is on and the mode reads traffic
    baseline_days: float                         # length of the coverage stretch that reaches the watermark
    baseline_required: int
    baseline_backfilling: bool                   # the initial backfill has not finished
    stale: tuple[StaleSelector, ...]
    traffic_watermark: datetime | None
    generation: int

    def baseline_full(self) -> bool:
        return not self.baseline_backfilling and self.baseline_days >= self.baseline_required


def _selectors(entries: tuple[LabelSelector, ...]) -> list[Selector]:
    return [(e.key, e.value) for e in entries]


def _baseline_days(ranges: list[tuple[datetime, datetime]], watermark: datetime | None, cap: int) -> float:
    """Only the stretch that reaches the watermark counts: the initial backfill writes oldest first, so an
    early range far from the live one says nothing about the days in between."""
    if watermark is None:
        return 0.0
    for a, b in ranges:
        if a <= watermark <= b:
            return min((watermark - a) / timedelta(days=1), float(cap))
    return 0.0


def load_lateral_context(ctx: AppContext, *, now: datetime) -> LateralContext:
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    lat = settings.lateral
    critical = _selectors(lat.critical_assets)
    admin = _selectors(lat.admin_groups)
    with fdb.connect() as conn:
        inventory = workloads.all_workloads(conn)
        sets = labels.label_sets(conn, {w.label_set for w in inventory if w.label_set is not None})
        known = frozenset(labels.known_labels(conn))
        pce_admin = ransomware.admin_services(conn)
        traffic = ingest_state.get(conn, IngestSource.TRAFFIC)
        ranges = ingest_state.coverage(conn, IngestSource.TRAFFIC)
        backfill = ingest_state.get(conn, IngestSource.BACKFILL)
    initial: dict[str, object] = ((backfill.progress or {}) if backfill else {}).get("initial") or {}
    watermark = traffic.watermark if traffic else None
    hosts = {}
    for w in inventory:
        host_labels = sets.get(w.label_set, {}) if w.label_set is not None else {}
        hosts[endpoint_key(w.href, "")] = HostInfo(
            key=endpoint_key(w.href, ""), href=w.href, hostname=w.hostname, managed=bool(w.managed),
            labels=host_labels, enforcement_mode=w.enforcement_mode, visibility_level=w.visibility_level,
            os_id=w.os_id, ven_href=w.ven_href, critical=selector_matches(host_labels, critical),
            admin_group=selector_matches(host_labels, admin))
    stale: list[StaleSelector] = [("critical_assets", k, v) for k, v in stale_selectors(critical, known)]
    stale += [("admin_groups", k, v) for k, v in stale_selectors(admin, known)]
    required = settings.collection.retention.baseline_days
    return LateralContext(
        settings=lat,
        admin_ports=effective_admin_ports(
            LATERAL_PORTS_DEFAULT, pce_admin, extra=[(e.port, e.proto, e.category) for e in lat.extra_admin_ports],
            removed=[(e.port, e.proto) for e in lat.removed_admin_ports], include_pce=lat.include_pce_admin_services),
        hosts=hosts, label_sets=sets, known_labels=known, collected=ctx.ondemand or collects(settings, IngestSource.TRAFFIC),
        baseline_days=_baseline_days(ranges, watermark, required), baseline_required=required,
        baseline_backfilling=bool(initial) and not initial.get("finished"), stale=tuple(stale),  # same test as reread
        traffic_watermark=watermark, generation=gen)


def host_for(lc: LateralContext, key: str, *, ip: str, hostname: str | None,
             labels: Mapping[str, str] | None = None) -> HostInfo:
    """The inventory's host for a flow endpoint; an endpoint not in it (unmanaged, or a workload deleted
    since) is judged by the labels the flow carried."""
    known = lc.hosts.get(key)
    if known is not None:
        return known
    flow_labels = dict(labels or {})
    return HostInfo(key=key, href=None if key.startswith("ip:") else key, hostname=hostname or ip,
                    managed=False, labels=flow_labels, enforcement_mode=None, visibility_level=None, os_id=None,
                    ven_href=None, critical=selector_matches(flow_labels, _selectors(lc.settings.critical_assets)),
                    admin_group=selector_matches(flow_labels, _selectors(lc.settings.admin_groups)))
