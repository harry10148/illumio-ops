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
                   "pce_cache": {"enabled": True, "db_path": str(tmp_path / "c.sqlite")}}, f)
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
    import datetime as dt
    from src.gui import _helpers
    # _overview_alerts only counts dispatches within the last 24h, so use recent
    # timestamps rather than hardcoded dates (which age out of the window).
    now = dt.datetime.now(dt.timezone.utc)
    ts1 = (now - dt.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts2 = (now - dt.timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sf = str(tmp_path / "state.json")
    json.dump({"dispatch_history": [
                  {"timestamp": ts1, "channel": "line", "status": "success"},
                  {"timestamp": ts2, "channel": "mail", "status": "failed"}],
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


def test_overview_includes_job_health(client, tmp_path, monkeypatch):
    """2026-07-16 可觀測性 backlog：overview 必須回 job_health 清單，
    從未跑過（registered 超過 2×interval）與逾期的 job 標 warn。"""
    import datetime
    from src import job_health as jh
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(jh, "_job_health_file", lambda: path)
    import src.gui.routes.dashboard as dash
    monkeypatch.setattr(dash.job_health, "_job_health_file", lambda: path,
                        raising=False)
    now = datetime.datetime.now(datetime.timezone.utc)
    old = (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump({
        "pce_cache_archive": {"last_status": "registered",
                               "registered_at": old, "interval_seconds": 3600},
        "ven_summary": {"last_run": fresh, "last_status": "ok",
                         "detail": "", "interval_seconds": 300},
        "pce_cache_retention": {"last_run": old, "last_status": "ok",
                                 "detail": "", "interval_seconds": 1800},
        "monitor_cycle": {"last_run": fresh, "last_status": "error",
                           "detail": "boom", "interval_seconds": 30},
    }, open(path, "w"))
    r = client.get("/api/dashboard/overview",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    body = r.get_json()
    levels = {e["job_id"]: e["level"] for e in body["job_health"]}
    assert levels["pce_cache_archive"] == "warn"      # never ran
    assert levels["pce_cache_retention"] == "warn"    # overdue（3h > 2×30m）
    assert levels["ven_summary"] == "ok"
    assert levels["monitor_cycle"] == "error"
    order = [e["level"] for e in body["job_health"]]
    assert order == sorted(order, key=lambda v: {"error": 0, "warn": 1, "ok": 2}[v])


def test_overview_includes_tls(client, monkeypatch):
    import src.gui.routes.dashboard as dash
    monkeypatch.setattr(dash, "_tls_overview",
                        lambda cm: {"enabled": True, "days_remaining": 12,
                                    "expiring_soon": True})
    r = client.get("/api/dashboard/overview",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    body = r.get_json()
    assert body["tls"]["days_remaining"] == 12
    assert body["tls"]["expiring_soon"] is True


def test_overview_job_health_tolerates_corrupt_entries(client, tmp_path, monkeypatch):
    """壞的 job_health.json 條目（非數字 interval_seconds）應被跳過，
    不影響其他條目或端點回傳 200."""
    import datetime
    from src import job_health as jh
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(jh, "_job_health_file", lambda: path)
    import src.gui.routes.dashboard as dash
    monkeypatch.setattr(dash.job_health, "_job_health_file", lambda: path,
                        raising=False)
    now = datetime.datetime.now(datetime.timezone.utc)
    fresh = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump({
        "bad_job": {"last_run": fresh, "last_status": "ok",
                    "interval_seconds": "not-a-number"},
        "good_job": {"last_run": fresh, "last_status": "ok",
                     "detail": "", "interval_seconds": 300},
    }, open(path, "w"))
    r = client.get("/api/dashboard/overview",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    body = r.get_json()
    job_ids = {e["job_id"] for e in body["job_health"]}
    assert "good_job" in job_ids
    assert "bad_job" not in job_ids
