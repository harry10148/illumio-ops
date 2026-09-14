"""Task 1 — `analyze_fleet` 這個純函式：compat 四態、數值版本、重正規化的分數。

Spec: docs/superpowers/specs/2026-09-09-ven-fleet-manager-design.md §2.2
Plan: docs/superpowers/plans/2026-09-09-ven-fleet-manager.md Task 1

工作負載的形狀沿用 `tests/test_ven_report_estate.py` 的既有 fixture 慣例
（`agent.status` 底下那一包），而不是照 spec 重新想像一份——這個 repo 記過的
教訓是「比真實紀錄更整齊的 fixture 會藏住它本來要抓的缺陷」。

lab 21 台實測 `agent_health` 全空、`agent_health_errors` 為
`{"errors": [], "warnings": []}`，所以 compat 的四態只能靠 fixture 驗；
兩種空值形狀都要吃得下。
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.report.analysis.fleet import (
    PIPELINE_BUCKETS,
    VALID_PROGRESSIONS,
    analyze_fleet,
    compat_state,
    parse_ven_version,
)

NOW = dt.datetime(2026, 9, 9, 12, 0, 0, tzinfo=dt.timezone.utc)


def _wl(hostname, mode="selective", *, version="26.2.20-2063", status="active",
        hslh=0.1, labels=None, agent_health=None, policy_received="2026-09-09T00:00:00Z",
        os_id="ubuntu-x86_64-22.04", href=None):
    st = {
        "status": status,
        "hours_since_last_heartbeat": hslh,
        "last_heartbeat_on": "2026-09-09T11:55:00Z",
        "agent_version": version,
        "security_policy_received_at": policy_received,
        "agent_health": agent_health if agent_health is not None else [],
        "agent_health_errors": {"errors": [], "warnings": []},
    }
    return {
        "href": href or ("/orgs/1/workloads/" + hostname),
        "hostname": hostname,
        "os_id": os_id,
        "enforcement_mode": mode,
        "labels": labels if labels is not None else [{"key": "app", "value": "web"},
                                                     {"key": "env", "value": "prod"}],
        "interfaces": [],
        "agent": {"status": st},
    }


# ── compat 四態 ──────────────────────────────────────────────────────────────

def test_compat_state_covers_all_four_and_ignores_case_in_type():
    """無 compat 項→unknown；任一 error→fail；否則任一 warning→warn；否則 pass。

    `type` 在真實紀錄裡大小寫不一致（見過 "Compatibility"），所以比對前一律
    降冪；severity 的 "err" 是 PCE 的寫法，不是 "error"。
    """
    assert compat_state([]) == "unknown"
    assert compat_state([{"type": "agent_missing_heartbeat", "severity": "err"}]) == "unknown"
    assert compat_state([{"type": "Compatibility", "severity": "err"}]) == "fail"
    assert compat_state([{"type": "compatibility_check", "severity": "warning"}]) == "warn"
    assert compat_state([{"type": "compatibility_check", "severity": "info"}]) == "pass"
    # error 蓋過 warning，順序無關
    assert compat_state([{"type": "compatibility_check", "severity": "warning"},
                         {"type": "Compatibility", "severity": "err"}]) == "fail"


# ── 版本 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("26.2.20-2063", (26, 2, 20, 2063)),
    ("23.4.11-8", (23, 4, 11, 8)),
    ("21.5", (21, 5)),
    ("", None),
    ("dev", None),
    (None, None),
])
def test_parse_ven_version(raw, expected):
    assert parse_ven_version(raw) == expected


def test_versions_are_ordered_numerically_with_unparsable_last():
    """排序依據必須是數值 tuple，不是字串。

    fixture 刻意含 "9.5.1-1"：字串降冪會把它排到 "26.2.20-2063" **前面**
    （"9" > "2"），數值降冪則排最後。26/25/23 三個版本的字串序與數值序恰好
    一致，只用它們的話這支測試永遠綠——第一版就是這樣，注入字串排序沒變紅
    才發現。
    """
    wls = [_wl("a", version="26.2.20-2063"), _wl("b", version="9.5.1-1"),
           _wl("c", version="23.4.11-8"), _wl("d", version="dev")]
    out = analyze_fleet(wls, NOW, None)
    assert out["versions"]["ordered"] == ["26.2.20-2063", "23.4.11-8", "9.5.1-1", "dev"]
    assert out["versions"]["unparsable"] == ["dev"]
    assert out["versions"]["newest"] == "26.2.20-2063"
    assert out["versions"]["oldest"] == "9.5.1-1"


# ── health score ─────────────────────────────────────────────────────────────

def test_no_target_means_no_upgrade_count_and_a_partial_renormalised_score():
    """target 是 None 時 version 分量不存在，分數用剩下的權重重正規化。

    三個存在的分量（online / enforcement / heartbeat）全滿 → 100，而 `partial`
    要說出「這不是五個分量都算過的分數」。把缺的分量當 0 會讓一個健康的車隊
    看起來像壞掉的。
    """
    wls = [_wl("h%d" % i, mode="full") for i in range(4)]
    out = analyze_fleet(wls, NOW, None)
    assert out["versions"]["needs_upgrade"] is None
    assert out["versions"]["target"] is None
    hs = out["health_score"]
    assert hs["components"]["version"]["present"] is False
    assert hs["components"]["compat"]["present"] is False
    assert hs["partial"] is True
    assert hs["score"] == 100


def test_an_empty_fleet_has_no_score_rather_than_a_zero():
    out = analyze_fleet([], NOW, None)
    assert out["total"] == 0
    assert out["health_score"]["score"] is None


# ── 管線與索引 ───────────────────────────────────────────────────────────────

def _fleet21():
    """1 idle、1 visibility_only、18 selective online、1 selective offline。"""
    wls = [_wl("idle-1", mode="idle",
               agent_health=[{"type": "compatibility_check", "severity": "warning"}]),
           _wl("vis-1", mode="visibility_only")]
    wls += [_wl("sel-%02d" % i) for i in range(18)]
    wls.append(_wl("sel-off", status="active", hslh=72.0))
    return wls


def test_pipeline_counts_agree_with_the_index_and_the_totals():
    out = analyze_fleet(_fleet21(), NOW, "26.2.20-2063")
    assert out["total"] == 21
    assert len(out["workloads_index"]) == 21
    assert out["index_truncated"] is False
    assert set(out["pipeline"]) == set(PIPELINE_BUCKETS)
    assert sum(b["count"] for b in out["pipeline"].values()) == 21
    assert out["pipeline"]["idle_compat_warn"]["count"] == 1
    assert out["pipeline"]["visibility_ready"]["count"] == 1
    assert out["pipeline"]["selective"]["count"] == 19
    assert out["managed_online"] == 20
    assert out["managed_offline"] == 1


def test_top_n_truncates_the_sample_but_never_the_count():
    """sample 是拿來看的，count 是拿來信的——截斷不得改變後者。"""
    out = analyze_fleet(_fleet21(), NOW, None, top_n=2)
    sel = out["pipeline"]["selective"]
    assert sel["count"] == 19
    assert len(sel["sample"]) == 2


def test_index_cap_drops_the_index_and_says_so():
    out = analyze_fleet(_fleet21(), NOW, None, index_cap=5)
    assert out["index_truncated"] is True
    assert out["workloads_index"] == []
    # 計數不受影響：截斷的是索引，不是分析
    assert out["total"] == 21
    assert out["pipeline"]["selective"]["count"] == 19


def test_a_workload_with_no_labels_is_unlabeled():
    wls = [_wl("bare", labels=[]), _wl("tagged")]
    out = analyze_fleet(wls, NOW, None)
    gaps = out["coverage_gaps"]
    assert gaps["unlabeled"]["count"] == 1
    assert gaps["unlabeled"]["sample"][0]["hostname"] == "bare"
    assert gaps["by_app"]["web"] == {"selective": 1}


def test_valid_progressions_never_go_backwards():
    """PCE 寫入的白名單：模式只能往前推，不能退。"""
    assert VALID_PROGRESSIONS["idle"] == {"visibility_only", "selective", "full"}
    assert VALID_PROGRESSIONS["visibility_only"] == {"selective", "full"}
    assert VALID_PROGRESSIONS["selective"] == {"full"}
    assert "full" not in VALID_PROGRESSIONS


def test_a_fleet_with_no_parsable_version_has_no_oldest_or_newest():
    """全是 "dev" 的車隊沒有「最舊」可言——回 None 比回一個任意字串誠實。"""
    wls = [_wl("a", version="dev"), _wl("b", version="snapshot")]
    v = analyze_fleet(wls, NOW, None)["versions"]
    assert v["oldest"] is None and v["newest"] is None
    assert v["unparsable"] == ["dev", "snapshot"]
    assert v["ordered"] == ["dev", "snapshot"]


def test_offline_is_not_the_same_as_stale_heartbeat():
    """online 門檻是 1 小時，heartbeat 分桶的 fresh 是 24 小時——兩把尺。

    一台心跳 3 小時前的 VEN 是「離線」但心跳仍 fresh；把兩者混為一談，會讓
    「多久沒回報」這個問題得到一個關於「現在連不連得上」的答案。
    """
    out = analyze_fleet([_wl("a", hslh=3.0)], NOW, None)
    assert out["managed_online"] == 0
    assert out["heartbeat"] == {"fresh": 1, "stale_24h": 0, "stale_48h": 0, "no_heartbeat": 0}


def test_a_workload_with_no_heartbeat_at_all_is_offline_not_fresh():
    wl = _wl("a")
    wl["agent"]["status"]["hours_since_last_heartbeat"] = None
    wl["agent"]["status"]["last_heartbeat_on"] = ""
    out = analyze_fleet([wl], NOW, None)
    assert out["managed_online"] == 0
    assert out["heartbeat"]["no_heartbeat"] == 1
