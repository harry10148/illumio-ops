"""One filter model, three executions: PCE payload (+ residual), SQL over the flow store, and a
per-record predicate. SQL and predicate must agree on every spec."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from illumio_ops.domain.filter import (
    EndpointFilter,
    FilterSpec,
    LabelCond,
    PortProto,
    matches,
    sql_functions,
    to_pce_payload,
    to_sql,
)
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, PolicyDecision
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.flows import upsert_flows

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "flows_sample.json"
T0 = datetime(2026, 10, 20, tzinfo=UTC)
T1 = datetime(2026, 10, 25, tzinfo=UTC)


def spec(**kw):
    return FilterSpec(start=T0, end=T1, **kw)


def test_spec_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        FilterSpec(start=datetime(2026, 10, 20), end=T1)
    with pytest.raises(ValidationError):
        FilterSpec(start=T1, end=T0)


def test_label_or_within_key_and_across_keys_in_payload():
    hrefs = {("app", "A"): "/l/1", ("app", "B"): "/l/2", ("env", "Prod"): "/l/3"}
    s = spec(src=EndpointFilter(labels=(LabelCond(key="app", values=("A", "B")), LabelCond(key="env", values=("Prod",)))))
    payload, residual = to_pce_payload(s, max_results=100, query_name="q", label_hrefs=hrefs)
    inc = payload["sources"]["include"]
    as_sets = sorted(sorted(x["label"]["href"] for x in group) for group in inc)
    assert as_sets == [["/l/1", "/l/3"], ["/l/2", "/l/3"]]  # (A or B) and Prod
    assert residual.src is None


def test_unresolved_label_keeps_side_local():
    s = spec(src=EndpointFilter(labels=(LabelCond(key="app", values=("Unknown",)),),
                                hrefs=("/orgs/1/workloads/w1",)))
    payload, residual = to_pce_payload(s, max_results=10, query_name="q", label_hrefs={})
    assert payload["sources"]["include"] == [[]]  # a union cannot be half-pushed
    assert residual.src == s.src


def test_user_and_process_go_to_residual():
    s = spec(initiator_user="alice", service_process="sql*", text="db", exclude_system_accounts=True,
             decisions=(PolicyDecision.ALLOWED,), ports=(PortProto(port=445, proto=6),))
    payload, residual = to_pce_payload(s, max_results=10, query_name="q", label_hrefs={})
    assert payload["policy_decisions"] == ["allowed"]
    assert payload["services"]["include"] == [{"port": 445, "proto": 6}]
    assert (residual.initiator_user, residual.service_process, residual.text) == ("alice", "sql*", "db")
    assert residual.exclude_system_accounts is True and residual.decisions == () and residual.ports == ()


def test_cidr_stays_local_exact_ip_goes_to_pce():
    payload, residual = to_pce_payload(spec(dst=EndpointFilter(ips=("10.0.0.5",))), max_results=1, query_name="q",
                                       label_hrefs={})
    assert payload["destinations"]["include"] == [[{"ip_address": "10.0.0.5"}]] and residual.dst is None
    payload, residual = to_pce_payload(spec(dst=EndpointFilter(ips=("10.0.0.0/24",))), max_results=1,
                                       query_name="q", label_hrefs={})
    assert payload["destinations"]["include"] == [[]] and residual.dst is not None


def test_wildcard_escapes_percent_and_underscore():
    where, params = to_sql(spec(initiator_process="a_b%c*"))
    assert "ESCAPE" in where and any(p == "a\\_b\\%c%" for p in params)


def test_cidr_match():
    rec = {"src_ip": "10.0.0.7", "dst_ip": "192.0.2.1", "is_primary": 1}
    assert matches(spec(src=EndpointFilter(ips=("10.0.0.0/24",))), _row(rec))
    assert not matches(spec(src=EndpointFilter(ips=("10.0.1.0/24",))), _row(rec))


def test_exclude_system_accounts():
    assert not matches(spec(exclude_system_accounts=True), _row({"initiator_user": "NT AUTHORITY\\SYSTEM"}))
    assert matches(spec(exclude_system_accounts=True), _row({"initiator_user": "LAB\\alice"}))


def _row(over):
    base = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "src_href": None, "dst_href": None, "src_hostname": None,
            "dst_hostname": None, "src_labels": {}, "dst_labels": {}, "port": 445, "proto": 6,
            "initiator_process": None, "initiator_user": None, "service_process": None, "service_user": None,
            "policy_decision": "allowed", "first_detected": "2026-10-22T00:00:00.000+00:00",
            "last_detected": "2026-10-22T00:10:00.000+00:00", "is_primary": 1}
    return base | over


SPECS = [
    {},
    {"decisions": (PolicyDecision.POTENTIALLY_BLOCKED,)},
    {"ports": (PortProto(port=443, proto=6),)},
    {"ports": (PortProto(port=8000, to_port=9999, proto=6),)},
    {"ports": (PortProto(proto=17),)},
    {"exclude_ports": (PortProto(port=443, proto=6),)},
    {"src": EndpointFilter(ips=("10.0.0.3",))},
    {"src": EndpointFilter(ips=("10.0.0.0/30",))},
    {"dst": EndpointFilter(labels=(LabelCond(key="app", values=("DemoApp",)),))},
    {"dst": EndpointFilter(labels=(LabelCond(key="app", values=("DemoApp", "Nope")), LabelCond(key="env", values=("Server",))))},
    {"src_exclude": EndpointFilter(ips=("10.0.0.3",))},
    {"dst_exclude": EndpointFilter(labels=(LabelCond(key="env", values=("Server",)),))},
    {"initiator_user": "user-0"},
    {"initiator_user": "user-0*"},
    {"initiator_process": "CALICO"},
    {"service_process": "mysql*"},
    {"text": "10.0.0.2"},
    {"text": "host-0"},
    {"exclude_system_accounts": True},
    {"start": T0 + timedelta(days=4, hours=6, minutes=50), "end": T1},
    # P6a final review: an "all" endpoint, exact value sets, a service without a port
    {"dst": EndpointFilter(match="all", labels=(LabelCond(key="app", values=("DemoApp",)),), ips=("10.0.0.0/8",))},
    {"src": EndpointFilter(match="all", labels=(LabelCond(key="env", values=("Server",)),), ips=("10.0.0.3",))},
    {"src": EndpointFilter(match="all", hrefs=("/orgs/1/workloads/a",), ips=("10.0.0.3",))},
    {"initiator_users": ("user-0", "USER-1")},
    {"initiator_processes": ("calico-node", "CALICO")},
    {"service_processes": ("mysqld",)},
    {"service_users": ("root",)},
    {"ports": (PortProto(port=-1, proto=1),)},
    {"exclude_ports": (PortProto(port=-1, proto=6),)},
]


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    db = FlowDb(tmp_path_factory.mktemp("f") / "flows.sqlite")
    conn = db.connect()
    recs = [normalize_flow(r) for r in json.loads(FIXTURE.read_text())]
    upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=T1)
    for name, fn in sql_functions().items():
        conn.create_function(name, -1, fn, deterministic=True)
    labels = {}
    for set_id, key, value in conn.execute("SELECT set_id, key, value FROM label_set_members"):
        labels.setdefault(set_id, {})[key] = value
    rows = []
    for r in conn.execute("SELECT * FROM flows WHERE is_primary = 1"):
        d = dict(r)
        d["src_labels"] = labels.get(d["src_label_set"], {})
        d["dst_labels"] = labels.get(d["dst_label_set"], {})
        rows.append(d)
    yield conn, rows
    conn.close()


@pytest.mark.parametrize("kw", SPECS, ids=[str(i) for i in range(len(SPECS))])
def test_sql_and_predicate_agree_on_fixture(store, kw):
    conn, rows = store
    s = FilterSpec(**({"start": T0, "end": T1} | kw))
    where, params = to_sql(s)
    via_sql = {r[0] for r in conn.execute(f"SELECT f.id FROM flows f WHERE {where}", params)}
    via_predicate = {r["id"] for r in rows if matches(s, r)}
    assert via_sql == via_predicate


def test_public_port_and_endpoint_matchers_agree_with_matches():
    from illumio_ops.domain.filter import (
        EndpointFilter,
        LabelCond,
        PortProto,
        endpoint_matches,
        port_matches,
    )
    assert port_matches(PortProto(port=20, to_port=25, proto=6), 22, 6)
    assert not port_matches(PortProto(port=22, proto=17), 22, 6)
    assert port_matches(PortProto(proto=6), None, 6)
    ep = EndpointFilter(labels=(LabelCond(key="app", values=("fin",)),), ips=("10.0.0.0/8",))
    assert endpoint_matches(ep, href=None, ip="10.1.2.3", labels={})
    assert endpoint_matches(ep, href="/w/1", ip="192.168.0.1", labels={"app": "fin"})
    assert not endpoint_matches(ep, href="/w/1", ip="192.168.0.1", labels={"app": "hr"})


def test_flow_condition_fields_equal_filter_spec_minus_window():
    from illumio_ops.domain.filter import FlowCondition
    assert set(FlowCondition.model_fields) == set(FilterSpec.model_fields) - {"start", "end"}
    for name, f in FlowCondition.model_fields.items():
        assert f.annotation == FilterSpec.model_fields[name].annotation, name
        assert f.default == FilterSpec.model_fields[name].default, name


def test_within_round_trips():
    from illumio_ops.domain.filter import (
        EndpointFilter,
        FlowCondition,
        LabelCond,
        PortProto,
    )
    cond = FlowCondition(src=EndpointFilter(labels=(LabelCond(key="env", values=("Prod",)),)),
                         ports=(PortProto(port=22, proto=6),), decisions=("blocked",), initiator_user="root")
    spec = cond.within(T0, T1)
    assert (spec.start, spec.end) == (T0, T1) and spec.condition() == cond



# ── P6a final review (Codex, 2026-10-30) ─────────────────────────────────────

def test_endpoint_all_is_an_intersection():
    """#3: the workbench's "role=Web and this host" narrows; the default stays the union."""
    from illumio_ops.domain.filter import endpoint_matches
    both = EndpointFilter(match="all", labels=(LabelCond(key="env", values=("Prod",)),), hrefs=("/w/a",))
    either = both.model_copy(update={"match": "any"})
    assert endpoint_matches(both, href="/w/a", ip="1.1.1.1", labels={"env": "Prod"})
    assert not endpoint_matches(both, href="/w/b", ip="1.1.1.1", labels={"env": "Prod"})
    assert endpoint_matches(either, href="/w/b", ip="1.1.1.1", labels={"env": "Prod"})


