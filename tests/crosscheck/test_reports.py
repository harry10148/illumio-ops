"""Report numbers recomputed from raw PCE data: the KPI algorithms on small fake data, the query lifecycle (the delete
always runs, a failed delete is a leftover), the limit and filter paths, and the whole area against an app database
made by the product's own migrations."""
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

import illumio_ops.crosscheck.__main__ as cli
from illumio_ops.crosscheck import events, kpis, reports
from illumio_ops.crosscheck.io import pce_target
from illumio_ops.crosscheck.model import Run
from illumio_ops.paths import resolve_paths
from illumio_ops.pce.client import PceResponse
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store.db import connect, migrate
from tests.crosscheck.test_events import URL, ev
from tests.web.conftest import cached_hash

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
START = datetime(2026, 11, 17, 16, 0, tzinfo=UTC)  # a display-zone midnight (+08:00), as reports have them
END = datetime(2026, 11, 19, 16, 0, tzinfo=UTC)
WL = "/orgs/3/workloads/"


def rec(src, dst, *, port=443, proto=6, direction="outbound", decision="allowed", first=None, last=None, conns=1,
        src_wl=None, dst_wl=None, dst_managed=None, draft=None, allow=(), deny=(), override=()):
    first = first or START + timedelta(hours=1)
    last = last or first + timedelta(minutes=5)
    side = lambda ip, wl, managed: {"ip": ip, **({"workload": {"href": WL + wl, "managed": managed}} if wl else {})}
    r = {"src": side(src, src_wl, True), "dst": side(dst, dst_wl, True if dst_managed is None else dst_managed),
         "service": {"port": port, "proto": proto}, "flow_direction": direction, "policy_decision": decision,
         "num_connections": conns,
         "timestamp_range": {"first_detected": first.isoformat().replace("+00:00", "Z"),
                             "last_detected": last.isoformat().replace("+00:00", "Z")}}
    if draft is not None:
        r.update(draft_policy_decision=draft, rules=[{"href": h} for h in allow],
                 enforcement_boundaries=[{"href": h} for h in deny], override_deny_rules=[{"href": h} for h in override])
    return r


def flows(*raws, draft=False):
    return [kpis.parse_flow(r, draft=draft) for r in raws]


# ── the algorithms ─────────────────────────────────────────────────────────────

def test_pairing_takes_the_inbound_record_within_the_gap():
    t = START + timedelta(hours=2)
    out = rec("10.0.0.1", "10.0.0.2", first=t)
    near = rec("10.0.0.1", "10.0.0.2", direction="inbound", first=t + timedelta(minutes=8))
    far = rec("10.0.0.1", "10.0.0.2", direction="inbound", first=t + timedelta(hours=3))
    pairs = kpis.pair(flows(out, near, far))
    assert len(pairs) == 2
    assert [(p.direction, q.direction if q else None) for p, q in pairs] == [("outbound", "inbound"), ("inbound", None)]


def test_traffic_sources_and_destinations():
    a = rec("10.0.0.1", "10.0.0.9", src_wl="1")
    b = rec("10.0.0.2", "10.0.0.9", decision="blocked")
    c = rec("10.0.0.2", "10.0.0.8", first=END + timedelta(hours=1))  # after the period: not counted
    d = rec("10.0.0.3", "10.0.0.7", first=START - timedelta(hours=1), last=START + timedelta(hours=1))  # reaches in
    e = rec("10.0.0.4", "10.0.0.6", first=START - timedelta(hours=2), last=START - timedelta(hours=1))  # before
    prim = flows(a, b, c, d, e)
    assert kpis.traffic_values(prim, START, END, frozenset()) == {"sources": 3, "destinations": 2}
    assert kpis.traffic_values(prim, START, END, frozenset({"blocked"})) == {"sources": 1, "destinations": 1}
    assert kpis.traffic_values([], START, END, frozenset()) == {"sources": None, "destinations": None}


