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


# ── public: a public address no Workload holds (user 2026-10-31: alert rules leave the internet side out) ──

PUBLIC_SPECS = [
    {"src": EndpointFilter(public=True)},
    {"dst": EndpointFilter(public=True)},
    {"src_exclude": EndpointFilter(public=True)},
    {"dst_exclude": EndpointFilter(public=True)},
    {"src": EndpointFilter(public=True, ips=("10.0.0.1",))},
    {"src": EndpointFilter(match="all", labels=(LabelCond(key="app", values=("DemoApp",)),), public=True)},
]


@pytest.fixture(scope="module")
def public_store(tmp_path_factory):
    from dataclasses import replace
    db = FlowDb(tmp_path_factory.mktemp("p") / "flows.sqlite")
    conn = db.connect()
    base = normalize_flow(json.loads(FIXTURE.read_text())[0])
    ends = [("10.0.0.1", "/orgs/1/workloads/a", "10.0.0.2", None), ("66.132.186.241", None, "114.35.37.162", None),
            ("10.0.0.1", "/orgs/1/workloads/a", "8.8.8.8", None),
            ("203.69.10.5", "/orgs/1/workloads/pub", "10.0.0.2", None)]
    recs = [replace(base, src_ip=s, src_href=sh, dst_ip=d, dst_href=dh, port=1000 + i)
            for i, (s, sh, d, dh) in enumerate(ends)]
    upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=T1)
    for name, fn in sql_functions().items():
        conn.create_function(name, -1, fn, deterministic=True)
    rows = [dict(r) | {"src_labels": {}, "dst_labels": {}} for r in conn.execute("SELECT * FROM flows WHERE is_primary = 1")]
    yield conn, rows
    conn.close()


@pytest.mark.parametrize("kw", PUBLIC_SPECS, ids=[str(i) for i in range(len(PUBLIC_SPECS))])
def test_public_sql_and_predicate_agree(public_store, kw):
    conn, rows = public_store
    s = FilterSpec(**({"start": T0, "end": T1} | kw))
    where, params = to_sql(s)
    via_sql = {r[0] for r in conn.execute(f"SELECT f.id FROM flows f WHERE {where}", params)}
    assert via_sql == {r["id"] for r in rows if matches(s, r)}


def test_public_means_outside_the_estate(public_store):
    _conn, rows = public_store
    s = spec(src_exclude=EndpointFilter(public=True), dst_exclude=EndpointFilter(public=True))
    kept = sorted((r["src_ip"], r["dst_ip"]) for r in rows if matches(s, r))
    # the internet scan and the egress are out; a Workload numbered in public space is inside
    assert kept == [("10.0.0.1", "10.0.0.2"), ("203.69.10.5", "10.0.0.2")]


def test_public_is_a_condition_and_stays_local_for_the_pce():
    assert not EndpointFilter(public=True).is_empty()
    s = spec(src=EndpointFilter(public=True), dst_exclude=EndpointFilter(public=True, ips=("10.0.0.9",)))
    payload, residual = to_pce_payload(s, max_results=10, query_name="q", label_hrefs={})
    assert payload["sources"]["include"] == [[]]
    assert residual.src == s.src
    assert payload["destinations"]["exclude"] == [{"ip_address": "10.0.0.9"}]
    assert residual.dst_exclude == s.dst_exclude


def test_endpoint_matches_public():
    from illumio_ops.domain.filter import endpoint_matches
    ep = EndpointFilter(public=True)
    assert endpoint_matches(ep, href=None, ip="8.8.8.8", labels={})
    assert not endpoint_matches(ep, href="/w/1", ip="8.8.8.8", labels={})
    assert not endpoint_matches(ep, href=None, ip="10.1.2.3", labels={})


# ── ip_lists: a PCE IP list by href, its networks from the inventory (user 2026-10-31) ──