def test_endpoint_all_hosts_are_one_part():
    """Two hosts picked on one side, one by href and one by address (no workload), are either host: the hosts
    together are one condition, intersected with the labels."""
    from illumio_ops.domain.filter import endpoint_matches
    ep = EndpointFilter(match="all", labels=(LabelCond(key="env", values=("Prod",)),), hrefs=("/w/a",), ips=("9.9.9.9",))
    assert endpoint_matches(ep, href="/w/a", ip="1.1.1.1", labels={"env": "Prod"})
    assert endpoint_matches(ep, href=None, ip="9.9.9.9", labels={"env": "Prod"})
    assert not endpoint_matches(ep, href="/w/b", ip="1.1.1.1", labels={"env": "Prod"})
    assert not endpoint_matches(ep, href="/w/a", ip="1.1.1.1", labels={"env": "Dev"})


def test_exact_values_are_not_partial():
    """#5: choosing bash does not take in bash-helper; domain accounts compare case-insensitively."""
    s = spec(initiator_processes=("bash",), initiator_users=("CORP\\Alice",))
    assert matches(s, _row({"initiator_process": "bash", "initiator_user": "corp\\alice"}))
    assert not matches(s, _row({"initiator_process": "bash-helper", "initiator_user": "corp\\alice"}))


def test_no_port_is_not_any_port():
    """#6: -1 is "no port"; a protocol alone still means any port."""
    s = spec(ports=(PortProto(port=-1, proto=6),))
    assert matches(s, _row({"port": None, "proto": 6})) and not matches(s, _row({"port": 443, "proto": 6}))
    assert matches(spec(ports=(PortProto(proto=6),)), _row({"port": 443, "proto": 6}))


def test_new_conditions_stay_local_in_the_payload():
    """What the PCE cannot filter goes to the residual, never to a wider payload."""
    s = spec(ports=(PortProto(port=-1, proto=6),), initiator_processes=("bash",),
             dst=EndpointFilter(match="all", labels=(LabelCond(key="app", values=("A",)),), hrefs=("/w/a",)))
    payload, residual = to_pce_payload(s, max_results=10, query_name="q", label_hrefs={("app", "A"): "/l/1"})
    assert payload["services"]["include"] == [] and residual.ports == s.ports
    assert payload["destinations"]["include"] == [[]] and residual.dst == s.dst
    assert residual.initiator_processes == ("bash",)
