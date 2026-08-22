"""清除必須清乾淨：只刪主資料表會讓新 PCE 沿用舊的擷取位置。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, DeadLetter, IngestionCursor, IngestionWatermark, PceEvent,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, SiemDispatch,
)
from src.pce_cache.flush import _MODELS, flush_pce_derived_state


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
        s.commit()
    return engine, sf


# 獨立於 flush.py 之外，逐字寫死 src/pce_cache/models.py 目前的八個
# __tablename__——不可從 _MODELS 反推，否則從 _MODELS 拿掉一個模型時，
# 兩個斷言迴圈只是少跑一輪、測試照樣綠燈，重演了原本的漏洞（只是從
# seed 端搬到 assert 端）。這裡用集合相等（而非子集）比對，才能同時
# 抓到「少一個表」和「多一個不該在的表」。
_EXPECTED_TABLENAMES = {
    "pce_events",
    "pce_traffic_flows_raw",
    "pce_traffic_flow_obs",
    "pce_traffic_flows_agg",
    "ingestion_cursors",
    "ingestion_watermarks",
    "siem_dispatch",
    "dead_letter",
}


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
                 "event_parser_stats", "posture_summary"):
        assert gone not in left, gone
    # 排程是操作者自己建的，不隨 PCE 的資料一起清掉。
    assert left["rule_schedule_states"] == {"s1": "keep"}
    assert left["settings_backup"] == {"keep": "me"}, "非 PCE 衍生的鍵不可被動到"


def test_flush_on_a_missing_db_is_not_an_error(tmp_path):
    counts = flush_pce_derived_state(str(tmp_path / "nope.db"), str(tmp_path / "nope.json"))
    assert counts == {}
