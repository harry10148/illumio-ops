"""Status.md Q5 fix: label cache must expire after 15 minutes."""
from __future__ import annotations

from unittest.mock import MagicMock

from freezegun import freeze_time


def _make_api():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://p", "org_id": "1", "key": "k",
                "secret": "s", "verify_ssl": True},
    }
    return ApiClient(cm)


def test_label_cache_is_ttl_backed():
    api = _make_api()
    from cachetools import TTLCache
    assert isinstance(api.label_cache, TTLCache), (
        "label_cache must be a TTLCache (Phase 2 Q5 fix)"
    )


def test_label_cache_default_ttl_is_15_minutes():
    api = _make_api()
    # 900 seconds = 15 minutes
    assert api.label_cache.ttl == 900


@freeze_time("2026-04-18 10:00:00")
def test_label_cache_entry_expires_after_ttl():
    with freeze_time("2026-04-18 10:00:00") as frozen:
        api = _make_api()
        api.label_cache["env:prod"] = "/orgs/1/labels/123"
        assert api.label_cache.get("env:prod") == "/orgs/1/labels/123"
        frozen.tick(delta=900 + 1)  # 15 min + 1 sec
        assert api.label_cache.get("env:prod") is None


def test_invalidate_labels_clears_cache():
    api = _make_api()
    api.label_cache["a"] = "href_a"
    api.label_cache["b"] = "href_b"
    api.invalidate_labels()
    assert len(api.label_cache) == 0
