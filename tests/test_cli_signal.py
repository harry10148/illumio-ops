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
    """End-to-end: send SIGTERM to a child running install_top_level_handler, expect exit 143."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    proc = subprocess.Popen(
        [sys.executable, '-c',
         f"import sys; sys.path.insert(0, {repr(project_root)}); "
         "from src.cli._errors import install_top_level_handler; "
         "install_top_level_handler(); "
         "import time; \n"
         "while True: time.sleep(0.1)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(0.4)  # let it install handler
    proc.terminate()  # sends SIGTERM
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("Process did not exit after SIGTERM")
    assert proc.returncode == EXIT_TERMINATED  # 143
