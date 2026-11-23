"""VEN fleet API: authentication, filters, bounded rate requests and their write-key requirement."""
import pytest

from .conftest import LOCAL, login, post

WL = "/orgs/1/workloads/w1"


def test_signed_in_and_csrf(client):
    assert client.get("/api/fleet/overview", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = client.post("/api/fleet/traffic-rate/apply", json={"keys": [WL]}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)
    o = client.get("/api/fleet/overview", environ_overrides=LOCAL)
    assert o.status_code == 200 and o.get_json()["data"]["total"] == 0
    h = client.get("/api/fleet/hosts?mode=full&env=Prod&q=web", environ_overrides=LOCAL)
    assert h.status_code == 200 and h.get_json()["data"]["hosts"] == []
    a = client.get("/api/fleet/actions", environ_overrides=LOCAL)
    assert a.status_code == 200 and a.get_json()["data"]["actions"] == []


def test_list_filter_checked(client):
    login(client)
    r = client.get("/api/fleet/hosts?online=sometimes", environ_overrides=LOCAL)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_input"


def test_no_write_key_is_a_conflict(client):
    login(client)
    r = post(client, "/api/fleet/traffic-rate/apply", {"keys": [WL]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "no_write_key"


def test_enforcement_preview_route_is_gone(client):
    login(client)
    r = post(client, "/api/fleet/enforcement/preview", {"target": "full", "keys": [WL]})
    assert r.status_code == 404


def test_wrong_method_on_a_registered_route_stays_405(client):
    login(client)
    assert client.get("/api/fleet/traffic-rate/check", environ_overrides=LOCAL).status_code == 405


def test_rate_batch_is_bounded(client):
    login(client)
    assert post(client, "/api/fleet/traffic-rate/check", {"keys": [WL] * 51}).status_code == 400


# ── finding a host on the VEN overview (2026-11-12: it is the one way in to hosts) ──

def _fleet(ctx):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.alert_devices import Device
    from illumio_ops.domain.alerting import Confidence, Trigger
    from illumio_ops.domain.values import AlertRuleType, Severity
    from illumio_ops.store import alerts as store
    from illumio_ops.store.flowdb import labels as label_store
    from illumio_ops.store.flowdb import workloads
    from tests.e2e.test_fleet_e2e import _wl
    now = datetime.now(UTC)
    w = "/orgs/1/workloads/"
    with ctx.flows().connect() as conn:
        prod = label_store.label_set_id(conn, (("app", "Payroll"), ("env", "Prod")))
        held = label_store.label_set_id(conn, (("Quarantine", "Severe"), ("env", "Dev")))
        workloads.replace_inventory(conn, [
            replace(_wl(w + "a", "web-01", "selective", prod, now), addresses_json='["10.1.2.3", "fe80::1"]',
                    os_id="ubuntu-x86_64-noble", ven_version="26.2.20-2063"),
            replace(_wl(w + "b", "db-02", "idle", held, now), last_heartbeat_at=(now - timedelta(hours=30)).isoformat()),
            _wl(w + "c", "app-03", "selective", None, now)])
        conn.commit()
    pce = ctx.settings.current().pce
    for keys in ([w + "a"], [w + "a", "ip:192.168.20.99"], ["ip:192.168.20.99"]):
        t = Trigger(rule_id="c" * 32, rule_type=AlertRuleType.EVENT, subject_key=keys[0], severity=Severity.HIGH,
                    first_seen=now, last_seen=now, late=False, message_key="alert_system_disk_low", params={}, facts={},
                    evidence=None, confidence=Confidence())
        with ctx.db() as conn:
            store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key=None,
                               trigger=replace(t, devices=tuple(Device(k, "subject") for k in keys)), at=now,
                               channels=["line"], hold=None)
    return w


def _hosts(client, query=""):
    return client.get(f"/api/fleet/hosts{query}", environ_overrides=LOCAL).get_json()["data"]


@pytest.mark.parametrize("q, found", [
    ("WEB", ["web-01"]),            # its name, any case
    ("10.1.2", ["web-01"]),         # one of its addresses
    ("fe80", ["web-01"]),
    ("payroll", ["web-01"]),        # a label's value
    ("noble", ["web-01"]),          # its operating system
    ("26.2.20", ["web-01"]),        # its VEN version
    ("severe", ["db-02"]),
    ("0", ["app-03", "db-02", "web-01"]),
    ("nothing-like-this", []),
])
def test_the_search_finds_a_host_by_any_of_what_names_it(client, ctx, q, found):
    _fleet(ctx)
    login(client)
    assert [h["name"] for h in _hosts(client, f"?q={q}")["hosts"]] == found


def test_the_quick_filters_and_their_counts(client, ctx):
    w = _fleet(ctx)
    login(client)
    data = _hosts(client)
    assert data["groups"] == {"alerted": 1, "lost": 1, "quarantined": 1, "all": 3}
    by = {h["key"]: h for h in data["hosts"]}
    assert (by[w + "a"]["alerts"], by[w + "a"]["addresses"], by[w + "b"]["quarantine"]) == (2, ["10.1.2.3", "fe80::1"], "Severe")
    assert [h["name"] for h in _hosts(client, "?group=alerted")["hosts"]] == ["web-01"]
    assert [h["name"] for h in _hosts(client, "?group=lost")["hosts"]] == ["db-02"]
    assert [h["name"] for h in _hosts(client, "?group=quarantined")["hosts"]] == ["db-02"]
    # a count is what pressing it would list: counted under the search
    assert _hosts(client, "?q=web")["groups"] == {"alerted": 1, "lost": 0, "quarantined": 0, "all": 1}
    assert client.get("/api/fleet/hosts?group=else", environ_overrides=LOCAL).status_code == 400


def test_an_alerted_address_the_pce_does_not_manage_is_named_beside_the_list(client, ctx):
    _fleet(ctx)
    login(client)
    assert _hosts(client)["unmanaged"] == []  # the plain list is the managed hosts
    assert _hosts(client, "?group=alerted")["unmanaged"] == [{"key": "ip:192.168.20.99", "name": "192.168.20.99", "alerts": 2}]
    assert [u["name"] for u in _hosts(client, "?q=192.168.20")["unmanaged"]] == ["192.168.20.99"]
    assert _hosts(client, "?group=lost")["unmanaged"] == []
