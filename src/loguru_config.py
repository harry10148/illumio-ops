"""Central loguru configuration for illumio_ops.

setup_loguru(log_file, level, json_sink, rotation, retention)
  - Configures loguru sinks: console (TTY-aware) + file (rotating) + optional JSON
  - Intercepts stdlib logging from 3rd-party libs via _StdLibInterceptHandler
  - L4: Sink-level redaction filter scrubs secret-looking key=value pairs
    from log messages before they hit any sink (console/file/JSON).
  - Idempotent: removes prior sinks on each call
"""
from __future__ import annotations

import logging
import re as _re
import sys
from pathlib import Path

from loguru import logger


# L4: Patterns of secret-looking values inside log messages.
# Field names matched: api_key, secret, password, token, webhook_url,
# line_channel_access_token, smtp_password, authorization (header).
# The optional `Bearer ` prefix lets us strip the token from
# `Authorization: Bearer <token>` style headers without keeping the value.
_LOG_SECRET_FIELD = _re.compile(
    r'\b('
    r'api[_-]?key'
    r'|secret(?:[_-]?key)?'
    r'|password'
    r'|(?:line[_-]?channel[_-]?access[_-]?)?token'
    r'|webhook[_-]?url'
    r'|authorization'
    r'|smtp[_-]?password'
    r')\b'
    r'["\']?'         # optional closing quote of a quoted JSON-style key
    r'\s*[:=]\s*'
    r'["\']?(?:Bearer\s+)?([^,"\'\s}\)]{4,})',
    _re.IGNORECASE,
)


def _redact_log_record(record):
    """Loguru filter: replace secret-like values in record['message'].

    Idempotent: re-running the filter on already-redacted text is a no-op
    (the [REDACTED] marker contains no field-name pattern). Loguru shares
    the record dict across sinks, so the first sink's mutation is observed
    by subsequent sinks — this is fine because of idempotency.
    """
    msg = record.get('message') or ''
    if not msg:
        return True
    record['message'] = _LOG_SECRET_FIELD.sub(
        lambda m: m.group(0).replace(m.group(2), '[REDACTED]'),
        msg,
    )
    return True


_NOISY_LIBS = frozenset({
    "fontTools", "fonttools",
    "weasyprint", "pydyf", "cssselect2", "tinycss2",
    "brotli", "PIL", "matplotlib",
})


class _StdLibInterceptHandler(logging.Handler):
    """Route stdlib logging calls (from 3rd-party libs) into loguru.

    Noisy font/PDF libs are hard-filtered below WARNING at the handler
    level — setLevel() alone is unreliable because submodule loggers
    (e.g. fontTools.subset) may be created before the parent level is set.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Hard-suppress verbose INFO/DEBUG from font & PDF rendering libs
        if record.levelno < logging.WARNING:
            top = record.name.split(".")[0]
            if top in _NOISY_LIBS:
                return

        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_loguru(
    log_file: str,
    level: str = "INFO",
    json_sink: bool = False,
    rotation: str = "10 MB",
    retention: int = 10,
) -> None:
    """Install loguru sinks. Idempotent — removes prior sinks first."""
    logger.remove()

    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        filter=_redact_log_record,  # L4: redact secrets even on console
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level=level,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        enqueue=True,
        filter=_redact_log_record,  # L4
        format="{time:YYYY-MM-DD HH:mm:ss} {level: <8} {name}:{line} - {message}",
    )

    if json_sink:
        json_path = str(Path(log_file).with_suffix(".json.log"))
        logger.add(
            json_path,
            level=level,
            rotation=rotation,
            retention=retention,
            serialize=True,
            enqueue=True,
            filter=_redact_log_record,  # L4
        )

    logging.basicConfig(handlers=[_StdLibInterceptHandler()], level=0, force=True)

    # Suppress verbose INFO/DEBUG noise from PDF/font rendering libraries
    for _lib in ("fontTools", "weasyprint", "pydyf", "cssselect2", "tinycss2", "brotli"):
        logging.getLogger(_lib).setLevel(logging.WARNING)


def setup_logger(
    name: str,
    log_file: str,
    level: str = "INFO",
    json_sink: bool = False,
    **_kwargs,
) -> None:
    """Configure logging — delegates to setup_loguru. Signature kept for back-compat."""
    setup_loguru(log_file, level=level, json_sink=json_sink)
