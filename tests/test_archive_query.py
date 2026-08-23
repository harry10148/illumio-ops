"""封存串流查詢：檔案層。

封存檔超過 `archive_gzip_after_days`（預設 7）就會被 `_gzip_old_files()`
原地換成 .jsonl.gz，而本功能的核心情境是「PCE 只留三個月，三個月後來這裡
查」——那個時間點的資料必然只有 .gz。只開 .jsonl 會把實際存在的資料回報成
「沒有封存資料」。
"""
from __future__ import annotations

import gzip
import json
from datetime import date

from src.pce_cache.archive_query import iter_archive_rows


def _write(tmp_path, name, rows, *, gz=False):
    p = tmp_path / name
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if gz:
        with gzip.open(p, "wb") as fh:
            fh.write(body.encode("utf-8"))
    else:
        p.write_text(body, encoding="utf-8")
    return p


def test_reads_plain_and_gzipped_days(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl.gz", [{"flow_hash": "a"}], gz=True)
    _write(tmp_path, "traffic-2026-05-02.jsonl", [{"flow_hash": "b"}])
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2))]
    assert got == ["a", "b"]


def test_days_outside_the_range_are_not_opened(tmp_path):
    _write(tmp_path, "traffic-2026-04-30.jsonl", [{"flow_hash": "before"}])
    _write(tmp_path, "traffic-2026-05-01.jsonl", [{"flow_hash": "in"}])
    _write(tmp_path, "traffic-2026-05-03.jsonl", [{"flow_hash": "after"}])
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2))]
    assert got == ["in"]


def test_a_truncated_gz_does_not_abort_the_whole_scan(tmp_path):
    (tmp_path / "traffic-2026-05-01.jsonl.gz").write_bytes(b"not actually gzip")
    _write(tmp_path, "traffic-2026-05-02.jsonl", [{"flow_hash": "survivor"}])
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2))]
    assert got == ["survivor"]


def test_a_bad_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "traffic-2026-05-01.jsonl"
    p.write_text('{"flow_hash": "ok"}\nnot json\n{"flow_hash": "ok2"}\n', encoding="utf-8")
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1))]
    assert got == ["ok", "ok2"]


def test_missing_directory_yields_nothing(tmp_path):
    assert list(iter_archive_rows(
        str(tmp_path / "nope"), "traffic", date(2026, 5, 1), date(2026, 5, 1))) == []
