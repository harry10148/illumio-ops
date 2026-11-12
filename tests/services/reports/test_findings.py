"""The findings engine over the flow store (P5b-1 Task 2): 5.x B001–B009 and L001–L010, one period read."""
import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from illumio_ops.domain.actions import ACTION_ORDER, group_actions
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.findings_rules import (
    ACTION_CODES,
    ACTION_SHORT_KEYS,
    BY_ID,
    RULES,
    RuleOutcome,
)
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, Language, Severity
from illumio_ops.i18n import dictionary
from illumio_ops.services.reports import findings
from illumio_ops.services.reports.common import tr
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
SPEC = FilterSpec(start=datetime(2026, 10, 20, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))
_n = iter(range(1, 1_000_000))


def flow(*, src=None, dst="db", port=445, proto=6, decision="allowed", src_env="Dev", dst_env="Dev", src_app="Web",
         dst_app="DB", user=None, unmanaged_src=False, unmanaged_dst=False, bytes_=None, conns=1):
    i = next(_n)
    first = datetime(2026, 10, 22, 3, tzinfo=UTC) + timedelta(seconds=i)
    raw = raw_flow(i, first, first + timedelta(minutes=5), port=port, user=user)
    raw["service"]["proto"] = proto
    raw["policy_decision"] = decision
    raw["num_connections"] = conns
    src_name = src or f"s{i}"
    if unmanaged_src:
        raw["src"] = {"ip": f"10.9.{i // 250 % 250}.{i % 250}"}
    else:
        raw["src"]["workload"].update(href=f"/orgs/1/workloads/{src_name}", hostname=src_name,
                                      labels=[{"key": "env", "value": src_env}, {"key": "app", "value": src_app}])
    if unmanaged_dst:
        raw["dst"] = {"ip": f"203.0.113.{i % 250}"}
    else:
        raw["dst"]["workload"].update(href=f"/orgs/1/workloads/{dst}", hostname=dst,
                                      labels=[{"key": "env", "value": dst_env}, {"key": "app", "value": dst_app}])
        raw["dst"]["ip"] = f"10.0.2.{abs(hash(dst)) % 250}"
    if bytes_ is not None:
        raw["dst_bi"], raw["dst_bo"] = bytes_, 0
    return normalize_flow(raw)


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def _write(ctx, flows):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)


def run(ctx, **thresholds):
    t = ctx.settings.current().reports.rule_thresholds.model_copy(update=thresholds)
    return {o.rule_id: o for o in findings.run_rules(ctx, SPEC, t, Language.EN, now=NOW)}


def test_b001_cross_env_without_ip_heuristic(ctx):
    _write(ctx, [flow(port=445, src_env="Dev", dst_env="Prod"), flow(port=445)])
    o = run(ctx)["B001"]
    assert o.severity is Severity.CRITICAL and o.params["n_cross_env"] == 1 and o.params["n_total"] == 2


def test_b001_allowed_same_env_high_and_pb_medium(tmp_path):
    a = configured_ctx(tmp_path / "a")
    _write(a, [flow(port=3389)])
    assert run(a)["B001"].severity is Severity.HIGH
    b = configured_ctx(tmp_path / "b")
    _write(b, [flow(port=3389, decision="potentially_blocked")])
    assert run(b)["B001"].severity is Severity.MEDIUM


def test_b001_blocked_and_udp_reply_ignored(ctx):
    _write(ctx, [flow(port=445, decision="blocked"), flow(port=445, proto=17)])
    assert "B001" not in run(ctx)


def test_b002_high_remote_access_allowed(ctx):
    _write(ctx, [flow(port=5900)])
    assert run(ctx)["B002"].severity is Severity.HIGH


def test_b003_medium_port_pb(ctx):
    _write(ctx, [flow(port=22, decision="potentially_blocked"), flow(port=80)])
    o = run(ctx)["B003"]
    assert o.severity is Severity.MEDIUM and o.params["n_flows"] == 1


