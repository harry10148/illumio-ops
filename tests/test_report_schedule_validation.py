"""BUG-2（2026-07-24 審查）：報表排程 CRUD 須驗證 cron/hour/minute/
day_of_month/schedule_type——畸形值原本 verbatim 存下、tick 靜默不跑無訊號。"""
import json
import os
import tempfile

import pytest

from src.config import ConfigManager
from src.gui import build_app as _create_app
from tests._helpers import _csrf


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw",
                               "secret_key": "s", "allowed_ips": ["127.0.0.1"]}}, f)
    cm = ConfigManager(config_file=path)
    from src.config import hash_password
    cm.config["web_gui"]["password"] = hash_password("testpass")
    cm.save()
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True
    with app.test_client() as c:
        login = c.post("/api/login", json={"username": "admin", "password": "testpass"},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        c._csrf = _csrf(login)
        yield c
    os.unlink(path)


def _post(c, body):
    return c.post("/api/report-schedules", json=body,
                  headers={"X-CSRF-Token": c._csrf},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})


def test_malformed_cron_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic", "cron_expr": "not a cron"})
    assert r.status_code == 400


def test_hour_out_of_range_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "daily", "hour": 25, "minute": 0})
    assert r.status_code == 400


def test_minute_out_of_range_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "daily", "hour": 8, "minute": 99})
    assert r.status_code == 400


def test_day_of_month_out_of_range_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "monthly", "day_of_month": 32, "hour": 8, "minute": 0})
    assert r.status_code == 400


def test_unknown_schedule_type_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "hourly", "hour": 8, "minute": 0})
    assert r.status_code == 400


def test_valid_daily_accepted(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "daily", "hour": 8, "minute": 30})
    assert r.status_code == 200


def test_valid_cron_accepted(client):
    r = _post(client, {"name": "x", "report_type": "traffic", "cron_expr": "0 8 * * MON-FRI"})
    assert r.status_code == 200
