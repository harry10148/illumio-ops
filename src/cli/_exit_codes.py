"""Exit code constants and dispatch (sysexits.h style + POSIX signal codes).

Track B Task 1: gives shell pipelines fine-grained failure dispatch
without parsing stderr.

Codes (per BSD sysexits.h, widely supported):
    0   OK
    64  USAGE     bad invocation
    65  DATAERR   input data invalid
    66  NOINPUT   input file missing/unreadable
    69  UNAVAILABLE  service down (PCE, mail server)
    70  SOFTWARE  internal error (bug)
    71  OSERR     OS-level (file perm, mkdir failure)
    78  CONFIG    bad config

Signal codes:
    130 SIGINT   (Ctrl-C)
    143 SIGTERM  (kill)
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 64
EXIT_DATAERR = 65
EXIT_NOINPUT = 66
EXIT_UNAVAILABLE = 69
EXIT_SOFTWARE = 70
EXIT_OSERR = 71
EXIT_CONFIG = 78
EXIT_INTERRUPT = 130
EXIT_TERMINATED = 143


def exit_for_exception(exc: BaseException) -> int:
    """Map an exception type to a sysexits.h exit code.

    Used in the top-level except handler / install_top_level_handler.
    """
    name = type(exc).__name__
    if 'ConnectionError' in name or 'ConnectTimeout' in name or 'ConnectionRefused' in name:
        return EXIT_UNAVAILABLE
    if 'FileNotFoundError' in name or 'NoInput' in name:
        return EXIT_NOINPUT
    if 'PermissionError' in name:
        return EXIT_OSERR
    if 'KeyboardInterrupt' in name:
        return EXIT_INTERRUPT
    if 'SystemExit' in name:
        return getattr(exc, 'code', EXIT_OK) or EXIT_OK
    if 'ValueError' in name or 'TypeError' in name:
        return EXIT_DATAERR
    if 'ConfigError' in name or 'BadConfig' in name:
        return EXIT_CONFIG
    return EXIT_SOFTWARE
