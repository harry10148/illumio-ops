"""F6：長壽 flow 的 archive 計數偏低——根因修復的端到端鎖定測試。

根因：ingest 端的 upsert 只刷新 volatile 欄位，不 bump ingested_at；archiver
的匯出游標依 (ingested_at, id) 前進——列一旦被匯出過，即使 live cache 端
持續成長，也不會再被撿到。修復兩件事必須一起生效：
  1. ingest 端：re-pull 時 bump ingested_at → archiver 游標會重新看到該列。
  2. import 端：同 flow_hash 的重複匯出改成 upsert（取 MAX），不再
     on_conflict_do_nothing 把後續匯出的成長值丟掉。
單獨修其中一個都不夠：只修 (1) 沒修 (2)，第二次匯出的新記錄匯入時會被
do_nothing 丟掉；只修 (2) 沒修 (1)，archiver 游標根本不會重新撿到該列，
export 端沒有新記錄可匯。
"""
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceTrafficFlowRaw


_FIRST = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()


def _flow(last, fc, bi, bo):
    return {
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443,
        "protocol": "tcp", "action": "blocked", "flow_count": fc,
        "bytes_in": bi, "bytes_out": bo,
        "first_detected": _FIRST, "last_detected": last,
    }


class _StepApiClient:
    """依呼叫順序回傳不同批次 flows，模擬同一 flow_hash 的長壽 flow
    被多次 re-pull、每次 last_detected/bytes/flow_count 都成長。"""

    def __init__(self, flows_by_call):
        self._flows_by_call = flows_by_call
        self.calls = 0

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        self.calls += 1
        return self._flows_by_call[self.calls - 1]


def test_ingest_bump_plus_import_upsert_fixes_long_lived_flow_undercount(tmp_path):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.archive import ArchiveExporter
    from src.pce_cache.archive_import import ArchiveImporter

    cache_engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    init_schema(cache_engine)
    cache_sf = sessionmaker(cache_engine)

    last1 = datetime(2026, 6, 1, 12, 1, 0, tzinfo=timezone.utc).isoformat()
    last2 = datetime(2026, 6, 1, 12, 30, 0, tzinfo=timezone.utc).isoformat()
    api = _StepApiClient([
        [_flow(last1, fc=1, bi=100, bo=200)],
        [_flow(last2, fc=5, bi=900, bo=1200)],
    ])
    ing = TrafficIngestor(api=api, session_factory=cache_sf, watermark=WatermarkStore(cache_sf))

    archive_dir = str(tmp_path / "archive")
    exporter = ArchiveExporter(cache_sf, archive_dir)

    # 1) 首次 ingest（新列）+ 首次 export（該列被撿走，游標推進到它的 ingested_at）
    assert ing.run_once() == 1
    exporter.run_once()

    # 2) re-pull：同 flow_hash，last_detected/bytes/flow_count 都成長
    #    （同 flow_hash → upsert，不是新插入，故回傳 0）
    assert ing.run_once() == 0

    # 3) 再次 export：修復後，re-pull 已把 ingested_at bump 到本次 ingest 時間，
    #    游標會重新看到該列並匯出成長後的值。
    exporter.run_once()

    review_engine = create_engine(f"sqlite:///{tmp_path / 'review.sqlite'}")
    init_schema(review_engine)
    review_sf = sessionmaker(review_engine)
    ArchiveImporter(archive_dir, review_sf).import_range(date(2026, 6, 1), date(2026, 6, 30))

    with review_sf() as s:
        row = s.execute(select(PceTrafficFlowRaw)).scalar_one()
    # 曾經的 bug：這裡會停在第一次匯出的舊值（bi=100/bo=200/fc=1），
    # 因為第二次 export 沒撿到該列（ingested_at 沒 bump），或即使撿到了，
    # import 端 on_conflict_do_nothing 也會把它丟掉。
    assert row.bytes_in == 900
    assert row.bytes_out == 1200
    assert row.flow_count == 5
    assert row.last_detected.replace(tzinfo=timezone.utc) == \
        datetime(2026, 6, 1, 12, 30, 0, tzinfo=timezone.utc)
