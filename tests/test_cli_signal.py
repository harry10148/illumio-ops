"""Test SIGTERM handler + typed excepthook installed by install_top_level_handler."""
import os
import signal
import sys
import subprocess
import time

import pytest

from src.cli._errors import install_top_level_handler, _recovery_for
from src.cli._exit_codes import EXIT_INTERRUPT, EXIT_TERMINATED, EXIT_SOFTWARE, EXIT_UNAVAILABLE


def test_recovery_for_connection_error():
    class ConnectionError(Exception): pass
    assert "PCE_HOST" in _recovery_for(ConnectionError)


def test_recovery_for_permission_error():
    assert "permissions" in _recovery_for(PermissionError)


def test_recovery_for_file_not_found():
    assert "file path" in _recovery_for(FileNotFoundError)


def test_recovery_for_generic():
    assert "verbose" in _recovery_for(RuntimeError)


def test_install_registers_sigterm_handler(monkeypatch):
    """install_top_level_handler should set signal.SIGTERM to a non-default handler."""
    # Save original handler and restore after
    orig = signal.getsignal(signal.SIGTERM)
    try:
        install_top_level_handler()
        new_handler = signal.getsignal(signal.SIGTERM)
        assert new_handler != signal.SIG_DFL
        assert callable(new_handler)
    finally:
        signal.signal(signal.SIGTERM, orig)


def test_install_replaces_excepthook(monkeypatch):
    """install_top_level_handler should set sys.excepthook to a custom handler."""
    orig = sys.excepthook
    try:
        install_top_level_handler()
        assert sys.excepthook is not orig
    finally:
        sys.excepthook = orig


# --- subprocess test for typed exit code on actual SIGTERM ---

@pytest.mark.skipif(sys.platform == 'win32', reason="POSIX signals only")
def test_sigterm_returns_exit_143(tmp_path):
    """End-to-end: send SIGTERM to a child running install_top_level_handler, expect exit 143.

    Synchronises on a "READY" line written by the child after the handler is
    installed — otherwise on slow hosts the SIGTERM lands before
    ``signal.signal(SIGTERM, handler)`` has executed, and the OS kills the
    process directly (returncode = -15) without going through our handler.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    proc = subprocess.Popen(
        [sys.executable, '-u', '-c',
         f"import sys; sys.path.insert(0, {repr(project_root)}); "
         "from src.cli._errors import install_top_level_handler; "
         "install_top_level_handler(); "
         "sys.stdout.write('READY\\n'); sys.stdout.flush(); "
         "import time; \n"
         "while True: time.sleep(0.1)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Block until the handler is installed (READY line written) or timeout.
    ready_line = proc.stdout.readline()
    if ready_line.strip() != b"READY":
        proc.kill()
        proc.wait()
        pytest.fail(f"Child did not signal READY before timeout (got {ready_line!r})")
    proc.terminate()  # sends SIGTERM
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("Process did not exit after SIGTERM")
    assert proc.returncode == EXIT_TERMINATED, (
        f"Expected SIGTERM handler to call sys.exit({EXIT_TERMINATED}), "
        f"got returncode={proc.returncode}. "
        f"Negative codes mean the OS killed the process before the handler ran."
    )
