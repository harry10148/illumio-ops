"""Gate tests for the aggregation-basis guard (bucket-basis guard, phase 1).

Established against a live PCE on 2026-07-25: querying the same flows with
5 / 30 / 120 minute windows returns IDENTICAL dst_bo / dst_bi /
num_connections, and ``timestamp_range.first_detected`` always sits at the
day boundary. The PCE aggregates into day-sized buckets and returns the whole
bucket's totals — the values are NOT clipped to the requested window.

Consequence: a rule whose ``threshold_window`` is shorter than a matched
flow's aggregation span would compare bucket-wide traffic against a
short-window threshold, so it over-counts (and the over-count grows through
the day, resetting at midnight).

The invariants pinned here:

  1. A short-window rule matched by bucket-spanning flows must NOT alert.
  2. It must WARN, naming the rule and quantifying window vs observed span,
     at most once per rule per cycle (the per-flow loop is hot).
  3. It must surface through the meta-alert channel, so "no alert" can never
     be mistaken for "no traffic".
  4. A long-window rule (window >= span) is unaffected and still alerts.
  5. An EDC-style ``(Interval)`` flow (dst_db* deltas) is unaffected — those
     values ARE interval-scoped.
  6. A flow with no parsable first_detected is unaffected — missing evidence
     is never treated as evidence of a violation.
  7. The guard is per rule, not global: one guarded rule must not suppress a
     different, healthy rule in the same cycle.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest
from loguru import logger as _logger

import src.analyzer as analyzer_mod
from src.analyzer import Analyzer, flow_aggregation_start


NOW = datetime.datetime(2026, 7, 25, 8, 27, 0, tzinfo=datetime.timezone.utc)
MIDNIGHT = "2026-07-25T00:00:00Z"          # bucket 起點：規則視窗外 507 分鐘
RECENT_FIRST = "2026-07-25T08:25:00Z"      # 落在 10 分鐘視窗內


def _analyzer(rules, *, subscriber_flows=None):
    cm = MagicMock()
    cm.config = {"rules": rules}
    az = Analyzer(cm, MagicMock(), MagicMock(), subscriber_flows=subscriber_flows)
    az.save_state = MagicMock()
    az.load_state = MagicMock()
    return az


def _rule(rid="tr1", rtype="traffic", *, window=10, threshold=1, name=None):
    return {
        "id": rid,
        "name": name or f"rule {rid}",
        "type": rtype,
        "threshold_type": "count",
        "threshold_count": threshold,
        "threshold_window": window,
        "pd": -1,
        "cooldown_minutes": 0,
    }


def _bucket_flow(first_detected=MIDNIGHT, **over):
    """真機形狀：dst_bi/dst_bo（非 dst_tb*/dst_db*），故 calculate_volume_mb
    落到第三個 fallback 標成 (Total)；last_detected 在視窗內，first_detected
    在午夜。"""
    flow = {
        "timestamp_range": {
            "first_detected": first_detected,
            "last_detected": "2026-07-25T08:26:30Z",
        },
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": 6124,
        "dst_bo": 3710468,
        "dst_bi": 4504322,
        "src": {},
        "dst": {},
        "service": {},
    }
    flow.update(over)
    return flow


def _interval_flow(first_detected=MIDNIGHT, **over):
    """EDC 形狀：帶 dst_db*/ddms 增量欄位，calculate_volume_mb 走 (Interval)
    分支——這種值本來就是區間增量，守門不得誤殺。"""
    flow = {
        "timestamp_range": {
            "first_detected": first_detected,
            "last_detected": "2026-07-25T08:26:30Z",
        },
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": 12,
        "dst_dbo": 4 * 1024 * 1024,
        "dst_dbi": 0,
        "ddms": 60_000,
        "src": {},
        "dst": {},
        "service": {},
    }
    flow.update(over)
    return flow


@pytest.fixture
def warnings():
    msgs: list[str] = []
    sink = _logger.add(lambda m: msgs.append(str(m)), level="WARNING")
    yield msgs
    _logger.remove(sink)


# ─── flow_aggregation_start ─────────────────────────────────────────────────

def test_aggregation_start_reads_nested_and_top_level():
    nested = _bucket_flow()
    assert flow_aggregation_start(nested) == datetime.datetime(
        2026, 7, 25, 0, 0, tzinfo=datetime.timezone.utc)
    flat = {"first_detected": MIDNIGHT}
    assert flow_aggregation_start(flat) == flow_aggregation_start(nested)


def test_aggregation_start_is_none_when_absent_or_unparsable():
    assert flow_aggregation_start({}) is None
    assert flow_aggregation_start({"timestamp_range": {}}) is None
    assert flow_aggregation_start({"timestamp_range": "not-a-dict"}) is None
    assert flow_aggregation_start({"first_detected": "yesterday"}) is None


# ─── 1 + 2: short window must not fire, and must warn ───────────────────────

@pytest.mark.parametrize("rtype", ["traffic", "bandwidth", "volume"])
def test_short_window_rule_is_suppressed_and_warns(rtype, warnings):
    rule = _rule("tr1", rtype, window=10, threshold=1, name=f"{rtype} short")
    az = _analyzer([rule])

    triggers = az._run_rule_engine(iter([_bucket_flow(), _bucket_flow()]), [rule], NOW)
    _, res = triggers[0]

    assert res.get("basis_mismatch"), "guard must flag the rule"
    assert res["basis_mismatch"]["flows"] == 2
    assert res["basis_mismatch"]["window_minutes"] == 10
    assert res["basis_mismatch"]["span_minutes"] == pytest.approx(507.0, abs=1.0)

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_traffic_alert.assert_not_called()
    az.reporter.add_metric_alert.assert_not_called()

    hits = [m for m in warnings if "aggregation-basis guard" in m]
    assert len(hits) == 1, f"expected exactly one warning per rule per cycle, got {len(hits)}"
    assert f"{rtype} short" in hits[0]
    assert "10 min" in hits[0]      # rule window
    assert "507 min" in hits[0]     # observed span


def test_suppression_is_recorded_for_the_operator_facing_stats():
    rule = _rule("tr1", "traffic", window=10)
    az = _analyzer([rule])
    az.stats = MagicMock()

    triggers = az._run_rule_engine(iter([_bucket_flow()]), [rule], NOW)
    az._dispatch_alerts(triggers, [rule])

    az.stats.record_suppression.assert_called_once()
    args, kwargs = az.stats.record_suppression.call_args
    assert args[1] == "aggregation_basis"
    assert kwargs["window_minutes"] == 10
    assert kwargs["span_minutes"] == pytest.approx(507.0, abs=1.0)
    az.stats.record_rule_trigger.assert_not_called()


# ─── 3: it must reach the operator, not only the log ────────────────────────

def test_guard_raises_a_meta_alert_through_the_health_channel():
    rule = _rule("tr1", "traffic", window=10, name="db blocked")
    az = _analyzer([rule])

    az._run_rule_engine(iter([_bucket_flow()]), [rule], NOW)
    assert az.state["basis_mismatch"]["rule_names"] == "db blocked"
    assert az.state["basis_mismatch"]["worst_window_minutes"] == 10

    az._maybe_alert_overflow()
    calls = [c.args[0] for c in az.reporter.add_health_alert.call_args_list]
    assert len(calls) == 1
    assert calls[0]["status"] == "warning"


def test_meta_alert_signal_clears_on_a_clean_cycle():
    sub = MagicMock()
    sub.fetch_window_rows.return_value = [_bucket_flow()]
    az = _analyzer([_rule()], subscriber_flows=sub)
    az.state["basis_mismatch"] = {"rule_names": "stale"}
    az._fetch_traffic()
    assert az.state["basis_mismatch"] == {}


def test_existing_overflow_meta_alerts_still_render_their_placeholders():
    """回歸鎖：details kwargs 改成「四個共用欄位 + state 純量」後，舊訊號的
    模板必須逐位不變（不可再出現未替換的 {raw}/{cap}/{since}/{until}）。"""
    az = _analyzer([])
    az.state["event_overflow"] = {
        "raw_count": 5000, "max_results": 5000,
        "query_since": "2026-07-25T00:00:00Z", "query_until": "2026-07-25T00:10:00Z",
    }
    az._maybe_alert_overflow()
    details = az.reporter.add_health_alert.call_args_list[0].args[0]["details"]
    for token in ("{raw}", "{cap}", "{since}", "{until}"):
        assert token not in details
    assert "5000" in details


# ─── 4: a long window is unaffected ─────────────────────────────────────────

def test_long_window_rule_still_alerts_normally():
    rule = _rule("tr1", "traffic", window=1440, threshold=1, name="daily")
    az = _analyzer([rule])

    triggers = az._run_rule_engine(iter([_bucket_flow()]), [rule], NOW)
    _, res = triggers[0]
    assert "basis_mismatch" not in res
    assert res["max_val"] == 6124

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_traffic_alert.assert_called_once()


# ─── 5: EDC interval-scoped flows are unaffected ────────────────────────────

@pytest.mark.parametrize("rtype", ["volume", "bandwidth"])
def test_edc_interval_flow_is_not_guarded(rtype):
    """dst_db*/ddms 走 (Interval) 分支＝值本身就是區間增量，即使 flow 的
    first_detected 早於視窗也不得被守門擋下。"""
    rule = _rule("tr1", rtype, window=10, threshold=0)
    az = _analyzer([rule])

    triggers = az._run_rule_engine(iter([_interval_flow()]), [rule], NOW)
    _, res = triggers[0]
    assert "basis_mismatch" not in res
    assert res["max_val"] > 0

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_metric_alert.assert_called_once()


def test_edc_interval_flow_still_guards_the_connection_count_rule():
    """同一筆 EDC flow 對 traffic(count) 型仍受守門——PCE 沒有「增量連線數」
    欄位，num_connections 依然是整個 bucket 的累計值。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule])
    triggers = az._run_rule_engine(iter([_interval_flow()]), [rule], NOW)
    _, res = triggers[0]
    assert res.get("basis_mismatch")


