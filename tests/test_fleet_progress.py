"""Task 3 — 兩段式 enforcement 推進（preview → apply）與可還原的紀錄。

Spec: docs/superpowers/specs/2026-09-09-ven-fleet-manager-design.md
Plan: docs/superpowers/plans/2026-09-09-ven-fleet-manager.md Task 3

這是整個 fleet 功能唯一會寫 PCE 的一段。守門的重點不是「功能會動」，而是
**不該被改的東西沒有被改**：只准 enforcement_mode 一個欄位、只准往前推、
preview 看到的與 apply 真正改的必須是同一批。

真 PCE 從未被呼叫：`_request` 一律被 patch，並且有測試斷言「整批被拒時它
一次都沒被呼叫」。
"""
import json

import pytest

from src.gui.routes.fleet import classify_targets


def _row(host, mode="idle", online=True, href=None):
    return {"href": href or ("/orgs/1/workloads/" + host), "hostname": host,
            "mode": mode, "online": online, "version": "26.2.20-2063",
            "compat": "pass", "hslh": 0.1, "app": "web", "env": "prod", "os": "ubuntu"}


# ── classify_targets ────────────────────────────────────────────────────────

def test_a_legal_forward_move_on_an_online_workload_is_eligible():
    eligible, deferred, skipped = classify_targets([_row("a")], "selective", cap=200)
    assert [r["href"] for r in eligible] == ["/orgs/1/workloads/a"]
    assert eligible[0]["from"] == "idle" and eligible[0]["to"] == "selective"
    assert deferred == [] and skipped == []


def test_offline_is_deferred_not_skipped():
    """離線不是「不能推」，是「推了要等它回來」——PCE 接受寫入，VEN 下次
    heartbeat 才套用。把它歸進 skipped 會讓操作者以為這台有問題。"""
    eligible, deferred, skipped = classify_targets([_row("a", online=False)], "selective", cap=200)
    assert eligible == []
    assert [r["href"] for r in deferred] == ["/orgs/1/workloads/a"]
    assert skipped == []


@pytest.mark.parametrize("rows,to_mode,reason", [
    ([_row("a", mode="selective")], "selective", "already_target"),
    ([_row("a", mode="full")], "selective", "invalid_transition"),
    ([_row("a", mode="selective")], "visibility_only", "invalid_transition"),
    ([_row("a", mode="")], "selective", "not_managed"),
])
def test_each_skip_reason_is_named(rows, to_mode, reason):
    """理由要說出口：一個沒有理由的 skipped 清單等於沒有清單。"""
    _, _, skipped = classify_targets(rows, to_mode, cap=200)
    assert [s["reason"] for s in skipped] == [reason]


def test_an_href_that_is_not_in_the_index_is_unknown_not_silently_dropped():
    rows = [_row("a")]
    _, _, skipped = classify_targets(rows, "selective", cap=200,
                                     requested=["/orgs/1/workloads/ghost"])
    assert [s["reason"] for s in skipped] == ["unknown_href"]


def test_the_cap_truncates_by_hostname_and_the_cut_ones_say_why():
    """被 cap 掉的必須出現在 skipped——消失的那幾台是最危險的那種「成功」。"""
    rows = [_row("h%02d" % i) for i in range(5)]
    eligible, deferred, skipped = classify_targets(rows, "selective", cap=3)
    assert [r["hostname"] for r in eligible] == ["h00", "h01", "h02"]
    assert [s["hostname"] for s in skipped] == ["h03", "h04"]
    assert {s["reason"] for s in skipped} == {"over_cap"}


def test_the_cap_counts_eligible_and_deferred_together():
    """cap 是「這一批要寫幾筆 PCE」，離線的那些一樣會被寫。"""
    rows = [_row("a"), _row("b", online=False), _row("c")]
    eligible, deferred, skipped = classify_targets(rows, "selective", cap=2)
    assert len(eligible) + len(deferred) == 2
    assert [s["hostname"] for s in skipped] == ["c"]


# ── ApiClient.bulk_update_workloads ─────────────────────────────────────────

def _api(monkeypatch, responses):
    from unittest.mock import MagicMock
    from src.api_client import ApiClient
    api = ApiClient.__new__(ApiClient)
    api.api_cfg = {"org_id": "1", "url": "https://pce.example.com"}
    calls = []

    def _fake(url, method="GET", data=None, **kw):
        calls.append({"url": url, "method": method, "data": data, "kw": kw})
        return responses[len(calls) - 1]

    monkeypatch.setattr(api, "_request", _fake, raising=False)
    return api, calls


def test_bulk_update_sends_only_href_and_enforcement_mode(monkeypatch):
    """多送一個欄位就是多改一個設定。PCE 的 bulk_update 會照單全收。"""
    body = json.dumps([{"href": "/orgs/1/workloads/a", "status": "updated"}]).encode()
    api, calls = _api(monkeypatch, [(200, body)])
    api.bulk_update_workloads([{"href": "/orgs/1/workloads/a", "enforcement_mode": "selective"}])
    assert len(calls) == 1
    assert calls[0]["method"] == "PUT"
    assert calls[0]["url"].endswith("/orgs/1/workloads/bulk_update")
    sent = calls[0]["data"]
    assert sent == [{"href": "/orgs/1/workloads/a", "enforcement_mode": "selective"}]


