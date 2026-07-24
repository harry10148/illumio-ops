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


def test_pipeline_verdict_thresholds():
    from src.pce_cache.health import pipeline_verdict
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=100.0, denom=10, dlq=0) == "ok"
    assert pipeline_verdict(lag_levels=["warning"], siem_success_1h=100.0, denom=10, dlq=0) == "warn"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=98.0, denom=10, dlq=0) == "warn"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=100.0, denom=10, dlq=1) == "warn"
    assert pipeline_verdict(lag_levels=["error"], siem_success_1h=100.0, denom=10, dlq=0) == "error"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=90.0, denom=10, dlq=0) == "error"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=100.0, denom=0, dlq=0) == "ok"  # no traffic


def test_pipeline_verdict_siem_idle_is_warn():
    """SIEM enabled but idle (no enabled destination, or has data yet zero
    24h enqueue) must not be green: 2026-07-16 scan caught the denom=0
    short-circuit reading "SIEM completely stalled" as ok."""
    from src.pce_cache.health import pipeline_verdict
    assert pipeline_verdict(lag_levels=[], siem_success_1h=100.0,
                            denom=0, dlq=0, siem_idle=True) == "warn"
    assert pipeline_verdict(lag_levels=[], siem_success_1h=100.0,
                            denom=0, dlq=0, siem_idle=False) == "ok"


