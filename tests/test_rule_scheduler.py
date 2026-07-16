"""Regression test for ScheduleEngine.check: one_time schedule + timezone
'local' must not silently fail to expire due to aware/naive datetime
comparison TypeError being swallowed by the per-item except."""
from unittest.mock import MagicMock

from src.rule_scheduler import ScheduleDB, ScheduleEngine


def test_one_time_local_tz_expires_correctly(tmp_path):
    """one_time schedule with timezone='local' (aware `now`) compared against a
    naive `expire_at` must still expire and be cleaned up, not raise a
    TypeError that gets swallowed by the per-item except."""
    db_path = tmp_path / "rule_schedules.json"
    href = "/orgs/1/sec_policy/draft/rules/1"
    db = ScheduleDB(str(db_path))
    db.put(href, {
        "type": "one_time",
        "name": "test_rule",
        "action": "allow",
        "expire_at": "2000-01-01T00:00:00",  # naive, far in the past
        "timezone": "local",
    })

    api = MagicMock()
    api.has_draft_changes.return_value = False
    engine = ScheduleEngine(db, api)

    engine.check(silent=True, tz_str="local")

    api.toggle_and_provision.assert_called_once_with(href, False, None)
    assert db.get(href) is None, "expired one_time schedule must be removed from db"


def test_one_time_reverse_tz_naive_now_aware_expire_stays_active(tmp_path):
    """反向情境（A1 對稱正規化的另一半）：schedule timezone 走 'UTC' 路徑，_now_in_tz
    回傳 naive item_now；expire_at 則是帶 offset 的 aware ISO 字串。兩側正規化後應
    可正確比較——expire_at 尚未到期時不得拋 TypeError，且必須維持啟用（target=True）。
    """
    db_path = tmp_path / "rule_schedules.json"
    href = "/orgs/1/sec_policy/draft/rules/2"
    db = ScheduleDB(str(db_path))
    db.put(href, {
        "type": "one_time",
        "name": "test_rule_reverse",
        "action": "allow",
        "expire_at": "2999-01-01T00:00:00+00:00",  # aware，遠在未來
        "timezone": "UTC",
    })

    api = MagicMock()
    api.has_draft_changes.return_value = False
    api.get_live_item.return_value = (200, {"enabled": False})
    engine = ScheduleEngine(db, api)

    engine.check(silent=True, tz_str="local")

    api.toggle_and_provision.assert_called_once_with(href, True, None)
    assert db.get(href) is not None, "not-yet-expired one_time schedule must stay in db"


def test_check_persists_per_schedule_state(tmp_path, monkeypatch):
    """2026-07-16 backlog：rule 排程要有 per-schedule 執行紀錄
    （report scheduler 早有，rule 這側缺——排程沒生效時分不出
    「時間未到」還是「從未觸發」）。"""
    import json
    from unittest.mock import MagicMock
    from src.rule_scheduler import ScheduleDB, ScheduleEngine
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr("src.rule_scheduler._resolve_rule_state_file",
                        lambda: state_file)
    db = ScheduleDB(str(tmp_path / "rule_schedules.json"))
    db.db = {"/orgs/1/sec_policy/active/rule_sets/1": {
        "type": "recurring", "name": "rs", "is_ruleset": True,
        "action": "enable", "days": ["mon", "tue", "wed", "thu", "fri",
                                      "sat", "sun"],
        "start": "00:00", "end": "23:59", "timezone": "UTC",
    }}
    api = MagicMock()
    api.has_draft_changes.return_value = False
    api.get_live_item.return_value = (200, {"enabled": True})
    engine = ScheduleEngine(db, api)
    engine.check(silent=True, tz_str="UTC")
    states = json.load(open(state_file))["rule_schedule_states"]
    entry = states["/orgs/1/sec_policy/active/rule_sets/1"]
    assert entry["last_checked"].endswith("Z")


