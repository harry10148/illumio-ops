"""The ransomware protection report (P5b-2 Task 4, spec §6.5.6): the PCE's judgement as stored, the three action
lists, each host's breakdown with contradictions flagged and left out of the ranking, the allow rules behind the
deductions for the top hosts, and the trend from the daily snapshots."""
import json
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import BarBlock, TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.analysis.ransomware import HostRansomware
from illumio_ops.services.reports import ransomware_report
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import analysis
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def svc(name, port, *, severity="critical", state="unprotected", status="listening", traffic="priority",
        coverage=0.0, sources=3):
    return {"name": name, "port": port, "proto": 6, "severity": severity, "category": "admin",
            "protection_state": state, "port_status": status, "active_policy": "allowed",
            "weight": {"critical": 40, "high": 30}.get(severity, 20), "coverage": coverage,
            "contribution": 0.0, "traffic": traffic, "recent_sources": sources}


def hostrow(name, *, pce=10.0, computed=10.0, contradiction=False, services=(), mode="selective"):
    return {"href": f"/orgs/1/workloads/{name}", "hostname": name, "enforcement_mode": mode,
            "pce_percent": pce, "pce_exposure": "critical", "computed_percent": computed, "approximate": True,
            "contradiction": contradiction, "services": list(services)}


def item(host, name, port, *, sources=3):
    return {"host": f"/orgs/1/workloads/{host}", "hostname": host, "name": name, "port": port, "proto": 6,
            "severity": "critical", "weight": 40, "recent_sources": sources}


def _result(ctx, result):
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result=result)
        conn.commit()


def _std(ctx, n_priority=1):
    _result(ctx, {"unsupported": False, "contradictions": 1,
                  "priority": [item(f"p{i}", "SMB", 445) for i in range(n_priority)],
                  "safe_to_block": [item("idle", "RDP", 3389, sources=0)],
                  "suspicious": [item("odd", "WinRM", 5985)],
                  "hosts": [hostrow("bad", computed=5.0, services=[svc("SMB", 445)]),
                            hostrow("good", computed=90.0, services=[svc("RDP", 3389, state="protected_closed")]),
                            hostrow("liar", pce=0.0, computed=100.0, contradiction=True,
                                    services=[svc("SMB", 445, state="protected_open")])]})


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    c = configured_ctx(tmp_path)
    monkeypatch.setattr(ransomware_report, "host_ransomware", lambda ctx, href, **kw: HostRansomware.model_construct(
        breakdown=None, allow_rules={}, allow_status={}))
    return c


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.RANSOMWARE].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.RANSOMWARE), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _tables(doc, sid):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)]


