"""The Rule Hit Count report (spec §6.5 rule_hit_count, P5c-2): the PCE's own count of how often each provisioned
rule was hit, from its native report. Rule Hit Count records provisioned rules only (user, 2026-10-24): a rule with
no record (provisioned during or after the period, or not yet provisioned) is never shown as 0, and Draft changes
point to the policy usage report. Greyed out until Rule Hit Count is on; checked again when the report runs, so a
schedule never produces an empty report."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from loguru import logger

from illumio_ops.domain.policy import RuleRef, index_rules
from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import RhcState, RuleAction, Severity
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.pce.policy import fetch_pending, fetch_policy_names, fetch_rule_sets
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.policy_usage import rule_id, rule_scope
from illumio_ops.services.reports.registry import (
    RHC_UNAVAILABLE,
    BuildInput,
    ReportFailed,
)
from illumio_ops.services.reports.render_html import fmt_time
from illumio_ops.services.rhc import RhcPullError, RhcRow, pull_rhc, rhc_status

ROWS = 200
POLICY_DEADLINE_SECONDS = 300
_TYPE_KEYS = {RuleAction.ALLOW: "rpt_rhc_type_allow", RuleAction.DENY: "rpt_rhc_type_deny",
              RuleAction.OVERRIDE_DENY: "rpt_rhc_type_override_deny"}
_KPI_KEYS = {"rules": "rpt_rhc_kpi_rules", "hit": "rpt_rhc_kpi_hit", "zero": "rpt_rhc_kpi_zero",
             "no_record": "rpt_rhc_kpi_no_record"}


def _created(sets: list[dict[str, Any]]) -> dict[str, datetime | None]:
    """Each rule's created_at as the PCE gives it (None when absent or unreadable)."""
    out: dict[str, datetime | None] = {}
    for rs in sets:
        for rule in [*(rs.get("rules") or []), *(rs.get("deny_rules") or [])]:
            raw = rule.get("created_at") if isinstance(rule, dict) else None
            try:
                out[rule["href"]] = datetime.fromisoformat(raw) if raw else None
            except (ValueError, AttributeError, KeyError, TypeError):
                continue
    return out


