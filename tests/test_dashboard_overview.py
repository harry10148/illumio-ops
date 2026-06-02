import json, os, tempfile
import pytest
from src.config import ConfigManager
import src.dashboard_store as dashboard_store


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw",
                               "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": False, "db_path": str(tmp_path / "c.sqlite")}}, f)
    cm = ConfigManager(config_file=path)
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True; app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c
    os.unlink(path)


def test_overview_ven_verdict_from_state(client, tmp_path, monkeypatch):
    # _overview_ven now reads from dashboard store, not state.json
    ds_path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: ds_path)
    dashboard_store.write_dashboard_summary(lambda d: {**d, "ven_summary": {
        "total": 21, "online": 19, "offline": 2,
        "degraded": 0, "oldest_heartbeat_age_s": 147600,
        "attention": [{"host": "x", "reason": "41h no heartbeat"}],
    }})
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    ven = r.get_json()["ven"]
    assert ven["online"] == 19 and ven["offline"] == 2
    assert ven["verdict"] == "warn"           # offline>=1, not over 10% of 21 (=3)
    assert "as_of" in r.get_json()


def test_overview_ven_unknown_when_missing(client, tmp_path, monkeypatch):
    # No dashboard store file → _overview_ven returns unknown
    ds_path = str(tmp_path / "dashboard_summary.json")
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: ds_path)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ven"]["verdict"] == "unknown"


def test_overview_alerts_from_state(client, tmp_path, monkeypatch):
    from src.gui import _helpers
    sf = str(tmp_path / "state.json")
    json.dump({"dispatch_history": [
                  {"timestamp": "2026-05-31T00:00:00Z", "channel": "line", "status": "success"},
                  {"timestamp": "2026-05-31T00:01:00Z", "channel": "mail", "status": "failed"}],
               "throttle_state": {"r1": {"suppressed": 8}}}, open(sf, "w"))
    monkeypatch.setattr(_helpers, "_resolve_state_file", lambda: sf)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    al = r.get_json()["alerts"]
    assert al["failed"] >= 1 and al["verdict"] == "warn"
    assert "recent" in al


def test_overview_pipeline_present(client, monkeypatch):
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    pl = r.get_json()["pipeline"]
    assert "verdict" in pl   # ok/warn/error/unknown depending on cache availability


def test_overview_blocked_from_agg(client, tmp_path):
    import datetime as dt
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceTrafficFlowAgg
    eng = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}"); init_schema(eng)
    today = dt.datetime.now(dt.timezone.utc)
    rows = [("allowed", 100, today), ("blocked", 30, today),
            ("potentially_blocked", 70, today)]
    with sessionmaker(eng)() as s:
        for i, (act, n, day) in enumerate(rows):
            s.add(PceTrafficFlowAgg(bucket_day=day, src_workload="a", dst_workload="b",
                                    port=440 + i, protocol="TCP", action=act, flow_count=n))
        s.commit()
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    blocked = r.get_json()["blocked"]
    assert blocked["blocked"] == 30 and blocked["potential"] == 70 and blocked["allowed"] == 100
    assert blocked["verdict"] == "ok"   # no spike vs prev window
