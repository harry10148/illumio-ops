"""
T2.10 / M-10: flask_limiter must use a persistent storage backend.

memory:// resets rate limits on every process restart and cannot shard
across workers.  We register a file:// backend backed by a JSON snapshot
so limits survive restarts without adding external dependencies.
"""
import json
import tempfile

import pytest


def _make_cm(tmp_dir: str):
    """Build a minimal ConfigManager pointing at a temp directory."""
    from src.config import ConfigManager, hash_password

    cfg_file = f"{tmp_dir}/config.json"
    with open(cfg_file, "w") as fh:
        json.dump(
            {
                "web_gui": {
                    "username": "u",
                    "password": hash_password("CorrectPw_2026!"),
                    "secret_key": "x" * 64,
                    "allowed_ips": [],
                },
                "api": {"profile": "dev", "verify_ssl": False},
            },
            fh,
        )
    cm = ConfigManager(config_file=cfg_file)
    cm.load()
    return cm


def test_limiter_storage_is_persistent():
    """Limiter must not use in-memory storage."""
    from src.gui import build_app

    with tempfile.TemporaryDirectory() as tmp:
        cm = _make_cm(tmp)
        app = build_app(cm)

        uri = app.config.get("RATELIMIT_STORAGE_URI", "")
        assert not uri.startswith("memory://"), (
            f"limiter should use persistent backend, got {uri!r}"
        )
        assert uri.startswith(("file://", "redis://", "memcached://")), (
            f"unexpected backend: {uri!r}"
        )


def test_limiter_storage_uri_uses_config_dir():
    """In dev/lab (no /var/lib/illumio-ops), the limiter dir sits next to config."""
    from src.gui import build_app
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        cm = _make_cm(tmp)
        app = build_app(cm)

        uri = app.config.get("RATELIMIT_STORAGE_URI", "")
        # Should be file://<tmp>/limiter  (when /var/lib/illumio-ops is absent)
        if uri.startswith("file://"):
            assert Path(uri[len("file://"):]).parent == Path(tmp), (
                f"expected limiter dir inside {tmp!r}, got {uri!r}"
            )


def test_limiter_snapshot_survives_restart():
    """Counter state written by _JsonFileStorage is reloaded on a fresh instance."""
    from limits.storage import SCHEMES

    # Ensure the file backend is registered by creating an app first.
    from src.gui import build_app

    with tempfile.TemporaryDirectory() as tmp:
        cm = _make_cm(tmp)
        build_app(cm)  # side-effect: registers SCHEMES["file"]

    # Now exercise the storage class directly.
    assert "file" in SCHEMES, "file:// scheme not registered after build_app()"

    with tempfile.TemporaryDirectory() as tmp2:
        storage_uri = f"file://{tmp2}/limiter"
        from pathlib import Path
        Path(f"{tmp2}/limiter").mkdir()

        cls = SCHEMES["file"]
        store1 = cls(storage_uri)
        store1.incr("ip:1.2.3.4", expiry=60, amount=1)
        store1.incr("ip:1.2.3.4", expiry=60, amount=1)
        assert store1.get("ip:1.2.3.4") == 2

        # Second instance reads the snapshot written by store1.
        store2 = cls(storage_uri)
        assert store2.get("ip:1.2.3.4") == 2, (
            "counter should survive re-instantiation (snapshot not loaded?)"
        )
