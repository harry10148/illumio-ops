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


# ── 搜尋、排序、版本與 label 篩選、匯出 ───────────────────────────────────────

def _with_target(fleet, target):
    fleet["versions"]["target"] = target
    return fleet


def test_no_bucket_means_every_workload(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=1)})
    _login(client)
    d = client.get("/api/fleet/list").get_json()
    assert d["total"] == 4 and d["bucket"] == "all"


def test_search_matches_hostname_app_env_and_version(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=1)})
    _login(client)
    assert client.get("/api/fleet/list?q=SEL-1").get_json()["total"] == 1   # case-insensitive
    assert client.get("/api/fleet/list?q=web").get_json()["total"] == 3     # app
    assert client.get("/api/fleet/list?q=23.4").get_json()["total"] == 1    # version
    assert client.get("/api/fleet/list?q=nothing-like-it").get_json()["total"] == 0


def test_version_app_and_env_filters_stack_with_the_bucket(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=3, n_idle=1)})
    _login(client)
    d = client.get("/api/fleet/list?version=23.4.11-8").get_json()
    assert [r["hostname"] for r in d["rows"]] == ["idle-0"]
    assert client.get("/api/fleet/list?app=web&env=prod").get_json()["total"] == 3
    assert client.get("/api/fleet/list?bucket=offline&app=web").get_json()["total"] == 0


def test_needs_upgrade_lists_exactly_what_the_summary_counts(client, monkeypatch, tmp_path):
    """摘要說「待升級 1」，點進去就必須是那 1 台——判定與 analyze_fleet 相同。"""
    _seed(monkeypatch, tmp_path, {"fleet": _with_target(_fleet(n_sel=3, n_idle=1), "26.2.20-2063")})
    _login(client)
    d = client.get("/api/fleet/list?bucket=needs_upgrade").get_json()
    assert [r["hostname"] for r in d["rows"]] == ["idle-0"]
    assert client.get("/api/fleet/list?bucket=on_target").get_json()["total"] == 3


def test_needs_upgrade_without_a_target_is_a_400(client, monkeypatch, tmp_path):
    """沒有目標版本時「待升級」沒有定義；空清單會被讀成「全都在目標上」。"""
    _seed(monkeypatch, tmp_path, {"fleet": _fleet()})
    _login(client)
    assert client.get("/api/fleet/list?bucket=needs_upgrade").status_code == 400


def test_sort_by_version_is_numeric_and_missing_values_go_last(client, monkeypatch, tmp_path):
    fleet = _fleet(n_sel=1, n_idle=1)
    fleet["workloads_index"].append({"href": "/w/x", "hostname": "nover", "mode": "full",
                                     "online": True, "version": "", "compat": "unknown",
                                     "hslh": None, "app": "", "env": "", "os": ""})
    fleet["workloads_index"].append({"href": "/w/y", "hostname": "nine", "mode": "full",
                                     "online": True, "version": "9.1.0-1", "compat": "unknown",
                                     "hslh": 1.0, "app": "", "env": "", "os": ""})
    _seed(monkeypatch, tmp_path, {"fleet": fleet})
    _login(client)
    asc = [r["hostname"] for r in client.get("/api/fleet/list?sort=version&dir=asc").get_json()["rows"]]
    desc = [r["hostname"] for r in client.get("/api/fleet/list?sort=version&dir=desc").get_json()["rows"]]
    # 字串排序會把 "9.1" 排在 "26.2" 之後
    assert asc == ["nine", "idle-0", "sel-0", "nover"]
    assert desc == ["sel-0", "idle-0", "nine", "nover"]
    hb = [r["hostname"] for r in client.get("/api/fleet/list?sort=hslh&dir=desc").get_json()["rows"]]
    assert hb[0] == "idle-0" and hb[-1] == "nover"


def test_sort_by_mode_follows_the_road_to_enforcement(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet(n_sel=2, n_idle=1)})
    _login(client)
    rows = client.get("/api/fleet/list?sort=mode").get_json()["rows"]
    assert [r["mode"] for r in rows] == ["idle", "selective", "selective"]


def test_an_unknown_sort_key_is_a_400(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet()})
    _login(client)
    assert client.get("/api/fleet/list?sort=href").status_code == 400
    assert client.get("/api/fleet/list?dir=sideways").status_code == 400


def test_export_is_the_filtered_list_unpaged_and_formula_safe(client, monkeypatch, tmp_path):
    fleet = _fleet(n_sel=3, n_idle=1)
    fleet["workloads_index"][0]["hostname"] = "=HYPERLINK(\"x\")"
    _seed(monkeypatch, tmp_path, {"fleet": fleet})
    _login(client)
    r = client.get("/api/fleet/export.csv?app=web&limit=1")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    text = r.get_data(as_text=True).lstrip("\ufeff")
    lines = text.strip().splitlines()
    assert len(lines) == 1 + 3                      # header + every match, no paging
    assert lines[1].startswith("\"'=HYPERLINK")       # spreadsheet formula defused
    assert "idle-0" not in text


def test_export_requires_login(client, monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, {"fleet": _fleet()})
    r = client.get("/api/fleet/export.csv")
    assert r.status_code in (302, 401, 403)


# ── 設定鍵 ───────────────────────────────────────────────────────────────────

def test_the_fleet_settings_are_savable(client):
    """白名單外的鍵會被 PUT /api/settings 靜默丟掉——那是最難查的那種壞法。

    GUI 存了、toast 說成功、下次讀回來是舊值，沒有任何地方報錯。
    """
    from src.gui._helpers import _SETTINGS_ALLOWLISTS
    allowed = _SETTINGS_ALLOWLISTS["settings"]
    for key in ("fleet_target_ven_version", "fleet_index_cap"):
        assert key in allowed, "%s 不在白名單，存了會被無聲丟掉" % key


# ── 唯讀 ─────────────────────────────────────────────────────────────────────

def test_the_inventory_has_no_route_that_writes(client):
    """VEN 盤點只看不改：enforcement 推進已移除，不准再長回來。

    任何 /api/fleet 底下的非 GET 路由、或 ApiClient 上改 enforcement mode 的
    方法，都代表這個工具又能改 PCE 的 enforcement 了。
    """
    from flask import current_app
    from src.api_client import ApiClient
    with client.application.app_context():
        writes = [(r.rule, sorted(r.methods - {"GET", "HEAD", "OPTIONS"}))
                  for r in current_app.url_map.iter_rules()
                  if r.rule.startswith("/api/fleet") and r.methods - {"GET", "HEAD", "OPTIONS"}]
    assert writes == []
    assert not hasattr(ApiClient, "bulk_update_workloads")


def test_a_config_saved_by_an_older_gui_still_loads(tmp_path):
    """舊版 GUI 每次儲存都寫 fleet_max_batch；拿掉 schema 欄位會讓整份 config
    驗證失敗、全部退回預設值（SIEM 轉送因此停擺）。"""
    import json as _json
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    cfg.write_text(_json.dumps({"settings": {"fleet_max_batch": 200}}), encoding="utf-8")
    cm = ConfigManager(str(cfg))
    assert not getattr(cm, "_load_error_locs", None)
    assert cm.models.settings.fleet_max_batch == 200


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
