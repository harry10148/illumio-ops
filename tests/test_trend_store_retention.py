"""trend_store 的 KPI 快照必須有保留上限。

Audit bug: save_snapshot 每次 run 寫一個 JSON 且從不刪除；排程器的兩個清理
掃描都只看 output_dir 下的扁平檔名（且只認 .html/.zip/.json 副檔名），不會
遞迴進 history/，所以這批檔沒有任何機制會清理。
"""
from __future__ import annotations

from src.report import trend_store


def test_save_snapshot_prunes_to_keep_limit(tmp_path):
    out = str(tmp_path)
    for i in range(trend_store._KEEP + 5):
        trend_store.save_snapshot(out, "traffic", {"kpi": i},
                                  generated_at=f"2026-04-{10 + i:02d}T10:00:00")
    files = sorted((tmp_path / "history" / "traffic").glob("*.json"))
    assert len(files) == trend_store._KEEP


def test_prune_keeps_the_newest_snapshot(tmp_path):
    out = str(tmp_path)
    for i in range(trend_store._KEEP + 3):
        trend_store.save_snapshot(out, "traffic", {"kpi": i},
                                  generated_at=f"2026-04-{10 + i:02d}T10:00:00")
    prev = trend_store.load_previous(out, "traffic")
    assert prev is not None
    assert prev["kpi"] == trend_store._KEEP + 2


def test_prune_does_not_touch_flow_history_files(tmp_path):
    """同目錄下 flow_history 的 flows_*.json.gz 不得被誤刪。"""
    out = str(tmp_path)
    hdir = tmp_path / "history" / "traffic"
    hdir.mkdir(parents=True)
    (hdir / "flows_20260410_100000.json.gz").write_bytes(b"x")
    for i in range(trend_store._KEEP + 3):
        trend_store.save_snapshot(out, "traffic", {"kpi": i},
                                  generated_at=f"2026-04-{10 + i:02d}T10:00:00")
    assert (hdir / "flows_20260410_100000.json.gz").exists()
