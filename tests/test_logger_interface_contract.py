"""Freeze the logger interface that all src/ files use.
After loguru migration, these must still work:
  logger.debug/info/warning/error/critical(msg, *args, **kwargs)
  logger.exception(msg)
  logger.error(msg, exc_info=True)
"""


def test_logger_has_standard_methods():
    from src.utils import logger
    for method in ("debug", "info", "warning", "error", "critical", "exception"):
        assert callable(getattr(logger, method)), f"logger.{method} missing"


def test_logger_error_with_exc_info_true():
    from src.utils import logger
    try:
        raise ValueError("boom")
    except ValueError:
        logger.error("caught", exc_info=True)


def test_logger_info_handles_format_args():
    from src.utils import logger
    logger.info("value is {}", 42)
