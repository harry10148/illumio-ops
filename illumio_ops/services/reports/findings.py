"""The findings engine (5.x B001–B009 and L001–L010 over the v6 flow store; P5b-1 Task 2).

The period's primary flow rows are read once, grouped in SQLite into a temporary table (millions of groups at 1,000
hosts never enter Python); every rule is a query on that table. "Flows" are connection records (COUNT of primary
rows), as 5.x counted rows. What differs from 5.x:
- B001 grades by environment instead of comparing /24 subnets (works for IPv6; 5.x's subnet test was string slicing).
- Port sets are protocol-aware: a UDP reply on an ephemeral port numbered 445 is not SMB.
- Management ports (B006, L006, L008, L010) are the configured remote-execution class the detectors read.
- L006 reads the stored exposure graph (hosts) instead of a second BFS over apps.
- B008 compares each source → destination × port total over the period (rows are per-day buckets).
- INFO (B009) becomes LOW: v6 severities start at low.
- A rule that raises is reported as not evaluated; the others still run (5.x showed one ENG01 card).
"""
from __future__ import annotations

import json
import sqlite3
import traceback
from collections.abc import Callable, Collection
from datetime import datetime
from statistics import median
from typing import Any

from loguru import logger

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.findings_rules import (
    CLEARTEXT_PORTS,
    CRITICAL_PORTS,
    DB_PORTS,
    DISCOVERY_PORTS,
    HIGH_PORTS,
    IDENTITY_PORTS,
    MEDIUM_PORTS,
    WINDOWS_MGMT_PORTS,
    RuleOutcome,
    ranked,
)
from illumio_ops.domain.values import Language, PortClass, Severity
from illumio_ops.services import flowsource
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import host_name, port_text
from illumio_ops.settings.schema import ReportRuleThresholds
from illumio_ops.store.flowdb import analysis

MiB = 1024 * 1024
TOP = 5
_AGG = "rpt_agg"


def _ports(pairs: Collection[tuple[int, int | None]]) -> tuple[str, list[Any]]:
    return reads.port_clause(sorted(pairs, key=str))


CROSS_ENV = "src_env != '' AND dst_env != '' AND src_env != dst_env"


class _Run:
    def __init__(self, conn: sqlite3.Connection, t: ReportRuleThresholds, lang: Language, admin: set[tuple[int, int]],
                 names: Callable[[str], str], exposure: dict[str, Any] | None) -> None:
        self.conn, self.t, self.lang, self.admin, self.names, self.exposure = conn, t, lang, admin, names, exposure

    def sum(self, cond: str, params: list[Any], column: str = "flows") -> int:
        return int(self.conn.execute(f"SELECT COALESCE(SUM({column}), 0) FROM {_AGG} WHERE {cond}",
                                     params).fetchone()[0])

    def top(self, sql: str, params: list[Any]) -> str:
        """'name (n), …' for the top rows of a (key, count) query."""
        return ", ".join(f"{self.names(str(k))} ({n:,})" for k, n in self.conn.execute(sql + f" LIMIT {TOP}", params))

    def ports_text(self, cond: str, params: list[Any]) -> str:
        return ", ".join(f"{port_text(p, q)} ({n:,})" for p, q, n in self.conn.execute(
            f"SELECT port, proto, SUM(flows) AS n FROM {_AGG} WHERE {cond} GROUP BY port, proto ORDER BY n DESC "
            f"LIMIT {TOP}", params))