NETS = {"/orgs/1/sec_policy/active/ip_lists/9": ("114.35.37.0/24", "8.8.8.8/32")}
IPL = "/orgs/1/sec_policy/active/ip_lists/9"
IP_LIST_SPECS = [
    {"dst": EndpointFilter(ip_lists=(IPL,))},
    {"dst_exclude": EndpointFilter(ip_lists=(IPL,))},
    {"src": EndpointFilter(ip_lists=("/orgs/1/sec_policy/active/ip_lists/gone",))},
    {"dst": EndpointFilter(ip_lists=(IPL,), ips=("10.0.0.2",))},
]


@pytest.fixture(scope="module")
def ip_list_store(public_store):
    from illumio_ops.store.flowdb import ip_lists
    conn, rows = public_store
    ip_lists.replace_all(conn, [ip_lists.IpListRow(IPL, "Internet edge", NETS[IPL])], at=T1)
    return conn, rows


@pytest.mark.parametrize("kw", IP_LIST_SPECS, ids=[str(i) for i in range(len(IP_LIST_SPECS))])
def test_ip_list_sql_and_predicate_agree(ip_list_store, kw):
    conn, rows = ip_list_store
    s = FilterSpec(**({"start": T0, "end": T1} | kw))
    where, params = to_sql(s)
    via_sql = {r[0] for r in conn.execute(f"SELECT f.id FROM flows f WHERE {where}", params)}
    assert via_sql == {r["id"] for r in rows if matches(s, r, ip_lists=NETS)}


def test_ip_list_matches_its_networks_and_a_deleted_list_nothing():
    from illumio_ops.domain.filter import endpoint_matches
    ep = EndpointFilter(ip_lists=(IPL,))
    assert endpoint_matches(ep, href=None, ip="114.35.37.162", labels={}, ip_lists=NETS)
    assert not endpoint_matches(ep, href=None, ip="10.0.0.2", labels={}, ip_lists=NETS)
    assert not endpoint_matches(ep, href=None, ip="114.35.37.162", labels={}, ip_lists={})
    assert not EndpointFilter(ip_lists=(IPL,)).is_empty()


def test_ip_list_stays_local_for_the_pce():
    s = spec(src=EndpointFilter(ip_lists=(IPL,)), dst_exclude=EndpointFilter(ip_lists=(IPL,)))
    payload, residual = to_pce_payload(s, max_results=10, query_name="q", label_hrefs={})
    assert payload["sources"]["include"] == [[]] and residual.src == s.src
    assert payload["destinations"]["exclude"] == [] and residual.dst_exclude == s.dst_exclude


# ── 5.x parity keys (2026-11-06): either end, label groups, named services, Windows services, transmission,
# excluded processes. Every key is checked on all three executions: SQL, the per-record predicate, the payload. ──

SVC_WEB = "/orgs/1/sec_policy/active/services/web"
SVC_ICMP = "/orgs/1/sec_policy/active/services/icmp"
SVC_ALL = "/orgs/1/sec_policy/active/services/all"
LG_PROD = "/orgs/1/sec_policy/active/label_groups/prod"
LG_EU = "/orgs/1/sec_policy/active/label_groups/eu"
LG_STAGE = "/orgs/1/sec_policy/active/label_groups/stage"  # a second group of the key env
SERVICES = {SVC_WEB: ((443, None, 6), (8000, 8100, 6)), SVC_ICMP: ((None, None, 1),), SVC_ALL: ((None, None, None),)}
GROUPS = {LG_PROD: ("env", frozenset({"Prod", "Staging"})), LG_EU: ("loc", frozenset({"EU"})),
          LG_STAGE: ("env", frozenset({"Staging"}))}

