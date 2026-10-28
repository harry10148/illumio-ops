"""Settings › Lateral movement: the settings with the effective ports, label choices and analysis status."""
from illumio_ops.store.flowdb import ransomware, workloads
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.services.collect.conftest import NOW

from .conftest import LOCAL, csrf, login


def _get(client):
    return client.get("/api/system/lateral", environ_overrides=LOCAL).get_json()["data"]


def _put(client, body):
    return client.open("/api/system/lateral", method="PUT", json=body, environ_overrides=LOCAL,
                       headers={"X-CSRFToken": csrf(client)})


def _inventory(ctx, labels):
    with ctx.flows().connect() as conn:
        rows = []
        for i, pairs in enumerate(labels):
            rows.append(workloads.WorkloadRow(
                href=f"/orgs/1/workloads/w{i}", hostname=f"h{i}", name=None, managed=1, enforcement_mode=None,
                visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=label_set_id(conn, pairs),
                online=1, risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x"))
        workloads.replace_inventory(conn, rows)


def test_get_returns_effective_ports_with_sources(client, ctx):
    login(client)
    with ctx.flows().connect() as conn:
        ransomware.upsert_services(conn, "/orgs/1/workloads/w1", [
            {"name": "VNC", "port": 5900, "proto": 6, "severity": "high", "category": "admin"}],
            source_updated_at=None, at=NOW)
    data = _get(client)
    sources = {(p["port"], p["source"]) for p in data["effective_ports"]}
    assert (445, "builtin") in sources and (5900, "pce") in sources
    assert data["settings"]["graph_hops"] == 3 and data["revision"] >= 0
    st = data["status"]
    assert st["collected"] is True and st["baseline_required"] == 30 and st["detectors"] == []
    assert st["observation_days_used"] == 30


def test_put_validates_and_bumps_revision(client, ctx):
    login(client)
    data = _get(client)
    data["settings"]["critical_assets"] = [{"key": "app", "value": "Finance"}]
    data["settings"]["observation_days"] = 60  # beyond the baseline: accepted, the graph uses 30
    r = _put(client, {"revision": data["revision"], "settings": data["settings"]})
    out = r.get_json()["data"]
    assert r.status_code == 200 and out["revision"] == data["revision"] + 1
    assert ctx.settings.current().lateral.critical_assets[0].value == "Finance"
    assert out["status"]["observation_days_used"] == 30
    bad = dict(out["settings"], graph_hops=0)
    r = _put(client, {"revision": out["revision"], "settings": bad})
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["field"] == "settings.graph_hops"


def test_put_stale_revision_conflict(client, ctx):
    login(client)
    data = _get(client)
    assert _put(client, {"revision": data["revision"], "settings": data["settings"]}).status_code == 200
    r = _put(client, {"revision": data["revision"], "settings": data["settings"]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "stale_revision"


def test_label_choices_truncation_flag(client, ctx, monkeypatch):
    from illumio_ops.services.analysis import status as lateral_status
    monkeypatch.setattr(lateral_status, "MAX_LABEL_VALUES", 2)
    login(client)
    _inventory(ctx, [(("app", "a"),), (("app", "b"),), (("app", "c"), ("env", "Prod"))])
    choices = {c["key"]: c for c in _get(client)["label_choices"]}
    assert choices["app"]["values"] == ["a", "b"] and choices["app"]["truncated"] is True
    assert choices["env"] == {"key": "env", "values": ["Prod"], "truncated": False}


def test_lightweight_status_says_mode_required(client, ctx):
    login(client)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update({"mode": "lightweight"}))
    assert _get(client)["status"]["collected"] is False
