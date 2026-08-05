import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
sys.path.insert(0, str(ROOT / "tools"))
import gate_coverage as gc


def test_report_flags_missing_and_extra():
    missing, extra = gc.report(found={"OV-01", "ZZ-99"})
    assert "OV-02" in missing and "ZZ-99" in extra and "OV-01" not in missing
