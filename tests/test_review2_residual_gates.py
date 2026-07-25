"""review2 殘項（R1–R6）的守門測試。

這批殘項全部是「API 層改成 fail-loud 之後，GUI/CLI 層還停在舊契約」造成的：
  * R1 check_and_create_quarantine_labels 改 raise APIError → 呼叫端要攔
  * R2 get_provision_state 改三態 → 訊息要分得出 draft 與 PCE 沒回應
  * R3 ScheduleDB 回滾要走單筆 delete，不可整檔覆寫
  * R4 adhoc job 修剪不得把剛寫入的那筆修掉
  * R5 匯出器把失敗記在 last_export_errors → 端點不可再無條件回 ok:True
  * R6 threshold_count < 1 要在 API 邊界擋下
"""
import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.exceptions import APIError
from src.i18n import t
from tests._helpers import _csrf

_SRC = Path(__file__).resolve().parents[1] / "src"
_WL_HREF = "/orgs/1/workloads/abc-123"
_RULE_HREF = "/orgs/1/sec_policy/active/rule_sets/1"


def _login(client):
    login = client.post(
        "/api/login",
        json={"username": "admin", "password": "testpass"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert login.status_code == 200
    return _csrf(login)


def _post(client, path, csrf, payload):
    return client.post(
        path, json=payload,
        headers={"X-CSRF-Token": csrf},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )


# ── R1: APIError from the label lookup must stay a readable error ────────────

@pytest.mark.parametrize("path,payload", [
    ("/api/quarantine/apply", {"href": _WL_HREF, "level": "Mild"}),
    ("/api/quarantine/bulk_apply", {"hrefs": [_WL_HREF], "level": "Mild"}),
])
def test_label_lookup_api_error_returns_label_fetch_failed(client, path, payload):
    csrf = _login(client)
    with patch("src.api_client.ApiClient.check_and_create_quarantine_labels",
               side_effect=APIError("labels 502")):
        r = _post(client, path, csrf, payload)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False
    assert body["error"] == t("gui_label_fetch_failed", lang="en", level="Mild")
    # 泛用 500 + request_id 才是這裡要避免的退化。
    assert "request_id" not in body


def test_init_quarantine_survives_a_pce_blip(client):
    csrf = _login(client)
    with patch("src.api_client.ApiClient.check_and_create_quarantine_labels",
               side_effect=APIError("labels 500")):
        r = _post(client, "/api/init_quarantine", csrf, {})
    assert r.status_code == 200
    assert r.get_json()["ok"] is False


def test_lift_still_fails_loudly_on_api_error(client):
    """解除隔離不得退回「靜默 not_quarantined」——例外必須讓整個請求失敗。"""
    csrf = _login(client)
    with patch("src.api_client.ApiClient.check_and_create_quarantine_labels",
               side_effect=APIError("labels 502")):
        r = _post(client, "/api/quarantine/lift", csrf, {"hrefs": [_WL_HREF]})
    body = r.get_json()
    assert body["ok"] is False
    assert "results" not in body


# ── R2: 'unknown' provision state must not be reported as "draft" ────────────

def test_unknown_provision_state_is_not_reported_as_draft(client):
    csrf = _login(client)
    with patch("src.api_client.ApiClient.has_draft_changes", lambda self, h: False), \
         patch("src.api_client.ApiClient.get_provision_state", lambda self, h: "unknown"):
        r = _post(client, "/api/rule_scheduler/schedules", csrf,
                  {"href": _RULE_HREF, "type": "one_time",
                   "expire_at": "2099-01-01T00:00:00"})
    body = r.get_json()
    assert body["ok"] is False, "unknown 仍必須 fail-closed（不得建立排程）"
    assert r.status_code == 502
    assert body["error"] != t("rs_sch_draft_block", lang="en")


def test_genuine_draft_still_reports_draft_block(client):
    csrf = _login(client)
    with patch("src.api_client.ApiClient.has_draft_changes", lambda self, h: False), \
         patch("src.api_client.ApiClient.get_provision_state", lambda self, h: "draft"):
        r = _post(client, "/api/rule_scheduler/schedules", csrf,
                  {"href": _RULE_HREF, "type": "one_time",
                   "expire_at": "2099-01-01T00:00:00"})
    assert r.status_code == 400
    assert r.get_json()["error"] == t("rs_sch_draft_block", lang="en")


# ── R3: no raw ScheduleDB whole-file mutation left in the GUI blueprint ──────

def test_rule_scheduler_blueprint_never_mutates_scheduledb_directly():
    """整檔覆寫（del db.db[...] + db.save()）會抹掉併發寫入者新增的排程；
    所有寫入都必須走會在鎖內重讀的 put/delete。"""
    source = (_SRC / "gui" / "routes" / "rule_scheduler.py").read_text(encoding="utf-8")
    assert "del db.db[" not in source
    assert "db.save()" not in source


# ── R4: the just-written adhoc job record must survive pruning ───────────────

def _zombie_running_jobs(n):
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        f"zombie{i}": {
            "status": "running",
            "started_at": (now - datetime.timedelta(minutes=i + 1)).isoformat(),
        }
        for i in range(n)
    }


def test_new_adhoc_job_is_not_pruned_by_a_pile_of_zombies(tmp_path, monkeypatch):
    from src.gui.routes import reports as reports_mod

    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(reports_mod, "_resolve_state_file", lambda: state_file)

    # 遠多於 _ADHOC_JOBS_MAX 的「進行中」殭屍紀錄（worker 被 kill，24h 內不過期）
    zombies = _zombie_running_jobs(reports_mod._ADHOC_JOBS_MAX + 5)
    from src.state_store import update_state_file
    update_state_file(state_file, lambda s: {**s, reports_mod._ADHOC_JOBS_KEY: zombies})

    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    reports_mod._save_adhoc_job("fresh", {"status": "running", "started_at": started})

    jobs = reports_mod._load_adhoc_jobs()
    assert "fresh" in jobs, "剛寫入的 job 被自己的修剪邏輯刪掉 → 輪詢立刻 404"
    assert len(jobs) <= reports_mod._ADHOC_JOBS_MAX
    # 更新同一筆（done）之後仍必須在。
    reports_mod._save_adhoc_job("fresh", {"status": "done", "started_at": started})
    assert reports_mod._load_adhoc_jobs()["fresh"]["status"] == "done"


# ── R5: a failed xlsx export must not be reported as success ─────────────────

def _fake_result(record_count=3):
    class _R:
        dataframe = None
        date_range = ("2026-01-01", "2026-01-02")
        source = "api"
        module_results = {"mod00": {"kpis": [], "execution_stats": {}, "execution_notes": []}}
        execution_stats = {}
    r = _R()
    r.record_count = record_count
    return r


def test_audit_report_surfaces_a_failed_xlsx_export(client):
    csrf = _login(client)
    result = _fake_result()
    with patch("src.report.audit_generator.AuditGenerator.generate_from_api",
               return_value=result), \
         patch("src.report.audit_generator.AuditGenerator.export",
               side_effect=lambda *a, **kw: ["/tmp/Illumio_Audit_Report.html"]), \
         patch("src.gui.routes.reports._write_audit_dashboard_summary", lambda *a, **kw: None), \
         patch("src.report.audit_generator.AuditGenerator.last_export_errors",
               {"xlsx": "boom"}, create=True):
        r = _post(client, "/api/audit_report/generate", csrf, {"format": "all"})
    body = r.get_json()
    assert body["ok"] is False
    assert body["partial"] is True
    assert body["failed_formats"] == ["xlsx"]
    # 已產出的 HTML 仍要回，操作者才知道是「少了 xlsx」而非整份沒產出。
    assert body["files"] == ["Illumio_Audit_Report.html"]


def test_audit_report_still_reports_success_when_nothing_failed(client):
    csrf = _login(client)
    result = _fake_result()
    with patch("src.report.audit_generator.AuditGenerator.generate_from_api",
               return_value=result), \
         patch("src.report.audit_generator.AuditGenerator.export",
               side_effect=lambda *a, **kw: ["/tmp/Illumio_Audit_Report.html"]), \
         patch("src.gui.routes.reports._write_audit_dashboard_summary", lambda *a, **kw: None), \
         patch("src.report.audit_generator.AuditGenerator.last_export_errors",
               {}, create=True):
        r = _post(client, "/api/audit_report/generate", csrf, {"format": "html"})
    body = r.get_json()
    assert body["ok"] is True
    assert "partial" not in body


# ── R6: threshold_count < 1 rejected at the API boundary ─────────────────────

@pytest.mark.parametrize("bad", [0, -1, "0"])
@pytest.mark.parametrize("path", ["/api/rules/traffic", "/api/rules/bandwidth"])
def test_threshold_count_below_one_rejected(client, path, bad):
    csrf = _login(client)
    r = _post(client, path, csrf, {"name": "R", "threshold_count": bad})
    assert r.status_code == 400
    assert r.get_json()["error"] == t("gui_err_invalid_number", lang="en")


def test_threshold_count_below_one_rejected_on_put(client):
    csrf = _login(client)
    assert _post(client, "/api/rules/traffic", csrf,
                 {"name": "R", "threshold_count": 5}).status_code == 200
    r = client.put(
        "/api/rules/0", json={"threshold_count": 0},
        headers={"X-CSRF-Token": csrf},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 400
    # 400 時 rule 必須完全沒被動過。
    listed = client.get("/api/rules", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert listed[0]["threshold_count"] == 5


# ── R6 補強：門檻語意依規則型別而異 ───────────────────────────────────────────
# bandwidth/volume 的 threshold_count 是浮點 Mbps/MB，0.5 Mbps 是合法設定；
# 只有 count 型（event/traffic）的門檻最小值才是 1。用 <1 一刀切會擋掉合法輸入。

def test_sub_one_bandwidth_threshold_is_accepted(client):
    csrf = _login(client)
    r = _post(client, "/api/rules/bandwidth", csrf,
              {"name": "半 Mbps", "threshold_count": 0.5})
    assert r.status_code == 200, r.get_json()
    listed = client.get("/api/rules", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert listed[0]["threshold_count"] == 0.5


def test_sub_one_bandwidth_threshold_is_accepted_on_put(client):
    csrf = _login(client)
    assert _post(client, "/api/rules/bandwidth", csrf,
                 {"name": "R", "threshold_count": 100}).status_code == 200
    r = client.put(
        "/api/rules/0", json={"threshold_count": 0.25},
        headers={"X-CSRF-Token": csrf},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200, r.get_json()
    listed = client.get("/api/rules", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert listed[0]["threshold_count"] == 0.25


@pytest.mark.parametrize("bad", [0, -1, "-0.5"])
def test_zero_or_negative_bandwidth_threshold_still_rejected(client, bad):
    csrf = _login(client)
    r = _post(client, "/api/rules/bandwidth", csrf, {"name": "R", "threshold_count": bad})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", [0, -1, "0"])
def test_event_rule_threshold_count_below_one_rejected(client, bad):
    """event 端點原本漏掉這道驗證（W2 回報的同類漏網）。"""
    csrf = _login(client)
    r = _post(client, "/api/rules/event", csrf,
              {"name": "R", "filter_value": "agent.tampering", "threshold_count": bad})
    assert r.status_code == 400
    assert r.get_json()["error"] == t("gui_err_invalid_number", lang="en")


def test_event_rule_threshold_count_one_is_accepted(client):
    csrf = _login(client)
    r = _post(client, "/api/rules/event", csrf,
              {"name": "R", "filter_value": "agent.tampering", "threshold_count": 1})
    assert r.status_code == 200, r.get_json()
