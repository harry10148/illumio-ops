"""VEN fleet overview: counts from the inventory with the VEN status report's own online and sync definitions, and the
host list filtered by mode, environment label and online state."""
from datetime import UTC, datetime, timedelta

from illumio_ops.services import fleet
from illumio_ops.services.fleet import FleetFilter
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb import workloads
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 11, 6, 9, tzinfo=UTC)


def _stamp(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def wl(href, hostname, mode, *, version="23.2.0", os_id="ubuntu", online=1, beat=timedelta(minutes=5),
       sync="applied", label_set=None, managed=1, applied=True, fetched_at="2026-11-06T08:55:00.000Z"):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=managed, enforcement_mode=mode, visibility_level=None,
        os_id=os_id, ven_version=version, ven_href=None, label_set=label_set, online=online, risk_exposure=None,
        risk_percent=None, risk_updated_at=None, fetched_at=fetched_at, agent_status="active",
        last_heartbeat_at=None if beat is None else _stamp(beat), policy_sync_state=sync,
        policy_applied_at=_stamp(timedelta(hours=1)) if applied else None)


def seed(ctx, rows_of):
    with ctx.flows().connect() as conn:
        prod = label_store.label_set_id(conn, (("app", "web"), ("env", "Prod")))
        dev = label_store.label_set_id(conn, (("app", "db"), ("env", "Dev")))
        workloads.replace_inventory(conn, rows_of(prod, dev))
        conn.commit()


def _rows(prod, dev):
    return [
        wl("/orgs/1/workloads/a", "web-01", "visibility_only", label_set=prod),
        wl("/orgs/1/workloads/b", "web-02", "visibility_only", label_set=prod, sync="syncing"),
        wl("/orgs/1/workloads/c", "db-01", "full", version="23.4.0", label_set=dev),
        wl("/orgs/1/workloads/d", "db-02", "idle", os_id="windows", online=0, beat=timedelta(hours=30), label_set=dev),
        wl("/orgs/1/workloads/e", None, "selective", beat=None, sync=None),
    ]


def test_overview_counts(tmp_path):
    ctx = configured_ctx(tmp_path)
    seed(ctx, _rows)
    o = fleet.overview(ctx, now=NOW)
    assert o.total == 5 and o.env_key == "env"
    assert [(t.value, t.hosts) for t in o.modes] == [("idle", 1), ("visibility_only", 2), ("selective", 1), ("full", 1)]
    assert [(t.value, t.hosts) for t in o.versions] == [("23.2.0", 4), ("23.4.0", 1)]
    assert [(t.value, t.hosts) for t in o.systems] == [("ubuntu", 4), ("windows", 1)]
    # the VEN status report's buckets: no heartbeat reported is unknown, never offline
    assert o.online == {"online": 3, "lost_24h": 0, "lost_48h": 1, "long_offline": 0, "unknown": 1}
    assert [(t.value, t.hosts) for t in o.sync_states] == [("applied", 3), ("syncing", 1), (None, 1)]
    assert o.sync_problems == 1  # web-02's "syncing"; the offline one is not held against it
    assert o.environments == ["Dev", "Prod"]


def test_list_filters(tmp_path):
    ctx = configured_ctx(tmp_path)
    seed(ctx, _rows)

    def names(**kw):
        return [h.name for h in fleet.host_list(ctx, FleetFilter(**kw), now=NOW).hosts]

    assert names() == ["db-01", "db-02", "web-01", "web-02", None]  # the nameless last
    assert names(mode="visibility_only") == ["web-01", "web-02"]
    assert names(env="Dev") == ["db-01", "db-02"]
    assert names(no_env=True) == [None]  # no environment label
    assert names(online="lost_48h") == ["db-02"]
    assert names(q="WEB-0", mode="visibility_only", env="Prod") == ["web-01", "web-02"]
    assert names(mode="unknown") == []
    h = fleet.host_list(ctx, FleetFilter(q="web-02"), now=NOW).hosts[0]
    assert (h.key, h.env, h.app, h.problems) == ("/orgs/1/workloads/b", "Prod", "web", ["sync_state"])


def test_list_is_bounded(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    seed(ctx, _rows)
    monkeypatch.setattr(fleet, "LIST_MAX", 2)
    got = fleet.host_list(ctx, FleetFilter(), now=NOW)
    assert (got.total, len(got.hosts), got.limit_hit) == (5, 2, True)


def test_empty_inventory_is_zero_not_missing(tmp_path):
    ctx = configured_ctx(tmp_path)
    o = fleet.overview(ctx, now=NOW)
    assert o.total == 0 and o.fetched_at is None and o.modes == []


def test_a_host_online_at_the_last_inventory_read_stays_online_until_the_next(tmp_path):
    """.106, 2026-11-06: the inventory is read once an hour and copies each heartbeat (sent every few minutes); aged
    against the clock, every host read 58 minutes ago with a heartbeat 5 minutes older than the read showed as lost.
    Online is what the PCE said at the read; how old that read is, the page says beside it (fetched_at)."""
    ctx = configured_ctx(tmp_path)
    read = (NOW - timedelta(minutes=58)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    seed(ctx, lambda prod, dev: [
        wl("/orgs/1/workloads/a", "web-01", "selective", beat=timedelta(minutes=63), fetched_at=read),
        wl("/orgs/1/workloads/d", "db-02", "idle", online=0, beat=timedelta(hours=3), fetched_at=read)])
    o = fleet.overview(ctx, now=NOW)
    assert o.online == {"online": 1, "lost_24h": 1, "lost_48h": 0, "long_offline": 0, "unknown": 0}
    assert {h.name: h.online for h in fleet.host_list(ctx, FleetFilter(), now=NOW).hosts} == {
        "web-01": "online", "db-02": "lost_24h"}
