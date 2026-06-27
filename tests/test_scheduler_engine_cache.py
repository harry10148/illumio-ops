"""Scheduler cache jobs must reuse one cached engine per db_path, not rebuild each tick."""
from unittest.mock import patch, MagicMock

import src.gui._helpers as helpers


def test_cache_jobs_reuse_one_engine_across_ticks(tmp_path):
    """run_traffic_aggregate builds the engine once per db_path and reuses it on
    subsequent ticks, instead of recreating engine + re-running init_schema every time."""
    from src.scheduler.jobs import run_traffic_aggregate

    db = str(tmp_path / "cache.sqlite")
    cm = MagicMock()
    cm.models.pce_cache.db_path = db

    helpers._cache_engines.pop(db, None)  # cold cache for this db_path
    try:
        with patch("sqlalchemy.create_engine") as mock_ce, \
             patch("sqlalchemy.orm.sessionmaker"), \
             patch("src.pce_cache.schema.init_schema") as mock_init, \
             patch("src.pce_cache.aggregator.TrafficAggregator") as mock_agg:
            mock_agg.return_value.run_once.return_value = 0
            run_traffic_aggregate(cm)
            run_traffic_aggregate(cm)

        assert mock_agg.return_value.run_once.call_count == 2, "both ticks ran"
        assert mock_ce.call_count == 1, "engine built once and reused"
        assert mock_init.call_count == 1, "init_schema runs once per engine"
    finally:
        helpers._cache_engines.pop(db, None)
