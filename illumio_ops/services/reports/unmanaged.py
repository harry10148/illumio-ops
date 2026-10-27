"""The unmanaged endpoints report (spec §6.5.5 盤點, split out of 5.x traffic): addresses without a VEN that
managed hosts talk to, from the daily rollups — which could get a VEN, which use management ports, which are on
the internet."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from illumio_ops.domain.anomaly import is_public
from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
)
from illumio_ops.domain.values import Severity
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import port_text, tr
from illumio_ops.services.reports.generate import (
    coverage_note,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.registry import BuildInput

ROW_LIMIT = 100_000
CANDIDATE_MIN_PEERS = 3
TOP_PORTS = 3
DECISION_KEYS = {"allowed": "decision_allowed", "potentially_blocked": "decision_potentially_blocked",
                 "blocked": "decision_blocked", "unknown": "decision_unknown"}
# One side of each rollup row is a managed host and the other an address without a VEN.
_SIDES = ("SELECT src_key AS ep, 'in' AS dir, dst_key AS peer, port, proto, policy_decision, connections, day "
          "FROM flow_rollup_daily WHERE day >= ? AND day <= ? AND src_key LIKE 'ip:%' AND dst_key NOT LIKE 'ip:%' "
          "UNION ALL "
          "SELECT dst_key, 'out', src_key, port, proto, policy_decision, connections, day "
          "FROM flow_rollup_daily WHERE day >= ? AND day <= ? AND dst_key LIKE 'ip:%' AND src_key NOT LIKE 'ip:%'")


@dataclass
class _Endpoint:
    key: str
    dirs: set[str]
    peers: int
    connections: int
    first_day: str
    last_day: str
    decisions: list[str]
    ports: list[tuple[int, int, int]] = field(default_factory=list)  # (connections, port, proto), busiest first
    admin_in: list[tuple[int, int]] = field(default_factory=list)    # management ports it connected to managed hosts on
    admin_peers: int = 0                                               # managed hosts it reached on those ports

    @property
    def address(self) -> str:
        return self.key[3:]


def _endpoints(conn: sqlite3.Connection, days: tuple[str, str],
               admin: list[tuple[int, int | None]]) -> dict[str, _Endpoint]:
    params = [*days, *days]
    out = {r[0]: _Endpoint(key=r[0], dirs=set(str(r[1]).split(",")), peers=r[2], connections=r[3], first_day=r[4],
                           last_day=r[5], decisions=sorted(set(str(r[6]).split(","))))
           for r in conn.execute(f"SELECT ep, group_concat(DISTINCT dir), COUNT(DISTINCT peer), SUM(connections), "
                                 f"MIN(day), MAX(day), group_concat(DISTINCT policy_decision) FROM ({_SIDES}) "
                                 "GROUP BY ep", params)}
    by_port: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for ep, port, proto, n in conn.execute(f"SELECT ep, port, proto, SUM(connections) FROM ({_SIDES}) "
                                           "GROUP BY ep, port, proto", params):
        by_port[ep].append((int(n), port, proto))
    for ep, ports in by_port.items():
        if ep in out:
            out[ep].ports = sorted(ports, key=lambda x: (-x[0], x[1]))
    if admin:  # only connections the unmanaged end started into managed hosts (dir 'in'), on management ports
        clause, admin_params = reads.port_clause(admin)
        inbound = f"SELECT * FROM ({_SIDES}) WHERE dir = 'in' AND {clause}"
        for ep, port, proto in conn.execute(f"SELECT DISTINCT ep, port, proto FROM ({inbound}) ORDER BY port",
                                            [*params, *admin_params]):
            out[ep].admin_in.append((port, proto))
        for ep, peers in conn.execute(f"SELECT ep, COUNT(DISTINCT peer) FROM ({inbound}) GROUP BY ep",
                                      [*params, *admin_params]):
            out[ep].admin_peers = int(peers)
    return out


def build_unmanaged(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=inp.now)
    admin = [(e.port, e.proto) for e in lc.admin_ports.entries]
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)
    prev_known = traffic_covered(inp.ctx, prev_start, inp.start, now=inp.now)
    with reads.reading(inp.ctx) as conn:
        now_eps = _endpoints(conn, reads.utc_days(inp.start, inp.end), admin)
        before_eps = _endpoints(conn, reads.utc_days(prev_start, inp.start), admin) if prev_known else {}

    def counts(eps: dict[str, _Endpoint]) -> dict[str, int]:
        return {"total": len(eps), "private": sum(1 for e in eps.values() if not is_public(e.address)),
                "admin_sources": sum(1 for e in eps.values() if e.admin_in),
                "public": sum(1 for e in eps.values() if is_public(e.address))}

    now_c, before_c = counts(now_eps), counts(before_eps)
    labels = {"total": "rpt_unm_kpi_total", "private": "rpt_unm_kpi_private",
              "admin_sources": "rpt_unm_kpi_admin_sources", "public": "rpt_unm_kpi_public"}
    kpis = tuple(Kpi(key=k, label=t(labels[k]), value=now_c[k], previous=before_c[k] if prev_known else None,
                     better="lower") for k in labels)

    def direction(e: _Endpoint) -> str:
        if e.dirs >= {"in", "out"}:
            return t("rpt_unm_dir_both")
        return t("rpt_unm_dir_in") if "in" in e.dirs else t("rpt_unm_dir_out")

    def scope(e: _Endpoint) -> str:
        return t("rpt_unm_public") if is_public(e.address) else t("rpt_unm_private")

    def top_ports(e: _Endpoint) -> str:
        return ", ".join(port_text(p, q) for _, p, q in e.ports[:TOP_PORTS])

    def decisions(e: _Endpoint) -> str:
        return ", ".join(t(DECISION_KEYS.get(d, "decision_unknown")) for d in e.decisions)

    ordered = sorted(now_eps.values(), key=lambda e: (-e.peers, -e.connections, e.key))
    columns = (Column(key="address", label=t("rpt_col_address")), Column(key="scope", label=t("rpt_col_scope")),
               Column(key="direction", label=t("rpt_col_direction")),
               Column(key="peers", label=t("rpt_col_managed_peers"), kind="number"),
               Column(key="connections", label=t("rpt_col_connections"), kind="number"),
               Column(key="ports", label=t("rpt_col_top_ports")), Column(key="decisions", label=t("rpt_col_decisions")),
               Column(key="first", label=t("rpt_col_first_day")), Column(key="last", label=t("rpt_col_last_day")))

    def row(e: _Endpoint) -> tuple[Any, ...]:
        return (e.address, scope(e), direction(e), e.peers, e.connections, top_ports(e), decisions(e), e.first_day,
                e.last_day)

    shown = ordered[:ROW_LIMIT]
    all_table = TableBlock(title=t("rpt_unm_tbl_all"), columns=columns, rows=tuple(row(e) for e in shown),
                           total_rows=len(ordered), empty_text=t("rpt_unm_none"),
                           limit_note=t("rpt_limit_top", shown=f"{len(shown):,}", total=f"{len(ordered):,}")
                           if len(ordered) > len(shown) else None)
    candidates = [e for e in ordered if not is_public(e.address) and e.peers >= CANDIDATE_MIN_PEERS]
    cand_table = TableBlock(title=t("rpt_unm_tbl_candidates"), columns=columns,
                            rows=tuple(row(e) for e in candidates), total_rows=len(candidates),
                            empty_text=t("rpt_unm_candidates_none", n=CANDIDATE_MIN_PEERS))
    admin_eps = sorted((e for e in ordered if e.admin_in), key=lambda e: (-e.admin_peers, e.key))
    admin_table = TableBlock(title=t("rpt_unm_tbl_admin"), columns=(
        Column(key="address", label=t("rpt_col_address")), Column(key="scope", label=t("rpt_col_scope")),
        Column(key="ports", label=t("rpt_col_admin_ports")),
        Column(key="peers", label=t("rpt_col_managed_peers"), kind="number")),
        rows=tuple((e.address, scope(e), ", ".join(port_text(p, q) for p, q in e.admin_in), e.admin_peers)
                   for e in admin_eps),
        total_rows=len(admin_eps), empty_text=t("rpt_unm_admin_none"))
    public = [e for e in ordered if is_public(e.address)]
    public_table = TableBlock(title=t("rpt_unm_tbl_public"), columns=columns, rows=tuple(row(e) for e in public),
                              total_rows=len(public), empty_text=t("rpt_unm_public_none"))
    findings = tuple(Finding(severity=Severity.MEDIUM if not is_public(e.address) else Severity.HIGH,
                             title=t("rpt_unm_finding_admin", address=e.address,
                                     ports=", ".join(port_text(p, q) for p, q in e.admin_in), peers=e.admin_peers),
                             why=t("rpt_unm_why_admin"), action=t("rpt_unm_action_admin")) for e in admin_eps[:5])
    quality = (*coverage_note(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz), t("rpt_quality_utc_days"))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_unmanaged"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=findings,
        data_quality=quality,
        sections=(Section(id="candidates", title=t("rpt_unm_sec_candidates"),
                          intro=t("rpt_unm_candidates_intro", n=CANDIDATE_MIN_PEERS), blocks=(cand_table,)),
                  Section(id="admin", title=t("rpt_unm_sec_admin"), blocks=(admin_table,)),
                  Section(id="public", title=t("rpt_unm_sec_public"), blocks=(public_table,)),
                  Section(id="all", title=t("rpt_unm_sec_all"), intro=t("rpt_unm_intro"), blocks=(all_table,))))
