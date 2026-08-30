"""Gate tests for the 2026-07-25 analyzer review (batch A).

Each test pins an invariant, not just the single reported line:

  H1 — an alert rule with enabled=False must not reach ANY dispatch path
       (event / traffic / system-health / debug simulation), and every rule
       selection site must go through Analyzer._select_rules.
  H2 — a rule carrying a services/ex_services filter must warm the client-side
       service lookup cache before the flow loop, otherwise the include side
       rejects every flow and the exclude side silently stops excluding.
  H4 — save_state() must only overlay the keys the Analyzer owns; every other
       state.json key belongs to a concurrent writer and must survive.

  Plus the supporting Medium/Low guards: no evidence => no traffic/volume
  alert, rules with no id are skipped instead of killing the cycle,
  save_state failures are fail-loud, a stale event_overflow is cleared on the
  cache path, and the dashboard-facing pce_stats fields reach disk.
"""
import ast
import datetime
import os
from unittest.mock import MagicMock, patch

import pytest

import src.analyzer as analyzer_mod
from src.analyzer import Analyzer, rule_enabled
from src.state_store import load_state_file, update_state_file


# ─── Helpers ────────────────────────────────────────────────────────────────

def _analyzer(rules, *, subscriber_events=None, subscriber_flows=None, api=None):
    cm = MagicMock()
    # Most tests in this module exercise non-health pipelines. Keep their API
    # doubles isolated by explicitly disabling the independent health probe.
    cm.config = {"rules": rules, "settings": {"enable_health_check": False}}
    az = Analyzer(cm, api or MagicMock(), MagicMock(),
                  subscriber_events=subscriber_events,
                  subscriber_flows=subscriber_flows)
    az.save_state = MagicMock()
    return az


def _event_rule(**over):
    rule = {"id": "ev1", "name": "event rule", "type": "event",
            "threshold_type": "immediate", "threshold_count": 1,
            "threshold_window": 10, "filter_type": "any", "filter_value": "",
            "cooldown_minutes": 0}
    rule.update(over)
    return rule


def _traffic_rule(**over):
    rule = {"id": "tr1", "name": "traffic rule", "type": "traffic",
            "threshold_count": 1, "threshold_window": 10, "pd": -1,
            "cooldown_minutes": 0}
    rule.update(over)
    return rule


def _raw_event():
    return {"timestamp": "2026-01-01T00:00:00Z", "event_type": "user.login",
            "severity": "warning", "status": "success", "created_by": {}}


def _cache_sub(rows):
    """Subscriber double honouring the at-least-once `processor` hook."""
    sub = MagicMock()

    def _poll(limit=1000, processor=None):
        batch = list(rows)
        if processor is not None:
            processor(batch)
        return batch

    sub.poll_new_rows.side_effect = _poll
    return sub


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    sf = str(tmp_path / "state.json")
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", sf)
    return sf


# ─── H1: the enable/disable flag must actually disable ──────────────────────

def test_rule_enabled_defaults_to_true_and_only_false_disables():
    assert rule_enabled({}) is True
    assert rule_enabled({"enabled": True}) is True
    assert rule_enabled({"enabled": False}) is False


def test_disabled_event_rule_never_alerts():
    az = _analyzer([_event_rule(enabled=False)])
    with patch("src.analyzer.matches_event_rule", return_value=True):
        az._analyze_event_batch([_raw_event()], None)
    az.reporter.add_event_alert.assert_not_called()


def test_enabled_event_rule_still_alerts():
    """Guard against over-filtering: the flag must not disable everything."""
    az = _analyzer([_event_rule()])
    with patch("src.analyzer.matches_event_rule", return_value=True):
        az._analyze_event_batch([_raw_event()], None)
    az.reporter.add_event_alert.assert_called_once()


def test_disabled_traffic_rule_is_not_selected_or_dispatched():
    az = _analyzer([_traffic_rule(enabled=False)])
    stream, tr_rules, _now = az._fetch_traffic()
    assert tr_rules == []
    assert stream is None
    az.reporter.add_traffic_alert.assert_not_called()


