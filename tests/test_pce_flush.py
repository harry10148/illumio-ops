"""清除必須清乾淨：只刪主資料表會讓新 PCE 沿用舊的擷取位置。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, CacheBinding, DeadLetter, IngestionCursor, IngestionWatermark, PceEvent,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, SiemDispatch,
)
from src.pce_cache.flush import _MODELS, _STATE_KEYS, flush_pce_derived_state


@pytest.fixture(autouse=True)
def _isolate_side_files(tmp_path, monkeypatch):
    """flush_pce_derived_state() now reaches two files it is not handed:
    <repo>/logs/analysis.lock (the cross-process analysis lock it takes) and
    <repo>/logs/dashboard_summary.json (ven_summary). Both must land in
    tmp_path — on a checkout where the appliance actually runs, the first
    would block on a live monitor cycle and the second would delete its real
    VEN summary."""
    import src.main as _main
    from src import dashboard_store
    monkeypatch.setattr(_main, "analysis_lock_path",
                        lambda: str(tmp_path / "analysis.lock"))
    monkeypatch.setattr(dashboard_store, "_dashboard_file",
                        lambda: str(tmp_path / "dashboard_summary.json"))


def _seed(db_path):
    """一個模型一列，覆蓋全部八個表——只種其中三個曾經讓拿掉
    IngestionCursor/DeadLetter/PceTrafficFlow* 之一而不掉 _MODELS 的
    回歸沒有任何測試會發現。欄位取自 src/pce_cache/models.py：多數欄位
    NOT NULL，少一個就是 IntegrityError 而不是測試失敗。"""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine)
    with sf() as s:
        s.add(PceEvent(pce_href="/orgs/1/events/a", pce_event_id="a",
                       timestamp=now, event_type="x", severity="info",
                       status="success", pce_fqdn="pce.example.com",
                       raw_json="{}", ingested_at=now))
        s.add(PceTrafficFlowRaw(flow_hash="h1", first_detected=now, last_detected=now,
                                src_ip="10.0.0.1", dst_ip="10.0.0.2", port=443,
                                protocol="tcp", action="allowed", raw_json="{}",
                                ingested_at=now))
        s.add(PceTrafficFlowObs(flow_hash="h1", observed_at=now))
        s.add(PceTrafficFlowAgg(bucket_day=now, port=443, protocol="tcp", action="allowed"))
        s.add(IngestionCursor(consumer="analyzer", source_table="pce_events", updated_at=now))
        s.add(IngestionWatermark(source="events", last_href="/orgs/1/events/a"))
        s.add(SiemDispatch(source_table="pce_events", source_id=1,
                           destination="splunk", status="pending",
                           queued_at=now))
        s.add(DeadLetter(source_table="pce_events", source_id=1, destination="splunk",
                         retries=3, last_error="boom", payload_preview="{}",
                         quarantined_at=now))
        s.add(CacheBinding(id=1, pce_url="https://pce.example.com:8443", org_id="1",
                           bound_at=now))
        s.commit()
    return engine, sf


# 獨立於 flush.py 之外，逐字寫死 src/pce_cache/models.py 目前的八個
# __tablename__——不可從 _MODELS 反推，否則從 _MODELS 拿掉一個模型時，
# 兩個斷言迴圈只是少跑一輪、測試照樣綠燈，重演了原本的漏洞（只是從
# seed 端搬到 assert 端）。這裡用集合相等（而非子集）比對，才能同時
# 抓到「少一個表」和「多一個不該在的表」。
# 同樣獨立於 flush.py：逐字寫死目前該被清掉的 state.json 鍵。不可從
# _STATE_KEYS 反推，理由與下面 _EXPECTED_TABLENAMES 相同——集合相等比對才
# 能同時抓到「漏掉一個 PCE 衍生鍵」（新 PCE 繼承舊 PCE 的擷取位置／告警冷卻）
# 和「多清了一個不該清的鍵」（操作者自己建的排程被連坐清掉）。
# 來源：src/analyzer.py 的 _ANALYZER_OWNED_STATE_KEYS ＋ flush.py 的
# _EXTRA_PCE_DERIVED。
_EXPECTED_STATE_KEYS = {
    # _ANALYZER_OWNED_STATE_KEYS
    "last_check",
    "event_watermark",
    "history",
    "alert_history",
    "event_seen",
    "unknown_events",
    "event_parser_stats",
    "event_parser_samples",
    "throttle_state",
    "overflow_last_alert_at",
    "traffic_overflow_last_alert_at",
    "window_truncation",
    "window_truncation_last_alert_at",
    "basis_mismatch",
    "basis_mismatch_last_alert_at",
    "basis_value_mismatch",
    "basis_value_mismatch_last_alert_at",
    # _EXTRA_PCE_DERIVED
    "event_timeline",
    "pce_stats",
    "posture_summary",
    # 擷取事故本身，不是它的冷卻——只清冷卻、留著事故，新 PCE 下一個 cycle
    # 就會用舊 PCE 的擷取紀錄再發一次資料遺失告警。
    "event_overflow",
    "traffic_overflow",
}


_EXPECTED_TABLENAMES = {
    "pce_events",
    "pce_traffic_flows_raw",
    "pce_traffic_flow_obs",
    "pce_traffic_flows_agg",
    "ingestion_cursors",
    "ingestion_watermarks",
    "siem_dispatch",
    "dead_letter",
    # 「這份快取屬於哪台 PCE」——flush.py 開頭說的那個缺席的 tenant 維度。
    # 模型在 models.py（schema.init_schema 只認 Base），驗證邏輯在
    # provenance.py。清它的理由見 flush.py 的 _MODELS 註解：每個呼叫端都在
    # 寫入新連線**之前** flush，所以留著它就是留著被拋下那台的名字。
    "cache_binding",
}


def test_state_key_inventory_matches_the_independent_expectation():
    _actual = set(_STATE_KEYS)
    assert _actual == _EXPECTED_STATE_KEYS, (
        f"_STATE_KEYS drifted: missing={_EXPECTED_STATE_KEYS - _actual}, "
        f"extra={_actual - _EXPECTED_STATE_KEYS}"
    )


def test_flush_empties_every_table_including_watermarks(tmp_path):
    _actual = {model.__tablename__ for model in _MODELS}
    assert _actual == _EXPECTED_TABLENAMES, (
        f"_MODELS drifted from src/pce_cache/models.py: "
        f"missing={_EXPECTED_TABLENAMES - _actual}, extra={_actual - _EXPECTED_TABLENAMES}"
    )

    db = tmp_path / "cache.db"
    engine, sf = _seed(str(db))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "event_watermark": "2026-01-01T00:00:00Z",
        "alert_history": {"r1": "2026-01-01T00:00:00Z"},
        "event_seen": ["a"],
        "event_parser_stats": {"n": 1},
        "posture_summary": {"x": 1},
        "event_overflow": {"window": "old-pce"},
        "traffic_overflow": {"window": "old-pce"},
        "rule_schedule_states": {"s1": "keep"},
        "settings_backup": {"keep": "me"},
    }), encoding="utf-8")

    counts = flush_pce_derived_state(str(db), str(state))

    with sf() as s:
        for model in _MODELS:
            assert s.execute(select(model)).all() == [], model.__tablename__
    for model in _MODELS:
        assert counts[model.__tablename__] == 1, model.__tablename__

    left = json.loads(state.read_text(encoding="utf-8"))
    for gone in ("event_watermark", "alert_history", "event_seen",
                 "event_parser_stats", "posture_summary",
                 "event_overflow", "traffic_overflow"):
        assert gone not in left, gone
    # 排程是操作者自己建的，不隨 PCE 的資料一起清掉。
    assert left["rule_schedule_states"] == {"s1": "keep"}
    assert left["settings_backup"] == {"keep": "me"}, "非 PCE 衍生的鍵不可被動到"


def test_flush_clears_the_dashboard_summarys_ven_counts(tmp_path):
    """ven_summary is the old PCE's estate too — same provenance as
    posture_summary, just a different file (logs/dashboard_summary.json).
    Keys of that file which are not PCE-derived stay."""
    from src import dashboard_store

    path = dashboard_store._dashboard_file()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ven_summary": {"total": 9, "online": 9},
                   "operator_note": "keep me"}, f)

    counts = flush_pce_derived_state(str(tmp_path / "nope.db"), str(tmp_path / "nope.json"))

    assert counts["dashboard_keys"] == 1
    with open(path, encoding="utf-8") as f:
        left = json.load(f)
    assert "ven_summary" not in left
    assert left["operator_note"] == "keep me"


def test_flush_on_a_missing_db_is_not_an_error(tmp_path):
    counts = flush_pce_derived_state(str(tmp_path / "nope.db"), str(tmp_path / "nope.json"))
    assert counts == {"dashboard_keys": 0}


def test_flush_runs_under_both_analysis_locks(tmp_path, monkeypatch):
    """The cleared keys are only cleared if no monitor cycle can write its
    load-time snapshot back over them (analyzer.py's save_state merge), so the
    clear has to hold the cross-process file lock AND the in-process one, in
    the order every other full-cycle entry point takes them
    (scheduler/jobs.py's run_monitor_cycle). Asserting the order — not just
    that both were held — is the point: it is what keeps this off the wrong
    side of an ABBA deadlock with the other callers."""
    import contextlib

    import src.analyzer as analyzer_mod
    import src.file_lock as file_lock_mod

    seen: list[str] = []

    class _Probe:
        def __enter__(self):
            seen.append("analysis_lock")
            return self

        def __exit__(self, *a):
            return False

    real_file_lock = file_lock_mod.file_lock

    @contextlib.contextmanager
    def _probe_file_lock(path, timeout=None):
        seen.append("file_lock")
        with real_file_lock(path, timeout=timeout):
            yield

    monkeypatch.setattr(analyzer_mod, "analysis_lock", _Probe())
    monkeypatch.setattr("src.file_lock.file_lock", _probe_file_lock)

    flush_pce_derived_state(str(tmp_path / "nope.db"), str(tmp_path / "nope.json"))

    assert seen == ["file_lock", "analysis_lock"], seen
