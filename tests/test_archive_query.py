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


from src.pce_cache.archive_query import unsupported_filters


def test_label_group_and_ams_filters_are_rejected():
    got = unsupported_filters({"src_label_groups": ["x"], "dst_ams": ["y"], "port": 443})
    assert got == ["dst_ams", "src_label_groups"]


def test_draft_policy_decision_is_rejected():
    assert unsupported_filters({"draft_policy_decision": "allowed"}) == ["draft_policy_decision"]


def test_empty_values_do_not_count_as_used():
    assert unsupported_filters({"src_label_groups": [], "dst_ams": None}) == []


def test_evaluable_filters_pass():
    assert unsupported_filters({"port": 443, "src_ip": "10.0.0.1"}) == []


def test_the_blacklist_covers_every_analyzer_unevaluable_key():
    """analyzer 已經維護了一份『cache 端無法評估』的清單；封存是更嚴格的
    離線情境，不得比它寬鬆。這條在 analyzer 新增 key 時會紅。"""
    from src.analyzer import _CACHE_UNEVALUABLE_FILTER_KEYS
    from src.pce_cache.archive_query import UNSUPPORTED_ARCHIVE_FILTER_KEYS
    missing = set(_CACHE_UNEVALUABLE_FILTER_KEYS) - set(UNSUPPORTED_ARCHIVE_FILTER_KEYS)
    assert missing == set(), f"archive blacklist is looser than the cache's: {sorted(missing)}"


from src.pce_cache.archive_query import merge_row, stream_query


def _row(fh, **kw):
    base = {"flow_hash": fh, "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
            "port": 443, "protocol": "tcp", "action": "allowed",
            "flow_count": 1, "bytes_in": 100, "bytes_out": 200,
            "first_detected": "2026-05-01T00:00:00+00:00",
            "event_time": "2026-05-01T01:00:00+00:00", "raw": {}}
    base.update(kw)
    return base


def test_merge_takes_max_of_volatile_fields_and_min_of_first_detected():
    """封存檔不是唯一列集合：長壽 flow 更新時會再次匯出，崩潰重跑也會重寫
    整批。ArchiveImporter 因此用 MAX/MIN upsert；串流不合併就會重複計數。"""
    a = _row("h", flow_count=3, bytes_in=10, bytes_out=20,
             first_detected="2026-05-01T05:00:00+00:00",
             event_time="2026-05-01T05:00:00+00:00")
    b = _row("h", flow_count=7, bytes_in=5, bytes_out=90,
             first_detected="2026-05-01T02:00:00+00:00",
             event_time="2026-05-01T09:00:00+00:00")
    m = merge_row(merge_row(None, a), b)
    assert m["flow_count"] == 7
    assert m["bytes_in"] == 10
    assert m["bytes_out"] == 90
    assert m["first_detected"] == "2026-05-01T02:00:00+00:00"
    assert m["event_time"] == "2026-05-01T09:00:00+00:00"


def test_duplicate_exports_do_not_inflate_the_summary(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl", [
        _row("h", flow_count=3, bytes_in=10, bytes_out=20),
        _row("h", flow_count=7, bytes_in=10, bytes_out=20),
    ])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: True)
    assert res.matched == 1
    assert len(res.rows) == 1
    assert res.summary[0]["flow_count"] == 7


def test_cap_keeps_the_globally_heaviest_not_the_first_seen(tmp_path):
    """現行 query_flows 是排序全部命中再取前 N。用檔案順序取前 N 會漏掉
    後面日期檔裡的大流量——這條測試就是為了讓那種實作失敗。"""
    _write(tmp_path, "traffic-2026-05-01.jsonl",
           [_row(f"small{i}", flow_count=1) for i in range(5)])
    _write(tmp_path, "traffic-2026-05-02.jsonl", [_row("huge", flow_count=999)])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2),
                       {"port": 443}, cap=2, sort_by="connections",
                       matcher=lambda r: True)
    assert res.truncated is True
    assert res.rows[0]["flow_hash"] == "huge"
    assert len(res.rows) == 2


def test_summary_cardinality_is_bounded_and_reports_what_it_dropped(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl",
           [_row(f"h{i}", port=1000 + i) for i in range(50)])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 0}, cap=100, sort_by="connections",
                       matcher=lambda r: True, summary_top_k=10)
    assert len(res.summary) == 10
    assert res.summary_omitted == 40


def test_matcher_decides_what_counts_as_a_hit(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl",
           [_row("keep", port=443), _row("drop", port=80)])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: r.get("port") == 443)
    assert [r["flow_hash"] for r in res.rows] == ["keep"]
    assert res.scanned == 2


def test_a_query_with_no_filters_is_refused(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                     {}, cap=10, sort_by="connections", matcher=lambda r: True)


def test_an_empty_string_filter_value_does_not_count_as_used(tmp_path):
    """Analyzer.query_flows（src/analyzer.py:2276-2289）建 filter dict 時是
    整組 key 都塞、沒填的欄位預設 ""/[]，不是省略 key。guard 若用
    `is not None` 判斷會把這種預設空值誤判成「有指定 filter」而放行
    無限制掃描；必須跟 unsupported_filters() 一樣用 truthy 語意。"""
    import pytest
    with pytest.raises(ValueError):
        stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                     {"src_ip": ""}, cap=10, sort_by="connections",
                     matcher=lambda r: True)


def test_bandwidth_sort_is_refused_because_the_archive_has_no_rate_inputs(tmp_path):
    """bandwidth（calculate_mbps，src/analyzer.py:285-325）是速率，跟 volume
    （calculate_volume_mb，:327-342）這個總量是兩回事；封存列沒有算速率
    要用的 ddms/tdms。近似出一個叫 bandwidth 的數字會是這個功能要防的
    「看似合理但錯」，所以直接拒絕而不是悄悄退回別的排序。"""
    import pytest
    with pytest.raises(ValueError, match="ddms/tdms|rate"):
        stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                     {"port": 443}, cap=10, sort_by="bandwidth",
                     matcher=lambda r: True)