def test_unmanaged_addresses_by_rollup_day():
    day = datetime(2026, 11, 18, 3, tzinfo=UTC)
    prim = flows(rec("8.8.8.8", "10.0.0.9", dst_wl="9", first=day),            # public, into a workload
                 rec("10.0.0.9", "192.168.1.5", src_wl="9", first=day),         # private, from a workload
                 rec("10.0.0.7", "10.0.0.8", first=day),                        # neither end a workload: not counted
                 rec("8.8.4.4", "10.0.0.9", dst_wl="9", first=day + timedelta(days=5)))  # another day
    assert kpis.unmanaged_values(prim, "2026-11-17", "2026-11-19") == {"total": 2, "private": 1, "public": 1}


def test_rule_usage_from_the_draft():
    sets = [{"href": "/rs/1", "rules": [{"href": "/r/a", "enabled": True}, {"href": "/r/b", "enabled": True},
                                       {"href": "/r/c", "enabled": False}],
             "deny_rules": [{"href": "/d/1"}, {"href": "/d/2"}]}]
    pairs = kpis.pair(flows(
        rec("10.0.0.1", "10.0.0.2", draft="allowed", allow=["/r/a"]),
        rec("10.0.0.1", "10.0.0.3", draft="potentially_blocked", allow=["/r/b"]),  # not allowed: /r/b took no effect
        rec("10.0.0.1", "10.0.0.4", draft="blocked_by_boundary", deny=["/d/1"]),
        rec("10.0.0.1", "10.0.0.5", draft="blocked", conns=7),                     # nothing allows or denies it
        rec("10.0.0.1", "10.0.0.6", draft="unknown", conns=100), draft=True))
    hits = kpis.rule_hits(pairs)
    # the potentially blocked one names /r/b but nothing allowed it: a default block, its 1 connection counts too
    assert hits.hit == {"/r/a", "/d/1"} and hits.no_rule_connections == 8
    assert kpis.policy_usage_values(sets, hits) == {"used": 1, "unused": 1, "deny_hit": 1, "no_rule": 8}


def test_predicted_blocks_into_managed_hosts():
    pairs = kpis.pair(flows(
        rec("10.0.0.1", "10.0.0.2", dst_wl="2", draft="blocked", conns=3),
        rec("10.0.0.1", "10.0.0.3", dst_wl="3", draft="blocked_by_boundary", conns=4),
        rec("10.0.0.1", "10.0.0.4", dst_wl="4", dst_managed=False, draft="blocked", conns=50),  # not managed
        rec("10.0.0.1", "10.0.0.5", dst_wl="5", draft="allowed", conns=9), draft=True))
    p = kpis.predicted(pairs)
    assert (p.blocked_flows, p.blocked_connections, p.undetermined_flows) == (2, 7, 0) and p.value() == 7
    none = kpis.predicted(kpis.pair(flows(rec("10.0.0.1", "10.0.0.2", dst_wl="2", draft="unknown"), draft=True)))
    assert none.value() is None  # nothing blocked while some had no decision: not a confirmed zero


def _audit_raw(i, et, kind=None, name=None, t=None):
    r = ev(i, t or START + timedelta(hours=i), et)
    if kind:
        r["created_by"] = {kind: {"username" if kind == "user" else "name": name}}
    return r


def test_audit_numbers():
    raws = [_audit_raw(1, "request.authentication_failed", "system", "sys"),
            _audit_raw(2, "sec_policy.create", "user", "ann"), _audit_raw(3, "sec_rule.update", "user", "ann"),
            _audit_raw(4, "agent.tampering", "ven", "host1"), _audit_raw(5, "rule_set.create", "service_account", "bot"),
            _audit_raw(6, "request.authorization_failed", "user", "bob")]
    evs = [kpis.parse_audit_event(r) for r in raws]
    assert kpis.audit_values(evs) == {"total": 6, "high_risk": 2, "auth_failed": 1, "authz_denied": 1,
                                      "policy_provisions": 1, "draft_changes": 2, "agent_security": 1, "actors": 3}
    assert kpis.provisions_value(evs) == 1
    assert kpis.audit_values([]) == dict.fromkeys(kpis.audit_values(evs)) and kpis.provisions_value([]) is None


