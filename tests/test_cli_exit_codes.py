"""Test exit code constants and helper."""
from src.cli._exit_codes import (
    EXIT_OK, EXIT_USAGE, EXIT_DATAERR, EXIT_NOINPUT,
    EXIT_UNAVAILABLE, EXIT_SOFTWARE, EXIT_OSERR, EXIT_CONFIG,
    EXIT_INTERRUPT, EXIT_TERMINATED,
    exit_for_exception,
)


def test_standard_exit_codes():
    # POSIX
    assert EXIT_OK == 0
    assert EXIT_USAGE == 64        # sysexits.h EX_USAGE
    assert EXIT_DATAERR == 65      # EX_DATAERR
    assert EXIT_NOINPUT == 66      # EX_NOINPUT
    assert EXIT_UNAVAILABLE == 69  # EX_UNAVAILABLE (service unavailable)
    assert EXIT_SOFTWARE == 70     # EX_SOFTWARE (internal error)
    assert EXIT_OSERR == 71        # EX_OSERR
    assert EXIT_CONFIG == 78       # EX_CONFIG
    # Signal-induced (POSIX 128 + signum)
    assert EXIT_INTERRUPT == 130   # SIGINT
    assert EXIT_TERMINATED == 143  # SIGTERM


def test_exit_for_exception_connection_error():
    class ConnectionError(Exception): pass
    code = exit_for_exception(ConnectionError("PCE down"))
    assert code == EXIT_UNAVAILABLE


def test_exit_for_exception_file_not_found():
    code = exit_for_exception(FileNotFoundError("no config"))
    assert code == EXIT_NOINPUT


def test_exit_for_exception_permission():
    code = exit_for_exception(PermissionError("denied"))
    assert code == EXIT_OSERR


def test_exit_for_exception_generic():
    code = exit_for_exception(RuntimeError("oops"))
    assert code == EXIT_SOFTWARE
