"""The weekly overview (UI redesign spec §9.2): five chapters whose every number is the one the topic report gives
for the same data; the previous period only where its records are whole; and, when the install keeps no traffic
and the PCE cannot give it, a report that is still made — two chapters and the rules say why, the rest stands."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.conclusion import CONCLUSIONS, conclusion
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import (
    AlertRuleType,
    DataOrigin,
    Language,
    ReportStatus,
    ReportType,
    Severity,
)
from illumio_ops.i18n import translate
from illumio_ops.services import ondemand
from illumio_ops.services.flowsource import flow_totals
from illumio_ops.services.reports import generate, views, weekly_overview
from illumio_ops.services.reports.finish import finish
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_email import render_email
from illumio_ops.services.reports.render_html import to_do
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb import binding
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import PCE, configured_ctx
from tests.services.reports import test_ondemand_reports as od
from tests.services.reports import test_report_i18n as rich
from tests.services.reports.dom import dom
from tests.services.reports.test_ven_status import _inventory, host
from tests.store.test_alert_store import trig

NOW, START, END = rich.NOW, rich.START, rich.END
PREV = START - timedelta(days=7)
WK = ReportType.WEEKLY_OVERVIEW
MICRO = timedelta(microseconds=1)


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    yield from rich.ctx.__wrapped__(tmp_path_factory)


def _build(ctx, rt=WK, lang=Language.EN, *, start=START, end=END, now=NOW):
    return specs()[rt].build(BuildInput(ctx=ctx, params=ReportParams(report_type=rt), start=start, end=end,
                                        lang=lang, tz=UTC, now=now, pce_label="pce"))


def _kpi(doc, key):
    return next(k for k in doc.kpis if k.key == key)


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, n=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][n]


def alert(ctx, at, *, severity=Severity.HIGH, rule_type=AlertRuleType.SYSTEM, devices=(), detector=None):
    t = replace(trig(f"s{at.isoformat()}"), severity=severity, rule_type=rule_type, devices=tuple(devices),
                params={"detector": detector} if detector else {"free_bytes": 1})
    with ctx.db() as conn:
        alert_store.insert_alert(conn, pce_url=PCE["url"], org_id=PCE["org_id"], rule_name="r", pack_key=None,
                                 trigger=t, at=at, channels=["line"], hold=None)
        conn.commit()


# ── full mode: the chapters, and every number against its topic report ───────────────────────────────────────

def test_the_five_chapters_come_in_order_and_none_is_folded_away(full):
    doc = finish(_build(full))
    assert [s.id for s in doc.sections][:5] == ["alerts", "vens", "flows", "new_connections", "policy"]
    assert doc.title == "Weekly overview" and _build(full, lang=Language.ZH_TW).title == "每週總覽"
    # each chapter ends with the sentence naming where its detail is
    for sid, named in (("vens", "VEN status"), ("flows", "Traffic"), ("new_connections", "New connections"),
                       ("policy", "Audit"), ("alerts", "Alerts page")):
        last = _section(doc, sid).blocks[-1]
        assert isinstance(last, TextBlock) and named in last.paragraphs[-1], sid


def test_the_key_numbers_are_the_six_in_order_with_the_lead_three_first(full):
    doc = finish(_build(full))
    assert [k.key for k in doc.kpis] == ["new_alerts", "vens_not_online", "pb_connections", "critical_high_alerts",
                                         "new_connections", "provisions"]
    assert {k.key: k.better for k in doc.kpis}["provisions"] == "neutral"


def test_alert_numbers_are_the_alert_stores_counts_for_the_period(full):
    doc = _build(full)
    with full.db() as conn:
        def count(since, until, **kw):
            return alert_store.count_alerts(conn, pce_url=PCE["url"], org_id=PCE["org_id"], since=since, until=until,
                                            **kw)
        total, before = count(START, END), count(PREV, START)
        crit_high = count(START, END, severity="critical") + count(START, END, severity="high")
    assert total > 0 and before > 0 and before != total, "the sample no longer tells the two periods apart"
    assert (_kpi(doc, "new_alerts").value, _kpi(doc, "new_alerts").previous) == (total, before)
    assert _kpi(doc, "critical_high_alerts").value == crit_high
    by_severity, by_category = _table(doc, "alerts", 0), _table(doc, "alerts", 1)
    assert sum(r[1] for r in by_severity.rows) == total == sum(r[1] for r in by_category.rows)
    assert sum(r[2] for r in by_severity.rows) == before == sum(r[2] for r in by_category.rows)


def test_the_hosts_with_the_most_alerts_are_the_stores_ranking(full):
    doc = _build(full)
    with full.db() as conn:
        ranked = alert_store.alerted_devices(conn, pce_url=PCE["url"], org_id=PCE["org_id"], since=START, until=END)
    hosts = _table(doc, "alerts", 2)
    assert ranked and [(r[1], r[2]) for r in hosts.rows] == [(r["n"], r["last"]) for r in ranked[:5]]
    assert hosts.host_keys["host"] == tuple(r["key"] for r in ranked[:5]) and hosts.host_section == "alerts"
    assert hosts.total_rows == len(ranked)


def test_ven_numbers_are_the_ven_status_reports(full):
    doc, ven = _build(full), _build(full, ReportType.VEN_STATUS)
    out = sum(_kpi(ven, k).value for k in ("lost_24h", "lost_48h", "long_offline"))
    assert out > 0 and _kpi(doc, "vens_not_online").value == out
    assert _kpi(doc, "vens_not_online").previous is None  # the inventory keeps no history of who was online
    states = {r[0]: r[1] for r in _table(doc, "vens", 0).rows}
    for key, label in (("online", "Online"), ("lost_24h", "Quiet under 24 hours"), ("lost_48h", "Quiet 24–48 hours"),
                       ("long_offline", "Quiet over 48 hours"), ("status_unknown", "Status not collected")):
        assert states[label] == _kpi(ven, key).value, key
    assert sum(states.values()) == _kpi(ven, "managed").value
    # the same findings, from the same function
    ven_titles = {f.title for f in ven.findings}
    assert ven_titles and ven_titles <= {f.title for f in doc.findings}


def test_flow_numbers_are_flow_totals_and_the_rules_are_the_security_risk_reports(full):
    doc, risk = _build(full), _build(full, ReportType.SECURITY_RISK)
    totals = flow_totals(full, FilterSpec(start=START, end=END))
    by = {d.decision: d.connections for d in totals.decided()}
    assert by["potentially_blocked"] > 0 and _kpi(doc, "pb_connections").value == by["potentially_blocked"]
    rows = _table(doc, "flows").rows
    assert [r[1] for r in rows] == [by["allowed"], by["potentially_blocked"], by["blocked"]]
    assert rows[1][0] == translate(Language.EN, "term_decision_potentially_blocked", {})
    rule_titles = [f.title for f in risk.findings]
    assert rule_titles and [f.title for f in doc.findings if f.title in rule_titles] == sorted(
        rule_titles, key=lambda title: [f.title for f in doc.findings].index(title))
    assert set(rule_titles) <= {f.title for f in doc.findings}


def test_new_connection_numbers_are_the_new_connections_reports(full):
    doc, new = _build(full), _build(full, ReportType.NEW_CONNECTIONS)
    assert _kpi(new, "new").value > 0
    assert (_kpi(doc, "new_connections").value, _kpi(doc, "new_connections").previous) == (
        _kpi(new, "new").value, _kpi(new, "new").previous)
    rows = _table(doc, "new_connections").rows
    assert [r[1] for r in rows] == [_kpi(new, "new").value, _kpi(new, "admin").value]


def test_provisions_are_the_audit_reports(full):
    doc, audit = _build(full), _build(full, ReportType.AUDIT)
    assert _kpi(audit, "policy_provisions").value > 0
    assert (_kpi(doc, "provisions").value, _kpi(doc, "provisions").previous) == (
        _kpi(audit, "policy_provisions").value, _kpi(audit, "policy_provisions").previous)
    assert _table(doc, "policy").rows == (("alice", _kpi(audit, "policy_provisions").value),)


def test_the_opening_sentence_is_the_full_form(full):
    doc = finish(_build(full))
    said = conclusion(doc, lambda key, p: translate(Language.EN, key, p), tz=UTC)
    assert said == translate(Language.EN, "rpt_conclusion_weekly_overview",
                             {k: f"{_kpi(doc, k).value:,}" for k in CONCLUSIONS[WK][0][0]})
    assert "Potentially Blocked connections: " in said


# ── the previous period of the alerts ────────────────────────────────────────────────────────────────────────

def test_an_alert_on_a_boundary_belongs_to_the_period_that_starts_there(tmp_path):
    ctx = configured_ctx(tmp_path)
    for at in (PREV - timedelta(days=3),  # before both: the records reach back past the previous period
               PREV, START - MICRO,  # the previous period's first and last instant
               START, END - MICRO,  # this period's
               END):  # after it: in neither
        alert(ctx, at)
    doc = _build(ctx)
    assert (_kpi(doc, "new_alerts").value, _kpi(doc, "new_alerts").previous) == (2, 2)


def test_no_previous_alert_count_when_the_records_do_not_reach_back_over_it(tmp_path):
    """Nothing says alerts were evaluated before this period: the previous count is not 0, it is not given."""
    ctx = configured_ctx(tmp_path)
    alert(ctx, START + timedelta(days=1))
    with ctx.flows().connect() as conn:
        assert binding.current(conn) is None
    doc = _build(ctx)
    assert (_kpi(doc, "new_alerts").value, _kpi(doc, "new_alerts").previous) == (1, None)
    assert _kpi(doc, "critical_high_alerts").previous is None
    assert [c.key for c in finish(doc).tables()[0][1].columns] == ["severity", "now"]  # no column of blanks
    assert "previous period is not wholly within" in " ".join(_section(doc, "alerts").blocks[0].paragraphs)


def test_the_binding_says_since_when_alerts_were_evaluated(tmp_path):
    """Bound to the PCE before the previous period began and no alert since: 0 is then a count, and is given."""
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        binding.bind(conn, PCE["url"], PCE["org_id"], PREV - timedelta(days=1))
    alert(ctx, START + timedelta(days=1))
    assert _kpi(_build(ctx), "new_alerts").previous == 0
    other = configured_ctx(tmp_path / "late")
    with other.flows().connect() as conn:
        binding.bind(conn, PCE["url"], PCE["org_id"], PREV + timedelta(days=1))  # during the previous period
    alert(other, START + timedelta(days=1))
    assert _kpi(_build(other), "new_alerts").previous is None


def test_retention_shorter_than_the_periods_takes_the_previous_count_away_and_marks_this_one(tmp_path):
    ctx = configured_ctx(tmp_path)
    alert(ctx, PREV - timedelta(days=3))
    alert(ctx, START + timedelta(days=4))
    assert _kpi(_build(ctx), "new_alerts").previous == 0
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"].update(retention_days=10))
    doc = _build(ctx)  # kept from 10-17 01:00: after the previous period's start, before this one's
    assert _kpi(doc, "new_alerts").previous is None and _kpi(doc, "new_alerts").note is None
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"].update(retention_days=5))
    doc = _build(ctx)  # kept from 10-22 01:00: inside this period
    assert _kpi(doc, "new_alerts").previous is None
    assert "complete from 2026-10-22 01:00" in _kpi(doc, "new_alerts").note
    assert _kpi(doc, "new_alerts").note in doc.data_quality


# ── VENs that went quiet in the period ───────────────────────────────────────────────────────────────────────

def test_only_a_ven_whose_last_heartbeat_is_in_the_period_is_listed_as_lost_in_it(tmp_path):
    ctx = configured_ctx(tmp_path)
    _inventory(ctx, [host("recent", online=0, hb=timedelta(days=3)), host("old", online=0, hb=timedelta(days=20)),
                     host("fine")])
    doc = _build(ctx)
    lost = _table(doc, "vens", 1)
    assert [r[0] for r in lost.rows] == ["recent"] and lost.rows[0][2] == "Over 48 hours"
    assert lost.host_keys == {"host": ("/orgs/1/workloads/recent",)} and lost.host_section == "status"
    assert _kpi(doc, "vens_not_online").value == 2  # both are out of contact now


def test_modes_are_compared_with_the_snapshot_of_the_previous_periods_last_day(tmp_path):
    ctx = configured_ctx(tmp_path)
    _inventory(ctx, [host("a", mode="full"), host("b", mode="visibility_only")])
    doc = _build(ctx)
    assert all(r[2] is None for r in _table(doc, "vens", 2).rows)
    assert [c.key for c in finish(doc).sections[1].blocks[2].columns] == ["mode", "now"]  # no column of blanks
    assert "no host snapshot" in " ".join(_section(doc, "vens").blocks[3].paragraphs)
    with ctx.flows().connect() as conn:
        conn.execute("INSERT INTO workload_snapshot_daily (day, href, enforcement_mode, managed) VALUES "
                     "('2026-10-19', '/orgs/1/workloads/a', 'visibility_only', 1), "
                     "('2026-10-19', '/orgs/1/workloads/b', 'visibility_only', 1)")
        conn.commit()
    rows = {r[0]: (r[1], r[2]) for r in _table(_build(ctx), "vens", 2).rows}
    assert rows[translate(Language.EN, "term_mode_full", {})] == (1, 0)
    assert rows[translate(Language.EN, "term_mode_visibility_only", {})] == (1, 2)


# ── lightweight mode ─────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pce(monkeypatch):
    fake = od.FakePce(od.ROWS)
    monkeypatch.setattr(ondemand, "run_traffic_query", fake)
    return fake


def _light(tmp_path):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    _inventory(ctx, [host("recent", online=0, hb=timedelta(days=3)), host("fine")])
    alert(ctx, PREV - timedelta(days=3))
    alert(ctx, START + timedelta(days=1), devices=())
    with ctx.flows().connect() as conn:
        from illumio_ops.store.flowdb.events import upsert_events
        from tests.services.reports.test_audit import event as audit_event
        upsert_events(conn, [audit_event("sec_policy.create", START + timedelta(days=2), user="alice")],
                      origin=DataOrigin.INGEST, now=NOW)
        conn.commit()
    return ctx


def _run(ctx, lang=Language.EN, **kw):
    rid = generate.enqueue(ctx, ReportParams(report_type=WK, lang=lang, **kw), trigger="manual", schedule_id=None,
                           now=NOW)
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        return store.get(conn, rid)


def _html(ctx, row):
    return next((ctx.paths.reports_dir / str(row.id) / f).read_text() for f in row.files if f.endswith(".html"))


def test_lightweight_pulls_once_and_all_five_chapters_have_content(tmp_path, pce):
    ctx = _light(tmp_path)
    row = _run(ctx)
    assert row.status is ReportStatus.DONE, (row.error_key, row.error_detail)
    starts = [p["start_date"] for p in pce.payloads]
    # one pull: it starts the baseline's 30 days before the period (further back than the previous period) and
    # asks for no window twice
    assert datetime.fromisoformat(min(starts)) == row.period_start - timedelta(days=30)
    assert len(starts) == len(set(starts))
    assert list(ondemand.ondemand_dir(ctx.paths).iterdir()) == []
    pb = sum(r["num_connections"] for r in od.ROWS if r["policy_decision"] == "potentially_blocked")
    values = {k["key"]: k["value"] for k in row.kpis}
    assert values["pb_connections"] == pb and values["new_connections"] == len(od.ROWS)
    assert values["new_alerts"] == 1 and values["vens_not_online"] == 1 and values["provisions"] == 1
    assert "Potentially Blocked connections: " in row.conclusion
    page = dom(_html(ctx, row))
    for sid in ("alerts", "vens", "flows", "new_connections", "policy"):
        assert page.one("id", sid).find("table"), sid
    assert "queried from the PCE when the report was made" in page.text()
    assert "could not be had from the PCE" not in page.text()


def test_when_the_pce_cannot_give_the_traffic_the_report_is_still_made(tmp_path, pce):
    pce.fail = True
    ctx = _light(tmp_path)
    row = _run(ctx)
    assert row.status is ReportStatus.DONE, (row.error_key, row.error_detail)
    values = {k["key"]: k["value"] for k in row.kpis}
    assert values["pb_connections"] is None and values["new_connections"] is None
    assert values["new_alerts"] == 1 and values["vens_not_online"] == 1 and values["provisions"] == 1
    # the second sentence form: no traffic number, and no "could not be computed"
    assert row.conclusion == "Alerts this period: 1; VENs out of contact: 1; policy provisions: 1."
    page = dom(_html(ctx, row))
    text = page.text()
    assert "The traffic of this period could not be had from the PCE: the PCE did not answer the query" in text
    assert "no traffic to evaluate the rules" not in text and "No traffic in this period" not in text
    assert "Nothing in this report needs action" not in text
    top = page.one("data-role", "top-actions")
    assert "The traffic could not be had from the PCE, so the rules were not evaluated. See “" in top.text()
    assert [a.attrs["href"] for a in top.find("a")][-1] == "#findings" and len(page.find_attr("id", "findings")) == 1
    for sid in ("flows", "new_connections"):  # one sentence each, and no table
        assert not page.one("id", sid).find("table"), sid
        assert "could not be had from the PCE" in page.one("id", sid).text(), sid
    for sid in ("alerts", "vens", "policy"):
        assert page.one("id", sid).find("table"), sid


def test_the_failed_pull_as_a_document(tmp_path, pce):
    """The same case read from the document: what each output renders."""
    pce.fail = True
    ctx = _light(tmp_path)
    doc = finish(_build(ctx))
    assert [s.id for s in doc.sections] == ["alerts", "vens", "flows", "new_connections", "policy", "findings"]
    for sid in ("flows", "new_connections"):
        assert [type(b) for b in _section(doc, sid).blocks] == [TextBlock]
    for key in ("pb_connections", "new_connections"):
        assert _kpi(doc, key).value is None and "could not be had from the PCE" in _kpi(doc, key).note
    assert any("could not be had from the PCE" in line for line in doc.data_quality)
    assert [f.action_code for f in doc.findings] == ["ven_offline"]  # the VENs' finding stands
    todo = to_do(doc)
    assert todo.nothing is False and todo.top and "so the rules were not evaluated. See “Rules not evaluated”" in todo.held
    assert "could not be had from the PCE, so the rules were not evaluated" in render_email(doc, tz=UTC).text
    zh = finish(_build(ctx, lang=Language.ZH_TW))
    assert to_do(zh).held == "流量向 PCE 取不到，所以規則沒有評估。見〈沒有評估的規則〉。"
    assert _section(zh, "flows").blocks[0].paragraphs == ("這段期間的流量向 PCE 取不到：PCE 沒有回答查詢。",)
    # the PCE's own error is said once, in the data notes
    assert sum("traffic query poll failed" in line for line in doc.data_quality) == 1
    assert "poll failed" not in " ".join(k.note or "" for k in doc.kpis)


def test_a_pce_that_returns_nothing_at_all_is_said_as_not_had_not_as_no_traffic(tmp_path, pce):
    """A period older than what the PCE keeps comes back empty, the month before it too: that is not "0 connections
    would be blocked"."""
    pce.rows = []
    doc = finish(_build(_light(tmp_path)))
    assert _kpi(doc, "pb_connections").value is None and _kpi(doc, "new_connections").value is None
    assert "the PCE returned no flow for this period" in _section(doc, "flows").blocks[0].paragraphs[0]
    assert "findings" in [s.id for s in doc.sections] and to_do(doc).nothing is False
    assert "so the rules were not evaluated" in to_do(doc).held


