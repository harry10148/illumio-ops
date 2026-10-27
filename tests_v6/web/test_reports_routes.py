"""Reports API (P5a Task 8): catalog, generate, list, one report, delete, and the file download."""
from datetime import UTC, datetime

from illumio_ops.domain.values import ReportStatus, ReportType
from illumio_ops.services.reports import generate
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.store import reports as store

from .conftest import LOCAL, csrf, login, post


def get(client, url):
    return client.get(url, environ_overrides=LOCAL)


def delete(client, url):
    return client.delete(url, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def _done_report(ctx):
    rid = post_report(ctx)
    generate.run_queued(ctx)
    return rid


def post_report(ctx):
    return generate.enqueue(ctx, ReportParams(report_type=ReportType.UNMANAGED_ENDPOINTS), trigger="manual",
                            schedule_id=None, now=datetime.now(UTC))


def _configure(ctx):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(
        url="https://pce.example.com:8443", org_id="1", api_key="k", api_secret="s"))


def test_requires_login(client):
    assert get(client, "/api/reports").status_code == 401
    assert get(client, "/api/reports/catalog").status_code == 401
    assert get(client, "/reports/files/1/x.html").status_code == 401


def test_generate_requires_csrf(client):
    login(client)
    r = client.post("/api/reports", json={"report_type": "lateral_posture"}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)


def test_catalog_lists_built_types(client, ctx):
    login(client)
    data = get(client, "/api/reports/catalog").get_json()["data"]
    types = {e["report_type"]: e for e in data["entries"]}
    assert set(types) == {"lateral_posture", "new_connections", "unmanaged_endpoints", "traffic", "security_risk", "network_inventory"}
    assert all(e["available"] for e in types.values()) and data["smtp_enabled"] is False


def test_catalog_events_only_unavailable(client, ctx):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="events_only"))
    login(client)
    e = get(client, "/api/reports/catalog").get_json()["data"]["entries"][0]
    assert e["available"] is False and e["reason_key"] == "rpt_unavailable_events_only"


def test_generate_then_list_and_get(client, ctx):
    _configure(ctx)
    login(client)
    r = post(client, "/api/reports", {"report_type": "unmanaged_endpoints", "lookback_days": 3, "lang": "zh_TW"})
    item = r.get_json()["data"]
    assert r.status_code == 200 and item["status"] == "queued" and item["trigger"] == "manual"
    assert item["lookback_days"] == 3 and item["lang"] == "zh_TW"
    listed = get(client, "/api/reports").get_json()["data"]
    assert listed["total"] == 1 and listed["items"][0]["id"] == item["id"]
    assert get(client, f"/api/reports/{item['id']}").get_json()["data"]["id"] == item["id"]
    assert get(client, "/api/reports/999").status_code == 404


def test_generate_validates_input(client):
    login(client)
    r = post(client, "/api/reports", {"report_type": "lateral_posture", "lookback_days": 0})
    assert r.status_code == 400 and r.get_json()["error"]["field"] == "lookback_days"
    assert post(client, "/api/reports", {"report_type": "nope"}).status_code == 400


def test_download_only_own_files(client, ctx):
    _configure(ctx)
    login(client)
    rid = _done_report(ctx)
    with ctx.db() as conn:
        row = store.get(conn, rid)
    assert row.status is ReportStatus.DONE
    html = next(f for f in row.files if f.endswith(".html"))
    r = get(client, f"/reports/files/{rid}/{html}")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    escape = get(client, f"/reports/files/{rid}/..%2F..%2Fconfig%2Fsettings.json")
    # not the download route (a name has no slash): the single-page app answers, never the file
    assert "attachment" not in escape.headers.get("Content-Disposition", "") and b"api_secret" not in escape.data
    assert get(client, f"/reports/files/{rid + 1}/{html}").status_code == 404
    (ctx.paths.reports_dir / str(rid) / "other.html").write_text("x")
    assert get(client, f"/reports/files/{rid}/other.html").status_code == 404


def test_delete(client, ctx):
    _configure(ctx)
    login(client)
    rid = _done_report(ctx)
    running = post_report(ctx)
    with ctx.db() as conn:
        store.claim_next(conn, at=datetime.now(UTC))
    assert delete(client, f"/api/reports/{running}").status_code == 409
    assert delete(client, f"/api/reports/{rid}").status_code == 200
    assert not (ctx.paths.reports_dir / str(rid)).exists()
    assert delete(client, f"/api/reports/{rid}").status_code == 404
