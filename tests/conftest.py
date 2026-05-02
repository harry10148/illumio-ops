import json
import logging
import os
import shutil
import sys
import tempfile

import pytest
from loguru import logger


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


class _PropagateHandler(logging.Handler):
    """Forward loguru records to stdlib logging so pytest caplog can capture them."""

    def emit(self, record: logging.LogRecord) -> None:
        logging.getLogger(record.name).handle(record)


@pytest.fixture(autouse=True)
def _loguru_caplog_bridge(caplog):
    """Route loguru → stdlib logging → caplog for test assertion compatibility."""
    handler_id = logger.add(_PropagateHandler(), format="{message}", level="DEBUG")
    with caplog.at_level(logging.DEBUG):
        yield
    try:
        logger.remove(handler_id)
    except ValueError:
        pass  # setup_loguru() may have already removed all handlers


@pytest.fixture
def header_client(tmp_path):
    """Minimal Flask test client for security-header contract tests.

    Used by tests/test_security_headers.py and tests/test_flask_talisman_headers.py;
    these previously duplicated the same fixture verbatim. Other suites that need a
    richer config (auth, CSRF) build their own clients on top of `app_persistent`.
    """
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {"username": "illumio", "password": "illumio",
                    "secret_key": "", "allowed_ips": []},
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app
    app = build_app(ConfigManager(str(cfg)))
    app.config["TESTING"] = True
    return app.test_client()


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')


@pytest.fixture
def temp_config_file():
    # Use a fresh temp directory so the auto-derived alerts.json sibling is
    # also test-private (otherwise tests in the same /tmp share alerts.json
    # across runs and across processes — verified to leak real lab tokens
    # in earlier runs).
    tmpdir = tempfile.mkdtemp(prefix="illumio_ops_test_")
    path = os.path.join(tmpdir, "config.json")

    # Init empty config
    with open(path, 'w') as f:
        json.dump({"api": {"url": "test", "key": "test", "secret": "test", "org_id": "1"}, "rules": []}, f)

    yield path
    # Cleanup config + sibling alerts.json (created on first save)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def app_persistent(temp_config_file):
    from src.config import ConfigManager, hash_password as _hash_password
    from src.gui import build_app as _create_app

    # Override ConfigManager path for testing
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()

    cm.config["web_gui"] = {
        "username": "admin",
        "password": _hash_password("testpass"),
        "allowed_ips": ["127.0.0.1", "192.168.1.0/24"],
        "secret_key": "test-secret"
    }
    cm.save()

    app = _create_app(cm, persistent_mode=True)
    app.config.update({
        "TESTING": True,
    })

    yield app


@pytest.fixture
def client(app_persistent):
    return app_persistent.test_client()
