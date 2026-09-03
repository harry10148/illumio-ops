"""Phase 3A Task 1 — AlertStore (logs/alerts.sqlite) and rule identity on alert items."""
from __future__ import annotations

import datetime
import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest


def _store(tmp_path):
    from src.alerts.store import AlertStore
    return AlertStore(str(tmp_path / "alerts.sqlite"))


def _row(**over):
    base = dict(
        fired_at="2026-09-03T08:00:00Z", type="traffic", rule_id="abc123", rule_name="SSH from outside",
        severity="warning", summary="SSH from outside · 24 · port 22", criteria="port 22 > 20 in 5m",
        payload={"rule": "SSH from outside", "count": "24", "raw_data": [{"a": 1}]},
        dispatch=[{"channel": "mail", "status": "success", "target": "***", "error": ""}],
    )
    base.update(over)
    return base


# ── file + schema ────────────────────────────────────────────────────────────

def test_new_store_is_owner_only_and_versioned(tmp_path):
    st = _store(tmp_path)
    path = str(tmp_path / "alerts.sqlite")
    assert os.path.exists(path)
    assert os.stat(path).st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    del st


def test_default_path_lives_under_logs(monkeypatch):
    """The unpatched resolver (tests run under conftest's redirect fixture)."""
    import src.alerts.store as store_mod
    from src.config import ROOT_DIR
    monkeypatch.undo()   # drop the autouse redirect for this assertion only
    assert store_mod.default_alerts_db_path() == os.path.join(ROOT_DIR, "logs", "alerts.sqlite")


def test_store_without_path_uses_the_resolver(tmp_path, _isolate_alert_store):
    from src.alerts.store import AlertStore
    assert AlertStore().path == _isolate_alert_store


# ── round trip ───────────────────────────────────────────────────────────────

def test_insert_then_get_round_trips_payload_and_dispatch(tmp_path):
    st = _store(tmp_path)
    rid = st.insert(**_row())
    got = st.get(rid)
    assert got["id"] == rid
    assert got["payload"] == _row()["payload"]
    assert got["dispatch"] == _row()["dispatch"]
    assert got["status"] == "new" and got["status_by"] is None
    assert got["rule_id"] == "abc123" and got["type"] == "traffic"
    assert st.get(rid + 99) is None


def test_update_dispatch_replaces_results(tmp_path):
    st = _store(tmp_path)
    rid = st.insert(**_row(dispatch=[{"channel": "mail", "status": "failed", "target": "", "error": "x"}]))
    st.update_dispatch(rid, [{"channel": "mail", "status": "success", "target": "***", "error": ""}])
    assert st.get(rid)["dispatch"][0]["status"] == "success"


def test_insert_rejects_unknown_type_and_severity_kept_verbatim(tmp_path):
    st = _store(tmp_path)
    with pytest.raises(ValueError):
        st.insert(**_row(type="weird"))
    rid = st.insert(**_row(type="system", severity="critical", rule_id=None))
    assert st.get(rid)["severity"] == "critical" and st.get(rid)["rule_id"] is None


# ── list / count / status ────────────────────────────────────────────────────

def test_list_filters_pages_and_counts(tmp_path):
    st = _store(tmp_path)
    for i in range(7):
        st.insert(**_row(fired_at=f"2026-09-03T08:0{i}:00Z", type="event" if i % 2 else "traffic"))
    done = st.insert(**_row(fired_at="2026-09-03T09:00:00Z"))
    assert st.set_status(done, "done", by="harry") is True

    page = st.list(status="new", page=1, page_size=3)
    assert page["total"] == 7 and len(page["items"]) == 3 and page["page"] == 1
    assert page["items"][0]["fired_at"] == "2026-09-03T08:06:00Z"      # newest first
    assert "payload" not in page["items"][0]
    assert st.list(type="event")["total"] == 3
    assert st.list(since="2026-09-03T08:05:00Z")["total"] == 3          # 08:05, 08:06, 09:00
    assert st.count(status="new") == 7 and st.count(status="done") == 1
    assert st.list(page=3, page_size=3)["items"] and st.list(page=4, page_size=3)["items"] == []


