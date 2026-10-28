"""The enforcement readiness report (spec §6.5 報表, §6.5.5 評估: readiness with predicted blocks): for each app
(environment), whether it can move to enforcement — five factors over the connections into its hosts and its hosts'
modes — what the draft policy would block (the PCE recomputes it), and the order to enforce in."""
from __future__ import annotations

from collections import Counter

from loguru import logger

from illumio_ops.domain.readiness import WEIGHTS, Readiness, ReadinessInputs, readiness
from illumio_ops.domain.report import (
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import PortClass
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.analysis.predicted_block import (
    PredictedSummary,
    predicted_summary,
)
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.flowsource import readiness_rows
from illumio_ops.services.reports import flowsections
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.generate import coverage_note
from illumio_ops.services.reports.registry import BuildInput

APP = "app"
PREDICTED_ROWS = 50
_FACTOR_KEYS = {"policy": "rpt_rdy_factor_policy", "ringfence": "rpt_rdy_factor_ringfence",
                "enforcement": "rpt_rdy_factor_enforcement", "staged": "rpt_rdy_factor_staged",
                "remote": "rpt_rdy_factor_remote"}
_ADVICE_KEYS = {"policy": "rpt_rdy_advice_policy", "ringfence": "rpt_rdy_advice_ringfence",
                "enforcement": "rpt_rdy_advice_enforcement", "staged": "rpt_rdy_advice_staged",
                "remote": "rpt_rdy_advice_remote"}
_KPI_KEYS = {"apps": "rpt_rdy_kpi_apps", "ready": "rpt_rdy_kpi_ready", "held_back": "rpt_rdy_kpi_held_back",
             "overall": "rpt_rdy_kpi_overall", "predicted_blocked": "rpt_rdy_kpi_predicted"}


def build_readiness(inp: BuildInput) -> ReportDocument:
    lang = inp.lang

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    lc = load_lateral_context(inp.ctx, now=inp.now)
    env_key = lc.settings.environment_label_key
    remote = {(e.port, e.proto) for e in lc.admin_ports.entries if e.category is PortClass.REMOTE}
    spec = flowsections.window(inp)
    flows = {(r.app, r.env): r for r in readiness_rows(inp.ctx, spec, app_key=APP, env_key=env_key,
                                                       remote_ports=remote)}
    hosts: dict[tuple[str | None, str | None], Counter[str]] = {}
    for h in lc.hosts.values():
        if flowsections.host_in_scope(h, inp.params.filter):
            key = (h.labels.get(APP) or None, h.labels.get(env_key) or None)
            hosts.setdefault(key, Counter())[h.enforcement_mode or "unknown"] += 1
    no_label = t("rpt_no_label")

    def name(key: tuple[str | None, str | None]) -> str:
        return f"{key[0] or no_label} ({key[1] or no_label})"
    scored: list[tuple[tuple[str | None, str | None], Readiness, Counter[str]]] = []
    for key in sorted(set(flows) | set(hosts), key=lambda k: (k[0] or "", k[1] or "")):
        f, m = flows.get(key), hosts.get(key, Counter())
        scored.append((key, readiness(ReadinessInputs(
            connections=f.connections if f else 0, allowed=f.allowed if f else 0, same_app=f.same_app if f else 0,
            potentially_blocked=f.potentially_blocked if f else 0, remote=f.remote if f else 0,
            remote_allowed=f.remote_allowed if f else 0, hosts=sum(m.values()), full=m["full"],
            selective=m["selective"])), m))

    # ── predicted blocks ────────────────────────────────────────────────────
    predicted: PredictedSummary | None = None
    failure: str | None = None
    try:
        predicted = predicted_summary(inp.ctx, spec, app_key=APP)
    except (PceQueryError, PceNotConfigured, *PCE_FAILURES) as exc:
        logger.warning("predicted blocks for the readiness report could not be computed: {}", exc)
        failure = f"{type(exc).__name__}: {exc}"[:200]
    usable = predicted is not None and not predicted.unsupported

    rated = [r.score for _, r, _ in scored if r.score is not None]
    values: dict[str, float | int | None] = {
        "apps": len(scored), "ready": sum(1 for _, r, _ in scored if r.grade in ("A", "B")),
        "held_back": sum(1 for _, r, _ in scored if r.grade in ("D", "F")),
        "overall": round(sum(rated) / len(rated), 1) if rated else None,
        "predicted_blocked": predicted.blocked_connections if usable and predicted else None}
    no_data = t("rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_rdy_no_apps")
    notes = {"overall": None if rated else no_data,
             "predicted_blocked": None if usable else (t("rpt_rdy_predicted_unsupported") if predicted
                                                       else t("rpt_rdy_predicted_failed", error=failure or ""))}
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k], previous=None,
                     unit="percent" if k == "overall" else "count",
                     better="higher" if k in ("ready", "overall") else "lower" if k != "apps" else "neutral",
                     note=notes.get(k)) for k, label in _KPI_KEYS.items())

    def pct(v: float | None) -> str:
        return f"{100 * v:.1f}%" if v is not None else "—"

    def modes(m: Counter[str]) -> str:
        return t("rpt_rdy_modes", full=m["full"], selective=m["selective"], visibility=m["visibility_only"],
                 idle=m["idle"]) if m else t("rpt_rdy_no_hosts")

    def advice(r: Readiness) -> str:
        return t(_ADVICE_KEYS[r.blocking]) if r.blocking else t("rpt_rdy_advice_ready")
    scores = TableBlock(
        title=t("rpt_rdy_tbl_scores"),
        columns=(Column(key="app", label=t("rpt_col_app_env")),
                 Column(key="score", label=t("rpt_rdy_col_score"), kind="number"),
                 Column(key="grade", label=t("rpt_rdy_col_grade")),
                 *(Column(key=k, label=t(_FACTOR_KEYS[k])) for k in WEIGHTS),
                 Column(key="blocking", label=t("rpt_rdy_col_blocking")),
                 Column(key="modes", label=t("rpt_rdy_col_modes")), Column(key="advice", label=t("rpt_col_action"))),
        rows=tuple((name(k), round(r.score, 1) if r.score is not None else None, r.grade or "—",
                    *(pct(r.parts[f]) for f in WEIGHTS), t(_FACTOR_KEYS[r.blocking]) if r.blocking else "—",
                    modes(m), advice(r)) for k, r, m in scored),
        total_rows=len(scored), empty_text=no_data)

    predicted_blocks: tuple[TableBlock | TextBlock, ...]
    if predicted is None:
        predicted_blocks = (TextBlock(paragraphs=(t("rpt_rdy_predicted_failed", error=failure or ""),)),)
    elif predicted.unsupported:
        predicted_blocks = (TextBlock(paragraphs=(t("rpt_rdy_predicted_unsupported"),)),)
    else:
        def rule_name(href: str) -> str:
            ref = predicted.rules.get(href) if predicted else None
            if ref is None:
                return t("rpt_rdy_rule_missing", id=href.rsplit("/", 1)[-1])
            return f"{ref.ruleset_name}: {ref.description or href.rsplit('/', 1)[-1]}"
        groups = predicted.groups
        predicted_blocks = (TableBlock(
            title=t("rpt_rdy_tbl_predicted"),
            columns=(Column(key="app", label=t("rpt_col_dst_label", key=APP)),
                     Column(key="rule", label=t("rpt_rdy_col_rule")),
                     Column(key="flows", label=t("rpt_col_flows"), kind="number"),
                     Column(key="connections", label=t("rpt_col_connections"), kind="number")),
            rows=tuple((g.dst_app or no_label, rule_name(g.rule_href), g.flows, g.connections)
                       for g in groups[:PREDICTED_ROWS]),
            total_rows=len(groups), empty_text=t("rpt_rdy_predicted_none"),
            limit_note=" ".join(x for x in (
                t("rpt_limit_top_n", n=PREDICTED_ROWS) if len(groups) > PREDICTED_ROWS else "",
                t("rpt_rdy_predicted_capped") if predicted.capped else "") if x) or None),)

    queue_rows = sorted((x for x in scored if x[1].score is not None), key=lambda x: (-(x[1].score or 0), name(x[0])))
    queue = TableBlock(
        title=t("rpt_rdy_tbl_queue"),
        columns=(Column(key="app", label=t("rpt_col_app_env")), Column(key="grade", label=t("rpt_rdy_col_grade")),
                 Column(key="blocking", label=t("rpt_rdy_col_blocking")),
                 Column(key="next", label=t("rpt_rdy_col_next"))),
        rows=tuple((name(k), r.grade or "—", t(_FACTOR_KEYS[r.blocking]) if r.blocking else "—", advice(r))
                   for k, r, _ in queue_rows),
        total_rows=len(queue_rows), empty_text=no_data)

    filter_line = flowsections.filter_text(inp.params.filter, lang)
    quality = (*coverage_note(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True),
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_rdy_quality_definition"))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_readiness"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=(),
        data_quality=quality,
        sections=(Section(id="scores", title=t("rpt_rdy_sec_scores"), intro=t("rpt_rdy_scores_intro"), blocks=(scores,)),
                  Section(id="predicted", title=t("rpt_rdy_sec_predicted"), intro=t("rpt_rdy_predicted_intro"),
                          blocks=predicted_blocks),
                  Section(id="queue", title=t("rpt_rdy_sec_queue"), intro=t("rpt_rdy_queue_intro"), blocks=(queue,))))
