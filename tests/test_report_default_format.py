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
    """pdf was removed: NO argparse/click choices list may include it.

    2026-07-17 補強：舊版只 re.search 第一個 choices=[...]（命中別的參數），
    形同空轉——改掃 main.py 全部 choices 清單與 cli/report.py 的
    _REPORT_FORMATS。"""
    import re
    src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
    for group in re.findall(r"choices=\[([^\]]+)\]", src):
        assert '"pdf"' not in group and "'pdf'" not in group, \
            f"pdf must not be an argparse choice: [{group}]"
    cli_src = pathlib.Path("src/cli/report.py").read_text(encoding="utf-8")
    m = re.search(r"_REPORT_FORMATS\s*=\s*\[([^\]]+)\]", cli_src)
    assert m and '"pdf"' not in m.group(1), "pdf must not be in _REPORT_FORMATS"


def test_default_format_is_html_not_all():
    """Phase 10 contract: --format default should be 'html' (CSV opt-in)."""
    src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
    m = re.search(r"""["\']--format["\'].*?default=["\'](\w+)["\']""", src, re.DOTALL)
    assert m, "--format default not found in src/main.py"
    assert m.group(1) == "html", f"Expected default 'html', got '{m.group(1)}'"