def test_a_pull_with_older_flows_and_none_in_the_period_is_a_period_without_traffic(tmp_path, pce):
    """The PCE answered and still keeps traffic older than the period: the period holds none, and the report says
    that — not that the PCE could not give it."""
    pce.rows = [od.raw(1, day=1)]  # in the baseline's month, before the previous period
    doc = finish(_build(_light(tmp_path)))
    assert _kpi(doc, "pb_connections").value is None and _kpi(doc, "pb_connections").note == "No traffic in this period."
    assert _kpi(doc, "new_connections").value == 0
    assert "could not be had" not in " ".join(doc.data_quality)
    assert to_do(doc).held.startswith("This period has no traffic to evaluate the rules on")


def test_a_long_pce_error_is_cut_with_a_mark(tmp_path, pce, monkeypatch):
    pce.fail = True
    monkeypatch.setattr(weekly_overview, "DETAIL_MAX", 20)
    doc = _build(_light(tmp_path))
    note = next(line for line in doc.data_quality if line.startswith("What the PCE query returned"))
    assert note.endswith("…") and len(note) < 60


def test_a_pull_that_stops_at_its_row_limit_before_the_period_is_said_as_not_had(tmp_path, pce, monkeypatch):
    monkeypatch.setattr(ondemand, "ONDEMAND_MAX_ROWS", 2)
    monkeypatch.setattr(weekly_overview, "ONDEMAND_MAX_ROWS", 2)
    pce.rows = [od.raw(1, day=1), od.raw(2, day=2), od.raw(3, day=3), od.raw(4, day=22)]
    doc = finish(_build(_light(tmp_path)))
    assert _kpi(doc, "pb_connections").value is None
    assert "reading stopped at 2 rows before it reached this period" in _section(doc, "flows").blocks[0].paragraphs[0]