def test_b004_unmanaged_sources(ctx):
    _write(ctx, [flow(port=443, unmanaged_src=True) for _ in range(3)])
    assert run(ctx, unmanaged_connection=2)["B004"].params["n_flows"] == 3
    assert "B004" not in run(ctx, unmanaged_connection=3)


def test_b005_low_policy_coverage(ctx):
    _write(ctx, [flow(port=443, decision="potentially_blocked") for _ in range(3)] + [flow(port=443)])
    o = run(ctx)["B005"]
    assert o.severity is Severity.MEDIUM and o.params["coverage_pct"] == "25.0"


def test_b006_fanout_on_management_ports(ctx):
    _write(ctx, [flow(src="jump", dst=f"t{i}", port=22) for i in range(4)])
    o = run(ctx, lateral_outbound_dst=3)["B006"]
    assert o.severity is Severity.HIGH and "jump" in o.params["top_sources"]
    assert "B006" not in run(ctx, lateral_outbound_dst=4)


def test_b007_user_destinations(ctx):
    _write(ctx, [flow(dst=f"t{i}", port=443, user="CORP\\alice") for i in range(3)])
    assert run(ctx, user_destination=2)["B007"].severity is Severity.HIGH


def test_b008_byte_outliers_need_byte_data(ctx):
    _write(ctx, [flow(dst=f"t{i}", port=443, bytes_=1000) for i in range(20)] +
           [flow(dst="big", port=443, bytes_=50 * 1024 * 1024)])
    o = run(ctx)["B008"]
    assert o.severity is Severity.MEDIUM and o.params["n_outliers"] == 1 and "big" in o.params["top_pairs"]


def test_b009_cross_env_volume(ctx):
    _write(ctx, [flow(port=443, src_env="Dev", dst_env="Prod") for _ in range(3)])
    assert run(ctx, cross_env_connection=2)["B009"].severity is Severity.LOW


def test_l001_cleartext(ctx):
    _write(ctx, [flow(port=23, decision="blocked")])
    assert run(ctx)["L001"].severity is Severity.MEDIUM


def test_l003_db_from_many_apps(ctx):
    _write(ctx, [flow(dst="sql", port=1433, src_app=f"A{i}") for i in range(3)])
    assert run(ctx, db_unique_src_app=2)["L003"].severity is Severity.HIGH


def test_l004_db_across_env(ctx):
    _write(ctx, [flow(dst="sql", port=5432, src_env="Dev", dst_env="Prod")])
    assert run(ctx)["L004"].severity is Severity.HIGH


def test_l005_identity_from_many_apps(ctx):
    _write(ctx, [flow(dst="dc", port=389, src_app=f"A{i}", decision="potentially_blocked") for i in range(4)])
    assert run(ctx)["L005"].severity is Severity.MEDIUM


def test_l006_reads_exposure(ctx):
    _write(ctx, [flow(port=443)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={
            "hosts": [{"key": "/orgs/1/workloads/hub", "reach_now": 9}, {"key": "/orgs/1/workloads/x", "reach_now": 1}]})
        conn.commit()
    o = run(ctx)["L006"]
    assert o.severity is Severity.HIGH and o.params["n_hosts"] == 1


def test_l007_unmanaged_to_critical(ctx):
    _write(ctx, [flow(port=445, unmanaged_src=True) for _ in range(2)])
    assert run(ctx, unmanaged_critical=2)["L007"].severity is Severity.HIGH


def test_l008_pb_lateral(ctx):
    _write(ctx, [flow(port=22, decision="potentially_blocked") for _ in range(2)])
    assert run(ctx, pb_lateral=2)["L008"].severity is Severity.HIGH


def test_l009_exfil_bytes(ctx):
    _write(ctx, [flow(port=443, unmanaged_dst=True, bytes_=2 * 1024 * 1024)])
    assert run(ctx, exfil_mb=1)["L009"].severity is Severity.HIGH
    assert "L009" not in run(ctx, exfil_mb=3)


def test_l010_cross_env_management(ctx):
    _write(ctx, [flow(port=22, src_env="Dev", dst_env="Prod") for _ in range(2)])
    assert run(ctx, cross_env_lateral=2)["L010"].severity is Severity.CRITICAL


def test_nothing_fires_on_quiet_traffic(ctx):
    _write(ctx, [flow(port=443)])
    with ctx.flows().connect() as conn:  # an exposure graph with no far-reaching host (without one L006 is unknown)
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={"hosts": []})
        conn.commit()
    assert run(ctx) == {}


