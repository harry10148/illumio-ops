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


# ── report_type whitelist (2026-08-28 backlog #2) ───────────────────────────
# The validator checked every field about *when* a schedule fires and nothing
# about *what* it produces, so an unknown report_type was stored verbatim and
# surfaced only as a logger.error + skip on every tick.

def test_unknown_report_type_rejected(client):
    r = _post(client, {"name": "x", "report_type": "not_a_real_type",
                       "schedule_type": "daily", "hour": 1, "minute": 0})
    assert r.status_code == 400
    assert "report_type" in r.get_json().get("error", "").lower()


def test_unknown_report_type_rejected_on_cron_schedules_too(client):
    """The cron branch returns early; report_type must be checked before it."""
    r = _post(client, {"name": "x", "report_type": "not_a_real_type",
                       "cron_expr": "0 8 * * MON-FRI"})
    assert r.status_code == 400
    assert "report_type" in r.get_json().get("error", "").lower()


def test_every_valid_report_type_accepted(client):
    """More important than the rejection test: a whitelist that is too strict
    blocks operators from creating legitimate schedules."""
    from src.report_scheduler import VALID_REPORT_TYPES
    for rtype in sorted(VALID_REPORT_TYPES):
        body = {"name": f"s-{rtype}", "report_type": rtype,
                "schedule_type": "daily", "hour": 1, "minute": 0}
        if rtype == "app_summary":
            body["app"] = "SomeApp"
        r = _post(client, body)
        assert r.status_code in (200, 201), (rtype, r.status_code, r.get_data(as_text=True))


# ── day_of_week whitelist (2026-08-28 backlog #1) ───────────────────────────
# report_scheduler.py compares a weekly schedule's day_of_week against
# strftime("%A").lower() — i.e. monday..sunday exactly. Anything else (e.g.
# an abbreviation like "mon") stored verbatim and the schedule never fired,
# with no signal at all.

def test_abbreviated_day_of_week_rejected(client):
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "weekly", "day_of_week": "mon",
                       "hour": 8, "minute": 0})
    assert r.status_code == 400
    assert "day_of_week" in r.get_json().get("error", "").lower()


def test_every_valid_day_of_week_accepted(client):
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"):
        r = _post(client, {"name": f"s-{day}", "report_type": "traffic",
                           "schedule_type": "weekly", "day_of_week": day,
                           "hour": 8, "minute": 0})
        assert r.status_code in (200, 201), (day, r.status_code, r.get_data(as_text=True))


def test_day_of_week_not_checked_for_daily_schedules(client):
    """day_of_week only means anything for schedule_type == weekly; a daily
    schedule must not be rejected for carrying a leftover bad value."""
    r = _post(client, {"name": "x", "report_type": "traffic",
                       "schedule_type": "daily", "day_of_week": "mon",
                       "hour": 8, "minute": 0})
    assert r.status_code == 200
