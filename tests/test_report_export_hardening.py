"""Regression tests for report-export hardening (review batch 3).

Covers:
  - CSV formula injection (the xlsx path already defused it, the CSV path did not)
  - CSV UTF-8 BOM (Excel on Windows reads BOM-less files as cp950 → 繁中亂碼)
  - collision-safe report filenames (minute-resolution names + concurrent runs)
  - HTML built before the output file is created (no 0-byte report on build error)
  - matplotlib figures closed on the chart-render failure path
"""
from __future__ import annotations

import os
import zipfile

import pandas as pd
import pytest

from src.report.exporters.csv_exporter import CsvExporter


def _read_entry(zip_path: str, name: str) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name)


# ── CSV: formula injection ───────────────────────────────────────────────────

def test_csv_cells_with_formula_prefix_are_neutralized(tmp_path):
    df = pd.DataFrame([
        {"Process": "=cmd|'/c calc.exe'!A1", "User Name": "@SUM(1+1)"},
        {"Process": "+1234", "User Name": "-2+3"},
        {"Process": "normal.exe", "User Name": "svc"},
    ])
    path = CsvExporter({"mod06": {"procs": df}}).export(str(tmp_path))
    text = _read_entry(path, "mod06_procs.csv").decode("utf-8-sig")
    for payload in ("=cmd|", "@SUM(", "+1234", "-2+3"):
        assert f"'{payload}" in text, f"{payload} not neutralized:\n{text}"
    # 未截斷：原始內容仍完整帶出，只是多了前綴單引號
    assert "calc.exe'!A1" in text
    assert "normal.exe" in text and "'normal.exe" not in text


def test_csv_headers_with_formula_prefix_are_neutralized(tmp_path):
    df = pd.DataFrame([{"=evil()": 1, "ok": 2}])
    path = CsvExporter({"m": {"t": df}}).export(str(tmp_path))
    text = _read_entry(path, "m_t.csv").decode("utf-8-sig")
    assert text.splitlines()[0].startswith("'=evil()")


# ── CSV: BOM + content integrity ─────────────────────────────────────────────

def test_csv_entries_start_with_utf8_bom(tmp_path):
    df = pd.DataFrame([{"app": "測試", "rec": "先補未涵蓋流量的允許規則"}])
    path = CsvExporter({"queue": df}, report_label="Readiness").export(str(tmp_path))
    raw = _read_entry(path, "queue.csv")
    assert raw.startswith(b"\xef\xbb\xbf"), raw[:16]
    assert "測試" in raw.decode("utf-8-sig")


def test_csv_streams_all_rows_across_chunk_boundary(tmp_path):
    from src.report.exporters import csv_exporter as ce
    df = pd.DataFrame({"n": range(ce._CHUNK_ROWS * 2 + 7)})
    path = CsvExporter({"raw": df}).export(str(tmp_path))
    lines = _read_entry(path, "raw.csv").decode("utf-8-sig").strip().splitlines()
    assert len(lines) == len(df) + 1          # header written exactly once
    assert lines[0] == "n"
    assert lines[-1] == str(len(df) - 1)


# ── Collision-safe / atomic output paths ─────────────────────────────────────

def test_csv_export_does_not_overwrite_a_same_minute_run(tmp_path):
    df = pd.DataFrame([{"a": 1}])
    first = CsvExporter({"m": df}).export(str(tmp_path))
    second = CsvExporter({"m": df}).export(str(tmp_path))
    assert first != second, "same-minute export reused the filename"
    assert os.path.exists(first) and os.path.exists(second)


def test_reserve_unique_path_claims_distinct_names(tmp_path):
    from src.report.exporters._output_paths import reserve_unique_path
    base = str(tmp_path / "Illumio_Traffic_Report_SecurityRisk_2026-07-25_1030.html")
    a = reserve_unique_path(base)
    b = reserve_unique_path(base)
    c = reserve_unique_path(base)
    assert a == base
    assert len({a, b, c}) == 3
    assert b.endswith("_1030-2.html") and c.endswith("_1030-3.html")


def test_html_export_leaves_no_file_when_build_fails(tmp_path):
    """建置期例外不可留下 0-byte 報表：GUI 的報表列表只看副檔名，
    殘檔照樣會被列出並下載成空白頁。"""
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter

    exporter = SecurityRiskHtmlExporter({})
    exporter._build = lambda *a, **k: (_ for _ in ()).throw(KeyError("boom"))
    with pytest.raises(KeyError):
        exporter.export(str(tmp_path))
    assert list(tmp_path.glob("*.html")) == []


def test_csv_export_leaves_no_file_when_zip_build_fails(tmp_path, monkeypatch):
    from src.report.exporters import csv_exporter as ce

    def _boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ce, "_write_df_entry", _boom)
    with pytest.raises(RuntimeError):
        CsvExporter({"m": pd.DataFrame([{"a": 1}])}).export(str(tmp_path))
    assert list(tmp_path.glob("*.zip")) == []
    assert list(tmp_path.glob("*.tmp")) == []


# ── chart_renderer: no figure leak on the failure path ───────────────────────

def test_failed_chart_render_closes_the_figure():
    import matplotlib.pyplot as plt
    from src.report.exporters.chart_renderer import render_matplotlib_svg

    plt.close("all")
    bad = {"type": "pie", "data": {"labels": ["a", "b"], "values": [0, 0]}}
    for _ in range(3):
        with pytest.raises(Exception):
            render_matplotlib_svg(bad)
    assert plt.get_fignums() == [], "matplotlib figures leaked on the error path"


def test_unsupported_chart_type_closes_the_figure():
    import matplotlib.pyplot as plt
    from src.report.exporters.chart_renderer import render_matplotlib_png

    plt.close("all")
    with pytest.raises(ValueError):
        render_matplotlib_png({"type": "sunburst", "data": {}})
    assert plt.get_fignums() == []


# ── mod13: 執行模式圖例不得讓整份報表建置失敗 ────────────────────────────────

def test_enforcement_mode_legend_renders_instead_of_killing_the_report():
    """回歸：圖例的 STRINGS fallback 曾寫成 f-string 內的 `{{}}`。

    在替換欄位裡，`{{}}` 是「內含一個空 dict 的集合」而不是空 dict，所以
    `enforcement_mode_distribution` 只要非空就會拋
    `TypeError: unhashable type: 'dict'`。`_mod13_html()` 在 `_build()` 裡沒有
    caller 端的 try/except，整份 security_risk 報表因此建置失敗——不是少一張圖，
    是沒有報表。這條用「有資料」的分佈直接建一次，確認四個模式都印出來。

    最小 fixture 走不到這裡（分佈是空的），這就是它活下來的原因。
    """
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter

    results = {k: {} for k in [
        "mod01", "mod02", "mod03", "mod04", "mod05", "mod06", "mod07",
        "mod08", "mod09", "mod11", "mod12", "mod14", "mod15",
    ]}
    results["mod13"] = {
        "total_score": 62,
        "grade": "C",
        "enforcement_mode_distribution": {
            "full": 4, "selective": 3, "visibility_only": 2, "idle": 1,
        },
    }
    html = SecurityRiskHtmlExporter(results, lang="en").build()
    for label in ("Full", "Selective", "Visibility Only", "Idle"):
        assert f"{label}: " in html, f"圖例缺少 {label}"
