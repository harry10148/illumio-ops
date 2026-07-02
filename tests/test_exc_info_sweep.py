"""C.5.2 驗證：src/ 不再有 `exc_info=True`（loguru 下被靜默忽略、無 traceback），
一律改用 logger.exception(...)（except 內）或 logger.opt(exception=True).<level>(...)。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"


def test_no_exc_info_true_in_src():
    hits = []
    for py in sorted(SRC.rglob("*.py")):
        for ln_no, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "exc_info=True" in line:
                hits.append(f"{py.relative_to(ROOT)}:{ln_no}: {line.strip()}")
    assert not hits, "exc_info=True found (silently ignored by loguru):\n" + "\n".join(hits)


def test_logger_error_exc_info_true_silently_drops_traceback():
    """Documents the bug being fixed: loguru's logger.error(msg, exc_info=True)
    does NOT include a traceback — the kwarg is silently ignored."""
    from loguru import logger

    msgs = []
    sink_id = logger.add(lambda m: msgs.append(str(m)), level="ERROR")
    try:
        try:
            raise ValueError("boom")
        except ValueError as exc:
            logger.error("caught: {}", exc, exc_info=True)
    finally:
        logger.remove(sink_id)

    assert msgs, "expected a log record"
    assert "Traceback" not in msgs[0], msgs[0]


def test_logger_exception_includes_traceback():
    """logger.exception(...) (used inside except blocks) DOES capture a traceback."""
    from loguru import logger

    msgs = []
    sink_id = logger.add(lambda m: msgs.append(str(m)), level="ERROR")
    try:
        try:
            raise ValueError("boom")
        except ValueError as exc:
            logger.exception("caught: {}", exc)
    finally:
        logger.remove(sink_id)

    assert msgs, "expected a log record"
    assert "Traceback" in msgs[0] and "ValueError" in msgs[0], msgs[0]


def test_logger_opt_exception_debug_includes_traceback():
    """logger.opt(exception=True).debug(...) — used for non-error-level exception
    logging (e.g. resolve_actor_str/resolve_service_str fallbacks)."""
    from loguru import logger

    msgs = []
    sink_id = logger.add(lambda m: msgs.append(str(m)), level="DEBUG")
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            logger.opt(exception=True).debug("resolve_actor_str failed")
    finally:
        logger.remove(sink_id)

    assert msgs, "expected a log record"
    assert "Traceback" in msgs[0] and "ValueError" in msgs[0], msgs[0]