def test_on_a_pull_the_previous_period_is_given_only_when_the_pce_reaches_back_over_it(tmp_path, pce):
    """A pulled store counts its whole range as collected, whatever the PCE still keeps."""
    doc = _build(_light(tmp_path))  # the PCE's first record is of 10-22: nothing says it keeps the week before
    assert _kpi(doc, "pb_connections").value is not None and _kpi(doc, "pb_connections").previous is None
    assert _kpi(doc, "new_connections").previous is None
    for sid in ("flows", "new_connections"):  # and each chapter says why, in the PCE's terms
        said = " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)
        assert "The PCE returned no flow from before the previous period began" in said, sid
        assert "not collected whole" not in said
    pce.rows = [*od.ROWS, od.raw(9, day=5), od.raw(10, day=15, port=22, decision="potentially_blocked", conns=2)]
    doc = _build(_light(tmp_path / "b"))
    assert _kpi(doc, "pb_connections").previous == 2 and _kpi(doc, "new_connections").previous == 1


def test_on_a_pull_a_previous_period_the_pce_keeps_by_the_week_is_not_compared(tmp_path, pce):
    """Lab 26.2 and SaaS 26.30, 2026-11-14: traffic older than about two weeks comes back as records running Monday
    to Sunday that hold the week's count. A count of the previous period would be of whole weeks (on the SaaS box:
    ten days' connections given as the seven before), so none is given and the chapters say why."""
    week = od.raw(10, day=13, port=22, decision="potentially_blocked", conns=70)
    week["timestamp_range"]["last_detected"] = "2026-10-19T23:55:00Z"
    pce.rows = [*od.ROWS, od.raw(9, day=5), week]
    doc = _build(_light(tmp_path))
    assert _kpi(doc, "pb_connections").value == 5 and _kpi(doc, "pb_connections").previous is None
    assert _kpi(doc, "new_connections").previous is None
    for sid in ("flows", "new_connections"):
        said = " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)
        assert "records longer than a day (the longest spans 7 days)" in said, sid
        assert "The PCE returned no flow" not in said and "not collected whole" not in said
    assert not any("records longer than a day" in q for q in doc.data_quality)  # this period's are records of a day


