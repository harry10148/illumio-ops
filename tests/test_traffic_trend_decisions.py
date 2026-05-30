"""/api/traffic/trend returns a per-day breakdown by policy decision.

The old endpoint returned a single `flows` total per day, which the UI drew as a
context-free area chart. It now splits each day into allowed / potentially_blocked
/ blocked so the trend carries an actionable security signal.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch


def _seed_db(path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.models import PceTrafficFlowAgg
    from src.pce_cache.schema import init_schema

    engine = create_engine(f"sqlite:///{path}")
    init_schema(engine)
    today = datetime.datetime.now(datetime.timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    yest = today - datetime.timedelta(days=1)
    # (day, action, port, flow_count) — port varied to satisfy the agg unique key
    rows = [
        (yest, "allowed", 443, 60), (yest, "allowed", 80, 40),
        (yest, "potentially_blocked", 22, 20), (yest, "blocked", 3389, 5),
        (today, "allowed", 443, 200), (today, "potentially_blocked", 22, 10),
    ]
    with sessionmaker(engine)() as s:
        for day, action, port, fc in rows:
            s.add(PceTrafficFlowAgg(bucket_day=day, src_workload="a", dst_workload="b",
                                    port=port, protocol="tcp", action=action, flow_count=fc,
                                    bytes_total=fc * 1000))
        s.commit()
    return today.date().isoformat(), yest.date().isoformat()


def _client(tmp_path):
    from src.gui import _create_app
    db = tmp_path / "cache.sqlite"
    today, yest = _seed_db(db)
    cm = MagicMock()
    cm.config = {"settings": {"language": "en"}, "api": {"url": "https://pce.example.com:8443"},
                 "rules": [], "report": {"output_dir": "/tmp/test-reports"}}
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.db_path = str(db)
    app = _create_app(cm)
    app.config["TESTING"] = True
    return app.test_client(), today, yest


def test_trend_splits_by_decision(tmp_path):
    client, today, yest = _client(tmp_path)
    with patch("flask_login.utils._get_user", return_value=MagicMock(is_authenticated=True)):
        resp = client.get("/api/traffic/trend")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    by_day = {b["ts"]: b for b in data["buckets"]}
    assert by_day[yest]["allowed"] == 100
    assert by_day[yest]["potential"] == 20
    assert by_day[yest]["blocked"] == 5
    assert by_day[today]["allowed"] == 200
    assert by_day[today]["potential"] == 10
    assert by_day[today]["blocked"] == 0
    # ordered oldest-first
    assert [b["ts"] for b in data["buckets"]] == [yest, today]
