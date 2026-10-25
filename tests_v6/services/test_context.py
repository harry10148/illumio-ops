from illumio_ops.pce.rate_limit import RateLimiter
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb.db import FlowDb
from tests_v6.web.conftest import make_ctx


def test_context_builds_flowdb_and_limiter_from_settings(tmp_path):
    ctx = make_ctx(tmp_path)
    assert isinstance(ctx.flowdb, FlowDb) and ctx.flowdb.path == ctx.paths.flows_db
    assert isinstance(ctx.rate_limiter, RateLimiter)
    assert ctx.rate_limiter.rate_per_minute == ctx.settings.current().collection.rate_limit_per_minute == 400


def test_context_injects_shared_rate_limiter(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(
        {"url": "https://pce.example.com:8443", "org_id": "1", "api_key": "k", "api_secret": "s"}))
    client = ctx.pce_client()
    try:
        assert client._rate_limiter is ctx.rate_limiter
    finally:
        client.close()


def test_explicit_context_parts_are_kept(tmp_path):
    base = make_ctx(tmp_path)
    limiter = RateLimiter(60)
    ctx = AppContext(paths=base.paths, settings=base.settings, rate_limiter=limiter)
    assert ctx.rate_limiter is limiter