def test_rule_error_is_reported_not_fatal(ctx, monkeypatch):
    _write(ctx, [flow(port=5900)])

    def boom(*a, **k):
        raise RuntimeError("bad rule")
    monkeypatch.setitem(findings.RULE_FUNCTIONS, "B001", boom)
    got = run(ctx)
    assert got["B001"].error == "RuntimeError: bad rule" and got["B002"].severity is Severity.HIGH


def test_rules_share_one_period_read(ctx, monkeypatch):
    _write(ctx, [flow(port=445), flow(port=5900)])
    seen: list[str] = []
    real = findings.reads.reading

    class Spy:
        def __init__(self, ctx_):
            self.cm = real(ctx_)

        def __enter__(self):
            conn = self.cm.__enter__()
            conn.set_trace_callback(seen.append)
            return conn

        def __exit__(self, *exc):
            return self.cm.__exit__(*exc)
    monkeypatch.setattr(findings.reads, "reading", Spy)
    run(ctx)
    assert sum(" FROM flows " in s for s in seen) == 1


def test_thresholds_from_settings(ctx):
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["reports"]["rule_thresholds"].update(unmanaged_connection=1))
    _write(ctx, [flow(port=443, unmanaged_src=True) for _ in range(2)])
    got = {o.rule_id for o in findings.run_rules(ctx, SPEC, ctx.settings.current().reports.rule_thresholds,
                                                 Language.EN, now=NOW)}
    assert "B004" in got


