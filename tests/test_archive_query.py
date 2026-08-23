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
    """Analyzer.query_flows（src/analyzer.py 內 query_filters dict）建 filter
    dict 時是整組 key 都塞、沒填的欄位預設 ""/[]，不是省略 key。guard 若用
    `is not None` 判斷會把這種預設空值誤判成「有指定 filter」而放行
    無限制掃描；必須跟 unsupported_filters() 一樣用 truthy 語意。"這裡用
    "search"——真的在 _NARROWING_FILTER_KEYS 白名單裡的 key，而不是舊版
    測試用的 "src_ip"（那個 key 從沒在白名單裡，改用它會讓這條測試測不到
    「有在白名單裡但值是空字串」這件事）。"""
    import pytest
    with pytest.raises(ValueError):
        stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                     {"search": ""}, cap=10, sort_by="connections",
                     matcher=lambda r: True)


def test_only_control_fields_is_refused(tmp_path):
    """finding #3：filters 若只帶 sort_by 跟預設塞滿四值的 policy_decisions
    這類控制欄位、沒有任何真正窄化資料的 key，guard 必須拒絕——即使
    dict 裡每個 key 都有非空值。這兩個 key 都不在 _NARROWING_FILTER_KEYS。"""
    import pytest
    with pytest.raises(ValueError):
        stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                     {"sort_by": "connections",
                      "policy_decisions": ["blocked", "potentially_blocked", "allowed", "unknown"]},
                     cap=10, sort_by="connections", matcher=lambda r: True)


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


def test_reads_both_gz_and_plain_when_a_day_has_both(tmp_path):
    """finding #1：_gzip_old_files（src/pce_cache/archive.py:204-232）在既有
    .gz 存在時是用 "ab" 把新內容當一個新 gzip member 附加進去、寫完才刪
    .jsonl——遲到的匯出可能在已經 gzip 過的舊日期又建一個新的 .jsonl，
    於是同一天可能長期同時存在「.gz 裝著先前所有內容、.jsonl 只裝這次
    輪替後的新一批」。只開其中一個會把另一個裡的資料整批漏掉。"""
    _write(tmp_path, "traffic-2026-05-01.jsonl.gz", [_row("in-gz")], gz=True)
    _write(tmp_path, "traffic-2026-05-01.jsonl", [_row("in-plain")])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: True)
    assert {r["flow_hash"] for r in res.rows} == {"in-gz", "in-plain"}


def test_matching_runs_after_merge_not_before(tmp_path):
    """finding #2：flow_hash（src_ip/dst_ip/port/proto/first_detected，
    ingestor_traffic._flow_hash）不含 filter 常測的欄位。若照 row-by-row
    先比對再合併，一個「較舊時符合、現在已經不符合」的 flow 會被誤判成
    命中，回報過期答案。

    這裡刻意用 bytes_in（MAX 語意）而不是 action／policy_decision 來測：
    merge_row 對非 volatile 欄位（如 action）本來就凍結在第一筆看到的列
    （比照 ArchiveImporter 的 upsert：這些欄位不在 `set_` 裡，維持初次
    插入值，見 merge_row 的 docstring 與上一輪 field-by-field 比對）。拿
    action 測「先合併再比對」得靠把檔案內兩筆的先後順序倒過來寫才會過，
    脆弱又容易誤導成「合併會更新 action」；bytes_in 是 MAX 語意、跟寫入
    順序無關，能乾淨、確定地證明「先合併再比對」這個機制本身，不牽連
    merge_row 對非 volatile 欄位的既有（已審過的）凍結行為。"""
    _write(tmp_path, "traffic-2026-05-01.jsonl", [
        _row("h", bytes_in=10),    # 較舊快照：10 bytes，符合 <=20 的過濾
        _row("h", bytes_in=100),   # 較新快照：長大到 100 bytes，不再符合
    ])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: (r.get("bytes_in") or 0) <= 20)
    assert res.rows == []
    assert res.matched == 0


def test_a_deadline_stops_the_scan_and_reports_incomplete_after(tmp_path):
    """finding #4：正式環境的封存可能有幾十 GB，filter 再精準也得逐列走
    過去，可能長時間卡住同步的 web worker。deadline_s=0 保證第一天日檔
    掃完後、還沒開始第二天之前就跳出——只在日檔之間量時鐘、不逐列量，
    所以第一天一定完整掃完，不會被腰斬到一半。"""
    _write(tmp_path, "traffic-2026-05-01.jsonl", [_row("day1")])
    _write(tmp_path, "traffic-2026-05-02.jsonl", [_row("day2")])
    _write(tmp_path, "traffic-2026-05-03.jsonl", [_row("day3")])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 3),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: True, deadline_s=0)
    assert res.incomplete_after == date(2026, 5, 1)
    assert [r["flow_hash"] for r in res.rows] == ["day1"]


def test_structurally_invalid_rows_are_skipped_and_counted(tmp_path):
    """finding #5：語法合法的 JSON 不保證是一筆 flow——`[]`、裸字串、
    counters 是字串的物件都能通過 orjson.loads，但會在合併時的數值比較
    或摘要加總炸出 AttributeError/TypeError，讓整趟 [start, end] 掃描失敗。
    這三種都要被擋下並計數，掃描本身不能失敗。"""
    p = tmp_path / "traffic-2026-05-01.jsonl"
    lines = [
        json.dumps(_row("ok")),
        json.dumps([]),
        json.dumps("not a flow"),
        json.dumps({**_row("bad-counters"), "bytes_in": "abc"}),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: True)
    assert [r["flow_hash"] for r in res.rows] == ["ok"]
    assert res.scanned == 4
    assert res.skipped == 3


def test_the_review_db_load_path_is_gone():
    """封存查閱不再匯入 review DB；殘留的符號代表某條路徑還在用它。

    只列這條路徑自己的符號，不含那個「單次載入範圍上限」的 config 鍵——
    它仍必須留在 `src/config.py` 的 `_DEPRECATED_KEY_PATHS`（讓帶著它的舊
    config.json 還能載入），且 `tests/test_config_deprecated_keys.py` 必須
    提到它才能斷言它被丟棄；兩處都合法留著，見該檔的另一條守門測試（不在
    這裡逐字寫出鍵名，以免這條測試自己的字串把守門的集合相等判斷弄髒）。"""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(
        r"load_archive_review|start_archive_load|ArchiveLoadBusy|"
        r"review_db_path|review_status|load_progress"
    )
    hits = []
    for sub in ("src", "tests"):
        for p in (root / sub).rglob("*.py"):
            if p.name == pathlib.Path(__file__).name:
                continue
            if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(root)))
    assert hits == [], f"still referencing the removed archive-load path: {hits}"
