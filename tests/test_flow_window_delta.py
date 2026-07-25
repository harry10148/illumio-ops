"""Gate tests for phase 2 of the aggregation-basis fix: per-window deltas
derived from successive cache observations.

Phase 1 (tests/test_analyzer_bucket_basis_guard.py) established the problem:
this PCE aggregates into day-sized buckets and returns whole-bucket byte and
connection totals that are NOT clipped to the query window, so a short-window
rule was comparing its threshold against hours of accumulated traffic. Phase 1
suppressed such rules; phase 2 makes them evaluable again by differencing two
observations of the same flow key.

The invariants pinned here:

  1. Two observations across a rule's window produce the true in-window delta,
     per metric (bytes out, bytes in, connection count), and the rule evaluates
     against THAT — not against the bucket total.
  2. A counter reset (PCE rolls the bucket at midnight) makes t2 - t1 negative.
     That is a rollover, never negative traffic: the engine must not emit a
     negative value and must fall back to the phase-1 guard.
  3. Every case where a delta genuinely cannot be derived (no cache, no prior
     observation, baseline too old for the window) falls back to the phase-1
     guard — suppression plus a loud signal, never a guess.
  4. Observations are pruned; growth is bounded, and pruning is NOT withheld
     by archive state (obs rows are never archived — see
     flow_deltas.prune_flow_observations).
  5. A DB at the previous schema version upgrades cleanly to the observation
     table, and a fresh DB lands on the current version.
  6. The ingestor and the analyzer must read the SAME cumulative counters from
     a payload, otherwise every delta is garbage.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest
from loguru import logger as _logger
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from src.analyzer import Analyzer, DELTA_BASIS_NOTE
from src.pce_cache.flow_deltas import (
    FlowDeltaReader, cumulative_metrics, prune_flow_observations,
)
from src.pce_cache.ingestor_traffic import TrafficIngestor, flow_hash
from src.pce_cache.models import PceTrafficFlowObs
from src.pce_cache.schema import _SCHEMA_VERSION, init_schema
from src.pce_cache.watermark import WatermarkStore

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 25, 8, 27, 0, tzinfo=UTC)
MIDNIGHT = "2026-07-25T00:00:00Z"


# ─── fixtures / builders ────────────────────────────────────────────────────

@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _bucket_flow(*, conns=6124, b_out=3_710_468, b_in=4_504_322,
                 first_detected=MIDNIGHT, src="10.0.0.5"):
    """真機形狀：dst_bi/dst_bo（非 dst_tb*/dst_db*），first_detected 在午夜。"""
    return {
        "timestamp_range": {
            "first_detected": first_detected,
            "last_detected": "2026-07-25T08:26:30Z",
        },
        "src_ip": src,
        "dst_ip": "10.9.9.9",
        "policy_decision": "blocked",
        "pd": 2,
        "num_connections": conns,
        "dst_bo": b_out,
        "dst_bi": b_in,
        "src": {},
        "dst": {},
        "service": {"port": 443, "proto": 6},
    }


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


def _analyzer(rules, delta_reader=None):
    cm = MagicMock()
    cm.config = {"rules": rules}
    az = Analyzer(cm, MagicMock(), MagicMock(), flow_delta_reader=delta_reader)
    az.save_state = MagicMock()
    az.load_state = MagicMock()
    return az


def _observe(session_factory, flow, observed_at):
    """手動記一筆觀測（等同 ingest 在該時刻跑過一次）。"""
    b_out, b_in, conn = cumulative_metrics(flow)
    with session_factory.begin() as s:
        s.add(PceTrafficFlowObs(
            flow_hash=flow_hash(flow), observed_at=observed_at,
            bytes_out=b_out, bytes_in=b_in, conn_count=conn))


@pytest.fixture
def warnings():
    msgs: list[str] = []
    sink = _logger.add(lambda m: msgs.append(str(m)), level="WARNING")
    yield msgs
    _logger.remove(sink)


# ─── 6: one implementation of the cumulative counters ───────────────────────

def test_cumulative_metrics_matches_the_analyzer_field_chain():
    """obs 寫入端與 analyzer 讀取端必須從同一組欄位取值。"""
    # 真機形狀（dst_bo/dst_bi）
    assert cumulative_metrics(_bucket_flow()) == (3_710_468, 4_504_322, 6124)
    # dst_tb* 優先於 dst_b*（與 calculate_volume_mb 的 Priority-2 相同）
    flow = _bucket_flow()
    flow["dst_tbo"], flow["dst_tbi"] = 7, 9
    assert cumulative_metrics(flow)[:2] == (7, 9)
    # 缺欄位 / 畸形值不得拋例外
    assert cumulative_metrics({}) == (0, 0, 1)
    assert cumulative_metrics({"dst_bo": "n/a", "num_connections": None}) == (0, 0, 1)


def test_analyzer_and_ingestor_agree_on_the_volume_basis():
    """analyzer 的 (Total) 位元組數＝obs 的 bytes_out + bytes_in。"""
    az = _analyzer([])
    flow = _bucket_flow()
    vol_mb, note = az.calculate_volume_mb(flow)
    b_out, b_in, _ = cumulative_metrics(flow)
    assert note == "(Total)"
    assert vol_mb == pytest.approx((b_out + b_in) / 1024 / 1024)


# ─── ingest records observations ────────────────────────────────────────────

class _FakeApi:
    last_fetch_error = None

    def __init__(self, flows):
        self._flows = flows

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        return self._flows


def test_ingest_records_one_observation_per_flow_per_run(session_factory):
    flow = _bucket_flow()
    wm = WatermarkStore(session_factory)
    TrafficIngestor(api=_FakeApi([flow]), session_factory=session_factory,
                    watermark=wm).run_once()
    grown = _bucket_flow(conns=6200, b_out=3_800_000, b_in=4_600_000)
    TrafficIngestor(api=_FakeApi([grown]), session_factory=session_factory,
                    watermark=wm).run_once()

    with session_factory() as s:
        rows = s.execute(
            select(PceTrafficFlowObs).order_by(PceTrafficFlowObs.observed_at)
        ).scalars().all()
    assert len(rows) == 2, "每次 ingest 每筆 flow 記一列，否則沒有前一次觀測可相減"
    assert [r.conn_count for r in rows] == [6124, 6200]
    assert [r.bytes_out for r in rows] == [3_710_468, 3_800_000]
    assert len({r.flow_hash for r in rows}) == 1


def test_ingest_can_be_told_not_to_record(session_factory):
    TrafficIngestor(api=_FakeApi([_bucket_flow()]), session_factory=session_factory,
                    watermark=WatermarkStore(session_factory),
                    record_observations=False).run_once()
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(PceTrafficFlowObs)).scalar() == 0


# ─── 1: the delta is the in-window traffic ──────────────────────────────────

def test_baseline_lookup_returns_latest_observation_at_or_before_the_window(session_factory):
    flow = _bucket_flow()
    _observe(session_factory, _bucket_flow(conns=1, b_out=10, b_in=20),
             NOW - datetime.timedelta(minutes=30))
    _observe(session_factory, _bucket_flow(conns=2, b_out=30, b_in=40),
             NOW - datetime.timedelta(minutes=11))
    # 視窗起點之後的觀測不得被選為基準（那會低估視窗內的量）
    _observe(session_factory, _bucket_flow(conns=3, b_out=50, b_in=60),
             NOW - datetime.timedelta(minutes=2))

    reader = FlowDeltaReader(session_factory)
    base = reader.baselines([flow_hash(flow)], NOW - datetime.timedelta(minutes=10))
    got = base[flow_hash(flow)]
    assert (got.bytes_out, got.bytes_in, got.conn_count) == (30, 40, 2)
    assert got.observed_at == NOW - datetime.timedelta(minutes=11)


@pytest.mark.parametrize("rtype,expected", [
    ("traffic", 124.0),                                   # 6124 - 6000 連線
    ("volume", (68_000 + 4_322) / 1024 / 1024),           # 位元組增量 → MB
])
def test_short_window_rule_evaluates_the_window_delta_not_the_bucket_total(
        session_factory, rtype, expected):
    """核心：規則拿到的是視窗內的增量，不再是整個 bucket 的累計值。"""
    rule = _rule("tr1", rtype, window=10, threshold=0)
    current = _bucket_flow(conns=6124, b_out=3_710_468, b_in=4_504_322)
    _observe(session_factory,
             _bucket_flow(conns=6000, b_out=3_642_468, b_in=4_500_000),
             NOW - datetime.timedelta(minutes=10))

    az = _analyzer([rule], FlowDeltaReader(session_factory))
    triggers = az._run_rule_engine([current], [rule], NOW)
    _, res = triggers[0]

    assert "basis_mismatch" not in res, "有基準就不該再退回守門"
    assert res["max_val"] == pytest.approx(expected, rel=1e-6)
    assert res["top_matches"][0]["_metric_fmt"].endswith(DELTA_BASIS_NOTE) or rtype == "traffic"


def test_bandwidth_rule_uses_the_delta_over_its_actual_span(session_factory):
    rule = _rule("bw", "bandwidth", window=10, threshold=0)
    base_at = NOW - datetime.timedelta(minutes=10)
    current = _bucket_flow(b_out=3_710_468, b_in=4_504_322)
    _observe(session_factory, _bucket_flow(b_out=3_700_468, b_in=4_500_322), base_at)

    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([current], [rule], NOW)[0]

    delta_bytes = (3_710_468 - 3_700_468) + (4_504_322 - 4_500_322)
    span = (NOW - base_at).total_seconds()
    assert res["max_val"] == pytest.approx(delta_bytes * 8.0 / span / 1e6)


def test_delta_is_per_flow_key(session_factory):
    """兩筆不同 flow 的增量不得互相污染。"""
    rule = _rule("tr1", "traffic", window=10, threshold=0)
    a_now, b_now = _bucket_flow(conns=100, src="10.0.0.1"), _bucket_flow(conns=500, src="10.0.0.2")
    _observe(session_factory, _bucket_flow(conns=90, src="10.0.0.1"),
             NOW - datetime.timedelta(minutes=10))
    _observe(session_factory, _bucket_flow(conns=200, src="10.0.0.2"),
             NOW - datetime.timedelta(minutes=10))

    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([a_now, b_now], [rule], NOW)[0]
    assert res["max_val"] == 10 + 300


# ─── 2: midnight counter reset ──────────────────────────────────────────────

def test_counter_reset_is_not_negative_traffic(session_factory, warnings):
    """午夜換 bucket → 累計值歸零 → t2 - t1 為負。那是歸零，不是負流量：
    引擎不得產出負值，必須退回守門。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    # 基準是上一個 bucket 的高水位；當下值已在新 bucket 內重新計數
    _observe(session_factory, _bucket_flow(conns=9000, b_out=9_000_000, b_in=9_000_000),
             NOW - datetime.timedelta(minutes=10))
    current = _bucket_flow(conns=12, b_out=1_000, b_in=2_000)

    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([current], [rule], NOW)[0]

    assert res["max_val"] == 0.0, "不得把負增量計入"
    assert res["max_val"] >= 0
    mismatch = res.get("basis_mismatch")
    assert mismatch, "歸零時必須退回守門，不可以猜"
    assert mismatch["reasons"]["counter_reset"] == 1
    assert any("counter_reset" in m for m in warnings)


