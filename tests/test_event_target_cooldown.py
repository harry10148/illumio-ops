"""immediate 型事件規則依目標分別冷卻。

舊版以規則為單位：主機 A 觸發 agent.tampering 後的冷卻期間，主機 B 的
tampering 只記一筆抑制、不送也不彙總。
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _ana():
    from src.analyzer import Analyzer
    ana = Analyzer.__new__(Analyzer)
    ana.state = {"alert_history": {}}
    ana.stats = MagicMock()
    ana.alert_throttler = MagicMock()
    ana.alert_throttler.allow.return_value = (True, {})
    return ana


def _event(host):
    return {"href": f"/orgs/1/events/{host}", "event_type": "agent.tampering",
            "timestamp": "2026-10-01T00:00:00Z"}


RULE = {"id": 7, "name": "tamper", "cooldown_minutes": 30}


def _norm(*hosts):
    from src.events.poller import event_identity
    return {event_identity(_event(h)): {"target_name": h} for h in hosts}


def test_other_target_still_alerts_during_cooldown():
    ana = _ana()
    norm = _norm("host-a", "host-b")

    first = ana._filter_targets_in_cooldown(RULE, [_event("host-a")], norm)
    assert ana._check_cooldown(RULE, target_keys=ana._event_target_keys(RULE, first, norm))

    # 同一個冷卻期間：host-b 仍要告警，host-a 被擋
    kept = ana._filter_targets_in_cooldown(RULE, [_event("host-a"), _event("host-b")], norm)
    assert [e["href"] for e in kept] == ["/orgs/1/events/host-b"]
    assert ana._check_cooldown(RULE, target_keys=ana._event_target_keys(RULE, kept, norm))

    # 兩台都在冷卻中：全部擋下並記一筆抑制
    assert ana._filter_targets_in_cooldown(RULE, [_event("host-a"), _event("host-b")], norm) == []
    ana.stats.record_suppression.assert_called()


def test_rule_level_history_still_recorded_for_gui():
    """GUI 規則列表讀 alert_history[rule_id] 顯示最後告警時間，必須照樣寫入。"""
    ana = _ana()
    assert ana._check_cooldown(RULE, target_keys=["7|host-a"])
    assert "7" in ana.state["alert_history"] and "7|host-a" in ana.state["alert_history"]
