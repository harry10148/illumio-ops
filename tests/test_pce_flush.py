"""清除必須清乾淨：只刪主資料表會讓新 PCE 沿用舊的擷取位置。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, PceEvent, IngestionWatermark, SiemDispatch,
)
from src.pce_cache.flush import flush_pce_derived_state


def _seed(db_path):
    """欄位取自 src/pce_cache/models.py：PceEvent 與 SiemDispatch 幾乎全欄位
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
        s.add(IngestionWatermark(source="events", last_href="/orgs/1/events/a"))
        s.add(SiemDispatch(source_table="pce_events", source_id=1,
                           destination="splunk", status="pending",
                           queued_at=now))
        s.commit()
    return engine, sf


def test_flush_empties_every_table_including_watermarks(tmp_path):
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
        assert s.execute(select(PceEvent)).all() == []
        assert s.execute(select(IngestionWatermark)).all() == []
        assert s.execute(select(SiemDispatch)).all() == []
    assert counts["pce_events"] == 1
    assert counts["ingestion_watermarks"] == 1

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
