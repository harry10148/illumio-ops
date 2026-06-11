# tests/test_flow_history.py
"""Per-run flow-signature persistence for baseline drift detection."""
import pandas as pd

from src.report.flow_history import (
    build_signatures,
    load_previous_signatures,
    save_signatures,
)


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP"},
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP"},  # dup → 1 sig
        {"src_app": "", "dst_app": "Cache", "port": 6379, "proto": "TCP"},  # unlabeled src
    ])


def test_build_signatures_dedupes_and_marks_unlabeled():
    sigs = build_signatures(_df())
    assert sigs == {"Web|DB|3306|TCP", "(unlabeled)|Cache|6379|TCP"}


def test_build_signatures_empty_df():
    assert build_signatures(pd.DataFrame()) == set()
    assert build_signatures(None) == set()


def test_save_then_load_roundtrip(tmp_path):
    out = str(tmp_path)
    save_signatures(out, "traffic", {"A|B|443|TCP"}, generated_at="2026-06-01T00:00:00")
    sigs, ts = load_previous_signatures(out, "traffic")
    assert sigs == {"A|B|443|TCP"}
    assert ts == "2026-06-01T00:00:00"


def test_load_returns_none_when_no_history(tmp_path):
    sigs, ts = load_previous_signatures(str(tmp_path), "traffic")
    assert sigs is None and ts is None


def test_retention_keeps_last_12(tmp_path):
    out = str(tmp_path)
    for i in range(15):
        save_signatures(out, "traffic", {f"A|B|{i}|TCP"}, generated_at=f"2026-06-01T00:00:{i:02d}")
    import pathlib
    files = list(pathlib.Path(out, "history", "traffic").glob("flows_*.json.gz"))
    assert len(files) == 12
