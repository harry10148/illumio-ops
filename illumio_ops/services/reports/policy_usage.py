"""The policy usage report (spec §6.5 policy_usage, P5c-1; user 2026-10-29, plan A): which rules the period's traffic
used and which it did not, which Deny Rules blocked something, and which connections no rule allows — all from the
PCE's own draft recompute (services/analysis/rule_usage.py). It says whether the draft is the active policy: with
nothing pending they are the same; active rules' real hits are the Rule Hit Count report."""
from __future__ import annotations

from loguru import logger

from illumio_ops.domain.policy import ActorRef, RuleRef
from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import RuleAction, Severity
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis.rule_usage import RuleUsage, rule_usage
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.reports.common import port_text, tr
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.services.reports.render_html import fmt_time

ROWS = 200
_KPI_KEYS = {"rules": "rpt_pu_kpi_rules", "used": "rpt_pu_kpi_used", "unused": "rpt_pu_kpi_unused",
             "disabled": "rpt_pu_kpi_disabled", "deny_hit": "rpt_pu_kpi_deny_hit", "no_rule": "rpt_pu_kpi_no_rule"}


def _rule_id(r: RuleRef) -> str:
    return f"#{r.href.rsplit('/', 1)[-1]}"


def _actor(a: ActorRef) -> str:
    text = a.name or (f"{a.key}={a.value}" if a.key else None) or a.kind
    return f"−{text}" if a.exclusion else text


def _scope(r: RuleRef, any_text: str) -> str:
    consumers = ", ".join(_actor(a) for a in r.consumers) or any_text
    providers = ", ".join(_actor(a) for a in r.providers) or any_text
    services = ", ".join(s.name or port_text(s.port, s.proto or 0) for s in r.services) or any_text
    return f"{consumers} → {providers}：{services}"


