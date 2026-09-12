"""健康告警的主旨嚴重度，必須跟本文說的一致。

成因（2026-09-12，從一則真的 LINE 告警查出來）：畫面上主旨是 `[INFO]`、本文是
`【重大】PCE 連線看門狗 … 事件與流量告警目前處於盲區`。那個矛盾本身就是證據。

`analyzer.py` 的三個健康告警產生處寫的都是 `status`，而決定主旨嚴重度的
`Reporter._highest_severity` 讀的是 `severity`，兩者沒有人接起來——於是**每一則
健康告警**都落到預設的 info，不只看門狗。後果是最該被看到的那一類（「監控已經
瞎了」）在以主旨分流的收件端會被濾掉，正好抵消這個告警存在的理由。

斷言對準「收件人看到什麼嚴重度」，不是對準某個 dict 有沒有某個鍵。
"""
from __future__ import annotations

import pytest

from src.reporter import Reporter


def _reporter():
    r = Reporter.__new__(Reporter)
    r.health_alerts = []
    r.event_alerts = []
    r.traffic_alerts = []
    r.metric_alerts = []
    r._alert_ids = {"health": [], "event": [], "traffic": [], "metric": []}
    return r


@pytest.mark.parametrize("status, expected", [
    ("critical", "critical"),
    ("warning", "warning"),
    ("info", "info"),
])
def test_the_digest_severity_matches_what_the_health_alert_says(status, expected):
    r = _reporter()
    r.add_health_alert({"time": "t", "rule": "PCE 連線看門狗",
                        "status": status, "details": "d"})
    assert Reporter._highest_severity(r.health_alerts) == expected


def test_a_critical_health_alert_is_never_summarised_as_info():
    """這一條是那則真告警的回歸：主旨不可以說 info。"""
    r = _reporter()
    r.add_health_alert({"time": "t", "rule": "PCE 連線看門狗",
                        "status": "critical",
                        "details": "PCE 輪詢已連續失敗 936 個週期"})
    assert Reporter._highest_severity(r.health_alerts) != "info"


def test_an_explicit_severity_wins_over_status():
    """呼叫端若自己寫了 severity，就不該被 status 覆蓋掉。"""
    r = _reporter()
    r.add_health_alert({"time": "t", "rule": "x", "status": "critical",
                        "severity": "warning", "details": "d"})
    assert r.health_alerts[0]["severity"] == "warning"


def test_an_alert_without_a_status_is_left_alone():
    r = _reporter()
    r.add_health_alert({"time": "t", "rule": "x", "details": "d"})
    assert "severity" not in r.health_alerts[0]
    assert Reporter._highest_severity(r.health_alerts) == "info"


def test_every_health_alert_emitter_still_only_sets_status():
    """這個修法的前提是「產生端寫 status」。哪天有人改成寫 severity，這條會
    提醒他回來看這裡——不是要禁止，是不要讓兩套慣例默默並存。"""
    import inspect
    from src import analyzer
    src = inspect.getsource(analyzer)
    emitters = src.count("add_health_alert(")
    assert emitters == 3, f"健康告警產生處變成 {emitters} 個，回來確認新的那個寫的是什麼鍵"