def test_every_appendix_kpi_is_recomputed_or_has_a_reason():
    assert set(kpis.KPI_KEYS) == set(reports.ORDER)
    total = sum(len(v) for v in kpis.KPI_KEYS.values())
    recomputed = sum(len(v) for v in kpis.RECOMPUTED.values())
    assert (total, recomputed) == (93, 19)
    for t, keys in kpis.KPI_KEYS.items():
        for k in keys:
            assert (k in kpis.RECOMPUTED.get(t, ())) != ((t, k) in kpis.REASONS), (t, k)


# ── windows and filters ──────────────────────────────────────────────────────────

def test_day_windows_never_cross_a_utc_midnight():
    w = reports.day_windows(START, END)
    assert w[0] == (START, datetime(2026, 11, 17, 23, 59, 59, tzinfo=UTC))
    assert w[-1] == (datetime(2026, 11, 19, tzinfo=UTC), END) and len(w) == 3
    assert all(a.date() == b.date() for a, b in w)
    assert reports.whole_days("2026-11-17", "2026-11-18")[1] == (datetime(2026, 11, 18, tzinfo=UTC),
                                                                 datetime(2026, 11, 18, 23, 59, 59, tzinfo=UTC))


def test_only_decisions_are_carried():
    assert reports.carried_decisions({"filter": None}) == frozenset()
    assert reports.carried_decisions({"filter": {"decisions": ["blocked"], "src": None, "ports": [],
                                                 "dst": {"labels": [], "hosts": []}}}) == {"blocked"}
    with pytest.raises(reports.CannotCheck, match="src"):
        reports.carried_decisions({"filter": {"src": {"labels": [{"key": "app", "values": ["web"]}]}}})


# ── a fake PCE: async traffic queries, draft rule sets, events ─────────────────────

class FakePce:
    def __init__(self, records=(), *, rule_sets=(), evs=(), update_rules=202, delete=204, poll_status=None):
        self.records, self.rule_sets, self.evs = list(records), list(rule_sets), list(evs)
        self.update_rules, self.delete, self.poll_status = update_rules, delete, poll_status
        self.queries, self.calls = {}, []

    def request(self, method, path, *, json=None, org_scoped=True, **kw):
        self.calls.append((method, path))
        if method == "POST" and path == "/traffic_flows/async_queries":
            href = f"/orgs/3/traffic_flows/async_queries/q{len(self.queries) + 1}"
            self.queries[href] = {"payload": json, "deleted": False}
            return PceResponse(202, _j({"href": href}))
        if method == "DELETE":
            self.queries[path]["deleted"] = self.delete in (200, 202, 204)
            if self.delete == "raise":
                raise OSError("network down")
            return PceResponse(self.delete, b"")
        if method == "PUT" and path.endswith("/update_rules"):
            return PceResponse(self.update_rules, b"")
        if method == "GET" and path.endswith("/download"):
            return PceResponse(200, "\n".join(_j(r).decode() for r in self._rows(path[:-9])).encode())
        if method == "GET" and path in self.queries:
            if self.poll_status:
                return PceResponse(self.poll_status, b"")
            return PceResponse(200, _j({"status": "completed", "rules": "completed",
                                        "flows_count": len(self._rows(path))}))
        if method == "GET" and path.startswith("/sec_policy/draft/rule_sets"):
            return PceResponse(200, _j(self.rule_sets))
        if method == "GET" and path.startswith("/events?"):
            q = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
            lo, hi = (datetime.fromisoformat(q[k]) for k in ("timestamp[gte]", "timestamp[lte]"))
            sel = [e for e in self.evs if lo <= datetime.fromisoformat(e["timestamp"]) <= hi]
            return PceResponse(200, _j(sel[: int(q["max_results"])]))
        raise AssertionError(f"unexpected {method} {path}")

    def _rows(self, href):
        p = self.queries[href]["payload"]
        lo, hi = (datetime.fromisoformat(p[k]) for k in ("start_date", "end_date"))
        dec = p["policy_decisions"]
        rows = [r for r in self.records
                if datetime.fromisoformat(r["timestamp_range"]["first_detected"]) <= hi
                and datetime.fromisoformat(r["timestamp_range"]["last_detected"]) >= lo
                and (not dec or r["policy_decision"] in dec)]
        return rows[: p["max_results"]]

    def close(self):
        pass