def build_policy_usage(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    usage: RuleUsage | None = None
    failure: str | None = None
    try:
        usage = rule_usage(inp.ctx, start=inp.start, end=inp.end, now=inp.now)
    except (PceQueryError, PceCollectionIncomplete, PceNotConfigured, *PCE_FAILURES) as exc:
        logger.warning("policy usage could not be computed: {}", exc)
        failure = f"{type(exc).__name__}: {exc}"[:200]
    any_text = t("rpt_pu_any")
    no_label = t("rpt_no_label")

    def rule_cells(r: RuleRef) -> tuple[str, str, str]:
        return (r.ruleset_name, f"{_rule_id(r)} {r.description or ''}".strip(), _scope(r, any_text))

    rules = usage.rules if usage else {}
    hits = usage.hits if usage and not usage.unsupported else {}
    allow = sorted((r for r in rules.values() if r.rule_type is RuleAction.ALLOW), key=lambda r: (r.ruleset_name, r.href))
    deny = [r for r in rules.values() if r.rule_type is not RuleAction.ALLOW]
    used = sorted((r for r in allow if r.href in hits), key=lambda r: -hits[r.href].connections)
    unused = [r for r in allow if r.enabled and r.href not in hits]
    disabled = [r for r in allow if not r.enabled]
    deny_hit = sorted((r for r in deny if r.href in hits), key=lambda r: -hits[r.href].connections)
    ok = usage is not None and not usage.unsupported
    missing = (t("rpt_pu_failed", error=failure or "") if usage is None else t("rpt_pu_unsupported"))

    values: dict[str, int | None] = {
        "rules": len(allow) if usage else None, "used": len(used) if ok else None,
        "unused": len(unused) if ok else None, "disabled": len(disabled) if usage else None,
        "deny_hit": len(deny_hit) if ok else None,
        "no_rule": sum(g.connections for g in usage.no_rule) if ok and usage else None}
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k], previous=None, unit="count",
                     better="neutral" if k in ("rules", "disabled") else "higher" if k == "used" else "lower",
                     note=None if values[k] is not None else missing) for k, label in _KPI_KEYS.items())

    # ── pending changes: is the draft the active policy? ─────────────────────
    pending_blocks: tuple[TextBlock | TableBlock, ...]
    if usage is None:
        pending_blocks = (TextBlock(paragraphs=(missing,)),)
    elif not usage.pending:
        pending_blocks = (TextBlock(paragraphs=(t("rpt_pu_pending_none"),)),)
    else:
        pending_blocks = (TextBlock(paragraphs=(t("rpt_pu_pending_some", n=len(usage.pending)),)), TableBlock(
            title=t("rpt_pu_tbl_pending"),
            columns=(Column(key="kind", label=t("rpt_pu_col_kind")), Column(key="name", label=t("rpt_col_name")),
                     Column(key="change", label=t("rpt_pu_col_change")),
                     Column(key="at", label=t("rpt_pu_col_updated"))),
            rows=tuple((p.kind, p.name or p.href.rsplit("/", 1)[-1], p.update_type or "—",
                        fmt_time(p.updated_at, inp.tz) if p.updated_at else "—") for p in usage.pending),
            total_rows=len(usage.pending), empty_text=""))

    hedge = (t("rpt_pu_unused_hedge", n=len(usage.truncated)) if usage and usage.truncated else None)

    def rule_table(title: str, items: list[RuleRef], empty: str, *, counts: bool, note: str | None = None) -> TableBlock:
        cols = [Column(key="ruleset", label="Ruleset"), Column(key="rule", label=t("rpt_pu_col_rule")),
                Column(key="scope", label=t("rpt_pu_col_scope"))]
        if counts:
            cols += [Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                     Column(key="connections", label=t("rpt_col_connections"), kind="number"),
                     Column(key="pairs", label=t("rpt_pu_col_pairs"))]
        rows = tuple(
            (*rule_cells(r), *((hits[r.href].flows, hits[r.href].connections,
                                "; ".join(f"{a or no_label} → {b or no_label}（{n:,}）"
                                          for a, b, n in hits[r.href].top_pairs) or "—") if counts else ()))
            for r in items[:ROWS])
        return TableBlock(title=title, columns=tuple(cols), rows=rows, total_rows=len(items),
                          empty_text=t(empty) if ok else missing,
                          limit_note=" ".join(x for x in (t("rpt_limit_top_n", n=ROWS) if len(items) > ROWS else None,
                                                          note) if x) or None)

    used_blocks: tuple[TextBlock | TableBlock, ...] = (
        (rule_table(t("rpt_pu_tbl_used"), used, "rpt_pu_none_used", counts=True, note=hedge),) if ok
        else (TextBlock(paragraphs=(missing,)),))
    unused_table = rule_table(t("rpt_pu_tbl_unused"), unused, "rpt_pu_none_unused", counts=False, note=hedge)
    disabled_table = rule_table(t("rpt_pu_tbl_disabled"), disabled, "rpt_pu_none_disabled", counts=False)
    deny_table = rule_table(t("rpt_pu_tbl_deny"), deny_hit, "rpt_pu_none_deny", counts=True, note=hedge)
    no_rule = usage.no_rule if ok and usage else []
    no_rule_table = TableBlock(
        title=t("rpt_pu_tbl_no_rule"),
        columns=(Column(key="src", label=t("rpt_col_src_label", key="app")),
                 Column(key="dst", label=t("rpt_col_dst_label", key="app")),
                 Column(key="service", label=t("rpt_col_service")),
                 Column(key="connections", label=t("rpt_col_connections"), kind="number")),
        rows=tuple((g.src_app or no_label, g.dst_app or no_label, port_text(g.port, g.proto), g.connections)
                   for g in no_rule),
        total_rows=usage.no_rule_total if ok and usage else 0, empty_text=t("rpt_pu_none_no_rule") if ok else missing,
        limit_note=t("rpt_limit_top_n", n=len(no_rule)) if ok and usage and usage.no_rule_total > len(no_rule) else None)

    findings: list[Finding] = []
    if ok and unused:
        findings.append(Finding(severity=Severity.LOW, title=t("rpt_pu_finding_unused", n=len(unused)),
                                why=t("rpt_pu_finding_unused_why"), action=t("rpt_pu_finding_unused_action")))
    if usage and usage.pending:
        findings.append(Finding(severity=Severity.LOW, title=t("rpt_pu_finding_pending", n=len(usage.pending)),
                                why=t("rpt_pu_finding_pending_why"), action=t("rpt_pu_finding_pending_action")))

    quality = [t("rpt_pu_quality_source")]
    if usage and usage.truncated:
        quality.append(t("rpt_pu_quality_truncated", n=len(usage.truncated)))
    if usage:
        quality.append(t("rpt_quality_analysis_at", at=fmt_time(usage.computed_at.isoformat(), inp.tz)))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_policy_usage"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=tuple(findings),
        data_quality=tuple(quality),
        sections=(Section(id="how", title=t("rpt_rdy_sec_how"), intro=t("rpt_pu_how_intro"),
                          blocks=(TextBlock(paragraphs=(t("rpt_pu_how_terms"),)),)),
                  Section(id="pending", title=t("rpt_pu_sec_pending"), intro=t("rpt_pu_pending_intro"),
                          blocks=pending_blocks),
                  Section(id="used", title=t("rpt_pu_sec_used"), intro=t("rpt_pu_used_intro"), blocks=used_blocks),
                  Section(id="unused", title=t("rpt_pu_sec_unused"), intro=t("rpt_pu_unused_intro"),
                          blocks=(unused_table,)),
                  Section(id="disabled", title=t("rpt_pu_sec_disabled"), intro=t("rpt_pu_disabled_intro"),
                          blocks=(disabled_table,)),
                  Section(id="deny", title=t("rpt_pu_sec_deny"), intro=t("rpt_pu_deny_intro"), blocks=(deny_table,)),
                  Section(id="no_rule", title=t("rpt_pu_sec_no_rule"), intro=t("rpt_pu_no_rule_intro"),
                          blocks=(no_rule_table,))))
