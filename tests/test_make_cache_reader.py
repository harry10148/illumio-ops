from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceTrafficFlowRaw
from datetime import datetime, timezone


def _cm(db_path, enabled=True):
    cache = SimpleNamespace(enabled=enabled, db_path=db_path,
                            events_retention_days=30, traffic_raw_retention_days=30)
    return SimpleNamespace(models=SimpleNamespace(pce_cache=cache))


def test_reader_uses_explicit_db_path_bypassing_enabled(tmp_path):
    from src.main import _make_cache_reader
    live = str(tmp_path / "live.sqlite")
    review = str(tmp_path / "review.sqlite")
    # review DB 有一列、live DB 沒有；即使 enabled=False，帶 db_path 仍應讀 review
    eng = create_engine(f"sqlite:///{review}")
    init_schema(eng)
    with sessionmaker(eng).begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="h1", first_detected=datetime(2026, 6, 30, tzinfo=timezone.utc),
            last_detected=datetime(2026, 6, 30, tzinfo=timezone.utc),
            src_ip="10.0.0.1", dst_ip="10.0.0.2", port=443, protocol="tcp",
            action="allowed", flow_count=1, bytes_in=0, bytes_out=0,
            raw_json="{}", ingested_at=datetime(2026, 6, 30, tzinfo=timezone.utc)))
    reader = _make_cache_reader(_cm(live, enabled=False), db_path=review)
    assert reader is not None
    flows = reader.read_flows_raw(
        datetime(2026, 6, 29, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert len(list(flows)) == 1


def test_reader_default_path_still_gated_by_enabled(tmp_path):
    from src.main import _make_cache_reader
    assert _make_cache_reader(_cm(str(tmp_path / "x.sqlite"), enabled=False)) is None
