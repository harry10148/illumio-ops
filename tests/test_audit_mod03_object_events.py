"""audit_policy_changes 的 object_events 輸出鍵。"""

import pandas as pd

from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes


def _events_df(rows):
    return pd.DataFrame(
        [{"timestamp": ts, "event_type": et, "resource_name": name,
          "severity": "info", "actor": "alice@corp"} for ts, et, name in rows]
    )


def test_object_events_key_present_and_filtered():
    df = _events_df([
        ("2026-07-01T00:00:00Z", "ip_list.update", "Corp-Nets"),
        ("2026-07-01T01:00:00Z", "service.create", "HTTPS-8443"),
        ("2026-07-01T02:00:00Z", "label_group.delete", "G1"),
        ("2026-07-01T03:00:00Z", "ip_lists.delete", "Bulk"),
        ("2026-07-01T04:00:00Z", "rule_set.update", "RS-A"),
    ])
    result = audit_policy_changes(df)
    obj = result["object_events"]
    assert set(obj["event_type"]) == {"ip_list.update", "service.create",
                                      "label_group.delete", "ip_lists.delete"}
    # draft_events 語義不變：只含 rule 事件
    assert set(result["draft_events"]["event_type"]) == {"rule_set.update"}


def test_object_events_empty_frame_on_no_policy_events():
    result = audit_policy_changes(pd.DataFrame({"event_type": ["login.success"], "timestamp": ["t"]}))
    assert result["object_events"].empty
