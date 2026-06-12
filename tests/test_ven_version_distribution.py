"""VEN report: distribution by agent version (upgrade planning)."""
import pandas as pd


def test_by_version_distribution_built():
    from src.report.ven_status_generator import VenStatusGenerator
    df = pd.DataFrame([
        {"ven_version": "23.2.10"}, {"ven_version": "23.2.10"},
        {"ven_version": "22.5.1"}, {"ven_version": ""},
    ])
    dist = VenStatusGenerator._by_version(df)
    assert dist == {"23.2.10": 2, "22.5.1": 1, "(unknown)": 1}
