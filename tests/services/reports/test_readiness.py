"""The enforcement readiness report (P5b-2 Task 5): per app (environment), five factors over its inbound connections
and its hosts, the predicted blocks of the draft policy, and the order to enforce in."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.analysis.predicted_block import (
    PredictedGroup,
    PredictedSummary,
)
from illumio_ops.services.reports import readiness as readiness_report
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import labels, workloads
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import covered, flow
from tests.services.reports.test_traffic import _write

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def summary(**kw):
    base = {"groups": [PredictedGroup(dst_app="DB", rule_href="/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/2",
                                      flows=3, connections=7)],
            "rules": {}, "blocked_flows": 3, "blocked_connections": 7, "undetermined_flows": 0, "capped": False,
            "computed_at": NOW,
            "unsupported": False, "missing_rules": ["/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/2"]}
    return PredictedSummary(**{**base, **kw})


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary())
    return configured_ctx(tmp_path)


def _inventory(ctx, hosts):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{n}", hostname=n, name=None, managed=1, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, (("app", app), ("env", "Dev"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for n, app, mode in hosts])
        conn.commit()


def _build(ctx, cond=None, lang=Language.EN):
    return specs()[ReportType.READINESS].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.READINESS, filter=cond), start=START, end=END, lang=lang,
        tz=UTC, now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


def _joined(doc):
    """The verdict table and the basis table (6.6.0: one table of eleven columns, now two) as one row per app:
    app, score, grade, explanation, the factor shares, the modes, the action."""
    basis = {r[0]: r[1:] for r in _table(doc, "scores", 1).rows}
    return [(*r[:4], *basis[r[0]], r[4]) for r in _table(doc, "scores").rows]


def _texts(doc, sid):
    return " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def test_inbound_only(ctx):
    # DB's inbound: two allowed from Web, one potentially blocked from DB itself; DB -> Web counts for Web only.
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, conns=2),
                 flow(src_app="DB", dst_app="DB", port=5432, decision="potentially_blocked", conns=2),
                 flow(src_app="DB", dst_app="Web", port=443, conns=10)])
    rows = {r[0]: r for r in _joined(_build(ctx))}
    db = rows["DB (Dev)"]
    assert db[4:8] == ("50.0%", "50.0%", "—", "50.0%")  # policy, ringfence, enforcement (no hosts), staged


def test_enforcement_from_inventory_exact_labels(ctx):
    _inventory(ctx, [("d1", "DB", "full"), ("d2", "DB", "selective"), ("x", "db", "full")])
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    row = {r[0]: r for r in _joined(_build(ctx))}["DB (Dev)"]
    assert row[6] == "75.0%"
    assert row[9] == ("Blocking everything (Full): 1, Blocking some (Selective): 1, "
                      "Recording only (Visibility Only): 0, Not blocking yet (Idle): 0")


def test_predicted_grouped_by_rule(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    assert _table(doc, "predicted").rows[0][0] == "DB" and _table(doc, "predicted").rows[0][2:] == (3, 7)
    assert {k.key: k.value for k in doc.kpis}["predicted_blocked"] == 7


def test_predicted_unsupported_says_so(ctx, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary(
        groups=[], unsupported=True, blocked_flows=0, blocked_connections=0))
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    assert "does not recompute" in _texts(doc, "predicted")
    assert {k.key: k.value for k in doc.kpis}["predicted_blocked"] is None


def test_predicted_error_report_still_built(ctx, monkeypatch):
    def boom(ctx, spec, **kw):
        raise PceQueryError("poll", 500)
    monkeypatch.setattr(readiness_report, "predicted_summary", boom)
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    assert "could not" in _texts(doc, "predicted").lower() and _table(doc, "scores").rows


def test_predicted_capped_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary(capped=True))
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    assert _table(_build(ctx), "predicted").limit_note


def test_queue_orders_by_score(ctx):
    _inventory(ctx, [("w1", "Web", "full"), ("d1", "DB", "idle")])
    _write(ctx, [flow(src_app="Web", dst_app="Web", port=443), flow(src_app="Web", dst_app="DB", port=5432,
                                                                    decision="potentially_blocked")])
    rows = _table(_build(ctx), "next").rows
    assert [r[0] for r in rows] == ["Web (Dev)", "DB (Dev)"]


def test_filter_narrows_apps(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432), flow(src_app="DB", dst_app="Web", port=443)])
    cond = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("DB",)),)))
    assert [r[0] for r in _table(_build(ctx, cond), "scores").rows] == ["DB (Dev)"]


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    assert _build(ctx, lang=Language.ZH_TW).title


def test_unknown_decisions_left_out(ctx):
    """Lab, 2026-10-28: 84% of the traffic had no reported decision and every app scored F on "allowed by a rule".
    A connection without a decision says nothing about policy: it is left out of policy and staged, and said."""
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, conns=2),
                 flow(src_app="Web", dst_app="DB", port=5432, decision="unknown", conns=8)])
    covered(ctx)
    doc = _build(ctx)
    row = {r[0]: r for r in _joined(doc)}["DB (Dev)"]
    assert row[4] == "100.0%" and row[7] == "100.0%"  # policy and staged over the 2 decided connections
    # stage 3b: said under the conclusion, in the flow reports' sentence (1 of the period's 2 flows, 8 of its 10
    # connections), naming the three factors that leave such connections out; this report has no chapter for them
    (said,) = doc.caveats
    assert said == ("Flows without a decision: 50.0% of the period's flows (80.0% by connections). The factors "
                    "“Allowed by a rule”, “Not blocked once enforced” and “Remote access with a rule” count only "
                    "the connections with a decision.")
    assert not any("no reported decision" in q for q in doc.data_quality)
    assert "monitor_only" not in {s.id for s in doc.sections}
    (zh,) = _build(ctx, lang=Language.ZH_TW).caveats
    assert zh == ("期間內有 50.0% 的流量（依連線數是 80.0%）沒有判定；「有規則允許」「切強制後不會被擋」與「遠端管理有規則」"
                  "三個因子只算有判定的連線。")


def test_every_flow_decided_no_sentence_under_the_conclusion(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, conns=2)])
    covered(ctx)
    assert _build(ctx).caveats == ()


def test_remote_factor_is_a_share_of_the_remote_connections_with_a_decision(ctx):
    """"Remote access with a rule" is a share of decisions, like "allowed by a rule": of the remote-access connections
    the PCE gave a decision for, the ones a rule allows. One without a decision is in neither number (6 of 8 here,
    not 6 of 20)."""
    from illumio_ops.services.flowsource import readiness_rows
    from illumio_ops.services.reports import flowsections
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=22, conns=6),
                 flow(src_app="Web", dst_app="DB", port=22, decision="potentially_blocked", conns=2),
                 flow(src_app="Web", dst_app="DB", port=22, decision="unknown", conns=12)])
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.READINESS), start=START, end=END,
                     lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")
    (row,) = readiness_rows(ctx, flowsections.window(inp), app_key="app", env_key="env", remote_ports={(22, 6)})
    assert (row.connections, row.unknown, row.remote, row.remote_allowed) == (20, 12, 8, 6)
    assert {r[0]: r for r in _joined(_build(ctx))}["DB (Dev)"][8] == "75.0%"


def test_remote_connections_all_without_a_decision_leave_the_factor_out(ctx):
    """Remote-access connections that all lack a decision say nothing about rules: the factor has no data and is
    not scored — never 0%, which would cost the app its 10 points."""
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, conns=3),
                 flow(src_app="Web", dst_app="DB", port=22, decision="unknown", conns=12)])
    row = {r[0]: r for r in _joined(_build(ctx))}["DB (Dev)"]
    assert row[8] == "—"
    # policy 3 of 3, from the app itself 0 of 15, no hosts, staged 3 of 3: 50 of the 70 points that have data
    # (with the remote factor at 0 it would be 50 of 80: 63)
    assert row[1] == 71


def test_how_to_read_says_which_factors_count_every_connection(ctx):
    """"From the app itself" measures where connections come from, not a decision: it alone counts every connection,
    and the table says so. "Remote access with a rule" is a share of decisions and says that it counts the
    connections with one."""
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    factors = next(b for b in _section(_build(ctx), "how").blocks if isinstance(b, TableBlock))
    measures = {r[0]: r[1] for r in factors.rows}
    assert "with or without a decision" in measures["From the app itself"]
    assert "not what was decided" in measures["From the app itself"]
    assert "with or without a decision" not in measures["Remote access with a rule"]
    assert "with a reported decision" in measures["Remote access with a rule"]
    zh = next(b for b in _section(_build(ctx, lang=Language.ZH_TW), "how").blocks if isinstance(b, TableBlock))
    said = {r[0]: r[1] for r in zh.rows}
    assert [k for k, v in said.items() if "不分有沒有判定" in v] == ["來自同一 app"]
    assert "有回報判定的" in said["遠端管理有規則"]


def test_all_unknown_no_policy_factor(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, decision="unknown", conns=5)])
    row = {r[0]: r for r in _joined(_build(ctx))}["DB (Dev)"]
    assert row[4] == "—" and row[7] == "—"


# ── readable (2026-10-29: customers could not read the scores; keep them, explain them) ──────────────────────

def test_how_to_read_explains_factors_and_grades(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    sec = _section(doc, "how")
    factors, grades = [b for b in sec.blocks if isinstance(b, TableBlock)]
    assert len(factors.rows) == 5 and {r[3] for r in factors.rows} == {"35", "20", "15", "10"}
    assert [r[0] for r in grades.rows] == ["A", "B", "C", "D", "F"]
    assert doc.sections[0].id == "how"


def test_each_score_says_why_and_what_fixing_it_gives(ctx):
    _inventory(ctx, [("d1", "DB", "selective")])
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, decision="potentially_blocked", conns=9),
                 flow(src_app="Web", dst_app="DB", port=5432, conns=1)])
    row = {r[0]: r for r in _joined(_build(ctx))}["DB (Dev)"]
    explain = row[3]
    assert "Allowed by a rule" in explain and "points" in explain  # the factor costing most, in words
    assert "about" in explain  # what the score would be with that factor fixed


def test_next_steps_list_the_connections_to_write_rules_for(ctx):
    _inventory(ctx, [("d1", "DB", "selective")])
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, decision="potentially_blocked", conns=9),
                 flow(src_app="Batch", dst_app="DB", port=1433, decision="potentially_blocked", conns=2),
                 flow(src_app="Web", dst_app="DB", port=5432, conns=1)])
    rows = _table(_build(ctx), "next").rows
    db = next(r for r in rows if r[0] == "DB (Dev)")
    assert "Web → 5432/TCP" in db[2] and db[2].index("Web →") < db[2].index("Batch")  # busiest first


def test_projected_score_with_one_factor_fixed():
    from illumio_ops.domain.readiness import ReadinessInputs, readiness, score_with
    r = readiness(ReadinessInputs(connections=10, decided=10, allowed=1, same_app=10, potentially_blocked=9,
                                  remote=0, remote_allowed=0, hosts=1, full=1, selective=0))
    assert r.blocking == "policy" and score_with(r.parts, "policy") > r.score


def test_summary_says_how_many_cannot_enforce_and_the_closest(ctx):
    """Lab 2026-10-29: 18 apps at F under "nothing to handle this period"."""
    _inventory(ctx, [("d1", "DB", "selective")])
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, decision="potentially_blocked", conns=9)])
    doc = _build(ctx)
    [f] = doc.findings
    assert "1" in f.title and "What to do first" in f.action
    assert f.what.startswith("The closest is DB (Dev): ") and f.why == "Enforcing them now would block normal traffic."
    assert f.action_code == "write_rules" and f.action_short == "Write rules for the traffic you have confirmed."


def test_average_score_in_points(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    k = {k.key: k for k in _build(ctx).kpis}["overall"]
    assert k.unit == "count" and isinstance(k.value, int)


def test_next_step_and_rules_to_write_in_one_column(ctx):
    """Lab 2026-10-29: at 1280 px the rules to write were past the table's right edge."""
    _inventory(ctx, [("d1", "DB", "selective")])
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, decision="potentially_blocked", conns=9)])
    table = _table(_build(ctx), "next")
    assert len(table.columns) == 3 and "Web → 5432/TCP" in table.rows[0][2]


def test_the_verdict_and_what_it_rests_on_are_two_tables(ctx):
    """6.6.0 Task 6: eleven columns in one table were unreadable; the factor shares are their own table."""
    _inventory(ctx, [("d1", "DB", "full")])
    doc = _build(ctx)
    verdict, basis = _table(doc, "scores"), _table(doc, "scores", 1)
    assert [c.key for c in verdict.columns] == ["app", "score", "grade", "explain", "advice"]
    assert basis.columns[0].key == "app" and basis.columns[-1].key == "modes" and len(basis.columns) >= 4
    assert [r[0] for r in verdict.rows] == [r[0] for r in basis.rows]
