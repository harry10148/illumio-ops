"""The weekly overview (UI redesign spec §9.2): one page for a manager or a shift handover — the period's alerts,
the VENs' state, the traffic by decision, the new connections and the policy provisions, each chapter ending with the
report that holds its detail, and the things to do first from the 19 findings rules and the VENs' state.

Every number is one a topic report gives for the same data, counted by the same function: alerts by the alert
store's reads, VENs by ven_status.read_fleet, traffic by flowsource.flow_totals, new connections by
new_connections.count_new, provisions by eventsource.audit_counts.

Traffic. Alerts, the inventory and events are read from the install in every mode. Traffic is read from the install's
store when that keeps the period, else pulled from the PCE here, once, for the previous period and the new
connections' baseline as well. When the PCE cannot give it — the pull fails, stops at its row limit before the period,
or returns no flow at all (a period older than what the PCE keeps looks like that) — the two traffic chapters
say why in one sentence, their two numbers are None with that reason, the rules are reported as not run for that
reason, and the other three chapters stand: the report is made. A PCE switched meanwhile fails the report as it fails
any other (BindingMismatch, StaleGeneration and the generator's own check are not caught here).

A number of the previous period is given only where that period's records are known to be whole — never a 0 for
"no record":
- alerts: both periods are checked against where this install's alert records start (alerts_known_from);
- traffic and new connections: the previous period was collected whole; on a pull, the PCE also returned a flow
  from before it (a pulled store counts its whole range as collected whatever the PCE still keeps);
- enforcement modes: the daily snapshot of the previous period's last day (workloads.mode_counts_on);
- VENs online or out of contact: the inventory keeps no history, so this period only."""
from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from illumio_ops.domain.audit import PROVISION
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.findings_rules import RuleOutcome
from illumio_ops.domain.report import (
    Block,
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import SEVERITY_ORDER, ReportType
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.collect.guard import normalize_target, require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import audit_counts
from illumio_ops.services.flowsource import (
    LONG_RECORD_DAYS,
    FlowTotals,
    flow_totals,
    longest_record_days,
)
from illumio_ops.services.hosts import display_names
from illumio_ops.services.ondemand import (
    ONDEMAND_MAX_ROWS,
    OnDemandFailed,
    OnDemandResult,
    pull_period,
)
from illumio_ops.services.reports import findings, flowsections, reads
from illumio_ops.services.reports.common import (
    DECISION_KEYS,
    host_key,
    host_keys,
    mode_word,
    severity_name,
    tr,
    utc_days_note,
)
from illumio_ops.services.reports.generate import (
    CoverageText,
    caveats_in_order,
    coverage_text,
    keeps_traffic,
    ondemand_lines,
    previous_period,
    traffic_covered,
)
from illumio_ops.services.reports.new_connections import NewCounts, count_new
from illumio_ops.services.reports.registry import BuildInput, specs
from illumio_ops.services.reports.render_html import fmt_time
from illumio_ops.services.reports.ven_status import (
    _BUCKET_KEYS,
    _KPI_KEYS,
    MODES,
    read_fleet,
    ven_findings,
)
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store import alerts as alert_store
from illumio_ops.store.flowdb import binding, workloads
from illumio_ops.store.flowdb.db import db_day

TOP_HOSTS = 5  # the hosts with the most alerts that are listed
PROVISION_USERS = 3  # eventsource.audit_counts keeps an event type's first three users
DETAIL_MAX = 300  # characters of the PCE's own error the data notes keep; a longer one ends with an ellipsis
NEW_KINDS = ("new", "admin")
BUCKETS = ("online", "lost_24h", "lost_48h", "long_offline", "unknown")
OUT_OF_CONTACT = ("lost_24h", "lost_48h", "long_offline")
_BUCKET_LABELS = {**{b: _KPI_KEYS[b] for b in BUCKETS if b in _KPI_KEYS}, "unknown": _KPI_KEYS["status_unknown"]}
_CATEGORY_KEYS = {"lateral": "alert_cat_lateral", "anomaly": "alert_cat_anomaly", "traffic": "alert_cat_traffic",
                  "event": "alert_cat_event", "system": "alert_cat_system"}
_NEW_LABELS = {"new": "rpt_new_kpi_new", "admin": "rpt_new_kpi_admin"}
_SEVERITIES = tuple(reversed(SEVERITY_ORDER))  # the most severe first


@dataclass(frozen=True)
class Traffic:
    """What the report read of the period's traffic."""
    totals: FlowTotals
    before: FlowTotals | None  # the previous period's; None: it cannot be compared with
    new: NewCounts
    outcomes: list[RuleOutcome]  # the rules' outcomes; empty when the period holds no flow (they did not run)
    coverage: CoverageText
    notes: tuple[str, ...] = ()  # the data notes of a pull
    # False: a pull whose first flow is later than the previous period's start — nothing says the PCE still keeps
    # that period, and no number of it is given
    reaches: bool = True
    # A pull whose records of the previous period span this many days (the PCE keeps traffic that old by the week):
    # a count of the period would be of whole weeks, and no number of it is given. 0: they are records of a day
    long_before: int = 0


@dataclass(frozen=True)
class NoTraffic:
    """The PCE could not give the period's traffic: `reason` is why, as the report says it wherever a traffic
    number or chapter would be; `detail` is the PCE's own error, said once, in the data notes."""
    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class AlertCounts:
    by_severity: dict[str, int]
    by_category: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.by_severity.values())

    @property
    def critical_high(self) -> int:
        return self.by_severity.get("critical", 0) + self.by_severity.get("high", 0)