def test_check_toggle_success_records_ok(tmp_path, monkeypatch):
    """live state (enabled=False) 與排程 target(全天 allow 視窗內應 enabled)
    不一致時觸發 toggle；toggle_and_provision 成功應記
    last_action/last_result=ok。"""
    import json
    from unittest.mock import MagicMock
    from src.rule_scheduler import ScheduleDB, ScheduleEngine
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr("src.rule_scheduler._resolve_rule_state_file",
                        lambda: state_file)
    href = "/orgs/1/sec_policy/active/rule_sets/1"
    db = ScheduleDB(str(tmp_path / "rule_schedules.json"))
    db.db = {href: {
        "type": "recurring", "name": "rs", "is_ruleset": True,
        "action": "allow", "days": ["mon", "tue", "wed", "thu", "fri",
                                     "sat", "sun"],
        "start": "00:00", "end": "23:59", "timezone": "UTC",
    }}
    api = MagicMock()
    api.has_draft_changes.return_value = False
    api.get_live_item.return_value = (200, {"enabled": False})
    api.toggle_and_provision.return_value = True
    engine = ScheduleEngine(db, api)
    engine.check(silent=True, tz_str="UTC")
    states = json.load(open(state_file))["rule_schedule_states"]
    entry = states[href]
    assert entry["last_action"] in ("enable", "disable")
    assert entry["last_result"] == "ok"


def test_check_toggle_failure_records_error(tmp_path, monkeypatch):
    """同上情境，但 toggle_and_provision 失敗（回傳 False）應記
    last_result=error，不可誤記為 ok。"""
    import json
    from unittest.mock import MagicMock
    from src.rule_scheduler import ScheduleDB, ScheduleEngine
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr("src.rule_scheduler._resolve_rule_state_file",
                        lambda: state_file)
    href = "/orgs/1/sec_policy/active/rule_sets/1"
    db = ScheduleDB(str(tmp_path / "rule_schedules.json"))
    db.db = {href: {
        "type": "recurring", "name": "rs", "is_ruleset": True,
        "action": "allow", "days": ["mon", "tue", "wed", "thu", "fri",
                                     "sat", "sun"],
        "start": "00:00", "end": "23:59", "timezone": "UTC",
    }}
    api = MagicMock()
    api.has_draft_changes.return_value = False
    api.get_live_item.return_value = (200, {"enabled": False})
    api.toggle_and_provision.return_value = False
    engine = ScheduleEngine(db, api)
    engine.check(silent=True, tz_str="UTC")
    states = json.load(open(state_file))["rule_schedule_states"]
    entry = states[href]
    assert entry["last_result"] == "error"


def test_schedules_list_enriches_last_state(client, monkeypatch, tmp_path):
    """GET /api/rule_scheduler/schedules must enrich each schedule with
    last_checked/last_action/last_result read from state.json, mirroring the
    report-schedules list enrichment in gui/routes/reports.py."""
    import json
    from tests._helpers import _csrf

    href = "/orgs/1/sec_policy/active/rule_sets/1"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "rule_schedules.json").write_text(json.dumps({
        href: {
            "type": "recurring", "name": "rs", "is_ruleset": True,
            "action": "allow", "days": ["mon", "tue", "wed", "thu", "fri",
                                         "sat", "sun"],
            "start": "00:00", "end": "23:59", "timezone": "UTC",
        }
    }), encoding="utf-8")

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "rule_schedule_states": {
            href: {
                "last_checked": "2026-07-16T00:00:00Z",
                "last_action": "enable",
                "last_result": "ok",
            }
        }
    }), encoding="utf-8")

    monkeypatch.setattr("src.gui.routes.rule_scheduler._resolve_config_dir",
                        lambda: str(config_dir))
    monkeypatch.setattr("src.rule_scheduler._resolve_rule_state_file",
                        lambda: str(state_file))
    monkeypatch.setattr("src.api_client.ApiClient.get_live_item",
                        lambda self, h: (200, {"enabled": True, "name": "rs"}))

    login = client.post(
        "/api/login",
        json={"username": "admin", "password": "testpass"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert login.status_code == 200
    _csrf(login)

    resp = client.get(
        "/api/rule_scheduler/schedules",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 1
    entry = body[0]
    assert entry["last_checked"] == "2026-07-16T00:00:00Z"
    assert entry["last_action"] == "enable"
    assert entry["last_result"] == "ok"