def test_disabled_system_health_rule_still_probes_but_does_not_alert():
    az = _analyzer([{"id": "sys1", "name": "health", "type": "system",
                     "filter_value": "pce_health", "enabled": False}])
    az.cm.config["settings"]["enable_health_check"] = True
    az.api.check_connectivity.return_value = (200, "")
    az.api.check_health.return_value = (200, '{"status": "normal"}')
    az.api.check_node_available.return_value = (200, "")

    az._run_health_check()

    az.api.check_health.assert_called_once()
    assert az.state["pce_stats"]["health_status"] == "ok"
    az.reporter.add_health_alert.assert_not_called()


def test_disabled_rule_excluded_from_debug_simulation(capsys):
    az = _analyzer([_traffic_rule(name="off rule", enabled=False),
                    _traffic_rule(id="tr2", name="on rule")])
    az.api.fetch_events.return_value = []
    az.api.execute_traffic_query_stream.return_value = iter([])
    az.run_debug_mode(mins=10, pd_sel=3, interactive=False)
    out = capsys.readouterr().out
    assert "on rule" in out
    assert "off rule" not in out


def test_every_rule_selection_site_goes_through_select_rules():
    """Class-level invariant: reading cm.config['rules'] anywhere other than
    _select_rules (plus the two retention/pruning helpers that deliberately
    consider disabled rules too) reintroduces the bug in a new dispatch path.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "src", "analyzer.py")
    tree = ast.parse(open(src, encoding="utf-8").read())

    def _reads_rules(node):
        for sub in ast.walk(node):
            # cm.config["rules"] / cm.config.get("rules", ...)
            if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) \
                    and sub.slice.value == "rules":
                return True
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and sub.func.attr == "get" and sub.args \
                    and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == "rules":
                return True
        return False

    offenders = sorted(
        fn.name for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef) and _reads_rules(fn)
    )
    assert offenders == ["_select_rules", "run_debug_mode", "save_state"], offenders


# ─── L1: a rule with no id must not take down the cycle ─────────────────────

def test_rule_without_id_is_skipped_not_fatal():
    az = _analyzer([{"type": "traffic", "name": "no id", "threshold_count": 1},
                    _traffic_rule()])
    _stream, tr_rules, _now = az._fetch_traffic()
    assert [r["id"] for r in tr_rules] == ["tr1"]


def test_run_analysis_survives_rule_without_id():
    az = _analyzer([{"type": "traffic", "name": "no id", "threshold_count": 1}])
    az.run_analysis()  # must not raise KeyError('id')


# ─── H2: services/ex_services filters need a warm lookup cache ──────────────

def _service_rule():
    return _traffic_rule(id="svc1", name="svc rule",
                         services=["/orgs/1/sec_policy/active/services/17"])


def test_service_filter_rule_warms_the_lookup_cache():
    api = MagicMock()
    az = _analyzer([_service_rule()], api=api)
    az._fetch_traffic()
    api._ensure_query_lookup_cache.assert_called_once()


def test_rule_without_service_filter_does_not_warm_cache():
    api = MagicMock()
    az = _analyzer([_traffic_rule()], api=api)
    az._fetch_traffic()
    api._ensure_query_lookup_cache.assert_not_called()


def test_service_filter_matches_once_the_cache_is_warmed():
    """End-to-end over the real matcher: a cold cache rejects every flow
    (include side), a warmed one matches — so the warm-up is what makes a
    services rule able to fire at all."""
    href = "/orgs/1/sec_policy/active/services/17"
    cache = {}
    api = MagicMock()
    api._labels.resolve_service_entries.side_effect = lambda h: cache.get(str(h))
    api._ensure_query_lookup_cache.side_effect = lambda: cache.update(
        {href: [{"port": 443, "proto": 6}]})

    rule = _service_rule()
    flow = {"timestamp": "2026-01-01T00:00:00Z", "pd": 0, "num_connections": 1,
            "service": {"port": 443, "proto": 6}}
    az = _analyzer([rule], api=api)
    now = datetime.datetime(2026, 1, 1, 0, 5, tzinfo=datetime.timezone.utc)

    assert az._match_flow_filters(rule, flow, None) is False  # cold cache
    az._warm_service_lookup_cache([rule])
    assert az._match_flow_filters(rule, flow, None) is True


def test_unresolvable_service_href_is_logged(caplog):
    api = MagicMock()
    api._labels.resolve_service_entries.return_value = None
    az = _analyzer([_service_rule()], api=api)
    with caplog.at_level("WARNING"):
        az._warm_service_lookup_cache([_service_rule()])
    assert any("could not be resolved" in r.message for r in caplog.records)


# ─── M1/L2: no evidence => no traffic/volume alert ──────────────────────────

@pytest.mark.parametrize("rtype", ["traffic", "volume"])
def test_zero_threshold_with_no_matches_sends_no_alert(rtype):
    az = _analyzer([_traffic_rule(type=rtype, threshold_count=0)])
    rule = az.cm.config["rules"][0]
    az._dispatch_alerts([(rule, {"max_val": 0.0, "top_matches": []})], [rule])
    az.reporter.add_traffic_alert.assert_not_called()
    az.reporter.add_metric_alert.assert_not_called()


def test_threshold_met_with_evidence_still_alerts():
    az = _analyzer([_traffic_rule(threshold_count=1)])
    rule = az.cm.config["rules"][0]
    az._dispatch_alerts([(rule, {"max_val": 5.0, "top_matches": [{"_metric_val": 5}]})], [rule])
    az.reporter.add_traffic_alert.assert_called_once()


# ─── H4: save_state must not clobber other writers' keys ────────────────────

_FOREIGN_KEYS = {
    "report_schedule_states": {"3": {"last_run": "2026-07-25T09:00:00Z"}},
    "rule_schedule_states": {"7": {"last_run": "2026-07-25T09:00:00Z"}},
    "adhoc_report_jobs": {"job-1": {"status": "running"}},
    "async_query_jobs": {"/href/1": {"status": "queued"}},
    "dispatch_history": [{"channel": "email", "status": "ok"}],
    "ven_summary": {"total": 10},
    "posture_summary": {"total": 3},
    "traffic_overflow": {"raw_count": 1},
    "alert_dlq": [{"id": "x"}],
    "a_future_key_nobody_has_written_yet": {"keep": "me"},
}


def test_save_state_preserves_every_foreign_key_written_mid_cycle(state_file):
    """A concurrent writer (report scheduler / GUI job / Reporter) updates
    state.json between this Analyzer's load_state() and its save_state().
    None of those writes may be reverted to the analyzer's load-time snapshot.
    """
    az = _analyzer([])
    az.save_state = Analyzer.save_state.__get__(az)

    update_state_file(state_file, lambda s: {**s, **_FOREIGN_KEYS})
    az.save_state()

    on_disk = load_state_file(state_file)
    for key, value in _FOREIGN_KEYS.items():
        assert on_disk.get(key) == value, key


def test_save_state_still_persists_analyzer_owned_keys(state_file):
    az = _analyzer([])
    az.save_state = Analyzer.save_state.__get__(az)
    az.state["alert_history"] = {}
    az.state["event_watermark"] = "2026-07-25T10:00:00Z"

    az.save_state()

    on_disk = load_state_file(state_file)
    assert on_disk["event_watermark"] == "2026-07-25T10:00:00Z"
    assert "history" in on_disk and "throttle_state" in on_disk


def test_save_state_appends_new_timeline_entries_without_dropping_foreign_ones(state_file):
    az = _analyzer([])
    az.save_state = Analyzer.save_state.__get__(az)
    az.stats.record_timeline("pce_error", "events failed", error="cache db locked")

    # Reporter writes its dispatch row mid-cycle
    update_state_file(state_file, lambda s: {
        **s, "event_timeline": [{"kind": "dispatch", "title": "dispatch email ok"}]})
    az.save_state()

    titles = [e.get("title") for e in load_state_file(state_file)["event_timeline"]]
    assert "dispatch email ok" in titles
    assert "events failed" in titles


def test_save_state_failure_is_fail_loud(state_file):
    """The cooldown timestamps written this cycle live only in this file; a
    swallowed write error means the alerts go out while the suppression state
    does not, re-alerting every cycle. The caller must see the failure."""
    az = _analyzer([])
    az.save_state = Analyzer.save_state.__get__(az)
    with patch("src.analyzer.update_state_file", side_effect=OSError("ENOSPC")):
        with pytest.raises(OSError):
            az.save_state()


def test_stale_alert_history_for_deleted_rules_is_pruned(state_file):
    az = _analyzer([_traffic_rule()])
    az.save_state = Analyzer.save_state.__get__(az)
    az.state["alert_history"] = {"tr1": "2026-07-25T10:00:00Z",
                                 "deleted-rule": "2026-07-25T10:00:00Z"}
    az.save_state()
    assert set(load_state_file(state_file)["alert_history"]) == {"tr1"}


def test_alert_history_is_kept_when_the_rule_list_is_unreadable(state_file):
    """Fail-safe: an empty/broken rules list must not wipe every cooldown
    timestamp (that would turn a config problem into an alert storm)."""
    az = _analyzer([])
    az.save_state = Analyzer.save_state.__get__(az)
    az.state["alert_history"] = {"tr1": "2026-07-25T10:00:00Z"}
    az.save_state()
    assert set(load_state_file(state_file)["alert_history"]) == {"tr1"}


# ─── M5/M6: cache-path event bookkeeping ────────────────────────────────────

def test_cache_path_clears_stale_event_overflow():
    az = _analyzer([], subscriber_events=_cache_sub([]))
    az.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000}
    az._run_event_analysis()
    assert az.state["event_overflow"] == {}


def test_failed_cache_poll_reaches_disk(state_file):
    """A cache event-poll failure must survive save_state's pce_stats merge,
    otherwise the dashboard Event Poll card stays green while event analysis
    is dead."""
    sub = MagicMock()
    sub.poll_new_rows.side_effect = Exception("cache db locked")
    az = _analyzer([], subscriber_events=sub)
    az.save_state = Analyzer.save_state.__get__(az)

    # disk owned by the ingest job: healthy, with its own watchdog counter
    update_state_file(state_file, lambda s: {
        **s, "pce_stats": {"event_poll_status": "ok", "consecutive_failures": 4}})

    az._run_event_analysis()
    az.save_state()

    on_disk = load_state_file(state_file)["pce_stats"]
    assert on_disk["event_poll_status"] == "error"
    assert "cache db locked" in on_disk["last_error"]
    # ingest-owned field untouched
    assert on_disk["consecutive_failures"] == 4


# ─── M2: event batch is acknowledged only after it is analysed ──────────────

def test_event_batch_uses_the_at_least_once_processor_hook():
    sub = MagicMock()
    sub.poll_new_rows.side_effect = lambda limit=1000, processor=None: (
        processor([_raw_event()]) or [_raw_event()])
    az = _analyzer([_event_rule()], subscriber_events=sub)
    with patch("src.analyzer.matches_event_rule", return_value=True):
        az._run_event_analysis()
    assert sub.poll_new_rows.call_args.kwargs.get("processor") is not None
    az.reporter.add_event_alert.assert_called_once()


# ─── M7: window truncation must raise a signal, not just a log line ─────────

def test_window_truncation_records_a_signal():
    sub = MagicMock()
    sub.fetch_window_rows.return_value = [{"num_connections": 1}] * analyzer_mod.TRAFFIC_WINDOW_ROW_LIMIT
    az = _analyzer([_traffic_rule()], subscriber_flows=sub)
    az._fetch_traffic()
    assert az.state["window_truncation"]["raw_count"] == analyzer_mod.TRAFFIC_WINDOW_ROW_LIMIT


def test_window_truncation_signal_clears_when_not_truncated():
    sub = MagicMock()
    sub.fetch_window_rows.return_value = [{"num_connections": 1}]
    az = _analyzer([_traffic_rule()], subscriber_flows=sub)
    az.state["window_truncation"] = {"raw_count": 10000}
    az._fetch_traffic()
    assert az.state["window_truncation"] == {}


# ─── L5: a resolved overflow must not suppress the next episode ─────────────

def test_overflow_cooldown_is_cleared_when_the_overflow_resolves():
    az = _analyzer([])
    az.state["traffic_overflow"] = {}
    az.state["traffic_overflow_last_alert_at"] = "2026-07-25T10:00:00Z"
    az._maybe_alert_overflow()
    assert not az.state["traffic_overflow_last_alert_at"]


# ─── M8: history is only written for the rules that read it back ────────────

def test_history_is_recorded_only_for_count_rules():
    az = _analyzer([_event_rule(id="imm", threshold_type="immediate"),
                    _event_rule(id="cnt", threshold_type="count", threshold_count=99)])
    with patch("src.analyzer.matches_event_rule", return_value=True):
        az._analyze_event_batch([_raw_event()], None)
    assert "imm" not in az.state["history"]
    assert len(az.state["history"]["cnt"]) == 1