def alerts_known_from(ctx: AppContext, pce: PceSettings, now: datetime) -> datetime | None:
    """From when on this install's alert records of this PCE are whole: a count over a period that starts before it
    counts less than happened. The later of two times —
    - since when alerts have been evaluated for this PCE: when the flow store was bound to it
      (store/flowdb/binding.py bound_at), or the oldest alert of this PCE still kept when that is earlier (the binding
      was renewed since: the same PCE at a new address);
    - what the retention still keeps: alerts.retention_days back from now (services/alerts/retention.py deletes the
      older ones; 0 keeps them forever).
    None when neither a binding nor an alert says since when: no period can be said to be whole."""
    with ctx.db() as conn:
        first = alert_store.first_fired_at(conn, pce_url=pce.url, org_id=pce.org_id)
    with ctx.flows().connect() as conn:
        bound = binding.current(conn)
    same = bound is not None and (normalize_target(bound.pce_url, bound.org_id)
                                  == normalize_target(pce.url, pce.org_id))
    since = min((x for x in (first, bound.bound_at if bound is not None and same else None) if x is not None),
                default=None)
    if since is None:
        return None
    days = ctx.settings.current().alerts.retention_days
    return max(since, now - timedelta(days=days)) if days else since


def read_alerts(ctx: AppContext, pce: PceSettings, start: datetime, end: datetime) -> AlertCounts:
    with ctx.db() as conn:
        by_severity = alert_store.period_counts(conn, pce_url=pce.url, org_id=pce.org_id, since=start, until=end)
        by_category = alert_store.counts_by_category(conn, pce_url=pce.url, org_id=pce.org_id, since=start, until=end)
    by_severity.pop("grouped", None)  # alerts marked as known, across the severities: not one more severity
    return AlertCounts(by_severity=by_severity, by_category=by_category)