def test_bulk_update_batches_at_a_thousand(monkeypatch):
    """PCE 的上限是每次操作 1000 筆（REST_APIs_26_1.pdf）。"""
    ok = json.dumps([]).encode()
    api, calls = _api(monkeypatch, [(200, ok), (200, ok)])
    items = [{"href": "/orgs/1/workloads/h%d" % i, "enforcement_mode": "full"}
             for i in range(1500)]
    api.bulk_update_workloads(items)
    assert len(calls) == 2
    assert len(calls[0]["data"]) == 1000
    assert len(calls[1]["data"]) == 500


def test_bulk_update_reports_each_item_the_pce_answered_for(monkeypatch):
    body = json.dumps([
        {"href": "/orgs/1/workloads/a", "status": "updated"},
        {"href": "/orgs/1/workloads/b", "errors": [{"token": "invalid", "message": "no"}]},
    ]).encode()
    api, _ = _api(monkeypatch, [(200, body)])
    out = api.bulk_update_workloads([
        {"href": "/orgs/1/workloads/a", "enforcement_mode": "full"},
        {"href": "/orgs/1/workloads/b", "enforcement_mode": "full"}])
    by_href = {r["href"]: r for r in out}
    assert by_href["/orgs/1/workloads/a"]["status"] == "updated"
    assert by_href["/orgs/1/workloads/b"]["status"] == "error"
    assert by_href["/orgs/1/workloads/b"]["errors"]


def test_a_non_2xx_marks_the_whole_batch_error_rather_than_losing_it(monkeypatch):
    """整批失敗時每一筆都要有下場。沒有回報的那些會被當成成功。"""
    api, _ = _api(monkeypatch, [(500, b"upstream exploded")])
    out = api.bulk_update_workloads([{"href": "/orgs/1/workloads/a", "enforcement_mode": "full"}])
    assert len(out) == 1
    assert out[0]["status"] == "error" and out[0]["http"] == 500
    assert "exploded" in str(out[0]["errors"])


def test_a_transport_exception_is_http_zero_not_a_crash(monkeypatch):
    from src.api_client import ApiClient
    api = ApiClient.__new__(ApiClient)
    api.api_cfg = {"org_id": "1", "url": "https://pce.example.com"}

    def _boom(*a, **kw):
        raise OSError("connection reset")
    monkeypatch.setattr(api, "_request", _boom, raising=False)
    out = api.bulk_update_workloads([{"href": "/orgs/1/workloads/a", "enforcement_mode": "full"}])
    assert out[0]["status"] == "error" and out[0]["http"] == 0


def test_a_429_says_it_may_be_the_previous_batch_still_running(monkeypatch):
    """PCE 一次只跑一個 bulk operation；前一批沒完成時第二批回 429
    （REST_APIs_26_1.pdf）。這個 429 與「你太快了」意思相反——該重試。
    訊息要分得開，否則操作者會照「慢一點」去處理一個「等一下」的問題。
    """
    api, _ = _api(monkeypatch, [(429, b"")])
    out = api.bulk_update_workloads([{"href": "/orgs/1/workloads/a", "enforcement_mode": "full"}])
    assert out[0]["http"] == 429
    assert out[0].get("retryable") is True


# ── FleetProgressStore ──────────────────────────────────────────────────────

def test_the_record_keeps_the_previous_mode_so_it_can_be_put_back(tmp_path):
    """沒有 previous_mode 的紀錄不是紀錄，是流水帳——還原不回去。"""
    from src.fleet_progress_store import FleetProgressStore
    st = FleetProgressStore(str(tmp_path / "fp.json"))
    st.put("r1", {"at": "2026-09-09T01:00:00Z", "user": "admin", "to_mode": "selective",
                  "items": [{"href": "/w/a", "hostname": "a", "previous_mode": "idle",
                             "new_mode": "selective", "deferred": False,
                             "status": "updated", "http": 200, "errors": []}]})
    got = st.get("r1")
    assert got["items"][0]["previous_mode"] == "idle"


def test_records_come_back_newest_first(tmp_path):
    from src.fleet_progress_store import FleetProgressStore
    st = FleetProgressStore(str(tmp_path / "fp.json"))
    st.put("old", {"at": "2026-09-01T00:00:00Z", "items": []})
    st.put("new", {"at": "2026-09-09T00:00:00Z", "items": []})
    assert [r["id"] for r in st.recent(10)] == ["new", "old"]


# ── 路由 ─────────────────────────────────────────────────────────────────────

import src.dashboard_store as dashboard_store
from tests._helpers import _csrf


