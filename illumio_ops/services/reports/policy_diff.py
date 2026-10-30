"""The policy diff report (spec §6.5 policy_diff, P5c-3): what provisioning the Draft would change against the
active policy — rule sets, rules, IP lists, services and label groups — risky changes first, each with the newest
stored event that names it. The diff is the PCE's state when the report runs; the period only bounds the events read
for "who changed it". A failed read fails the report: an empty side would read as everything added or removed."""
from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from illumio_ops.domain.policy_diff import Change, draft_href
from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import Severity
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis.policy_diff import (
    EVENT_LIMIT,
    PolicyDiff,
    policy_diff,
)
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.registry import BuildInput, ReportFailed
from illumio_ops.services.reports.render_html import fmt_time

ROWS = 200
HIGH_FINDINGS = 5
_KPI_KEYS = {"total": "rpt_pdf_kpi_total", "high": "rpt_pdf_kpi_high", "rule_sets": "rpt_pdf_kpi_rule_sets",
             "rules": "rpt_pdf_kpi_rules", "objects": "rpt_pdf_kpi_objects", "other_pending": "rpt_pdf_kpi_other"}
# Literal maps: i18n keys are never built from data.
_CHANGE = {"added": "rpt_pdf_change_added", "removed": "rpt_pdf_change_removed", "modified": "rpt_pdf_change_modified"}
_KIND = {"rule_set": "rpt_pdf_kind_rule_set", "rule": "rpt_pdf_kind_rule", "ip_list": "rpt_pdf_kind_ip_list",
         "service": "rpt_pdf_kind_service", "label_group": "rpt_pdf_kind_label_group"}
_RISK = {"high": "rpt_pdf_risk_high", "medium": "rpt_pdf_risk_medium"}
_RULE_TYPE = {"allow": "rpt_rhc_type_allow", "deny": "rpt_rhc_type_deny", "override_deny": "rpt_rhc_type_override_deny"}
_FIELD = {"*": "rpt_pdf_field_whole", "name": "rpt_pdf_field_name", "enabled": "rpt_pdf_field_enabled",
          "description": "rpt_pdf_field_description", "rule_count": "rpt_pdf_field_rule_count",
          "rule_type": "rpt_pdf_field_rule_type", "providers": "rpt_pdf_field_providers",
          "consumers": "rpt_pdf_field_consumers", "services": "rpt_pdf_field_services",
          "ip_ranges": "rpt_pdf_field_ip_ranges", "fqdns": "rpt_pdf_field_fqdns",
          "service_ports": "rpt_pdf_field_service_ports", "windows_services": "rpt_pdf_field_windows_services",
          "labels": "rpt_pdf_field_labels", "sub_groups": "rpt_pdf_field_sub_groups"}
_OBJECT_KINDS = ("ip_list", "service", "label_group")


