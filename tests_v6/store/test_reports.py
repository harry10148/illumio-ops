from datetime import UTC, datetime

from illumio_ops.domain.values import ReportStatus
from illumio_ops.store import reports as store
from tests_v6.web.conftest import make_ctx

T = datetime(2026, 10, 27, tzinfo=UTC)


def _insert(conn, **over):
    args = {"report_type": "lateral_posture", "params_json": '{"lookback_days": 7}', "status": ReportStatus.QUEUED,
                "trigger": "manual", "schedule_id": None, "pce_label": "pce", "period_start": T, "period_end": T, "created_at": T}
    args.update(over)
    return store.insert(conn, **args)


def test_queue_order_and_claim(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a, b = _insert(conn), _insert(conn)
        assert store.claim_next(conn, at=T).id == a
        assert store.claim_next(conn, at=T).id == b
        assert store.claim_next(conn, at=T) is None
        store.finish(conn, a, status=ReportStatus.DONE, at=T, files=["x.html"], kpis=[{"key": "k", "value": 1}])
        row = store.get(conn, a)
        assert row.status is ReportStatus.DONE and row.files == ["x.html"] and row.params == {"lookback_days": 7}
        assert store.requeue_running(conn) == 1 and store.get(conn, b).status is ReportStatus.QUEUED


def test_failed_at_insert_is_finished(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        rid = _insert(conn, status=ReportStatus.FAILED, error_key="rpt_unavailable_events_only")
        row = store.get(conn, rid)
    assert row.finished_at == T and row.error_key == "rpt_unavailable_events_only"


def test_list_newest_first_and_delete_skips_running(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a = _insert(conn, status=ReportStatus.DONE)
        b = _insert(conn, status=ReportStatus.RUNNING)
        rows, total = store.list_reports(conn, limit=10, offset=0)
        assert [r.id for r in rows] == [b, a] and total == 2
        store.delete(conn, [a, b])
        assert store.get(conn, a) is None and store.get(conn, b) is not None