# ─── bandwidth-basis Task 1 fix round 1: unavailable bw_val must not crash ──
#
# calculate_mbps() can now return val=None (no byte fields, or no usable
# duration/timestamps — bandwidth-basis Task 1). The per-flow bandwidth
# comparison in _run_rule_engine used to assume calculate_mbps always
# returned a float; a None flowing into `m_bw > res['max_val']` raises
# TypeError and aborts the whole monitor cycle.

def _unavailable_bw_flow(first_detected=RECENT_FIRST, **over):
    """No byte telemetry at all: calculate_mbps returns val=None. Recent
    first_detected keeps the bucket-basis guard from swallowing it first --
    this flow must reach the bandwidth comparison itself, not get filtered
    out upstream by an unrelated mechanism."""
    flow = {
        "timestamp_range": {
            "first_detected": first_detected,
            "last_detected": "2026-07-25T08:26:30Z",
        },
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": 12,
        "src": {},
        "dst": {},
        "service": {},
    }
    flow.update(over)
    return flow


def test_run_rule_engine_bandwidth_tolerates_unavailable_flows():
    """A mixed stream (one measured flow, one with no byte fields) must not
    raise. The unavailable flow carries no evidence, so it must never become
    the rule's max_val or enter top_matches -- same "no evidence is not
    evidence" doctrine this guard already applies to missing timestamps --
    while the real measured flow still triggers normally."""
    rule = _rule("tr1", "bandwidth", window=10, threshold=0)
    az = _analyzer([rule])

    triggers = az._run_rule_engine(
        iter([_interval_flow(first_detected=RECENT_FIRST), _unavailable_bw_flow()]),
        [rule], NOW)
    _, res = triggers[0]

    assert res["max_val"] > 0
    assert all(m['_metric_val'] is not None for m in res["top_matches"])