def test_l006_scoped_to_the_filtered_flows(ctx):
    """A filtered report (one app) lists only exposure hosts that appear in its own flows."""
    _write(ctx, [flow(src="hub", port=443)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={
            "hosts": [{"key": "/orgs/1/workloads/hub", "reach_now": 9}, {"key": "/orgs/1/workloads/far", "reach_now": 9}]})
        conn.commit()
    t = ctx.settings.current().reports.rule_thresholds
    whole = {o.rule_id: o for o in findings.run_rules(ctx, SPEC, t, Language.EN, now=NOW)}
    scoped = {o.rule_id: o for o in findings.run_rules(ctx, SPEC, t, Language.EN, now=NOW, scoped=True)}
    assert whole["L006"].params["n_hosts"] == 2 and scoped["L006"].params["n_hosts"] == 1


def test_l006_not_evaluated_without_exposure(ctx):
    """Review #7: with no exposure graph (lightweight mode, or before the first hourly run) L006 vanished as if
    no host reached too far; it says it was not evaluated."""
    _write(ctx, [flow(port=22)])
    o = run(ctx)["L006"]
    assert o.severity is None and o.error


def test_mitre_techniques_per_rule():
    """5.x mitre_map: ransomware, lateral and exfiltration rules carry ATT&CK techniques; governance rules (B005,
    B009, L008) carry none rather than a misleading one."""
    from illumio_ops.domain.findings_rules import BY_ID, RULES
    assert [t for t, _ in BY_ID["B001"].techniques] == ["T1486", "T1021.002"]
    assert [t for t, _ in BY_ID["L010"].techniques] == ["T1021", "T1570"]
    assert {r.rule_id for r in RULES if not r.techniques} == {"B005", "B009", "L008"}


def test_findings_carry_mitre_techniques(ctx):
    _write(ctx, [flow(port=445, src_env="Dev", dst_env="Prod")])
    outcomes = list(run(ctx).values())
    found = {f.title: f for f in findings.as_findings(outcomes, Language.EN)}
    b001 = found[tr(Language.EN, BY_ID["B001"].name_key)]
    assert ("T1486", "Data Encrypted for Impact") in b001.techniques
    table = findings.outcomes_table(outcomes, Language.EN, title="Findings")
    col = [c.key for c in table.columns].index("mitre")
    row = next(r for r in table.rows if r[0] == "B001")
    assert row[col] == "T1486 Data Encrypted for Impact, T1021.002 SMB/Windows Admin Shares"


# ── stage 3a: every rule that fired is a finding, with the fact, the reason and the thing to do ──────────────

_REC = re.compile(r"^rpt_rule_([bl]\d{3})_rec(?:_\w+)?$")
_ALL_FIRE = {"unmanaged_connection": 1, "min_policy_coverage_pct": 100, "lateral_outbound_dst": 1,
             "user_destination": 1, "cross_env_connection": 1, "discovery_protocol": 1, "db_unique_src_app": 1,
             "identity_unique_src_app": 1, "blast_radius": 1, "unmanaged_critical": 1, "pb_lateral": 1, "exfil_mb": 1,
             "cross_env_lateral": 1}


def _rec_literals() -> set[tuple[str, str]]:
    """(rule, recommendation key) for every recommendation key the engine's source spells out."""
    tree = ast.parse(Path(findings.__file__).read_text(encoding="utf-8"))
    return {(m[1].upper(), n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and (m := _REC.match(n.value))}


def _unregistered(table) -> list[tuple[str, str]]:
    return sorted(_rec_literals() - set(table))


def test_every_recommendation_has_an_action_code():
    assert len(_rec_literals()) >= 24 and _unregistered(ACTION_CODES) == []
    assert set(ACTION_CODES) == _rec_literals()  # and none is registered that the engine cannot return
    # the check itself: a table one entry short is caught
    short = {k: v for k, v in ACTION_CODES.items() if k != ("B006", "rpt_rule_b006_rec_pb")}
    assert _unregistered(short) == [("B006", "rpt_rule_b006_rec_pb")]


def test_action_codes_are_registered_and_worded_in_both_languages():
    codes = set(ACTION_CODES.values())
    assert codes <= set(ACTION_ORDER) and set(ACTION_SHORT_KEYS) == codes
    for code in codes:
        assert ACTION_SHORT_KEYS[code] == f"rpt_act_{code}"
        for lang in Language:
            assert dictionary(lang)[ACTION_SHORT_KEYS[code]].strip()


def test_every_rule_says_why_it_matters():
    from tests.i18n.test_terminology import BANNED, _words
    assert len(RULES) == 19
    for r in RULES:
        assert r.why_key == f"rpt_rule_{r.rule_id.lower()}_why"
        for lang in Language:
            assert dictionary(lang)[r.why_key].strip()
        zh = dictionary(Language.ZH_TW)[r.why_key]
        assert not [p for p in BANNED if re.search(p, _words(zh))], r.rule_id


def test_rule_info_keeps_its_techniques_beside_the_new_key():
    assert BY_ID["B001"].techniques[0] == ("T1486", "Data Encrypted for Impact") and BY_ID["B005"].techniques == ()


def _all_rule_flows():
    return [flow(port=445, src_env="Dev", dst_env="Prod"), flow(port=5900), flow(port=22, decision="potentially_blocked"),
            flow(port=1433, unmanaged_src=True), flow(port=443, unmanaged_src=True),
            flow(src="jump", dst="t1", port=22), flow(src="jump", dst="t2", port=22),
            flow(dst="t1", port=443, user="CORP\\alice"), flow(dst="t2", port=443, user="CORP\\alice"),
            flow(port=23, decision="blocked"), flow(port=137, proto=17), flow(port=1433, src_app="A", src_env="Prod"),
            flow(port=1433), flow(port=389, src_app="A"), flow(port=389, src_app="B"),
            flow(port=443, unmanaged_dst=True, bytes_=2 * 1024 * 1024),
            *(flow(dst=f"p{i}", port=443, bytes_=1000) for i in range(20)),
            flow(dst="big", port=443, bytes_=50 * 1024 * 1024)]


@pytest.mark.parametrize("lang", list(Language))
def test_every_rule_that_fired_is_a_finding(ctx, lang):
    _write(ctx, _all_rule_flows())
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={
            "hosts": [{"key": "/orgs/1/workloads/hub", "reach_now": 9}]})
        conn.commit()
    outcomes = list(run(ctx, **_ALL_FIRE).values())
    assert {o.rule_id for o in outcomes if o.severity is not None} == {r.rule_id for r in RULES}
    found = findings.as_findings(outcomes, lang)
    assert [f.title for f in found] == [tr(lang, BY_ID[o.rule_id].name_key) for o in outcomes]  # all 19, same order
    for f in found:
        assert f.what and f.why and f.action and f.action_code in ACTION_ORDER and f.action_short
        assert f.what != f.why and "{" not in f.what + f.why + f.action + f.action_short + f.action_focus
    assert sum(len(a.findings) for a in group_actions(found)) == len(found)
    by = {o.rule_id: f for o, f in zip(outcomes, found, strict=True)}
    # the rules with no "who" carry no focus sentence; the others name the first row of their ranking
    assert not any(by[r].action_focus for r in ("B005", "L001", "L002", "L005"))
    assert all(by[r.rule_id].action_focus for r in RULES if r.rule_id not in ("B005", "L001", "L002", "L005"))


def test_findings_say_the_fact_apart_from_the_reason(ctx):
    _write(ctx, [flow(port=5900)])
    (f,) = findings.as_findings(list(run(ctx).values()), Language.EN)  # L006 (no exposure graph) is no finding
    assert f.what.startswith("1 allowed flows from 1 sources on secondary remote-access ports.")
    assert f.why == "These remote-access ports let someone outside keep control of a host."
    assert f.action.startswith("1) Verify each allowed flow") and f.action_code == "narrow_rules"
    assert f.action_short == ("Narrow the rules that allow management, database and identity ports to the sources "
                              "that need them.")


def test_b001_action_follows_the_recommendation_the_data_chose(tmp_path):
    def code(name, flows):
        c = configured_ctx(tmp_path / name)
        _write(c, flows)
        found = {f.title: f for f in findings.as_findings(list(run(c).values()), Language.EN)}
        return found[tr(Language.EN, BY_ID["B001"].name_key)].action_code
    assert code("cross", [flow(port=445, src_env="Dev", dst_env="Prod")]) == "cross_env_rules"
    assert code("same", [flow(port=445)]) == "narrow_rules"
    assert code("pb", [flow(port=445, decision="potentially_blocked")]) == "enforce"
    assert code("cross_pb", [flow(port=445, decision="potentially_blocked", src_env="Dev", dst_env="Prod")]) == "enforce"


def test_focus_is_the_first_row_not_cut_out_of_the_joined_text(ctx):
    """A host name may hold a comma: the focus is the ranking's first row, never the joined text split on ', '."""
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/dbp", hostname="db, primary", name=None, managed=1, enforcement_mode="selective",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
        conn.commit()
    _write(ctx, [flow(dst="dbp", port=445), flow(dst="dbp", port=445), flow(dst="other", port=445)])
    o = run(ctx)["B001"]
    assert o.params["top_destinations"].startswith("db, primary (2), ") and o.focus == "db, primary"
    assert o.params["top_destinations"].split(", ")[0] == "db"  # what cutting the text would have given
    (f,) = [f for f in findings.as_findings([o], Language.EN) if f.action_code]
    assert f.action_focus == "Ransomware Risk Port — Contextual Analysis: db, primary has the most."
    zh = findings.as_findings([o], Language.ZH_TW)[0]
    assert zh.action_focus == "勒索軟體風險 port（情境分析）：最多的是 db, primary。"


def test_focus_costs_no_second_ranking_query(ctx, monkeypatch):
    _write(ctx, [flow(dst="a", port=445), flow(dst="b", port=5900)])
    seen: list[str] = []
    real = findings.reads.reading

    class Spy:
        def __init__(self, ctx_):
            self.cm = real(ctx_)

        def __enter__(self):
            conn = self.cm.__enter__()
            conn.set_trace_callback(seen.append)
            return conn

        def __exit__(self, *exc):
            return self.cm.__exit__(*exc)
    monkeypatch.setattr(findings.reads, "reading", Spy)
    got = run(ctx)
    # hosts the inventory does not hold are named "Removed workload …<id>", as in the joined text
    assert got["B001"].focus.endswith("…a") and got["B002"].focus.endswith("…b")
    assert got["B001"].params["top_destinations"] == f"{got['B001'].focus} (1)"
    ranking = [s for s in seen if "GROUP BY dst_key ORDER BY n DESC" in s]
    assert len(ranking) == 2  # one per rule that fired (B001, B002): the same read gives the text and the focus


def test_l008_focus_empty_when_most_goes_to_hosts_without_an_app(ctx):
    _write(ctx, [flow(port=22, decision="potentially_blocked", dst_app="") for _ in range(3)] +
           [flow(port=22, decision="potentially_blocked", dst_app="DB")])
    o = run(ctx, pb_lateral=2)["L008"]
    assert o.params["top_apps"].startswith("— (3)") and o.focus == ""
    assert findings.as_findings([o], Language.EN)[0].action_focus == ""


def _section_args():
    return {"title": "Rules not evaluated", "intro": "intro", "table_title": "could not be evaluated"}


def test_unevaluated_section_nothing_when_every_rule_was_evaluated(ctx):
    _write(ctx, [flow(port=5900)])
    with ctx.flows().connect() as conn:  # an exposure graph with no far-reaching host: L006 evaluated, did not fire
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={"hosts": []})
        conn.commit()
    outcomes = list(run(ctx).values())
    assert [o.rule_id for o in outcomes] == ["B002"]
    assert findings.unevaluated_section(outcomes, Language.EN, **_section_args()) == ()
    assert findings.unevaluated_section([], Language.EN, **_section_args()) == ()  # nothing fired, all evaluated