@pytest.mark.parametrize("rtype", ["traffic", "volume", "bandwidth"])
def test_no_metric_can_go_negative_across_the_reset(session_factory, rtype):
    rule = _rule("tr1", rtype, window=10, threshold=0)
    _observe(session_factory, _bucket_flow(conns=9000, b_out=9_000_000, b_in=9_000_000),
             NOW - datetime.timedelta(minutes=10))
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([_bucket_flow(conns=1, b_out=1, b_in=1)], [rule], NOW)[0]
    assert res["max_val"] >= 0.0
    assert res["top_matches"] == []


def test_a_single_rolled_over_metric_guards_the_whole_flow(session_factory):
    """只有 bytes 歸零、連線數還在漲時也算歸零——三個計數器同源，
    其中之一倒退就代表 PCE 換了 bucket，全部都不可信。"""
    rule = _rule("tr1", "traffic", window=10, threshold=0)
    _observe(session_factory, _bucket_flow(conns=10, b_out=9_000_000, b_in=1),
             NOW - datetime.timedelta(minutes=10))
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([_bucket_flow(conns=20, b_out=5, b_in=2)], [rule], NOW)[0]
    assert res.get("basis_mismatch")
    assert res["basis_mismatch"]["reasons"]["counter_reset"] == 1


# ─── 3: fall back to the phase-1 guard, never guess ─────────────────────────