def _j(x):
    return json.dumps(x).encode()


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(reports, "_sleep", lambda s: None)
    monkeypatch.setattr(events, "_sleep", lambda s: None)


def _payload(**kw):
    return {"start_date": "2026-11-18T00:00:00Z", "end_date": "2026-11-18T23:59:59Z", "max_results": 10,
            "policy_decisions": [], **kw}


def test_the_query_is_deleted_even_when_it_fails():
    pce = FakePce(poll_status=500)
    left = []
    with pytest.raises(reports.QueryFailed, match="HTTP 500"):
        reports.run_query(pce, _payload(), draft=False, leftovers=left)
    assert ("DELETE", "/orgs/3/traffic_flows/async_queries/q1") in pce.calls and left == []


def test_a_failed_delete_is_a_leftover():
    for delete in (500, "raise"):
        pce = FakePce([rec("10.0.0.1", "10.0.0.2", first=datetime(2026, 11, 18, 1, tzinfo=UTC))], delete=delete)
        left = []
        got = reports.run_query(pce, _payload(), draft=False, leftovers=left)
        assert len(got.rows) == 1 and left == ["/orgs/3/traffic_flows/async_queries/q1"]


def test_update_rules_404_is_unsupported_and_still_deleted():
    pce = FakePce(update_rules=404)
    left = []
    with pytest.raises(reports.DraftUnsupported):
        reports.run_query(pce, _payload(), draft=True, leftovers=left)
    assert pce.calls[-1][0] == "DELETE" and left == []


def test_a_full_window_is_halved_and_one_still_full_is_listed():
    day = datetime(2026, 11, 18, tzinfo=UTC)
    spread = [rec(f"10.0.1.{i}", "10.0.0.2", first=day + timedelta(hours=2 * i)) for i in range(8)]
    got = reports.fetch(FakePce(spread), [(day, day + timedelta(hours=23, minutes=59, seconds=59))],
                        decisions=frozenset(), draft=False, max_results=4, leftovers=[])
    assert len(got.flows) == 8 and got.capped == [] and got.queries > 1
    burst = [rec(f"10.0.1.{i}", "10.0.0.2", first=day + timedelta(hours=5), last=day + timedelta(hours=5))
             for i in range(8)]  # all in one instant: halving cannot separate them
    got = reports.fetch(FakePce(burst), [(day, day + timedelta(hours=23, minutes=59, seconds=59))],
                        decisions=frozenset(), draft=False, max_results=4, leftovers=[])
    assert got.capped


# ── the whole area ─────────────────────────────────────────────────────────────

def _run(tmp_path, pce):
    paths = resolve_paths(tmp_path / "root")
    paths.ensure_dirs()
    store = SettingsStore(paths.settings_file)
    store.create_initial(password_hash=cached_hash("illumio"), secret_key="ab" * 32)
    s = store.update(store.current().revision,
                     lambda d: d["pce"].update(url=URL, org_id="3", api_key="k", api_secret="s"))
    start, end = cli.period(NOW, 7, 30)
    return Run(paths=paths, settings=s, pce=pce, start=start, end=end, now=NOW)


