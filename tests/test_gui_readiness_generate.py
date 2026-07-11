"""GUI endpoint tests for the readiness report generation route."""
from unittest.mock import MagicMock, patch

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def _fake_result(count=5):
    r = MagicMock()
    r.record_count = count
    r.module_results = {"kpis": [{"i18n_key": "rpt_readiness_kpi_score",
                                  "label": "Readiness Score", "value": 80}]}
    return r


def test_generate_readiness_returns_files(client):
    csrf_token = _login(client)
    with patch("src.report.readiness_report.ReadinessReportGenerator") as MockGen:
        MockGen.return_value.generate_from_api.return_value = _fake_result()
        MockGen.return_value.export.return_value = [
            "/tmp/x/Illumio_Readiness_Report_x.html"]
        r = client.post(
            "/api/readiness_report/generate",
            json={"start_date": "2026-07-01", "end_date": "2026-07-08",
                  "format": "html", "lang": "zh_TW", "data_source": "live"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["Illumio_Readiness_Report_x.html"]
    assert body["record_count"] == 5
    kw = MockGen.return_value.generate_from_api.call_args.kwargs
    assert kw["lang"] == "zh_TW"
    assert kw["use_cache"] is False   # data_source=live


def test_generate_readiness_zero_records_returns_error(client):
    csrf_token = _login(client)
    with patch("src.report.readiness_report.ReadinessReportGenerator") as MockGen:
        MockGen.return_value.generate_from_api.return_value = _fake_result(count=0)
        r = client.post(
            "/api/readiness_report/generate", json={"lang": "en"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is False and body.get("error")
    MockGen.return_value.export.assert_not_called()
