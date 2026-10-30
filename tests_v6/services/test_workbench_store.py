"""The workbench's pulled period (P6a, lightweight mode): read from the PCE once, kept 30 minutes for the next
clicks, dropped when it expires, when another period is asked, or when the PCE changes."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.services import ondemand, workbench_store
from illumio_ops.services.ondemand import OnDemandFailed, OnDemandResult
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 12, 7, tzinfo=UTC)


def _ctx_for(ctx, start, end, *, now):
    with workbench_store.lease(ctx, start, end, now=now) as got:
        return got


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path, mode="lightweight")


@pytest.fixture
def pulls(monkeypatch):
    log = {"opened": [], "closed": 0, "fail": None}

    def fake_open(ctx, *, start, end, spec=None, now=None):
        if log["fail"]:
            raise log["fail"]
        log["opened"].append((start, end))

        def close():
            log["closed"] += 1
        return OnDemandResult(ctx=ctx, rows=42, windows=1, truncated=[], earliest=start, capped_total=False,
                              unread_from=None), close
    monkeypatch.setattr(ondemand, "open_period", fake_open)
    monkeypatch.setattr(workbench_store, "open_period", fake_open)
    workbench_store.drop()
    yield log
    workbench_store.drop()


def test_lightweight_pulls_then_reuses(ctx, pulls):
    _, info = _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)
    assert info is not None and info.rows == 42 and len(pulls["opened"]) == 1
    # a click a minute later asks for the same period ending a minute later: the held pull answers it
    _ctx_for(ctx, NOW - timedelta(days=1, minutes=-1), NOW + timedelta(minutes=1),
                                now=NOW + timedelta(minutes=1))
    assert len(pulls["opened"]) == 1
    start, end = pulls["opened"][0]
    assert start == datetime(2026, 10, 29, 12, tzinfo=UTC) and end == datetime(2026, 10, 30, 13, tzinfo=UTC)


def test_expired_store_removed(ctx, pulls):
    _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)
    _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW + workbench_store.KEEP + timedelta(minutes=1))
    assert len(pulls["opened"]) == 2 and pulls["closed"] == 1


def test_other_period_replaces(ctx, pulls):
    _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)
    _ctx_for(ctx, NOW - timedelta(days=7), NOW, now=NOW)
    assert len(pulls["opened"]) == 2 and pulls["closed"] == 1


def test_pce_switch_drops_store(ctx, pulls):
    _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://other.example:8443"))
    _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)
    assert len(pulls["opened"]) == 2


def test_pull_failure_raised(ctx, pulls):
    pulls["fail"] = OnDemandFailed("the PCE could not answer")
    with pytest.raises(OnDemandFailed):
        _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)


def test_kept_period_not_pulled(tmp_path, pulls):
    """Full mode keeps the period: the install's store answers, nothing is pulled."""
    c = configured_ctx(tmp_path, mode="full")
    got, info = _ctx_for(c, NOW - timedelta(days=1), NOW, now=NOW)
    assert got is c and info is None and pulls["opened"] == []


# ── security review (2026-10-30) ─────────────────────────────────────────────

def test_store_in_use_not_closed_by_another_period(ctx, pulls):
    """#1: a request still reading the held pull keeps it open when another request replaces it."""
    with workbench_store.lease(ctx, NOW - timedelta(days=1), NOW, now=NOW):
        _ctx_for(ctx, NOW - timedelta(days=7), NOW, now=NOW)  # replaces the held pull
        assert pulls["closed"] == 0  # still leased
    assert pulls["closed"] == 1


def test_covered_request_not_blocked_by_a_pull(ctx, pulls, monkeypatch):
    """#2: while another period is being pulled, a request the held pull covers is answered at once."""
    import threading
    _ctx_for(ctx, NOW - timedelta(days=1), NOW, now=NOW)
    started, release = threading.Event(), threading.Event()
    real = workbench_store.open_period

    def slow_open(ctx, **kw):
        started.set()
        release.wait(5)
        return real(ctx, **kw)
    monkeypatch.setattr(workbench_store, "open_period", slow_open)
    t = threading.Thread(target=_ctx_for, args=(ctx, NOW - timedelta(days=7), NOW), kwargs={"now": NOW})
    t.start()
    assert started.wait(5)
    done = threading.Event()
    threading.Thread(target=lambda: (_ctx_for(ctx, NOW - timedelta(hours=2), NOW, now=NOW), done.set())).start()
    assert done.wait(2)  # not held up by the 7-day pull
    release.set()
    t.join(5)
