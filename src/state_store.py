import json
import orjson
from loguru import logger
import os
import tempfile
import threading
import time
from contextlib import contextmanager

_LOCK_RETRY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_STALE_SECONDS = 30.0

@contextmanager
def _state_lock(lock_path: str, timeout: float = _LOCK_TIMEOUT_SECONDS):
    start = time.time()
    # pid:tid token：讓持有者在 finally 能確認鎖仍是自己的（鎖被 stale
    # 判定強拆後，不可誤刪拆鎖者剛建立的新鎖）。
    token = f"{os.getpid()}:{threading.get_ident()}"
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                os.write(fd, token.encode("ascii", errors="ignore"))
            except OSError:
                pass
            try:
                yield
            finally:
                os.close(fd)
                try:
                    with open(lock_path, "r", encoding="ascii", errors="ignore") as lf:
                        owner = lf.read()
                    if owner == token:
                        os.unlink(lock_path)
                except (FileNotFoundError, OSError):
                    pass
            return
        except FileExistsError:
            try:
                st = os.stat(lock_path)
                if time.time() - st.st_mtime > _LOCK_STALE_SECONDS:
                    # 先 rename 再刪：rename 是原子操作，多個等待者只有一個會
                    # 成功強拆，避免同時 unlink 把別人剛重建的新鎖也刪掉。
                    stale_path = f"{lock_path}.stale-{os.getpid()}-{threading.get_ident()}"
                    try:
                        os.rename(lock_path, stale_path)
                    except OSError:
                        continue
                    try:
                        if os.stat(stale_path).st_ino == st.st_ino:
                            # 搶到的確實是量測過期的那把鎖，安全移除。
                            os.unlink(stale_path)
                        else:
                            # 窗口期間鎖已被換新——放回去，不強拆活鎖。
                            os.replace(stale_path, lock_path)
                    except OSError:
                        pass
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
        # 更新路徑必須區分「檔案不存在」與「檔案存在但壞掉」：壞檔若默默
        # 當成 {} 續寫，下一次 os.replace 會把可能救得回來的原檔整個蓋掉。
        current: dict = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "rb") as f:
                    data = orjson.loads(f.read())
                if not isinstance(data, dict):
                    raise ValueError("state root is not a dict")
                current = data
            except Exception as exc:
                corrupt_path = f"{state_file}.corrupt-{int(time.time())}"
                try:
                    os.replace(state_file, corrupt_path)
                    logger.error(
                        "State file {} is corrupt ({}); backed up to {} and rebuilding from empty",
                        state_file, exc, corrupt_path)
                except OSError:
                    logger.error(
                        "State file {} is corrupt ({}); rebuilding from empty",
                        state_file, exc)
        updated = updater(dict(current))
        if not isinstance(updated, dict):
            raise ValueError("State updater must return a dict")

        state_dir = os.path.dirname(state_file) or "."
        fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(updated, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, state_file)
            # fsync parent dir for metadata durability (Linux only; harmless on other POSIX)
            try:
                dirfd = os.open(state_dir, os.O_RDONLY)
                try:
                    os.fsync(dirfd)
                finally:
                    os.close(dirfd)
            except OSError:
                pass  # best-effort
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # intentional fallback: tmp file cleanup is best-effort; original exception is re-raised
            raise
        return updated