def _texts(doc):
    return " ".join(p for s in doc.sections for b in s.blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def test_three_lists_from_analysis(ctx):
    _std(ctx)
    doc = _build(ctx)
    assert _tables(doc, "priority")[0].rows[0][:3] == ("p0", "SMB", "445/TCP")
    assert _tables(doc, "safe")[0].rows[0][:2] == ("idle", "RDP")
    assert _tables(doc, "suspicious")[0].rows[0][:2] == ("odd", "WinRM")
    k = {x.key: x.value for x in doc.kpis}
    assert (k["priority"], k["safe_to_block"], k["suspicious"], k["contradictions"], k["rated_hosts"]) == (1, 1, 1, 1, 3)


def test_contradiction_flagged_not_ranked(ctx):
    _std(ctx)
    rows = _tables(_build(ctx), "hosts")[0].rows
    assert [r[0] for r in rows] == ["bad", "good", "liar"]  # ranked by computed share; the contradiction last
    assert rows[2][-2] and not rows[0][-2]  # the flag; the explanation is last


def test_allow_rules_top_hosts_only(ctx, monkeypatch):
    _std(ctx, n_priority=25)
    asked = []

    def fake(ctx_, href, **kw):
        asked.append(href)
        return HostRansomware.model_construct(breakdown=None, allow_rules={"445/6": []}, allow_status={"445/6": "ok"})
    monkeypatch.setattr(ransomware_report, "host_ransomware", fake)
    _build(ctx)
    assert len(asked) == 20 and kw_ok(asked)


def kw_ok(asked):
    return asked[0] == "/orgs/1/workloads/p0"


def test_allow_lookup_error_not_clean(ctx, monkeypatch):
    _std(ctx)
    monkeypatch.setattr(ransomware_report, "host_ransomware", lambda ctx_, href, **kw: HostRansomware.model_construct(
        breakdown=None, allow_rules={"445/6": []}, allow_status={"445/6": "error"}))
    row = _tables(_build(ctx), "allow")[0].rows[0]
    assert "could not" in row[-1].lower()

    def boom(*a, **k):
        raise RuntimeError("PCE down")
    monkeypatch.setattr(ransomware_report, "host_ransomware", boom)
    row = _tables(_build(ctx), "allow")[0].rows[0]
    assert "could not" in row[-1].lower()


def test_trend_from_snapshots(ctx):
    _std(ctx)
    with ctx.flows().connect() as conn:
        for day, state in (("2026-10-21", "unprotected"), ("2026-10-22", "protected_open")):
            conn.execute("INSERT INTO ransomware_snapshot_daily (day, workload_href, name, port, proto, severity, "
                         "protection_state, port_status) VALUES (?, '/orgs/1/workloads/bad', 'SMB', 445, 6, 'critical', ?, "
                         "'listening')", (day, state))
        conn.execute("INSERT INTO org_risk_snapshot_daily (day, summary_json) VALUES ('2026-10-26', ?)",
                     (json.dumps({"ransomware": {"ransomware_protection_coverage_percent": 42.5}}),))
        conn.commit()
    doc = _build(ctx)
    bars = dict(next(b for b in _section(doc, "trend").blocks if isinstance(b, BarBlock)).points)
    assert bars["2026-10-21"] == 0.0 and bars["2026-10-22"] == 100.0 and bars["2026-10-20"] is None
    assert {k.key: k.value for k in doc.kpis}["org_percent"] == 42.5


def test_not_computed_and_unsupported_say_so(tmp_path, ctx):
    assert "not been computed" in _texts(_build(ctx))
    _result(ctx, {"unsupported": True})
    assert "does not provide" in _texts(_build(ctx))


def test_zh_tw_builds(ctx):
    _std(ctx)
    assert _build(ctx, Language.ZH_TW).title


# ── readable (2026-10-29: customers could not read the scores; keep them, explain them) ──────────────────────

def test_how_to_read_explains_the_numbers(ctx):
    _std(ctx)
    doc = _build(ctx)
    assert doc.sections[0].id == "how"
    terms = {r[0] for r in _tables(doc, "how")[0].rows}
    assert {"PCE score", "Computed from its services (approximate)", "The two scores differ"} <= terms


def test_each_host_says_what_its_numbers_mean(ctx):
    _std(ctx)
    rows = {r[0]: r for r in _tables(_build(ctx), "hosts")[0].rows}
    assert "1 high-risk service(s) unprotected" in rows["bad"][-1] and "SMB" in rows["bad"][-1]
    assert "protected" in rows["good"][-1].lower()
    assert "Selective" in rows["liar"][-1] and "Deny Rule" in rows["liar"][-1]  # why, and how to raise it


def test_protection_states_in_words(ctx):
    _std(ctx)
    states = {r[5] for r in _tables(_build(ctx), "hosts")[1].rows}
    assert states <= {"Unprotected", "Protected", "Unknown"}


def test_summary_finding_for_services_in_use(ctx):
    _std(ctx, n_priority=2)
    [f, *_] = _build(ctx).findings
    assert "2" in f.title and "Fix first" in f.action


def test_host_explanation_names_few_services_once(ctx):
    """Lab 2026-10-29: 24 names with S-SSH twice (TCP and UDP) in one cell."""
    many = [svc(f"S-{i}", 1000 + i) for i in range(8)] + [svc("S-0", 2000)]
    _result(ctx, {"unsupported": False, "contradictions": 0, "priority": [], "safe_to_block": [], "suspicious": [],
                  "hosts": [hostrow("big", services=many)]})
    text = _tables(_build(ctx), "hosts")[0].rows[0][-1]
    assert text.count("S-0") == 1 and "S-7" not in text and "and 3 more" in text


def test_exposure_in_words(ctx):
    _result(ctx, {"unsupported": False, "contradictions": 0, "priority": [], "safe_to_block": [], "suspicious": [],
                  "hosts": [{**hostrow("ok", services=[svc("RDP", 3389, state="protected_closed")]),
                             "pce_exposure": "fully_protected"}]})
    assert _tables(_build(ctx), "hosts")[0].rows[0][3] == "Fully protected"


def test_contradiction_with_nothing_unprotected_reads(ctx):
    _std(ctx)
    liar = {r[0]: r for r in _tables(_build(ctx), "hosts")[0].rows}["liar"][-1]
    assert "—" not in liar and "go by the pce score" in liar.lower()


def test_unprotected_with_unknown_traffic_is_a_finding(ctx):
    """Lightweight mode keeps no traffic: unprotected services cannot be sorted into the lists, which stay empty;
    the summary must not say there is nothing to handle."""
    _result(ctx, {"unsupported": False, "contradictions": 0, "priority": [], "safe_to_block": [], "suspicious": [],
                  "hosts": [hostrow("dev", services=[svc("SMB", 445, traffic="unknown", sources=None),
                                                     svc("RDP", 3389, traffic="unknown", sources=None)])]})
    [f] = _build(ctx).findings
    assert "2" in f.title and "alert mode" in f.action


def test_host_explanation_does_not_point_to_empty_lists(ctx):
    """With no traffic to sort by, the services are in no list: the explanation says so instead of sending the
    reader to "Fix first"."""
    _result(ctx, {"unsupported": False, "contradictions": 0, "priority": [], "safe_to_block": [], "suspicious": [],
                  "hosts": [hostrow("dev", services=[svc("SMB", 445, traffic="unknown", sources=None)])]})
    text = _tables(_build(ctx), "hosts")[0].rows[0][-1]
    assert "Fix first" not in text and "traffic" in text


def test_unenforced_host_says_the_vendor_counts_nothing(ctx):
    """User 2026-10-29: the vendor counts only Selective or Full hosts; a Visibility Only host scores 0 for that."""
    _result(ctx, {"unsupported": False, "contradictions": 0, "priority": [], "safe_to_block": [], "suspicious": [],
                  "hosts": [hostrow("vis", pce=0.0, computed=0.0, mode="visibility_only",
                                    services=[svc("RDP", 3389, state="protected_closed")])]})
    text = _tables(_build(ctx), "hosts")[0].rows[0][-1]
    assert "Visibility Only" in text and "Selective or Full" in text


def test_full_host_gap_not_explained_as_selective(ctx):
    """Review #7: only a Selective host's gap is the Deny Rule coverage; a Full host's is a disagreement."""
    _result(ctx, {"unsupported": False, "contradictions": 1, "priority": [], "safe_to_block": [], "suspicious": [],
                  "hosts": [hostrow("f", pce=0.0, computed=100.0, contradiction=True, mode="full",
                                    services=[svc("RDP", 3389, state="protected_closed")])]})
    text = _tables(_build(ctx), "hosts")[0].rows[0][-1]
    assert "move it to Full" not in text and "PCE console" in text
