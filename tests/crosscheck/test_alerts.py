"""Event-rule alerts against the PCE's events. The app and flow databases are made by the product's own migrations;
alert rows are written in the product's format (datetime.isoformat, as store.alerts writes them)."""
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

import illumio_ops.crosscheck.__main__ as cli
from illumio_ops.crosscheck import alerts, events
from illumio_ops.crosscheck.model import Run
from illumio_ops.domain.events import EventRecord
from illumio_ops.domain.values import DataOrigin
from illumio_ops.paths import resolve_paths
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store.db import connect, migrate
from illumio_ops.store.flowdb import binding
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.events import upsert_events
from tests.crosscheck.test_events import NOW, URL, FakePce, ev
from tests.web.conftest import cached_hash

T = NOW - timedelta(days=2)  # well inside the period, collected and evaluated


def rule(**kw):
    r = {"id": uuid4().hex, "name": "my rule", "pack_key": None, "enabled": True, "notify": True, "severity": "high",
         "cooldown_minutes": 0, "throttle": None, "type": "event", "event_types": ["user.sign_in"], "status": "all",
         "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1,
         "window_minutes": 10}
    r.update(kw)
    return r


def _run(tmp_path, pce, rules, *, enabled=True, alert_days=90):
    paths = resolve_paths(tmp_path / "root")
    paths.ensure_dirs()
    store = SettingsStore(paths.settings_file)
    store.create_initial(password_hash=cached_hash("illumio"), secret_key="ab" * 32)

    def mutate(d):
        d["pce"].update(url=URL, org_id="3", api_key="k", api_secret="s")
        d["collection"]["enabled"] = enabled
        d["alerts"]["rules"] = rules
        d["alerts"]["retention_days"] = alert_days

    s = store.update(store.current().revision, mutate)
    start, end = cli.period(NOW, 7, 30)
    return Run(paths=paths, settings=s, pce=pce, start=start, end=end, now=NOW)


def _flows(run, rows, origin=DataOrigin.INGEST):
    """Store rows with the product's writer; returns href -> id."""
    conn = FlowDb(run.paths.flows_db).connect()
    try:
        binding.bind(conn, URL, "3", NOW)
        recs = [EventRecord(r["href"], r["event_type"], r.get("severity"), r.get("status"),
                            datetime.fromisoformat(r["timestamp"]), None, None, None, None, None, "{}") for r in rows]
        upsert_events(conn, recs, origin=origin, now=NOW)
        return {h: i for h, i in conn.execute("SELECT href, id FROM events")}
    finally:
        conn.close()


def _app(run, rows=(), *, watermark="all", wm_pce=(URL, "3")):
    """rows: (rule, fired_at, first_seen, last_seen[, pce_url]). watermark "all": every stored event evaluated."""
    conn = connect(run.paths.app_db)
    try:
        migrate(conn)
        for r in rows:
            rid, fired, first, last = r[:4]
            pce_url = r[4] if len(r) > 4 else URL
            conn.execute(
                "INSERT INTO alerts (pce_url, org_id, rule_id, rule_type, rule_name, pack_key, severity, subject_key, "
                "fired_at, first_seen, last_seen, late, notify, message_key, params_json, facts_json, confidence_json) "
                "VALUES (?, '3', ?, 'event', 'r', NULL, 'high', 'subject', ?, ?, ?, 0, 1, 'k', '{}', '{}', '{}')",
                (pce_url, rid, fired.isoformat(), first.isoformat(), last.isoformat()))
        if watermark == "all":
            fconn = FlowDb(run.paths.flows_db).connect()
            watermark = str(fconn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])
            fconn.close()
        if watermark is not None:
            conn.execute("INSERT INTO alert_eval_state (source, pce_url, org_id, watermark) VALUES ('events', ?, ?, ?)",
                         (wm_pce[0], wm_pce[1], watermark))
        conn.commit()
    finally:
        conn.close()


def _setup(tmp_path, items, rules, alert_rows=(), *, stored=None, **kw):
    pce = FakePce(items)
    run = _run(tmp_path, pce, rules, **kw)
    _flows(run, items if stored is None else stored)
    _app(run, alert_rows)
    return run


def _by(findings, status=None, item=None):
    return [f for f in findings if (status is None or f.status == status) and (item is None or item in f.item)]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(events, "_sleep", lambda s: None)


# --- the matcher ------------------------------------------------------------------------------------------------

