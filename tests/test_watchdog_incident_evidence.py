"""看門狗的判斷依據：事故要留下證據，訊息要講時間。

2026-09-12 的實例：使用者在 11:02 收到「PCE 輪詢已連續失敗 936 個週期」的 LINE
告警，兩分鐘後查 state.json 只看到 `consecutive_failures: 0` /
`watchdog_last_alert_at: None`——因為期間有一次探測成功，而
`record_pce_success` 把**計數**與**冷卻時戳**一起歸零了。自癒機制吃掉了事後
診斷能力：告警說剛剛盲了 936 次，系統裡卻查不到那件事發生過。

同一則訊息還有兩個判讀問題：
  · 「936 個週期」在不同輪詢間隔上是完全不同的時長，收訊的人無從判斷盲了多久。
  · 「最近錯誤」取的是 `last_error`（**最後一次**記錄的錯誤），未必屬於它正在
    計數的那串失敗——當時告警說 `/noop` 401，state 裡的 last_error 卻是
    `/health` 200 body=critical。

這支測試守的就是這三件事。
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

from src.analyzer import Analyzer, WATCHDOG_FAILURE_THRESHOLD, humanize_outage
from src.events import StatsTracker
from src.events.poller import format_utc


@pytest.fixture
def tracker() -> StatsTracker:
    return StatsTracker({})


@pytest.fixture
def ana(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = []
    return Analyzer(cm, MagicMock(), MagicMock())


# ── 失敗串的起點 ───────────────────────────────────────────────────────────

def test_the_first_failure_records_when_the_run_started(tracker):
    tracker.record_pce_error("health", "connection refused", status=None)
    stats = tracker.state["pce_stats"]
    assert stats["consecutive_failures"] == 1
    assert stats["failure_run_started_at"], "0→1 必須寫下這串失敗的起點"
    assert "connection refused" in stats["failure_run_first_error"]
    assert stats["failure_run_first_stage"] == "health"


def test_later_failures_do_not_move_the_start(tracker):
    tracker.record_pce_error("health", "connection refused")
    started = tracker.state["pce_stats"]["failure_run_started_at"]
    tracker.record_pce_error("events", "read timeout")
    tracker.record_pce_error("events", "read timeout")
    stats = tracker.state["pce_stats"]
    assert stats["consecutive_failures"] == 3
    assert stats["failure_run_started_at"] == started
    # 起始錯誤仍是**開啟**這串失敗的那一個，不是最新的那一個。
    assert "connection refused" in stats["failure_run_first_error"]
    assert stats["failure_run_first_stage"] == "health"
    # last_error 照舊是最新的——兩者是不同的問題，各自保留。
    assert "read timeout" in stats["last_error"]


# ── 復原時保留事故，而不是抹掉它 ───────────────────────────────────────────

def test_recovery_keeps_the_incident_instead_of_erasing_it(tracker):
    tracker.record_pce_error("health", "connection refused")
    tracker.record_pce_error("health", "still refused")
    tracker.record_pce_success("health")

    stats = tracker.state["pce_stats"]
    assert stats["consecutive_failures"] == 0, "目前狀態照舊歸零"
    incident = stats["last_incident"]
    assert incident["failures"] == 2
    assert incident["started_at"]
    assert incident["ended_at"]
    assert "connection refused" in incident["first_error"]
    assert incident["first_stage"] == "health"
    assert "still refused" in incident["last_error"]
    # 現役欄位清乾淨，下一串失敗才不會接到上一串的起點上。
    assert not stats["failure_run_started_at"]


def test_the_incident_record_says_whether_anyone_was_told(tracker):
    """`alerted` 是在冷卻時戳被清掉**之前**讀的——否則永遠是 False。

    這也是 2026-09-12 那次唯一能回答「這台到底有沒有發過警」的欄位。
    """
    tracker.record_pce_error("health", "down")
    tracker.state["watchdog_last_alert_at"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc)
    )
    tracker.record_pce_success("health")
    assert tracker.state["pce_stats"]["last_incident"]["alerted"] is True
    assert tracker.state["watchdog_last_alert_at"] is None


def test_an_unalerted_incident_is_recorded_as_unalerted(tracker):
    tracker.record_pce_error("health", "down")
    tracker.record_pce_success("health")
    assert tracker.state["pce_stats"]["last_incident"]["alerted"] is False


def test_a_success_with_no_failures_leaves_the_previous_incident_alone(tracker):
    tracker.record_pce_error("health", "down")
    tracker.record_pce_success("health")
    first = dict(tracker.state["pce_stats"]["last_incident"])
    tracker.record_pce_success("health")
    tracker.record_pce_success("events")
    assert tracker.state["pce_stats"]["last_incident"] == first, (
        "每次成功都覆寫 last_incident 等於沒有保留——健康的系統會在幾分鐘內"
        "把唯一那筆事故洗掉"
    )


def test_recovery_still_clears_the_watchdog_cooldown(tracker):
    """既有契約不得被上面那些新欄位改掉。"""
    tracker.record_pce_error("health", "down")
    tracker.state["watchdog_last_alert_at"] = "2026-01-01T00:00:00Z"
    tracker.record_pce_success("health")
    assert tracker.state["pce_stats"]["consecutive_failures"] == 0
    assert tracker.state["watchdog_last_alert_at"] is None


# ── 時長 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("minutes", [0, 1, 45, 90, 60 * 5, 60 * 26, 60 * 24 * 9])
def test_humanize_outage_never_leaks_a_template(minutes):
    text = humanize_outage(minutes)
    assert text and "{" not in text and "}" not in text


def test_humanize_outage_scales_the_unit():
    assert humanize_outage(45) != humanize_outage(60 * 5)
    assert humanize_outage(60 * 5) != humanize_outage(60 * 24 * 3)


# ── 告警訊息 ──────────────────────────────────────────────────────────────

def _fire(ana, *, started_minutes_ago: int | None, first_error: str = "",
          first_stage: str = "health", last_error: str = "",
          failures: int = WATCHDOG_FAILURE_THRESHOLD) -> dict:
    stats = ana.state["pce_stats"]
    stats["consecutive_failures"] = failures
    stats["last_error"] = last_error
    if started_minutes_ago is not None:
        stats["failure_run_started_at"] = format_utc(
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=started_minutes_ago)
        )
        stats["failure_run_first_error"] = first_error
        stats["failure_run_first_stage"] = first_stage
    ana._check_watchdog()
    ana.reporter.add_health_alert.assert_called_once()
    return ana.reporter.add_health_alert.call_args[0][0]


def test_the_alert_says_how_long_the_blind_spot_has_lasted(ana):
    alert = _fire(ana, started_minutes_ago=137, first_error="connection refused")
    details = alert["details"]
    assert humanize_outage(137) in details, (
        "「連續失敗 N 次」在不同輪詢間隔上是不同的時長；收訊的人要的是時間"
    )
    assert str(WATCHDOG_FAILURE_THRESHOLD) in details, "次數仍然要在，只是不再是唯一的量"


def test_the_alert_quotes_the_error_that_opened_the_run(ana):
    alert = _fire(
        ana, started_minutes_ago=20,
        first_error="POST /noop failed: auth_failed (HTTP 401)",
        last_error="GET /health 200 body=critical",
    )
    assert "401" in alert["details"]
    assert "body=critical" not in alert["details"], (
        "last_error 是最後一次記錄的錯誤，未必屬於正在計數的這串失敗"
    )


def test_the_alert_falls_back_cleanly_when_the_start_is_unknown(ana):
    """升版前就已在進行中的失敗串沒有起點欄位——訊息要退化，不能印出樣板。"""
    alert = _fire(ana, started_minutes_ago=None, last_error="connection refused")
    details = alert["details"]
    assert "{" not in details and "}" not in details
    assert str(WATCHDOG_FAILURE_THRESHOLD) in details
    assert "connection refused" in details, "沒有起始錯誤時退回 last_error 總比沒有好"


def test_the_alert_is_still_critical(ana):
    alert = _fire(ana, started_minutes_ago=5, first_error="down")
    assert alert["status"] == "critical"


def test_the_alert_leaves_a_trace_that_a_recovery_cannot_erase(ana):
    """2026-09-12 的告警送達了，這台卻查不到任何發警痕跡。

    log 會輪替、計數會被下一次成功歸零，`event_timeline` 兩者都不是：它隨
    state.json 保存、以 append 合併，`record_pce_success` 不碰它。
    """
    _fire(ana, started_minutes_ago=30, first_error="connection refused")
    marks = [e for e in ana.state["event_timeline"] if e.get("kind") == "watchdog"]
    assert len(marks) == 1
    assert marks[0]["details"]["failures"] == WATCHDOG_FAILURE_THRESHOLD

    ana.stats.record_pce_success("health")
    assert [e for e in ana.state["event_timeline"] if e.get("kind") == "watchdog"] == marks


def test_a_run_already_under_way_at_upgrade_does_not_invent_a_start(ana):
    """升版當下磁碟上已有一串失敗（計數 936、沒有起點欄位）。

    若在起點缺席時「順手補寫」，起點會變成**現在**、起始錯誤會變成第 937 次的
    那一個，告警於是說「937 次、中斷 0 分鐘」——時長與錯誤都是假的，而這正是
    2026-09-12 那個事故的形狀。沒有起點就只講次數。
    """
    ana.state["pce_stats"]["consecutive_failures"] = 936
    ana.state["pce_stats"].pop("failure_run_started_at", None)
    ana.stats.record_pce_error("health", "still refused")

    assert not ana.state["pce_stats"].get("failure_run_started_at")
    ana._check_watchdog()
    details = ana.reporter.add_health_alert.call_args[0][0]["details"]
    assert humanize_outage(0) not in details, "不能憑空生出一個 0 分鐘的中斷時長"
    assert "937" in details
    assert "still refused" in details


# ── 文案：Codex UI 評估 2026-09-13 的四條 ────────────────────────────────────

def test_the_message_actually_leads_with_time_not_the_count(ana):
    """`_check_watchdog` 的註解寫著「the MESSAGE leads with elapsed time」，
    但第一版的字串是「已連續失敗 936 次、中斷 39 小時」——**次數仍然在前**。
    註解宣稱了實作沒做到的事，而沒有任何測試在看那個順序。
    """
    # 計數刻意不用門檻值 3：時長字串「39 小時」裡就有一個 3，找裸數字會命中它。
    alert = _fire(ana, started_minutes_ago=2340, first_error="connection refused",
                  failures=936)
    details = alert["details"]
    duration = humanize_outage(2340)
    assert duration in details and "936" in details
    assert details.index(duration) < details.index("936"), (
        f"時長要在次數之前：{details!r}"
    )


def test_a_blind_spot_shorter_than_a_minute_does_not_say_zero(ana):
    """「已持續失敗 0 分鐘」讀起來是自相矛盾的。"""
    assert "0" not in humanize_outage(0)
    alert = _fire(ana, started_minutes_ago=0, first_error="down")
    assert humanize_outage(0) in alert["details"]


def test_the_nostart_message_says_the_duration_is_unknown(ana):
    """沒有起點時訊息會突然少掉時長——收件者不知道是「很短」還是「不知道」。"""
    alert = _fire(ana, started_minutes_ago=None, last_error="connection refused")
    from src.i18n import t
    assert t('alert_watchdog_duration_unknown') in alert["details"]


@pytest.mark.parametrize("started", [137, None])
def test_both_variants_warn_that_zero_alerts_is_not_all_clear(ana, started):
    """盲區訊息會跟「安全事件：0 流量告警：0」並排顯示。

    那個零正是盲區造成的，卻最容易被讀成「一切平安」——把盲區的意思讀反了。
    """
    alert = _fire(ana, started_minutes_ago=started, first_error="down", last_error="down")
    from src.i18n import t
    assert t('alert_watchdog_zero_caveat') in alert["details"]