# ─── bandwidth-basis Task 2: the three-way branch on the alert engine ──────
#
# calculate_mbps() (Task 1) can now return a POINT value ((Interval)/(Avg)),
# a provable LOWER BOUND (BOUND_BASIS_NOTE "(>=)", true rate is strictly
# greater), or None (unavailable). Spec:
#   - point value            -> compare against threshold as before (>)
#   - lower bound >= threshold -> certain trigger (true value is higher)
#   - lower bound <  threshold -> cannot be determined -> guard + count
#   - None (unavailable)       -> guard + count, never treated as 0

def _bound_flow(first_detected, last_detected, dst_bo, dst_bi=0, **over):
    """No ddms/tdms -- calculate_mbps falls through to the span-based lower
    bound (BOUND_BASIS_NOTE). Numbers are chosen so span_seconds+1 divides
    total_bytes*8 evenly, giving an exact Mbps value for boundary tests."""
    flow = {
        "timestamp_range": {
            "first_detected": first_detected,
            "last_detected": last_detected,
        },
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": 1,
        "dst_bo": dst_bo,
        "dst_bi": dst_bi,
        "src": {},
        "dst": {},
        "service": {},
    }
    flow.update(over)
    return flow


# first/last 9 秒間距（denom = span+1 = 10s）；dst_bo 選成 125,000,000 bytes
# 使 val = 125,000,000 * 8 / 10 / 1e6 = 100.0 Mbps 整數，可精確對齊門檻。
_BOUND_FIRST = "2026-07-25T08:26:50Z"
_BOUND_LAST = "2026-07-25T08:26:59Z"
_BOUND_VAL_MBPS = 100.0