def test_set_status_rules(tmp_path):
    st = _store(tmp_path)
    rid = st.insert(**_row())
    assert st.set_status(rid, "ack", by="harry") is True
    got = st.get(rid)
    assert got["status"] == "ack" and got["status_by"] == "harry" and got["status_at"].endswith("Z")
    assert st.set_status(rid + 5, "ack", by="harry") is False
    with pytest.raises(ValueError):
        st.set_status(rid, "closed", by="harry")


def test_prune_deletes_only_older_than_days(tmp_path):
    st = _store(tmp_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    old = (now - datetime.timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st.insert(**_row(fired_at=old)); st.insert(**_row(fired_at=old)); st.insert(**_row(fired_at=fresh))
    assert st.prune(days=30) == 2
    assert st.list()["total"] == 1


# ── rule identity on alert items ─────────────────────────────────────────────

def _make_analyzer(rules):
    from src.analyzer import Analyzer
    cm = MagicMock(); cm.config = {"rules": rules}
    az = Analyzer(cm, MagicMock(), MagicMock())
    az.load_state = MagicMock(); az.save_state = MagicMock()
    return az


def test_event_alert_items_carry_rule_identity():
    from src.events.poller import EventBatch
    rule = {"id": 18, "name": "Login failed", "type": "event", "threshold_type": "instant",
            "threshold_count": 1, "threshold_window": 10, "filter_type": "any", "filter_value": ""}
    az = _make_analyzer([rule])
    raw = {"timestamp": "2026-01-01T00:00:00Z", "event_type": "user.login",
           "severity": "warning", "status": "success", "created_by": {}}
    az._fetch_event_batch = MagicMock(return_value=EventBatch(
        events=[raw], next_watermark="2026-01-01T00:00:00Z", query_since="2026-01-01T00:00:00Z",
        query_until="2026-01-01T00:00:00Z", raw_count=1, overflow_risk=False, seen_events={}))
    with patch("src.analyzer.matches_event_rule", return_value=True):
        az._run_event_analysis()
    item = az.reporter.add_event_alert.call_args[0][0]
    assert item["rule_id"] == "18"          # stringified, like _check_cooldown's key
    assert item["rule_type"] == "event"


def test_traffic_alert_items_carry_rule_identity():
    rule = {"id": "r1", "name": "Rule r1", "type": "traffic", "threshold_type": "count",
            "threshold_count": 1, "threshold_window": 10, "pd": -1}
    az = _make_analyzer([rule])
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = (now - datetime.timedelta(seconds=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    flow = {"timestamp": ts, "policy_decision": "blocked", "num_connections": 5, "pd": 2,
            "src": {}, "dst": {}, "service": {}}
    with patch.object(az, "check_flow_match", return_value=True):
        triggers = az._run_rule_engine(iter([flow]), [rule], now)
    with patch.object(az, "_check_cooldown", return_value=True):
        az._dispatch_alerts(triggers, [rule])
    item = az.reporter.add_traffic_alert.call_args[0][0]
    assert item["rule_id"] == "r1" and item["rule_type"] == "traffic"


def test_health_rule_alert_items_carry_rule_identity():
    rule = {"id": 7, "name": "PCE health", "type": "system", "filter_value": "pce_health"}
    az = _make_analyzer([rule])
    az.stats = MagicMock()
    with patch.object(az, "_check_cooldown", return_value=True):
        az._record_health_failure([rule], status="degraded", details="details", probe="health",
                                  deployment="saas", category="health")
    item = az.reporter.add_health_alert.call_args[0][0]
    assert item["rule_id"] == "7" and item["rule_type"] == "system"
