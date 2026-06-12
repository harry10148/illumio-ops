"""GUI endpoint tests for async ad-hoc traffic report generation (Task 7).

POST /api/reports/generate returns a job_id immediately and runs the report in a
daemon thread; GET /api/reports/jobs/<job_id> polls status until done/error.
"""
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


@pytest.fixture
def client_logged_in(client):
    """A logged-in test client carrying the CSRF token on every POST."""
    csrf_token = _login(client)

    class _Wrapped:
        def post(self, path, **kw):
            headers = dict(kw.pop('headers', {}) or {})
            headers.setdefault('X-CSRF-Token', csrf_token)
            kw.setdefault('environ_overrides', {'REMOTE_ADDR': '127.0.0.1'})
            return client.post(path, headers=headers, **kw)

        def get(self, path, **kw):
            kw.setdefault('environ_overrides', {'REMOTE_ADDR': '127.0.0.1'})
            return client.get(path, **kw)

    return _Wrapped()


def test_traffic_generate_returns_job_id_and_completes(client_logged_in):
    fake_result = SimpleNamespace(record_count=5)
    with patch("src.report.report_generator.ReportGenerator") as MockGen:
        inst = MockGen.return_value
        inst.generate_from_api.return_value = fake_result
        inst.export.return_value = ["/tmp/x/x.html"]
        inst.last_export_errors = {}

        r = client_logged_in.post("/api/reports/generate", json={
            "source": "api", "format": "html",
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-01-02T23:59:59Z",
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True and "job_id" in body

        s = None
        for _ in range(50):
            s = client_logged_in.get(f"/api/reports/jobs/{body['job_id']}").get_json()
            if s["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert s is not None
        assert s["status"] == "done", s
        assert s["files"] == ["x.html"]


def test_job_endpoint_unknown_id_404(client_logged_in):
    assert client_logged_in.get("/api/reports/jobs/nonexistent").status_code == 404
