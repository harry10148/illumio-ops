"""Phase 3.1 Task 5 — collapse the 12 mini KPI grid into <details>."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"


def test_kpi_grid_wrapped_in_details_id():
    html = INDEX_HTML.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<details[^>]*id="d-detailed-kpis"[^>]*>[\s\S]*?id="snap-kpi-grid"[\s\S]*?</details>',
        re.MULTILINE,
    )
    assert pattern.search(html), "snap-kpi-grid must be inside <details id='d-detailed-kpis'>"


def test_details_not_open_by_default():
    html = INDEX_HTML.read_text(encoding="utf-8")
    pattern = re.compile(r'<details([^>]*)id="d-detailed-kpis"([^>]*)>')
    m = pattern.search(html)
    assert m, "details tag with id d-detailed-kpis not found"
    attrs = (m.group(1) or "") + (m.group(2) or "")
    assert "open" not in attrs.split(), "details must be collapsed by default"