def _reports(run, *rows):
    """rows: (report_type, {kpi: value}, params filter or None)."""
    conn = connect(run.paths.app_db)
    try:
        migrate(conn)
        for rtype, values, flt in rows:
            conn.execute(
                "INSERT INTO reports (report_type, params_json, status, trigger, pce_label, period_start, period_end, "
                "created_at, kpis_json, pce_target) VALUES (?, ?, 'done', 'manual', 'x', ?, ?, ?, ?, ?)",
                (rtype, json.dumps({"report_type": rtype, "filter": flt}), START.isoformat(), END.isoformat(),
                 (END + timedelta(hours=1)).isoformat(), json.dumps([{"key": k, "value": v} for k, v in values.items()]),
                 pce_target(URL, "3")))
        conn.commit()
    finally:
        conn.close()


def _by(findings, status=None, item=None):
    return [f for f in findings if (status is None or f.status == status) and (item is None or item in f.item)]


def test_traffic_and_unmanaged_against_the_reports(tmp_path):
    t = datetime(2026, 11, 18, 3, tzinfo=UTC)
    records = [rec("8.8.8.8", "10.0.0.9", dst_wl="9", first=t), rec("10.0.0.9", "192.168.1.5", src_wl="9", first=t),
               rec("10.0.0.9", "192.168.1.5", src_wl="9", direction="inbound", first=t)]
    pce = FakePce(records)
    run = _run(tmp_path, pce)
    _reports(run, ("traffic", {"flows": 2, "connections": 2, "sources": 2, "destinations": 2}, None),
             ("unmanaged_endpoints", {"total": 2, "private": 1, "admin_sources": 0, "public": 2}, None))
    f = reports.check(run)
    assert [x.detail.split(".")[0] for x in _by(f, "consistent", "traffic #")] == ["report 2, recomputed 2"] * 2
    bad = _by(f, "inconsistent", "unmanaged_endpoints")
    assert len(bad) == 1 and "public" in bad[0].item
    assert "report 2, recomputed 1, difference -1 (-50.0%)" in bad[0].detail
    assert _by(f, "unchecked", "traffic #1: flows") and _by(f, "unchecked", "unmanaged_endpoints #2: admin_sources")
    assert all(q["deleted"] for q in pce.queries.values())


def test_every_kpi_of_a_report_is_listed_and_missing_types_are_said(tmp_path):
    run = _run(tmp_path, FakePce())
    _reports(run, ("lateral_posture", {"pivots": 3}, None))
    f = reports.check(run)
    lat = _by(f, None, "lateral_posture #")
    assert len(lat) == 4 and all(x.status == "unchecked" and "not recomputable" in x.detail for x in lat)
    missing = _by(f, "unchecked", "audit")
    assert len(missing) == 1 and "no finished report" in missing[0].detail
    assert not _by(f, "consistent")


def test_a_filter_not_carried_leaves_the_numbers_unchecked(tmp_path):
    pce = FakePce()
    run = _run(tmp_path, pce)
    _reports(run, ("traffic", {"sources": 1, "destinations": 1},
                   {"src": {"labels": [{"key": "app", "values": ["web"]}]}}))
    f = _by(reports.check(run), None, "traffic #")
    assert {x.status for x in f} == {"unchecked"} and any("does not carry" in x.detail for x in f)
    assert not pce.queries  # nothing was asked


def test_a_truncated_answer_leaves_the_numbers_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "F_MAX_RESULTS", 2)
    t = datetime(2026, 11, 18, 3, tzinfo=UTC)
    pce = FakePce([rec(f"10.0.1.{i}", "10.0.0.2", first=t, last=t) for i in range(5)])
    run = _run(tmp_path, pce)
    _reports(run, ("traffic", {"sources": 5, "destinations": 1}, None))
    f = _by(reports.check(run), None, "traffic #1: sources")
    assert f[0].status == "unchecked" and "limit" in f[0].detail