def test_unevaluated_section_lists_only_the_rule_that_could_not_run(ctx):
    _write(ctx, [flow(port=5900)])  # no exposure graph (lightweight mode): L006 is unknown, B002 fired
    outcomes = list(run(ctx).values())
    assert {o.rule_id for o in outcomes} == {"B002", "L006"}
    (section,) = findings.unevaluated_section(outcomes, Language.EN, **_section_args())
    (table,) = section.blocks
    assert section.id == "findings" and [r[0] for r in table.rows] == ["L006"] and table.total_rows == 1
    assert "Not evaluated" in table.rows[0] and "exposure graph has not been computed" in " ".join(table.rows[0])


def test_closing_table_title_fits_an_xlsx_sheet_name():
    """Excel caps a sheet name at 31 characters; a longer title is shortened (with the whole title above the table).
    The closing table's own title is kept within the cap so its sheet is not one of those."""
    for lang in Language:
        assert len(tr(lang, "rpt_rules_tbl_unevaluated")) <= 31


def test_unevaluated_section_says_the_rules_did_not_run():
    for lang, said in ((Language.EN, "The rules were not evaluated"), (Language.ZH_TW, "規則未評估")):
        (section,) = findings.unevaluated_section([], lang, **_section_args(), evaluated=False)
        (table,) = section.blocks
        assert table.rows == () and said in table.empty_text


def test_a_rule_not_evaluated_is_never_a_finding():
    broken = RuleOutcome("B001", None, "", "", {}, error="RuntimeError: bad rule")
    assert findings.as_findings([broken], Language.EN) == ()
