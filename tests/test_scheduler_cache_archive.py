from unittest.mock import patch, MagicMock


def _cm(tmp_path, archive_enabled=True):
    cm = MagicMock()
    cfg = cm.models.pce_cache
    cfg.db_path = str(tmp_path / "cache.sqlite")
    cfg.archive_enabled = archive_enabled
    cfg.archive_dir = str(tmp_path / "archive")
    cfg.archive_gzip_after_days = 7
    return cm


def test_run_cache_archive_invokes_exporter(tmp_path):
    from src.scheduler.jobs import run_cache_archive
    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.pce_cache.archive.ArchiveExporter") as mock_exp:
        mock_exp.return_value.run_once.return_value = {}
        run_cache_archive(cm)
    mock_exp.assert_called_once()
    _args, kwargs = mock_exp.call_args
    assert kwargs.get("archive_dir") == cm.models.pce_cache.archive_dir
    assert kwargs.get("gzip_after_days") == 7
    mock_exp.return_value.run_once.assert_called_once()


def test_run_cache_archive_swallows_exceptions(tmp_path):
    from src.scheduler.jobs import run_cache_archive
    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine", side_effect=RuntimeError("boom")):
        run_cache_archive(cm)  # 不得拋出


def test_run_cache_retention_passes_archive_enabled(tmp_path):
    from src.scheduler.jobs import run_cache_retention
    cm = _cm(tmp_path)
    cfg = cm.models.pce_cache
    cfg.events_retention_days = 90
    cfg.traffic_raw_retention_days = 7
    cfg.traffic_agg_retention_days = 90
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.pce_cache.retention.RetentionWorker") as mock_w:
        mock_w.return_value.run_once.return_value = {}
        run_cache_retention(cm)
    _a, kwargs = mock_w.return_value.run_once.call_args
    assert kwargs.get("archive_enabled") is True


def test_archive_job_registered_only_when_enabled(tmp_path):
    from src.scheduler import build_scheduler
    cm = _cm(tmp_path, archive_enabled=False)
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    assert sched.get_job("pce_cache_archive") is None
    for j in list(sched.get_jobs()):
        sched.remove_job(j.id)


def test_archive_job_uses_cache_writer_executor(tmp_path):
    """archive job 會推進 archiver cursor（寫 cache SQLite），須與其他 cache 寫入
    job 共用同一個 cache_writer executor（單 worker），避免與 ingest/aggregate/
    retention 產生破壞性 SQLite 寫鎖競爭。"""
    from src.scheduler import build_scheduler
    cm = _cm(tmp_path, archive_enabled=True)
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.archive_interval_hours = 24
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    try:
        assert sched.get_job("pce_cache_archive").executor == "cache_writer"
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)
