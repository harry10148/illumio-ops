"""Tests for offline-bundle PDF graceful-degrade behaviour."""
from __future__ import annotations


def test_pdf_available_flag_is_bool():
    from src.report.exporters.pdf_exporter import PDF_AVAILABLE
    assert isinstance(PDF_AVAILABLE, bool)


def test_requirements_offline_excludes_weasyprint(tmp_path):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offline_req = os.path.join(root, "requirements-offline.txt")
    assert os.path.exists(offline_req), "requirements-offline.txt not found"
    content = open(offline_req).read().lower()
    assert "weasyprint" not in content
    # Must still list the other core packages
    for pkg in ("flask", "pandas", "requests", "apscheduler", "loguru"):
        assert pkg in content, f"{pkg} missing from requirements-offline.txt"
