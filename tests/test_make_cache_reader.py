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


def test_reader_uses_nullpool(tmp_path):
    # _make_cache_reader 每次呼叫都建新 engine；預設 pool（QueuePool）從不
    # dispose，per-request 熱路徑（gui/routes/actions.py 對 archive 查詢）
    # 會累積連線池與 FD。鎖定必須用 NullPool，比照 review_session_factory。
    from src.main import _make_cache_reader
    reader = _make_cache_reader(_cm(str(tmp_path / "x.sqlite")))
    engine = reader._sf.kw["bind"]
    assert type(engine.pool).__name__ == "NullPool"


def test_reader_explicit_db_path_uses_nullpool(tmp_path):
    from src.main import _make_cache_reader
    reader = _make_cache_reader(
        _cm(str(tmp_path / "live.sqlite"), enabled=False),
        db_path=str(tmp_path / "review.sqlite"),
    )
    engine = reader._sf.kw["bind"]
    assert type(engine.pool).__name__ == "NullPool"


def test_subscribers_use_nullpool(tmp_path):
    from src.main import _make_subscribers
    sub_events, sub_flows = _make_subscribers(_cm(str(tmp_path / "x.sqlite")))
    assert type(sub_events._sf.kw["bind"].pool).__name__ == "NullPool"
    assert type(sub_flows._sf.kw["bind"].pool).__name__ == "NullPool"


def test_ensure_schema_once_same_db_path_only_inits_once(tmp_path, monkeypatch):
    # init_schema 一次要跑十來個 DDL/metadata 語句（PRAGMA + create_all 反射
    # + table_info + 3 CREATE INDEX + 5 DROP INDEX）；per-request 熱路徑上
    # 同一個 db_path 只該確保一次 schema，不該每次呼叫都重跑一輪。
    from src.pce_cache import schema as schema_mod
    from src.main import _make_cache_reader
    calls = []
    orig = schema_mod.init_schema

    def spy(engine):
        calls.append(engine)
        orig(engine)

    monkeypatch.setattr(schema_mod, "init_schema", spy)
    db_path = str(tmp_path / "once.sqlite")
    cm = _cm(db_path)
    _make_cache_reader(cm)
    _make_cache_reader(cm)
    assert len(calls) == 1


def test_ensure_schema_once_different_db_paths_each_init_once(tmp_path, monkeypatch):
    from src.pce_cache import schema as schema_mod
    from src.main import _make_cache_reader
    calls = []
    orig = schema_mod.init_schema

    def spy(engine):
        calls.append(engine)
        orig(engine)

    monkeypatch.setattr(schema_mod, "init_schema", spy)
    db_path_a = str(tmp_path / "a.sqlite")
    db_path_b = str(tmp_path / "b.sqlite")
    _make_cache_reader(_cm(db_path_a))
    _make_cache_reader(_cm(db_path_b))
    assert len(calls) == 2