def test_overview_pipeline_flags_siem_idle_when_no_enabled_destination(tmp_path):
    """siem.enabled=true with all destinations disabled -> pipeline verdict
    warn/error and siem_idle True."""
    from sqlalchemy import create_engine
    from src.pce_cache.schema import init_schema
    db_path = str(tmp_path / "c.sqlite")
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw", "secret_key": "s",
                               "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": True, "db_path": db_path},
                   "siem": {"enabled": True, "destinations": [
                       {"name": "x", "enabled": False, "host": "h", "port": 514}]}}, f)
    init_schema(create_engine(f"sqlite:///{db_path}"))
    cm = ConfigManager(config_file=path)
    c = _client(cm)
    body = c.get("/api/dashboard/overview",
                 environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    os.unlink(path)
    assert body["pipeline"]["siem_idle"] is True
    assert body["pipeline"]["verdict"] in ("warn", "error")


def test_siem_status_has_1h_window_and_latency(app_cm):
    cm, tmp = app_cm
    now = dt.datetime.now(dt.timezone.utc)
    _seed_dispatch(str(tmp / "c.sqlite"), [
        dict(source_table="pce_events", source_id=1, destination="d1", status="sent",
             retries=0, queued_at=now - dt.timedelta(minutes=10),
             sent_at=now - dt.timedelta(minutes=9)),           # latency ~60s, in 1h
        # 真實斷線形狀：3 小時前 queued、5 分鐘前才 quarantine。failed_1h 必須
        # 錨定失敗時間（DeadLetter.quarantined_at），錨在 queued_at 會讓整段
        # 斷線期間回報 100% 成功。
        dict(source_table="pce_events", source_id=2, destination="d1", status="failed",
             retries=10, queued_at=now - dt.timedelta(hours=3), sent_at=None),
        dict(source_table="pce_events", source_id=3, destination="d1", status="sent",
             retries=0, queued_at=now - dt.timedelta(hours=3),
             sent_at=now - dt.timedelta(hours=3)),             # old, outside 1h
    ])
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.models import DeadLetter
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}")
    with sessionmaker(eng)() as s:
        s.add(DeadLetter(source_table="pce_events", source_id=2, destination="d1",
                         retries=10, last_error="connrefused", payload_preview="{}",
                         quarantined_at=now - dt.timedelta(minutes=5)))
        s.commit()
    c = _client(cm)
    body = c.get("/api/siem/status", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    d1 = next(x for x in body["status"] if x["destination"] == "d1")
    assert d1["sent_1h"] == 1 and d1["failed_1h"] == 1
    assert d1["success_1h"] == 50.0
    assert d1["avg_latency_ms"] is not None and d1["avg_latency_ms"] > 0


def test_siem_status_counts_retrying_rows_and_null_success_when_idle(app_cm):
    """斷線初期（尚未 quarantine）retry backoff 中的列要算進 failed_1h，
    視窗內無任何嘗試時 success_1h 必須是 null（unknown），不得假報 100。"""
    cm, tmp = app_cm
    now = dt.datetime.now(dt.timezone.utc)
    _seed_dispatch(str(tmp / "c.sqlite"), [
        # d2：目的地掛掉、列還在 backoff（pending + retries>0 + next_attempt_at 未來）
        dict(source_table="pce_events", source_id=1, destination="d2", status="pending",
             retries=3, queued_at=now - dt.timedelta(minutes=30),
             next_attempt_at=now + dt.timedelta(minutes=2), sent_at=None),
        # d3：只有 1h 視窗外的活動 → 成功率未知
        dict(source_table="pce_events", source_id=2, destination="d3", status="sent",
             retries=0, queued_at=now - dt.timedelta(hours=3),
             sent_at=now - dt.timedelta(hours=3)),
    ])
    c = _client(cm)
    body = c.get("/api/siem/status", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    d2 = next(x for x in body["status"] if x["destination"] == "d2")
    assert d2["failed_1h"] == 1
    assert d2["success_1h"] == 0.0
    d3 = next(x for x in body["status"] if x["destination"] == "d3")
    assert d3["sent_1h"] == 0 and d3["failed_1h"] == 0
    assert d3["success_1h"] is None


def test_dlq_item_rebuilds_full_payload(app_cm):
    cm, tmp = app_cm
    import datetime as dt
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import DeadLetter, PceEvent
    now = dt.datetime.now(dt.timezone.utc)
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        ev = PceEvent(pce_href="/x", pce_event_id="ev1", timestamp=now,
                      event_type="agent.tampering", severity="err", status="active",
                      pce_fqdn="pce.local", raw_json='{"full":"event-body"}',
                      ingested_at=now)
        s.add(ev); s.flush()
        s.add(DeadLetter(source_table="pce_events", source_id=ev.id, destination="d1",
                         retries=3, last_error="connrefused", payload_preview='{"full":"eve',
                         quarantined_at=now))
        s.commit()
        dl_id = s.execute(__import__("sqlalchemy").select(DeadLetter.id)).scalar()
    c = _client(cm)
    body = c.get(f"/api/siem/dlq/{dl_id}", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body["id"] == dl_id
    assert body["last_error"] == "connrefused"
    assert "event-body" in (body["payload"] or "")   # full payload rebuilt from source row


def test_cache_throughput_last_1h(app_cm):
    cm, tmp = app_cm
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceEvent
    now = dt.datetime.now(dt.timezone.utc)
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        s.add(PceEvent(pce_href="/a", pce_event_id="e1", timestamp=now,
                       event_type="x", severity="info", status="ok",
                       pce_fqdn="pce.local", raw_json="{}",
                       ingested_at=now - dt.timedelta(minutes=5)))
        s.add(PceEvent(pce_href="/b", pce_event_id="e2", timestamp=now,
                       event_type="x", severity="info", status="ok",
                       pce_fqdn="pce.local", raw_json="{}",
                       ingested_at=now - dt.timedelta(hours=3)))
        s.commit()
    c = _client(cm)
    body = c.get("/api/cache/throughput", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body["events_1h"] == 1


def test_dlq_replay_by_ids(app_cm):
    cm, tmp = app_cm
    import datetime as dt
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import DeadLetter, SiemDispatch
    now = dt.datetime.now(dt.timezone.utc)
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        s.add(DeadLetter(source_table="pce_events", source_id=7, destination="d1",
                         retries=3, last_error="x", payload_preview="{}", quarantined_at=now))
        s.commit()
        dl_id = s.execute(select(DeadLetter.id)).scalar()
    c = _client(cm)
    body = c.post("/api/siem/dlq/replay", json={"ids": [dl_id]},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body["status"] == "ok"
    assert any(r["id"] == dl_id and r["ok"] for r in body["requeued"])
    with sessionmaker(eng)() as s:                  # a pending dispatch row was created
        pend = s.execute(select(func.count()).select_from(SiemDispatch)
                         .where(SiemDispatch.status == "pending")).scalar()
        assert pend == 1
