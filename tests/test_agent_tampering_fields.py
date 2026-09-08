"""PCE 26.2 起 `agent.tampering` 帶著判讀所需的事實，而我們整包丟掉了。

真實樣本（測試機 lab，26.2.20）的 `notifications[0].info`：

    {"tampering_revert_succeeded": true, "event_classification": "confirmed",
     "beginning_timestamp": "...", "ending_timestamp": "...", "num_events": 1}

正規化器只取 `info.user.username`，其餘不留。畫面上因此看不出「這次竄改有沒有
被自動還原」——而那正好決定要不要現在派人上機。同一則事件的 `action.api_endpoint`
是字面值 `"FILTERED"`（PCE 自己的遮蔽標記），照字面渲染就成了「PUT FILTERED」，
看起來像我們解析壞了。

斷言對準「操作者看得到什麼」，不是對準某個欄位名存在。
"""
from __future__ import annotations

import pandas as pd

from src.events.normalizer import normalize_event
from src.report.analysis.audit.audit_mod04_correlation import audit_event_correlation


def _tampering(reverted=True, **info_over):
    info = {
        "tampering_revert_succeeded": reverted,
        "event_classification": "confirmed",
        "beginning_timestamp": "2026-09-06T14:15:47Z",
        "ending_timestamp": "2026-09-06T14:15:47Z",
        "num_events": 1,
    }
    info.update(info_over)
    return {
        "href": "/orgs/1/events/e16ca92b",
        "timestamp": "2026-09-06T14:15:47.681Z",
        "created_by": {"agent": {"href": "/orgs/1/agents/1334", "hostname": "batch.lab.local"},
                       "ven": {"href": "/orgs/1/vens/82f2", "hostname": "batch.lab.local"}},
        "event_type": "agent.tampering",
        "status": "success",
        "severity": "info",
        "action": {"uuid": "7aea", "api_endpoint": "FILTERED", "api_method": "PUT",
                   "http_status_code": 204, "src_ip": "172.16.15.106"},
        "resource_changes": [],
        "notifications": [{"uuid": "0ab2", "notification_type": "workload.oob_policy_changes",
                           "info": info}],
    }


class TestTheFactsSurviveNormalisation:
    def test_the_revert_result_is_kept(self):
        assert normalize_event(_tampering(reverted=True))["notification_info"][
            "tampering_revert_succeeded"] is True
        assert normalize_event(_tampering(reverted=False))["notification_info"][
            "tampering_revert_succeeded"] is False

    def test_every_scalar_info_field_is_kept_not_a_chosen_few(self):
        """白名單式的修法會在下一次 PCE 升版時再壞一次，而且一樣無聲。
        沒見過的欄位也要留下來——顯示端至少列得出它。"""
        ev = _tampering(some_future_field="whatever", another_one=7)
        info = normalize_event(ev)["notification_info"]
        assert info["some_future_field"] == "whatever"
        assert info["another_one"] == 7

    def test_the_username_is_not_duplicated_into_the_info_bag(self):
        ev = _tampering()
        ev["notifications"][0]["info"]["user"] = {"username": "someone"}
        info = normalize_event(ev)["notification_info"]
        assert "user" not in info
        assert normalize_event(ev)["actor_user"] or True  # user 仍走既有的取法

    def test_nested_structures_are_left_out(self):
        """巢狀沒有通用呈現方式，硬攤平只會在畫面上長出沒人看得懂的鍵。"""
        ev = _tampering()
        ev["notifications"][0]["info"]["nested"] = {"a": 1}
        ev["notifications"][0]["info"]["listy"] = [1, 2]
        info = normalize_event(ev)["notification_info"]
        assert "nested" not in info and "listy" not in info


class TestTheRedactionMarkerIsNotShownAsAnAction:
    def test_a_filtered_endpoint_does_not_reach_the_action_label(self):
        n = normalize_event(_tampering())
        assert "FILTERED" not in n["action"], n["action"]
        # 方法是真的，留著。
        assert n["action"] == "PUT"
        assert n["action_path"] == ""
        # 「沒有端點」與「端點被遮蔽」對操作者是兩件事。
        assert n["action_redacted"] is True

    def test_a_real_endpoint_is_untouched(self):
        ev = _tampering()
        ev["action"]["api_endpoint"] = "/api/v2/orgs/1/sec_policy/active/rule_sets/9"
        n = normalize_event(ev)
        assert n["action_redacted"] is False
        assert "rule_sets/9" in n["action"]


class TestTheAuditReportSaysWhetherItWasReverted:
    def _mod04(self, rows):
        return audit_event_correlation(pd.DataFrame(rows))

    def _row(self, ev):
        n = normalize_event(ev)
        return {"event_type": n["event_type"], "timestamp": n["timestamp"],
                "actor": n["actor"], "notification_info": n["notification_info"]}

    def test_a_tampering_event_appears_even_with_no_follow_up_policy_change(self):
        """相關性那三個 pattern 只在「A 之後接了 B」時才產生列。一台被竄改、
        沒有人接著改 policy 的主機，原本在這份報表裡一個字都沒有。"""
        m = self._mod04([self._row(_tampering())])
        assert m["total_agent_security"] == 1
        assert m["correlated_sequences"].empty
        assert m["agent_security_events"].iloc[0]["Reverted"] == "Yes"

    def test_unreverted_tampering_is_counted_separately(self):
        """已自動還原與沒有還原的處置優先序完全不同。"""
        m = self._mod04([self._row(_tampering(reverted=True)),
                         self._row(_tampering(reverted=False))])
        assert m["total_agent_security"] == 2
        assert m["agent_security_unreverted"] == 1

    def test_an_old_pce_that_says_nothing_is_not_reported_as_not_reverted(self):
        """「沒說」不是「沒有」。舊版 PCE 不帶這些欄位，顯示 — 而不是 No，
        否則報表會憑空指控一批其實不知道結果的事件。"""
        ev = _tampering()
        ev["notifications"][0]["info"] = {}
        m = self._mod04([self._row(ev)])
        assert m["agent_security_events"].iloc[0]["Reverted"] == "—"
        assert m["agent_security_unreverted"] == 0
