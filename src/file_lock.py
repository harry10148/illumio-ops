"""Cross-process advisory file locking.

`threading.Lock` / `RLock` 只在**單一行程內**有效。本專案的正式部署是常駐的
`--monitor-gui` 服務（APScheduler 背景 thread ＋ Flask 主 thread，同一行程），
但操作者同時會在同一台機器上以**獨立行程**的 CLI（`illumio-ops config set`、
互動式選單、rule_scheduler_cli 等）寫同一批「整檔覆寫」的 JSON 儲存體
（config/config.json、config/alerts.json、config/rule_schedules.json）。
行程內的鎖對這種情境完全無效：後存檔的一方會用自己的過期快照整檔蓋掉前者
（密碼/secret_key 輪替被還原、併發新增的排程憑空消失）。

這裡提供 OS 層 advisory lock：POSIX 用 `fcntl.flock`、Windows 用
`msvcrt.locking`（本專案有 Windows 安裝路徑，兩邊都必須能跑）。兩者皆不可用
時退化成「只剩行程內鎖」並記一次警告——不因為缺少 backend 就 crash。

用法：

    from src.file_lock import file_lock

    with file_lock(path + ".lock"):
        ...  # 鎖內重讀 → 改動 → 寫回

這是既有行程內鎖的**外層額外一圈**，不是替代品：thread-vs-thread 仍然要靠
原本的 Lock/RLock（例如 ConfigManager._rw_lock、rule_scheduler._rs_db_lock）。

鎖檔不刪除：flock/byte-range lock 由 OS 在行程結束時自動釋放，留著空檔案比
「unlink 後另一個等待者拿到已被刪除的 inode」安全（state_store.py 的 O_EXCL
方案必須靠 stale 逾時強拆，這裡不需要）。
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

from loguru import logger

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - POSIX
    _msvcrt = None

DEFAULT_TIMEOUT = 10.0
_RETRY_SECONDS = 0.02

# path → 行程內 RLock。POSIX flock 是 per-(process, open-file-description)：
# 同一行程用另一個 fd 再取一次會直接成功，完全擋不住自家的第二個 thread；
# Windows 的 byte-range lock 則會自我死鎖。兩種情況都要靠這層行程內鎖補上。
_registry: dict[str, threading.RLock] = {}
_registry_guard = threading.Lock()

# thread-local 巢狀計數：同一 thread 對同一路徑重入時不得重複向 OS 取鎖。
_held = threading.local()

_warned_degraded = False


def has_os_backend() -> bool:
    """True 表示這台機器有可用的 OS 層鎖（fcntl 或 msvcrt）。"""
    return _fcntl is not None or _msvcrt is not None


def _warn_degraded(reason: str) -> None:
    global _warned_degraded
    if not _warned_degraded:
        _warned_degraded = True
        logger.warning(
            "Cross-process file locking degraded to in-process only ({}); "
            "concurrent CLI + service writes to the JSON stores are unprotected.",
            reason,
        )


def _local_lock(key: str) -> threading.RLock:
    with _registry_guard:
        lk = _registry.get(key)
        if lk is None:
            lk = threading.RLock()
            _registry[key] = lk
        return lk


def _depths() -> dict[str, int]:
    d = getattr(_held, "depth", None)
    if d is None:
        d = {}
        _held.depth = d
    return d


def _os_acquire(fd: int) -> bool:
    """非阻塞地取得 OS 層獨佔鎖。False = 已被其他行程持有。"""
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if _msvcrt is not None:  # pragma: no cover - Windows only
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    _warn_degraded("neither fcntl nor msvcrt is available")
    return True


def _os_release(fd: int) -> None:
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        except OSError:
            pass
        return
    if _msvcrt is not None:  # pragma: no cover - Windows only
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


@contextmanager
def file_lock(lock_path: str, timeout: float = DEFAULT_TIMEOUT):
    """跨行程獨佔鎖。同一 thread 對同一路徑可重入。

    逾時 raise TimeoutError——寧可讓呼叫端看見錯誤，也不要放行一次會靜默
    覆蓋別人資料的寫入。
    """
    key = os.path.abspath(lock_path)
    depths = _depths()
    if depths.get(key):
        # 巢狀重入：OS 層已由本 thread 持有，只計數。
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return

    # 兩段等待（行程內 RLock + OS 鎖）共用同一個 deadline，逾時語意才一致。
    deadline = time.monotonic() + max(timeout, 0.0)
    local = _local_lock(key)
    if not local.acquire(timeout=max(timeout, 0.0) or 0.001):
        raise TimeoutError(f"Timed out acquiring file lock: {key}")
    fd = None
    try:
        try:
            os.makedirs(os.path.dirname(key) or ".", exist_ok=True)
            fd = os.open(key, os.O_CREAT | os.O_RDWR, 0o600)
            if os.fstat(fd).st_size == 0:
                # Windows 的 byte-range lock 需要實際存在的位元組可鎖。
                os.write(fd, b"0")
        except OSError as exc:
            # 鎖檔本身開不起來（唯讀掛載、權限）不該讓整個寫入路徑爆掉：
            # 退化成行程內鎖並警告一次。
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            fd = None
            _warn_degraded(f"cannot open lock file {key}: {exc}")

        if fd is not None:
            while not _os_acquire(fd):
                if time.monotonic() >= deadline:
                    os.close(fd)
                    fd = None
                    raise TimeoutError(f"Timed out acquiring file lock: {key}")
                time.sleep(_RETRY_SECONDS)

        depths[key] = 1
        try:
            yield
        finally:
            depths[key] = 0
    finally:
        if fd is not None:
            _os_release(fd)
            try:
                os.close(fd)
            except OSError:
                pass
        local.release()
