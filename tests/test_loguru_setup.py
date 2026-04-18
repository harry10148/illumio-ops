"""Tests for src/loguru_config.py — rotation, JSON sink, interception."""
import json
import logging
import os
import time


def test_loguru_setup_creates_log_file(tmp_path):
    from src.loguru_config import setup_loguru
    from loguru import logger

    log_file = str(tmp_path / "logs" / "test.log")
    setup_loguru(log_file, level="DEBUG")
    logger.info("hello loguru setup")
    time.sleep(0.1)
    assert os.path.exists(log_file)
    content = open(log_file, encoding="utf-8").read()
    assert "hello loguru setup" in content


def test_loguru_setup_json_sink(tmp_path):
    from src.loguru_config import setup_loguru
    from loguru import logger

    log_file = str(tmp_path / "test.log")
    setup_loguru(log_file, level="DEBUG", json_sink=True)
    logger.info("json sink test")
    time.sleep(0.1)
    json_file = str(tmp_path / "test.json.log")
    assert os.path.exists(json_file), "JSON sink file not created"
    with open(json_file, encoding="utf-8") as f:
        line = f.readline()
    record = json.loads(line)
    assert "text" in record or "record" in record


def test_loguru_setup_no_json_sink_by_default(tmp_path):
    from src.loguru_config import setup_loguru

    log_file = str(tmp_path / "test.log")
    setup_loguru(log_file)
    json_file = str(tmp_path / "test.json.log")
    assert not os.path.exists(json_file)


def test_loguru_intercepts_stdlib_logging(tmp_path):
    from src.loguru_config import setup_loguru
    from loguru import logger

    log_file = str(tmp_path / "intercept.log")
    setup_loguru(log_file, level="DEBUG")
    std_logger = logging.getLogger("third_party_lib")
    std_logger.warning("stdlib warning intercepted")
    time.sleep(0.1)
    content = open(log_file, encoding="utf-8").read()
    assert "stdlib warning intercepted" in content


def test_loguru_setup_is_idempotent(tmp_path):
    from src.loguru_config import setup_loguru
    from loguru import logger

    log_file = str(tmp_path / "idem.log")
    setup_loguru(log_file, level="INFO")
    setup_loguru(log_file, level="INFO")
    logger.info("idempotent call")
    time.sleep(0.1)
    content = open(log_file, encoding="utf-8").read()
    assert content.count("idempotent call") == 1


def test_loguru_exception_trace(tmp_path):
    from src.loguru_config import setup_loguru
    from loguru import logger

    log_file = str(tmp_path / "exc.log")
    setup_loguru(log_file, level="DEBUG")
    try:
        raise RuntimeError("test exception")
    except RuntimeError:
        logger.exception("caught error")
    time.sleep(0.1)
    content = open(log_file, encoding="utf-8").read()
    assert "caught error" in content
