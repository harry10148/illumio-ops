"""GUI endpoint tests for /api/app_report/generate (Task 5)."""
from unittest.mock import patch

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def test_app_report_generate_returns_file(client):
    csrf_token = _login(client)
    fake_path = "/tmp/x/Illumio_App_Summary_DB.html"
    with patch("src.report.app_summary_report.AppSummaryReport") as MockRep:
        MockRep.return_value.run.return_value = fake_path
        r = client.post(
            "/api/app_report/generate",
            json={"app": "DB", "lang": "zh_TW"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["Illumio_App_Summary_DB.html"]
    assert MockRep.return_value.run.call_args.kwargs["app"] == "DB"


def test_app_report_generate_requires_app(client):
    csrf_token = _login(client)
    with patch("src.report.app_summary_report.AppSummaryReport") as MockRep:
        r = client.post(
            "/api/app_report/generate",
            json={"lang": "zh_TW"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    assert r.status_code == 400
    body = r.get_json()
    assert body["ok"] is False
    assert body["error"]
    MockRep.return_value.run.assert_not_called()


def test_labels_endpoint_returns_app_labels(client):
    _login(client)
    with patch("src.api_client.ApiClient.get_labels", return_value=[
        {"key": "app", "value": "DB"}, {"key": "app", "value": "Web"}]):
        r = client.get("/api/labels?key=app",
                       environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["labels"] == ["DB", "Web"]


def test_labels_endpoint_bad_key_400(client):
    _login(client)
    assert client.get("/api/labels?key=evil",
                      environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).status_code == 400


def test_app_report_generate_rejects_bad_lang(client):
    csrf_token = _login(client)
    with patch("src.report.app_summary_report.AppSummaryReport") as MockRep:
        MockRep.return_value.run.return_value = "/tmp/x/a.html"
        r = client.post(
            "/api/app_report/generate",
            json={"app": "DB", "lang": "fr"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    assert r.status_code == 200
    MockRep.return_value.run.assert_called_once()
    assert MockRep.return_value.run.call_args.kwargs["lang"] == "en"