def test_a_period_the_pce_keeps_by_the_week_says_its_counts_are_of_whole_records(tmp_path, pce):
    """Any report read from the PCE: a record of the period that spans a week is counted whole, and a data note
    says so."""
    week = od.raw(3, port=22, decision="potentially_blocked", conns=70)
    week["timestamp_range"].update(first_detected="2026-10-19T00:05:00Z", last_detected="2026-10-25T23:55:00Z")
    pce.rows = [*od.ROWS[:2], week]
    doc = _build(_light(tmp_path))
    assert _kpi(doc, "pb_connections").value == 70
    assert any("records longer than a day (the longest spans 7 days)" in q and "counted whole" in q
               for q in doc.data_quality)


def test_a_pce_switched_during_the_pull_fails_the_report(tmp_path, pce, monkeypatch):
    """Not a report of PCE A's alerts and PCE B's traffic, and not "the traffic could not be had" either."""
    ctx = _light(tmp_path)
    real, switched = pce.__call__, []

    def query(client, payload, **kw):
        if not switched:
            switched.append(1)
            ctx.settings.update(ctx.settings.current().revision,
                                lambda d: d["pce"].update(url="https://other.example.com:8443"))
            ctx.flows().reset()
        return real(client, payload, **kw)
    monkeypatch.setattr(ondemand, "run_traffic_query", query)
    row = _run(ctx)
    assert switched and row.status is ReportStatus.FAILED and row.error_key == "rpt_err_pce_switched"
    assert row.files == []