PARITY_SPECS = [
    {"either": EndpointFilter(ips=("10.0.0.9",))},
    {"either_exclude": EndpointFilter(ips=("10.0.0.9",))},
    {"either": EndpointFilter(labels=(LabelCond(key="app", values=("Pay",)),))},
    {"either_exclude": EndpointFilter(public=True)},
    {"src": EndpointFilter(label_groups=(LG_PROD,))},
    {"dst": EndpointFilter(label_groups=(LG_PROD, LG_EU))},
    {"src": EndpointFilter(label_groups=(LG_PROD, LG_STAGE))},  # review 2026-11-06: two groups of one key
    {"src": EndpointFilter(labels=(LabelCond(key="env", values=("Dev",)),), label_groups=(LG_PROD,))},
    {"src": EndpointFilter(labels=(LabelCond(key="app", values=("Pay",)),), label_groups=(LG_PROD,))},
    {"dst_exclude": EndpointFilter(label_groups=(LG_PROD,))},
    {"src": EndpointFilter(label_groups=("/orgs/1/sec_policy/active/label_groups/gone",))},
    {"src": EndpointFilter(match="all", label_groups=(LG_PROD,), ips=("10.0.0.1",))},
    {"services": (SVC_WEB,)},
    {"services": (SVC_ICMP,)},
    {"services": (SVC_ALL,)},
    {"services": (SVC_WEB,), "ports": (PortProto(port=22, proto=6),)},
    {"exclude_services": (SVC_WEB,)},
    {"services": ("/orgs/1/sec_policy/active/services/gone",)},
    {"windows_services": ("wuauserv",)},
    {"windows_services": ("WUAUSERV", "spooler")},
    {"exclude_windows_services": ("wuauserv",)},
    {"transmissions": ("broadcast",)},
    {"transmissions": ("broadcast", "multicast")},
    {"exclude_transmissions": ("broadcast", "multicast")},
    {"exclude_processes": ("svchost.exe",)},
    {"exclude_processes": ("nginx", "svchost.exe")},
]


def _parity_records():
    from dataclasses import replace
    base = normalize_flow(json.loads(FIXTURE.read_text())[0])
    lab = {"prod": (("app", "Pay"), ("env", "Prod"), ("loc", "EU")), "stg": (("env", "Staging"), ("loc", "US")),
           "dev": (("app", "Pay"), ("env", "Dev")), "none": ()}
    rows = [  # src, dst, port, proto, src labels, dst labels, windows service, transmission, process
        ("10.0.0.1", "10.0.0.9", 443, 6, "prod", "stg", "wuauserv", None, "svchost.exe"),
        ("10.0.0.9", "10.0.0.2", 8050, 6, "stg", "prod", None, "unicast", "nginx"),
        ("10.0.0.3", "10.0.0.255", 137, 17, "dev", "none", "Spooler", "broadcast", None),
        ("10.0.0.4", "224.0.0.251", 5353, 17, "none", "none", None, "multicast", "avahi"),
        ("10.0.0.5", "10.0.0.6", None, 1, "prod", "dev", None, None, None),
        ("10.0.0.6", "8.8.8.8", 22, 6, "dev", "none", None, "unicast", "ssh"),
    ]
    out = []
    for i, (s, d, port, proto, sl, dl, win, tx, proc) in enumerate(rows):
        out.append(replace(base, src_ip=s, dst_ip=d, src_href=f"/orgs/1/workloads/s{i}", dst_href=None, port=port,
                           proto=proto, src_labels=lab[sl], dst_labels=lab[dl], windows_service=win, transmission=tx,
                           own_process=proc))
    return out


