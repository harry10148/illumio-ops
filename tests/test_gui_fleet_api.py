"""Task 2 — 唯讀的 fleet API。

Spec: docs/superpowers/specs/2026-09-09-ven-fleet-manager-design.md
Plan: docs/superpowers/plans/2026-09-09-ven-fleet-manager.md Task 2

`GET /api/fleet` 與 `GET /api/fleet/list` 只讀 `run_ven_summary` 寫下的那份
快照，不碰 PCE。沒有快照時要說「還沒有」，不是回一個看起來像空車隊的 0。
"""
import json

import src.dashboard_store as dashboard_store


def _login(client):
    r = client.post("/api/login", json={"username": "admin", "password": "testpass"},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200


def _seed(monkeypatch, tmp_path, payload):
    path = str(tmp_path / "dashboard_summary.json")
    with open(path, "w") as fh:
        json.dump(payload, fh)
    monkeypatch.setattr(dashboard_store, "_dashboard_file", lambda: path)


def _fleet(n_sel=3, n_idle=1):
    index = [{"href": "/w/s%d" % i, "hostname": "sel-%d" % i, "mode": "selective",
              "online": True, "version": "26.2.20-2063", "compat": "unknown",
              "hslh": 0.1, "app": "web", "env": "prod", "os": "ubuntu"}
             for i in range(n_sel)]
    index += [{"href": "/w/i%d" % i, "hostname": "idle-%d" % i, "mode": "idle",
               "online": False, "version": "23.4.11-8", "compat": "warn",
               "hslh": 99.0, "app": "", "env": "", "os": "rhel"}
              for i in range(n_idle)]
    return {
        "total": n_sel + n_idle, "managed_online": n_sel, "managed_offline": n_idle,
        "versions": {"ordered": ["26.2.20-2063", "23.4.11-8"], "target": None,
                     "on_target": 0, "needs_upgrade": None, "unparsable": [],
                     "distribution": {}, "oldest": "23.4.11-8", "newest": "26.2.20-2063"},
        "compat": {"pass": 0, "warn": n_idle, "fail": 0, "unknown": 0},
        "pipeline": {"idle_compat_warn": {"count": n_idle, "sample": []},
                     "selective": {"count": n_sel, "sample": []}},
        "heartbeat": {"fresh": n_sel, "stale_24h": 0, "stale_48h": n_idle, "no_heartbeat": 0},
        "coverage_gaps": {"by_app": {}, "by_env": {}, "unlabeled": {"count": n_idle, "sample": []}},
        "agent_health": {"errors": {"count": 0, "sample": []},
                         "warnings": {"count": 0, "sample": []}},
        "health_score": {"score": 60, "partial": True, "components": {}},
        "workloads_index": index,
        "index_truncated": False,
        "updated_at": "2026-09-09T12:00:00Z",
    }


# ── GET /api/fleet ───────────────────────────────────────────────────────────

def test_no_snapshot_yet_says_so_rather_than_showing_an_empty_fleet(client, monkeypatch, tmp_path):
    """還沒跑過排程 ≠ 車隊是空的。"""
    _seed(monkeypatch, tmp_path, {})
    _login(client)
    d = client.get("/api/fleet").get_json()
    assert d["ok"] is True
    assert d["available"] is False
    assert d["fleet"] == {}


def test_the_summary_never_carries_the_whole_index(client, monkeypatch, tmp_path):
    """index 在 1 萬台時約 2 MB——摘要端點不該把它塞給每一次輪詢。"""
    _seed(monkeypatch, tmp_path, {"fleet": _fleet()})
    _login(client)
    d = client.get("/api/fleet").get_json()
    assert d["available"] is True
    assert "workloads_index" not in d["fleet"]
    assert d["fleet"]["total"] == 4
    assert d["fleet"]["health_score"]["score"] == 60
    assert "next_run_at" in d


def test_fleet_requires_login(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet()})
    r = client.get("/api/fleet")
    assert r.status_code in (302, 401, 403)


