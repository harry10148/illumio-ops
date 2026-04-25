import csv, io, json, os, tempfile
from datetime import datetime, timezone

import pytest
from src.config import ConfigManager, hash_password


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "cache.sqlite")

    # Pre-seed the DeadLetter table before the app starts reading it.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import DeadLetter

    engine = create_engine(f"sqlite:///{db_path}")
    init_schema(engine)
    sf = sessionmaker(engine)
    with sf.begin() as s:
        s.add(DeadLetter(
            source_table="pce_events", source_id=1,
            destination="demo", retries=3,
            last_error="timeout", payload_preview='{"k":"v"}',
            quarantined_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ))
        s.add(DeadLetter(
            source_table="pce_events", source_id=2,
            destination="other", retries=1,
            last_error="connection refused", payload_preview="{}",
            quarantined_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ))

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        salt = "testsalt"
        h = hash_password(salt, "pw")
        with open(path, "w") as f:
            json.dump({
                "web_gui": {
                    "username": "admin",
                    "password_hash": h,
                    "password_salt": salt,
                    "secret_key": "s",
                    "allowed_ips": ["127.0.0.1"],
                },
                "pce_cache": {
                    "enabled": True,
                    "db_path": db_path,
                },
            }, f)

        cm = ConfigManager(config_file=path)
        from src.gui import _create_app
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            c.post("/api/login", json={"username": "admin", "password": "pw"},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            yield c
    finally:
        os.unlink(path)


def test_dlq_export_all(client):
    resp = client.get("/api/siem/dlq/export",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert rows[0] == ["id", "destination", "source_table", "source_id",
                       "retries", "last_error", "payload_preview", "quarantined_at"]
    assert len(rows) >= 3  # header + 2 data rows
    destinations = {r[1] for r in rows[1:]}
    assert "demo" in destinations and "other" in destinations


def test_dlq_export_filtered_by_destination(client):
    resp = client.get("/api/siem/dlq/export?dest=demo",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert len(rows) == 2  # header + 1 data row
    assert rows[1][1] == "demo"


def test_dlq_export_filtered_no_match(client):
    resp = client.get("/api/siem/dlq/export?dest=nosuch",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert len(rows) == 1  # header only


def test_dlq_export_filtered_by_reason(client):
    resp = client.get("/api/siem/dlq/export?reason=timeout",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert len(rows) == 2  # header + 1 data row (only "demo" has "timeout")
    assert rows[1][5] == "timeout"


def test_dlq_export_content_disposition(client):
    resp = client.get("/api/siem/dlq/export",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "dlq.csv" in resp.headers["Content-Disposition"]
