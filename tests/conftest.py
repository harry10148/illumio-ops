import json
import logging
import os
import shutil
import sys
import tempfile

# Use ephemeral in-memory rate-limit storage for all tests.
# Prevents cross-test 401/429 failures from persistent file:// counter accumulation
# (introduced by the file backend in T2.10 / commit f14e2f7).
# Production code path is unaffected — this env var is only set here.
os.environ.setdefault("ILLUMIO_OPS_RATELIMIT_URI", "memory://")

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


@pytest.fixture(autouse=True)
def _reset_i18n_language():
    """Restore the process-global i18n language after every test.

    The i18n engine keeps a process-global language (src/i18n/engine.py). Tests
    that call set_language("zh_TW") without restoring it leak that state into
    later tests, so English-output assertions become order-dependent (e.g.
    test_cli_rule_edit / test_cli_rule_list fail only depending on collection
    order). Save/restore here keeps the suite order-independent for language.
    """
    from src.i18n import get_language, set_language
    saved = get_language()
    yield
    set_language(saved)


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
        "secret_key": "x" * 64
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


@pytest.fixture
def cli_runner():
    """A click CliRunner that captures stderr separately, across click versions.

    click <8.2 mixes stderr into ``result.output`` unless ``mix_stderr=False``;
    click >=8.2 removed the parameter and always separates stderr. This keeps
    ``result.stderr`` usable on any click in the project's ``>=8.1,<9.0`` range.
    """
    from click.testing import CliRunner
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()
