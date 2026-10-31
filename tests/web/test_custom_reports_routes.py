"""Custom reports API (P6e): signed in, CSRF on writes, a section saved from a workbench request, not deleted while a
schedule makes it, a schedule refused for a custom report that does not exist."""
from datetime import UTC, datetime, timedelta

from .conftest import LOCAL, csrf, login, post


def _req():
    end = datetime.now(UTC)
    return {"mode": "flows", "view": "ranking", "start": (end - timedelta(days=1)).isoformat(), "end": end.isoformat(),
            "group_by": [{"dimension": "src_host"}]}


def test_save_list_rename_remove_delete(client):
    assert client.get("/api/custom-reports", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = post(client, "/api/custom-reports/sections", {"name": "DB", "title": "Who", "request": _req()})
    assert r.status_code == 200
    rid = r.get_json()["data"]["id"]
    post(client, "/api/custom-reports/sections", {"report_id": rid, "title": "Who 2", "request": _req()})
    assert post(client, f"/api/custom-reports/{rid}/rename", {"name": "DB2"}).get_json()["data"]["name"] == "DB2"
    r = post(client, f"/api/custom-reports/{rid}/sections/0/remove", {})
    assert [s["title"] for s in r.get_json()["data"]["sections"]] == ["Who 2"]
    reports = client.get("/api/custom-reports", environ_overrides=LOCAL).get_json()["data"]["reports"]
    assert [x["name"] for x in reports] == ["DB2"]
    assert client.delete(f"/api/custom-reports/{rid}", headers={"X-CSRFToken": csrf(client)},
                         environ_overrides=LOCAL).status_code == 200
    assert post(client, "/api/custom-reports/sections", {"report_id": rid, "title": "x", "request": _req()}).status_code == 404


def test_name_needed_for_a_new_report(client):
    login(client)
    assert post(client, "/api/custom-reports/sections", {"title": "Who", "request": _req()}).status_code == 400


def test_schedule_for_a_missing_custom_report_refused(client):
    login(client)
    rev = client.get("/api/report-schedules", environ_overrides=LOCAL).get_json()["data"]["revision"]
    sched = {"name": "n", "enabled": True, "report_type": "custom", "custom_id": 777, "lookback_days": 7,
             "frequency": "daily", "day_of_week": None, "day_of_month": None, "hour": 1, "minute": 0,
             "formats": ["html"], "email": False, "recipients": [], "lang": None, "keep": 5}
    r = post(client, "/api/report-schedules", {"revision": rev, "schedule": sched})
    assert r.status_code == 400 and r.get_json()["error"]["field"] == "schedule.custom_id"