def test_lower_bound_equal_to_threshold_triggers():
    """真值嚴格大於下界，所以下界 >= 門檻即可確定觸發——若把比較寫成
    `>`，這個案例會被錯誤地判定成未達標（漏報）。"""
    rule = _rule("tr1", "bandwidth", window=10, threshold=_BOUND_VAL_MBPS, name="bw bound eq")
    az = _analyzer([rule])

    triggers = az._run_rule_engine(
        iter([_bound_flow(_BOUND_FIRST, _BOUND_LAST, 125_000_000)]), [rule], NOW)
    _, res = triggers[0]

    assert "basis_mismatch" not in res
    assert res["max_val"] == pytest.approx(_BOUND_VAL_MBPS)
    assert len(res["top_matches"]) == 1

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_metric_alert.assert_called_once()


def test_lower_bound_below_threshold_is_guarded_not_a_silent_miss():
    """下界小於門檻時真值仍可能超過門檻（下界只是下限）——不可當成
    「評估後未達標」而悄悄放行，必須進守門並計數。"""
    rule = _rule("tr1", "bandwidth", window=10, threshold=_BOUND_VAL_MBPS + 1, name="bw bound lt")
    az = _analyzer([rule])
    az.stats = MagicMock()

    triggers = az._run_rule_engine(
        iter([_bound_flow(_BOUND_FIRST, _BOUND_LAST, 125_000_000)]), [rule], NOW)
    _, res = triggers[0]

    assert res.get("basis_mismatch"), "an inconclusive lower bound must guard the rule"
    assert "bound_below_threshold" in res["basis_mismatch"]["reasons"]

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_metric_alert.assert_not_called()
    az.stats.record_suppression.assert_called_once()
    az.stats.record_rule_trigger.assert_not_called()


def test_unavailable_bandwidth_is_guarded_never_treated_as_zero():
    """val is None（無 bytes 或時間戳不可解析）不得當成 0 評估——0 輸給任何
    正數門檻，會讓規則悄悄失去保護卻仍回報「已評估、未觸發」。必須進守門
    並計數，讓操作者看得到。"""
    rule = _rule("tr1", "bandwidth", window=10, threshold=1, name="bw none")
    az = _analyzer([rule])
    az.stats = MagicMock()

    triggers = az._run_rule_engine(iter([_unavailable_bw_flow()]), [rule], NOW)
    _, res = triggers[0]

    assert res.get("basis_mismatch"), "an unavailable value must guard the rule"
    assert "no_measurement" in res["basis_mismatch"]["reasons"]
    assert res["max_val"] == 0.0
    assert res["top_matches"] == []

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_metric_alert.assert_not_called()
    az.stats.record_suppression.assert_called_once()
    az.stats.record_rule_trigger.assert_not_called()


def test_point_value_exactly_at_threshold_still_uses_strict_greater_than():
    """回歸鎖：下界的 `>=` 規則不可外溢到點值分支——點值等於門檻沿用既有
    嚴格 `>` 語意，不觸發。"""
    rule = _rule("tr1", "bandwidth", window=10, threshold=100, name="bw point eq")
    az = _analyzer([rule])
    # dst_dbo=12,500,000 bytes, ddms=1000ms -> 12,500,000*8/1/1e6 = 100.0 Mbps
    flow = _interval_flow(first_detected=RECENT_FIRST,
                           dst_dbo=12_500_000, dst_dbi=0, ddms=1000)

    triggers = az._run_rule_engine(iter([flow]), [rule], NOW)
    _, res = triggers[0]

    assert "basis_mismatch" not in res
    assert res["max_val"] == pytest.approx(100.0)
    assert res["top_matches"] == []

    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_metric_alert.assert_not_called()


# ─── bandwidth-basis Task 2: run_debug_mode must not diverge from the engine

class _DebugApi:
    """run_debug_mode 只需要這兩個方法（不會派送任何東西）。"""

    def __init__(self, flows):
        self._flows = flows

    def fetch_events(self, since):
        return []

    def execute_traffic_query_stream(self, start, end, pds):
        return iter(self._flows)


def _debug_analyzer(rules, flows):
    cm = MagicMock()
    cm.config = {"rules": rules}
    az = Analyzer(cm, _DebugApi(flows), MagicMock())
    az.save_state = MagicMock()
    az.load_state = MagicMock()
    return az


