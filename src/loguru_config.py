"""Central loguru configuration for illumio_ops.

setup_loguru(log_file, level, json_sink, rotation, retention)
  - Configures loguru sinks: console (TTY-aware) + file (rotating) + optional JSON
  - Intercepts stdlib logging from 3rd-party libs via _StdLibInterceptHandler
  - Idempotent: removes prior sinks on each call
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger


class _StdLibInterceptHandler(logging.Handler):
    """Route stdlib logging calls (from 3rd-party libs) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
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
        )

    logging.basicConfig(handlers=[_StdLibInterceptHandler()], level=0, force=True)

    # Suppress verbose INFO/DEBUG noise from PDF/font rendering libraries
    for _lib in ("fontTools", "weasyprint", "pydyf", "cssselect2", "tinycss2", "brotli"):
        logging.getLogger(_lib).setLevel(logging.WARNING)
