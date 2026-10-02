"""Alert accuracy: fires once when it should, never when it shouldn't.

Each test is a scenario found in the 2026-10 alert-pipeline review, written so
that it failed on the code before the fix.
"""
import datetime as dt
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    import src.analyzer as an
    import src.reporter as rp
    monkeypatch.setattr(an, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(rp, "STATE_FILE", str(tmp_path / "state.json"))


def _analyzer(rules, *, sub_events=None, settings=None, api=None):
    from src.analyzer import Analyzer
    cm = MagicMock()
    cm.config = {"rules": rules, "settings": settings or {}}
    rep = MagicMock()
    a = Analyzer(cm, api or MagicMock(), rep, subscriber_events=sub_events)
    a.save_state = MagicMock()
    return a, rep


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _cache(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


TAMPER = {"id": 1, "name": "Tampering", "type": "event", "filter_value": "agent.tampering",
          "threshold_type": "immediate", "threshold_count": 1, "threshold_window": 10,
          "cooldown_minutes": 30}


def _tamper_event(i, when, host="web01"):
    return {"href": f"/orgs/1/events/t{i}", "event_type": "agent.tampering",
            "severity": "warning", "status": "success", "timestamp": _iso(when),
            "created_by": {"agent": {"href": "/orgs/1/agents/9", "hostname": host}}}


# ── replayed history ────────────────────────────────────────────────────────

def test_a_backfilled_old_event_does_not_page(tmp_path):
    """Backfill stamps ingested_at=now, so a 10-day-old tampering event used to
    reach the analyzer as new and page on-call as if it had just happened."""
    from src.pce_cache.backfill import BackfillRunner
    from src.pce_cache.subscriber import CacheSubscriber

    sf = _cache(tmp_path)
    sub = CacheSubscriber(sf, consumer="analyzer", source_table="pce_events")
    assert sub.poll_new_rows() == []
    old = dt.datetime.now(UTC) - dt.timedelta(days=10)
    api = MagicMock()
    api.fetch_events.return_value = [_tamper_event(1, old)]
    api.last_fetch_error = None
    BackfillRunner(api, sf).run_events(old - dt.timedelta(hours=1), old + dt.timedelta(hours=1))

    a, rep = _analyzer([TAMPER], sub_events=sub)
    a._run_event_analysis()
    rep.add_event_alert.assert_not_called()


def test_a_fresh_event_still_pages():
    a, rep = _analyzer([TAMPER])
    a._analyze_event_batch([_tamper_event(2, dt.datetime.now(UTC))], None)
    assert rep.add_event_alert.call_count == 1


def test_a_replayed_event_is_counted_once():
    """A count rule counted the same event twice when the cache replayed it."""
    rule = {"id": 3, "name": "Login failures", "type": "event", "filter_value": "user.login",
            "filter_status": "failure", "threshold_type": "count", "threshold_count": 3,
            "threshold_window": 30, "cooldown_minutes": 30}
    a, rep = _analyzer([rule])
    now = dt.datetime.now(UTC)
    evs = [{"href": f"/orgs/1/events/l{i}", "event_type": "user.login", "status": "failure",
            "severity": "err", "timestamp": _iso(now), "created_by": {"system": {}}}
           for i in range(2)]
    a._analyze_event_batch(evs, None)
    a._analyze_event_batch(evs, None)          # same two events again
    rep.add_event_alert.assert_not_called()    # 2 distinct events < 3


# ── one bad rule ────────────────────────────────────────────────────────────

def test_a_non_numeric_cooldown_falls_back_instead_of_raising(tmp_path):
    """cooldown_minutes='abc' raised inside the batch: on the cache path the
    cursor never advanced, so the event pipeline stalled for good."""
    from src.pce_cache.models import PceEvent
    from src.pce_cache.subscriber import CacheSubscriber

    sf = _cache(tmp_path)
    now = dt.datetime.now(UTC)
    ev = _tamper_event(5, now)
    with sf.begin() as s:
        s.add(PceEvent(pce_href=ev["href"], pce_event_id="t5", timestamp=now,
                       event_type=ev["event_type"], severity="warning", status="success",
                       pce_fqdn="", raw_json=json.dumps(ev), ingested_at=now))
    sub = CacheSubscriber(sf, consumer="analyzer", source_table="pce_events")
    good = dict(TAMPER, id=1, name="Good", cooldown_minutes=0)
    bad = dict(TAMPER, id=2, name="Bad", cooldown_minutes="abc")

    a, rep = _analyzer([good, bad], sub_events=sub)
    a.state.setdefault("alert_history", {})["2|web01"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    a._run_event_analysis()
    assert rep.add_event_alert.call_count == 1          # good rule fired, bad one cooling
    assert sub._read_cursor() != (None, None)           # the cursor moved on

    a2, rep2 = _analyzer([good, bad], sub_events=sub)
    a2._run_event_analysis()
    rep2.add_event_alert.assert_not_called()            # not re-alerted every cycle


def test_one_rule_that_raises_does_not_stop_the_others(monkeypatch):
    import src.analyzer as an
    first = dict(TAMPER, id=1, name="Broken")
    second = dict(TAMPER, id=2, name="Fine")
    a, rep = _analyzer([first, second])
    real = an.matches_event_rule

    def boom(rule, event):
        if rule["name"] == "Broken":
            raise RuntimeError("bad rule")
        return real(rule, event)
    monkeypatch.setattr(an, "matches_event_rule", boom)
    a._analyze_event_batch([_tamper_event(6, dt.datetime.now(UTC))], None)
    assert [c.args[0]["rule"] for c in rep.add_event_alert.call_args_list] == ["Fine"]


def test_traffic_rules_with_text_numbers_work_and_unusable_ones_are_skipped():
    from src.analyzer import usable_traffic_rules
    rules = usable_traffic_rules([
        {"id": 1, "name": "ok", "type": "traffic", "threshold_window": "15", "port": "22", "pd": "2"},
        {"id": 2, "name": "named port", "type": "traffic", "port": "ssh"},
        {"id": 3, "name": "blank", "type": "traffic", "threshold_window": "", "port": ""},
    ])
    assert [r["name"] for r in rules] == ["ok", "blank"]
    assert rules[0]["port"] == 22 and rules[0]["pd"] == 2 and rules[0]["threshold_window"] == 15
    assert "port" not in rules[1] and rules[1]["threshold_window"] == 10


def test_saving_a_non_numeric_cooldown_is_refused(client):
    """The rule editor used to keep an unparsable number as typed."""
    from tests._helpers import _csrf
    env = {"REMOTE_ADDR": "127.0.0.1"}
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"},
                        environ_overrides=env)
    hdr = {"X-CSRF-Token": _csrf(login)}
    r = client.post("/api/rules/event", json={"name": "x", "filter_value": "agent.tampering",
                                             "threshold_type": "immediate", "cooldown_minutes": 5},
                    environ_overrides=env, headers=hdr)
    assert r.status_code == 200, r.get_json()
    idx = len(client.get("/api/rules", environ_overrides=env).get_json()) - 1
    r = client.put(f"/api/rules/{idx}", json={"cooldown_minutes": "abc"},
                   environ_overrides=env, headers=hdr)
    assert r.status_code == 400
    saved = client.get("/api/rules", environ_overrides=env).get_json()[idx]
    assert saved["cooldown_minutes"] == 5


# ── traffic lag ─────────────────────────────────────────────────────────────

def test_traffic_lag_shifts_the_window_instead_of_widening_it():
    """With lag 10 and window 10 the window is [now-20, now-10]; flows from the
    last two minutes were counted too, so the rule fired below its threshold."""
    rule = {"id": 7, "name": "Blocked burst", "type": "traffic", "pd": 2,
            "threshold_type": "count", "threshold_count": 2, "threshold_window": 10,
            "cooldown_minutes": 10}
    a, _ = _analyzer([rule], settings={"traffic_alert_lag_minutes": 10})
    real_now = dt.datetime.now(UTC)
    eval_now = a._evaluation_time(real_now)

    def flow(minutes_ago, h):
        t = real_now - dt.timedelta(minutes=minutes_ago)
        return {"policy_decision": "blocked", "num_connections": 1,
                "timestamp_range": {"first_detected": _iso(t), "last_detected": _iso(t)},
                "src": {"ip": f"10.0.0.{h}"}, "dst": {"ip": "10.0.1.1"},
                "service": {"port": 22, "proto": 6}}
    res = dict((r["id"], v) for r, v in a._run_rule_engine([flow(1, 1), flow(2, 2)], [rule], eval_now))
    assert res[7]["max_val"] == 0
    res = dict((r["id"], v) for r, v in a._run_rule_engine([flow(12, 1), flow(15, 2)], [rule], eval_now))
    assert res[7]["max_val"] == 2


# ── per-target cooldown ─────────────────────────────────────────────────────

def test_attempts_from_different_addresses_cool_down_separately():
    """System-created auth failures carry only a source IP; every attacker used
    to share one cooldown, so IP B was silenced by IP A's alert."""
    rule = {"id": 4, "name": "API auth failed", "type": "event",
            "filter_value": "request.authentication_failed",
            "threshold_type": "immediate", "threshold_count": 1, "cooldown_minutes": 30}
    a, rep = _analyzer([rule])
    now = dt.datetime.now(UTC)

    def ev(i, ip):
        return {"href": f"/orgs/1/events/a{i}", "event_type": "request.authentication_failed",
                "status": "failure", "severity": "err", "timestamp": _iso(now),
                "created_by": {"system": {}},
                "notifications": [{"notification_type": "request.authentication_failed",
                                   "info": {"api_endpoint": "/api/v2/noop", "api_method": "GET",
                                            "src_ip": ip}}]}
    a._analyze_event_batch([ev(1, "192.168.20.32")], None)
    a._analyze_event_batch([ev(2, "203.0.113.9")], None)
    assert rep.add_event_alert.call_count == 2
    a._analyze_event_batch([ev(3, "192.168.20.32")], None)
    assert rep.add_event_alert.call_count == 2          # same source: still cooling


# ── PCE health ──────────────────────────────────────────────────────────────

HEALTH = {"id": "h1", "name": "PCE health", "type": "system", "filter_value": "pce_health",
          "threshold_type": "immediate", "threshold_count": 3, "threshold_window": 10,
          "cooldown_minutes": 0}


def _health_analyzer(api):
    a, rep = _analyzer([HEALTH], api=api, settings={"enable_health_check": True})
    a.cm.config["api"] = {"url": "https://x.illum.io", "org_id": "1", "deployment_type": "saas"}
    return a, rep


def test_pce_health_waits_for_its_threshold_then_says_when_it_recovers():
    api = MagicMock()
    api.check_connectivity.return_value = (401, "unauthorized")    # not retried
    a, rep = _health_analyzer(api)
    for _ in range(2):
        a._run_health_check(force=True)
    rep.add_health_alert.assert_not_called()             # 2 < threshold_count 3
    a._run_health_check(force=True)
    assert rep.add_health_alert.call_count == 1
    assert rep.add_health_alert.call_args[0][0]["status"] != "recovered"

    api.check_connectivity.return_value = (200, "")
    a._run_health_check(force=True)
    assert rep.add_health_alert.call_count == 2
    notice = rep.add_health_alert.call_args[0][0]
    assert notice["status"] == "recovered" and notice["severity"] == "info"

    a._run_health_check(force=True)                      # still healthy: no repeat
    assert rep.add_health_alert.call_count == 2


def test_no_recovery_notice_for_a_run_that_never_paged():
    api = MagicMock()
    api.check_connectivity.side_effect = [(401, ""), (200, "")]
    a, rep = _health_analyzer(api)
    a._run_health_check(force=True)
    a._run_health_check(force=True)
    rep.add_health_alert.assert_not_called()
