"""The policy resolver report (spec §6.5 policy_resolver, P5c-4): the active policy's rules expanded to IP-level rows,
as JSON and CSV for other tools (no HTML, user). The document carries the summary the email shows and the rows; the
period does not matter (the policy in force when the report runs). A failed read fails the report."""
from __future__ import annotations

from loguru import logger

from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    RowsExport,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import Severity
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis.policy_resolver import (
    COLUMNS,
    MAX_TOTAL_ROWS,
    resolve,
)
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.registry import BuildInput, ReportFailed
from illumio_ops.services.reports.render_html import fmt_time

# The files' column names and values: data, the same in every language (not translated).
COLUMN_GUIDE = ("ruleset_name, rule_href, action (allow / deny / override_deny), src_ip, dst_ip, port, port_to, protocol, "
                "src_kind and dst_kind (label, label_group, ip_list, workload, all_workloads, ip_address, any), service_name, truncated (src / dst: "
                "that side is a summary; total_row_cap: rows left out)")
BROAD_EXAMPLE = "All Workloads → All Workloads"
_KPI_KEYS = {"rulesets": "rpt_prs_kpi_rulesets", "rules": "rpt_prs_kpi_rules", "rows": "rpt_prs_kpi_rows",
             "capped": "rpt_prs_kpi_capped", "omitted": "rpt_prs_kpi_omitted"}


def build_policy_resolver(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    try:
        r = resolve(inp.ctx, now=inp.now)
    except (PceQueryError, PceCollectionIncomplete, PceNotConfigured, *PCE_FAILURES) as exc:
        logger.warning("policy resolver could not read the policy: {}", exc)
        raise ReportFailed("rpt_prs_err_read", f"{type(exc).__name__}: {exc}"[:200]) from exc
    kept = len(r.rows) - len(r.truncated_rulesets)  # notice rows are not policy rows
    values = {"rulesets": len(r.per_ruleset), "rules": r.rule_count, "rows": kept, "capped": r.rules_capped,
              "omitted": r.rows_omitted}
    kpis = tuple(Kpi(key=k, label=t(lbl), value=values[k], previous=None, unit="count",
                     better="neutral" if k in ("rulesets", "rules", "rows") else "lower")
                 for k, lbl in _KPI_KEYS.items())
    findings: list[Finding] = []
    if r.rows_omitted:
        findings.append(Finding(severity=Severity.MEDIUM,
                                title=t("rpt_prs_finding_omitted", n=f"{r.rows_omitted:,}", cap=f"{MAX_TOTAL_ROWS:,}"),
                                why=t("rpt_prs_finding_omitted_why", rulesets=", ".join(r.truncated_rulesets)),
                                action=t("rpt_prs_finding_omitted_action", example=BROAD_EXAMPLE)))
    if r.rules_capped:
        findings.append(Finding(severity=Severity.LOW, title=t("rpt_prs_finding_capped", n=r.rules_capped),
                                why=t("rpt_prs_finding_capped_why"), action=t("rpt_prs_finding_capped_action")))
    quality = [t("rpt_prs_quality_live", at=fmt_time(r.computed_at.isoformat(), inp.tz))]
    if r.rows_omitted:
        quality.append(t("rpt_prs_quality_omitted", n=f"{r.rows_omitted:,}", cap=f"{MAX_TOTAL_ROWS:,}"))
    per = sorted(r.per_ruleset.items(), key=lambda kv: (-kv[1], kv[0]))
    table = TableBlock(title=t("rpt_prs_tbl_rulesets"),
                       columns=(Column(key="ruleset", label="Ruleset"),
                                Column(key="rows", label=t("rpt_prs_col_rows"), kind="number")),
                       rows=tuple(per), total_rows=len(per), empty_text=t("rpt_prs_none"))
    export = RowsExport(columns=COLUMNS, rows=[tuple(row.get(c) for c in COLUMNS) for row in r.rows],
                        meta={"truncated": bool(r.rows_omitted), "row_cap": MAX_TOTAL_ROWS,
                              "rows_omitted": r.rows_omitted, "truncated_rulesets": ", ".join(r.truncated_rulesets)})
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_policy_resolver"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=tuple(findings),
        data_quality=tuple(quality), export=export,
        sections=(Section(id="how", title=t("rpt_rdy_sec_how"), intro=t("rpt_prs_how_intro"),
                          blocks=(TextBlock(paragraphs=(t("rpt_prs_how_columns", columns=COLUMN_GUIDE, ams="All Workloads"),)), table)),))
