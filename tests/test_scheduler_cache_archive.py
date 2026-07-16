from unittest.mock import patch, MagicMock


def _cm(tmp_path, archive_enabled=True):
    cm = MagicMock()
    cfg = cm.models.pce_cache
    cfg.db_path = str(tmp_path / "cache.sqlite")
    cfg.archive_enabled = archive_enabled
    cfg.archive_dir = str(tmp_path / "archive")
    cfg.archive_gzip_after_days = 7
    cfg.archive_retention_days = 90
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
    assert kwargs.get("retention_days") == 90
    mock_exp.return_value.run_once.assert_called_once()


def test_run_cache_archive_swallows_exceptions(tmp_path):
    from src.scheduler.jobs import run_cache_archive
    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine", side_effect=RuntimeError("boom")), \
         patch("src.scheduler.jobs.logger") as mock_logger:
        run_cache_archive(cm)  # 不得拋出
    # 例外必須被收斂到 logger.exception（讓維運看得到），而非靜默吞掉
    assert mock_logger.exception.called


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


def test_periodic_cache_jobs_get_startup_kick(tmp_path):
    """真機事故（2026-07-14）：aggregate/retention/archive 未帶 next_run_time，
    IntervalTrigger 首跑排在啟動後一整個間隔；部署頻繁重啟下 24h 間隔的
    archive/retention 永遠跑不到（data/archive 恆空、DB 無上限成長）。
    比照 ingest job 的 _kick 慣例：三者都要有近期的首跑時間（錯開避免同時搶
    cache_writer）。"""
    import datetime
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
        now = datetime.datetime.now(datetime.timezone.utc)
        kicks = {}
        for job_id in ("pce_cache_aggregate", "pce_cache_retention", "pce_cache_archive",
                       "pce_cache_capacity_monitor"):
            job = sched.get_job(job_id)
            assert job is not None, job_id
            nrt = job.next_run_time
            assert nrt is not None, f"{job_id} 缺 next_run_time 首跑 kick"
            delta = (nrt - now).total_seconds()
            assert 0 <= delta <= 900, f"{job_id} 首跑須在啟動後 15 分鐘內（實際 {delta:.0f}s）"
            kicks[job_id] = nrt
        # 錯開：三個 kick 不得同時（避免同刻搶 cache_writer 單 worker）
        assert len(set(kicks.values())) == 4, f"kick 時間須錯開: {kicks}"
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)


def test_top_level_periodic_jobs_get_startup_kick(tmp_path):
    """monitor_cycle（cache 停用時 10m）與 posture_summary（10m）同屬長間隔
    interval job：密集重啟下首跑會被無限推遲（同 2026-07-14 archive 事故類）。
    兩者皆須有近期首跑。"""
    import datetime
    from src.scheduler import build_scheduler
    cm = _cm(tmp_path, archive_enabled=False)
    cm.models.pce_cache.enabled = False
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        for job_id in ("monitor_cycle", "posture_summary"):
            job = sched.get_job(job_id)
            assert job is not None, job_id
            assert job.next_run_time is not None, f"{job_id} 缺首跑 kick"
            delta = (job.next_run_time - now).total_seconds()
            assert 0 <= delta <= 900, f"{job_id} 首跑須在 15 分鐘內（實際 {delta:.0f}s）"
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)