def _e(event_type="user.sign_in", status="success", severity="info"):
    return events.PceEvent("/orgs/3/events/1", event_type, T, "x", status, severity, ())


@pytest.mark.parametrize("types,status,sev,event,want", [
    (["user.sign_in"], "all", "all", _e(), True),
    (["user.login|user.sign_in"], "", "*", _e(), True),
    (["*"], "ANY", "All", _e("anything.at_all"), True),
    (["user.login"], "all", "all", _e(), False),
    (["user.sign_in"], "failure", "all", _e(), False),
    (["user.sign_in"], "failure|success", "all", _e(), True),
    (["user.sign_in"], "all", "error", _e(severity="err"), True),
    (["user.sign_in"], "all", "warning|err", _e(severity="info"), False),
    (["user.sign_in"], "success", "all", _e(status=None), False),
])
def test_matcher(types, status, sev, event, want):
    r = alerts.Rule.from_settings(rule(event_types=types, status=status, event_severity=sev))
    assert alerts.unsupported(r) is None
    assert alerts.matches(r, event) is want


@pytest.mark.parametrize("kw,why", [
    ({"event_types": ["user\\..*"]}, "regular expression"),
    ({"event_types": ["^user"]}, "regular expression"),
    ({"status": "!success"}, "negation"),
    ({"event_severity": "!info"}, "negation"),
    ({"status": "succ.+"}, "regular expression"),
    ({"match_fields": {"created_by.user.username": "x"}}, "match_fields"),
])
def test_unsupported_rules(kw, why):
    assert why in alerts.unsupported(alerts.Rule.from_settings(rule(**kw)))


# --- explanations -----------------------------------------------------------------------------------------------

def test_an_event_inside_an_alert_is_explained(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], [(r["id"], T + timedelta(minutes=2), T, T)])
    f = alerts.check(run)
    assert _by(f, "inconsistent") == []
    ok = _by(f, "consistent", "my rule")
    assert len(ok) == 1 and "in an alert 1" in ok[0].detail


def test_a_matching_event_without_an_alert_is_a_possible_miss(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T), ev(2, T + timedelta(hours=1), "user.login")], [r])
    miss = _by(alerts.check(run), "inconsistent", "possible missed alert")
    assert len(miss) == 1 and miss[0].sample[0]["href"] == "/orgs/3/events/000001"
    assert set(miss[0].sample[0]) == {"href", "event_type", "timestamp", "received"}


def test_cooldown_absorbs_only_inside_and_not_at_its_end(tmp_path):
    r = rule(cooldown_minutes=30)
    items = [ev(1, T), ev(2, T + timedelta(minutes=10)), ev(3, T + timedelta(minutes=30))]
    run = _setup(tmp_path, items, [r], [(r["id"], T, T, T)])  # fired at T itself
    f = alerts.check(run)
    miss = _by(f, "inconsistent", "possible missed alert")
    assert [s["href"] for s in miss[0].sample] == ["/orgs/3/events/000003"]  # exactly at fired_at + cooldown
    assert "cooldown 1" in miss[0].detail


def test_cooldown_of_another_rule_explains_nothing(tmp_path):
    r, other = rule(cooldown_minutes=30), rule(name="other", event_types=["user.login"], cooldown_minutes=30)
    items = [ev(1, T, "user.login"), ev(2, T + timedelta(minutes=10))]
    run = _setup(tmp_path, items, [r, other], [(other["id"], T, T, T)])
    miss = _by(alerts.check(run), "inconsistent", "my rule: possible missed alert")
    assert len(miss) == 1 and miss[0].sample[0]["href"] == "/orgs/3/events/000002"


def test_throttle_absorbs_only_when_its_count_is_reached(tmp_path):
    full = rule(name="full", throttle={"count": 1, "period_minutes": 60})
    room = rule(name="room", throttle={"count": 2, "period_minutes": 60})
    items = [ev(1, T), ev(2, T + timedelta(minutes=20))]
    run = _setup(tmp_path, items, [full, room], [(full["id"], T, T, T), (room["id"], T, T, T)])
    f = alerts.check(run)
    assert _by(f, "inconsistent", "full") == [] and "throttle 1" in _by(f, "consistent", "full")[0].detail
    assert _by(f, "inconsistent", "room: possible missed alert")


