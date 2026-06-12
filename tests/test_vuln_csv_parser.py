"""Vuln CSV ingest: column aliases (Qualys/Tenable exports), normalization."""
import pandas as pd
import pytest

from src.report.parsers.vuln_csv import load_vulns


def _write(tmp_path, text):
    p = tmp_path / "v.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_generic_columns(tmp_path):
    df = load_vulns(_write(tmp_path, "ip,cve_id,severity,cvss\n10.0.0.5,CVE-2024-1234,High,8.1\n"))
    assert list(df.columns) == ["ip", "cve_id", "severity", "cvss"]
    assert df.iloc[0]["cve_id"] == "CVE-2024-1234"
    assert df.iloc[0]["cvss"] == 8.1


def test_tenable_aliases(tmp_path):
    df = load_vulns(_write(tmp_path, "IP Address,CVE,Risk,CVSS V3 Base Score\n10.0.0.5,CVE-2024-1,Critical,9.8\n"))
    assert df.iloc[0]["ip"] == "10.0.0.5" and df.iloc[0]["severity"] == "Critical"


def test_missing_required_column_raises(tmp_path):
    with pytest.raises(ValueError, match="ip"):
        load_vulns(_write(tmp_path, "host,cve_id\nh1,CVE-1\n"))


def test_rows_without_cve_dropped(tmp_path):
    df = load_vulns(_write(tmp_path, "ip,cve_id\n10.0.0.5,\n10.0.0.6,CVE-2024-2\n"))
    assert len(df) == 1