def _login(client):
    r = client.post("/api/login", json={"username": "admin", "password": "testpass"},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    return _csrf(r)


def _seed_index(monkeypatch, tmp_path, rows):
    path = str(tmp_path / "dashboard_summary.json")
    with open(path, "w") as fh:
        json.dump({"fleet": {"total": len(rows), "workloads_index": rows,
                             "index_truncated": False}}, fh)
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: path)


def _post(client, csrf, url, payload):
    return client.post(url, json=payload, headers={"X-CSRFToken": csrf},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})


def test_preview_needs_exactly_one_of_hrefs_or_bucket(client, monkeypatch, tmp_path):
    """兩個都給時該用哪個？沒有正確答案，所以不猜。"""
    _seed_index(monkeypatch, tmp_path, [_row("a")])
    csrf = _login(client)
    assert _post(client, csrf, "/api/fleet/progress/preview",
                 {"to_mode": "selective"}).status_code == 400
    assert _post(client, csrf, "/api/fleet/progress/preview",
                 {"to_mode": "selective", "hrefs": ["/orgs/1/workloads/a"],
                  "bucket": "idle_compat_pass"}).status_code == 400


def test_preview_rejects_a_mode_nobody_may_progress_to(client, monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path, [_row("a")])
    csrf = _login(client)
    for bad in ("idle", "", "unmanaged"):
        r = _post(client, csrf, "/api/fleet/progress/preview",
                  {"to_mode": bad, "bucket": "idle_compat_pass"})
        assert r.status_code == 400, bad


def test_apply_refuses_the_whole_batch_and_never_touches_the_pce(client, monkeypatch, tmp_path):
    """一筆不合格就整批拒絕，而且 PCE 一次都不能被呼叫。

    部分套用是最難收拾的結果：操作者不知道哪幾台動了。
    """
    _seed_index(monkeypatch, tmp_path, [_row("a"), _row("b", mode="full")])
    csrf = _login(client)
    called = []
    monkeypatch.setattr("src.api_client.ApiClient.bulk_update_workloads",
                        lambda self, items, **kw: called.append(items) or [])
    r = _post(client, csrf, "/api/fleet/progress/apply",
              {"to_mode": "selective",
               "hrefs": ["/orgs/1/workloads/a", "/orgs/1/workloads/b"]})
    assert r.status_code == 400
    assert r.get_json()["skipped"]
    assert called == [], "整批被拒卻還是打了 PCE"


def test_apply_writes_a_record_carrying_the_previous_mode(client, monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path, [_row("a")])
    store_path = str(tmp_path / "fleet_progressions.json")
    monkeypatch.setattr("src.gui.routes.fleet._store_path", lambda: store_path)
    monkeypatch.setattr("src.api_client.ApiClient.bulk_update_workloads",
                        lambda self, items, **kw: [{"href": items[0]["href"],
                                                    "status": "updated", "http": 200,
                                                    "errors": []}])
    csrf = _login(client)
    r = _post(client, csrf, "/api/fleet/progress/apply",
              {"to_mode": "selective", "hrefs": ["/orgs/1/workloads/a"]})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["ok"] is True and d["record_id"]
    assert [x["href"] for x in d["applied"]] == ["/orgs/1/workloads/a"]

    rec = json.load(open(store_path))[d["record_id"]]
    assert rec["items"][0]["previous_mode"] == "idle"
    assert rec["items"][0]["new_mode"] == "selective"
    assert rec["to_mode"] == "selective"


def test_apply_does_not_claim_the_vens_have_it_yet(client, monkeypatch, tmp_path):
    """PCE 收下 ≠ VEN 套用了。政策在受影響的 VEN 下次 heartbeat 才生效
    （REST_APIs_26_1.pdf），期間 PCE 顯示 Syncing。回應要說得出這件事。
    """
    _seed_index(monkeypatch, tmp_path, [_row("a")])
    monkeypatch.setattr("src.gui.routes.fleet._store_path",
                        lambda: str(tmp_path / "fp.json"))
    monkeypatch.setattr("src.api_client.ApiClient.bulk_update_workloads",
                        lambda self, items, **kw: [{"href": items[0]["href"],
                                                    "status": "updated", "http": 200,
                                                    "errors": []}])
    csrf = _login(client)
    d = _post(client, csrf, "/api/fleet/progress/apply",
              {"to_mode": "selective", "hrefs": ["/orgs/1/workloads/a"]}).get_json()
    assert d.get("pending_heartbeat") is True


def test_records_are_listed_newest_first(client, monkeypatch, tmp_path):
    store_path = str(tmp_path / "fp.json")
    with open(store_path, "w") as fh:
        json.dump({"old": {"at": "2026-09-01T00:00:00Z", "items": []},
                   "new": {"at": "2026-09-09T00:00:00Z", "items": []}}, fh)
    monkeypatch.setattr("src.gui.routes.fleet._store_path", lambda: store_path)
    _login(client)
    d = client.get("/api/fleet/progress/records").get_json()
    assert [r["id"] for r in d["records"]] == ["new", "old"]