def build_policy_diff(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    try:
        diff: PolicyDiff = policy_diff(inp.ctx, start=inp.start, end=inp.end, now=inp.now)
    except (PceQueryError, PceCollectionIncomplete, PceNotConfigured, *PCE_FAILURES) as exc:
        logger.warning("policy diff could not read the policy: {}", exc)
        raise ReportFailed("rpt_pdf_err_read", f"{type(exc).__name__}: {exc}"[:200]) from exc

    def value(c: Change, v: str) -> str:
        if not v:
            return "—"
        if c.field == "enabled":
            return t("rpt_pdf_on" if v == "True" else "rpt_pdf_off")
        if c.field == "rule_type" or (c.kind == "rule" and c.field == "*"):
            return t(_RULE_TYPE[v]) if v in _RULE_TYPE else v
        if c.kind == "rule_set" and c.field == "*" and c.rule_count is not None:
            return t("rpt_pdf_with_rules", name=v, n=c.rule_count)
        return v

    def who(c: Change) -> str:
        a = diff.attribution.get(draft_href(c.href))
        return f"{a.actor} ({fmt_time(a.at.isoformat(), inp.tz)})" if a else "—"

    def label(mapping: dict[str, str], key: str) -> str:
        return t(mapping[key]) if key in mapping else key

    def table(title: str, items: list[Change], cols: tuple[Column, ...], cells: Callable[[Change], tuple[str | int | float | None, ...]],
              empty: str) -> TableBlock:
        return TableBlock(title=title, columns=cols, rows=tuple(cells(c) for c in items[:ROWS]), total_rows=len(items),
                          empty_text=t(empty), limit_note=t("rpt_limit_top_n", n=ROWS) if len(items) > ROWS else None)

    c_change, c_field = Column(key="change", label=t("rpt_pdf_col_change")), Column(key="field", label=t("rpt_pdf_col_field"))
    c_draft, c_active = Column(key="draft", label="Draft"), Column(key="active", label=t("rpt_pdf_col_active"))
    c_who, c_risk = Column(key="who", label=t("rpt_pdf_col_who")), Column(key="risk", label=t("rpt_pdf_col_risk"))

    changes = diff.changes
    risky = [c for c in changes if c.risk == "high"] + [c for c in changes if c.risk == "medium"]
    rule_sets = [c for c in changes if c.kind == "rule_set"]
    rules = [c for c in changes if c.kind == "rule"]
    objects = [c for c in changes if c.kind in _OBJECT_KINDS]

    def where(c: Change) -> str:
        if c.kind == "rule":
            return f"{c.ruleset} › {c.name} ({c.ref})"
        return c.name or c.ref

    risk_table = table(t("rpt_pdf_tbl_risk"), risky,
                       (Column(key="risk", label=t("rpt_pdf_col_risk")), Column(key="kind", label=t("rpt_pdf_col_kind")),
                        Column(key="what", label=t("rpt_pdf_col_what")), c_change, c_field, c_draft, c_active, c_who),
                       lambda c: (label(_RISK, c.risk), label(_KIND, c.kind), where(c), label(_CHANGE, c.change),
                                  label(_FIELD, c.field), value(c, c.draft), value(c, c.active), who(c)),
                       "rpt_pdf_none_risk")
    rs_table = table(t("rpt_pdf_tbl_rule_sets"), rule_sets,
                     (Column(key="ruleset", label="Ruleset"), c_change, c_field, c_draft, c_active, c_risk, c_who),
                     lambda c: (c.name or c.ref, label(_CHANGE, c.change), label(_FIELD, c.field), value(c, c.draft),
                                value(c, c.active), label(_RISK, c.risk) if c.risk else "—", who(c)),
                     "rpt_pdf_none_rule_sets")
    rule_table = table(t("rpt_pdf_tbl_rules"), rules,
                       (Column(key="ruleset", label="Ruleset"), Column(key="rule", label=t("rpt_pu_col_rule")),
                        Column(key="type", label=t("rpt_rhc_col_type")), c_change, c_field, c_draft, c_active, c_risk,
                        c_who),
                       lambda c: (c.ruleset, f"{c.name} ({c.ref})", label(_RULE_TYPE, c.rule_type),
                                  label(_CHANGE, c.change), label(_FIELD, c.field), value(c, c.draft),
                                  value(c, c.active), label(_RISK, c.risk) if c.risk else "—", who(c)),
                       "rpt_pdf_none_rules")
    obj_table = table(t("rpt_pdf_tbl_objects"), objects,
                      (Column(key="kind", label=t("rpt_pdf_col_kind")), Column(key="name", label=t("rpt_col_name")),
                       c_change, c_field, c_draft, c_active, Column(key="wider", label=t("rpt_pdf_col_wider")), c_risk,
                       c_who),
                      lambda c: (label(_KIND, c.kind), c.name or c.ref, label(_CHANGE, c.change), label(_FIELD, c.field),
                                 value(c, c.draft), value(c, c.active),
                                 t("rpt_pdf_yes") if c.scope_expanded else "—",
                                 label(_RISK, c.risk) if c.risk else "—", who(c)),
                      "rpt_pdf_none_objects")
    other = diff.other_pending
    other_table = TableBlock(
        title=t("rpt_pdf_tbl_other"),
        columns=(Column(key="kind", label=t("rpt_pu_col_kind")), Column(key="name", label=t("rpt_col_name")),
                 Column(key="change", label=t("rpt_pu_col_change")), Column(key="at", label=t("rpt_pu_col_updated"))),
        rows=tuple((p.kind, p.name or p.href.rsplit("/", 1)[-1], p.update_type or "—",
                    fmt_time(p.updated_at, inp.tz) if p.updated_at else "—") for p in other),
        total_rows=len(other), empty_text=t("rpt_pdf_none_other"))

    values = {"total": len(changes), "high": sum(1 for c in changes if c.risk == "high"),
              "rule_sets": len({c.ref for c in rule_sets}), "rules": len({c.ref + c.ruleset for c in rules}),
              "objects": len({c.kind + c.ref for c in objects}), "other_pending": len(other)}
    kpis = tuple(Kpi(key=k, label=t(lbl), value=values[k], previous=None, unit="count",
                     better="neutral" if k != "high" else "lower") for k, lbl in _KPI_KEYS.items())
    findings: list[Finding] = []
    for c in [c for c in changes if c.risk == "high"][:HIGH_FINDINGS]:
        widened = c.kind in _OBJECT_KINDS
        findings.append(Finding(
            severity=Severity.HIGH,
            title=t("rpt_pdf_finding_widened" if widened else "rpt_pdf_finding_disabled", kind=label(_KIND, c.kind),
                    name=where(c)),
            why=t("rpt_pdf_finding_widened_why" if widened else "rpt_pdf_finding_disabled_why"),
            action=t("rpt_pdf_finding_action")))
    if other:
        findings.append(Finding(severity=Severity.LOW, title=t("rpt_pdf_finding_other", n=len(other)),
                                why=t("rpt_pdf_finding_other_why"), action=t("rpt_pdf_finding_other_action")))
    summary = t("rpt_pdf_summary_same") if not changes and not other else t("rpt_pdf_summary_some", n=len(changes))
    quality = [t("rpt_pdf_quality_live", at=fmt_time(diff.computed_at.isoformat(), inp.tz)), t("rpt_pdf_quality_who")]
    if diff.attribution_limited:
        quality.append(t("rpt_pdf_quality_who_limited", n=f"{EVENT_LIMIT:,}"))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_policy_diff"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=tuple(findings),
        data_quality=tuple(quality),
        sections=(Section(id="how", title=t("rpt_rdy_sec_how"), intro=t("rpt_pdf_how_intro"),
                          blocks=(TextBlock(paragraphs=(summary, t("rpt_pdf_how_terms"))),)),
                  Section(id="risk", title=t("rpt_pdf_sec_risk"), intro=t("rpt_pdf_risk_intro"), blocks=(risk_table,)),
                  Section(id="rule_sets", title=t("rpt_pdf_sec_rule_sets"), intro=t("rpt_pdf_rule_sets_intro"),
                          blocks=(rs_table,)),
                  Section(id="rules", title=t("rpt_pdf_sec_rules"), intro=t("rpt_pdf_rules_intro"), blocks=(rule_table,)),
                  Section(id="objects", title=t("rpt_pdf_sec_objects"), intro=t("rpt_pdf_objects_intro"),
                          blocks=(obj_table,)),
                  Section(id="other", title=t("rpt_pdf_sec_other"), intro=t("rpt_pdf_other_intro"),
                          blocks=(other_table,))))
