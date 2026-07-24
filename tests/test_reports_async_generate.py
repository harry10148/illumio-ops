"""GUI endpoint tests for async ad-hoc traffic report generation (Task 7).

POST /api/reports/generate returns a job_id immediately and runs the report in a
daemon thread; GET /api/reports/jobs/<job_id> polls status until done/error.
"""
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests._helpers import _csrf


@pytest.fixture(autouse=True)
def isolated_state_file(tmp_path, monkeypatch):
    """Isolate this module from the repo's real logs/state.json.

    /api/reports/generate and /api/reports/jobs/<id> persist and read
    adhoc job records via src.gui.routes.reports._resolve_state_file()
    (= <repo>/logs/state.json). Sharing that file with the rest of the
    suite is an order-dependent flake vector: stale jobs make
    _save_adhoc_job's most-recent-20 prune evict the fresh job (poll 404),
    and full-suite state.json rewrites / .lock contention can drop it
    mid-poll. Same family as commit 79c51e3 (analyzer STATE_FILE flake).
    """
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(
        "src.gui.routes.reports._resolve_state_file", lambda: state_file)
    return state_file


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


def test_traffic_generate_forwards_object_and_any_filters(client_logged_in):
    """Phase 4a：report_filters whitelist 須 forward FilterBar 的 object/複數/any_* key

    既有 whitelist 只保留 labels/src_ip/dst_ip/ex_*/port/proto，會丟棄前端送的
    any_*（既有 bug）與所有 object/複數 key（iplists/workloads/label_groups/
    src_ip_in）。這裡直接攔 ReportGenerator.generate_from_api 收到的 filters，
    確認整條 forward 鏈（端點 → report_filters dict → 報表生成入口）沒有漏 key。
    """
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
            "filters": {
                "src_labels": ["app=erp", "app=web"],
                "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
                "src_workloads": ["/orgs/1/workloads/abc"],
                "src_label_groups": ["PG-Prod"],
                "any_label": "env=prod",
                "any_iplist": "corp-vpn",
                "src_ip_in": ["10.0.0.1"],
                "ex_src_ip": ["10.9.9.9"],
            },
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

        filters = inst.generate_from_api.call_args.kwargs["filters"]
        assert filters["src_labels"] == ["app=erp", "app=web"]
        assert filters["dst_iplists"] == ["/orgs/1/sec_policy/active/ip_lists/7"]
        assert filters["src_workloads"] == ["/orgs/1/workloads/abc"]
        assert filters["src_label_groups"] == ["PG-Prod"]
        assert filters["any_label"] == "env=prod"          # 既有 bug 修復
        assert filters["any_iplist"] == "corp-vpn"
        assert filters["src_ip_in"] == ["10.0.0.1"]
        assert filters["ex_src_ip"] == ["10.9.9.9"]  # list 形狀 forward（見 filter-bar.js 排除 IP pill）


def _seed_future_jobs(state_file, n=20):
    """塞 n 筆 started_at 在遠未來的假 job（模擬共享 state 檔的髒殘留）。"""
    from src.state_store import update_state_file

    def _merge(data):
        data["adhoc_report_jobs"] = {
            f"stale{i:02d}": {
                "status": "done", "files": [], "error": "",
                "started_at": f"2099-01-01T00:00:{i:02d}+00:00",
                "finished_at": None,
            } for i in range(n)
        }
        return data
    update_state_file(state_file, _merge)


def test_stale_future_jobs_do_not_evict_fresh_running_job(client_logged_in, isolated_state_file):
    """機制釘測試（2026-07-25 修正後行為）：state.json 殘留 20 筆未來
    started_at 的 done job 時，新 job 的 status=running 記錄豁免 most-recent-20
    prune——「建立當下」不得被剔除（否則長工作進行中被較新 job 擠掉，poll 直接
    404「unknown job」）。被修剪的只能是 done/error 記錄。"""
    import threading as _threading
    _seed_future_jobs(isolated_state_file)
    gate = _threading.Event()
    with patch("src.report.report_generator.ReportGenerator") as MockGen:
        inst = MockGen.return_value
        # worker 卡在 gate 上，保證 poll 當下 job 仍是 running 狀態（消除
        # 「worker 先完成、done 記錄再被未來殘留擠掉」的競態）。
        inst.generate_from_api.side_effect = (
            lambda **kw: (gate.wait(5), SimpleNamespace(record_count=5))[1])
        inst.export.return_value = ["/tmp/x/x.html"]
        inst.last_export_errors = {}
        try:
            r = client_logged_in.post("/api/reports/generate", json={
                "source": "api", "format": "html",
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": "2026-01-02T23:59:59Z",
            })
            assert r.status_code == 200
            job_id = r.get_json()["job_id"]
            # prune 在 POST 內同步發生：running 記錄豁免，poll 不得 404。
            poll = client_logged_in.get(f"/api/reports/jobs/{job_id}")
            assert poll.status_code == 200
            assert poll.get_json()["status"] == "running"
            # 上限仍受控：修剪後總數 ≤ 20（running 保護 + done 殘留裁到 19）。
            import json as _json
            with open(isolated_state_file, encoding="utf-8") as fh:
                jobs = _json.load(fh)["adhoc_report_jobs"]
            assert job_id in jobs
            assert len(jobs) <= 20
        finally:
            gate.set()


def test_jobs_persist_to_isolated_state_file(client_logged_in, isolated_state_file):
    """隔離驗證：job 記錄落在 tmp state 檔（而非 repo logs/state.json）。"""
    import json as _json
    with patch("src.report.report_generator.ReportGenerator") as MockGen:
        inst = MockGen.return_value
        inst.generate_from_api.return_value = SimpleNamespace(record_count=5)
        inst.export.return_value = ["/tmp/x/x.html"]
        inst.last_export_errors = {}
        r = client_logged_in.post("/api/reports/generate", json={
            "source": "api", "format": "html",
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-01-02T23:59:59Z",
        })
        job_id = r.get_json()["job_id"]
        for _ in range(50):
            s = client_logged_in.get(f"/api/reports/jobs/{job_id}").get_json()
            if s["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        with open(isolated_state_file, encoding="utf-8") as f:
            assert job_id in _json.load(f)["adhoc_report_jobs"]
