"""WebGUI must not reference Montserrat font — removed per Improvement_Plan §B 4.
Report-side Montserrat (src/reporter.py, src/report/...) is intentionally kept
for now and is NOT covered by this test."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parent.parent

WEBGUI_FILES = [
    ROOT / "src" / "static" / "css" / "app.css",
    ROOT / "src" / "templates" / "login.html",
    ROOT / "src" / "templates" / "index.html",
]


def test_no_montserrat_in_app_css():
    text = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "Montserrat" not in text, (
        "app.css should not reference Montserrat — use Inter / Space Grotesk."
    )


def test_no_montserrat_in_login_html():
    text = (ROOT / "src" / "templates" / "login.html").read_text(encoding="utf-8")
    assert "Montserrat" not in text, (
        "login.html should not reference Montserrat — use Inter / Space Grotesk."
    )


def test_login_uses_inter_or_space_grotesk():
    text = (ROOT / "src" / "templates" / "login.html").read_text(encoding="utf-8")
    assert ("Inter" in text) or ("Space Grotesk" in text), (
        "login.html should reference Inter or Space Grotesk for typography"
    )


def test_montserrat_woff2_not_referenced_in_webgui():
    for path in WEBGUI_FILES:
        text = path.read_text(encoding="utf-8")
        assert "Montserrat-latin.woff2" not in text, (
            f"{path} still references Montserrat woff2"
        )