def test_an_alert_without_a_supporting_event(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], [(r["id"], T, T, T),
                                              (r["id"], T + timedelta(hours=3), T + timedelta(hours=2),
                                               T + timedelta(hours=2, minutes=5))])
    bad = _by(alerts.check(run), "inconsistent", "alert without a supporting event")
    assert len(bad) == 1 and len(bad[0].sample) == 1


def test_alerts_of_another_pce_are_not_this_pces(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], [(r["id"], T, T, T, "https://other.example.test")])
    f = alerts.check(run)
    assert _by(f, "inconsistent", "possible missed alert")
    assert _by(f, "inconsistent", "without a supporting event") == []


def test_count_rule_below_its_threshold_expects_no_alert_and_a_short_alert_is_reported(tmp_path):
    r = rule(threshold="count", threshold_count=3, window_minutes=10)
    lone = [ev(1, T)]  # one match: no alert expected
    burst = [ev(10 + i, T + timedelta(hours=1, minutes=i)) for i in range(3)]  # three in 3 minutes: alert expected
    short = [ev(20 + i, T + timedelta(hours=2, minutes=i)) for i in range(2)]  # an alert fired on only two
    b_end, s_end = T + timedelta(hours=1, minutes=2), T + timedelta(hours=2, minutes=1)
    run = _setup(tmp_path, lone + burst + short, [r],
                 [(r["id"], b_end + timedelta(minutes=1), b_end, b_end), (r["id"], s_end + timedelta(minutes=1),
                                                                         s_end - timedelta(minutes=1), s_end)])
    f = alerts.check(run)
    below = _by(f, "inconsistent", "below threshold")
    assert len(below) == 1 and below[0].sample[0]["matches"] == 2
    miss = _by(f, "inconsistent", "possible missed alert")
    # the burst's first two are below the threshold at their own time; none of them is called missed
    assert all(not s["href"].endswith(("000001", "000010", "000011", "000012")) for m in miss for s in m.sample)


def test_not_evaluated_yet_by_id_watermark(tmp_path):
    r = rule()
    items = [ev(1, T), ev(2, T + timedelta(hours=1))]
    pce = FakePce(items)
    run = _run(tmp_path, pce, [r])
    ids = _flows(run, items)
    _app(run, [(r["id"], T + timedelta(minutes=1), T, T)], watermark=str(ids["/orgs/3/events/000001"]))
    f = alerts.check(run)
    assert _by(f, "inconsistent") == []
    assert "not evaluated yet 1" in _by(f, "consistent", "my rule")[0].detail
    aside = _by(f, "unchecked", "my rule: possible missed alert")
    assert len(aside) == 1 and "set aside" in aside[0].detail and "1 not evaluated yet" in aside[0].detail
    assert pce_z(T) in aside[0].detail  # the watermark's event time, for the reader
    wm = _by(f, "unchecked", "evaluation start")
    assert wm and "period start" in wm[0].detail and pce_z(T) in wm[0].detail


def pce_z(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def test_time_watermark_from_an_upgrade(tmp_path):
    r = rule()
    items = [ev(1, T), ev(2, T + timedelta(hours=1))]
    pce = FakePce(items)
    run = _run(tmp_path, pce, [r])
    _flows(run, items)
    _app(run, [], watermark="t:" + (T + timedelta(minutes=30)).isoformat())
    f = alerts.check(run)
    assert _by(f, "inconsistent") == []
    d = _by(f, "consistent", "my rule")[0].detail
    assert "before evaluation start 1" in d and "not evaluated yet 1" in d
    aside = _by(f, "unchecked", "my rule: possible missed alert")[0].detail
    assert "1 not evaluated yet" in aside and "1 before evaluation start" in aside


def test_no_watermark_for_this_pce_means_nothing_was_evaluated(tmp_path):
    r = rule()
    pce = FakePce([ev(1, T)])
    run = _run(tmp_path, pce, [r])
    _flows(run, pce.items)
    _app(run, [], watermark="5", wm_pce=("https://other.example.test", "3"))
    f = alerts.check(run)
    assert _by(f, "inconsistent") == [] and "not evaluated yet 1" in _by(f, "consistent", "my rule")[0].detail
    assert "no evaluation watermark" in _by(f, "unchecked", "my rule: possible missed alert")[0].detail


def test_backfilled_events_are_never_evaluated(tmp_path):
    r = rule()
    pce = FakePce([ev(1, T)])
    run = _run(tmp_path, pce, [r])
    _flows(run, pce.items, origin=DataOrigin.BACKFILL)
    _app(run, [])
    f = alerts.check(run)
    assert _by(f, "inconsistent") == [] and "backfilled 1" in _by(f, "consistent", "my rule")[0].detail


def test_an_event_never_received_is_still_a_possible_miss_and_says_so(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], stored=[])
    miss = _by(alerts.check(run), "inconsistent", "possible missed alert")
    assert miss and miss[0].sample[0]["received"] is False and "not in this system's events" in miss[0].detail