def test_no_delta_reader_falls_back_to_the_guard(session_factory):
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule], delta_reader=None)
    _, res = az._run_rule_engine([_bucket_flow()], [rule], NOW)[0]
    assert res["basis_mismatch"]["reasons"]["no_cache"] == 1


def test_first_observation_of_a_flow_falls_back_to_the_guard(session_factory):
    """視窗起點之前沒有觀測（flow 剛第一次被看到）＝算不出增量。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    _observe(session_factory, _bucket_flow(), NOW - datetime.timedelta(minutes=2))
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([_bucket_flow()], [rule], NOW)[0]
    assert res["basis_mismatch"]["reasons"]["no_baseline"] == 1


def test_stale_baseline_falls_back_to_the_guard(session_factory):
    """基準遠早於視窗起點（ingest 間隔遠大於視窗）＝增量涵蓋的區間比視窗長
    太多，還原不出短視窗語意，寧可不評估。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    _observe(session_factory, _bucket_flow(conns=1),
             NOW - datetime.timedelta(minutes=70))     # 早於視窗起點 60 分鐘
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([_bucket_flow()], [rule], NOW)[0]
    assert res["basis_mismatch"]["reasons"]["stale_baseline"] == 1


def test_baseline_slightly_older_than_the_window_is_accepted(session_factory):
    """容忍度內（視窗 10 分鐘 → 2.5 分鐘）的基準仍可用：增量是視窗的超集，
    多算的部分有上限。"""
    rule = _rule("tr1", "traffic", window=10, threshold=0)
    _observe(session_factory, _bucket_flow(conns=6000),
             NOW - datetime.timedelta(minutes=12))
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine([_bucket_flow(conns=6124)], [rule], NOW)[0]
    assert "basis_mismatch" not in res
    assert res["max_val"] == 124


