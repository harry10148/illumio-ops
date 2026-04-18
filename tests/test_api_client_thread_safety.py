"""Concurrent update + read on TTLCaches should not raise.

Verifies that ApiClient._cache_lock exists and that concurrent readers/writers
do not produce RuntimeError or data corruption.
"""
import threading
from unittest.mock import MagicMock


def _make_client():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce",
            "org_id": "1",
            "key": "k",
            "secret": "s",
            "verify_ssl": False,
        }
    }
    return ApiClient(cm)


def test_cache_lock_attribute_exists():
    """ApiClient must expose _cache_lock (threading.Lock)."""
    import threading
    api = _make_client()
    assert hasattr(api, "_cache_lock"), "ApiClient missing _cache_lock"
    # Accept Lock or RLock
    # Accept Lock or RLock — RLock is required if update_label_cache calls invalidate_*
    assert isinstance(api._cache_lock, (type(threading.Lock()), type(threading.RLock())))


def test_concurrent_update_and_read_label_cache():
    """Concurrent label_cache writes + reads must not raise RuntimeError."""
    api = _make_client()
    errors = []

    def writer():
        try:
            for i in range(500):
                with api._cache_lock:
                    api.label_cache[f"/orgs/1/labels/href-{i}"] = f"env:val{i}"
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(500):
                with api._cache_lock:
                    list(api.label_cache.items())
        except Exception as exc:
            errors.append(exc)

    threads = (
        [threading.Thread(target=writer) for _ in range(3)]
        + [threading.Thread(target=reader) for _ in range(3)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety errors: {errors}"


def test_concurrent_invalidate_label_cache():
    """Calling invalidate_labels() while writers are active must not raise."""
    api = _make_client()
    errors = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            try:
                with api._cache_lock:
                    api.label_cache[f"/orgs/1/labels/href-{i}"] = f"env:val{i}"
                i += 1
            except Exception as exc:
                errors.append(exc)
                break

    def invalidator():
        import time
        for _ in range(20):
            try:
                api.invalidate_labels()
                time.sleep(0.001)
            except Exception as exc:
                errors.append(exc)
                break

    threads = [threading.Thread(target=writer) for _ in range(2)]
    inv_t = threading.Thread(target=invalidator)
    for t in threads:
        t.start()
    inv_t.start()
    inv_t.join()
    stop.set()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety errors during invalidate: {errors}"


def test_concurrent_invalidate_query_lookup_cache():
    """invalidate_query_lookup_cache() while writers active must not raise."""
    api = _make_client()
    errors = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            try:
                with api._cache_lock:
                    api.service_ports_cache[f"/orgs/1/services/href-{i}"] = [{"port": i}]
                i += 1
            except Exception as exc:
                errors.append(exc)
                break

    def invalidator():
        import time
        for _ in range(20):
            try:
                api.invalidate_query_lookup_cache()
                time.sleep(0.001)
            except Exception as exc:
                errors.append(exc)
                break

    threads = [threading.Thread(target=writer) for _ in range(2)]
    inv_t = threading.Thread(target=invalidator)
    for t in threads:
        t.start()
    inv_t.start()
    inv_t.join()
    stop.set()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety errors during invalidate_query_lookup_cache: {errors}"
