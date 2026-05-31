import datetime as dt, json, os, tempfile
import pytest
from src.config import ConfigManager


@pytest.fixture
def app_cm(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw", "secret_key": "s",
                               "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": True, "db_path": str(tmp_path / "c.sqlite")},
                   "siem": {"enabled": True}}, f)
    cm = ConfigManager(config_file=path)
    yield cm, tmp_path
    os.unlink(path)


def _client(cm):
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True; app.config["WTF_CSRF_ENABLED"] = False
    c = app.test_client()
    c.post("/api/login", json={"username": "admin", "password": "pw"},
           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    return c


def _seed_dispatch(db, rows):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import SiemDispatch
    eng = create_engine(f"sqlite:///{db}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        for r in rows:
            s.add(SiemDispatch(**r))
        s.commit()


def test_siem_status_has_1h_window_and_latency(app_cm):
    cm, tmp = app_cm
    now = dt.datetime.now(dt.timezone.utc)
    _seed_dispatch(str(tmp / "c.sqlite"), [
        dict(source_table="pce_events", source_id=1, destination="d1", status="sent",
             retries=0, queued_at=now - dt.timedelta(minutes=10),
             sent_at=now - dt.timedelta(minutes=9)),           # latency ~60s, in 1h
        dict(source_table="pce_events", source_id=2, destination="d1", status="failed",
             retries=3, queued_at=now - dt.timedelta(minutes=5), sent_at=None),  # failed in 1h
        dict(source_table="pce_events", source_id=3, destination="d1", status="sent",
             retries=0, queued_at=now - dt.timedelta(hours=3),
             sent_at=now - dt.timedelta(hours=3)),             # old, outside 1h
    ])
    c = _client(cm)
    body = c.get("/api/siem/status", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    d1 = next(x for x in body["status"] if x["destination"] == "d1")
    assert d1["sent_1h"] == 1 and d1["failed_1h"] == 1
    assert d1["success_1h"] == 50.0
    assert d1["avg_latency_ms"] is not None and d1["avg_latency_ms"] > 0
