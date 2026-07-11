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


def test_traffic_upload_rejects_non_csv_extension(client):
    csrf_token = _login(client)
    r = client.post(
        "/api/reports/generate",
        data={"source": "csv", "lang": "en",
              "file": (BytesIO(b"src,dst\n1.1.1.1,2.2.2.2\n"),
                       "evil.exe", "application/octet-stream")},
        headers={"X-CSRF-Token": csrf_token},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        content_type="multipart/form-data",
    )
    assert r.status_code == 415


def test_rhc_enablement_error_respects_lang(client):
    # 錯誤訊息語言須跟隨 ?lang=，不得硬編 en。
    _login(client)
    with patch("src.gui.routes.reports.check_enablement",
               side_effect=RuntimeError("boom")):
        r_en = client.get("/api/rule_hit_count/enablement?lang=en",
                          environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        r_zh = client.get("/api/rule_hit_count/enablement?lang=zh_TW",
                          environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r_en.get_json()["ok"] is False and r_zh.get_json()["ok"] is False
    assert r_en.get_json()["error"] != r_zh.get_json()["error"]


def test_rhc_upload_rejects_non_csv_extension_with_whitelisted_mimetype(client):
    # mimetype 可由 client 偽造：octet-stream 在白名單內，但副檔名不是 .csv 要拒。
    csrf_token = _login(client)
    r = _post_csv(client, csrf_token, "/api/rule_hit_count_report/generate",
                  "evil.exe", "application/octet-stream")
    assert r.status_code == 415
    assert r.get_json()["ok"] is False


def test_policy_usage_upload_rejects_non_csv_extension(client):
    csrf_token = _login(client)
    r = _post_csv(client, csrf_token, "/api/policy_usage_report/generate",
                  "evil.exe", "application/octet-stream")
    assert r.status_code == 415


def test_rhc_upload_accepts_uppercase_csv_extension(client):
    # 副檔名判定不分大小寫（Windows 匯出常見 .CSV）
    csrf_token = _login(client)
    fake = MagicMock()
    fake.record_count = 1
    fake.module_results = {"kpis": {"total_rules": 1}}
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_csv.return_value = fake
        MockGen.return_value.export.return_value = ["/tmp/x/r.html"]
        r = _post_csv(client, csrf_token, "/api/rule_hit_count_report/generate",
                      "RHC.CSV", "text/csv")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


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