@pytest.fixture(scope="module")
def parity_store(tmp_path_factory):
    from illumio_ops.store.flowdb import policy_objects
    db = FlowDb(tmp_path_factory.mktemp("parity") / "flows.sqlite")
    conn = db.connect()
    upsert_flows(conn, _parity_records(), origin=DataOrigin.INGEST, now=T1)
    policy_objects.replace_services(conn, [policy_objects.ServiceRow(h, h.rsplit("/", 1)[1], p)
                                           for h, p in SERVICES.items()], at=T1)
    policy_objects.replace_label_groups(conn, [policy_objects.LabelGroupRow(h, h.rsplit("/", 1)[1], k, tuple(sorted(v)))
                                               for h, (k, v) in GROUPS.items()], at=T1)
    for name, fn in sql_functions().items():
        conn.create_function(name, -1, fn, deterministic=True)
    labels = {}
    for set_id, key, value in conn.execute("SELECT set_id, key, value FROM label_set_members"):
        labels.setdefault(set_id, {})[key] = value
    rows = [dict(r) | {"src_labels": labels.get(r["src_label_set"], {}), "dst_labels": labels.get(r["dst_label_set"], {})}
            for r in conn.execute("SELECT * FROM flows WHERE is_primary = 1")]
    assert len(rows) == 6
    yield conn, rows
    conn.close()


@pytest.mark.parametrize("kw", PARITY_SPECS, ids=[str(i) for i in range(len(PARITY_SPECS))])
def test_parity_keys_sql_and_predicate_agree(parity_store, kw):
    conn, rows = parity_store
    s = FilterSpec(**({"start": T0, "end": T1} | kw))
    where, params = to_sql(s)
    via_sql = {r[0] for r in conn.execute(f"SELECT f.id FROM flows f WHERE {where}", params)}
    via_predicate = {r["id"] for r in rows if matches(s, r, label_groups=GROUPS, services=SERVICES)}
    assert via_sql == via_predicate
    # each spec splits the rows, except a deleted object (nothing) and "All Services" (everything)
    assert 0 < len(via_sql) < len(rows) or kw in ({"src": EndpointFilter(label_groups=(
        "/orgs/1/sec_policy/active/label_groups/gone",))}, {"services": ("/orgs/1/sec_policy/active/services/gone",)},
        {"services": (SVC_ALL,)})


def _kept(rows, **kw):
    s = spec(**kw)
    return sorted((r["src_ip"], r["dst_ip"]) for r in rows if matches(s, r, label_groups=GROUPS, services=SERVICES))


def test_either_end_matches_one_end_or_the_other(parity_store):
    _conn, rows = parity_store
    assert _kept(rows, either=EndpointFilter(ips=("10.0.0.9",))) == [("10.0.0.1", "10.0.0.9"), ("10.0.0.9", "10.0.0.2")]
    assert ("10.0.0.1", "10.0.0.9") not in _kept(rows, either_exclude=EndpointFilter(ips=("10.0.0.9",)))


def test_label_group_joins_its_key_and_a_deleted_group_matches_nothing(parity_store):
    _conn, rows = parity_store
    # env in {Prod, Staging} on the source
    assert _kept(rows, src=EndpointFilter(label_groups=(LG_PROD,))) == [
        ("10.0.0.1", "10.0.0.9"), ("10.0.0.5", "10.0.0.6"), ("10.0.0.9", "10.0.0.2")]
    # a label of the same key widens the group (env Dev or the group), another key narrows
    assert ("10.0.0.3", "10.0.0.255") in _kept(rows, src=EndpointFilter(
        labels=(LabelCond(key="env", values=("Dev",)),), label_groups=(LG_PROD,)))
    assert _kept(rows, src=EndpointFilter(label_groups=("/orgs/1/sec_policy/active/label_groups/gone",))) == []
    assert not EndpointFilter(label_groups=(LG_PROD,)).is_empty()


def test_named_service_is_its_ports_and_joins_the_listed_ports(parity_store):
    _conn, rows = parity_store
    assert _kept(rows, services=(SVC_WEB,)) == [("10.0.0.1", "10.0.0.9"), ("10.0.0.9", "10.0.0.2")]
    assert _kept(rows, services=(SVC_ICMP,)) == [("10.0.0.5", "10.0.0.6")]
    assert len(_kept(rows, services=(SVC_WEB,), ports=(PortProto(port=22, proto=6),))) == 3
    assert _kept(rows, services=("/orgs/1/sec_policy/active/services/gone",)) == []


