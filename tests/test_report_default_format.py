"""Freeze format handling contract before Phase 10 changes."""
import ast
import pathlib
import re

import pytest


@pytest.mark.parametrize("fmt", ["html", "csv", "xlsx", "all"])
def test_cli_format_choice_accepted(fmt):
    """argparse --format must accept the 4 supported values."""
    src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
    assert f'"{fmt}"' in src or f"'{fmt}'" in src, f"{fmt} missing from main.py choices"


def test_cli_format_pdf_no_longer_accepted():
    """pdf was removed: argparse choices must not include it."""
    src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
    import re
    m = re.search(r"choices=\[([^\]]+)\]", src)
    assert m and '"pdf"' not in m.group(1), "pdf must not be a --format choice"


def test_default_format_is_html_not_all():
    """Phase 10 contract: --format default should be 'html' (CSV opt-in)."""
    src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
    m = re.search(r"""["\']--format["\'].*?default=["\'](\w+)["\']""", src, re.DOTALL)
    assert m, "--format default not found in src/main.py"
    assert m.group(1) == "html", f"Expected default 'html', got '{m.group(1)}'"