def _read_traffic(inp: BuildInput, ctx: AppContext, prev_start: datetime, pulled: OnDemandResult | None) -> Traffic:
    """The period's traffic from `ctx`'s store: the install's, or the one pulled from the PCE (`pulled`)."""
    spec = FilterSpec(start=inp.start, end=inp.end)
    totals = flow_totals(ctx, spec)
    # A pulled store counts its whole range as collected: the previous period is known only when the PCE returned a
    # flow from before it started (it still keeps that far back).
    reaches = pulled is None or (pulled.earliest is not None and pulled.earliest <= prev_start)
    # ... and only when the PCE keeps that period by the day: records of a week would count the week (flowsource)
    longest = longest_record_days(ctx, prev_start, inp.start) if pulled is not None and reaches else 0
    long_before = longest if longest > LONG_RECORD_DAYS else 0
    before = (flow_totals(ctx, spec.model_copy(update={"start": prev_start, "end": inp.start}))
              if reaches and not long_before and traffic_covered(ctx, prev_start, inp.start, now=inp.now, flows=True)
              else None)
    lc = load_lateral_context(ctx, now=inp.now)
    with reads.reading(ctx) as conn:
        new = count_new(ctx, conn, lc, start=inp.start, end=inp.end, tz=inp.tz, now=inp.now, lang=inp.lang,
                        kinds=NEW_KINDS)
    if not reaches or long_before:
        new = dataclasses.replace(new, before=dict.fromkeys(NEW_KINDS), prev_known=False)
    outcomes = (findings.run_rules(ctx, spec, ctx.settings.current().reports.rule_thresholds, inp.lang, now=inp.now)
                if totals.flows else [])
    return Traffic(totals=totals, before=before, new=new, outcomes=outcomes,
                   coverage=coverage_text(ctx, inp.start, inp.end, inp.lang, now=inp.now, tz=inp.tz, flows=True),
                   notes=(*(ondemand_lines(pulled, inp.start, inp.end, inp.lang, inp.tz) if pulled is not None else ()),
                          *utc_days_note(inp.start, inp.end, inp.lang)),
                   reaches=reaches, long_before=long_before)


def read_traffic(inp: BuildInput, base: AppContext, prev_start: datetime) -> Traffic | NoTraffic:
    """The period's traffic: from the install's store when it keeps the period, else from one pull of the PCE that
    reaches back over the previous period and the baseline the new connections are told by (the lead, and the step
    run on the pulled store, of the new connections report). Only what the PCE could not give is a NoTraffic; a PCE
    switched meanwhile raises, as in every report."""
    if keeps_traffic(base, inp.start, inp.now):
        return _read_traffic(inp, base, prev_start, None)
    settings = base.settings.current()
    baseline = specs()[ReportType.NEW_CONNECTIONS]
    lead = baseline.ondemand_lead(settings) if baseline.ondemand_lead else timedelta(0)
    try:
        with pull_period(base, start=min(prev_start, inp.start - lead), end=inp.end, now=inp.now) as res:
            if res.unread_from is not None and res.unread_from <= inp.start:  # read oldest first: the period is unread
                return NoTraffic(tr(inp.lang, "rpt_wk_reason_capped", n=f"{ONDEMAND_MAX_ROWS:,}"))
            if res.earliest is None:
                # Not one flow in the whole pull, the baseline's month included: nothing says the PCE keeps traffic
                # that old, so the period is not said to hold none. (A pull that brought older flows and none of the
                # period is a period without traffic, and is read as one below.)
                return NoTraffic(tr(inp.lang, "rpt_wk_reason_none"))
            if baseline.ondemand_prepare is not None:
                baseline.ondemand_prepare(res.ctx, inp.now)
            got = _read_traffic(inp, res.ctx, prev_start, res)
    except OnDemandFailed as exc:
        said = str(exc)
        return NoTraffic(tr(inp.lang, "rpt_wk_reason_failed"),
                         detail=said if len(said) <= DETAIL_MAX else said[:DETAIL_MAX] + "…")
    return got