def build_rule_hit_count(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    status = rhc_status(inp.ctx)  # fresh: the catalog's answer may be minutes old
    if status.state is not RhcState.ENABLED:
        raise ReportFailed(RHC_UNAVAILABLE[status.state] or "rpt_unavailable_rhc_unknown")
    try:
        pull = pull_rhc(inp.ctx, inp.start, inp.end)
        settings = inp.ctx.settings.current()
        deadline = time.monotonic() + POLICY_DEADLINE_SECONDS
        with inp.ctx.pce_client(settings.pce) as client:
            sets = fetch_rule_sets(client, "active", deadline=deadline)
            rules = index_rules(sets, **fetch_policy_names(client, "active", deadline=deadline).__dict__)
            pending = fetch_pending(client, deadline=deadline)
    except RhcPullError as exc:
        raise ReportFailed(exc.key, exc.detail) from exc
    except (PceQueryError, PceCollectionIncomplete, PceNotConfigured, *PCE_FAILURES) as exc:
        logger.warning("rule hit count report: PCE read failed: {}", exc)
        raise ReportFailed("rhc_err_unreachable", f"{type(exc).__name__}: {exc}"[:200]) from exc

    any_text = t("rpt_pu_any")
    by_href = {r.rule_href: r for r in pull.rows}
    hit = sorted((r for r in pull.rows if r.hit_count > 0), key=lambda r: (-r.hit_count, r.rule_href))
    # The PCE's report also lists rules that are only in Draft (a ruleset pending create), under active hrefs with
    # 0 hits (lab, 2026-10-30): not provisioned, so not "0 hits". A 0 for a rule deleted since is no count either.
    # A rule created after the period ended had no count in it either (final review #2).
    later = {h for h, at in _created(sets).items() if at is not None and at >= inp.end}
    counted = {h for h in rules if h not in later}
    zero = sorted((r for r in pull.rows if r.hit_count == 0 and r.rule_href in counted), key=lambda r: r.rule_href)
    unprovisioned = sorted((r for r in pull.rows if r.hit_count == 0 and r.rule_href not in counted),
                           key=lambda r: (r.ruleset_name, r.rule_href))
    # Enabled provisioned rules the PCE has no count for; a disabled rule is not expected to have one.
    no_record = sorted((r for r in rules.values() if r.enabled and r.href not in by_href),
                       key=lambda r: (r.ruleset_name, r.href))

    def cells(row: RhcRow) -> tuple[str, str, str, str]:
        ref: RuleRef | None = rules.get(row.rule_href)
        rid = f"#{row.rule_href.rsplit('/', 1)[-1]}"
        if ref is None:  # deleted or changed since: what the PCE's report said
            return (row.ruleset_name or "—", f"{rid} {row.description}".strip(), "—", "—")
        return (ref.ruleset_name, f"{rule_id(ref)} {ref.description or ''}".strip(), t(_TYPE_KEYS[ref.rule_type]),
                rule_scope(ref, any_text))

    base_cols = (Column(key="ruleset", label="Ruleset"), Column(key="rule", label=t("rpt_pu_col_rule")),
                 Column(key="type", label=t("rpt_rhc_col_type")), Column(key="scope", label=t("rpt_pu_col_scope")))

    def limit(n: int) -> str | None:
        return t("rpt_limit_top_n", n=ROWS) if n > ROWS else None

    hit_table = TableBlock(
        title=t("rpt_rhc_tbl_hit"),
        columns=(*base_cols[:3], Column(key="hits", label=t("rpt_rhc_col_hits"), kind="number"),
                 Column(key="last", label=t("rpt_rhc_col_last_hit")), base_cols[3]),
        rows=tuple((c[0], c[1], c[2], r.hit_count, fmt_time(r.last_hit_at, inp.tz) if r.last_hit_at else "—", c[3])
                   for r in hit[:ROWS] for c in (cells(r),)),
        total_rows=len(hit), empty_text=t("rpt_rhc_none_hit"), limit_note=limit(len(hit)))
    zero_table = TableBlock(
        title=t("rpt_rhc_tbl_zero"),
        columns=(*base_cols[:3], Column(key="last", label=t("rpt_rhc_col_last_hit_ever")), base_cols[3]),
        rows=tuple((c[0], c[1], c[2], fmt_time(r.last_hit_at, inp.tz) if r.last_hit_at else t("rpt_rhc_never"), c[3])
                   for r in zero[:ROWS] for c in (cells(r),)),
        total_rows=len(zero), empty_text=t("rpt_rhc_none_zero"), limit_note=limit(len(zero)))
    unprovisioned_table = TableBlock(
        title=t("rpt_rhc_tbl_unprovisioned"),
        columns=(Column(key="ruleset", label="Ruleset"), Column(key="rule", label=t("rpt_pu_col_rule"))),
        rows=tuple((r.ruleset_name or "—", f"#{r.rule_href.rsplit('/', 1)[-1]} {r.description}".strip())
                   for r in unprovisioned[:ROWS]),
        total_rows=len(unprovisioned), empty_text="", limit_note=limit(len(unprovisioned)))
    no_record_table = TableBlock(
        title=t("rpt_rhc_tbl_no_record"), columns=base_cols,
        rows=tuple((r.ruleset_name, f"{rule_id(r)} {r.description or ''}".strip(), t(_TYPE_KEYS[r.rule_type]),
                    rule_scope(r, any_text)) for r in no_record[:ROWS]),
        total_rows=len(no_record), empty_text=t("rpt_rhc_none_no_record"), limit_note=limit(len(no_record)))

    if pending:
        pending_blocks: tuple[TextBlock | TableBlock, ...] = (
            TextBlock(paragraphs=(t("rpt_rhc_pending_some", n=len(pending)),)),
            TableBlock(title=t("rpt_pu_tbl_pending"),
                       columns=(Column(key="kind", label=t("rpt_pu_col_kind")),
                                Column(key="name", label=t("rpt_col_name")),
                                Column(key="change", label=t("rpt_pu_col_change")),
                                Column(key="at", label=t("rpt_pu_col_updated"))),
                       rows=tuple((p.kind, p.name or p.href.rsplit("/", 1)[-1], p.update_type or "—",
                                   fmt_time(p.updated_at, inp.tz) if p.updated_at else "—") for p in pending),
                       total_rows=len(pending), empty_text=""))
    else:
        pending_blocks = (TextBlock(paragraphs=(t("rpt_rhc_pending_none"),)),)

    enabled_rules = sum(1 for r in rules.values() if r.enabled)
    values = {"rules": enabled_rules, "hit": len(hit), "zero": len(zero),
              "no_record": len(no_record) + len(unprovisioned)}
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k], previous=None, unit="count",
                     better="neutral" if k in ("rules", "no_record") else "higher" if k == "hit" else "lower")
                 for k, label in _KPI_KEYS.items())
    findings: list[Finding] = []
    # An allow rule at 0 still opens a path; a Deny Rule at 0 only means nothing tried the path it blocks.
    zero_allow = [r for r in zero if rules[r.rule_href].rule_type is RuleAction.ALLOW]
    if zero_allow:
        findings.append(Finding(severity=Severity.LOW, title=t("rpt_rhc_finding_zero", n=len(zero_allow)),
                                why=t("rpt_rhc_finding_zero_why"), action=t("rpt_rhc_finding_zero_action")))
    if pending:
        findings.append(Finding(severity=Severity.LOW, title=t("rpt_rhc_finding_pending", n=len(pending)),
                                why=t("rpt_rhc_finding_pending_why"), action=t("rpt_rhc_finding_pending_action")))
    quality = [t("rpt_rhc_quality_source")]
    if pull.unparsed:
        quality.append(t("rpt_rhc_quality_unparsed", n=pull.unparsed))
    gone = sum(1 for r in pull.rows if r.rule_href not in rules and r.hit_count > 0)
    if gone:
        quality.append(t("rpt_rhc_quality_gone", n=gone))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_rule_hit_count"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=tuple(findings),
        data_quality=tuple(quality),
        sections=(Section(id="how", title=t("rpt_rdy_sec_how"), intro=t("rpt_rhc_how_intro"),
                          blocks=(TextBlock(paragraphs=(t("rpt_rhc_how_terms"),)),)),
                  Section(id="hit", title=t("rpt_rhc_sec_hit"), intro=t("rpt_rhc_hit_intro"), blocks=(hit_table,)),
                  Section(id="zero", title=t("rpt_rhc_sec_zero"), intro=t("rpt_rhc_zero_intro"),
                          blocks=(zero_table,)),
                  Section(id="no_record", title=t("rpt_rhc_sec_no_record"), intro=t("rpt_rhc_no_record_intro"),
                          blocks=(no_record_table, *((unprovisioned_table,) if unprovisioned else ()))),
                  Section(id="pending", title=t("rpt_rhc_sec_pending"), intro=t("rpt_rhc_pending_intro"),
                          blocks=pending_blocks)))