def test_delta_reader_failure_degrades_to_the_guard_not_a_crash(session_factory, warnings):
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    broken = MagicMock()
    broken.baselines.side_effect = RuntimeError("database is locked")
    az = _analyzer([rule], broken)
    _, res = az._run_rule_engine([_bucket_flow()], [rule], NOW)[0]
    assert res["basis_mismatch"]["reasons"]["no_cache"] == 1
    assert any("Window-delta baselines unavailable" in m for m in warnings)


def test_guard_still_suppresses_the_alert_and_meta_alerts(session_factory):
    """退回守門時 phase-1 的所有保證仍然成立（不告警 + meta-alert）。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    triggers = az._run_rule_engine([_bucket_flow()], [rule], NOW)
    az._dispatch_alerts(triggers, [rule])
    az.reporter.add_traffic_alert.assert_not_called()
    assert az.state["basis_mismatch"]["delta_reasons"] == "no_baseline=1"
    az._maybe_alert_overflow()
    az.reporter.add_health_alert.assert_called_once()


def test_flow_inside_the_window_never_needs_a_delta(session_factory):
    """聚合區間本來就落在視窗內：原始值就是視窗值，不查基準也不守門。"""
    rule = _rule("tr1", "traffic", window=10, threshold=1)
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    fresh = _bucket_flow(first_detected="2026-07-25T08:25:00Z")
    _, res = az._run_rule_engine([fresh], [rule], NOW)[0]
    assert "basis_mismatch" not in res
    assert res["max_val"] == 6124


# ─── 4: retention / pruning ─────────────────────────────────────────────────

def test_prune_deletes_only_observations_older_than_the_cutoff(session_factory):
    _observe(session_factory, _bucket_flow(src="10.0.0.1"), NOW - datetime.timedelta(hours=9))
    _observe(session_factory, _bucket_flow(src="10.0.0.2"), NOW - datetime.timedelta(hours=1))
    deleted = prune_flow_observations(session_factory, NOW - datetime.timedelta(hours=6))
    assert deleted == 1
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(PceTrafficFlowObs)).scalar() == 1


def test_prune_is_not_withheld_by_archive_state(session_factory):
    """obs 從不進 archive，扣住不刪保護不到任何 archive 內容，只會讓一張
    以小時計的工作表無界成長。archive_enabled 不得阻擋 obs 修剪。
    （retention.py 的 archive 守門仍完整適用於 raw/events。）"""
    from src.pce_cache.retention import RetentionWorker
    _observe(session_factory, _bucket_flow(), NOW - datetime.timedelta(hours=9))
    result = RetentionWorker(session_factory).run_once(
        archive_enabled=True, flow_obs_hours=6)
    assert result["flow_obs"] == 1
    # 對照：archive 守門確實把 raw 的刪除扣住了（cursor 為 None）
    assert result["traffic_raw"] == 0


def test_ingest_prunes_so_the_table_cannot_grow_unbounded(session_factory):
    """修剪跟著 ingest 節奏跑，而不是只靠 24 小時一次的 retention job。"""
    _observe(session_factory, _bucket_flow(src="10.9.9.9"),
             datetime.datetime.now(UTC) - datetime.timedelta(hours=48))
    TrafficIngestor(api=_FakeApi([_bucket_flow()]), session_factory=session_factory,
                    watermark=WatermarkStore(session_factory),
                    obs_retention_hours=6).run_once()
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowObs)).scalars().all()
    assert len(rows) == 1, "48 小時前的觀測必須在 ingest 後被刪掉"


def test_ingest_survives_a_prune_failure(session_factory, monkeypatch, warnings):
    """修剪失敗不得把整次 ingest 標成失敗（資料已寫入、watermark 已前進）。"""
    import src.pce_cache.flow_deltas as fd
    monkeypatch.setattr(fd, "prune_flow_observations",
                        MagicMock(side_effect=RuntimeError("database is locked")))
    count = TrafficIngestor(api=_FakeApi([_bucket_flow()]),
                            session_factory=session_factory,
                            watermark=WatermarkStore(session_factory)).run_once()
    assert count == 1
    assert any("Flow observation prune failed" in m for m in warnings)


# ─── 5: schema upgrade ──────────────────────────────────────────────────────

def test_fresh_db_lands_on_the_current_schema_version(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.sqlite'}")
    init_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION
    engine.dispose()


def test_previous_version_db_upgrades_to_the_observation_table(tmp_path):
    """既有部署（user_version=1、沒有 obs 表）必須乾淨升級。"""
    db = tmp_path / "old.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    # 倒回前一版：丟掉 obs 表並把版本設回 1
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE pce_traffic_flow_obs"))
        conn.execute(text("PRAGMA user_version = 1"))
    engine.dispose()

    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION
        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "pce_traffic_flow_obs" in names
        idx = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='pce_traffic_flow_obs'"))}
        assert "ix_obs_hash_observed" in idx
    # 升級後立刻可用（讀寫都不再需要人工介入）
    sf = sessionmaker(engine)
    _observe(sf, _bucket_flow(), NOW - datetime.timedelta(minutes=10))
    assert FlowDeltaReader(sf).baselines([flow_hash(_bucket_flow())], NOW)
    engine.dispose()


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "twice.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    init_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION
    engine.dispose()


# ─── run_debug_mode must not lie about what the engine would do ─────────────

class _DebugApi:
    """run_debug_mode 只需要這兩個方法（不會派送任何東西）。"""

    def __init__(self, flows):
        self._flows = flows

    def fetch_events(self, since):
        return []

    def execute_traffic_query_stream(self, start, end, pds):
        return iter(self._flows)


def _debug_analyzer(rules, flows, delta_reader=None):
    cm = MagicMock()
    cm.config = {"rules": rules}
    az = Analyzer(cm, _DebugApi(flows), MagicMock(), flow_delta_reader=delta_reader)
    az.save_state = MagicMock()
    az.load_state = MagicMock()
    return az


def _live_bucket_flow(now, **over):
    """debug 模式用真實時鐘（now=datetime.now），flow 時戳必須跟著真實時間走，
    否則 _match_flow_filters 的視窗過濾會先把它濾掉。"""
    flow = _bucket_flow(**over)
    flow["timestamp_range"] = {
        # 聚合區間起點＝當日午夜（真機形狀），一定早於任何短視窗起點
        "first_detected": now.replace(hour=0, minute=0, second=0, microsecond=0)
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_detected": (now - datetime.timedelta(seconds=30))
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return flow


def test_debug_mode_reports_the_guard_instead_of_a_false_would_trigger(
        session_factory, capsys):
    """守門生效時，模擬不可以照樣宣告 Would Trigger——引擎其實根本沒評估。"""
    now = datetime.datetime.now(UTC)
    rule = _rule("tr1", "traffic", window=10, threshold=1, name="short win")
    az = _debug_analyzer([rule], [_live_bucket_flow(now)], FlowDeltaReader(session_factory))
    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "Aggregation-basis guard" in out
    assert "no_baseline=1" in out
    assert "NOT evaluated" in out
    assert "WOULD TRIGGER" not in out.upper()


def test_debug_mode_uses_the_same_window_delta_as_the_engine(session_factory, capsys):
    now = datetime.datetime.now(UTC)
    rule = _rule("tr1", "traffic", window=10, threshold=0, name="short win")
    current = _live_bucket_flow(now, conns=6124)
    _observe(session_factory, _live_bucket_flow(now, conns=6000),
             now - datetime.timedelta(minutes=10))

    az = _debug_analyzer([rule], [current], FlowDeltaReader(session_factory))
    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "per-window delta" in out
    assert "Aggregation-basis guard" not in out
    # 模擬印出的量必須就是引擎會算出的量（124，而非 bucket 累計的 6124）
    assert "124" in out and "6124" not in out


# ─── end-to-end: ingest → cache → rule engine ───────────────────────────────

def test_end_to_end_ingest_then_evaluate_uses_the_delta(session_factory):
    """整條真實路徑：ingest 兩次寫入觀測 → subscriber 取出視窗列 → 規則引擎
    算增量。特別守的是「analyzer 從 raw_json 重算的 flow_hash 必須等於 ingest
    寫進 obs 的鍵」——兩邊對不上的話增量會全面退化成 no_baseline，而且不會有
    任何單元測試看得出來。"""
    from src.pce_cache.subscriber import CacheSubscriber

    now = datetime.datetime.now(UTC)
    wm = WatermarkStore(session_factory)

    def _flow(conns, last_offset_s):
        f = _bucket_flow(conns=conns)
        f["timestamp_range"] = {
            "first_detected": now.replace(hour=0, minute=0, second=0, microsecond=0)
                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_detected": (now - datetime.timedelta(seconds=last_offset_s))
                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return f

    TrafficIngestor(api=_FakeApi([_flow(6000, 700)]), session_factory=session_factory,
                    watermark=wm).run_once()
    # 第一次觀測往回挪到視窗起點之前（模擬上一輪 poll）
    with session_factory.begin() as s:
        s.execute(text("UPDATE pce_traffic_flow_obs SET observed_at = :ts"),
                  {"ts": (now - datetime.timedelta(minutes=10))
                          .strftime("%Y-%m-%d %H:%M:%S.%f")})
    TrafficIngestor(api=_FakeApi([_flow(6124, 30)]), session_factory=session_factory,
                    watermark=wm).run_once()

    sub = CacheSubscriber(session_factory, consumer="analyzer",
                          source_table="pce_traffic_flows_raw")
    flows = sub.fetch_window_rows(now - datetime.timedelta(minutes=12))
    assert len(flows) == 1

    rule = _rule("tr1", "traffic", window=10, threshold=0)
    az = _analyzer([rule], FlowDeltaReader(session_factory))
    _, res = az._run_rule_engine(flows, [rule], now)[0]

    assert "basis_mismatch" not in res, "hash 對不上就會退回守門"
    assert res["max_val"] == 124


def test_migration_step_alone_creates_the_table(tmp_path):
    """遷移步驟本身必須能建表——不可以只依賴 create_all 的呼叫順序，
    否則走 create_all 之外的入口（或未來把 create_all 拿掉）就升不上去。"""
    from src.pce_cache.schema import _run_migrations

    db = tmp_path / "bare.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE pce_traffic_flow_obs"))
        conn.execute(text("PRAGMA user_version = 1"))
    # 只跑遷移鏈（不經 create_all）
    _run_migrations(engine)
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "pce_traffic_flow_obs" in names
        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION
    engine.dispose()