def build_weekly_overview(inp: BuildInput) -> ReportDocument:
    lang, now = inp.lang, inp.now
    # The install: its alerts, inventory and kept traffic. inp.ctx is the store events are read from — the install's
    # own, or the archive's when the period starts before the events kept (the generator then names the install).
    base = inp.install or inp.ctx
    pce = base.settings.current().pce
    prev_start, _ = previous_period(inp.start, inp.end, inp.tz)

    def t(msg: str, /, **params: object) -> str:
        return tr(lang, msg, **params)

    def see(*reports: str) -> TextBlock:
        """The sentence a chapter ends with: where its detail is."""
        titles = [t(r) for r in reports]
        return TextBlock(paragraphs=(t("rpt_wk_see_report", report=titles[0]) if len(titles) == 1
                                     else t("rpt_wk_see_reports", first=titles[0], second=titles[1]),))

    this, previous = Column(key="now", label=t("rpt_sec_col_this_period"), kind="number"), Column(
        key="before", label=t("rpt_wk_col_previous"), kind="number")

    # ── alerts ──────────────────────────────────────────────────────────────
    known_from = alerts_known_from(base, pce, now)
    alerts = read_alerts(base, pce, inp.start, inp.end)
    alerts_before = (read_alerts(base, pce, prev_start, inp.start)
                     if known_from is not None and prev_start >= known_from else None)
    partial = (t("rpt_wk_alerts_partial", since=fmt_time(known_from.isoformat(), inp.tz))
               if known_from is not None and inp.start < known_from else None)
    with base.db() as conn:
        alerted = alert_store.alerted_devices(conn, pce_url=pce.url, org_id=pce.org_id, since=inp.start, until=inp.end)
        hosts_since = alert_store.devices_recorded_since(conn, pce_url=pce.url, org_id=pce.org_id)
    top = alerted[:TOP_HOSTS]
    names = display_names(base, {r["key"] for r in top}, lang=lang)
    severity_table = TableBlock(
        title=t("rpt_wk_tbl_alerts_severity"),
        columns=(Column(key="severity", label=t("rpt_col_severity")), this, previous),
        rows=tuple((severity_name(lang, s.value), alerts.by_severity.get(s.value, 0),
                    alerts_before.by_severity.get(s.value, 0) if alerts_before else None) for s in _SEVERITIES),
        total_rows=len(_SEVERITIES), empty_text="")
    category_table = TableBlock(
        title=t("rpt_wk_tbl_alerts_category"),
        columns=(Column(key="category", label=t("rpt_col_category")), this, previous),
        rows=tuple((t(key), alerts.by_category[c], alerts_before.by_category[c] if alerts_before else None)
                   for c, key in _CATEGORY_KEYS.items()),
        total_rows=len(_CATEGORY_KEYS), empty_text="")
    hosts_table = TableBlock(
        title=t("rpt_wk_tbl_alert_hosts"),
        columns=(Column(key="host", label=t("rpt_col_host"), kind="host"),
                 Column(key="n", label=t("rpt_wk_col_alerts"), kind="number"),
                 Column(key="last", label=t("rpt_wk_col_latest_alert"), kind="time")),
        rows=tuple((names.get(r["key"], r["key"]), r["n"], r["last"]) for r in top), total_rows=len(alerted),
        empty_text=t("rpt_wk_alert_hosts_none"),
        limit_note=t("rpt_limit_top_n", n=TOP_HOSTS) if len(alerted) > len(top) else None,
        host_keys=host_keys(host=(host_key({}, r["key"]) for r in top)), host_section="alerts")
    # alerts raised before hosts were recorded with them name no host: the ranking cannot count those
    hosts_partial = (t("rpt_wk_alert_hosts_since", since=fmt_time(hosts_since.isoformat(), inp.tz))
                     if hosts_since is not None and hosts_since > inp.start else None)
    alert_words = (t("rpt_wk_alerts_total", n=f"{alerts.total:,}"), *((partial,) if partial else ()),
                   *(() if alerts_before is not None else (t("rpt_wk_alerts_no_previous"),)))
    alerts_section = Section(
        id="alerts", title=t("rpt_wk_sec_alerts"), intro=t("rpt_wk_alerts_intro"),
        blocks=(TextBlock(paragraphs=alert_words), severity_table, category_table, hosts_table,
                TextBlock(paragraphs=(*((hosts_partial,) if hosts_partial else ()), t("rpt_wk_see_alerts")))))

    # ── VENs ────────────────────────────────────────────────────────────────
    fleet = read_fleet(base, now)
    not_online = sum(fleet.counts[b] for b in OUT_OF_CONTACT)
    bucket_table = TableBlock(
        title=t("rpt_wk_tbl_ven_state"),
        columns=(Column(key="state", label=t("rpt_wk_col_state")),
                 Column(key="n", label=t("rpt_col_managed_hosts"), kind="number")),
        rows=tuple((t(_BUCKET_LABELS[b]), fleet.counts[b]) for b in BUCKETS), total_rows=len(BUCKETS),
        empty_text="")
    # Out of contact now, with the last heartbeat inside the period: the hosts that went quiet during it.
    lost = [w for w in fleet.offline() if w.last_heartbeat_at
            and inp.start <= datetime.fromisoformat(w.last_heartbeat_at) < inp.end]
    lost_table = TableBlock(
        title=t("rpt_wk_tbl_lost"),
        columns=(Column(key="host", label=t("rpt_col_host"), kind="host"),
                 Column(key="heartbeat", label=t("rpt_ven_col_heartbeat"), kind="time"),
                 Column(key="bucket", label=t("rpt_ven_col_bucket"))),
        rows=tuple((fleet.name[w.href], w.last_heartbeat_at, t(_BUCKET_KEYS[fleet.buckets[w.href]])) for w in lost),
        total_rows=len(lost), empty_text=t("rpt_wk_lost_none"),
        host_keys=host_keys(host=(w.href for w in lost)), host_section="status")
    # The modes of the previous period's last day, from that day's snapshot: only for a period that ends now (the
    # inventory is today's), as the security risk report compares them.
    ends_now = (now.astimezone(inp.tz).date() - inp.end.astimezone(inp.tz).date()).days <= 1
    modes_now = Counter(w.enforcement_mode if w.enforcement_mode in MODES else "unknown" for w in fleet.hosts)
    modes_before: workloads.ModeCounts | None = None
    if ends_now:
        with reads.reading(base) as conn:
            modes_before = workloads.mode_counts_on(conn, db_day(inp.start - timedelta(microseconds=1)))

    def mode_before(mode: str) -> int | None:
        if modes_before is None:
            return None
        if mode == "unknown":  # the managed hosts of that day the PCE gave no mode of these for
            return modes_before.hosts - sum(modes_before.modes.get(m, 0) for m in MODES)
        return modes_before.modes.get(mode, 0)
    mode_rows = [m for m in (*MODES, "unknown") if m != "unknown" or modes_now["unknown"] or mode_before("unknown")]
    modes_table = TableBlock(
        title=t("rpt_wk_tbl_modes"),
        columns=(Column(key="mode", label=t("rpt_ven_col_mode")),
                 Column(key="now", label=t("rpt_wk_col_hosts_now"), kind="number"),
                 Column(key="before", label=t("rpt_wk_col_hosts_before"), kind="number")),
        rows=tuple((mode_word(lang, m) if m != "unknown" else t("rpt_ven_unknown"), modes_now[m], mode_before(m))
                   for m in mode_rows),
        total_rows=len(mode_rows), empty_text="")
    ven_words = (t("rpt_wk_vens_now_only"), *(() if modes_before is not None else (t("rpt_wk_modes_no_previous"),)))
    vens_section = Section(
        id="vens", title=t("rpt_wk_sec_vens"), intro=t("rpt_wk_vens_intro"),
        blocks=(bucket_table, lost_table, modes_table, TextBlock(paragraphs=ven_words),
                see("rpt_title_ven_status")))

    # ── traffic, new connections and the rules ──────────────────────────────
    traffic = read_traffic(inp, base, prev_start)
    with base.flows().connect() as conn:  # the install's store is still this PCE's after a pull that took minutes
        require_same_pce(conn, pce)
    flow_blocks: tuple[Block, ...]
    new_blocks: tuple[Block, ...]
    rule_findings: tuple[Finding, ...] = ()
    caveats: tuple[str, ...] = ()
    if isinstance(traffic, NoTraffic):
        no_flows = t("rpt_wk_no_flows", reason=traffic.reason)
        flow_blocks = new_blocks = (TextBlock(paragraphs=(no_flows,)),)
        pb: int | None = None
        pb_before: int | None = None
        pb_note: str | None = no_flows
        new_now: dict[str, int | None] = dict.fromkeys(NEW_KINDS)
        new_before: dict[str, int | None] = dict.fromkeys(NEW_KINDS)
        new_note: str | None = no_flows
        traffic_notes: tuple[str, ...] = (no_flows, *((t("rpt_wk_pce_error", detail=traffic.detail),)
                                                       if traffic.detail else ()))
        rules_section = findings.unevaluated_section(
            [], lang, title=t("rpt_rules_sec_unevaluated"), intro=t("rpt_trf_findings_intro"),
            table_title=t("rpt_rules_tbl_unevaluated"), evaluated=False, not_run_key="rpt_wk_rules_no_flows")
    else:
        def no_previous(key: str) -> str:
            """Why a chapter gives no previous period: the PCE's reason when the traffic came from it."""
            if not traffic.reaches:
                return t("rpt_wk_no_previous_pce")
            return t("rpt_wk_no_previous_long", n=traffic.long_before) if traffic.long_before else t(key)

        totals = traffic.totals
        saw = flowsections.seen(totals)
        by_before = {d.decision: d for d in traffic.before.decided()} if traffic.before is not None else None
        decided = totals.decided() if totals.flows else []
        decisions_table = TableBlock(
            title=t("rpt_wk_tbl_decisions"),
            columns=(Column(key="decision", label=t("rpt_col_decision")),
                     Column(key="now", label=t("rpt_wk_col_connections_now"), kind="number"),
                     Column(key="before", label=t("rpt_wk_col_connections_before"), kind="number")),
            rows=tuple((t(DECISION_KEYS[d.decision]), d.connections,
                        by_before[d.decision].connections if by_before is not None else None) for d in decided),
            total_rows=len(decided), empty_text=t("rpt_no_flows"))
        undecided = totals.undecided
        flow_words = ((t("rpt_wk_undecided", flows=f"{undecided.flows:,}", connections=f"{undecided.connections:,}",
                         pct_flows=flowsections.share_text(lang, undecided.flows, saw.flows),
                         pct_connections=flowsections.share_text(lang, undecided.connections, saw.connections),
                         report=t("rpt_title_traffic")),) if undecided.flows
                      else (t("rpt_wk_all_decided"),) if totals.flows else ())
        flow_blocks = (decisions_table,
                       TextBlock(paragraphs=(*flow_words,
                                             *(() if traffic.before is not None or not totals.flows
                                               else (no_previous("rpt_wk_flows_no_previous"),)))),
                       see("rpt_title_traffic", "rpt_title_security_risk"))
        by_now = {d.decision: d for d in decided}
        pb = by_now["potentially_blocked"].connections if totals.flows else None
        pb_before = by_before["potentially_blocked"].connections if by_before is not None and totals.flows else None
        pb_note = None if totals.flows else t("rpt_no_flows")
        new = traffic.new
        new_now, new_before, new_note = dict(new.now), dict(new.before), new.note
        new_table = TableBlock(
            title=t("rpt_wk_tbl_new"),
            columns=(Column(key="kind", label=t("rpt_wk_col_new_kind")), this, previous),
            rows=tuple((t(_NEW_LABELS[k]), new.now[k], new.before[k]) for k in NEW_KINDS),
            total_rows=len(NEW_KINDS), empty_text="")
        new_blocks = (new_table,
                      TextBlock(paragraphs=tuple(x for x in (
                          new.partial, new.accumulating,
                          None if new.prev_known else no_previous("rpt_wk_new_no_previous")) if x)),
                      see("rpt_title_new_connections"))
        rule_findings = findings.as_findings(traffic.outcomes, lang)
        rules_section = findings.unevaluated_section(
            traffic.outcomes, lang, title=t("rpt_rules_sec_unevaluated"), intro=t("rpt_trf_findings_intro"),
            table_title=t("rpt_rules_tbl_unevaluated"), evaluated=bool(totals.flows))
        caveats = caveats_in_order(gaps=traffic.coverage.caveats, undecided=flowsections.undecided_caveat(
            lang, saw, elsewhere=t("rpt_title_traffic")))
        traffic_notes = (*traffic.coverage.lines, *traffic.notes)
    flows_section = Section(id="flows", title=t("rpt_wk_sec_flows"), intro=t("rpt_wk_flows_intro"),
                            blocks=tuple(b for b in flow_blocks if not isinstance(b, TextBlock) or b.paragraphs))
    new_section = Section(id="new_connections", title=t("rpt_wk_sec_new"), intro=t("rpt_wk_new_intro"),
                          blocks=tuple(b for b in new_blocks if not isinstance(b, TextBlock) or b.paragraphs))

    # ── policy ──────────────────────────────────────────────────────────────
    events = audit_counts(inp.ctx, start=inp.start, end=inp.end, top=0, now=now)
    events_prev = audit_counts(inp.ctx, start=prev_start, end=inp.start, top=0, now=now)
    # as the audit report: a period with no event at all has no count to give, and the previous one is compared
    # with only when its events were all collected
    provisions = events.by_type.get(PROVISION, 0) if events.total else None
    provisions_before = events_prev.by_type.get(PROVISION, 0) if not events_prev.coverage.gaps else None
    by_user = events.type_users.get(PROVISION, [])
    users_table = TableBlock(
        title=t("rpt_wk_tbl_provision_users", n=PROVISION_USERS),
        columns=(Column(key="user", label=t("rpt_col_user")),
                 Column(key="n", label=t("rpt_wk_col_provisions"), kind="number")),
        rows=tuple((name, n) for name, n in by_user), total_rows=len(by_user),
        empty_text=t("rpt_aud_none_provisions") if not provisions else t("rpt_aud_no_user"))
    policy_section = Section(
        id="policy", title=t("rpt_wk_sec_policy"), intro=t("rpt_wk_policy_intro"),
        blocks=(TextBlock(paragraphs=(t("rpt_wk_provisions", n=f"{provisions:,}") if provisions is not None
                                      else t("rpt_aud_no_events"),)),
                users_table, see("rpt_title_audit", "rpt_title_policy_diff")))

    # ── key numbers ─────────────────────────────────────────────────────────
    kpis = (
        Kpi(key="new_alerts", label=t("rpt_wk_kpi_new_alerts"), value=alerts.total,
            previous=alerts_before.total if alerts_before else None, better="lower", note=partial),
        Kpi(key="vens_not_online", label=t("rpt_wk_kpi_vens_not_online"), value=not_online, previous=None,
            better="lower", note=t("rpt_wk_vens_now_only")),
        Kpi(key="pb_connections", label=t("rpt_wk_kpi_pb_connections"), value=pb, previous=pb_before, better="lower",
            note=pb_note),
        Kpi(key="critical_high_alerts", label=t("rpt_wk_kpi_critical_high_alerts"), value=alerts.critical_high,
            previous=alerts_before.critical_high if alerts_before else None, better="lower", note=partial),
        Kpi(key="new_connections", label=t("rpt_new_kpi_new"), value=new_now["new"], previous=new_before["new"],
            better="lower", note=new_note),
        Kpi(key="provisions", label=t("rpt_aud_kpi_provisions"), value=provisions, previous=provisions_before,
            better="neutral", note=None if provisions is not None else t("rpt_aud_no_events")))

    latest = max((w.fetched_at for w in fleet.hosts), default=None)
    quality = (
        *traffic_notes,
        t("rpt_ven_quality_inventory", at=fmt_time(latest, inp.tz)) if latest else t("rpt_ven_quality_no_inventory"),
        t("rpt_aud_quality_gaps", n=len(events.coverage.gaps)) if events.coverage.gaps else t("rpt_aud_quality_whole"),
        *((partial,) if partial else ()), *((hosts_partial,) if hosts_partial else ()))
    # The VENs' findings are the VEN status report's, word for word; the tables they send the reader to are in that
    # report, so each says so here.
    in_report = t("rpt_wk_tables_in_report", report=t("rpt_title_ven_status"))
    of_vens = [f.model_copy(update={"action": f"{f.action} {in_report}"}) for f in ven_findings(fleet, lang)]
    # the rules' findings and the VENs', the most severe first (the rules' before the VENs' of the same severity)
    found = sorted((*rule_findings, *of_vens), key=lambda f: -SEVERITY_ORDER.index(f.severity))
    return ReportDocument(
        report_type=inp.params.report_type, lang=lang, title=t("rpt_title_weekly_overview"), period_start=inp.start,
        period_end=inp.end, generated_at=now, pce_label=inp.pce_label, kpis=kpis, findings=tuple(found),
        caveats=caveats, data_quality=quality,
        sections=(alerts_section, vens_section, flows_section, new_section, policy_section, *rules_section))
