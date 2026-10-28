"""The audit report (spec §6.5 報表, §6.5.5 營運): what happened on the PCE in the period — the event types that
matter by risk, who did what and who failed to sign in, policy provisions, agent security events and brute force —
from the events the product collected. Actors are users and service accounts only: the system and VENs are never
correlated as one person (5.x counted every system event under one "System" actor)."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from typing import Any

from illumio_ops.domain.audit import (
    AGENT_SECURITY,
    AUTH_FAILED,
    AUTHZ_DENIED,
    PROVISION,
    is_draft_change,
    risk_of,
)
from illumio_ops.domain.findings_rules import SEVERITY_RANK
from illumio_ops.domain.report import (
    BarBlock,
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.segment import EventFilter, EventSegment, GroupBy
from illumio_ops.domain.values import SegmentDimension, SegmentView, Severity
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.eventsource import (
    USER_KINDS,
    AuditCounts,
    EventRow,
    audit_counts,
    event_detail,
)
from illumio_ops.services.reports.common import severity_name, tr
from illumio_ops.services.reports.registry import BuildInput

TOP = 20
ATTENTION_FINDINGS = 5
FAILED_ROWS = 30
BRUTE_WINDOW = timedelta(minutes=30)
BRUTE_MIN = 5
DETAIL_ROWS = 1_000  # newest rows per detail table (an event segment's limit); more are disclosed
_KPI_KEYS = {"total": "rpt_aud_kpi_total", "high_risk": "rpt_aud_kpi_high_risk", "auth_failed": "rpt_aud_kpi_auth_failed",
             "authz_denied": "rpt_aud_kpi_authz_denied", "policy_provisions": "rpt_aud_kpi_provisions",
             "draft_changes": "rpt_aud_kpi_draft_changes", "agent_security": "rpt_aud_kpi_agent_security",
             "actors": "rpt_aud_kpi_actors", "source_ips": "rpt_aud_kpi_source_ips"}
_ACTION_KEYS = {Severity.CRITICAL: "rpt_aud_action_critical", Severity.HIGH: "rpt_aud_action_high",
                Severity.MEDIUM: "rpt_aud_action_medium", Severity.LOW: "rpt_aud_action_low"}


def _values(c: AuditCounts) -> dict[str, int]:
    by = c.by_type
    return {"total": c.total,
            "high_risk": sum(n for k, n in by.items() if risk_of(k) in (Severity.CRITICAL, Severity.HIGH)),
            "auth_failed": by.get(AUTH_FAILED, 0), "authz_denied": by.get(AUTHZ_DENIED, 0),
            "policy_provisions": by.get(PROVISION, 0), "draft_changes": sum(n for k, n in by.items() if is_draft_change(k)),
            "agent_security": sum(by.get(k, 0) for k in AGENT_SECURITY), "actors": c.actors, "source_ips": c.source_ips}


def _walk(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def _first(raw: Mapping[str, Any], key: str) -> Any:
    """The first value of `key` anywhere in the event (the PCE nests sec_policy under resource_changes)."""
    return next((m[key] for m in _walk(raw) if key in m and m[key] not in (None, "")), None)


def _actor(r: EventRow) -> str | None:
    return r.created_by_name if r.created_by_kind in USER_KINDS and (r.created_by_name or "").strip() else None


def brute_force(by_ip: Mapping[str, list[datetime]]) -> list[tuple[str, int, int, datetime, datetime]]:
    """(source address, most failures in any 30 minutes, failures, first, last) for addresses with at least
    BRUTE_MIN in one such window, worst first."""
    out = []
    for ip, times in by_ip.items():
        best, j = 0, 0
        for i, at in enumerate(times):
            while times[j] < at - BRUTE_WINDOW:
                j += 1
            best = max(best, i - j + 1)
        if best >= BRUTE_MIN:
            out.append((ip, best, len(times), times[0], times[-1]))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def build_audit(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    counts = audit_counts(inp.ctx, start=inp.start, end=inp.end, top=TOP, now=inp.now)
    period = inp.end - inp.start
    prev = audit_counts(inp.ctx, start=inp.start - period, end=inp.start, top=0, now=inp.now)
    before = _values(prev) if not prev.coverage.gaps else None
    none = t("rpt_aud_no_events")
    now_v = _values(counts)
    kpis = tuple(Kpi(key=k, label=t(label), value=now_v[k] if counts.total else None,
                     previous=before[k] if before is not None else None,
                     better="neutral" if k in ("total", "actors") else "lower",
                     note=None if counts.total else none) for k, label in _KPI_KEYS.items())

    def detail(types: tuple[str, ...], limit: int) -> tuple[list[EventRow], bool]:
        q = event_detail(inp.ctx, EventSegment(filter=EventFilter(start=inp.start, end=inp.end, event_types=types),
                                               view=SegmentView.DETAIL, limit=limit), now=inp.now)
        return q.rows, q.limit_hit

    # ── attention ───────────────────────────────────────────────────────────
    by_actor = run_segment(inp.ctx, EventSegment(
        filter=EventFilter(start=inp.start, end=inp.end), view=SegmentView.RANKING, limit=1000,
        group_by=(GroupBy(dimension=SegmentDimension.EVENT_TYPE), GroupBy(dimension=SegmentDimension.ACTOR))),
        now=inp.now)
    actors: dict[str, list[str]] = defaultdict(list)
    for r in by_actor.ranking or []:
        if r.keys[1] not in (None, "") and len(actors[str(r.keys[0])]) < 3:
            actors[str(r.keys[0])].append(f"{r.keys[1]} ({r.value})")
    risky = sorted(((k, risk_of(k), n) for k, n in counts.by_type.items() if risk_of(k) is not None),
                   key=lambda x: (SEVERITY_RANK[x[1]], -x[2], x[0]))  # type: ignore[index]
    attention = TableBlock(
        title=t("rpt_aud_tbl_attention"),
        columns=(Column(key="type", label=t("rpt_aud_col_type")), Column(key="risk", label=t("rpt_aud_col_risk")),
                 Column(key="n", label=t("rpt_aud_col_events"), kind="number"),
                 Column(key="actors", label=t("rpt_aud_col_top_actors"))),
        rows=tuple((k, severity_name(lang, s.value), n, ", ".join(actors.get(k, ())) or "—")
                   for k, s, n in risky if s is not None),
        total_rows=len(risky), empty_text=t("rpt_aud_none_attention") if counts.total else none)
    findings = tuple(Finding(severity=s, title=t("rpt_aud_finding_title", type=k, n=f"{n:,}"),
                             why=t("rpt_aud_finding_why", actors=", ".join(actors.get(k, ())) or "—"),
                             action=t(_ACTION_KEYS[s])) for k, s, n in risky[:ATTENTION_FINDINGS] if s is not None)

    # ── event types and trend ───────────────────────────────────────────────
    types = sorted(counts.by_type.items(), key=lambda kv: (-kv[1], kv[0]))
    type_table = TableBlock(
        title=t("rpt_aud_tbl_types"),
        columns=(Column(key="type", label=t("rpt_aud_col_type")),
                 Column(key="n", label=t("rpt_aud_col_events"), kind="number"),
                 Column(key="risk", label=t("rpt_aud_col_risk"))),
        rows=tuple((k, n, severity_name(lang, s.value) if (s := risk_of(k)) else "—") for k, n in types[:TOP]),
        total_rows=len(types), empty_text=none,
        limit_note=t("rpt_limit_top_n", n=TOP) if len(types) > TOP else None)
    per_day: Counter[str] = Counter()
    for hour, n in counts.by_hour.items():
        per_day[datetime.fromisoformat(hour + ":00:00+00:00").astimezone(inp.tz).strftime("%Y-%m-%d")] += n
    days = [(inp.start + timedelta(days=i)).astimezone(inp.tz).strftime("%Y-%m-%d") for i in range(period.days or 1)]
    trend = BarBlock(title=t("rpt_aud_bar_daily"), points=tuple((d, per_day.get(d, 0)) for d in days), empty_text=none)

    # ── users ───────────────────────────────────────────────────────────────
    users = TableBlock(
        title=t("rpt_aud_tbl_users"),
        columns=(Column(key="user", label=t("rpt_col_user")), Column(key="n", label=t("rpt_aud_col_events"), kind="number"),
                 Column(key="failures", label=t("rpt_aud_col_failures"), kind="number"),
                 Column(key="ips", label=t("rpt_aud_col_source_ips"), kind="number")),
        rows=tuple((u.name, u.events, u.failures, u.source_ips) for u in counts.users), total_rows=counts.users_total,
        empty_text=t("rpt_aud_none_users") if counts.total else none,
        limit_note=t("rpt_limit_top_n", n=TOP) if counts.users_total > TOP else None)
    failed, failed_more = detail((AUTH_FAILED,), FAILED_ROWS)
    failed_table = TableBlock(
        title=t("rpt_aud_tbl_failed"),
        columns=(Column(key="at", label=t("rpt_aud_col_time"), kind="time"), Column(key="user", label=t("rpt_col_user")),
                 Column(key="ip", label=t("rpt_aud_col_source_ip"))),
        rows=tuple((r.timestamp.isoformat(), r.created_by_name or "—", str(_first(r.raw, "src_ip") or "—"))
                   for r in failed),
        total_rows=now_v["auth_failed"], empty_text=t("rpt_aud_none_failed") if counts.total else none,
        limit_note=t("rpt_aud_newest_n", n=FAILED_ROWS) if failed_more else None)

    # ── policy provisions ───────────────────────────────────────────────────
    provisions, prov_more = detail((PROVISION,), DETAIL_ROWS)
    policy = TableBlock(
        title=t("rpt_aud_tbl_provisions"),
        columns=(Column(key="at", label=t("rpt_aud_col_time"), kind="time"), Column(key="user", label=t("rpt_col_user")),
                 Column(key="affected", label=t("rpt_aud_col_affected"), kind="number"),
                 Column(key="message", label=t("rpt_aud_col_message"))),
        rows=tuple((r.timestamp.isoformat(), _actor(r) or t("rpt_aud_system"), _first(r.raw, "workloads_affected"),
                    str(_first(r.raw, "commit_message") or "—")) for r in provisions),
        total_rows=now_v["policy_provisions"], empty_text=t("rpt_aud_none_provisions") if counts.total else none,
        limit_note=t("rpt_aud_newest_n", n=DETAIL_ROWS) if prov_more else None)

    # ── agent security ──────────────────────────────────────────────────────
    agent_rows, agent_more = detail(AGENT_SECURITY, DETAIL_ROWS)
    agent = TableBlock(
        title=t("rpt_aud_tbl_agent"),
        columns=(Column(key="at", label=t("rpt_aud_col_time"), kind="time"), Column(key="type", label=t("rpt_aud_col_type")),
                 Column(key="host", label=t("rpt_col_host")), Column(key="status", label=t("rpt_aud_col_status"))),
        rows=tuple((r.timestamp.isoformat(), r.event_type, r.created_by_name or "—", r.status or "—") for r in agent_rows),
        total_rows=now_v["agent_security"], empty_text=t("rpt_aud_none_agent") if counts.total else none,
        limit_note=t("rpt_aud_newest_n", n=DETAIL_ROWS) if agent_more else None)

    # ── brute force ─────────────────────────────────────────────────────────
    found = brute_force(counts.failed_by_ip)
    brute = TableBlock(
        title=t("rpt_aud_tbl_brute"),
        columns=(Column(key="ip", label=t("rpt_aud_col_source_ip")),
                 Column(key="peak", label=t("rpt_aud_col_peak"), kind="number"),
                 Column(key="n", label=t("rpt_aud_col_failures"), kind="number"),
                 Column(key="first", label=t("rpt_aud_col_first"), kind="time"),
                 Column(key="last", label=t("rpt_aud_col_last"), kind="time")),
        rows=tuple((ip, peak, n, a.isoformat(), b.isoformat()) for ip, peak, n, a, b in found),
        total_rows=len(found), empty_text=t("rpt_aud_none_brute") if counts.total else none)

    quality = [t("rpt_aud_quality_gaps", n=len(counts.coverage.gaps)) if counts.coverage.gaps
               else t("rpt_aud_quality_whole"), t("rpt_aud_quality_actors")]
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_audit"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=findings,
        data_quality=tuple(quality),
        sections=(Section(id="attention", title=t("rpt_aud_sec_attention"), intro=t("rpt_aud_attention_intro"),
                          blocks=(attention,)),
                  Section(id="types", title=t("rpt_aud_sec_types"), blocks=(type_table, trend)),
                  Section(id="users", title=t("rpt_aud_sec_users"), intro=t("rpt_aud_users_intro"),
                          blocks=(users, failed_table)),
                  Section(id="policy", title=t("rpt_aud_sec_policy"), blocks=(policy,)),
                  Section(id="agent", title=t("rpt_aud_sec_agent"),
                          blocks=(agent, TextBlock(paragraphs=(t("rpt_aud_agent_see"),)))),
                  Section(id="brute_force", title=t("rpt_aud_sec_brute"), intro=t("rpt_aud_brute_intro"),
                          blocks=(brute,))))
