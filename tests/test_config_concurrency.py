"""Concurrency tests for ConfigManager.write_lock (GUI lost-update fix).

The Web GUI runs under cheroot's multi-thread pool. Handlers that do
load→mutate→save on the shared ConfigManager must serialize that section, or
two concurrent writers interleave (load A, load B, mutate, mutate, save A,
save B) and silently drop one update. These tests exercise the shared
``cm.write_lock`` that every config-mutating handler now wraps its critical
section in.
"""
import json
import threading
import time


def _make_cm(tmp_path):
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "settings": {"dashboard_queries": []},
        "rules": [],
    }), encoding="utf-8")
    return ConfigManager(config_file=str(cfg))


def test_write_lock_present_and_reentrant(tmp_path):
    cm = _make_cm(tmp_path)
    assert hasattr(cm, "write_lock")
    # Re-entrant: load() can call save() while a handler already holds the lock,
    # so nested acquisition must not deadlock.
    with cm.write_lock:
        with cm.write_lock:
            pass


def test_concurrent_saves_do_not_lose_updates(tmp_path):
    cm = _make_cm(tmp_path)

    n = 8
    barrier = threading.Barrier(n)
    errors: list[str] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()  # release all threads together to maximize overlap
            # Mirror the GUI handlers' load→mutate→save critical section.
            with cm.write_lock:
                cm.load()
                cm.config.setdefault("settings", {}).setdefault(
                    "dashboard_queries", []).append({"name": f"q{i}"})
                time.sleep(0.01)  # widen the race window
                cm.save()
        except Exception as exc:  # pragma: no cover - surfaced via assert below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors

    cm.load()
    names = {q["name"] for q in cm.config["settings"]["dashboard_queries"]}
    assert names == {f"q{i}" for i in range(n)}, f"lost updates, only kept: {names}"