def test_windows_service_transmission_and_process_exclusion(parity_store):
    _conn, rows = parity_store
    assert _kept(rows, windows_services=("WUAUSERV",)) == [("10.0.0.1", "10.0.0.9")]
    assert len(_kept(rows, exclude_windows_services=("spooler",))) == 5  # no service name: not excluded
    assert _kept(rows, transmissions=("broadcast",)) == [("10.0.0.3", "10.0.0.255")]
    assert len(_kept(rows, exclude_transmissions=("broadcast", "multicast"))) == 4
    assert ("10.0.0.1", "10.0.0.9") not in _kept(rows, exclude_processes=("svchost.exe",))
    assert len(_kept(rows, exclude_processes=("svchost.exe",))) == 5


def test_excluded_process_names_are_normalized():
    from illumio_ops.domain.filter import FlowCondition
    assert FlowCondition(exclude_processes=("C:\\Windows\\System32\\SVCHOST.EXE",)).exclude_processes == ("svchost.exe",)


def test_parity_keys_stay_local_for_the_pce():
    s = spec(either=EndpointFilter(ips=("10.0.0.9",)), src=EndpointFilter(label_groups=(LG_PROD,)),
             services=(SVC_WEB,), ports=(PortProto(port=22, proto=6),), exclude_services=(SVC_ICMP,),
             windows_services=("wuauserv",), transmissions=("broadcast",), exclude_processes=("ssh",),
             dst_exclude=EndpointFilter(labels=(LabelCond(key="env", values=("Dev",)),), label_groups=(LG_EU,)))
    payload, residual = to_pce_payload(s, max_results=10, query_name="q", label_hrefs={("env", "Dev"): "/l/9"})
    assert payload["sources"]["include"] == [[]] and residual.src == s.src
    # ports and named services are one set: neither half goes to the PCE alone
    assert payload["services"]["include"] == [] and residual.ports == s.ports and residual.services == s.services
    assert residual.exclude_services == s.exclude_services
    # an exclusion whose labels must hold with a group is never pushed as the label alone
    assert payload["destinations"]["exclude"] == [] and residual.dst_exclude == s.dst_exclude
    for k in ("either", "windows_services", "transmissions", "exclude_processes"):
        assert getattr(residual, k) == getattr(s, k), k


def test_flow_record_view_carries_windows_service_and_transmission():
    rec = _parity_records()[2]
    assert matches(spec(windows_services=("spooler",), transmissions=("broadcast",)), rec)


def test_endpoint_matches_label_groups():
    from illumio_ops.domain.filter import endpoint_matches
    ep = EndpointFilter(label_groups=(LG_PROD,))
    assert endpoint_matches(ep, href=None, ip="10.0.0.1", labels={"env": "Staging"}, label_groups=GROUPS)
    assert not endpoint_matches(ep, href=None, ip="10.0.0.1", labels={"env": "Dev"}, label_groups=GROUPS)
    assert not endpoint_matches(ep, href=None, ip="10.0.0.1", labels={"env": "Prod"}, label_groups={})


def test_hrefs_named_on_every_part():
    from illumio_ops.domain.filter import (
        FlowCondition,
        ip_list_hrefs,
        label_group_hrefs,
        service_hrefs,
    )
    c = FlowCondition(either=EndpointFilter(ip_lists=(IPL,), label_groups=(LG_EU,)),
                      either_exclude=EndpointFilter(label_groups=(LG_PROD,)), services=(SVC_WEB,),
                      exclude_services=(SVC_ICMP,))
    assert ip_list_hrefs(c) == {IPL} and label_group_hrefs(c) == {LG_EU, LG_PROD}
    assert service_hrefs(c) == {SVC_WEB, SVC_ICMP}