# ── GET /api/fleet/list ──────────────────────────────────────────────────────

def test_list_returns_only_the_rows_the_bucket_names(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=1)})
    _login(client)
    d = client.get("/api/fleet/list?bucket=selective").get_json()
    assert d["ok"] is True and d["bucket"] == "selective"
    assert d["total"] == 3
    assert {r["mode"] for r in d["rows"]} == {"selective"}


def test_list_paginates_without_changing_the_total(client, monkeypatch, tmp_path):
    """total 是桶的大小，不是這一頁的長度——否則分頁器算不出頁數。"""
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=5, n_idle=0)})
    _login(client)
    d = client.get("/api/fleet/list?bucket=selective&offset=2&limit=2").get_json()
    assert d["total"] == 5
    assert len(d["rows"]) == 2
    assert d["rows"][0]["hostname"] == "sel-2"


def test_an_unknown_bucket_is_a_400_not_an_empty_list(client, monkeypatch, tmp_path):
    """空清單會被讀成「這個桶裡沒東西」，而不是「你問了一個不存在的桶」。"""
    _seed(monkeypatch, tmp_path, {"fleet": _fleet()})
    _login(client)
    r = client.get("/api/fleet/list?bucket=nonsense")
    assert r.status_code == 400


def test_list_says_when_the_index_was_dropped(client, monkeypatch, tmp_path):
    """index 被 cap 掉時清單必須說出來，不能假裝桶是空的。"""
    fleet = _fleet()
    fleet["workloads_index"] = []
    fleet["index_truncated"] = True
    _seed(monkeypatch, tmp_path, {"fleet": fleet})
    _login(client)
    d = client.get("/api/fleet/list?bucket=selective").get_json()
    assert d["index_truncated"] is True
    assert d["rows"] == []


def test_heartbeat_buckets_are_listable_too(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=1)})
    _login(client)
    d = client.get("/api/fleet/list?bucket=stale_48h").get_json()
    assert d["total"] == 1
    assert d["rows"][0]["hostname"] == "idle-0"


def test_unlabeled_is_listable(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=1)})
    _login(client)
    d = client.get("/api/fleet/list?bucket=unlabeled").get_json()
    assert d["total"] == 1
    assert d["rows"][0]["hostname"] == "idle-0"


def test_limit_is_capped(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=0)})
    _login(client)
    r = client.get("/api/fleet/list?bucket=selective&limit=99999")
    assert r.status_code == 200
    assert len(r.get_json()["rows"]) == 3


# ── 設定鍵 ───────────────────────────────────────────────────────────────────

def test_the_three_fleet_settings_are_savable(client):
    """白名單外的鍵會被 PUT /api/settings 靜默丟掉——那是最難查的那種壞法。

    GUI 存了、toast 說成功、下次讀回來是舊值，沒有任何地方報錯。
    """
    from src.gui._helpers import _SETTINGS_ALLOWLISTS
    allowed = _SETTINGS_ALLOWLISTS["settings"]
    for key in ("fleet_target_ven_version", "fleet_max_batch", "fleet_index_cap"):
        assert key in allowed, "%s 不在白名單，存了會被無聲丟掉" % key


def test_every_pipeline_bucket_can_actually_be_listed():
    """摘要上的每個桶都點得進去。

    少一個 predicate 的症狀是：畫面顯示「idle 且 compat fail：3 台」，點下去
    卻永遠是空的——而且不會有任何錯誤。這個不變量原本寫成 fleet.py 的模組層
    `assert`，但那在 import 時才跑一次、訊息又被 i18n 稽核當成硬編中文；
    放在這裡它是一支真的守門。
    """
    from src.gui.routes.fleet import BUCKET_PREDICATES
    from src.report.analysis.fleet import PIPELINE_BUCKETS

    missing = sorted(set(PIPELINE_BUCKETS) - set(BUCKET_PREDICATES))
    assert missing == [], "這些桶列不出來：%s" % missing