def test_draft_numbers_and_a_leftover(tmp_path):
    t = datetime(2026, 11, 18, 3, tzinfo=UTC)
    records = [rec("10.0.0.1", "10.0.0.2", dst_wl="2", first=t, draft="allowed", allow=["/r/a"], conns=2),
               rec("10.0.0.1", "10.0.0.3", dst_wl="3", first=t, draft="blocked", conns=5)]
    sets = [{"href": "/orgs/3/sec_policy/draft/rule_sets/1", "rules": [{"href": "/r/a"}, {"href": "/r/b"}],
             "deny_rules": []}]
    pce = FakePce(records, rule_sets=sets, delete=500)
    run = _run(tmp_path, pce)
    _reports(run, ("policy_usage", {"rules": 2, "used": 1, "unused": 1, "disabled": 0, "deny_hit": 0, "no_rule": 5,
                                    "rhc_hit": None, "rhc_zero": None, "rhc_no_record": None}, None),
             ("readiness", {"apps": 2, "ready": 0, "held_back": 0, "overall": None, "predicted_blocked": 4}, None))
    f = reports.check(run)
    assert len(_by(f, "consistent", "policy_usage #")) == 4
    assert all("POST /reports" in x.detail for x in _by(f, None, ": rhc_"))
    bad = _by(f, "inconsistent", "readiness #2: predicted_blocked")
    assert bad and "report 4, recomputed 5" in bad[0].detail
    assert run.cache[reports.LEFTOVERS] and _by(f, "unchecked", "traffic queries left")


def test_events_numbers_against_the_audit_and_weekly_reports(tmp_path):
    evs = [_audit_raw(1, "sec_policy.create", "user", "ann"), _audit_raw(2, "user.sign_in", "user", "bob"),
           _audit_raw(3, "sec_policy.create", "user", "ann", t=END)]  # at the end: not in the period
    run = _run(tmp_path, FakePce(evs=evs))
    _reports(run, ("audit", {"total": 2, "high_risk": 0, "auth_failed": 0, "authz_denied": 0, "policy_provisions": 1,
                             "draft_changes": 0, "agent_security": 0, "actors": 2, "source_ips": 0}, None),
             ("weekly_overview", {"provisions": 2}, None))
    f = reports.check(run)
    assert len(_by(f, "consistent", "audit #")) == 8 and _by(f, "unchecked", "audit #1: source_ips")
    assert _by(f, "inconsistent", "weekly_overview #2: provisions")


def test_main_writes_leftovers_at_the_top(tmp_path, monkeypatch):
    t = datetime(2026, 11, 18, 3, tzinfo=UTC)
    pce = FakePce([rec("10.0.0.1", "10.0.0.2", first=t)], delete=500)
    run = _run(tmp_path, pce)
    _reports(run, ("traffic", {"sources": 1, "destinations": 1}, None))
    monkeypatch.setitem(cli.CHECKS, "events", lambda r: [])
    monkeypatch.setitem(cli.CHECKS, "alerts", lambda r: [])
    out = tmp_path / "out"
    cli.main(["reports", "--root", str(run.paths.root), "--out", str(out)], now=NOW, pce_factory=lambda s: pce)
    md = (out / "report.md").read_text()
    assert "## Leftovers on the PCE" in md and "/orgs/3/traffic_flows/async_queries/q1" in md
    assert json.loads((out / "findings.json").read_text())["meta"]["leftovers"]


def test_a_full_page_of_rule_sets_is_not_compared(tmp_path):
    t = datetime(2026, 11, 18, 3, tzinfo=UTC)
    sets = [{"href": f"/orgs/3/sec_policy/draft/rule_sets/{i}", "rules": [], "deny_rules": []}
            for i in range(reports.GET_PAGE_LIMIT)]
    pce = FakePce([rec("10.0.0.1", "10.0.0.2", first=t, draft="allowed", allow=["/r/a"])], rule_sets=sets)
    run = _run(tmp_path, pce)
    _reports(run, ("policy_usage", {"used": 1, "unused": 0, "deny_hit": 0, "no_rule": 0}, None))
    f = _by(reports.check(run), None, "policy_usage #1: used")
    assert f[0].status == "unchecked" and "full page" in f[0].detail