def _now_relative_bound_flow(span_seconds, dst_bo, dst_bi=0):
    """debug 模式用真實時鐘，flow 時戳必須跟著真實時間走。span_seconds 秒的
    first/last 間距 -> denom = span_seconds + 1。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    last = now - datetime.timedelta(seconds=2)
    first = last - datetime.timedelta(seconds=span_seconds)
    return {
        "timestamp_range": {
            "first_detected": first.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_detected": last.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": 1,
        "dst_bo": dst_bo,
        "dst_bi": dst_bi,
        "src": {},
        "dst": {},
        "service": {},
    }


def test_debug_mode_lower_bound_equal_to_threshold_would_trigger(capsys):
    rule = _rule("tr1", "bandwidth", window=10, threshold=100, name="bw bound eq")
    flow = _now_relative_bound_flow(9, 125_000_000)  # span=9 -> denom=10 -> 100.0 Mbps
    az = _debug_analyzer([rule], [flow])

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "WOULD TRIGGER" in out.upper()
    assert "Aggregation-basis guard" not in out


def test_debug_mode_lower_bound_below_threshold_is_guarded_not_a_silent_pass(capsys):
    rule = _rule("tr1", "bandwidth", window=10, threshold=101, name="bw bound lt")
    flow = _now_relative_bound_flow(9, 125_000_000)  # bound = 100.0 < 101
    az = _debug_analyzer([rule], [flow])

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "WOULD TRIGGER" not in out.upper()
    assert "bound_below_threshold=1" in out


def test_debug_mode_unavailable_bandwidth_is_guarded_not_treated_as_zero(capsys):
    rule = _rule("tr1", "bandwidth", window=10, threshold=1, name="bw none")
    now = datetime.datetime.now(datetime.timezone.utc)
    flow = {
        "timestamp_range": {
            "first_detected": (now - datetime.timedelta(seconds=11)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_detected": (now - datetime.timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": 1,
        "src": {},
        "dst": {},
        "service": {},
    }
    az = _debug_analyzer([rule], [flow])

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "WOULD TRIGGER" not in out.upper()
    assert "no_measurement=1" in out


# ─── 6: no evidence is not evidence ─────────────────────────────────────────

def test_flow_without_first_detected_is_not_guarded():
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule])
    flow = _bucket_flow()
    flow["timestamp_range"] = {"last_detected": "2026-07-25T08:26:30Z"}
    flow["timestamp"] = "2026-07-25T08:26:30Z"

    triggers = az._run_rule_engine(iter([flow]), [rule], NOW)
    _, res = triggers[0]
    assert "basis_mismatch" not in res
    assert res["max_val"] == 6124


def test_flow_whose_span_fits_the_window_is_not_guarded():
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule])
    triggers = az._run_rule_engine(
        iter([_bucket_flow(first_detected=RECENT_FIRST)]), [rule], NOW)
    _, res = triggers[0]
    assert "basis_mismatch" not in res
    assert res["max_val"] == 6124


# ─── 7: the guard is per rule, not global ───────────────────────────────────

def test_guard_is_per_rule(warnings):
    short = _rule("short", "traffic", window=10, threshold=1, name="short win")
    long_ = _rule("long", "traffic", window=1440, threshold=1, name="long win")
    az = _analyzer([short, long_])

    triggers = az._run_rule_engine(iter([_bucket_flow()]), [short, long_], NOW)
    by_id = {rule["id"]: res for rule, res in triggers}
    assert by_id["short"].get("basis_mismatch")
    assert "basis_mismatch" not in by_id["long"]

    az._dispatch_alerts(triggers, [short, long_])
    dispatched = [c.args[0]["rule"] for c in az.reporter.add_traffic_alert.call_args_list]
    assert dispatched == ["long win"]

    hits = [m for m in warnings if "aggregation-basis guard" in m]
    assert len(hits) == 1
    assert "short win" in hits[0]


def test_many_flows_still_warn_only_once_per_rule(warnings):
    """per-flow 迴圈是熱路徑：200 筆命中的 flow 只能產生 1 行 WARNING。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule])
    az._run_rule_engine(iter([_bucket_flow() for _ in range(200)]), [rule], NOW)
    hits = [m for m in warnings if "aggregation-basis guard" in m]
    assert len(hits) == 1
    assert "200 matched" in hits[0]


def test_state_key_is_owned_by_the_analyzer_so_it_reaches_disk():
    """訊號寫進 state 後必須真的落盤——不在白名單裡就會被 save_state 丟掉，
    meta-alert 的冷卻與自癒都會失效。"""
    assert "basis_mismatch" in analyzer_mod._ANALYZER_OWNED_STATE_KEYS
    assert "basis_mismatch_last_alert_at" in analyzer_mod._ANALYZER_OWNED_STATE_KEYS
