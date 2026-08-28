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


@pytest.fixture(scope="session")
def _stdlib_root_logger_baseline():
    """Snapshot of the stdlib root logger's handlers/level, taken once
    before the first test runs (this is a dependency of the autouse,
    function-scoped fixture below, so pytest instantiates it on first use —
    i.e. before any test body, including its own logging setup, executes).

    Exists only so `_loguru_caplog_bridge` can restore this baseline after
    any test whose call to setup_loguru() clobbers it — see that fixture's
    docstring for why this specific restoration is required, not optional.
    """
    root_logger = logging.getLogger()
    return list(root_logger.handlers), root_logger.level


@pytest.fixture(autouse=True)
def _loguru_caplog_bridge(caplog, _stdlib_root_logger_baseline):
    """Route loguru → stdlib logging → caplog for test assertion compatibility.

    Also guards, session-wide, against any test leaking global loguru/stdlib
    logging state. setup_loguru() (src/loguru_config.py) does two things
    that outlive a single test unless undone:

    1. It installs enqueue=True sinks, each backed by a real
       multiprocessing.SimpleQueue/Lock/Event plus a background feeder
       thread (verified against loguru's Handler.__init__/Handler.stop()).
       A test that calls setup_loguru() without teardown leaves that thread
       running for the rest of the pytest session, writing to a tmp_path
       file pytest has since deleted.
    2. It calls `logging.basicConfig(handlers=[_StdLibInterceptHandler()],
       level=0, force=True)` — force=True unconditionally REPLACES the
       stdlib root logger's entire handler list, process-wide. Nothing
       restores pytest's own root-logger setup afterward, so
       _StdLibInterceptHandler (which forwards every stdlib log call into
       loguru) is still installed root-wide in every later test.

    (2) is the sharper hazard: this fixture re-adds its own _PropagateHandler
    (loguru → stdlib logging.getLogger(...).handle(...)) for every test, so
    once _StdLibInterceptHandler (stdlib → loguru) is stuck on the root
    logger from an earlier test, the two form a closed loop — any later
    stdlib log call (e.g. urllib3's DEBUG/WARNING retry logging under the
    concurrent request threads a Playwright-driven Flask e2e test produces)
    bounces between stdlib logging and loguru indefinitely. Confirmed by
    direct inspection: running tests/test_logging.py's two setup_loguru()
    tests followed by tests/test_v2_alerting_e2e.py, the root logger's
    handlers still contained _StdLibInterceptHandler at the start of the
    e2e test, and the run produced a storm of loguru's own re-entrancy
    guard firing ("RuntimeError: Could not acquire internal lock ...
    deadlock avoided") immediately before hanging — cleaning up loguru's
    own handler registry alone (point 1) did not stop the hang; only
    additionally undoing (2) did.

    Both cleanups here only touch state added since this fixture's own
    setup ran (or, for (2), only fire when _StdLibInterceptHandler is
    actually present) — this is pure teardown of a specific, named test
    fixture's own footprint, not a general reset, so it can't mask a real
    logging misconfiguration in the code under test.
    """
    from src.loguru_config import _StdLibInterceptHandler

    before_ids = set(logger._core.handlers.keys())
    handler_id = logger.add(_PropagateHandler(), format="{message}", level="DEBUG")
    with caplog.at_level(logging.DEBUG):
        yield
    leaked_ids = set(logger._core.handlers.keys()) - before_ids
    for hid in leaked_ids:
        try:
            logger.remove(hid)
        except ValueError:
            pass  # already removed (e.g. by another setup_loguru() call)

    root_logger = logging.getLogger()
    if any(isinstance(h, _StdLibInterceptHandler) for h in root_logger.handlers):
        # A test called setup_loguru()/setup_logger() and its force=True
        # basicConfig() call is still in effect — restore pytest's original
        # root-logger handlers/level (captured once, pre-session, above).
        baseline_handlers, baseline_level = _stdlib_root_logger_baseline
        root_logger.handlers = list(baseline_handlers)
        root_logger.setLevel(baseline_level)


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


@pytest.fixture(scope="session")
def _analysis_lock_file(tmp_path_factory):
    """One session-private path for the cross-process analysis lock.

    Deliberately NOT under the per-test ``tmp_path``: a lock file appearing in
    a test's own tmp directory would show up in any test that enumerates it.
    """
    return str(tmp_path_factory.mktemp("analysis_lock") / "analysis.lock")


@pytest.fixture(autouse=True)
def _isolate_analysis_lock(_analysis_lock_file, monkeypatch):
    """Keep the whole suite off ``<repo>/logs/analysis.lock``.

    src/main.py's analysis_lock_path() anchors that file off ``__file__``, so
    every entry point that runs a full analysis cycle (the CLI menu's options
    6/7, the scheduler's monitor job, the GUI's run/debug actions) takes a REAL
    cross-process flock on the working checkout. A developer box routinely has
    a second process on that same checkout — a running ``--monitor-gui``
    service, or a second pytest — and the test then blocks for the full
    _ANALYSIS_LOCK_WAIT_S (5s) timeout and takes the TimeoutError branch
    instead of the code it meant to exercise.

    tests/test_api_settings.py and tests/test_pce_flush.py each already
    monkeypatch analysis_lock_path per-test for exactly this reason; this
    fixture generalises that to the suite so no new test has to remember.
    Tests that need the production path back can monkeypatch.delenv it.
    """
    monkeypatch.setenv("ILLUMIO_OPS_ANALYSIS_LOCK", _analysis_lock_file)


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
        json.dump({"api": {"url": "https://pce.test", "key": "test", "secret": "test", "org_id": "1"}, "rules": []}, f)

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