def test_one_report_failing_leaves_the_others(tmp_path, monkeypatch):
    def boom(run, r, leftovers):
        raise RuntimeError("secret-ish detail that must not be written")
    monkeypatch.setitem(reports.RECOMPUTE, "traffic", boom)
    evs = [_audit_raw(1, "sec_policy.create", "user", "ann")]
    run = _run(tmp_path, FakePce(evs=evs))
    _reports(run, ("traffic", {"sources": 1, "destinations": 1}, None), ("weekly_overview", {"provisions": 1}, None))
    f = reports.check(run)
    t = _by(f, None, "traffic #1: sources")
    assert t[0].status == "unchecked" and "RuntimeError" in t[0].detail and "secret-ish" not in t[0].detail
    assert _by(f, "consistent", "weekly_overview #2: provisions")
    assert len(_by(f, None, "traffic #1")) == 4  # its other numbers are still listed


# ── .106 triage (2026-11-20): what the first real run showed ──────────────────────

def test_draft_change_events_are_recognised():
    t = START
    raws = [_audit_raw(1, "rule_sets.delete", t=t), _audit_raw(2, "rule_set.create", t=t),
            _audit_raw(3, "sec_rule.update", t=t), _audit_raw(4, "workload.update", t=t),
            _audit_raw(5, "workload.online", t=t), _audit_raw(6, "sec_policy.create", t=t),
            _audit_raw(7, "user.sign_in", t=t), _audit_raw(8, "ip_list.update", t=t),
            _audit_raw(9, "workloads.set_labels", t=t), _audit_raw(10, "workloads.remove_labels", t=t),
            _audit_raw(11, "workloads.bulk_create", t=t), _audit_raw(12, "workloads.apply_policy", t=t)]
    got = kpis.draft_changes([kpis.parse_audit_event(r) for r in raws])
    assert set(got) == {"rule_sets.delete", "rule_set.create", "sec_rule.update", "workload.update", "ip_list.update",
                        "workloads.set_labels", "workloads.remove_labels", "workloads.bulk_create",
                        "workloads.apply_policy"}


def _draft_setup(tmp_path, evs, records):
    sets = [{"href": "/orgs/3/sec_policy/draft/rule_sets/1", "rules": [{"href": "/r/a"}], "deny_rules": []}]
    pce = FakePce(records, rule_sets=sets, evs=evs)
    run = _run(tmp_path, pce)
    _reports(run, ("policy_usage", {"used": 1, "unused": 0, "deny_hit": 0, "no_rule": 0}, None),
             ("readiness", {"predicted_blocked": 0}, None))
    return run, pce


def test_a_draft_changed_after_the_report_leaves_the_draft_numbers_unchecked(tmp_path):
    t = datetime(2026, 11, 18, 3, tzinfo=UTC)
    changed = [_audit_raw(1, "rule_sets.delete", "user", "ann", t=NOW - timedelta(hours=2))]  # after the report ran
    run, pce = _draft_setup(tmp_path, changed, [rec("10.0.0.1", "10.0.0.2", first=t, draft="allowed", allow=["/r/a"])])
    f = reports.check(run)
    for item in ("policy_usage #1: used", "policy_usage #1: no_rule", "readiness #2: predicted_blocked"):
        got = _by(f, None, item)
        assert got[0].status == "unchecked" and "changed after the report ran" in got[0].detail, item
    assert not pce.queries  # no draft recompute was spent on it


def test_weekly_records_leave_the_draft_numbers_unchecked(tmp_path):
    week = datetime(2026, 11, 16, tzinfo=UTC)
    long = rec("10.0.0.1", "10.0.0.2", first=week, last=week + timedelta(days=6), draft="allowed", allow=["/r/a"])
    run, _ = _draft_setup(tmp_path, [], [long])
    f = reports.check(run)
    for item in ("policy_usage #1: no_rule", "readiness #2: predicted_blocked"):
        got = _by(f, None, item)
        assert got[0].status == "unchecked" and "by the week" in got[0].detail, item