def test_full_mode_reads_its_own_store_and_asks_the_pce_nothing(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="full")
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(r) for r in od.ROWS], origin=DataOrigin.INGEST, now=NOW)
    row = _run(ctx)
    assert row.status is ReportStatus.DONE and pce.payloads == []
    pb = sum(r["num_connections"] for r in od.ROWS if r["policy_decision"] == "potentially_blocked")
    assert {k["key"]: k["value"] for k in row.kpis}["pb_connections"] == pb


def test_a_week_with_no_traffic_in_the_store_says_no_traffic_not_that_the_pce_failed(tmp_path, pce):
    doc = finish(_build(configured_ctx(tmp_path, mode="full")))
    assert _kpi(doc, "pb_connections").value is None and _kpi(doc, "pb_connections").note == "No traffic in this period."
    assert to_do(doc).held.startswith("This period has no traffic to evaluate the rules on")
    assert [s.id for s in doc.sections][:5] == ["alerts", "vens", "flows", "new_connections", "policy"]


# ── how the type is registered ───────────────────────────────────────────────────────────────────────────────

def test_the_reports_page_leads_with_it_as_a_type_that_pulls_on_demand(tmp_path):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    entries = views.catalog(ctx).entries
    first = entries[0]
    assert first.report_type is WK and first.tier == "common" and first.mode == "on_demand"
    assert first.available and not first.accepts_filter and first.ui_group == "operations"
    assert views.COMMON[0] is WK
    assert {e.report_type for e in entries if e.tier == "common"} == set(views.COMMON) and len(views.COMMON) == 5
    assert first.max_lookback == 90 and first.formats == ["html", "xlsx"]
    # the first day the picker offers is one the request is not refused for
    settings = ctx.settings.current()
    ok = ReportParams(report_type=WK, period_from=first.earliest_day, period_to=first.earliest_day + timedelta(days=6))
    assert generate.refusal(settings, ok, now=datetime.now(UTC)) is None


