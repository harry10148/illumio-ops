"""The enforcement readiness report (spec §6.5 報表, §6.5.5 評估: readiness with predicted blocks): for each app
(environment), whether it can move to enforcement — five factors over the connections into its hosts and its hosts'
modes — what the draft policy would block (the PCE recomputes it), and the order to enforce in."""
from __future__ import annotations

from collections import Counter

from loguru import logger

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.readiness import (
    WEIGHTS,
    Readiness,
    ReadinessInputs,
    readiness,
    score_with,
)
from illumio_ops.domain.report import (
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import PortClass, Severity
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.analysis.predicted_block import (
    PredictedSummary,
    predicted_summary,
)
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.flowsource import UnruledLink, readiness_rows, unruled_inbound
from illumio_ops.services.reports import flowsections
from illumio_ops.services.reports.common import port_text, tr
from illumio_ops.services.reports.generate import coverage_note
from illumio_ops.services.reports.history import previous_values
from illumio_ops.services.reports.registry import BuildInput

APP = "app"
PREDICTED_ROWS = 50
# Rows the draft recompute asks the PCE for: its answer is held whole while it is read (about 4 KB a row in
# memory), so 50,000 keeps a report within its half-gigabyte budget; more is disclosed as capped.
PREDICTED_MAX_RESULTS = 50_000
_FACTOR_KEYS = {"policy": "rpt_rdy_factor_policy", "ringfence": "rpt_rdy_factor_ringfence",
                "enforcement": "rpt_rdy_factor_enforcement", "staged": "rpt_rdy_factor_staged",
                "remote": "rpt_rdy_factor_remote"}
_ADVICE_KEYS = {"policy": "rpt_rdy_advice_policy", "ringfence": "rpt_rdy_advice_ringfence",
                "enforcement": "rpt_rdy_advice_enforcement", "staged": "rpt_rdy_advice_staged",
                "remote": "rpt_rdy_advice_remote"}
NEXT_APPS = 5  # the apps closest to ready, in "what to do first"
UNRULED_TOP = 3  # inbound connections without a rule, per app
_MEASURES_KEYS = {"policy": "rpt_rdy_measures_policy", "ringfence": "rpt_rdy_measures_ringfence",
                  "enforcement": "rpt_rdy_measures_enforcement", "staged": "rpt_rdy_measures_staged",
                  "remote": "rpt_rdy_measures_remote"}
_FULL_KEYS = {"policy": "rpt_rdy_full_policy", "ringfence": "rpt_rdy_full_ringfence",
              "enforcement": "rpt_rdy_full_enforcement", "staged": "rpt_rdy_full_staged", "remote": "rpt_rdy_full_remote"}
# grade -> (score range, what it means)
_GRADE_KEYS = {"A": ("rpt_rdy_range_a", "rpt_rdy_means_a"), "B": ("rpt_rdy_range_b", "rpt_rdy_means_b"),
               "C": ("rpt_rdy_range_c", "rpt_rdy_means_c"), "D": ("rpt_rdy_range_d", "rpt_rdy_means_d"),
               "F": ("rpt_rdy_range_f", "rpt_rdy_means_f")}
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
    # The apps assessed are destinations: a source condition narrows their traffic, never their hosts.
    cond = inp.params.filter
    dst_scope = FlowCondition(dst=cond.dst, dst_exclude=cond.dst_exclude) if cond is not None else None
    hosts: dict[tuple[str | None, str | None], Counter[str]] = {}
    for h in lc.hosts.values():
        if flowsections.host_in_scope(h, dst_scope):
            key = (h.labels.get(APP) or None, h.labels.get(env_key) or None)
            hosts.setdefault(key, Counter())[h.enforcement_mode or "unknown"] += 1
    no_label = t("rpt_no_label")

    def name(key: tuple[str | None, str | None]) -> str:
        return f"{key[0] or no_label} ({key[1] or no_label})"
    scored: list[tuple[tuple[str | None, str | None], Readiness, Counter[str]]] = []
    for key in sorted(set(flows) | set(hosts), key=lambda k: (k[0] or "", k[1] or "")):
        f, m = flows.get(key), hosts.get(key, Counter())
        if f is None or not f.connections:  # no traffic into it in the period: not assessed (Review Focus 1)
            scored.append((key, Readiness(score=None, grade=None, parts=dict.fromkeys(WEIGHTS), blocking=None), m))
            continue
        scored.append((key, readiness(ReadinessInputs(
            connections=f.connections, decided=f.connections - f.unknown, allowed=f.allowed, same_app=f.same_app,
            potentially_blocked=f.potentially_blocked, remote=f.remote, remote_allowed=f.remote_allowed,
            hosts=sum(m.values()), full=m["full"],
            selective=m["selective"])), m))

    # ── predicted blocks ────────────────────────────────────────────────────
    predicted: PredictedSummary | None = None
    failure: str | None = None
    try:
        predicted = predicted_summary(inp.ctx, spec, app_key=APP, max_results=PREDICTED_MAX_RESULTS)
    except (PceQueryError, PceCollectionIncomplete, PceNotConfigured, *PCE_FAILURES) as exc:
        logger.warning("predicted blocks for the readiness report could not be computed: {}", exc)
        failure = f"{type(exc).__name__}: {exc}"[:200]
    # Blocked connections found stand; a zero with undetermined flows is not a confirmed "blocks nothing".
    usable = (predicted is not None and not predicted.unsupported
              and (predicted.blocked_flows > 0 or not predicted.undetermined_flows))

    rated = [r.score for _, r, _ in scored if r.score is not None]
    values: dict[str, float | int | None] = {
        "apps": sum(1 for _, r, _ in scored if r.score is not None), "ready": sum(1 for _, r, _ in scored if r.grade in ("A", "B")),
        "held_back": sum(1 for _, r, _ in scored if r.grade in ("D", "F")),
        "overall": round(sum(rated) / len(rated)) if rated else None,  # points, as each app's score
        "predicted_blocked": predicted.blocked_connections if usable and predicted else None}
    no_data = t("rpt_no_flows_filtered" if inp.params.filter is not None else "rpt_rdy_no_apps")
    notes = {"overall": None if rated else no_data,
             "predicted_blocked": (
                 t("rpt_rdy_predicted_failed", error=failure or "") if predicted is None
                 else t("rpt_rdy_predicted_unsupported") if predicted.unsupported
                 else t("rpt_rdy_predicted_undetermined", n=f"{predicted.undetermined_flows:,}")
                 if predicted.undetermined_flows else None)}
    before = previous_values(inp)
    kpis = tuple(Kpi(key=k, label=t(label), value=values[k], previous=before.get(k) if before else None,
                     unit="count",
                     better="higher" if k in ("ready", "overall") else "lower" if k != "apps" else "neutral",
                     note=notes.get(k)) for k, label in _KPI_KEYS.items())

    def pct(v: float | None) -> str:
        return f"{100 * v:.1f}%" if v is not None else "—"

    def modes(m: Counter[str]) -> str:
        return t("rpt_rdy_modes", full=m["full"], selective=m["selective"], visibility=m["visibility_only"],
                 idle=m["idle"]) if m else t("rpt_rdy_no_hosts")

    def advice(r: Readiness) -> str:
        if r.score is None:
            return t("rpt_rdy_advice_not_assessed")
        return t(_ADVICE_KEYS[r.blocking]) if r.blocking else t("rpt_rdy_advice_ready")

    def explain(r: Readiness) -> str:
        """Why the score is what it is, in words: the factor costing most, its points, and the score without it."""
        if r.score is None or r.grade is None:
            return t("rpt_rdy_advice_not_assessed")
        if r.blocking is None:
            return t("rpt_rdy_explain_ready", score=f"{r.score:.0f}", grade=r.grade)
        part = r.parts[r.blocking] or 0.0
        fixed = score_with(r.parts, r.blocking)
        return t("rpt_rdy_explain", score=f"{r.score:.0f}", grade=r.grade, factor=t(_FACTOR_KEYS[r.blocking]),
                 got=f"{WEIGHTS[r.blocking] * part:.0f}", weight=WEIGHTS[r.blocking], share=pct(part),
                 fixed=f"{fixed:.0f}" if fixed is not None else "—")

    unruled = unruled_inbound(inp.ctx, spec, app_key=APP, env_key=env_key, top=UNRULED_TOP)

    def links(key: tuple[str | None, str | None]) -> str:
        found: list[UnruledLink] = unruled.get(key, [])
        if not found:
            return "—"
        return "; ".join(t("rpt_rdy_link", src=l.src_app or no_label, service=port_text(l.port, l.proto),
                           n=f"{l.connections:,}") for l in found)
    scores = TableBlock(
        title=t("rpt_rdy_tbl_scores"),
        columns=(Column(key="app", label=t("rpt_col_app_env")),
                 Column(key="score", label=t("rpt_rdy_col_score"), kind="number"),
                 Column(key="grade", label=t("rpt_rdy_col_grade")),
                 Column(key="explain", label=t("rpt_rdy_col_explain")),
                 *(Column(key=k, label=t(_FACTOR_KEYS[k])) for k in WEIGHTS),
                 Column(key="modes", label=t("rpt_rdy_col_modes")), Column(key="advice", label=t("rpt_col_action"))),
        # whole points, as the explanation says them
        rows=tuple((name(k), round(r.score) if r.score is not None else None, r.grade or "—", explain(r),
                    *(pct(r.parts[f]) for f in WEIGHTS), modes(m), advice(r)) for k, r, m in scored),
        total_rows=len(scored), empty_text=no_data)

    predicted_blocks: tuple[TableBlock | TextBlock, ...]
    if predicted is None:
        predicted_blocks = (TextBlock(paragraphs=(t("rpt_rdy_predicted_failed", error=failure or ""),)),)
    elif predicted.unsupported:
        predicted_blocks = (TextBlock(paragraphs=(t("rpt_rdy_predicted_unsupported"),)),)
    else:
        undetermined = (TextBlock(paragraphs=(t("rpt_rdy_predicted_undetermined", n=f"{predicted.undetermined_flows:,}"),)),)

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
            total_rows=len(groups),
            empty_text=t("rpt_rdy_predicted_none_unconfirmed") if predicted.undetermined_flows
            else t("rpt_rdy_predicted_none"),
            limit_note=" ".join(x for x in (
                t("rpt_limit_top_n", n=PREDICTED_ROWS) if len(groups) > PREDICTED_ROWS else "",
                t("rpt_rdy_predicted_capped", n=f"{PREDICTED_MAX_RESULTS:,}") if predicted.capped else "") if x)
                or None), *(undetermined if predicted.undetermined_flows else ()))

    closest = sorted((x for x in scored if x[1].score is not None),
                     key=lambda x: (-(x[1].score or 0), name(x[0])))[:NEXT_APPS]
    next_steps = TableBlock(
        title=t("rpt_rdy_tbl_next"),
        # the next step and the rules to write in one column: at 1280 px a fourth column was past the edge
        columns=(Column(key="app", label=t("rpt_col_app_env")), Column(key="where", label=t("rpt_rdy_col_where")),
                 Column(key="next", label=t("rpt_rdy_col_next"))),
        rows=tuple((name(k), explain(r), advice(r) if links(k) == "—" else t("rpt_rdy_next_with_links",
                                                                                advice=advice(r), links=links(k)))
                   for k, r, _ in closest),
        total_rows=len(closest), empty_text=no_data)
    factors = TableBlock(
        title=t("rpt_rdy_tbl_factors"),
        columns=(Column(key="factor", label=t("rpt_rdy_col_factor")), Column(key="measures", label=t("rpt_rdy_col_measures")),
                 Column(key="full", label=t("rpt_rdy_col_full_marks")), Column(key="points", label=t("rpt_rdy_col_points"))),
        rows=tuple((t(_FACTOR_KEYS[k]), t(_MEASURES_KEYS[k]), t(_FULL_KEYS[k]), str(w))
                   for k, w in WEIGHTS.items()),
        total_rows=len(WEIGHTS), empty_text="")
    grades = TableBlock(
        title=t("rpt_rdy_tbl_grades"),
        columns=(Column(key="grade", label=t("rpt_rdy_col_grade")), Column(key="range", label=t("rpt_rdy_col_range")),
                 Column(key="means", label=t("rpt_rdy_col_means"))),
        rows=tuple((g, t(rng), t(means)) for g, (rng, means) in _GRADE_KEYS.items()),
        total_rows=len(_GRADE_KEYS), empty_text="")

    findings: tuple[Finding, ...] = ()
    if values["held_back"] and closest:
        first_key, first, _ = closest[0]
        findings = (Finding(severity=Severity.MEDIUM,
                            title=t("rpt_rdy_finding_title", n=values["held_back"], total=values["apps"]),
                            why=t("rpt_rdy_finding_why", app=name(first_key), explain=explain(first)),
                            action=t("rpt_rdy_finding_action")),)

    total = sum(r.connections for r in flows.values())
    unknown = sum(r.unknown for r in flows.values())
    filter_line = flowsections.filter_text(inp.params.filter, lang)
    quality = (*coverage_note(inp.ctx, inp.start, inp.end, lang, now=inp.now, tz=inp.tz, flows=True),
               *((t("rpt_quality_filter", filter=filter_line),) if filter_line else ()),
               t("rpt_rdy_quality_definition"),
               *((t("rpt_rdy_quality_unknown", pct=f"{100 * unknown / total:.1f}"),) if unknown else ()))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_readiness"), period_start=inp.start,
        period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=kpis, findings=findings,
        data_quality=quality,
        sections=(Section(id="how", title=t("rpt_rdy_sec_how"), intro=t("rpt_rdy_how_intro"), blocks=(factors, grades)),
                  Section(id="next", title=t("rpt_rdy_sec_next"), intro=t("rpt_rdy_next_intro"), blocks=(next_steps,)),
                  Section(id="scores", title=t("rpt_rdy_sec_scores"), intro=t("rpt_rdy_scores_intro"), blocks=(scores,)),
                  Section(id="predicted", title=t("rpt_rdy_sec_predicted"), intro=t("rpt_rdy_predicted_intro"),
                          blocks=predicted_blocks)))
