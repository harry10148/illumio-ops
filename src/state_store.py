import json
import orjson
from loguru import logger
import os
import tempfile
import time
from contextlib import contextmanager

_LOCK_RETRY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_STALE_SECONDS = 30.0

@contextmanager
def _state_lock(lock_path: str, timeout: float = _LOCK_TIMEOUT_SECONDS):
    start = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            except OSError:
                pass
            try:
                yield
            finally:
                os.close(fd)
                try:
                    os.unlink(lock_path)
                except FileNotFoundError:
                    pass
            return
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path)
                if age > _LOCK_STALE_SECONDS:
                    os.unlink(lock_path)
                    continue
            except FileNotFoundError:
                continue

            if time.time() - start >= timeout:
                raise TimeoutError(f"Timed out acquiring state lock: {lock_path}")
            time.sleep(_LOCK_RETRY_SECONDS)

def load_state_file(state_file: str) -> dict:
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, "rb") as f:
            data = orjson.loads(f.read())
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load state file {}: {}", state_file, exc)
        return {}

def update_state_file(state_file: str, updater) -> dict:
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    lock_path = state_file + ".lock"
    with _state_lock(lock_path):
        current = load_state_file(state_file)
        updated = updater(dict(current))
        if not isinstance(updated, dict):
            raise ValueError("State updater must return a dict")

        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(state_file) or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(updated, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return updated
