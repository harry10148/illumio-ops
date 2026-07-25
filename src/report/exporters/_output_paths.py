"""Collision-safe, atomic report output paths.

報表檔名只帶到「分」的解析度（Illumio_..._2026-07-25_1030.html），而 GUI 臨時
報表跑在各自的 daemon thread、排程器同一 tick 也可能連跑兩張同型報表，因此同
一分鐘內的兩次產出會指到同一個路徑並互相截斷／交錯覆寫。這裡提供兩個原語：

  reserve_unique_path()  以 O_CREAT|O_EXCL 搶下檔名（碰撞時加 -2、-3… 後綴），
                         保留既有檔名格式，只有真的撞名時才偏離。
  write_bytes_atomic()   先寫同目錄暫存檔再 os.replace()，避免半寫檔被 GUI 列出。

兩者搭配使用時，呼叫端應先把文件建置完成（字串／bytes）再 reserve，建置失敗就
不會留下 0-byte 殘檔；reserve 之後的失敗則以 discard_reserved() 清掉佔位檔。
"""
from __future__ import annotations

import os
import uuid

_MAX_SUFFIX = 100


def reserve_unique_path(path: str) -> str:
    """Atomically claim `path` (or the first free `<stem>-N<ext>`) and return it.

    建立一個 0-byte 佔位檔，確保同時間的另一個 writer 不會拿到同一個名字。
    """
    stem, ext = os.path.splitext(path)
    candidate = path
    for n in range(1, _MAX_SUFFIX + 1):
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            candidate = f"{stem}-{n + 1}{ext}"
            continue
        os.close(fd)
        return candidate
    # 極端情況（同分鐘 100 次同型報表）：改用隨機後綴，仍以 O_EXCL 確認唯一。
    candidate = f"{stem}-{uuid.uuid4().hex[:8]}{ext}"
    fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(fd)
    return candidate


def discard_reserved(path: str) -> None:
    """Remove a reserved placeholder (or a partially written file); never raises."""
    try:
        os.unlink(path)
    except OSError:
        pass  # intentional fallback: 清理失敗不應蓋掉原本要往上拋的錯誤


def write_bytes_atomic(path: str, data: bytes) -> None:
    """Write `data` to `path` via a same-directory temp file + os.replace()."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        discard_reserved(tmp)
        raise


def write_text_atomic(path: str, text: str, encoding: str = "utf-8") -> None:
    """Text convenience wrapper over write_bytes_atomic()."""
    write_bytes_atomic(path, text.encode(encoding))
