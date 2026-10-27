"""Report schedules and report settings API (P5a Task 9)."""
from .conftest import LOCAL, csrf, login, post

SCHEDULE = {"name": "Weekly lateral", "enabled": True, "report_type": "lateral_posture", "lookback_days": 7,
            "frequency": "weekly", "day_of_week": 0, "day_of_month": None, "hour": 8, "minute": 0,
            "formats": ["html", "xlsx"], "email": False, "recipients": [], "lang": None, "keep": 30}


def get(client, url):
    return client.get(url, environ_overrides=LOCAL)


def put(client, url, body):
    return client.put(url, json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def delete(client, url, body):
    return client.delete(url, json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def _create(client, schedule=None):
    rev = get(client, "/api/report-schedules").get_json()["data"]["revision"]
    return post(client, "/api/report-schedules", {"revision": rev, "schedule": schedule or SCHEDULE})


def test_create_list_update_delete(client, ctx):
    login(client)
    r = _create(client)
    view = r.get_json()["data"]
    [item] = view["items"]
    sid = item["schedule"]["id"]
    assert len(sid) == 32 and item["next_run"] is not None and item["last_report_id"] is None
    changed = SCHEDULE | {"name": "Daily", "frequency": "daily", "day_of_week": None}
    r = put(client, f"/api/report-schedules/{sid}", {"revision": view["revision"], "schedule": changed})
    assert r.status_code == 200 and r.get_json()["data"]["items"][0]["schedule"]["name"] == "Daily"
    rev = r.get_json()["data"]["revision"]
    assert delete(client, f"/api/report-schedules/{sid}", {"revision": rev}).get_json()["data"]["items"] == []
    assert delete(client, f"/api/report-schedules/{sid}", {"revision": rev + 1}).status_code == 404


def test_validation_names_the_field(client):
    login(client)
    r = _create(client, SCHEDULE | {"day_of_week": None})
    assert r.status_code == 400
    r = _create(client, SCHEDULE | {"hour": 25})
    assert r.status_code == 400 and "hour" in (r.get_json()["error"]["field"] or "")


def test_revision_conflict(client):
    login(client)
    view = _create(client).get_json()["data"]
    stale = view["revision"] - 1
    r = post(client, "/api/report-schedules", {"revision": stale, "schedule": SCHEDULE})
    assert r.status_code == 409


def test_run_now_makes_a_schedule_report(client, ctx):
    login(client)
    sid = _create(client).get_json()["data"]["items"][0]["schedule"]["id"]
    r = post(client, f"/api/report-schedules/{sid}/run", {})
    item = r.get_json()["data"]
    assert r.status_code == 200 and item["trigger"] == "schedule" and item["schedule_name"] == "Weekly lateral"
    assert post(client, f"/api/report-schedules/{'f' * 32}/run", {}).status_code == 404


def test_deleting_schedule_keeps_its_reports(client, ctx):
    login(client)
    view = _create(client).get_json()["data"]
    sid = view["items"][0]["schedule"]["id"]
    rid = post(client, f"/api/report-schedules/{sid}/run", {}).get_json()["data"]["id"]
    rev = get(client, "/api/report-schedules").get_json()["data"]["revision"]
    delete(client, f"/api/report-schedules/{sid}", {"revision": rev})
    item = get(client, f"/api/reports/{rid}").get_json()["data"]
    assert item["schedule_id"] == sid and item["schedule_name"] is None


def test_report_settings(client):
    login(client)
    view = get(client, "/api/system/reports").get_json()["data"]
    assert view["gui_external_url"] == "" and view["retention_days"] == 90
    r = put(client, "/api/system/reports", {"revision": view["revision"], "gui_external_url": "https://ops.example/",
                                            "retention_days": 30})
    assert r.get_json()["data"]["gui_external_url"] == "https://ops.example"
    bad = put(client, "/api/system/reports", {"revision": r.get_json()["data"]["revision"],
                                              "gui_external_url": "ftp://x", "retention_days": 30})
    assert bad.status_code == 400
