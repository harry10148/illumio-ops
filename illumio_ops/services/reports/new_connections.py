"""The new connections report (spec §6.5.5 分析): every source → destination × port/protocol whose first sighting
in the connection baseline falls in the period, with its management-port class and newest reported decision."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
)
from illumio_ops.domain.values import Severity
from illumio_ops.services.analysis.context import LateralContext, load_lateral_context
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import (
    PORT_CLASS_KEYS,
    host_name,
    port_text,
    tr,
)
from illumio_ops.services.reports.generate import coverage_note
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.store.flowdb.db import db_time

ROW_LIMIT = 100_000
ADMIN_ROW_LIMIT = 5_000
TOP = 20
DECISION_KEYS = {"allowed": "decision_allowed", "potentially_blocked": "decision_potentially_blocked",
                 "blocked": "decision_blocked", "unknown": "decision_unknown"}
_WINDOW = "first_seen >= ? AND first_seen < ?"


def _where(lc: LateralContext, kind: str) -> tuple[str, list[Any]]:
    if kind == "admin":
        return reads.port_clause([(e.port, e.proto) for e in lc.admin_ports.entries])
    if kind == "critical":
        keys = sorted(k for k, h in lc.hosts.items() if h.critical)
        return (f"dst_key IN ({','.join('?' * len(keys))})" if keys else "0"), list(keys)
    if kind == "unmanaged_source":
        return "src_key LIKE 'ip:%'", []
    return "1", []


def _count(conn: sqlite3.Connection, lc: LateralContext, kind: str, start: datetime, end: datetime) -> int:
    clause, params = _where(lc, kind)
    return int(conn.execute(f"SELECT COUNT(*) FROM connection_baseline WHERE {_WINDOW} AND {clause}",
                            [db_time(start), db_time(end), *params]).fetchone()[0])


class _Builder:
    def __init__(self, inp: BuildInput) -> None:
        self.inp, self.lang = inp, inp.lang
        self.lc = load_lateral_context(inp.ctx, now=inp.now)

    def t(self, msg: str, /, **params: object) -> str:
        return tr(self.lang, msg, **params)

    def name(self, key: str) -> str:
        return host_name(self.lc.hosts, key)

    def port_class(self, port: int, proto: int) -> str:
        cls = self.lc.admin_ports.class_of(None if port < 0 else port, proto)
        return self.t(PORT_CLASS_KEYS[cls]) if cls is not None else ""

    def connection_rows(self, rows: Sequence[sqlite3.Row]) -> tuple[tuple[Any, ...], ...]:
        return tuple((self.name(r["src_key"]), self.name(r["dst_key"]), port_text(r["port"], r["proto"]),
                      self.port_class(r["port"], r["proto"]), r["first_seen"], r["last_seen"],
                      self.t(DECISION_KEYS.get(r["last_decision"] or "unknown", "decision_unknown")))
                     for r in rows)

    def columns(self) -> tuple[Column, ...]:
        return (Column(key="src", label=self.t("rpt_col_source"), kind="host"),
                Column(key="dst", label=self.t("rpt_col_destination"), kind="host"),
                Column(key="service", label=self.t("rpt_col_service")),
                Column(key="class", label=self.t("rpt_col_port_class")),
                Column(key="first", label=self.t("rpt_col_first_seen"), kind="time"),
                Column(key="last", label=self.t("rpt_col_last_seen"), kind="time"),
                Column(key="decision", label=self.t("rpt_col_last_decision")))

    def findings(self, admin_rows: Sequence[sqlite3.Row]) -> tuple[Finding, ...]:
        """New management connections into critical assets first, then from unmanaged sources (at most 5)."""
        out = []
        for r in admin_rows:
            dst = self.lc.hosts.get(r["dst_key"])
            if dst is not None and dst.critical:
                out.append((0, Severity.HIGH, r, "rpt_new_why_critical"))
            elif str(r["src_key"]).startswith("ip:"):
                out.append((1, Severity.MEDIUM, r, "rpt_new_why_unmanaged"))
        out.sort(key=lambda x: (x[0], x[2]["first_seen"]))
        return tuple(Finding(severity=sev, title=self.t("rpt_new_finding_title", service=port_text(r["port"], r["proto"]),
                                                         src=self.name(r["src_key"]), dst=self.name(r["dst_key"])),
                             why=self.t(why), action=self.t("rpt_new_action")) for _, sev, r, why in out[:5])

    def limit_note(self, shown: int, total: int) -> str | None:
        return self.t("rpt_limit_earliest", shown=f"{shown:,}", total=f"{total:,}") if total > shown else None


def build_new_connections(inp: BuildInput) -> ReportDocument:
    b = _Builder(inp)
    lc = b.lc
    period = inp.end - inp.start
    window = [db_time(inp.start), db_time(inp.end)]
    kinds = ("new", "admin", "critical", "unmanaged_source")
    with reads.reading(inp.ctx) as conn:
        now_counts = {k: _count(conn, lc, k, inp.start, inp.end) for k in kinds}
        before = {k: _count(conn, lc, k, inp.start - period, inp.start) for k in kinds}
        by_service = conn.execute(f"SELECT port, proto, COUNT(*) AS n FROM connection_baseline WHERE {_WINDOW} "
                                  "GROUP BY port, proto ORDER BY n DESC, port LIMIT ?", [*window, TOP]).fetchall()
        services_total = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM connection_baseline WHERE {_WINDOW} "
                                      "GROUP BY port, proto)", window).fetchone()[0]
        by_dst = conn.execute(f"SELECT dst_key, COUNT(*) AS n, COUNT(DISTINCT src_key) FROM connection_baseline "
                              f"WHERE {_WINDOW} GROUP BY dst_key ORDER BY n DESC, dst_key LIMIT ?",
                              [*window, TOP]).fetchall()
        dst_total = conn.execute(f"SELECT COUNT(DISTINCT dst_key) FROM connection_baseline WHERE {_WINDOW}",
                                 window).fetchone()[0]
        clause, params = _where(lc, "admin")
        admin_rows = conn.execute(f"SELECT * FROM connection_baseline WHERE {_WINDOW} AND {clause} "
                                  "ORDER BY first_seen, src_key LIMIT ?", [*window, *params, ADMIN_ROW_LIMIT]).fetchall()
        all_rows = conn.execute(f"SELECT * FROM connection_baseline WHERE {_WINDOW} ORDER BY first_seen, src_key "
                                "LIMIT ?", [*window, ROW_LIMIT]).fetchall()
    accumulating = None if lc.baseline_full() else b.t(
        "detector_baseline_accumulating", days=f"{lc.baseline_days:.0f}", required=lc.baseline_required)
    labels = {"new": "rpt_new_kpi_new", "admin": "rpt_new_kpi_admin", "critical": "rpt_new_kpi_critical",
              "unmanaged_source": "rpt_new_kpi_unmanaged_source"}
    kpis = tuple(Kpi(key=k, label=b.t(labels[k]), value=now_counts[k], previous=before[k], better="lower",
                     note=accumulating) for k in kinds)
    empty = b.t("rpt_new_none")
    service_table = TableBlock(title=b.t("rpt_new_tbl_by_service"), columns=(
        Column(key="service", label=b.t("rpt_col_service")), Column(key="class", label=b.t("rpt_col_port_class")),
        Column(key="count", label=b.t("rpt_col_new_connections"), kind="number")),
        rows=tuple((port_text(r[0], r[1]), b.port_class(r[0], r[1]), r[2]) for r in by_service),
        total_rows=int(services_total), empty_text=empty,
        limit_note=b.t("rpt_limit_top", shown=len(by_service), total=services_total)
        if services_total > len(by_service) else None)
    dst_table = TableBlock(title=b.t("rpt_new_tbl_by_destination"), columns=(
        Column(key="dst", label=b.t("rpt_col_destination"), kind="host"),
        Column(key="count", label=b.t("rpt_col_new_connections"), kind="number"),
        Column(key="sources", label=b.t("rpt_col_distinct_sources"), kind="number")),
        rows=tuple((b.name(r[0]), r[1], r[2]) for r in by_dst), total_rows=int(dst_total), empty_text=empty,
        limit_note=b.t("rpt_limit_top", shown=len(by_dst), total=dst_total) if dst_total > len(by_dst) else None)
    admin_table = TableBlock(title=b.t("rpt_new_tbl_admin"), columns=b.columns(),
                             rows=b.connection_rows(admin_rows), total_rows=max(now_counts["admin"], len(admin_rows)),
                             empty_text=b.t("rpt_new_admin_none"),
                             limit_note=b.limit_note(len(admin_rows), now_counts["admin"]))
    all_table = TableBlock(title=b.t("rpt_new_tbl_all"), columns=b.columns(), rows=b.connection_rows(all_rows),
                           total_rows=max(now_counts["new"], len(all_rows)), empty_text=empty,
                           limit_note=b.limit_note(len(all_rows), now_counts["new"]))
    quality = [*coverage_note(inp.ctx, inp.start, inp.end, inp.lang, now=inp.now, tz=inp.tz)]
    if accumulating:
        quality.append(accumulating)
    return ReportDocument(
        report_type=inp.params.report_type, lang=inp.lang, title=b.t("rpt_title_new_connections"),
        period_start=inp.start, period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis,
        findings=b.findings(admin_rows), data_quality=tuple(quality),
        sections=(Section(id="by_service", title=b.t("rpt_new_sec_by_service"), intro=b.t("rpt_new_intro"),
                          blocks=(service_table,)),
                  Section(id="by_destination", title=b.t("rpt_new_sec_by_destination"), blocks=(dst_table,)),
                  Section(id="admin", title=b.t("rpt_new_sec_admin"), blocks=(admin_table,)),
                  Section(id="all", title=b.t("rpt_new_sec_all"), blocks=(all_table,))))
