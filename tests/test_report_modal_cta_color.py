"""Report-generation modal CTA button ('產生') should use brand-orange (.btn-primary),
not green (.btn-success) — per UX_Review §7.2 brand consistency."""
from __future__ import annotations

import re
from pathlib import Path


INDEX = Path(__file__).parent.parent / "src" / "templates" / "index.html"


def test_m_gen_confirm_is_btn_primary():
    html = INDEX.read_text(encoding="utf-8")
    # Find the button with id="m-gen-confirm"
    m = re.search(r'<button[^>]*id=["\']m-gen-confirm["\'][^>]*>', html)
    assert m, '<button id="m-gen-confirm"> not found in index.html'
    tag = m.group(0)
    assert "btn-primary" in tag, f"m-gen-confirm should have class btn-primary, got: {tag!r}"
    assert "btn-success" not in tag, f"m-gen-confirm must not be btn-success: {tag!r}"