def test_a_period_past_its_lookback_and_a_filter_are_refused(tmp_path):
    from illumio_ops.domain.filter import FlowCondition
    settings = configured_ctx(tmp_path, mode="lightweight").settings.current()
    day = NOW.date()
    assert generate.refusal(settings, ReportParams(report_type=WK, lookback_days=90), now=NOW) is None
    far = ReportParams(report_type=WK, period_from=day - timedelta(days=120), period_to=day - timedelta(days=114))
    assert generate.refusal(settings, far, now=NOW) == "rpt_err_lookback_beyond_retention"
    cond = FlowCondition.model_validate({"decisions": ["blocked"]})
    assert generate.refusal(settings, ReportParams(report_type=WK, filter=cond), now=NOW) == "rpt_err_filter_not_supported"
    assert ReportParams(report_type=WK).lookback_days == 7


def test_events_read_from_the_archive_leave_the_traffic_the_installs(tmp_path):
    """A period that starts before the events kept: the generator builds from the archive's store of events, which
    holds no traffic — the traffic, the inventory and the alerts are still read from the install."""
    from illumio_ops.services.collect.archive import run_archive
    from illumio_ops.services.collect.retention import run_retention
    from illumio_ops.store.flowdb.events import upsert_events
    from tests.services.reports.test_audit import event as audit_event

    def make(path, archive):
        ctx = configured_ctx(path)
        ctx.settings.update(ctx.settings.current().revision, lambda d: (
            d["collection"]["retention"].update({"flow_days": 30, "event_days": 3, "rollup_days": 30,
                                                 "baseline_days": 30}),
            d["collection"]["archive"].update({"enabled": archive, "retention_days": 0}),
            d["display"].update({"timezone": "UTC", "language": "en"})))
        _inventory(ctx, [host("recent", online=0, hb=timedelta(days=3)), host("fine")])
        with ctx.flows().connect() as conn:
            upsert_flows(conn, [normalize_flow(r) for r in od.ROWS], origin=DataOrigin.INGEST, now=NOW)
            upsert_events(conn, [audit_event("sec_policy.create", START + timedelta(days=1), user="alice")],
                          origin=DataOrigin.INGEST, now=NOW)
            conn.commit()
        run_archive(ctx, now=NOW)
        run_retention(ctx, now=NOW)
        return {k["key"]: k["value"] for k in _run(ctx).kpis}
    with_archive, without = make(tmp_path / "a", True), make(tmp_path / "b", False)
    assert with_archive["provisions"] == 1 and without["provisions"] is None  # the event is in the archive only
    for key in ("pb_connections", "new_connections", "vens_not_online", "new_alerts"):
        assert with_archive[key] == without[key], key
    assert with_archive["pb_connections"] == sum(r["num_connections"] for r in od.ROWS
                                                 if r["policy_decision"] == "potentially_blocked")


def test_only_a_registered_reason_changes_what_the_first_page_says_of_rules_that_did_not_run():
    """The first page reads the reason from the rules table's own words — and only a sentence registered as one
    (finish.NOT_RUN_REASONS): any other empty rules table still reads as "no traffic in the period"."""
    from illumio_ops.services.reports import findings
    from illumio_ops.services.reports.finish import NOT_RUN_REASONS
    from tests.services.reports.conftest import make_doc
    same = {"title": "Rules not evaluated", "intro": "", "table_title": "t", "evaluated": False}
    with pytest.raises(ValueError, match="registered"):
        findings.unevaluated_section([], Language.EN, **same, not_run_key="rpt_no_flows")
    for key in NOT_RUN_REASONS:
        doc = make_doc(sections=findings.unevaluated_section([], Language.EN, **same, not_run_key=key))
        assert to_do(doc).held == f"{translate(Language.EN, key, {})} See “Rules not evaluated”."
    plain = make_doc(sections=findings.unevaluated_section([], Language.EN, **same))
    assert to_do(plain).held == "This period has no traffic to evaluate the rules on; see “Rules not evaluated”."
