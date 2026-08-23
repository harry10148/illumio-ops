"""封存日檔的串流讀取。

封存是「PCE 只保留三個月，之後還想查」的唯一途徑，所以查詢一定落在舊資料
上——而舊檔在 `archive_gzip_after_days`（預設 7）之後就被原地換成 .gz。
兩種副檔名都要開，否則核心情境永遠查不到東西。
"""
from __future__ import annotations

import gzip
import os
import re
from datetime import date
from typing import Iterator

import orjson
from loguru import logger

_DAY_FILE = re.compile(r"^(?P<source>[a-z_]+)-(?P<day>\d{4}-\d{2}-\d{2})\.jsonl(?P<gz>\.gz)?$")


def _matching_files(archive_dir: str, source: str, start: date, end: date) -> list[str]:
    """[start, end]（含端點）內該 source 的日檔，依日期排序。

    同一天同時存在 .jsonl 與 .jsonl.gz 時取 .jsonl：壓縮是原地取代，兩者並存
    只會在輪替中途出現，未壓縮的那份才是完整的。
    """
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError:
        return []
    by_day: dict[str, str] = {}
    for name in names:
        m = _DAY_FILE.match(name)
        if not m or m.group("source") != source:
            continue
        try:
            day = date.fromisoformat(m.group("day"))
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        key = m.group("day")
        if key in by_day and m.group("gz"):
            continue  # 已有未壓縮版本，優先用它
        by_day[key] = os.path.join(archive_dir, name)
    return [by_day[k] for k in sorted(by_day)]


def _iter_lines(path: str) -> Iterator[bytes]:
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rb") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield line
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        # 截斷/損壞的封存檔：已讀出的行照常處理，放棄該檔剩餘部分，
        # 讓呼叫端繼續下一檔。與 archive_import 的既有行為一致。
        logger.warning("archive_query: corrupt/truncated file {}: {}", path, exc)


def iter_archive_rows(archive_dir: str, source: str,
                      start: date, end: date) -> Iterator[dict]:
    """依序產出 [start, end] 內該 source 每個日檔的每一列。

    無法解析的單列跳過並記 warning——一列壞掉不該讓整趟查詢失敗。
    """
    for path in _matching_files(archive_dir, source, start, end):
        for line in _iter_lines(path):
            try:
                yield orjson.loads(line)
            except orjson.JSONDecodeError as exc:
                logger.warning("archive_query: unparsable line in {}: {}", path, exc)
