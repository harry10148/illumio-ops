# tests/test_mod_drift.py
"""Baseline drift: new / disappeared app-to-app flows vs previous run."""
import pandas as pd

from src.report.analysis.mod_drift import baseline_drift


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP", "num_connections": 40},
        {"src_app": "Web", "dst_app": "Cache", "port": 6379, "proto": "TCP", "num_connections": 7},
    ])


def test_no_previous_returns_unavailable():
    res = baseline_drift(_df(), prev_signatures=None, prev_generated_at=None)
    assert res["available"] is False


def test_new_and_disappeared_pairs_detected():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="2026-06-01T00:00:00")
    assert res["available"] is True
    assert res["new_count"] == 1                       # Web→Cache:6379 是新的
    assert res["disappeared_count"] == 1               # Batch→DB 不見了
    new_rows = res["new_pairs"]
    assert list(new_rows.iloc[0][["Src App", "Dst App"]]) == ["Web", "Cache"]
    assert int(new_rows.iloc[0]["Connections"]) == 7
    gone = res["disappeared_pairs"]
    assert list(gone.iloc[0][["Src App", "Dst App"]]) == ["Batch", "DB"]
    assert res["prev_generated_at"] == "2026-06-01T00:00:00"


def test_identical_periods_produce_zero_drift():
    prev = {"Web|DB|3306|TCP", "Web|Cache|6379|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="x")
    assert res["new_count"] == 0 and res["disappeared_count"] == 0


def test_drift_section_reaches_html_output(tmp_path, monkeypatch):
    """mod_drift must be injected BEFORE exporters consume module_results.

    Two consecutive export() runs: the second run's HTML must contain drift
    data (new-pairs heading with a count), not the first-run note. It must
    also already contain trend deltas — trend_store.load_previous is called
    before save_snapshot on every run, so the snapshot written by run 1 is
    "the previous run" the moment run 2 calls load_previous; no third run
    is needed to see a trend-chip.
    """
    import datetime
    from unittest.mock import MagicMock
    from src.report.report_generator import ReportGenerator, ReportResult

    # Keep the post-export dashboard refresh from touching repo-level state.
    monkeypatch.setattr("src.scheduler.jobs.run_posture_summary", lambda cm: None)

    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.test", "org_id": "1", "key": "k",
                         "secret": "s", "verify_ssl": False}}
    gen = ReportGenerator(cm, api_client=MagicMock())

    def _export(df, run_no, kpi_value):
        result = ReportResult(
            # Distinct second-resolution timestamps so snapshot/signature
            # filenames never collide between back-to-back runs.
            generated_at=datetime.datetime(2026, 1, 1, 0, 0, run_no),
            record_count=len(df),
            date_range=("2024-01-01", "2024-01-31"),
            module_results={"mod12": {"kpis": [
                {"label_key": "kpi_total_flows", "label": "Total Flows",
                 "value": kpi_value}]}},
            dataframe=df,
        )
        paths = gen.export(result, fmt="html", output_dir=str(tmp_path), lang="en")
        html_path = next(p for p in paths if p.endswith(".html"))
        with open(html_path, encoding="utf-8") as fh:
            return fh.read()

    df2 = pd.concat(
        [_df(), pd.DataFrame([{"src_app": "Batch", "dst_app": "DB", "port": 5432,
                               "proto": "TCP", "num_connections": 3}])],
        ignore_index=True)

    _export(_df(), run_no=0, kpi_value=10)          # run 1: builds baseline
    html2 = _export(df2, run_no=1, kpi_value=11)    # run 2: +1 new pair

    assert "No previous flow baseline" not in html2
    assert "New App-to-App Pairs (not seen last period) (1)" in html2

    # Trend deltas must reach the HTML on this very run too (same
    # dead-on-arrival bug), not only after a third export.
    assert "No previous snapshot" not in html2
    assert "trend-chip" in html2
