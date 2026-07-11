"""CSV upload mimetype whitelist on rule_hit_count / policy_usage routes（spec §C）。
traffic 路由已有前例；此檔釘兩條新路由的拒絕（415）與放行路徑。"""
from io import BytesIO
from unittest.mock import MagicMock, patch

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def _post_csv(client, csrf_token, endpoint, filename, mimetype):
    return client.post(
        endpoint,
        data={"source": "csv", "lang": "en",
              "file": (BytesIO(b"Rule HREF,Rule Hit Count\n/r/1,3\n"),
                       filename, mimetype)},
        headers={"X-CSRF-Token": csrf_token},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        content_type="multipart/form-data",
    )


def test_rhc_upload_rejects_bad_mimetype(client):
    csrf_token = _login(client)
    r = _post_csv(client, csrf_token, "/api/rule_hit_count_report/generate",
                  "evil.pdf", "application/pdf")
    assert r.status_code == 415
    assert r.get_json()["ok"] is False
    assert r.get_json()["error"]


def test_policy_usage_upload_rejects_bad_mimetype(client):
    csrf_token = _login(client)
    r = _post_csv(client, csrf_token, "/api/policy_usage_report/generate",
                  "evil.pdf", "application/pdf")
    assert r.status_code == 415
    assert r.get_json()["ok"] is False


def test_rhc_upload_accepts_text_csv(client):
    # 放行釘：text/csv 通過白名單、進到 generator（mock 掉實際產出）
    csrf_token = _login(client)
    fake = MagicMock()
    fake.record_count = 1
    fake.module_results = {"kpis": {"total_rules": 1}}
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_csv.return_value = fake
        MockGen.return_value.export.return_value = ["/tmp/x/r.html"]
        r = _post_csv(client, csrf_token, "/api/rule_hit_count_report/generate",
                      "rhc.csv", "text/csv")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