def test_unsupported_rule_is_unchecked_and_never_reported(tmp_path):
    r = rule(event_types=["user\\..*"])
    run = _setup(tmp_path, [ev(1, T)], [r])
    f = alerts.check(run)
    assert _by(f, "inconsistent") == []
    u = _by(f, "unchecked", "my rule")
    assert len(u) == 1 and "regular expression" in u[0].detail


def test_built_in_rule_is_named_by_its_pack_key_and_disabled_rules_are_skipped(tmp_path):
    builtin = rule(name="", pack_key="rule_user_sign_in_failed")
    off = rule(name="switched off", enabled=False)
    run = _setup(tmp_path, [ev(1, T)], [builtin, off])
    f = alerts.check(run)
    assert _by(f, "inconsistent", "rule_user_sign_in_failed: possible missed alert")
    assert not any("switched off" in x.item for x in f)


def test_immediate_rule_needing_several_events_is_not_judged_for_misses(tmp_path):
    r = rule(threshold_count=2)
    run = _setup(tmp_path, [ev(1, T)], [r])
    f = alerts.check(run)
    assert _by(f, "inconsistent") == []
    assert _by(f, "unchecked", "my rule: possible missed alert")


def test_collection_off_leaves_misses_unchecked(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], enabled=False)
    f = alerts.check(run)
    assert _by(f, "inconsistent") == [] and _by(f, "unchecked", "my rule: possible missed alert")


def test_past_alert_retention_is_not_compared(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, NOW - timedelta(days=5))], [r], alert_days=3)
    f = alerts.check(run)
    assert _by(f, "inconsistent") == [] and "past alert retention 1" in _by(f, "consistent", "my rule")[0].detail
    assert "1 past alert retention" in _by(f, "unchecked", "my rule: possible missed alert")[0].detail


def test_a_clean_rule_has_no_unchecked_finding(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], [(r["id"], T, T, T)])
    f = alerts.check(run)
    assert _by(f, None, "my rule") == _by(f, "consistent", "my rule")


def test_count_rule_window_reaching_before_the_period_is_not_judged(tmp_path):
    r = rule(threshold="count", threshold_count=3, window_minutes=60)
    pce = FakePce([])
    run = _run(tmp_path, pce, [r])
    early = run.start + timedelta(minutes=10)  # its window reaches 50 minutes before the period
    pce.items.append(ev(1, early))
    _flows(run, pce.items)
    _app(run, [])
    f = alerts.check(run)
    assert _by(f, "inconsistent") == []
    assert "1 not judged" in _by(f, "unchecked", "my rule: possible missed alert")[0].detail
    assert "below threshold 0" in _by(f, "consistent", "my rule")[0].detail


def test_unread_pce_windows_are_said(tmp_path):
    r = rule()
    sec = T
    items = [ev(i, sec + timedelta(milliseconds=i)) for i in range(5)]
    pce = FakePce(items)
    run = _run(tmp_path, pce, [r])
    _flows(run, items)
    _app(run, [(r["id"], sec + timedelta(seconds=5), sec, sec + timedelta(milliseconds=4))])
    events.gather(run, cap=4)
    f = alerts.check(run)
    assert _by(f, "unchecked", "unread PCE windows")


def test_reuses_the_events_areas_pce_read(tmp_path):
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], [(r["id"], T, T, T)])
    events.check(run)
    calls = len(run.pce.calls)
    alerts.check(run)
    assert len(run.pce.calls) == calls


def test_reads_both_databases_read_only(tmp_path, monkeypatch):
    seen = []
    real = alerts.open_ro
    monkeypatch.setattr(alerts, "open_ro", lambda p: seen.append(p) or real(p))
    r = rule()
    run = _setup(tmp_path, [ev(1, T)], [r], [(r["id"], T, T, T)])
    alerts.check(run)
    assert set(seen) == {run.paths.app_db, run.paths.flows_db}
    assert json  # module used
