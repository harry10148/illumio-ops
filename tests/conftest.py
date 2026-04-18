import logging
import os
import sys

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
