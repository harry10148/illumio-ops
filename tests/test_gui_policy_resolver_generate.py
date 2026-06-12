"""GUI endpoint tests for /api/policy_resolver_report/generate (Task 3)."""
from unittest.mock import patch

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def test_policy_resolver_generate_returns_files(client):
    csrf_token = _login(client)
    with patch("src.report.policy_resolver_report.PolicyResolverReport") as MockRep:
        MockRep.return_value.run.return_value = ["/tmp/x/a.json", "/tmp/x/b.csv"]
        r = client.post(
            "/api/policy_resolver_report/generate",
            json={"lang": "zh_TW", "format": "all"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["a.json", "b.csv"]


def test_policy_resolver_generate_rejects_bad_lang(client):
    csrf_token = _login(client)
    with patch("src.report.policy_resolver_report.PolicyResolverReport") as MockRep:
        MockRep.return_value.run.return_value = ["/tmp/x/a.json"]
        r = client.post(
            "/api/policy_resolver_report/generate",
            json={"lang": "fr"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    assert r.status_code == 200
    MockRep.return_value.run.assert_called_once()
    assert MockRep.return_value.run.call_args.kwargs["lang"] == "en"