def _b001(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(CRITICAL_PORTS)
    base = f"{pc} AND decision != 'blocked'"
    total = r.sum(base, pp)
    if not total:
        return None
    allowed = r.sum(f"{base} AND decision = 'allowed'", pp)
    pb = r.sum(f"{base} AND decision = 'potentially_blocked'", pp)
    cross = r.sum(f"{base} AND {CROSS_ENV}", pp)
    cross_allowed = r.sum(f"{base} AND {CROSS_ENV} AND decision = 'allowed'", pp)
    params = {"n_total": total, "n_allowed": allowed, "n_pb": pb, "n_cross_env": cross,
              "named_ports": r.ports_text(base, pp),
              "top_destinations": r.top(f"SELECT dst_key, SUM(flows) n FROM {_AGG} WHERE {base} GROUP BY dst_key "
                                        "ORDER BY n DESC", pp)}
    if cross:
        rec = "rpt_rule_b001_rec_critical_cross_env" if cross_allowed else "rpt_rule_b001_rec_pb_cross_env"
        return RuleOutcome("B001", Severity.CRITICAL, "rpt_rule_b001_desc", rec, params)
    if allowed:
        return RuleOutcome("B001", Severity.HIGH, "rpt_rule_b001_desc", "rpt_rule_b001_rec_allowed", params)
    return RuleOutcome("B001", Severity.MEDIUM, "rpt_rule_b001_desc", "rpt_rule_b001_rec_pb", params)


def _simple(rule_id: str, ports: Collection[tuple[int, int | None]], decision: str, severity: Severity,
            desc: str, rec: str) -> Callable[[_Run], RuleOutcome | None]:
    def rule(r: _Run) -> RuleOutcome | None:
        pc, pp = _ports(ports)
        cond = f"{pc} AND decision = '{decision}'"
        n = r.sum(cond, pp)
        if not n:
            return None
        return RuleOutcome(rule_id, severity, desc, rec, {
            "n_flows": n, "named_ports": r.ports_text(cond, pp),
            "unique_src": r.conn.execute(f"SELECT COUNT(DISTINCT src_key) FROM {_AGG} WHERE {cond}", pp).fetchone()[0],
            "top_destinations": r.top(f"SELECT dst_key, SUM(flows) n FROM {_AGG} WHERE {cond} GROUP BY dst_key "
                                      "ORDER BY n DESC", pp)})
    return rule


def _b004(r: _Run) -> RuleOutcome | None:
    n = r.sum("src_managed = 0", [])
    if n <= r.t.unmanaged_connection:
        return None
    return RuleOutcome("B004", Severity.MEDIUM, "rpt_rule_b004_desc", "rpt_rule_b004_rec", {
        "n_flows": n, "threshold": r.t.unmanaged_connection,
        "top_sources": r.top(f"SELECT src_key, SUM(flows) n FROM {_AGG} WHERE src_managed = 0 GROUP BY src_key "
                             "ORDER BY n DESC", [])})


def _b005(r: _Run) -> RuleOutcome | None:
    total = r.sum("1", [])
    if not total:
        return None
    pct = 100 * r.sum("decision = 'allowed'", []) / total
    if pct >= r.t.min_policy_coverage_pct:
        return None
    return RuleOutcome("B005", Severity.MEDIUM, "rpt_rule_b005_desc", "rpt_rule_b005_rec", {
        "coverage_pct": f"{pct:.1f}", "threshold": f"{r.t.min_policy_coverage_pct:g}", "n_flows": total})


def _fanout(r: _Run, cond: str, params: list[Any], key: str, limit: int) -> list[tuple[str, int]]:
    return [(k, n) for k, n in r.conn.execute(
        f"SELECT {key}, COUNT(DISTINCT dst_key) AS n FROM {_AGG} WHERE {cond} GROUP BY {key} HAVING n > ? "
        "ORDER BY n DESC", [*params, limit])]


def _b006(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(r.admin)
    base = f"{pc} AND decision != 'blocked'"
    over = _fanout(r, base, pp, "src_key", r.t.lateral_outbound_dst)
    if not over:
        return None
    allowed_over = _fanout(r, f"{base} AND decision = 'allowed'", pp, "src_key", r.t.lateral_outbound_dst)
    sev, rec = ((Severity.HIGH, "rpt_rule_b006_rec_allowed") if allowed_over
                else (Severity.MEDIUM, "rpt_rule_b006_rec_pb"))
    return RuleOutcome("B006", sev, "rpt_rule_b006_desc", rec, {
        "n_sources": len(over), "threshold": r.t.lateral_outbound_dst,
        "top_sources": ", ".join(f"{r.names(k)} ({n})" for k, n in over[:TOP])})


def _b007(r: _Run) -> RuleOutcome | None:
    over = _fanout(r, "user != ''", [], "user", r.t.user_destination)
    if not over:
        return None
    return RuleOutcome("B007", Severity.HIGH, "rpt_rule_b007_desc", "rpt_rule_b007_rec", {
        "n_users": len(over), "threshold": r.t.user_destination,
        "top_users": ", ".join(f"{k} ({n})" for k, n in over[:TOP])})


def _b008(r: _Run) -> RuleOutcome | None:
    totals = [b for (b,) in r.conn.execute(
        f"SELECT SUM(bytes) FROM {_AGG} WHERE bytes_rows > 0 GROUP BY src_key, dst_key, port, proto")]
    if len(totals) < 2:
        return None
    ordered = sorted(totals)
    p = ordered[min(len(ordered) - 1, int(len(ordered) * r.t.high_bytes_percentile / 100))]
    limit = max(p, r.t.high_bytes_median_factor * median(ordered), r.t.high_bytes_min_mb * MiB)
    rows = r.conn.execute(
        f"SELECT src_key, dst_key, port, proto, SUM(bytes) AS b FROM {_AGG} WHERE bytes_rows > 0 "
        "GROUP BY src_key, dst_key, port, proto HAVING b > ? ORDER BY b DESC", (limit,)).fetchall()
    if not rows:
        return None
    return RuleOutcome("B008", Severity.MEDIUM, "rpt_rule_b008_desc", "rpt_rule_b008_rec", {
        "n_outliers": len(rows), "limit_mb": f"{limit / MiB:.1f}", "n_with_bytes": len(totals),
        "top_pairs": ", ".join(f"{r.names(s)} → {r.names(d)} {port_text(p_, q)} ({b / MiB:.1f} MB)"
                               for s, d, p_, q, b in rows[:TOP])})


def _b009(r: _Run) -> RuleOutcome | None:
    n = r.sum(CROSS_ENV, [])
    if n <= r.t.cross_env_connection:
        return None
    return RuleOutcome("B009", Severity.LOW, "rpt_rule_b009_desc", "rpt_rule_b009_rec", {
        "n_flows": n, "threshold": r.t.cross_env_connection,
        "top_pairs": ", ".join(f"{a} → {b} ({n_:,})" for a, b, n_ in r.conn.execute(
            f"SELECT src_env, dst_env, SUM(flows) n FROM {_AGG} WHERE {CROSS_ENV} GROUP BY 1, 2 ORDER BY n DESC "
            f"LIMIT {TOP}"))})


def _l001(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(CLEARTEXT_PORTS)
    n = r.sum(pc, pp)
    if not n:
        return None
    allowed = r.sum(f"{pc} AND decision = 'allowed'", pp)
    return RuleOutcome("L001", Severity.HIGH if allowed else Severity.MEDIUM, "rpt_rule_l001_desc",
                       "rpt_rule_l001_rec", {"n_flows": n, "n_allowed": allowed, "named_ports": r.ports_text(pc, pp)})


def _l002(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(DISCOVERY_PORTS)
    cond = f"{pc} AND decision != 'blocked'"
    n = r.sum(cond, pp)
    if n < r.t.discovery_protocol:
        return None
    return RuleOutcome("L002", Severity.MEDIUM, "rpt_rule_l002_desc", "rpt_rule_l002_rec",
                       {"n_flows": n, "named_ports": r.ports_text(cond, pp), "threshold": r.t.discovery_protocol})


def _l003(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(DB_PORTS)
    rows = r.conn.execute(
        f"SELECT dst_key, port, proto, COUNT(DISTINCT src_app) AS n FROM {_AGG} WHERE {pc} AND decision = 'allowed' "
        "AND src_app != '' GROUP BY dst_key, port, proto HAVING n > ? ORDER BY n DESC",
        [*pp, r.t.db_unique_src_app]).fetchall()
    if not rows:
        return None
    return RuleOutcome("L003", Severity.HIGH, "rpt_rule_l003_desc", "rpt_rule_l003_rec", {
        "n_targets": len(rows), "threshold": r.t.db_unique_src_app,
        "top_targets": ", ".join(f"{r.names(d)} {port_text(p, q)} ({n})" for d, p, q, n in rows[:TOP])})


def _l004(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(DB_PORTS)
    cond = f"{pc} AND decision = 'allowed' AND {CROSS_ENV}"
    n = r.sum(cond, pp)
    if not n:
        return None
    return RuleOutcome("L004", Severity.HIGH, "rpt_rule_l004_desc", "rpt_rule_l004_rec", {
        "n_flows": n, "top_destinations": r.top(f"SELECT dst_key, SUM(flows) n FROM {_AGG} WHERE {cond} "
                                                "GROUP BY dst_key ORDER BY n DESC", pp)})


def _l005(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(IDENTITY_PORTS)

    def apps(extra: str) -> int:
        return int(r.conn.execute(f"SELECT COUNT(DISTINCT src_app) FROM {_AGG} WHERE {pc} AND src_app != '' "
                                  f"AND {extra}", pp).fetchone()[0])
    n = apps("decision != 'blocked'")
    if n <= r.t.identity_unique_src_app:
        return None
    allowed = apps("decision = 'allowed'")
    high = allowed > r.t.identity_unique_src_app
    return RuleOutcome("L005", Severity.HIGH if high else Severity.MEDIUM, "rpt_rule_l005_desc",
                       "rpt_rule_l005_rec_allowed" if high else "rpt_rule_l005_rec_pb",
                       {"n_apps": n, "threshold": r.t.identity_unique_src_app})


def _l006(r: _Run) -> RuleOutcome | None:
    hosts = [h for h in (r.exposure or {}).get("hosts") or () if int(h.get("reach_now") or 0) >= r.t.blast_radius]
    if not hosts:
        return None
    hosts.sort(key=lambda h: -int(h.get("reach_now") or 0))
    return RuleOutcome("L006", Severity.HIGH, "rpt_rule_l006_desc", "rpt_rule_l006_rec", {
        "n_hosts": len(hosts), "threshold": r.t.blast_radius,
        "top_hosts": ", ".join(f"{r.names(h['key'])} ({h['reach_now']})" for h in hosts[:TOP])})


def _l007(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(DB_PORTS | IDENTITY_PORTS | WINDOWS_MGMT_PORTS)
    cond = f"src_managed = 0 AND {pc} AND decision != 'blocked'"
    n = r.sum(cond, pp)
    if n < r.t.unmanaged_critical:
        return None
    return RuleOutcome("L007", Severity.HIGH, "rpt_rule_l007_desc", "rpt_rule_l007_rec", {
        "n_flows": n, "named_ports": r.ports_text(cond, pp),
        "top_sources": r.top(f"SELECT src_key, SUM(flows) n FROM {_AGG} WHERE {cond} GROUP BY src_key "
                             "ORDER BY n DESC", pp)})


def _l008(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(r.admin | WINDOWS_MGMT_PORTS | DB_PORTS | IDENTITY_PORTS)
    cond = f"{pc} AND decision = 'potentially_blocked'"
    n = r.sum(cond, pp)
    if n < r.t.pb_lateral:
        return None
    return RuleOutcome("L008", Severity.HIGH, "rpt_rule_l008_desc", "rpt_rule_l008_rec", {
        "n_flows": n, "threshold": r.t.pb_lateral,
        "top_apps": ", ".join(f"{a or '—'} ({n_:,})" for a, n_ in r.conn.execute(
            f"SELECT dst_app, SUM(flows) n FROM {_AGG} WHERE {cond} GROUP BY dst_app ORDER BY n DESC LIMIT {TOP}",
            pp))})


def _l009(r: _Run) -> RuleOutcome | None:
    cond = "src_managed = 1 AND dst_managed = 0 AND decision = 'allowed' AND bytes_rows > 0"
    total = r.sum(cond, [], "bytes")
    if total < r.t.exfil_mb * MiB:
        return None
    return RuleOutcome("L009", Severity.HIGH, "rpt_rule_l009_desc", "rpt_rule_l009_rec", {
        "total_mb": f"{total / MiB:.1f}", "threshold": f"{r.t.exfil_mb:g}",
        "top_dst_fmt": ", ".join(f"{r.names(d)} ({b / MiB:.1f} MB)" for d, b in r.conn.execute(
            f"SELECT dst_key, SUM(bytes) b FROM {_AGG} WHERE {cond} GROUP BY dst_key ORDER BY b DESC LIMIT {TOP}"))})


def _l010(r: _Run) -> RuleOutcome | None:
    pc, pp = _ports(r.admin | WINDOWS_MGMT_PORTS)
    cond = f"{pc} AND decision = 'allowed' AND {CROSS_ENV}"
    n = r.sum(cond, pp)
    if n < r.t.cross_env_lateral:
        return None
    return RuleOutcome("L010", Severity.CRITICAL, "rpt_rule_l010_desc", "rpt_rule_l010_rec", {
        "n_flows": n, "named_ports": r.ports_text(cond, pp),
        "top_pairs": ", ".join(f"{a} → {b} ({n_:,})" for a, b, n_ in r.conn.execute(
            f"SELECT src_env, dst_env, SUM(flows) n FROM {_AGG} WHERE {cond} GROUP BY 1, 2 ORDER BY n DESC "
            f"LIMIT {TOP}", pp))})


RULE_FUNCTIONS: dict[str, Callable[[_Run], RuleOutcome | None]] = {
    "B001": _b001,
    "B002": _simple("B002", HIGH_PORTS, "allowed", Severity.HIGH, "rpt_rule_b002_desc",
                    "rpt_rule_b002_rec"),
    "B003": _simple("B003", MEDIUM_PORTS, "potentially_blocked", Severity.MEDIUM,
                    "rpt_rule_b003_desc", "rpt_rule_b003_rec"),
    "B004": _b004, "B005": _b005, "B006": _b006, "B007": _b007, "B008": _b008, "B009": _b009,
    "L001": _l001, "L002": _l002, "L003": _l003, "L004": _l004, "L005": _l005, "L006": _l006, "L007": _l007,
    "L008": _l008, "L009": _l009, "L010": _l010,
}


def run_rules(ctx: AppContext, spec: FilterSpec, thresholds: ReportRuleThresholds, lang: Language, *,
              now: datetime) -> list[RuleOutcome]:
    """Every rule that fired or could not be evaluated, most severe first."""
    lc = load_lateral_context(ctx, now=now)
    admin = {(e.port, e.proto) for e in lc.admin_ports.entries if e.category is PortClass.REMOTE
             and e.proto is not None}
    admin |= {(e.port, p) for e in lc.admin_ports.entries if e.category is PortClass.REMOTE and e.proto is None
              for p in (6, 17)}

    def names(key: str) -> str:
        return host_name(lc.hosts, key, lang)
    out: list[RuleOutcome] = []
    with reads.reading(ctx) as conn:
        row = analysis.read_result(conn, "exposure")
        exposure = json.loads(row["result_json"]) if row is not None else None
        flowsource.group_for_findings(conn, spec, env_key=lc.settings.environment_label_key, table=_AGG)
        run = _Run(conn, thresholds, lang, admin, names, exposure)
        for rule_id, rule in RULE_FUNCTIONS.items():
            try:
                outcome = rule(run)
            except Exception as exc:  # noqa: BLE001 - one rule's failure is reported, the others still run
                logger.error("findings rule {} failed: {}", rule_id, traceback.format_exc())
                outcome = RuleOutcome(rule_id, None, "", "", {}, error=f"{type(exc).__name__}: {exc}"[:300])
            if outcome is not None:
                out.append(outcome)
    return ranked(out)
